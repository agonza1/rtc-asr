from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol


class WebSocketConnection(Protocol):
    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str: ...

    async def close(self, code: int = 1000) -> None: ...


ConnectFn = Callable[[str], Awaitable[WebSocketConnection]]


@dataclass(slots=True)
class TranscriptEvent:
    type: str
    text: str
    stream_id: int | None
    is_final: bool
    chunks_received: int
    buffered_bytes: int
    remaining_buffer_bytes: int
    raw: dict[str, Any]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "TranscriptEvent":
        return cls(
            type=str(payload.get("type", "")),
            text=str(payload.get("text", payload.get("message", ""))),
            stream_id=_maybe_int(payload.get("stream_id")),
            is_final=bool(payload.get("is_final", False)),
            chunks_received=_maybe_int(payload.get("chunks_received")) or 0,
            buffered_bytes=_maybe_int(payload.get("buffered_bytes")) or 0,
            remaining_buffer_bytes=_maybe_int(payload.get("remaining_buffer_bytes")) or 0,
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
            event = TranscriptEvent.from_payload(await self._recv_json(raise_on_error=False))
            if event.type != "partial":
                return event

    async def cancel(self) -> TranscriptEvent:
        websocket = self._require_websocket()
        await websocket.send(json.dumps({"type": "cancel"}))
        self._chunks_sent = 0
        self._send_binary_frames = False
        while True:
            event = TranscriptEvent.from_payload(await self._recv_json(raise_on_error=False))
            if event.type in {"canceled", "error"}:
                return event

    async def close(self) -> None:
        if self._websocket is None:
            return
        await self._websocket.close(code=1000)
        self._websocket = None
        self._send_binary_frames = False

    async def _recv_json(self, *, raise_on_error: bool = True) -> dict[str, Any]:
        websocket = self._require_websocket()
        payload = json.loads(await websocket.recv())
        if raise_on_error and payload.get("type") == "error":
            raise RuntimeError(str(payload.get("message", "Unknown ASR websocket error")))
        return payload


    async def _recv_json_with_timeout(self, timeout: float) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(self._recv_json(), timeout=timeout)
        except TimeoutError:
            return None

    def _require_websocket(self) -> WebSocketConnection:
        if self._websocket is None:
            raise RuntimeError("Call connect() or start() before using the ASR client")
        return self._websocket


async def _default_connect(ws_url: str) -> WebSocketConnection:
    import websockets

    return await websockets.connect(ws_url, max_size=2**23)


def _maybe_int(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _validate_positive_number(value: Any, *, field_name: str) -> None:
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive number")
