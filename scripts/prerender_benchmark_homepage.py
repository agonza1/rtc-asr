#!/usr/bin/env python3
"""Render a crawlable benchmark summary into docs/index.html."""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_MANIFEST_PATH = Path("docs") / "benchmark-results" / "manifest.json"
DEFAULT_HOMEPAGE_PATH = Path("docs") / "index.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prerender benchmark homepage summary")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH, help="Manifest JSON path")
    parser.add_argument("--homepage", type=Path, default=DEFAULT_HOMEPAGE_PATH, help="Homepage HTML path")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when the homepage prerender is stale")
    return parser.parse_args()


def format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} ms"


def format_ratio(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


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


def sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda entry: (
            status_rank(entry),
            numeric(first_visible_partial(entry)),
            numeric(entry.get("streaming", {}).get("partial_mean_ms")),
            numeric(entry.get("streaming", {}).get("final_mean_ms")),
            numeric(entry.get("rest", {}).get("mean_ms")),
        ),
    )


def comparable_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    validated = [entry for entry in entries if entry.get("status") == "validated"]
    return validated or entries


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
            f'<td data-label="Partial response"><strong>{format_ms(partial_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("partial_p95_ms"))}</div><div class="tiny">{delta_text(partial_delta)} vs fastest</div></td>',
            f'<td data-label="Final"><strong>{format_ms(final_value)}</strong><div class="tiny">P95 {format_ms(streaming.get("final_p95_ms"))}</div><div class="tiny">{delta_text(final_delta)} vs fastest</div></td>',
            f'<td data-label="REST"><strong>{format_ms(rest.get("mean_ms"))}</strong><div class="tiny">P95 {format_ms(rest.get("p95_ms"))} . RTF {format_ratio(rest.get("rtf_mean"))}</div><div class="metric-bar"><span style="width:{rest_width}%"></span></div></td>',
            f'<td data-label="Official WER"><strong>{html.escape(entry.get("official_wer_reference") or "see notes")}</strong><div class="tiny">Upstream model-card / benchmark reference</div></td>',
            f'<td data-label="Samples"><strong>{entry.get("sample_count") or "n/a"}</strong><div class="tiny">Measured {html.escape(format_date(entry.get("measured_at")))}</div></td>',
            f'<td data-label="Artifact"><a href="{html.escape(entry.get("artifact_path") or "#")}">open JSON</a></td>',
            "</tr>",
        ]
    )


def render_homepage(manifest: dict[str, Any], homepage: str) -> str:
    summary = manifest.get("summary", {})
    entries = published_tracks(manifest)
    ranked = sort_entries(entries)
    baseline_entries = comparable_entries(ranked)
    first_partial_baseline = min_defined([first_visible_partial(entry) for entry in baseline_entries])
    partial_baseline = min_defined([entry.get("streaming", {}).get("partial_mean_ms") for entry in ranked])
    final_baseline = min_defined([entry.get("streaming", {}).get("final_mean_ms") for entry in ranked])
    baseline_label = "vs validated fastest" if len(baseline_entries) != len(ranked) else "vs fastest"
    max_rest = max([entry.get("rest", {}).get("mean_ms") or 0 for entry in ranked] or [1])
    medians = {
        "first_partial": median([first_visible_partial(entry) for entry in entries]),
        "partial": median([entry.get("streaming", {}).get("partial_mean_ms") for entry in entries]),
        "final": median([entry.get("streaming", {}).get("final_mean_ms") for entry in entries]),
        "rest": median([entry.get("rest", {}).get("mean_ms") for entry in entries]),
    }
    top_cards = "".join(
        f'<article class="story-card panel"><div class="section-kicker">Rank {index + 1}</div><div class="story-rank">{html.escape(entry.get("label") or "unknown")}</div><div class="chip-row"><div class="chip"><strong>{html.escape(entry.get("runtime") or "unknown")}</strong> runtime</div><div class="chip"><strong>{html.escape(entry.get("lane") or "unknown")}</strong> lane</div></div><p>{html.escape(entry.get("status_detail") or "")}</p></article>'
        for index, entry in enumerate(sort_entries(comparable_entries(entries))[:3])
    )
    rows = "".join(
        render_row(entry, first_partial_baseline, partial_baseline, final_baseline, baseline_label, max_rest)
        for entry in ranked
    )
    static_summary = f"""
<section class="section-head">
  <div>
    <div class="section-kicker">Static summary</div>
    <h2>Benchmark content rendered into initial HTML</h2>
  </div>
  <p class="subcopy">Published {len(entries)} visible ASR lanes from {summary.get('tracked_count', 0)} tracked runtime lanes. This prerender keeps the key comparison crawlable before JavaScript enhances the page.</p>
</section>
<div class="snapshot-grid">
  <article class="snapshot-card">
    <div class="section-kicker">Median first partial</div>
    <div class="headline-value">{format_ms(medians['first_partial'])}</div>
    <p>Time until a caller could first see a useful partial in a real-time stream.</p>
  </article>
  <article class="snapshot-card">
    <div class="section-kicker">Median partial response</div>
    <div class="headline-value">{format_ms(medians['partial'])}</div>
    <p>Server response time after a partial trigger, separated from chunk and window cadence.</p>
  </article>
  <article class="snapshot-card">
    <div class="section-kicker">Median final</div>
    <div class="headline-value">{format_ms(medians['final'])}</div>
    <p>How long a caller waits for completed transcript closure after speech ends.</p>
  </article>
  <article class="snapshot-card">
    <div class="section-kicker">Median REST</div>
    <div class="headline-value">{format_ms(medians['rest'])}</div>
    <p>Batch-style request latency for the same published benchmark set.</p>
  </article>
</div>
<div class="story-grid">
{top_cards}
</div>
<div class="comparison-wrap panel">
  <div class="comparison-scroll">
    <table>
      <thead>
        <tr><th>Lane</th><th>State</th><th>Score</th><th>{hint('First partial', 'End-to-end time from stream start until the first visible partial transcript appears.')}</th><th>{hint('Partial response', 'Server response time once a partial-triggering chunk has been sent; this is not time-to-first-partial.')}</th><th>{hint('Final', 'Time from stop or utterance end until the final transcript returns.')}</th><th>{hint('REST', 'Batch request latency for the same backend outside the streaming websocket path.')}</th><th>{hint('Official WER', 'Upstream model-card or benchmark reference numbers, not repo-measured accuracy from this site.')}</th><th>{hint('Samples', 'How many benchmark samples were recorded for this published artifact.')}</th><th>Artifact</th></tr>
      </thead>
      <tbody>
{rows}
      </tbody>
    </table>
  </div>
</div>
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
    if args.check:
        if homepage != rendered:
            raise SystemExit(
                f"Homepage prerender is stale: {args.homepage}. Run scripts/prerender_benchmark_homepage.py to regenerate it."
            )
        return
    args.homepage.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
