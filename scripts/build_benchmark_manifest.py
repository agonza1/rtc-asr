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


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def invert_score(value: float | None, floor: float, ceiling: float) -> float | None:
    if value is None:
        return None
    if ceiling <= floor:
        return 100.0
    normalized = (value - floor) / (ceiling - floor)
    return round(clamp((1 - normalized) * 100), 1)


def average_scores(*values: float | None) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return round(sum(present) / len(present), 1)


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
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero when the checked-in manifest does not match generated output",
    )
    return parser.parse_args()


def render_manifest(manifest: dict[str, Any]) -> str:
    return f"{json.dumps(manifest, indent=2)}\n"


def comparable_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    comparable = dict(manifest)
    comparable.pop("generated_at", None)
    return comparable


def manifests_match(current: dict[str, Any], generated: dict[str, Any]) -> bool:
    return comparable_manifest(current) == comparable_manifest(generated)


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


def extract_benchmark_contract(payload: dict[str, Any]) -> dict[str, Any]:
    benchmark = payload.get("benchmark") or {}
    streaming = payload.get("streaming") or {}
    ready = streaming.get("ready") or {}
    contract = {
        "chunk_ms": benchmark.get("chunk_ms", streaming.get("chunk_ms")),
        "partial_interval_chunks": benchmark.get("partial_interval_chunks", ready.get("partial_interval_chunks")),
        "partial_window_seconds": benchmark.get("partial_window_seconds", ready.get("partial_window_seconds")),
        "binary_frames": benchmark.get("binary_frames", streaming.get("binary_frames")),
    }
    partial_event_timeout_seconds = benchmark.get(
        "partial_event_timeout_seconds",
        streaming.get("partial_event_timeout_seconds"),
    )
    if partial_event_timeout_seconds is not None:
        contract["partial_event_timeout_seconds"] = partial_event_timeout_seconds
    return contract


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
    contract = extract_benchmark_contract(payload)
    return {
        "kind": "asr",
        "backend": backend["name"],
        "model": backend["model"],
        "runtime": runtime_label(payload),
        "measured_at": artifact_timestamp(path, payload),
        "sample_count": sample_count(payload),
        "artifact_path": f"benchmark-results/{path.name}",
        "contract": contract,
        "rest": {
            "mean_ms": rest.get("mean_ms"),
            "p95_ms": rest.get("p95_ms"),
            "rtf_mean": rest.get("rtf_mean"),
        },
        "streaming": {
            "partial_mean_ms": streaming.get("partial_mean_ms"),
            "partial_p95_ms": streaming.get("partial_p95_ms"),
            "first_partial_end_to_end_mean_ms": streaming.get("first_partial_end_to_end_mean_ms", streaming.get("first_partial_end_to_end_ms")),
            "first_partial_end_to_end_p95_ms": streaming.get("first_partial_end_to_end_p95_ms", streaming.get("first_partial_end_to_end_ms")),
            "partial_gap_mean_ms": streaming.get("partial_gap_mean_ms"),
            "partial_gap_p95_ms": streaming.get("partial_gap_p95_ms"),
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


def derive_track_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    rest = entry["rest"]
    streaming = entry["streaming"]
    accuracy = entry["accuracy"]
    target_sample_count = entry.get("target_sample_count") or 0
    actual_sample_count = entry.get("sample_count") or 0

    rest_jitter_ratio = None
    if rest.get("mean_ms") and rest.get("p95_ms"):
        rest_jitter_ratio = round(rest["p95_ms"] / rest["mean_ms"], 3)

    partial_jitter_ratio = None
    if streaming.get("partial_mean_ms") and streaming.get("partial_p95_ms"):
        partial_jitter_ratio = round(streaming["partial_p95_ms"] / streaming["partial_mean_ms"], 3)

    final_jitter_ratio = None
    if streaming.get("final_mean_ms") and streaming.get("final_p95_ms"):
        final_jitter_ratio = round(streaming["final_p95_ms"] / streaming["final_mean_ms"], 3)

    sample_coverage_pct = None
    if target_sample_count:
        sample_coverage_pct = round(clamp((actual_sample_count / target_sample_count) * 100), 1)

    latency_score = average_scores(
        invert_score(rest.get("mean_ms"), 250, 6000),
        invert_score(rest.get("p95_ms"), 350, 7000),
    )
    live_caption_score = average_scores(
        invert_score(streaming.get("first_partial_end_to_end_mean_ms"), 250, 5000),
        invert_score(streaming.get("partial_mean_ms"), 100, 4000),
        invert_score(streaming.get("partial_p95_ms"), 150, 6500),
    )
    finalization_score = average_scores(
        invert_score(streaming.get("final_mean_ms"), 200, 5000),
        invert_score(streaming.get("final_p95_ms"), 300, 7000),
    )
    stability_score = average_scores(
        invert_score(rest_jitter_ratio, 1.0, 5.0),
        invert_score(partial_jitter_ratio, 1.0, 6.0),
        invert_score(final_jitter_ratio, 1.0, 5.0),
    )
    efficiency_score = invert_score(rest.get("rtf_mean"), 0.03, 1.0)
    accuracy_score = invert_score(accuracy.get("word_error_rate_mean"), 0.0, 0.35)

    status_confidence = {
        "validated": 100.0,
        "legacy": 70.0,
        "blocked": 25.0,
    }.get(entry.get("status"), 50.0)
    confidence_score = average_scores(sample_coverage_pct, status_confidence)

    weighted_scores = [
        (latency_score, 0.28),
        (live_caption_score, 0.2),
        (finalization_score, 0.18),
        (stability_score, 0.14),
        (efficiency_score, 0.1),
        (accuracy_score, 0.1),
    ]
    weighted_total = sum(value * weight for value, weight in weighted_scores if value is not None)
    applied_weight = sum(weight for value, weight in weighted_scores if value is not None)
    overall_score = round(weighted_total / applied_weight, 1) if applied_weight else None
    if overall_score is not None and entry.get("status") == "legacy":
        overall_score = round(overall_score * 0.94, 1)
    if overall_score is not None and entry.get("status") == "blocked":
        overall_score = round(overall_score * 0.55, 1)

    return {
        "latency_score": latency_score,
        "live_caption_score": live_caption_score,
        "finalization_score": finalization_score,
        "stability_score": stability_score,
        "efficiency_score": efficiency_score,
        "accuracy_score": accuracy_score,
        "overall_score": overall_score,
        "confidence_score": confidence_score,
        "sample_coverage_pct": sample_coverage_pct,
        "rest_jitter_ratio": rest_jitter_ratio,
        "partial_jitter_ratio": partial_jitter_ratio,
        "final_jitter_ratio": final_jitter_ratio,
    }


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
        "contract": {
            "chunk_ms": None,
            "partial_interval_chunks": None,
            "partial_window_seconds": None,
            "binary_frames": None,
        },
        "rest": {"mean_ms": None, "p95_ms": None, "rtf_mean": None},
        "streaming": {
            "partial_mean_ms": None,
            "partial_p95_ms": None,
            "first_partial_end_to_end_mean_ms": None,
            "first_partial_end_to_end_p95_ms": None,
            "partial_gap_mean_ms": None,
            "partial_gap_p95_ms": None,
            "final_mean_ms": None,
            "final_p95_ms": None,
        },
        "accuracy": {"word_error_rate_mean": None, "character_error_rate_mean": None},
    }
    if artifact is not None:
        _, path, payload = artifact
        measured = build_asr_entry(path, payload)
        entry.update(
            {
                "measured_at": measured["measured_at"],
                "sample_count": measured["sample_count"],
                "artifact_path": measured["artifact_path"],
                "contract": measured["contract"],
                "rest": measured["rest"],
                "streaming": measured["streaming"],
                "accuracy": measured["accuracy"],
            }
        )

    entry["derived"] = derive_track_metrics(entry)
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


def build_derived_highlight(label: str, metric: str, entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [entry for entry in entries if entry["derived"].get(metric) is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda item: item["derived"][metric])
    return {
        "label": label,
        "slug": best["slug"],
        "backend": best["backend"],
        "model": best["model"],
        "value": best["derived"][metric],
        "artifact_path": best["artifact_path"],
    }


def build_metric_range(entries: list[dict[str, Any]], getter) -> dict[str, float] | None:
    values = [getter(entry) for entry in entries if getter(entry) is not None]
    if not values:
        return None
    return {"min": round(min(values), 3), "max": round(max(values), 3)}


def build_manifest(results_dir: Path, tracks_path: Path = DEFAULT_TRACKS_PATH) -> dict[str, Any]:
    latest: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    artifacts_by_name: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    artifact_history: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name in {"manifest.json", tracks_path.name}:
            continue
        payload = load_payload(path)
        key = benchmark_key(payload)
        stamp = artifact_timestamp(path, payload)
        artifact_history.append(build_artifact_history_entry(path, payload))
        artifacts_by_name[path.name] = (stamp, path, payload)
        previous = latest.get(key)
        if previous is None or stamp > previous[0]:
            latest[key] = (stamp, path, payload)

    catalog = load_catalog(tracks_path)
    tracks = [
        build_track_entry(
            track,
            artifacts_by_name.get(track.get("artifact")) if track.get("artifact") else latest.get(track_key(track)),
        )
        for track in catalog.get("tracks", [])
    ]
    tracks.sort(
        key=lambda item: (
            STATUS_ORDER.get(item["status"], 99),
            item["derived"]["overall_score"] is None,
            -(item["derived"]["overall_score"] or -1),
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
        key=lambda item: (
            item["derived"]["overall_score"] is None,
            -(item["derived"]["overall_score"] or -1),
            item["rest"]["mean_ms"] is None,
            item["rest"]["mean_ms"] or float("inf"),
        ),
    )
    latest_measured_at = max((entry["measured_at"] for entry in artifact_backed), default=None)

    ranges = {
        "rest_mean_ms": build_metric_range(artifact_backed, lambda entry: entry["rest"]["mean_ms"]),
        "partial_mean_ms": build_metric_range(artifact_backed, lambda entry: entry["streaming"]["partial_mean_ms"]),
        "first_partial_end_to_end_mean_ms": build_metric_range(artifact_backed, lambda entry: entry["streaming"]["first_partial_end_to_end_mean_ms"]),
        "partial_gap_mean_ms": build_metric_range(artifact_backed, lambda entry: entry["streaming"]["partial_gap_mean_ms"]),
        "final_mean_ms": build_metric_range(artifact_backed, lambda entry: entry["streaming"]["final_mean_ms"]),
        "rtf_mean": build_metric_range(artifact_backed, lambda entry: entry["rest"]["rtf_mean"]),
        "wer": build_metric_range(artifact_backed, lambda entry: entry["accuracy"]["word_error_rate_mean"]),
        "overall_score": build_metric_range(artifact_backed, lambda entry: entry["derived"]["overall_score"]),
    }

    summary = {
        "asr_count": len(asr_entries),
        "tracked_count": len(tracks),
        "artifact_file_count": len(artifact_history),
        "validated_count": sum(1 for entry in tracks if entry["status"] == "validated"),
        "legacy_count": sum(1 for entry in tracks if entry["status"] == "legacy"),
        "blocked_count": sum(1 for entry in tracks if entry["status"] == "blocked"),
        "latest_measured_at": latest_measured_at,
        "sample_contract": catalog.get("sample_contract", {}),
        "backend_count": len({entry["backend"] for entry in tracks}),
        "lane_count": len({entry["lane"] for entry in tracks}),
        "ranges": ranges,
        "highlights": {
            "fastest_rest": build_highlight("Fastest REST mean", ("rest", "mean_ms"), highlight_entries),
            "fastest_partial": build_highlight(
                "Fastest streaming partial mean", ("streaming", "partial_mean_ms"), highlight_entries
            ),
            "fastest_first_partial": build_highlight(
                "Fastest first visible partial", ("streaming", "first_partial_end_to_end_mean_ms"), highlight_entries
            ),
            "tightest_partial_cadence": build_highlight(
                "Tightest partial cadence", ("streaming", "partial_gap_mean_ms"), highlight_entries
            ),
            "fastest_final": build_highlight(
                "Fastest streaming final mean", ("streaming", "final_mean_ms"), highlight_entries
            ),
            "best_accuracy": build_accuracy_highlight(highlight_entries),
            "best_overall": build_derived_highlight("Best overall benchmark balance", "overall_score", highlight_entries),
            "best_live_caption": build_derived_highlight(
                "Best live caption score", "live_caption_score", highlight_entries
            ),
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
    rendered = render_manifest(manifest)

    if args.check:
        if not args.output.exists():
            raise SystemExit(f"Manifest is missing: {args.output}")
        current = json.loads(args.output.read_text(encoding="utf-8"))
        if not manifests_match(current, manifest):
            raise SystemExit(
                f"Manifest is stale: {args.output}. Run scripts/build_benchmark_manifest.py to regenerate it."
            )
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
