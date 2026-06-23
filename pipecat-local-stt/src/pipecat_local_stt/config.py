from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DropPolicy = Literal["drop_oldest", "block", "raise"]
Transport = Literal["tcp_ws", "uds_ws"]


@dataclass(slots=True)
class LocalSTTConfig:
    transport: Transport = "tcp_ws"
    url: str = "ws://rtc-asr:8080/v1/stt/stream"
    uds_path: str | None = None
    language: str | None = "en"
    sample_rate: int = 16000
    channels: int = 1
    format: str = "pcm_s16le"
    frame_ms: int = 20
    interim_results: bool = True
    partial_interval_ms: int = 100
    partial_window_seconds: float = 1.0
    max_buffer_seconds: float = 10.0

    connect_timeout_s: float = 3.0
    reconnect_on_error: bool = True
    max_send_queue_ms: int = 500
    drop_policy: DropPolicy = "drop_oldest"

    emit_interim_frames: bool = True
    emit_final_frames: bool = True
    pass_audio_downstream: bool = True
    enable_timing_metadata: bool = True

    def __post_init__(self) -> None:
        if self.transport not in {"tcp_ws", "uds_ws"}:
            raise ValueError("transport must be tcp_ws or uds_ws")
        if not self.url:
            raise ValueError("url must not be empty")
        if self.transport == "uds_ws" and not self.uds_path:
            raise ValueError("uds_path is required when transport is uds_ws")
        if self.transport == "tcp_ws" and self.uds_path is not None:
            raise ValueError("uds_path is only valid when transport is uds_ws")
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.format != "pcm_s16le":
            raise ValueError("format must be pcm_s16le")
        if self.frame_ms <= 0:
            raise ValueError("frame_ms must be positive")
        if self.partial_interval_ms <= 0:
            raise ValueError("partial_interval_ms must be positive")
        if self.partial_window_seconds <= 0:
            raise ValueError("partial_window_seconds must be positive")
        if self.max_buffer_seconds <= 0:
            raise ValueError("max_buffer_seconds must be positive")
        if self.connect_timeout_s <= 0:
            raise ValueError("connect_timeout_s must be positive")
        if self.max_send_queue_ms <= 0:
            raise ValueError("max_send_queue_ms must be positive")
        if self.drop_policy not in {"drop_oldest", "block", "raise"}:
            raise ValueError("drop_policy must be drop_oldest, block, or raise")

    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.channels * 2

    @property
    def bytes_per_frame(self) -> int:
        return int(self.bytes_per_second * (self.frame_ms / 1000.0))

    @property
    def max_queue_bytes(self) -> int:
        return max(1, int(self.bytes_per_second * (self.max_send_queue_ms / 1000.0)))
