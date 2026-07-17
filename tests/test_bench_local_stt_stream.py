from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from src.protocols import RAW_UDS_HEADER_BYTES, RAW_UDS_MAX_PAYLOAD_BYTES
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
                    metadata={
                        "audio_send_queue_depth_ms": 1.0,
                        "asr_receive_loop_append_ms": 2.0,
                        "asr_queue_delay_ms": 3.0,
                        "asr_decode_ms": 4.0,
                        "websocket_roundtrip_ms": 5.0,
                    },
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
                    metadata={
                        "audio_send_queue_depth_ms": 1.5,
                        "asr_receive_loop_append_ms": 2.5,
                        "asr_queue_delay_ms": 3.5,
                        "asr_decode_ms": 4.5,
                        "websocket_roundtrip_ms": 5.5,
                    },
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
                metadata={
                    "audio_send_queue_depth_ms": 2.0,
                    "asr_receive_loop_append_ms": 3.0,
                    "asr_queue_delay_ms": 4.0,
                    "asr_decode_ms": 5.0,
                    "websocket_roundtrip_ms": 6.0,
                },
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


class BrokenSendLocalSttClient(FakeLocalSttClient):
    async def send_audio(self, chunk: bytes) -> None:
        if self.sent:
            raise ConnectionError("forced send disconnect")
        await super().send_audio(chunk)


class MalformedReceiveLocalSttClient(FakeLocalSttClient):
    def __init__(self, url: str) -> None:
        super().__init__(url)
        self._raised_malformed = False

    async def recv_event(self, *, timeout=None, allow_error=True):
        if not self._raised_malformed:
            self._raised_malformed = True
            raise ValueError("malformed protocol event")
        return await super().recv_event(timeout=timeout, allow_error=allow_error)


class ErrorEventLocalSttClient(FakeLocalSttClient):
    async def send_audio(self, chunk: bytes) -> None:
        await super().send_audio(chunk)
        await self._events.put(
            TranscriptEvent(
                type="error",
                text="upstream disconnected",
                stream_id=None,
                is_final=False,
                chunks_received=len(self.sent),
                buffered_bytes=sum(len(sent) for sent in self.sent),
                remaining_buffer_bytes=0,
                raw={"type": "error", "code": "upstream_disconnect", "message": "upstream disconnected"},
            )
        )


class ReconnectMetadataLocalSttClient(FakeLocalSttClient):
    async def finalize(self) -> None:
        self.finalized = True
        await self._events.put(
            TranscriptEvent(
                type="final",
                text="hello after reconnect",
                stream_id=None,
                is_final=True,
                chunks_received=len(self.sent),
                buffered_bytes=sum(len(chunk) for chunk in self.sent),
                remaining_buffer_bytes=0,
                metadata={"local_stt_reconnects_total": 2},
            )
        )


def test_split_pcm_frames_uses_20_ms_pcm16_boundaries() -> None:
    pcm = b"a" * 640 + b"b" * 640 + b"tail"

    frames = benchmark_module.split_pcm_frames(pcm, sample_rate=16000, frame_ms=20)

    assert frames == [b"a" * 640, b"b" * 640, b"tail"]



def test_parse_args_accepts_optional_power_and_thermal_signals(tmp_path) -> None:
    pcm_path = tmp_path / "sample.pcm"
    pcm_path.write_bytes(b"\0" * 640)

    args = benchmark_module.parse_args([
        "--input-raw-pcm",
        str(pcm_path),
        "--package-power-watts",
        "7.4",
        "--energy-per-audio-second-j",
        "2.6",
        "--thermal-peak-celsius",
        "63.5",
        "--thermal-observation",
        "stable after 5 minutes",
        "--thermal-duration-minutes",
        "5",
    ])

    assert args.package_power_watts == 7.4
    assert args.energy_per_audio_second_j == 2.6
    assert args.thermal_peak_celsius == 63.5
    assert args.thermal_observation == "stable after 5 minutes"
    assert args.thermal_duration_minutes == 5.0


def test_parse_args_accepts_documented_thermal_state_alias(tmp_path) -> None:
    pcm_path = tmp_path / "sample.pcm"
    pcm_path.write_bytes(b"\0" * 640)

    args = benchmark_module.parse_args([
        "--input-raw-pcm",
        str(pcm_path),
        "--thermal-state",
        "nominal",
    ])

    assert args.thermal_observation == "nominal"


def test_parse_args_rejects_negative_power_and_thermal_values(tmp_path) -> None:
    pcm_path = tmp_path / "sample.pcm"
    pcm_path.write_bytes(b"\0" * 640)

    for flag in ("--package-power-watts", "--energy-per-audio-second-j", "--thermal-peak-celsius", "--thermal-duration-minutes"):
        try:
            benchmark_module.parse_args(["--input-raw-pcm", str(pcm_path), flag, "-1"])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError(f"expected {flag} to reject negative values")

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


def test_describe_environment_records_memory_when_psutil_is_available(monkeypatch) -> None:
    fake_psutil = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(total=16 * 1024 * 1024 * 1024),
        Process=lambda: SimpleNamespace(
            memory_info=lambda: SimpleNamespace(rss=384 * 1024 * 1024),
        ),
    )
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    payload = benchmark_module.describe_environment()

    assert payload["memory_total_mb"] == 16384.0
    assert payload["process_rss_mb"] == 384.0
    assert payload["process_metrics_pid"] is None
    assert payload["peak_rss_mb"] is None
    assert payload["cpu_utilization_percent"] is None
    assert payload["process_metrics_sample_count"] == 0


def test_process_metrics_monitor_tracks_peak_rss_and_cpu_average(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, pid=None) -> None:
            self.pid = pid
            self._rss_values = [128 * 1024 * 1024, 256 * 1024 * 1024]
            self._cpu_values = [0.0, 20.0, 40.0]

        def memory_info(self):
            rss = self._rss_values.pop(0) if self._rss_values else 192 * 1024 * 1024
            return SimpleNamespace(rss=rss)

        def cpu_percent(self, interval=None):
            return self._cpu_values.pop(0) if self._cpu_values else 40.0

    fake_psutil = SimpleNamespace(Process=FakeProcess)
    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)

    monitor = benchmark_module.ProcessMetricsMonitor(pid=4321, interval_seconds=0.01)
    monitor.sample_once()
    monitor.sample_once()
    monitor.stop()

    assert monitor.peak_rss_mb == 256.0
    assert monitor.cpu_utilization_percent == 10.0
    assert monitor._process.pid == 4321
    assert monitor._samples == [0.0, 20.0]


def test_process_metrics_monitor_skips_immediate_post_prime_cpu_sample(monkeypatch) -> None:
    class FakeProcess:
        def __init__(self, pid=None) -> None:
            self._cpu_values = [0.0, 95.0]

        def memory_info(self):
            return SimpleNamespace(rss=128 * 1024 * 1024)

        def cpu_percent(self, interval=None):
            return self._cpu_values.pop(0) if self._cpu_values else 95.0

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=FakeProcess))

    monitor = benchmark_module.ProcessMetricsMonitor(pid=4321, interval_seconds=10.0)
    monitor.start()
    monitor.stop()

    assert monitor.peak_rss_mb == 128.0
    assert monitor.cpu_utilization_percent is None
    assert monitor._samples == []


def test_process_metrics_monitor_stays_null_without_explicit_pid(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda pid=None: SimpleNamespace()))

    monitor = benchmark_module.ProcessMetricsMonitor()
    monitor.start()
    monitor.sample_once()
    monitor.stop()

    assert monitor.peak_rss_mb is None
    assert monitor.cpu_utilization_percent is None


def test_describe_environment_accepts_measured_process_metrics(monkeypatch) -> None:
    seen = {}

    def fake_process(pid=None):
        seen["pid"] = pid
        return SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=384 * 1024 * 1024))

    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(total=16 * 1024 * 1024 * 1024),
            Process=fake_process,
        ),
    )

    payload = benchmark_module.describe_environment(
        process_pid=4321,
        peak_rss_mb=512.5,
        cpu_utilization_percent=42.0,
        process_metrics_sample_count=3,
    )

    assert payload["process_rss_mb"] == 384.0
    assert payload["process_metrics_pid"] == 4321
    assert payload["peak_rss_mb"] == 512.5
    assert payload["cpu_utilization_percent"] == 42.0
    assert payload["process_metrics_sample_count"] == 3
    assert seen["pid"] == 4321


def test_describe_environment_records_optional_power_and_thermal_signals(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            virtual_memory=lambda: SimpleNamespace(total=16 * 1024 * 1024 * 1024),
            Process=lambda pid=None: SimpleNamespace(memory_info=lambda: SimpleNamespace(rss=384 * 1024 * 1024)),
        ),
    )

    payload = benchmark_module.describe_environment(
        package_power_watts=7.4,
        energy_per_audio_second_j=2.6,
        thermal_peak_celsius=63.5,
        thermal_observation="stable after 5 minutes",
        thermal_duration_minutes=5.0,
    )

    assert payload["package_power_watts"] == 7.4
    assert payload["energy_per_audio_second_j"] == 2.6
    assert payload["thermal_peak_celsius"] == 63.5
    assert payload["thermal_observation"] == "stable after 5 minutes"
    assert payload["thermal_duration_minutes"] == 5.0


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
    assert payload["target"] == {"transport": "tcp_ws", "url": "ws://example.test/v1/stt/stream", "uds_path": None}
    assert payload["target_contract"] == {
        "control_channel": "tcp_websocket",
        "audio_framing": "binary_websocket_pcm16",
        "per_frame_overhead_bytes": 0,
        "max_payload_bytes": None,
    }
    assert payload["environment"]["cpu_logical_cores"] is not None
    assert payload["environment"]["process_metrics_sample_count"] == 0
    assert payload["audio"]["channels"] == 1
    assert payload["audio"]["format"] == "pcm_s16le"
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
    assert sample["successful_runs"] == 1
    assert sample["final_transcript"] == "hello"
    assert sample["warnings_received"] == 1
    assert sample["warning_codes"] == ["partial_dropped"]
    assert sample["protocol_errors"] == 0
    assert sample["protocol_error_codes"] == []
    assert sample["time_to_first_interim_ms"] is not None
    assert sample["time_to_final_after_finalize_ms"] is not None
    assert sample["audio_end_finalization_rtf"] is not None
    assert sample["audio_end_finalization_rtf"] >= 0
    assert sample["audio_send_duration_ms"] is not None
    assert sample["send_receive_overlap_ms"] is not None
    assert sample["audio_send_queue_depth_p95_ms"] == 2.0
    assert sample["audio_send_queue_depth_samples"] == 3
    assert sample["audio_send_latency_p95_ms"] is not None
    assert sample["partial_cadence_p95_ms"] is not None
    assert sample["pcm16_normalization_p95_ms"] is not None
    assert sample["asr_receive_loop_append_p95_ms"] == 3.0
    assert sample["asr_receive_loop_append_samples"] == 3
    assert sample["asr_queue_delay_p95_ms"] == 4.0
    assert sample["asr_queue_delay_samples"] == 3
    assert sample["asr_decode_p95_ms"] == 5.0
    assert sample["asr_decode_samples"] == 3
    assert sample["websocket_roundtrip_p95_ms"] == 6.0
    assert sample["websocket_roundtrip_samples"] == 3
    assert payload["summary"]["time_to_first_interim_ms"]["p95"] >= 0
    assert payload["summary"]["audio_end_finalization_rtf"]["p95"] >= 0
    assert payload["summary"]["audio_send_duration_ms"]["p95"] >= 0
    assert payload["summary"]["send_receive_overlap_ms"]["p95"] >= 0
    assert payload["summary"]["audio_send_queue_depth_p95_ms"] == {"p50": 2.0, "p95": 2.0, "p99": 2.0}
    assert payload["summary"]["audio_send_queue_depth_samples"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["asr_receive_loop_append_p95_ms"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["asr_receive_loop_append_samples"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["asr_queue_delay_p95_ms"] == {"p50": 4.0, "p95": 4.0, "p99": 4.0}
    assert payload["summary"]["asr_queue_delay_samples"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["asr_decode_p95_ms"] == {"p50": 5.0, "p95": 5.0, "p99": 5.0}
    assert payload["summary"]["asr_decode_samples"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["websocket_roundtrip_p95_ms"] == {"p50": 6.0, "p95": 6.0, "p99": 6.0}
    assert payload["summary"]["websocket_roundtrip_samples"] == {"p50": 3.0, "p95": 3.0, "p99": 3.0}
    assert payload["summary"]["audio_send_latency_p95_ms"]["p95"] >= 0
    assert payload["summary"]["partial_cadence_p95_ms"]["p95"] >= 0
    assert payload["summary"]["pcm16_normalization_p95_ms"]["p95"] >= 0
    assert payload["summary"]["warnings_received"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}
    assert payload["diagnostics"] == {
        "warning_codes": {"partial_dropped": 1},
        "protocol_error_codes": {},
    }
    assert payload["summary"]["audio_frames_sent"] == {"p50": 2.0, "p95": 2.0, "p99": 2.0}
    assert payload["summary"]["audio_frames_dropped"] == {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    assert payload["summary"]["interim_events_received"] == {"p50": 2.0, "p95": 2.0, "p99": 2.0}
    assert payload["summary"]["interim_transcript_changes"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}
    assert payload["summary"]["final_events_received"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}
    assert payload["summary"]["successful_runs"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}
    assert payload["summary"]["reconnects"] == {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    assert payload["summary"]["protocol_errors"] == {"p50": 0.0, "p95": 0.0, "p99": 0.0}


def test_run_benchmark_records_send_disconnect_as_dropped_frames_and_protocol_error() -> None:
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
            client_factory=BrokenSendLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert sample["audio_frames_sent"] == 1
    assert sample["audio_frames_dropped"] == 2
    assert sample["protocol_errors"] == 1
    assert sample["successful_runs"] == 0
    assert sample["protocol_error_codes"] == ["send_exception"]
    assert payload["summary"]["audio_frames_dropped"] == {"p50": 2.0, "p95": 2.0, "p99": 2.0}
    assert payload["summary"]["successful_runs"] == {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    assert payload["summary"]["protocol_errors"] == {"p50": 1.0, "p95": 1.0, "p99": 1.0}
    assert payload["diagnostics"]["protocol_error_codes"] == {"send_exception": 1}


def test_run_benchmark_records_malformed_receive_event_as_protocol_error() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://example.test/v1/stt/stream",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=MalformedReceiveLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert sample["protocol_errors"] == 1
    assert sample["protocol_error_codes"] == ["receive_exception"]
    assert sample["final_events_received"] == 0


def test_run_benchmark_records_protocol_error_codes_from_error_events() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://example.test/v1/stt/stream",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=ErrorEventLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert sample["protocol_errors"] == 1
    assert sample["protocol_error_codes"] == ["upstream_disconnect"]
    assert payload["diagnostics"]["protocol_error_codes"] == {"upstream_disconnect": 1}
    assert sample["final_events_received"] == 0


def test_run_benchmark_records_reconnect_count_from_event_metadata() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://example.test/v1/stt/stream",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=ReconnectMetadataLocalSttClient,
        )
    )

    sample = payload["samples"][0]
    assert sample["reconnects"] == 2
    assert payload["summary"]["reconnects"] == {"p50": 2.0, "p95": 2.0, "p99": 2.0}


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


def test_compute_audio_end_finalization_rtf_normalizes_by_audio_duration() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640, b"b" * 640, b"c" * 640, b"d" * 640, b"e" * 640],
    )

    assert benchmark_module.compute_audio_end_finalization_rtf(150.0, audio) == 1.5
    assert benchmark_module.compute_audio_end_finalization_rtf(None, audio) is None


def test_receive_latency_ignores_empty_poll_timeouts() -> None:
    assert benchmark_module.percentile([], 0.95) is None
    assert benchmark_module.summarize_samples([{"websocket_roundtrip_p95_ms": None}])["websocket_roundtrip_p95_ms"] == {
        "p50": None,
        "p95": None,
        "p99": None,
    }


def test_summarize_diagnostics_counts_codes_across_runs() -> None:
    diagnostics = benchmark_module.summarize_diagnostics(
        [
            {"warning_codes": ["partial_dropped"], "protocol_error_codes": ["send_exception"]},
            {"warning_codes": ["partial_dropped", "queue_depth_high"], "protocol_error_codes": ["send_exception", "receive_exception"]},
        ]
    )

    assert diagnostics == {
        "warning_codes": {"partial_dropped": 2, "queue_depth_high": 1},
        "protocol_error_codes": {"receive_exception": 1, "send_exception": 2},
    }


def test_summarize_samples_preserves_small_rtf_precision() -> None:
    summary = benchmark_module.summarize_samples(
        [
            {"audio_end_finalization_rtf": 0.015, "time_to_first_interim_ms": 1.24},
            {"audio_end_finalization_rtf": 0.024, "time_to_first_interim_ms": 2.26},
        ]
    )

    assert summary["audio_end_finalization_rtf"] == {"p50": 0.015, "p95": 0.024, "p99": 0.024}
    assert summary["time_to_first_interim_ms"] == {"p50": 1.2, "p95": 2.3, "p99": 2.3}


def test_print_summary_formats_warning_counts_without_ms(capsys) -> None:
    benchmark_module.print_summary(
        {
            "summary": {
                "warnings_received": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
                "audio_frames_sent": {"p50": 4.0, "p95": 4.0, "p99": 4.0},
                "interim_transcript_changes": {"p50": 2.0, "p95": 3.0, "p99": 3.0},
                "successful_runs": {"p50": 1.0, "p95": 1.0, "p99": 1.0},
                "reconnects": {"p50": 0.0, "p95": 1.0, "p99": 1.0},
                "asr_decode_samples": {"p50": 3.0, "p95": 4.0, "p99": 4.0},
                "audio_end_finalization_rtf": {"p50": 0.5, "p95": 0.75, "p99": None},
                "time_to_first_interim_ms": {"p50": 4.0, "p95": 5.0, "p99": None},
            }
        }
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "warnings_received: p50=1.0 p95=2.0 p99=3.0"
    assert lines[1] == "audio_frames_sent: p50=4.0 p95=4.0 p99=4.0"
    assert lines[2] == "interim_transcript_changes: p50=2.0 p95=3.0 p99=3.0"
    assert lines[3] == "successful_runs: p50=1.0 p95=1.0 p99=1.0"
    assert lines[4] == "reconnects: p50=0.0 p95=1.0 p99=1.0"
    assert lines[5] == "asr_decode_samples: p50=3.0 p95=4.0 p99=4.0"
    assert lines[6] == "audio_end_finalization_rtf: p50=0.5 p95=0.75 p99=n/a"
    assert lines[7] == "time_to_first_interim_ms: p50=4.0ms p95=5.0ms p99=n/a"


def test_parse_args_accepts_uds_ws_with_socket_path(tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)

    args = benchmark_module.parse_args(["--transport", "uds_ws", "--uds-path", "/tmp/stt.sock", "--input-raw-pcm", str(raw_path)])

    assert args.transport == "uds_ws"
    assert args.uds_path == Path("/tmp/stt.sock")


def test_parse_args_accepts_raw_uds_with_socket_path(tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)

    args = benchmark_module.parse_args(["--transport", "raw_uds", "--uds-path", "/tmp/stt.raw.sock", "--input-raw-pcm", str(raw_path)])

    assert args.transport == "raw_uds"
    assert args.uds_path == Path("/tmp/stt.raw.sock")


def test_make_client_factory_uses_raw_uds_client() -> None:
    factory = benchmark_module.make_client_factory(transport="raw_uds", uds_path="/tmp/stt.raw.sock")
    client = factory("ws://ignored/v1/stt/stream")

    assert isinstance(client, benchmark_module.AsyncRawUdsLocalSttClient)
    assert client.uds_path == "/tmp/stt.raw.sock"


def test_describe_transport_contract_records_raw_uds_framing() -> None:
    contract = benchmark_module.describe_transport_contract("raw_uds")

    assert contract == {
        "control_channel": "unix_stream",
        "audio_framing": "length_prefixed_pcm16",
        "plugin_config": {"transport": "raw_uds", "uds_path": "<LOCAL_STT_RAW_UDS_PATH>"},
        "enable_env": "LOCAL_STT_RAW_UDS_ENABLED",
        "path_env": "LOCAL_STT_RAW_UDS_PATH",
        "frame_format": "uint8_type_uint32_len_le",
        "frame_header_bytes": RAW_UDS_HEADER_BYTES,
        "per_frame_overhead_bytes": RAW_UDS_HEADER_BYTES,
        "max_payload_bytes": RAW_UDS_MAX_PAYLOAD_BYTES,
        "frame_types": ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR", "PING", "PONG"],
        "frame_type_codes": {
            "JSON_CONTROL": 1,
            "AUDIO_PCM16": 2,
            "JSON_EVENT": 3,
            "ERROR": 4,
            "PING": 5,
            "PONG": 6,
        },
        "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
        "semantic_lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
        "start_control_payload": {
            "type": "start",
            "protocol": "local-stt-v1",
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "frame_ms": 20,
            "partial_interval_ms": 100,
        },
        "error_handling": [
            "bad_frame_type",
            "malformed_json_control",
            "oversized_payload",
            "incomplete_frame",
            "frame_length_mismatch",
        ],
        "error_codes": [
            "raw_uds_unsupported_frame_type",
            "raw_uds_malformed_json_control",
            "raw_uds_payload_too_large",
            "raw_uds_incomplete_frame",
            "raw_uds_frame_length_mismatch",
        ],
        "shared_stream_runtime": True,
        "benchmark_metrics": [
            "time_to_first_interim_ms",
            "time_to_final_after_finalize_ms",
            "send_queue_depth_p95",
            "asr_queue_delay_p95",
            "protocol_errors",
            "cpu_utilization",
        ],
        "comparison_required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "latency_win_threshold_ms": 5.0,
        "recommendation_gate": "experimental_until_p95_win_over_uds_ws_is_at_least_5ms",
    }


def test_parse_args_rejects_uds_path_for_default_tcp_transport(tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)

    try:
        benchmark_module.parse_args(["--uds-path", "/tmp/stt.sock", "--input-raw-pcm", str(raw_path)])
    except Exception as exc:
        assert "--uds-path is only valid" in str(exc)
    else:
        raise AssertionError("expected TCP transport to reject a UDS path")


def test_make_client_factory_reports_missing_unix_connect(monkeypatch) -> None:
    async def exercise() -> None:
        factory = benchmark_module.make_client_factory(transport="uds_ws", uds_path="/tmp/stt.sock")
        client = factory("ws://localhost/v1/stt/stream")
        await client._connect_fn("ws://localhost/v1/stt/stream")

    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=object()))

    try:
        asyncio.run(exercise())
    except RuntimeError as exc:
        assert "uds_ws transport requires websockets.unix_connect" in str(exc)
    else:
        raise AssertionError("expected uds_ws without unix_connect to fail clearly")


def test_run_benchmark_records_uds_ws_target_with_injected_client() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://localhost/v1/stt/stream",
            transport="uds_ws",
            uds_path="/tmp/stt.sock",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=FakeLocalSttClient,
        )
    )

    assert payload["target"] == {"transport": "uds_ws", "url": "ws://localhost/v1/stt/stream", "uds_path": "/tmp/stt.sock"}
    assert payload["target_contract"] == {
        "control_channel": "unix_stream_websocket",
        "audio_framing": "binary_websocket_pcm16",
        "per_frame_overhead_bytes": 0,
        "max_payload_bytes": None,
    }


def test_run_benchmark_records_raw_uds_target_contract_with_injected_client() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    payload = asyncio.run(
        benchmark_module.run_benchmark(
            url="ws://ignored/v1/stt/stream",
            transport="raw_uds",
            uds_path="/tmp/stt.raw.sock",
            audio=audio,
            partial_interval_ms=100,
            runs=1,
            realtime_pace=False,
            client_factory=FakeLocalSttClient,
        )
    )

    assert payload["target"] == {
        "transport": "raw_uds",
        "url": "ws://ignored/v1/stt/stream",
        "uds_path": "/tmp/stt.raw.sock",
        "frame_format": "uint8_type_uint32_len_le",
        "plugin_config": {"transport": "raw_uds", "uds_path": "/tmp/stt.raw.sock"},
        "enable_env": "LOCAL_STT_RAW_UDS_ENABLED",
        "path_env": "LOCAL_STT_RAW_UDS_PATH",
        "frame_header_bytes": RAW_UDS_HEADER_BYTES,
        "per_frame_overhead_bytes": RAW_UDS_HEADER_BYTES,
        "max_payload_bytes": RAW_UDS_MAX_PAYLOAD_BYTES,
        "frame_types": ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR", "PING", "PONG"],
        "frame_type_codes": {
            "JSON_CONTROL": 1,
            "AUDIO_PCM16": 2,
            "JSON_EVENT": 3,
            "ERROR": 4,
            "PING": 5,
            "PONG": 6,
        },
        "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
        "semantic_lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
        "start_control_payload": {
            "type": "start",
            "protocol": "local-stt-v1",
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "frame_ms": 20,
            "partial_interval_ms": 100,
        },
        "error_handling": [
            "bad_frame_type",
            "malformed_json_control",
            "oversized_payload",
            "incomplete_frame",
            "frame_length_mismatch",
        ],
        "error_codes": [
            "raw_uds_unsupported_frame_type",
            "raw_uds_malformed_json_control",
            "raw_uds_payload_too_large",
            "raw_uds_incomplete_frame",
            "raw_uds_frame_length_mismatch",
        ],
        "shared_stream_runtime": True,
        "benchmark_metrics": [
            "time_to_first_interim_ms",
            "time_to_final_after_finalize_ms",
            "send_queue_depth_p95",
            "asr_queue_delay_p95",
            "protocol_errors",
            "cpu_utilization",
        ],
        "comparison_required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "latency_win_threshold_ms": 5.0,
        "recommendation_gate": "experimental_until_p95_win_over_uds_ws_is_at_least_5ms",
    }
    assert payload["target_contract"]["control_channel"] == "unix_stream"
    assert payload["target_contract"]["audio_framing"] == "length_prefixed_pcm16"
    assert payload["target_contract"]["plugin_config"] == {
        "transport": "raw_uds",
        "uds_path": "<LOCAL_STT_RAW_UDS_PATH>",
    }
    assert payload["target_contract"]["frame_format"] == "uint8_type_uint32_len_le"
    assert payload["target_contract"]["frame_header_bytes"] == RAW_UDS_HEADER_BYTES
    assert payload["target_contract"]["per_frame_overhead_bytes"] == RAW_UDS_HEADER_BYTES
    assert payload["target_contract"]["start_control_payload"] == {
        "type": "start",
        "protocol": "local-stt-v1",
        "sample_rate": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "frame_ms": 20,
        "partial_interval_ms": 100,
    }


def test_run_benchmark_requires_uds_path_for_uds_ws_even_with_injected_client() -> None:
    audio = benchmark_module.AudioInput(
        source="fixture.raw",
        sample_rate=16000,
        frame_ms=20,
        frames=[b"a" * 640],
    )

    try:
        asyncio.run(
            benchmark_module.run_benchmark(
                url="ws://localhost/v1/stt/stream",
                transport="uds_ws",
                uds_path=None,
                audio=audio,
                partial_interval_ms=100,
                runs=1,
                realtime_pace=False,
                client_factory=FakeLocalSttClient,
            )
        )
    except Exception as exc:
        assert "--uds-path is required" in str(exc)
    else:
        raise AssertionError("expected uds_ws benchmark artifacts to require a socket path")


def test_parse_args_requires_uds_path_for_uds_ws(tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)

    try:
        benchmark_module.parse_args(["--transport", "uds_ws", "--input-raw-pcm", str(raw_path)])
    except Exception as exc:
        assert "--uds-path is required" in str(exc)
    else:
        raise AssertionError("expected missing uds path to be rejected")


def test_parse_args_requires_uds_path_for_raw_uds(tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)

    try:
        benchmark_module.parse_args(["--transport", "raw_uds", "--input-raw-pcm", str(raw_path)])
    except Exception as exc:
        assert "--uds-path is required" in str(exc)
    else:
        raise AssertionError("expected missing raw UDS path to be rejected")


def test_main_writes_json_artifact_with_raw_pcm(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "clip.pcm"
    raw_path.write_bytes(b"a" * 640)
    output_path = tmp_path / "artifact.json"
    audio_seen: dict[str, object] = {}

    async def fake_run_benchmark(**kwargs):
        audio_seen["audio"] = kwargs["audio"]
        audio_seen["metrics_pid"] = kwargs["metrics_pid"]
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
            "--metrics-pid",
            "4321",
            "--no-realtime-pace",
        ]
    )

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written["kind"] == "local-stt-v1-latency-benchmark"
    assert written["settings"]["receive_timeout_seconds"] == 7
    assert audio_seen["audio"].frames == [b"a" * 640]
    assert audio_seen["metrics_pid"] == 4321
