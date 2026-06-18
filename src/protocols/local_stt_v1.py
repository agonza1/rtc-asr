"""Lightweight vendor-neutral Local STT v1 protocol models and validators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from pydantic_core import PydanticCustomError

PROTOCOL_VERSION = "local-stt.v1"
HOT_PATH_SAMPLE_RATE = 16000
HOT_PATH_CHANNELS = 1
HOT_PATH_PCM_FORMAT = "pcm_s16le"
HOT_PATH_FRAME_MS = 20
HOT_PATH_BYTES_PER_FRAME = 640


class LocalSttModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AudioFormat(LocalSttModel):
    sample_rate: int
    channels: int
    format: str
    frame_ms: int = HOT_PATH_FRAME_MS
    bytes_per_frame: int | None = None

    @model_validator(mode="after")
    def validate_hot_path(self) -> "AudioFormat":
        if self.sample_rate != HOT_PATH_SAMPLE_RATE:
            raise PydanticCustomError(
                "unsupported_audio_format",
                f"audio.sample_rate must be {HOT_PATH_SAMPLE_RATE}",
            )
        if self.channels != HOT_PATH_CHANNELS:
            raise PydanticCustomError(
                "unsupported_audio_format",
                f"audio.channels must be {HOT_PATH_CHANNELS}",
            )
        if self.format != HOT_PATH_PCM_FORMAT:
            raise PydanticCustomError(
                "unsupported_audio_format",
                f"audio.format must be {HOT_PATH_PCM_FORMAT}",
            )
        if self.frame_ms != HOT_PATH_FRAME_MS:
            raise PydanticCustomError(
                "unsupported_audio_format",
                f"audio.frame_ms must be {HOT_PATH_FRAME_MS}",
            )
        if self.bytes_per_frame is not None and self.bytes_per_frame != HOT_PATH_BYTES_PER_FRAME:
            raise PydanticCustomError(
                "unsupported_audio_format",
                f"audio.bytes_per_frame must be {HOT_PATH_BYTES_PER_FRAME}",
            )
        return self


class StartMessage(LocalSttModel):
    type: Literal["start"]
    version: Literal[PROTOCOL_VERSION]
    audio: AudioFormat
    language: str | None = None
    interim_results: bool = True
    partial_interval_ms: int | None = Field(default=None, ge=1)
    partial_window_seconds: float | None = Field(default=None, gt=0)
    max_buffer_seconds: float | None = Field(default=None, gt=0)
    client_stream_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class FinalizeMessage(LocalSttModel):
    type: Literal["finalize"]


class CancelMessage(LocalSttModel):
    type: Literal["cancel"]


class CloseMessage(LocalSttModel):
    type: Literal["close"]


class PingMessage(LocalSttModel):
    type: Literal["ping"]
    ping_id: str | None = None
    timestamp_ms: int | None = Field(default=None, ge=0)


class ReadyMessage(LocalSttModel):
    type: Literal["ready"]
    version: Literal[PROTOCOL_VERSION]
    audio: AudioFormat
    interim_results: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class TranscriptMessage(LocalSttModel):
    type: Literal["transcript"]
    text: str
    is_final: bool
    speech_final: bool
    revision: int = Field(ge=1)
    audio_received_ms: int = Field(ge=0)
    audio_transcribed_ms: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    language: str | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> "TranscriptMessage":
        if self.audio_transcribed_ms > self.audio_received_ms:
            raise PydanticCustomError(
                "invalid_timing_metadata",
                "audio_transcribed_ms must be less than or equal to audio_received_ms",
            )
        if self.is_final and self.revision < 1:
            raise PydanticCustomError(
                "invalid_transcript_revision",
                "final transcripts must include a positive revision",
            )
        return self


class WarningMessage(LocalSttModel):
    type: Literal["warning"]
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False


class ErrorMessage(LocalSttModel):
    type: Literal["error"]
    code: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    retryable: bool = False
    fatal: bool = True


class PongMessage(LocalSttModel):
    type: Literal["pong"]
    ping_id: str | None = None
    timestamp_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClosedMessage(LocalSttModel):
    type: Literal["closed"]
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)


ClientMessage: TypeAlias = Annotated[
    StartMessage | FinalizeMessage | CancelMessage | CloseMessage | PingMessage,
    Field(discriminator="type"),
]
ServerMessage: TypeAlias = Annotated[
    ReadyMessage | TranscriptMessage | WarningMessage | ErrorMessage | PongMessage | ClosedMessage,
    Field(discriminator="type"),
]

_CLIENT_ADAPTER = TypeAdapter(ClientMessage)
_SERVER_ADAPTER = TypeAdapter(ServerMessage)


@dataclass(slots=True)
class LocalSttProtocolError(ValueError):
    message: str
    code: str = "invalid_message"
    fatal: bool = True
    retryable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ValueError.__init__(self, self.message)

    def as_event(self) -> ErrorMessage:
        return ErrorMessage(
            type="error",
            code=self.code,
            message=self.message,
            retryable=self.retryable,
            fatal=self.fatal,
            metadata=dict(self.metadata),
        )


def parse_client_message(payload: Any) -> ClientMessage:
    return _validate_message(payload, adapter=_CLIENT_ADAPTER)


def parse_server_message(payload: Any) -> ServerMessage:
    return _validate_message(payload, adapter=_SERVER_ADAPTER)


def build_hot_path_audio_format() -> AudioFormat:
    return AudioFormat(
        sample_rate=HOT_PATH_SAMPLE_RATE,
        channels=HOT_PATH_CHANNELS,
        format=HOT_PATH_PCM_FORMAT,
        frame_ms=HOT_PATH_FRAME_MS,
        bytes_per_frame=HOT_PATH_BYTES_PER_FRAME,
    )


def build_start_message(
    *,
    language: str | None = "en",
    interim_results: bool = True,
    partial_interval_ms: int | None = None,
    partial_window_seconds: float | None = None,
    max_buffer_seconds: float | None = None,
    client_stream_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> StartMessage:
    return StartMessage(
        type="start",
        version=PROTOCOL_VERSION,
        audio=build_hot_path_audio_format(),
        language=language,
        interim_results=interim_results,
        partial_interval_ms=partial_interval_ms,
        partial_window_seconds=partial_window_seconds,
        max_buffer_seconds=max_buffer_seconds,
        client_stream_id=client_stream_id,
        metadata=metadata or {},
    )


def build_ready_message(
    *,
    interim_results: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ReadyMessage:
    return ReadyMessage(
        type="ready",
        version=PROTOCOL_VERSION,
        audio=build_hot_path_audio_format(),
        interim_results=interim_results,
        metadata=metadata or {},
    )


def validate_audio_chunk(chunk: Any) -> bytes:
    if isinstance(chunk, str):
        raise LocalSttProtocolError(
            "Audio frames must be sent as binary PCM16 websocket messages; Local STT v1 never base64-wraps audio",
            code="audio_must_be_binary",
        )
    if not isinstance(chunk, (bytes, bytearray, memoryview)):
        raise LocalSttProtocolError(
            "Audio frames must be bytes-like PCM16 payloads",
            code="invalid_audio_chunk",
        )

    audio_bytes = bytes(chunk)
    if not audio_bytes:
        raise LocalSttProtocolError(
            "Audio frames must not be empty",
            code="invalid_audio_chunk",
        )
    if len(audio_bytes) % 2 != 0:
        raise LocalSttProtocolError(
            "PCM16 audio frames must contain an even number of bytes",
            code="invalid_audio_chunk",
        )
    return audio_bytes


def _validate_message(payload: Any, *, adapter: TypeAdapter[Any]) -> Any:
    if not isinstance(payload, dict):
        raise LocalSttProtocolError("Local STT v1 messages must be JSON objects")
    try:
        return adapter.validate_python(payload)
    except ValidationError as exc:
        raise _protocol_error_from_validation(exc) from exc


def _protocol_error_from_validation(exc: ValidationError) -> LocalSttProtocolError:
    error = exc.errors()[0]
    code = _error_code_from_validation(error)
    if code == "unsupported_message_type":
        tag = str((error.get("ctx") or {}).get("tag", "unknown"))
        return LocalSttProtocolError(
            f"Unsupported Local STT v1 message type: {tag}",
            code=code,
        )
    location_parts = [str(part) for part in error.get("loc", ())]
    if location_parts and location_parts[0] in {"start", "finalize", "cancel", "close", "ping", "ready", "transcript", "warning", "error", "pong", "closed"}:
        location_parts = location_parts[1:]
    location = ".".join(location_parts)
    message = str(error.get("msg", "Invalid Local STT v1 message"))
    if location:
        message = f"{location}: {message}"
    return LocalSttProtocolError(message, code=code)


def _error_code_from_validation(error: dict[str, Any]) -> str:
    error_type = str(error.get("type", "invalid_message"))
    if error_type in {"unsupported_audio_format", "invalid_timing_metadata"}:
        return error_type
    if error_type == "union_tag_invalid":
        return "unsupported_message_type"
    return "invalid_message"
