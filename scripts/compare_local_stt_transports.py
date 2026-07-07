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
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(percentile)
    if value is None:
        return None
    return float(value)


def metric_percentiles(summary: dict[str, Any], metric: str) -> dict[str, float | None]:
    return {percentile: _percentile(summary, metric, percentile) for percentile in PERCENTILES}


def fastest_transport_by_metric(transports: dict[str, dict[str, Any]], metric: str) -> str | None:
    candidates: list[tuple[float, str]] = []
    for transport, payload in transports.items():
        value = payload.get("metrics_p95", {}).get(metric)
        if value is not None:
            candidates.append((float(value), transport))
    if not candidates:
        return None
    return min(candidates)[1]


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
    transports: dict[str, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(f"missing transport benchmark: {transport}" for transport in missing)
    reasons.extend(f"unexpected transport benchmark: {transport}" for transport in unexpected)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        reasons.extend(f"{transport} missing metric percentile: {metric_gap}" for metric_gap in metric_gaps)
    reasons.extend(run_gaps)
    reasons.extend(target_gaps)
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
        environment = artifact.get("environment") if isinstance(artifact.get("environment"), dict) else {}
        metrics = {metric: metric_percentiles(summary, metric) for metric in KEY_METRICS}
        metrics_p95 = {metric: metrics[metric]["p95"] for metric in KEY_METRICS}
        missing_metrics = missing_required_metrics(metrics)
        by_transport[transport] = {
            "artifact": str(path),
            **artifact_provenance(path),
            "url": artifact["target"].get("url"),
            "uds_path": artifact["target"].get("uds_path"),
            "runs": artifact.get("runs"),
            "metrics": metrics,
            "metrics_p95": metrics_p95,
            "missing_p95_metrics": missing_metrics,
            "protocol_error_free": protocol_error_free(metrics),
            "cpu_utilization_percent": environment.get("cpu_utilization_percent"),
        }

    missing = [transport for transport in REQUIRED_TRANSPORTS if transport not in by_transport]
    unexpected = sorted(transport for transport in by_transport if transport not in REQUIRED_TRANSPORTS)
    missing_metrics_by_transport = {
        transport: payload["missing_p95_metrics"]
        for transport, payload in by_transport.items()
        if payload["missing_p95_metrics"]
    }
    raw_vs_uds_deltas = raw_uds_vs_uds_p95_deltas(by_transport)
    raw_vs_uds_delta_ms = raw_vs_uds_deltas["time_to_first_interim_ms"]
    raw_vs_uds_final_after_finalize_delta_ms = raw_vs_uds_deltas["time_to_final_after_finalize_ms"]
    raw_uds_latency_experimental = raw_vs_uds_delta_ms is None or raw_vs_uds_delta_ms < raw_uds_min_win_ms
    fastest_first_interim_transport = fastest_transport_by_metric(by_transport, "time_to_first_interim_ms")
    fastest_final_after_finalize_transport = fastest_transport_by_metric(
        by_transport, "time_to_final_after_finalize_ms"
    )
    lowest_cpu_transport = lowest_cpu_utilization_transport(by_transport)
    missing_cpu_utilization = missing_cpu_utilization_transports(by_transport)
    cpu_coverage = cpu_utilization_coverage(by_transport)
    run_coverage = run_count_coverage(by_transport)
    run_gaps = run_count_gaps(by_transport, min_runs)
    target_gaps = target_field_gaps(by_transport)

    all_present_transports_protocol_error_free = all(
        transport["protocol_error_free"] for transport in by_transport.values()
    )
    recommendation_gate = raw_uds_recommendation_gate(
        missing=missing,
        unexpected=unexpected,
        missing_metrics=missing_metrics_by_transport,
        run_gaps=run_gaps,
        target_gaps=target_gaps,
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
        "lowest_cpu_utilization_percent_transport": lowest_cpu_transport,
        "missing_cpu_utilization_transports": missing_cpu_utilization,
        "cpu_utilization_coverage": cpu_coverage,
        "run_count_coverage": run_coverage,
        "minimum_required_runs": min_runs,
        "run_count_gaps": run_gaps,
        "target_field_gaps": target_gaps,
        "raw_uds_min_win_ms": raw_uds_min_win_ms,
        "raw_uds_recommendation_gate": recommendation_gate,
        "raw_uds_vs_uds_ws_p95_deltas_ms": raw_vs_uds_deltas,
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
        or not comparison["all_present_transports_protocol_error_free"]
        or (require_raw_uds_recommendation and comparison["raw_uds_should_remain_experimental"])
    )


def _format_optional_ms(value: float | None) -> str:
    if value is None:
        return "missing"
    return f"{value:.1f} ms"


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
