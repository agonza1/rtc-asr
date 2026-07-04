from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_TRANSPORTS = ("tcp_ws", "uds_ws", "raw_uds")
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
    "protocol_errors": ("p95",),
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 transport benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
    parser.add_argument(
        "--require-raw-uds-recommendation",
        action="store_true",
        help="Exit non-zero unless raw UDS clears the recommendation gate",
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


def protocol_error_free(metrics_p95: dict[str, float | None]) -> bool:
    protocol_errors = metrics_p95.get("protocol_errors")
    return protocol_errors is not None and protocol_errors == 0.0


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
    raw_vs_uds_delta_ms: float | None,
    raw_uds_experimental: bool,
    all_present_transports_protocol_error_free: bool,
    missing_metrics: dict[str, list[str]],
) -> str:
    if missing:
        return "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."
    if missing_metrics:
        return "Re-run transport benchmarks with the full required metric set before recommending raw UDS."
    if not all_present_transports_protocol_error_free:
        return "Keep raw UDS experimental until all present transport benchmarks are protocol-error free."
    if raw_vs_uds_delta_ms is None:
        return "Raw UDS and UDS websocket first-interim P95 metrics were unavailable; keep raw UDS experimental."
    if raw_uds_experimental:
        return "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms."
    return "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


def blocking_gap_reasons(
    *,
    missing: list[str],
    missing_metrics: dict[str, list[str]],
    transports: dict[str, dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    reasons.extend(f"missing transport benchmark: {transport}" for transport in missing)
    for transport, metric_gaps in sorted(missing_metrics.items()):
        reasons.extend(f"{transport} missing metric percentile: {metric_gap}" for metric_gap in metric_gaps)
    for transport, payload in sorted(transports.items()):
        if not payload["protocol_error_free"]:
            protocol_errors = payload.get("metrics_p95", {}).get("protocol_errors")
            reasons.append(f"{transport} protocol_errors p95 is {protocol_errors}")
    return reasons


def compare_artifacts(paths: list[Path]) -> dict[str, Any]:
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
            "url": artifact["target"].get("url"),
            "uds_path": artifact["target"].get("uds_path"),
            "runs": artifact.get("runs"),
            "metrics": metrics,
            "metrics_p95": metrics_p95,
            "missing_p95_metrics": missing_metrics,
            "protocol_error_free": protocol_error_free(metrics_p95),
            "cpu_utilization_percent": environment.get("cpu_utilization_percent"),
        }

    missing = [transport for transport in REQUIRED_TRANSPORTS if transport not in by_transport]
    missing_metrics_by_transport = {
        transport: payload["missing_p95_metrics"]
        for transport, payload in by_transport.items()
        if payload["missing_p95_metrics"]
    }
    raw_p95 = by_transport.get("raw_uds", {}).get("metrics_p95", {}).get("time_to_first_interim_ms")
    uds_p95 = by_transport.get("uds_ws", {}).get("metrics_p95", {}).get("time_to_first_interim_ms")
    raw_vs_uds_delta_ms = None
    raw_uds_latency_experimental = True
    if raw_p95 is not None and uds_p95 is not None:
        raw_vs_uds_delta_ms = round(float(uds_p95) - float(raw_p95), 1)
        raw_uds_latency_experimental = raw_vs_uds_delta_ms < 5.0
    fastest_first_interim_transport = fastest_transport_by_metric(by_transport, "time_to_first_interim_ms")
    fastest_final_after_finalize_transport = fastest_transport_by_metric(
        by_transport, "time_to_final_after_finalize_ms"
    )
    lowest_cpu_transport = lowest_cpu_utilization_transport(by_transport)
    missing_cpu_utilization = missing_cpu_utilization_transports(by_transport)

    all_present_transports_protocol_error_free = all(
        transport["protocol_error_free"] for transport in by_transport.values()
    )
    raw_uds_experimental = bool(
        missing
        or missing_metrics_by_transport
        or not all_present_transports_protocol_error_free
        or raw_uds_latency_experimental
    )

    return {
        "kind": "local-stt-v1-transport-comparison",
        "required_transports": list(REQUIRED_TRANSPORTS),
        "missing_transports": missing,
        "transports": by_transport,
        "fastest_time_to_first_interim_p95_transport": fastest_first_interim_transport,
        "fastest_time_to_final_after_finalize_p95_transport": fastest_final_after_finalize_transport,
        "lowest_cpu_utilization_percent_transport": lowest_cpu_transport,
        "missing_cpu_utilization_transports": missing_cpu_utilization,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_should_remain_experimental": raw_uds_experimental,
        "all_present_transports_protocol_error_free": all_present_transports_protocol_error_free,
        "missing_p95_metrics_by_transport": missing_metrics_by_transport,
        "blocking_gaps": blocking_gap_reasons(
            missing=missing,
            missing_metrics=missing_metrics_by_transport,
            transports=by_transport,
        ),
        "recommendation": recommendation_text(
            missing=missing,
            raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
            raw_uds_experimental=raw_uds_experimental,
            all_present_transports_protocol_error_free=all_present_transports_protocol_error_free,
            missing_metrics=missing_metrics_by_transport,
        ),
    }


def comparison_has_blocking_gaps(
    comparison: dict[str, Any], *, require_raw_uds_recommendation: bool = False
) -> bool:
    return bool(
        comparison["missing_transports"]
        or comparison["missing_p95_metrics_by_transport"]
        or not comparison["all_present_transports_protocol_error_free"]
        or (require_raw_uds_recommendation and comparison["raw_uds_should_remain_experimental"])
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(args.artifacts)
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    return 1 if comparison_has_blocking_gaps(
        comparison,
        require_raw_uds_recommendation=args.require_raw_uds_recommendation,
    ) else 0


if __name__ == "__main__":
    raise SystemExit(main())
