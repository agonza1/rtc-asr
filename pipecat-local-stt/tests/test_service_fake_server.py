from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService
from pipecat_local_stt.pipecat_compat import (
    AudioRawFrame,
    FrameDirection,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat_local_stt.protocol import (
    LocalSTTProtocolError,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RawUdsFrameType,
    decode_raw_uds_frame,
    encode_raw_uds_frame,
    encode_raw_uds_json_frame,
)
from pipecat_local_stt.service import RawUdsConnectionAdapter, _default_connect


class FakeLocalSTTWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False
        self.finalize_count = 0

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, bytes):
            await self.incoming.put(json.dumps({
                "type": "transcript",
                "text": "hel",
                "is_final": False,
                "speech_final": False,
                "revision": 1,
                "audio_received_ms": 20,
                "audio_transcribed_ms": 20,
                "metadata": {"local_stt_generation": self._current_generation()},
            }))
            return
        payload = json.loads(data)
        if payload["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready", "metadata": payload.get("metadata", {})}))
        elif payload["type"] == "finalize":
            self.finalize_count += 1
            await self.incoming.put(json.dumps({
                "type": "transcript",
                "text": "hello world",
                "is_final": True,
                "speech_final": True,
                "revision": 2,
                "audio_received_ms": 40,
                "audio_transcribed_ms": 40,
                "metadata": {"local_stt_generation": self._current_generation()},
            }))
        elif payload["type"] == "close":
            await self.incoming.put(json.dumps({"type": "closed", "reason": "client_close"}))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    def _current_generation(self) -> int:
        starts = [json.loads(item) for item in self.sent if isinstance(item, str) and json.loads(item)["type"] == "start"]
        if not starts:
            return 0
        metadata = starts[-1].get("metadata", {})
        return int(metadata.get("local_stt_generation", 0))


def capture_pushed_frames(service: LocalStreamingSTTService) -> list[tuple[Any, FrameDirection]]:
    frames: list[tuple[Any, FrameDirection]] = []
    original_push_frame = service.push_frame

    async def push_frame(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        frames.append((frame, direction))
        await original_push_frame(frame, direction)

    service.push_frame = push_frame  # type: ignore[method-assign]
    return frames


def pushed_frame_types(frames: list[tuple[Any, FrameDirection]]) -> list[type[Any]]:
    return [type(frame) for frame, _direction in frames]


async def wait_for(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


def test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping() -> None:
    asyncio.run(_test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping())


async def _test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping() -> None:
    websocket = FakeLocalSTTWebSocket()
    service = LocalStreamingSTTService(LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20), connect_fn=lambda _url: asyncio.sleep(0, websocket))
    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"x" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: InterimTranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: TranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.cleanup()

    sent_start = json.loads(next(item for item in websocket.sent if isinstance(item, str)))
    binary_messages = [item for item in websocket.sent if isinstance(item, bytes)]
    final_frames = [frame for frame, _ in pushed_frames if isinstance(frame, TranscriptionFrame)]

    assert sent_start["type"] == "start"
    assert sent_start["protocol"] == "local-stt-v1"
    assert sent_start["sample_rate"] == 16000
    assert binary_messages == [b"x" * 640]
    assert websocket.finalize_count == 1
    assert final_frames[-1].text == "hello world"
    assert final_frames[-1].finalized is True
    assert service.metrics.local_stt_audio_frames_sent_total == 1
    assert service.metrics.local_stt_interim_events_total == 1
    assert service.metrics.local_stt_final_events_total == 1

def test_config_validates_optional_uds_transport() -> None:
    config = LocalSTTConfig(transport="uds_ws", uds_path="/tmp/rtc-asr.sock")

    assert config.transport == "uds_ws"
    assert config.uds_path == "/tmp/rtc-asr.sock"


def test_config_validates_optional_raw_uds_transport() -> None:
    config = LocalSTTConfig(transport="raw_uds", uds_path="/tmp/rtc-asr.raw.sock")

    assert config.transport == "raw_uds"
    assert config.uds_path == "/tmp/rtc-asr.raw.sock"


def test_config_requires_uds_path_for_socket_transports() -> None:
    with pytest.raises(ValueError, match="uds_path is required"):
        LocalSTTConfig(transport="uds_ws")
    with pytest.raises(ValueError, match="uds_path is required"):
        LocalSTTConfig(transport="raw_uds")
    with pytest.raises(ValueError, match="only valid"):
        LocalSTTConfig(uds_path="/tmp/rtc-asr.sock")


def test_default_connect_uses_tcp_websocket_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def fake_connect(*args: Any, **kwargs: Any) -> FakeLocalSTTWebSocket:
        calls.append(("connect", args, kwargs))
        return FakeLocalSTTWebSocket()

    async def fake_unix_connect(*args: Any, **kwargs: Any) -> FakeLocalSTTWebSocket:
        calls.append(("unix_connect", args, kwargs))
        return FakeLocalSTTWebSocket()

    monkeypatch.setitem(
        sys.modules, "websockets", SimpleNamespace(connect=fake_connect, unix_connect=fake_unix_connect)
    )

    websocket = asyncio.run(_default_connect(LocalSTTConfig(url="ws://localhost:8080/v1/stt/stream")))

    assert isinstance(websocket, FakeLocalSTTWebSocket)
    assert calls == [("connect", ("ws://localhost:8080/v1/stt/stream",), {"max_size": 2**23})]


def test_default_connect_uses_unix_socket_for_uds_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def fake_connect(*args: Any, **kwargs: Any) -> FakeLocalSTTWebSocket:
        calls.append(("connect", args, kwargs))
        return FakeLocalSTTWebSocket()

    async def fake_unix_connect(*args: Any, **kwargs: Any) -> FakeLocalSTTWebSocket:
        calls.append(("unix_connect", args, kwargs))
        return FakeLocalSTTWebSocket()

    monkeypatch.setitem(
        sys.modules, "websockets", SimpleNamespace(connect=fake_connect, unix_connect=fake_unix_connect)
    )

    websocket = asyncio.run(
        _default_connect(
            LocalSTTConfig(
                transport="uds_ws",
                url="ws://localhost/v1/stt/stream",
                uds_path="/run/rtc-asr/stt.sock",
            )
        )
    )

    assert isinstance(websocket, FakeLocalSTTWebSocket)
    assert calls == [
        (
            "unix_connect",
            ("/run/rtc-asr/stt.sock",),
            {"uri": "ws://localhost/v1/stt/stream", "max_size": 2**23},
        )
    ]



class FakeRawUdsReader:
    def __init__(self, payload: bytes) -> None:
        self._payload = bytearray(payload)

    async def readexactly(self, size: int) -> bytes:
        if len(self._payload) < size:
            raise AssertionError(f"expected at least {size} bytes")
        chunk = bytes(self._payload[:size])
        del self._payload[:size]
        return chunk


class FakeRawUdsWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_default_connect_uses_raw_uds_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"}))
    calls: list[str] = []

    async def fake_open_unix_connection(path: str):
        calls.append(path)
        return reader, writer

    monkeypatch.setattr(asyncio, "open_unix_connection", fake_open_unix_connection)

    connection = asyncio.run(
        _default_connect(LocalSTTConfig(transport="raw_uds", uds_path="/run/rtc-asr/stt.raw.sock"))
    )
    asyncio.run(connection.send(json.dumps({"type": "start", "protocol": "local-stt-v1"})))
    asyncio.run(connection.send(b"pcm"))
    event = asyncio.run(connection.recv())
    asyncio.run(connection.close())

    control_frame = decode_raw_uds_frame(writer.writes[0])
    audio_frame = decode_raw_uds_frame(writer.writes[1])
    assert calls == ["/run/rtc-asr/stt.raw.sock"]
    assert control_frame.frame_type == RawUdsFrameType.JSON_CONTROL
    assert audio_frame.frame_type == RawUdsFrameType.AUDIO_PCM16
    assert audio_frame.payload == b"pcm"
    assert json.loads(event) == {"type": "ready"}
    assert writer.closed is True


def test_raw_uds_adapter_encodes_ping_as_ping_frame() -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(b"")
    connection = RawUdsConnectionAdapter(reader, writer)

    asyncio.run(connection.send(json.dumps({"type": "ping", "ping_id": "p1"})))

    ping_frame = decode_raw_uds_frame(writer.writes[0])
    assert ping_frame.frame_type == RawUdsFrameType.PING
    assert json.loads(ping_frame.payload.decode("utf-8")) == {"type": "ping", "ping_id": "p1"}


def test_raw_uds_adapter_decodes_empty_pong_frame() -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(encode_raw_uds_frame(RawUdsFrameType.PONG, b""))
    connection = RawUdsConnectionAdapter(reader, writer)

    event = asyncio.run(connection.recv())

    assert json.loads(event) == {"type": "pong"}


def test_raw_uds_adapter_decodes_empty_ping_frame() -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(encode_raw_uds_frame(RawUdsFrameType.PING, b""))
    connection = RawUdsConnectionAdapter(reader, writer)

    event = asyncio.run(connection.recv())

    assert json.loads(event) == {"type": "ping"}


def test_raw_uds_adapter_rejects_client_frame_types_from_server() -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x00"))
    connection = RawUdsConnectionAdapter(reader, writer)

    with pytest.raises(LocalSTTProtocolError, match="not a server frame") as excinfo:
        asyncio.run(connection.recv())

    assert excinfo.value.code == "raw_uds_invalid_server_frame_type"


def test_raw_uds_adapter_reports_oversized_payload_with_protocol_code() -> None:
    writer = FakeRawUdsWriter()
    header = bytes([RawUdsFrameType.JSON_EVENT]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little")
    reader = FakeRawUdsReader(header)
    connection = RawUdsConnectionAdapter(reader, writer)

    with pytest.raises(LocalSTTProtocolError, match="payload exceeds") as excinfo:
        asyncio.run(connection.recv())

    assert excinfo.value.code == "raw_uds_payload_too_large"


def test_raw_uds_adapter_maps_truncated_header_to_protocol_error() -> None:
    async def recv_truncated_header() -> None:
        writer = FakeRawUdsWriter()
        reader = asyncio.StreamReader()
        reader.feed_data(b"\x03\x02")
        reader.feed_eof()
        connection = RawUdsConnectionAdapter(reader, writer)
        await connection.recv()

    with pytest.raises(LocalSTTProtocolError, match="buffered frame bytes") as excinfo:
        asyncio.run(recv_truncated_header())

    assert excinfo.value.code == "raw_uds_incomplete_frame"


def test_raw_uds_adapter_maps_truncated_payload_to_protocol_error() -> None:
    async def recv_truncated_payload() -> None:
        writer = FakeRawUdsWriter()
        reader = asyncio.StreamReader()
        reader.feed_data(bytes([RawUdsFrameType.JSON_EVENT]) + (6).to_bytes(4, "little") + b'{"ty')
        reader.feed_eof()
        connection = RawUdsConnectionAdapter(reader, writer)
        await connection.recv()

    with pytest.raises(LocalSTTProtocolError, match="buffered frame bytes") as excinfo:
        asyncio.run(recv_truncated_payload())

    assert excinfo.value.code == "raw_uds_incomplete_frame"


def test_raw_uds_adapter_decodes_error_frame_without_json_type() -> None:
    writer = FakeRawUdsWriter()
    reader = FakeRawUdsReader(
        encode_raw_uds_json_frame(RawUdsFrameType.ERROR, {"message": "bad control frame"})
    )
    connection = RawUdsConnectionAdapter(reader, writer)

    event = asyncio.run(connection.recv())

    assert json.loads(event) == {"type": "error", "message": "bad control frame"}


def test_service_counts_raw_uds_error_frame_without_crashing() -> None:
    service = LocalStreamingSTTService()

    asyncio.run(service._handle_server_payload({"type": "error", "message": "bad control frame"}))

    assert service.metrics.local_stt_protocol_errors_total == 1


def test_service_ignores_server_heartbeat_events() -> None:
    service = LocalStreamingSTTService()

    asyncio.run(service._handle_server_payload({"type": "ping"}))
    asyncio.run(service._handle_server_payload({"type": "pong"}))

    assert service.metrics.local_stt_protocol_errors_total == 0
