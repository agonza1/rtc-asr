from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from src.rtc_client import TranscriptEvent


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "bench_local_stt_stream.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_bench_local_stt_stream", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_bench_local_stt_stream", benchmark_module)
SPEC.loader.exec_module(benchmark_module)


class FakeLocalSttClient:
    def __init__(self, _: str) -> None:
        self.started: dict[str, object] | None = None
        self.sent: list[bytes] = []
        self.finalized = False
        self.closed = False
        self._events = asyncio.Queue()

    async def start(self, **kwargs):
        self.started = kwargs
        return {"type": "ready"}

    async def send_audio(self, chunk: bytes) -> None:
        self.sent.append(chunk)
        if len(self.sent) == 1:
            await self._events.put(
                TranscriptEvent(
                    type="partial",
                    text="hel",
                    stream_id=None,
                    is_final=False,
                    chunks_received=1,
                    buffered_bytes=len(chunk),
                    remaining_buffer_bytes=0,
                )
            )

    async def finalize(self) -> None:
        self.finalized = True
        await self._events.put(
            TranscriptEvent(
                type="final",
                text="hello",
                stream_id=None,
                is_final=True,
                chunks_received=len(self.sent),
                buffered_bytes=sum(len(chunk) for chunk in self.sent),
                remaining_buffer_bytes=0,
            )
        )

    async def recv_event(self, *, timeout=None, allow_error=True):
        try:
            if timeout is None:
                return await self._events.get()
            return await asyncio.wait_for(self._events.get(), timeout)
        except TimeoutError:
            return None

    async def close(self, *, graceful=True):
        self.closed = True
        return None


def test_split_pcm_frames_uses_20_ms_pcm16_boundaries() -> None:
    pcm = b"a" * 640 + b"b" * 640 + b"tail"

    frames = benchmark_module.split_pcm_frames(pcm, sample_rate=16000, frame_ms=20)

    assert frames == [b"a" * 640, b"b" * 640, b"tail"]


def test_run_benchmark_records_required_latency_metrics() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640, b"b" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://example.test/v1/stt/stream",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=FakeLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert payload["kind"] == "local-stt-v1-latency-benchmark"
    assert payload["audio"]["bytes_per_frame"] == 640
    assert payload["audio"]["duration_ms"] == 40
    assert payload["settings"] == {
        "partial_interval_ms": 100,
        "receive_timeout_seconds": 5,
        "realtime_pace": False,
    }
    assert sample["audio_frames_sent"] == 2
    assert sample["audio_frames_dropped"] == 0
    assert sample["interim_events_received"] == 1
    assert sample["final_events_received"] == 1
    assert sample["protocol_errors"] == 0
    assert sample["time_to_first_interim_ms"] is not None
    assert sample["time_to_final_after_finalize_ms"] is not None
    assert sample["audio_send_queue_depth_p95_ms"] is None
    assert sample["asr_queue_delay_p95_ms"] is None
    assert sample["asr_decode_p95_ms"] is None
    assert payload["summary"]["time_to_first_interim_ms"]["p95"] >= 0
    assert payload["summary"]["audio_send_queue_depth_p95_ms"] == {"p50": None, "p95": None, "p99": None}


def test_receive_latency_ignores_empty_poll_timeouts() -> None:
    assert benchmark_module.percentile([], 0.95) is None
    assert benchmark_module.summarize_samples([{"websocket_roundtrip_p95_ms": None}])["websocket_roundtrip_p95_ms"] == {
        "p50": None,
        "p95": None,
        "p99": None,
    }


def test_main_writes_json_artifact_with_raw_pcm(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)
    output_path = tmp_path / "artifact.json"
    audio_seen: dict[str, object] = {}

    async def fake_run_benchmark(**kwargs):
        audio_seen["audio"] = kwargs["audio"]
        return {
            "kind": "local-stt-v1-latency-benchmark",
            "samples": [],
            "settings": {"receive_timeout_seconds": kwargs["receive_timeout_seconds"]},
            "summary": {
                "time_to_first_interim_ms": {"p50": 1.0, "p95": 1.0, "p99": 1.0},
                "time_to_final_after_finalize_ms": {"p50": 2.0, "p95": 2.0, "p99": 2.0},
            },
        }

    monkeypatch.setattr(benchmark_module, "run_benchmark", fake_run_benchmark)

    exit_code = benchmark_module.main(
        [
            "--input-raw-pcm",
            str(raw_path),
            "--runs",
            "1",
            "--output",
            str(output_path),
            "--receive-timeout-seconds",
            "7",
            "--no-realtime-pace",
        ]
    )

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["kind"] == "local-stt-v1-latency-benchmark"
    assert written["settings"]["receive_timeout_seconds"] == 7
    assert audio_seen["audio"].frames == [b"a" * 640]
