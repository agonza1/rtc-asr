from __future__ import annotations

from typing import Any

from .config import DropPolicy, LocalSTTConfig, Transport
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
        aggregation_ms: int = 100,
        pre_roll_ms: int = 200,
        interim_results: bool = True,
        partial_interval_ms: int = 100,
        partial_window_seconds: float = 1.0,
        max_buffer_seconds: float = 10.0,
        final_timeout_s: float = 1.0,
        reconnect_on_error: bool = True,
        max_send_queue_ms: int = 500,
        drop_policy: DropPolicy = "drop_oldest",
        emit_interim_frames: bool = True,
        emit_final_frames: bool = True,
        pass_audio_downstream: bool = True,
        enable_timing_metadata: bool = True,
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
            aggregation_ms=aggregation_ms,
            pre_roll_ms=pre_roll_ms,
            interim_results=interim_results,
            partial_interval_ms=partial_interval_ms,
            partial_window_seconds=partial_window_seconds,
            max_buffer_seconds=max_buffer_seconds,
            final_timeout_s=final_timeout_s,
            reconnect_on_error=reconnect_on_error,
            max_send_queue_ms=max_send_queue_ms,
            drop_policy=drop_policy,
            emit_interim_frames=emit_interim_frames,
            emit_final_frames=emit_final_frames,
            pass_audio_downstream=pass_audio_downstream,
            enable_timing_metadata=enable_timing_metadata,
        )
        super().__init__(config, connect_fn=connect_fn, **kwargs)
