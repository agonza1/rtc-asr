from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService, RtcAsrSTTService


@dataclass(frozen=True)
class BotSettings:
    service: str = "local"
    ws_url: str = "ws://rtc-asr:8080/v1/stt/stream"
    language: str | None = "en"
    sample_rate: int = 16000
    channels: int = 1
    frame_ms: int = 20
    partial_interval_ms: int = 100
    partial_window_seconds: float = 1.0
    max_buffer_seconds: float = 10.0
    whisper_model: str = "base.en"

    @classmethod
    def from_env(cls) -> "BotSettings":
        return cls(
            service=os.getenv("LOCAL_STT_SERVICE", cls.service),
            ws_url=os.getenv("RTC_ASR_WS_URL", cls.ws_url),
            language=os.getenv("LOCAL_STT_LANGUAGE", cls.language or "") or None,
            sample_rate=int(os.getenv("LOCAL_STT_SAMPLE_RATE", str(cls.sample_rate))),
            channels=int(os.getenv("LOCAL_STT_CHANNELS", str(cls.channels))),
            frame_ms=int(os.getenv("LOCAL_STT_FRAME_MS", str(cls.frame_ms))),
            partial_interval_ms=int(os.getenv("LOCAL_STT_PARTIAL_INTERVAL_MS", str(cls.partial_interval_ms))),
            partial_window_seconds=float(
                os.getenv("LOCAL_STT_PARTIAL_WINDOW_SECONDS", str(cls.partial_window_seconds))
            ),
            max_buffer_seconds=float(os.getenv("LOCAL_STT_MAX_BUFFER_SECONDS", str(cls.max_buffer_seconds))),
            whisper_model=os.getenv("PIPECAT_WHISPER_MODEL", cls.whisper_model),
        )


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
            max_buffer_seconds=settings.max_buffer_seconds,
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
        max_buffer_seconds=settings.max_buffer_seconds,
    )


def build_pipecat_whisper_stt(settings: BotSettings) -> Any:
    try:
        from pipecat.services.whisper.stt import WhisperSTTService
    except ImportError as exc:
        raise RuntimeError(
            "LOCAL_STT_SERVICE=pipecat-whisper requires Pipecat's built-in Whisper STT dependencies. "
            "Install the example requirements and any platform-specific Whisper extras before using this baseline."
        ) from exc

    return WhisperSTTService(model=settings.whisper_model)


def build_stt(settings: BotSettings) -> LocalStreamingSTTService | RtcAsrSTTService | Any:
    if settings.service == "local":
        return build_local_stt(settings)
    if settings.service == "rtc-asr":
        return build_rtc_asr_stt(settings)
    if settings.service == "pipecat-whisper":
        return build_pipecat_whisper_stt(settings)
    raise ValueError("LOCAL_STT_SERVICE must be 'local', 'rtc-asr', or 'pipecat-whisper'")


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
    settings = BotSettings.from_env()
    stt = build_stt(settings)
    print(
        "Pipecat Local STT example configured for "
        f"service={settings.service}, {settings.ws_url} at sample_rate={settings.sample_rate}, "
        f"language={settings.language or 'auto'}, channels={settings.channels}, frame_ms={settings.frame_ms}, "
        f"partial_interval_ms={settings.partial_interval_ms}, max_buffer_seconds={settings.max_buffer_seconds}."
    )
    print(
        "Attach the returned STT service between transport.input() and "
        "context_aggregator.user() in your Pipecat app."
    )
    print(f"Service object: {stt.__class__.__name__}")


if __name__ == "__main__":
    main()
