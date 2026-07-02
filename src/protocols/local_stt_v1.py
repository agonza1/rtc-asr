"""Lightweight vendor-neutral Local STT v1 protocol models and validators."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator
from pydantic_core import PydanticCustomError

PROTOCOL_VERSION = "local-stt.v1"
HOT_PATH_SAMPLE_RATE = 16000
HOT_PATH_CHANNELS = 1
HOT_PATH_PCM_FORMAT = "pcm_s16le"
HOT_PATH_FRAME_MS = 20
HOT_PATH_BYTES_PER_FRAME = 640
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


@dataclass(slots=True)
class RawUdsFrameDecoder:
    """Incrementally decode length-prefixed Raw UDS frames from socket chunks."""

    _buffer: bytearray = field(default_factory=bytearray)

    def feed(self, data: bytes | bytearray | memoryview) -> list[RawUdsFrame]:
        chunk = bytes(data)
        if not chunk:
            return []
        self._buffer.extend(chunk)

        frames: list[RawUdsFrame] = []
        while len(self._buffer) >= RAW_UDS_HEADER_BYTES:
            frame_type_value, payload_length = struct.unpack("<BI", self._buffer[:RAW_UDS_HEADER_BYTES])
            frame_type = _parse_raw_uds_frame_type(frame_type_value)
            if payload_length > RAW_UDS_MAX_PAYLOAD_BYTES:
                raise LocalSttProtocolError(
                    f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
                    code="raw_uds_payload_too_large",
                )
            frame_length = RAW_UDS_HEADER_BYTES + payload_length
            if len(self._buffer) < frame_length:
                break
            payload = bytes(self._buffer[RAW_UDS_HEADER_BYTES:frame_length])
            del self._buffer[:frame_length]
            frames.append(RawUdsFrame(frame_type=frame_type, payload=payload))
        return frames

    @property
    def buffered_bytes(self) -> int:
        return len(self._buffer)


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


def encode_raw_uds_frame(frame_type: RawUdsFrameType | int, payload: bytes | bytearray | memoryview) -> bytes:
    resolved_type = _parse_raw_uds_frame_type(frame_type)
    payload_bytes = bytes(payload)
    if len(payload_bytes) > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSttProtocolError(
            f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
            code="raw_uds_payload_too_large",
        )
    return struct.pack("<BI", int(resolved_type), len(payload_bytes)) + payload_bytes


def decode_raw_uds_frame(data: bytes | bytearray | memoryview) -> RawUdsFrame:
    frame_bytes = bytes(data)
    if len(frame_bytes) < RAW_UDS_HEADER_BYTES:
        raise LocalSttProtocolError(
            "Raw UDS frames must include a 5 byte header",
            code="raw_uds_incomplete_frame",
        )
    frame_type_value, payload_length = struct.unpack("<BI", frame_bytes[:RAW_UDS_HEADER_BYTES])
    frame_type = _parse_raw_uds_frame_type(frame_type_value)
    if payload_length > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSttProtocolError(
            f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
            code="raw_uds_payload_too_large",
        )
    expected_length = RAW_UDS_HEADER_BYTES + payload_length
    if len(frame_bytes) != expected_length:
        raise LocalSttProtocolError(
            f"Raw UDS frame length mismatch: header declares {payload_length} payload bytes but received {len(frame_bytes) - RAW_UDS_HEADER_BYTES}",
            code="raw_uds_frame_length_mismatch",
        )
    return RawUdsFrame(frame_type=frame_type, payload=frame_bytes[RAW_UDS_HEADER_BYTES:])


def encode_raw_uds_json_frame(frame_type: RawUdsFrameType, payload: dict[str, Any]) -> bytes:
    json_frame_types = {
        RawUdsFrameType.JSON_CONTROL,
        RawUdsFrameType.JSON_EVENT,
        RawUdsFrameType.ERROR,
        RawUdsFrameType.PING,
        RawUdsFrameType.PONG,
    }
    if frame_type not in json_frame_types:
        raise LocalSttProtocolError(
            f"Raw UDS frame type {frame_type.name} cannot carry JSON control data",
            code="raw_uds_invalid_json_frame_type",
        )
    json_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return encode_raw_uds_frame(frame_type, json_payload)


def decode_raw_uds_json_payload(frame: RawUdsFrame) -> dict[str, Any]:
    if frame.frame_type == RawUdsFrameType.AUDIO_PCM16:
        raise LocalSttProtocolError(
            "Raw UDS audio frames do not carry JSON payloads",
            code="raw_uds_invalid_json_frame_type",
        )
    try:
        payload = json.loads(frame.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LocalSttProtocolError(
            "Raw UDS JSON frame payload must be valid UTF-8 JSON",
            code="raw_uds_invalid_json",
        ) from exc
    if not isinstance(payload, dict):
        raise LocalSttProtocolError(
            "Raw UDS JSON frame payload must be a JSON object",
            code="raw_uds_invalid_json",
        )
    return payload


def _parse_raw_uds_frame_type(frame_type: RawUdsFrameType | int) -> RawUdsFrameType:
    try:
        return frame_type if isinstance(frame_type, RawUdsFrameType) else RawUdsFrameType(int(frame_type))
    except (TypeError, ValueError) as exc:
        raise LocalSttProtocolError(
            f"Unsupported Raw UDS frame type: {frame_type}",
            code="raw_uds_unsupported_frame_type",
        ) from exc


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
