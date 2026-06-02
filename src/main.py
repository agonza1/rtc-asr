"""FastAPI application for the realtime ASR service."""

from __future__ import annotations

import base64
import binascii
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket
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
            detail="Streaming chunk transcription is not implemented yet; use /api/transcribe for file-based requests.",
        )

    @app.websocket("/ws/stream")
    async def websocket_stream(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "error",
                "message": "Streaming transcription is not implemented yet; use POST /api/transcribe while /ws/stream state management is built.",
            }
        )
        await websocket.close(code=1003)

    return app


def _decode_base64_audio(encoded_audio: str) -> bytes:
    try:
        return base64.b64decode(encoded_audio, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="audio_data must be valid base64-encoded audio bytes") from exc


def _transcribe_bytes(
    services: AppServices,
    *,
    audio_bytes: bytes,
    language: str | None,
    sample_rate: int | None,
) -> dict[str, object]:
    try:
        return services.transcriber.transcribe(
            audio_bytes,
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
