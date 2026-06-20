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
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
import soundfile as sf
import websockets

from src.rtc_client import AsyncASRClient, AsyncLocalSttClient, TranscriptEvent

DEFAULT_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a realtime ASR latency benchmark for the rtc asr service."
)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "smoke.wav"
CACHE_ROOT = ROOT / ".cache" / "huggingface"
BENCHMARK_SAMPLE_RATE = 16000


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
    preload_group = parser.add_mutually_exclusive_group()
    require_preloaded_group = parser.add_mutually_exclusive_group()
    simulate_realtime_group = parser.add_mutually_exclusive_group()
    parser.add_argument(
        "--mode",
        choices=("direct", "pipecat-e2e", "v1-stt-stream"),
        default="direct",
        help="Streaming benchmark mode: direct websocket chunks, Pipecat-style source frames, or /v1/stt/stream local STT protocol mode",
    )
    parser.add_argument("--url", default="http://127.0.0.1:8090", help="Base URL for the ASR service")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8090/ws/stream", help="WebSocket URL for streaming")
    parser.add_argument("--v1-ws-url", default="ws://127.0.0.1:8090/v1/stt/stream", help="WebSocket URL for Local STT v1 streaming")
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
    parser.add_argument("--model", default="base.en", help="Model name when spawning a local server")
    parser.add_argument("--device", default="cpu", help="ASR device when spawning a local server")
    parser.add_argument("--compute-type", default="int8", help="Compute type for faster-whisper when spawning a local server")
    parser.add_argument("--qwen-dtype", default="auto", help="Dtype for qwen-asr when spawning a local server")
    parser.add_argument("--parakeet-dtype", default="auto", help="Dtype for parakeet when spawning a local server")
    preload_group.add_argument(
        "--preload-model",
        dest="preload_model",
        action="store_true",
        help="Preload the model before a managed benchmark server starts accepting traffic (default)",
    )
    preload_group.add_argument(
        "--no-preload-model",
        dest="preload_model",
        action="store_false",
        help="Allow managed benchmark servers to lazy-load the model on first request",
    )
    parser.add_argument("--partial-window", type=non_negative_float, default=2.0, help="Partial transcription window in seconds when spawning a local server")
    parser.add_argument("--max-buffer", type=non_negative_float, help="Optional stream buffer cap in seconds for websocket benchmarking")
    parser.add_argument(
        "--partial-event-timeout",
        type=non_negative_float,
        default=0.1,
        help="Seconds to wait for an eligible streaming partial before moving on",
    )
    parser.add_argument(
        "--final-event-timeout",
        type=non_negative_float,
        default=10.0,
        help="Seconds to wait for the final streaming transcript after finalize",
    )
    parser.add_argument("--request-retries", type=positive_int, default=3, help="REST request attempts before failing a sample")
    parser.add_argument("--request-retry-delay", type=non_negative_float, default=2.0, help="Seconds to wait between REST request retries")
    parser.add_argument("--package-power-watts", type=non_negative_float, help="Optional externally measured package power average in watts")
    parser.add_argument("--thermal-state", help="Optional externally observed sustained thermal state for the benchmark run")
    parser.add_argument(
        "--pipecat-source-frame-ms",
        type=positive_int,
        default=20,
        help="Pipecat-style source frame duration in milliseconds before bridge aggregation",
    )
    parser.add_argument(
        "--v1-source-frame-ms",
        type=positive_int,
        default=20,
        help="Source PCM16 frame duration in milliseconds for /v1/stt/stream",
    )
    parser.add_argument(
        "--v1-aggregation-ms",
        type=positive_int,
        default=100,
        help="Aggregation chunk duration in milliseconds before sending a /v1/stt/stream payload",
    )
    parser.add_argument(
        "--v1-partial-interval-ms",
        type=positive_int,
        default=100,
        help="Requested partial cadence in milliseconds for /v1/stt/stream",
    )
    simulate_realtime_group.add_argument(
        "--simulate-realtime",
        dest="simulate_realtime",
        action="store_true",
        help="Pace source frames against wall clock time so streaming metrics reflect live speech cadence (default)",
    )
    simulate_realtime_group.add_argument(
        "--no-simulate-realtime",
        dest="simulate_realtime",
        action="store_false",
        help="Send source frames as fast as possible for stress or catch-up measurements",
    )
    require_preloaded_group.add_argument(
        "--require-preloaded-service",
        dest="require_preloaded_service",
        action="store_true",
        help="Fail when benchmarking an external service that does not report preload_enabled=true (default)",
    )
    require_preloaded_group.add_argument(
        "--allow-unpreloaded-service",
        dest="require_preloaded_service",
        action="store_false",
        help="Allow benchmarking an external service even when it reports preload_enabled=false",
    )
    parser.add_argument("--output", type=Path, help="Optional path for the benchmark JSON artifact")
    parser.set_defaults(preload_model=True, require_preloaded_service=True, simulate_realtime=True)
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


def summarize_ratio_series(values: list[float]) -> dict[str, float]:
    return {
        "mean": round(statistics.mean(values), 3),
        "p90": round(percentile(values, 0.90), 3),
        "p95": round(percentile(values, 0.95), 3),
        "min": round(min(values), 3),
        "max": round(max(values), 3),
    }


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


def resample_audio(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    if samples.size == 0:
        return samples.astype(np.float32, copy=False)
    duration_seconds = samples.shape[0] / source_rate
    target_length = max(int(round(duration_seconds * target_rate)), 1)
    source_positions = np.linspace(0.0, duration_seconds, num=samples.shape[0], endpoint=False)
    target_positions = np.linspace(0.0, duration_seconds, num=target_length, endpoint=False)
    return np.interp(target_positions, source_positions, samples).astype(np.float32)


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


def summarize_partial_churn(partial_texts: list[str]) -> dict[str, object]:
    if len(partial_texts) < 2:
        return {
            "partial_revision_count": max(len(partial_texts) - 1, 0),
            "partial_transcript_churn_char_mean": None,
            "partial_transcript_churn_char_p95": None,
            "partial_transcript_churn_word_mean": None,
            "partial_transcript_churn_word_p95": None,
        }

    char_churn: list[float] = []
    word_churn: list[float] = []
    for previous, current in zip(partial_texts, partial_texts[1:]):
        normalized_previous = normalize_text(previous)
        normalized_current = normalize_text(current)
        previous_chars = list(normalized_previous.replace(" ", ""))
        current_chars = list(normalized_current.replace(" ", ""))
        previous_words = normalized_previous.split()
        current_words = normalized_current.split()
        char_denominator = max(len(previous_chars), len(current_chars), 1)
        word_denominator = max(len(previous_words), len(current_words), 1)
        char_churn.append(edit_distance(previous_chars, current_chars) / char_denominator)
        word_churn.append(edit_distance(previous_words, current_words) / word_denominator)

    return {
        "partial_revision_count": len(partial_texts) - 1,
        "partial_transcript_churn_char_mean": round(statistics.mean(char_churn), 3),
        "partial_transcript_churn_char_p95": round(percentile(char_churn, 0.95), 3),
        "partial_transcript_churn_word_mean": round(statistics.mean(word_churn), 3),
        "partial_transcript_churn_word_p95": round(percentile(word_churn, 0.95), 3),
    }


def resolve_reference_text(args: argparse.Namespace, *, synthesized: bool) -> str | None:
    if args.reference_text:
        return args.reference_text.strip()
    if args.reference_file:
        return args.reference_file.read_text(encoding="utf-8").strip()
    if synthesized:
        return args.speech_text.strip()
    return None


class ProcessPeakRSSMonitor:
    """Poll a managed service process so published RSS reflects the run peak."""

    def __init__(self, pid: int, *, interval_seconds: float = 0.05) -> None:
        self.pid = pid
        self.interval_seconds = interval_seconds
        self.peak_rss_mb: float | None = None
        self.cpu_utilization_percent: float | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import psutil
        except Exception:
            return

        self._thread = threading.Thread(target=self._run, args=(psutil,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1)

    def _run(self, psutil_module: object) -> None:
        try:
            process = psutil_module.Process(self.pid)
        except Exception:
            return

        cpu_samples: list[float] = []
        try:
            process.cpu_percent(interval=None)
        except Exception:
            return

        while True:
            stop_requested = self._stop_event.wait(self.interval_seconds)
            try:
                rss_mb = round(process.memory_info().rss / (1024 * 1024), 1)
                cpu_percent = float(process.cpu_percent(interval=None))
            except Exception:
                return
            if self.peak_rss_mb is None or rss_mb > self.peak_rss_mb:
                self.peak_rss_mb = rss_mb
            cpu_samples.append(cpu_percent)

            if stop_requested:
                break

        if cpu_samples:
            self.cpu_utilization_percent = round(statistics.mean(cpu_samples), 1)


def describe_environment(
    *,
    service_pid: int | None = None,
    peak_rss_mb: float | None = None,
    cpu_utilization_percent: float | None = None,
    package_power_watts: float | None = None,
    thermal_state: str | None = None,
) -> dict[str, object]:
    cpu_logical_cores = os.cpu_count()
    memory_total_mb: float | None = None
    process_rss_mb: float | None = None
    measured_peak_rss_mb = peak_rss_mb

    try:
        import psutil

        virtual_memory = psutil.virtual_memory()
        memory_total_mb = round(virtual_memory.total / (1024 * 1024), 1)
        if service_pid is not None:
            process_rss_mb = round(psutil.Process(service_pid).memory_info().rss / (1024 * 1024), 1)
            if measured_peak_rss_mb is None:
                measured_peak_rss_mb = process_rss_mb
    except Exception:
        memory_total_mb = None
        process_rss_mb = None
        measured_peak_rss_mb = peak_rss_mb

    return {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor() or platform.machine(),
        "machine": platform.machine(),
        "cpu_logical_cores": cpu_logical_cores,
        "memory_total_mb": memory_total_mb,
        "process_rss_mb": process_rss_mb,
        "peak_rss_mb": measured_peak_rss_mb,
        "cpu_utilization_percent": cpu_utilization_percent,
        "package_power_watts": package_power_watts,
        "thermal_state": thermal_state,
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


def service_preload_enabled(service: dict[str, object] | None) -> bool | None:
    if not isinstance(service, dict):
        return None
    preload_enabled = service.get("preload_enabled")
    if isinstance(preload_enabled, bool):
        return preload_enabled
    return None


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
        preload_model: bool,
    ) -> None:
        self.url = url
        self.model = model
        self.partial_window = partial_window
        self.backend = backend
        self.device = device
        self.compute_type = compute_type
        self.qwen_dtype = qwen_dtype
        self.parakeet_dtype = parakeet_dtype
        self.preload_model = preload_model
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        (CACHE_ROOT / "hub").mkdir(parents=True, exist_ok=True)
        env.setdefault("HF_HOME", str(CACHE_ROOT))
        env.setdefault("HUGGINGFACE_HUB_CACHE", str(CACHE_ROOT / "hub"))
        env.setdefault("ASR_BACKEND", self.backend)
        env.setdefault("ASR_DEVICE", self.device)
        env["ASR_PRELOAD_MODEL"] = "true" if self.preload_model else "false"
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
    partial_gap_ms: list[float] = []
    last_partial_visible_ms = 0.0
    last_recorded_partial_received_at: float | None = None
    partial_text = ""
    partial_texts: list[str] = []
    late_partial_events = 0
    pending_partial_event: tuple[dict[str, object], float] | None = None
    pending_partial_started_at: dict[int, float] = {}
    recorded_partial_chunks: set[int] = set()

    def record_partial_event(
        event: dict[str, object],
        received_at: float,
        *,
        fallback_chunk_index: int,
    ) -> int | None:
        nonlocal last_partial_visible_ms, last_recorded_partial_received_at, partial_text

        chunk_index = event.get("chunks_received")
        if not isinstance(chunk_index, int) or isinstance(chunk_index, bool) or chunk_index < 1:
            chunk_index = fallback_chunk_index
        started_at = pending_partial_started_at.get(chunk_index)
        if started_at is None:
            return None

        partial_text = event.get("text", "")
        partial_texts.append(partial_text)
        if chunk_index in recorded_partial_chunks:
            return None

        response_latency_ms = (received_at - started_at) * 1000
        partial_latencies.append(response_latency_ms)
        audio_offset_ms = min(round(chunk_index * chunk_ms, 1), total_audio_ms)
        partial_audio_offsets_ms.append(audio_offset_ms)
        visible_elapsed_ms = max(audio_offset_ms, last_partial_visible_ms) + response_latency_ms
        visible_elapsed_ms = round(visible_elapsed_ms, 1)
        partial_end_to_end_ms.append(visible_elapsed_ms)
        if last_recorded_partial_received_at is not None:
            partial_gap_ms.append(round((received_at - last_recorded_partial_received_at) * 1000, 1))
        last_partial_visible_ms = visible_elapsed_ms
        last_recorded_partial_received_at = received_at
        recorded_partial_chunks.add(chunk_index)
        return chunk_index

    async def collect_partial_events(expected_chunk_index: int) -> None:
        nonlocal pending_partial_event, late_partial_events

        deadline = time.perf_counter() + partial_event_timeout_seconds
        nonlocal late_partial_events
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
            if isinstance(chunk_index, int) and not isinstance(chunk_index, bool) and chunk_index != expected_chunk_index:
                late_partial_events += 1
                if chunk_index > expected_chunk_index:
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
    partial_churn = summarize_partial_churn(partial_texts)
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
        "late_partial_events": late_partial_events,
        "late_partial_ratio": round(late_partial_events / len(recorded_partial_chunks), 3) if recorded_partial_chunks else None,
        "final_event_received": True,
        "closeout_event_type": final_event.get("type", "final"),
        **partial_churn,
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
    simulate_realtime: bool = False,
    sleep_fn=None,
    connect_fn=None,
) -> dict[str, object]:
    source_frames = chunk_pcm(raw_pcm, sample_rate, source_frame_ms)
    aggregation_bytes = pcm_chunk_size(sample_rate, chunk_ms)
    total_audio_ms = round((len(raw_pcm) / max(sample_rate * 2, 1)) * 1000, 1)
    sleep = sleep_fn or asyncio.sleep

    partial_latencies = []
    partial_audio_offsets_ms = []
    partial_end_to_end_ms = []
    partial_gap_ms: list[float] = []
    chunk_audio_offsets_ms: list[float] = []
    last_partial_visible_ms = 0.0
    last_recorded_partial_received_at: float | None = None
    last_partial_text = ""
    partial_texts: list[str] = []
    observed_partial_events = 0
    late_partial_events = 0
    pending_partial_started_at: dict[int, float] = {}
    recorded_partial_chunks: set[int] = set()
    chunk_count = 0
    source_audio_ms = 0.0

    def latest_recorded_chunk_index() -> int:
        return max(recorded_partial_chunks, default=0)

    def record_partial_event(
        event: TranscriptEvent,
        received_at: float,
        *,
        fallback_chunk_index: int,
    ) -> int | None:
        nonlocal last_partial_visible_ms, last_recorded_partial_received_at, last_partial_text, observed_partial_events

        chunk_index = getattr(event, "chunks_received", 0)
        if chunk_index < 1:
            chunk_index = fallback_chunk_index
        started_at = pending_partial_started_at.get(chunk_index)
        if started_at is None:
            return None

        if chunk_index < latest_recorded_chunk_index():
            return None

        last_partial_text = event.text
        partial_texts.append(last_partial_text)
        if chunk_index in recorded_partial_chunks:
            return None

        response_latency_ms = (received_at - started_at) * 1000
        audio_offset_ms = chunk_audio_offsets_ms[min(chunk_index - 1, len(chunk_audio_offsets_ms) - 1)]
        visible_elapsed_ms = max(audio_offset_ms, last_partial_visible_ms) + response_latency_ms
        visible_elapsed_ms = round(visible_elapsed_ms, 1)
        partial_latencies.append(response_latency_ms)
        partial_audio_offsets_ms.append(audio_offset_ms)
        partial_end_to_end_ms.append(visible_elapsed_ms)
        if last_recorded_partial_received_at is not None:
            partial_gap_ms.append(round((received_at - last_recorded_partial_received_at) * 1000, 1))
        last_partial_visible_ms = visible_elapsed_ms
        last_recorded_partial_received_at = received_at
        observed_partial_events += 1
        recorded_partial_chunks.add(chunk_index)
        return chunk_index

    async def recv_event_with_timeout(timeout: float) -> TranscriptEvent | None:
        payload = await client._recv_json_with_timeout(timeout)
        if payload is None:
            return None
        return TranscriptEvent.from_payload(payload)

    async def collect_partial_events(expected_chunk_index: int) -> None:
        nonlocal late_partial_events
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
            event_chunk_index = getattr(event, "chunks_received", 0)
            if event_chunk_index > 0 and event_chunk_index != expected_chunk_index:
                late_partial_events += 1
                if event_chunk_index > expected_chunk_index:
                    record_partial_event(event, received_at, fallback_chunk_index=event_chunk_index)
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
        stream_started_at = time.perf_counter()
        buffer = bytearray()
        for frame_index, frame in enumerate(source_frames, start=1):
            if simulate_realtime:
                target_elapsed_s = (frame_index * source_frame_ms) / 1000.0
                delay_s = target_elapsed_s - (time.perf_counter() - stream_started_at)
                if delay_s > 0:
                    await sleep(delay_s)
            buffer.extend(frame)
            source_audio_ms = min(round(source_audio_ms + source_frame_ms, 1), total_audio_ms)
            if len(buffer) < aggregation_bytes and frame_index != len(source_frames):
                continue

            chunk = bytes(buffer)
            buffer.clear()
            chunk_count += 1
            chunk_index = chunk_count
            chunk_audio_offsets_ms.append(source_audio_ms)
            started = time.perf_counter()
            sent_at: float | None = None

            def mark_sent() -> None:
                nonlocal sent_at
                sent_at = time.perf_counter()

            partial_event = await client.send_audio(
                chunk,
                response_timeout=partial_event_timeout_seconds,
                on_sent=mark_sent,
            )
            pending_partial_started_at[chunk_index] = started
            if frame_index == len(source_frames):
                audio_finished_at = sent_at if sent_at is not None else time.perf_counter()
            if chunk_index % partial_interval_chunks != 0:
                continue
            if partial_event is None:
                if hasattr(client, "_recv_json_with_timeout"):
                    await collect_partial_events(chunk_index)
                continue
            if partial_event.type != "partial":
                raise RuntimeError(f"Expected partial event, got: {partial_event.type}")
            event_chunk_index = getattr(partial_event, "chunks_received", 0)
            if event_chunk_index > 0 and event_chunk_index != chunk_index:
                late_partial_events += 1
            fallback_chunk_index = event_chunk_index if event_chunk_index > 0 else chunk_index
            record_partial_event(partial_event, time.perf_counter(), fallback_chunk_index=fallback_chunk_index)

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
                    fallback_chunk_index = event.chunks_received if event.chunks_received > 0 else chunk_count
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
    partial_churn = summarize_partial_churn(partial_texts)
    expected_partial_events = chunk_count // partial_interval_chunks
    return {
        "chunks": chunk_count,
        "chunk_ms": chunk_ms,
        "binary_frames": send_binary_frames,
        "transport": "pipecat-e2e",
        "source_frame_ms": source_frame_ms,
        "source_frame_count": len(source_frames),
        "simulate_realtime": simulate_realtime,
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
        "late_partial_events": late_partial_events,
        "late_partial_ratio": round(late_partial_events / observed_partial_events, 3) if observed_partial_events else None,
        "bridge": {
            "source_frame_ms": source_frame_ms,
            "source_frame_count": len(source_frames),
            "chunk_count": chunk_count,
            "aggregation_frame_count": max(int(round(chunk_ms / max(source_frame_ms, 1))), 1),
            "source_frames_dropped": 0,
            "simulate_realtime": simulate_realtime,
        },
        "final_event_received": final_event is not None and final_event.type == "final",
        "closeout_event_type": None if final_event is None else final_event.type,
        **partial_churn,
    }


async def run_v1_stt_stream_benchmark(
    ws_url: str,
    raw_pcm: bytes,
    sample_rate: int,
    chunk_ms: int,
    *,
    source_frame_ms: int = 20,
    partial_interval_ms: int = 100,
    partial_window_seconds: float | None = None,
    max_buffer_seconds: float | None = None,
    partial_event_timeout_seconds: float = 0.1,
    final_event_timeout_seconds: float = 10.0,
    simulate_realtime: bool = False,
    sleep_fn=None,
    connect_fn=None,
) -> dict[str, object]:
    source_frames = chunk_pcm(raw_pcm, sample_rate, source_frame_ms)
    aggregation_ms = max(chunk_ms, source_frame_ms)
    aggregation_bytes = pcm_chunk_size(sample_rate, aggregation_ms)
    partial_interval_chunks = max(int(round(partial_interval_ms / max(aggregation_ms, 1))), 1)
    total_audio_ms = round((len(raw_pcm) / max(sample_rate * 2, 1)) * 1000, 1)
    sleep = sleep_fn or asyncio.sleep
    late_partial_threshold_ms = float(max(partial_interval_ms, 100))

    partial_latencies: list[float] = []
    partial_audio_offsets_ms: list[float] = []
    partial_end_to_end_ms: list[float] = []
    partial_gap_ms: list[float] = []
    partial_texts: list[str] = []
    last_partial_text = ""
    chunk_audio_offsets_ms: list[float] = []
    last_partial_received_at: float | None = None
    chunk_count = 0
    source_audio_ms = 0.0
    late_partial_events = 0
    stream_started_at = 0.0
    next_expected_partial_audio_ms = float(partial_interval_ms)
    expected_partial_events = 0
    recorded_partial_revisions: set[int] = set()

    def expected_partial_for_audio_offset(audio_offset_ms: float) -> None:
        nonlocal expected_partial_events, next_expected_partial_audio_ms
        while audio_offset_ms + 0.5 >= next_expected_partial_audio_ms:
            expected_partial_events += 1
            next_expected_partial_audio_ms += float(partial_interval_ms)

    def record_partial_event(event: TranscriptEvent, received_at: float) -> bool:
        nonlocal last_partial_received_at, last_partial_text, late_partial_events

        if event.type != "partial":
            return False
        if event.revision is not None:
            if event.revision in recorded_partial_revisions:
                return False
            recorded_partial_revisions.add(event.revision)

        audio_offset_ms = float(event.audio_received_ms or 0)
        if audio_offset_ms <= 0 and chunk_audio_offsets_ms:
            audio_offset_ms = chunk_audio_offsets_ms[-1]
        audio_offset_ms = min(round(audio_offset_ms, 1), total_audio_ms)
        end_to_end_ms = round((received_at - stream_started_at) * 1000, 1)
        staleness_ms = max(round(end_to_end_ms - audio_offset_ms, 1), 0.0)
        if staleness_ms > late_partial_threshold_ms:
            late_partial_events += 1

        partial_latencies.append(staleness_ms)
        partial_audio_offsets_ms.append(audio_offset_ms)
        partial_end_to_end_ms.append(end_to_end_ms)
        partial_texts.append(event.text)
        last_partial_text = event.text
        if last_partial_received_at is not None:
            partial_gap_ms.append(round((received_at - last_partial_received_at) * 1000, 1))
        last_partial_received_at = received_at
        return True

    pending_terminal_event: tuple[TranscriptEvent, float] | None = None

    async def recv_event_with_timeout(timeout_seconds: float) -> TranscriptEvent | None:
        if hasattr(client, "recv_event"):
            return await client.recv_event(timeout=timeout_seconds, allow_error=True)
        payload = await client._recv_json_with_timeout(timeout_seconds, allow_error=True)
        if payload is None:
            return None
        return TranscriptEvent.from_payload(payload)

    async def collect_partial_events(timeout_seconds: float) -> None:
        nonlocal pending_terminal_event
        deadline = time.perf_counter() + timeout_seconds
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return
            event = await recv_event_with_timeout(remaining)
            if event is None:
                return
            received_at = time.perf_counter()
            if event.type == "partial":
                record_partial_event(event, received_at)
                continue
            if event.type == "error":
                continue
            pending_terminal_event = (event, received_at)
            return

    client = AsyncLocalSttClient(ws_url, connect_fn=connect_fn)
    ready_event = await client.start(
        language="en",
        sample_rate=sample_rate,
        partial_interval_ms=partial_interval_ms,
        partial_window_seconds=partial_window_seconds,
        max_buffer_seconds=max_buffer_seconds,
    )
    final_event = None
    audio_finished_at: float | None = None
    final_received_at = 0.0
    finalize_started_at = 0.0

    try:
        stream_started_at = time.perf_counter()
        buffer = bytearray()
        for frame_index, frame in enumerate(source_frames, start=1):
            if simulate_realtime:
                target_elapsed_s = (frame_index * source_frame_ms) / 1000.0
                delay_s = target_elapsed_s - (time.perf_counter() - stream_started_at)
                if delay_s > 0:
                    await sleep(delay_s)
            buffer.extend(frame)
            source_audio_ms = min(round(source_audio_ms + source_frame_ms, 1), total_audio_ms)
            if len(buffer) < aggregation_bytes and frame_index != len(source_frames):
                continue

            chunk = bytes(buffer)
            buffer.clear()
            chunk_count += 1
            chunk_audio_offsets_ms.append(source_audio_ms)
            sent_at: float | None = None

            def mark_sent() -> None:
                nonlocal sent_at
                sent_at = time.perf_counter()

            await client.send_audio(chunk, on_sent=mark_sent)
            expected_partial_for_audio_offset(source_audio_ms)
            if frame_index == len(source_frames):
                audio_finished_at = sent_at if sent_at is not None else time.perf_counter()
            await collect_partial_events(partial_event_timeout_seconds)

        finalize_started_at = time.perf_counter()
        await client.finalize()
        final_deadline = time.perf_counter() + final_event_timeout_seconds
        while time.perf_counter() < final_deadline:
            if pending_terminal_event is not None:
                event, received_at = pending_terminal_event
                pending_terminal_event = None
            else:
                event = await recv_event_with_timeout(max(0.0, final_deadline - time.perf_counter()))
                if event is None:
                    break
                received_at = time.perf_counter()
            if event.type == "partial":
                record_partial_event(event, received_at)
                continue
            if event.type == "error":
                continue
            final_event = event
            if event.type == "final":
                final_received_at = received_at
            break
    finally:
        await client.close(graceful=False)

    if final_event is None:
        final_event = TranscriptEvent.from_payload({"type": "final", "text": "", "is_final": True, "chunks_received": chunk_count})
        final_received_at = time.perf_counter()

    final_ms = (final_received_at - finalize_started_at) * 1000
    time_to_final_from_audio_end_ms = (final_received_at - (audio_finished_at or stream_started_at)) * 1000
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
    partial_churn = summarize_partial_churn(partial_texts)
    return {
        "chunks": chunk_count,
        "chunk_ms": aggregation_ms,
        "binary_frames": True,
        "transport": "v1-stt-stream",
        "aggregation_ms": aggregation_ms,
        "source_frame_ms": source_frame_ms,
        "source_frame_count": len(source_frames),
        "simulate_realtime": simulate_realtime,
        "aggregation_frame_count": max(int(round(aggregation_ms / max(source_frame_ms, 1))), 1),
        "partial_interval_ms": partial_interval_ms,
        "partial_interval_chunks": partial_interval_chunks,
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
        "observed_partial_events": len(partial_latencies),
        "missing_partial_events": max(expected_partial_events - len(partial_latencies), 0),
        "late_partial_events": late_partial_events,
        "late_partial_ratio": round(late_partial_events / len(partial_latencies), 3) if partial_latencies else None,
        "final_event_received": final_event is not None and final_event.type == "final",
        "closeout_event_type": final_event.type if final_event is not None else None,
        **partial_churn,
        "bridge": {
            "protocol": "local-stt-v1",
            "path": "/v1/stt/stream",
            "source_frame_ms": source_frame_ms,
            "source_frame_count": len(source_frames),
            "chunk_count": chunk_count,
            "aggregation_frame_count": max(int(round(aggregation_ms / max(source_frame_ms, 1))), 1),
            "chunk_ms": aggregation_ms,
            "partial_interval_ms": partial_interval_ms,
            "simulate_realtime": simulate_realtime,
        },
    }


async def async_main(args: argparse.Namespace) -> dict[str, object]:
    audio_path = benchmark_audio_path(args)
    synthesized = audio_path != args.audio_file if args.audio_file else audio_path != FIXTURE_PATH
    reference_text = resolve_reference_text(args, synthesized=synthesized)
    samples, source_sample_rate = load_audio(audio_path)
    sample_rate = BENCHMARK_SAMPLE_RATE
    samples = resample_audio(samples, source_sample_rate, sample_rate)
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
        preload_model=args.preload_model,
    ) if args.spawn_server else None
    process_rss_monitor: ProcessPeakRSSMonitor | None = None

    try:
        if server is not None:
            server.start()
            await server.wait_ready()
            if server.process is not None:
                process_rss_monitor = ProcessPeakRSSMonitor(server.process.pid)
                process_rss_monitor.start()
        service = await fetch_service_metadata(args.url)
        preload_enabled = service_preload_enabled(service)
        require_preloaded_service = args.require_preloaded_service
        if server is not None and not args.preload_model:
            require_preloaded_service = False
        if require_preloaded_service and preload_enabled is not True:
            raise RuntimeError(
                "Benchmark target must report preload_enabled=true. Restart the service with ASR_PRELOAD_MODEL=true "
                "or rerun with --allow-unpreloaded-service if you intentionally want a cold-path measurement."
            )
        if server is not None and args.preload_model and preload_enabled is not True:
            raise RuntimeError(
                "Managed benchmark server did not report preload_enabled=true after startup. "
                "This run would not be comparable to the warmed benchmark lanes."
            )

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
        late_partial_events_all: list[int] = []
        partial_churn_char_all: list[float] = []
        partial_churn_word_all: list[float] = []
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
                    simulate_realtime=args.simulate_realtime,
                )
            elif args.mode == "v1-stt-stream":
                ws = await run_v1_stt_stream_benchmark(
                    args.v1_ws_url,
                    raw_pcm,
                    sample_rate,
                    args.v1_aggregation_ms,
                    source_frame_ms=args.v1_source_frame_ms,
                    partial_interval_ms=args.v1_partial_interval_ms,
                    partial_window_seconds=args.partial_window,
                    max_buffer_seconds=args.max_buffer,
                    partial_event_timeout_seconds=args.partial_event_timeout,
                    final_event_timeout_seconds=args.final_event_timeout,
                    simulate_realtime=args.simulate_realtime,
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
            late_partial_events_all.append(int(ws.get("late_partial_events", 0)))
            if ws.get("partial_transcript_churn_char_mean") is not None:
                partial_churn_char_all.append(float(ws["partial_transcript_churn_char_mean"]))
            if ws.get("partial_transcript_churn_word_mean") is not None:
                partial_churn_word_all.append(float(ws["partial_transcript_churn_word_mean"]))
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
                "partial_interval_chunks": ws.get("partial_interval_chunks"),
                "binary_frames": ws["binary_frames"],
                "simulate_realtime": ws.get("simulate_realtime"),
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
                "late_partial_events": ws.get("late_partial_events"),
                "late_partial_ratio": ws.get("late_partial_ratio"),
                "partial_revision_count": ws.get("partial_revision_count"),
                "partial_transcript_churn_char_mean": ws.get("partial_transcript_churn_char_mean"),
                "partial_transcript_churn_char_p95": ws.get("partial_transcript_churn_char_p95"),
                "partial_transcript_churn_word_mean": ws.get("partial_transcript_churn_word_mean"),
                "partial_transcript_churn_word_p95": ws.get("partial_transcript_churn_word_p95"),
                "bridge": ws.get("bridge"),
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
        stop_to_final_summary = summarize_latencies(final_latencies_all)
        live_streaming_metrics_comparable = args.mode == "v1-stt-stream" and getattr(args, "simulate_realtime", False)
        partial_churn_char_summary = summarize_ratio_series(partial_churn_char_all) if partial_churn_char_all else None
        partial_churn_word_summary = summarize_ratio_series(partial_churn_word_all) if partial_churn_word_all else None
        source_frame_mode = args.mode in {"pipecat-e2e", "v1-stt-stream"}
        first_streaming_sample = streaming_samples[0] if streaming_samples else None
        stream_chunk_ms = (
            first_streaming_sample.get("chunk_ms", first_streaming_sample.get("aggregation_ms", args.v1_aggregation_ms))
            if args.mode == "v1-stt-stream" and first_streaming_sample is not None
            else args.v1_aggregation_ms if args.mode == "v1-stt-stream"
            else args.chunk_ms
        )
        stream_aggregation_ms = (
            first_streaming_sample.get("aggregation_ms", stream_chunk_ms)
            if args.mode == "v1-stt-stream" and first_streaming_sample is not None
            else args.v1_aggregation_ms if args.mode == "v1-stt-stream"
            else None
        )
        stream_source_frame_ms = (
            args.pipecat_source_frame_ms if args.mode == "pipecat-e2e"
            else args.v1_source_frame_ms if args.mode == "v1-stt-stream"
            else None
        )
        stream_binary_frames = True if args.mode == "v1-stt-stream" else args.binary_frames
        stream_simulate_realtime = args.simulate_realtime if source_frame_mode else None
        stream_partial_interval_chunks = (
            streaming_samples[0].get("partial_interval_chunks")
            if streaming_samples and args.mode == "v1-stt-stream"
            else args.partial_interval_chunks
        )

        peak_rss_mb = None
        cpu_utilization_percent = None
        if process_rss_monitor is not None:
            process_rss_monitor.stop()
            peak_rss_mb = process_rss_monitor.peak_rss_mb
            cpu_utilization_percent = process_rss_monitor.cpu_utilization_percent

        return {
            "environment": describe_environment(
                service_pid=server.process.pid if server is not None and server.process is not None else None,
                peak_rss_mb=peak_rss_mb,
                cpu_utilization_percent=cpu_utilization_percent,
                package_power_watts=getattr(args, "package_power_watts", None),
                thermal_state=getattr(args, "thermal_state", None),
            ),
            "benchmark": {
                "sample_count": sample_count,
                "mode": args.mode,
                "rest_runs_per_sample": args.rest_runs,
                "chunk_ms": stream_chunk_ms,
                "partial_interval_chunks": stream_partial_interval_chunks,
                "binary_frames": stream_binary_frames,
                "source_frame_ms": stream_source_frame_ms,
                "simulate_realtime": stream_simulate_realtime,
                "partial_window_seconds": args.partial_window,
                "max_buffer_seconds": args.max_buffer,
                "partial_event_timeout_seconds": args.partial_event_timeout,
                "partial_interval_ms": args.v1_partial_interval_ms if args.mode == "v1-stt-stream" else None,
                "request_retries": args.request_retries,
                "request_retry_delay": args.request_retry_delay,
                "pipecat_source_frame_ms": args.pipecat_source_frame_ms if args.mode == "pipecat-e2e" else None,
                "v1_source_frame_ms": args.v1_source_frame_ms if args.mode == "v1-stt-stream" else None,
                "v1_aggregation_ms": stream_aggregation_ms,
                "v1_partial_interval_ms": args.v1_partial_interval_ms if args.mode == "v1-stt-stream" else None,
                "preload_model": args.preload_model,
                "require_preloaded_service": args.require_preloaded_service,
                "spawn_server": args.spawn_server,
            },
            "integration": {
                "name": "pipecat" if args.mode == "pipecat-e2e" else "local-stt-v1",
                "protocol": "local-stt-v1" if args.mode == "v1-stt-stream" else None,
                "path": "/v1/stt/stream" if args.mode == "v1-stt-stream" else None,
                "transport": args.mode,
                "source_frame_ms": stream_source_frame_ms,
                "bridge_chunk_ms": stream_chunk_ms,
                "partial_interval_ms": args.v1_partial_interval_ms if args.mode == "v1-stt-stream" else None,
                "send_binary_frames": stream_binary_frames,
                "simulate_realtime": stream_simulate_realtime,
            } if source_frame_mode else None,
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
                "chunk_ms": stream_chunk_ms,
                "aggregation_ms": stream_aggregation_ms,
                "partial_interval_chunks": stream_partial_interval_chunks,
                "partial_interval_ms": args.v1_partial_interval_ms if args.mode == "v1-stt-stream" else None,
                "binary_frames": stream_binary_frames,
                "source_frame_ms": stream_source_frame_ms,
                "simulate_realtime": stream_simulate_realtime,
                "partial_window_seconds": args.partial_window,
                "max_buffer_seconds": args.max_buffer,
                "partial_event_timeout_seconds": args.partial_event_timeout,
                "request_retries": args.request_retries,
                "request_retry_delay": args.request_retry_delay,
                "live_metrics_comparable": live_streaming_metrics_comparable,
                "partial_latencies_ms": [round(value, 1) for value in partial_latencies_all],
                "first_partial_end_to_end_latencies_ms": [round(value, 1) for value in first_partial_end_to_end_all],
                "partial_gap_latencies_ms": [round(value, 1) for value in partial_gap_all],
                "final_latencies_ms": [round(value, 1) for value in finalization_latencies_all],
                "stop_to_final_latencies_ms": [round(value, 1) for value in final_latencies_all],
                "binary_frames": stream_binary_frames,
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

                "stop_to_final_mean_ms": stop_to_final_summary["mean_ms"],
                "stop_to_final_p90_ms": stop_to_final_summary["p90_ms"],
                "stop_to_final_p95_ms": stop_to_final_summary["p95_ms"],
                "stop_to_final_min_ms": stop_to_final_summary["min_ms"],
                "stop_to_final_max_ms": stop_to_final_summary["max_ms"],
                "ready": streaming_samples[0]["ready"] if streaming_samples else None,
                "last_partial": streaming_samples[0]["last_partial"] if streaming_samples else "",
                "final_transcript": streaming_samples[0]["final_transcript"] if streaming_samples else "",
                "expected_partial_events": sum(int(sample.get("expected_partial_events", 0)) for sample in streaming_samples),
                "observed_partial_events": sum(int(sample.get("observed_partial_events", 0)) for sample in streaming_samples),
                "missing_partial_events": sum(missing_partial_events_all),
                "late_partial_events": sum(late_partial_events_all),
                "late_partial_ratio": round(sum(late_partial_events_all) / sum(int(sample.get("observed_partial_events", 0)) for sample in streaming_samples), 3) if sum(int(sample.get("observed_partial_events", 0)) for sample in streaming_samples) else None,
                "partial_revision_count": sum(int(sample.get("partial_revision_count", 0)) for sample in streaming_samples),
                "partial_transcript_churn_char_mean": partial_churn_char_summary["mean"] if partial_churn_char_summary else None,
                "partial_transcript_churn_char_p95": partial_churn_char_summary["p95"] if partial_churn_char_summary else None,
                "partial_transcript_churn_word_mean": partial_churn_word_summary["mean"] if partial_churn_word_summary else None,
                "partial_transcript_churn_word_p95": partial_churn_word_summary["p95"] if partial_churn_word_summary else None,
                "bridge": streaming_samples[0].get("bridge") if streaming_samples and source_frame_mode else None,
                "final_event_received_count": final_event_received_count,
                "closeout_event_types": closeout_event_types,
                "accuracy": summarize_accuracy(streaming_accuracy_samples),
            },
        }
    finally:
        if process_rss_monitor is not None:
            process_rss_monitor.stop()
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
