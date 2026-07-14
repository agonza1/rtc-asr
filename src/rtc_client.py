from __future__ import annotations

import asyncio
import base64
import json
import math
import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol

from .protocols import (
    HOT_PATH_BYTES_PER_FRAME,
    HOT_PATH_CHANNELS,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    HOT_PATH_SAMPLE_RATE,
    LocalSttProtocolError,
    PROTOCOL_VERSION,
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RawUdsFrameType,
    decode_raw_uds_frame,
    encode_raw_uds_client_message,
    encode_raw_uds_frame,
    parse_raw_uds_server_frame,
    validate_audio_chunk,
)


class WebSocketConnection(Protocol):
    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str: ...

    async def close(self, code: int = 1000) -> None: ...


ConnectFn = Callable[[str], Awaitable[WebSocketConnection]]
RawUdsConnectFn = Callable[[str], Awaitable[tuple[asyncio.StreamReader, asyncio.StreamWriter]]]


@dataclass(slots=True, frozen=True)
class LocalSTTConfig:
    transport: Literal["tcp_ws", "uds_ws", "raw_uds"] = "tcp_ws"
    url: str = "ws://127.0.0.1:8080/v1/stt/stream"
    uds_path: str | None = None

    def __post_init__(self) -> None:
        if self.transport in {"tcp_ws", "uds_ws"} and not self.url.strip():
            raise ValueError("url is required for Local STT websocket transports")
        if self.transport in {"uds_ws", "raw_uds"} and not (self.uds_path and self.uds_path.strip()):
            raise ValueError(f"uds_path is required when transport='{self.transport}'")

    @classmethod
    def from_env(cls) -> "LocalSTTConfig":
        transport = os.getenv("LOCAL_STT_TRANSPORT", cls.transport).strip().lower()
        if transport not in {"tcp_ws", "uds_ws", "raw_uds"}:
            raise ValueError("LOCAL_STT_TRANSPORT must be 'tcp_ws', 'uds_ws', or 'raw_uds'")
        uds_path_env = "LOCAL_STT_RAW_UDS_PATH" if transport == "raw_uds" else "LOCAL_STT_UDS_PATH"
        return cls(
            transport=transport,
            url=os.getenv("LOCAL_STT_URL", cls.url),
            uds_path=os.getenv(uds_path_env),
        )


def build_async_local_stt_client(
    config: LocalSTTConfig,
    *,
    connect_fn: ConnectFn | None = None,
    raw_uds_connect_fn: RawUdsConnectFn | None = None,
) -> "AsyncLocalSttClient | AsyncRawUdsLocalSttClient":
    if config.transport == "raw_uds":
        return AsyncRawUdsLocalSttClient(config.uds_path or "", connect_fn=raw_uds_connect_fn)
    if config.transport == "uds_ws":
        uds_path = config.uds_path or ""
        return AsyncLocalSttClient(
            config.url,
            connect_fn=connect_fn or (lambda ws_url: _default_unix_websocket_connect(uds_path, ws_url)),
        )

    return AsyncLocalSttClient(config.url, connect_fn=connect_fn)


@dataclass(slots=True)
class TranscriptEvent:
    type: str
    text: str
    stream_id: int | None
    is_final: bool
    chunks_received: int
    buffered_bytes: int
    remaining_buffer_bytes: int
    speech_final: bool = False
    revision: int | None = None
    audio_received_ms: int | None = None
    audio_transcribed_ms: int | None = None
    metadata: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TranscriptEvent":
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        payload_type = str(payload.get("type", ""))
        is_final = bool(payload.get("is_final", False))
        if payload_type == "transcript":
            payload_type = "final" if is_final else "partial"
        return cls(
            type=payload_type,
            text=str(payload.get("text", payload.get("message", ""))),
            stream_id=_maybe_int(payload.get("stream_id")) or _maybe_int(metadata.get("stream_id")),
            is_final=is_final,
            chunks_received=_maybe_int(payload.get("chunks_received")) or _maybe_int(metadata.get("chunks_received")) or 0,
            buffered_bytes=_maybe_int(payload.get("buffered_bytes")) or _maybe_int(metadata.get("buffered_bytes")) or 0,
            remaining_buffer_bytes=_maybe_int(payload.get("remaining_buffer_bytes")) or _maybe_int(metadata.get("remaining_buffer_bytes")) or 0,
            speech_final=bool(payload.get("speech_final", is_final)),
            revision=_maybe_int(payload.get("revision")),
            audio_received_ms=_maybe_int(payload.get("audio_received_ms")),
            audio_transcribed_ms=_maybe_int(payload.get("audio_transcribed_ms")),
            metadata=metadata or None,
            raw=payload,
        )


class AsyncASRClient:
    def __init__(
        self,
        ws_url: str,
        *,
        connect_fn: ConnectFn | None = None,
    ) -> None:
        self.ws_url = ws_url
        self._connect_fn = connect_fn
        self._websocket: WebSocketConnection | None = None
        self._partial_interval_chunks = 1
        self._chunks_sent = 0
        self._send_binary_frames = False

    async def connect(self) -> WebSocketConnection:
        if self._websocket is not None:
            return self._websocket
        connect_fn = self._connect_fn or _default_connect
        self._websocket = await connect_fn(self.ws_url)
        return self._websocket

    async def start(
        self,
        *,
        language: str | None = "en",
        sample_rate: int = 16000,
        partial_interval_chunks: int = 1,
        partial_window_seconds: float | None = None,
        max_buffer_seconds: float | None = None,
        send_binary_frames: bool = False,
    ) -> dict[str, Any]:
        if sample_rate < 1:
            raise ValueError("sample_rate must be a positive integer")
        if partial_interval_chunks < 1:
            raise ValueError("partial_interval_chunks must be a positive integer")
        _validate_positive_number(partial_window_seconds, field_name="partial_window_seconds")
        _validate_positive_number(max_buffer_seconds, field_name="max_buffer_seconds")
        websocket = await self.connect()
        payload: dict[str, Any] = {
            "type": "start",
            "language": language,
            "sample_rate": sample_rate,
            "partial_interval_chunks": partial_interval_chunks,
        }
        if partial_window_seconds is not None:
            payload["partial_window_seconds"] = partial_window_seconds
        if max_buffer_seconds is not None:
            payload["max_buffer_seconds"] = max_buffer_seconds
        await websocket.send(json.dumps(payload))
        ready_event = await self._recv_json()
        if ready_event.get("type") != "ready":
            raise RuntimeError(f"Expected ready event, got: {ready_event}")
        self._partial_interval_chunks = partial_interval_chunks
        self._chunks_sent = 0
        self._send_binary_frames = send_binary_frames
        return ready_event

    async def send_audio(
        self,
        chunk: bytes,
        *,
        binary: bool | None = None,
        expect_response: bool | None = None,
        response_timeout: float = 0.1,
        on_sent: Callable[[], None] | None = None,
    ) -> TranscriptEvent | None:
        websocket = self._require_websocket()
        use_binary = self._send_binary_frames if binary is None else binary
        if use_binary:
            await websocket.send(chunk)
        else:
            await websocket.send(json.dumps({
                "type": "audio",
                "audio_data": base64.b64encode(chunk).decode("ascii"),
            }))
        self._chunks_sent += 1
        if on_sent is not None:
            on_sent()

        if expect_response is None:
            expect_response = self._chunks_sent % self._partial_interval_chunks == 0
        if not expect_response:
            return None

        payload = await self._recv_json_with_timeout(response_timeout)
        if payload is None:
            return None
        return TranscriptEvent.from_payload(payload)

    async def stop(self) -> TranscriptEvent:
        websocket = self._require_websocket()
        await websocket.send(json.dumps({"type": "stop"}))
        self._chunks_sent = 0
        self._send_binary_frames = False
        while True:
            event = TranscriptEvent.from_payload(await self._recv_json(allow_error=True))
            if event.type != "partial":
                return event

    async def cancel(self) -> TranscriptEvent:
        websocket = self._require_websocket()
        await websocket.send(json.dumps({"type": "cancel"}))
        self._chunks_sent = 0
        self._send_binary_frames = False
        while True:
            event = TranscriptEvent.from_payload(await self._recv_json(allow_error=True))
            if event.type in {"canceled", "error"}:
                return event

    async def close(self) -> None:
        if self._websocket is None:
            return
        await self._websocket.close(code=1000)
        self._websocket = None
        self._send_binary_frames = False

    async def _recv_json(self, *, allow_error: bool = False) -> dict[str, Any]:
        websocket = self._require_websocket()
        payload = json.loads(await websocket.recv())
        if payload.get("type") == "error" and not allow_error:
            raise RuntimeError(str(payload.get("message", "Unknown ASR websocket error")))
        return payload

    async def _recv_json_with_timeout(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._recv_json(), timeout)
        except TimeoutError:
            return None

    def _require_websocket(self) -> WebSocketConnection:
        if self._websocket is None:
            raise RuntimeError("Call connect() or start() before using the ASR client")
        return self._websocket


class AsyncLocalSttClient:
    def __init__(
        self,
        ws_url: str,
        *,
        connect_fn: ConnectFn | None = None,
    ) -> None:
        self.ws_url = ws_url
        self._connect_fn = connect_fn
        self._websocket: WebSocketConnection | None = None

    async def connect(self) -> WebSocketConnection:
        if self._websocket is not None:
            return self._websocket
        connect_fn = self._connect_fn or _default_connect
        self._websocket = await connect_fn(self.ws_url)
        return self._websocket

    async def start(
        self,
        *,
        language: str | None = "en",
        sample_rate: int = HOT_PATH_SAMPLE_RATE,
        interim_results: bool = True,
        partial_interval_ms: int = HOT_PATH_FRAME_MS,
        partial_window_seconds: float | None = None,
        max_buffer_seconds: float | None = None,
        client_stream_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if sample_rate != HOT_PATH_SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {HOT_PATH_SAMPLE_RATE}")
        if partial_interval_ms < 1:
            raise ValueError("partial_interval_ms must be a positive integer")
        _validate_positive_number(partial_window_seconds, field_name="partial_window_seconds")
        _validate_positive_number(max_buffer_seconds, field_name="max_buffer_seconds")
        websocket = await self.connect()
        payload: dict[str, Any] = {
            "type": "start",
            "version": PROTOCOL_VERSION,
            "audio": {
                "sample_rate": HOT_PATH_SAMPLE_RATE,
                "channels": HOT_PATH_CHANNELS,
                "format": HOT_PATH_PCM_FORMAT,
                "frame_ms": HOT_PATH_FRAME_MS,
                "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
            },
            "language": language,
            "interim_results": interim_results,
            "partial_interval_ms": partial_interval_ms,
        }
        if partial_window_seconds is not None:
            payload["partial_window_seconds"] = partial_window_seconds
        if max_buffer_seconds is not None:
            payload["max_buffer_seconds"] = max_buffer_seconds
        if client_stream_id is not None:
            payload["client_stream_id"] = client_stream_id
        if metadata:
            payload["metadata"] = dict(metadata)
        await websocket.send(json.dumps(payload))
        ready_event = await self._recv_json()
        if ready_event.get("type") != "ready":
            raise RuntimeError(f"Expected ready event, got: {ready_event}")
        return ready_event

    async def send_audio(self, chunk: bytes, *, on_sent: Callable[[], None] | None = None) -> None:
        websocket = self._require_websocket()
        await websocket.send(chunk)
        if on_sent is not None:
            on_sent()

    async def finalize(self) -> None:
        websocket = self._require_websocket()
        await websocket.send(json.dumps({"type": "finalize"}))

    async def cancel(self) -> None:
        websocket = self._require_websocket()
        await websocket.send(json.dumps({"type": "cancel"}))

    async def ping(self, *, ping_id: str | None = None, timestamp_ms: int | None = None) -> dict[str, Any]:
        websocket = self._require_websocket()
        payload: dict[str, Any] = {"type": "ping"}
        if ping_id is not None:
            payload["ping_id"] = ping_id
        if timestamp_ms is not None:
            payload["timestamp_ms"] = timestamp_ms
        await websocket.send(json.dumps(payload))
        pong_event = await self._recv_json()
        if pong_event.get("type") != "pong":
            raise RuntimeError(f"Expected pong event, got: {pong_event}")
        return pong_event

    async def recv_event(
        self,
        *,
        timeout: float | None = None,
        allow_error: bool = True,
    ) -> TranscriptEvent | None:
        if timeout is None:
            payload = await self._recv_json(allow_error=allow_error)
        else:
            payload = await self._recv_json_with_timeout(timeout, allow_error=allow_error)
            if payload is None:
                return None
        return TranscriptEvent.from_payload(payload)

    async def close(self, *, graceful: bool = True) -> dict[str, Any] | None:
        if self._websocket is None:
            return None

        closed_event: dict[str, Any] | None = None
        if graceful:
            websocket = self._require_websocket()
            await websocket.send(json.dumps({"type": "close"}))
            closed_event = await self._recv_json(allow_error=True)
            if closed_event.get("type") != "closed":
                raise RuntimeError(f"Expected closed event, got: {closed_event}")

        await self._websocket.close(code=1000)
        self._websocket = None
        return closed_event

    async def _recv_json(self, *, allow_error: bool = False) -> dict[str, Any]:
        websocket = self._require_websocket()
        payload = json.loads(await websocket.recv())
        if payload.get("type") == "error" and not allow_error:
            raise RuntimeError(str(payload.get("message", "Unknown Local STT websocket error")))
        return payload

    async def _recv_json_with_timeout(self, timeout: float, *, allow_error: bool = False) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._recv_json(allow_error=allow_error), timeout)
        except TimeoutError:
            return None

    def _require_websocket(self) -> WebSocketConnection:
        if self._websocket is None:
            raise RuntimeError("Call connect() or start() before using the Local STT client")
        return self._websocket


class AsyncRawUdsLocalSttClient:
    def __init__(
        self,
        uds_path: str,
        *,
        connect_fn: RawUdsConnectFn | None = None,
    ) -> None:
        self.uds_path = uds_path
        self._connect_fn = connect_fn
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        if self._reader is not None and self._writer is not None:
            return self._reader, self._writer
        connect_fn = self._connect_fn or _default_raw_uds_connect
        self._reader, self._writer = await connect_fn(self.uds_path)
        return self._reader, self._writer

    async def start(
        self,
        *,
        language: str | None = "en",
        sample_rate: int = HOT_PATH_SAMPLE_RATE,
        interim_results: bool = True,
        partial_interval_ms: int = HOT_PATH_FRAME_MS,
        partial_window_seconds: float | None = None,
        max_buffer_seconds: float | None = None,
        client_stream_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if sample_rate != HOT_PATH_SAMPLE_RATE:
            raise ValueError(f"sample_rate must be {HOT_PATH_SAMPLE_RATE}")
        if partial_interval_ms < 1:
            raise ValueError("partial_interval_ms must be a positive integer")
        _validate_positive_number(partial_window_seconds, field_name="partial_window_seconds")
        _validate_positive_number(max_buffer_seconds, field_name="max_buffer_seconds")
        payload: dict[str, Any] = {
            "type": "start",
            "version": PROTOCOL_VERSION,
            "audio": {
                "sample_rate": HOT_PATH_SAMPLE_RATE,
                "channels": HOT_PATH_CHANNELS,
                "format": HOT_PATH_PCM_FORMAT,
                "frame_ms": HOT_PATH_FRAME_MS,
                "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
            },
            "language": language,
            "interim_results": interim_results,
            "partial_interval_ms": partial_interval_ms,
        }
        if partial_window_seconds is not None:
            payload["partial_window_seconds"] = partial_window_seconds
        if max_buffer_seconds is not None:
            payload["max_buffer_seconds"] = max_buffer_seconds
        if client_stream_id is not None:
            payload["client_stream_id"] = client_stream_id
        if metadata:
            payload["metadata"] = dict(metadata)
        await self._send_client_message(payload)
        ready_event = await self._recv_json()
        if ready_event.get("type") != "ready":
            raise RuntimeError(f"Expected ready event, got: {ready_event}")
        return ready_event

    async def send_audio(self, chunk: bytes, *, on_sent: Callable[[], None] | None = None) -> None:
        await self._send_frame(RawUdsFrameType.AUDIO_PCM16, validate_audio_chunk(chunk))
        if on_sent is not None:
            on_sent()

    async def finalize(self) -> None:
        await self._send_client_message({"type": "finalize"})

    async def cancel(self) -> None:
        await self._send_client_message({"type": "cancel"})

    async def ping(self, *, ping_id: str | None = None, timestamp_ms: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"type": "ping"}
        if ping_id is not None:
            payload["ping_id"] = ping_id
        if timestamp_ms is not None:
            payload["timestamp_ms"] = timestamp_ms
        await self._send_client_message(payload)
        pong_event = await self._recv_json()
        if pong_event.get("type") != "pong":
            raise RuntimeError(f"Expected pong event, got: {pong_event}")
        return pong_event

    async def recv_event(
        self,
        *,
        timeout: float | None = None,
        allow_error: bool = True,
    ) -> TranscriptEvent | None:
        if timeout is None:
            payload = await self._recv_json(allow_error=allow_error)
        else:
            payload = await self._recv_json_with_timeout(timeout, allow_error=allow_error)
            if payload is None:
                return None
        return TranscriptEvent.from_payload(payload)

    async def close(self, *, graceful: bool = True) -> dict[str, Any] | None:
        if self._writer is None:
            return None

        closed_event: dict[str, Any] | None = None
        if graceful:
            await self._send_client_message({"type": "close"})
            closed_event = await self._recv_json(allow_error=True)
            if closed_event.get("type") != "closed":
                raise RuntimeError(f"Expected closed event, got: {closed_event}")

        writer = self._writer
        try:
            writer.close()
            await writer.wait_closed()
        finally:
            self._reader = None
            self._writer = None
        return closed_event

    async def _send_client_message(self, payload: dict[str, Any]) -> None:
        await self._send_bytes(encode_raw_uds_client_message(payload))

    async def _send_frame(self, frame_type: RawUdsFrameType, payload: bytes) -> None:
        await self._send_bytes(encode_raw_uds_frame(frame_type, payload))

    async def _send_bytes(self, data: bytes) -> None:
        _, writer = await self.connect()
        writer.write(data)
        await writer.drain()

    async def _recv_json(self, *, allow_error: bool = False) -> dict[str, Any]:
        reader, _ = await self.connect()
        try:
            header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
        except asyncio.IncompleteReadError as exc:
            raise LocalSttProtocolError(
                f"Raw UDS stream ended while reading frame header; received {len(exc.partial)} of {RAW_UDS_HEADER_BYTES} bytes",
                code="raw_uds_incomplete_frame",
            ) from exc
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        if payload_length > RAW_UDS_MAX_PAYLOAD_BYTES:
            raise LocalSttProtocolError(
                f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
                code="raw_uds_payload_too_large",
            )
        try:
            frame_payload = await reader.readexactly(payload_length)
        except asyncio.IncompleteReadError as exc:
            raise LocalSttProtocolError(
                f"Raw UDS stream ended while reading frame payload; received {len(exc.partial)} of {payload_length} bytes",
                code="raw_uds_incomplete_frame",
            ) from exc
        frame = decode_raw_uds_frame(header + frame_payload)
        payload = parse_raw_uds_server_frame(frame).model_dump(exclude_none=True)
        if payload.get("type") == "error" and not allow_error:
            raise RuntimeError(str(payload.get("message", "Unknown Local STT raw UDS error")))
        return payload

    async def _recv_json_with_timeout(self, timeout: float, *, allow_error: bool = False) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._recv_json(allow_error=allow_error), timeout)
        except TimeoutError:
            return None


async def _default_connect(ws_url: str) -> WebSocketConnection:
    import websockets

    return await websockets.connect(ws_url, max_size=2**23)


async def _default_unix_websocket_connect(uds_path: str, ws_url: str) -> WebSocketConnection:
    import websockets

    unix_connect = getattr(websockets, "unix_connect", None)
    if unix_connect is None:
        raise RuntimeError("uds_ws transport requires websockets.unix_connect")
    return await unix_connect(uds_path, uri=ws_url, max_size=2**23)


async def _default_raw_uds_connect(uds_path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    return await asyncio.open_unix_connection(uds_path)


def _maybe_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _validate_positive_number(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0 or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a positive finite number")
