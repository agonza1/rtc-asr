from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import os
import platform
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

DEFAULT_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a realtime ASR latency benchmark for the rtc asr service."
)
ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "smoke.wav"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark the realtime ASR service")
    parser.add_argument("--url", default="http://127.0.0.1:8090", help="Base URL for the ASR service")
    parser.add_argument("--ws-url", default="ws://127.0.0.1:8090/ws/stream", help="WebSocket URL for streaming")
    parser.add_argument("--audio-file", type=Path, help="Optional audio file to benchmark instead of synthesized speech")
    parser.add_argument("--speech-text", default=DEFAULT_TEXT, help="Speech text used when synthesizing a local benchmark clip")
    parser.add_argument("--spawn-server", action="store_true", help="Start a local uvicorn server for the benchmark run")
    parser.add_argument("--rest-runs", type=int, default=5, help="Number of REST runs")
    parser.add_argument("--chunk-ms", type=int, default=250, help="Streaming chunk duration in milliseconds")
    parser.add_argument("--partial-interval-chunks", type=int, default=1, help="Streaming partial cadence in chunks")
    parser.add_argument("--binary-frames", action="store_true", help="Send raw PCM bytes over websocket instead of JSON base64 frames")
    parser.add_argument("--model", default="tiny.en", help="Model name when spawning a local server")
    parser.add_argument("--partial-window", type=float, default=2.0, help="Partial transcription window in seconds when spawning a local server")
    parser.add_argument("--max-buffer", type=float, help="Optional stream buffer cap in seconds for websocket benchmarking")
    return parser.parse_args()


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


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


def describe_environment() -> dict[str, object]:
    return {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor() or platform.machine(),
    }


class ManagedServer:
    def __init__(self, url: str, model: str, partial_window: float) -> None:
        self.url = url
        self.model = model
        self.partial_window = partial_window
        self.process: subprocess.Popen[str] | None = None

    def start(self) -> None:
        env = os.environ.copy()
        env.setdefault("ASR_MODEL_SIZE", self.model)
        env.setdefault("ASR_PRELOAD_MODEL", "true")
        env.setdefault("ASR_STREAM_PARTIAL_WINDOW_SECONDS", str(self.partial_window))
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


async def run_rest_benchmark(base_url: str, wav_bytes: bytes, sample_rate: int, runs: int, duration_s: float) -> dict[str, object]:
    payload = {
        "audio_data": base64.b64encode(wav_bytes).decode("ascii"),
        "language": "en",
        "sample_rate": sample_rate,
    }
    durations = []
    transcription = ""
    async with httpx.AsyncClient(base_url=base_url, timeout=120) as client:
        warmup = await client.post("/api/transcribe", json=payload)
        warmup.raise_for_status()
        transcription = warmup.json().get("text", "")
        for _ in range(runs):
            started = time.perf_counter()
            response = await client.post("/api/transcribe", json=payload)
            elapsed_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            durations.append(elapsed_ms)
            transcription = response.json().get("text", "")
    return {
        "runs": runs,
        "mean_ms": round(statistics.mean(durations), 1),
        "p95_ms": round(percentile(durations, 0.95), 1),
        "min_ms": round(min(durations), 1),
        "max_ms": round(max(durations), 1),
        "rtf_mean": round(statistics.mean(durations) / (duration_s * 1000), 3),
        "transcript": transcription,
    }


def _connect_websocket(ws_url: str):
    return websockets.connect(ws_url, max_size=2**23)


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
    connect_fn=None,
) -> dict[str, object]:
    chunk_size = max(int(sample_rate * 2 * chunk_ms / 1000), 2)
    if chunk_size % 2:
        chunk_size += 1
    chunks = [raw_pcm[index:index + chunk_size] for index in range(0, len(raw_pcm), chunk_size)]
    partial_latencies = []
    partial_text = ""
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
            if chunk_index % partial_interval_chunks != 0:
                continue
            event = json.loads(await websocket.recv())
            partial_latencies.append((time.perf_counter() - started) * 1000)
            partial_text = event.get("text", "")
        started = time.perf_counter()
        await websocket.send(json.dumps({"type": "stop"}))
        final_event = json.loads(await websocket.recv())
        final_ms = (time.perf_counter() - started) * 1000
    partial_summary = {
        "partial_mean_ms": round(statistics.mean(partial_latencies), 1) if partial_latencies else None,
        "partial_p95_ms": round(percentile(partial_latencies, 0.95), 1) if partial_latencies else None,
        "partial_first_ms": round(partial_latencies[0], 1) if partial_latencies else None,
        "partial_last_ms": round(partial_latencies[-1], 1) if partial_latencies else None,
    }
    return {
        "chunks": len(chunks),
        "chunk_ms": chunk_ms,
        "binary_frames": send_binary_frames,
        **partial_summary,
        "final_ms": round(final_ms, 1),
        "ready": ready_event,
        "last_partial": partial_text,
        "final_transcript": final_event.get("text", ""),
    }


async def async_main(args: argparse.Namespace) -> dict[str, object]:
    audio_path = benchmark_audio_path(args)
    synthesized = audio_path != args.audio_file if args.audio_file else audio_path != FIXTURE_PATH
    samples, sample_rate = load_audio(audio_path)
    wav_bytes = make_wav_bytes(samples, sample_rate)
    raw_pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    duration_s = len(samples) / sample_rate
    server = ManagedServer(args.url, args.model, args.partial_window) if args.spawn_server else None

    try:
        if server is not None:
            server.start()
            await server.wait_ready()
        rest = await run_rest_benchmark(args.url, wav_bytes, sample_rate, args.rest_runs, duration_s)
        ws = await run_ws_benchmark(
            args.ws_url,
            raw_pcm,
            sample_rate,
            args.chunk_ms,
            partial_interval_chunks=args.partial_interval_chunks,
            send_binary_frames=args.binary_frames,
            partial_window_seconds=args.partial_window,
            max_buffer_seconds=args.max_buffer,
        )
        return {
            "environment": describe_environment(),
            "audio": {
                "path": str(audio_path),
                "duration_s": round(duration_s, 3),
                "sample_rate": sample_rate,
                "synthesized": synthesized,
            },
            "rest": rest,
            "streaming": ws,
        }
    finally:
        if server is not None:
            server.stop()
        if audio_path != FIXTURE_PATH and (args.audio_file is None or audio_path != args.audio_file):
            audio_path.unlink(missing_ok=True)


def main() -> None:
    args = parse_args()
    results = asyncio.run(async_main(args))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
