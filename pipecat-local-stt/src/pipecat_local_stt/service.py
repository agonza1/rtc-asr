from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Protocol
from uuid import uuid4

from .config import LocalSTTConfig
from .metrics import LocalSTTMetrics
from .pipecat_compat import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    FrameDirection,
    InterimTranscriptionFrame,
    InterruptionFrame,
    STTService,
    STTSettings,
    StartFrame,
    TranscriptionFrame,
    UserStoppedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from .protocol import (
    LocalSTTProtocolError,
    LocalSTTTranscriptEvent,
    build_start_message,
    parse_server_message,
    parse_transcript_event,
)

logger = logging.getLogger(__name__)


class WebSocketConnection(Protocol):
    async def send(self, data: str | bytes) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self, code: int = 1000) -> None: ...


ConnectFn = Callable[[str], Awaitable[WebSocketConnection]]


@dataclass(slots=True)
class _AudioChunk:
    data: bytes
    duration_ms: float
    generation: int


class LocalStreamingSTTService(STTService):
    def __init__(
        self,
        config: LocalSTTConfig | None = None,
        *,
        connect_fn: ConnectFn | None = None,
        **kwargs: Any,
    ) -> None:
        self.config = config or LocalSTTConfig()
        self.metrics = LocalSTTMetrics()
        self._connect_fn = connect_fn
        self._websocket: WebSocketConnection | None = None
        self._send_queue: asyncio.Queue[_AudioChunk] = asyncio.Queue()
        self._queued_audio_ms = 0.0
        self._connect_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._ready_event: asyncio.Event | None = None
        self._send_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._closed = False
        self._utterance_active = False
        self._generation = 0
        self._suppress_transcripts = False
        self._session_id = uuid4().hex
        settings = kwargs.pop("settings", None) or STTSettings(model=None, language=self.config.language)
        super().__init__(
            audio_passthrough=self.config.pass_audio_downstream,
            sample_rate=self.config.sample_rate,
            settings=settings,
            **kwargs,
        )

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        await self._ensure_connection()
        await self._ensure_utterance_started()

    async def stop(self, frame: EndFrame) -> None:
        if self._websocket is not None:
            await self._send_json({"type": "close"})
        await self._disconnect()
        stop = getattr(super(), "stop", None)
        if callable(stop):
            await stop(frame)

    async def cancel(self, frame: CancelFrame) -> None:
        await self.cancel_current_utterance()
        cancel = getattr(super(), "cancel", None)
        if callable(cancel):
            await cancel(frame)

    async def cleanup(self) -> None:
        await self._disconnect()
        cleanup = getattr(super(), "cleanup", None)
        if callable(cleanup):
            await cleanup()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            await self.finalize_current_utterance()
        elif isinstance(frame, InterruptionFrame):
            await self.cancel_current_utterance()

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        await self._enqueue_audio(audio)
        yield None

    async def finalize_current_utterance(self) -> None:
        if not self._utterance_active:
            return
        await self._send_queue.join()
        if not self._utterance_active or self._websocket is None:
            return
        await self._send_control({"type": "finalize"}, ensure_started=False)
        self._utterance_active = False

    async def cancel_current_utterance(self) -> None:
        self._generation += 1
        self._suppress_transcripts = True
        self._utterance_active = False
        self._clear_send_queue()
        if self._websocket is not None:
            await self._send_control({"type": "cancel"}, ensure_started=False)

    def metrics_snapshot(self) -> dict[str, int | float]:
        return self.metrics.as_dict()

    async def _enqueue_audio(self, audio: bytes) -> None:
        if not audio:
            return
        self.metrics.local_stt_audio_frames_received_total += 1
        await self._ensure_connection()
        await self._ensure_utterance_started()

        chunk = _AudioChunk(
            data=bytes(audio),
            duration_ms=self._audio_duration_ms(audio),
            generation=self._generation,
        )
        if self.config.drop_policy == "block":
            while self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
                if self._send_queue.empty() and chunk.duration_ms > self.config.max_send_queue_ms:
                    break
                await asyncio.sleep(self.config.frame_ms / 1000.0)
            await self._put_chunk(chunk)
            return
        if self.config.drop_policy == "raise" and self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
            self.metrics.local_stt_audio_frames_dropped_total += 1
            self._update_queue_depth_metric()
            raise asyncio.QueueFull("Local STT send queue is full")
        while self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms and not self._send_queue.empty():
            dropped = self._send_queue.get_nowait()
            self._send_queue.task_done()
            self._queued_audio_ms = max(0.0, self._queued_audio_ms - dropped.duration_ms)
            self.metrics.local_stt_audio_frames_dropped_total += 1
        if self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
            self.metrics.local_stt_audio_frames_dropped_total += 1
            self._update_queue_depth_metric()
            return
        await self._put_chunk(chunk)

    async def _put_chunk(self, chunk: _AudioChunk) -> None:
        await self._send_queue.put(chunk)
        self._queued_audio_ms += chunk.duration_ms
        self._update_queue_depth_metric()

    async def _ensure_connection(self) -> None:
        if self._websocket is not None:
            return
        async with self._connect_lock:
            if self._websocket is not None:
                return
            self._closed = False
            connect_fn = self._connect_fn or _default_connect
            self._websocket = await asyncio.wait_for(connect_fn(self.config.url), timeout=self.config.connect_timeout_s)
            self._ready_event = asyncio.Event()
            self._send_task = asyncio.create_task(self._send_loop())
            self._receive_task = asyncio.create_task(self._receive_loop())

    async def _ensure_utterance_started(self) -> None:
        if self._utterance_active:
            return
        async with self._start_lock:
            if self._utterance_active:
                return
            await self._ensure_connection()
            if self._ready_event is None:
                self._ready_event = asyncio.Event()
            else:
                self._ready_event.clear()
            self._suppress_transcripts = False
            metadata = {"local_stt_generation": self._generation}
            await self._send_ws(
                json.dumps(
                    build_start_message(
                        self.config,
                        client_stream_id=f"{self._session_id}:{self._generation}",
                        metadata=metadata,
                    )
                ),
                start_after_reconnect=False,
            )
            await asyncio.wait_for(self._ready_event.wait(), timeout=self.config.connect_timeout_s)
            self._utterance_active = True

    async def _send_loop(self) -> None:
        current_task = asyncio.current_task()
        while not self._closed:
            chunk = await self._send_queue.get()
            try:
                self._queued_audio_ms = max(0.0, self._queued_audio_ms - chunk.duration_ms)
                self._update_queue_depth_metric()
                if chunk.generation != self._generation:
                    continue
                try:
                    await self._send_binary(chunk.data)
                except Exception as exc:
                    self.metrics.local_stt_protocol_errors_total += 1
                    logger.warning("Local STT send loop error: %s", exc)
                    await self._disconnect()
                    return
                self.metrics.local_stt_audio_frames_sent_total += 1
                if self._send_task is not current_task:
                    return
            finally:
                self._send_queue.task_done()

    async def _receive_loop(self) -> None:
        while not self._closed:
            websocket = self._websocket
            if websocket is None:
                return
            try:
                raw = await websocket.recv()
                payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw)
                await self._handle_server_payload(parse_server_message(payload))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.metrics.local_stt_protocol_errors_total += 1
                logger.warning("Local STT receive loop error: %s", exc)
                if not self.config.reconnect_on_error or self._closed:
                    return
                await self._reconnect()
                return

    async def _handle_server_payload(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type == "ready":
            if self._ready_event is not None:
                self._ready_event.set()
            return
        if event_type == "transcript":
            event = parse_transcript_event(payload)
            if self._should_drop_transcript(event):
                return
            await self._push_transcript(event)
            if event.is_final:
                self._utterance_active = False
            return
        if event_type == "error":
            self.metrics.local_stt_protocol_errors_total += 1
            logger.warning("Local STT protocol error: %s", payload.get("message", payload))

    def _should_drop_transcript(self, event: LocalSTTTranscriptEvent) -> bool:
        generation = event.metadata.get("local_stt_generation")
        if not isinstance(generation, int):
            client_metadata = event.metadata.get("client_metadata")
            if isinstance(client_metadata, dict):
                generation = client_metadata.get("local_stt_generation")
        if isinstance(generation, int) and generation != self._generation:
            return True
        return self._suppress_transcripts

    async def _push_transcript(self, event: LocalSTTTranscriptEvent) -> None:
        timestamp = datetime.now(timezone.utc).isoformat()
        language = event.language or self.config.language
        result = event.raw if self.config.enable_timing_metadata else None
        if event.is_final:
            self.metrics.local_stt_final_events_total += 1
            if not self.config.emit_final_frames:
                return
            frame = TranscriptionFrame(
                text=event.text,
                user_id=getattr(self, "_user_id", ""),
                timestamp=timestamp,
                language=language,
                result=result,
                finalized=True,
            )
            await self.push_frame(frame)
        else:
            self.metrics.local_stt_interim_events_total += 1
            if not self.config.emit_interim_frames:
                return
            frame = InterimTranscriptionFrame(
                text=event.text,
                user_id=getattr(self, "_user_id", ""),
                timestamp=timestamp,
                language=language,
                result=result,
            )
            await self.push_frame(frame)

    async def _send_control(self, payload: dict[str, Any], *, ensure_started: bool) -> None:
        await self._ensure_connection()
        if ensure_started:
            await self._ensure_utterance_started()
        await self._send_ws(json.dumps(payload), replay_after_reconnect=False, start_after_reconnect=False)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        await self._send_ws(json.dumps(payload))

    async def _send_binary(self, payload: bytes) -> None:
        await self._send_ws(payload)

    async def _send_ws(
        self,
        payload: str | bytes,
        *,
        replay_after_reconnect: bool = True,
        start_after_reconnect: bool = True,
    ) -> None:
        websocket = self._websocket
        if websocket is None:
            raise RuntimeError("Local STT websocket is not connected")
        try:
            await websocket.send(payload)
        except Exception:
            if not self.config.reconnect_on_error:
                raise
            await self._reconnect(start_utterance=start_after_reconnect)
            if not replay_after_reconnect:
                return
            websocket = self._websocket
            if websocket is None:
                raise RuntimeError("Local STT websocket reconnect failed")
            await websocket.send(payload)

    async def _reconnect(self, *, start_utterance: bool = True) -> None:
        self.metrics.local_stt_reconnects_total += 1
        await self._close_socket_and_tasks(cancel_current=False)
        self._websocket = None
        self._utterance_active = False
        await self._ensure_connection()
        if start_utterance:
            await self._ensure_utterance_started()

    async def _disconnect(self) -> None:
        await self._close_socket_and_tasks(cancel_current=True)
        self._clear_send_queue()
        self._websocket = None
        self._utterance_active = False

    async def _close_socket_and_tasks(self, *, cancel_current: bool) -> None:
        self._closed = True
        current = asyncio.current_task()
        tasks = [task for task in (self._send_task, self._receive_task) if task is not None and task is not current]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._send_task = None
        self._receive_task = None
        if self._websocket is not None:
            try:
                await self._websocket.close(code=1000)
            except Exception:
                logger.debug("Local STT websocket close failed", exc_info=True)
        if not cancel_current:
            self._closed = False

    def _clear_send_queue(self) -> None:
        while not self._send_queue.empty():
            chunk = self._send_queue.get_nowait()
            self._send_queue.task_done()
            self._queued_audio_ms = max(0.0, self._queued_audio_ms - chunk.duration_ms)
            self.metrics.local_stt_audio_frames_dropped_total += 1
        self._update_queue_depth_metric()

    def _update_queue_depth_metric(self) -> None:
        self.metrics.local_stt_send_queue_depth_ms = round(self._queued_audio_ms, 3)

    def _audio_duration_ms(self, audio: bytes) -> float:
        return (len(audio) / self.config.bytes_per_second) * 1000.0


async def _default_connect(url: str) -> WebSocketConnection:
    import websockets

    return await websockets.connect(url, max_size=2**23)
