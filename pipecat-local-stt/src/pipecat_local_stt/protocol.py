from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import LocalSTTConfig

PROTOCOL_NAME = "local-stt-v1"
PROTOCOL_VERSION = "local-stt.v1"


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
