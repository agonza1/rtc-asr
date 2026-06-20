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
        if len(self.sent) == 2:
            await self._events.put(
                TranscriptEvent(
                    type="partial",
                    text="hello",
                    stream_id=None,
                    is_final=False,
                    chunks_received=2,
                    buffered_bytes=len(chunk),
                    remaining_buffer_bytes=0,
                )
            )

    async def finalize(self) -> None:
        self.finalized = True
        await self._events.put(
            TranscriptEvent(
                type="warning",
                text="partial dropped",
                stream_id=None,
                is_final=False,
                chunks_received=len(self.sent),
                buffered_bytes=sum(len(chunk) for chunk in self.sent),
                remaining_buffer_bytes=0,
                raw={"type": "warning", "code": "partial_dropped", "message": "partial dropped"},
            )
        )
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


class OverlapLocalSttClient(FakeLocalSttClient):
    async def send_audio(self, chunk: bytes) -> None:
        await super().send_audio(chunk)
        await asyncio.sleep(0.01)


def test_split_pcm_frames_uses_20_ms_pcm16_boundaries() -> None:
    pcm = b"a" * 640 + b"b" * 640 + b"tail"

    frames = benchmark_module.split_pcm_frames(pcm, sample_rate=16000, frame_ms=20)

    assert frames == [b"a" * 640, b"b" * 640, b"tail"]


def test_describe_environment_records_host_capacity(monkeypatch) -> None:
    monkeypatch.setattr(benchmark_module.platform, "platform", lambda: "TestOS")
    monkeypatch.setattr(benchmark_module.platform, "processor", lambda: "TestCPU")
    monkeypatch.setattr(benchmark_module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(benchmark_module.os, "cpu_count", lambda: 8)

    payload = benchmark_module.describe_environment()

    assert payload["date_utc"].endswith("Z")
    assert payload["platform"] == "TestOS"
    assert payload["processor"] == "TestCPU"
    assert payload["machine"] == "arm64"
    assert payload["cpu_logical_cores"] == 8
    assert payload["python"]


def test_normalize_pcm16_buffer_reports_float32_samples() -> None:
    samples = benchmark_module.normalize_pcm16_buffer(b"\x00\x00\x00@")

    assert samples.dtype.name == "float32"
    assert samples.tolist() == [0.0, 0.5]


def test_normalize_pcm16_buffer_rejects_odd_byte_buffers() -> None:
    try:
        benchmark_module.normalize_pcm16_buffer(b"x")
    except ValueError as exc:
        assert "even number of bytes" in str(exc)
    else:
        raise AssertionError("expected odd-byte PCM16 buffer to fail")


def test_iter_server_decode_buffers_matches_accumulated_partial_and_final_audio() -> None:
    frames = [b"a" * 640, b"b" * 640, b"c" * 640, b"d" * 640, b"e" * 640, b"f" * 640]

    buffers = list(benchmark_module.iter_server_decode_buffers(frames, frame_ms=20, partial_interval_ms=100))

    assert buffers == [b"".join(frames[:5]), b"".join(frames)]


def test_iter_server_decode_buffers_streams_without_list_storage() -> None:
    buffers = benchmark_module.iter_server_decode_buffers([b"a" * 640, b"b" * 640], frame_ms=20, partial_interval_ms=20)

    assert iter(buffers) is buffers
    assert next(buffers) == b"a" * 640
    assert next(buffers) == b"a" * 640 + b"b" * 640


def test_measure_pcm16_normalization_uses_server_decode_buffers(monkeypatch) -> None:
    normalized_lengths: list[int] = []

    def fake_normalize(audio_data: bytes):
        normalized_lengths.append(len(audio_data))
        return []

    monkeypatch.setattr(benchmark_module, "normalize_pcm16_buffer", fake_normalize)

    latencies = benchmark_module.measure_pcm16_normalization_latencies(
        [b"a" * 640, b"b" * 640, b"c" * 640],
        frame_ms=20,
        partial_interval_ms=40,
    )

    assert len(latencies) == 2
    assert normalized_lengths == [1280, 1920]


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
    assert payload["environment"]["cpu_logical_cores"] is not None
    assert payload["audio"]["bytes_per_frame"] == 640
    assert payload["audio"]["duration_ms"] == 40
    assert payload["settings"] == {
        "partial_interval_ms": 100,
        "receive_timeout_seconds": 5,
        "realtime_pace": False,
    }
    assert sample["audio_frames_sent"] == 2
    assert sample["audio_frames_dropped"] == 0
    assert sample["interim_events_received"] == 2
    assert sample["interim_transcript_changes"] == 1
    assert sample["final_events_received"] == 1
    assert sample["final_transcript"] == "hello"
    assert sample["warnings_received"] == 1
    assert sample["warning_codes"] == ["partial_dropped"]
    assert sample["protocol_errors"] == 0
    assert sample["time_to_first_interim_ms"] is not None
    assert sample["time_to_final_after_finalize_ms"] is not None
    assert sample["audio_send_duration_ms"] is not None
    assert sample["send_receive_overlap_ms"] is not None
    assert sample["audio_send_queue_depth_p95_ms"] is None
    assert sample["audio_send_latency_p95_ms"] is not None
    assert sample["partial_cadence_p95_ms"] is not None
    assert sample["pcm16_normalization_p95_ms"] is not None
    assert sample["asr_queue_delay_p95_ms"] is None
    assert sample["asr_decode_p95_ms"] is None
    assert payload["summary"]["time_to_first_interim_ms"]["p95"] >= 0
    assert payload["summary"]["audio_send_duration_ms"]["p95"] >= 0
    assert payload["summary"]["send_receive_overlap_ms"]["p95"] >= 0
    assert payload["summary"]["audio_send_queue_depth_p95_ms"] == {"p50": None, "p95": None, "p99": None}
    assert payload["summary"]["audio_send_latency_p95_ms"]["p95"] >= 0
    assert payload["summary"]["partial_cadence_p95_ms"]["p95"] >= 0
    assert payload["summary"]["pcm16_normalization_p95_ms"]["p95"] >= 0
    assert payload["summary"]["warnings_received"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}


def test_send_receive_overlap_proves_receive_loop_runs_during_audio_send() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640, b"b" * 640, b"c" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://example.test/v1/stt/stream",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=OverlapLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert sample["audio_frames_sent"] == 3
    assert sample["interim_events_received"] == 2
    assert sample["send_receive_overlap_ms"] > 0


def test_receive_latency_ignores_empty_poll_timeouts() -> None:
    assert benchmark_module.percentile([], 0.95) is None
    assert benchmark_module.summarize_samples([{"websocket_roundtrip_p95_ms": None}])["websocket_roundtrip_p95_ms"] == {
        "p50": None,
        "p95": None,
        "p99": None,
    }


def test_print_summary_formats_warning_counts_without_ms(capsys) -> None:
    benchmark_module.print_summary(
        {
            "summary": {
                "warnings_received": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
                "time_to_first_interim_ms": {"p50": 4.0, "p95": 5.0, "p99": None},
            }
        }
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "warnings_received: p50=1.0 p95=2.0 p99=3.0"
    assert lines[1] == "time_to_first_interim_ms: p50=4.0ms p95=5.0ms p99=n/a"


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
