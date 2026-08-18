"""Shared websocket protocol helpers for rtc-asr clients and integrations."""

from __future__ import annotations

import asyncio
import base64
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import websockets


@dataclass(slots=True, frozen=True)
class StreamConfig:
    language: str | None = "en"
    sample_rate: int = 16000
    partial_interval_chunks: int = 1
    partial_window_seconds: float | None = None
    max_buffer_seconds: float | None = None
    finalize_on_stable_partial: bool = False
    stable_partial_cycles: int | None = None
    partial_event_timeout_seconds: float = 0.1
    send_binary_frames: bool = False

    def __post_init__(self) -> None:
        if not _is_positive_integer(self.sample_rate):
            raise ValueError("sample_rate must be a positive integer")
        if not _is_positive_integer(self.partial_interval_chunks):
            raise ValueError("partial_interval_chunks must be a positive integer")
        if self.partial_window_seconds is not None and not _is_positive_finite_number(self.partial_window_seconds):
            raise ValueError("partial_window_seconds must be a positive finite number")
        if self.max_buffer_seconds is not None and not _is_positive_finite_number(self.max_buffer_seconds):
            raise ValueError("max_buffer_seconds must be a positive finite number")
        if not isinstance(self.finalize_on_stable_partial, bool):
            raise ValueError("finalize_on_stable_partial must be a boolean")
        if self.stable_partial_cycles is not None and not _is_positive_integer(self.stable_partial_cycles):
            raise ValueError("stable_partial_cycles must be a positive integer")
        if not _is_nonnegative_finite_number(self.partial_event_timeout_seconds):
            raise ValueError("partial_event_timeout_seconds must be zero or a finite positive number")

    def as_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": "start",
            "language": self.language,
            "sample_rate": self.sample_rate,
            "partial_interval_chunks": self.partial_interval_chunks,
        }
        if self.partial_window_seconds is not None:
            payload["partial_window_seconds"] = self.partial_window_seconds
        if self.max_buffer_seconds is not None:
            payload["max_buffer_seconds"] = self.max_buffer_seconds
        if self.finalize_on_stable_partial:
            payload["finalize_on_stable_partial"] = self.finalize_on_stable_partial
        if self.stable_partial_cycles is not None:
            payload["stable_partial_cycles"] = self.stable_partial_cycles
        return payload


@dataclass(slots=True, frozen=True)
class TranscriptEvent:
    type: str
    text: str
    stream_id: int | None = None
    is_final: bool = False
    chunks_received: int = 0
    buffered_bytes: int = 0
    remaining_buffer_bytes: int = 0
    language: str | None = None
    backend: str | None = None
    model: str | None = None
    duration_ms: int | None = None
    raw: dict[str, Any] | None = None

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
            language=_maybe_str(payload.get("language")),
            backend=_maybe_str(payload.get("backend")),
            model=_maybe_str(payload.get("model")),
            duration_ms=_maybe_int(payload.get("duration_ms")),
            raw=payload,
        )


class ASRWebSocketClient:
    """Minimal reusable websocket client for rtc-asr integrations."""

    def __init__(self, url: str, *, open_timeout: float = 10.0) -> None:
        self.url = url
        self.open_timeout = open_timeout
        self._websocket: Any | None = None

    async def __aenter__(self) -> "ASRWebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self) -> None:
        if self._websocket is not None:
            return
        self._websocket = await websockets.connect(self.url, open_timeout=self.open_timeout)

    async def close(self) -> None:
        if self._websocket is None:
            return
        await self._websocket.close()
        self._websocket = None

    async def start_stream(self, config: StreamConfig) -> TranscriptEvent:
        await self._send_json(config.as_payload())
        return await self.receive_event()

    async def send_audio_chunk(self, chunk: bytes, *, binary: bool = False) -> None:
        websocket = self._require_websocket()
        if binary:
            await websocket.send(chunk)
            return

        await self._send_json({
            "type": "audio",
            "audio_data": base64.b64encode(chunk).decode("ascii"),
        })

    async def stop_stream(self) -> TranscriptEvent:
        await self._send_json({"type": "stop"})
        while True:
            event = await self.receive_event()
            if event.type != "partial":
                return event

    async def cancel_stream(self) -> TranscriptEvent:
        await self._send_json({"type": "cancel"})
        while True:
            event = await self.receive_event()
            if event.type in {"canceled", "error"}:
                return event

    async def receive_event(self) -> TranscriptEvent:
        websocket = self._require_websocket()
        payload = json.loads(await websocket.recv())
        return TranscriptEvent.from_payload(payload)

    async def transcribe_once(self, chunks: Iterable[bytes], *, config: StreamConfig) -> list[TranscriptEvent]:
        events: list[TranscriptEvent] = []
        ready = await self.start_stream(config)
        events.append(ready)

        for chunk_index, chunk in enumerate(chunks, start=1):
            await self.send_audio_chunk(chunk, binary=config.send_binary_frames)
            if chunk_index % config.partial_interval_chunks != 0:
                continue

            partial_event = await self._receive_optional_event(timeout=config.partial_event_timeout_seconds)
            if partial_event is None:
                continue

            events.append(partial_event)
            if partial_event.type == "error":
                return events

        events.append(await self.stop_stream())
        return events

    async def _receive_optional_event(self, *, timeout: float) -> TranscriptEvent | None:
        try:
            return await asyncio.wait_for(self.receive_event(), timeout=timeout)
        except TimeoutError:
            return None

    async def _send_json(self, payload: dict[str, Any]) -> None:
        websocket = self._require_websocket()
        await websocket.send(json.dumps(payload))

    def _require_websocket(self) -> Any:
        if self._websocket is None:
            raise RuntimeError("WebSocket client is not connected")
        return self._websocket


def transcribe_chunks(url: str, chunks: Iterable[bytes], *, config: StreamConfig) -> list[TranscriptEvent]:
    async def _run() -> list[TranscriptEvent]:
        async with ASRWebSocketClient(url) as client:
            return await client.transcribe_once(chunks, config=config)

    return asyncio.run(_run())


def _maybe_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_positive_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 and math.isfinite(value)


def _is_nonnegative_finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 and math.isfinite(value)


def _maybe_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None
