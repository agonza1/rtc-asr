from __future__ import annotations

import asyncio
import json

import pytest

from fake_local_stt_server import FakeLocalSTTWebSocket
from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService
from pipecat_local_stt.pipecat_compat import (
    AudioRawFrame,
    FrameDirection,
    InterruptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from test_service_fake_server import capture_pushed_frames, pushed_frame_types, wait_for


def control_types(websocket: FakeLocalSTTWebSocket) -> list[str]:
    return [json.loads(item)["type"] for item in websocket.sent if isinstance(item, str)]


def binary_messages(websocket: FakeLocalSTTWebSocket) -> list[bytes]:
    return [item for item in websocket.sent if isinstance(item, bytes)]


def test_vad_lifecycle_reuses_one_connection_and_batches_audio() -> None:
    asyncio.run(_test_vad_lifecycle_reuses_one_connection_and_batches_audio())


async def _test_vad_lifecycle_reuses_one_connection_and_batches_audio() -> None:
    websocket = FakeLocalSTTWebSocket()
    connect_count = 0

    async def connect(_url: str) -> FakeLocalSTTWebSocket:
        nonlocal connect_count
        connect_count += 1
        return websocket

    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=60, pre_roll_ms=20),
        connect_fn=connect,
    )
    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(AudioRawFrame(audio=b"i" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: TranscriptionFrame in pushed_frame_types(pushed_frames))

    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"c" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.cleanup()

    assert connect_count == 1
    assert control_types(websocket).count("start") == 2
    assert control_types(websocket).count("finalize") == 2
    assert binary_messages(websocket)[0] == (b"i" * 640) + (b"a" * 640) + (b"b" * 640)
    assert binary_messages(websocket)[1] == b"c" * 640


def test_interruption_frame_does_not_cancel_or_discard_user_asr() -> None:
    asyncio.run(_test_interruption_frame_does_not_cancel_or_discard_user_asr())


async def _test_interruption_frame_does_not_cancel_or_discard_user_asr() -> None:
    websocket = FakeLocalSTTWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20),
        connect_fn=websocket.connect_fn(),
    )
    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    await service.process_frame(AudioRawFrame(audio=b"b" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: TranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.cleanup()

    assert "cancel" not in control_types(websocket)
    assert len(binary_messages(websocket)) == 2


def test_rejects_non_16khz_mono_pcm16_audio_contract() -> None:
    asyncio.run(_test_rejects_non_16khz_mono_pcm16_audio_contract())


async def _test_rejects_non_16khz_mono_pcm16_audio_contract() -> None:
    websocket = FakeLocalSTTWebSocket()
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream"),
        connect_fn=websocket.connect_fn(),
    )

    await service.start(StartFrame(audio_in_sample_rate=16000))
    with pytest.raises(ValueError, match="16000 Hz"):
        await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=24000, num_channels=1), FrameDirection.DOWNSTREAM)
    with pytest.raises(ValueError, match="mono"):
        await service.process_frame(AudioRawFrame(audio=b"a" * 640, sample_rate=16000, num_channels=2), FrameDirection.DOWNSTREAM)
    with pytest.raises(ValueError, match="PCM16"):
        await service.process_frame(AudioRawFrame(audio=b"a", sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await service.cleanup()
