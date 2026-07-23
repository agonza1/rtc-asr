"""FastAPI application for the realtime ASR service."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import math
import stat
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
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
    HOT_PATH_CHANNELS,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    HOT_PATH_SAMPLE_RATE,
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_FRAME_DIRECTION,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    PROTOCOL_VERSION,
    CancelMessage,
    CloseMessage,
    PingMessage,
    PongMessage,
    AudioFormat,
    ErrorMessage,
    FinalizeMessage,
    LocalSttProtocolError,
    ReadyMessage,
    RawUdsFrameType,
    StartMessage,
    TranscriptMessage,
    WarningMessage,
    decode_raw_uds_frame,
    encode_raw_uds_protocol_error,
    encode_raw_uds_server_message,
    parse_client_message,
    parse_raw_uds_client_frame,
    validate_audio_chunk,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
RAW_UDS_FRAME_TYPE_VALUES = {int(frame_type) for frame_type in RawUdsFrameType}
RAW_UDS_FRAME_TYPE_CODES = {frame_type.name: int(frame_type) for frame_type in RawUdsFrameType}
RAW_UDS_FRAME_TYPES = {name.lower(): value for name, value in RAW_UDS_FRAME_TYPE_CODES.items()}


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
        "protocols": _protocol_catalog(services.config),
    }


def _protocol_catalog(config: AppConfig | None = None) -> list[dict[str, object]]:
    local_stt_transport: dict[str, object] = {
        "mode": "tcp",
        "transport": "tcp_ws",
        "path": "/v1/stt/stream",
    }
    if config is not None and config.local_stt_socket_mode == "uds":
        local_stt_transport = {
            "mode": "uds",
            "transport": "uds_ws",
            "path": "/v1/stt/stream",
            "uds_path": config.local_stt_uds_path,
        }

    return [
        {
            "id": "rtc-asr-stream.v1",
            "transport": "websocket",
            "path": "/ws/stream",
            "docs": "/docs/api-reference.md#websocket-streaming",
            "status": "legacy",
            "notes": "Deprecated transport: buffered websocket contract; prefer /v1/stt/stream for native-local-stream compatibility and lower-latency framing guidance.",
            "message_format": "json-control-plus-binary-audio",
        },
        {
            "id": PROTOCOL_VERSION,
            "transport": "websocket",
            "path": "/v1/stt/stream",
            "docs": "/docs/local-stt-v1.md",
            "status": "preview",
            "message_format": "json-control-plus-binary-pcm16",
            "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
            "audio": {
                "sample_rate": HOT_PATH_SAMPLE_RATE,
                "channels": HOT_PATH_CHANNELS,
                "format": HOT_PATH_PCM_FORMAT,
                "frame_ms": HOT_PATH_FRAME_MS,
                "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
            },
            "partial_interval": {
                "request_field": "partial_interval_ms",
                "resolution_ms": HOT_PATH_FRAME_MS,
                "rounding": "ceil_to_audio_frame",
                "ready_metadata_field": "partial_interval_ms",
            },
            "start_control_payload": {
                "type": "start",
                "version": PROTOCOL_VERSION,
                "audio": {
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                    "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
                },
                "language": "en",
                "interim_results": True,
                "partial_interval_ms": 100,
            },
            "server_transport": local_stt_transport,
            "experimental_transports": [
                {
                    "transport": "raw_uds",
                    "status": "served" if config is not None and config.local_stt_raw_uds_enabled else "codec_only",
                    "enabled": bool(config is not None and config.local_stt_raw_uds_enabled),
                    "enable_env": "LOCAL_STT_RAW_UDS_ENABLED",
                    "path_env": "LOCAL_STT_RAW_UDS_PATH",
                    "uds_path": (
                        config.local_stt_raw_uds_path
                        if config is not None
                        else AppConfig().local_stt_raw_uds_path
                    ),
                    "plugin_config": {
                        "transport": "raw_uds",
                        "uds_path": (
                            config.local_stt_raw_uds_path
                            if config is not None
                            else AppConfig().local_stt_raw_uds_path
                        ),
                    },
                    "frame_header_bytes": RAW_UDS_HEADER_BYTES,
                    "per_frame_overhead_bytes": RAW_UDS_HEADER_BYTES,
                    "max_payload_bytes": RAW_UDS_MAX_PAYLOAD_BYTES,
                    "frame_format": "uint8_type_uint32_len_le",
                    "frame_direction": RAW_UDS_FRAME_DIRECTION,
                    "keepalive_payloads": ["empty_ping", "json_ping", "empty_pong", "json_pong"],
                    "comparison_required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
                    "benchmark_command": (
                        "python scripts/bench_local_stt_stream.py --transport raw_uds "
                        "--uds-path <LOCAL_STT_RAW_UDS_PATH> --input-raw-pcm <clip.pcm>"
                    ),
                    "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
                    "semantic_lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
                    "start_control_payload": {
                        "type": "start",
                        "protocol": "local-stt-v1",
                        "sample_rate": HOT_PATH_SAMPLE_RATE,
                        "channels": HOT_PATH_CHANNELS,
                        "format": HOT_PATH_PCM_FORMAT,
                        "frame_ms": HOT_PATH_FRAME_MS,
                        "partial_interval_ms": 100,
                    },
                    "error_handling": [
                        "bad_frame_type",
                        "malformed_json_control",
                        "invalid_json_payload",
                        "oversized_payload",
                        "incomplete_frame",
                        "frame_length_mismatch",
                        "invalid_client_frame_type",
                        "invalid_server_frame_type",
                    ],
                    "error_codes": [
                        "raw_uds_unsupported_frame_type",
                        "raw_uds_malformed_json_control",
                        "raw_uds_invalid_json",
                        "raw_uds_payload_too_large",
                        "raw_uds_incomplete_frame",
                        "raw_uds_frame_length_mismatch",
                        "raw_uds_invalid_client_frame_type",
                        "raw_uds_invalid_server_frame_type",
                    ],
                    "shared_stream_runtime": True,
                    "benchmark_metrics": [
                        "time_to_first_interim_ms",
                        "time_to_final_after_finalize_ms",
                        "send_queue_depth_p95",
                        "asr_queue_delay_p95",
                        "protocol_errors",
                        "cpu_utilization",
                    ],
                    "benchmark_metric_requirements": {
                        "time_to_first_interim_ms": ["p50", "p95", "p99"],
                        "time_to_final_after_finalize_ms": ["p50", "p95", "p99"],
                        "send_queue_depth_p95": ["p95"],
                        "asr_queue_delay_p95": ["p95"],
                        "protocol_errors": ["p50", "p95", "p99"],
                        "cpu_utilization": ["if_available"],
                    },
                    "latency_win_threshold_ms": 5.0,
                    "recommendation_gate": "experimental_until_p95_win_over_uds_ws_is_at_least_5ms",
                    "frame_types": RAW_UDS_FRAME_TYPES,
                    "frame_type_codes": RAW_UDS_FRAME_TYPE_CODES,
                    "notes": (
                        "Raw UDS framing is served on the configured Unix socket when LOCAL_STT_RAW_UDS_ENABLED=true; keep it experimental until benchmarked against UDS websocket."
                        if config is not None and config.local_stt_raw_uds_enabled
                        else "Raw UDS framing is available as a tested codec for latency experiments; enable LOCAL_STT_RAW_UDS_ENABLED=true to serve it."
                    ),
                }
            ],
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

    def record_partial(
        self,
        transcript: dict[str, object],
        *,
        chunks_received: int | None = None,
        audio_received_ms: int | None = None,
    ) -> None:
        self.last_partial_result = transcript
        self.last_partial_chunks_received = (
            chunks_received if chunks_received is not None else self.chunks_received
        )
        self.last_partial_audio_received_ms = (
            audio_received_ms if audio_received_ms is not None else self.audio_received_ms()
        )

    def audio_received_ms(self) -> int:
        return _audio_bytes_to_duration_ms(len(self.audio_buffer), self.sample_rate)

    def should_emit_partial(self) -> bool:
        if self.partial_interval_audio_ms is None:
            return (self.chunks_received - self.last_partial_chunks_received) >= self.partial_interval_chunks
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
class StreamRuntime:
    stream_id: int
    client_stream_id: str | None
    session: StreamSession
    services: AppServices
    audio_updated: asyncio.Event = field(default_factory=asyncio.Event)
    finalize_requested: asyncio.Event = field(default_factory=asyncio.Event)
    cancel_requested: asyncio.Event = field(default_factory=asyncio.Event)
    outgoing_events: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    latest_revision: int = 0
    decode_in_flight: bool = False
    partial_decode_started: bool = False
    dirty: bool = False
    closed: bool = False
    final_emitted: bool = False

    def note_audio(self) -> None:
        self.dirty = True
        self.audio_updated.set()

    def request_finalize(self) -> None:
        self.finalize_requested.set()
        self.audio_updated.set()

    def request_cancel(self) -> None:
        self.cancel_requested.set()
        self.session.audio_buffer.clear()
        self.session.last_partial_result = None
        self.audio_updated.set()

    def close(self) -> None:
        self.closed = True
        self.audio_updated.set()


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
    audio_processor = AudioProcessor(
        AudioConfig(
            sample_rate=runtime_config.local_stt_target_sample_rate,
            enable_pcm16_fast_path=runtime_config.local_stt_enable_pcm16_fast_path,
            require_target_sample_rate=runtime_config.local_stt_require_target_sample_rate,
        )
    )
    runtime_transcriber = transcriber or build_transcriber(runtime_config, audio_processor)
    services = AppServices(
        config=runtime_config,
        audio_processor=audio_processor,
        transcriber=runtime_transcriber,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.services = services
        raw_uds_server: asyncio.Server | None = None
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
        if services.config.local_stt_raw_uds_enabled:
            raw_uds_server = await asyncio.start_unix_server(
                lambda reader, writer: _raw_uds_stream_client(reader, writer, services),
                path=_prepare_uds_socket(services.config.local_stt_raw_uds_path, env_name="LOCAL_STT_RAW_UDS_PATH"),
            )
            logger.info("Raw UDS Local STT v1 listener ready at %s", services.config.local_stt_raw_uds_path)
        try:
            yield
        finally:
            if raw_uds_server is not None:
                raw_uds_server.close()
                await raw_uds_server.wait_closed()
                with suppress(FileNotFoundError):
                    Path(services.config.local_stt_raw_uds_path).unlink()
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
            "protocols": _protocol_catalog(current.config),
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
        runtime: StreamRuntime | None = None
        worker_task: asyncio.Task[None] | None = None
        send_task: asyncio.Task[None] | None = None
        next_stream_id = 1

        async def stop_runtime() -> None:
            nonlocal runtime, worker_task, send_task
            if runtime is not None:
                runtime.close()
            if worker_task is not None:
                try:
                    await worker_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            if send_task is not None and not send_task.done():
                send_task.cancel()
            if send_task is not None:
                try:
                    await send_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            runtime = None
            worker_task = None
            send_task = None

        try:
            while True:
                receive_task = asyncio.create_task(_receive_local_stt_event(websocket))
                wait_tasks: set[asyncio.Task[object]] = {receive_task}
                if worker_task is not None:
                    wait_tasks.add(worker_task)
                done, _pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

                if worker_task is not None and worker_task in done:
                    receive_task.cancel()
                    try:
                        await receive_task
                    except asyncio.CancelledError:
                        pass
                    await worker_task

                payload, event_type = await receive_task

                if event_type == "start":
                    if runtime is not None:
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
                    runtime = StreamRuntime(
                        stream_id=session.stream_id,
                        client_stream_id=session.client_stream_id,
                        session=session,
                        services=services,
                    )
                    worker_task = asyncio.create_task(_local_stt_asr_worker(runtime))
                    send_task = asyncio.create_task(_send_queued_events(websocket, runtime))
                    await websocket.send_json(
                        _local_stt_ready_event(
                            session,
                            backend=services.transcriber.backend_name,
                            model=services.transcriber.model_name,
                        )
                    )
                    continue

                if event_type == "audio":
                    if runtime is None:
                        raise LocalSttProtocolError(
                            "Send a start event before audio chunks",
                            code="invalid_state",
                        )

                    try:
                        runtime.session.append_audio(payload)
                    except StreamClientError as exc:
                        raise LocalSttProtocolError(
                            str(exc),
                            code="buffer_limit_exceeded",
                            metadata={"max_buffer_bytes": runtime.session.max_buffer_bytes},
                        ) from exc

                    runtime.note_audio()
                    continue

                if event_type == "finalize":
                    if runtime is None:
                        raise LocalSttProtocolError(
                            "Send a start event before finalizing the stream",
                            code="invalid_state",
                        )
                    if not runtime.session.audio_buffer:
                        raise LocalSttProtocolError(
                            "No audio chunks received for this stream",
                            code="invalid_state",
                        )

                    runtime.request_finalize()
                    assert worker_task is not None
                    await worker_task
                    await runtime.outgoing_events.join()
                    if send_task is not None:
                        send_task.cancel()
                        try:
                            await send_task
                        except asyncio.CancelledError:
                            pass
                    runtime = None
                    worker_task = None
                    send_task = None
                    continue

                if event_type == "cancel":
                    if runtime is None:
                        raise LocalSttProtocolError(
                            "Send a start event before canceling the stream",
                            code="invalid_state",
                        )

                    runtime.request_cancel()
                    await runtime.outgoing_events.put(_local_stt_cancel_warning_event(runtime.session))
                    await runtime.outgoing_events.join()
                    await stop_runtime()
                    continue

                if event_type == "ping":
                    if runtime is None or send_task is None:
                        await websocket.send_json(_local_stt_pong_event(payload))
                    else:
                        await runtime.outgoing_events.put(_local_stt_pong_event(payload))
                    continue

                if event_type == "pong":
                    continue

                if event_type == "close":
                    if runtime is not None:
                        await stop_runtime()
                    await websocket.send_json({"type": "closed", "reason": "client_close", "metadata": {}})
                    await websocket.close(code=1000)
                    return

                raise LocalSttProtocolError(
                    f"Unsupported Local STT v1 message type: {event_type}",
                    code="unsupported_message_type",
                )
        except WebSocketDisconnect:
            await stop_runtime()
            return
        except ASRUnavailableError as exc:
            services.preload_error = str(exc)
            await stop_runtime()
            await _close_local_stt_error(
                websocket,
                ErrorMessage(type="error", code="backend_unavailable", message=str(exc)),
                close_code=1011,
            )
        except LocalSttProtocolError as exc:
            await stop_runtime()
            await _close_local_stt_error(websocket, exc.as_event(), close_code=1003)
        except Exception as exc:  # pragma: no cover - defensive websocket boundary
            _record_lazy_load_failure(services, exc)
            await stop_runtime()
            logger.exception("Unexpected Local STT v1 websocket stream error")
            await _close_local_stt_error(
                websocket,
                ErrorMessage(type="error", code="internal_error", message="Unexpected streaming error"),
                close_code=1011,
            )

    return app


async def _send_queued_events(websocket: WebSocket, runtime: StreamRuntime) -> None:
    while not runtime.closed or not runtime.outgoing_events.empty():
        try:
            event = await asyncio.wait_for(runtime.outgoing_events.get(), timeout=0.1)
        except TimeoutError:
            continue
        try:
            await websocket.send_json(event)
        finally:
            runtime.outgoing_events.task_done()


class RawUdsClientDisconnected(Exception):
    """Raised when a raw UDS client closes the socket between frames."""


async def _raw_uds_stream_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    services: AppServices,
) -> None:
    runtime: StreamRuntime | None = None
    worker_task: asyncio.Task[None] | None = None
    send_task: asyncio.Task[None] | None = None
    next_stream_id = 1

    async def stop_runtime() -> None:
        nonlocal runtime, worker_task, send_task
        if runtime is not None:
            runtime.close()
        if worker_task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await worker_task
        if send_task is not None and not send_task.done():
            send_task.cancel()
        if send_task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await send_task
        runtime = None
        worker_task = None
        send_task = None

    try:
        while True:
            receive_task = asyncio.create_task(_receive_raw_uds_event(reader))
            wait_tasks: set[asyncio.Task[object]] = {receive_task}
            if worker_task is not None:
                wait_tasks.add(worker_task)
            done, _pending = await asyncio.wait(wait_tasks, return_when=asyncio.FIRST_COMPLETED)

            if worker_task is not None and worker_task in done:
                receive_task.cancel()
                with suppress(asyncio.CancelledError):
                    await receive_task
                await worker_task

            payload, event_type = await receive_task

            if event_type == "start":
                if runtime is not None:
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
                runtime = StreamRuntime(
                    stream_id=session.stream_id,
                    client_stream_id=session.client_stream_id,
                    session=session,
                    services=services,
                )
                worker_task = asyncio.create_task(_local_stt_asr_worker(runtime))
                send_task = asyncio.create_task(_send_queued_raw_uds_events(writer, runtime))
                await _write_raw_uds_event(
                    writer,
                    _local_stt_ready_event(
                        session,
                        backend=services.transcriber.backend_name,
                        model=services.transcriber.model_name,
                    ),
                )
                continue

            if event_type == "audio":
                if runtime is None:
                    raise LocalSttProtocolError(
                        "Send a start event before audio chunks",
                        code="invalid_state",
                    )
                try:
                    runtime.session.append_audio(payload)
                except StreamClientError as exc:
                    raise LocalSttProtocolError(
                        str(exc),
                        code="buffer_limit_exceeded",
                        metadata={"max_buffer_bytes": runtime.session.max_buffer_bytes},
                    ) from exc
                runtime.note_audio()
                continue

            if event_type == "finalize":
                if runtime is None:
                    raise LocalSttProtocolError(
                        "Send a start event before finalizing the stream",
                        code="invalid_state",
                    )
                if not runtime.session.audio_buffer:
                    raise LocalSttProtocolError(
                        "No audio chunks received for this stream",
                        code="invalid_state",
                    )
                runtime.request_finalize()
                assert worker_task is not None
                await worker_task
                await runtime.outgoing_events.join()
                if send_task is not None:
                    send_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await send_task
                runtime = None
                worker_task = None
                send_task = None
                continue

            if event_type == "cancel":
                if runtime is None:
                    raise LocalSttProtocolError(
                        "Send a start event before canceling the stream",
                        code="invalid_state",
                    )
                runtime.request_cancel()
                await runtime.outgoing_events.put(_local_stt_cancel_warning_event(runtime.session))
                await runtime.outgoing_events.join()
                await stop_runtime()
                continue

            if event_type == "ping":
                if runtime is None or send_task is None:
                    await _write_raw_uds_event(writer, _local_stt_pong_event(payload))
                else:
                    await runtime.outgoing_events.put(_local_stt_pong_event(payload))
                continue

            if event_type == "pong":
                continue

            if event_type == "close":
                if runtime is not None:
                    await stop_runtime()
                await _write_raw_uds_event(writer, {"type": "closed", "reason": "client_close", "metadata": {}})
                return

            raise LocalSttProtocolError(
                f"Unsupported Local STT v1 message type: {event_type}",
                code="unsupported_message_type",
            )
    except RawUdsClientDisconnected:
        await stop_runtime()
    except ASRUnavailableError as exc:
        services.preload_error = str(exc)
        await stop_runtime()
        await _write_raw_uds_event(
            writer,
            ErrorMessage(type="error", code="backend_unavailable", message=str(exc)).model_dump(),
        )
    except LocalSttProtocolError as exc:
        await stop_runtime()
        await _write_raw_uds_protocol_error(writer, exc)
    except Exception as exc:  # pragma: no cover - defensive socket boundary
        _record_lazy_load_failure(services, exc)
        await stop_runtime()
        logger.exception("Unexpected Local STT v1 raw UDS stream error")
        await _write_raw_uds_event(
            writer,
            ErrorMessage(type="error", code="internal_error", message="Unexpected streaming error").model_dump(),
        )
    finally:
        writer.close()
        with suppress(ConnectionError, RuntimeError):
            await writer.wait_closed()


async def _send_queued_raw_uds_events(writer: asyncio.StreamWriter, runtime: StreamRuntime) -> None:
    while not runtime.closed or not runtime.outgoing_events.empty():
        try:
            event = await asyncio.wait_for(runtime.outgoing_events.get(), timeout=0.1)
        except TimeoutError:
            continue
        try:
            await _write_raw_uds_event(writer, event)
        finally:
            runtime.outgoing_events.task_done()


async def _receive_raw_uds_event(reader: asyncio.StreamReader) -> tuple[object, str]:
    try:
        header = await reader.readexactly(RAW_UDS_HEADER_BYTES)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            raise RawUdsClientDisconnected() from exc
        raise LocalSttProtocolError(
            f"Raw UDS stream ended while reading frame header; received {len(exc.partial)} of {RAW_UDS_HEADER_BYTES} bytes",
            code="raw_uds_incomplete_frame",
        ) from exc
    frame_type = header[0]
    if frame_type not in RAW_UDS_FRAME_TYPE_VALUES:
        raise LocalSttProtocolError(
            f"Unsupported Raw UDS frame type: {frame_type}",
            code="raw_uds_unsupported_frame_type",
        )
    payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
    if payload_length > RAW_UDS_MAX_PAYLOAD_BYTES:
        raise LocalSttProtocolError(
            f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
            code="raw_uds_payload_too_large",
        )
    try:
        frame_payload = await reader.readexactly(payload_length)
    except asyncio.IncompleteReadError as exc:
        raise LocalSttProtocolError(
            f"Raw UDS stream ended while reading frame payload; received {len(exc.partial)} of {payload_length} bytes",
            code="raw_uds_incomplete_frame",
        ) from exc
    frame = decode_raw_uds_frame(header + frame_payload)

    payload = parse_raw_uds_client_frame(frame)
    if isinstance(payload, bytes):
        return payload, "audio"
    if isinstance(payload, StartMessage):
        return _parse_local_stt_start_message(payload.model_dump()), "start"
    if isinstance(payload, FinalizeMessage):
        return payload, "finalize"
    if isinstance(payload, CancelMessage):
        return payload, "cancel"
    if isinstance(payload, CloseMessage):
        return payload, "close"
    if isinstance(payload, PingMessage):
        return payload, "ping"
    if isinstance(payload, PongMessage):
        return payload, "pong"
    raise LocalSttProtocolError(
        f"Unsupported Local STT v1 message type: {getattr(payload, 'type', type(payload).__name__)}",
        code="unsupported_message_type",
    )


async def _write_raw_uds_event(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
    writer.write(encode_raw_uds_server_message(payload))
    await writer.drain()


async def _write_raw_uds_protocol_error(writer: asyncio.StreamWriter, exc: LocalSttProtocolError) -> None:
    writer.write(encode_raw_uds_protocol_error(exc))
    await writer.drain()

async def _local_stt_asr_worker(runtime: StreamRuntime) -> None:
    session = runtime.session
    while True:
        await runtime.audio_updated.wait()
        runtime.audio_updated.clear()

        if runtime.cancel_requested.is_set():
            return
        if runtime.final_emitted or runtime.closed:
            return

        if runtime.finalize_requested.is_set():
            final_audio = bytes(session.audio_buffer)
            final_result = await _resolve_final_result_async(session, runtime.services)
            if runtime.cancel_requested.is_set() or runtime.closed:
                return
            await runtime.outgoing_events.put(
                _local_stt_transcript_event(
                    session,
                    final_result,
                    is_final=True,
                    transcribed_audio_bytes=len(final_audio),
                )
            )
            runtime.final_emitted = True
            runtime.closed = True
            return

        if runtime.partial_decode_started or not session.interim_results or not session.should_emit_partial():
            runtime.dirty = False
            continue

        runtime.dirty = False
        runtime.partial_decode_started = True
        partial_audio_bytes = session.partial_audio_bytes()
        partial_chunks_received = session.chunks_received
        partial_audio_received_ms = session.audio_received_ms()
        runtime.decode_in_flight = True
        try:
            partial = await _run_transcription_async(
                runtime.services,
                audio_bytes=partial_audio_bytes,
                language=session.language,
                sample_rate=session.sample_rate,
            )
        finally:
            runtime.decode_in_flight = False
            runtime.partial_decode_started = False

        if runtime.cancel_requested.is_set() or runtime.final_emitted or runtime.closed:
            return
        if runtime.finalize_requested.is_set():
            if partial_chunks_received == session.chunks_received and _partial_covers_full_buffer(session):
                session.record_partial(
                    partial,
                    chunks_received=partial_chunks_received,
                    audio_received_ms=partial_audio_received_ms,
                )
            runtime.audio_updated.set()
            continue
        session.record_partial(
            partial,
            chunks_received=partial_chunks_received,
            audio_received_ms=partial_audio_received_ms,
        )
        partial_text = str(partial.get("text", "")).strip()
        if partial_text:
            await runtime.outgoing_events.put(
                _local_stt_transcript_event(
                    session,
                    partial,
                    is_final=False,
                    transcribed_audio_bytes=len(partial_audio_bytes),
                )
            )
        if runtime.dirty:
            runtime.audio_updated.set()


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
    has_nested_v1_shape = "audio" in payload or "version" in payload
    is_flat_start = not has_nested_v1_shape and any(
        key in payload for key in {"protocol", "sample_rate", "channels", "format", "frame_ms"}
    )
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

    legacy_partial_interval_chunks = payload.get("partial_interval_chunks")

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
    elif legacy_partial_interval_chunks is not None:
        if not isinstance(legacy_partial_interval_chunks, int) or legacy_partial_interval_chunks < 1:
            raise LocalSttProtocolError("partial_interval_chunks must be a positive integer")
        partial_interval_chunks = legacy_partial_interval_chunks

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
        "partial_interval_chunks": session.partial_interval_chunks,
        "partial_interval_ms": session.partial_interval_audio_ms
        if session.partial_interval_audio_ms is not None
        else session.partial_interval_chunks * HOT_PATH_FRAME_MS,
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
    if _can_reuse_last_partial(session):
        assert session.last_partial_result is not None
        return session.last_partial_result

    return _run_transcription(
        services,
        audio_bytes=bytes(session.audio_buffer),
        language=session.language,
        sample_rate=session.sample_rate,
    )


async def _resolve_final_result_async(session: StreamSession, services: AppServices) -> dict[str, object]:
    if _can_reuse_last_partial(session):
        assert session.last_partial_result is not None
        return session.last_partial_result

    return await _run_transcription_async(
        services,
        audio_bytes=bytes(session.audio_buffer),
        language=session.language,
        sample_rate=session.sample_rate,
    )


def _can_reuse_last_partial(session: StreamSession) -> bool:
    return (
        session.last_partial_result is not None
        and session.last_partial_chunks_received == session.chunks_received
        and _partial_covers_full_buffer(session)
    )


def _partial_covers_full_buffer(session: StreamSession) -> bool:
    return session.partial_window_bytes is None or len(session.audio_buffer) <= session.partial_window_bytes


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


async def _run_transcription_async(
    services: AppServices,
    *,
    audio_bytes: bytes,
    language: str | None,
    sample_rate: int | None,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_transcription,
        services,
        audio_bytes=audio_bytes,
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


def _prepare_uds_socket(path: str, *, env_name: str = "LOCAL_STT_UDS_PATH") -> str:
    socket_path = Path(path)
    try:
        socket_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot create {env_name} parent directory for {socket_path}. "
            "Choose a writable socket path or fix directory permissions."
        ) from exc

    try:
        mode = socket_path.stat().st_mode
    except FileNotFoundError:
        return str(socket_path)
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot inspect {env_name} {socket_path}. "
            "Choose a readable socket path or fix file permissions."
        ) from exc

    if not stat.S_ISSOCK(mode):
        raise RuntimeError(
            f"{env_name} exists and is not a socket: {socket_path}. "
            "Remove it or choose a different path."
        )
    try:
        socket_path.unlink()
    except PermissionError as exc:
        raise RuntimeError(
            f"Cannot remove stale {env_name} socket {socket_path}. "
            "Fix socket directory permissions or remove the stale socket manually."
        ) from exc
    return str(socket_path)


def main() -> None:
    config = AppConfig.from_env()
    if config.local_stt_socket_mode == "uds":
        uvicorn.run(
            "src.main:app",
            uds=_prepare_uds_socket(config.local_stt_uds_path),
            log_level="info",
        )
        return

    uvicorn.run(
        "src.main:app",
        host=config.host,
        port=config.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
