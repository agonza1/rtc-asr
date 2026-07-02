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


def _p95(summary: dict[str, Any], metric: str) -> float | None:
    bucket = summary.get(metric)
    if not isinstance(bucket, dict):
        return None
    value = bucket.get("p95")
    if value is None:
        return None
    return float(value)


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
            "metrics_p95": {metric: _p95(summary, metric) for metric in KEY_METRICS},
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

    return {
        "kind": "local-stt-v1-transport-comparison",
        "required_transports": list(REQUIRED_TRANSPORTS),
        "missing_transports": missing,
        "transports": by_transport,
        "raw_uds_vs_uds_ws_time_to_first_interim_p95_delta_ms": raw_vs_uds_delta_ms,
        "raw_uds_should_remain_experimental": raw_uds_experimental,
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
