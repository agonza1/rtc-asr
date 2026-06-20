from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import time
import wave
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
import sys
from typing import Any, Callable, Iterator, Protocol

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.protocols import HOT_PATH_BYTES_PER_FRAME, HOT_PATH_FRAME_MS, HOT_PATH_SAMPLE_RATE
from src.rtc_client import AsyncLocalSttClient, TranscriptEvent


class LocalSttClient(Protocol):
    async def start(self, **kwargs: Any) -> dict[str, Any]: ...
    async def send_audio(self, chunk: bytes) -> None: ...
    async def finalize(self) -> None: ...
    async def recv_event(self, *, timeout: float | None = None, allow_error: bool = True) -> TranscriptEvent | None: ...
    async def close(self, *, graceful: bool = True) -> dict[str, Any] | None: ...


ClientFactory = Callable[[str], LocalSttClient]


@dataclass(slots=True)
class AudioInput:
    source: str
    sample_rate: int
    frame_ms: int
    frames: list[bytes]


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Local STT v1 websocket latency")
    parser.add_argument("--url", default="ws://localhost:8080/v1/stt/stream")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-wav", type=Path)
    source.add_argument("--input-raw-pcm", type=Path)
    parser.add_argument("--sample-rate", type=positive_int, default=HOT_PATH_SAMPLE_RATE)
    parser.add_argument("--frame-ms", type=positive_int, default=HOT_PATH_FRAME_MS)
    parser.add_argument("--partial-interval-ms", type=positive_int, default=100)
    parser.add_argument("--runs", type=positive_int, default=3)
    parser.add_argument(
        "--receive-timeout-seconds",
        type=positive_int,
        default=5,
        help="Seconds to wait for a final transcript after finalize",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--no-realtime-pace", action="store_true", help="Send frames without sleeping between frames")
    return parser.parse_args(argv)


def load_audio_input(*, input_wav: Path | None, input_raw_pcm: Path | None, sample_rate: int, frame_ms: int) -> AudioInput:
    if input_wav is None and input_raw_pcm is None:
        raise ValueError("input_wav or input_raw_pcm is required")

    if input_wav is not None:
        pcm_bytes, resolved_rate = _read_pcm16_mono_wav(input_wav)
        source = str(input_wav)
    else:
        assert input_raw_pcm is not None
        pcm_bytes = input_raw_pcm.read_bytes()
        resolved_rate = sample_rate
        source = str(input_raw_pcm)

    frames = split_pcm_frames(pcm_bytes, sample_rate=resolved_rate, frame_ms=frame_ms)
    return AudioInput(source=source, sample_rate=resolved_rate, frame_ms=frame_ms, frames=frames)


def split_pcm_frames(pcm_bytes: bytes, *, sample_rate: int, frame_ms: int) -> list[bytes]:
    bytes_per_frame = sample_rate * frame_ms * 2 // 1000
    if bytes_per_frame <= 0 or sample_rate * frame_ms * 2 % 1000 != 0:
        raise ValueError("sample_rate and frame_ms must resolve to a whole PCM16 frame byte count")
    return [pcm_bytes[index : index + bytes_per_frame] for index in range(0, len(pcm_bytes), bytes_per_frame) if pcm_bytes[index : index + bytes_per_frame]]


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return round(ordered[index], 1)


def summarize_percentile(metric: str, values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    precision = 3 if metric.endswith("_rtf") else 1
    return round(ordered[index], precision)


def summarize_samples(samples: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    keys = [
        "time_to_first_interim_ms",
        "time_to_final_after_finalize_ms",
        "audio_end_finalization_rtf",
        "audio_send_duration_ms",
        "send_receive_overlap_ms",
        "audio_send_queue_depth_p95_ms",
        "audio_send_latency_p95_ms",
        "partial_cadence_p95_ms",
        "pcm16_normalization_p95_ms",
        "asr_receive_loop_append_p95_ms",
        "asr_queue_delay_p95_ms",
        "asr_decode_p95_ms",
        "websocket_roundtrip_p95_ms",
        "warnings_received",
        "audio_frames_sent",
        "audio_frames_dropped",
        "interim_events_received",
        "interim_transcript_changes",
        "final_events_received",
        "reconnects",
        "protocol_errors",
    ]
    summary: dict[str, dict[str, float]] = {}
    for key in keys:
        values = [float(sample[key]) for sample in samples if sample.get(key) is not None]
        summary[key] = {
            "p50": summarize_percentile(key, values, 0.50),
            "p95": summarize_percentile(key, values, 0.95),
            "p99": summarize_percentile(key, values, 0.99),
        }
    return summary


def describe_environment() -> dict[str, Any]:
    return {
        "date_utc": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "processor": platform.processor() or platform.machine(),
        "machine": platform.machine(),
        "cpu_logical_cores": os.cpu_count(),
    }


async def run_benchmark(
    *,
    url: str,
    audio: AudioInput,
    partial_interval_ms: int,
    runs: int,
    realtime_pace: bool = True,
    receive_timeout_seconds: int = 5,
    client_factory: ClientFactory | None = None,
) -> dict[str, Any]:
    factory = client_factory or (lambda ws_url: AsyncLocalSttClient(ws_url))
    samples = []
    for index in range(1, runs + 1):
        samples.append(
            await _run_once(
                index=index,
                url=url,
                audio=audio,
                partial_interval_ms=partial_interval_ms,
                realtime_pace=realtime_pace,
                receive_timeout_seconds=receive_timeout_seconds,
                client_factory=factory,
            )
        )

    return {
        "kind": "local-stt-v1-latency-benchmark",
        "protocol": "local-stt.v1",
        "target": {"url": url},
        "environment": describe_environment(),
        "audio": {
            "source": audio.source,
            "sample_rate": audio.sample_rate,
            "frame_ms": audio.frame_ms,
            "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME if audio.sample_rate == HOT_PATH_SAMPLE_RATE and audio.frame_ms == HOT_PATH_FRAME_MS else len(audio.frames[0]) if audio.frames else 0,
            "frames": len(audio.frames),
            "duration_ms": len(audio.frames) * audio.frame_ms,
        },
        "settings": {
            "partial_interval_ms": partial_interval_ms,
            "receive_timeout_seconds": receive_timeout_seconds,
            "realtime_pace": realtime_pace,
        },
        "runs": runs,
        "samples": samples,
        "summary": summarize_samples(samples),
    }


async def _run_once(
    *,
    index: int,
    url: str,
    audio: AudioInput,
    partial_interval_ms: int,
    realtime_pace: bool,
    receive_timeout_seconds: int,
    client_factory: ClientFactory,
) -> dict[str, Any]:
    client = client_factory(url)
    first_audio_sent_at: float | None = None
    first_interim_ms: float | None = None
    final_requested_at: float | None = None
    final_after_finalize_ms: float | None = None
    interim_events = 0
    final_events = 0
    interim_transcript_changes = 0
    interim_received_at: list[float] = []
    first_event_received_at: float | None = None
    last_event_received_at: float | None = None
    previous_interim_text: str | None = None
    final_transcript: str | None = None
    protocol_errors = 0
    warnings_received = 0
    warning_codes: list[str] = []
    reconnects = 0
    send_latencies: list[float] = []
    receive_latencies: list[float] = []
    audio_send_started_at: float | None = None
    audio_send_completed_at: float | None = None
    pcm16_normalization_latencies = measure_pcm16_normalization_latencies(
        audio.frames,
        frame_ms=audio.frame_ms,
        partial_interval_ms=partial_interval_ms,
    )

    await client.start(sample_rate=audio.sample_rate, partial_interval_ms=partial_interval_ms)
    receive_done = asyncio.Event()

    async def receive_loop() -> None:
        nonlocal first_interim_ms, final_after_finalize_ms, interim_events, final_events, interim_transcript_changes, previous_interim_text, final_transcript, protocol_errors, warnings_received, first_event_received_at, last_event_received_at
        while not receive_done.is_set():
            wait_started = time.perf_counter()
            event = await client.recv_event(timeout=0.05, allow_error=True)
            if event is None:
                continue
            event_received_at = time.perf_counter()
            if first_event_received_at is None:
                first_event_received_at = event_received_at
            last_event_received_at = event_received_at
            receive_latencies.append((event_received_at - wait_started) * 1000)
            if event.type == "error":
                protocol_errors += 1
                receive_done.set()
                return
            if event.type == "warning":
                warnings_received += 1
                if isinstance(event.raw, dict) and isinstance(event.raw.get("code"), str):
                    warning_codes.append(event.raw["code"])
                continue
            if event.type == "partial":
                interim_received_at.append(time.perf_counter())
                interim_events += 1
                if previous_interim_text is not None and event.text != previous_interim_text:
                    interim_transcript_changes += 1
                previous_interim_text = event.text
                if first_interim_ms is None and first_audio_sent_at is not None:
                    first_interim_ms = (time.perf_counter() - first_audio_sent_at) * 1000
            if event.is_final or event.type == "final":
                final_events += 1
                final_transcript = event.text
                if final_requested_at is not None:
                    final_after_finalize_ms = (time.perf_counter() - final_requested_at) * 1000
                receive_done.set()
                return

    receive_task = asyncio.create_task(receive_loop())
    frames_sent = 0
    try:
        for frame in audio.frames:
            if audio_send_started_at is None:
                audio_send_started_at = time.perf_counter()
            if first_audio_sent_at is None:
                first_audio_sent_at = time.perf_counter()
            send_started = time.perf_counter()
            await client.send_audio(frame)
            send_latencies.append((time.perf_counter() - send_started) * 1000)
            frames_sent += 1
            if realtime_pace:
                await asyncio.sleep(audio.frame_ms / 1000)
        if audio_send_started_at is not None:
            audio_send_completed_at = time.perf_counter()

        final_requested_at = time.perf_counter()
        await client.finalize()
        try:
            await asyncio.wait_for(receive_done.wait(), timeout=receive_timeout_seconds)
        except TimeoutError:
            protocol_errors += 1
    finally:
        receive_done.set()
        await receive_task
        await client.close(graceful=False)

    send_p95 = percentile(send_latencies, 0.95)
    receive_p95 = percentile(receive_latencies, 0.95)
    partial_cadences = [
        (received_at - previous_received_at) * 1000
        for previous_received_at, received_at in zip(interim_received_at, interim_received_at[1:])
    ]
    return {
        "index": index,
        "time_to_first_interim_ms": _rounded_or_none(first_interim_ms),
        "time_to_final_after_finalize_ms": _rounded_or_none(final_after_finalize_ms),
        "audio_end_finalization_rtf": compute_audio_end_finalization_rtf(final_after_finalize_ms, audio),
        "audio_send_duration_ms": _rounded_or_none(
            None
            if audio_send_started_at is None or audio_send_completed_at is None
            else (audio_send_completed_at - audio_send_started_at) * 1000
        ),
        "send_receive_overlap_ms": _rounded_or_none(
            compute_overlap_ms(
                audio_send_started_at,
                audio_send_completed_at,
                first_event_received_at,
                last_event_received_at,
            )
        ),
        "audio_send_queue_depth_p95_ms": None,
        "audio_send_latency_p95_ms": send_p95,
        "partial_cadence_p95_ms": percentile(partial_cadences, 0.95),
        "pcm16_normalization_p95_ms": percentile(pcm16_normalization_latencies, 0.95),
        "asr_receive_loop_append_p95_ms": receive_p95,
        "asr_queue_delay_p95_ms": None,
        "asr_decode_p95_ms": None,
        "websocket_roundtrip_p95_ms": receive_p95,
        "audio_frames_sent": frames_sent,
        "audio_frames_dropped": max(0, len(audio.frames) - frames_sent),
        "interim_events_received": interim_events,
        "interim_transcript_changes": interim_transcript_changes,
        "final_events_received": final_events,
        "final_transcript": final_transcript,
        "warnings_received": warnings_received,
        "warning_codes": warning_codes,
        "reconnects": reconnects,
        "protocol_errors": protocol_errors,
    }


def normalize_pcm16_buffer(audio_data: bytes) -> np.ndarray:
    if len(audio_data) % 2 != 0:
        raise ValueError("Raw PCM16 audio must contain an even number of bytes")
    return np.frombuffer(audio_data, dtype="<i2").astype(np.float32) / 32768.0


def iter_server_decode_buffers(frames: list[bytes], *, frame_ms: int, partial_interval_ms: int) -> Iterator[bytes]:
    accumulated = bytearray()
    partial_elapsed_ms = 0
    last_emitted_length = 0
    for frame in frames:
        accumulated.extend(frame)
        partial_elapsed_ms += frame_ms
        if partial_elapsed_ms >= partial_interval_ms:
            yield bytes(accumulated)
            last_emitted_length = len(accumulated)
            partial_elapsed_ms = 0

    if accumulated and last_emitted_length != len(accumulated):
        yield bytes(accumulated)


def measure_pcm16_normalization_latencies(frames: list[bytes], *, frame_ms: int, partial_interval_ms: int) -> list[float]:
    latencies = []
    for audio_data in iter_server_decode_buffers(frames, frame_ms=frame_ms, partial_interval_ms=partial_interval_ms):
        started_at = time.perf_counter()
        normalize_pcm16_buffer(audio_data)
        latencies.append((time.perf_counter() - started_at) * 1000)
    return latencies


def compute_overlap_ms(
    send_started_at: float | None,
    send_completed_at: float | None,
    receive_started_at: float | None,
    receive_completed_at: float | None,
) -> float | None:
    if None in (send_started_at, send_completed_at, receive_started_at, receive_completed_at):
        return None
    assert send_started_at is not None
    assert send_completed_at is not None
    assert receive_started_at is not None
    assert receive_completed_at is not None
    overlap_started_at = max(send_started_at, receive_started_at)
    overlap_completed_at = min(send_completed_at, receive_completed_at)
    return max(0.0, (overlap_completed_at - overlap_started_at) * 1000)


def compute_audio_end_finalization_rtf(final_after_finalize_ms: float | None, audio: AudioInput) -> float | None:
    if final_after_finalize_ms is None or not audio.frames:
        return None
    audio_duration_ms = len(audio.frames) * audio.frame_ms
    if audio_duration_ms <= 0:
        return None
    return round(final_after_finalize_ms / audio_duration_ms, 3)


def _read_pcm16_mono_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        if channels != 1 or sample_width != 2:
            raise ValueError("input WAV must be mono PCM16")
        return wav_file.readframes(wav_file.getnframes()), sample_rate


def _rounded_or_none(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def print_summary(payload: dict[str, Any]) -> None:
    for metric, values in payload["summary"].items():
        print(
            f"{metric}: "
            f"p50={_format_summary_value(metric, values['p50'])} "
            f"p95={_format_summary_value(metric, values['p95'])} "
            f"p99={_format_summary_value(metric, values['p99'])}"
        )


def _format_summary_value(metric: str, value: float | None) -> str:
    if (
        metric.endswith("_received")
        or metric.endswith("_events")
        or metric.endswith("_errors")
        or metric.endswith("_sent")
        or metric.endswith("_dropped")
        or metric.endswith("_changes")
        or metric == "reconnects"
    ):
        return "n/a" if value is None else str(value)
    if metric.endswith("_rtf"):
        return "n/a" if value is None else str(value)
    return _format_ms(value)


def _format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value}ms"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audio = load_audio_input(input_wav=args.input_wav, input_raw_pcm=args.input_raw_pcm, sample_rate=args.sample_rate, frame_ms=args.frame_ms)
    payload = asyncio.run(
        run_benchmark(
            url=args.url,
            audio=audio,
            partial_interval_ms=args.partial_interval_ms,
            runs=args.runs,
            receive_timeout_seconds=args.receive_timeout_seconds,
            realtime_pace=not args.no_realtime_pace,
        )
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
