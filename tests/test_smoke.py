from __future__ import annotations

import asyncio
import base64
import json
import socket
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from src.config import AppConfig
from src.main import (
    StreamSession,
    _prepare_uds_socket,
    _receive_stream_event,
    _seconds_to_buffer_bytes,
    create_app,
    main,
)
from src.model_loader import ASRUnavailableError
from src.protocols.local_stt_v1 import (
    HOT_PATH_BYTES_PER_FRAME,
    HOT_PATH_CHANNELS,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    HOT_PATH_SAMPLE_RATE,
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    PROTOCOL_VERSION,
    decode_raw_uds_frame,
    parse_raw_uds_server_frame,
    parse_server_message,
    RawUdsFrameType,
)
from src.rtc_client import AsyncRawUdsLocalSttClient
from src.streaming import ASRWebSocketClient, StreamConfig, TranscriptEvent

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smoke.wav"
DEFAULT_MAX_BUFFER_BYTES = AppConfig().stream_max_buffer_bytes


DEFAULT_PROTOCOLS = [
    {
        "id": "rtc-asr-stream.v1",
        "transport": "websocket",
        "path": "/ws/stream",
        "docs": "/docs/api-reference.md#websocket-streaming",
        "status": "legacy",
        "notes": "Deprecated transport: buffered websocket contract; prefer /v1/stt/stream for native-local-stream compatibility and lower-latency framing guidance.",
        "message_format": "json-control-plus-binary-audio",
    },
    {
        "id": PROTOCOL_VERSION,
        "transport": "websocket",
        "path": "/v1/stt/stream",
        "docs": "/docs/local-stt-v1.md",
        "status": "preview",
        "message_format": "json-control-plus-binary-pcm16",
        "server_transport": {
            "mode": "tcp",
            "transport": "tcp_ws",
            "path": "/v1/stt/stream",
        },
        "experimental_transports": [
            {
                "transport": "raw_uds",
                "status": "codec_only",
                "enabled": False,
                "enable_env": "LOCAL_STT_RAW_UDS_ENABLED",
                "path_env": "LOCAL_STT_RAW_UDS_PATH",
                "uds_path": AppConfig().local_stt_raw_uds_path,
                "plugin_config": {
                    "transport": "raw_uds",
                    "uds_path": AppConfig().local_stt_raw_uds_path,
                },
                "frame_header_bytes": RAW_UDS_HEADER_BYTES,
                "per_frame_overhead_bytes": RAW_UDS_HEADER_BYTES,
                "max_payload_bytes": RAW_UDS_MAX_PAYLOAD_BYTES,
                "frame_format": "uint8_type_uint32_len_le",
                "comparison_required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
                "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
                "semantic_lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
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
                "latency_win_threshold_ms": 5.0,
                "recommendation_gate": "experimental_until_p95_win_over_uds_ws_is_at_least_5ms",
                "frame_types": {
                    "json_control": 1,
                    "audio_pcm16": 2,
                    "json_event": 3,
                    "error": 4,
                    "ping": 5,
                    "pong": 6,
                },
                "frame_type_codes": {
                    "JSON_CONTROL": 1,
                    "AUDIO_PCM16": 2,
                    "JSON_EVENT": 3,
                    "ERROR": 4,
                    "PING": 5,
                    "PONG": 6,
                },
                "start_control_payload": {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_ms": 100,
                },
                "notes": "Raw UDS framing is available as a tested codec for latency experiments; enable LOCAL_STT_RAW_UDS_ENABLED=true to serve it.",
            }
        ],
        "audio": {
            "sample_rate": HOT_PATH_SAMPLE_RATE,
            "channels": HOT_PATH_CHANNELS,
            "format": HOT_PATH_PCM_FORMAT,
            "frame_ms": HOT_PATH_FRAME_MS,
            "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
        },
    },
]


class FakeIncomingWebSocket:
    def __init__(self, message: dict[str, object]) -> None:
        self._message = message

    async def receive(self) -> dict[str, object]:
        return self._message


class FakeTranscriber:
    backend_name = "fake-whisper"
    model_name = "fixture-adapter"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.preload_calls = 0
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def preload(self) -> None:
        self.preload_calls += 1
        self.loaded = True

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "loaded": self.is_loaded(),
            "streaming": {
                "transport": "websocket",
                "path": "/ws/stream",
                "reusable_connection": True,
                "message_types": ["start", "audio", "stop", "cancel"],
                "audio_frame_formats": ["json-base64", "binary"],
                "event_types": ["ready", "partial", "final", "canceled", "error"],
            },
            "audio": {
                "target_sample_rate": 16000,
                "channels": 1,
                "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
            },
        }

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        self.loaded = True
        self.calls.append(
            {
                "audio_size": len(audio_data),
                "language": language,
                "sample_rate": sample_rate,
                "prefix": audio_data[:4],
            }
        )
        return {
            "text": f"fixture transcription {len(self.calls)}",
            "language": language,
            "duration_ms": 125,
            "backend": self.backend_name,
            "model": self.model_name,
        }


class StableTextTranscriber(FakeTranscriber):
    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        result = super().transcribe(audio_data, language=language, sample_rate=sample_rate)
        result["text"] = "steady partial"
        return result


class FailingPreloadTranscriber(FakeTranscriber):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def preload(self) -> None:
        raise self.exc


class RecoveringPreloadTranscriber(FakeTranscriber):
    def __init__(self) -> None:
        super().__init__()
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def preload(self) -> None:
        raise RuntimeError("model download failed")

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        self.loaded = True
        return super().transcribe(audio_data, language=language, sample_rate=sample_rate)


class BrokenLazyLoadTranscriber(FakeTranscriber):
    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        raise RuntimeError("invalid device")


class UnavailableLazyLoadTranscriber(FakeTranscriber):
    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        raise ASRUnavailableError("backend unavailable")


class SleepingTranscriber(FakeTranscriber):
    def __init__(self, *, delay_seconds: float = 0.2) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds
        self.active_calls = 0
        self.max_active_calls = 0
        self._lock = threading.Lock()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        with self._lock:
            self.active_calls += 1
            self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            time.sleep(self.delay_seconds)
            return super().transcribe(audio_data, language=language, sample_rate=sample_rate)
        finally:
            with self._lock:
                self.active_calls -= 1


def test_health_and_ready_report_lazy_backend_as_traffic_ready() -> None:
    transcriber = FakeTranscriber()
    config = AppConfig(asr_preload_model=False)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert health.status_code == 200
    assert health.json() == {
        "status": "loading",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "ready": True,
        "model_loaded": False,
        "preload_enabled": False,
        "preload_error": None,
        "protocols": DEFAULT_PROTOCOLS,
    }
    assert ready.status_code == 200
    assert ready.json() == health.json()
    assert models.status_code == 200
    assert models.json()["status"] == "loading"
    assert models.json()["ready"] is True
    assert models.json()["preload_enabled"] is False
    assert models.json()["preload_error"] is None
    assert transcriber.preload_calls == 0


def test_ready_and_model_capabilities_smoke() -> None:
    transcriber = FakeTranscriber()
    config = AppConfig(asr_preload_model=True)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ready",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "ready": True,
        "model_loaded": True,
        "preload_enabled": True,
        "preload_error": None,
        "protocols": DEFAULT_PROTOCOLS,
    }
    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "ready": True,
        "model_loaded": True,
        "preload_enabled": True,
        "preload_error": None,
        "protocols": DEFAULT_PROTOCOLS,
    }
    assert models.status_code == 200
    assert models.json() == {
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "sample_rate": 16000,
        "status": "ready",
        "ready": True,
        "preload_enabled": True,
        "preload_error": None,
        "protocols": DEFAULT_PROTOCOLS,
        "streaming": {
            "transport": "websocket",
            "path": "/ws/stream",
            "reusable_connection": True,
            "message_types": ["start", "audio", "stop", "cancel"],
            "audio_frame_formats": ["json-base64", "binary"],
            "event_types": ["ready", "partial", "final", "canceled", "error"],
        },
        "audio": {
            "target_sample_rate": 16000,
            "channels": 1,
            "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
        },
        "models": [
            {
                "id": "fixture-adapter",
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "loaded": True,
                "streaming": {
                    "transport": "websocket",
                    "path": "/ws/stream",
                    "reusable_connection": True,
                    "message_types": ["start", "audio", "stop", "cancel"],
                    "audio_frame_formats": ["json-base64", "binary"],
                    "event_types": ["ready", "partial", "final", "canceled", "error"],
                },
                "audio": {
                    "target_sample_rate": 16000,
                    "channels": 1,
                    "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
                },
                "capabilities": {
                    "backend": "fake-whisper",
                    "model": "fixture-adapter",
                    "loaded": True,
                    "streaming": {
                        "transport": "websocket",
                        "path": "/ws/stream",
                        "reusable_connection": True,
                        "message_types": ["start", "audio", "stop", "cancel"],
                        "audio_frame_formats": ["json-base64", "binary"],
                        "event_types": ["ready", "partial", "final", "canceled", "error"],
                    },
                    "audio": {
                        "target_sample_rate": 16000,
                        "channels": 1,
                        "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
                    },
                },
            }
        ],
        "capabilities": {
            "backend": "fake-whisper",
            "model": "fixture-adapter",
            "loaded": True,
            "streaming": {
                "transport": "websocket",
                "path": "/ws/stream",
                "reusable_connection": True,
                "message_types": ["start", "audio", "stop", "cancel"],
                "audio_frame_formats": ["json-base64", "binary"],
                "event_types": ["ready", "partial", "final", "canceled", "error"],
            },
            "audio": {
                "target_sample_rate": 16000,
                "channels": 1,
                "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
            },
        },
    }
    assert transcriber.preload_calls == 1


def test_health_reports_active_uds_local_stt_transport(tmp_path: Path) -> None:
    socket_path = tmp_path / "stt.sock"
    config = AppConfig(local_stt_socket_mode="uds", local_stt_uds_path=str(socket_path))

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as client:
        protocols = client.get("/health").json()["protocols"]

    local_stt = next(protocol for protocol in protocols if protocol["id"] == PROTOCOL_VERSION)
    assert local_stt["server_transport"] == {
        "mode": "uds",
        "transport": "uds_ws",
        "path": "/v1/stt/stream",
        "uds_path": str(socket_path),
    }


def test_health_reports_configured_raw_uds_experiment_path(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_path=str(raw_socket_path))

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as client:
        protocols = client.get("/health").json()["protocols"]

    local_stt = next(protocol for protocol in protocols if protocol["id"] == PROTOCOL_VERSION)
    raw_uds = next(
        transport for transport in local_stt["experimental_transports"] if transport["transport"] == "raw_uds"
    )
    assert raw_uds["enabled"] is False
    assert raw_uds["enable_env"] == "LOCAL_STT_RAW_UDS_ENABLED"
    assert raw_uds["path_env"] == "LOCAL_STT_RAW_UDS_PATH"
    assert raw_uds["uds_path"] == str(raw_socket_path)
    assert raw_uds["plugin_config"] == {"transport": "raw_uds", "uds_path": str(raw_socket_path)}
    assert raw_uds["frame_format"] == "uint8_type_uint32_len_le"
    assert raw_uds["frame_header_bytes"] == RAW_UDS_HEADER_BYTES
    assert raw_uds["per_frame_overhead_bytes"] == RAW_UDS_HEADER_BYTES
    assert raw_uds["comparison_required_transports"] == ["tcp_ws", "uds_ws", "raw_uds"]
    assert raw_uds["lifecycle"] == ["start", "audio", "transcript", "finalize", "cancel", "close"]
    assert raw_uds["error_handling"] == [
        "bad_frame_type",
        "malformed_json_control",
        "oversized_payload",
        "incomplete_frame",
        "frame_length_mismatch",
    ]
    assert raw_uds["error_codes"] == [
        "raw_uds_unsupported_frame_type",
        "raw_uds_malformed_json_control",
        "raw_uds_payload_too_large",
        "raw_uds_incomplete_frame",
        "raw_uds_frame_length_mismatch",
    ]
    assert raw_uds["frame_type_codes"] == {
        "JSON_CONTROL": 1,
        "AUDIO_PCM16": 2,
        "JSON_EVENT": 3,
        "ERROR": 4,
        "PING": 5,
        "PONG": 6,
    }
    assert raw_uds["start_control_payload"] == {
        "type": "start",
        "protocol": "local-stt-v1",
        "sample_rate": HOT_PATH_SAMPLE_RATE,
        "channels": HOT_PATH_CHANNELS,
        "format": HOT_PATH_PCM_FORMAT,
        "frame_ms": HOT_PATH_FRAME_MS,
        "partial_interval_ms": 100,
    }
    assert raw_uds["shared_stream_runtime"] is True
    assert raw_uds["latency_win_threshold_ms"] == 5.0


def test_health_reports_enabled_raw_uds_server_path(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as client:
        protocols = client.get("/health").json()["protocols"]
        assert raw_socket_path.exists()

    local_stt = next(protocol for protocol in protocols if protocol["id"] == PROTOCOL_VERSION)
    raw_uds = next(
        transport for transport in local_stt["experimental_transports"] if transport["transport"] == "raw_uds"
    )
    assert raw_uds["status"] == "served"
    assert raw_uds["enabled"] is True
    assert raw_uds["uds_path"] == str(raw_socket_path)
    assert "LOCAL_STT_RAW_UDS_ENABLED=true" in raw_uds["notes"]
    assert not raw_socket_path.exists()


def test_raw_uds_server_shares_local_stt_v1_stream_runtime(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    transcriber = FakeTranscriber()
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))
    chunk = b"r" * HOT_PATH_BYTES_PER_FRAME

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient(str(raw_socket_path))
        ready = await client.start(
            client_stream_id="raw-turn-1",
            metadata={"turn_id": "raw-turn-1"},
            partial_interval_ms=HOT_PATH_FRAME_MS,
        )
        assert ready["metadata"]["client_stream_id"] == "raw-turn-1"

        await client.send_audio(chunk)
        partial = await client.recv_event()
        assert partial is not None
        assert partial.type == "partial"
        assert partial.metadata["chunks_received"] == 1

        await client.finalize()
        final = await client.recv_event()
        assert final is not None
        assert final.type == "final"
        assert final.metadata["client_stream_id"] == "raw-turn-1"

        closed = await client.close()
        assert closed == {"type": "closed", "reason": "client_close", "metadata": {}}

    with TestClient(create_app(config=config, transcriber=transcriber)):
        asyncio.run(scenario())

    assert transcriber.calls == [
        {
            "audio_size": len(chunk),
            "language": "en",
            "sample_rate": HOT_PATH_SAMPLE_RATE,
            "prefix": chunk[:4],
        }
    ]


def test_raw_uds_cancel_resets_stream_without_transcribing(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    transcriber = FakeTranscriber()
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))
    chunk = b"c" * HOT_PATH_BYTES_PER_FRAME

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient(str(raw_socket_path))
        ready = await client.start(client_stream_id="cancel-turn", partial_interval_ms=100_000)
        assert ready["metadata"]["client_stream_id"] == "cancel-turn"

        await client.send_audio(chunk)
        await client.cancel()
        canceled = await client.recv_event()
        assert canceled is not None
        assert canceled.type == "warning"
        assert canceled.raw is not None
        assert canceled.raw["code"] == "stream_canceled"
        assert canceled.raw["metadata"]["client_stream_id"] == "cancel-turn"
        assert canceled.raw["metadata"]["chunks_received"] == 1
        assert canceled.raw["metadata"]["buffered_bytes"] == 0

        second_ready = await client.start(client_stream_id="second-turn", partial_interval_ms=HOT_PATH_FRAME_MS)
        assert second_ready["metadata"]["stream_id"] == 2
        assert second_ready["metadata"]["client_stream_id"] == "second-turn"

        await client.send_audio(chunk)
        await client.finalize()
        while True:
            event = await client.recv_event()
            assert event is not None
            if event.type == "final":
                assert event.raw is not None
                assert event.raw["metadata"]["client_stream_id"] == "second-turn"
                break

        closed = await client.close()
        assert closed == {"type": "closed", "reason": "client_close", "metadata": {}}

    with TestClient(create_app(config=config, transcriber=transcriber)):
        asyncio.run(scenario())

    assert transcriber.calls == [
        {
            "audio_size": len(chunk),
            "language": "en",
            "sample_rate": HOT_PATH_SAMPLE_RATE,
            "prefix": chunk[:4],
        }
    ]


def test_raw_uds_protocol_error_does_not_stop_listener(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))

    async def read_server_frame(reader: asyncio.StreamReader) -> dict[str, object]:
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        frame = decode_raw_uds_frame(header + await reader.readexactly(payload_length))
        return parse_raw_uds_server_frame(frame).model_dump(exclude_none=True)

    async def send_bad_frame_then_valid_client() -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(raw_socket_path))
        writer.write(b"\xff\x00\x00\x00\x00")
        await writer.drain()
        error = await read_server_frame(reader)
        writer.close()
        await writer.wait_closed()

        client = AsyncRawUdsLocalSttClient(str(raw_socket_path))
        ready = await client.start(client_stream_id="after-bad-frame")
        await client.close()
        assert ready["metadata"]["client_stream_id"] == "after-bad-frame"
        return error

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as http_client:
        error = asyncio.run(send_bad_frame_then_valid_client())
        health = http_client.get("/health")

    assert error["type"] == "error"
    assert error["code"] == "raw_uds_unsupported_frame_type"
    assert health.status_code == 200
    assert health.json()["ready"] is True


def test_raw_uds_malformed_json_control_does_not_stop_listener(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))

    async def read_server_frame(reader: asyncio.StreamReader) -> dict[str, object]:
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        frame = decode_raw_uds_frame(header + await reader.readexactly(payload_length))
        return parse_raw_uds_server_frame(frame).model_dump(exclude_none=True)

    async def send_malformed_control_then_valid_client() -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(raw_socket_path))
        writer.write(bytes([RawUdsFrameType.JSON_CONTROL]) + (1).to_bytes(4, "little") + b"{")
        await writer.drain()
        error = await read_server_frame(reader)
        writer.close()
        await writer.wait_closed()

        client = AsyncRawUdsLocalSttClient(str(raw_socket_path))
        ready = await client.start(client_stream_id="after-malformed-json")
        await client.close()
        assert ready["metadata"]["client_stream_id"] == "after-malformed-json"
        return error

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as http_client:
        error = asyncio.run(send_malformed_control_then_valid_client())
        health = http_client.get("/health")

    assert error["type"] == "error"
    assert error["code"] == "raw_uds_malformed_json_control"
    assert error["metadata"] == {"original_code": "raw_uds_invalid_json"}
    assert health.status_code == 200
    assert health.json()["ready"] is True


def test_raw_uds_rejects_unknown_frame_type_before_waiting_for_payload(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))

    async def read_server_frame(reader: asyncio.StreamReader) -> dict[str, object]:
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        frame = decode_raw_uds_frame(header + await reader.readexactly(payload_length))
        return parse_raw_uds_server_frame(frame).model_dump(exclude_none=True)

    async def send_unknown_header_without_payload() -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(raw_socket_path))
        writer.write(b"\xff" + (RAW_UDS_MAX_PAYLOAD_BYTES).to_bytes(4, "little"))
        await writer.drain()
        error = await asyncio.wait_for(read_server_frame(reader), timeout=0.5)
        writer.close()
        await writer.wait_closed()
        return error

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as http_client:
        error = asyncio.run(send_unknown_header_without_payload())
        health = http_client.get("/health")

    assert error["type"] == "error"
    assert error["code"] == "raw_uds_unsupported_frame_type"
    assert health.status_code == 200
    assert health.json()["ready"] is True


def test_raw_uds_rejects_oversized_payload_before_waiting_for_body(tmp_path: Path) -> None:
    raw_socket_path = tmp_path / "stt.raw.sock"
    config = AppConfig(local_stt_raw_uds_enabled=True, local_stt_raw_uds_path=str(raw_socket_path))

    async def read_server_frame(reader: asyncio.StreamReader) -> dict[str, object]:
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        frame = decode_raw_uds_frame(header + await reader.readexactly(payload_length))
        return parse_raw_uds_server_frame(frame).model_dump(exclude_none=True)

    async def send_oversized_header_without_payload() -> dict[str, object]:
        reader, writer = await asyncio.open_unix_connection(str(raw_socket_path))
        writer.write(bytes([RawUdsFrameType.JSON_CONTROL]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little"))
        await writer.drain()
        error = await asyncio.wait_for(read_server_frame(reader), timeout=0.5)
        writer.close()
        await writer.wait_closed()
        return error

    with TestClient(create_app(config=config, transcriber=FakeTranscriber())) as http_client:
        error = asyncio.run(send_oversized_header_without_payload())
        health = http_client.get("/health")

    assert error["type"] == "error"
    assert error["code"] == "raw_uds_payload_too_large"
    assert health.status_code == 200
    assert health.json()["ready"] is True


def test_ready_returns_503_when_preload_is_degraded() -> None:
    transcriber = FailingPreloadTranscriber(ASRUnavailableError("backend unavailable"))
    config = AppConfig(asr_preload_model=True, asr_fail_fast=False)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        health = client.get("/health")
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert health.status_code == 200
    assert health.json() == {
        "status": "degraded",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "ready": False,
        "model_loaded": False,
        "preload_enabled": True,
        "preload_error": "backend unavailable",
        "protocols": DEFAULT_PROTOCOLS,
    }
    assert ready.status_code == 503
    assert ready.json() == {
        "status": "degraded",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "ready": False,
        "model_loaded": False,
        "preload_enabled": True,
        "preload_error": "backend unavailable",
        "protocols": DEFAULT_PROTOCOLS,
    }
    assert models.status_code == 200
    assert models.json()["status"] == "degraded"
    assert models.json()["ready"] is False
    assert models.json()["preload_error"] == "backend unavailable"
    assert models.json()["models"][0]["loaded"] is False


def test_ready_recovers_after_successful_transcription() -> None:
    transcriber = RecoveringPreloadTranscriber()
    config = AppConfig(asr_preload_model=True, asr_fail_fast=False)
    fixture_bytes = FIXTURE_PATH.read_bytes()

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        degraded_health = client.get("/health")
        degraded_ready = client.get("/ready")
        degraded_models = client.get("/api/models")
        transcribe = client.post(
            "/api/transcribe",
            json={
                "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                "language": "en",
                "sample_rate": 16000,
            },
        )
        recovered_health = client.get("/health")
        recovered_ready = client.get("/ready")
        recovered_models = client.get("/api/models")

    assert degraded_health.status_code == 200
    assert degraded_health.json()["status"] == "degraded"
    assert degraded_health.json()["ready"] is False
    assert degraded_health.json()["preload_error"] == "model download failed"
    assert degraded_ready.status_code == 503
    assert degraded_ready.json()["preload_error"] == "model download failed"
    assert degraded_ready.json()["status"] == "degraded"
    assert degraded_models.status_code == 200
    assert degraded_models.json()["status"] == "degraded"
    assert degraded_models.json()["ready"] is False
    assert degraded_models.json()["preload_error"] == "model download failed"
    assert degraded_models.json()["models"][0]["loaded"] is False
    assert transcribe.status_code == 200
    assert recovered_health.status_code == 200
    assert recovered_health.json()["status"] == "ready"
    assert recovered_health.json()["ready"] is True
    assert recovered_health.json()["preload_error"] is None
    assert recovered_health.json()["model_loaded"] is True
    assert recovered_ready.status_code == 200
    assert recovered_ready.json()["status"] == "ready"
    assert recovered_ready.json()["ready"] is True
    assert recovered_ready.json()["preload_error"] is None
    assert recovered_ready.json()["model_loaded"] is True
    assert recovered_models.status_code == 200
    assert recovered_models.json()["status"] == "ready"
    assert recovered_models.json()["ready"] is True
    assert recovered_models.json()["preload_error"] is None
    assert recovered_models.json()["models"][0]["loaded"] is True


def test_fail_fast_raises_for_non_asr_preload_failures() -> None:
    transcriber = FailingPreloadTranscriber(RuntimeError("invalid device"))
    config = AppConfig(asr_preload_model=True, asr_fail_fast=True)

    with pytest.raises(RuntimeError, match="invalid device"):
        with TestClient(create_app(config=config, transcriber=transcriber)):
            pass


def test_lazy_load_runtime_failure_marks_service_degraded() -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    transcriber = BrokenLazyLoadTranscriber()
    config = AppConfig(asr_preload_model=False)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        response = client.post(
            "/api/transcribe",
            json={
                "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                "language": "en",
                "sample_rate": 16000,
            },
        )
        health = client.get("/health")
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert response.status_code == 500
    assert response.json() == {"detail": "invalid device"}
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["ready"] is False
    assert health.json()["preload_error"] == "invalid device"
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["preload_error"] == "invalid device"
    assert models.status_code == 200
    assert models.json()["status"] == "degraded"
    assert models.json()["ready"] is False
    assert models.json()["preload_error"] == "invalid device"
    assert models.json()["models"][0]["loaded"] is False


def test_websocket_lazy_load_runtime_failure_marks_service_degraded() -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    transcriber = BrokenLazyLoadTranscriber()
    config = AppConfig(asr_preload_model=False)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"
            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                }
            )
            error_event = websocket.receive_json()

        health = client.get("/health")
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert error_event == {
        "type": "error",
        "message": "Unexpected streaming error",
        "code": 1011,
    }
    assert health.status_code == 200
    assert health.json()["status"] == "degraded"
    assert health.json()["ready"] is False
    assert health.json()["preload_error"] == "invalid device"
    assert ready.status_code == 503
    assert ready.json()["status"] == "degraded"
    assert ready.json()["preload_error"] == "invalid device"
    assert models.status_code == 200
    assert models.json()["status"] == "degraded"
    assert models.json()["ready"] is False
    assert models.json()["preload_error"] == "invalid device"
    assert models.json()["models"][0]["loaded"] is False


def test_transcribe_smoke_fixture() -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        response = client.post(
            "/api/transcribe",
            json={
                "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                "language": "en",
                "sample_rate": 16000,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "fixture transcription 1",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(fixture_bytes),
            "language": "en",
            "sample_rate": 16000,
            "prefix": b"RIFF",
        }
    ]


def test_websocket_stream_emits_partial_and_final_events() -> None:
    transcriber = FakeTranscriber()
    chunk_one = b"first chunk"
    chunk_two = b" second chunk"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
            })
            ready = websocket.receive_json()
            assert ready == {
                "type": "ready",
                "stream_id": 1,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "en",
                "sample_rate": 16000,
                "partial_interval_chunks": 1,
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
            }

            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(chunk_one).decode("ascii"),
            })
            partial = websocket.receive_json()
            assert partial == {
                "type": "partial",
                "stream_id": 1,
                "is_final": False,
                "chunks_received": 1,
                "buffered_bytes": len(chunk_one),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one),
                "text": "fixture transcription 1",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(chunk_two).decode("ascii"),
            })
            partial = websocket.receive_json()
            assert partial == {
                "type": "partial",
                "stream_id": 1,
                "is_final": False,
                "chunks_received": 2,
                "buffered_bytes": len(chunk_one) + len(chunk_two),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one) - len(chunk_two),
                "text": "fixture transcription 2",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()
            assert final_event == {
                "type": "final",
                "stream_id": 1,
                "is_final": True,
                "chunks_received": 2,
                "buffered_bytes": len(chunk_one) + len(chunk_two),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one) - len(chunk_two),
                "text": "fixture transcription 2",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

    assert transcriber.calls == [
        {
            "audio_size": len(chunk_one),
            "language": "en",
            "sample_rate": 16000,
            "prefix": chunk_one[:4],
        },
        {
            "audio_size": len(chunk_one) + len(chunk_two),
            "language": "en",
            "sample_rate": 16000,
            "prefix": chunk_one[:4],
        },
    ]


def test_websocket_stream_accepts_binary_audio_frames() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(first_chunk)
            first_partial = websocket.receive_json()

            websocket.send_bytes(second_chunk)
            second_partial = websocket.receive_json()

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert first_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 1,
        "buffered_bytes": len(first_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
        "text": "fixture transcription 1",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert second_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {"audio_size": len(first_chunk), "language": "en", "sample_rate": 16000, "prefix": first_chunk[:4]},
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
    ]


def test_websocket_stream_reuses_connection_for_multiple_utterances() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            websocket.send_json({"type": "stop"})
            first_final = websocket.receive_json()
            assert first_final == {
                "type": "final",
                "stream_id": 1,
                "is_final": True,
                "chunks_received": 1,
                "buffered_bytes": len(first_chunk),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
                "text": "fixture transcription 1",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            second_ready = websocket.receive_json()
            assert second_ready == {
                "type": "ready",
                "stream_id": 2,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "es",
                "sample_rate": 8000,
                "partial_interval_chunks": 1,
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
            }

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            second_partial = websocket.receive_json()
            assert second_partial == {
                "type": "partial",
                "stream_id": 2,
                "is_final": False,
                "chunks_received": 1,
                "buffered_bytes": len(second_chunk),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(second_chunk),
                "text": "fixture transcription 2",
                "language": "es",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "stop"})
            second_final = websocket.receive_json()
            assert second_final == {
                "type": "final",
                "stream_id": 2,
                "is_final": True,
                "chunks_received": 1,
                "buffered_bytes": len(second_chunk),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(second_chunk),
                "text": "fixture transcription 2",
                "language": "es",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

    assert transcriber.calls == [
        {"audio_size": len(first_chunk), "language": "en", "sample_rate": 16000, "prefix": first_chunk[:4]},
        {"audio_size": len(second_chunk), "language": "es", "sample_rate": 8000, "prefix": second_chunk[:4]},
    ]


def test_websocket_stream_cancel_resets_state_without_transcribing() -> None:
    transcriber = FakeTranscriber()
    chunk = b"first!"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            websocket.send_json({"type": "cancel"})
            canceled = websocket.receive_json()
            assert canceled == {
                "type": "canceled",
                "stream_id": 1,
                "chunks_received": 1,
                "buffered_bytes": len(chunk),
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk),
            }

            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            second_ready = websocket.receive_json()
            assert second_ready == {
                "type": "ready",
                "stream_id": 2,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "es",
                "sample_rate": 8000,
                "partial_interval_chunks": 1,
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
            }

    assert transcriber.calls == [
        {"audio_size": len(chunk), "language": "en", "sample_rate": 16000, "prefix": chunk[:4]},
    ]


def test_websocket_stream_rejects_start_while_another_stream_is_active() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Finish the active stream before starting a new one",
        "code": 1003,
    }
    assert transcriber.calls == []


def test_websocket_stream_ids_reset_for_a_new_connection() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            first_ready = websocket.receive_json()

        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            second_ready = websocket.receive_json()

    assert first_ready["stream_id"] == 1
    assert second_ready["stream_id"] == 1
    assert first_ready["language"] == "en"
    assert second_ready["language"] == "es"


def test_websocket_stream_retranscribes_on_stop_when_partial_interval_skips_latest_chunk() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 2,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            third_chunk = b"third"
            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(third_chunk).decode("ascii"),
                }
            )
            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 3,
        "buffered_bytes": len(first_chunk) + len(second_chunk) + len(third_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk) - len(third_chunk),
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
        {
            "audio_size": len(first_chunk) + len(second_chunk) + len(third_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
    ]


def test_local_stt_v1_partial_interval_chunks_remains_supported() -> None:
    transcriber = FakeTranscriber()
    chunk = b"x" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_chunks": 2,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            websocket.send_bytes(chunk)
            partial_message = parse_server_message(websocket.receive_json())

    assert partial_message.type == "transcript"
    assert partial_message.is_final is False
    assert partial_message.metadata["chunks_received"] == 2
    assert transcriber.calls == [
        {
            "audio_size": len(chunk) * 2,
            "language": None,
            "sample_rate": HOT_PATH_SAMPLE_RATE,
            "prefix": chunk[:4],
        }
    ]


def test_local_stt_v1_partial_interval_chunks_still_emit_after_batched_audio() -> None:
    session = StreamSession(
        stream_id=1,
        language=None,
        sample_rate=HOT_PATH_SAMPLE_RATE,
        max_buffer_bytes=HOT_PATH_BYTES_PER_FRAME * 8,
        partial_interval_chunks=2,
    )
    chunk = b"z" * HOT_PATH_BYTES_PER_FRAME

    session.append_audio(chunk)
    session.append_audio(chunk)
    session.append_audio(chunk)

    assert session.should_emit_partial() is True

    session.record_partial({"text": "steady partial"})
    session.append_audio(chunk)

    assert session.should_emit_partial() is False


def test_local_stt_v1_partial_interval_ms_takes_priority_over_chunks() -> None:
    transcriber = FakeTranscriber()
    chunk = b"y" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_chunks": 10,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            partial_message = parse_server_message(websocket.receive_json())

    assert partial_message.type == "transcript"
    assert partial_message.metadata["chunks_received"] == 1


def test_local_stt_v1_partial_interval_uses_audio_duration_for_batched_frames() -> None:
    transcriber = FakeTranscriber()
    hundred_ms_pcm = b"x" * (HOT_PATH_BYTES_PER_FRAME * 5)

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_ms": 100,
                }
            )
            websocket.receive_json()

            websocket.send_bytes(hundred_ms_pcm)
            partial_message = parse_server_message(websocket.receive_json())

            assert partial_message.type == "transcript"
            assert partial_message.is_final is False
            assert partial_message.audio_received_ms == 100
            assert partial_message.audio_transcribed_ms == 100
            assert partial_message.metadata["chunks_received"] == 1

    assert transcriber.calls == [
        {
            "audio_size": len(hundred_ms_pcm),
            "language": None,
            "sample_rate": HOT_PATH_SAMPLE_RATE,
            "prefix": hundred_ms_pcm[:4],
        }
    ]


def test_local_stt_v1_stream_accepts_flat_start_binary_audio_and_finalize() -> None:
    transcriber = FakeTranscriber()
    chunk = b"f" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                    "client_stream_id": "turn-1",
                    "metadata": {"turn_id": "turn-1", "tenant": "demo"},
                }
            )
            ready = websocket.receive_json()
            ready_message = parse_server_message(ready)
            assert ready_message.type == "ready"
            assert ready_message.version == PROTOCOL_VERSION
            assert ready_message.audio.bytes_per_frame == HOT_PATH_BYTES_PER_FRAME
            assert ready_message.metadata == {
                "stream_id": 1,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
                "client_stream_id": "turn-1",
                "client_metadata": {"turn_id": "turn-1", "tenant": "demo"},
            }

            websocket.send_bytes(chunk)
            partial = websocket.receive_json()
            partial_message = parse_server_message(partial)
            assert partial_message.type == "transcript"
            assert partial_message.is_final is False
            assert partial_message.speech_final is False
            assert partial_message.revision == 1
            assert partial_message.audio_received_ms == round((len(chunk) / 2) * 1000 / HOT_PATH_SAMPLE_RATE)
            assert partial_message.audio_transcribed_ms == partial_message.audio_received_ms
            assert partial_message.metadata["stream_id"] == 1
            assert partial_message.metadata["client_stream_id"] == "turn-1"
            assert partial_message.metadata["client_metadata"] == {"turn_id": "turn-1", "tenant": "demo"}

            websocket.send_json({"type": "finalize"})
            final_event = websocket.receive_json()
            final_message = parse_server_message(final_event)
            assert final_message.type == "transcript"
            assert final_message.is_final is True
            assert final_message.speech_final is True
            assert final_message.revision == 2
            assert final_message.text == "fixture transcription 1"
            assert final_message.metadata["stream_id"] == 1
            assert final_message.metadata["client_stream_id"] == "turn-1"
            assert final_message.metadata["client_metadata"] == {"turn_id": "turn-1", "tenant": "demo"}

            websocket.send_json(
                {
                    "type": "start",
                    "version": PROTOCOL_VERSION,
                    "audio": {
                        "sample_rate": HOT_PATH_SAMPLE_RATE,
                        "channels": HOT_PATH_CHANNELS,
                        "format": HOT_PATH_PCM_FORMAT,
                        "frame_ms": HOT_PATH_FRAME_MS,
                        "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
                    },
                }
            )
            second_ready = websocket.receive_json()
            assert second_ready["type"] == "ready"
            assert second_ready["metadata"]["stream_id"] == 2


def test_local_stt_v1_stream_ignores_extra_top_level_fields_on_nested_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "version": PROTOCOL_VERSION,
                    "audio": {
                        "sample_rate": HOT_PATH_SAMPLE_RATE,
                        "channels": HOT_PATH_CHANNELS,
                        "format": HOT_PATH_PCM_FORMAT,
                        "frame_ms": HOT_PATH_FRAME_MS,
                        "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
                    },
                    "sample_rate": 8000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 40,
                    "protocol": "not-local-stt-v1",
                    "metadata": {"turn_id": "nested-extra"},
                }
            )
            ready = parse_server_message(websocket.receive_json())

    assert ready.type == "ready"
    assert ready.audio.sample_rate == HOT_PATH_SAMPLE_RATE
    assert ready.audio.frame_ms == HOT_PATH_FRAME_MS
    assert ready.metadata["client_metadata"] == {"turn_id": "nested-extra"}
    assert transcriber.calls == []


def test_local_stt_v1_stream_stop_is_a_finalize_alias() -> None:
    transcriber = FakeTranscriber()
    chunk = b"steady"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            assert websocket.receive_json()["type"] == "transcript"

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert final_event["type"] == "transcript"
    assert final_event["is_final"] is True
    assert transcriber.calls == [
        {"audio_size": len(chunk), "language": None, "sample_rate": HOT_PATH_SAMPLE_RATE, "prefix": chunk[:4]}
    ]


def test_local_stt_v1_stream_cancel_clears_buffer_and_suppresses_final_transcription() -> None:
    transcriber = FakeTranscriber()
    chunk = b"first!"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            assert websocket.receive_json()["type"] == "transcript"

            websocket.send_json({"type": "cancel"})
            warning = websocket.receive_json()
            assert warning == {
                "type": "warning",
                "code": "stream_canceled",
                "message": "Active utterance canceled",
                "metadata": {
                    "stream_id": 1,
                    "chunks_received": 1,
                    "buffered_bytes": 0,
                    "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
                },
                "retryable": False,
            }

            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                }
            )
            second_ready = websocket.receive_json()

    assert second_ready["metadata"]["stream_id"] == 2
    assert transcriber.calls == [
        {"audio_size": len(chunk), "language": None, "sample_rate": HOT_PATH_SAMPLE_RATE, "prefix": chunk[:4]}
    ]


def test_local_stt_v1_stream_rejects_audio_that_exceeds_buffer_limit() -> None:
    transcriber = FakeTranscriber()
    config = AppConfig(stream_max_buffer_bytes=8)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(b"overflow!!")
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "code": "buffer_limit_exceeded",
        "message": "Stream buffer exceeded 8 bytes; send stop and start a new stream",
        "metadata": {"max_buffer_bytes": 8},
        "retryable": False,
        "fatal": True,
    }
    assert transcriber.calls == []


def test_local_stt_v1_closes_when_worker_lazy_load_fails() -> None:
    transcriber = UnavailableLazyLoadTranscriber()
    chunk = b"u" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_chunks": 1,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            assert websocket.receive_json() == {
                "type": "error",
                "code": "backend_unavailable",
                "message": "backend unavailable",
                "metadata": {},
                "retryable": False,
                "fatal": True,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1011
    assert transcriber.calls == []


def test_local_stt_v1_receive_loop_accepts_audio_while_partial_decode_runs() -> None:
    transcriber = SleepingTranscriber(delay_seconds=0.2)
    chunk = b"a" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            send_started = time.perf_counter()
            for _ in range(10):
                websocket.send_bytes(chunk)
            send_elapsed = time.perf_counter() - send_started

            websocket.send_json({"type": "finalize"})
            final_event = parse_server_message(websocket.receive_json())
            while not final_event.is_final:
                final_event = parse_server_message(websocket.receive_json())

    assert send_elapsed < 0.15
    assert final_event.type == "transcript"
    assert final_event.is_final is True
    assert final_event.audio_received_ms == HOT_PATH_FRAME_MS * 10
    assert final_event.audio_transcribed_ms == HOT_PATH_FRAME_MS * 10
    assert transcriber.max_active_calls == 1
    assert transcriber.calls[-1]["audio_size"] == len(chunk) * 10


def test_local_stt_v1_emits_repeated_partials_after_first_decode() -> None:
    transcriber = FakeTranscriber()
    chunk = b"r" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            first_partial = parse_server_message(websocket.receive_json())
            websocket.send_bytes(chunk)
            second_partial = parse_server_message(websocket.receive_json())
            websocket.send_json({"type": "cancel"})
            websocket.receive_json()

    assert first_partial.type == "transcript"
    assert first_partial.is_final is False
    assert second_partial.type == "transcript"
    assert second_partial.is_final is False
    assert second_partial.audio_transcribed_ms == HOT_PATH_FRAME_MS * 2
    assert len(transcriber.calls) == 2


def test_local_stt_v1_emits_inflight_partial_while_audio_continues() -> None:
    transcriber = SleepingTranscriber(delay_seconds=0.1)
    chunk = b"p" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            time.sleep(0.02)
            for _ in range(5):
                websocket.send_bytes(chunk)
                time.sleep(0.01)

            partial_event = parse_server_message(websocket.receive_json())
            websocket.send_json({"type": "cancel"})
            websocket.receive_json()

    assert partial_event.type == "transcript"
    assert partial_event.is_final is False
    assert partial_event.audio_transcribed_ms == HOT_PATH_FRAME_MS
    assert partial_event.audio_received_ms > partial_event.audio_transcribed_ms
    assert transcriber.max_active_calls == 1


def test_local_stt_v1_runs_at_most_one_partial_decode_per_stream() -> None:
    transcriber = SleepingTranscriber(delay_seconds=0.05)
    chunk = b"m" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            first_partial = parse_server_message(websocket.receive_json())
            assert first_partial.type == "transcript"
            assert first_partial.is_final is False

            for _ in range(3):
                websocket.send_bytes(chunk)
            time.sleep(0.12)

            assert transcriber.max_active_calls == 1

            websocket.send_json({"type": "finalize"})
            final_event = parse_server_message(websocket.receive_json())
            while not final_event.is_final:
                final_event = parse_server_message(websocket.receive_json())

    assert final_event.type == "transcript"
    assert final_event.is_final is True
    assert final_event.audio_received_ms == HOT_PATH_FRAME_MS * 4
    assert final_event.audio_transcribed_ms == HOT_PATH_FRAME_MS * 4
    assert transcriber.max_active_calls == 1
    assert [call["audio_size"] for call in transcriber.calls] == [len(chunk), len(chunk) * 2, len(chunk) * 4]


def test_local_stt_v1_finalize_suppresses_inflight_stale_partial() -> None:
    transcriber = SleepingTranscriber(delay_seconds=0.05)
    chunk = b"b" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            websocket.send_json({"type": "finalize"})
            final_event = parse_server_message(websocket.receive_json())

    assert final_event.type == "transcript"
    assert final_event.is_final is True
    assert final_event.revision == 1
    assert transcriber.max_active_calls == 1
    assert len(transcriber.calls) == 1


def test_local_stt_v1_cancel_suppresses_inflight_partial_result() -> None:
    transcriber = SleepingTranscriber(delay_seconds=0.1)
    chunk = b"c" * HOT_PATH_BYTES_PER_FRAME

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "protocol": "local-stt-v1",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "partial_interval_ms": HOT_PATH_FRAME_MS,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(chunk)
            websocket.send_json({"type": "cancel"})
            warning = websocket.receive_json()

    assert warning["type"] == "warning"
    assert warning["code"] == "stream_canceled"
    assert transcriber.max_active_calls == 1


def test_local_stt_v1_stream_pong_and_close_semantics() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json({"type": "ping", "ping_id": "heartbeat-1", "timestamp_ms": 1234})
            assert websocket.receive_json() == {
                "type": "pong",
                "metadata": {},
                "ping_id": "heartbeat-1",
                "timestamp_ms": 1234,
            }

            websocket.send_json({"type": "close"})
            assert websocket.receive_json() == {
                "type": "closed",
                "reason": "client_close",
                "metadata": {},
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1000
    assert transcriber.calls == []


def test_local_stt_v1_stream_emits_json_error_before_close() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/v1/stt/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                }
            )
            assert websocket.receive_json() == {
                "type": "error",
                "code": "invalid_message",
                "message": "protocol must be local-stt-v1",
                "metadata": {},
                "retryable": False,
                "fatal": True,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1003
    assert transcriber.calls == []


def test_legacy_env_aliases_and_cuda_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_NAME", "small.en")
    monkeypatch.delenv("ASR_MODEL_SIZE", raising=False)
    monkeypatch.setenv("AUDIO_SAMPLE_RATE", "22050")
    monkeypatch.delenv("SAMPLE_RATE", raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.delenv("ASR_DEVICE", raising=False)

    config = AppConfig.from_env()

    assert config.asr_model_size == "small.en"
    assert config.sample_rate == 22050
    assert config.asr_device == "cuda"


@pytest.mark.parametrize("invalid_value", ["0", "-1"])
def test_stream_max_buffer_bytes_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: str,
) -> None:
    monkeypatch.setenv("STREAM_MAX_BUFFER_BYTES", invalid_value)

    with pytest.raises(ValueError, match="STREAM_MAX_BUFFER_BYTES must be a positive integer"):
        AppConfig.from_env()




def test_local_stt_socket_mode_env_defaults_to_tcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOCAL_STT_SOCKET_MODE", raising=False)
    monkeypatch.delenv("LOCAL_STT_UDS_PATH", raising=False)
    monkeypatch.delenv("LOCAL_STT_RAW_UDS_PATH", raising=False)

    config = AppConfig.from_env()

    assert config.local_stt_socket_mode == "tcp"
    assert config.local_stt_uds_path == "/run/rtc-asr/stt.sock"
    assert config.local_stt_raw_uds_path == "/run/rtc-asr/stt.raw.sock"


def test_local_stt_socket_mode_env_supports_uds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    socket_path = tmp_path / "stt.sock"
    raw_socket_path = tmp_path / "stt.raw.sock"
    monkeypatch.setenv("LOCAL_STT_SOCKET_MODE", "uds")
    monkeypatch.setenv("LOCAL_STT_UDS_PATH", str(socket_path))
    monkeypatch.setenv("LOCAL_STT_RAW_UDS_PATH", str(raw_socket_path))

    config = AppConfig.from_env()

    assert config.local_stt_socket_mode == "uds"
    assert config.local_stt_uds_path == str(socket_path)
    assert config.local_stt_raw_uds_path == str(raw_socket_path)


def test_local_stt_raw_uds_path_rejects_empty_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_STT_RAW_UDS_PATH", "   ")

    with pytest.raises(ValueError, match="LOCAL_STT_RAW_UDS_PATH must not be empty"):
        AppConfig.from_env()


def test_local_stt_socket_mode_rejects_invalid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCAL_STT_SOCKET_MODE", "named-pipe")

    with pytest.raises(ValueError, match="LOCAL_STT_SOCKET_MODE must be 'tcp' or 'uds'"):
        AppConfig.from_env()


def test_prepare_uds_socket_removes_stale_socket(tmp_path: Path) -> None:
    socket_path = tmp_path / "run" / "stt.sock"
    socket_path.parent.mkdir()
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
    finally:
        server.close()

    assert socket_path.exists()

    prepared = _prepare_uds_socket(str(socket_path))

    assert prepared == str(socket_path)
    assert not socket_path.exists()


def test_prepare_uds_socket_rejects_non_socket_file(tmp_path: Path) -> None:
    socket_path = tmp_path / "stt.sock"
    socket_path.write_text("not a socket", encoding="utf-8")

    with pytest.raises(RuntimeError, match="exists and is not a socket"):
        _prepare_uds_socket(str(socket_path))


def test_prepare_uds_socket_reports_unwritable_parent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    socket_path = tmp_path / "run" / "stt.sock"

    def deny_mkdir(self: Path, *args: object, **kwargs: object) -> None:
        raise PermissionError("read-only parent")

    monkeypatch.setattr(Path, "mkdir", deny_mkdir)

    with pytest.raises(RuntimeError, match="Cannot create LOCAL_STT_UDS_PATH parent directory"):
        _prepare_uds_socket(str(socket_path))


def test_prepare_uds_socket_reports_unremovable_stale_socket(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    socket_path = tmp_path / "stt.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
    finally:
        server.close()

    def deny_unlink(self: Path) -> None:
        raise PermissionError("sticky directory")

    monkeypatch.setattr(Path, "unlink", deny_unlink)

    with pytest.raises(RuntimeError, match="Cannot remove stale LOCAL_STT_UDS_PATH socket"):
        _prepare_uds_socket(str(socket_path))


def test_main_runs_uvicorn_with_uds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    socket_path = tmp_path / "stt.sock"
    monkeypatch.setenv("LOCAL_STT_SOCKET_MODE", "uds")
    monkeypatch.setenv("LOCAL_STT_UDS_PATH", str(socket_path))
    monkeypatch.setattr(
        "src.main.uvicorn.run",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    main()

    assert calls == [{"args": ("src.main:app",), "kwargs": {"uds": str(socket_path), "log_level": "info"}}]


def test_main_keeps_tcp_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.delenv("LOCAL_STT_SOCKET_MODE", raising=False)
    monkeypatch.delenv("LOCAL_STT_UDS_PATH", raising=False)
    monkeypatch.setattr(
        "src.main.uvicorn.run",
        lambda *args, **kwargs: calls.append({"args": args, "kwargs": kwargs}),
    )

    main()

    assert calls == [
        {
            "args": ("src.main:app",),
            "kwargs": {"host": "0.0.0.0", "port": 8080, "log_level": "info"},
        }
    ]

def test_app_config_defaults_to_base_en() -> None:
    assert AppConfig().asr_model_size == "base.en"


def test_receive_stream_event_keeps_binary_audio_bytes() -> None:
    payload, event_type = asyncio.run(
        _receive_stream_event(FakeIncomingWebSocket({"type": "websocket.receive", "bytes": b"frame-bytes"}), object())
    )

    assert event_type == "audio"
    assert payload == {"audio_bytes": b"frame-bytes"}


def test_websocket_rejects_audio_before_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(b"premature").decode("ascii"),
            })
            assert websocket.receive_json() == {
                "type": "error",
                "message": "Send a start event before audio chunks",
                "code": 1003,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1003
    assert transcriber.calls == []


def test_websocket_rejects_duplicate_start_events() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json({
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
            })
            assert websocket.receive_json() == {
                "type": "error",
                "message": "Finish the active stream before starting a new one",
                "code": 1003,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1003
    assert transcriber.calls == []


def test_websocket_stream_emits_partial_updates_when_text_is_stable() -> None:
    transcriber = StableTextTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            first_partial = websocket.receive_json()

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            second_partial = websocket.receive_json()

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert first_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 1,
        "buffered_bytes": len(first_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert second_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(first_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
    ]


def test_websocket_stream_applies_partial_window_and_max_buffer_overrides() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"abcd"
    second_chunk = b"efgh"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 4,
                    "partial_interval_chunks": 1,
                    "partial_window_seconds": 0.5,
                    "max_buffer_seconds": 1.0,
                }
            )
            ready = websocket.receive_json()
            assert ready == {
                "type": "ready",
                "stream_id": 1,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "en",
                "sample_rate": 4,
                "partial_interval_chunks": 1,
                "partial_window_seconds": 0.5,
                "max_buffer_seconds": 1.0,
                "max_buffer_bytes": 8,
            }

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            second_partial = websocket.receive_json()

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert second_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": 0,
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "remaining_buffer_bytes": 0,
        "text": "fixture transcription 3",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(first_chunk),
            "language": "en",
            "sample_rate": 4,
            "prefix": first_chunk[:4],
        },
        {
            "audio_size": len(second_chunk),
            "language": "en",
            "sample_rate": 4,
            "prefix": second_chunk[:4],
        },
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 4,
            "prefix": first_chunk[:4],
        },
    ]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [("partial_window_seconds", 0), ("max_buffer_seconds", -1)],
)
def test_websocket_stream_rejects_invalid_window_overrides(field_name: str, value: int) -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    field_name: value,
                }
            )
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": f"{field_name} must be a positive number",
        "code": 1003,
    }
    assert transcriber.calls == []


def test_seconds_to_buffer_bytes_returns_whole_pcm16_samples() -> None:
    assert _seconds_to_buffer_bytes(0.0001, 16000) == 4
    assert _seconds_to_buffer_bytes(0.5, 4) == 4


def test_websocket_stream_rejects_audio_that_exceeds_the_session_buffer_limit() -> None:
    transcriber = FakeTranscriber()
    config = AppConfig(stream_max_buffer_bytes=8)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(b"overflow!").decode("ascii"),
                }
            )
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Stream buffer exceeded 8 bytes; send stop and start a new stream",
        "code": 1009,
    }
    assert transcriber.calls == []


def test_websocket_stream_error_payload_includes_close_code() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "stop"})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Send a start event before stopping the stream",
        "code": 1003,
    }


def test_websocket_stream_rejects_cancel_before_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "cancel"})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Send a start event before canceling the stream",
        "code": 1003,
    }
    assert transcriber.calls == []


def test_websocket_stream_rejects_binary_audio_before_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_bytes(b"orphan-audio")
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Send a start event before audio chunks",
        "code": 1003,
    }
    assert transcriber.calls == []


def test_transcript_event_parses_remaining_buffer_bytes() -> None:
    event = TranscriptEvent.from_payload({
        "type": "partial",
        "text": "hel",
        "stream_id": 1,
        "buffered_bytes": 3,
        "remaining_buffer_bytes": 1021,
    })

    assert event.type == "partial"
    assert event.text == "hel"
    assert event.stream_id == 1
    assert event.buffered_bytes == 3
    assert event.remaining_buffer_bytes == 1021


def test_streaming_client_stops_after_error_event() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "error",
                        "message": "backend unavailable",
                        "code": 1011,
                    }
                ),
            ]
            self.sent: list[dict[str, object]] = []

        async def send(self, data: str) -> None:
            self.sent.append(json.loads(data))

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig(partial_event_timeout_seconds=0.01))

        assert [event.type for event in events] == ["ready", "error"]
        assert events[-1].text == "backend unavailable"
        assert client._websocket.sent == [
            {
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
                "partial_interval_chunks": 1,
            },
            {
                "type": "audio",
                "audio_data": base64.b64encode(b"hel").decode("ascii"),
            },
        ]

    asyncio.run(scenario())


def test_streaming_client_drains_stale_partial_before_final() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "partial",
                        "stream_id": 1,
                        "is_final": False,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hel",
                    }
                ),
                json.dumps(
                    {
                        "type": "final",
                        "stream_id": 1,
                        "is_final": True,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hello",
                    }
                ),
            ]
            self.recv_calls = 0
            self.sent: list[dict[str, object]] = []

        async def send(self, data: str) -> None:
            self.sent.append(json.loads(data))

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig(partial_event_timeout_seconds=0.01))

        assert [event.type for event in events] == ["ready", "final"]
        assert events[-1].text == "hello"

    asyncio.run(scenario())


def test_streaming_client_stops_after_model_download_error_event() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "error",
                        "message": "model download failed",
                        "code": 1011,
                    }
                ),
            ]
            self.sent: list[object] = []

        async def send(self, data: str | bytes) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig())

        assert [event.type for event in events] == ["ready", "error"]
        assert events[-1].text == "model download failed"
        assert client._websocket.sent == [
            json.dumps(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 1,
                }
            ),
            json.dumps(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(b"hel").decode("ascii"),
                }
            ),
        ]

    asyncio.run(scenario())


def test_stream_config_includes_stream_window_overrides() -> None:
    config = StreamConfig(partial_window_seconds=1.5, max_buffer_seconds=6.0)

    assert config.as_payload() == {
        "type": "start",
        "language": "en",
        "sample_rate": 16000,
        "partial_interval_chunks": 1,
        "partial_window_seconds": 1.5,
        "max_buffer_seconds": 6.0,
    }


def test_streaming_client_can_send_binary_audio_frames() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "partial",
                        "stream_id": 1,
                        "is_final": False,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hel",
                    }
                ),
                json.dumps(
                    {
                        "type": "final",
                        "stream_id": 1,
                        "is_final": True,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hello",
                    }
                ),
            ]
            self.sent: list[object] = []

        async def send(self, data: str | bytes) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        await client.transcribe_once([b"hel"], config=StreamConfig(send_binary_frames=True))

        assert client._websocket.sent == [
            json.dumps(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 1,
                }
            ),
            b"hel",
            json.dumps({"type": "stop"}),
        ]

    asyncio.run(scenario())


def test_streaming_client_can_cancel_a_stream() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "partial",
                        "stream_id": 1,
                        "is_final": False,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hel",
                    }
                ),
                json.dumps(
                    {
                        "type": "canceled",
                        "stream_id": 1,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "remaining_buffer_bytes": 1021,
                    }
                ),
            ]
            self.recv_calls = 0
            self.sent: list[object] = []

        async def send(self, data: str | bytes) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            self.recv_calls += 1
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        event = await client.cancel_stream()

        assert event.type == "canceled"
        assert event.stream_id == 1
        assert event.remaining_buffer_bytes == 1021
        assert client._websocket.recv_calls == 2
        assert client._websocket.sent == [json.dumps({"type": "cancel"})]

    asyncio.run(scenario())


def test_stream_config_rejects_invalid_partial_interval_chunks() -> None:
    with pytest.raises(ValueError, match='partial_interval_chunks must be a positive integer'):
        StreamConfig(partial_interval_chunks=0)


def test_stream_config_rejects_negative_partial_event_timeout() -> None:
    with pytest.raises(ValueError, match='partial_event_timeout_seconds must be zero or greater'):
        StreamConfig(partial_event_timeout_seconds=-0.1)


@pytest.mark.parametrize("value", [0, True, float("inf"), float("nan")])
def test_stream_config_rejects_invalid_partial_window_seconds(value: object) -> None:
    with pytest.raises(ValueError, match='partial_window_seconds must be a positive finite number'):
        StreamConfig(partial_window_seconds=value)


@pytest.mark.parametrize("value", [0, True, float("inf"), float("nan")])
def test_stream_config_rejects_invalid_max_buffer_seconds(value: object) -> None:
    with pytest.raises(ValueError, match='max_buffer_seconds must be a positive finite number'):
        StreamConfig(max_buffer_seconds=value)
