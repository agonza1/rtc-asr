#!/usr/bin/env python3
"""Build a static benchmark manifest for the GitHub Pages frontend."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RESULTS_DIR = Path("docs") / "benchmark-results"
DEFAULT_TRACKS_PATH = DEFAULT_RESULTS_DIR / "tracks.json"
STATUS_ORDER = {"validated": 0, "legacy": 1, "blocked": 2}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the benchmark site manifest")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing benchmark JSON artifacts",
    )
    parser.add_argument(
        "--tracks",
        type=Path,
        default=DEFAULT_TRACKS_PATH,
        help="JSON file listing tracked benchmark lanes",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS_DIR / "manifest.json",
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
    if compute:
        return f"{device} / {compute}"
    return str(device)


def track_runtime(track: dict[str, Any]) -> str:
    compute = track.get("compute")
    device = track.get("device") or "unknown"
    if compute:
        return f"{device} / {compute}"
    return str(device)


def benchmark_key(payload: dict[str, Any]) -> str:
    backend = payload.get("backend") or {}
    compute = (
        backend.get("compute_type")
        or backend.get("qwen_dtype")
        or backend.get("parakeet_dtype")
        or backend.get("ultravox_dtype")
        or "default"
    )
    device = backend.get("device") or "unknown"
    return f"asr::{backend.get('name', 'unknown')}::{backend.get('model', 'unknown')}::{device}::{compute}"


def track_key(track: dict[str, Any]) -> str:
    return "asr::{backend}::{model}::{device}::{compute}".format(
        backend=track.get("backend", "unknown"),
        model=track.get("model", "unknown"),
        device=track.get("device", "unknown"),
        compute=track.get("compute", "default"),
    )


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
        "character_error_rate_mean": accuracy.get(
            "character_error_rate_mean", accuracy.get("character_error_rate")
        ),
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


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sample_contract": {}, "tracks": []}
    return json.loads(path.read_text(encoding="utf-8"))


def build_artifact_history_entry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    entry = build_asr_entry(path, payload)
    entry["label"] = payload["backend"]["model"]
    return entry


def build_track_entry(track: dict[str, Any], artifact: tuple[str, Path, dict[str, Any]] | None) -> dict[str, Any]:
    entry = {
        "kind": "asr",
        "slug": track["slug"],
        "label": track["label"],
        "backend": track["backend"],
        "model": track["model"],
        "lane": track["lane"],
        "runtime": track_runtime(track),
        "status": track["status"],
        "status_detail": track["status_detail"],
        "target_sample_count": track["target_sample_count"],
        "run_command": track["run_command"],
        "measured_at": None,
        "sample_count": None,
        "artifact_path": None,
        "rest": {"mean_ms": None, "p95_ms": None, "rtf_mean": None},
        "streaming": {
            "partial_mean_ms": None,
            "partial_p95_ms": None,
            "final_mean_ms": None,
            "final_p95_ms": None,
        },
        "accuracy": {"word_error_rate_mean": None, "character_error_rate_mean": None},
    }
    if artifact is None:
        return entry

    _, path, payload = artifact
    measured = build_asr_entry(path, payload)
    entry.update(
        {
            "measured_at": measured["measured_at"],
            "sample_count": measured["sample_count"],
            "artifact_path": measured["artifact_path"],
            "rest": measured["rest"],
            "streaming": measured["streaming"],
            "accuracy": measured["accuracy"],
        }
    )
    return entry


def build_highlight(label: str, metric_key: tuple[str, str], entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if entry[metric_key[0]][metric_key[1]] is not None]
    if not candidates:
        return None
    best = min(candidates, key=lambda item: item[metric_key[0]][metric_key[1]])
    return {
        "label": label,
        "slug": best["slug"],
        "backend": best["backend"],
        "model": best["model"],
        "value": best[metric_key[0]][metric_key[1]],
        "artifact_path": best["artifact_path"],
    }


def build_accuracy_highlight(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        entry
        for entry in entries
        if entry["accuracy"]["word_error_rate_mean"] is not None
        and entry["accuracy"]["character_error_rate_mean"] is not None
    ]
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda item: (
            item["accuracy"]["word_error_rate_mean"],
            item["accuracy"]["character_error_rate_mean"],
            item["rest"]["mean_ms"] if item["rest"]["mean_ms"] is not None else float("inf"),
        ),
    )
    return {
        "label": "Lowest normalized WER",
        "slug": best["slug"],
        "backend": best["backend"],
        "model": best["model"],
        "value": best["accuracy"]["word_error_rate_mean"],
        "artifact_path": best["artifact_path"],
    }


def build_manifest(results_dir: Path, tracks_path: Path = DEFAULT_TRACKS_PATH) -> dict[str, Any]:
    latest: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    artifact_history: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name in {"manifest.json", tracks_path.name}:
            continue
        payload = load_payload(path)
        key = benchmark_key(payload)
        stamp = artifact_timestamp(path, payload)
        artifact_history.append(build_artifact_history_entry(path, payload))
        previous = latest.get(key)
        if previous is None or stamp > previous[0]:
            latest[key] = (stamp, path, payload)

    catalog = load_catalog(tracks_path)
    tracks = [build_track_entry(track, latest.get(track_key(track))) for track in catalog.get("tracks", [])]
    tracks.sort(
        key=lambda item: (
            STATUS_ORDER.get(item["status"], 99),
            item["rest"]["mean_ms"] is None,
            item["rest"]["mean_ms"] if item["rest"]["mean_ms"] is not None else float("inf"),
            item["label"],
        )
    )

    artifact_history.sort(
        key=lambda item: (
            item["measured_at"] is None,
            item["measured_at"] or "",
            item["artifact_path"],
        ),
        reverse=True,
    )

    artifact_backed = [track for track in tracks if track["artifact_path"]]
    validated_entries = [track for track in artifact_backed if track["status"] == "validated"]
    highlight_entries = validated_entries or artifact_backed
    asr_entries = sorted(
        artifact_backed,
        key=lambda item: (item["rest"]["mean_ms"] is None, item["rest"]["mean_ms"] or 0),
    )
    latest_measured_at = max((entry["measured_at"] for entry in artifact_backed), default=None)
    summary = {
        "asr_count": len(asr_entries),
        "tracked_count": len(tracks),
        "artifact_file_count": len(artifact_history),
        "validated_count": sum(1 for entry in tracks if entry["status"] == "validated"),
        "legacy_count": sum(1 for entry in tracks if entry["status"] == "legacy"),
        "blocked_count": sum(1 for entry in tracks if entry["status"] == "blocked"),
        "latest_measured_at": latest_measured_at,
        "sample_contract": catalog.get("sample_contract", {}),
        "highlights": {
            "fastest_rest": build_highlight("Fastest REST mean", ("rest", "mean_ms"), highlight_entries),
            "fastest_partial": build_highlight(
                "Fastest streaming partial mean", ("streaming", "partial_mean_ms"), highlight_entries
            ),
            "fastest_final": build_highlight(
                "Fastest streaming final mean", ("streaming", "final_mean_ms"), highlight_entries
            ),
            "best_accuracy": build_accuracy_highlight(highlight_entries),
        },
    }
    return {
        "generated_at": iso_now(),
        "summary": summary,
        "tracks": tracks,
        "artifacts": artifact_history,
        "asr_benchmarks": asr_entries,
    }


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args.results_dir, args.tracks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f"{json.dumps(manifest, indent=2)}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
