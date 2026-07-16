from __future__ import annotations

import asyncio
import base64
import importlib
import json
import sys

import pytest

from src.protocols.local_stt_v1 import (
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RawUdsFrameType,
    decode_raw_uds_json_payload,
    decode_raw_uds_frame,
    encode_raw_uds_json_frame,
    LocalSttProtocolError,
)
from src.rtc_client import (
    AsyncASRClient,
    AsyncLocalSttClient,
    AsyncRawUdsLocalSttClient,
    LocalSTTConfig,
    _default_raw_uds_connect,
    build_async_local_stt_client,
)


class FakeWebSocket:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = [json.dumps(response) for response in responses]
        self.sent: list[object] = []
        self.closed_with: int | None = None

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            self.sent.append(data)
            return
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if not self.responses:
            raise RuntimeError('No fake websocket responses left')
        return self.responses.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def test_importing_rtc_client_does_not_load_main_module() -> None:
    sys.modules.pop("src", None)
    sys.modules.pop("src.main", None)
    sys.modules.pop("src.rtc_client", None)

    rtc_client = importlib.import_module("src.rtc_client")

    assert rtc_client.AsyncASRClient is not None
    assert rtc_client.AsyncLocalSttClient is not None
    assert "src.main" not in sys.modules


def test_async_asr_client_stream_flow() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 2,
            'partial_window_seconds': 1.5,
            'max_buffer_seconds': 6.0,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
        {
            'type': 'final',
            'is_final': True,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hello',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        ready_event = await client.start(
            language='en',
            sample_rate=16000,
            partial_interval_chunks=2,
            partial_window_seconds=1.5,
            max_buffer_seconds=6.0,
        )
        first_event = await client.send_audio(b'hel')
        second_event = await client.send_audio(b'lo')
        final_event = await client.stop()
        await client.close()

        assert ready_event['type'] == 'ready'
        assert first_event is None
        assert second_event is not None
        assert second_event.text == 'hel'
        assert second_event.is_final is False
        assert final_event.text == 'hello'
        assert final_event.is_final is True
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 2,
                'partial_window_seconds': 1.5,
                'max_buffer_seconds': 6.0,
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'hel').decode('ascii'),
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'lo').decode('ascii'),
            },
            {'type': 'stop'},
        ]
        assert websocket.closed_with == 1000

    asyncio.run(scenario())


def test_async_asr_client_can_send_binary_audio_frames() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
        {
            'type': 'final',
            'is_final': True,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hello',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start(send_binary_frames=True)
        partial_event = await client.send_audio(b'hel')
        final_event = await client.stop()
        await client.close()

        assert partial_event is not None
        assert partial_event.text == 'hel'
        assert final_event.text == 'hello'
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            b'hel',
            {'type': 'stop'},
        ]
        assert websocket.closed_with == 1000

    asyncio.run(scenario())


def test_async_local_stt_client_stream_flow() -> None:
    websocket = FakeWebSocket([
        {
            "type": "ready",
            "version": "local-stt.v1",
            "metadata": {"stream_id": 7},
        },
        {
            "type": "pong",
            "ping_id": "heartbeat-1",
            "timestamp_ms": 1234,
            "metadata": {},
        },
        {
            "type": "transcript",
            "text": "hel",
            "is_final": False,
            "speech_final": False,
            "revision": 1,
            "audio_received_ms": 120,
            "audio_transcribed_ms": 120,
            "metadata": {"stream_id": 7, "chunks_received": 1},
        },
        {
            "type": "warning",
            "code": "stream_canceled",
            "message": "Active utterance canceled",
            "metadata": {"stream_id": 7, "chunks_received": 2},
            "retryable": False,
        },
        {
            "type": "ready",
            "version": "local-stt.v1",
            "metadata": {"stream_id": 8},
        },
        {
            "type": "transcript",
            "text": "hello",
            "is_final": True,
            "speech_final": True,
            "revision": 1,
            "audio_received_ms": 120,
            "audio_transcribed_ms": 120,
            "metadata": {"stream_id": 8, "chunks_received": 1},
        },
        {
            "type": "closed",
            "reason": "client_close",
            "metadata": {},
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncLocalSttClient("ws://example.test/v1/stt/stream", connect_fn=fake_connect)
        ready_event = await client.start(
            client_stream_id="turn-1",
            partial_interval_ms=100,
            partial_window_seconds=1.5,
            max_buffer_seconds=6.0,
            metadata={"turn_id": "turn-1", "tenant": "demo"},
        )
        pong_event = await client.ping(ping_id="heartbeat-1", timestamp_ms=1234)
        await client.send_audio(b"hel")
        partial_event = await client.recv_event()
        await client.send_audio(b"lo")
        await client.cancel()
        canceled_event = await client.recv_event()
        second_ready_event = await client.start()
        await client.send_audio(b"lo")
        await client.finalize()
        final_event = await client.recv_event()
        closed_event = await client.close()

        assert ready_event["type"] == "ready"
        assert closed_event == {"type": "closed", "reason": "client_close", "metadata": {}}
        assert pong_event == {"type": "pong", "ping_id": "heartbeat-1", "timestamp_ms": 1234, "metadata": {}}
        assert partial_event is not None
        assert partial_event.type == "partial"
        assert partial_event.stream_id == 7
        assert partial_event.revision == 1
        assert canceled_event is not None
        assert canceled_event.type == "warning"
        assert canceled_event.stream_id == 7
        assert second_ready_event["metadata"]["stream_id"] == 8
        assert final_event is not None
        assert final_event.type == "final"
        assert final_event.speech_final is True
        assert final_event.stream_id == 8
        assert websocket.sent == [
            {
                "type": "start",
                "version": "local-stt.v1",
                "audio": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "bytes_per_frame": 640,
                },
                "language": "en",
                "interim_results": True,
                "partial_interval_ms": 100,
                "partial_window_seconds": 1.5,
                "max_buffer_seconds": 6.0,
                "client_stream_id": "turn-1",
                "metadata": {"turn_id": "turn-1", "tenant": "demo"},
            },
            {"type": "ping", "ping_id": "heartbeat-1", "timestamp_ms": 1234},
            b"hel",
            b"lo",
            {"type": "cancel"},
            {
                "type": "start",
                "version": "local-stt.v1",
                "audio": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "bytes_per_frame": 640,
                },
                "language": "en",
                "interim_results": True,
                "partial_interval_ms": 20,
            },
            b"lo",
            {"type": "finalize"},
            {"type": "close"},
        ]
        assert websocket.closed_with == 1000

    asyncio.run(scenario())



def test_local_stt_config_selects_websocket_and_raw_uds_clients() -> None:
    tcp_client = build_async_local_stt_client(LocalSTTConfig(url="ws://example.test/v1/stt/stream"))
    uds_ws_client = build_async_local_stt_client(
        LocalSTTConfig(transport="uds_ws", url="ws://example.test/v1/stt/stream", uds_path="/tmp/stt.sock")
    )
    raw_client = build_async_local_stt_client(LocalSTTConfig(transport="raw_uds", uds_path="/tmp/stt.raw.sock"))

    assert isinstance(tcp_client, AsyncLocalSttClient)
    assert isinstance(uds_ws_client, AsyncLocalSttClient)
    assert isinstance(raw_client, AsyncRawUdsLocalSttClient)
    assert raw_client.uds_path == "/tmp/stt.raw.sock"


def test_uds_ws_client_opens_unix_websocket(monkeypatch) -> None:
    calls: list[tuple[str, str, int]] = []
    websocket = object()

    async def fake_unix_connect(uds_path: str, *, uri: str, max_size: int):
        calls.append((uds_path, uri, max_size))
        return websocket

    monkeypatch.setitem(sys.modules, "websockets", type("FakeWebsockets", (), {"unix_connect": fake_unix_connect}))
    client = build_async_local_stt_client(
        LocalSTTConfig(transport="uds_ws", url="ws://example.test/v1/stt/stream", uds_path="/tmp/stt.sock")
    )

    assert asyncio.run(client.connect()) is websocket
    assert calls == [("/tmp/stt.sock", "ws://example.test/v1/stt/stream", 2**23)]


def test_uds_ws_client_reports_missing_unix_connect(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "websockets", type("FakeWebsockets", (), {}))
    client = build_async_local_stt_client(
        LocalSTTConfig(transport="uds_ws", url="ws://example.test/v1/stt/stream", uds_path="/tmp/stt.sock")
    )

    with pytest.raises(RuntimeError, match="uds_ws transport requires websockets.unix_connect"):
        asyncio.run(client.connect())


def test_local_stt_config_requires_socket_transport_path() -> None:
    with pytest.raises(ValueError, match="uds_path is required"):
        LocalSTTConfig(transport="uds_ws")
    with pytest.raises(ValueError, match="uds_path is required"):
        LocalSTTConfig(transport="raw_uds")


def test_local_stt_config_from_env_selects_raw_uds(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_STT_TRANSPORT", "raw_uds")
    monkeypatch.setenv("LOCAL_STT_URL", "ws://example.test/ignored")
    monkeypatch.setenv("LOCAL_STT_RAW_UDS_PATH", "/tmp/stt.raw.sock")

    config = LocalSTTConfig.from_env()

    assert config.transport == "raw_uds"
    assert config.url == "ws://example.test/ignored"
    assert config.uds_path == "/tmp/stt.raw.sock"


def test_local_stt_config_from_env_selects_uds_ws(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_STT_TRANSPORT", "uds_ws")
    monkeypatch.setenv("LOCAL_STT_URL", "ws://example.test/v1/stt/stream")
    monkeypatch.setenv("LOCAL_STT_UDS_PATH", "/tmp/stt.sock")

    config = LocalSTTConfig.from_env()

    assert config.transport == "uds_ws"
    assert config.url == "ws://example.test/v1/stt/stream"
    assert config.uds_path == "/tmp/stt.sock"


def test_local_stt_config_from_env_rejects_unknown_transport(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_STT_TRANSPORT", "named_pipe")

    with pytest.raises(ValueError, match="LOCAL_STT_TRANSPORT"):
        LocalSTTConfig.from_env()


def test_async_raw_uds_local_stt_client_stream_flow(tmp_path) -> None:
    socket_path = tmp_path / "stt.raw.sock"
    received_frames: list[tuple[RawUdsFrameType, object]] = []

    async def read_raw_frame(reader: asyncio.StreamReader):
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        return decode_raw_uds_frame(header + await reader.readexactly(payload_length))

    async def send_json(writer: asyncio.StreamWriter, frame_type: RawUdsFrameType, payload: dict[str, object]) -> None:
        writer.write(encode_raw_uds_json_frame(frame_type, payload))
        await writer.drain()

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        start_frame = await read_raw_frame(reader)
        received_frames.append((start_frame.frame_type, decode_raw_uds_json_payload(start_frame)))
        await send_json(
            writer,
            RawUdsFrameType.JSON_EVENT,
            {
                "type": "ready",
                "version": "local-stt.v1",
                "audio": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "bytes_per_frame": 640,
                },
                "metadata": {"stream_id": 7},
            },
        )

        ping_frame = await read_raw_frame(reader)
        received_frames.append((ping_frame.frame_type, decode_raw_uds_json_payload(ping_frame)))
        await send_json(writer, RawUdsFrameType.PONG, {"type": "pong", "ping_id": "raw-1", "metadata": {}})

        audio_frame = await read_raw_frame(reader)
        received_frames.append((audio_frame.frame_type, audio_frame.payload))

        finalize_frame = await read_raw_frame(reader)
        received_frames.append((finalize_frame.frame_type, decode_raw_uds_json_payload(finalize_frame)))
        await send_json(
            writer,
            RawUdsFrameType.JSON_EVENT,
            {
                "type": "transcript",
                "text": "hello",
                "is_final": True,
                "speech_final": True,
                "revision": 1,
                "audio_received_ms": 20,
                "audio_transcribed_ms": 20,
                "metadata": {"stream_id": 7, "chunks_received": 1},
            },
        )

        close_frame = await read_raw_frame(reader)
        received_frames.append((close_frame.frame_type, decode_raw_uds_json_payload(close_frame)))
        await send_json(writer, RawUdsFrameType.JSON_EVENT, {"type": "closed", "reason": "client_close", "metadata": {}})
        writer.close()
        await writer.wait_closed()

    async def scenario() -> None:
        server = await asyncio.start_unix_server(handle_client, path=str(socket_path))
        async with server:
            client = AsyncRawUdsLocalSttClient(str(socket_path))
            ready_event = await client.start(client_stream_id="turn-raw", partial_interval_ms=100)
            pong_event = await client.ping(ping_id="raw-1")
            await client.send_audio(b"\x00\x01")
            await client.finalize()
            final_event = await client.recv_event()
            closed_event = await client.close()
            server.close()
            await server.wait_closed()

        assert ready_event["metadata"]["stream_id"] == 7
        assert pong_event == {"type": "pong", "ping_id": "raw-1", "metadata": {}}
        assert final_event is not None
        assert final_event.type == "final"
        assert final_event.text == "hello"
        assert closed_event == {"type": "closed", "reason": "client_close", "metadata": {}}

    asyncio.run(scenario())

    assert received_frames == [
        (
            RawUdsFrameType.JSON_CONTROL,
            {
                "type": "start",
                "version": "local-stt.v1",
                "audio": {
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "bytes_per_frame": 640,
                },
                "language": "en",
                "interim_results": True,
                "partial_interval_ms": 100,
                "client_stream_id": "turn-raw",
            },
        ),
        (RawUdsFrameType.PING, {"type": "ping", "ping_id": "raw-1"}),
        (RawUdsFrameType.AUDIO_PCM16, b"\x00\x01"),
        (RawUdsFrameType.JSON_CONTROL, {"type": "finalize"}),
        (RawUdsFrameType.JSON_CONTROL, {"type": "close"}),
    ]


def test_async_raw_uds_client_rejects_invalid_pcm16_without_connecting() -> None:
    async def fail_connect(_path: str):
        raise AssertionError("invalid audio should not open the raw UDS socket")

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.raw.sock", connect_fn=fail_connect)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.send_audio(b"\x00")

        assert excinfo.value.as_event().code == "invalid_audio_chunk"

    asyncio.run(scenario())


def test_async_raw_uds_client_rejects_invalid_ping_without_connecting() -> None:
    async def fail_connect(_path: str):
        raise AssertionError("invalid ping should not open the raw UDS socket")

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.raw.sock", connect_fn=fail_connect)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.ping(timestamp_ms=-1)

        assert excinfo.value.as_event().code == "invalid_message"
        assert "timestamp_ms" in excinfo.value.as_event().message

    asyncio.run(scenario())


def test_async_raw_uds_client_clears_connection_after_close_wait_failure() -> None:
    class NoopReader:
        pass

    class FailingCloseWriter:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            raise RuntimeError("socket close failed")

    writer = FailingCloseWriter()

    async def connect_fn(_path: str):
        return NoopReader(), writer

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.raw.sock", connect_fn=connect_fn)
        await client.connect()

        with pytest.raises(RuntimeError, match="socket close failed"):
            await client.close(graceful=False)

        assert writer.closed is True
        assert client._reader is None
        assert client._writer is None

    asyncio.run(scenario())


def test_async_raw_uds_client_clears_connection_after_bad_close_ack() -> None:
    class ErrorAckReader:
        def __init__(self) -> None:
            self.frame = encode_raw_uds_json_frame(
                RawUdsFrameType.ERROR,
                {
                    "type": "error",
                    "code": "close_failed",
                    "message": "close failed",
                    "metadata": {},
                },
            )
            self.offset = 0

        async def readexactly(self, size: int) -> bytes:
            chunk = self.frame[self.offset : self.offset + size]
            self.offset += size
            return chunk

    class ClosingWriter:
        def __init__(self) -> None:
            self.closed = False
            self.sent: list[bytes] = []

        def write(self, data: bytes) -> None:
            self.sent.append(data)

        async def drain(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

        async def wait_closed(self) -> None:
            pass

    writer = ClosingWriter()

    async def connect_fn(_path: str):
        return ErrorAckReader(), writer

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.raw.sock", connect_fn=connect_fn)
        await client.connect()

        with pytest.raises(RuntimeError, match="Expected closed event"):
            await client.close()

        assert writer.closed is True
        assert client._reader is None
        assert client._writer is None

    asyncio.run(scenario())


def test_async_raw_uds_client_rejects_oversized_payload_before_body_read() -> None:
    class OversizedPayloadReader:
        def __init__(self) -> None:
            self.reads: list[int] = []

        async def readexactly(self, size: int) -> bytes:
            self.reads.append(size)
            if size == RAW_UDS_HEADER_BYTES:
                return bytes([RawUdsFrameType.JSON_EVENT]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little")
            raise AssertionError("client attempted to read an oversized Raw UDS payload body")

    class NoopWriter:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    reader = OversizedPayloadReader()

    async def connect_fn(_path: str):
        return reader, NoopWriter()

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.sock", connect_fn=connect_fn)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.recv_event()

        assert excinfo.value.as_event().code == "raw_uds_payload_too_large"
        assert f"{RAW_UDS_MAX_PAYLOAD_BYTES} bytes" in excinfo.value.as_event().message

    asyncio.run(scenario())

    assert reader.reads == [RAW_UDS_HEADER_BYTES]


def test_async_raw_uds_client_rejects_unknown_server_frame_type_before_body_read() -> None:
    class UnknownFrameReader:
        def __init__(self) -> None:
            self.reads: list[int] = []

        async def readexactly(self, size: int) -> bytes:
            self.reads.append(size)
            if size == RAW_UDS_HEADER_BYTES:
                return b"\xff" + (4).to_bytes(4, "little")
            raise AssertionError("client attempted to read an unknown Raw UDS frame body")

    class NoopWriter:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    reader = UnknownFrameReader()

    async def connect_fn(_path: str):
        return reader, NoopWriter()

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.sock", connect_fn=connect_fn)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.recv_event()

        assert excinfo.value.as_event().code == "raw_uds_invalid_server_frame_type"
        assert "Unsupported Raw UDS frame type: 255" in excinfo.value.message

    asyncio.run(scenario())

    assert reader.reads == [RAW_UDS_HEADER_BYTES]


def test_async_raw_uds_client_maps_truncated_server_frames_to_protocol_errors() -> None:
    class TruncatedFrameReader:
        def __init__(self) -> None:
            self._reads = 0

        async def readexactly(self, size: int) -> bytes:
            self._reads += 1
            if self._reads == 1:
                return bytes([RawUdsFrameType.JSON_EVENT]) + (4).to_bytes(4, "little")
            raise asyncio.IncompleteReadError(partial=b"{", expected=size)

    class NoopWriter:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    async def connect_fn(_path: str):
        return TruncatedFrameReader(), NoopWriter()

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.sock", connect_fn=connect_fn)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.recv_event()

        assert excinfo.value.as_event().code == "raw_uds_incomplete_frame"
        assert "reading frame payload" in excinfo.value.message

    asyncio.run(scenario())


def test_async_raw_uds_client_rejects_inbound_client_frame_types_before_body_read() -> None:
    class ClientFrameReader:
        def __init__(self) -> None:
            self.reads: list[int] = []

        async def readexactly(self, size: int) -> bytes:
            self.reads.append(size)
            if size == RAW_UDS_HEADER_BYTES:
                return bytes([RawUdsFrameType.JSON_CONTROL]) + (4).to_bytes(4, "little")
            raise AssertionError("client attempted to read an inbound client frame body")

    class NoopWriter:
        def close(self) -> None:
            pass

        async def wait_closed(self) -> None:
            pass

    reader = ClientFrameReader()

    async def connect_fn(_path: str):
        return reader, NoopWriter()

    async def scenario() -> None:
        client = AsyncRawUdsLocalSttClient("/tmp/stt.sock", connect_fn=connect_fn)
        with pytest.raises(LocalSttProtocolError) as excinfo:
            await client.recv_event()

        assert excinfo.value.as_event().code == "raw_uds_invalid_server_frame_type"

    asyncio.run(scenario())

    assert reader.reads == [RAW_UDS_HEADER_BYTES]


def test_default_raw_uds_connect_rejects_existing_non_socket_path(tmp_path) -> None:
    path = tmp_path / "stt.raw.sock"
    path.write_text("not a socket", encoding="utf-8")

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="not a socket"):
            await _default_raw_uds_connect(str(path))

    asyncio.run(scenario())


def test_async_asr_client_invokes_on_sent_callback_before_waiting_for_response() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
    ])
    sent_lengths: list[int] = []

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    def record_sent() -> None:
        sent_lengths.append(len(websocket.sent))

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel', on_sent=record_sent)
        await client.close()

        assert partial_event is not None
        assert partial_event.text == 'hel'
        assert sent_lengths == [2]
        assert websocket.sent[1] == {
            'type': 'audio',
            'audio_data': base64.b64encode(b'hel').decode('ascii'),
        }

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("param_name", "param_value"),
    [("partial_window_seconds", 0), ("max_buffer_seconds", -1), ("partial_window_seconds", True), ("max_buffer_seconds", float("inf"))],
)
def test_async_asr_client_rejects_invalid_optional_window_settings(param_name: str, param_value: object) -> None:
    async def scenario() -> None:
        client = AsyncASRClient("ws://example.test/ws/stream")
        with pytest.raises(ValueError, match=rf"{param_name} must be a positive finite number"):
            await client.start(**{param_name: param_value})

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("param_name", "param_value"),
    [("partial_window_seconds", 0), ("max_buffer_seconds", -1), ("max_buffer_seconds", True), ("partial_window_seconds", float("nan"))],
)
def test_async_local_stt_client_rejects_invalid_optional_window_settings(param_name: str, param_value: object) -> None:
    async def scenario() -> None:
        client = AsyncLocalSttClient("ws://example.test/v1/stt/stream")
        with pytest.raises(ValueError, match=rf"{param_name} must be a positive finite number"):
            await client.start(**{param_name: param_value})

    asyncio.run(scenario())


def test_async_asr_client_invokes_on_sent_callback() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        sent_markers: list[str] = []

        partial_event = await client.send_audio(b'hel', on_sent=lambda: sent_markers.append('sent'))
        await client.close()

        assert partial_event is not None
        assert sent_markers == ['sent']

    asyncio.run(scenario())


def test_async_asr_client_tolerates_missing_partial_event() -> None:
    class SlowPartialWebSocket(FakeWebSocket):
        def __init__(self) -> None:
            super().__init__([
                {
                    'type': 'ready',
                    'backend': 'fake-whisper',
                    'model': 'fixture-adapter',
                    'language': 'en',
                    'sample_rate': 16000,
                    'partial_interval_chunks': 1,
                },
                {
                    'type': 'final',
                    'is_final': True,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hello',
                },
            ])
            self.recv_calls = 0

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return await super().recv()

    websocket = SlowPartialWebSocket()

    async def fake_connect(_: str) -> SlowPartialWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel', response_timeout=0.01)
        final_event = await client.stop()
        await client.close()

        assert partial_event is None
        assert final_event.text == 'hello'

    asyncio.run(scenario())


def test_async_asr_client_drains_stale_partial_before_final() -> None:
    class DelayedPartialWebSocket(FakeWebSocket):
        def __init__(self) -> None:
            super().__init__([
                {
                    'type': 'ready',
                    'backend': 'fake-whisper',
                    'model': 'fixture-adapter',
                    'language': 'en',
                    'sample_rate': 16000,
                    'partial_interval_chunks': 1,
                },
                {
                    'type': 'partial',
                    'is_final': False,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hel',
                },
                {
                    'type': 'final',
                    'is_final': True,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hello',
                },
            ])
            self.recv_calls = 0

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return await super().recv()

    websocket = DelayedPartialWebSocket()

    async def fake_connect(_: str) -> DelayedPartialWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel', response_timeout=0.01)
        final_event = await client.stop()
        await client.close()

        assert partial_event is None
        assert final_event.type == 'final'
        assert final_event.text == 'hello'

    asyncio.run(scenario())


def test_async_asr_client_can_cancel_stream() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'stream_id': 7,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'remaining_buffer_bytes': 1021,
            'text': 'hel',
        },
        {
            'type': 'canceled',
            'stream_id': 7,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'remaining_buffer_bytes': 1021,
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel')
        canceled_event = await client.cancel()
        await client.close()

        assert partial_event is not None
        assert partial_event.stream_id == 7
        assert partial_event.remaining_buffer_bytes == 1021
        assert canceled_event.type == 'canceled'
        assert canceled_event.stream_id == 7
        assert canceled_event.remaining_buffer_bytes == 1021
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'hel').decode('ascii'),
            },
            {'type': 'cancel'},
        ]

    asyncio.run(scenario())


def test_async_asr_client_returns_cancel_error_events() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'error',
            'stream_id': 7,
            'message': 'Send a start event before canceling the stream',
            'code': 1003,
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        cancel_event = await client.cancel()
        await client.close()

        assert cancel_event.type == 'error'
        assert cancel_event.stream_id == 7
        assert cancel_event.text == 'Send a start event before canceling the stream'
        assert cancel_event.raw['code'] == 1003
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            {'type': 'cancel'},
        ]

    asyncio.run(scenario())


def test_async_asr_client_rejects_invalid_start_arguments() -> None:
    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream')

        with pytest.raises(ValueError, match='sample_rate must be a positive integer'):
            await client.start(sample_rate=0)

        with pytest.raises(ValueError, match='partial_interval_chunks must be a positive integer'):
            await client.start(partial_interval_chunks=0)

    asyncio.run(scenario())
