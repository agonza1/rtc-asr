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
    "audio_send_queue_depth_p95_ms": ("send_queue_depth_p95", "send_queue_depth_p95_ms"),
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
RAW_UDS_PER_FRAME_OVERHEAD_BYTES = RAW_UDS_FRAME_HEADER_BYTES
RAW_UDS_MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
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
    "incomplete_frame",
    "frame_length_mismatch",
    "invalid_client_frame_type",
)
RAW_UDS_REQUIRED_ERROR_CODES = (
    "raw_uds_unsupported_frame_type",
    "raw_uds_malformed_json_control",
    "raw_uds_payload_too_large",
    "raw_uds_incomplete_frame",
    "raw_uds_frame_length_mismatch",
    "raw_uds_invalid_client_frame_type",
)
RAW_UDS_REQUIRED_START_CONTROL_PAYLOAD = {
    "type": "start",
    "protocol": "local-stt-v1",
    "sample_rate": 16000,
    "channels": 1,
    "format": "pcm_s16le",
    "frame_ms": 20,
    "partial_interval_ms": 100,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 transport benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown summary output path")
    parser.add_argument("--decision-output", type=Path, help="Optional compact raw UDS decision JSON output path")
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
        "--require-cpu-utilization",
        action="store_true",
        help="Exit non-zero unless every required transport artifact includes CPU utilization evidence",
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
        if metric == "protocol_errors" and bucket is not None:
            return float(bucket)
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


def numeric_or_percentile(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        value = first_defined(
            value.get("p95"),
            value.get("average"),
            value.get("avg"),
            value.get("mean"),
            value.get("p50"),
        )
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value.endswith("%"):
            value = value[:-1].strip()
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _matching_experimental_transport_contract(
    candidates: Any, transport: str | None
) -> dict[str, Any] | None:
    if not isinstance(candidates, list) or not transport:
        return None
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("transport") == transport:
            return dict(candidate)
    return None


def _service_protocol_transport_contract(artifact: dict[str, Any], transport: str | None) -> dict[str, Any] | None:
    service = artifact.get("service")
    if not isinstance(service, dict):
        return None
    protocols = service.get("protocols")
    if not isinstance(protocols, list):
        return None
    for protocol in protocols:
        if not isinstance(protocol, dict):
            continue
        contract = _matching_experimental_transport_contract(
            protocol.get("experimental_transports"),
            transport,
        )
        if contract is not None:
            return contract
    return None


def normalized_target_contract(artifact: dict[str, Any]) -> dict[str, Any]:
    target = artifact.get("target") if isinstance(artifact.get("target"), dict) else {}
    transport = target.get("transport") if isinstance(target.get("transport"), str) else None
    normalized: dict[str, Any] = {}
    for candidate in (
        _service_protocol_transport_contract(artifact, transport),
        _matching_experimental_transport_contract(
            artifact.get("contract", {}).get("experimental_transports")
            if isinstance(artifact.get("contract"), dict)
            else None,
            transport,
        ),
        target.get("contract"),
        artifact.get("contract"),
        artifact.get("target_contract"),
    ):
        if isinstance(candidate, dict):
            normalized.update(candidate)
    if normalized:
        return normalized
    for candidate in (
        artifact.get("target_contract"),
        artifact.get("contract"),
        target.get("contract"),
    ):
        if isinstance(candidate, dict):
            return candidate
    return {}


def extract_cpu_utilization_percent(artifact: dict[str, Any]) -> float | None:
    environment = artifact.get("environment") if isinstance(artifact.get("environment"), dict) else {}
    metrics = artifact.get("metrics") if isinstance(artifact.get("metrics"), dict) else {}
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    system = artifact.get("system") if isinstance(artifact.get("system"), dict) else {}
    cpu = artifact.get("cpu") if isinstance(artifact.get("cpu"), dict) else {}
    value = first_defined(
        environment.get("cpu_utilization_percent"),
        environment.get("cpu_utilization"),
        environment.get("cpu_percent"),
        environment.get("average_cpu_percent"),
        environment.get("process_cpu_percent"),
        system.get("cpu_utilization_percent"),
        system.get("cpu_utilization"),
        system.get("cpu_percent"),
        system.get("average_cpu_percent"),
        system.get("process_cpu_percent"),
        metrics.get("cpu_utilization_percent"),
        metrics.get("cpu_utilization"),
        metrics.get("cpu_percent"),
        metrics.get("average_cpu_percent"),
        metrics.get("process_cpu_percent"),
        nested_value(metrics, "cpu", "utilization_percent"),
        nested_value(metrics, "cpu", "utilization"),
        nested_value(metrics, "cpu", "average_utilization_percent"),
        nested_value(metrics, "cpu", "percent"),
        nested_value(metrics, "cpu", "average_percent"),
        nested_value(metrics, "cpu", "process_percent"),
        nested_value(metrics, "process", "cpu_percent"),
        nested_value(metrics, "process", "average_cpu_percent"),
        summary.get("cpu_utilization_percent"),
        summary.get("cpu_utilization"),
        summary.get("cpu_percent"),
        summary.get("average_cpu_percent"),
        summary.get("process_cpu_percent"),
        nested_value(summary, "cpu", "utilization_percent"),
        nested_value(summary, "cpu", "utilization"),
        nested_value(summary, "cpu", "average_utilization_percent"),
        nested_value(summary, "cpu", "percent"),
        nested_value(summary, "cpu", "average_percent"),
        nested_value(summary, "cpu", "process_percent"),
        nested_value(summary, "process", "cpu_percent"),
        nested_value(summary, "process", "average_cpu_percent"),
        cpu.get("utilization_percent"),
        cpu.get("utilization"),
        cpu.get("average_utilization_percent"),
        cpu.get("percent"),
        cpu.get("average_percent"),
        cpu.get("process_percent"),
    )
    return numeric_or_percentile(value)


DIAGNOSTIC_CODE_ALIASES = {
    "protocol_error_codes": ("protocol_errors_by_code", "protocol_error_counts"),
    "warning_codes": ("warnings_by_code", "warning_counts"),
}

DIAGNOSTIC_TOTAL_ALIASES = {
    "protocol_error_codes": ("protocol_error_total", "protocol_errors_total", "protocol_error_count"),
    "warning_codes": ("warning_total", "warnings_total", "warning_count"),
}


def extract_diagnostic_code_counts(artifact: dict[str, Any], key: str) -> dict[str, int]:
    diagnostics = artifact.get("diagnostics") if isinstance(artifact.get("diagnostics"), dict) else {}
    values = first_defined(
        diagnostics.get(key),
        *(diagnostics.get(alias) for alias in DIAGNOSTIC_CODE_ALIASES.get(key, ())),
    )
    counts: dict[str, int] = {}
    if isinstance(values, dict):
        for code, count in values.items():
            if not isinstance(code, str):
                continue
            try:
                counts[code] = int(count)
            except (TypeError, ValueError):
                continue
    else:
        for sample in sample_records(artifact):
            sample_codes = sample.get(key)
            if not isinstance(sample_codes, list):
                continue
            for code in sample_codes:
                if isinstance(code, str):
                    counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


def diagnostic_code_total(counts: dict[str, int]) -> int:
    return sum(count for count in counts.values() if count > 0)


def extract_diagnostic_total(artifact: dict[str, Any], key: str, counts: dict[str, int]) -> int:
    diagnostics = artifact.get("diagnostics") if isinstance(artifact.get("diagnostics"), dict) else {}
    value = first_defined(*(diagnostics.get(alias) for alias in DIAGNOSTIC_TOTAL_ALIASES.get(key, ())))
    try:
        explicit_total = int(value) if value is not None else 0
    except (TypeError, ValueError):
        explicit_total = 0
    return max(explicit_total, diagnostic_code_total(counts))


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


def raw_uds_distinct_p95_leaders(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds_metrics = transports.get("raw_uds", {}).get("metrics_p95", {})
    leaders: list[str] = []
    for metric in KEY_METRICS:
        raw_value = raw_uds_metrics.get(metric)
        if raw_value is None:
            continue
        raw_value = float(raw_value)
        baseline_values = [
            float(payload.get("metrics_p95", {})[metric])
            for transport, payload in transports.items()
            if transport != "raw_uds" and metric in payload.get("metrics_p95", {})
        ]
        if baseline_values and all(raw_value < value for value in baseline_values):
            leaders.append(metric)
    return leaders


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
        for transport in sorted(REQUIRED_TRANSPORTS)
        if transports.get(transport, {}).get("cpu_utilization_percent") is None
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


def cpu_utilization_gaps(
    transports: dict[str, dict[str, Any]], *, required: bool = False
) -> list[str]:
    if not required:
        return []
    missing = missing_cpu_utilization_transports(transports)
    return [f"{transport} missing CPU utilization" for transport in missing]


def run_count_coverage(transports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    run_counts = {
        transport: payload.get("runs")
        for transport, payload in sorted(transports.items())
        if transport in REQUIRED_TRANSPORTS and isinstance(payload.get("runs"), int)
    }
    missing = sorted(transport for transport in REQUIRED_TRANSPORTS if transport not in run_counts)
    return {
        "available_transports": sorted(run_counts),
        "missing_transports": missing,
        "required_transports": list(REQUIRED_TRANSPORTS),
        "run_counts": run_counts,
        "min_runs": min(run_counts.values()) if run_counts else None,
        "complete": not missing and all(transport in transports for transport in REQUIRED_TRANSPORTS),
    }


def artifact_run_count(artifact: dict[str, Any]) -> int | None:
    for key in ("runs", "run_count", "iteration_count", "sample_count"):
        value = artifact.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    samples = artifact.get("samples")
    if isinstance(samples, list):
        return len(samples)
    if isinstance(samples, dict):
        return len([sample for sample in samples.values() if isinstance(sample, dict)])
    return None


def sample_records(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    samples = artifact.get("samples")
    if isinstance(samples, list):
        return [sample for sample in samples if isinstance(sample, dict)]
    if isinstance(samples, dict):
        return [sample for sample in samples.values() if isinstance(sample, dict)]
    return []


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
    if raw_uds.get("per_frame_overhead_bytes") != RAW_UDS_PER_FRAME_OVERHEAD_BYTES:
        gaps.append(f"raw_uds missing target.per_frame_overhead_bytes={RAW_UDS_PER_FRAME_OVERHEAD_BYTES}")
    if raw_uds.get("max_payload_bytes") != RAW_UDS_MAX_PAYLOAD_BYTES:
        gaps.append(f"raw_uds missing target.max_payload_bytes={RAW_UDS_MAX_PAYLOAD_BYTES}")
    return gaps


def raw_uds_lifecycle_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    lifecycle = raw_uds.get("lifecycle")
    if not isinstance(lifecycle, list):
        return ["raw_uds missing target.lifecycle coverage"]

    semantic_lifecycle = raw_uds.get("semantic_lifecycle")
    if isinstance(semantic_lifecycle, list) and semantic_lifecycle != lifecycle:
        expected = ",".join(lifecycle)
        observed = ",".join(str(event) for event in semantic_lifecycle)
        return [f"raw_uds semantic_lifecycle mismatch: expected {expected}; got {observed}"]

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


def raw_uds_error_code_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    error_codes = raw_uds.get("error_codes")
    if not isinstance(error_codes, list):
        return ["raw_uds missing target.error_codes coverage"]

    missing = [code for code in RAW_UDS_REQUIRED_ERROR_CODES if code not in error_codes]
    if missing:
        return [f"raw_uds missing protocol-error code coverage: {','.join(missing)}"]
    return []


def raw_uds_runtime_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []
    if raw_uds.get("shared_stream_runtime") is True:
        return []
    return ["raw_uds missing shared stream runtime evidence"]


def raw_uds_plugin_config_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    plugin_config = raw_uds.get("plugin_config")
    if not isinstance(plugin_config, dict):
        return ["raw_uds missing target.plugin_config"]

    gaps: list[str] = []
    if plugin_config.get("transport") != "raw_uds":
        gaps.append("raw_uds missing target.plugin_config.transport=raw_uds")
    plugin_uds_path = plugin_config.get("uds_path")
    if raw_uds.get("uds_path") and plugin_uds_path not in {
        raw_uds.get("uds_path"),
        "<LOCAL_STT_RAW_UDS_PATH>",
        "<uds_path>",
        "<socket>",
    }:
        gaps.append("raw_uds target.plugin_config.uds_path must match target.uds_path")
    return gaps


def raw_uds_start_payload_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    payload = raw_uds.get("start_control_payload")
    if not isinstance(payload, dict):
        return ["raw_uds missing target.start_control_payload"]

    gaps: list[str] = []
    for field, expected in RAW_UDS_REQUIRED_START_CONTROL_PAYLOAD.items():
        if payload.get(field) != expected:
            gaps.append(f"raw_uds target.start_control_payload.{field} must be {expected!r}")
    return gaps


def raw_uds_comparison_requirement_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    required = raw_uds.get("comparison_required_transports")
    if not isinstance(required, list):
        return ["raw_uds missing target.comparison_required_transports"]

    observed = [transport for transport in required if isinstance(transport, str)]
    missing = [transport for transport in REQUIRED_TRANSPORTS if transport not in observed]
    unexpected = [transport for transport in observed if transport not in REQUIRED_TRANSPORTS]
    gaps: list[str] = []
    if missing:
        gaps.append(f"raw_uds missing comparison transport coverage: {','.join(missing)}")
    if unexpected:
        gaps.append(f"raw_uds unexpected comparison transport coverage: {','.join(unexpected)}")
    return gaps


def parse_frame_type_code(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def normalize_frame_type_name(value: str) -> str:
    return value.strip().upper()


def raw_uds_frame_type_code_lookup(
    frame_type_codes: dict[str, Any],
    frame_type: str,
) -> Any:
    if frame_type in frame_type_codes:
        return frame_type_codes[frame_type]
    for key, code in frame_type_codes.items():
        if isinstance(key, str) and normalize_frame_type_name(key) == frame_type:
            return code
    return None


def raw_uds_frame_type_names(value: Any) -> list[str] | None:
    if isinstance(value, list):
        return [normalize_frame_type_name(frame_type) for frame_type in value if isinstance(frame_type, str)]
    if isinstance(value, dict):
        names: list[str] = []
        for key, code in value.items():
            if not isinstance(key, str):
                continue
            name = normalize_frame_type_name(key)
            if name in RAW_UDS_REQUIRED_FRAME_TYPE_CODES:
                names.append(name)
                continue
            parsed_code = parse_frame_type_code(code)
            for required_name, required_code in RAW_UDS_REQUIRED_FRAME_TYPE_CODES.items():
                if parsed_code == required_code:
                    names.append(required_name)
                    break
        return names
    return None


def raw_uds_frame_type_gaps(transports: dict[str, dict[str, Any]]) -> list[str]:
    raw_uds = transports.get("raw_uds")
    if raw_uds is None:
        return []

    gaps: list[str] = []
    frame_types = raw_uds_frame_type_names(raw_uds.get("frame_types"))
    if frame_types is None:
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
        observed_code = raw_uds_frame_type_code_lookup(frame_type_codes, frame_type)
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


def normalized_audio_inputs(artifact: dict[str, Any]) -> dict[str, Any]:
    audio = artifact.get("audio") if isinstance(artifact.get("audio"), dict) else {}
    settings = artifact.get("settings") if isinstance(artifact.get("settings"), dict) else {}
    benchmark = artifact.get("benchmark") if isinstance(artifact.get("benchmark"), dict) else {}
    integration = artifact.get("integration") if isinstance(artifact.get("integration"), dict) else {}
    streaming = artifact.get("streaming") if isinstance(artifact.get("streaming"), dict) else {}
    source = first_defined(audio.get("source"), audio.get("path"))
    duration_ms = first_defined(audio.get("duration_ms"), audio.get("duration_s"))
    if duration_ms is not None and audio.get("duration_ms") is None:
        duration_ms = round(float(duration_ms) * 1000, 3)
    frame_ms = first_defined(
        audio.get("frame_ms"),
        settings.get("source_frame_ms"),
        benchmark.get("source_frame_ms"),
        integration.get("source_frame_ms"),
        streaming.get("source_frame_ms"),
    )
    return {
        "source": source,
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
        "format": audio.get("format"),
        "frame_ms": frame_ms,
        "duration_ms": duration_ms,
    }


def normalized_benchmark_settings(artifact: dict[str, Any]) -> dict[str, Any]:
    settings = artifact.get("settings") if isinstance(artifact.get("settings"), dict) else {}
    benchmark = artifact.get("benchmark") if isinstance(artifact.get("benchmark"), dict) else {}
    integration = artifact.get("integration") if isinstance(artifact.get("integration"), dict) else {}
    streaming = artifact.get("streaming") if isinstance(artifact.get("streaming"), dict) else {}
    return {
        "partial_interval_ms": first_defined(
            settings.get("partial_interval_ms"),
            settings.get("requested_partial_interval_ms"),
            benchmark.get("partial_interval_ms"),
            benchmark.get("requested_partial_interval_ms"),
            integration.get("partial_interval_ms"),
            integration.get("requested_partial_interval_ms"),
            streaming.get("partial_interval_ms"),
            streaming.get("requested_partial_interval_ms"),
        ),
        "realtime_pace": first_defined(
            settings.get("realtime_pace"),
            settings.get("simulate_realtime"),
            benchmark.get("simulate_realtime"),
            integration.get("simulate_realtime"),
            streaming.get("simulate_realtime"),
        ),
    }


def normalized_service_identity(artifact: dict[str, Any]) -> dict[str, Any]:
    backend = artifact.get("backend") if isinstance(artifact.get("backend"), dict) else {}
    service = artifact.get("service") if isinstance(artifact.get("service"), dict) else {}
    target = artifact.get("target") if isinstance(artifact.get("target"), dict) else {}
    return {
        "backend": first_defined(
            backend.get("backend"),
            backend.get("name"),
            service.get("backend"),
            target.get("backend"),
        ),
        "model": first_defined(
            backend.get("model"),
            backend.get("model_name"),
            service.get("model"),
            service.get("model_name"),
            target.get("model"),
            target.get("model_name"),
        ),
    }


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

    for field in ("backend", "model"):
        values = {
            transport: payload.get("service", {}).get(field)
            for transport, payload in sorted(transports.items())
        }
        if not any(value not in (None, "") for value in values.values()):
            continue
        missing = [transport for transport, value in values.items() if value is None or value == ""]
        if missing:
            gaps.append(f"benchmark service identity missing for {field}: {','.join(missing)}")
            continue
        if len(set(values.values())) > 1:
            rendered = ", ".join(f"{transport}={value!r}" for transport, value in values.items())
            gaps.append(f"benchmark service identity mismatch for {field}: {rendered}")
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


def protocol_error_free(
    metrics: dict[str, dict[str, float | None]], *, diagnostic_protocol_error_total: int = 0
) -> bool:
    if diagnostic_protocol_error_total > 0:
        return False
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


def apply_diagnostic_protocol_error_counts(
    metrics: dict[str, dict[str, float | None]],
    protocol_error_total: int,
) -> None:
    protocol_errors = metrics["protocol_errors"]
    if any(protocol_errors.get(percentile) is not None for percentile in PERCENTILES):
        return
    total = float(protocol_error_total)
    metrics["protocol_errors"] = {percentile: total for percentile in PERCENTILES}


def recommendation_text(
    *,
    missing: list[str],
    unexpected: list[str],
    raw_vs_uds_delta_ms: float | None,
    raw_vs_uds_final_after_finalize_delta_ms: float | None,
    raw_uds_min_win_ms: float,
    raw_uds_experimental: bool,
    all_present_transports_protocol_error_free: bool,
    missing_metrics: dict[str, list[str]],
    run_gaps: list[str],
    cpu_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    error_code_gaps: list[str],
    runtime_gaps: list[str],
    plugin_config_gaps: list[str],
    start_payload_gaps: list[str],
    comparison_requirement_gaps: list[str],
    input_gaps: list[str],
    raw_uds_queue_regressions: list[str],
) -> str:
    if missing:
        return "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."
    if unexpected:
        return "Remove unexpected transport benchmark artifacts before recommending raw UDS."
    if missing_metrics:
        return "Re-run transport benchmarks with the full required metric set before recommending raw UDS."
    if run_gaps:
        return "Re-run transport benchmarks with enough repeated runs before recommending raw UDS."
    if cpu_gaps:
        return "Re-run transport benchmarks with CPU utilization evidence before recommending raw UDS."
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
    if error_code_gaps:
        return "Re-run raw UDS benchmarks with protocol-error code coverage before recommending raw UDS."
    if runtime_gaps:
        return "Re-run raw UDS benchmarks with shared stream runtime evidence before recommending raw UDS."
    if plugin_config_gaps:
        return "Re-run raw UDS benchmarks with plugin config target metadata before recommending raw UDS."
    if start_payload_gaps:
        return "Re-run raw UDS benchmarks with the documented Local STT v1 start payload before recommending raw UDS."
    if comparison_requirement_gaps:
        return "Re-run raw UDS benchmarks with explicit three-transport comparison coverage before recommending raw UDS."
    if input_gaps:
        return "Re-run transport benchmarks with matching audio and pacing settings before recommending raw UDS."
    if not all_present_transports_protocol_error_free:
        return "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    if raw_vs_uds_delta_ms is None:
        return "Raw UDS and UDS websocket first-interim P95 metrics were unavailable; keep raw UDS experimental."
    if raw_vs_uds_final_after_finalize_delta_ms is not None and raw_vs_uds_final_after_finalize_delta_ms < 0:
        return "Keep raw UDS experimental until final-after-finalize P95 does not regress against UDS websocket."
    if raw_uds_queue_regressions:
        return "Keep raw UDS experimental until queue latency P95 does not regress against UDS websocket."
    if raw_uds_experimental:
        return f"Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least {raw_uds_min_win_ms:g} ms."
    return "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def blocking_gap_reasons(
    *,
    missing: list[str],
    unexpected: list[str],
    missing_metrics: dict[str, list[str]],
    run_gaps: list[str],
    cpu_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    error_code_gaps: list[str],
    runtime_gaps: list[str],
    plugin_config_gaps: list[str],
    start_payload_gaps: list[str],
    comparison_requirement_gaps: list[str],
    input_gaps: list[str],
    transports: dict[str, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(f"missing transport benchmark: {transport}" for transport in missing)
    reasons.extend(f"unexpected transport benchmark: {transport}" for transport in unexpected)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        reasons.extend(f"{transport} missing metric percentile: {metric_gap}" for metric_gap in metric_gaps)
    reasons.extend(run_gaps)
    reasons.extend(cpu_gaps)
    reasons.extend(target_gaps)
    reasons.extend(frame_contract_gaps)
    reasons.extend(frame_type_gaps)
    reasons.extend(lifecycle_gaps)
    reasons.extend(error_handling_gaps)
    reasons.extend(error_code_gaps)
    reasons.extend(runtime_gaps)
    reasons.extend(plugin_config_gaps)
    reasons.extend(start_payload_gaps)
    reasons.extend(comparison_requirement_gaps)
    reasons.extend(input_gaps)
    for transport, payload in sorted(transports.items()):
        if not payload["protocol_error_free"]:
            diagnostic_total = payload.get("diagnostics", {}).get("protocol_error_total", 0)
            if diagnostic_total:
                codes = payload.get("diagnostics", {}).get("protocol_error_codes", {})
                recorded_codes = ", ".join(
                    f"{code}={count}" for code, count in sorted(codes.items())
                ) or "no per-code counts"
                reasons.append(
                    f"{transport} diagnostic protocol_error_total must be zero; "
                    f"got total={diagnostic_total} ({recorded_codes})"
                )
                continue
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
    cpu_gaps: list[str],
    target_gaps: list[str],
    frame_contract_gaps: list[str],
    frame_type_gaps: list[str],
    lifecycle_gaps: list[str],
    error_handling_gaps: list[str],
    error_code_gaps: list[str],
    runtime_gaps: list[str],
    plugin_config_gaps: list[str],
    start_payload_gaps: list[str],
    comparison_requirement_gaps: list[str],
    input_gaps: list[str],
    all_present_transports_protocol_error_free: bool,
    raw_vs_uds_delta_ms: float | None,
    raw_vs_uds_final_after_finalize_delta_ms: float | None,
    raw_vs_uds_deltas: dict[str, float | None],
    raw_uds_min_win_ms: float,
) -> dict[str, Any]:
    blockers: list[str] = []
    blockers.extend(f"missing_transport:{transport}" for transport in missing)
    blockers.extend(f"unexpected_transport:{transport}" for transport in unexpected)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        blockers.extend(f"missing_metric:{transport}:{metric_gap}" for metric_gap in metric_gaps)
    blockers.extend(f"run_count:{gap}" for gap in run_gaps)
    blockers.extend(f"cpu_utilization:{gap}" for gap in cpu_gaps)
    blockers.extend(f"target:{gap}" for gap in target_gaps)
    blockers.extend(f"frame_contract:{gap}" for gap in frame_contract_gaps)
    blockers.extend(f"frame_type:{gap}" for gap in frame_type_gaps)
    blockers.extend(f"lifecycle:{gap}" for gap in lifecycle_gaps)
    blockers.extend(f"error_handling:{gap}" for gap in error_handling_gaps)
    blockers.extend(f"error_codes:{gap}" for gap in error_code_gaps)
    blockers.extend(f"runtime:{gap}" for gap in runtime_gaps)
    blockers.extend(f"plugin_config:{gap}" for gap in plugin_config_gaps)
    blockers.extend(f"start_payload:{gap}" for gap in start_payload_gaps)
    blockers.extend(f"comparison_required_transports:{gap}" for gap in comparison_requirement_gaps)
    blockers.extend(f"benchmark_input:{gap}" for gap in input_gaps)
    if not all_present_transports_protocol_error_free:
        blockers.append("protocol_errors")
    if raw_vs_uds_delta_ms is None:
        blockers.append("missing_raw_uds_latency_delta")
    elif raw_vs_uds_delta_ms < raw_uds_min_win_ms:
        blockers.append("insufficient_raw_uds_latency_win")
    if raw_vs_uds_final_after_finalize_delta_ms is not None and raw_vs_uds_final_after_finalize_delta_ms < 0:
        blockers.append("raw_uds_finalization_regression")
    queue_regressions = raw_uds_queue_regressions(raw_vs_uds_deltas)
    blockers.extend(f"raw_uds_queue_regression:{metric}" for metric in queue_regressions)
    return {
        "passed": not blockers,
        "blockers": blockers,
        "raw_uds_min_win_ms": raw_uds_min_win_ms,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms": raw_vs_uds_final_after_finalize_delta_ms,
    }


def raw_uds_queue_regressions(raw_vs_uds_deltas: dict[str, float | None]) -> list[str]:
    return [
        metric
        for metric in ("audio_send_queue_depth_p95_ms", "asr_queue_delay_p95_ms")
        if raw_vs_uds_deltas.get(metric) is not None and raw_vs_uds_deltas[metric] < 0
    ]


def raw_uds_decision_next_action(gate_blockers: list[str]) -> str:
    if not gate_blockers:
        return "Proceed with the next raw UDS adapter prototype."

    blocker = gate_blockers[0]
    if blocker.startswith("missing_transport:"):
        transport = blocker.split(":", 1)[1]
        return f"Run the missing {transport} benchmark before deciding on raw UDS."
    if blocker.startswith("missing_metric:"):
        _, transport, metric = blocker.split(":", 2)
        return f"Re-run {transport} with required metric coverage for {metric}."
    if blocker.startswith("run_count:"):
        return "Re-run transport benchmarks with enough repeated runs."
    if blocker.startswith("cpu_utilization:"):
        return "Re-run transport benchmarks with CPU utilization evidence."
    if blocker.startswith("target:"):
        return "Re-run transport benchmarks with explicit endpoint targets."
    if blocker.startswith("frame_contract:"):
        return "Re-run raw UDS with the required length-prefixed frame contract."
    if blocker.startswith("frame_type:"):
        return "Re-run raw UDS with complete frame type coverage."
    if blocker.startswith("lifecycle:"):
        return "Re-run raw UDS with full Local STT v1 lifecycle coverage."
    if blocker.startswith("error_handling:"):
        return "Re-run raw UDS with protocol-error handling coverage."
    if blocker.startswith("error_codes:"):
        return "Re-run raw UDS with protocol-error code coverage."
    if blocker.startswith("runtime:"):
        return "Re-run raw UDS with shared stream runtime evidence."
    if blocker.startswith("plugin_config:"):
        return "Re-run raw UDS with plugin config target metadata."
    if blocker.startswith("start_payload:"):
        return "Re-run raw UDS with the documented Local STT v1 start payload."
    if blocker.startswith("comparison_required_transports:"):
        return "Re-run raw UDS with explicit TCP, UDS websocket, and raw UDS comparison coverage."
    if blocker.startswith("benchmark_input:"):
        return "Re-run transport benchmarks with matching audio and pacing settings."
    if blocker == "protocol_errors":
        return "Fix protocol errors before comparing raw UDS latency."
    if blocker == "missing_raw_uds_latency_delta":
        return "Capture raw UDS and UDS websocket first-interim P95 metrics."
    if blocker == "insufficient_raw_uds_latency_win":
        return "Keep raw UDS experimental unless a future benchmark clears the latency gate."
    if blocker == "raw_uds_finalization_regression":
        return "Keep raw UDS experimental until finalization latency no longer regresses."
    if blocker.startswith("raw_uds_queue_regression:"):
        metric = blocker.split(":", 1)[1]
        return f"Keep raw UDS experimental until {metric} no longer regresses."
    return "Review the gate blockers before deciding on raw UDS."


def raw_uds_decision_summary(
    *,
    recommendation: str,
    recommendation_gate: dict[str, Any],
    raw_uds_leading_metrics: list[str],
    raw_vs_uds_delta_ms: float | None,
    raw_vs_uds_final_after_finalize_delta_ms: float | None,
    raw_uds_min_win_ms: float,
    raw_uds_experimental: bool,
) -> dict[str, Any]:
    gate_blockers = list(recommendation_gate.get("blockers") or [])
    return {
        "status": "experimental" if raw_uds_experimental else "recommended",
        "reason": recommendation,
        "next_action": raw_uds_decision_next_action(gate_blockers),
        "primary_metric": "time_to_first_interim_ms",
        "comparison_baseline": "uds_ws",
        "observed_first_interim_p95_win_ms": raw_vs_uds_delta_ms,
        "required_first_interim_p95_win_ms": raw_uds_min_win_ms,
        "observed_final_after_finalize_p95_delta_ms": raw_vs_uds_final_after_finalize_delta_ms,
        "raw_uds_leading_p95_metrics": raw_uds_leading_metrics,
        "gate_passed": bool(recommendation_gate.get("passed")),
        "gate_blockers": gate_blockers,
        "gate_blocker_count": len(gate_blockers),
    }


def compare_artifacts(
    paths: list[Path],
    *,
    min_runs: int | None = None,
    require_cpu_utilization: bool = False,
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
        target_contract = normalized_target_contract(artifact)
        protocol_error_codes = extract_diagnostic_code_counts(artifact, "protocol_error_codes")
        warning_codes = extract_diagnostic_code_counts(artifact, "warning_codes")
        protocol_error_total = extract_diagnostic_total(artifact, "protocol_error_codes", protocol_error_codes)
        warning_total = extract_diagnostic_total(artifact, "warning_codes", warning_codes)
        target_semantic_lifecycle = artifact["target"].get("semantic_lifecycle") or target_contract.get("semantic_lifecycle")
        target_lifecycle = (
            artifact["target"].get("lifecycle")
            or target_contract.get("lifecycle")
            or target_semantic_lifecycle
        )
        target_frame_types = artifact["target"].get("frame_types") or target_contract.get("frame_types")
        target_frame_type_codes = artifact["target"].get("frame_type_codes") or target_contract.get("frame_type_codes")
        target_error_handling = artifact["target"].get("error_handling") or target_contract.get("error_handling")
        target_error_codes = artifact["target"].get("error_codes") or target_contract.get("error_codes")
        target_plugin_config = artifact["target"].get("plugin_config") or target_contract.get("plugin_config")
        target_start_control_payload = artifact["target"].get("start_control_payload") or target_contract.get(
            "start_control_payload"
        )
        target_comparison_required_transports = artifact["target"].get(
            "comparison_required_transports"
        ) or target_contract.get("comparison_required_transports")
        shared_stream_runtime = artifact["target"].get("shared_stream_runtime")
        if shared_stream_runtime is None:
            shared_stream_runtime = target_contract.get("shared_stream_runtime")
        metrics = {metric: metric_percentiles(summary, metric) for metric in KEY_METRICS}
        apply_diagnostic_protocol_error_counts(metrics, protocol_error_total)
        metrics_p95 = {metric: metrics[metric]["p95"] for metric in KEY_METRICS}
        missing_metrics = missing_required_metrics(metrics)
        by_transport[transport] = {
            "artifact": str(path),
            **artifact_provenance(path),
            "url": artifact["target"].get("url"),
            "uds_path": artifact["target"].get("uds_path"),
            "frame_format": artifact["target"].get("frame_format") or target_contract.get("frame_format"),
            "frame_header_bytes": artifact["target"].get("frame_header_bytes") or target_contract.get("frame_header_bytes"),
            "per_frame_overhead_bytes": artifact["target"].get("per_frame_overhead_bytes")
            or target_contract.get("per_frame_overhead_bytes"),
            "max_payload_bytes": artifact["target"].get("max_payload_bytes")
            or target_contract.get("max_payload_bytes"),
            "frame_types": target_frame_types,
            "frame_type_codes": target_frame_type_codes,
            "lifecycle": target_lifecycle,
            "semantic_lifecycle": target_semantic_lifecycle,
            "error_handling": target_error_handling,
            "error_codes": target_error_codes,
            "shared_stream_runtime": shared_stream_runtime,
            "plugin_config": target_plugin_config,
            "start_control_payload": target_start_control_payload,
            "comparison_required_transports": target_comparison_required_transports,
            "audio": normalized_audio_inputs(artifact),
            "settings": normalized_benchmark_settings(artifact),
            "service": normalized_service_identity(artifact),
            "runs": artifact_run_count(artifact),
            "metrics": metrics,
            "metrics_p95": metrics_p95,
            "missing_p95_metrics": missing_metrics,
            "protocol_error_free": protocol_error_free(
                metrics,
                diagnostic_protocol_error_total=protocol_error_total,
            ),
            "cpu_utilization_percent": extract_cpu_utilization_percent(artifact),
            "diagnostics": {
                "protocol_error_codes": protocol_error_codes,
                "protocol_error_total": protocol_error_total,
                "warning_codes": warning_codes,
                "warning_total": warning_total,
            },
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
    queue_regressions = raw_uds_queue_regressions(raw_vs_uds_deltas)
    raw_uds_latency_experimental = raw_vs_uds_delta_ms is None or raw_vs_uds_delta_ms < raw_uds_min_win_ms
    fastest_first_interim_transport = fastest_transport_by_metric(by_transport, "time_to_first_interim_ms")
    fastest_final_after_finalize_transport = fastest_transport_by_metric(
        by_transport, "time_to_final_after_finalize_ms"
    )
    metric_leaders = p95_metric_leaders(by_transport)
    raw_uds_leading_metrics = raw_uds_distinct_p95_leaders(by_transport)
    lowest_cpu_transport = lowest_cpu_utilization_transport(by_transport)
    missing_cpu_utilization = missing_cpu_utilization_transports(by_transport)
    cpu_coverage = cpu_utilization_coverage(by_transport)
    cpu_gaps = cpu_utilization_gaps(by_transport, required=require_cpu_utilization)
    run_coverage = run_count_coverage(by_transport)
    run_gaps = run_count_gaps(by_transport, min_runs)
    target_gaps = target_field_gaps(by_transport)
    frame_contract_gaps = raw_uds_frame_contract_gaps(by_transport)
    frame_type_gaps = raw_uds_frame_type_gaps(by_transport)
    lifecycle_gaps = raw_uds_lifecycle_gaps(by_transport)
    error_handling_gaps = raw_uds_error_handling_gaps(by_transport)
    error_code_gaps = raw_uds_error_code_gaps(by_transport)
    runtime_gaps = raw_uds_runtime_gaps(by_transport)
    plugin_config_gaps = raw_uds_plugin_config_gaps(by_transport)
    start_payload_gaps = raw_uds_start_payload_gaps(by_transport)
    comparison_requirement_gaps = raw_uds_comparison_requirement_gaps(by_transport)
    input_gaps = benchmark_input_gaps(by_transport)

    all_present_transports_protocol_error_free = all(
        transport["protocol_error_free"] for transport in by_transport.values()
    )
    recommendation_gate = raw_uds_recommendation_gate(
        missing=missing,
        unexpected=unexpected,
        missing_metrics=missing_metrics_by_transport,
        run_gaps=run_gaps,
        cpu_gaps=cpu_gaps,
        target_gaps=target_gaps,
        frame_contract_gaps=frame_contract_gaps,
        frame_type_gaps=frame_type_gaps,
        lifecycle_gaps=lifecycle_gaps,
        error_handling_gaps=error_handling_gaps,
        error_code_gaps=error_code_gaps,
        runtime_gaps=runtime_gaps,
        plugin_config_gaps=plugin_config_gaps,
        start_payload_gaps=start_payload_gaps,
        comparison_requirement_gaps=comparison_requirement_gaps,
        input_gaps=input_gaps,
        all_present_transports_protocol_error_free=all_present_transports_protocol_error_free,
        raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
        raw_vs_uds_final_after_finalize_delta_ms=raw_vs_uds_final_after_finalize_delta_ms,
        raw_vs_uds_deltas=raw_vs_uds_deltas,
        raw_uds_min_win_ms=raw_uds_min_win_ms,
    )
    raw_uds_experimental = bool(raw_uds_latency_experimental or not recommendation_gate["passed"])

    recommendation = recommendation_text(
        missing=missing,
        unexpected=unexpected,
        raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
        raw_vs_uds_final_after_finalize_delta_ms=raw_vs_uds_final_after_finalize_delta_ms,
        raw_uds_min_win_ms=raw_uds_min_win_ms,
        raw_uds_experimental=raw_uds_experimental,
        all_present_transports_protocol_error_free=all_present_transports_protocol_error_free,
        missing_metrics=missing_metrics_by_transport,
        run_gaps=run_gaps,
        cpu_gaps=cpu_gaps,
        target_gaps=target_gaps,
        frame_contract_gaps=frame_contract_gaps,
        frame_type_gaps=frame_type_gaps,
        lifecycle_gaps=lifecycle_gaps,
        error_handling_gaps=error_handling_gaps,
        error_code_gaps=error_code_gaps,
        runtime_gaps=runtime_gaps,
        plugin_config_gaps=plugin_config_gaps,
        start_payload_gaps=start_payload_gaps,
        comparison_requirement_gaps=comparison_requirement_gaps,
        input_gaps=input_gaps,
        raw_uds_queue_regressions=queue_regressions,
    )

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
        "cpu_utilization_gaps": cpu_gaps,
        "run_count_coverage": run_coverage,
        "minimum_required_runs": min_runs,
        "run_count_gaps": run_gaps,
        "target_field_gaps": target_gaps,
        "raw_uds_frame_contract_gaps": frame_contract_gaps,
        "raw_uds_frame_type_gaps": frame_type_gaps,
        "raw_uds_lifecycle_gaps": lifecycle_gaps,
        "raw_uds_error_handling_gaps": error_handling_gaps,
        "raw_uds_error_code_gaps": error_code_gaps,
        "raw_uds_runtime_gaps": runtime_gaps,
        "raw_uds_plugin_config_gaps": plugin_config_gaps,
        "raw_uds_start_payload_gaps": start_payload_gaps,
        "raw_uds_comparison_requirement_gaps": comparison_requirement_gaps,
        "benchmark_input_gaps": input_gaps,
        "raw_uds_min_win_ms": raw_uds_min_win_ms,
        "raw_uds_recommendation_gate": recommendation_gate,
        "raw_uds_vs_uds_ws_p95_deltas_ms": raw_vs_uds_deltas,
        "raw_uds_queue_regressions": queue_regressions,
        "raw_uds_p95_comparison_summary": raw_uds_comparison_summary,
        "pairwise_p95_deltas_ms": p95_delta_matrix,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_vs_uds_ws_time_to_final_after_finalize_p95_delta_ms": raw_vs_uds_final_after_finalize_delta_ms,
        "raw_uds_should_remain_experimental": raw_uds_experimental,
        "raw_uds_decision_summary": raw_uds_decision_summary(
            recommendation=recommendation,
            recommendation_gate=recommendation_gate,
            raw_uds_leading_metrics=raw_uds_leading_metrics,
            raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
            raw_vs_uds_final_after_finalize_delta_ms=raw_vs_uds_final_after_finalize_delta_ms,
            raw_uds_min_win_ms=raw_uds_min_win_ms,
            raw_uds_experimental=raw_uds_experimental,
        ),
        "all_present_transports_protocol_error_free": all_present_transports_protocol_error_free,
        "missing_p95_metrics_by_transport": missing_metrics_by_transport,
        "blocking_gaps": blocking_gap_reasons(
            missing=missing,
            unexpected=unexpected,
            missing_metrics=missing_metrics_by_transport,
            run_gaps=run_gaps,
            cpu_gaps=cpu_gaps,
            target_gaps=target_gaps,
            frame_contract_gaps=frame_contract_gaps,
            frame_type_gaps=frame_type_gaps,
            lifecycle_gaps=lifecycle_gaps,
            error_handling_gaps=error_handling_gaps,
            error_code_gaps=error_code_gaps,
            runtime_gaps=runtime_gaps,
            plugin_config_gaps=plugin_config_gaps,
            start_payload_gaps=start_payload_gaps,
            comparison_requirement_gaps=comparison_requirement_gaps,
            input_gaps=input_gaps,
            transports=by_transport,
        ),
        "recommendation": recommendation,
    }


def comparison_has_blocking_gaps(
    comparison: dict[str, Any], *, require_raw_uds_recommendation: bool = False
) -> bool:
    return bool(
        comparison["missing_transports"]
        or comparison["unexpected_transports"]
        or comparison["missing_p95_metrics_by_transport"]
        or comparison.get("run_count_gaps")
        or comparison.get("cpu_utilization_gaps")
        or comparison.get("target_field_gaps")
        or comparison.get("raw_uds_frame_contract_gaps")
        or comparison.get("raw_uds_frame_type_gaps")
        or comparison.get("raw_uds_lifecycle_gaps")
        or comparison.get("raw_uds_error_handling_gaps")
        or comparison.get("raw_uds_error_code_gaps")
        or comparison.get("raw_uds_runtime_gaps")
        or comparison.get("raw_uds_plugin_config_gaps")
        or comparison.get("raw_uds_start_payload_gaps")
        or comparison.get("raw_uds_comparison_requirement_gaps")
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
            "| Transport | URL | UDS path | Raw frame format | Header bytes | Max payload bytes | Frame types | Lifecycle | Error handling | Error codes | Shared runtime |",
            "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for transport in comparison["required_transports"]:
        payload = comparison["transports"].get(transport)
        if payload is None:
            lines.append(f"| {transport} | missing | missing | missing | missing | missing | missing | missing | missing | missing | missing |")
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
                    _format_optional_value(payload.get("max_payload_bytes")),
                    _format_optional_value(payload.get("frame_types")),
                    _format_optional_value(payload.get("lifecycle")),
                    _format_optional_value(payload.get("error_handling")),
                    _format_optional_value(payload.get("error_codes")),
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

    has_diagnostics = any(
        payload.get("diagnostics", {}).get("protocol_error_codes")
        or payload.get("diagnostics", {}).get("warning_codes")
        for payload in comparison["transports"].values()
    )
    if has_diagnostics:
        lines.extend(
            [
                "",
                "Transport diagnostics:",
                "| Transport | Protocol error total | Protocol error codes | Warning total | Warning codes |",
                "| --- | ---: | --- | ---: | --- |",
            ]
        )
        for transport in comparison["required_transports"]:
            payload = comparison["transports"].get(transport)
            if payload is None:
                lines.append(f"| {transport} | missing | missing | missing | missing |")
                continue
            diagnostics = payload.get("diagnostics") or {}
            protocol_error_codes = [
                f"{code}={count}"
                for code, count in sorted((diagnostics.get("protocol_error_codes") or {}).items())
            ]
            warning_codes = [
                f"{code}={count}"
                for code, count in sorted((diagnostics.get("warning_codes") or {}).items())
            ]
            lines.append(
                "| "
                + " | ".join(
                    [
                        transport,
                        _format_optional_value(diagnostics.get("protocol_error_total")),
                        _format_optional_value(protocol_error_codes),
                        _format_optional_value(diagnostics.get("warning_total")),
                        _format_optional_value(warning_codes),
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

    run_coverage = comparison.get("run_count_coverage", {})
    if run_coverage:
        run_counts = run_coverage.get("run_counts", {})
        lines.extend(
            [
                "",
                "Run count coverage:",
                f"- Complete: {_format_optional_value(run_coverage.get('complete'))}",
                f"- Minimum observed runs: {_format_optional_value(run_coverage.get('min_runs'))}",
                f"- Required minimum runs: {_format_optional_value(comparison.get('minimum_required_runs'))}",
                f"- Missing run counts: {_format_optional_value(run_coverage.get('missing_transports', []))}",
                f"- Recorded runs: {_format_optional_value([f'{transport}={count}' for transport, count in sorted(run_counts.items())])}",
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
    decision = comparison.get("raw_uds_decision_summary", {})
    lines.extend(
        [
            "",
            f"Raw UDS recommendation gate: {'passed' if gate['passed'] else 'blocked'}",
            f"Raw UDS first-interim p95 win over UDS WebSocket: {_format_optional_ms(gate['raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms'])}",
            f"Minimum required win: {gate['raw_uds_min_win_ms']:g} ms",
            f"Raw UDS decision status: {_format_optional_value(decision.get('status'))}",
            f"Raw UDS leading p95 metrics: {_format_optional_value(decision.get('raw_uds_leading_p95_metrics'))}",
        ]
    )
    if gate["blockers"]:
        lines.extend(["", "Raw UDS gate blockers:"])
        lines.extend(f"- {blocker}" for blocker in gate["blockers"])
    lines.append("")
    return "\n".join(lines)


def raw_uds_decision_output(comparison: dict[str, Any]) -> dict[str, Any]:
    gate = comparison["raw_uds_recommendation_gate"]
    decision = comparison["raw_uds_decision_summary"]
    required_artifact_snapshot = {
        transport: {
            "artifact": payload.get("artifact"),
            "artifact_sha256": payload.get("artifact_sha256"),
            "artifact_size_bytes": payload.get("artifact_size_bytes"),
        }
        for transport, payload in sorted(comparison.get("transports", {}).items())
    }
    required_target_snapshot = {
        transport: {
            "url": payload.get("url"),
            "uds_path": payload.get("uds_path"),
            "frame_format": payload.get("frame_format"),
            "frame_header_bytes": payload.get("frame_header_bytes"),
            "per_frame_overhead_bytes": payload.get("per_frame_overhead_bytes"),
            "max_payload_bytes": payload.get("max_payload_bytes"),
            "frame_types": payload.get("frame_types"),
            "frame_type_codes": payload.get("frame_type_codes"),
            "lifecycle": payload.get("lifecycle"),
            "semantic_lifecycle": payload.get("semantic_lifecycle"),
            "error_handling": payload.get("error_handling"),
            "error_codes": payload.get("error_codes"),
            "shared_stream_runtime": payload.get("shared_stream_runtime"),
            "plugin_config": payload.get("plugin_config"),
            "start_control_payload": payload.get("start_control_payload"),
        }
        for transport, payload in sorted(comparison.get("transports", {}).items())
    }
    for target in required_target_snapshot.values():
        if target.get("semantic_lifecycle") is None:
            target.pop("semantic_lifecycle", None)
    required_metric_snapshot = {
        transport: {
            "time_to_first_interim_ms_p95": payload.get("metrics_p95", {}).get("time_to_first_interim_ms"),
            "time_to_final_after_finalize_ms_p95": payload.get("metrics_p95", {}).get(
                "time_to_final_after_finalize_ms"
            ),
            "audio_send_queue_depth_p95_ms": payload.get("metrics_p95", {}).get(
                "audio_send_queue_depth_p95_ms"
            ),
            "asr_queue_delay_p95_ms": payload.get("metrics_p95", {}).get("asr_queue_delay_p95_ms"),
            "protocol_errors_p95": payload.get("metrics_p95", {}).get("protocol_errors"),
            "cpu_utilization_percent": payload.get("cpu_utilization_percent"),
        }
        for transport, payload in sorted(comparison.get("transports", {}).items())
    }
    required_benchmark_input_snapshot = {
        transport: {
            "audio": payload.get("audio") or {},
            "settings": payload.get("settings") or {},
            "service": payload.get("service") or {},
            "runs": payload.get("runs"),
        }
        for transport, payload in sorted(comparison.get("transports", {}).items())
    }
    required_diagnostic_snapshot = {
        transport: {
            "protocol_error_total": payload.get("diagnostics", {}).get("protocol_error_total"),
            "protocol_error_codes": payload.get("diagnostics", {}).get("protocol_error_codes", {}),
            "warning_total": payload.get("diagnostics", {}).get("warning_total"),
            "warning_codes": payload.get("diagnostics", {}).get("warning_codes", {}),
        }
        for transport, payload in sorted(comparison.get("transports", {}).items())
    }
    return {
        "kind": "local-stt-v1-raw-uds-decision",
        "status": decision["status"],
        "reason": decision["reason"],
        "next_action": decision["next_action"],
        "required_transports": comparison["required_transports"],
        "missing_transports": comparison["missing_transports"],
        "unexpected_transports": comparison["unexpected_transports"],
        "blocking_gaps": comparison["blocking_gaps"],
        "blocking_gap_count": len(comparison["blocking_gaps"]),
        "primary_metric": decision["primary_metric"],
        "comparison_baseline": decision["comparison_baseline"],
        "gate_passed": gate["passed"],
        "gate_blockers": gate["blockers"],
        "gate_blocker_count": decision["gate_blocker_count"],
        "required_first_interim_p95_win_ms": decision["required_first_interim_p95_win_ms"],
        "observed_first_interim_p95_win_ms": decision["observed_first_interim_p95_win_ms"],
        "observed_final_after_finalize_p95_delta_ms": decision[
            "observed_final_after_finalize_p95_delta_ms"
        ],
        "required_artifact_snapshot": required_artifact_snapshot,
        "required_target_snapshot": required_target_snapshot,
        "required_benchmark_input_snapshot": required_benchmark_input_snapshot,
        "required_metric_snapshot": required_metric_snapshot,
        "required_diagnostic_snapshot": required_diagnostic_snapshot,
        "run_count_coverage": comparison["run_count_coverage"],
        "cpu_utilization_coverage": comparison["cpu_utilization_coverage"],
        "raw_uds_vs_uds_ws_p95_deltas_ms": comparison["raw_uds_vs_uds_ws_p95_deltas_ms"],
        "raw_uds_leading_p95_metrics": decision["raw_uds_leading_p95_metrics"],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(
        args.artifacts,
        min_runs=args.min_runs,
        require_cpu_utilization=args.require_cpu_utilization,
        raw_uds_min_win_ms=args.raw_uds_min_win_ms,
    )
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    if args.markdown_output is not None:
        args.markdown_output.write_text(format_markdown_summary(comparison), encoding="utf8")
    if args.decision_output is not None:
        args.decision_output.write_text(
            json.dumps(raw_uds_decision_output(comparison), indent=2, sort_keys=True) + "\n",
            encoding="utf8",
        )
    return 1 if comparison_has_blocking_gaps(
        comparison,
        require_raw_uds_recommendation=args.require_raw_uds_recommendation,
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
