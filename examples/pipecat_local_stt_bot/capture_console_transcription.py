from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.protocols import HOT_PATH_FRAME_MS, HOT_PATH_SAMPLE_RATE
from src.rtc_client import AsyncLocalSttClient, TranscriptEvent


DEFAULT_WAV = ROOT / "tests" / "fixtures" / "smoke.wav"
DEFAULT_OUTPUT = ROOT / "artifacts" / "pipecat_local_stt_bot" / "console-transcription-30s.log"
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class AudioFrames:
    source: Path
    sample_rate: int
    frame_ms: int
    frames: list[bytes]

    @property
    def duration_seconds(self) -> float:
        return len(self.frames) * self.frame_ms / 1000


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture about 30 seconds of readable Local STT console transcript events."
    )
    parser.add_argument("--url", default=os.getenv("RTC_ASR_WS_URL", "ws://127.0.0.1:8080/v1/stt/stream"))
    parser.add_argument("--input-wav", type=Path, default=DEFAULT_WAV)
    parser.add_argument("--duration-seconds", type=float, default=30.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--language", default=os.getenv("LOCAL_STT_LANGUAGE", "en"))
    parser.add_argument("--partial-interval-ms", type=int, default=100)
    parser.add_argument("--partial-window-seconds", type=float, default=1.0)
    parser.add_argument("--max-buffer-seconds", type=float, default=None)
    parser.add_argument("--receive-timeout-seconds", type=float, default=8.0)
    parser.add_argument(
        "--no-realtime-pace",
        action="store_true",
        help="Send audio as fast as possible. Keep realtime pacing enabled for demo recordings.",
    )
    args = parser.parse_args(argv)
    if args.duration_seconds <= 0:
        parser.error("--duration-seconds must be greater than 0")
    if args.partial_interval_ms <= 0:
        parser.error("--partial-interval-ms must be greater than 0")
    if args.receive_timeout_seconds <= 0:
        parser.error("--receive-timeout-seconds must be greater than 0")
    if args.max_buffer_seconds is not None and args.max_buffer_seconds <= 0:
        parser.error("--max-buffer-seconds must be greater than 0")
    if args.max_buffer_seconds is None:
        args.max_buffer_seconds = max(10.0, args.duration_seconds)
    return args


def load_demo_audio(path: Path, *, duration_seconds: float, frame_ms: int = HOT_PATH_FRAME_MS) -> AudioFrames:
    pcm, sample_rate = read_pcm16_mono_wav(path)
    frames = split_pcm_frames(pcm, sample_rate=sample_rate, frame_ms=frame_ms)
    if not frames:
        raise ValueError(f"{path} did not contain any audio frames")

    target_frames = max(1, round(duration_seconds * 1000 / frame_ms))
    repeated = [frames[index % len(frames)] for index in range(target_frames)]
    return AudioFrames(source=path, sample_rate=sample_rate, frame_ms=frame_ms, frames=repeated)


def read_pcm16_mono_wav(path: Path) -> tuple[bytes, int]:
    with wave.open(str(path), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        sample_rate = wav_file.getframerate()
        if channels != 1 or sample_width != 2:
            raise ValueError("input WAV must be mono PCM16")
        if sample_rate != HOT_PATH_SAMPLE_RATE:
            raise ValueError(f"input WAV sample rate must be {HOT_PATH_SAMPLE_RATE} Hz")
        return wav_file.readframes(wav_file.getnframes()), sample_rate


def split_pcm_frames(pcm: bytes, *, sample_rate: int, frame_ms: int) -> list[bytes]:
    bytes_per_frame = sample_rate * frame_ms * 2 // 1000
    if bytes_per_frame <= 0 or sample_rate * frame_ms * 2 % 1000 != 0:
        raise ValueError("sample_rate and frame_ms must produce whole PCM16 frames")
    full_frame_bytes = len(pcm) - (len(pcm) % bytes_per_frame)
    return [pcm[index : index + bytes_per_frame] for index in range(0, full_frame_bytes, bytes_per_frame)]


def sanitize_console_text(value: str) -> str:
    without_ansi = ANSI_ESCAPE.sub("", value)
    sanitized = CONTROL_CHARS.sub("", without_ansi).replace("\r", " ").replace("\n", " ")
    return " ".join(sanitized.split())


def redact_url_for_log(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    if parts.username is not None:
        host = f"{parts.username}:***@{host}"
    query = "<redacted>" if parts.query else ""
    return urlunsplit((parts.scheme, host, parts.path, query, ""))


def format_event_line(event: TranscriptEvent, *, elapsed_seconds: float) -> str:
    wall_clock = datetime.now().strftime("%H:%M:%S")
    kind = "final" if event.is_final or event.type == "final" else event.type
    text = sanitize_console_text(event.text)
    pieces = [f"[{wall_clock} +{elapsed_seconds:05.1f}s]", f"{kind:<7}"]
    if event.revision is not None:
        pieces.append(f"rev={event.revision}")
    if event.audio_received_ms is not None:
        pieces.append(f"audio={event.audio_received_ms}ms")
    return " ".join(pieces) + f" | {text}"


async def capture_transcription(args: argparse.Namespace) -> int:
    audio = load_demo_audio(args.input_wav, duration_seconds=args.duration_seconds)
    output = args.output
    output.parent.mkdir(parents=True, exist_ok=True)

    client = AsyncLocalSttClient(args.url)
    started_at = time.perf_counter()
    lines: list[str] = []
    final_seen = False

    def emit(line: str) -> None:
        safe_line = sanitize_console_text(line)
        print(safe_line, flush=True)
        lines.append(safe_line)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")

    emit(
        f"# pipecat_local_stt_bot console transcription capture: "
        f"source={audio.source}, target_duration={audio.duration_seconds:.1f}s, url={redact_url_for_log(args.url)}"
    )

    try:
        await client.start(
            language=args.language or None,
            sample_rate=audio.sample_rate,
            interim_results=True,
            partial_interval_ms=args.partial_interval_ms,
            partial_window_seconds=args.partial_window_seconds,
            max_buffer_seconds=args.max_buffer_seconds,
            client_stream_id="pipecat-local-stt-bot-console-demo",
            metadata={"example": "pipecat_local_stt_bot", "capture_duration_seconds": audio.duration_seconds},
        )

        receive_done = asyncio.Event()

        async def receive_loop() -> None:
            nonlocal final_seen
            while not receive_done.is_set():
                event = await client.recv_event(timeout=0.1, allow_error=True)
                if event is None:
                    continue
                emit(format_event_line(event, elapsed_seconds=time.perf_counter() - started_at))
                if event.type == "error" or event.is_final or event.type == "final":
                    final_seen = event.is_final or event.type == "final"
                    receive_done.set()

        receive_task = asyncio.create_task(receive_loop())
        try:
            for frame in audio.frames:
                if receive_done.is_set():
                    break
                await client.send_audio(frame)
                if not args.no_realtime_pace:
                    await asyncio.sleep(audio.frame_ms / 1000)

            if not receive_done.is_set():
                await client.finalize()
                try:
                    await asyncio.wait_for(receive_done.wait(), timeout=args.receive_timeout_seconds)
                except TimeoutError:
                    emit(f"# timed out waiting {args.receive_timeout_seconds:.1f}s for a final transcript")
        finally:
            receive_done.set()
            await receive_task
            await client.close(graceful=False)
    except Exception as exc:
        emit(f"# capture failed: {exc.__class__.__name__}: {exc}")
        return 1

    emit(f"# wrote clean console log to {output}")
    return 0 if final_seen else 2


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(capture_transcription(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
