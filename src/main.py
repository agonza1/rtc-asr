"""FastAPI application for the realtime ASR service."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import math
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator
import uvicorn

from .audio_processor import AudioConfig, AudioProcessor
from .config import AppConfig
from .model_loader import ASRUnavailableError, Transcriber, build_transcriber
from .protocols import (
    HOT_PATH_BYTES_PER_FRAME,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    PROTOCOL_VERSION,
    AudioFormat,
    ErrorMessage,
    FinalizeMessage,
    LocalSttProtocolError,
    ReadyMessage,
    StartMessage,
    TranscriptMessage,
    WarningMessage,
    parse_client_message,
    validate_audio_chunk,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TranscribeRequest(BaseModel):
    audio_data: str | None = Field(default=None, description="Base64-encoded audio bytes")
    audio: str | None = Field(default=None, description="Alias for audio_data")
    language: str | None = Field(default="en")
    sample_rate: int | None = Field(default=16000, ge=1)
    stream: bool = False

    @model_validator(mode="after")
    def validate_audio_payload(self) -> "TranscribeRequest":
        if not self.audio_data and not self.audio:
            raise ValueError("audio_data or audio is required")
        return self

    @property
    def encoded_audio(self) -> str:
        return self.audio_data or self.audio or ""


@dataclass(slots=True)
class AppServices:
    config: AppConfig
    audio_processor: AudioProcessor
    transcriber: Transcriber
    preload_error: str | None = None


def _backend_status(services: AppServices) -> str:
    if services.preload_error is not None:
        return "degraded"
    if services.transcriber.is_loaded():
        return "ready"
    return "loading"


def _accepting_traffic(services: AppServices) -> bool:
    return services.preload_error is None and (not services.config.asr_preload_model or services.transcriber.is_loaded())


def _health_payload(services: AppServices) -> dict[str, object]:
    status = _backend_status(services)
    return {
        "status": status,
        "service": "realtime-asr",
        "backend": services.transcriber.backend_name,
        "model": services.transcriber.model_name,
        "ready": _accepting_traffic(services),
        "model_loaded": services.transcriber.is_loaded(),
        "preload_enabled": services.config.asr_preload_model,
        "preload_error": services.preload_error,
        "protocols": _protocol_catalog(),
    }


def _protocol_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": "rtc-asr-stream.v1",
            "transport": "websocket",
            "path": "/ws/stream",
            "docs": "/docs/api-reference.md#websocket-streaming",
            "status": "stable",
            "message_format": "json-control-plus-binary-audio",
        },
        {
            "id": PROTOCOL_VERSION,
            "transport": "websocket",
            "path": "/v1/stt/stream",
            "docs": "/docs/local-stt-v1.md",
            "status": "preview",
            "message_format": "json-control-plus-binary-pcm16",
            "audio": {
                "sample_rate": 16000,
                "channels": 1,
                "format": HOT_PATH_PCM_FORMAT,
                "frame_ms": HOT_PATH_FRAME_MS,
                "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
            },
        },
    ]


def _record_lazy_load_failure(services: AppServices, exc: Exception) -> None:
    # Only promote the service to degraded when the backend failed before it ever loaded.
    if not services.transcriber.is_loaded():
        services.preload_error = str(exc)


class StreamClientError(ValueError):
    def __init__(self, message: str, *, code: int = 1003) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class StreamSession:
    stream_id: int
    language: str | None
    sample_rate: int
    max_buffer_bytes: int
    partial_interval_chunks: int = 1
    partial_interval_audio_ms: int | None = None
    partial_window_seconds: float | None = None
    max_buffer_seconds: float | None = None
    partial_window_bytes: int | None = None
    interim_results: bool = True
    client_stream_id: str | None = None
    client_metadata: dict[str, Any] = field(default_factory=dict)
    audio_buffer: bytearray = field(default_factory=bytearray, repr=False)
    chunks_received: int = 0
    last_partial_chunks_received: int = 0
    last_partial_audio_received_ms: int = 0
    last_partial_result: dict[str, object] | None = None
    transcript_revision: int = 0

    def append_audio(self, chunk: bytes) -> None:
        next_size = len(self.audio_buffer) + len(chunk)
        if next_size > self.max_buffer_bytes:
            raise StreamClientError(
                f"Stream buffer exceeded {self.max_buffer_bytes} bytes; send stop and start a new stream",
                code=1009,
            )
        self.audio_buffer.extend(chunk)
        self.chunks_received += 1

    def record_partial(self, transcript: dict[str, object]) -> None:
        self.last_partial_result = transcript
        self.last_partial_chunks_received = self.chunks_received
        self.last_partial_audio_received_ms = self.audio_received_ms()

    def audio_received_ms(self) -> int:
        return _audio_bytes_to_duration_ms(len(self.audio_buffer), self.sample_rate)

    def should_emit_partial(self) -> bool:
        if self.partial_interval_audio_ms is None:
            return self.chunks_received % self.partial_interval_chunks == 0
        elapsed_audio_ms = self.audio_received_ms() - self.last_partial_audio_received_ms
        return elapsed_audio_ms >= self.partial_interval_audio_ms

    def partial_audio_bytes(self) -> bytes:
        if self.partial_window_bytes is None or len(self.audio_buffer) <= self.partial_window_bytes:
            return bytes(self.audio_buffer)
        return bytes(self.audio_buffer[-self.partial_window_bytes :])

    def next_transcript_revision(self) -> int:
        self.transcript_revision += 1
        return self.transcript_revision


@dataclass(slots=True)
class LocalSttStartConfig:
    start: StartMessage
    partial_interval_chunks: int = 1
    partial_interval_audio_ms: int | None = None
    partial_window_seconds: float | None = None
    max_buffer_seconds: float | None = None
    client_stream_id: str | None = None
    client_metadata: dict[str, Any] = field(default_factory=dict)


def create_app(config: AppConfig | None = None, transcriber: Transcriber | None = None) -> FastAPI:
    runtime_config = config or AppConfig.from_env()
    audio_processor = AudioProcessor(AudioConfig(sample_rate=runtime_config.sample_rate))
    runtime_transcriber = transcriber or build_transcriber(runtime_config, audio_processor)
    services = AppServices(
        config=runtime_config,
        audio_processor=audio_processor,
        transcriber=runtime_transcriber,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        logger.info(
            "ASR service starting with backend=%s model=%s",
            services.transcriber.backend_name,
            services.transcriber.model_name,
        )
        if services.config.asr_preload_model:
            try:
                services.transcriber.preload()
            except Exception as exc:
                services.preload_error = str(exc)
                logger.warning("ASR preload failed: %s", exc)
                if services.config.asr_fail_fast:
                    raise
        try:
            yield
        finally:
            services.audio_processor.cleanup()
            logger.info("ASR service shutdown complete")

    app = FastAPI(
        title=runtime_config.app_name,
        description="Low-latency speech-to-text powered by a pluggable ASR backend",
        version=runtime_config.app_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(runtime_config.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, object]:
        return _health_payload(app.state.services)

    @app.get("/ready")
    async def readiness_check() -> JSONResponse:
        current = app.state.services
        payload = _health_payload(current)
        return JSONResponse(status_code=200 if payload["ready"] else 503, content=payload)

    @app.get("/api/models")
    async def list_models() -> dict[str, object]:
        current = app.state.services
        description = current.transcriber.describe()
        status = _backend_status(current)
        streaming = description.get("streaming")
        audio = description.get("audio")
        return {
            "backend": current.transcriber.backend_name,
            "model": current.transcriber.model_name,
            "sample_rate": current.config.sample_rate,
            "status": status,
            "ready": _accepting_traffic(current),
            "preload_enabled": current.config.asr_preload_model,
            "preload_error": current.preload_error,
            "protocols": _protocol_catalog(),
            "streaming": streaming,
            "audio": audio,
            "models": [
                {
                    "id": current.transcriber.model_name,
                    "backend": current.transcriber.backend_name,
                    "model": current.transcriber.model_name,
                    "loaded": current.transcriber.is_loaded(),
                    "streaming": streaming,
                    "audio": audio,
                    "capabilities": description,
                }
            ],
            "capabilities": description,
        }

    @app.post("/api/transcribe")
    async def transcribe_audio(payload: TranscribeRequest) -> dict[str, object]:
        audio_bytes = _decode_base64_audio(payload.encoded_audio)
        return _transcribe_bytes(
            app.state.services,
            audio_bytes=audio_bytes,
            language=payload.language,
            sample_rate=payload.sample_rate,
        )

    @app.post("/api/transcribe/file")
    async def transcribe_file(
        file: UploadFile = File(...),
        language: str | None = "en",
        sample_rate: int | None = 16000,
    ) -> dict[str, object]:
        if not file.filename:
            raise HTTPException(status_code=400, detail="No file provided")

        audio_bytes = await file.read()
        result = _transcribe_bytes(
            app.state.services,
            audio_bytes=audio_bytes,
            language=language,
            sample_rate=sample_rate,
        )
        return {
            "filename": file.filename,
            "transcription": result,
        }

    @app.post("/api/stream")
    async def stream_transcribe() -> None:
        raise HTTPException(
            status_code=501,
            detail="Streaming chunk transcription is available on /ws/stream; the HTTP streaming route is not implemented yet.",
        )

    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        services = app.state.services
        session: StreamSession | None = None
        next_stream_id = 1

        try:
            while True:
                payload, event_type = await _receive_stream_event(websocket, session)

                if event_type == "start":
                    if session is not None:
                        raise ValueError("Finish the active stream before starting a new one")
                    session = _create_stream_session(
                        payload,
                        services.config,
                        stream_id=next_stream_id,
                    )
                    next_stream_id += 1
                    ready_payload = {
                        "type": "ready",
                        "stream_id": session.stream_id,
                        "backend": services.transcriber.backend_name,
                        "model": services.transcriber.model_name,
                        "language": session.language,
                        "sample_rate": session.sample_rate,
                        "partial_interval_chunks": session.partial_interval_chunks,
                        "max_buffer_bytes": session.max_buffer_bytes,
                    }
                    if session.partial_window_seconds is not None:
                        ready_payload["partial_window_seconds"] = session.partial_window_seconds
                    if session.max_buffer_seconds is not None:
                        ready_payload["max_buffer_seconds"] = session.max_buffer_seconds
                    await websocket.send_json(ready_payload)
                    continue

                if event_type == "audio":
                    if session is None:
                        raise StreamClientError("Send a start event before audio chunks")

                    audio_bytes = _decode_websocket_audio(payload)
                    session.append_audio(audio_bytes)

                    if session.chunks_received % session.partial_interval_chunks != 0:
                        continue

                    partial = _run_transcription(
                        services,
                        audio_bytes=session.partial_audio_bytes(),
                        language=session.language,
                        sample_rate=session.sample_rate,
                    )
                    session.record_partial(partial)
                    partial_text = str(partial.get("text", "")).strip()
                    if partial_text:
                        await websocket.send_json(_stream_event("partial", session, partial))
                    continue

                if event_type == "stop":
                    if session is None:
                        raise StreamClientError("Send a start event before stopping the stream")
                    if not session.audio_buffer:
                        raise StreamClientError("No audio chunks received for this stream")

                    final_result = _resolve_final_result(session, services)
                    await websocket.send_json(_stream_event("final", session, final_result))
                    session = None
                    continue

                if event_type == "cancel":
                    if session is None:
                        raise StreamClientError("Send a start event before canceling the stream")

                    await websocket.send_json(
                        {
                            "type": "canceled",
                            "stream_id": session.stream_id,
                            "chunks_received": session.chunks_received,
                            "buffered_bytes": len(session.audio_buffer),
                            "remaining_buffer_bytes": session.max_buffer_bytes - len(session.audio_buffer),
                        }
                    )
                    session = None
                    continue

                raise StreamClientError("Unsupported stream event type")
        except WebSocketDisconnect:
            return
        except ASRUnavailableError as exc:
            services.preload_error = str(exc)
            await _close_websocket_error(websocket, str(exc), code=1011)
        except StreamClientError as exc:
            await _close_websocket_error(websocket, str(exc), code=exc.code)
        except ValueError as exc:
            await _close_websocket_error(websocket, str(exc), code=1003)
        except Exception as exc:  # pragma: no cover - defensive websocket boundary
            _record_lazy_load_failure(services, exc)
            logger.exception("Unexpected websocket stream error")
            await _close_websocket_error(websocket, "Unexpected streaming error", code=1011)

    @app.websocket("/v1/stt/stream")
    async def websocket_stream_v1(websocket: WebSocket) -> None:
        await websocket.accept()
        services = app.state.services
        session: StreamSession | None = None
        next_stream_id = 1

        try:
            while True:
                payload, event_type = await _receive_local_stt_event(websocket)

                if event_type == "start":
                    if session is not None:
                        raise LocalSttProtocolError(
                            "Finish the active stream before starting a new one",
                            code="invalid_state",
                        )
                    assert isinstance(payload, LocalSttStartConfig)
                    session = _create_local_stt_stream_session(
                        payload,
                        services.config,
                        stream_id=next_stream_id,
                    )
                    next_stream_id += 1
                    await websocket.send_json(
                        _local_stt_ready_event(
                            session,
                            backend=services.transcriber.backend_name,
                            model=services.transcriber.model_name,
                        )
                    )
                    continue

                if event_type == "audio":
                    if session is None:
                        raise LocalSttProtocolError(
                            "Send a start event before audio chunks",
                            code="invalid_state",
                        )

                    try:
                        session.append_audio(payload)
                    except StreamClientError as exc:
                        raise LocalSttProtocolError(
                            str(exc),
                            code="buffer_limit_exceeded",
                            metadata={"max_buffer_bytes": session.max_buffer_bytes},
                        ) from exc

                    if not session.interim_results or not session.should_emit_partial():
                        continue

                    partial_audio_bytes = session.partial_audio_bytes()
                    partial = _run_transcription(
                        services,
                        audio_bytes=partial_audio_bytes,
                        language=session.language,
                        sample_rate=session.sample_rate,
                    )
                    session.record_partial(partial)
                    partial_text = str(partial.get("text", "")).strip()
                    if partial_text:
                        await websocket.send_json(
                            _local_stt_transcript_event(
                                session,
                                partial,
                                is_final=False,
                                transcribed_audio_bytes=len(partial_audio_bytes),
                            )
                        )
                    continue

                if event_type == "finalize":
                    if session is None:
                        raise LocalSttProtocolError(
                            "Send a start event before finalizing the stream",
                            code="invalid_state",
                        )
                    if not session.audio_buffer:
                        raise LocalSttProtocolError(
                            "No audio chunks received for this stream",
                            code="invalid_state",
                        )

                    final_result = _resolve_final_result(session, services)
                    await websocket.send_json(
                        _local_stt_transcript_event(
                            session,
                            final_result,
                            is_final=True,
                            transcribed_audio_bytes=len(session.audio_buffer),
                        )
                    )
                    session = None
                    continue

                if event_type == "cancel":
                    if session is None:
                        raise LocalSttProtocolError(
                            "Send a start event before canceling the stream",
                            code="invalid_state",
                        )

                    await websocket.send_json(_local_stt_cancel_warning_event(session))
                    session = None
                    continue

                if event_type == "ping":
                    await websocket.send_json(_local_stt_pong_event(payload))
                    continue

                if event_type == "close":
                    await websocket.send_json({"type": "closed", "reason": "client_close", "metadata": {}})
                    await websocket.close(code=1000)
                    return

                raise LocalSttProtocolError(
                    f"Unsupported Local STT v1 message type: {event_type}",
                    code="unsupported_message_type",
                )
        except WebSocketDisconnect:
            return
        except ASRUnavailableError as exc:
            services.preload_error = str(exc)
            await _close_local_stt_error(
                websocket,
                ErrorMessage(type="error", code="backend_unavailable", message=str(exc)),
                close_code=1011,
            )
        except LocalSttProtocolError as exc:
            await _close_local_stt_error(websocket, exc.as_event(), close_code=1003)
        except Exception as exc:  # pragma: no cover - defensive websocket boundary
            _record_lazy_load_failure(services, exc)
            logger.exception("Unexpected Local STT v1 websocket stream error")
            await _close_local_stt_error(
                websocket,
                ErrorMessage(type="error", code="internal_error", message="Unexpected streaming error"),
                close_code=1011,
            )

    return app


def _create_stream_session(
    payload: dict[str, Any],
    config: AppConfig,
    *,
    stream_id: int,
) -> StreamSession:
    sample_rate = payload.get("sample_rate", config.sample_rate)
    partial_interval = payload.get("partial_interval_chunks", 1)
    language = payload.get("language", "en")
    partial_window_seconds = _coerce_positive_seconds(
        payload.get("partial_window_seconds"),
        field_name="partial_window_seconds",
    )
    max_buffer_seconds = _coerce_positive_seconds(
        payload.get("max_buffer_seconds"),
        field_name="max_buffer_seconds",
    )

    if not isinstance(sample_rate, int) or sample_rate < 1:
        raise StreamClientError("sample_rate must be a positive integer")
    if not isinstance(partial_interval, int) or partial_interval < 1:
        raise StreamClientError("partial_interval_chunks must be a positive integer")
    if language is not None and not isinstance(language, str):
        raise StreamClientError("language must be a string or null")

    max_buffer_bytes = config.stream_max_buffer_bytes
    if max_buffer_seconds is not None:
        max_buffer_bytes = min(max_buffer_bytes, _seconds_to_buffer_bytes(max_buffer_seconds, sample_rate))

    partial_window_bytes = None
    if partial_window_seconds is not None:
        partial_window_bytes = min(max_buffer_bytes, _seconds_to_buffer_bytes(partial_window_seconds, sample_rate))

    return StreamSession(
        stream_id=stream_id,
        language=language,
        sample_rate=sample_rate,
        max_buffer_bytes=max_buffer_bytes,
        partial_interval_chunks=partial_interval,
        partial_window_seconds=partial_window_seconds,
        max_buffer_seconds=max_buffer_seconds,
        partial_window_bytes=partial_window_bytes,
    )


def _create_local_stt_stream_session(
    payload: LocalSttStartConfig,
    config: AppConfig,
    *,
    stream_id: int,
) -> StreamSession:
    partial_window_bytes = None
    max_buffer_bytes = config.stream_max_buffer_bytes
    sample_rate = payload.start.audio.sample_rate

    if payload.max_buffer_seconds is not None:
        max_buffer_bytes = min(max_buffer_bytes, _seconds_to_buffer_bytes(payload.max_buffer_seconds, sample_rate))

    if payload.partial_window_seconds is not None:
        partial_window_bytes = min(
            max_buffer_bytes,
            _seconds_to_buffer_bytes(payload.partial_window_seconds, sample_rate),
        )

    return StreamSession(
        stream_id=stream_id,
        language=payload.start.language,
        sample_rate=sample_rate,
        max_buffer_bytes=max_buffer_bytes,
        partial_interval_chunks=payload.partial_interval_chunks,
        partial_interval_audio_ms=payload.partial_interval_audio_ms,
        partial_window_seconds=payload.partial_window_seconds,
        max_buffer_seconds=payload.max_buffer_seconds,
        partial_window_bytes=partial_window_bytes,
        interim_results=payload.start.interim_results,
        client_stream_id=payload.client_stream_id,
        client_metadata=dict(payload.client_metadata),
    )


def _parse_local_stt_start_message(payload: dict[str, Any]) -> LocalSttStartConfig:
    is_flat_start = any(key in payload for key in {"protocol", "sample_rate", "channels", "format", "frame_ms"})
    translated_payload = payload

    if is_flat_start:
        protocol = payload.get("protocol")
        if protocol != "local-stt-v1":
            raise LocalSttProtocolError("protocol must be local-stt-v1")
        translated_payload = {
            "type": "start",
            "version": PROTOCOL_VERSION,
            "audio": {
                "sample_rate": payload.get("sample_rate"),
                "channels": payload.get("channels"),
                "format": payload.get("format"),
                "frame_ms": payload.get("frame_ms", HOT_PATH_FRAME_MS),
                "bytes_per_frame": payload.get("bytes_per_frame"),
            },
            "language": payload.get("language"),
            "interim_results": payload.get("interim_results", True),
            "partial_interval_ms": payload.get("partial_interval_ms"),
            "partial_window_seconds": payload.get("partial_window_seconds"),
            "max_buffer_seconds": payload.get("max_buffer_seconds"),
            "client_stream_id": payload.get("client_stream_id"),
            "metadata": payload.get("metadata", {}),
        }

    start = parse_client_message(translated_payload)
    if not isinstance(start, StartMessage):
        raise LocalSttProtocolError("Expected a start message")

    client_stream_id = start.client_stream_id

    partial_interval_ms = start.partial_interval_ms
    partial_interval_chunks = 1
    partial_interval_audio_ms = None
    if partial_interval_ms is not None:
        partial_interval_chunks = max(1, math.ceil(partial_interval_ms / start.audio.frame_ms))
        partial_interval_audio_ms = partial_interval_chunks * start.audio.frame_ms

    partial_window_seconds = start.partial_window_seconds
    max_buffer_seconds = start.max_buffer_seconds

    return LocalSttStartConfig(
        start=start,
        partial_interval_chunks=partial_interval_chunks,
        partial_interval_audio_ms=partial_interval_audio_ms,
        partial_window_seconds=partial_window_seconds,
        max_buffer_seconds=max_buffer_seconds,
        client_stream_id=client_stream_id,
        client_metadata=dict(start.metadata),
    )


def _parse_local_stt_client_event(payload: dict[str, Any]) -> tuple[object, str]:
    event_type = str(payload.get("type", "")).strip().lower()
    if event_type == "start":
        return _parse_local_stt_start_message(payload), "start"
    if event_type == "stop":
        return FinalizeMessage(type="finalize"), "finalize"

    message = parse_client_message(payload)
    return message, str(message.type)


async def _receive_local_stt_event(websocket: WebSocket) -> tuple[object, str]:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message["code"], message.get("reason"))

    binary_audio = message.get("bytes")
    if binary_audio is not None:
        return validate_audio_chunk(binary_audio), "audio"

    raw_text = message.get("text")
    if raw_text is None:
        raise LocalSttProtocolError("Local STT v1 events must be JSON objects or binary PCM16 frames")

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LocalSttProtocolError("Local STT v1 messages must be valid JSON objects") from exc

    if not isinstance(payload, dict):
        raise LocalSttProtocolError("Local STT v1 messages must be JSON objects")

    return _parse_local_stt_client_event(payload)


def _local_stt_ready_event(session: StreamSession, *, backend: str, model: str) -> dict[str, object]:
    metadata: dict[str, object] = {
        "stream_id": session.stream_id,
        "backend": backend,
        "model": model,
        "max_buffer_bytes": session.max_buffer_bytes,
    }
    if session.client_stream_id is not None:
        metadata["client_stream_id"] = session.client_stream_id
    if session.client_metadata:
        metadata["client_metadata"] = dict(session.client_metadata)
    if session.partial_window_seconds is not None:
        metadata["partial_window_seconds"] = session.partial_window_seconds
    if session.max_buffer_seconds is not None:
        metadata["max_buffer_seconds"] = session.max_buffer_seconds

    return ReadyMessage(
        type="ready",
        version=PROTOCOL_VERSION,
        audio=AudioFormat(
            sample_rate=session.sample_rate,
            channels=1,
            format=HOT_PATH_PCM_FORMAT,
            frame_ms=HOT_PATH_FRAME_MS,
            bytes_per_frame=HOT_PATH_BYTES_PER_FRAME,
        ),
        interim_results=session.interim_results,
        metadata=metadata,
    ).model_dump()


def _local_stt_transcript_event(
    session: StreamSession,
    transcript: dict[str, object],
    *,
    is_final: bool,
    transcribed_audio_bytes: int,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "stream_id": session.stream_id,
        "chunks_received": session.chunks_received,
        "buffered_bytes": len(session.audio_buffer),
        "remaining_buffer_bytes": session.max_buffer_bytes - len(session.audio_buffer),
    }
    backend = transcript.get("backend")
    if isinstance(backend, str):
        metadata["backend"] = backend
    model = transcript.get("model")
    if isinstance(model, str):
        metadata["model"] = model
    if session.client_stream_id is not None:
        metadata["client_stream_id"] = session.client_stream_id
    if session.client_metadata:
        metadata["client_metadata"] = dict(session.client_metadata)

    return TranscriptMessage(
        type="transcript",
        text=str(transcript.get("text", "")).strip(),
        is_final=is_final,
        speech_final=is_final,
        revision=session.next_transcript_revision(),
        audio_received_ms=_audio_bytes_to_duration_ms(len(session.audio_buffer), session.sample_rate),
        audio_transcribed_ms=_audio_bytes_to_duration_ms(transcribed_audio_bytes, session.sample_rate),
        metadata=metadata,
        language=transcript.get("language") if isinstance(transcript.get("language"), str) else session.language,
    ).model_dump()


def _local_stt_cancel_warning_event(session: StreamSession) -> dict[str, object]:
    metadata: dict[str, object] = {
        "stream_id": session.stream_id,
        "chunks_received": session.chunks_received,
        "buffered_bytes": len(session.audio_buffer),
        "remaining_buffer_bytes": session.max_buffer_bytes - len(session.audio_buffer),
    }
    if session.client_stream_id is not None:
        metadata["client_stream_id"] = session.client_stream_id
    if session.client_metadata:
        metadata["client_metadata"] = dict(session.client_metadata)
    return WarningMessage(
        type="warning",
        code="stream_canceled",
        message="Active utterance canceled",
        metadata=metadata,
    ).model_dump()


def _local_stt_pong_event(message: object) -> dict[str, object]:
    ping_id = getattr(message, "ping_id", None)
    timestamp_ms = getattr(message, "timestamp_ms", None)
    payload: dict[str, object] = {"type": "pong", "metadata": {}}
    if ping_id is not None:
        payload["ping_id"] = ping_id
    if timestamp_ms is not None:
        payload["timestamp_ms"] = timestamp_ms
    return payload


def _audio_bytes_to_duration_ms(byte_count: int, sample_rate: int) -> int:
    if sample_rate < 1:
        return 0
    return max(0, round((byte_count / 2) * 1000 / sample_rate))


def _coerce_positive_seconds(value: Any, *, field_name: str, error_cls: type[ValueError] = StreamClientError) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise error_cls(f"{field_name} must be a positive number")
    return float(value)


def _seconds_to_buffer_bytes(seconds: float, sample_rate: int) -> int:
    sample_count = max(1, round(seconds * sample_rate))
    return sample_count * 2


def _decode_base64_audio(encoded_audio: str) -> bytes:
    try:
        return base64.b64decode(encoded_audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="audio_data must be valid base64-encoded audio bytes") from exc


def _decode_websocket_audio(payload: dict[str, Any]) -> bytes:
    raw_audio = payload.get("audio_bytes")
    if raw_audio is not None:
        if not isinstance(raw_audio, (bytes, bytearray)):
            raise StreamClientError("audio_bytes must be raw bytes")
        return bytes(raw_audio)

    encoded_audio = payload.get("audio_data") or payload.get("audio")
    if not encoded_audio or not isinstance(encoded_audio, str):
        raise StreamClientError("audio_data or audio is required for audio events")

    try:
        return base64.b64decode(encoded_audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise StreamClientError("audio_data must be valid base64-encoded audio bytes") from exc


async def _receive_stream_event(
    websocket: WebSocket,
    session: StreamSession | None,
) -> tuple[dict[str, Any], str]:
    message = await websocket.receive()
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(message["code"], message.get("reason"))

    binary_audio = message.get("bytes")
    if binary_audio is not None:
        if session is None:
            raise StreamClientError("Send a start event before audio chunks")
        return {"audio_bytes": binary_audio}, "audio"

    raw_text = message.get("text")
    if raw_text is None:
        raise StreamClientError("Stream events must be JSON text or binary audio frames")

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StreamClientError("Stream events must be valid JSON") from exc

    if not isinstance(payload, dict):
        raise StreamClientError("Stream events must be JSON objects")

    event_type = str(payload.get("type", "")).strip().lower()
    return payload, event_type


def _stream_event(event_type: str, session: StreamSession, transcript: dict[str, object]) -> dict[str, object]:
    buffered_bytes = len(session.audio_buffer)
    return {
        "type": event_type,
        "stream_id": session.stream_id,
        "is_final": event_type == "final",
        "chunks_received": session.chunks_received,
        "buffered_bytes": buffered_bytes,
        "remaining_buffer_bytes": session.max_buffer_bytes - buffered_bytes,
        **transcript,
    }


def _resolve_final_result(session: StreamSession, services: AppServices) -> dict[str, object]:
    if (
        session.last_partial_result is not None
        and session.last_partial_chunks_received == session.chunks_received
        and (session.partial_window_bytes is None or len(session.audio_buffer) <= session.partial_window_bytes)
    ):
        return session.last_partial_result

    return _run_transcription(
        services,
        audio_bytes=bytes(session.audio_buffer),
        language=session.language,
        sample_rate=session.sample_rate,
    )


def _run_transcription(
    services: AppServices,
    *,
    audio_bytes: bytes,
    language: str | None,
    sample_rate: int | None,
) -> dict[str, object]:
    result = services.transcriber.transcribe(
        audio_bytes,
        language=language,
        sample_rate=sample_rate,
    )
    services.preload_error = None
    return result


def _transcribe_bytes(
    services: AppServices,
    *,
    audio_bytes: bytes,
    language: str | None,
    sample_rate: int | None,
) -> dict[str, object]:
    try:
        return _run_transcription(
            services,
            audio_bytes=audio_bytes,
            language=language,
            sample_rate=sample_rate,
        )
    except ASRUnavailableError as exc:
        services.preload_error = str(exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary
        _record_lazy_load_failure(services, exc)
        logger.exception("Unexpected transcription error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _close_local_stt_error(websocket: WebSocket, message: ErrorMessage, *, close_code: int) -> None:
    try:
        await websocket.send_json(message.model_dump())
        await websocket.close(code=close_code)
    except RuntimeError:
        return


async def _close_websocket_error(websocket: WebSocket, message: str, *, code: int) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message, "code": code})
        await websocket.close(code=code)
    except RuntimeError:
        return


app = create_app()


def main() -> None:
    config = AppConfig.from_env()
    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
