from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_local_stt_transports.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_compare_local_stt_transports", MODULE_PATH)
compare_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_compare_local_stt_transports", compare_module)
assert SPEC.loader is not None
SPEC.loader.exec_module(compare_module)


def write_artifact(
    path: Path,
    transport: str,
    first_interim_p95: float,
    *,
    final_after_finalize_p95: float = 25.0,
    audio_send_queue_depth_p95: float = 2.0,
    asr_queue_delay_p95: float = 5.0,
    cpu_utilization_percent: float | None = 12.5,
    runs: int | None = 3,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "local-stt-v1-latency-benchmark",
                "target": {
                    "transport": transport,
                    "url": "ws://localhost/v1/stt/stream" if transport != "raw_uds" else None,
                    "uds_path": "/tmp/stt.sock" if transport != "tcp_ws" else None,
                    **(
                        {
                            "frame_format": "uint8_type_uint32_len_le",
                            "frame_header_bytes": 5,
                            "per_frame_overhead_bytes": 5,
                            "frame_types": [
                                "JSON_CONTROL",
                                "AUDIO_PCM16",
                                "JSON_EVENT",
                                "ERROR",
                                "PING",
                                "PONG",
                            ],
                            "frame_type_codes": {
                                "JSON_CONTROL": 1,
                                "AUDIO_PCM16": 2,
                                "JSON_EVENT": 3,
                                "ERROR": 4,
                                "PING": 5,
                                "PONG": 6,
                            },
                            "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
                            "error_handling": [
                                "bad_frame_type",
                                "malformed_json_control",
                                "oversized_payload",
                            ],
                            "shared_stream_runtime": True,
                        }
                        if transport == "raw_uds"
                        else {}
                    ),
                },
                "environment": (
                    {"cpu_utilization_percent": cpu_utilization_percent}
                    if cpu_utilization_percent is not None
                    else {}
                ),
                "audio": {"source": "sample.raw", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le", "frame_ms": 20, "duration_ms": 1000},
                "settings": {"partial_interval_ms": 100, "realtime_pace": True},
                **({"runs": runs} if runs is not None else {}),
                "summary": {
                    "time_to_first_interim_ms": {"p50": first_interim_p95 - 1, "p95": first_interim_p95, "p99": first_interim_p95 + 1},
                    "time_to_final_after_finalize_ms": {
                        "p50": final_after_finalize_p95 - 5.0,
                        "p95": final_after_finalize_p95,
                        "p99": final_after_finalize_p95 + 5.0,
                    },
                    "audio_send_queue_depth_p95_ms": {
                        "p50": audio_send_queue_depth_p95 - 1.0,
                        "p95": audio_send_queue_depth_p95,
                        "p99": audio_send_queue_depth_p95 + 1.0,
                    },
                    "asr_queue_delay_p95_ms": {
                        "p50": asr_queue_delay_p95 - 1.0,
                        "p95": asr_queue_delay_p95,
                        "p99": asr_queue_delay_p95 + 1.0,
                    },
                    "protocol_errors": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
                },
            }
        ),
        encoding="utf8",
    )
    return path


def test_compare_artifacts_requires_all_raw_uds_experiment_transports(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, final_after_finalize_p95=23.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0, final_after_finalize_p95=28.0)

    comparison = compare_module.compare_artifacts([tcp, raw])

    assert comparison["missing_transports"] == ["uds_ws"]
    assert comparison["blocking_gaps"] == ["missing transport benchmark: uds_ws"]
    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["fastest_time_to_final_after_finalize_p95_transport"] == "tcp_ws"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] is None
    assert comparison["raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms"] is None
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["raw_uds_recommendation_gate"] == {
        "passed": False,
        "blockers": ["missing_transport:uds_ws", "missing_raw_uds_latency_delta"],
        "raw_uds_min_win_ms": 5.0,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": None,
    }
    assert comparison["raw_uds_decision_summary"]["next_action"] == (
        "Run the missing uds_ws benchmark before deciding on raw UDS."
    )
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is True
    assert comparison["recommendation"] == "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."


def test_compare_artifacts_reports_unexpected_transport_artifacts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    legacy = write_artifact(tmp_path / "legacy.json", "websocket", 21.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw, legacy])

    assert comparison["missing_transports"] == []
    assert comparison["unexpected_transports"] == ["websocket"]
    assert comparison["blocking_gaps"] == ["unexpected transport benchmark: websocket"]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == "Remove unexpected transport benchmark artifacts before recommending raw UDS."
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_requires_transport_target_fields(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 10.0)

    for path, missing_field in [(tcp, "url"), (uds, "uds_path"), (raw, "uds_path")]:
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["target"][missing_field] = None
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["target_field_gaps"] == [
        "tcp_ws missing target.url",
        "uds_ws missing target.uds_path",
        "raw_uds missing target.uds_path",
    ]
    assert comparison["blocking_gaps"] == comparison["target_field_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "target:tcp_ws missing target.url",
        "target:uds_ws missing target.uds_path",
        "target:raw_uds missing target.uds_path",
    ]
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with explicit endpoint targets before recommending raw UDS."
    )
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_issue_88_queue_metric_aliases(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 17.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 11.0)

    for path in (tcp, uds, raw):
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["summary"]["send_queue_depth_p95"] = payload["summary"].pop("audio_send_queue_depth_p95_ms")
        payload["summary"]["asr_queue_delay_p95"] = payload["summary"].pop("asr_queue_delay_p95_ms")
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_p95_metrics_by_transport"] == {}
    assert comparison["transports"]["raw_uds"]["metrics_p95"]["audio_send_queue_depth_p95_ms"] == 2.0
    assert comparison["transports"]["raw_uds"]["metrics_p95"]["asr_queue_delay_p95_ms"] == 5.0
    assert comparison["transports"]["tcp_ws"]["metrics"]["audio_send_queue_depth_p95_ms"]["p50"] == 1.0
    assert comparison["transports"]["tcp_ws"]["metrics"]["asr_queue_delay_p95_ms"]["p50"] == 4.0


def test_compare_artifacts_accepts_scalar_protocol_error_counts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 17.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 11.0)

    for path in (tcp, uds, raw):
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["summary"]["protocol_errors"] = 0
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_p95_metrics_by_transport"] == {}
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["metrics"]["protocol_errors"] == {
        "p50": 0.0,
        "p95": 0.0,
        "p99": 0.0,
    }
    assert comparison["transports"]["raw_uds"]["metrics_p95"]["protocol_errors"] == 0.0


def test_compare_artifacts_blocks_nonzero_scalar_protocol_errors(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 17.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 11.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["summary"]["protocol_errors"] = 1
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == ["protocol_errors"]
    assert comparison["blocking_gaps"] == [
        "raw_uds protocol_errors must be zero at p50/p95/p99; got p50=1.0, p95=1.0, p99=1.0"
    ]
    assert comparison["recommendation"] == (
        "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    )


def test_compare_artifacts_requires_raw_uds_frame_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("frame_format")
    raw_payload["target"]["frame_header_bytes"] = 4
    raw_payload["target"].pop("per_frame_overhead_bytes")
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_contract_gaps"] == [
        "raw_uds missing target.frame_format=uint8_type_uint32_len_le",
        "raw_uds missing target.frame_header_bytes=5",
        "raw_uds missing target.per_frame_overhead_bytes=5",
    ]
    assert comparison["blocking_gaps"] == comparison["raw_uds_frame_contract_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "frame_contract:raw_uds missing target.frame_format=uint8_type_uint32_len_le",
        "frame_contract:raw_uds missing target.frame_header_bytes=5",
        "frame_contract:raw_uds missing target.per_frame_overhead_bytes=5",
    ]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_raw_uds_frame_contract_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("frame_format")
    raw_payload["target"].pop("frame_header_bytes")
    raw_payload["target"].pop("per_frame_overhead_bytes")
    raw_payload["target_contract"] = {
        "frame_format": "uint8_type_uint32_len_le",
        "frame_header_bytes": 5,
        "per_frame_overhead_bytes": 5,
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_contract_gaps"] == []
    assert comparison["transports"]["raw_uds"]["frame_format"] == "uint8_type_uint32_len_le"
    assert comparison["transports"]["raw_uds"]["frame_header_bytes"] == 5
    assert comparison["transports"]["raw_uds"]["per_frame_overhead_bytes"] == 5


def test_compare_artifacts_requires_raw_uds_frame_type_coverage(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"]["frame_types"] = ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_type_gaps"] == ["raw_uds missing frame type coverage: PING,PONG"]
    assert comparison["blocking_gaps"] == comparison["raw_uds_frame_type_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "frame_type:raw_uds missing frame type coverage: PING,PONG"
    ]
    assert comparison["recommendation"] == (
        "Re-run raw UDS benchmarks with complete frame type coverage before recommending raw UDS."
    )
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_raw_uds_frame_types_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("frame_types")
    raw_payload["target_contract"] = {
        "frame_types": ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR", "PING", "PONG"],
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_type_gaps"] == []
    assert comparison["transports"]["raw_uds"]["frame_types"] == [
        "JSON_CONTROL",
        "AUDIO_PCM16",
        "JSON_EVENT",
        "ERROR",
        "PING",
        "PONG",
    ]


def test_compare_artifacts_requires_raw_uds_frame_type_code_coverage(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"]["frame_type_codes"] = {
        "JSON_CONTROL": 1,
        "AUDIO_PCM16": 2,
        "JSON_EVENT": 3,
        "ERROR": 4,
        "PING": 7,
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_type_gaps"] == [
        "raw_uds missing frame type code coverage: PONG",
        "raw_uds frame type code mismatch: PING=0x07,expected=0x05",
    ]
    assert comparison["blocking_gaps"] == comparison["raw_uds_frame_type_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "frame_type:raw_uds missing frame type code coverage: PONG",
        "frame_type:raw_uds frame type code mismatch: PING=0x07,expected=0x05",
    ]
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_raw_uds_frame_type_codes_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("frame_type_codes")
    raw_payload["target_contract"] = {
        "frame_type_codes": {
            "JSON_CONTROL": 1,
            "AUDIO_PCM16": 2,
            "JSON_EVENT": 3,
            "ERROR": 4,
            "PING": 5,
            "PONG": 6,
        },
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_type_gaps"] == []
    assert comparison["transports"]["raw_uds"]["frame_type_codes"] == {
        "JSON_CONTROL": 1,
        "AUDIO_PCM16": 2,
        "JSON_EVENT": 3,
        "ERROR": 4,
        "PING": 5,
        "PONG": 6,
    }


def test_compare_artifacts_accepts_raw_uds_contract_aliases(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    for field in (
        "frame_format",
        "frame_header_bytes",
        "per_frame_overhead_bytes",
        "frame_types",
        "frame_type_codes",
        "lifecycle",
        "error_handling",
        "shared_stream_runtime",
    ):
        raw_payload["target"].pop(field)
    raw_payload["contract"] = {
        "frame_format": "uint8_type_uint32_len_le",
        "frame_header_bytes": 5,
        "per_frame_overhead_bytes": 5,
        "frame_types": ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR", "PING", "PONG"],
        "frame_type_codes": {
            "JSON_CONTROL": 1,
            "AUDIO_PCM16": 2,
            "JSON_EVENT": 3,
            "ERROR": 4,
            "PING": 5,
            "PONG": 6,
        },
        "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
        "error_handling": ["bad_frame_type", "malformed_json_control", "oversized_payload"],
        "shared_stream_runtime": True,
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_contract_gaps"] == []
    assert comparison["raw_uds_frame_type_gaps"] == []
    assert comparison["raw_uds_lifecycle_gaps"] == []
    assert comparison["raw_uds_error_handling_gaps"] == []
    assert comparison["raw_uds_runtime_gaps"] == []
    assert comparison["transports"]["raw_uds"]["shared_stream_runtime"] is True


def test_compare_artifacts_accepts_nested_raw_uds_target_contract_alias(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("frame_format")
    raw_payload["target"]["contract"] = {"frame_format": "uint8_type_uint32_len_le"}
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_frame_contract_gaps"] == []
    assert comparison["transports"]["raw_uds"]["frame_format"] == "uint8_type_uint32_len_le"


def test_compare_artifacts_requires_raw_uds_lifecycle_coverage(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"]["lifecycle"] = ["start", "audio", "transcript", "finalize"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_lifecycle_gaps"] == ["raw_uds missing lifecycle coverage: cancel,close"]
    assert comparison["blocking_gaps"] == comparison["raw_uds_lifecycle_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "lifecycle:raw_uds missing lifecycle coverage: cancel,close"
    ]
    assert comparison["recommendation"] == (
        "Re-run raw UDS benchmarks with full Local STT v1 lifecycle coverage before recommending raw UDS."
    )
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_requires_raw_uds_lifecycle_order(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"]["lifecycle"] = ["start", "audio", "finalize", "transcript", "cancel", "close"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_lifecycle_gaps"] == [
        "raw_uds lifecycle order mismatch: expected start,audio,transcript,finalize,cancel,close; "
        "got start,audio,finalize,transcript,cancel,close"
    ]
    assert comparison["blocking_gaps"] == comparison["raw_uds_lifecycle_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "lifecycle:raw_uds lifecycle order mismatch: expected start,audio,transcript,finalize,cancel,close; "
        "got start,audio,finalize,transcript,cancel,close"
    ]
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_raw_uds_lifecycle_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("lifecycle")
    raw_payload["target_contract"] = {
        "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_lifecycle_gaps"] == []
    assert comparison["transports"]["raw_uds"]["lifecycle"] == [
        "start",
        "audio",
        "transcript",
        "finalize",
        "cancel",
        "close",
    ]


def test_compare_artifacts_requires_raw_uds_shared_runtime_evidence(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("shared_stream_runtime")
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_runtime_gaps"] == ["raw_uds missing shared stream runtime evidence"]
    assert comparison["blocking_gaps"] == comparison["raw_uds_runtime_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "runtime:raw_uds missing shared stream runtime evidence"
    ]
    assert comparison["recommendation"] == (
        "Re-run raw UDS benchmarks with shared stream runtime evidence before recommending raw UDS."
    )
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_accepts_raw_uds_shared_runtime_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("shared_stream_runtime")
    raw_payload["target_contract"] = {"shared_stream_runtime": True}
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_runtime_gaps"] == []
    assert comparison["transports"]["raw_uds"]["shared_stream_runtime"] is True


def test_compare_artifacts_requires_raw_uds_error_handling_coverage(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"]["error_handling"] = ["bad_frame_type"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_error_handling_gaps"] == [
        "raw_uds missing protocol-error handling coverage: malformed_json_control,oversized_payload"
    ]
    assert comparison["blocking_gaps"] == comparison["raw_uds_error_handling_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "error_handling:raw_uds missing protocol-error handling coverage: malformed_json_control,oversized_payload"
    ]
    assert comparison["recommendation"] == (
        "Re-run raw UDS benchmarks with protocol-error handling coverage before recommending raw UDS."
    )


def test_compare_artifacts_accepts_raw_uds_error_handling_from_benchmark_contract(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["target"].pop("error_handling")
    raw_payload["target_contract"] = {
        "error_handling": ["bad_frame_type", "malformed_json_control", "oversized_payload"]
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["raw_uds_error_handling_gaps"] == []
    assert comparison["transports"]["raw_uds"]["error_handling"] == [
        "bad_frame_type",
        "malformed_json_control",
        "oversized_payload",
    ]


def test_compare_artifacts_marks_raw_uds_experimental_under_five_ms_win(tmp_path: Path) -> None:
    tcp = write_artifact(
        tmp_path / "tcp.json",
        "tcp_ws",
        18.0,
        final_after_finalize_p95=31.0,
        cpu_utilization_percent=15.0,
    )
    uds = write_artifact(
        tmp_path / "uds.json",
        "uds_ws",
        16.0,
        final_after_finalize_p95=24.0,
        audio_send_queue_depth_p95=7.0,
        asr_queue_delay_p95=11.0,
        cpu_utilization_percent=13.0,
    )
    raw = write_artifact(
        tmp_path / "raw.json",
        "raw_uds",
        12.5,
        final_after_finalize_p95=27.0,
        audio_send_queue_depth_p95=4.0,
        asr_queue_delay_p95=6.5,
        cpu_utilization_percent=11.0,
    )

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_transports"] == []
    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["fastest_time_to_final_after_finalize_p95_transport"] == "uds_ws"
    assert comparison["p95_metric_leaders"] == {
        "time_to_first_interim_ms": "raw_uds",
        "time_to_final_after_finalize_ms": "uds_ws",
        "audio_send_queue_depth_p95_ms": "tcp_ws",
        "asr_queue_delay_p95_ms": "tcp_ws",
        "protocol_errors": "raw_uds",
    }
    assert comparison["lowest_cpu_utilization_percent_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_p95_deltas_ms"] == {
        "time_to_first_interim_ms": 3.5,
        "time_to_final_after_finalize_ms": -3.0,
        "audio_send_queue_depth_p95_ms": 3.0,
        "asr_queue_delay_p95_ms": 4.5,
        "protocol_errors": 0.0,
    }
    assert comparison["pairwise_p95_deltas_ms"]["time_to_first_interim_ms"] == {
        "tcp_ws": {"tcp_ws": None, "uds_ws": 2.0, "raw_uds": 5.5},
        "uds_ws": {"tcp_ws": -2.0, "uds_ws": None, "raw_uds": 3.5},
        "raw_uds": {"tcp_ws": -5.5, "uds_ws": -3.5, "raw_uds": None},
    }
    assert comparison["pairwise_p95_deltas_ms"]["time_to_final_after_finalize_ms"] == {
        "tcp_ws": {"tcp_ws": None, "uds_ws": 7.0, "raw_uds": 4.0},
        "uds_ws": {"tcp_ws": -7.0, "uds_ws": None, "raw_uds": -3.0},
        "raw_uds": {"tcp_ws": -4.0, "uds_ws": 3.0, "raw_uds": None},
    }
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 3.5
    assert comparison["raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms"] == -3.0
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["raw_uds_recommendation_gate"] == {
        "passed": False,
        "blockers": ["insufficient_raw_uds_latency_win"],
        "raw_uds_min_win_ms": 5.0,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": 3.5,
    }
    assert comparison["raw_uds_decision_summary"] == {
        "status": "experimental",
        "reason": "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms.",
        "next_action": "Keep raw UDS experimental unless a future benchmark clears the latency gate.",
        "primary_metric": "time_to_first_interim_ms",
        "comparison_baseline": "uds_ws",
        "observed_first_interim_p95_win_ms": 3.5,
        "required_first_interim_p95_win_ms": 5.0,
        "observed_final_after_finalize_p95_delta_ms": -3.0,
        "raw_uds_leading_p95_metrics": ["time_to_first_interim_ms"],
        "gate_passed": False,
        "gate_blockers": ["insufficient_raw_uds_latency_win"],
        "gate_blocker_count": 1,
    }
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is True
    assert comparison["recommendation"] == "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms."
    assert comparison["transports"]["raw_uds"]["metrics_p95"] == {
        "time_to_first_interim_ms": 12.5,
        "time_to_final_after_finalize_ms": 27.0,
        "audio_send_queue_depth_p95_ms": 4.0,
        "asr_queue_delay_p95_ms": 6.5,
        "protocol_errors": 0.0,
    }
    raw_payload = raw.read_bytes()
    assert comparison["transports"]["raw_uds"]["artifact_sha256"] == hashlib.sha256(raw_payload).hexdigest()
    assert comparison["transports"]["raw_uds"]["artifact_size_bytes"] == len(raw_payload)
    assert comparison["transports"]["raw_uds"]["metrics"]["time_to_first_interim_ms"] == {
        "p50": 11.5,
        "p95": 12.5,
        "p99": 13.5,
    }
    assert comparison["transports"]["raw_uds"]["metrics"]["time_to_final_after_finalize_ms"] == {
        "p50": 22.0,
        "p95": 27.0,
        "p99": 32.0,
    }
    assert comparison["raw_uds_p95_comparison_summary"]["tcp_ws"]["time_to_first_interim_ms"] == {
        "baseline_p95": 18.0,
        "raw_uds_p95": 12.5,
        "delta_ms": 5.5,
        "status": "improved",
    }
    assert comparison["raw_uds_p95_comparison_summary"]["uds_ws"]["time_to_final_after_finalize_ms"] == {
        "baseline_p95": 24.0,
        "raw_uds_p95": 27.0,
        "delta_ms": -3.0,
        "status": "regressed",
    }
    assert comparison["raw_uds_p95_comparison_summary"]["uds_ws"]["protocol_errors"] == {
        "baseline_p95": 0.0,
        "raw_uds_p95": 0.0,
        "delta_ms": 0.0,
        "status": "matched",
    }


def test_compare_artifacts_marks_missing_raw_uds_summary_metrics(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)

    comparison = compare_module.compare_artifacts([tcp])

    assert comparison["raw_uds_p95_comparison_summary"]["tcp_ws"]["time_to_first_interim_ms"] == {
        "baseline_p95": 18.0,
        "raw_uds_p95": None,
        "delta_ms": None,
        "status": "missing",
    }
    assert comparison["raw_uds_p95_comparison_summary"]["uds_ws"]["time_to_first_interim_ms"] == {
        "baseline_p95": None,
        "raw_uds_p95": None,
        "delta_ms": None,
        "status": "missing",
    }


def test_compare_artifacts_reports_lowest_cpu_transport_when_available(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, cpu_utilization_percent=14.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0, cpu_utilization_percent=None)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0, cpu_utilization_percent=11.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["run_count_coverage"] == {
        "available_transports": ["raw_uds", "tcp_ws", "uds_ws"],
        "missing_transports": [],
        "required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "run_counts": {"raw_uds": 3, "tcp_ws": 3, "uds_ws": 3},
        "min_runs": 3,
        "complete": True,
    }
    assert comparison["lowest_cpu_utilization_percent_transport"] == "raw_uds"
    assert comparison["missing_cpu_utilization_transports"] == ["uds_ws"]
    assert comparison["cpu_utilization_coverage"] == {
        "available_transports": ["raw_uds", "tcp_ws"],
        "missing_transports": ["uds_ws"],
        "required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "complete": False,
    }
    assert comparison["transports"]["uds_ws"]["cpu_utilization_percent"] is None


def test_compare_artifacts_reads_nested_cpu_utilization_aliases(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, cpu_utilization_percent=None)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0, cpu_utilization_percent=None)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0, cpu_utilization_percent=None)

    tcp_payload = json.loads(tcp.read_text(encoding="utf8"))
    tcp_payload["metrics"] = {"cpu": {"average_percent": 10.5}}
    tcp.write_text(json.dumps(tcp_payload), encoding="utf8")
    uds_payload = json.loads(uds.read_text(encoding="utf8"))
    uds_payload["system"] = {"cpu_percent": 12.0}
    uds.write_text(json.dumps(uds_payload), encoding="utf8")
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["cpu"] = {"utilization_percent": 9.5}
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["lowest_cpu_utilization_percent_transport"] == "raw_uds"
    assert comparison["missing_cpu_utilization_transports"] == []
    assert comparison["cpu_utilization_coverage"]["complete"] is True
    assert comparison["transports"]["tcp_ws"]["cpu_utilization_percent"] == 10.5
    assert comparison["transports"]["uds_ws"]["cpu_utilization_percent"] == 12.0
    assert comparison["transports"]["raw_uds"]["cpu_utilization_percent"] == 9.5


def test_compare_artifacts_reports_all_transports_missing_cpu_when_unavailable(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, cpu_utilization_percent=None, runs=5)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0, cpu_utilization_percent=None, runs=None)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0, cpu_utilization_percent=None, runs=3)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["run_count_coverage"] == {
        "available_transports": ["raw_uds", "tcp_ws"],
        "missing_transports": ["uds_ws"],
        "required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "run_counts": {"raw_uds": 3, "tcp_ws": 5},
        "min_runs": 3,
        "complete": False,
    }
    assert comparison["lowest_cpu_utilization_percent_transport"] is None
    assert comparison["missing_cpu_utilization_transports"] == ["raw_uds", "tcp_ws", "uds_ws"]
    assert comparison["cpu_utilization_coverage"] == {
        "available_transports": [],
        "missing_transports": ["raw_uds", "tcp_ws", "uds_ws"],
        "required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "complete": False,
    }
    assert comparison["raw_uds_should_remain_experimental"] is False


def test_compare_artifacts_can_require_minimum_run_counts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, runs=3)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0, runs=2)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0, runs=None)

    comparison = compare_module.compare_artifacts([tcp, uds, raw], min_runs=3)

    assert comparison["minimum_required_runs"] == 3
    assert comparison["run_count_gaps"] == [
        "raw_uds missing run count",
        "uds_ws has 2 runs; requires at least 3",
    ]
    assert comparison["blocking_gaps"] == comparison["run_count_gaps"]
    assert compare_module.comparison_has_blocking_gaps(comparison) is True
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with enough repeated runs before recommending raw UDS."
    )


def test_compare_artifacts_rejects_invalid_minimum_run_count(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)

    try:
        compare_module.compare_artifacts([tcp], min_runs=0)
    except ValueError as exc:
        assert "min_runs must be positive" in str(exc)
    else:
        raise AssertionError("expected min_runs validation failure")


def test_compare_artifacts_allows_raw_uds_recommendation_at_five_ms_win(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 5.0
    assert comparison["raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms"] == 0.0
    assert comparison["cpu_utilization_coverage"] == {
        "available_transports": ["raw_uds", "tcp_ws", "uds_ws"],
        "missing_transports": [],
        "required_transports": ["tcp_ws", "uds_ws", "raw_uds"],
        "complete": True,
    }
    assert comparison["raw_uds_should_remain_experimental"] is False
    assert comparison["raw_uds_recommendation_gate"] == {
        "passed": True,
        "blockers": [],
        "raw_uds_min_win_ms": 5.0,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": 5.0,
    }
    assert comparison["raw_uds_decision_summary"] == {
        "status": "recommended",
        "reason": "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype.",
        "next_action": "Proceed with the next raw UDS adapter prototype.",
        "primary_metric": "time_to_first_interim_ms",
        "comparison_baseline": "uds_ws",
        "observed_first_interim_p95_win_ms": 5.0,
        "required_first_interim_p95_win_ms": 5.0,
        "observed_final_after_finalize_p95_delta_ms": 0.0,
        "raw_uds_leading_p95_metrics": ["time_to_first_interim_ms"],
        "gate_passed": True,
        "gate_blockers": [],
        "gate_blocker_count": 0,
    }
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["recommendation"] == "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def test_compare_artifacts_can_raise_raw_uds_recommendation_threshold(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw], raw_uds_min_win_ms=7.5)

    assert comparison["raw_uds_min_win_ms"] == 7.5
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 5.0
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["raw_uds_recommendation_gate"] == {
        "passed": False,
        "blockers": ["insufficient_raw_uds_latency_win"],
        "raw_uds_min_win_ms": 7.5,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": 5.0,
    }
    assert comparison["recommendation"] == (
        "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 7.5 ms."
    )


def test_raw_uds_decision_summary_excludes_tied_p95_metrics(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, final_after_finalize_p95=25.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0, final_after_finalize_p95=25.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0, final_after_finalize_p95=25.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["p95_metric_leaders"]["protocol_errors"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_p95_deltas_ms"]["protocol_errors"] == 0.0
    assert comparison["raw_uds_decision_summary"]["raw_uds_leading_p95_metrics"] == [
        "time_to_first_interim_ms"
    ]


def test_compare_artifacts_rejects_invalid_raw_uds_recommendation_threshold(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)

    try:
        compare_module.compare_artifacts([tcp], raw_uds_min_win_ms=0)
    except ValueError as exc:
        assert "raw_uds_min_win_ms must be positive" in str(exc)
    else:
        raise AssertionError("expected raw_uds_min_win_ms validation failure")


def test_compare_artifacts_can_require_cpu_utilization_evidence(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0, cpu_utilization_percent=None)

    comparison = compare_module.compare_artifacts([tcp, uds, raw], require_cpu_utilization=True)

    assert comparison["cpu_utilization_gaps"] == ["raw_uds missing CPU utilization"]
    assert comparison["blocking_gaps"] == comparison["cpu_utilization_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "cpu_utilization:raw_uds missing CPU utilization"
    ]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with CPU utilization evidence before recommending raw UDS."
    )


def test_compare_artifacts_keeps_cpu_utilization_evidence_optional_by_default(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0, cpu_utilization_percent=None)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_cpu_utilization_transports"] == ["raw_uds"]
    assert comparison["cpu_utilization_gaps"] == []
    assert comparison["blocking_gaps"] == []
    assert comparison["raw_uds_recommendation_gate"]["passed"] is True


def test_compare_artifacts_requires_complete_benchmark_inputs(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    payload = json.loads(raw.read_text(encoding="utf8"))
    del payload["audio"]["duration_ms"]
    raw.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == [
        "benchmark input missing for audio.duration_ms: raw_uds"
    ]
    assert comparison["blocking_gaps"] == comparison["benchmark_input_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "benchmark_input:benchmark input missing for audio.duration_ms: raw_uds"
    ]
    assert comparison["raw_uds_should_remain_experimental"] is True


def test_compare_artifacts_accepts_benchmark_input_aliases_from_stream_artifacts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    for path in (tcp, uds, raw):
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["audio"] = {
            "path": "/tmp/rtc_asr_bench.aiff",
            "duration_s": 1.0,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
        }
        payload["settings"] = {
            "source_frame_ms": 20,
            "requested_partial_interval_ms": 100,
            "simulate_realtime": True,
        }
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == []
    assert comparison["transports"]["raw_uds"]["audio"] == {
        "source": "/tmp/rtc_asr_bench.aiff",
        "sample_rate": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "frame_ms": 20,
        "duration_ms": 1000.0,
    }
    assert comparison["transports"]["raw_uds"]["settings"] == {
        "partial_interval_ms": 100,
        "realtime_pace": True,
    }



def test_compare_artifacts_accepts_stream_artifact_benchmark_sections(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    for path in (tcp, uds, raw):
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["audio"] = {
            "path": "/tmp/rtc_asr_bench.aiff",
            "duration_s": 1.0,
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
        }
        payload.pop("settings")
        payload["benchmark"] = {
            "source_frame_ms": 20,
            "requested_partial_interval_ms": 100,
            "simulate_realtime": True,
        }
        payload["integration"] = {
            "source_frame_ms": 20,
            "requested_partial_interval_ms": 100,
            "simulate_realtime": True,
        }
        payload["streaming"] = {
            "source_frame_ms": 20,
            "requested_partial_interval_ms": 100,
            "simulate_realtime": True,
        }
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == []
    assert comparison["transports"]["raw_uds"]["audio"]["frame_ms"] == 20
    assert comparison["transports"]["raw_uds"]["settings"] == {
        "partial_interval_ms": 100,
        "realtime_pace": True,
    }


def test_compare_artifacts_requires_matching_benchmark_inputs(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    for path, frame_ms in [(tcp, 20), (uds, 20), (raw, 40)]:
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["audio"] = {"source": "sample.raw", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le", "frame_ms": frame_ms, "duration_ms": 1000}
        payload["settings"] = {"partial_interval_ms": 100, "realtime_pace": True}
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == [
        "benchmark input mismatch for audio.frame_ms: raw_uds=40, tcp_ws=20, uds_ws=20"
    ]
    assert comparison["blocking_gaps"] == comparison["benchmark_input_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "benchmark_input:benchmark input mismatch for audio.frame_ms: raw_uds=40, tcp_ws=20, uds_ws=20"
    ]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with matching audio and pacing settings before recommending raw UDS."
    )


def test_compare_artifacts_requires_matching_audio_format(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    payload = json.loads(raw.read_text(encoding="utf8"))
    payload["audio"]["format"] = "pcm_f32le"
    raw.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == [
        "benchmark input mismatch for audio.format: raw_uds='pcm_f32le', tcp_ws='pcm_s16le', uds_ws='pcm_s16le'"
    ]
    assert comparison["blocking_gaps"] == comparison["benchmark_input_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "benchmark_input:benchmark input mismatch for audio.format: raw_uds='pcm_f32le', tcp_ws='pcm_s16le', uds_ws='pcm_s16le'"
    ]


def test_compare_artifacts_requires_matching_service_identity_when_recorded(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    for path, model in [(tcp, "base.en"), (uds, "base.en"), (raw, "small.en")]:
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["backend"] = {"name": "faster-whisper", "model": model}
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == [
        "benchmark service identity mismatch for model: raw_uds='small.en', tcp_ws='base.en', uds_ws='base.en'"
    ]
    assert comparison["blocking_gaps"] == comparison["benchmark_input_gaps"]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == [
        "benchmark_input:benchmark service identity mismatch for model: raw_uds='small.en', tcp_ws='base.en', uds_ws='base.en'"
    ]
    assert comparison["transports"]["raw_uds"]["service"] == {
        "backend": "faster-whisper",
        "model": "small.en",
    }


def test_compare_artifacts_allows_unrecorded_service_identity(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["benchmark_input_gaps"] == []
    assert comparison["transports"]["raw_uds"]["service"] == {"backend": None, "model": None}


def test_compare_artifacts_flags_protocol_errors_in_present_transport(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["summary"]["protocol_errors"]["p95"] = 1.0
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["blocking_gaps"] == [
        "raw_uds protocol_errors must be zero at p50/p95/p99; got p50=0.0, p95=1.0, p99=0.0"
    ]
    assert comparison["transports"]["tcp_ws"]["protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is False
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    )


def test_compare_artifacts_flags_protocol_error_tail_percentiles(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["summary"]["protocol_errors"]["p99"] = 1.0
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["blocking_gaps"] == [
        "raw_uds protocol_errors must be zero at p50/p95/p99; got p50=0.0, p95=0.0, p99=1.0"
    ]
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is False
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


def test_compare_artifacts_preserves_diagnostic_code_counts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["diagnostics"] = {
        "protocol_error_codes": {"raw_uds_invalid_json": 2, "raw_uds_payload_too_large": "1"},
        "warning_codes": {"late_partial": 3},
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["transports"]["raw_uds"]["diagnostics"] == {
        "protocol_error_codes": {
            "raw_uds_invalid_json": 2,
            "raw_uds_payload_too_large": 1,
        },
        "protocol_error_total": 3,
        "warning_codes": {"late_partial": 3},
        "warning_total": 3,
    }
    assert comparison["transports"]["tcp_ws"]["diagnostics"] == {
        "protocol_error_codes": {},
        "protocol_error_total": 0,
        "warning_codes": {},
        "warning_total": 0,
    }


def test_compare_artifacts_blocks_diagnostic_protocol_error_codes(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["diagnostics"] = {
        "protocol_error_codes": {"raw_uds_invalid_json": 2, "raw_uds_payload_too_large": 1}
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is False
    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["blocking_gaps"] == [
        "raw_uds diagnostic protocol_error_codes total must be zero; "
        "got total=3 (raw_uds_invalid_json=2, raw_uds_payload_too_large=1)"
    ]
    assert comparison["raw_uds_recommendation_gate"]["blockers"] == ["protocol_errors"]
    assert comparison["raw_uds_should_remain_experimental"] is True


def test_compare_artifacts_reports_missing_required_p95_metrics(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    del raw_payload["summary"]["asr_queue_delay_p95_ms"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_p95_metrics_by_transport"] == {"raw_uds": ["asr_queue_delay_p95_ms:p95"]}
    assert comparison["blocking_gaps"] == ["raw_uds missing metric percentile: asr_queue_delay_p95_ms:p95"]
    assert comparison["transports"]["raw_uds"]["missing_p95_metrics"] == ["asr_queue_delay_p95_ms:p95"]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with the full required metric set before recommending raw UDS."
    )


def test_compare_artifacts_reports_missing_required_first_interim_percentiles(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    del raw_payload["summary"]["time_to_first_interim_ms"]["p99"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_p95_metrics_by_transport"] == {"raw_uds": ["time_to_first_interim_ms:p99"]}
    assert comparison["blocking_gaps"] == ["raw_uds missing metric percentile: time_to_first_interim_ms:p99"]
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Re-run transport benchmarks with the full required metric set before recommending raw UDS."
    )


def test_main_returns_failure_when_required_p95_metrics_are_missing(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    del raw_payload["summary"]["asr_queue_delay_p95_ms"]
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    assert compare_module.main([str(tcp), str(uds), str(raw)]) == 1


def test_main_succeeds_when_all_transport_comparison_gates_pass(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    assert compare_module.main([str(tcp), str(uds), str(raw)]) == 0


def test_main_can_require_minimum_run_counts(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0, runs=3)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0, runs=3)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0, runs=2)

    assert compare_module.main([str(tcp), str(uds), str(raw)]) == 0
    assert compare_module.main(["--min-runs", "3", str(tcp), str(uds), str(raw)]) == 1


def test_main_can_require_raw_uds_recommendation_gate(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.5)

    assert compare_module.main([str(tcp), str(uds), str(raw)]) == 0
    assert compare_module.main(["--require-raw-uds-recommendation", str(tcp), str(uds), str(raw)]) == 1


def test_main_raw_uds_recommendation_gate_passes_at_five_ms_win(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    assert compare_module.main(["--require-raw-uds-recommendation", str(tcp), str(uds), str(raw)]) == 0

def test_format_markdown_summary_includes_transport_gate_and_blockers(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["diagnostics"] = {
        "protocol_error_codes": {"raw_uds_invalid_json": 2},
        "warning_codes": {"late_partial": 1},
    }
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, raw])
    markdown = compare_module.format_markdown_summary(comparison)

    assert "# Local STT v1 Transport Comparison" in markdown
    assert "| tcp_ws | 18.0 ms | 25.0 ms | 0.0 | 12.5% | 3 |" in markdown
    assert "| uds_ws | missing | missing | missing | missing | missing | missing | missing | missing |" in markdown
    assert "Transport targets:" in markdown
    assert "P95 metric leaders:" in markdown
    assert "| time_to_first_interim_ms | raw_uds |" in markdown
    assert "| time_to_final_after_finalize_ms | raw_uds |" in markdown
    assert "CPU utilization coverage:" in markdown
    assert "- Complete: False" in markdown
    assert "- Available transports: raw_uds,tcp_ws" in markdown
    assert "- Missing CPU samples: missing" in markdown
    assert "- Missing required transports: uds_ws" in markdown
    assert "Run count coverage:" in markdown
    assert "- Complete: False" in markdown
    assert "- Minimum observed runs: 3" in markdown
    assert "- Required minimum runs: missing" in markdown
    assert "- Missing run counts: missing" in markdown
    assert "- Recorded runs: raw_uds=3,tcp_ws=3" in markdown
    assert "First-interim p95 deltas:" in markdown
    assert "| TCP WebSocket | protocol_errors | 0 | 0 | 0 | matched |" in markdown
    assert "| TCP WebSocket | baseline | missing | 5.0 ms |" in markdown
    assert "| Raw UDS | -5.0 ms | missing | baseline |" in markdown
    assert "| tcp_ws | ws://localhost/v1/stt/stream | missing | missing | missing | missing | missing | missing |" in markdown
    assert "| uds_ws | missing | missing | missing | missing | missing | missing | missing | missing |" in markdown
    assert "| raw_uds | missing | /tmp/stt.sock | uint8_type_uint32_len_le | 5 | JSON_CONTROL,AUDIO_PCM16,JSON_EVENT,ERROR,PING,PONG | start,audio,transcript,finalize,cancel,close | bad_frame_type,malformed_json_control,oversized_payload | True |" in markdown
    assert "Benchmark inputs:" in markdown
    assert "| tcp_ws | sample.raw | 16000 | 1 | pcm_s16le | 20 | 1000 | 100 | True |" in markdown
    assert "| raw_uds | sample.raw | 16000 | 1 | pcm_s16le | 20 | 1000 | 100 | True |" in markdown
    assert "Transport diagnostics:" in markdown
    assert "| raw_uds | 2 | raw_uds_invalid_json=2 | 1 | late_partial=1 |" in markdown
    assert "- missing transport benchmark: uds_ws" in markdown
    assert "Raw UDS recommendation gate: blocked" in markdown
    assert "Raw UDS first-interim p95 win over UDS WebSocket: missing" in markdown
    assert "Raw UDS gate blockers:" in markdown
    assert "- missing_transport:uds_ws" in markdown
    assert "- missing_raw_uds_latency_delta" in markdown


def test_main_writes_markdown_summary(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    markdown_path = tmp_path / "comparison.md"

    assert compare_module.main(["--markdown-output", str(markdown_path), str(tcp), str(uds), str(raw)]) == 0

    markdown = markdown_path.read_text(encoding="utf8")
    assert "Recommendation: Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype." in markdown
    assert "Raw UDS recommendation gate: passed" in markdown
    assert "P95 metric leaders:" in markdown
    assert "| time_to_first_interim_ms | raw_uds |" in markdown
    assert "CPU utilization coverage:" in markdown
    assert "- Complete: True" in markdown
    assert "- Available transports: raw_uds,tcp_ws,uds_ws" in markdown
    assert "- Missing CPU samples: missing" in markdown
    assert "- Missing required transports: missing" in markdown
    assert "Run count coverage:" in markdown
    assert "- Complete: True" in markdown
    assert "- Minimum observed runs: 3" in markdown
    assert "- Recorded runs: raw_uds=3,tcp_ws=3,uds_ws=3" in markdown
    assert "| raw_uds | missing | /tmp/stt.sock | uint8_type_uint32_len_le | 5 | JSON_CONTROL,AUDIO_PCM16,JSON_EVENT,ERROR,PING,PONG | start,audio,transcript,finalize,cancel,close | bad_frame_type,malformed_json_control,oversized_payload | True |" in markdown
    assert "Minimum required win: 5 ms" in markdown


def test_main_writes_compact_raw_uds_decision_output(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["diagnostics"] = {"warning_codes": {"late_partial": 1}}
    raw.write_text(json.dumps(raw_payload), encoding="utf8")
    decision_path = tmp_path / "decision.json"

    assert compare_module.main(["--decision-output", str(decision_path), str(tcp), str(uds), str(raw)]) == 0

    decision = json.loads(decision_path.read_text(encoding="utf8"))
    assert decision == {
        "kind": "local-stt-v1-raw-uds-decision",
        "status": "recommended",
        "reason": "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype.",
        "next_action": "Proceed with the next raw UDS adapter prototype.",
        "gate_passed": True,
        "gate_blockers": [],
        "required_first_interim_p95_win_ms": 5.0,
        "observed_first_interim_p95_win_ms": 5.0,
        "observed_final_after_finalize_p95_delta_ms": 0.0,
        "required_artifact_snapshot": {
            "raw_uds": {
                "artifact": str(raw),
                "artifact_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                "artifact_size_bytes": raw.stat().st_size,
            },
            "tcp_ws": {
                "artifact": str(tcp),
                "artifact_sha256": hashlib.sha256(tcp.read_bytes()).hexdigest(),
                "artifact_size_bytes": tcp.stat().st_size,
            },
            "uds_ws": {
                "artifact": str(uds),
                "artifact_sha256": hashlib.sha256(uds.read_bytes()).hexdigest(),
                "artifact_size_bytes": uds.stat().st_size,
            },
        },
        "required_target_snapshot": {
            "raw_uds": {
                "error_handling": ["bad_frame_type", "malformed_json_control", "oversized_payload"],
                "frame_format": "uint8_type_uint32_len_le",
                "frame_header_bytes": 5,
                "frame_type_codes": {
                    "AUDIO_PCM16": 2,
                    "ERROR": 4,
                    "JSON_CONTROL": 1,
                    "JSON_EVENT": 3,
                    "PING": 5,
                    "PONG": 6,
                },
                "frame_types": ["JSON_CONTROL", "AUDIO_PCM16", "JSON_EVENT", "ERROR", "PING", "PONG"],
                "lifecycle": ["start", "audio", "transcript", "finalize", "cancel", "close"],
                "per_frame_overhead_bytes": 5,
                "shared_stream_runtime": True,
                "uds_path": "/tmp/stt.sock",
                "url": None,
            },
            "tcp_ws": {
                "error_handling": None,
                "frame_format": None,
                "frame_header_bytes": None,
                "frame_type_codes": None,
                "frame_types": None,
                "lifecycle": None,
                "per_frame_overhead_bytes": None,
                "shared_stream_runtime": None,
                "uds_path": None,
                "url": "ws://localhost/v1/stt/stream",
            },
            "uds_ws": {
                "error_handling": None,
                "frame_format": None,
                "frame_header_bytes": None,
                "frame_type_codes": None,
                "frame_types": None,
                "lifecycle": None,
                "per_frame_overhead_bytes": None,
                "shared_stream_runtime": None,
                "uds_path": "/tmp/stt.sock",
                "url": "ws://localhost/v1/stt/stream",
            },
        },
        "required_diagnostic_snapshot": {
            "raw_uds": {
                "protocol_error_codes": {},
                "protocol_error_total": 0,
                "warning_codes": {"late_partial": 1},
                "warning_total": 1,
            },
            "tcp_ws": {
                "protocol_error_codes": {},
                "protocol_error_total": 0,
                "warning_codes": {},
                "warning_total": 0,
            },
            "uds_ws": {
                "protocol_error_codes": {},
                "protocol_error_total": 0,
                "warning_codes": {},
                "warning_total": 0,
            },
        },
        "required_benchmark_input_snapshot": {
            "raw_uds": {
                "audio": {
                    "channels": 1,
                    "duration_ms": 1000,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "sample_rate": 16000,
                    "source": "sample.raw",
                },
                "runs": 3,
                "service": {"backend": None, "model": None},
                "settings": {"partial_interval_ms": 100, "realtime_pace": True},
            },
            "tcp_ws": {
                "audio": {
                    "channels": 1,
                    "duration_ms": 1000,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "sample_rate": 16000,
                    "source": "sample.raw",
                },
                "runs": 3,
                "service": {"backend": None, "model": None},
                "settings": {"partial_interval_ms": 100, "realtime_pace": True},
            },
            "uds_ws": {
                "audio": {
                    "channels": 1,
                    "duration_ms": 1000,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "sample_rate": 16000,
                    "source": "sample.raw",
                },
                "runs": 3,
                "service": {"backend": None, "model": None},
                "settings": {"partial_interval_ms": 100, "realtime_pace": True},
            },
        },
        "required_metric_snapshot": {
            "raw_uds": {
                "asr_queue_delay_p95_ms": 5.0,
                "audio_send_queue_depth_p95_ms": 2.0,
                "cpu_utilization_percent": 12.5,
                "protocol_errors_p95": 0.0,
                "time_to_final_after_finalize_ms_p95": 25.0,
                "time_to_first_interim_ms_p95": 13.0,
            },
            "tcp_ws": {
                "asr_queue_delay_p95_ms": 5.0,
                "audio_send_queue_depth_p95_ms": 2.0,
                "cpu_utilization_percent": 12.5,
                "protocol_errors_p95": 0.0,
                "time_to_final_after_finalize_ms_p95": 25.0,
                "time_to_first_interim_ms_p95": 18.0,
            },
            "uds_ws": {
                "asr_queue_delay_p95_ms": 5.0,
                "audio_send_queue_depth_p95_ms": 2.0,
                "cpu_utilization_percent": 12.5,
                "protocol_errors_p95": 0.0,
                "time_to_final_after_finalize_ms_p95": 25.0,
                "time_to_first_interim_ms_p95": 18.0,
            },
        },
        "raw_uds_vs_uds_ws_p95_deltas_ms": {
            "asr_queue_delay_p95_ms": 0.0,
            "audio_send_queue_depth_p95_ms": 0.0,
            "protocol_errors": 0.0,
            "time_to_final_after_finalize_ms": 0.0,
            "time_to_first_interim_ms": 5.0,
        },
        "raw_uds_leading_p95_metrics": ["time_to_first_interim_ms"],
    }


def test_format_markdown_summary_includes_benchmark_inputs_when_recorded(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)
    for path in (tcp, uds, raw):
        payload = json.loads(path.read_text(encoding="utf8"))
        payload["audio"] = {"source": "sample.raw", "sample_rate": 16000, "channels": 1, "format": "pcm_s16le", "frame_ms": 20, "duration_ms": 1000}
        payload["settings"] = {"partial_interval_ms": 100, "realtime_pace": True}
        path.write_text(json.dumps(payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    markdown = compare_module.format_markdown_summary(comparison)

    assert "Benchmark inputs:" in markdown
    assert "| tcp_ws | sample.raw | 16000 | 1 | pcm_s16le | 20 | 1000 | 100 | True |" in markdown
    assert "| uds_ws | sample.raw | 16000 | 1 | pcm_s16le | 20 | 1000 | 100 | True |" in markdown
    assert "| raw_uds | sample.raw | 16000 | 1 | pcm_s16le | 20 | 1000 | 100 | True |" in markdown
