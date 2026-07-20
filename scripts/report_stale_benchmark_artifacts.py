#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from build_benchmark_manifest import DEFAULT_RESULTS_DIR, DEFAULT_TRACKS_PATH, build_manifest

SUMMARY_GROUPS = (
    "slug",
    "artifact-name",
    "artifact-dir",
    "status",
    "backend",
    "model",
    "label",
    "current-artifact",
    "current-artifact-name",
    "track-state",
    "detail-page",
    "detail-page-name",
    "measured-month",
)


def format_bytes(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"

    units = ("B", "KiB", "MiB", "GiB")
    size = float(size_bytes)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report stale benchmark artifacts")
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
        "--older-than-days",
        type=int,
        default=None,
        help="Only include stale artifacts measured before this many days ago",
    )
    parser.add_argument(
        "--measured-before",
        default=None,
        help="Only include stale artifacts measured before this ISO timestamp or date",
    )
    parser.add_argument(
        "--measured-after",
        default=None,
        help="Only include stale artifacts measured after this ISO timestamp or date",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only print the first N stale artifacts after filtering and sorting",
    )
    parser.add_argument(
        "--sort",
        choices=(
            "size",
            "size-asc",
            "measured-at",
            "measured-at-desc",
            "path",
            "artifact-name",
            "artifact-dir",
            "detail-page",
            "detail-page-name",
            "status",
            "backend",
            "model",
            "label",
            "slug",
            "track-state",
            "current-path",
            "current-path-name",
            "measured-month",
        ),
        default="size",
        help="Sort stale artifacts before applying --limit",
    )
    parser.add_argument(
        "--min-size-bytes",
        type=int,
        default=None,
        help="Only include stale artifacts at least this many bytes large",
    )
    parser.add_argument(
        "--max-size-bytes",
        type=int,
        default=None,
        help="Only include stale artifacts no larger than this many bytes",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=None,
        help="Only include stale artifacts for this benchmark track slug; repeat to include multiple slugs",
    )
    parser.add_argument(
        "--slug-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose track slug contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Only include stale artifacts whose label contains this text; repeat to include multiple labels",
    )
    parser.add_argument(
        "--backend",
        action="append",
        default=None,
        help="Only include stale artifacts for this backend; repeat to include multiple backends",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="Only include stale artifacts whose model contains this text; repeat to include multiple models",
    )
    parser.add_argument(
        "--measured-month",
        action="append",
        default=None,
        help="Only include stale artifacts measured in this UTC YYYY-MM month; repeat to include multiple months",
    )
    parser.add_argument(
        "--current-path",
        action="append",
        default=None,
        help="Only include stale artifacts whose track currently points at this artifact path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--current-path-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file name matches this name; repeat to include multiple names",
    )
    parser.add_argument(
        "--current-path-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--track-state",
        choices=("any", "tracked", "untracked"),
        default="any",
        help="Filter stale artifacts by whether their slug still maps to a current benchmark track",
    )
    parser.add_argument(
        "--artifact-path",
        action="append",
        default=None,
        help="Only include this stale artifact path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--artifact-path-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose artifact path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--artifact-name",
        action="append",
        default=None,
        help="Only include stale artifacts with this file name; repeat to include multiple names",
    )
    parser.add_argument(
        "--artifact-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page path matches this path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--detail-page-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file name matches this name; repeat to include multiple names",
    )
    parser.add_argument(
        "--detail-page-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help="Only include stale artifacts with this status; repeat to include multiple statuses; use 'any' for all statuses (default: legacy)",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero when matching stale artifacts are found",
    )
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Print one stale artifact path per line for cleanup scripts",
    )
    parser.add_argument(
        "-0",
        "--null",
        action="store_true",
        help="With --paths-only, separate paths with NUL bytes for safe xargs -0 cleanup",
    )
    parser.add_argument(
        "--include-detail-pages",
        action="store_true",
        help="With --paths-only, also print matching prerendered detail page paths",
    )
    parser.add_argument(
        "--detail-pages-only",
        action="store_true",
        help="With --paths-only, only print matching prerendered detail page paths",
    )
    parser.add_argument(
        "--existing-paths-only",
        action="store_true",
        help="With --paths-only, only print artifact or detail page paths that exist on disk",
    )
    parser.add_argument(
        "--missing-paths-only",
        action="store_true",
        help="With --paths-only, only print artifact or detail page paths that are missing on disk",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--count-only", action="store_true", help="Print only the matching stale artifact count")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only stale artifact totals grouped by track slug",
    )
    parser.add_argument(
        "--summary-group",
        action="append",
        default=None,
        help="With --summary-only, only print this grouping; repeat or comma-separate to include multiple groups",
    )
    parser.add_argument(
        "--summary-limit",
        type=int,
        default=None,
        help="With --summary-only, print at most this many rows per grouping",
    )
    return parser.parse_args(argv)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_required_timestamp(value: str, *, field_name: str) -> datetime:
    parsed = parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be an ISO timestamp or date")
    return parsed


def detail_page_path(artifact_path: str | None) -> str | None:
    if not artifact_path:
        return None
    artifact_name = Path(artifact_path).name
    if not artifact_name.endswith(".json"):
        return None
    return f"benchmark-results/pages/{Path(artifact_name).stem}.html"


def normalize_status_filters(statuses: list[str] | None) -> set[str] | None:
    if statuses is None:
        return {"legacy"}
    normalized = {
        status.strip().lower()
        for value in statuses
        for status in value.split(",")
        if status.strip()
    }
    return None if "any" in normalized else normalized


def normalize_filter_values(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [
        item.strip()
        for value in values
        for item in value.split(",")
        if item.strip()
    ]


def measured_month(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y-%m")


def normalize_summary_groups(groups: list[str] | None) -> set[str]:
    return {
        group.strip()
        for value in (groups or list(SUMMARY_GROUPS))
        for group in value.split(",")
        if group.strip()
    }


def stale_artifacts(
    manifest: dict[str, Any],
    *,
    older_than_days: int | None = None,
    measured_before: datetime | str | None = None,
    measured_after: datetime | str | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
    slugs: list[str] | None = None,
    slug_contains: list[str] | None = None,
    labels: list[str] | None = None,
    backends: list[str] | None = None,
    models: list[str] | None = None,
    current_paths: list[str] | None = None,
    current_path_contains: list[str] | None = None,
    current_path_names: list[str] | None = None,
    current_path_name_contains: list[str] | None = None,
    track_state: str = "any",
    measured_months: list[str] | None = None,
    artifact_paths: list[str] | None = None,
    artifact_path_contains: list[str] | None = None,
    artifact_names: list[str] | None = None,
    artifact_name_contains: list[str] | None = None,
    detail_pages: list[str] | None = None,
    detail_page_contains: list[str] | None = None,
    detail_page_names: list[str] | None = None,
    detail_page_name_contains: list[str] | None = None,
    statuses: list[str] | None = None,
    now: datetime | None = None,
    sort_by: str = "size",
) -> list[dict[str, Any]]:
    if min_size_bytes is not None and min_size_bytes < 0:
        raise ValueError("min_size_bytes must be non-negative")
    if max_size_bytes is not None and max_size_bytes < 0:
        raise ValueError("max_size_bytes must be non-negative")
    if min_size_bytes is not None and max_size_bytes is not None and min_size_bytes > max_size_bytes:
        raise ValueError("min_size_bytes cannot exceed max_size_bytes")
    if track_state not in {"any", "tracked", "untracked"}:
        raise ValueError("track_state must be one of: any, tracked, untracked")
    slugs = normalize_filter_values(slugs)
    slug_contains = normalize_filter_values(slug_contains)
    labels = normalize_filter_values(labels)
    backends = normalize_filter_values(backends)
    models = normalize_filter_values(models)
    measured_months = normalize_filter_values(measured_months)
    current_paths = normalize_filter_values(current_paths)
    current_path_contains = normalize_filter_values(current_path_contains)
    current_path_names = normalize_filter_values(current_path_names)
    current_path_name_contains = normalize_filter_values(current_path_name_contains)
    artifact_paths = normalize_filter_values(artifact_paths)
    artifact_path_contains = normalize_filter_values(artifact_path_contains)
    artifact_names = normalize_filter_values(artifact_names)
    artifact_name_contains = normalize_filter_values(artifact_name_contains)
    detail_pages = normalize_filter_values(detail_pages)
    detail_page_contains = normalize_filter_values(detail_page_contains)
    detail_page_names = normalize_filter_values(detail_page_names)
    detail_page_name_contains = normalize_filter_values(detail_page_name_contains)
    allowed_measured_months = None
    if measured_months is not None:
        allowed_measured_months = {month.strip() for month in measured_months if month.strip()}
        invalid_months = [month for month in allowed_measured_months if len(month) != 7 or month[4] != "-"]
        if invalid_months:
            raise ValueError("measured_month values must use YYYY-MM")

    cutoff = None
    if older_than_days is not None:
        if older_than_days < 0:
            raise ValueError("older_than_days must be non-negative")
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        cutoff = reference.astimezone(UTC) - timedelta(days=older_than_days)
    if measured_before is not None:
        measured_before_cutoff = (
            parse_required_timestamp(measured_before, field_name="measured_before")
            if isinstance(measured_before, str)
            else measured_before
        )
        if measured_before_cutoff.tzinfo is None:
            measured_before_cutoff = measured_before_cutoff.replace(tzinfo=UTC)
        measured_before_cutoff = measured_before_cutoff.astimezone(UTC)
        cutoff = min(cutoff, measured_before_cutoff) if cutoff is not None else measured_before_cutoff
    lower_cutoff = None
    if measured_after is not None:
        lower_cutoff = (
            parse_required_timestamp(measured_after, field_name="measured_after")
            if isinstance(measured_after, str)
            else measured_after
        )
        if lower_cutoff.tzinfo is None:
            lower_cutoff = lower_cutoff.replace(tzinfo=UTC)
        lower_cutoff = lower_cutoff.astimezone(UTC)
    if cutoff is not None and lower_cutoff is not None and lower_cutoff >= cutoff:
        raise ValueError("measured_after must be earlier than the effective measured-before cutoff")

    tracks = [track for track in manifest.get("tracks", []) if track.get("artifact_path")]
    current_artifact_paths = {track["artifact_path"] for track in tracks}
    current_path_by_slug = {track.get("slug"): track.get("artifact_path") for track in tracks if track.get("slug")}
    allowed_backends = None if backends is None else {backend.lower() for backend in backends}
    allowed_current_paths = None if current_paths is None else set(current_paths)
    current_path_needles = None if current_path_contains is None else [needle.lower() for needle in current_path_contains]
    allowed_current_path_names = (
        None if current_path_names is None else {Path(name).name for name in current_path_names}
    )
    current_path_name_needles = (
        None if current_path_name_contains is None else [needle.lower() for needle in current_path_name_contains]
    )
    allowed_artifact_paths = None if artifact_paths is None else set(artifact_paths)
    slug_needles = None if slug_contains is None else [needle.lower() for needle in slug_contains]
    artifact_path_needles = (
        None if artifact_path_contains is None else [needle.lower() for needle in artifact_path_contains]
    )
    allowed_artifact_names = None if artifact_names is None else {Path(name).name for name in artifact_names}
    artifact_name_needles = (
        None if artifact_name_contains is None else [needle.lower() for needle in artifact_name_contains]
    )
    allowed_detail_pages = None if detail_pages is None else set(detail_pages)
    detail_page_needles = None if detail_page_contains is None else [needle.lower() for needle in detail_page_contains]
    allowed_detail_page_names = None if detail_page_names is None else {Path(name).name for name in detail_page_names}
    detail_page_name_needles = (
        None if detail_page_name_contains is None else [needle.lower() for needle in detail_page_name_contains]
    )
    allowed_statuses = normalize_status_filters(statuses)
    stale: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        artifact_path = artifact.get("artifact_path")
        if not artifact_path or artifact_path in current_artifact_paths:
            continue
        if allowed_artifact_paths is not None and artifact_path not in allowed_artifact_paths:
            continue
        if artifact_path_needles is not None:
            artifact_path_text = artifact_path.lower()
            if not any(needle in artifact_path_text for needle in artifact_path_needles):
                continue
        artifact_name = Path(artifact_path).name
        if allowed_artifact_names is not None and artifact_name not in allowed_artifact_names:
            continue
        if artifact_name_needles is not None and not any(
            needle in artifact_name.lower() for needle in artifact_name_needles
        ):
            continue
        artifact_detail_page_path = detail_page_path(artifact_path)
        if allowed_detail_pages is not None and artifact_detail_page_path not in allowed_detail_pages:
            continue
        if detail_page_needles is not None:
            detail_page_text = str(artifact_detail_page_path or "").lower()
            if not any(needle in detail_page_text for needle in detail_page_needles):
                continue
        detail_page_name = Path(artifact_detail_page_path or "").name
        if allowed_detail_page_names is not None and detail_page_name not in allowed_detail_page_names:
            continue
        if detail_page_name_needles is not None:
            if not any(needle in detail_page_name.lower() for needle in detail_page_name_needles):
                continue
        artifact_status = str(artifact.get("status") or "").lower()
        if allowed_statuses is not None and artifact_status not in allowed_statuses:
            continue
        if slugs is not None and artifact.get("slug") not in slugs:
            continue
        if labels is not None:
            artifact_label = str(artifact.get("label") or "").lower()
            if not any(label.lower() in artifact_label for label in labels):
                continue
        artifact_backend = str(artifact.get("backend") or "").lower()
        if allowed_backends is not None and artifact_backend not in allowed_backends:
            continue
        if models is not None:
            artifact_model = str(artifact.get("model") or "").lower()
            if not any(model.lower() in artifact_model for model in models):
                continue
        current_artifact_path = current_path_by_slug.get(artifact.get("slug"))
        if allowed_current_paths is not None and current_artifact_path not in allowed_current_paths:
            continue
        if current_path_needles is not None:
            current_path_text = str(current_artifact_path or "").lower()
            if not any(needle in current_path_text for needle in current_path_needles):
                continue
        current_path_name = Path(current_artifact_path or "").name
        if allowed_current_path_names is not None and current_path_name not in allowed_current_path_names:
            continue
        if current_path_name_needles is not None:
            if not any(needle in current_path_name.lower() for needle in current_path_name_needles):
                continue
        if track_state == "tracked" and current_artifact_path is None:
            continue
        if track_state == "untracked" and current_artifact_path is not None:
            continue
        if slug_needles is not None:
            artifact_slug = str(artifact.get("slug") or "").lower()
            if not any(needle in artifact_slug for needle in slug_needles):
                continue
        measured_at = artifact.get("measured_at")
        measured_timestamp = parse_timestamp(measured_at)
        artifact_measured_month = measured_month(measured_at)
        if allowed_measured_months is not None and artifact_measured_month not in allowed_measured_months:
            continue
        if cutoff is not None and (measured_timestamp is None or measured_timestamp >= cutoff):
            continue
        if lower_cutoff is not None and (measured_timestamp is None or measured_timestamp <= lower_cutoff):
            continue
        artifact_size_bytes = artifact.get("artifact_size_bytes")
        if min_size_bytes is not None and (artifact_size_bytes or 0) < min_size_bytes:
            continue
        if max_size_bytes is not None and (artifact_size_bytes or 0) > max_size_bytes:
            continue
        stale.append(
            {
                "artifact_path": artifact_path,
                "slug": artifact.get("slug"),
                "label": artifact.get("label"),
                "backend": artifact.get("backend"),
                "model": artifact.get("model"),
                "status": artifact.get("status"),
                "measured_at": measured_at,
                "measured_month": artifact_measured_month,
                "current_artifact_path": current_artifact_path,
                "track_state": "tracked" if current_artifact_path is not None else "untracked",
                "detail_page_path": artifact_detail_page_path,
                "artifact_size_bytes": artifact_size_bytes,
                "artifact_size": format_bytes(artifact_size_bytes),
            }
        )
    if sort_by == "size":
        return sorted(
            stale,
            key=lambda entry: (
                -(entry.get("artifact_size_bytes") or 0),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "size-asc":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("artifact_size_bytes") or 0,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-at":
        return sorted(
            stale,
            key=lambda entry: (
                parse_timestamp(entry.get("measured_at")) or datetime.max.replace(tzinfo=UTC),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-at-desc":
        return sorted(
            stale,
            key=lambda entry: (
                -(parse_timestamp(entry.get("measured_at")) or datetime.min.replace(tzinfo=UTC)).timestamp(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "path":
        return sorted(stale, key=lambda entry: entry.get("artifact_path") or "")
    if sort_by == "artifact-name":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-dir":
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("artifact_path") or "").parent),
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page":
        return sorted(stale, key=lambda entry: entry.get("detail_page_path") or "")
    if sort_by == "detail-page-name":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "status":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("status") or "unknown").lower(),
                entry.get("slug") or "untracked",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "backend":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("backend") or "unknown").lower(),
                str(entry.get("model") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "model":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("model") or "unknown").lower(),
                str(entry.get("backend") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "label":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("label") or "unknown").lower(),
                str(entry.get("backend") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "slug":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("slug") or "untracked").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "track-state":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("track_state") or "untracked").lower(),
                str(entry.get("slug") or "untracked").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-name":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-month":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_month") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    raise ValueError(
        "sort_by must be one of: size, size-asc, measured-at, measured-at-desc, path, artifact-name, artifact-dir, detail-page, detail-page-name, status, backend, model, label, slug, track-state, current-path, current-path-name, measured-month"
    )


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    by_slug: dict[str, dict[str, Any]] = {}
    by_artifact_name: dict[str, dict[str, Any]] = {}
    by_artifact_dir: dict[str, dict[str, Any]] = {}
    by_status: dict[str, dict[str, Any]] = {}
    by_backend: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    by_current_artifact_path: dict[str, dict[str, Any]] = {}
    by_current_artifact_name: dict[str, dict[str, Any]] = {}
    by_track_state: dict[str, dict[str, Any]] = {}
    by_detail_page_path: dict[str, dict[str, Any]] = {}
    by_detail_page_name: dict[str, dict[str, Any]] = {}
    by_measured_month: dict[str, dict[str, Any]] = {}
    for entry in stale:
        slug = str(entry.get("slug") or "untracked")
        bucket = by_slug.setdefault(
            slug,
            {
                "slug": slug,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        bucket["count"] += 1
        bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        bucket["total_size"] = format_bytes(bucket["total_size_bytes"])

        artifact_name = Path(entry.get("artifact_path") or "").name or "unknown"
        artifact_name_bucket = by_artifact_name.setdefault(
            artifact_name,
            {
                "artifact_name": artifact_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_name_bucket["count"] += 1
        artifact_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_name_bucket["total_size"] = format_bytes(artifact_name_bucket["total_size_bytes"])

        artifact_dir = str(Path(entry.get("artifact_path") or "").parent) or "."
        artifact_dir_bucket = by_artifact_dir.setdefault(
            artifact_dir,
            {
                "artifact_dir": artifact_dir,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_dir_bucket["count"] += 1
        artifact_dir_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_dir_bucket["total_size"] = format_bytes(artifact_dir_bucket["total_size_bytes"])

        status = str(entry.get("status") or "unknown")
        status_bucket = by_status.setdefault(
            status,
            {
                "status": status,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        status_bucket["count"] += 1
        status_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        status_bucket["total_size"] = format_bytes(status_bucket["total_size_bytes"])

        backend = str(entry.get("backend") or "unknown")
        backend_bucket = by_backend.setdefault(
            backend,
            {
                "backend": backend,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        backend_bucket["count"] += 1
        backend_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        backend_bucket["total_size"] = format_bytes(backend_bucket["total_size_bytes"])

        model = str(entry.get("model") or "unknown")
        model_bucket = by_model.setdefault(
            model,
            {
                "model": model,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        model_bucket["count"] += 1
        model_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        model_bucket["total_size"] = format_bytes(model_bucket["total_size_bytes"])

        label = str(entry.get("label") or "unknown")
        label_bucket = by_label.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        label_bucket["count"] += 1
        label_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        label_bucket["total_size"] = format_bytes(label_bucket["total_size_bytes"])

        current_artifact_path = str(entry.get("current_artifact_path") or "untracked")
        current_bucket = by_current_artifact_path.setdefault(
            current_artifact_path,
            {
                "current_artifact_path": current_artifact_path,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_bucket["count"] += 1
        current_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_bucket["total_size"] = format_bytes(current_bucket["total_size_bytes"])

        current_artifact_name = Path(entry.get("current_artifact_path") or "").name or "untracked"
        current_name_bucket = by_current_artifact_name.setdefault(
            current_artifact_name,
            {
                "current_artifact_name": current_artifact_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_name_bucket["count"] += 1
        current_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_name_bucket["total_size"] = format_bytes(current_name_bucket["total_size_bytes"])

        track_state = str(entry.get("track_state") or "untracked")
        track_state_bucket = by_track_state.setdefault(
            track_state,
            {
                "track_state": track_state,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        track_state_bucket["count"] += 1
        track_state_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        track_state_bucket["total_size"] = format_bytes(track_state_bucket["total_size_bytes"])

        detail_page = str(entry.get("detail_page_path") or "missing")
        detail_bucket = by_detail_page_path.setdefault(
            detail_page,
            {
                "detail_page_path": detail_page,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_bucket["count"] += 1
        detail_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_bucket["total_size"] = format_bytes(detail_bucket["total_size_bytes"])

        detail_page_name = Path(entry.get("detail_page_path") or "").name or "missing"
        detail_name_bucket = by_detail_page_name.setdefault(
            detail_page_name,
            {
                "detail_page_name": detail_page_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_name_bucket["count"] += 1
        detail_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_name_bucket["total_size"] = format_bytes(detail_name_bucket["total_size_bytes"])

        month = measured_month(entry.get("measured_at"))
        month_bucket = by_measured_month.setdefault(
            month,
            {
                "measured_month": month,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        month_bucket["count"] += 1
        month_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        month_bucket["total_size"] = format_bytes(month_bucket["total_size_bytes"])

    return {
        "count": len(stale),
        "total_size_bytes": total_size_bytes,
        "total_size": format_bytes(total_size_bytes),
        "by_slug": sorted(
            by_slug.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["slug"]),
        ),
        "by_artifact_name": sorted(
            by_artifact_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_name"]),
        ),
        "by_artifact_dir": sorted(
            by_artifact_dir.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_dir"]),
        ),
        "by_status": sorted(
            by_status.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["status"]),
        ),
        "by_backend": sorted(
            by_backend.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["backend"]),
        ),
        "by_model": sorted(
            by_model.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["model"]),
        ),
        "by_label": sorted(
            by_label.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["label"]),
        ),
        "by_current_artifact_path": sorted(
            by_current_artifact_path.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_path"]),
        ),
        "by_current_artifact_name": sorted(
            by_current_artifact_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_name"]),
        ),
        "by_track_state": sorted(
            by_track_state.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["track_state"]),
        ),
        "by_detail_page_path": sorted(
            by_detail_page_path.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_path"]),
        ),
        "by_detail_page_name": sorted(
            by_detail_page_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_name"]),
        ),
        "by_measured_month": sorted(
            by_measured_month.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_month"]),
        ),
        "artifacts": stale,
    }


def limit_artifacts(stale: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return stale
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return stale[:limit]


def render_text(
    stale: list[dict[str, Any]],
    *,
    total_count: int | None = None,
    total_size_bytes: int | None = None,
) -> str:
    if not stale:
        if total_count:
            return (
                f"Found {total_count} stale benchmark artifacts, but 0 are shown "
                "because --limit omitted all matches."
            )
        return "No stale benchmark artifacts found."
    summary = stale_summary(stale)
    total_count = total_count if total_count is not None else summary["count"]
    shown_noun = "artifact" if summary["count"] == 1 else "artifacts"
    lines = [
        "Found {count} stale benchmark {noun} ({size}, {bytes} bytes):".format(
            count=summary["count"],
            noun=shown_noun,
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    for entry in stale:
        current_artifact_path = entry.get("current_artifact_path")
        current_suffix = f"; current: {current_artifact_path}" if current_artifact_path else ""
        detail_page_path = entry.get("detail_page_path")
        detail_suffix = f"; detail: {detail_page_path}" if detail_page_path else ""
        status = entry.get("status") or "unknown"
        lines.append(
            "- {artifact_path} [{slug}] status {status} measured {measured_at} ({artifact_size}){current_suffix}{detail_suffix}".format(
                artifact_path=entry["artifact_path"],
                slug=entry.get("slug") or "untracked",
                status=status,
                measured_at=entry.get("measured_at") or "unknown",
                artifact_size=entry.get("artifact_size") or format_bytes(entry.get("artifact_size_bytes")),
                current_suffix=current_suffix,
                detail_suffix=detail_suffix,
            )
        )
    if total_count > summary["count"]:
        suffix = ""
        if total_size_bytes is not None:
            omitted_size_bytes = max(total_size_bytes - summary["total_size_bytes"], 0)
            suffix = f" ({format_bytes(omitted_size_bytes)}, {omitted_size_bytes} bytes)"
        omitted_count = total_count - summary["count"]
        omitted_noun = "artifact" if omitted_count == 1 else "artifacts"
        lines.append(f"... {omitted_count} more stale {omitted_noun}{suffix} omitted by --limit.")
    return "\n".join(lines)


def render_paths(
    stale: list[dict[str, Any]],
    *,
    include_detail_pages: bool = False,
    detail_pages_only: bool = False,
    existing_root: Path | None = None,
    missing_root: Path | None = None,
    separator: str = "\n",
) -> str:
    paths = []

    def append_path_once(path: str) -> None:
        if path not in paths:
            paths.append(path)

    for entry in stale:
        if not detail_pages_only:
            artifact_path = entry["artifact_path"]
            if existing_root is None or (existing_root / artifact_path).exists():
                if missing_root is None or not (missing_root / artifact_path).exists():
                    append_path_once(artifact_path)
        detail_path = entry.get("detail_page_path")
        if (include_detail_pages or detail_pages_only) and detail_path:
            if existing_root is not None and not (existing_root / detail_path).exists():
                continue
            if missing_root is not None and (missing_root / detail_path).exists():
                continue
            append_path_once(detail_path)
    return separator.join(paths)


def limit_summary_buckets(buckets: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return buckets
    if limit < 0:
        raise ValueError("summary_limit must be non-negative")
    return buckets[:limit]


def append_omitted_summary_buckets(
    lines: list[str],
    buckets: list[dict[str, Any]],
    shown_buckets: list[dict[str, Any]],
    *,
    limit: int | None,
) -> None:
    if limit is None or len(buckets) <= len(shown_buckets):
        return
    omitted_count = len(buckets) - len(shown_buckets)
    omitted_size_bytes = sum(bucket["total_size_bytes"] for bucket in buckets[len(shown_buckets) :])
    noun = "bucket" if omitted_count == 1 else "buckets"
    lines.append(
        "... {count} more {noun} ({size}, {bytes} bytes) omitted by --summary-limit.".format(
            count=omitted_count,
            noun=noun,
            size=format_bytes(omitted_size_bytes),
            bytes=omitted_size_bytes,
        )
    )


def render_summary(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
) -> str:
    if summary_limit is not None and summary_limit < 0:
        raise ValueError("summary_limit must be non-negative")
    allowed_groups = set(SUMMARY_GROUPS)
    selected_groups = normalize_summary_groups(groups)
    unknown_groups = sorted(selected_groups - allowed_groups)
    if unknown_groups:
        raise ValueError(f"summary groups must be one of: {', '.join(SUMMARY_GROUPS)}")

    summary = stale_summary(stale)
    total_noun = "artifact" if summary["count"] == 1 else "artifacts"
    lines = [
        "Found {count} stale benchmark {total_noun} ({size}, {bytes} bytes).".format(
            count=summary["count"],
            total_noun=total_noun,
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    if "slug" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_slug"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {slug}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    slug=bucket["slug"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_slug"], shown_buckets, limit=summary_limit)
    if "artifact-name" in selected_groups and summary["by_artifact_name"]:
        lines.append("By artifact name:")
    if "artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_artifact_name"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_name=bucket["artifact_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_artifact_name"], shown_buckets, limit=summary_limit)
    if "artifact-dir" in selected_groups and summary["by_artifact_dir"]:
        lines.append("By artifact directory:")
    if "artifact-dir" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_artifact_dir"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_dir}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_dir=bucket["artifact_dir"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_artifact_dir"], shown_buckets, limit=summary_limit)
    if "status" in selected_groups and summary["by_status"]:
        lines.append("By status:")
    if "status" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_status"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {status}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    status=bucket["status"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_status"], shown_buckets, limit=summary_limit)
    if "backend" in selected_groups and summary["by_backend"]:
        lines.append("By backend:")
    if "backend" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_backend"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {backend}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    backend=bucket["backend"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_backend"], shown_buckets, limit=summary_limit)
    if "model" in selected_groups and summary["by_model"]:
        lines.append("By model:")
    if "model" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_model"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {model}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    model=bucket["model"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_model"], shown_buckets, limit=summary_limit)
    if "label" in selected_groups and any(bucket["label"] != "unknown" for bucket in summary["by_label"]):
        lines.append("By label:")
        shown_buckets = limit_summary_buckets(summary["by_label"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {label}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    label=bucket["label"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_label"], shown_buckets, limit=summary_limit)
    if "current-artifact" in selected_groups and summary["by_current_artifact_path"]:
        lines.append("By current artifact:")
    if "current-artifact" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_current_artifact_path"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_path}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_path=bucket["current_artifact_path"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_current_artifact_path"], shown_buckets, limit=summary_limit)
    if "current-artifact-name" in selected_groups and summary["by_current_artifact_name"]:
        lines.append("By current artifact name:")
    if "current-artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_current_artifact_name"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_name=bucket["current_artifact_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_current_artifact_name"], shown_buckets, limit=summary_limit)
    if "track-state" in selected_groups and summary["by_track_state"]:
        lines.append("By track state:")
    if "track-state" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_track_state"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {track_state}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    track_state=bucket["track_state"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_track_state"], shown_buckets, limit=summary_limit)
    if "detail-page" in selected_groups and summary["by_detail_page_path"]:
        lines.append("By detail page:")
    if "detail-page" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_detail_page_path"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_path}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_path=bucket["detail_page_path"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_detail_page_path"], shown_buckets, limit=summary_limit)
    if "detail-page-name" in selected_groups and summary["by_detail_page_name"]:
        lines.append("By detail page name:")
    if "detail-page-name" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_detail_page_name"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_name=bucket["detail_page_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_detail_page_name"], shown_buckets, limit=summary_limit)
    if "measured-month" in selected_groups and summary["by_measured_month"]:
        lines.append("By measured month:")
    if "measured-month" in selected_groups:
        shown_buckets = limit_summary_buckets(summary["by_measured_month"], summary_limit)
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {measured_month}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    measured_month=bucket["measured_month"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(lines, summary["by_measured_month"], shown_buckets, limit=summary_limit)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.json and args.paths_only:
        raise ValueError("--json and --paths-only cannot be used together")
    if args.count_only and args.json:
        raise ValueError("--count-only and --json cannot be used together")
    if args.count_only and args.paths_only:
        raise ValueError("--count-only and --paths-only cannot be used together")
    if args.summary_only and args.json:
        raise ValueError("--summary-only and --json cannot be used together")
    if args.summary_only and args.paths_only:
        raise ValueError("--summary-only and --paths-only cannot be used together")
    if args.summary_only and args.count_only:
        raise ValueError("--summary-only and --count-only cannot be used together")
    if args.summary_group and not args.summary_only:
        raise ValueError("--summary-group requires --summary-only")
    if args.summary_limit is not None and not args.summary_only:
        raise ValueError("--summary-limit requires --summary-only")
    if args.include_detail_pages and not args.paths_only:
        raise ValueError("--include-detail-pages requires --paths-only")
    if args.detail_pages_only and not args.paths_only:
        raise ValueError("--detail-pages-only requires --paths-only")
    if args.null and not args.paths_only:
        raise ValueError("--null requires --paths-only")
    if args.existing_paths_only and not args.paths_only:
        raise ValueError("--existing-paths-only requires --paths-only")
    if args.missing_paths_only and not args.paths_only:
        raise ValueError("--missing-paths-only requires --paths-only")
    if args.existing_paths_only and args.missing_paths_only:
        raise ValueError("--existing-paths-only cannot be combined with --missing-paths-only")
    if args.detail_pages_only and args.include_detail_pages:
        raise ValueError("--detail-pages-only cannot be combined with --include-detail-pages")

    manifest = build_manifest(args.results_dir, args.tracks)
    stale = stale_artifacts(
        manifest,
        older_than_days=args.older_than_days,
        measured_before=args.measured_before,
        measured_after=args.measured_after,
        min_size_bytes=args.min_size_bytes,
        max_size_bytes=args.max_size_bytes,
        slugs=args.slug,
        slug_contains=args.slug_contains,
        labels=args.label,
        backends=args.backend,
        models=args.model,
        measured_months=args.measured_month,
        current_paths=args.current_path,
        current_path_contains=args.current_path_contains,
        current_path_names=args.current_path_name,
        current_path_name_contains=args.current_path_name_contains,
        track_state=args.track_state,
        artifact_paths=args.artifact_path,
        artifact_path_contains=args.artifact_path_contains,
        artifact_names=args.artifact_name,
        artifact_name_contains=args.artifact_name_contains,
        detail_pages=args.detail_page,
        detail_page_contains=args.detail_page_contains,
        detail_page_names=args.detail_page_name,
        detail_page_name_contains=args.detail_page_name_contains,
        statuses=args.status,
        sort_by=args.sort,
    )
    limited_stale = limit_artifacts(stale, args.limit)
    if args.count_only:
        print(len(stale))
    elif args.summary_only:
        print(render_summary(stale, groups=args.summary_group, summary_limit=args.summary_limit))
    elif args.paths_only:
        rendered_paths = render_paths(
            limited_stale,
            include_detail_pages=args.include_detail_pages,
            detail_pages_only=args.detail_pages_only,
            existing_root=args.results_dir.parent if args.existing_paths_only else None,
            missing_root=args.results_dir.parent if args.missing_paths_only else None,
            separator="\0" if args.null else "\n",
        )
        if args.null:
            sys.stdout.write(rendered_paths)
        else:
            print(rendered_paths)
    elif args.json:
        summary = stale_summary(limited_stale)
        summary["total_matching_count"] = len(stale)
        matching_summary = stale_summary(stale)
        summary["total_matching_size_bytes"] = matching_summary["total_size_bytes"]
        summary["total_matching_size"] = matching_summary["total_size"]
        print(json.dumps(summary, indent=2))
    else:
        matching_summary = stale_summary(stale)
        print(
            render_text(
                limited_stale,
                total_count=len(stale),
                total_size_bytes=matching_summary["total_size_bytes"],
            )
        )
    return 1 if args.fail_on_stale and stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
