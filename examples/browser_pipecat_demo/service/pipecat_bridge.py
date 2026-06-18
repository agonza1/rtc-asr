from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from src.rtc_client import AsyncLocalSttClient, TranscriptEvent

logger = logging.getLogger(__name__)

DEFAULT_RTC_ASR_CHUNK_MS = 100
MIN_RTC_ASR_CHUNK_MS = 80
MAX_RTC_ASR_CHUNK_MS = 160


class BridgeUnavailableError(RuntimeError):
    """Raised when the demo bridge cannot create a media session."""

    error_code = "BRIDGE_UNAVAILABLE"
    status_code = 502
    bridge_status = "error"


class PipecatDependencyMissingError(BridgeUnavailableError):
    """Raised when the optional Pipecat WebRTC runtime is not installed."""

    error_code = "PIPECAT_WEBRTC_DEPENDENCY_MISSING"
    status_code = 501
    bridge_status = "dependency_missing"


class BridgeRuntimeError(BridgeUnavailableError):
    """Raised when Pipecat signaling or ASR relay startup fails."""

    error_code = "PIPECAT_BRIDGE_RUNTIME_ERROR"
    status_code = 502
    bridge_status = "error"


class SessionState(str, Enum):
    STARTING = "starting"
    WAITING_FOR_PIPECAT = "waiting_for_pipecat"
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass(slots=True)
class DemoSession:
    session_id: str
    created_at: datetime
    state: SessionState
    offer_type: str
    offer_sdp_length: int
    answer_sdp: str | None = None
    answer_type: str | None = None
    pc_id: str | None = None
    error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "offer_type": self.offer_type,
            "offer_sdp_length": self.offer_sdp_length,
            "has_answer": self.answer_sdp is not None,
            "answer_type": self.answer_type,
            "pc_id": self.pc_id,
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class PipecatRuntime:
    request_cls: type
    request_handler_cls: type
    transport_cls: type
    transport_params_cls: type
    pipeline_cls: type
    frame_processor_cls: type
    frame_direction_cls: type
    input_audio_frame_cls: type
    pipeline_worker_cls: type
    pipeline_params_cls: type
    worker_runner_cls: type


ASRClientFactory = Callable[[str], Any]
PipecatRuntimeLoader = Callable[[], PipecatRuntime]
AppMessageSender = Callable[[dict[str, object]], None]
ErrorCallback = Callable[[str], None]


def _chunk_ms_from_env(value: str | None) -> int:
    if value is None or value == "":
        return DEFAULT_RTC_ASR_CHUNK_MS
    try:
        chunk_ms = int(value)
    except ValueError as exc:
        raise ValueError("RTC_ASR_CHUNK_MS must be an integer") from exc
    if not MIN_RTC_ASR_CHUNK_MS <= chunk_ms <= MAX_RTC_ASR_CHUNK_MS:
        raise ValueError(
            f"RTC_ASR_CHUNK_MS must be between {MIN_RTC_ASR_CHUNK_MS} and {MAX_RTC_ASR_CHUNK_MS}"
        )
    return chunk_ms


def load_pipecat_runtime() -> PipecatRuntime:
    try:
        from pipecat.frames.frames import InputAudioRawFrame
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker
        from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
        from pipecat.transports.base_transport import TransportParams
        from pipecat.transports.smallwebrtc.request_handler import (
            SmallWebRTCRequest,
            SmallWebRTCRequestHandler,
        )
        from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    except Exception as exc:  # pragma: no cover - exercised via missing dependency tests.
        raise PipecatDependencyMissingError(
            "Install the demo WebRTC extras with "
            "`pip install -r examples/browser_pipecat_demo/requirements.txt` "
            "to enable Pipecat SmallWebRTC."
        ) from exc

    try:
        from pipecat.workers.runner import WorkerRunner
    except ModuleNotFoundError:
        from pipecat.pipeline.runner import WorkerRunner

    return PipecatRuntime(
        request_cls=SmallWebRTCRequest,
        request_handler_cls=SmallWebRTCRequestHandler,
        transport_cls=SmallWebRTCTransport,
        transport_params_cls=TransportParams,
        pipeline_cls=Pipeline,
        frame_processor_cls=FrameProcessor,
        frame_direction_cls=FrameDirection,
        input_audio_frame_cls=InputAudioRawFrame,
        pipeline_worker_cls=PipelineWorker,
        pipeline_params_cls=PipelineParams,
        worker_runner_cls=WorkerRunner,
    )


class RTCASRAudioRelay:
    def __init__(
        self,
        *,
        session_id: str,
        rtc_asr_ws_url: str,
        chunk_ms: int,
        send_app_message: AppMessageSender,
        mark_failed: ErrorCallback,
        asr_client_factory: ASRClientFactory = AsyncLocalSttClient,
    ) -> None:
        self.session_id = session_id
        self.rtc_asr_ws_url = rtc_asr_ws_url
        self.chunk_ms = chunk_ms
        self._send_app_message = send_app_message
        self._mark_failed = mark_failed
        self._asr_client_factory = asr_client_factory
        self._buffer = bytearray()
        self._client: Any | None = None
        self._sample_rate: int | None = None
        self._num_channels: int | None = None
        self._final_event: asyncio.Future[TranscriptEvent] | None = None
        self._receiver_task: asyncio.Task[None] | None = None

    async def handle_audio_frame(self, frame: Any) -> None:
        audio = bytes(getattr(frame, "audio", b""))
        if not audio:
            return

        sample_rate = int(getattr(frame, "sample_rate", 16000))
        num_channels = int(getattr(frame, "num_channels", 1))
        await self._ensure_client(sample_rate=sample_rate, num_channels=num_channels)

        self._buffer.extend(audio)
        chunk_size = self._chunk_size_bytes(sample_rate=sample_rate, num_channels=num_channels)
        while len(self._buffer) >= chunk_size:
            chunk = bytes(self._buffer[:chunk_size])
            del self._buffer[:chunk_size]
            await self._send_chunk(chunk)

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            if self._buffer:
                await self._send_chunk(bytes(self._buffer))
                self._buffer.clear()
            finalize = getattr(self._client, "finalize", None)
            if callable(finalize):
                await finalize()
                if self._final_event is not None:
                    await asyncio.wait_for(asyncio.shield(self._final_event), timeout=5.0)
            else:
                final_event = await self._client.stop()
                self._send_transcript_event(final_event)
        except Exception as exc:
            self._send_error(f"ASR relay shutdown failed: {exc}")
        finally:
            if self._receiver_task is not None:
                self._receiver_task.cancel()
                try:
                    await self._receiver_task
                except asyncio.CancelledError:
                    pass
                self._receiver_task = None
            await self._client.close()
            self._client = None
            self._final_event = None

    async def _ensure_client(self, *, sample_rate: int, num_channels: int) -> None:
        if self._client is not None:
            return
        self._sample_rate = sample_rate
        self._num_channels = num_channels
        self._client = self._asr_client_factory(self.rtc_asr_ws_url)
        self._final_event = asyncio.get_running_loop().create_future()
        try:
            await asyncio.wait_for(
                self._client.start(
                    sample_rate=sample_rate,
                    partial_interval_ms=self.chunk_ms,
                    client_stream_id=self.session_id,
                ),
                timeout=5.0,
            )
        except Exception as exc:
            self._client = None
            self._final_event = None
            self._send_error(f"ASR websocket start failed: {exc}")
            raise
        if hasattr(self._client, "recv_event"):
            self._receiver_task = asyncio.create_task(self._pump_events())
        self._send_app_message({
            "type": "status",
            "message": "ASR websocket connected.",
            "session_id": self.session_id,
            "sample_rate": sample_rate,
            "num_channels": num_channels,
            "chunk_ms": self.chunk_ms,
        })

    async def _send_chunk(self, chunk: bytes) -> None:
        if self._client is None:
            raise RuntimeError("ASR client is not started")
        try:
            await self._client.send_audio(chunk)
        except Exception as exc:
            self._send_error(f"ASR websocket send failed: {exc}")
            raise

    async def _pump_events(self) -> None:
        assert self._client is not None
        try:
            while True:
                event = await self._client.recv_event()
                if event is None:
                    continue
                self._send_transcript_event(event)
                if event.is_final:
                    if self._final_event is not None and not self._final_event.done():
                        self._final_event.set_result(event)
                    return
                if event.type == "error":
                    if self._final_event is not None and not self._final_event.done():
                        self._final_event.set_exception(RuntimeError(event.text or "ASR websocket error"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._final_event is not None and not self._final_event.done():
                self._final_event.set_exception(exc)
            self._send_error(f"ASR websocket receive failed: {exc}")
            raise

    def _send_transcript_event(self, event: TranscriptEvent) -> None:
        event_type = "final" if event.is_final or event.type == "final" else event.type
        if event_type not in {"partial", "final", "error", "canceled"}:
            event_type = "status"
        self._send_app_message({
            "type": event_type,
            "text": event.text,
            "session_id": self.session_id,
            "chunks_received": event.chunks_received,
        })

    def _send_error(self, message: str) -> None:
        self._mark_failed(message)
        self._send_app_message({
            "type": "error",
            "message": message,
            "session_id": self.session_id,
        })

    def _chunk_size_bytes(self, *, sample_rate: int, num_channels: int) -> int:
        return max(1, int(sample_rate * num_channels * 2 * (self.chunk_ms / 1000)))


def build_relay_processor_cls(runtime: PipecatRuntime) -> type:
    class RTCASRRelayProcessor(runtime.frame_processor_cls):  # type: ignore[misc, valid-type]
        def __init__(self, relay: RTCASRAudioRelay) -> None:
            super().__init__(name="RTCASRRelayProcessor")
            self._relay = relay

        async def process_frame(self, frame: Any, direction: Any) -> None:
            await super().process_frame(frame, direction)
            if isinstance(frame, runtime.input_audio_frame_cls):
                await self._relay.handle_audio_frame(frame)
            await self.push_frame(frame, direction)

        async def cleanup(self) -> None:
            await self._relay.close()
            await super().cleanup()

    return RTCASRRelayProcessor


class PipecatDemoBridge:
    """Session facade for the local browser-to-Pipecat demo."""

    def __init__(
        self,
        *,
        rtc_asr_ws_url: str | None = None,
        chunk_ms: int | None = None,
        runtime_loader: PipecatRuntimeLoader = load_pipecat_runtime,
        asr_client_factory: ASRClientFactory = AsyncLocalSttClient,
        request_handler: Any | None = None,
    ) -> None:
        self.rtc_asr_ws_url = rtc_asr_ws_url or os.getenv(
            "RTC_ASR_WS_URL",
            "ws://127.0.0.1:8080/v1/stt/stream",
        )
        self.chunk_ms = chunk_ms if chunk_ms is not None else _chunk_ms_from_env(
            os.getenv("RTC_ASR_CHUNK_MS")
        )
        self._runtime_loader = runtime_loader
        self._asr_client_factory = asr_client_factory
        self._runtime: PipecatRuntime | None = None
        self._request_handler = request_handler
        self._dependency_error: PipecatDependencyMissingError | None = None
        self._sessions: dict[str, DemoSession] = {}
        self._pipeline_tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def bridge_status(self) -> str:
        try:
            self._ensure_runtime()
        except PipecatDependencyMissingError as exc:
            self._dependency_error = exc
            return exc.bridge_status
        return "ready"

    def config(self) -> dict[str, object]:
        return {
            "service": "browser-pipecat-demo",
            "route": "/rtc-asr",
            "pipecat_transport": "smallwebrtc",
            "rtc_asr_ws_url": self.rtc_asr_ws_url,
            "rtc_asr_chunk_ms": self.chunk_ms,
            "bridge_status": self.bridge_status,
        }

    async def create_session(
        self,
        *,
        offer_type: str,
        offer_sdp: str,
        pc_id: str | None = None,
        restart_pc: bool | None = None,
        request_data: Any | None = None,
    ) -> DemoSession:
        session = DemoSession(
            session_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            state=SessionState.STARTING,
            offer_type=offer_type,
            offer_sdp_length=len(offer_sdp),
            metadata={
                "rtc_asr_ws_url": self.rtc_asr_ws_url,
                "rtc_asr_chunk_ms": str(self.chunk_ms),
            },
        )
        self._sessions[session.session_id] = session

        try:
            runtime = self._ensure_runtime()
            request = runtime.request_cls(
                sdp=offer_sdp,
                type=offer_type,
                pc_id=pc_id,
                restart_pc=restart_pc,
                request_data=request_data,
            )
            session.state = SessionState.WAITING_FOR_PIPECAT
            answer = await self._request_handler.handle_web_request(
                request,
                lambda connection: self._start_pipeline(session, connection, runtime),
            )
            if not answer or not answer.get("sdp") or not answer.get("pc_id"):
                raise BridgeRuntimeError("Pipecat SmallWebRTC did not return a complete SDP answer.")
        except BridgeUnavailableError as exc:
            session.state = SessionState.FAILED
            session.error = exc.error_code
            raise
        except Exception as exc:
            session.state = SessionState.FAILED
            session.error = BridgeRuntimeError.error_code
            logger.exception("browser_pipecat_demo_session_failed")
            raise BridgeRuntimeError("Pipecat bridge failed while creating the WebRTC session.") from exc

        session.answer_sdp = str(answer["sdp"])
        session.answer_type = str(answer.get("type", "answer"))
        session.pc_id = str(answer["pc_id"])
        session.state = SessionState.CONNECTED
        session.metadata["pc_id"] = session.pc_id
        session.metadata["answer_type"] = session.answer_type
        return session

    def get_session(self, session_id: str) -> DemoSession | None:
        return self._sessions.get(session_id)

    async def close_session(self, session_id: str) -> None:
        task = self._pipeline_tasks.pop(session_id, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    def _ensure_runtime(self) -> PipecatRuntime:
        if self._runtime is None:
            self._runtime = self._runtime_loader()
        if self._request_handler is None:
            self._request_handler = self._runtime.request_handler_cls()
        return self._runtime

    async def _start_pipeline(
        self,
        session: DemoSession,
        webrtc_connection: Any,
        runtime: PipecatRuntime,
    ) -> None:
        task = asyncio.create_task(self._run_pipeline(session, webrtc_connection, runtime))
        self._pipeline_tasks[session.session_id] = task

        def _handle_done(done_task: asyncio.Task[None]) -> None:
            self._pipeline_tasks.pop(session.session_id, None)
            if done_task.cancelled():
                return
            if done_task.exception() is not None:
                session.state = SessionState.FAILED
                session.error = BridgeRuntimeError.error_code

        task.add_done_callback(_handle_done)

    async def _run_pipeline(
        self,
        session: DemoSession,
        webrtc_connection: Any,
        runtime: PipecatRuntime,
    ) -> None:
        def send_app_message(message: dict[str, object]) -> None:
            webrtc_connection.send_app_message(message)

        def mark_failed(message: str) -> None:
            session.state = SessionState.FAILED
            session.error = message

        relay = RTCASRAudioRelay(
            session_id=session.session_id,
            rtc_asr_ws_url=self.rtc_asr_ws_url,
            chunk_ms=self.chunk_ms,
            send_app_message=send_app_message,
            mark_failed=mark_failed,
            asr_client_factory=self._asr_client_factory,
        )
        processor_cls = build_relay_processor_cls(runtime)
        relay_processor = processor_cls(relay)
        transport = runtime.transport_cls(
            webrtc_connection=webrtc_connection,
            params=runtime.transport_params_cls(
                audio_in_enabled=True,
                audio_out_enabled=False,
            ),
        )
        pipeline = runtime.pipeline_cls([transport.input(), relay_processor])
        worker = runtime.pipeline_worker_cls(
            pipeline,
            params=runtime.pipeline_params_cls(
                enable_metrics=False,
                enable_usage_metrics=False,
            ),
        )
        runner = runtime.worker_runner_cls(handle_sigint=False)
        try:
            await runner.add_workers(worker)
            await runner.run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            session.state = SessionState.FAILED
            session.error = BridgeRuntimeError.error_code
            send_app_message({
                "type": "error",
                "message": f"Pipecat pipeline failed: {exc}",
                "session_id": session.session_id,
            })
            logger.exception("browser_pipecat_demo_pipeline_failed")
            raise
