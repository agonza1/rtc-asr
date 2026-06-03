"""FastAPI application for the realtime ASR service."""

from __future__ import annotations

import base64
import binascii
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
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


@dataclass(slots=True)
class StreamSession:
    language: str | None
    sample_rate: int
    partial_interval_chunks: int = 1
    audio_buffer: bytearray = field(default_factory=bytearray, repr=False)
    chunks_received: int = 0
    last_partial_text: str = ""

    def append_audio(self, chunk: bytes) -> None:
        self.audio_buffer.extend(chunk)
        self.chunks_received += 1


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
        current = app.state.services
        return {
            "status": "healthy",
            "service": "realtime-asr",
            "backend": current.transcriber.backend_name,
            "model": current.transcriber.model_name,
            "model_loaded": current.transcriber.is_loaded(),
        }

    @app.get("/api/models")
    async def list_models() -> dict[str, object]:
        current = app.state.services
        return {
            "models": [current.transcriber.model_name],
            "backend": current.transcriber.backend_name,
            "sample_rate": current.config.sample_rate,
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

        try:
            while True:
                payload = await websocket.receive_json()
                event_type = str(payload.get("type", "")).strip().lower()

                if event_type == "start":
                    session = _create_stream_session(payload, services.config.sample_rate)
                    await websocket.send_json(
                        {
                            "type": "ready",
                            "backend": services.transcriber.backend_name,
                            "model": services.transcriber.model_name,
                            "language": session.language,
                            "sample_rate": session.sample_rate,
                            "partial_interval_chunks": session.partial_interval_chunks,
                        }
                    )
                    continue

                if event_type == "audio":
                    if session is None:
                        raise ValueError("Send a start event before audio chunks")

                    audio_bytes = _decode_websocket_audio(payload)
                    session.append_audio(audio_bytes)

                    if session.chunks_received % session.partial_interval_chunks != 0:
                        continue

                    partial = _run_transcription(
                        services,
                        audio_bytes=bytes(session.audio_buffer),
                        language=session.language,
                        sample_rate=session.sample_rate,
                    )
                    partial_text = str(partial.get("text", "")).strip()
                    if partial_text and partial_text != session.last_partial_text:
                        session.last_partial_text = partial_text
                        await websocket.send_json(_stream_event("partial", session, partial))
                    continue

                if event_type == "stop":
                    if session is None:
                        raise ValueError("Send a start event before stopping the stream")
                    if not session.audio_buffer:
                        raise ValueError("No audio chunks received for this stream")

                    final_result = _run_transcription(
                        services,
                        audio_bytes=bytes(session.audio_buffer),
                        language=session.language,
                        sample_rate=session.sample_rate,
                    )
                    await websocket.send_json(_stream_event("final", session, final_result))
                    await websocket.close(code=1000)
                    return

                raise ValueError("Unsupported stream event type")
        except WebSocketDisconnect:
            return
        except ASRUnavailableError as exc:
            await _close_websocket_error(websocket, str(exc), code=1011)
        except ValueError as exc:
            await _close_websocket_error(websocket, str(exc), code=1003)
        except Exception:  # pragma: no cover - defensive websocket boundary
            logger.exception("Unexpected websocket stream error")
            await _close_websocket_error(websocket, "Unexpected streaming error", code=1011)

    return app


def _create_stream_session(payload: dict[str, Any], default_sample_rate: int) -> StreamSession:
    sample_rate = payload.get("sample_rate", default_sample_rate)
    partial_interval = payload.get("partial_interval_chunks", 1)
    language = payload.get("language", "en")

    if not isinstance(sample_rate, int) or sample_rate < 1:
        raise ValueError("sample_rate must be a positive integer")
    if not isinstance(partial_interval, int) or partial_interval < 1:
        raise ValueError("partial_interval_chunks must be a positive integer")
    if language is not None and not isinstance(language, str):
        raise ValueError("language must be a string or null")

    return StreamSession(
        language=language,
        sample_rate=sample_rate,
        partial_interval_chunks=partial_interval,
    )


def _decode_base64_audio(encoded_audio: str) -> bytes:
    try:
        return base64.b64decode(encoded_audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="audio_data must be valid base64-encoded audio bytes") from exc


def _decode_websocket_audio(payload: dict[str, Any]) -> bytes:
    encoded_audio = payload.get("audio_data") or payload.get("audio")
    if not encoded_audio or not isinstance(encoded_audio, str):
        raise ValueError("audio_data or audio is required for audio events")

    try:
        return base64.b64decode(encoded_audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("audio_data must be valid base64-encoded audio bytes") from exc


def _stream_event(event_type: str, session: StreamSession, transcript: dict[str, object]) -> dict[str, object]:
    return {
        "type": event_type,
        "is_final": event_type == "final",
        "chunks_received": session.chunks_received,
        "buffered_bytes": len(session.audio_buffer),
        **transcript,
    }


def _run_transcription(
    services: AppServices,
    *,
    audio_bytes: bytes,
    language: str | None,
    sample_rate: int | None,
) -> dict[str, object]:
    return services.transcriber.transcribe(
        audio_bytes,
        language=language,
        sample_rate=sample_rate,
    )


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
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive API boundary
        logger.exception("Unexpected transcription error")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


async def _close_websocket_error(websocket: WebSocket, message: str, *, code: int) -> None:
    try:
        await websocket.send_json({"type": "error", "message": message})
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
