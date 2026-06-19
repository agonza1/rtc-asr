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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prerender benchmark homepage summary")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH, help="Manifest JSON path")
    parser.add_argument("--homepage", type=Path, default=DEFAULT_HOMEPAGE_PATH, help="Homepage HTML path")
    parser.add_argument("--detail-dir", type=Path, default=DEFAULT_DETAIL_DIR, help="Detail pages output directory")
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


def published_tracks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [track for track in manifest.get("tracks", []) if track.get("artifact_path") and track.get("status") != "blocked"]


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
    validated = [entry for entry in entries if entry.get("status") == "validated"]
    return validated or entries


def has_primary_live_metrics(entry: dict[str, Any]) -> bool:
    streaming = entry.get("streaming", {})
    return all(
        streaming.get(field) is not None
        for field in ("first_partial_end_to_end_mean_ms", "partial_gap_mean_ms", "final_mean_ms")
    )


def primary_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary = [entry for entry in comparable_entries(entries) if has_primary_live_metrics(entry)]
    return primary or comparable_entries(entries)


def secondary_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    primary_slugs = {entry.get("slug") for entry in primary_entries(entries)}
    return [entry for entry in sort_entries(entries) if entry.get("slug") not in primary_slugs]


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


def format_system_text(value: Any) -> str:
    return "n/a" if value is None else html.escape(str(value))


def extract_system_signals(artifact_payload: dict[str, Any] | None) -> dict[str, Any]:
    if artifact_payload is None:
        return {}

    environment = artifact_payload.get("environment", {})
    system = artifact_payload.get("system", {})
    metrics = artifact_payload.get("metrics", {})
    return {
        "platform": first_defined(environment.get("platform"), system.get("platform")),
        "processor": first_defined(environment.get("processor"), environment.get("machine"), system.get("processor")),
        "python": first_defined(environment.get("python"), system.get("python")),
        "cpu_logical_cores": first_defined(
            environment.get("cpu_logical_cores"),
            system.get("cpu_logical_cores"),
            metrics.get("cpu_logical_cores"),
        ),
        "memory_total_mb": first_defined(
            environment.get("memory_total_mb"),
            system.get("memory_total_mb"),
            metrics.get("memory_total_mb"),
        ),
        "peak_rss_mb": first_defined(
            environment.get("peak_rss_mb"),
            environment.get("process_rss_mb"),
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
            system.get("thermal_observation"),
            metrics.get("thermal_observation"),
        ),
    }


def render_detail_page(entry: dict[str, Any], artifact_payload: dict[str, Any] | None) -> str:
    rest = entry.get("rest", {})
    streaming = entry.get("streaming", {})
    contract = entry.get("contract", {})
    derived = entry.get("derived", {})
    title = html.escape(entry.get("label") or "Benchmark artifact")
    artifact_href = html.escape("../" + Path(entry.get("artifact_path") or "").name)
    homepage_href = html.escape("../../index.html")
    score = "n/a" if derived.get("overall_score") is None else f"{derived['overall_score']:.1f} / 100"
    confidence = "n/a" if derived.get("confidence_score") is None else f"{derived['confidence_score']:.1f} / 100"
    contract_value = "n/a" if contract.get("chunk_ms") is None else f"{contract['chunk_ms']} ms chunks"
    official_wer_reference = entry.get("official_wer_reference")
    run_command = entry.get("run_command")
    artifact_sha256 = entry.get("artifact_sha256")
    artifact_size_bytes = entry.get("artifact_size_bytes")
    system_signals = extract_system_signals(artifact_payload)
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
            f"System RAM {format_mb(system_signals.get('memory_total_mb'))}",
            f"CPU {format_percent(system_signals.get('cpu_utilization_percent') / 100) if system_signals.get('cpu_utilization_percent') is not None else 'n/a'}",
            f"Power {format_watts(system_signals.get('package_power_watts'))}",
            f"Thermal {format_celsius(system_signals.get('thermal_peak_celsius'))}",
        ]
    )
    thermal_note = format_system_text(system_signals.get("thermal_observation") or "Artifact does not record sustained thermal notes yet.")
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title} | rtc-asr benchmark artifact</title>
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
      a {{ color: var(--accent); text-decoration-thickness: 0.08em; }}
    </style>
  </head>
  <body>
    <main>
      <div class="eyebrow">Artifact detail page</div>
      <h1>{title}</h1>
      <p>{html.escape(entry.get("status_detail") or "Checked-in benchmark artifact.")}</p>
      <div class="actions">
        <div class="card"><span class="label">Lane</span><div class="value">{html.escape(entry.get("lane") or "unknown")}</div><p>{html.escape(entry.get("backend") or "unknown")} · {html.escape(entry.get("model") or "unknown")}</p></div>
        <div class="card"><span class="label">Runtime</span><div class="value">{html.escape(entry.get("runtime") or "unknown")}</div><p>Status: {html.escape(entry.get("status") or "unknown")} · Samples: {entry.get("sample_count") or 'n/a'}</p></div>
        <div class="card"><span class="label">Links</span><div><a href="{homepage_href}">Back to benchmark homepage</a></div><div><a href="{artifact_href}">Open raw JSON artifact</a></div><p>Measured {html.escape(format_date(entry.get("measured_at")))}</p></div>
      </div>
      <div class="grid">
        <article class="card"><span class="label">Overall score</span><div class="value">{score}</div><p>Confidence {confidence}</p></article>
        <article class="card"><span class="label">First visible partial</span><div class="value">{format_ms(streaming.get("first_partial_end_to_end_mean_ms"))}</div><p>P95 {format_ms(streaming.get("first_partial_end_to_end_p95_ms"))}</p></article>
        <article class="card"><span class="label">Partial backlog latency</span><div class="value">{format_ms(streaming.get("partial_mean_ms"))}</div><p>Diagnostic chunk-response delay. Gap {format_ms(streaming.get("partial_gap_mean_ms"))} · Late ratio {format_percent(streaming.get("late_partial_ratio"))}</p></article>
        <article class="card"><span class="label">Audio-end finalization</span><div class="value">{format_ms(streaming.get("final_mean_ms"))}</div><p>P95 {format_ms(streaming.get("final_p95_ms"))}</p></article>
        <article class="card"><span class="label">REST throughput context</span><div class="value">{format_ms(rest.get("mean_ms"))}</div><p>P95 {format_ms(rest.get("p95_ms"))} · RTF {format_ratio(rest.get("rtf_mean"))}</p></article>
        <article class="card"><span class="label">Buffered contract</span><div class="value">{contract_value}</div><p>Window {contract.get("partial_window_seconds") or 'n/a'} s · Interval {contract.get("partial_interval_chunks") or 'n/a'} · Binary {contract.get("binary_frames") if contract.get("binary_frames") is not None else 'n/a'}</p></article>
        <article class="card"><span class="label">Accuracy context</span><div class="value">{html.escape(official_wer_reference or 'No external WER reference')}</div><p>Shown as external context rather than an official rtc-asr measurement.</p></article>
        <article class="card"><span class="label">Reproduction command</span><div class="value"><code>{html.escape(run_command or 'No checked-in run command')}</code></div><p>Use the recorded invocation when you need to refresh or compare this lane.</p></article>
        <article class="card"><span class="label">Artifact integrity</span><div class="value"><code>{html.escape(artifact_sha256[:12] if artifact_sha256 else 'n/a')}</code></div><p>SHA-256 {html.escape(artifact_sha256 or 'not available')}</p><p>Size {format_bytes(artifact_size_bytes)}</p></article>
        <article class="card"><span class="label">System profile</span><div class="value">{html.escape(entry.get("device") or entry.get("runtime") or "unknown")}</div><p>{system_summary}</p></article>
        <article class="card"><span class="label">Efficiency signals</span><div class="value">Peak RSS {format_mb(system_signals.get("peak_rss_mb"))}</div><p>{efficiency_summary}</p><p>{thermal_note}</p></article>
      </div>
      <div class="card" style="margin-top: 24px;">
        <span class="label">Artifact access</span>
        <p>The homepage now leads with decision-ready summaries instead of raw benchmark dumps. Use the JSON artifact only when you need the underlying machine-readable record.</p>
        <div><a href="{artifact_href}">Open raw JSON artifact</a></div>
      </div>
    </main>
  </body>
</html>
"""


def render_detail_pages(manifest: dict[str, Any], manifest_path: Path, detail_dir: Path) -> dict[Path, str]:
    results_dir = manifest_path.parent
    pages: dict[Path, str] = {}
    for entry in manifest.get("tracks", []):
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
        pages[detail_output_path(detail_dir, entry)] = render_detail_page(detail_entry, artifact_payload)
    return pages


def orphaned_detail_pages(detail_dir: Path, detail_pages: dict[Path, str]) -> list[Path]:
    expected_paths = set(detail_pages)
    return sorted(path for path in detail_dir.glob("*.html") if path not in expected_paths)


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
    partial_value = streaming.get("partial_mean_ms")
    final_value = streaming.get("final_mean_ms")
    first_partial_delta = None if first_partial_value is None or first_partial_baseline is None else first_partial_value - first_partial_baseline
    partial_delta = None if partial_value is None or partial_baseline is None else partial_value - partial_baseline
    final_delta = None if final_value is None or final_baseline is None else final_value - final_baseline
    rest_width = max(6, ((rest.get("mean_ms") or 0) / max_rest) * 100)
    overall = derived.get("overall_score")
    confidence = derived.get("confidence_score")
    score = "n/a" if overall is None else f"{overall:.1f} / 100"
    confidence_text = "n/a" if confidence is None else f"{confidence:.1f} / 100"
    status = html.escape(entry.get("status") or "unknown")
    return "".join(
        [
            "<tr>",
            f'<td data-label="Lane" class="leader-name"><strong>{html.escape(entry.get("label") or "unknown")}</strong><span>{html.escape(entry.get("backend") or "unknown")} . {html.escape(entry.get("model") or "unknown")}</span><div class="table-note">{html.escape(entry.get("lane") or "unknown")} . {html.escape(entry.get("runtime") or "unknown")}</div></td>',
            f'<td data-label="State"><span class="status status-{status}">{status}</span></td>',
            f'<td data-label="Score"><strong>{score}</strong><div class="tiny">Confidence {confidence_text}</div></td>',
            f'<td data-label="First partial"><strong>{format_ms(first_partial_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("first_partial_end_to_end_p95_ms"))}</div><div class="tiny">{delta_text(first_partial_delta)} {html.escape(baseline_label)}</div></td>',
            f'<td data-label="Partial backlog latency"><strong>{format_ms(partial_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("partial_p95_ms"))}</div><div class="tiny">{delta_text(partial_delta)} vs lowest diagnostic</div></td>',
            f'<td data-label="Audio-end finalization"><strong>{format_ms(final_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("final_p95_ms"))}</div><div class="tiny">{delta_text(final_delta)} vs fastest</div></td>',
            f'<td data-label="REST throughput context"><strong>{format_ms(rest.get("mean_ms"))}</strong><div class="tiny">P95 {format_ms(rest.get("p95_ms"))} . RTF {format_ratio(rest.get("rtf_mean"))}</div><div class="metric-bar"><span style="width:{rest_width}%"></span></div></td>',
            f'<td data-label="Samples"><strong>{entry.get("sample_count") or "n/a"}</strong><div class="tiny">Measured {html.escape(format_date(entry.get("measured_at")))}</div></td>',
            f'<td data-label="Details"><a href="{html.escape(detail_page_path(entry))}">Open detail page</a><div class="tiny">Artifact-backed benchmark summary</div></td>',
            "</tr>",
        ]
    )


def render_secondary_row(entry: dict[str, Any]) -> str:
    streaming = entry.get("streaming", {})
    missing = []
    if streaming.get("first_partial_end_to_end_mean_ms") is None:
        missing.append("first partial")
    if streaming.get("partial_mean_ms") is None:
        missing.append("partial cadence")
    if streaming.get("final_mean_ms") is None:
        missing.append("finalization")
    gap_reason = "Missing comparable live metrics: " + ", ".join(missing) if missing else "Supporting artifact with a different contract or publication scope."
    return "".join(
        [
            "<tr>",
            f'<td data-label="Lane" class="leader-name"><strong>{html.escape(entry.get("label") or "unknown")}</strong><span>{html.escape(entry.get("backend") or "unknown")} . {html.escape(entry.get("model") or "unknown")}</span><div class="table-note">{html.escape(entry.get("lane") or "unknown")} . {html.escape(entry.get("runtime") or "unknown")}</div></td>',
            f'<td data-label="Why it is secondary">{html.escape(gap_reason)}</td>',
            f'<td data-label="Visible live metrics"><strong>First partial {format_ms(streaming.get("first_partial_end_to_end_mean_ms"))}</strong><div class="tiny">Finalization {format_ms(streaming.get("final_mean_ms"))}</div></td>',
            f'<td data-label="Details"><a href="{html.escape(detail_page_path(entry))}">Open detail page</a><div class="tiny">Measured {html.escape(format_date(entry.get("measured_at")))}</div></td>',
            "</tr>",
        ]
    )


def render_homepage(manifest: dict[str, Any], homepage: str) -> str:
    summary = manifest.get("summary", {})
    entries = published_tracks(manifest)
    ranked = sort_entries(entries)
    primary = sort_entries(primary_entries(ranked))
    secondary = secondary_entries(ranked)
    baseline_entries = comparable_entries(primary)
    first_partial_baseline = min_defined([first_visible_partial(entry) for entry in baseline_entries])
    partial_baseline = min_defined([entry.get("streaming", {}).get("partial_mean_ms") for entry in primary])
    final_baseline = min_defined([entry.get("streaming", {}).get("final_mean_ms") for entry in primary])
    baseline_label = "vs validated fastest" if len(baseline_entries) != len(primary) else "vs fastest"
    max_rest = max([entry.get("rest", {}).get("mean_ms") or 0 for entry in primary] or [1])
    best_primary = primary[0] if primary else None
    alternative = primary[1] if len(primary) > 1 else (secondary[0] if secondary else None)
    best_first_partial = first_visible_partial(best_primary) if best_primary else None
    best_final = best_primary.get("streaming", {}).get("final_mean_ms") if best_primary else None
    recommendation_title = (
        f"Start with {best_primary.get('label')} for live turn-taking." if best_primary else "Use the benchmark as a live ASR shortlist."
    )
    recommendation_copy = (
        f"{best_primary.get('label')} is the strongest publishable default right now: {format_ms(first_visible_partial(best_primary))} first visible partial, {format_ms(best_primary.get('streaming', {}).get('final_mean_ms'))} audio-end finalization, and backlog diagnostics that stay separated from perceived latency." if best_primary else "The homepage now leads with decision-ready comparisons instead of raw benchmark plumbing."
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
        f'<article class="snapshot-card {tone_class(2)}"><div class="section-kicker">Primary ranking scope</div><div class="headline-value">{len(primary)} fully comparable lanes</div><p>{len(secondary)} supporting lanes stay below the fold because they are missing at least one live metric, usually first-partial capture.</p></article>'
    )
    summary_cards.append(
        f'<article class="snapshot-card {tone_class(0)}"><div class="section-kicker">Best live numbers</div><div class="headline-value">{format_ms(best_first_partial)}</div><p>Fastest first visible partial in the primary comparison. Best finalization is {format_ms(best_final)}.</p></article>'
    )
    top_cards = "".join(
        f'<article class="story-card panel {tone_class(index)}"><div class="section-kicker">Rank {index + 1}</div><div class="story-rank">{html.escape(entry.get("label") or "unknown")}</div><div class="chip-row"><div class="chip"><strong>{html.escape(entry.get("runtime") or "unknown")}</strong> runtime</div><div class="chip"><strong>{html.escape(entry.get("lane") or "unknown")}</strong> lane</div></div><p>{html.escape(entry.get("status_detail") or "")}</p></article>'
        for index, entry in enumerate(primary[:3])
    )
    rows = "".join(
        render_row(entry, first_partial_baseline, partial_baseline, final_baseline, baseline_label, max_rest)
        for entry in primary
    )
    secondary_rows = "".join(render_secondary_row(entry) for entry in secondary)
    secondary_section = ""
    if secondary_rows:
        secondary_section = f"""
<div class="comparison-wrap panel" style="margin-top: 16px;">
  <div class="section-head">
    <div>
      <div class="section-kicker">Supporting lanes</div>
      <h2>Artifacts kept out of the primary ranking</h2>
    </div>
    <p class="subcopy">These lanes still add context, but they are missing at least one comparable live metric or were published for a narrower benchmarking purpose.</p>
  </div>
  <div class="comparison-scroll">
    <table>
      <thead>
        <tr><th>Lane</th><th>Why it is secondary</th><th>Visible live metrics</th><th>Details</th></tr>
      </thead>
      <tbody>
{secondary_rows}
      </tbody>
    </table>
  </div>
</div>
""".strip()
    static_summary = f"""
<section class="section-head">
  <div>
    <div class="section-kicker">Launch readout</div>
    <h2>{html.escape(recommendation_title)}</h2>
  </div>
  <p class="subcopy">{html.escape(recommendation_copy)} The main ranking now stays focused on fully comparable live lanes, while incomplete or differently scoped artifacts move into a labeled supporting section.</p>
</section>
<div class="snapshot-grid">
  {''.join(summary_cards)}
</div>
<div class="story-grid">
{top_cards}
</div>
<div class="comparison-wrap panel">
  <div class="comparison-scroll">
    <table>
      <thead>
        <tr><th>Lane</th><th>State</th><th>Score</th><th>{hint('First partial', 'End-to-end time from stream start until the first visible partial transcript appears.')}</th><th>{hint('Partial backlog latency', 'Diagnostic latency for chunk-triggered partial updates after streaming is already underway; this is not perceived first-response latency, so read it alongside partial gap and late partial ratio.')}</th><th>{hint('Audio-end finalization', 'Time from audio end until the final transcript returns; this is closeout delay, not total clip duration.')}</th><th>{hint('REST throughput context', 'Batch request latency for the same backend outside the streaming websocket path. Keep this as throughput context rather than the main live turn-taking signal.')}</th><th>{hint('Samples', 'How many benchmark samples were recorded for this published artifact.')}</th><th>Details</th></tr>
      </thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>
</div>
{secondary_section}
""".strip()
    generated_at = html.escape(
        f"Published {format_date(manifest.get('generated_at'))} . {len(entries)} visible ASR lanes . {summary.get('tracked_count', 0)} tracked lanes in the registry."
    )
    rendered = replace_generated_block(homepage, "generated-at", generated_at)
    return replace_generated_block(rendered, "static-summary", static_summary)


def main() -> None:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    homepage = args.homepage.read_text(encoding="utf-8")
    rendered = render_homepage(manifest, homepage)
    detail_pages = render_detail_pages(manifest, args.manifest, args.detail_dir)
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
                f"Benchmark detail pages are stale: {args.detail_dir}. Run scripts/prerender_benchmark_homepage.py to regenerate them."
            )
        return
    args.homepage.write_text(rendered, encoding="utf-8")
    args.detail_dir.mkdir(parents=True, exist_ok=True)
    for path in orphaned_detail_pages(args.detail_dir, detail_pages):
        path.unlink()
    for path, content in detail_pages.items():
        path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
