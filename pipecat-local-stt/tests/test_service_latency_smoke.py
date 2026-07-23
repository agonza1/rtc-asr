from __future__ import annotations

import asyncio

from fake_local_stt_server import FakeLocalSTTServerConfig, FakeLocalSTTWebSocket
from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService
from pipecat_local_stt.pipecat_compat import (
    AudioRawFrame,
    FrameDirection,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)

from test_service_fake_server import capture_pushed_frames, pushed_frame_types, wait_for


def test_fake_server_latency_smoke_records_plugin_metrics_without_rtc_asr() -> None:
    asyncio.run(_test_fake_server_latency_smoke_records_plugin_metrics_without_rtc_asr())


async def _test_fake_server_latency_smoke_records_plugin_metrics_without_rtc_asr() -> None:
    websocket = FakeLocalSTTWebSocket(
        FakeLocalSTTServerConfig(
            interim_every_frames=2,
            decode_delay_s=0.001,
            final_text="latency smoke final",
        )
    )
    service = LocalStreamingSTTService(
        LocalSTTConfig(url="ws://fake/v1/stt/stream", aggregation_ms=20, max_send_queue_ms=80),
        connect_fn=websocket.connect_fn(),
    )
    pushed_frames = capture_pushed_frames(service)

    await service.start(StartFrame(audio_in_sample_rate=16000))
    await service.process_frame(VADUserStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    for _index in range(4):
        await service.process_frame(AudioRawFrame(audio=b"x" * 640, sample_rate=16000, num_channels=1), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: service.metrics.local_stt_interim_events_total >= 1)

    await service.process_frame(VADUserStoppedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    await wait_for(lambda: TranscriptionFrame in pushed_frame_types(pushed_frames))
    await service.cleanup()

    final_frames = [frame for frame, _direction in pushed_frames if isinstance(frame, TranscriptionFrame)]
    metrics = service.metrics_snapshot()

    assert websocket.binary_frames_received == 4
    assert websocket.finalize_count == 1
    assert final_frames[-1].text == "latency smoke final"
    assert metrics["local_stt_audio_frames_received_total"] == 4
    assert metrics["local_stt_audio_received_ms_total"] == 80.0
    assert metrics["local_stt_audio_frames_sent_total"] == 4
    assert metrics["local_stt_audio_sent_ms_total"] == 80.0
    assert metrics["local_stt_audio_dropped_ms_total"] == 0.0
    assert metrics["local_stt_send_queue_utilization_ratio"] == 0.0
    assert metrics["local_stt_send_queue_utilization_high_water_ratio"] > 0.0
    assert metrics["local_stt_ready_events_total"] == 1
    assert metrics["local_stt_interim_events_total"] >= 1
    assert metrics["local_stt_final_events_total"] == 1
    assert metrics["local_stt_protocol_errors_total"] == 0
