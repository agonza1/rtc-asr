#!/usr/bin/env python3
"""Render a crawlable benchmark summary into docs/index.html."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST_PATH = Path("docs") / "benchmark-results" / "manifest.json"
DEFAULT_HOMEPAGE_PATH = Path("docs") / "index.html"
DEFAULT_DETAIL_DIR = Path("docs") / "benchmark-results" / "pages"
DEFAULT_SITEMAP_PATH = Path("docs") / "sitemap.xml"
DEFAULT_ROBOTS_PATH = Path("docs") / "robots.txt"
DEFAULT_LLMS_PATH = Path("docs") / "llms.txt"
DEFAULT_SITE_BASE_URL = "https://benchmarks.webrtc.ventures/asr-latency/"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prerender benchmark homepage summary")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH, help="Manifest JSON path")
    parser.add_argument("--homepage", type=Path, default=DEFAULT_HOMEPAGE_PATH, help="Homepage HTML path")
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR, help="Detail pages output directory")
    parser.add_argument("--sitemap", type=Path, default=DEFAULT_SITEMAP_PATH, help="Sitemap XML path")
    parser.add_argument("--robots", type=Path, default=DEFAULT_ROBOTS_PATH, help="Robots.txt output path")
    parser.add_argument("--llms", type=Path, default=DEFAULT_LLMS_PATH, help="llms.txt output path")
    parser.add_argument("--site-base-url", default=DEFAULT_SITE_BASE_URL, help="Absolute public base URL for sitemap entries")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when the homepage prerender is stale")
    return parser.parse_args()


def format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def format_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def format_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def format_mb(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} MB"


def format_watts(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} W"


def format_celsius(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} C"


def format_minutes(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} min"


def format_joules(value: float | int | None) -> str:
    return "n/a" if value is None else f"{value:.1f} J"


def format_count(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def format_sample_coverage(sample_count: float | int | None, target_sample_count: float | int | None) -> str:
    if sample_count is None and target_sample_count is None:
        return "n/a"
    if target_sample_count in (None, 0):
        return f"{format_count(sample_count)} samples"
    if sample_count is None:
        return f"n/a / {format_count(target_sample_count)} target"
    coverage = float(sample_count) / float(target_sample_count)
    return f"{format_count(sample_count)} / {format_count(target_sample_count)} target ({format_percent(coverage)})"


def format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none recorded"


def format_bytes(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def format_date(value: str | None) -> str:
    if not value:
        return "n/a"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return parsed.astimezone(UTC).strftime("%b %d, %Y, %I:%M %p UTC")


def first_visible_partial(entry: dict[str, Any]) -> float | None:
    return entry.get("streaming", {}).get("first_partial_end_to_end_mean_ms")


def ttfb_first_partial_label() -> str:
    return "TTFB / first partial"


def ttfb_first_partial_description() -> str:
    return "End-to-end ASR time-to-first-byte equivalent: stream start until the first visible partial transcript appears."


def benchmark_scope_copy() -> str:
    return (
        "These benchmarks target real-time voice AI on practical edge and local inference setups: "
        "CPU sidecars, Docker Compose CPU lanes, and small Apple Silicon runtimes. High-power GPUs, "
        "cloud accelerators, or tuned hosted inference may perform much better and should be published "
        "as separate tracks."
    )


def partial_backlog_mean(entry: dict[str, Any]) -> float | None:
    return entry.get("streaming", {}).get("partial_gap_mean_ms")


def partial_backlog_p95(entry: dict[str, Any]) -> float | None:
    return entry.get("streaming", {}).get("partial_gap_p95_ms")


def published_tracks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [track for track in manifest.get("tracks", []) if track.get("artifact_path") and track.get("status") != "blocked"]


def contract_signature(entry: dict[str, Any]) -> tuple[Any, Any, Any]:
    contract = entry.get("contract", {})
    streaming = entry.get("streaming", {})
    return (
        contract.get("path"),
        contract.get("transport") or streaming.get("transport"),
        streaming.get("live_metrics_comparable"),
    )


def status_rank(entry: dict[str, Any]) -> int:
    if entry.get("status") == "validated":
        return 0
    if entry.get("status") == "legacy":
        return 1
    return 2


def numeric(value: float | None) -> float:
    return float("inf") if value is None else value


def score_rank(entry: dict[str, Any]) -> float:
    derived = entry.get("derived", {})
    overall = derived.get("overall_score")
    if overall is not None:
        return -overall
    live_caption = derived.get("live_caption_score")
    if live_caption is not None:
        return -live_caption
    return float("inf")


def sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda entry: (
            status_rank(entry),
            score_rank(entry),
            numeric(first_visible_partial(entry)),
            numeric(entry.get("streaming", {}).get("partial_gap_mean_ms")),
            numeric(entry.get("streaming", {}).get("final_mean_ms")),
            numeric(entry.get("rest", {}).get("mean_ms")),
        ),
    )


def comparable_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [entry for entry in entries if entry.get("streaming", {}).get("live_metrics_comparable") is True]


def has_primary_live_metrics(entry: dict[str, Any]) -> bool:
    streaming = entry.get("streaming", {})
    return streaming.get("live_metrics_comparable") is True and all(
        streaming.get(field) is not None
        for field in ("first_partial_end_to_end_mean_ms", "partial_gap_mean_ms", "final_mean_ms")
    )


def primary_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = [entry for entry in comparable_entries(entries) if has_primary_live_metrics(entry)]
    return primary or comparable_entries(entries)


def secondary_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary_slugs = {entry.get("slug") for entry in primary_entries(entries)}
    return [entry for entry in sort_entries(entries) if entry.get("slug") not in primary_slugs]


def historical_supporting_entries(manifest: dict[str, Any], current_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_by_slug = {entry.get("slug"): entry for entry in current_entries if entry.get("slug")}
    current_paths = {entry.get("artifact_path") for entry in current_entries if entry.get("artifact_path")}
    latest_by_slug: dict[str, dict[str, Any]] = {}
    for entry in manifest.get("artifacts", []):
        artifact_path = entry.get("artifact_path")
        slug = entry.get("slug")
        if not artifact_path or artifact_path in current_paths or not slug:
            continue
        current = current_by_slug.get(slug)
        if current is None:
            continue
        if entry.get("status") != "legacy":
            continue
        if contract_signature(entry) == contract_signature(current):
            continue
        previous = latest_by_slug.get(slug)
        if previous is None or (entry.get("measured_at") or "") > (previous.get("measured_at") or ""):
            latest_by_slug[slug] = entry
    return sort_entries(list(latest_by_slug.values()))


def secondary_reason(entry: dict[str, Any]) -> str:
    streaming = entry.get("streaming", {})
    contract = entry.get("contract", {})
    path = contract.get("path")
    transport = contract.get("transport")
    if streaming.get("live_metrics_comparable") is not True:
        if path == "/ws/stream" or transport in {"direct", "ws/stream"} or entry.get("status") == "legacy":
            return "Deprecated /ws/stream artifact: buffered websocket contract with lower-performance partial handling."
        return "Non-comparable streaming contract or protocol path."

    missing = []
    if streaming.get("first_partial_end_to_end_mean_ms") is None:
        missing.append("TTFB / first partial")
    if streaming.get("partial_gap_mean_ms") is None:
        missing.append("partial cadence")
    if streaming.get("final_mean_ms") is None:
        missing.append("finalization")
    if missing:
        return "Missing comparable live metrics: " + ", ".join(missing)
    return "Supporting artifact with a different contract or publication scope."


def median(values: list[float | None]) -> float | None:
    defined = sorted(value for value in values if value is not None)
    if not defined:
        return None
    middle = len(defined) // 2
    if len(defined) % 2:
        return defined[middle]
    return (defined[middle - 1] + defined[middle]) / 2


def min_defined(values: list[float | None]) -> float | None:
    defined = [value for value in values if value is not None]
    if not defined:
        return None
    return min(defined)


def delta_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) < 0.05:
        return "best baseline"
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.1f} ms"


def replace_generated_block(document: str, block_id: str, content: str) -> str:
    pattern = re.compile(
        rf"(<!-- BEGIN GENERATED:{re.escape(block_id)} -->)(.*?)(<!-- END GENERATED:{re.escape(block_id)} -->)",
        re.DOTALL,
    )
    updated, count = pattern.subn(lambda _: f"<!-- BEGIN GENERATED:{block_id} -->\n{content}\n<!-- END GENERATED:{block_id} -->", document)
    if count != 1:
        raise ValueError(f"Expected one generated block for {block_id}, found {count}")
    return updated


def hint(label: str, description: str) -> str:
    return f'<span class="hint" title="{html.escape(description)}">{html.escape(label)}</span>'


def tone_class(index: int) -> str:
    tones = ["tone-moss", "tone-sage", "tone-olive"]
    return tones[index % len(tones)]


def detail_page_path(entry: dict[str, Any]) -> str:
    artifact_path = entry.get("artifact_path") or ""
    artifact_name = Path(artifact_path).name
    if not artifact_name.endswith(".json"):
        return "#"
    return f"benchmark-results/pages/{Path(artifact_name).stem}.html"


def detail_output_path(detail_dir: Path, entry: dict[str, Any]) -> Path:
    return detail_dir / Path(detail_page_path(entry)).name


def warning_badge_text(entry: dict[str, Any]) -> str | None:
    warnings = entry.get("warnings") or {}
    received = warnings.get("received_total")
    codes = warnings.get("codes") or []
    if received in (None, 0) and not codes:
        return None

    code_text = format_list(codes)
    if received is None:
        return f"Warnings recorded: {code_text}"
    return f"Warnings {format_count(received)} ({code_text})"


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


def inferred_artifact_status(entry: dict[str, Any]) -> str | None:
    contract = entry.get("contract") or {}
    streaming = entry.get("streaming") or {}
    path = contract.get("path")
    transport = contract.get("transport") or streaming.get("transport")
    if path == "/ws/stream" or transport in {"direct", "ws/stream"}:
        return "legacy"
    if streaming.get("live_metrics_comparable") is True:
        return "validated"
    return None


def historical_status_detail(entry: dict[str, Any], track: dict[str, Any] | None) -> str | None:
    status = entry.get("status")
    if status == "legacy":
        if track and track.get("artifact_path") != entry.get("artifact_path"):
            return "Historical /ws/stream artifact kept as supporting evidence after this lane moved to a newer /v1/stt/stream result."
        return "Historical /ws/stream artifact kept as supporting evidence."
    if status == "validated":
        return "Checked-in /v1/stt/stream benchmark artifact."
    return None


def hydrate_detail_entry(entry: dict[str, Any], tracks: list[dict[str, Any]]) -> dict[str, Any]:
    hydrated = dict(entry)
    matched_track = next(
        (
            track
            for track in tracks
            if track.get("backend") == entry.get("backend")
            and track.get("model") == entry.get("model")
            and track.get("runtime") == entry.get("runtime")
        ),
        None,
    )
    if matched_track is not None:
        for key in ("slug", "label", "lane", "runtime", "official_wer_reference", "run_command"):
            hydrated[key] = first_defined(hydrated.get(key), matched_track.get(key))
    hydrated["status"] = first_defined(hydrated.get("status"), inferred_artifact_status(hydrated), matched_track.get("status") if matched_track else None)
    hydrated["status_detail"] = first_defined(hydrated.get("status_detail"), historical_status_detail(hydrated, matched_track), matched_track.get("status_detail") if matched_track else None)
    return hydrated


def nested_value(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def format_system_text(value: Any) -> str:
    return "n/a" if value is None else html.escape(str(value))


def measurement_technique(entry: dict[str, Any]) -> str:
    contract = entry.get("contract") or {}
    path = contract.get("path")
    transport = contract.get("transport")

    if transport == "raw_uds" or path == "raw_uds":
        return "REST and raw Unix-domain-socket Local STT v1 ASR latency benchmark"
    if path == "/v1/stt/stream" or transport in {"v1-stt-stream", "tcp_ws", "uds_ws"}:
        return "REST and Local STT v1 websocket ASR latency benchmark"
    if path == "/ws/stream" or transport in {"direct", "ws/stream"}:
        return "REST and legacy buffered websocket ASR latency benchmark"
    return "REST and websocket ASR latency benchmark"


def extract_system_signals(artifact_payload: dict[str, Any] | None) -> dict[str, Any]:
    if artifact_payload is None:
        return {}

    environment = artifact_payload.get("environment", {})
    system = artifact_payload.get("system", {})
    metrics = artifact_payload.get("metrics", {})
    power = artifact_payload.get("power", {})
    thermal = artifact_payload.get("thermal", {})
    memory = artifact_payload.get("memory", {})
    cpu = artifact_payload.get("cpu", {})
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
            nested_value(environment, "accelerator", "name"),
            nested_value(environment, "accelerator", "model"),
            nested_value(environment, "accelerator", "type"),
            environment.get("accelerator"),
            nested_value(environment, "gpu", "name"),
            nested_value(environment, "gpu", "model"),
            nested_value(environment, "gpu", "type"),
            environment.get("gpu"),
            nested_value(system, "accelerator", "name"),
            nested_value(system, "accelerator", "model"),
            nested_value(system, "accelerator", "type"),
            system.get("accelerator"),
            nested_value(system, "gpu", "name"),
            nested_value(system, "gpu", "model"),
            nested_value(system, "gpu", "type"),
            system.get("gpu"),
            nested_value(metrics, "accelerator", "name"),
            nested_value(metrics, "accelerator", "model"),
            nested_value(metrics, "accelerator", "type"),
            metrics.get("accelerator"),
            nested_value(metrics, "gpu", "name"),
            nested_value(metrics, "gpu", "model"),
            nested_value(metrics, "gpu", "type"),
            metrics.get("gpu"),
        ),
        "memory_total_mb": first_defined(
            environment.get("memory_total_mb"),
            system.get("memory_total_mb"),
            metrics.get("memory_total_mb"),
            memory.get("total_mb"),
            nested_value(metrics, "memory", "total_mb"),
        ),
        "process_rss_mb": first_defined(
            environment.get("process_rss_mb"),
            environment.get("rss_mb"),
            system.get("process_rss_mb"),
            system.get("rss_mb"),
            metrics.get("process_rss_mb"),
            metrics.get("rss_mb"),
            memory.get("process_rss_mb"),
            memory.get("rss_mb"),
            memory.get("resident_set_size_mb"),
            nested_value(metrics, "memory", "process_rss_mb"),
            nested_value(metrics, "memory", "rss_mb"),
            nested_value(metrics, "memory", "resident_set_size_mb"),
        ),
        "process_metrics_pid": first_defined(
            environment.get("process_metrics_pid"),
            system.get("process_metrics_pid"),
            metrics.get("process_metrics_pid"),
            nested_value(metrics, "process", "metrics_pid"),
            nested_value(metrics, "process", "pid"),
        ),
        "peak_rss_mb": first_defined(
            environment.get("peak_rss_mb"),
            system.get("peak_rss_mb"),
            metrics.get("peak_rss_mb"),
            memory.get("peak_rss_mb"),
            memory.get("rss_peak_mb"),
            memory.get("max_rss_mb"),
            memory.get("rss_max_mb"),
            nested_value(metrics, "memory", "peak_rss_mb"),
            nested_value(metrics, "memory", "rss_peak_mb"),
            nested_value(metrics, "memory", "max_rss_mb"),
            nested_value(metrics, "memory", "rss_max_mb"),
        ),
        "cpu_utilization_percent": first_defined(
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
        ),
        "package_power_watts": first_defined(
            environment.get("package_power_watts"),
            environment.get("package_power_avg_watts"),
            environment.get("package_power_average_watts"),
            system.get("package_power_watts"),
            system.get("package_power_avg_watts"),
            system.get("package_power_average_watts"),
            metrics.get("package_power_watts"),
            metrics.get("package_power_avg_watts"),
            metrics.get("package_power_average_watts"),
            nested_value(metrics, "power", "package_watts"),
            nested_value(metrics, "power", "package_power_watts"),
            nested_value(metrics, "power", "package_power_avg_watts"),
            nested_value(metrics, "power", "package_power_average_watts"),
            nested_value(metrics, "power", "average_package_watts"),
            power.get("package_watts"),
            power.get("package_power_watts"),
            power.get("package_power_avg_watts"),
            power.get("package_power_average_watts"),
            power.get("average_package_watts"),
        ),
        "energy_per_audio_second_j": first_defined(
            environment.get("energy_per_audio_second_j"),
            environment.get("joules_per_audio_second"),
            system.get("energy_per_audio_second_j"),
            system.get("joules_per_audio_second"),
            metrics.get("energy_per_audio_second_j"),
            metrics.get("joules_per_audio_second"),
            nested_value(metrics, "power", "energy_per_audio_second_j"),
            nested_value(metrics, "power", "joules_per_audio_second"),
            power.get("energy_per_audio_second_j"),
            power.get("joules_per_audio_second"),
        ),
        "thermal_peak_celsius": first_defined(
            environment.get("thermal_peak_celsius"),
            environment.get("thermal_max_celsius"),
            system.get("thermal_peak_celsius"),
            system.get("thermal_max_celsius"),
            metrics.get("thermal_peak_celsius"),
            metrics.get("thermal_max_celsius"),
            nested_value(metrics, "thermal", "peak_celsius"),
            nested_value(metrics, "thermal", "thermal_peak_celsius"),
            nested_value(metrics, "thermal", "max_celsius"),
            nested_value(metrics, "thermal", "thermal_max_celsius"),
            thermal.get("peak_celsius"),
            thermal.get("thermal_peak_celsius"),
            thermal.get("max_celsius"),
            thermal.get("thermal_max_celsius"),
        ),
        "thermal_observation": first_defined(
            environment.get("thermal_observation"),
            environment.get("thermal_state"),
            system.get("thermal_observation"),
            system.get("thermal_state"),
            metrics.get("thermal_observation"),
            metrics.get("thermal_state"),
            nested_value(metrics, "thermal", "observation"),
            nested_value(metrics, "thermal", "state"),
            thermal.get("observation"),
            thermal.get("state"),
        ),
        "thermal_duration_minutes": first_defined(
            environment.get("thermal_duration_minutes"),
            environment.get("thermal_observation_minutes"),
            system.get("thermal_duration_minutes"),
            system.get("thermal_observation_minutes"),
            metrics.get("thermal_duration_minutes"),
            metrics.get("thermal_observation_minutes"),
            nested_value(metrics, "thermal", "duration_minutes"),
            nested_value(metrics, "thermal", "observation_minutes"),
            thermal.get("duration_minutes"),
            thermal.get("observation_minutes"),
        ),
    }


def telemetry_coverage_text(system_signals: dict[str, Any]) -> str:
    fields = {
        "platform": system_signals.get("platform"),
        "processor": system_signals.get("processor"),
        "python": system_signals.get("python"),
        "cpu logical cores": system_signals.get("cpu_logical_cores"),
        "accelerator": system_signals.get("accelerator"),
        "system RAM": system_signals.get("memory_total_mb"),
        "process RSS": system_signals.get("process_rss_mb"),
        "metrics PID": system_signals.get("process_metrics_pid"),
        "peak RSS": system_signals.get("peak_rss_mb"),
        "CPU utilization": system_signals.get("cpu_utilization_percent"),
        "package power": system_signals.get("package_power_watts"),
        "energy per audio second": system_signals.get("energy_per_audio_second_j"),
        "thermal peak": system_signals.get("thermal_peak_celsius"),
        "thermal observation": system_signals.get("thermal_observation"),
        "thermal duration": system_signals.get("thermal_duration_minutes"),
    }
    present = [label for label, value in fields.items() if value not in (None, "")]
    if not present:
        return "0 of 15 telemetry fields recorded. Missing: all optional system, power, memory, and thermal signals."
    missing = [label for label in fields if label not in present]
    missing_text = ", ".join(missing) if missing else "none"
    return f"{len(present)} of {len(fields)} telemetry fields recorded. Missing: {missing_text}."


def absolute_site_url(site_base_url: str | None, path: str) -> str:
    if not site_base_url:
        return path
    return f"{site_base_url.rstrip('/')}/{path.lstrip('/')}"


def evidence_role(entry: dict[str, Any]) -> str:
    status = str(entry.get("status") or "").lower()
    contract = entry.get("contract", {})
    if status == "validated" and contract.get("path") == "/v1/stt/stream":
        return "Primary comparable evidence"
    if status == "validated":
        return "Published supporting evidence"
    if status == "blocked":
        return "Blocked benchmark evidence"
    if status == "legacy":
        return "Historical supporting evidence"
    return "Supporting benchmark evidence"


def detail_variable_measured(system_signals: dict[str, Any], warnings: dict[str, Any] | None = None) -> list[str]:
    variables = [
        "ASR TTFB / first visible partial latency",
        "partial backlog latency",
        "audio-end finalization latency",
        "REST throughput latency",
    ]
    optional_variables = [
        ("process RSS memory", system_signals.get("process_rss_mb")),
        ("peak RSS memory", system_signals.get("peak_rss_mb")),
        ("CPU utilization", system_signals.get("cpu_utilization_percent")),
        ("package power", system_signals.get("package_power_watts")),
        ("energy per audio second", system_signals.get("energy_per_audio_second_j")),
        ("thermal peak temperature", system_signals.get("thermal_peak_celsius")),
        ("thermal observation duration", system_signals.get("thermal_duration_minutes")),
    ]
    variables.extend(label for label, value in optional_variables if value not in (None, ""))
    if rss_delta_mb(system_signals) is not None:
        variables.append("peak-to-process RSS delta")
    warning_metrics = warnings or {}
    if warning_metrics.get("received_total") not in (None, 0) or warning_metrics.get("codes"):
        variables.append("stream warning telemetry")
    if warning_metrics.get("rate_per_sample") is not None:
        variables.append("stream warnings per sample")
    return variables


def citation_text(entry: dict[str, Any]) -> str:
    label = entry.get("label") or "rtc-asr benchmark artifact"
    artifact_name = Path(entry.get("artifact_path") or "").name or "unknown artifact"
    measured_at = entry.get("measured_at") or "unknown measurement date"
    artifact_sha256 = entry.get("artifact_sha256")
    sha_suffix = f", SHA-256 {artifact_sha256}" if artifact_sha256 else ""
    return f"{label}, {measured_at}, rtc-asr benchmark artifact {artifact_name}{sha_suffix}."


def detail_decision_summary(entry: dict[str, Any]) -> str:
    streaming = entry.get("streaming", {})
    status = entry.get("status")
    label = entry.get("label") or "This artifact"
    ttfb = format_ms(streaming.get("first_partial_end_to_end_mean_ms"))
    final = format_ms(streaming.get("final_mean_ms"))
    backlog = format_ms(partial_backlog_mean(entry))
    transport = entry.get("contract", {}).get("transport") or entry.get("contract", {}).get("path") or "unknown transport"

    if status == "blocked":
        return (
            f"{label} is tracked but blocked for primary ranking; use it only to understand the current gap "
            f"for {transport}."
        )
    if status == "legacy":
        return (
            f"{label} is historical supporting evidence with {ttfb} first partial latency, {backlog} partial backlog, "
            f"and {final} audio-end finalization."
        )
    if streaming.get("live_metrics_comparable") is True:
        return (
            f"{label} is comparable live evidence: {ttfb} first partial latency, {backlog} partial backlog, "
            f"and {final} audio-end finalization on {transport}."
        )
    return (
        f"{label} is publishable supporting evidence, but its live metrics are not directly comparable with the "
        "primary Local STT ranking contract."
    )


def rss_delta_mb(system_signals: dict[str, Any]) -> float | None:
    process_rss = system_signals.get("process_rss_mb")
    peak_rss = system_signals.get("peak_rss_mb")
    if process_rss is None or peak_rss is None:
        return None
    return float(peak_rss) - float(process_rss)


def render_detail_page(entry: dict[str, Any], artifact_payload: dict[str, Any] | None, site_base_url: str | None = None) -> str:
    rest = entry.get("rest", {})
    streaming = entry.get("streaming", {})
    contract = entry.get("contract", {})
    derived = entry.get("derived", {})
    title = html.escape(entry.get("label") or "Benchmark artifact")
    artifact_href = html.escape("../" + Path(entry.get("artifact_path") or "").name)
    homepage_href = html.escape("../../index.html")
    sitemap_href = html.escape("../../sitemap.xml")
    score = "n/a" if derived.get("overall_score") is None else f"{derived['overall_score']:.1f} / 100"
    confidence = "n/a" if derived.get("confidence_score") is None else f"{derived['confidence_score']:.1f} / 100"
    contract_value = "n/a" if contract.get("chunk_ms") is None else f"{contract['chunk_ms']} ms chunks"
    transport_value = contract.get("transport") or contract.get("path") or "n/a"
    uds_path_value = contract.get("uds_path") or "n/a"
    frame_format_value = contract.get("frame_format") or "n/a"
    frame_header_value = contract.get("frame_header_bytes")
    official_wer_reference = entry.get("official_wer_reference")
    warnings = entry.get("warnings") or {}
    run_command = entry.get("run_command")
    artifact_sha256 = entry.get("artifact_sha256")
    artifact_size_bytes = entry.get("artifact_size_bytes")
    artifact_name = Path(entry.get("artifact_path") or "").name
    citation = citation_text(entry)
    sample_coverage = format_sample_coverage(entry.get("sample_count"), entry.get("target_sample_count"))
    manifest_artifact_path = entry.get("artifact_path") or "n/a"
    description = entry.get("status_detail") or "Checked-in rtc-asr benchmark artifact."
    technique = measurement_technique(entry)
    role = evidence_role(entry)
    decision_summary = detail_decision_summary(entry)
    detail_href = Path(detail_page_path(entry)).name
    detail_url = absolute_site_url(site_base_url, f"benchmark-results/pages/{detail_href}")
    artifact_url = absolute_site_url(site_base_url, f"benchmark-results/{artifact_name}") if site_base_url and artifact_name else artifact_href
    homepage_url = absolute_site_url(site_base_url, "index.html")
    preview_title = f"{entry.get('label') or artifact_name or 'Benchmark artifact'} | rtc-asr benchmark artifact"
    measured_at = entry.get("measured_at")
    artifact_modified_at = entry.get("artifact_modified_at")
    article_modified_at = artifact_modified_at or measured_at
    system_signals = extract_system_signals(artifact_payload)
    keywords = [
        "rtc-asr",
        "ASR latency benchmark",
        str(entry.get("label") or artifact_name or "benchmark artifact"),
        str(entry.get("backend") or "unknown backend"),
        str(entry.get("runtime") or "unknown runtime"),
        str(entry.get("lane") or "unknown lane"),
        str(contract.get("transport") or contract.get("path") or "unknown transport"),
    ]
    structured_data = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": f"rtc-asr benchmark artifact: {entry.get('label') or artifact_name or 'unknown'}",
        "description": decision_summary,
        "identifier": artifact_sha256 or manifest_artifact_path,
        "url": detail_url,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": detail_url,
            "url": detail_url,
            "name": preview_title,
        },
        "datePublished": measured_at,
        "dateModified": article_modified_at,
        "citation": citation,
        "measurementTechnique": technique,
        "keywords": keywords,
        "variableMeasured": detail_variable_measured(system_signals, warnings),
        "isPartOf": {
            "@type": "Dataset",
            "name": "rtc-asr benchmark results",
            "url": homepage_url,
        },
        "distribution": {
            "@type": "DataDownload",
            "encodingFormat": "application/json",
            "contentUrl": artifact_url,
            "sha256": artifact_sha256,
            "contentSize": artifact_size_bytes,
        },
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": 1,
                    "name": "rtc-asr benchmark homepage",
                    "item": homepage_url,
                },
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": entry.get("label") or artifact_name or "Benchmark artifact",
                    "item": detail_url,
                },
            ],
        },
    }
    structured_data_json = json.dumps(structured_data, indent=6).replace("</", "<\\/")
    system_summary = " · ".join(
        [
            format_system_text(system_signals.get("platform")),
            format_system_text(system_signals.get("processor")),
            f"Python {format_system_text(system_signals.get('python'))}",
        ]
    )
    efficiency_summary = " · ".join(
        [
            f"Logical cores {format_system_text(system_signals.get('cpu_logical_cores'))}",
            f"Accelerator {format_system_text(system_signals.get('accelerator'))}",
            f"System RAM {format_mb(system_signals.get('memory_total_mb'))}",
            f"Process RSS {format_mb(system_signals.get('process_rss_mb'))}",
            f"RSS delta {format_mb(rss_delta_mb(system_signals))}",
            f"Metrics PID {format_count(system_signals.get('process_metrics_pid'))}",
            f"CPU {format_percent(system_signals.get('cpu_utilization_percent') / 100) if system_signals.get('cpu_utilization_percent') is not None else 'n/a'}",
            f"Power {format_watts(system_signals.get('package_power_watts'))}",
            f"Energy/audio-sec {format_joules(system_signals.get('energy_per_audio_second_j'))}",
            f"Thermal {format_celsius(system_signals.get('thermal_peak_celsius'))}",
            f"Thermal run {format_minutes(system_signals.get('thermal_duration_minutes'))}",
        ]
    )
    thermal_note = format_system_text(system_signals.get("thermal_observation") or "Artifact does not record sustained thermal notes yet.")
    telemetry_coverage = telemetry_coverage_text(system_signals)
    telemetry_count, telemetry_missing = telemetry_coverage.split(". ", 1)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="{html.escape(description)}">
    <meta name="keywords" content="{html.escape(', '.join(keywords))}">
    <meta property="og:type" content="article">
    <meta property="og:title" content="{html.escape(preview_title)}">
    <meta property="og:description" content="{html.escape(description)}">
    <meta property="og:url" content="{html.escape(detail_url)}">
    <meta property="article:published_time" content="{html.escape(measured_at or '')}">
    <meta property="article:modified_time" content="{html.escape(article_modified_at or '')}">
    <meta name="twitter:card" content="summary">
    <link rel="canonical" href="{html.escape(detail_url)}">
    <link rel="sitemap" type="application/xml" href="{sitemap_href}">
    <link rel="alternate" type="application/json" href="{artifact_href}" title="Raw benchmark JSON artifact">
    <link rel="alternate" type="application/json" href="../manifest.json" title="Benchmark results manifest">
    <title>{title} | rtc-asr benchmark artifact</title>
    <script type="application/ld+json">
{structured_data_json}
    </script>
    <style>
      :root {{
        color-scheme: light;
        --panel: #fffdf9;
        --ink: #1f2933;
        --muted: #5f6c7b;
        --accent: #8a3b12;
        --line: rgba(31, 41, 51, 0.12);
      }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; background: linear-gradient(180deg, #f4efe7 0%, #fbf7f0 100%); color: var(--ink); }}
      main {{ max-width: 980px; margin: 0 auto; padding: 40px 20px 64px; }}
      .eyebrow {{ text-transform: uppercase; letter-spacing: 0.14em; font: 600 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent); }}
      h1 {{ margin: 12px 0 10px; font-size: clamp(2.2rem, 4vw, 3.6rem); line-height: 0.98; }}
      p {{ color: var(--muted); line-height: 1.6; }}
      .actions, .grid {{ display: grid; gap: 16px; }}
      .actions {{ grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin: 28px 0; }}
      .grid {{ grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }}
      .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 12px 30px rgba(31, 41, 51, 0.06); }}
      .label {{ display: block; font: 600 12px/1.2 ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); margin-bottom: 8px; }}
      .value {{ font-size: 1.4rem; line-height: 1.2; }}
      .breadcrumb {{ display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 20px; color: var(--muted); font: 600 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; letter-spacing: 0.08em; }}
      .breadcrumb span::before {{ content: "/"; margin-right: 8px; color: rgba(31, 41, 51, 0.35); }}
      a {{ color: var(--accent); text-decoration-thickness: 0.08em; }}
    </style>
  </head>
  <body>
    <main>
      <nav class="breadcrumb" aria-label="Breadcrumb"><a href="{homepage_href}">Benchmark homepage</a><span>{title}</span></nav>
      <div class="eyebrow">Artifact detail page</div>
      <h1>{title}</h1>
      <p>{html.escape(entry.get("status_detail") or "Checked-in benchmark artifact.")}</p>
      <div class="actions">
        <div class="card"><span class="label">Decision summary</span><div class="value">{html.escape(entry.get("status") or "unknown")}</div><p>{html.escape(decision_summary)}</p></div>
        <div class="card"><span class="label">Lane</span><div class="value">{html.escape(entry.get("lane") or "unknown")}</div><p>{html.escape(entry.get("backend") or "unknown")} · {html.escape(entry.get("model") or "unknown")}</p></div>
        <div class="card"><span class="label">Runtime</span><div class="value">{html.escape(entry.get("runtime") or "unknown")}</div><p>Status: {html.escape(entry.get("status") or "unknown")} · Sample coverage: {html.escape(sample_coverage)}</p></div>
        <div class="card"><span class="label">Evidence role</span><div class="value">{html.escape(role)}</div><p>{html.escape(description)}</p></div>
        <div class="card"><span class="label">Links</span><div><a href="{homepage_href}">Back to benchmark homepage</a></div><div><a href="../manifest.json">Open benchmark manifest</a></div><div><a href="{artifact_href}">Open raw JSON artifact</a></div><div><a href="{artifact_href}" download="{html.escape(artifact_name)}">Download raw JSON artifact</a></div><p>Measured {html.escape(format_date(entry.get("measured_at")))}</p></div>
      </div>
      <div class="grid">
        <article class="card"><span class="label">Overall score</span><div class="value">{score}</div><p>Confidence {confidence}</p></article>
        <article class="card"><span class="label">TTFB / first partial</span><div class="value">{format_ms(streaming.get("first_partial_end_to_end_mean_ms"))}</div><p>P95 {format_ms(streaming.get("first_partial_end_to_end_p95_ms"))}</p></article>
        <article class="card"><span class="label">Partial backlog latency</span><div class="value">{format_ms(partial_backlog_mean(entry))}</div><p>Diagnostic partial cadence after streaming is underway. P95 {format_ms(partial_backlog_p95(entry))} . Late ratio {format_percent(streaming.get("late_partial_ratio"))}</p></article>
        <article class="card"><span class="label">Transcript stability</span><div class="value">{format_ratio(streaming.get("partial_transcript_churn_word_mean"))}</div><p>Mean word churn across interim transcripts. Character churn {format_ratio(streaming.get("partial_transcript_churn_char_mean"))} · Late partial events {format_count(streaming.get("late_partial_events"))}</p></article>
        <article class="card"><span class="label">Audio-end finalization</span><div class="value">{format_ms(streaming.get("final_mean_ms"))}</div><p>P95 {format_ms(streaming.get("final_p95_ms"))}</p></article>
        <article class="card"><span class="label">REST throughput context</span><div class="value">{format_ms(rest.get("mean_ms"))}</div><p>P95 {format_ms(rest.get("p95_ms"))} · RTF {format_ratio(rest.get("rtf_mean"))}</p></article>
        <article class="card"><span class="label">Transport contract</span><div class="value">{html.escape(str(transport_value))}</div><p>{contract_value} · Window {contract.get("partial_window_seconds") or 'n/a'} s · Interval {contract.get("partial_interval_chunks") or 'n/a'} · Sample rate {contract.get("sample_rate") or 'n/a'} Hz · Binary {contract.get("binary_frames") if contract.get("binary_frames") is not None else 'n/a'}</p><p>UDS path {html.escape(str(uds_path_value))} · Frame format {html.escape(str(frame_format_value))} · Header bytes {html.escape(str(frame_header_value if frame_header_value is not None else 'n/a'))}</p></article>
        <article class="card"><span class="label">Measurement technique</span><div class="value">{html.escape(technique)}</div><p>Separates Local STT v1 websocket artifacts from legacy buffered websocket evidence.</p></article>
        <article class="card"><span class="label">Accuracy context</span><div class="value">{html.escape(official_wer_reference or 'No external WER reference')}</div><p>Shown as external context rather than an official rtc-asr measurement.</p></article>
        <article class="card"><span class="label">Warnings</span><div class="value">{format_count(warnings.get("received_total"))}</div><p>Rate {format_ratio(warnings.get("rate_per_sample"))} per sample · Codes: {html.escape(format_list(warnings.get("codes") or []))}</p></article>
        <article class="card"><span class="label">Reproduction command</span><div class="value"><code>{html.escape(run_command or 'No checked-in run command')}</code></div><p>Use the recorded invocation when you need to refresh or compare this lane.</p></article>
        <article class="card"><span class="label">Artifact integrity</span><div class="value"><code>{html.escape(artifact_sha256[:12] if artifact_sha256 else 'n/a')}</code></div><p>SHA-256 {html.escape(artifact_sha256 or 'not available')}</p><p>Size {format_bytes(artifact_size_bytes)}</p></article>
        <article class="card"><span class="label">Citation</span><div class="value">{html.escape(entry.get("label") or artifact_name or "Benchmark artifact")}</div><p>{html.escape(citation)}</p></article>
        <article class="card"><span class="label">Artifact provenance</span><div class="value"><code>{html.escape(artifact_name or 'n/a')}</code></div><p>Manifest path <code>{html.escape(manifest_artifact_path)}</code></p><p>Artifact modified {html.escape(format_date(artifact_modified_at)) if artifact_modified_at else 'Not recorded'}</p><p>Generated detail page {html.escape(Path(detail_page_path(entry)).name)}</p></article>
        <article class="card"><span class="label">System profile</span><div class="value">{html.escape(entry.get("device") or entry.get("runtime") or "unknown")}</div><p>{system_summary}</p></article>
        <article class="card"><span class="label">Efficiency signals</span><div class="value">Peak RSS {format_mb(system_signals.get("peak_rss_mb"))}</div><p>{efficiency_summary}</p><p>{thermal_note}</p></article>
        <article class="card"><span class="label">Telemetry coverage</span><div class="value">{html.escape(telemetry_count)}</div><p>{html.escape(telemetry_missing)}</p></article>
      </div>
      <div class="card" style="margin-top: 24px;">
        <span class="label">Artifact access</span>
        <p>The homepage now leads with decision-ready summaries instead of raw benchmark dumps. Use the JSON artifact only when you need the underlying machine-readable record.</p>
        <p>Manifest artifact path: <code>{html.escape(manifest_artifact_path)}</code></p>
        <p>Integrity check: SHA-256 <code>{html.escape(artifact_sha256 or 'not available')}</code> · Size {format_bytes(artifact_size_bytes)}</p>
        <div><a href="../manifest.json">Open benchmark manifest</a></div>
        <div><a href="{artifact_href}">Open raw JSON artifact</a></div>
        <div><a href="{artifact_href}" download="{html.escape(artifact_name)}">Download raw JSON artifact</a></div>
      </div>
    </main>
  </body>
</html>
"""


def render_detail_pages(manifest: dict[str, Any], manifest_path: Path, detail_dir: Path, site_base_url: str | None = None) -> dict[Path, str]:
    results_dir = manifest_path.parent
    pages: dict[Path, str] = {}
    detail_entries: dict[str, dict[str, Any]] = {}
    tracks = manifest.get("tracks", [])
    for entry in manifest.get("artifacts", []):
        artifact_path = entry.get("artifact_path")
        if artifact_path:
            detail_entries[str(artifact_path)] = hydrate_detail_entry(entry, tracks)
    for entry in tracks:
        artifact_path = entry.get("artifact_path")
        if artifact_path:
            detail_entries[str(artifact_path)] = entry

    for entry in detail_entries.values():
        if not entry.get("artifact_path"):
            continue
        artifact_payload = None
        artifact_path = results_dir.parent / entry["artifact_path"]
        detail_entry = dict(entry)
        if artifact_path.exists():
            artifact_bytes = artifact_path.read_bytes()
            detail_entry["artifact_sha256"] = hashlib.sha256(artifact_bytes).hexdigest()
            detail_entry["artifact_size_bytes"] = len(artifact_bytes)
            artifact_payload = json.loads(artifact_bytes.decode("utf-8"))
        pages[detail_output_path(detail_dir, entry)] = render_detail_page(detail_entry, artifact_payload, site_base_url)
    return pages


def orphaned_detail_pages(detail_dir: Path, detail_pages: dict[Path, str]) -> list[Path]:
    expected_paths = set(detail_pages)
    return sorted(path for path in detail_dir.glob("*.html") if path not in expected_paths)


def sitemap_url(base_url: str, path: str) -> str:
    normalized_base = base_url.rstrip("/") + "/"
    normalized_path = path.lstrip("/")
    return normalized_base + normalized_path


def sitemap_lastmod(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC).date().isoformat()


def sitemap_entry_lastmod(entry: dict[str, Any]) -> str | None:
    return sitemap_lastmod(entry.get("artifact_modified_at") or entry.get("measured_at"))


def render_sitemap(manifest: dict[str, Any], base_url: str) -> str:
    generated_lastmod = sitemap_lastmod(manifest.get("generated_at"))
    detail_lastmods: dict[str, str | None] = {}
    artifact_lastmods: dict[str, str | None] = {}
    for entry in [*manifest.get("tracks", []), *manifest.get("artifacts", [])]:
        artifact_path = entry.get("artifact_path")
        if not artifact_path:
            continue
        lastmod = sitemap_entry_lastmod(entry)
        if str(artifact_path).endswith(".json"):
            current_artifact_lastmod = artifact_lastmods.get(artifact_path)
            if current_artifact_lastmod is None or (lastmod is not None and lastmod > current_artifact_lastmod):
                artifact_lastmods[artifact_path] = lastmod

        detail_path = detail_page_path(entry)
        if detail_path == "#":
            continue
        current_lastmod = detail_lastmods.get(detail_path)
        if current_lastmod is None or (lastmod is not None and lastmod > current_lastmod):
            detail_lastmods[detail_path] = lastmod

    urls = [("", generated_lastmod), ("benchmark-results/manifest.json", generated_lastmod), ("llms.txt", generated_lastmod)]
    urls.extend((path, artifact_lastmods[path]) for path in sorted(artifact_lastmods))
    urls.extend((path, detail_lastmods[path]) for path in sorted(detail_lastmods))
    url_entries = "\n".join(
        "  <url>\n"
        f"    <loc>{html.escape(sitemap_url(base_url, path))}</loc>\n"
        + (f"    <lastmod>{html.escape(lastmod)}</lastmod>\n" if lastmod else "")
        + "  </url>"
        for path, lastmod in urls
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{url_entries}\n</urlset>\n'


def render_robots(base_url: str) -> str:
    return "User-agent: *\nAllow: /\nSitemap: " + html.escape(sitemap_url(base_url, "sitemap.xml")) + "\n"


def render_llms(manifest: dict[str, Any], base_url: str) -> str:
    summary = manifest.get("summary", {})
    primary = primary_entries(published_tracks(manifest))
    artifact_entries = sort_entries(published_tracks(manifest))
    detail_entries = sort_entries([entry for entry in manifest.get("artifacts", []) if detail_page_path(entry) != "#"])
    lines = [
        "# Edge ASR Latency Benchmarks for WebRTC Voice AI",
        "",
        "This site publishes reproducible local and edge ASR latency evidence for real-time WebRTC and Voice AI systems.",
        "Use the manifest for machine-readable benchmark metadata and the detail pages for artifact-level provenance, integrity, and measurement notes.",
        "",
        "## Key URLs",
        f"- Benchmark homepage: {sitemap_url(base_url, '')}",
        f"- Manifest JSON: {sitemap_url(base_url, 'benchmark-results/manifest.json')}",
        f"- Sitemap: {sitemap_url(base_url, 'sitemap.xml')}",
        "",
        "## Publication Summary",
        f"- Current comparable tracks: {format_count(summary.get('live_comparable_count'))}",
        f"- Validated tracks: {format_count(summary.get('validated_count'))}",
        f"- Tracked lanes: {format_count(summary.get('tracked_count'))}",
        f"- Published current artifacts: {format_count(summary.get('published_artifact_count'))}",
        f"- Historical supporting artifacts: {format_count(summary.get('stale_artifact_count'))}",
        f"- Latest measurement: {format_date(summary.get('latest_measured_at'))}",
        "",
        "## Current Comparable Tracks",
    ]
    if not primary:
        lines.append("- No comparable artifact-backed tracks are published yet.")
    for entry in primary[:8]:
        label = entry.get("label") or entry.get("slug") or "unknown"
        detail_path = detail_page_path(entry)
        first_partial = format_ms(first_visible_partial(entry))
        final_latency = format_ms(entry.get("streaming", {}).get("final_mean_ms"))
        lines.append(
            f"- {label}: {entry.get('runtime') or 'unknown runtime'}; "
            f"TTFB / first partial {first_partial}; audio-end finalization {final_latency}; "
            f"details {sitemap_url(base_url, detail_path)}"
        )
    if primary:
        recommended = sort_entries(primary)[0]
        label = recommended.get("label") or recommended.get("slug") or "unknown"
        detail_path = detail_page_path(recommended)
        derived = recommended.get("derived", {})
        score_note = ""
        if derived.get("overall_score") is not None:
            score_note = f" Score: {derived['overall_score']:.1f} / 100."
            if derived.get("confidence_score") is not None:
                score_note = f" Score: {derived['overall_score']:.1f} / 100; confidence {derived['confidence_score']:.1f} / 100."
        lines.extend(
            [
                "",
                "## Current Recommendation",
                (
                    f"- {label}: {recommended.get('status_detail') or 'Top comparable live ASR lane by current benchmark ordering.'} "
                    f"Evidence: {format_ms(first_visible_partial(recommended))} TTFB / first partial, "
                    f"{format_ms(partial_backlog_mean(recommended))} partial cadence, "
                    f"{format_ms(recommended.get('streaming', {}).get('final_mean_ms'))} audio-end finalization; "
                    f"details {sitemap_url(base_url, detail_path)}.{score_note}"
                ),
            ]
        )
    lines.extend(["", "## Artifact Detail Pages"])
    if not detail_entries:
        lines.append("- No artifact detail pages are published yet.")
    for entry in detail_entries[:12]:
        label = entry.get("label") or entry.get("slug") or Path(entry.get("artifact_path") or "").stem or "unknown"
        status = entry.get("status") or "unknown status"
        measured_at = format_date(entry.get("measured_at"))
        lines.append(
            f"- {label}: {evidence_role(entry)}; status {status}; "
            f"measured {measured_at}; details {sitemap_url(base_url, detail_page_path(entry))}"
        )
    lines.extend(["", "## Raw Artifact URLs"])
    if not artifact_entries:
        lines.append("- No raw artifact URLs are published yet.")
    for entry in artifact_entries[:8]:
        artifact_path = entry.get("artifact_path")
        if not artifact_path:
            continue
        label = entry.get("label") or entry.get("slug") or "unknown"
        artifact_size = format_bytes(entry.get("artifact_size_bytes"))
        artifact_hash = entry.get("artifact_sha256")
        hash_label = f"SHA-256 {artifact_hash[:12]}" if artifact_hash else "SHA-256 n/a"
        lines.append(
            f"- {label}: raw JSON {sitemap_url(base_url, artifact_path)}; "
            f"{artifact_size}; {hash_label}"
        )
    lines.extend([
        "",
        "## Selection Notes",
        "- Primary comparisons use artifact-backed tracks with comparable live streaming metrics.",
        "- Rank live turn-taking first by TTFB / first partial, partial cadence, and audio-end finalization before REST throughput context.",
        "- Use confidence score, sample coverage, artifact hash, and measurement notes as tie-breakers before recommending a model lane.",
    ])
    warning_summary = summary.get("warnings") or {}
    has_warning_telemetry = (
        (warning_summary.get("artifacts_with_warnings_count") or 0) > 0
        or (warning_summary.get("received_total") or 0) > 0
        or bool(warning_summary.get("codes"))
    )
    if has_warning_telemetry:
        warning_codes = format_list(warning_summary.get("codes") or [])
        lines.append(
            "- Warning telemetry: "
            f"{format_count(warning_summary.get('received_total'))} warnings across "
            f"{format_count(warning_summary.get('artifacts_with_warnings_count'))} artifacts; "
            f"rate {format_ratio(warning_summary.get('rate_per_sample'))} per sample; "
            f"codes {warning_codes}."
        )
        for entry in artifact_entries[:8]:
            warning_label = warning_badge_text(entry)
            if warning_label:
                label = entry.get("label") or entry.get("slug") or "unknown"
                lines.append(f"- {label}: {warning_label}")
    lines.append(
        "- Blocked or registry-only lanes are documented in the manifest but omitted from the public comparison flow until publishable artifacts exist."
    )
    lines.extend([
        "",
        "## Coverage",
        f"- Current comparable tracks: {summary.get('live_comparable_count', len(primary))}",
        f"- Validated tracks: {summary.get('validated_count', 0)}",
        f"- Tracked lanes: {summary.get('tracked_count', len(manifest.get('tracks', [])))}",
        f"- Published current artifacts: {summary.get('published_artifact_count', len(published_tracks(manifest)))}",
        f"- Raw artifact files: {summary.get('artifact_file_count', 0)}",
        f"- Historical artifacts linked from detail pages: {summary.get('stale_artifact_count', 0)}",
        "",
    ])
    return "\n".join(lines)


def summarize_path_samples(paths: list[Path], *, limit: int = 3) -> str:
    samples = [path.name for path in paths[:limit]]
    if len(paths) > limit:
        samples.append(f"+{len(paths) - limit} more")
    return ", ".join(samples)


def summarize_detail_page_drift(missing: list[Path], stale: list[Path], orphaned: list[Path]) -> str:
    counts = []
    if missing:
        counts.append(f"{len(missing)} missing [{summarize_path_samples(missing)}]")
    if stale:
        counts.append(f"{len(stale)} stale [{summarize_path_samples(stale)}]")
    if orphaned:
        counts.append(f"{len(orphaned)} orphaned [{summarize_path_samples(orphaned)}]")
    return ", ".join(counts) if counts else "no detail page drift"


def render_row(
    entry: dict[str, Any],
    first_partial_baseline: float | None,
    partial_baseline: float | None,
    final_baseline: float | None,
    baseline_label: str,
    max_rest: float,
) -> str:
    streaming = entry.get("streaming", {})
    rest = entry.get("rest", {})
    derived = entry.get("derived", {})
    first_partial_value = first_visible_partial(entry)
    partial_value = partial_backlog_mean(entry)
    final_value = streaming.get("final_mean_ms")
    first_partial_delta = None if first_partial_value is None or first_partial_baseline is None else first_partial_value - first_partial_baseline
    partial_delta = None if partial_value is None or partial_baseline is None else partial_value - partial_baseline
    final_delta = None if final_value is None or final_baseline is None else final_value - final_baseline
    rest_width = max(6, ((rest.get("mean_ms") or 0) / max_rest) * 100)
    overall = derived.get("overall_score")
    confidence = derived.get("confidence_score")
    score = "n/a" if overall is None else f"{overall:.1f} / 100"
    confidence_text = "n/a" if confidence is None else f"{confidence:.1f} / 100"
    artifact_hash = entry.get("artifact_sha256")
    artifact_hash_label = f"SHA-256 {artifact_hash[:12]}" if artifact_hash else "SHA-256 n/a"
    artifact_size_label = format_bytes(entry.get("artifact_size_bytes"))
    warning_label = warning_badge_text(entry)
    warning_html = f'<div class="tiny">{html.escape(warning_label)}</div>' if warning_label else ""
    sample_target_label = entry.get("target_sample_count") or "n/a"
    status = html.escape(entry.get("status") or "unknown")
    return "".join(
        [
            "<tr>",
            f'<td data-label="Lane" class="leader-name"><strong>{html.escape(entry.get("label") or "unknown")}</strong><span>{html.escape(entry.get("backend") or "unknown")} . {html.escape(entry.get("model") or "unknown")}</span><div class="table-note">{html.escape(entry.get("lane") or "unknown")} . {html.escape(entry.get("runtime") or "unknown")}</div></td>',
            f'<td data-label="State"><span class="status status-{status}">{status}</span></td>',
            f'<td data-label="Score"><strong>{score}</strong><div class="tiny">Confidence {confidence_text}</div></td>',
            f'<td data-label="TTFB / first partial"><strong>{format_ms(first_partial_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("first_partial_end_to_end_p95_ms"))}</div><div class="tiny">{delta_text(first_partial_delta)} {html.escape(baseline_label)}</div></td>',
            f'<td data-label="Partial backlog latency"><strong>{format_ms(partial_value)}</strong><div class="tiny">P95 {format_ms(partial_backlog_p95(entry))}</div><div class="tiny">{delta_text(partial_delta)} vs lowest diagnostic</div></td>',
            f'<td data-label="Audio-end finalization"><strong>{format_ms(final_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("final_p95_ms"))}</div><div class="tiny">{delta_text(final_delta)} vs fastest</div></td>',
            f'<td data-label="REST throughput context"><strong>{format_ms(rest.get("mean_ms"))}</strong><div class="tiny">P95 {format_ms(rest.get("p95_ms"))} . RTF {format_ratio(rest.get("rtf_mean"))}</div><div class="metric-bar"><span style="width:{rest_width}%"></span></div></td>',
            f'<td data-label="Samples"><strong>{entry.get("sample_count") or "n/a"}</strong><div class="tiny">Target {sample_target_label}</div><div class="tiny">Measured {html.escape(format_date(entry.get("measured_at")))}</div></td>',
            f'<td data-label="Details"><a href="{html.escape(detail_page_path(entry))}">Open detail page</a><div class="tiny">Artifact size {html.escape(artifact_size_label)}</div><div class="tiny">{html.escape(artifact_hash_label)}</div>{warning_html}</td>',
            "</tr>",
        ]
    )


def render_secondary_row(entry: dict[str, Any]) -> str:
    streaming = entry.get("streaming", {})
    artifact_hash = entry.get("artifact_sha256")
    artifact_hash_label = f"SHA-256 {artifact_hash[:12]}" if artifact_hash else "SHA-256 n/a"
    artifact_size_label = format_bytes(entry.get("artifact_size_bytes"))
    warning_label = warning_badge_text(entry)
    warning_html = f'<div class="tiny">{html.escape(warning_label)}</div>' if warning_label else ""
    sample_count_label = entry.get("sample_count") or "n/a"
    sample_target_label = entry.get("target_sample_count") or "n/a"
    return "".join(
        [
            "<tr>",
            f'<td data-label="Lane" class="leader-name"><strong>{html.escape(entry.get("label") or "unknown")}</strong><span>{html.escape(entry.get("backend") or "unknown")} . {html.escape(entry.get("model") or "unknown")}</span><div class="table-note">{html.escape(entry.get("lane") or "unknown")} . {html.escape(entry.get("runtime") or "unknown")}</div></td>',
            f'<td data-label="Why it is secondary">{html.escape(secondary_reason(entry))}</td>',
            f'<td data-label="Visible live metrics"><strong>TTFB / first partial {format_ms(streaming.get("first_partial_end_to_end_mean_ms"))}</strong><div class="tiny">Finalization {format_ms(streaming.get("final_mean_ms"))}</div><div class="tiny">Samples {sample_count_label} / target {sample_target_label}</div></td>',
            f'<td data-label="Details"><a href="{html.escape(detail_page_path(entry))}">Open detail page</a><div class="tiny">Measured {html.escape(format_date(entry.get("measured_at")))}</div><div class="tiny">Artifact size {html.escape(artifact_size_label)}</div><div class="tiny">{html.escape(artifact_hash_label)}</div>{warning_html}</td>',
            "</tr>",
        ]
    )


def render_homepage(manifest: dict[str, Any], homepage: str) -> str:
    summary = manifest.get("summary", {})
    entries = published_tracks(manifest)
    ranked = sort_entries(entries)
    primary = sort_entries(primary_entries(ranked))
    secondary = secondary_entries(ranked)
    historical_secondary = historical_supporting_entries(manifest, ranked)
    secondary_paths = {entry.get("artifact_path") for entry in secondary if entry.get("artifact_path")}
    secondary = sort_entries(secondary + [entry for entry in historical_secondary if entry.get("artifact_path") not in secondary_paths])
    baseline_entries = comparable_entries(primary)
    first_partial_baseline = min_defined([first_visible_partial(entry) for entry in baseline_entries])
    partial_baseline = min_defined([partial_backlog_mean(entry) for entry in primary])
    final_baseline = min_defined([entry.get("streaming", {}).get("final_mean_ms") for entry in primary])
    baseline_label = "vs validated fastest" if len(baseline_entries) != len(primary) else "vs fastest"
    max_rest = max([entry.get("rest", {}).get("mean_ms") or 0 for entry in primary] or [1]) or 1
    best_primary = primary[0] if primary else None
    alternative = primary[1] if len(primary) > 1 else (secondary[0] if secondary else None)
    best_first_partial = first_visible_partial(best_primary) if best_primary else None
    best_final = best_primary.get("streaming", {}).get("final_mean_ms") if best_primary else None
    recommendation_title = (
        f"Start with {best_primary.get('label')} for live turn-taking." if best_primary else "No backend-only lane currently meets the live comparability contract."
    )
    recommendation_copy = (
        f"{best_primary.get('label')} is the strongest publishable default right now: {format_ms(first_visible_partial(best_primary))} ASR TTFB / first visible partial, {format_ms(best_primary.get('streaming', {}).get('final_mean_ms'))} audio-end finalization, and backlog diagnostics that stay separated from perceived latency." if best_primary else "Legacy /ws/stream artifacts stay published as supporting evidence, but the live leaderboard now waits for paced /v1/stt/stream replacements."
    )
    summary_cards: list[str] = []
    if best_primary:
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Recommended default</div><div class="headline-value">{html.escape(best_primary.get("label") or "unknown")}</div><p>{html.escape(best_primary.get("status_detail") or recommendation_copy)}</p></article>'
        )
    if alternative:
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(1)}"><div class="section-kicker">Alternative lane</div><div class="headline-value">{html.escape(alternative.get("label") or "unknown")}</div><p>{html.escape(alternative.get("status_detail") or "Supporting lane")}</p></article>'
        )
    summary_cards.append(
        f'<article class="snapshot-card {tone_class(2)}"><div class="section-kicker">Primary ranking scope</div><div class="headline-value">{len(primary)} edge/local lanes</div><p>The main ranking only includes comparable live metrics from practical local inference targets. Historical, high-power, or differently scoped artifacts belong in separate tracks and detail pages.</p></article>'
    )
    live_comparable_count = summary.get("live_comparable_count", len(primary))
    summary_cards.append(
        f'<article class="snapshot-card {tone_class(1)}"><div class="section-kicker">Published live contract</div><div class="headline-value">{live_comparable_count} comparable artifacts</div><p>{len(primary)} lanes are eligible for primary ranking after validation and publication filters; the rest stay discoverable as supporting evidence.</p></article>'
    )
    published_artifact_bytes = summary.get("published_artifact_total_size_bytes")
    if published_artifact_bytes:
        published_artifact_count = summary.get("published_artifact_count", len(entries))
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Current artifact footprint</div><div class="headline-value">{format_bytes(published_artifact_bytes)}</div><p>Current public ranking artifacts: {published_artifact_count}; historical files are counted separately in archive hygiene.</p></article>'
        )
    transport_coverage = summary.get("transport_coverage") or {}
    if transport_coverage:
        raw_uds_count = transport_coverage.get("raw_uds_artifact_count", 0)
        comparable_count = transport_coverage.get("comparable_local_stt_artifact_count", 0)
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(2)}"><div class="section-kicker">Transport coverage</div><div class="headline-value">{raw_uds_count} raw UDS artifacts</div><p>{comparable_count} Local STT artifacts are comparable today; raw UDS stays experimental until checked-in evidence beats UDS websocket by at least 5 ms p95.</p></article>'
        )
    summary_cards.append(
        f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Best live numbers</div><div class="headline-value">{format_ms(best_first_partial)}</div><p>Fastest ASR TTFB / first visible partial in the primary comparison. Best finalization is {format_ms(best_final)}.</p></article>'
    )
    system_coverage = summary.get("system_coverage") or {}
    if system_coverage:
        energy_count = max(
            system_coverage.get("package_power_watts_count", 0),
            system_coverage.get("energy_per_audio_second_j_count", 0),
        )
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(2)}"><div class="section-kicker">System evidence</div><div class="headline-value">{system_coverage.get("peak_rss_mb_count", 0)} memory traces</div><p>{system_coverage.get("cpu_utilization_percent_count", 0)} artifacts include CPU utilization; {energy_count} include power or energy readings; {system_coverage.get("thermal_observation_count", 0)} include sustained thermal notes.</p></article>'
        )
    low_power_evidence = summary.get("low_power_evidence") or {}
    if low_power_evidence:
        complete_count = low_power_evidence.get("complete_artifact_count", 0)
        artifact_count = low_power_evidence.get("artifact_count", summary.get("artifact_file_count", 0))
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Low-power readiness</div><div class="headline-value">{complete_count} complete artifacts</div><p>{low_power_evidence.get("power_evidence_count", 0)} of {artifact_count} artifacts include power evidence; {low_power_evidence.get("sustained_thermal_evidence_count", 0)} include sustained thermal evidence for battery-sensitive deployment decisions.</p></article>'
        )
    sample_coverage = summary.get("sample_coverage") or {}
    if sample_coverage:
        complete_count = sample_coverage.get("complete_artifact_count", 0)
        targeted_count = sample_coverage.get("targeted_artifact_count", 0)
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(2)}"><div class="section-kicker">Sample coverage</div><div class="headline-value">{complete_count} complete targets</div><p>{targeted_count} artifacts declare a sample target; {sample_coverage.get("partial_artifact_count", 0)} are below target and {sample_coverage.get("missing_sample_count_artifact_count", 0)} are missing sample-count metadata.</p></article>'
        )
    warning_summary = summary.get("warnings") or {}
    has_warning_telemetry = (
        (warning_summary.get("artifacts_with_warnings_count") or 0) > 0
        or (warning_summary.get("received_total") or 0) > 0
        or warning_summary.get("rate_per_sample") is not None
        or bool(warning_summary.get("codes"))
    )
    if has_warning_telemetry:
        warned_count = warning_summary.get("artifacts_with_warnings_count", 0)
        warning_codes = warning_summary.get("codes") or []
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Warning telemetry</div><div class="headline-value">{warned_count} flagged artifacts</div><p>{format_count(warning_summary.get("received_total"))} warnings recorded across checked-in artifacts; rate {format_ratio(warning_summary.get("rate_per_sample"))} per sample. Codes: {html.escape(format_list(warning_codes))}.</p></article>'
        )
    stale_artifact_count = summary.get("stale_artifact_count", 0)
    if stale_artifact_count:
        summary_cards.append(
            f'<article class="snapshot-card {tone_class(1)}"><div class="section-kicker">Archive hygiene</div><div class="headline-value">{stale_artifact_count} historical artifacts</div><p>{format_bytes(summary.get("stale_artifact_total_size_bytes"))} of older evidence stays linked through detail pages while current tracked artifacts drive the homepage ranking.</p></article>'
        )
    top_cards = "".join(
        f'<article class="story-card panel {tone_class(index)}"><div class="section-kicker">Rank {index + 1}</div><div class="story-rank">{html.escape(entry.get("label") or "unknown")}</div><div class="chip-row"><div class="chip"><strong>{html.escape(entry.get("runtime") or "unknown")}</strong> runtime</div><div class="chip"><strong>{html.escape(entry.get("lane") or "unknown")}</strong> lane</div></div><p>{html.escape(entry.get("status_detail") or "")}</p></article>'
        for index, entry in enumerate(primary[:3])
    )
    rows = "".join(
        render_row(entry, first_partial_baseline, partial_baseline, final_baseline, baseline_label, max_rest)
        for entry in primary
    )
    static_summary = f"""
<section class="section-head">
  <div>
    <div class="section-kicker">Launch readout</div>
    <h2>{html.escape(recommendation_title)}</h2>
  </div>
  <p class="subcopy">{html.escape(recommendation_copy)} The main ranking stays focused on fully comparable live lanes, while historical or differently scoped artifacts remain available through the appendix and detail pages.</p>
  <p class="subcopy">{html.escape(benchmark_scope_copy())}</p>
</section>
<div class="snapshot-grid">
  {''.join(summary_cards)}
</div>
<div class="story-grid" id="story-grid">
{top_cards}
</div>
<div class="comparison-wrap panel" id="comparison-wrap">
  <div class="comparison-scroll">
    <table>
      <thead>
        <tr><th>Lane</th><th>State</th><th>Score</th><th>{hint(ttfb_first_partial_label(), ttfb_first_partial_description())}</th><th>{hint('Partial backlog latency', 'Diagnostic latency for chunk-triggered partial updates after streaming is already underway; this is not perceived first-response latency, so read it alongside partial gap and late partial ratio.')}</th><th>{hint('Audio-end finalization', 'Time from audio end until the final transcript returns; this is closeout delay, not total clip duration.')}</th><th>{hint('REST throughput context', 'Batch request latency for the same backend outside the streaming websocket path. Keep this as throughput context rather than the main live turn-taking signal.')}</th><th>{hint('Samples', 'How many benchmark samples were recorded for this published artifact.')}</th><th>Details</th></tr>
      </thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>
</div>
""".strip()
    generated_at = html.escape(
        f"Published {format_date(manifest.get('generated_at'))} . {len(entries)} visible ASR lanes . {summary.get('published_artifact_count', len(published_tracks(manifest)))} current artifact-backed lanes . {summary.get('tracked_count', 0)} tracked lanes in the registry . {summary.get('artifact_file_count', 0)} raw artifacts with detail pages, including {summary.get('stale_artifact_count', 0)} historical artifacts."
    )
    rendered = replace_generated_block(homepage, "generated-at", generated_at)
    return replace_generated_block(rendered, "static-summary", static_summary)


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    homepage = args.homepage.read_text(encoding="utf-8")
    rendered = render_homepage(manifest, homepage)
    detail_pages = render_detail_pages(manifest, args.manifest, args.detail_dir, args.site_base_url)
    sitemap = render_sitemap(manifest, args.site_base_url)
    robots = render_robots(args.site_base_url)
    llms = render_llms(manifest, args.site_base_url)
    if args.check:
        if homepage != rendered:
            raise SystemExit(
                f"Homepage prerender is stale: {args.homepage}. Run scripts/prerender_benchmark_homepage.py to regenerate it."
            )
        missing = [path for path in detail_pages if not path.exists()]
        stale = [path for path, content in detail_pages.items() if path.exists() and path.read_text(encoding="utf-8") != content]
        orphaned = orphaned_detail_pages(args.detail_dir, detail_pages) if args.detail_dir.exists() else []
        if missing or stale or orphaned:
            raise SystemExit(
                f"Benchmark detail pages are stale: {args.detail_dir} "
                f"({summarize_detail_page_drift(missing, stale, orphaned)}). "
                "Run scripts/prerender_benchmark_homepage.py to regenerate them."
            )
        if not args.sitemap.exists() or args.sitemap.read_text(encoding="utf-8") != sitemap:
            raise SystemExit(
                f"Benchmark sitemap is stale: {args.sitemap}. Run scripts/prerender_benchmark_homepage.py to regenerate it."
            )
        if not args.robots.exists() or args.robots.read_text(encoding="utf-8") != robots:
            raise SystemExit(
                f"Benchmark robots.txt is stale: {args.robots}. Run scripts/prerender_benchmark_homepage.py to regenerate it."
            )
        if not args.llms.exists() or args.llms.read_text(encoding="utf-8") != llms:
            raise SystemExit(
                f"Benchmark llms.txt is stale: {args.llms}. Run scripts/prerender_benchmark_homepage.py to regenerate it."
            )
        return
    args.homepage.write_text(rendered, encoding="utf-8")
    args.sitemap.write_text(sitemap, encoding="utf-8")
    args.robots.write_text(robots, encoding="utf-8")
    args.llms.write_text(llms, encoding="utf-8")
    args.detail_dir.mkdir(parents=True, exist_ok=True)
    for path in orphaned_detail_pages(args.detail_dir, detail_pages):
        path.unlink()
    for path, content in detail_pages.items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
