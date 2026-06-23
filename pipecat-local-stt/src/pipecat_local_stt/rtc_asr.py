from __future__ import annotations

from typing import Any

from .config import LocalSTTConfig, Transport
from .service import ConnectFn, LocalStreamingSTTService


class RtcAsrSTTService(LocalStreamingSTTService):
    def __init__(
        self,
        *,
        transport: Transport = "tcp_ws",
        url: str = "ws://rtc-asr:8080/v1/stt/stream",
        uds_path: str | None = None,
        language: str | None = "en",
        sample_rate: int = 16000,
        channels: int = 1,
        frame_ms: int = 20,
        partial_interval_ms: int = 100,
        partial_window_seconds: float = 1.0,
        max_buffer_seconds: float = 10.0,
        connect_fn: ConnectFn | None = None,
        **kwargs: Any,
    ) -> None:
        config = LocalSTTConfig(
            transport=transport,
            url=url,
            uds_path=uds_path,
            language=language,
            sample_rate=sample_rate,
            channels=channels,
            frame_ms=frame_ms,
            partial_interval_ms=partial_interval_ms,
            partial_window_seconds=partial_window_seconds,
            max_buffer_seconds=max_buffer_seconds,
        )
        super().__init__(config, connect_fn=connect_fn, **kwargs)
