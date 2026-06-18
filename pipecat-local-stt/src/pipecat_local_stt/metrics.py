from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class LocalSTTMetrics:
    local_stt_audio_frames_received_total: int = 0
    local_stt_audio_frames_sent_total: int = 0
    local_stt_audio_frames_dropped_total: int = 0
    local_stt_send_queue_depth_ms: float = 0.0
    local_stt_reconnects_total: int = 0
    local_stt_interim_events_total: int = 0
    local_stt_final_events_total: int = 0
    local_stt_protocol_errors_total: int = 0

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)
