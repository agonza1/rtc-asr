#!/usr/bin/env python3
"""Build a simple static benchmark manifest for the GitHub Pages frontend."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the benchmark site manifest")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("docs") / "benchmark-results",
        help="Directory containing benchmark JSON artifacts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs") / "benchmark-results" / "manifest.json",
        help="Output manifest path",
    )
    return parser.parse_args()


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def artifact_timestamp(path: Path, payload: dict[str, Any]) -> str:
    environment = payload.get("environment") or {}
    date_utc = environment.get("date_utc")
    if isinstance(date_utc, str) and date_utc:
        return date_utc

    stem_parts = path.stem.rsplit("-", 3)
    if len(stem_parts) == 4:
        year, month, day = stem_parts[-3:]
        if all(part.isdigit() for part in (year, month, day)):
            return f"{year}-{month}-{day}T00:00:00Z"
    return "1970-01-01T00:00:00Z"


def runtime_label(payload: dict[str, Any]) -> str:
    backend = payload.get("backend") or {}
    device = backend.get("device") or "unknown"
    compute = (
        backend.get("compute_type")
        or backend.get("qwen_dtype")
        or backend.get("parakeet_dtype")
        or backend.get("ultravox_dtype")
    )
    benchmark = payload.get("benchmark") or {}
    task = benchmark.get("task")
    if task == "mlx-text-generation":
        model = payload.get("model") or {}
        runtime = model.get("runtime") or "mlx-lm"
        precision = model.get("precision") or "unknown precision"
        return f"{runtime} / {precision}"
    if compute:
        return f"{device} / {compute}"
    return str(device)


def benchmark_key(payload: dict[str, Any]) -> str:
    benchmark = payload.get("benchmark") or {}
    if benchmark.get("task") == "mlx-text-generation":
        model = payload.get("model") or {}
        return f"mlx-text::{model.get('id', 'unknown')}"
    backend = payload.get("backend") or {}
    return f"asr::{backend.get('name', 'unknown')}::{backend.get('model', 'unknown')}"



def sample_count(payload: dict[str, Any]) -> int:
    benchmark = payload.get("benchmark") or {}
    if benchmark.get("sample_count") is not None:
        return int(benchmark["sample_count"])
    rest = payload.get("rest") or {}
    if rest.get("sample_count") is not None:
        return int(rest["sample_count"])
    streaming = payload.get("streaming") or {}
    final_latencies = streaming.get("final_latencies_ms") or []
    if final_latencies:
        return len(final_latencies)
    return 1


def summarize_accuracy(rest: dict[str, Any], streaming: dict[str, Any]) -> dict[str, Any]:
    accuracy = rest.get("accuracy") or streaming.get("accuracy") or {}
    return {
        "word_error_rate_mean": accuracy.get("word_error_rate_mean", accuracy.get("word_error_rate")),
        "character_error_rate_mean": accuracy.get("character_error_rate_mean", accuracy.get("character_error_rate")),
    }

def build_asr_entry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    backend = payload["backend"]
    rest = payload["rest"]
    streaming = payload["streaming"]
    return {
        "kind": "asr",
        "backend": backend["name"],
        "model": backend["model"],
        "runtime": runtime_label(payload),
        "measured_at": artifact_timestamp(path, payload),
        "sample_count": sample_count(payload),
        "artifact_path": f"benchmark-results/{path.name}",
        "rest": {
            "mean_ms": rest.get("mean_ms"),
            "p95_ms": rest.get("p95_ms"),
            "rtf_mean": rest.get("rtf_mean"),
        },
        "streaming": {
            "partial_mean_ms": streaming.get("partial_mean_ms"),
            "partial_p95_ms": streaming.get("partial_p95_ms"),
            "final_mean_ms": streaming.get("final_mean_ms", streaming.get("final_ms")),
            "final_p95_ms": streaming.get("final_p95_ms", streaming.get("final_ms")),
        },
        "accuracy": summarize_accuracy(rest, streaming),
    }


def build_experiment_entry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    model = payload["model"]
    summary = payload["summary"]
    return {
        "kind": "experiment",
        "task": payload["benchmark"]["task"],
        "model": model["id"],
        "runtime": runtime_label(payload),
        "measured_at": artifact_timestamp(path, payload),
        "sample_count": sample_count(payload),
        "artifact_path": f"benchmark-results/{path.name}",
        "load": payload.get("load") or {},
        "summary": summary,
    }


def build_manifest(results_dir: Path) -> dict[str, Any]:
    latest: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    for path in sorted(results_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        payload = load_payload(path)
        key = benchmark_key(payload)
        stamp = artifact_timestamp(path, payload)
        previous = latest.get(key)
        if previous is None or stamp > previous[0]:
            latest[key] = (stamp, path, payload)

    asr_entries: list[dict[str, Any]] = []
    experiment_entries: list[dict[str, Any]] = []
    for _, path, payload in sorted(latest.values(), key=lambda item: item[0], reverse=True):
        benchmark = payload.get("benchmark") or {}
        if benchmark.get("task") == "mlx-text-generation":
            experiment_entries.append(build_experiment_entry(path, payload))
        else:
            asr_entries.append(build_asr_entry(path, payload))

    asr_entries.sort(key=lambda item: (item["rest"]["mean_ms"] is None, item["rest"]["mean_ms"] or 0))
    experiment_entries.sort(key=lambda item: item["measured_at"], reverse=True)
    return {
        "generated_at": iso_now(),
        "summary": {
            "asr_count": len(asr_entries),
            "experiment_count": len(experiment_entries),
        },
        "asr_benchmarks": asr_entries,
        "experiments": experiment_entries,
    }


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args.results_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f"{json.dumps(manifest, indent=2)}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
