from __future__ import annotations

import pytest

from pipecat_local_stt import LocalSTTConfig, RtcAsrSTTService
from pipecat_local_stt.protocol import build_start_message, parse_transcript_event


def test_build_start_message_uses_required_flat_local_stt_v1_shape() -> None:
    config = LocalSTTConfig(language="en", partial_interval_ms=100)

    payload = build_start_message(config, client_stream_id="turn-1", metadata={"k": "v"})

    assert payload == {
        "type": "start",
        "protocol": "local-stt-v1",
        "language": "en",
        "sample_rate": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "frame_ms": 20,
        "interim_results": True,
        "partial_interval_ms": 100,
        "partial_window_seconds": 1.0,
        "max_buffer_seconds": 10.0,
        "client_stream_id": "turn-1",
        "metadata": {"k": "v"},
    }


def test_parse_transcript_event_rejects_invalid_timing() -> None:
    with pytest.raises(ValueError, match="audio_transcribed_ms"):
        parse_transcript_event({
            "type": "transcript",
            "text": "hello",
            "is_final": False,
            "speech_final": False,
            "revision": 1,
            "audio_received_ms": 20,
            "audio_transcribed_ms": 40,
            "metadata": {},
        })


def test_rtc_asr_wrapper_exports_default_service_config() -> None:
    service = RtcAsrSTTService(url="ws://localhost:8080/v1/stt/stream", language="es")

    assert service.config.url == "ws://localhost:8080/v1/stt/stream"
    assert service.config.language == "es"


def test_rtc_asr_wrapper_accepts_stream_tuning_overrides() -> None:
    service = RtcAsrSTTService(
        url="ws://localhost:8080/v1/stt/stream",
        sample_rate=8000,
        channels=2,
        frame_ms=40,
        partial_interval_ms=250,
        partial_window_seconds=1.5,
    )

    assert service.config.sample_rate == 8000
    assert service.config.channels == 2
    assert service.config.frame_ms == 40
    assert service.config.partial_interval_ms == 250
    assert service.config.partial_window_seconds == 1.5


def test_rtc_asr_wrapper_accepts_optional_uds_transport() -> None:
    service = RtcAsrSTTService(
        transport="uds_ws",
        url="ws://localhost/v1/stt/stream",
        uds_path="/run/rtc-asr/stt.sock",
    )

    assert service.config.transport == "uds_ws"
    assert service.config.url == "ws://localhost/v1/stt/stream"
    assert service.config.uds_path == "/run/rtc-asr/stt.sock"
