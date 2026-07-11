from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


REQUIRED_TRANSPORTS = ("tcp_ws", "uds_ws", "raw_uds")
DEFAULT_RAW_UDS_MIN_WIN_MS = 5.0
KEY_METRICS = (
    "time_to_first_interim_ms",
    "time_to_final_after_finalize_ms",
    "audio_send_queue_depth_p95_ms",
    "asr_queue_delay_p95_ms",
    "protocol_errors",
)
METRIC_ALIASES = {
    # Issue #88 names these acceptance metrics without the historical audio_/ms
    # suffixes; accept both artifact spellings while keeping the comparison schema stable.
    "audio_send_queue_depth_p95_ms": ("send_queue_depth_p95",),
    "asr_queue_delay_p95_ms": ("asr_queue_delay_p95",),
}

PERCENTILES = ("p50", "p95", "p99")
REQUIRED_PERCENTILES_BY_METRIC = {
    "time_to_first_interim_ms": PERCENTILES,
    "time_to_final_after_finalize_ms": PERCENTILES,
    "audio_send_queue_depth_p95_ms": ("p95",),
    "asr_queue_delay_p95_ms": ("p95",),
    "protocol_errors": PERCENTILES,
}
REQUIRED_TARGET_FIELDS_BY_TRANSPORT = {
    "tcp_ws": ("url",),
    "uds_ws": ("url", "uds_path"),
    "raw_uds": ("uds_path",),
}
RAW_UDS_FRAME_FORMAT = "uint8_type_uint32_len_le"
RAW_UDS_FRAME_HEADER_BYTES = 5
RAW_UDS_REQUIRED_FRAME_TYPES = (
    "JSON_CONTROL",
    "AUDIO_PCM16",
    "JSON_EVENT",
    "ERROR",
    "PING",
    "PONG",
)
RAW_UDS_REQUIRED_FRAME_TYPE_CODES = {
    "JSON_CONTROL": 0x01,
    "AUDIO_PCM16": 0x02,
    "JSON_EVENT": 0x03,
    "ERROR": 0x04,
    "PING": 0x05,
    "PONG": 0x06,
}
RAW_UDS_REQUIRED_LIFECYCLE = ("start", "audio", "transcript", "finalize", "cancel", "close")
RAW_UDS_LIFECYCLE_ORDER = {
    event: position for position, event in enumerate(RAW_UDS_REQUIRED_LIFECYCLE)
}
RAW_UDS_REQUIRED_ERROR_HANDLING = (
    "bad_frame_type",
    "malformed_json_control",
    "oversized_payload",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 transport benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown summary output path")
    parser.add_argument(
        "--require-raw-uds-recommendation",
        action="store_true",
        help="Exit non-zero unless raw UDS clears the recommendation gate",
    )
    parser.add_argument(
        "--min-runs",
        type=int,
        help="Require each transport artifact to record at least this many benchmark runs",
    )
    parser.add_argument(
        "--raw-uds-min-win-ms",
        type=float,
        default=DEFAULT_RAW_UDS_MIN_WIN_MS,
        help="Minimum first-interim P95 win over UDS websocket before raw UDS can be recommended",
    )
    return parser.parse_args(argv)


def load_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf8"))
    if payload.get("kind") != "local-stt-v1-latency-benchmark":
        raise ValueError(f"{path} is not a Local STT v1 latency benchmark artifact")
    target = payload.get("target")
    if not isinstance(target, dict) or not isinstance(target.get("transport"), str):
        raise ValueError(f"{path} is missing target.transport")
    return payload


def artifact_provenance(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "artifact_sha256": hashlib.sha256(content).hexdigest(),
        "artifact_size_bytes": len(content),
    }


def _percentile(summary: dict[str, Any], metric: str, percentile: str) -> float | None:
    bucket = summary.get(metric)
    for alias in METRIC_ALIASES.get(metric, ()):
        if isinstance(bucket, dict):
            break
        bucket = summary.get(alias)
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(percentile)
    if value is None:
        return None
    return float(value)


def metric_percentiles(summary: dict[str, Any], metric: str) -> dict[str, float | None]:
    return {percentile: _percentile(summary, metric, percentile) for percentile in PERCENTILES}


def first_defined(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        return value


def nested_value(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def extract_cpu_utilization_percent(artifact: dict[str, Any]) -> float | None:
    environment = artifact.get("environment") if isinstance(artifact.get("environment"), dict) else {}
    metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
    system = artifact.get("system") if isinstance(artifact.get("system"), dict) else {}
    cpu = artifact.get("cpu") if isinstance(artifact.get("cpu"), dict) else {}
    value = first_defined(
        environment.get("cpu_utilization_percent"),
        environment.get("cpu_percent"),
        system.get("cpu_utilization_percent"),
        system.get("cpu_percent"),
        metrics.get("cpu_utilization_percent"),
        metrics.get("cpu_percent"),
        nested_value(metrics, "cpu", "utilization_percent"),
        nested_value(metrics, "cpu", "average_utilization_percent"),
        nested_value(metrics, "cpu", "percent"),
        nested_value(metrics, "cpu", "average_percent"),
        cpu.get("utilization_percent"),
        cpu.get("average_utilization_percent"),
        cpu.get("percent"),
        cpu.get("average_percent"),
    )
    return None if value is None else float(value)


def fastest_transport_by_metric(transports: dict[str, dict[str, Any]], metric: str) -> str | None:
    candidates: list[tuple[float, str]] = []
    for transport, payload in transports.items():
        value = payload.get("metrics_p95", {}).get(metric)
        if value is not None:
            candidates.append((float(value), transport))
    if not candidates:
        return None
    return min(candidates)[1]


def p95_metric_leaders(transports: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    return {metric: fastest_transport_by_metric(transports, metric) for metric in KEY_METRICS}


def classify_p95_delta(delta_ms: float | None) -> str:
    if delta_ms is None:
        return "missing"
    if delta_ms > 0:
        return "improved"
    if delta_ms < 0:
        return "regressed"
    return "matched"


def raw_uds_p95_comparison_summary(
    transports: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, float | str | None]]]:
    raw_uds = transports.get("raw_uds")
    summary: dict[str, dict[str, dict[str, float | str | None]]] = {}
    for baseline in ("tcp_ws", "uds_ws"):
        baseline_payload = transports.get(baseline)
        summary[baseline] = {}
        for metric in KEY_METRICS:
            baseline_value = None if baseline_payload is None else baseline_payload.get("metrics_p95", {}).get(metric)
            raw_value = None if raw_uds is None else raw_uds.get("metrics_p95", {}).get(metric)
            delta_ms = None
            if baseline_value is not None and raw_value is not None:
                delta_ms = round(float(baseline_value) - float(raw_value), 3)
            summary[baseline][metric] = {
                "baseline_p95": baseline_value,
                "raw_uds_p95": raw_value,
                "delta_ms": delta_ms,
                "status": classify_p95_delta(delta_ms),
            }
    return summary


def lowest_cpu_utilization_transport(transports: dict[str, dict[str, Any]]) -> str | None:
    candidates: list[tuple[float, str]] = []
    for transport, payload in transports.items():
        value = payload.get("cpu_utilization_percent")
        if value is not None:
            candidates.append((float(value), transport))
    if not candidates:
        return None
    return min(candidates)[1]


def missing_cpu_utilization_transports(transports: dict[str, dict[str, Any]]) -> list[str]:
    return [
        transport
        for transport, payload in sorted(transports.items())
        if payload.get("cpu_utilization_percent") is None
    ]


def cpu_utilization_coverage(transports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = missing_cpu_utilization_transports(transports)
    available = sorted(transport for transport in transports if transport not in missing)
    return {
        "available_transports": available,
        "missing_transports": missing,
        "required_transports": list(REQUIRED_TRANSPORTS),
        "complete": not missing and all(transport in transports for transport in REQUIRED_TRANSPORTS),
    }


def run_count_coverage(transports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_counts = {
        transport: payload.get("runs")
        for transport, payload in sorted(transports.items())
        if isinstance(payload.get("runs"), int)
    }
    missing = sorted(transport for transport in transports if transport not in run_counts)
    return {
        "available_transports": sorted(run_counts),
        "missing_transports": missing,
        "required_transports": list(REQUIRED_TRANSPORTS),
        "run_counts": run_counts,
        "min_runs": min(run_counts.values()) if run_counts else None,
        "complete": not missing and all(transport in transports for transport in REQUIRED_TRANSPORTS),
    }


def run_count_gaps(transports: dict[str, dict[str, Any]], min_runs: int | None) -> list[str]:
    if min_runs is None:
        return []
    gaps: list[str] = []
    for transport, payload in sorted(transports.items()):
        runs = payload.get("runs")
        if not isinstance(runs, int):
            gaps.append(f"{transport} missing run count")
        elif runs < min_runs:
            gaps.append(f"{transport} has {runs} runs; requires at least {min_runs}")
    return gaps


def target_field_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    gaps: list[str] = []
    for transport, required_fields in REQUIRED_TARGET_FIELDS_BY_TRANSPORT.items():
        payload = transports.get(transport)
        if payload is None:
            continue
        for field in required_fields:
            if not payload.get(field):
                gaps.append(f"{transport} missing target.{field}")
    return gaps


def raw_uds_frame_contract_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    gaps: list[str] = []
    if raw_uds.get("frame_format") != RAW_UDS_FRAME_FORMAT:
        gaps.append(f"raw_uds missing target.frame_format={RAW_UDS_FRAME_FORMAT}")
    if raw_uds.get("frame_header_bytes") != RAW_UDS_FRAME_HEADER_BYTES:
        gaps.append(f"raw_uds missing target.frame_header_bytes={RAW_UDS_FRAME_HEADER_BYTES}")
    return gaps


def raw_uds_lifecycle_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    lifecycle = raw_uds.get("lifecycle")
    if not isinstance(lifecycle, list):
        return ["raw_uds missing target.lifecycle coverage"]

    missing = [event for event in RAW_UDS_REQUIRED_LIFECYCLE if event not in lifecycle]
    if missing:
        return [f"raw_uds missing lifecycle coverage: {','.join(missing)}"]
    ordered_events = [event for event in lifecycle if event in RAW_UDS_LIFECYCLE_ORDER]
    ordered_positions = [RAW_UDS_LIFECYCLE_ORDER[event] for event in ordered_events]
    if ordered_positions != sorted(ordered_positions):
        expected = ",".join(RAW_UDS_REQUIRED_LIFECYCLE)
        observed = ",".join(ordered_events)
        return [f"raw_uds lifecycle order mismatch: expected {expected}; got {observed}"]
    return []


def raw_uds_error_handling_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    error_handling = raw_uds.get("error_handling")
    if not isinstance(error_handling, list):
        return ["raw_uds missing target.error_handling coverage"]

    missing = [scenario for scenario in RAW_UDS_REQUIRED_ERROR_HANDLING if scenario not in error_handling]
    if missing:
        return [f"raw_uds missing protocol-error handling coverage: {','.join(missing)}"]
    return []


def raw_uds_runtime_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []
    if raw_uds.get("shared_stream_runtime") is True:
        return []
    return ["raw_uds missing shared stream runtime evidence"]


def parse_frame_type_code(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def raw_uds_frame_type_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    gaps: list[str] = []
    frame_types = raw_uds.get("frame_types")
    if not isinstance(frame_types, list):
        gaps.append("raw_uds missing target.frame_types coverage")
    else:
        missing = [frame_type for frame_type in RAW_UDS_REQUIRED_FRAME_TYPES if frame_type not in frame_types]
        if missing:
            gaps.append(f"raw_uds missing frame type coverage: {','.join(missing)}")

    frame_type_codes = raw_uds.get("frame_type_codes")
    if not isinstance(frame_type_codes, dict):
        gaps.append("raw_uds missing target.frame_type_codes coverage")
        return gaps

    missing_codes = []
    wrong_codes = []
    for frame_type, expected_code in RAW_UDS_REQUIRED_FRAME_TYPE_CODES.items():
        observed_code = frame_type_codes.get(frame_type)
        if observed_code is None:
            missing_codes.append(frame_type)
            continue
        observed_int = parse_frame_type_code(observed_code)
        if observed_int != expected_code:
            observed_display = "invalid" if observed_int is None else f"0x{observed_int:02x}"
            wrong_codes.append(f"{frame_type}={observed_display},expected=0x{expected_code:02x}")

    if missing_codes:
        gaps.append(f"raw_uds missing frame type code coverage: {','.join(missing_codes)}")
    if wrong_codes:
        gaps.append(f"raw_uds frame type code mismatch: {','.join(wrong_codes)}")
    return gaps


def benchmark_input_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    comparable_fields = (
        ("audio", "source"),
        ("audio", "sample_rate"),
        ("audio", "channels"),
        ("audio", "format"),
        ("audio", "frame_ms"),
        ("audio", "duration_ms"),
        ("settings", "partial_interval_ms"),
        ("settings", "realtime_pace"),
    )
    values_by_field: dict[str, dict[str, Any]] = {}
    for section, field in comparable_fields:
        key = f"{section}.{field}"
        values_by_field[key] = {
            transport: payload.get(section, {}).get(field)
            for transport, payload in sorted(transports.items())
        }

    gaps: list[str] = []
    for field, values in values_by_field.items():
        missing = [transport for transport, value in values.items() if value is None or value == ""]
        if missing:
            gaps.append(f"benchmark input missing for {field}: {','.join(missing)}")
            continue
        if len(set(values.values())) > 1:
            rendered = ", ".join(f"{transport}={value!r}" for transport, value in values.items())
            gaps.append(f"benchmark input mismatch for {field}: {rendered}")
    return gaps


def metric_delta_ms(
    transports: dict[str, dict[str, Any]],
    *,
    baseline_transport: str,
    candidate_transport: str,
    metric: str,
) -> float | None:
    baseline_p95 = transports.get(baseline_transport, {}).get("metrics_p95", {}).get(metric)
    candidate_p95 = transports.get(candidate_transport, {}).get("metrics_p95", {}).get(metric)
    if baseline_p95 is None or candidate_p95 is None:
        return None
    return round(float(baseline_p95) - float(candidate_p95), 1)


def raw_uds_vs_uds_p95_deltas(transports: dict[str, dict[str, Any]]) -> dict[str, float | None]:
    return {
        metric: metric_delta_ms(
            transports,
            baseline_transport="uds_ws",
            candidate_transport="raw_uds",
            metric=metric,
        )
        for metric in KEY_METRICS
    }


def pairwise_p95_delta_matrix(transports: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, float | None]]]:
    return {
        metric: {
            baseline: {
                candidate: None
                if baseline == candidate
                else metric_delta_ms(
                    transports,
                    baseline_transport=baseline,
                    candidate_transport=candidate,
                    metric=metric,
                )
                for candidate in REQUIRED_TRANSPORTS
            }
            for baseline in REQUIRED_TRANSPORTS
        }
        for metric in KEY_METRICS
    }


def protocol_error_free(metrics: dict[str, dict[str, float | None]]) -> bool:
    protocol_errors = metrics.get("protocol_errors", {})
    return all(protocol_errors.get(percentile) == 0.0 for percentile in PERCENTILES)


def missing_required_metrics(metrics: dict[str, dict[str, float | None]]) -> list[str]:
    missing: list[str] = []
    for metric in KEY_METRICS:
        required_percentiles = REQUIRED_PERCENTILES_BY_METRIC[metric]
        missing_percentiles = [
            percentile
            for percentile in required_percentiles
            if metrics[metric].get(percentile) is None
        ]
        if missing_percentiles:
            missing.append(f"{metric}:{','.join(missing_percentiles)}")
    return missing


def recommendation_text(
    *,
    missing: list[str],
    unexpected: list[str],
    raw_vs_uds_delta_ms: float | None,
    raw_uds_min_win_ms: float,
    raw_uds_experimental: bool,
    all_present_transports_protocol_error_free: bool,
    missing_metrics: dict[str, list[str]],
    run_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    runtime_gaps: list[str],
    input_gaps: list[str],
) -> str:
    if missing:
        return "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."
    if unexpected:
        return "Remove unexpected transport benchmark artifacts before recommending raw UDS."
    if missing_metrics:
        return "Re-run transport benchmarks with the full required metric set before recommending raw UDS."
    if run_gaps:
        return "Re-run transport benchmarks with enough repeated runs before recommending raw UDS."
    if target_gaps:
        return "Re-run transport benchmarks with explicit endpoint targets before recommending raw UDS."
    if frame_contract_gaps:
        return "Re-run raw UDS benchmarks with the required length-prefixed frame contract before recommending raw UDS."
    if frame_type_gaps:
        return "Re-run raw UDS benchmarks with complete frame type coverage before recommending raw UDS."
    if lifecycle_gaps:
        return "Re-run raw UDS benchmarks with full Local STT v1 lifecycle coverage before recommending raw UDS."
    if error_handling_gaps:
        return "Re-run raw UDS benchmarks with protocol-error handling coverage before recommending raw UDS."
    if runtime_gaps:
        return "Re-run raw UDS benchmarks with shared stream runtime evidence before recommending raw UDS."
    if input_gaps:
        return "Re-run transport benchmarks with matching audio and pacing settings before recommending raw UDS."
    if not all_present_transports_protocol_error_free:
        return "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    if raw_vs_uds_delta_ms is None:
        return "Raw UDS and UDS websocket first-interim P95 metrics were unavailable; keep raw UDS experimental."
    if raw_uds_experimental:
        return f"Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least {raw_uds_min_win_ms:g} ms."
    return "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def blocking_gap_reasons(
    *,
    missing: list[str],
    unexpected: list[str],
    missing_metrics: dict[str, list[str]],
    run_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    runtime_gaps: list[str],
    input_gaps: list[str],
    transports: dict[str, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(f"missing transport benchmark: {transport}" for transport in missing)
    reasons.extend(f"unexpected transport benchmark: {transport}" for transport in unexpected)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        reasons.extend(f"{transport} missing metric percentile: {metric_gap}" for metric_gap in metric_gaps)
    reasons.extend(run_gaps)
    reasons.extend(target_gaps)
    reasons.extend(frame_contract_gaps)
    reasons.extend(frame_type_gaps)
    reasons.extend(lifecycle_gaps)
    reasons.extend(error_handling_gaps)
    reasons.extend(runtime_gaps)
    reasons.extend(input_gaps)
    for transport, payload in sorted(transports.items()):
        if not payload["protocol_error_free"]:
            protocol_errors = payload.get("metrics", {}).get("protocol_errors", {})
            recorded = ", ".join(
                f"{percentile}={protocol_errors.get(percentile)}" for percentile in PERCENTILES
            )
            reasons.append(f"{transport} protocol_errors must be zero at p50/p95/p99; got {recorded}")
    return reasons


def raw_uds_recommendation_gate(
    *,
    missing: list[str],
    unexpected: list[str],
    missing_metrics: dict[str, list[str]],
    run_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    runtime_gaps: list[str],
    input_gaps: list[str],
    all_present_transports_protocol_error_free: bool,
    raw_vs_uds_delta_ms: float | None,
    raw_uds_min_win_ms: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    blockers.extend(f"missing_transport:{transport}" for transport in missing)
    blockers.extend(f"unexpected_transport:{transport}" for transport in unexpected)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        blockers.extend(f"missing_metric:{transport}:{metric_gap}" for metric_gap in metric_gaps)
    blockers.extend(f"run_count:{gap}" for gap in run_gaps)
    blockers.extend(f"target:{gap}" for gap in target_gaps)
    blockers.extend(f"frame_contract:{gap}" for gap in frame_contract_gaps)
    blockers.extend(f"frame_type:{gap}" for gap in frame_type_gaps)
    blockers.extend(f"lifecycle:{gap}" for gap in lifecycle_gaps)
    blockers.extend(f"error_handling:{gap}" for gap in error_handling_gaps)
    blockers.extend(f"runtime:{gap}" for gap in runtime_gaps)
    blockers.extend(f"benchmark_input:{gap}" for gap in input_gaps)
    if not all_present_transports_protocol_error_free:
        blockers.append("protocol_errors")
    if raw_vs_uds_delta_ms is None:
        blockers.append("missing_raw_uds_latency_delta")
    elif raw_vs_uds_delta_ms < raw_uds_min_win_ms:
        blockers.append("insufficient_raw_uds_latency_win")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "raw_uds_min_win_ms": raw_uds_min_win_ms,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
    }


def compare_artifacts(
    paths: list[Path],
    *,
    min_runs: int | None = None,
    raw_uds_min_win_ms: float = DEFAULT_RAW_UDS_MIN_WIN_MS,
) -> dict[str, Any]:
    if min_runs is not None and min_runs <= 0:
        raise ValueError("min_runs must be positive")
    if raw_uds_min_win_ms <= 0:
        raise ValueError("raw_uds_min_win_ms must be positive")
    artifacts = [load_artifact(path) for path in paths]
    by_transport: dict[str, dict[str, Any]] = {}
    for path, artifact in zip(paths, artifacts, strict=True):
        transport = artifact["target"]["transport"]
        if transport in by_transport:
            raise ValueError(f"duplicate benchmark artifact for transport {transport}")
        summary = artifact.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{path} is missing summary")
        target_contract = artifact.get("target_contract") if isinstance(artifact.get("target_contract"), dict) else {}
        target_lifecycle = artifact["target"].get("lifecycle") or target_contract.get("lifecycle")
        target_frame_types = artifact["target"].get("frame_types") or target_contract.get("frame_types")
        target_frame_type_codes = artifact["target"].get("frame_type_codes") or target_contract.get("frame_type_codes")
        target_error_handling = artifact["target"].get("error_handling") or target_contract.get("error_handling")
        shared_stream_runtime = artifact["target"].get("shared_stream_runtime")
        if shared_stream_runtime is None:
            shared_stream_runtime = target_contract.get("shared_stream_runtime")
        metrics = {metric: metric_percentiles(summary, metric) for metric in KEY_METRICS}
        metrics_p95 = {metric: metrics[metric]["p95"] for metric in KEY_METRICS}
        missing_metrics = missing_required_metrics(metrics)
        by_transport[transport] = {
            "artifact": str(path),
            **artifact_provenance(path),
            "url": artifact["target"].get("url"),
            "uds_path": artifact["target"].get("uds_path"),
            "frame_format": artifact["target"].get("frame_format") or target_contract.get("frame_format"),
            "frame_header_bytes": artifact["target"].get("frame_header_bytes") or target_contract.get("frame_header_bytes"),
            "frame_types": target_frame_types,
            "frame_type_codes": target_frame_type_codes,
            "lifecycle": target_lifecycle,
            "error_handling": target_error_handling,
            "shared_stream_runtime": shared_stream_runtime,
            "audio": artifact.get("audio") if isinstance(artifact.get("audio"), dict) else {},
            "settings": artifact.get("settings") if isinstance(artifact.get("settings"), dict) else {},
            "runs": artifact.get("runs"),
            "metrics": metrics,
            "metrics_p95": metrics_p95,
            "missing_p95_metrics": missing_metrics,
            "protocol_error_free": protocol_error_free(metrics),
            "cpu_utilization_percent": extract_cpu_utilization_percent(artifact),
        }

    missing = [transport for transport in REQUIRED_TRANSPORTS if transport not in by_transport]
    unexpected = sorted(transport for transport in by_transport if transport not in REQUIRED_TRANSPORTS)
    missing_metrics_by_transport = {
        transport: payload["missing_p95_metrics"]
        for transport, payload in by_transport.items()
        if payload["missing_p95_metrics"]
    }
    raw_vs_uds_deltas = raw_uds_vs_uds_p95_deltas(by_transport)
    p95_delta_matrix = pairwise_p95_delta_matrix(by_transport)
    raw_uds_comparison_summary = raw_uds_p95_comparison_summary(by_transport)
    raw_vs_uds_delta_ms = raw_vs_uds_deltas["time_to_first_interim_ms"]
    raw_vs_uds_final_after_finalize_delta_ms = raw_vs_uds_deltas["time_to_final_after_finalize_ms"]
    raw_uds_latency_experimental = raw_vs_uds_delta_ms is None or raw_vs_uds_delta_ms < raw_uds_min_win_ms
    fastest_first_interim_transport = fastest_transport_by_metric(by_transport, "time_to_first_interim_ms")
    fastest_final_after_finalize_transport = fastest_transport_by_metric(
        by_transport, "time_to_final_after_finalize_ms"
    )
    metric_leaders = p95_metric_leaders(by_transport)
    lowest_cpu_transport = lowest_cpu_utilization_transport(by_transport)
    missing_cpu_utilization = missing_cpu_utilization_transports(by_transport)
    cpu_coverage = cpu_utilization_coverage(by_transport)
    run_coverage = run_count_coverage(by_transport)
    run_gaps = run_count_gaps(by_transport, min_runs)
    target_gaps = target_field_gaps(by_transport)
    frame_contract_gaps = raw_uds_frame_contract_gaps(by_transport)
    frame_type_gaps = raw_uds_frame_type_gaps(by_transport)
    lifecycle_gaps = raw_uds_lifecycle_gaps(by_transport)
    error_handling_gaps = raw_uds_error_handling_gaps(by_transport)
    runtime_gaps = raw_uds_runtime_gaps(by_transport)
    input_gaps = benchmark_input_gaps(by_transport)

    all_present_transports_protocol_error_free = all(
        transport["protocol_error_free"] for transport in by_transport.values()
    )
    recommendation_gate = raw_uds_recommendation_gate(
        missing=missing,
        unexpected=unexpected,
        missing_metrics=missing_metrics_by_transport,
        run_gaps=run_gaps,
        target_gaps=target_gaps,
        frame_contract_gaps=frame_contract_gaps,
        frame_type_gaps=frame_type_gaps,
        lifecycle_gaps=lifecycle_gaps,
        error_handling_gaps=error_handling_gaps,
        runtime_gaps=runtime_gaps,
        input_gaps=input_gaps,
        all_present_transports_protocol_error_free=all_present_transports_protocol_error_free,
        raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
        raw_uds_min_win_ms=raw_uds_min_win_ms,
    )
    raw_uds_experimental = bool(raw_uds_latency_experimental or not recommendation_gate["passed"])

    return {
        "kind": "local-stt-v1-transport-comparison",
        "required_transports": list(REQUIRED_TRANSPORTS),
        "missing_transports": missing,
        "unexpected_transports": unexpected,
        "transports": by_transport,
        "fastest_time_to_first_interim_p95_transport": fastest_first_interim_transport,
        "fastest_time_to_final_after_finalize_p95_transport": fastest_final_after_finalize_transport,
        "p95_metric_leaders": metric_leaders,
        "lowest_cpu_utilization_percent_transport": lowest_cpu_transport,
        "missing_cpu_utilization_transports": missing_cpu_utilization,
        "cpu_utilization_coverage": cpu_coverage,
        "run_count_coverage": run_coverage,
        "minimum_required_runs": min_runs,
        "run_count_gaps": run_gaps,
        "target_field_gaps": target_gaps,
        "raw_uds_frame_contract_gaps": frame_contract_gaps,
        "raw_uds_frame_type_gaps": frame_type_gaps,
        "raw_uds_lifecycle_gaps": lifecycle_gaps,
        "raw_uds_error_handling_gaps": error_handling_gaps,
        "raw_uds_runtime_gaps": runtime_gaps,
        "benchmark_input_gaps": input_gaps,
        "raw_uds_min_win_ms": raw_uds_min_win_ms,
        "raw_uds_recommendation_gate": recommendation_gate,
        "raw_uds_vs_uds_ws_p95_deltas_ms": raw_vs_uds_deltas,
        "raw_uds_p95_comparison_summary": raw_uds_comparison_summary,
        "pairwise_p95_deltas_ms": p95_delta_matrix,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms": raw_vs_uds_final_after_finalize_delta_ms,
        "raw_uds_should_remain_experimental": raw_uds_experimental,
        "all_present_transports_protocol_error_free": all_present_transports_protocol_error_free,
        "missing_p95_metrics_by_transport": missing_metrics_by_transport,
        "blocking_gaps": blocking_gap_reasons(
            missing=missing,
            unexpected=unexpected,
            missing_metrics=missing_metrics_by_transport,
            run_gaps=run_gaps,
            target_gaps=target_gaps,
            frame_contract_gaps=frame_contract_gaps,
            frame_type_gaps=frame_type_gaps,
            lifecycle_gaps=lifecycle_gaps,
            error_handling_gaps=error_handling_gaps,
            runtime_gaps=runtime_gaps,
            input_gaps=input_gaps,
            transports=by_transport,
        ),
        "recommendation": recommendation_text(
            missing=missing,
            unexpected=unexpected,
            raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
            raw_uds_min_win_ms=raw_uds_min_win_ms,
            raw_uds_experimental=raw_uds_experimental,
            all_present_transports_protocol_error_free=all_present_transports_protocol_error_free,
            missing_metrics=missing_metrics_by_transport,
            run_gaps=run_gaps,
            target_gaps=target_gaps,
            frame_contract_gaps=frame_contract_gaps,
            frame_type_gaps=frame_type_gaps,
            lifecycle_gaps=lifecycle_gaps,
            error_handling_gaps=error_handling_gaps,
            runtime_gaps=runtime_gaps,
            input_gaps=input_gaps,
        ),
    }


def comparison_has_blocking_gaps(
    comparison: dict[str, Any], *, require_raw_uds_recommendation: bool = False
) -> bool:
    return bool(
        comparison["missing_transports"]
        or comparison["unexpected_transports"]
        or comparison["missing_p95_metrics_by_transport"]
        or comparison.get("run_count_gaps")
        or comparison.get("target_field_gaps")
        or comparison.get("raw_uds_frame_contract_gaps")
        or comparison.get("raw_uds_frame_type_gaps")
        or comparison.get("raw_uds_lifecycle_gaps")
        or comparison.get("raw_uds_error_handling_gaps")
        or comparison.get("raw_uds_runtime_gaps")
        or comparison.get("benchmark_input_gaps")
        or not comparison["all_present_transports_protocol_error_free"]
        or (require_raw_uds_recommendation and comparison["raw_uds_should_remain_experimental"])
    )


def _format_optional_ms(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"{value:.1f} ms"


def _format_optional_metric_value(metric: str, value: float | None) -> str:
    if metric == "protocol_errors":
        if value is None:
            return "missing"
        return f"{value:g}"
    return _format_optional_ms(value)


def _format_optional_value(value: Any) -> str:
    if value is None or value == "":
        return "missing"
    if isinstance(value, list):
        if not value:
            return "missing"
        return ",".join(str(item) for item in value)
    return str(value)


def _format_pairwise_delta(
    candidates: dict[str, float | None], *, baseline: str, candidate: str
) -> str:
    if baseline == candidate:
        return "baseline"
    return _format_optional_ms(candidates.get(candidate))


def format_markdown_summary(comparison: dict[str, Any]) -> str:
    lines = [
        "# Local STT v1 Transport Comparison",
        "",
        f"Recommendation: {comparison['recommendation']}",
        "",
        "| Transport | First interim p95 | Final-after-finalize p95 | Protocol errors p95 | CPU utilization | Runs |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for transport in comparison["required_transports"]:
        payload = comparison["transports"].get(transport)
        if payload is None:
            lines.append(f"| {transport} | missing | missing | missing | missing | missing |")
            continue
        metrics = payload["metrics_p95"]
        cpu_value = payload.get("cpu_utilization_percent")
        cpu = "missing" if cpu_value is None else f"{float(cpu_value):.1f}%"
        runs = payload.get("runs")
        lines.append(
            "| "
            + " | ".join(
                [
                    transport,
                    _format_optional_ms(metrics.get("time_to_first_interim_ms")),
                    _format_optional_ms(metrics.get("time_to_final_after_finalize_ms")),
                    str(metrics.get("protocol_errors") if metrics.get("protocol_errors") is not None else "missing"),
                    cpu,
                    str(runs if runs is not None else "missing"),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "Transport targets:",
            "| Transport | URL | UDS path | Raw frame format | Header bytes | Frame types | Lifecycle | Error handling | Shared runtime |",
            "| --- | --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for transport in comparison["required_transports"]:
        payload = comparison["transports"].get(transport)
        if payload is None:
            lines.append(f"| {transport} | missing | missing | missing | missing | missing | missing | missing | missing |")
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    transport,
                    _format_optional_value(payload.get("url")),
                    _format_optional_value(payload.get("uds_path")),
                    _format_optional_value(payload.get("frame_format")),
                    _format_optional_value(payload.get("frame_header_bytes")),
                    _format_optional_value(payload.get("frame_types")),
                    _format_optional_value(payload.get("lifecycle")),
                    _format_optional_value(payload.get("error_handling")),
                    _format_optional_value(payload.get("shared_stream_runtime")),
                ]
            )
            + " |"
        )

    has_benchmark_inputs = any(
        payload.get("audio") or payload.get("settings")
        for payload in comparison["transports"].values()
    )
    if has_benchmark_inputs:
        lines.extend(
            [
                "",
                "Benchmark inputs:",
                "| Transport | Source | Sample rate | Channels | Format | Frame ms | Duration ms | Partial interval ms | Realtime pace |",
                "| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for transport in comparison["required_transports"]:
            payload = comparison["transports"].get(transport)
            if payload is None:
                lines.append(f"| {transport} | missing | missing | missing | missing | missing | missing | missing | missing |")
                continue
            audio = payload.get("audio") or {}
            settings = payload.get("settings") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        transport,
                        _format_optional_value(audio.get("source")),
                        _format_optional_value(audio.get("sample_rate")),
                        _format_optional_value(audio.get("channels")),
                        _format_optional_value(audio.get("format")),
                        _format_optional_value(audio.get("frame_ms")),
                        _format_optional_value(audio.get("duration_ms")),
                        _format_optional_value(settings.get("partial_interval_ms")),
                        _format_optional_value(settings.get("realtime_pace")),
                    ]
                )
                + " |"
            )

    metric_leaders = comparison.get("p95_metric_leaders", {})
    if metric_leaders:
        lines.extend(
            [
                "",
                "P95 metric leaders:",
                "| Metric | Best transport |",
                "| --- | --- |",
            ]
        )
        for metric in KEY_METRICS:
            lines.append(f"| {metric} | {_format_optional_value(metric_leaders.get(metric))} |")

    cpu_coverage = comparison.get("cpu_utilization_coverage", {})
    if cpu_coverage:
        available = cpu_coverage.get("available_transports", [])
        missing = cpu_coverage.get("missing_transports", [])
        lines.extend(
            [
                "",
                "CPU utilization coverage:",
                f"- Complete: {_format_optional_value(cpu_coverage.get('complete'))}",
                f"- Available transports: {_format_optional_value(available)}",
                f"- Missing CPU samples: {_format_optional_value(missing)}",
                f"- Missing required transports: {_format_optional_value(comparison.get('missing_transports', []))}",
            ]
        )

    raw_uds_summary = comparison.get("raw_uds_p95_comparison_summary", {})
    if raw_uds_summary:
        labels = {"tcp_ws": "TCP WebSocket", "uds_ws": "UDS WebSocket"}
        lines.extend(
            [
                "",
                "Raw UDS p95 comparison:",
                "| Baseline | Metric | Baseline p95 | Raw UDS p95 | Delta | Status |",
                "| --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for baseline in ("tcp_ws", "uds_ws"):
            for metric in KEY_METRICS:
                payload = raw_uds_summary.get(baseline, {}).get(metric, {})
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            labels[baseline],
                            metric,
                            _format_optional_metric_value(metric, payload.get("baseline_p95")),
                            _format_optional_metric_value(metric, payload.get("raw_uds_p95")),
                            _format_optional_metric_value(metric, payload.get("delta_ms")),
                            _format_optional_value(payload.get("status")),
                        ]
                    )
                    + " |"
                )

    pairwise_deltas = comparison.get("pairwise_p95_deltas_ms", {}).get("time_to_first_interim_ms", {})
    if pairwise_deltas:
        lines.extend(
            [
                "",
                "First-interim p95 deltas:",
                "| Baseline | TCP WebSocket | UDS WebSocket | Raw UDS |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        labels = {"tcp_ws": "TCP WebSocket", "uds_ws": "UDS WebSocket", "raw_uds": "Raw UDS"}
        for baseline in comparison["required_transports"]:
            candidates = pairwise_deltas.get(baseline, {})
            lines.append(
                "| "
                + " | ".join(
                    [
                        labels[baseline],
                        _format_pairwise_delta(candidates, baseline=baseline, candidate="tcp_ws"),
                        _format_pairwise_delta(candidates, baseline=baseline, candidate="uds_ws"),
                        _format_pairwise_delta(candidates, baseline=baseline, candidate="raw_uds"),
                    ]
                )
                + " |"
            )

    blockers = comparison.get("blocking_gaps", [])
    if blockers:
        lines.extend(["", "Blocking gaps:"])
        lines.extend(f"- {blocker}" for blocker in blockers)

    gate = comparison["raw_uds_recommendation_gate"]
    lines.extend(
        [
            "",
            f"Raw UDS recommendation gate: {'passed' if gate['passed'] else 'blocked'}",
            f"Raw UDS first-interim p95 win over UDS WebSocket: {_format_optional_ms(gate['raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms'])}",
            f"Minimum required win: {gate['raw_uds_min_win_ms']:g} ms",
        ]
    )
    if gate["blockers"]:
        lines.extend(["", "Raw UDS gate blockers:"])
        lines.extend(f"- {blocker}" for blocker in gate["blockers"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(
        args.artifacts,
        min_runs=args.min_runs,
        raw_uds_min_win_ms=args.raw_uds_min_win_ms,
    )
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    if args.markdown_output is not None:
        args.markdown_output.write_text(format_markdown_summary(comparison), encoding="utf8")
    return 1 if comparison_has_blocking_gaps(
        comparison,
        require_raw_uds_recommendation=args.require_raw_uds_recommendation,
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
