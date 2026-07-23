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
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from .protocol import (
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RawUdsFrameType,
    LocalSTTProtocolError,
    LocalSTTTranscriptEvent,
    build_start_message,
    decode_raw_uds_frame,
    encode_raw_uds_frame,
    parse_raw_uds_server_frame,
    encode_raw_uds_json_frame,
    parse_server_message,
    validate_raw_uds_audio_payload,
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
        self._pre_roll_buffer = bytearray()
        self._aggregate_buffer = bytearray()
        self._aggregate_duration_ms = 0.0
        self._connect_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._ready_event: asyncio.Event | None = None
        self._send_task: asyncio.Task[None] | None = None
        self._receive_task: asyncio.Task[None] | None = None
        self._closed = False
        self._utterance_active = False
        self._generation = 0
        self._suppress_transcripts = False
        self._final_events: dict[int, asyncio.Event] = {}
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
        if isinstance(frame, AudioRawFrame):
            self._validate_audio_frame(frame)
        elif isinstance(frame, VADUserStartedSpeakingFrame):
            await self._start_current_utterance()

        await super().process_frame(frame, direction)

        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            await self.finalize_current_utterance()
        elif isinstance(frame, InterruptionFrame):
            logger.debug("Ignoring Pipecat InterruptionFrame for Local STT; ASR cancel is reserved for CancelFrame or explicit discard.")

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
        await self._handle_audio(audio)
        yield None

    async def finalize_current_utterance(self) -> None:
        if not self._utterance_active:
            return
        generation = self._generation
        await self._flush_aggregate_buffer()
        await self._send_queue.join()
        if not self._utterance_active or self._websocket is None:
            return
        final_event = self._final_events.setdefault(generation, asyncio.Event())
        await self._send_control({"type": "finalize"}, ensure_started=False)
        self._utterance_active = False
        try:
            if self.config.final_timeout_s > 0:
                try:
                    await asyncio.wait_for(final_event.wait(), timeout=self.config.final_timeout_s)
                except asyncio.TimeoutError:
                    self.metrics.local_stt_final_timeouts_total += 1
                    logger.debug("Timed out waiting for Local STT final transcript for generation %s", generation)
        finally:
            self._final_events.pop(generation, None)

    async def cancel_current_utterance(self) -> None:
        self._generation += 1
        self._suppress_transcripts = True
        self._utterance_active = False
        self._pre_roll_buffer.clear()
        self._aggregate_buffer.clear()
        self._aggregate_duration_ms = 0.0
        self._clear_send_queue()
        if self._websocket is not None:
            await self._send_control({"type": "cancel"}, ensure_started=False)

    def metrics_snapshot(self) -> dict[str, int | float]:
        return self.metrics.as_dict()

    async def _start_current_utterance(self) -> None:
        if self._utterance_active:
            return
        self._generation += 1
        await self._ensure_utterance_started()
        if self._pre_roll_buffer:
            pre_roll = bytes(self._pre_roll_buffer)
            self._pre_roll_buffer.clear()
            await self._queue_audio_for_send(pre_roll)

    async def _handle_audio(self, audio: bytes) -> None:
        if not audio:
            return
        audio_duration_ms = self._audio_duration_ms(audio)
        self.metrics.local_stt_audio_frames_received_total += 1
        self.metrics.local_stt_audio_received_ms_total = round(
            self.metrics.local_stt_audio_received_ms_total + audio_duration_ms,
            3,
        )
        await self._ensure_connection()
        if not self._utterance_active:
            self._append_pre_roll(audio)
            return
        await self._queue_audio_for_send(audio)

    async def _queue_audio_for_send(self, audio: bytes) -> None:
        self._aggregate_buffer.extend(audio)
        self._aggregate_duration_ms += self._audio_duration_ms(audio)
        if len(self._aggregate_buffer) >= self.config.aggregation_bytes:
            await self._flush_aggregate_buffer()

    async def _flush_aggregate_buffer(self) -> None:
        if not self._aggregate_buffer:
            return
        chunk = _AudioChunk(
            data=bytes(self._aggregate_buffer),
            duration_ms=self._aggregate_duration_ms,
            generation=self._generation,
        )
        self._aggregate_buffer.clear()
        self._aggregate_duration_ms = 0.0
        await self._enqueue_chunk(chunk)

    async def _enqueue_chunk(self, chunk: _AudioChunk) -> None:
        if self.config.drop_policy == "block":
            while self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
                if self._send_queue.empty() and chunk.duration_ms > self.config.max_send_queue_ms:
                    break
                await asyncio.sleep(self.config.frame_ms / 1000.0)
            await self._put_chunk(chunk)
            return
        if self.config.drop_policy == "raise" and self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
            self.metrics.local_stt_audio_frames_dropped_total += 1
            self._record_dropped_audio_ms(chunk.duration_ms)
            self._update_queue_depth_metric()
            raise asyncio.QueueFull("Local STT send queue is full")
        while self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms and not self._send_queue.empty():
            dropped = self._send_queue.get_nowait()
            self._send_queue.task_done()
            self._queued_audio_ms = max(0.0, self._queued_audio_ms - dropped.duration_ms)
            self.metrics.local_stt_audio_frames_dropped_total += 1
            self._record_dropped_audio_ms(dropped.duration_ms)
        if self._queued_audio_ms + chunk.duration_ms > self.config.max_send_queue_ms:
            self.metrics.local_stt_audio_frames_dropped_total += 1
            self._record_dropped_audio_ms(chunk.duration_ms)
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
            if self._connect_fn is not None:
                connect_coro = self._connect_fn(self.config.url)
            else:
                connect_coro = _default_connect(self.config)
            self._websocket = await asyncio.wait_for(connect_coro, timeout=self.config.connect_timeout_s)
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
            ready_started_at = asyncio.get_running_loop().time()
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
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=self.config.connect_timeout_s)
            except asyncio.TimeoutError:
                self.metrics.local_stt_ready_timeouts_total += 1
                raise
            self.metrics.local_stt_ready_latency_ms = round(
                (asyncio.get_running_loop().time() - ready_started_at) * 1000,
                3,
            )
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
                self.metrics.local_stt_audio_sent_ms_total = round(
                    self.metrics.local_stt_audio_sent_ms_total + chunk.duration_ms,
                    3,
                )
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
                    await self._disconnect()
                    return
                await self._reconnect()
                return

    async def _handle_server_payload(self, payload: dict[str, Any]) -> None:
        event_type = payload.get("type")
        if event_type in {"ping", "pong"}:
            self.metrics.local_stt_heartbeat_events_total += 1
            return
        if event_type == "ready":
            self.metrics.local_stt_ready_events_total += 1
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
                generation = self._event_generation(event)
                if isinstance(generation, int):
                    final_event = self._final_events.get(generation)
                    if final_event is not None:
                        final_event.set()
            return
        if event_type == "error":
            self.metrics.local_stt_protocol_errors_total += 1
            logger.warning("Local STT protocol error: %s", payload.get("message", payload))

    def _event_generation(self, event: LocalSTTTranscriptEvent) -> int | None:
        generation = event.metadata.get("local_stt_generation")
        if not isinstance(generation, int):
            client_metadata = event.metadata.get("client_metadata")
            if isinstance(client_metadata, dict):
                generation = client_metadata.get("local_stt_generation")
        return generation if isinstance(generation, int) else None

    def _should_drop_transcript(self, event: LocalSTTTranscriptEvent) -> bool:
        generation = self._event_generation(event)
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
        self._pre_roll_buffer.clear()
        self._aggregate_buffer.clear()
        self._aggregate_duration_ms = 0.0
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
            self._record_dropped_audio_ms(chunk.duration_ms)
        self._update_queue_depth_metric()


    def _append_pre_roll(self, audio: bytes) -> None:
        if self.config.pre_roll_bytes <= 0:
            return
        self._pre_roll_buffer.extend(audio)
        overflow = len(self._pre_roll_buffer) - self.config.pre_roll_bytes
        if overflow > 0:
            del self._pre_roll_buffer[:overflow]

    def _validate_audio_frame(self, frame: AudioRawFrame) -> None:
        sample_rate = getattr(frame, "sample_rate", self.config.sample_rate)
        channels = getattr(frame, "num_channels", self.config.channels)
        audio = getattr(frame, "audio", b"")
        if sample_rate != self.config.sample_rate:
            raise ValueError(f"Local STT requires {self.config.sample_rate} Hz audio; got {sample_rate}")
        if channels != self.config.channels:
            raise ValueError(f"Local STT requires mono audio; got {channels} channels")
        if len(audio) % (self.config.channels * 2) != 0:
            raise ValueError("Local STT requires complete little-endian PCM16 samples")

    def _update_queue_depth_metric(self) -> None:
        self.metrics.local_stt_send_queue_depth_ms = round(self._queued_audio_ms, 3)

    def _record_dropped_audio_ms(self, duration_ms: float) -> None:
        self.metrics.local_stt_audio_dropped_ms_total = round(
            self.metrics.local_stt_audio_dropped_ms_total + duration_ms,
            3,
        )

    def _audio_duration_ms(self, audio: bytes) -> float:
        return (len(audio) / self.config.bytes_per_second) * 1000.0


class RawUdsConnectionAdapter:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._reader = reader
        self._writer = writer

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            frame = encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, validate_raw_uds_audio_payload(data))
        else:
            try:
                payload = json.loads(data)
            except json.JSONDecodeError as exc:
                raise LocalSTTProtocolError(
                    "Raw UDS JSON control payload must be valid JSON",
                    code="raw_uds_invalid_json",
                ) from exc
            if not isinstance(payload, dict):
                raise LocalSTTProtocolError(
                    "Raw UDS JSON control payload must be an object",
                    code="raw_uds_invalid_json",
                )
            heartbeat_frame_types = {"ping": RawUdsFrameType.PING, "pong": RawUdsFrameType.PONG}
            frame_type = heartbeat_frame_types.get(payload.get("type"), RawUdsFrameType.JSON_CONTROL)
            if frame_type in heartbeat_frame_types.values():
                payload = _compact_raw_uds_heartbeat_payload(payload)
            if frame_type in heartbeat_frame_types.values() and payload == {"type": payload.get("type")}:
                frame = encode_raw_uds_frame(frame_type, b"")
            else:
                frame = encode_raw_uds_json_frame(frame_type, payload)
        self._writer.write(frame)
        await self._writer.drain()

    async def recv(self) -> str:
        try:
            header = await self._reader.readexactly(RAW_UDS_HEADER_BYTES)
        except asyncio.IncompleteReadError as exc:
            raise LocalSTTProtocolError(
                f"Raw UDS stream ended with {len(exc.partial)} buffered frame bytes",
                code="raw_uds_incomplete_frame",
            ) from exc
        try:
            frame_type = RawUdsFrameType(header[0])
        except ValueError as exc:
            raise LocalSTTProtocolError(
                f"Unsupported Raw UDS frame type: {header[0]}",
                code="raw_uds_unsupported_frame_type",
            ) from exc
        if frame_type in {RawUdsFrameType.JSON_CONTROL, RawUdsFrameType.AUDIO_PCM16}:
            raise LocalSTTProtocolError(
                f"Raw UDS frame type {frame_type.name} is not a server frame",
                code="raw_uds_invalid_server_frame_type",
            )
        payload_length = int.from_bytes(header[1:RAW_UDS_HEADER_BYTES], "little")
        if payload_length > RAW_UDS_MAX_PAYLOAD_BYTES:
            raise LocalSTTProtocolError(
                f"Raw UDS frame payload exceeds {RAW_UDS_MAX_PAYLOAD_BYTES} bytes",
                code="raw_uds_payload_too_large",
            )
        try:
            payload = await self._reader.readexactly(payload_length)
        except asyncio.IncompleteReadError as exc:
            raise LocalSTTProtocolError(
                f"Raw UDS stream ended with {RAW_UDS_HEADER_BYTES + len(exc.partial)} buffered frame bytes",
                code="raw_uds_incomplete_frame",
            ) from exc
        frame = decode_raw_uds_frame(header + payload)
        return json.dumps(parse_raw_uds_server_frame(frame))

    async def close(self, code: int = 1000) -> None:
        self._writer.close()
        await self._writer.wait_closed()


def _compact_raw_uds_heartbeat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    compacted = dict(payload)
    if compacted.get("metadata") == {}:
        compacted.pop("metadata")
    return compacted


async def _default_connect(config: LocalSTTConfig) -> WebSocketConnection:
    if config.transport == "raw_uds":
        if config.uds_path is None:
            raise ValueError("uds_path is required when transport is raw_uds")
        reader, writer = await asyncio.open_unix_connection(config.uds_path)
        return RawUdsConnectionAdapter(reader, writer)

    import websockets

    if config.transport == "uds_ws":
        if config.uds_path is None:
            raise ValueError("uds_path is required when transport is uds_ws")
        return await websockets.unix_connect(config.uds_path, uri=config.url, max_size=2**23)
    return await websockets.connect(config.url, max_size=2**23)
