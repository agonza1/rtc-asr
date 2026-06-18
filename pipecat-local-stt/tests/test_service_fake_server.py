from __future__ import annotations

import asyncio
import json
from typing import Any


from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService
from pipecat_local_stt.pipecat_compat import (
    AudioRawFrame,
    FrameDirection,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStoppedSpeakingFrame,
)


class FakeLocalSTTWebSocket:
    def __init__(self) -> None:
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False
        self.finalize_count = 0

    async def send(self, data: str | bytes) -> None:
        self.sent.append(data)
        if isinstance(data, bytes):
            await self.incoming.put(json.dumps({
                "type": "transcript",
                "text": "hel",
                "is_final": False,
                "speech_final": False,
                "revision": 1,
                "audio_received_ms": 20,
                "audio_transcribed_ms": 20,
                "metadata": {"local_stt_generation": self._current_generation()},
            }))
            return
        payload = json.loads(data)
        if payload["type"] == "start":
            await self.incoming.put(json.dumps({"type": "ready", "metadata": payload.get("metadata", {})}))
        elif payload["type"] == "finalize":
            self.finalize_count += 1
            await self.incoming.put(json.dumps({
                "type": "transcript",
                "text": "hello world",
                "is_final": True,
                "speech_final": True,
                "revision": 2,
                "audio_received_ms": 40,
                "audio_transcribed_ms": 40,
                "metadata": {"local_stt_generation": self._current_generation()},
            }))
        elif payload["type"] == "close":
            await self.incoming.put(json.dumps({"type": "closed", "reason": "client_close"}))

    async def recv(self) -> str:
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    def _current_generation(self) -> int:
        starts = [json.loads(item) for item in self.sent if isinstance(item, str) and json.loads(item)["type"] == "start"]
        if not starts:
            return 0
        metadata = starts[-1].get("metadata", {})
        return int(metadata.get("local_stt_generation", 0))


def capture_pushed_frames(service: LocalStreamingSTTService) -> list[tuple[Any, FrameDirection]]:
    frames: list[tuple[Any, FrameDirection]] = []
    original_push_frame = service.push_frame

    async def push_frame(frame: Any, direction: FrameDirection = FrameDirection.DOWNSTREAM) -> None:
        frames.append((frame, direction))
        await original_push_frame(frame, direction)

    service.push_frame = push_frame  # type: ignore[method-assign]
    return frames


def pushed_frame_types(frames: list[tuple[Any, FrameDirection]]) -> list[type[Any]]:
    return [type(frame) for frame, _direction in frames]


async def wait_for(predicate, *, timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


def test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping() -> None:
    asyncio.run(_test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping())


async def _test_fake_server_verifies_start_binary_audio_finalize_and_transcript_mapping() -> None:
    websocket = FakeLocalSTTWebSocket()
    service = LocalStreamingSTTService(LocalSTTConfig(url="ws://fake/v1/stt/stream"), connect_fn=lambda _url: asyncio.sleep(0, websocket))
    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(AudioRawFrame(audio=b"x" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: InterimTranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: TranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.cleanup()

    sent_start = json.loads(next(item for item in websocket.sent if isinstance(item, str)))
    binary_messages = [item for item in websocket.sent if isinstance(item, bytes)]
    final_frames = [frame for frame, _ in pushed_frames if isinstance(frame, TranscriptionFrame)]

    assert sent_start["type"] == "start"
    assert sent_start["protocol"] == "local-stt-v1"
    assert sent_start["sample_rate"] == 16000
    assert binary_messages == [b"x" * 640]
    assert websocket.finalize_count == 1
    assert final_frames[-1].text == "hello world"
    assert final_frames[-1].finalized is True
    assert service.metrics.local_stt_audio_frames_sent_total == 1
    assert service.metrics.local_stt_interim_events_total == 1
    assert service.metrics.local_stt_final_events_total == 1
