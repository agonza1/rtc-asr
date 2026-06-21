#!/usr/bin/env python3
"""Build a static benchmark manifest for the GitHub Pages frontend."""

from __future__ import annotations

import argparse
import hashlib
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
    audio = payload.get("audio") or {}
    integration = payload.get("integration") or {}
    bridge = streaming.get("bridge") or {}
    contract = {
        "chunk_ms": benchmark.get("chunk_ms", streaming.get("chunk_ms")),
        "partial_interval_chunks": benchmark.get("partial_interval_chunks", ready.get("partial_interval_chunks")),
        "partial_window_seconds": benchmark.get("partial_window_seconds", ready.get("partial_window_seconds")),
        "binary_frames": benchmark.get("binary_frames", streaming.get("binary_frames")),
        "sample_rate": audio.get("sample_rate", ready.get("sample_rate")),
        "live_metrics_comparable": bool(streaming.get("live_metrics_comparable", False)),
    }
    transport = first_defined(streaming.get("transport"), benchmark.get("mode"), integration.get("transport"))
    if transport is not None:
        contract["transport"] = transport
    protocol = first_defined(bridge.get("protocol"), integration.get("protocol"))
    if protocol is not None:
        contract["protocol"] = protocol
    path = first_defined(
        bridge.get("path"),
        integration.get("path"),
        "/v1/stt/stream" if transport == "v1-stt-stream" else "/ws/stream" if transport in {"direct", "ws/stream"} else None,
    )
    if path is not None:
        contract["path"] = path
    max_buffer_seconds = benchmark.get("max_buffer_seconds", streaming.get("max_buffer_seconds"))
    if max_buffer_seconds is not None:
        contract["max_buffer_seconds"] = max_buffer_seconds
    source_frame_ms = benchmark.get("source_frame_ms", streaming.get("source_frame_ms"))
    if source_frame_ms is not None:
        contract["source_frame_ms"] = source_frame_ms
    aggregation_ms = benchmark.get("aggregation_ms", streaming.get("aggregation_ms"))
    if aggregation_ms is not None:
        contract["aggregation_ms"] = aggregation_ms
    partial_interval_ms = benchmark.get("partial_interval_ms", streaming.get("partial_interval_ms"))
    if partial_interval_ms is not None:
        contract["partial_interval_ms"] = partial_interval_ms
    simulate_realtime = benchmark.get("simulate_realtime", streaming.get("simulate_realtime"))
    if simulate_realtime is not None:
        contract["simulate_realtime"] = simulate_realtime
    partial_event_timeout_seconds = benchmark.get(
        "partial_event_timeout_seconds",
        streaming.get("partial_event_timeout_seconds"),
    )
    if partial_event_timeout_seconds is not None:
        contract["partial_event_timeout_seconds"] = partial_event_timeout_seconds
    final_event_timeout_seconds = benchmark.get(
        "final_event_timeout_seconds",
        streaming.get("final_event_timeout_seconds"),
    )
    if final_event_timeout_seconds is not None:
        contract["final_event_timeout_seconds"] = final_event_timeout_seconds
    return contract


def first_defined(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and value == "":
            continue
        if isinstance(value, (list, dict)) and not value:
            continue
        return value
    return None


def extract_system_signals(payload: dict[str, Any]) -> dict[str, Any]:
    environment = payload.get("environment") or {}
    system = payload.get("system") or {}
    metrics = payload.get("metrics") or {}
    return {
        "platform": first_defined(environment.get("platform"), system.get("platform")),
        "processor": first_defined(environment.get("processor"), environment.get("machine"), system.get("processor")),
        "python": first_defined(environment.get("python"), system.get("python")),
        "cpu_logical_cores": first_defined(
            environment.get("cpu_logical_cores"),
            system.get("cpu_logical_cores"),
            metrics.get("cpu_logical_cores"),
        ),
        "accelerator": first_defined(
            environment.get("accelerator"),
            environment.get("gpu"),
            system.get("accelerator"),
            system.get("gpu"),
            metrics.get("accelerator"),
            metrics.get("gpu"),
        ),
        "memory_total_mb": first_defined(
            environment.get("memory_total_mb"),
            system.get("memory_total_mb"),
            metrics.get("memory_total_mb"),
        ),
        "process_rss_mb": first_defined(
            environment.get("process_rss_mb"),
            system.get("process_rss_mb"),
            metrics.get("process_rss_mb"),
        ),
        "peak_rss_mb": first_defined(
            environment.get("peak_rss_mb"),
            system.get("peak_rss_mb"),
            metrics.get("peak_rss_mb"),
        ),
        "cpu_utilization_percent": first_defined(
            environment.get("cpu_utilization_percent"),
            system.get("cpu_utilization_percent"),
            metrics.get("cpu_utilization_percent"),
        ),
        "package_power_watts": first_defined(
            environment.get("package_power_watts"),
            system.get("package_power_watts"),
            metrics.get("package_power_watts"),
        ),
        "thermal_peak_celsius": first_defined(
            environment.get("thermal_peak_celsius"),
            system.get("thermal_peak_celsius"),
            metrics.get("thermal_peak_celsius"),
        ),
        "thermal_observation": first_defined(
            environment.get("thermal_observation"),
            environment.get("thermal_state"),
            system.get("thermal_observation"),
            system.get("thermal_state"),
            metrics.get("thermal_observation"),
            metrics.get("thermal_state"),
        ),
    }


def accuracy_is_publishable(entry: dict[str, Any]) -> bool:
    return False



def summarize_accuracy(rest: dict[str, Any], streaming: dict[str, Any]) -> dict[str, Any]:
    accuracy = rest.get("accuracy") or streaming.get("accuracy") or {}
    return {
        "word_error_rate_mean": accuracy.get("word_error_rate_mean", accuracy.get("word_error_rate")),
        "character_error_rate_mean": accuracy.get(
            "character_error_rate_mean", accuracy.get("character_error_rate")
        ),
    }


def summarize_warnings(payload: dict[str, Any]) -> dict[str, Any]:
    summary = payload.get("summary") or {}
    raw_samples = payload.get("samples") or []
    samples = [sample for sample in raw_samples if isinstance(sample, dict)] if isinstance(raw_samples, list) else []
    warning_summary = summary.get("warnings_received")
    summary_warning_codes = summary.get("warning_codes") or []
    warning_codes = sorted(
        {
            code
            for sample in samples
            for code in sample.get("warning_codes", [])
            if isinstance(code, str) and code
        }
        | {code for code in summary_warning_codes if isinstance(code, str) and code}
    )

    counts = [sample.get("warnings_received") for sample in samples]
    numeric_counts = [value for value in counts if isinstance(value, (int, float))]
    if numeric_counts:
        total = sum(numeric_counts)
    elif isinstance(warning_summary, (int, float)):
        total = warning_summary
    else:
        total = None

    return {
        "received_total": total,
        "codes": warning_codes,
    }


def build_asr_entry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    backend = payload["backend"]
    rest = payload["rest"]
    streaming = payload["streaming"]
    contract = extract_benchmark_contract(payload)
    artifact_bytes = path.read_bytes()
    return {
        "kind": "asr",
        "backend": backend["name"],
        "model": backend["model"],
        "runtime": runtime_label(payload),
        "measured_at": artifact_timestamp(path, payload),
        "sample_count": sample_count(payload),
        "artifact_path": f"benchmark-results/{path.name}",
        "artifact_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "artifact_size_bytes": len(artifact_bytes),
        "system": extract_system_signals(payload),
        "contract": contract,
        "rest": {
            "mean_ms": rest.get("mean_ms"),
            "p95_ms": rest.get("p95_ms"),
            "rtf_mean": rest.get("rtf_mean"),
        },
        "streaming": {
            "transport": contract.get("transport"),
            "live_metrics_comparable": contract.get("live_metrics_comparable", False),
            "partial_mean_ms": streaming.get("partial_mean_ms"),
            "partial_p95_ms": streaming.get("partial_p95_ms"),
            "first_partial_end_to_end_mean_ms": streaming.get("first_partial_end_to_end_mean_ms", streaming.get("first_partial_end_to_end_ms")),
            "first_partial_end_to_end_p95_ms": streaming.get("first_partial_end_to_end_p95_ms", streaming.get("first_partial_end_to_end_ms")),
            "partial_gap_mean_ms": streaming.get("partial_gap_mean_ms"),
            "partial_gap_p95_ms": streaming.get("partial_gap_p95_ms"),
            "partial_transcript_churn_char_mean": streaming.get("partial_transcript_churn_char_mean"),
            "partial_transcript_churn_word_mean": streaming.get("partial_transcript_churn_word_mean"),
            "late_partial_events": streaming.get("late_partial_events"),
            "late_partial_ratio": streaming.get("late_partial_ratio"),
            "final_mean_ms": streaming.get("time_to_final_from_audio_end_mean_ms", streaming.get("final_mean_ms", streaming.get("time_to_final_from_audio_end_ms", streaming.get("final_ms")))),
            "final_p95_ms": streaming.get("time_to_final_from_audio_end_p95_ms", streaming.get("final_p95_ms", streaming.get("time_to_final_from_audio_end_ms", streaming.get("final_ms")))),
        },
        "warnings": summarize_warnings(payload),
        "accuracy": summarize_accuracy(rest, streaming),
    }


def load_catalog(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sample_contract": {}, "tracks": []}
    return json.loads(path.read_text(encoding="utf-8"))


def is_asr_payload(payload: dict[str, Any]) -> bool:
    kind = payload.get("kind")
    if kind in (None, "asr"):
        return True
    return all(key in payload for key in ("backend", "rest", "streaming"))


def build_artifact_history_entry(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    entry = build_asr_entry(path, payload)
    entry["label"] = payload["backend"]["model"]
    return entry


def derive_track_metrics(entry: dict[str, Any]) -> dict[str, Any]:
    rest = entry["rest"]
    streaming = entry["streaming"]
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
        invert_score(streaming.get("partial_gap_mean_ms"), 80, 1500),
        invert_score(streaming.get("late_partial_ratio"), 0.0, 0.5),
    )
    partial_backlog_score = average_scores(
        invert_score(streaming.get("partial_mean_ms"), 100, 4000),
        invert_score(streaming.get("partial_p95_ms"), 150, 6500),
        invert_score(streaming.get("late_partial_ratio"), 0.0, 0.5),
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
        "partial_backlog_score": partial_backlog_score,
        "finalization_score": finalization_score,
        "stability_score": stability_score,
        "efficiency_score": efficiency_score,
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
        "official_wer_reference": track.get("official_wer_reference"),
        "measured_at": None,
        "sample_count": None,
        "artifact_path": None,
        "artifact_sha256": None,
        "artifact_size_bytes": None,
        "system": {
            "platform": None,
            "processor": None,
            "python": None,
            "cpu_logical_cores": None,
            "accelerator": None,
            "memory_total_mb": None,
            "peak_rss_mb": None,
            "cpu_utilization_percent": None,
            "package_power_watts": None,
            "thermal_peak_celsius": None,
            "thermal_observation": None,
        },
        "contract": {
            "chunk_ms": None,
            "partial_interval_chunks": None,
            "partial_window_seconds": None,
            "binary_frames": None,
            "live_metrics_comparable": False,
        },
        "rest": {"mean_ms": None, "p95_ms": None, "rtf_mean": None},
        "streaming": {
            "transport": None,
            "live_metrics_comparable": False,
            "partial_mean_ms": None,
            "partial_p95_ms": None,
            "first_partial_end_to_end_mean_ms": None,
            "first_partial_end_to_end_p95_ms": None,
            "partial_gap_mean_ms": None,
            "partial_gap_p95_ms": None,
            "late_partial_events": None,
            "late_partial_ratio": None,
            "final_mean_ms": None,
            "final_p95_ms": None,
        },
        "warnings": {"received_total": None, "codes": []},
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
                "artifact_sha256": measured["artifact_sha256"],
                "artifact_size_bytes": measured["artifact_size_bytes"],
                "system": measured["system"],
                "contract": measured["contract"],
                "rest": measured["rest"],
                "streaming": measured["streaming"],
                "warnings": measured["warnings"],
            }
        )

    if not accuracy_is_publishable(entry):
        entry["accuracy"] = {"word_error_rate_mean": None, "character_error_rate_mean": None}

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


def build_system_coverage(entries: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "memory_total_mb_count": sum(1 for entry in entries if entry["system"].get("memory_total_mb") is not None),
        "peak_rss_mb_count": sum(1 for entry in entries if entry["system"].get("peak_rss_mb") is not None),
        "accelerator_count": sum(1 for entry in entries if entry["system"].get("accelerator") is not None),
        "cpu_utilization_percent_count": sum(
            1 for entry in entries if entry["system"].get("cpu_utilization_percent") is not None
        ),
        "package_power_watts_count": sum(1 for entry in entries if entry["system"].get("package_power_watts") is not None),
        "thermal_peak_celsius_count": sum(1 for entry in entries if entry["system"].get("thermal_peak_celsius") is not None),
        "thermal_observation_count": sum(1 for entry in entries if entry["system"].get("thermal_observation") is not None),
    }


def build_manifest(results_dir: Path, tracks_path: Path = DEFAULT_TRACKS_PATH) -> dict[str, Any]:
    latest: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    artifacts_by_name: dict[str, tuple[str, Path, dict[str, Any]]] = {}
    artifact_history: list[dict[str, Any]] = []
    for path in sorted(results_dir.glob("*.json")):
        if path.name in {"manifest.json", tracks_path.name}:
            continue
        payload = load_payload(path)
        if not is_asr_payload(payload):
            continue
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
    live_comparable_entries = [
        track
        for track in artifact_backed
        if track.get("status") != "blocked"
        and track.get("streaming", {}).get("live_metrics_comparable") is True
        and track.get("contract", {}).get("transport") == "v1-stt-stream"
    ]
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
        "system_coverage": build_system_coverage(artifact_history),
        "ranges": ranges,
        "highlights": {
            "fastest_rest": build_highlight("Fastest REST mean", ("rest", "mean_ms"), highlight_entries),
            "lowest_partial_backlog": build_highlight(
                "Lowest partial backlog latency", ("streaming", "partial_mean_ms"), live_comparable_entries
            ),
            "fastest_first_partial": build_highlight(
                "Fastest first visible partial", ("streaming", "first_partial_end_to_end_mean_ms"), live_comparable_entries
            ),
            "tightest_partial_cadence": build_highlight(
                "Tightest partial cadence", ("streaming", "partial_gap_mean_ms"), live_comparable_entries
            ),
            "lowest_late_partial_ratio": build_highlight(
                "Lowest late partial ratio", ("streaming", "late_partial_ratio"), live_comparable_entries
            ),
            "fastest_final": build_highlight(
                "Fastest streaming finalization delay", ("streaming", "final_mean_ms"), live_comparable_entries
            ),
            "best_overall": build_derived_highlight("Best overall benchmark balance", "overall_score", live_comparable_entries),
            "best_live_caption": build_derived_highlight(
                "Best live turn-taking score", "live_caption_score", live_comparable_entries
            ),
            "best_partial_backlog": build_derived_highlight(
                "Best partial backlog score", "partial_backlog_score", live_comparable_entries
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
