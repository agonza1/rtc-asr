from __future__ import annotations

import json
import struct

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .config import LocalSTTConfig

PROTOCOL_NAME = "local-stt-v1"
PROTOCOL_VERSION = "local-stt.v1"
RAW_UDS_HEADER_BYTES = 5
RAW_UDS_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024


class RawUdsFrameType(IntEnum):
    JSON_CONTROL = 0x01
    AUDIO_PCM16 = 0x02
    JSON_EVENT = 0x03
    ERROR = 0x04
    PING = 0x05
    PONG = 0x06


RAW_UDS_CLIENT_FRAME_TYPES = (
    RawUdsFrameType.JSON_CONTROL,
    RawUdsFrameType.AUDIO_PCM16,
    RawUdsFrameType.PING,
    RawUdsFrameType.PONG,
)
RAW_UDS_SERVER_FRAME_TYPES = (
    RawUdsFrameType.JSON_EVENT,
    RawUdsFrameType.ERROR,
    RawUdsFrameType.PING,
    RawUdsFrameType.PONG,
)
RAW_UDS_FRAME_DIRECTION = {
    "client_to_server": [frame_type.name for frame_type in RAW_UDS_CLIENT_FRAME_TYPES],
    "server_to_client": [frame_type.name for frame_type in RAW_UDS_SERVER_FRAME_TYPES],
}


@dataclass(frozen=True, slots=True)
class RawUdsFrame:
    frame_type: RawUdsFrameType
    payload: bytes


@dataclass(slots=True)
class RawUdsFrameDecoder:
    """Incrementally decode length-prefixed Raw UDS frames from socket chunks."""

    _buffer: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes | bytearray | memoryview) -> list[RawUdsFrame]:
        try:
            chunk = _coerce_bytes_like(data, context="Raw UDS socket chunks")
        except LocalSTTProtocolError:
            self._buffer.clear()
            raise
        if not chunk:
            return []
        self._buffer.extend(chunk)

        frames: list[RawUdsFrame] = []
        while len(self._buffer) >= RAW_UDS_HEADER_BYTES:
            try:
                frame_type_value, payload_len = struct.unpack("<BI", self._buffer[:RAW_UDS_HEADER_BYTES])
                frame_type = _parse_raw_uds_frame_type(frame_type_value)
            except LocalSTTProtocolError:
                self._buffer.clear()
                raise
            if payload_len > RAW_UDS_MAX_PAYLOAD_BYTES:
                self._buffer.clear()
                raise LocalSTTProtocolError(
                    f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
                    code="raw_uds_payload_too_large",
                )
            frame_len = RAW_UDS_HEADER_BYTES + payload_len
            if len(self._buffer) < frame_len:
                break
            payload = bytes(self._buffer[RAW_UDS_HEADER_BYTES:frame_len])
            del self._buffer[:frame_len]
            frames.append(RawUdsFrame(frame_type=frame_type, payload=payload))
        return frames

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)

    def finish(self) -> None:
        if not self._buffer:
            return
        buffered = len(self._buffer)
        self._buffer.clear()
        raise LocalSTTProtocolError(
            f"Raw UDS stream ended with {buffered} buffered frame bytes",
            code="raw_uds_incomplete_frame",
        )


def encode_raw_uds_frame(frame_type: RawUdsFrameType | int, payload: bytes | bytearray | memoryview) -> bytes:
    resolved_type = _parse_raw_uds_frame_type(frame_type)
    payload_bytes = _coerce_bytes_like(payload, context="Raw UDS frame payload")
    if len(payload_bytes) > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSTTProtocolError(
            f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
            code="raw_uds_payload_too_large",
        )
    return struct.pack("<BI", int(resolved_type), len(payload_bytes)) + payload_bytes


def validate_raw_uds_audio_payload(payload: bytes | bytearray | memoryview) -> bytes:
    payload_bytes = _coerce_bytes_like(payload, context="Raw UDS audio payload")
    if not payload_bytes:
        raise LocalSTTProtocolError("Raw UDS audio frames must not be empty", code="invalid_audio_chunk")
    if len(payload_bytes) % 2 != 0:
        raise LocalSTTProtocolError(
            "Raw UDS PCM16 audio frames must contain an even number of bytes",
            code="invalid_audio_chunk",
        )
    return payload_bytes


def encode_raw_uds_json_frame(frame_type: RawUdsFrameType | int, payload: dict[str, Any]) -> bytes:
    resolved_type = _parse_raw_uds_frame_type(frame_type)
    json_frame_types = {
        RawUdsFrameType.JSON_CONTROL,
        RawUdsFrameType.JSON_EVENT,
        RawUdsFrameType.ERROR,
        RawUdsFrameType.PING,
        RawUdsFrameType.PONG,
    }
    if resolved_type not in json_frame_types:
        raise LocalSTTProtocolError(
            f"Raw UDS frame type {resolved_type.name} cannot carry JSON control data",
            code="raw_uds_invalid_json_frame_type",
        )
    if not isinstance(payload, dict):
        raise LocalSTTProtocolError("Raw UDS JSON payload must be an object", code="raw_uds_invalid_json")
    return encode_raw_uds_frame(resolved_type, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decode_raw_uds_frame(data: bytes | bytearray | memoryview) -> RawUdsFrame:
    frame_bytes = _coerce_bytes_like(data, context="Raw UDS frame")
    if len(frame_bytes) < RAW_UDS_HEADER_BYTES:
        raise LocalSTTProtocolError(
            "Raw UDS frames must include a 5 byte header",
            code="raw_uds_incomplete_frame",
        )
    frame_type_value, payload_len = struct.unpack("<BI", frame_bytes[:RAW_UDS_HEADER_BYTES])
    frame_type = _parse_raw_uds_frame_type(frame_type_value)
    if payload_len > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSTTProtocolError(
            f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
            code="raw_uds_payload_too_large",
        )
    payload = frame_bytes[RAW_UDS_HEADER_BYTES:]
    if len(payload) != payload_len:
        raise LocalSTTProtocolError(
            f"Raw UDS frame length mismatch: header declares {payload_len} payload bytes but received {len(payload)}",
            code="raw_uds_frame_length_mismatch",
        )
    return RawUdsFrame(frame_type=frame_type, payload=payload)


def decode_raw_uds_json_payload(frame: RawUdsFrame) -> dict[str, Any]:
    json_frame_types = {
        RawUdsFrameType.JSON_CONTROL,
        RawUdsFrameType.JSON_EVENT,
        RawUdsFrameType.ERROR,
        RawUdsFrameType.PING,
        RawUdsFrameType.PONG,
    }
    if frame.frame_type not in json_frame_types:
        raise LocalSTTProtocolError(
            f"Raw UDS frame type {frame.frame_type.name} does not carry a JSON payload",
            code="raw_uds_invalid_json_frame_type",
        )
    try:
        payload = json.loads(frame.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalSTTProtocolError(
            "Raw UDS JSON payload must be valid UTF-8 JSON",
            code="raw_uds_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise LocalSTTProtocolError("Raw UDS JSON payload must be an object", code="raw_uds_invalid_json")
    return payload


def parse_raw_uds_server_frame(frame: RawUdsFrame) -> dict[str, Any]:
    if frame.frame_type in {RawUdsFrameType.PING, RawUdsFrameType.PONG} and not frame.payload:
        return {"type": frame.frame_type.name.lower()}
    if frame.frame_type in {RawUdsFrameType.JSON_EVENT, RawUdsFrameType.ERROR, RawUdsFrameType.PING, RawUdsFrameType.PONG}:
        payload = decode_raw_uds_json_payload(frame)
        if frame.frame_type in {RawUdsFrameType.PING, RawUdsFrameType.PONG}:
            frame_event_type = frame.frame_type.name.lower()
            event_type = payload.setdefault("type", frame_event_type)
            if event_type != frame_event_type:
                raise LocalSTTProtocolError(
                    f"Raw UDS {frame.frame_type.name} frame cannot carry a {event_type!r} event",
                    code="raw_uds_heartbeat_type_mismatch",
                )
        elif frame.frame_type == RawUdsFrameType.ERROR:
            payload.setdefault("type", "error")
        return parse_server_message(payload)
    raise LocalSTTProtocolError(
        f"Raw UDS frame type {frame.frame_type.name} is not a server frame",
        code="raw_uds_invalid_server_frame_type",
    )


def _parse_raw_uds_frame_type(frame_type: RawUdsFrameType | int) -> RawUdsFrameType:
    if isinstance(frame_type, bool):
        raise LocalSTTProtocolError(
            f"Unsupported Raw UDS frame type: {frame_type}",
            code="raw_uds_unsupported_frame_type",
        )
    try:
        return frame_type if isinstance(frame_type, RawUdsFrameType) else RawUdsFrameType(int(frame_type))
    except (TypeError, ValueError) as exc:
        raise LocalSTTProtocolError(
            f"Unsupported Raw UDS frame type: {frame_type}",
            code="raw_uds_unsupported_frame_type",
        ) from exc


def _coerce_bytes_like(value: Any, *, context: str) -> bytes:
    if isinstance(value, str):
        raise LocalSTTProtocolError(
            f"{context} must be bytes-like, not text",
            code="raw_uds_invalid_bytes",
        )
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise LocalSTTProtocolError(
            f"{context} must be bytes-like",
            code="raw_uds_invalid_bytes",
        )
    return bytes(value)


@dataclass(slots=True)
class LocalSTTProtocolError(ValueError):
    message: str
    code: str = "invalid_message"
    fatal: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)


@dataclass(slots=True)
class LocalSTTTranscriptEvent:
    text: str
    is_final: bool
    speech_final: bool
    revision: int
    audio_received_ms: int
    audio_transcribed_ms: int
    metadata: dict[str, Any] = field(default_factory=dict)
    language: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def build_start_message(
    config: LocalSTTConfig,
    *,
    client_stream_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "start",
        "protocol": PROTOCOL_NAME,
        "language": config.language,
        "sample_rate": config.sample_rate,
        "channels": config.channels,
        "format": config.format,
        "frame_ms": config.frame_ms,
        "interim_results": config.interim_results,
        "partial_interval_ms": config.partial_interval_ms,
        "partial_window_seconds": config.partial_window_seconds,
        "max_buffer_seconds": config.max_buffer_seconds,
    }
    if client_stream_id is not None:
        payload["client_stream_id"] = client_stream_id
    if metadata:
        payload["metadata"] = dict(metadata)
    return payload


def parse_server_message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise LocalSTTProtocolError("Local STT v1 server messages must be JSON objects")
    event_type = payload.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise LocalSTTProtocolError("Local STT v1 server message is missing type")
    return payload


def parse_transcript_event(payload: dict[str, Any]) -> LocalSTTTranscriptEvent:
    if payload.get("type") != "transcript":
        raise LocalSTTProtocolError("Expected a transcript event")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    try:
        event = LocalSTTTranscriptEvent(
            text=str(payload["text"]),
            is_final=_parse_bool_field(payload["is_final"], "is_final"),
            speech_final=_parse_bool_field(payload.get("speech_final", payload["is_final"]), "speech_final"),
            revision=_parse_int_field(payload["revision"], "revision"),
            audio_received_ms=_parse_int_field(payload["audio_received_ms"], "audio_received_ms"),
            audio_transcribed_ms=_parse_int_field(payload["audio_transcribed_ms"], "audio_transcribed_ms"),
            metadata=dict(metadata),
            language=payload.get("language") if isinstance(payload.get("language"), str) else None,
            raw=dict(payload),
        )
    except KeyError as exc:
        raise LocalSTTProtocolError(f"Transcript event missing required field: {exc.args[0]}") from exc
    except LocalSTTProtocolError:
        raise
    except (TypeError, ValueError) as exc:
        raise LocalSTTProtocolError("Transcript event contains invalid timing or revision fields") from exc
    if event.revision < 1:
        raise LocalSTTProtocolError("Transcript event revision must be positive")
    if event.audio_received_ms < 0 or event.audio_transcribed_ms < 0:
        raise LocalSTTProtocolError("Transcript event timing metadata must be non-negative")
    if event.audio_transcribed_ms > event.audio_received_ms:
        raise LocalSTTProtocolError("audio_transcribed_ms must be <= audio_received_ms")
    return event


def _parse_bool_field(value: Any, field_name: str) -> bool:
    if isinstance(value, bool):
        return value
    raise LocalSTTProtocolError(f"Transcript event {field_name} must be a boolean")


def _parse_int_field(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise LocalSTTProtocolError(f"Transcript event {field_name} must be an integer, not a boolean")
    return int(value)
