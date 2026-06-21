from __future__ import annotations

from typing import Any

from .config import LocalSTTConfig
from .service import ConnectFn, LocalStreamingSTTService


class RtcAsrSTTService(LocalStreamingSTTService):
    def __init__(
        self,
        *,
        url: str = "ws://rtc-asr:8080/v1/stt/stream",
        language: str | None = "en",
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: int = 20,
        partial_interval_ms: int = 100,
        partial_window_seconds: float = 1.0,
        connect_fn: ConnectFn | None = None,
        **kwargs: Any,
    ) -> None:
        config = LocalSTTConfig(
            url=url,
            language=language,
            sample_rate=sample_rate,
            channels=channels,
            frame_ms=frame_ms,
            partial_interval_ms=partial_interval_ms,
            partial_window_seconds=partial_window_seconds,
        )
        super().__init__(config, connect_fn=connect_fn, **kwargs)
