from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService, RtcAsrSTTService


@dataclass(frozen=True)
class BotSettings:
    service: str = os.getenv("LOCAL_STT_SERVICE", "local")
    ws_url: str = os.getenv("RTC_ASR_WS_URL", "ws://rtc-asr:8080/v1/stt/stream")
    language: str | None = os.getenv("LOCAL_STT_LANGUAGE", "en") or None
    sample_rate: int = int(os.getenv("LOCAL_STT_SAMPLE_RATE", "16000"))
    channels: int = int(os.getenv("LOCAL_STT_CHANNELS", "1"))
    frame_ms: int = int(os.getenv("LOCAL_STT_FRAME_MS", "20"))
    partial_interval_ms: int = int(os.getenv("LOCAL_STT_PARTIAL_INTERVAL_MS", "100"))
    partial_window_seconds: float = float(os.getenv("LOCAL_STT_PARTIAL_WINDOW_SECONDS", "1.0"))


def build_local_stt(settings: BotSettings) -> LocalStreamingSTTService:
    return LocalStreamingSTTService(
        LocalSTTConfig(
            url=settings.ws_url,
            language=settings.language,
            sample_rate=settings.sample_rate,
            channels=settings.channels,
            format="pcm_s16le",
            frame_ms=settings.frame_ms,
            partial_interval_ms=settings.partial_interval_ms,
            partial_window_seconds=settings.partial_window_seconds,
            interim_results=True,
        )
    )


def build_rtc_asr_stt(settings: BotSettings) -> RtcAsrSTTService:
    return RtcAsrSTTService(
        url=settings.ws_url,
        language=settings.language,
        sample_rate=settings.sample_rate,
        channels=settings.channels,
        frame_ms=settings.frame_ms,
        partial_interval_ms=settings.partial_interval_ms,
        partial_window_seconds=settings.partial_window_seconds,
    )


def build_stt(settings: BotSettings) -> LocalStreamingSTTService | RtcAsrSTTService:
    if settings.service == "local":
        return build_local_stt(settings)
    if settings.service == "rtc-asr":
        return build_rtc_asr_stt(settings)
    raise ValueError("LOCAL_STT_SERVICE must be 'local' or 'rtc-asr'")


def build_pipeline(transport: Any, context_aggregator: Any, llm: Any, tts: Any, stt: Any) -> Any:
    from pipecat.pipeline.pipeline import Pipeline

    return Pipeline(
        [
            transport.input(),
            stt,
            context_aggregator.user(),
            llm,
            tts,
            transport.output(),
        ]
    )


def main() -> None:
    settings = BotSettings()
    stt = build_stt(settings)
    print(
        "Pipecat Local STT example configured for "
        f"service={settings.service}, {settings.ws_url} at sample_rate={settings.sample_rate}, "
        f"language={settings.language or 'auto'}, channels={settings.channels}, frame_ms={settings.frame_ms}, "
        f"partial_interval_ms={settings.partial_interval_ms}."
    )
    print(
        "Attach the returned STT service between transport.input() and "
        "context_aggregator.user() in your Pipecat app."
    )
    print(f"Service object: {stt.__class__.__name__}")


if __name__ == "__main__":
    main()
