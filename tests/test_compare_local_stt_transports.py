from __future__ import annotations

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


def write_artifact(path: Path, transport: str, first_interim_p95: float) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "local-stt-v1-latency-benchmark",
                "target": {"transport": transport, "url": "ws://localhost/v1/stt/stream", "uds_path": "/tmp/stt.sock" if transport != "tcp_ws" else None},
                "environment": {"cpu_utilization_percent": 12.5},
                "runs": 3,
                "summary": {
                    "time_to_first_interim_ms": {"p50": first_interim_p95 - 1, "p95": first_interim_p95, "p99": first_interim_p95 + 1},
                    "time_to_final_after_finalize_ms": {"p50": 20.0, "p95": 25.0, "p99": 30.0},
                    "audio_send_queue_depth_p95_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
                    "asr_queue_delay_p95_ms": {"p50": 4.0, "p95": 5.0, "p99": 6.0},
                    "protocol_errors": {"p50": 0.0, "p95": 0.0, "p99": 0.0},
                },
            }
        ),
        encoding="utf8",
    )
    return path


def test_compare_artifacts_requires_all_raw_uds_experiment_transports(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)

    comparison = compare_module.compare_artifacts([tcp, raw])

    assert comparison["missing_transports"] == ["uds_ws"]
    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] is None
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is True
    assert comparison["recommendation"] == "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."


def test_compare_artifacts_marks_raw_uds_experimental_under_five_ms_win(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 16.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.5)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_transports"] == []
    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 3.5
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is True
    assert comparison["recommendation"] == "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms."
    assert comparison["transports"]["raw_uds"]["metrics_p95"] == {
        "time_to_first_interim_ms": 12.5,
        "time_to_final_after_finalize_ms": 25.0,
        "audio_send_queue_depth_p95_ms": 2.0,
        "asr_queue_delay_p95_ms": 5.0,
        "protocol_errors": 0.0,
    }
    assert comparison["transports"]["raw_uds"]["metrics"]["time_to_first_interim_ms"] == {
        "p50": 11.5,
        "p95": 12.5,
        "p99": 13.5,
    }
    assert comparison["transports"]["raw_uds"]["metrics"]["time_to_final_after_finalize_ms"] == {
        "p50": 20.0,
        "p95": 25.0,
        "p99": 30.0,
    }


def test_compare_artifacts_allows_raw_uds_recommendation_at_five_ms_win(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 13.0)

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 5.0
    assert comparison["raw_uds_should_remain_experimental"] is False
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["recommendation"] == "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def test_compare_artifacts_flags_protocol_errors_in_present_transport(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["summary"]["protocol_errors"]["p95"] = 1.0
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, raw])

    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["transports"]["tcp_ws"]["protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is False

