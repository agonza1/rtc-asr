from __future__ import annotations

import asyncio
import json
from typing import Any

from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService

from pipecat_local_stt.pipecat_compat import AudioRawFrame, FrameDirection, StartFrame, TranscriptionFrame, VADUserStartedSpeakingFrame


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
                    "metadata": {"client_metadata": {"local_stt_generation": 0}},
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


class FailingSendWebSocket:
    def __init__(self, *, fail_first_binary: bool = False) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.fail_first_binary = fail_first_binary
        self.binary_failures = 0

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data)["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready"}))
            return
        if isinstance(data, bytes) and self.fail_first_binary and self.binary_failures == 0:
            self.binary_failures += 1
            raise RuntimeError("simulated send failure")

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class FailFirstCancelWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.failed_cancel = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str):
            payload = json.loads(data)
            if payload["type"] == "start":
                await self.incoming.put(json.dumps({"type": "ready"}))
                return
            if payload["type"] == "cancel" and not self.failed_cancel:
                self.failed_cancel = True
                raise RuntimeError("simulated cancel send failure")

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class FailFirstStartWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.failed_start = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str):
            payload = json.loads(data)
            if payload["type"] == "start":
                if not self.failed_start:
                    self.failed_start = True
                    raise RuntimeError("simulated start send failure")
                await self.incoming.put(json.dumps({"type": "ready"}))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class FinalizeWaitWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.release_binary_send = asyncio.Event()
        self.binary_send_completed = 0
        self.finalize_before_binary_completed = False

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str):
            payload = json.loads(data)
            if payload["type"] == "start":
                await self.incoming.put(json.dumps({"type": "ready"}))
            elif payload["type"] == "finalize":
                self.finalize_before_binary_completed = self.binary_send_completed == 0
            return

        await self.release_binary_send.wait()
        self.binary_send_completed += 1

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class AlwaysFailSendWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data)["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready"}))
            return
        if isinstance(data, bytes):
            raise RuntimeError("simulated permanent send failure")

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class BlockingFailSendWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.release_binary_send = asyncio.Event()

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data)["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready"}))
            return
        if isinstance(data, bytes):
            await self.release_binary_send.wait()
            raise RuntimeError("simulated tail send failure")

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        return None


class HealthySendWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, str) and json.loads(data)["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready"}))

    async def recv(self) -> str:
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
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, max_send_queue_ms=20, drop_policy="drop_oldest"),
        connect_fn=lambda _url: asyncio.sleep(0, websocket),
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
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
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20),
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
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=True),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    first_receive_task = service._receive_task

    await eventually(lambda: len(websockets) == 0)
    await eventually(lambda: service._receive_task is not None and service._receive_task is not first_receive_task)
    assert service._receive_task is not first_receive_task
    assert service.metrics.local_stt_reconnects_total == 1

    await service.cleanup()


def test_finalize_waits_for_queued_audio_before_control_message() -> None:
    asyncio.run(_test_finalize_waits_for_queued_audio_before_control_message())


async def _test_finalize_waits_for_queued_audio_before_control_message() -> None:
    websocket = FinalizeWaitWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20),
        connect_fn=lambda _url: asyncio.sleep(0, websocket),
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)

    finalize_task = asyncio.create_task(service.finalize_current_utterance())
    await asyncio.sleep(0.05)
    assert not finalize_task.done()

    websocket.release_binary_send.set()
    await finalize_task
    await service.cleanup()

    assert websocket.finalize_before_binary_completed is False


def test_finalize_skips_control_after_queued_send_failure_disconnects() -> None:
    asyncio.run(_test_finalize_skips_control_after_queued_send_failure_disconnects())


async def _test_finalize_skips_control_after_queued_send_failure_disconnects() -> None:
    first = BlockingFailSendWebSocket()
    second = HealthySendWebSocket()
    websockets = [first, second]

    async def connect(_url: str) -> BlockingFailSendWebSocket | HealthySendWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=False),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)

    finalize_task = asyncio.create_task(service.finalize_current_utterance())
    await asyncio.sleep(0.05)
    assert not finalize_task.done()

    first.release_binary_send.set()
    await asyncio.wait_for(finalize_task, timeout=0.5)

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: any(isinstance(item, bytes) for item in second.sent))
    await service.cleanup()

    first_control_types = [json.loads(item)["type"] for item in first.sent if isinstance(item, str)]
    second_control_types = [json.loads(item)["type"] for item in second.sent if isinstance(item, str)]

    assert first_control_types == ["start"]
    assert second_control_types == ["start"]


def test_send_loop_exits_after_reconnect_replaces_task() -> None:
    asyncio.run(_test_send_loop_exits_after_reconnect_replaces_task())


async def _test_send_loop_exits_after_reconnect_replaces_task() -> None:
    first = FailingSendWebSocket(fail_first_binary=True)
    second = FailingSendWebSocket()
    websockets = [first, second]

    async def connect(_url: str) -> FailingSendWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=True),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    original_send_task = service._send_task
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: service._send_task is not None and service._send_task is not original_send_task)

    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: sum(1 for item in second.sent if isinstance(item, bytes)) == 2)

    assert original_send_task is not None and original_send_task.done()
    await service.cleanup()


def test_block_policy_does_not_deadlock_on_oversized_chunk() -> None:
    asyncio.run(_test_block_policy_does_not_deadlock_on_oversized_chunk())


async def _test_block_policy_does_not_deadlock_on_oversized_chunk() -> None:
    websocket = SlowSendWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, max_send_queue_ms=20, drop_policy="block"),
        connect_fn=lambda _url: asyncio.sleep(0, websocket),
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    oversized_audio = b"o" * 3200
    await asyncio.wait_for(
        service.process_frame(AudioRawFrame(audio=oversized_audio, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM),
        timeout=0.1,
    )

    await eventually(lambda: any(item == oversized_audio for item in websocket.sent if isinstance(item, bytes)))
    websocket.release_binary_send.set()
    await service.cleanup()


def test_unrecoverable_send_failure_disconnects_and_allows_reconnect() -> None:
    asyncio.run(_test_unrecoverable_send_failure_disconnects_and_allows_reconnect())


async def _test_unrecoverable_send_failure_disconnects_and_allows_reconnect() -> None:
    first = AlwaysFailSendWebSocket()
    second = HealthySendWebSocket()
    websockets = [first, second]

    async def connect(_url: str) -> AlwaysFailSendWebSocket | HealthySendWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=False),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: service._websocket is None)

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: any(isinstance(item, bytes) for item in second.sent))

    assert service.metrics.local_stt_protocol_errors_total >= 1
    await service.cleanup()


def test_cancel_send_failure_does_not_replay_cancel_on_reconnect() -> None:
    asyncio.run(_test_cancel_send_failure_does_not_replay_cancel_on_reconnect())


async def _test_cancel_send_failure_does_not_replay_cancel_on_reconnect() -> None:
    first = FailFirstCancelWebSocket()
    second = HealthySendWebSocket()
    websockets = [first, second]

    async def connect(_url: str) -> FailFirstCancelWebSocket | HealthySendWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=True),
        connect_fn=connect,
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.cancel_current_utterance()
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: any(isinstance(item, bytes) for item in second.sent))
    await service.cleanup()

    first_control_types = [json.loads(item)["type"] for item in first.sent if isinstance(item, str)]
    second_control_types = [json.loads(item)["type"] for item in second.sent if isinstance(item, str)]

    assert first_control_types == ["cancel"]
    assert second_control_types == ["start"]
    assert service.metrics.local_stt_reconnects_total == 1


def test_start_send_failure_reconnect_does_not_reenter_start_lock() -> None:
    asyncio.run(_test_start_send_failure_reconnect_does_not_reenter_start_lock())


async def _test_start_send_failure_reconnect_does_not_reenter_start_lock() -> None:
    first = FailFirstStartWebSocket()
    second = HealthySendWebSocket()
    websockets = [first, second]

    async def connect(_url: str) -> FailFirstStartWebSocket | HealthySendWebSocket:
        return websockets.pop(0)

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, reconnect_on_error=True),
        connect_fn=connect,
    )

    await asyncio.wait_for(service.start(StartFrame(audio_in_sample_rate=16000)), timeout=0.5)
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await eventually(lambda: any(isinstance(item, bytes) for item in second.sent))
    await service.cleanup()

    first_control_types = [json.loads(item)["type"] for item in first.sent if isinstance(item, str)]
    second_control_types = [json.loads(item)["type"] for item in second.sent if isinstance(item, str)]

    assert first_control_types == ["start"]
    assert second_control_types == ["start"]
    assert service.metrics.local_stt_reconnects_total == 1
