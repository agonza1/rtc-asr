from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(slots=True)
class LocalSTTMetrics:
    local_stt_audio_frames_received_total: int = 0
    local_stt_audio_received_ms_total: float = 0.0
    local_stt_audio_frames_sent_total: int = 0
    local_stt_audio_sent_ms_total: float = 0.0
    local_stt_audio_frames_dropped_total: int = 0
    local_stt_audio_dropped_ms_total: float = 0.0
    local_stt_oversized_audio_chunks_total: int = 0
    local_stt_oversized_audio_ms_total: float = 0.0
    local_stt_aggregate_buffer_bytes: int = 0
    local_stt_aggregate_buffer_bytes_high_water: int = 0
    local_stt_aggregate_buffer_ms: float = 0.0
    local_stt_aggregate_buffer_high_water_ms: float = 0.0
    local_stt_send_queue_chunks: int = 0
    local_stt_send_queue_chunks_high_water: int = 0
    local_stt_send_queue_depth_ms: float = 0.0
    local_stt_send_queue_depth_high_water_ms: float = 0.0
    local_stt_send_queue_utilization_ratio: float = 0.0
    local_stt_send_queue_utilization_high_water_ratio: float = 0.0
    local_stt_reconnects_total: int = 0
    local_stt_ready_events_total: int = 0
    local_stt_stale_ready_events_total: int = 0
    local_stt_ready_latency_ms: float = 0.0
    local_stt_ready_timeouts_total: int = 0
    local_stt_interim_events_total: int = 0
    local_stt_final_events_total: int = 0
    local_stt_final_latency_ms: float = 0.0
    local_stt_stale_transcript_events_total: int = 0
    local_stt_transcripts_suppressed_total: int = 0
    local_stt_warning_events_total: int = 0
    local_stt_final_timeouts_total: int = 0
    local_stt_heartbeat_events_total: int = 0
    local_stt_ping_events_total: int = 0
    local_stt_pong_events_total: int = 0
    local_stt_pong_events_sent_total: int = 0
    local_stt_closed_events_total: int = 0
    local_stt_protocol_errors_total: int = 0
    local_stt_start_messages_sent_total: int = 0
    local_stt_finalize_messages_sent_total: int = 0
    local_stt_cancel_messages_sent_total: int = 0
    local_stt_close_messages_sent_total: int = 0

    def as_dict(self) -> dict[str, int | float]:
        return asdict(self)
