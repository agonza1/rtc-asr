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
        connect_fn: ConnectFn | None = None,
        **kwargs: Any,
    ) -> None:
        config = LocalSTTConfig(url=url, language=language)
        super().__init__(config, connect_fn=connect_fn, **kwargs)
