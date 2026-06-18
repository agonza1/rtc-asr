from __future__ import annotations

import asyncio
import json
from typing import Any

from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService

from pipecat_local_stt.pipecat_compat import AudioRawFrame, FrameDirection, StartFrame, TranscriptionFrame


class SlowSendWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.release_binary_send = asyncio.Event()

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str):
            payload = json.loads(data)
            if payload["type"] == "start":
                await self.incoming.put(json.dumps({"type": "ready"}))
            return
        await self.release_binary_send.wait()

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class CancelWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str):
            payload = json.loads(data)
            if payload["type"] == "start":
                await self.incoming.put(json.dumps({"type": "ready"}))
            elif payload["type"] == "cancel":
                await self.incoming.put(json.dumps({
                    "type": "transcript",
                    "text": "stale",
                    "is_final": True,
                    "speech_final": True,
                    "revision": 1,
                    "audio_received_ms": 20,
                    "audio_transcribed_ms": 20,
                    "metadata": {"local_stt_generation": 0},
                }))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class ReconnectWebSocket:
    def __init__(self, *, fail_after_ready: bool) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.fail_after_ready = fail_after_ready
        self.ready_sent = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data)["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready"}))

    async def recv(self) -> str:
        if self.fail_after_ready and self.ready_sent:
            raise RuntimeError("simulated receive failure")
        self.ready_sent = True
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


def capture_pushed_frames(service: LocalStreamingSTTService) -> list[tuple[Any, FrameDirection]]:
    frames: list[tuple[Any, FrameDirection]] = []
    original_push_frame = service.push_frame

    async def push_frame(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        frames.append((frame, direction))
        await original_push_frame(frame, direction)

    service.push_frame = push_frame  # type: ignore[method-assign]
    return frames


async def eventually(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


def test_drop_oldest_queue_overflow_is_explicit_and_counted() -> None:
    asyncio.run(_test_drop_oldest_queue_overflow_is_explicit_and_counted())


async def _test_drop_oldest_queue_overflow_is_explicit_and_counted() -> None:
    websocket = SlowSendWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", max_send_queue_ms=20, drop_policy="drop_oldest"),
        connect_fn=lambda _url: asyncio.sleep(0, websocket),
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: any(isinstance(item, bytes) for item in websocket.sent))
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"c" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"d" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)

    assert service.metrics.local_stt_audio_frames_dropped_total >= 2
    assert service.metrics.local_stt_send_queue_depth_ms <= 20
    websocket.release_binary_send.set()
    await service.cleanup()


def test_cancel_suppresses_stale_results() -> None:
    asyncio.run(_test_cancel_suppresses_stale_results())


async def _test_cancel_suppresses_stale_results() -> None:
    websocket = CancelWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream"),
        connect_fn=lambda _url: asyncio.sleep(0, websocket),
    )

    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.cancel_current_utterance()
    await asyncio.sleep(0.05)
    await service.cleanup()

    final_frames = [frame for frame, _ in pushed_frames if isinstance(frame, TranscriptionFrame)]
    assert final_frames == []


def test_receive_loop_reconnect_exits_old_reader() -> None:
    asyncio.run(_test_receive_loop_reconnect_exits_old_reader())


async def _test_receive_loop_reconnect_exits_old_reader() -> None:
    websockets = [
        ReconnectWebSocket(fail_after_ready=True),
        ReconnectWebSocket(fail_after_ready=False),
    ]

    async def connect(_url: str) -> ReconnectWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", reconnect_on_error=True),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    first_receive_task = service._receive_task

    await eventually(lambda: len(websockets) == 0)
    await eventually(lambda: service._receive_task is not None and service._receive_task is not first_receive_task)
    assert service._receive_task is not first_receive_task
    assert service.metrics.local_stt_reconnects_total == 1

    await service.cleanup()
