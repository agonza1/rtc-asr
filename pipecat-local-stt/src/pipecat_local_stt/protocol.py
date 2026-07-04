from __future__ import annotations

import json

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


@dataclass(frozen=True, slots=True)
class RawUdsFrame:
    frame_type: RawUdsFrameType
    payload: bytes


def encode_raw_uds_frame(frame_type: RawUdsFrameType, payload: bytes) -> bytes:
    if len(payload) > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSTTProtocolError(f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes")
    return bytes([int(frame_type)]) + len(payload).to_bytes(4, "little") + payload


def encode_raw_uds_json_frame(frame_type: RawUdsFrameType, payload: dict[str, Any]) -> bytes:
    return encode_raw_uds_frame(frame_type, json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def decode_raw_uds_frame(data: bytes) -> RawUdsFrame:
    if len(data) < RAW_UDS_HEADER_BYTES:
        raise LocalSTTProtocolError("Raw UDS frame is missing its header")
    try:
        frame_type = RawUdsFrameType(data[0])
    except ValueError as exc:
        raise LocalSTTProtocolError(f"Unsupported Raw UDS frame type: {data[0]}") from exc
    payload_len = int.from_bytes(data[1:RAW_UDS_HEADER_BYTES], "little")
    if payload_len > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSTTProtocolError(f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes")
    payload = data[RAW_UDS_HEADER_BYTES:]
    if len(payload) != payload_len:
        raise LocalSTTProtocolError("Raw UDS frame payload length mismatch")
    return RawUdsFrame(frame_type=frame_type, payload=payload)


def decode_raw_uds_json_payload(frame: RawUdsFrame) -> dict[str, Any]:
    if frame.frame_type not in {RawUdsFrameType.JSON_EVENT, RawUdsFrameType.ERROR, RawUdsFrameType.PONG}:
        raise LocalSTTProtocolError(f"Raw UDS frame type {frame.frame_type.name} does not carry a server JSON event")
    payload = json.loads(frame.payload.decode("utf-8"))
    if not isinstance(payload, dict):
        raise LocalSTTProtocolError("Raw UDS JSON payload must be an object")
    return payload



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
            is_final=bool(payload["is_final"]),
            speech_final=bool(payload.get("speech_final", payload["is_final"])),
            revision=int(payload["revision"]),
            audio_received_ms=int(payload["audio_received_ms"]),
            audio_transcribed_ms=int(payload["audio_transcribed_ms"]),
            metadata=dict(metadata),
            language=payload.get("language") if isinstance(payload.get("language"), str) else None,
            raw=dict(payload),
        )
    except KeyError as exc:
        raise LocalSTTProtocolError(f"Transcript event missing required field: {exc.args[0]}") from exc
    except (TypeError, ValueError) as exc:
        raise LocalSTTProtocolError("Transcript event contains invalid timing or revision fields") from exc
    if event.revision < 1:
        raise LocalSTTProtocolError("Transcript event revision must be positive")
    if event.audio_received_ms < 0 or event.audio_transcribed_ms < 0:
        raise LocalSTTProtocolError("Transcript event timing metadata must be non-negative")
    if event.audio_transcribed_ms > event.audio_received_ms:
        raise LocalSTTProtocolError("audio_transcribed_ms must be <= audio_received_ms")
    return event
