"""FastAPI application for the realtime ASR service."""

from __future__ import annotations

import base64
import binascii
import json
import logging
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
    }


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
    partial_window_seconds: float | None = None
    max_buffer_seconds: float | None = None
    partial_window_bytes: int | None = None
    audio_buffer: bytearray = field(default_factory=bytearray, repr=False)
    chunks_received: int = 0
    last_partial_chunks_received: int = 0
    last_partial_result: dict[str, object] | None = None

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

    def partial_audio_bytes(self) -> bytes:
        if self.partial_window_bytes is None or len(self.audio_buffer) <= self.partial_window_bytes:
            return bytes(self.audio_buffer)
        return bytes(self.audio_buffer[-self.partial_window_bytes :])


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
        return {
            "backend": current.transcriber.backend_name,
            "model": current.transcriber.model_name,
            "sample_rate": current.config.sample_rate,
            "status": status,
            "ready": _accepting_traffic(current),
            "preload_enabled": current.config.asr_preload_model,
            "preload_error": current.preload_error,
            "streaming": streaming,
            "models": [
                {
                    "id": current.transcriber.model_name,
                    "backend": current.transcriber.backend_name,
                    "model": current.transcriber.model_name,
                    "loaded": current.transcriber.is_loaded(),
                    "streaming": streaming,
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
        except Exception:  # pragma: no cover - defensive websocket boundary
            logger.exception("Unexpected websocket stream error")
            await _close_websocket_error(websocket, "Unexpected streaming error", code=1011)

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


def _coerce_positive_seconds(value: Any, *, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise StreamClientError(f"{field_name} must be a positive number")
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
        return {"audio_data": base64.b64encode(binary_audio).decode("ascii")}, "audio"

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
        logger.exception("Unexpected transcription error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
