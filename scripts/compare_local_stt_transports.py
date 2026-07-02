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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 transport benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
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


def recommendation_text(*, missing: list[str], raw_vs_uds_delta_ms: float | None, raw_uds_experimental: bool) -> str:
    if missing:
        return "Run the missing transport benchmarks before comparing TCP, UDS websocket, and raw UDS paths."
    if raw_vs_uds_delta_ms is None:
        return "Raw UDS and UDS websocket first-interim P95 metrics were unavailable; keep raw UDS experimental."
    if raw_uds_experimental:
        return "Keep raw UDS experimental until it beats UDS websocket first-interim P95 by at least 5 ms."
    return "Raw UDS has a measurable first-interim P95 win; consider it for the next adapter prototype."


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
        by_transport[transport] = {
            "artifact": str(path),
            "url": artifact["target"].get("url"),
            "uds_path": artifact["target"].get("uds_path"),
            "runs": artifact.get("runs"),
            "metrics": {metric: metric_percentiles(summary, metric) for metric in KEY_METRICS},
            "metrics_p95": {metric: _percentile(summary, metric, "p95") for metric in KEY_METRICS},
            "cpu_utilization_percent": environment.get("cpu_utilization_percent"),
        }

    missing = [transport for transport in REQUIRED_TRANSPORTS if transport not in by_transport]
    raw_p95 = by_transport.get("raw_uds", {}).get("metrics_p95", {}).get("time_to_first_interim_ms")
    uds_p95 = by_transport.get("uds_ws", {}).get("metrics_p95", {}).get("time_to_first_interim_ms")
    raw_vs_uds_delta_ms = None
    raw_uds_experimental = True
    if raw_p95 is not None and uds_p95 is not None:
        raw_vs_uds_delta_ms = round(float(uds_p95) - float(raw_p95), 1)
        raw_uds_experimental = raw_vs_uds_delta_ms < 5.0
    fastest_first_interim_transport = fastest_transport_by_metric(by_transport, "time_to_first_interim_ms")

    return {
        "kind": "local-stt-v1-transport-comparison",
        "required_transports": list(REQUIRED_TRANSPORTS),
        "missing_transports": missing,
        "transports": by_transport,
        "fastest_time_to_first_interim_p95_transport": fastest_first_interim_transport,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_should_remain_experimental": raw_uds_experimental,
        "recommendation": recommendation_text(
            missing=missing,
            raw_vs_uds_delta_ms=raw_vs_uds_delta_ms,
            raw_uds_experimental=raw_uds_experimental,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(args.artifacts)
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    return 1 if comparison["missing_transports"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
