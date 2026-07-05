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


def write_artifact(
    path: Path,
    transport: str,
    first_interim_p95: float,
    *,
    final_after_finalize_p95: float = 25.0,
    cpu_utilization_percent: float | None = 12.5,
    runs: int | None = 3,
) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "local-stt-v1-latency-benchmark",
                "target": {"transport": transport, "url": "ws://localhost/v1/stt/stream", "uds_path": "/tmp/stt.sock" if transport != "tcp_ws" else None},
                "environment": (
                    {"cpu_utilization_percent": cpu_utilization_percent}
                    if cpu_utilization_percent is not None
                    else {}
                ),
                **({"runs": runs} if runs is not None else {}),
                "summary": {
                    "time_to_first_interim_ms": {"p50": first_interim_p95 - 1, "p95": first_interim_p95, "p99": first_interim_p95 + 1},
                    "time_to_final_after_finalize_ms": {
                        "p50": final_after_finalize_p95 - 5.0,
                        "p95": final_after_finalize_p95,
                        "p99": final_after_finalize_p95 + 5.0,
                    },
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
    assert compare_module.comparison_has_blocking_gaps(comparison) is True


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
        cpu_utilization_percent=13.0,
    )
    raw = write_artifact(
        tmp_path / "raw.json",
        "raw_uds",
        12.5,
        final_after_finalize_p95=27.0,
        cpu_utilization_percent=11.0,
    )

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["missing_transports"] == []
    assert comparison["fastest_time_to_first_interim_p95_transport"] == "raw_uds"
    assert comparison["fastest_time_to_final_after_finalize_p95_transport"] == "uds_ws"
    assert comparison["lowest_cpu_utilization_percent_transport"] == "raw_uds"
    assert comparison["raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms"] == 3.5
    assert comparison["raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms"] == -3.0
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is True
    assert comparison["recommendation"] == "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms."
    assert comparison["transports"]["raw_uds"]["metrics_p95"] == {
        "time_to_first_interim_ms": 12.5,
        "time_to_final_after_finalize_ms": 27.0,
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
        "p50": 22.0,
        "p95": 27.0,
        "p99": 32.0,
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
    assert comparison["all_present_transports_protocol_error_free"] is True
    assert comparison["recommendation"] == "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def test_compare_artifacts_flags_protocol_errors_in_present_transport(tmp_path: Path) -> None:
    tcp = write_artifact(tmp_path / "tcp.json", "tcp_ws", 18.0)
    uds = write_artifact(tmp_path / "uds.json", "uds_ws", 18.0)
    raw = write_artifact(tmp_path / "raw.json", "raw_uds", 12.0)
    raw_payload = json.loads(raw.read_text(encoding="utf8"))
    raw_payload["summary"]["protocol_errors"]["p95"] = 1.0
    raw.write_text(json.dumps(raw_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts([tcp, uds, raw])

    assert comparison["all_present_transports_protocol_error_free"] is False
    assert comparison["blocking_gaps"] == ["raw_uds protocol_errors p95 is 1.0"]
    assert comparison["transports"]["tcp_ws"]["protocol_error_free"] is True
    assert comparison["transports"]["raw_uds"]["protocol_error_free"] is False
    assert comparison["raw_uds_should_remain_experimental"] is True
    assert comparison["recommendation"] == (
        "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    )


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
