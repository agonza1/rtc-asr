from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import websockets

from src.rtc_client import AsyncASRClient, TranscriptEvent

DEFAULT_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a realtime ASR latency benchmark for the rtc asr service."
)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "smoke.wav"
CACHE_ROOT = ROOT / ".cache" / "huggingface"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be greater than or equal to 0")
    return parsed


class BenchmarkRequestError(RuntimeError):
    """Wrap exhausted benchmark retries with stage-specific context."""

    def __init__(self, stage: str, attempts: int, cause: Exception) -> None:
        self.stage = stage
        self.attempts = attempts
        self.cause = cause
        message = f"{stage} failed after {attempts} attempt(s): {cause.__class__.__name__}: {cause}"
        super().__init__(message)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the realtime ASR service")
    parser.add_argument(
        "--mode",
        choices=("direct", "pipecat-e2e"),
        default="direct",
        help="Streaming benchmark mode: direct websocket chunks or Pipecat-style source frames aggregated into websocket chunks",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8090", help="Base URL for the ASR service")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8090/ws/stream", help="WebSocket URL for streaming")
    parser.add_argument("--audio-file", type=Path, help="Optional audio file to benchmark instead of synthesized speech")
    parser.add_argument("--speech-text", default=DEFAULT_TEXT, help="Speech text used when synthesizing a local benchmark clip")
    parser.add_argument("--reference-text", help="Reference transcript used to compute simple accuracy metrics")
    parser.add_argument("--reference-file", type=Path, help="Path to a UTF-8 transcript file used to compute simple accuracy metrics")
    parser.add_argument("--spawn-server", action="store_true", help="Start a local uvicorn server for the benchmark run")
    parser.add_argument("--backend", default="faster-whisper", help="ASR backend to benchmark when spawning a local server")
    parser.add_argument("--sample-count", type=positive_int, default=10, help="Number of benchmark samples to run per model")
    parser.add_argument("--rest-runs", type=positive_int, default=5, help="Number of REST runs")
    parser.add_argument("--chunk-ms", type=positive_int, default=250, help="Streaming chunk duration in milliseconds")
    parser.add_argument("--partial-interval-chunks", type=positive_int, default=1, help="Streaming partial cadence in chunks")
    parser.add_argument("--binary-frames", action="store_true", help="Send raw PCM bytes over websocket instead of JSON base64 frames")
    parser.add_argument("--model", default="small.en", help="Model name when spawning a local server")
    parser.add_argument("--device", default="cpu", help="ASR device when spawning a local server")
    parser.add_argument("--compute-type", default="int8", help="Compute type for faster-whisper when spawning a local server")
    parser.add_argument("--qwen-dtype", default="auto", help="Dtype for qwen-asr when spawning a local server")
    parser.add_argument("--parakeet-dtype", default="auto", help="Dtype for parakeet when spawning a local server")
    parser.add_argument("--partial-window", type=non_negative_float, default=2.0, help="Partial transcription window in seconds when spawning a local server")
    parser.add_argument("--max-buffer", type=non_negative_float, help="Optional stream buffer cap in seconds for websocket benchmarking")
    parser.add_argument(
        "--partial-event-timeout",
        type=non_negative_float,
        default=0.1,
        help="Seconds to wait for an eligible streaming partial before moving on",
    )
    parser.add_argument("--request-retries", type=positive_int, default=3, help="REST request attempts before failing a sample")
    parser.add_argument("--request-retry-delay", type=non_negative_float, default=2.0, help="Seconds to wait between REST request retries")
    parser.add_argument(
        "--pipecat-source-frame-ms",
        type=positive_int,
        default=20,
        help="Pipecat-style source frame duration in milliseconds before bridge aggregation",
    )
    parser.add_argument("--output", type=Path, help="Optional path for the benchmark JSON artifact")
    return parser.parse_args()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def summarize_latencies(values: list[float], *, duration_s: float | None = None) -> dict[str, float]:
    if not values:
        raise ValueError("Cannot summarize an empty latency series")

    summary: dict[str, float] = {
        "mean_ms": round(statistics.mean(values), 1),
        "p90_ms": round(percentile(values, 0.90), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
    }
    if duration_s is not None:
        summary["rtf_mean"] = round(statistics.mean(values) / (duration_s * 1000), 3)
    return summary


def make_wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    clipped = np.clip(samples, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())
    return buffer.getvalue()


def synthesize_speech(text: str) -> Path | None:
    say_bin = shutil.which("say")
    if not say_bin:
        return None
    handle = tempfile.NamedTemporaryFile(prefix="rtc_asr_bench_", suffix=".aiff", delete=False)
    handle.close()
    subprocess.run([say_bin, "-v", "Samantha", "-o", handle.name, text], check=True)
    return Path(handle.name)


def load_audio(path: Path) -> tuple[np.ndarray, int]:
    samples, sample_rate = sf.read(str(path), dtype="float32", always_2d=False)
    if getattr(samples, "ndim", 1) > 1:
        samples = samples.mean(axis=1)
    samples = np.asarray(samples, dtype=np.float32)
    if samples.size == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return samples, int(sample_rate)


def benchmark_audio_path(args: argparse.Namespace) -> Path:
    if args.audio_file:
        return args.audio_file
    synthesized = synthesize_speech(args.speech_text)
    if synthesized is not None:
        return synthesized
    return FIXTURE_PATH


def normalize_text(text: str) -> str:
    lowered = text.casefold()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    return " ".join(lowered.split())


def edit_distance(reference: list[str], hypothesis: list[str]) -> int:
    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)

    previous = list(range(len(hypothesis) + 1))
    for ref_index, ref_token in enumerate(reference, start=1):
        current = [ref_index]
        for hyp_index, hyp_token in enumerate(hypothesis, start=1):
            substitution_cost = 0 if ref_token == hyp_token else 1
            current.append(min(
                previous[hyp_index] + 1,
                current[hyp_index - 1] + 1,
                previous[hyp_index - 1] + substitution_cost,
            ))
        previous = current
    return previous[-1]


def compute_accuracy_metrics(reference_text: str | None, hypothesis_text: str) -> dict[str, object] | None:
    if not reference_text:
        return None

    normalized_reference = normalize_text(reference_text)
    normalized_hypothesis = normalize_text(hypothesis_text)
    reference_words = normalized_reference.split()
    hypothesis_words = normalized_hypothesis.split()
    reference_chars = list(normalized_reference.replace(" ", ""))
    hypothesis_chars = list(normalized_hypothesis.replace(" ", ""))

    word_distance = edit_distance(reference_words, hypothesis_words)
    char_distance = edit_distance(reference_chars, hypothesis_chars)

    return {
        "reference_text": reference_text,
        "normalized_reference": normalized_reference,
        "normalized_hypothesis": normalized_hypothesis,
        "exact_match": normalized_reference == normalized_hypothesis,
        "word_error_rate": round(word_distance / max(len(reference_words), 1), 3),
        "character_error_rate": round(char_distance / max(len(reference_chars), 1), 3),
        "reference_word_count": len(reference_words),
        "hypothesis_word_count": len(hypothesis_words),
    }


def resolve_reference_text(args: argparse.Namespace, *, synthesized: bool) -> str | None:
    if args.reference_text:
        return args.reference_text.strip()
    if args.reference_file:
        return args.reference_file.read_text(encoding="utf-8").strip()
    if synthesized:
        return args.speech_text.strip()
    return None


def describe_environment() -> dict[str, object]:
    return {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor() or platform.machine(),
    }


async def fetch_service_metadata(base_url: str) -> dict[str, object] | None:
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        try:
            response = await client.get("/api/models")
            response.raise_for_status()
        except httpx.HTTPError:
            return None

    payload = response.json()
    if not isinstance(payload, dict):
        return None
    return payload


def resolve_service_model(service: dict[str, object] | None, fallback_model: str) -> str:
    if not isinstance(service, dict):
        return fallback_model

    top_level_model = service.get("model")
    if isinstance(top_level_model, str) and top_level_model:
        return top_level_model

    service_models = service.get("models")
    if isinstance(service_models, list) and service_models:
        primary_model = service_models[0]
        if isinstance(primary_model, str) and primary_model:
            return primary_model
        if isinstance(primary_model, dict):
            for key in ("id", "model"):
                value = primary_model.get(key)
                if isinstance(value, str) and value:
                    return value

    return fallback_model


class ManagedServer:
    def __init__(
        self,
        url: str,
        model: str,
        partial_window: float,
        *,
        backend: str,
        device: str,
        compute_type: str,
        qwen_dtype: str,
        parakeet_dtype: str,
    ) -> None:
        self.url = url
        self.model = model
        self.partial_window = partial_window
        self.backend = backend
        self.device = device
        self.compute_type = compute_type
        self.qwen_dtype = qwen_dtype
        self.parakeet_dtype = parakeet_dtype
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        (CACHE_ROOT / "hub").mkdir(parents=True, exist_ok=True)
        env.setdefault("HF_HOME", str(CACHE_ROOT))
        env.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_ROOT / "hub"))
        env.setdefault("ASR_BACKEND", self.backend)
        env.setdefault("ASR_DEVICE", self.device)
        env.setdefault("ASR_PRELOAD_MODEL", "true")
        env.setdefault("ASR_STREAM_PARTIAL_WINDOW_SECONDS", str(self.partial_window))
        if self.backend == "qwen-asr":
            env.setdefault("ASR_QWEN_MODEL", self.model)
            env.setdefault("ASR_QWEN_DTYPE", self.qwen_dtype)
        elif self.backend in {"parakeet", "parakeet-nemo", "parakeet-mlx"}:
            env.setdefault("ASR_PARAKEET_MODEL", self.model)
            env.setdefault("ASR_PARAKEET_DTYPE", self.parakeet_dtype)
        else:
            env.setdefault("ASR_MODEL_SIZE", self.model)
            env.setdefault("ASR_COMPUTE_TYPE", self.compute_type)
        command = [
            sys.executable,
            "-m",
            "uvicorn",
            "src.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            self.url.rsplit(":", 1)[1],
            "--log-level",
            "warning",
        ]
        self.process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )

    async def wait_ready(self, timeout_seconds: int = 120) -> None:
        deadline = time.monotonic() + timeout_seconds
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < deadline:
                try:
                    response = await client.get(f"{self.url}/ready")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1)
        raise TimeoutError(f"Service did not become ready: {self.url}/ready")

    def stop(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is not None:
            return
        self.process.send_signal(signal.SIGTERM)
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


async def post_transcribe_with_retries(
    client: httpx.AsyncClient,
    payload: dict[str, object],
    *,
    attempts: int,
    retry_delay: float,
    stage: str = "transcribe request",
) -> httpx.Response:
    last_error: Exception | None = None
    total_attempts = max(attempts, 1)
    for attempt in range(1, total_attempts + 1):
        try:
            response = await client.post("/api/transcribe", json=payload)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt >= total_attempts:
                break
            await asyncio.sleep(retry_delay)
    assert last_error is not None
    raise BenchmarkRequestError(stage, total_attempts, last_error) from last_error


async def run_rest_benchmark(
    base_url: str,
    wav_bytes: bytes,
    sample_rate: int,
    runs: int,
    duration_s: float,
    *,
    request_retries: int = 3,
    request_retry_delay: float = 2.0,
) -> dict[str, object]:
    payload = {
        "audio_data": base64.b64encode(wav_bytes).decode("ascii"),
        "language": "en",
        "sample_rate": sample_rate,
    }
    durations = []
    transcription = ""
    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        warmup = await post_transcribe_with_retries(
            client,
            payload,
            attempts=request_retries,
            retry_delay=request_retry_delay,
            stage="REST warmup",
        )
        transcription = warmup.json().get("text", "")
        for run_index in range(runs):
            started = time.perf_counter()
            response = await post_transcribe_with_retries(
                client,
                payload,
                attempts=request_retries,
                retry_delay=request_retry_delay,
                stage=f"REST sample {run_index + 1}/{runs}",
            )
            elapsed_ms = (time.perf_counter() - started) * 1000
            durations.append(elapsed_ms)
            transcription = response.json().get("text", "")
    return {
        "runs": runs,
        "durations_ms": [round(value, 1) for value in durations],
        **summarize_latencies(durations, duration_s=duration_s),
        "transcript": transcription,
    }


def _connect_websocket(ws_url: str):
    return websockets.connect(ws_url, max_size=2**23, ping_timeout=None)


def pcm_chunk_size(sample_rate: int, chunk_ms: int) -> int:
    chunk_size = max(int(sample_rate * 2 * chunk_ms / 1000), 2)
    if chunk_size % 2:
        chunk_size += 1
    return chunk_size


def chunk_pcm(raw_pcm: bytes, sample_rate: int, chunk_ms: int) -> list[bytes]:
    chunk_size = pcm_chunk_size(sample_rate, chunk_ms)
    return [raw_pcm[index:index + chunk_size] for index in range(0, len(raw_pcm), chunk_size)]


async def run_ws_benchmark(
    ws_url: str,
    raw_pcm: bytes,
    sample_rate: int,
    chunk_ms: int,
    *,
    partial_interval_chunks: int = 1,
    send_binary_frames: bool = False,
    partial_window_seconds: float | None = None,
    max_buffer_seconds: float | None = None,
    partial_event_timeout_seconds: float = 0.1,
    connect_fn=None,
) -> dict[str, object]:
    chunks = chunk_pcm(raw_pcm, sample_rate, chunk_ms)
    total_audio_ms = round((len(raw_pcm) / max(sample_rate * 2, 1)) * 1000, 1)
    partial_latencies = []
    partial_audio_offsets_ms = []
    partial_end_to_end_ms = []
    last_partial_visible_ms = 0.0
    partial_text = ""
    pending_partial_event: tuple[dict[str, object], float] | None = None
    pending_partial_started_at: dict[int, float] = {}
    recorded_partial_chunks: set[int] = set()

    def record_partial_event(
        event: dict[str, object],
        received_at: float,
        *,
        fallback_chunk_index: int,
    ) -> int | None:
        nonlocal last_partial_visible_ms, partial_text

        chunk_index = event.get("chunks_received")
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 1:
            chunk_index = fallback_chunk_index
        started_at = pending_partial_started_at.get(chunk_index)
        if started_at is None or chunk_index in recorded_partial_chunks:
            return None

        response_latency_ms = (received_at - started_at) * 1000
        partial_latencies.append(response_latency_ms)
        audio_offset_ms = min(round(chunk_index * chunk_ms, 1), total_audio_ms)
        partial_audio_offsets_ms.append(audio_offset_ms)
        visible_elapsed_ms = max(audio_offset_ms, last_partial_visible_ms) + response_latency_ms
        visible_elapsed_ms = round(visible_elapsed_ms, 1)
        partial_end_to_end_ms.append(visible_elapsed_ms)
        last_partial_visible_ms = visible_elapsed_ms
        partial_text = event.get("text", "")
        recorded_partial_chunks.add(chunk_index)
        pending_partial_started_at.pop(chunk_index, None)
        return chunk_index

    async def collect_partial_events(expected_chunk_index: int) -> None:
        nonlocal pending_partial_event

        deadline = time.perf_counter() + partial_event_timeout_seconds
        while expected_chunk_index not in recorded_partial_chunks:
            if pending_partial_event is not None:
                event, received_at = pending_partial_event
                pending_partial_event = None
            else:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    return
                try:
                    event = json.loads(await asyncio.wait_for(websocket.recv(), timeout=remaining))
                except TimeoutError:
                    return
                received_at = time.perf_counter()
            if event.get("type") != "partial":
                raise RuntimeError(f"Expected partial event, got: {event}")
            chunk_index = event.get("chunks_received")
            if isinstance(chunk_index, int) and not isinstance(chunk_index, bool) and chunk_index > expected_chunk_index:
                pending_partial_event = (event, received_at)
                return
            record_partial_event(event, received_at, fallback_chunk_index=expected_chunk_index)

    audio_finished_at: float | None = None
    connect = connect_fn or _connect_websocket
    async with connect(ws_url) as websocket:
        start_payload: dict[str, object] = {
            "type": "start",
            "language": "en",
            "sample_rate": sample_rate,
            "partial_interval_chunks": partial_interval_chunks,
        }
        if partial_window_seconds is not None:
            start_payload["partial_window_seconds"] = partial_window_seconds
        if max_buffer_seconds is not None:
            start_payload["max_buffer_seconds"] = max_buffer_seconds
        await websocket.send(json.dumps(start_payload))
        ready_event = json.loads(await websocket.recv())
        if ready_event.get("type") != "ready":
            raise RuntimeError(f"Expected ready event, got: {ready_event}")
        for chunk_index, chunk in enumerate(chunks, start=1):
            started = time.perf_counter()
            if send_binary_frames:
                await websocket.send(chunk)
            else:
                await websocket.send(json.dumps({
                    "type": "audio",
                    "audio_data": base64.b64encode(chunk).decode("ascii"),
                }))
            if chunk_index == len(chunks):
                audio_finished_at = time.perf_counter()
            if chunk_index % partial_interval_chunks != 0:
                continue
            pending_partial_started_at[chunk_index] = started
            await collect_partial_events(chunk_index)
        stop_started_at = time.perf_counter()
        await websocket.send(json.dumps({"type": "stop"}))
        while True:
            if pending_partial_event is not None:
                final_event, received_at = pending_partial_event
                pending_partial_event = None
            else:
                final_event = json.loads(await websocket.recv())
                received_at = time.perf_counter()
            if final_event.get("type") == "partial":
                record_partial_event(final_event, received_at, fallback_chunk_index=len(chunks))
                continue
            if final_event.get("type") != "final":
                raise RuntimeError(f"Expected final event, got: {final_event}")
            final_received_at = received_at
            break
        final_ms = (final_received_at - stop_started_at) * 1000
        time_to_final_from_audio_end_ms = (final_received_at - (audio_finished_at or stop_started_at)) * 1000
    partial_gap_ms = [
        round(current - previous, 1)
        for previous, current in zip(partial_end_to_end_ms, partial_end_to_end_ms[1:])
    ]
    partial_summary = {
        "partial_mean_ms": round(statistics.mean(partial_latencies), 1) if partial_latencies else None,
        "partial_p95_ms": round(percentile(partial_latencies, 0.95), 1) if partial_latencies else None,
        "partial_first_ms": round(partial_latencies[0], 1) if partial_latencies else None,
        "partial_last_ms": round(partial_latencies[-1], 1) if partial_latencies else None,
        "first_partial_audio_ms": partial_audio_offsets_ms[0] if partial_audio_offsets_ms else None,
        "first_partial_end_to_end_ms": partial_end_to_end_ms[0] if partial_end_to_end_ms else None,
        "partial_gap_mean_ms": round(statistics.mean(partial_gap_ms), 1) if partial_gap_ms else None,
        "partial_gap_p95_ms": round(percentile(partial_gap_ms, 0.95), 1) if partial_gap_ms else None,
    }
    return {
        "chunks": len(chunks),
        "chunk_ms": chunk_ms,
        "binary_frames": send_binary_frames,
        "transport": "direct",
        "partial_latencies_ms": [round(value, 1) for value in partial_latencies],
        "partial_audio_offsets_ms": partial_audio_offsets_ms,
        "partial_end_to_end_ms": partial_end_to_end_ms,
        "partial_gap_ms": partial_gap_ms,
        "partial_p90_ms": round(percentile(partial_latencies, 0.90), 1) if partial_latencies else None,
        **partial_summary,
        "final_ms": round(final_ms, 1),
        "time_to_final_from_audio_end_ms": round(time_to_final_from_audio_end_ms, 1),
        "ready": ready_event,
        "last_partial": partial_text,
        "final_transcript": final_event.get("text", ""),
        "expected_partial_events": len(chunks) // partial_interval_chunks,
        "observed_partial_events": len(recorded_partial_chunks),
        "missing_partial_events": max((len(chunks) // partial_interval_chunks) - len(recorded_partial_chunks), 0),
        "final_event_received": True,
        "closeout_event_type": final_event.get("type", "final"),
    }


async def run_pipecat_e2e_benchmark(
    ws_url: str,
    raw_pcm: bytes,
    sample_rate: int,
    chunk_ms: int,
    *,
    source_frame_ms: int = 20,
    partial_interval_chunks: int = 1,
    send_binary_frames: bool = False,
    partial_window_seconds: float | None = None,
    max_buffer_seconds: float | None = None,
    partial_event_timeout_seconds: float = 0.1,
    connect_fn=None,
) -> dict[str, object]:
    source_frames = chunk_pcm(raw_pcm, sample_rate, source_frame_ms)
    aggregation_bytes = pcm_chunk_size(sample_rate, chunk_ms)
    chunks: list[bytes] = []
    chunk_audio_offsets_ms: list[float] = []
    buffer = bytearray()
    source_audio_ms = 0.0
    total_audio_ms = round((len(raw_pcm) / max(sample_rate * 2, 1)) * 1000, 1)
    for frame in source_frames:
        buffer.extend(frame)
        source_audio_ms = min(round(source_audio_ms + source_frame_ms, 1), total_audio_ms)
        if len(buffer) < aggregation_bytes:
            continue
        chunks.append(bytes(buffer))
        chunk_audio_offsets_ms.append(source_audio_ms)
        buffer.clear()
    if buffer:
        chunks.append(bytes(buffer))
        chunk_audio_offsets_ms.append(total_audio_ms)

    partial_latencies = []
    partial_audio_offsets_ms = []
    partial_end_to_end_ms = []
    partial_gap_ms: list[float] = []
    last_partial_visible_ms = 0.0
    last_partial_text = ""
    observed_partial_events = 0
    pending_partial_started_at: dict[int, float] = {}
    recorded_partial_chunks: set[int] = set()

    def record_partial_event(
        event: TranscriptEvent,
        received_at: float,
        *,
        fallback_chunk_index: int,
    ) -> int | None:
        nonlocal last_partial_visible_ms, last_partial_text, observed_partial_events

        chunk_index = getattr(event, "chunks_received", 0)
        if chunk_index < 1:
            chunk_index = fallback_chunk_index
        started_at = pending_partial_started_at.get(chunk_index)
        if started_at is None or chunk_index in recorded_partial_chunks:
            return None

        response_latency_ms = (received_at - started_at) * 1000
        audio_offset_ms = chunk_audio_offsets_ms[min(chunk_index - 1, len(chunk_audio_offsets_ms) - 1)]
        visible_elapsed_ms = max(audio_offset_ms, last_partial_visible_ms) + response_latency_ms
        visible_elapsed_ms = round(visible_elapsed_ms, 1)
        partial_latencies.append(response_latency_ms)
        partial_audio_offsets_ms.append(audio_offset_ms)
        partial_end_to_end_ms.append(visible_elapsed_ms)
        if len(partial_end_to_end_ms) > 1:
            partial_gap_ms.append(round(partial_end_to_end_ms[-1] - partial_end_to_end_ms[-2], 1))
        last_partial_visible_ms = visible_elapsed_ms
        last_partial_text = event.text
        observed_partial_events += 1
        recorded_partial_chunks.add(chunk_index)
        pending_partial_started_at.pop(chunk_index, None)
        return chunk_index

    async def recv_event_with_timeout(timeout: float) -> TranscriptEvent | None:
        payload = await client._recv_json_with_timeout(timeout)
        if payload is None:
            return None
        return TranscriptEvent.from_payload(payload)

    async def collect_partial_events(expected_chunk_index: int) -> None:
        deadline = time.perf_counter() + partial_event_timeout_seconds
        while expected_chunk_index not in recorded_partial_chunks:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            event = await recv_event_with_timeout(remaining)
            if event is None:
                return
            received_at = time.perf_counter()
            if event.type != "partial":
                raise RuntimeError(f"Expected partial event, got: {event.type}")
            if event.chunks_received > expected_chunk_index:
                record_partial_event(event, received_at, fallback_chunk_index=event.chunks_received)
                return
            record_partial_event(event, received_at, fallback_chunk_index=expected_chunk_index)

    client = AsyncASRClient(ws_url, connect_fn=connect_fn)
    ready_event = await client.start(
        language="en",
        sample_rate=sample_rate,
        partial_interval_chunks=partial_interval_chunks,
        partial_window_seconds=partial_window_seconds,
        max_buffer_seconds=max_buffer_seconds,
        send_binary_frames=send_binary_frames,
    )
    final_event = None
    audio_finished_at: float | None = None
    try:
        for chunk_index, chunk in enumerate(chunks, start=1):
            started = time.perf_counter()
            partial_event = await client.send_audio(chunk, response_timeout=partial_event_timeout_seconds)
            if chunk_index == len(chunks):
                audio_finished_at = time.perf_counter()
            if chunk_index % partial_interval_chunks != 0:
                continue
            pending_partial_started_at[chunk_index] = started
            if partial_event is None:
                if hasattr(client, "_recv_json_with_timeout"):
                    await collect_partial_events(chunk_index)
                continue
            if partial_event.type != "partial":
                raise RuntimeError(f"Expected partial event, got: {partial_event.type}")
            record_partial_event(partial_event, time.perf_counter(), fallback_chunk_index=chunk_index)

        stop_started_at = time.perf_counter()
        if hasattr(client, "_require_websocket") and hasattr(client, "_recv_json"):
            websocket = client._require_websocket()
            await websocket.send(json.dumps({"type": "stop"}))
            client._chunks_sent = 0
            client._send_binary_frames = False
            while True:
                event = TranscriptEvent.from_payload(await client._recv_json(allow_error=True))
                received_at = time.perf_counter()
                if event.type == "partial":
                    fallback_chunk_index = event.chunks_received if event.chunks_received > 0 else len(chunks)
                    record_partial_event(event, received_at, fallback_chunk_index=fallback_chunk_index)
                    continue
                final_event = event
                final_received_at = received_at
                break
        else:
            final_event = await client.stop()
            final_received_at = time.perf_counter()
    finally:
        await client.close()

    final_ms = (final_received_at - stop_started_at) * 1000
    time_to_final_from_audio_end_ms = (final_received_at - (audio_finished_at or stop_started_at)) * 1000
    partial_summary = {
        "partial_mean_ms": round(statistics.mean(partial_latencies), 1) if partial_latencies else None,
        "partial_p95_ms": round(percentile(partial_latencies, 0.95), 1) if partial_latencies else None,
        "partial_first_ms": round(partial_latencies[0], 1) if partial_latencies else None,
        "partial_last_ms": round(partial_latencies[-1], 1) if partial_latencies else None,
        "first_partial_audio_ms": partial_audio_offsets_ms[0] if partial_audio_offsets_ms else None,
        "first_partial_end_to_end_ms": partial_end_to_end_ms[0] if partial_end_to_end_ms else None,
        "partial_gap_mean_ms": round(statistics.mean(partial_gap_ms), 1) if partial_gap_ms else None,
        "partial_gap_p95_ms": round(percentile(partial_gap_ms, 0.95), 1) if partial_gap_ms else None,
    }
    expected_partial_events = len(chunks) // partial_interval_chunks
    return {
        "chunks": len(chunks),
        "chunk_ms": chunk_ms,
        "binary_frames": send_binary_frames,
        "transport": "pipecat-e2e",
        "source_frame_ms": source_frame_ms,
        "source_frame_count": len(source_frames),
        "aggregation_frame_count": max(int(round(chunk_ms / max(source_frame_ms, 1))), 1),
        "partial_latencies_ms": [round(value, 1) for value in partial_latencies],
        "partial_audio_offsets_ms": partial_audio_offsets_ms,
        "partial_end_to_end_ms": partial_end_to_end_ms,
        "partial_gap_ms": partial_gap_ms,
        "partial_p90_ms": round(percentile(partial_latencies, 0.90), 1) if partial_latencies else None,
        **partial_summary,
        "final_ms": round(final_ms, 1),
        "time_to_final_from_audio_end_ms": round(time_to_final_from_audio_end_ms, 1),
        "ready": ready_event,
        "last_partial": last_partial_text,
        "final_transcript": final_event.text if final_event is not None else "",
        "expected_partial_events": expected_partial_events,
        "observed_partial_events": observed_partial_events,
        "missing_partial_events": max(expected_partial_events - observed_partial_events, 0),
        "final_event_received": final_event is not None and final_event.type == "final",
        "closeout_event_type": None if final_event is None else final_event.type,
    }


async def async_main(args: argparse.Namespace) -> dict[str, object]:
    audio_path = benchmark_audio_path(args)
    synthesized = audio_path != args.audio_file if args.audio_file else audio_path != FIXTURE_PATH
    reference_text = resolve_reference_text(args, synthesized=synthesized)
    samples, sample_rate = load_audio(audio_path)
    wav_bytes = make_wav_bytes(samples, sample_rate)
    raw_pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    duration_s = len(samples) / sample_rate
    server = ManagedServer(
        args.url,
        args.model,
        args.partial_window,
        backend=args.backend,
        device=args.device,
        compute_type=args.compute_type,
        qwen_dtype=args.qwen_dtype,
        parakeet_dtype=args.parakeet_dtype,
    ) if args.spawn_server else None

    try:
        if server is not None:
            server.start()
            await server.wait_ready()
        service = await fetch_service_metadata(args.url)

        sample_count = max(args.sample_count, 1)
        rest_samples: list[dict[str, object]] = []
        streaming_samples: list[dict[str, object]] = []
        rest_durations_all: list[float] = []
        partial_latencies_all: list[float] = []
        first_partial_end_to_end_all: list[float] = []
        partial_gap_all: list[float] = []
        final_latencies_all: list[float] = []
        finalization_latencies_all: list[float] = []
        missing_partial_events_all: list[int] = []
        closeout_event_types: list[str] = []
        final_event_received_count = 0

        for index in range(sample_count):
            rest = await run_rest_benchmark(
                args.url,
                wav_bytes,
                sample_rate,
                args.rest_runs,
                duration_s,
                request_retries=args.request_retries,
                request_retry_delay=args.request_retry_delay,
            )
            if args.mode == "pipecat-e2e":
                ws = await run_pipecat_e2e_benchmark(
                    args.ws_url,
                    raw_pcm,
                    sample_rate,
                    args.chunk_ms,
                    source_frame_ms=args.pipecat_source_frame_ms,
                    partial_interval_chunks=args.partial_interval_chunks,
                    send_binary_frames=args.binary_frames,
                    partial_window_seconds=args.partial_window,
                    max_buffer_seconds=args.max_buffer,
                    partial_event_timeout_seconds=args.partial_event_timeout,
                )
            else:
                ws = await run_ws_benchmark(
                    args.ws_url,
                    raw_pcm,
                    sample_rate,
                    args.chunk_ms,
                    partial_interval_chunks=args.partial_interval_chunks,
                    send_binary_frames=args.binary_frames,
                    partial_window_seconds=args.partial_window,
                    max_buffer_seconds=args.max_buffer,
                    partial_event_timeout_seconds=args.partial_event_timeout,
                )
            rest["accuracy"] = compute_accuracy_metrics(reference_text, str(rest.get("transcript", "")))
            ws["accuracy"] = compute_accuracy_metrics(reference_text, str(ws.get("final_transcript", "")))
            rest_durations_all.extend(float(value) for value in rest.get("durations_ms", []))
            partial_latencies_all.extend(float(value) for value in ws.get("partial_latencies_ms", []))
            first_partial_end_to_end = ws.get("first_partial_end_to_end_ms")
            if first_partial_end_to_end is not None:
                first_partial_end_to_end_all.append(float(first_partial_end_to_end))
            partial_gap_all.extend(float(value) for value in ws.get("partial_gap_ms", []))
            final_latencies_all.append(float(ws.get("final_ms", 0.0)))
            finalization_latencies_all.append(
                float(ws.get("time_to_final_from_audio_end_ms", ws.get("final_ms", 0.0)))
            )
            missing_partial_events_all.append(int(ws.get("missing_partial_events", 0)))
            if ws.get("final_event_received"):
                final_event_received_count += 1
            closeout_event_type = ws.get("closeout_event_type")
            if isinstance(closeout_event_type, str) and closeout_event_type:
                closeout_event_types.append(closeout_event_type)
            rest_samples.append({
                "sample": index + 1,
                "mean_ms": rest["mean_ms"],
                "p90_ms": rest["p90_ms"],
                "p95_ms": rest["p95_ms"],
                "min_ms": rest["min_ms"],
                "max_ms": rest["max_ms"],
                "rtf_mean": rest["rtf_mean"],
                "transcript": rest["transcript"],
                "accuracy": rest["accuracy"],
            })
            streaming_samples.append({
                "sample": index + 1,
                "transport": ws.get("transport", "direct"),
                "source_frame_ms": ws.get("source_frame_ms"),
                "source_frame_count": ws.get("source_frame_count"),
                "aggregation_frame_count": ws.get("aggregation_frame_count"),
                "binary_frames": ws["binary_frames"],
                "partial_mean_ms": ws["partial_mean_ms"],
                "partial_p90_ms": ws["partial_p90_ms"],
                "partial_p95_ms": ws["partial_p95_ms"],
                "partial_first_ms": ws["partial_first_ms"],
                "partial_last_ms": ws["partial_last_ms"],
                "first_partial_audio_ms": ws["first_partial_audio_ms"],
                "first_partial_end_to_end_ms": ws["first_partial_end_to_end_ms"],
                "partial_gap_mean_ms": ws["partial_gap_mean_ms"],
                "partial_gap_p95_ms": ws["partial_gap_p95_ms"],
                "time_to_final_from_audio_end_ms": ws["time_to_final_from_audio_end_ms"],
                "final_ms": ws["final_ms"],
                "ready": ws["ready"],
                "last_partial": ws["last_partial"],
                "final_transcript": ws["final_transcript"],
                "expected_partial_events": ws.get("expected_partial_events"),
                "observed_partial_events": ws.get("observed_partial_events"),
                "missing_partial_events": ws.get("missing_partial_events"),
                "final_event_received": ws.get("final_event_received"),
                "closeout_event_type": ws.get("closeout_event_type"),
                "accuracy": ws["accuracy"],
            })
        capabilities = service.get("capabilities") if isinstance(service, dict) else None
        effective_backend = service.get("backend", args.backend) if isinstance(service, dict) else args.backend
        effective_model = resolve_service_model(service, args.model)
        effective_device = capabilities.get("device", args.device) if isinstance(capabilities, dict) else args.device
        effective_compute_type = None
        effective_qwen_dtype = None
        effective_parakeet_dtype = None
        if effective_backend == "qwen-asr":
            if isinstance(capabilities, dict):
                effective_qwen_dtype = capabilities.get("dtype")
            if effective_qwen_dtype is None:
                effective_qwen_dtype = args.qwen_dtype
        elif effective_backend in {"parakeet", "parakeet-nemo", "parakeet-mlx"}:
            if isinstance(capabilities, dict):
                effective_parakeet_dtype = capabilities.get("dtype")
            if effective_parakeet_dtype is None:
                effective_parakeet_dtype = args.parakeet_dtype
        else:
            if isinstance(capabilities, dict):
                effective_compute_type = capabilities.get("compute_type")
            if effective_compute_type is None:
                effective_compute_type = args.compute_type

        rest_accuracy_samples = [sample["accuracy"] for sample in rest_samples if sample.get("accuracy")]
        streaming_accuracy_samples = [sample["accuracy"] for sample in streaming_samples if sample.get("accuracy")]

        def summarize_accuracy(samples: list[dict[str, object]]) -> dict[str, object] | None:
            if not samples:
                return None
            word_error_rates = [float(sample["word_error_rate"]) for sample in samples if sample.get("word_error_rate") is not None]
            character_error_rates = [float(sample["character_error_rate"]) for sample in samples if sample.get("character_error_rate") is not None]
            exact_match_rate = sum(1 for sample in samples if sample.get("exact_match")) / len(samples)
            summary: dict[str, object] = {
                "sample_count": len(samples),
                "exact_match_rate": round(exact_match_rate, 3),
                "word_error_rate_mean": round(statistics.mean(word_error_rates), 3) if word_error_rates else None,
                "word_error_rate_p90": round(percentile(word_error_rates, 0.90), 3) if word_error_rates else None,
                "character_error_rate_mean": round(statistics.mean(character_error_rates), 3) if character_error_rates else None,
                "character_error_rate_p90": round(percentile(character_error_rates, 0.90), 3) if character_error_rates else None,
            }
            return summary

        rest_summary = summarize_latencies(rest_durations_all, duration_s=duration_s)
        streaming_summary = summarize_latencies(partial_latencies_all) if partial_latencies_all else None
        first_partial_summary = summarize_latencies(first_partial_end_to_end_all) if first_partial_end_to_end_all else None
        partial_gap_summary = summarize_latencies(partial_gap_all) if partial_gap_all else None
        final_summary = summarize_latencies(finalization_latencies_all)

        return {
            "environment": describe_environment(),
            "benchmark": {
                "sample_count": sample_count,
                "mode": args.mode,
                "rest_runs_per_sample": args.rest_runs,
                "chunk_ms": args.chunk_ms,
                "partial_interval_chunks": args.partial_interval_chunks,
                "binary_frames": args.binary_frames,
                "source_frame_ms": args.pipecat_source_frame_ms if args.mode == "pipecat-e2e" else None,
                "partial_window_seconds": args.partial_window,
                "max_buffer_seconds": args.max_buffer,
                "partial_event_timeout_seconds": args.partial_event_timeout,
                "request_retries": args.request_retries,
                "request_retry_delay": args.request_retry_delay,
                "pipecat_source_frame_ms": args.pipecat_source_frame_ms if args.mode == "pipecat-e2e" else None,
            },
            "integration": {
                "name": "pipecat" if args.mode == "pipecat-e2e" else None,
                "transport": args.mode,
                "source_frame_ms": args.pipecat_source_frame_ms if args.mode == "pipecat-e2e" else None,
                "bridge_chunk_ms": args.chunk_ms if args.mode == "pipecat-e2e" else None,
                "send_binary_frames": args.binary_frames if args.mode == "pipecat-e2e" else None,
            } if args.mode == "pipecat-e2e" else None,
            "audio": {
                "path": str(audio_path),
                "duration_s": round(duration_s, 3),
                "sample_rate": sample_rate,
                "synthesized": synthesized,
                "reference_text": reference_text,
            },
            "backend": {
                "name": effective_backend,
                "model": effective_model,
                "device": effective_device,
                "compute_type": effective_compute_type,
                "qwen_dtype": effective_qwen_dtype,
                "parakeet_dtype": effective_parakeet_dtype,
            },
            "service": service,
            "samples": {
                "rest": rest_samples,
                "streaming": streaming_samples,
            },
            "rest": {
                "sample_count": sample_count,
                "runs_per_sample": args.rest_runs,
                "durations_ms": [round(value, 1) for value in rest_durations_all],
                **rest_summary,
                "accuracy": summarize_accuracy(rest_accuracy_samples),
                "transcript": rest_samples[0]["transcript"] if rest_samples else "",
            },
            "streaming": {
                "sample_count": sample_count,
                "transport": args.mode,
                "chunk_ms": args.chunk_ms,
                "partial_interval_chunks": args.partial_interval_chunks,
                "binary_frames": args.binary_frames,
                "source_frame_ms": args.pipecat_source_frame_ms if args.mode == "pipecat-e2e" else None,
                "partial_window_seconds": args.partial_window,
                "max_buffer_seconds": args.max_buffer,
                "partial_event_timeout_seconds": args.partial_event_timeout,
                "request_retries": args.request_retries,
                "request_retry_delay": args.request_retry_delay,
                "partial_latencies_ms": [round(value, 1) for value in partial_latencies_all],
                "first_partial_end_to_end_latencies_ms": [round(value, 1) for value in first_partial_end_to_end_all],
                "partial_gap_latencies_ms": [round(value, 1) for value in partial_gap_all],
                "final_latencies_ms": [round(value, 1) for value in finalization_latencies_all],
                "stop_to_final_latencies_ms": [round(value, 1) for value in final_latencies_all],
                "binary_frames": args.binary_frames,
                "partial_mean_ms": streaming_summary["mean_ms"] if streaming_summary else None,
                "partial_p90_ms": streaming_summary["p90_ms"] if streaming_summary else None,
                "partial_p95_ms": streaming_summary["p95_ms"] if streaming_summary else None,
                "partial_min_ms": streaming_summary["min_ms"] if streaming_summary else None,
                "partial_max_ms": streaming_summary["max_ms"] if streaming_summary else None,
                "first_partial_end_to_end_mean_ms": first_partial_summary["mean_ms"] if first_partial_summary else None,
                "first_partial_end_to_end_p90_ms": first_partial_summary["p90_ms"] if first_partial_summary else None,
                "first_partial_end_to_end_p95_ms": first_partial_summary["p95_ms"] if first_partial_summary else None,
                "partial_gap_mean_ms": partial_gap_summary["mean_ms"] if partial_gap_summary else None,
                "partial_gap_p90_ms": partial_gap_summary["p90_ms"] if partial_gap_summary else None,
                "partial_gap_p95_ms": partial_gap_summary["p95_ms"] if partial_gap_summary else None,
                "time_to_final_from_audio_end_mean_ms": final_summary["mean_ms"],
                "time_to_final_from_audio_end_p90_ms": final_summary["p90_ms"],
                "time_to_final_from_audio_end_p95_ms": final_summary["p95_ms"],
                "time_to_final_from_audio_end_min_ms": final_summary["min_ms"],
                "time_to_final_from_audio_end_max_ms": final_summary["max_ms"],
                "final_mean_ms": final_summary["mean_ms"],
                "final_p90_ms": final_summary["p90_ms"],
                "final_p95_ms": final_summary["p95_ms"],
                "final_min_ms": final_summary["min_ms"],
                "final_max_ms": final_summary["max_ms"],
                "ready": streaming_samples[0]["ready"] if streaming_samples else None,
                "last_partial": streaming_samples[0]["last_partial"] if streaming_samples else "",
                "final_transcript": streaming_samples[0]["final_transcript"] if streaming_samples else "",
                "expected_partial_events": sum(int(sample.get("expected_partial_events", 0)) for sample in streaming_samples),
                "observed_partial_events": sum(int(sample.get("observed_partial_events", 0)) for sample in streaming_samples),
                "missing_partial_events": sum(missing_partial_events_all),
                "final_event_received_count": final_event_received_count,
                "closeout_event_types": closeout_event_types,
                "accuracy": summarize_accuracy(streaming_accuracy_samples),
            },
        }
    finally:
        if server is not None:
            server.stop()
        if audio_path != FIXTURE_PATH and (args.audio_file is None or audio_path != args.audio_file):
            audio_path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    results = asyncio.run(async_main(args))
    rendered = json.dumps(results, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
