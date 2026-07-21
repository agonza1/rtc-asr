#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from build_benchmark_manifest import DEFAULT_RESULTS_DIR, DEFAULT_TRACKS_PATH, build_manifest

SUMMARY_GROUPS = (
    "slug",
    "artifact-name",
    "artifact-stem",
    "artifact-dir",
    "artifact-extension",
    "status",
    "backend",
    "model",
    "label",
    "current-artifact",
    "current-artifact-name",
    "current-artifact-stem",
    "current-artifact-extension",
    "track-state",
    "detail-page",
    "detail-page-name",
    "measured-month",
    "age-bucket",
)

SUMMARY_GROUP_KEYS = {
    "slug": "by_slug",
    "artifact-name": "by_artifact_name",
    "artifact-stem": "by_artifact_stem",
    "artifact-dir": "by_artifact_dir",
    "artifact-extension": "by_artifact_extension",
    "status": "by_status",
    "backend": "by_backend",
    "model": "by_model",
    "label": "by_label",
    "current-artifact": "by_current_artifact_path",
    "current-artifact-name": "by_current_artifact_name",
    "current-artifact-stem": "by_current_artifact_stem",
    "current-artifact-extension": "by_current_artifact_extension",
    "track-state": "by_track_state",
    "detail-page": "by_detail_page_path",
    "detail-page-name": "by_detail_page_name",
    "measured-month": "by_measured_month",
    "age-bucket": "by_age_bucket",
}

AGE_BUCKET_ORDER = {
    "0-6d": 0,
    "7-29d": 1,
    "30-89d": 2,
    "90d+": 3,
    "unknown": 4,
}


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


def format_age_days(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    noun = "day" if age_days == 1 else "days"
    return f"{age_days} {noun}"


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
            "age",
            "age-asc",
            "measured-at",
            "measured-at-desc",
            "path",
            "path-desc",
            "artifact-name",
            "artifact-name-desc",
            "artifact-dir",
            "artifact-dir-desc",
            "artifact-extension",
            "artifact-extension-desc",
            "detail-page",
            "detail-page-desc",
            "detail-page-name",
            "detail-page-name-desc",
            "artifact-stem",
            "artifact-stem-desc",
            "status",
            "status-desc",
            "backend",
            "backend-desc",
            "model",
            "model-desc",
            "label",
            "label-desc",
            "slug",
            "slug-desc",
            "track-state",
            "track-state-desc",
            "current-path",
            "current-path-desc",
            "current-path-name",
            "current-path-name-desc",
            "current-path-stem",
            "current-path-stem-desc",
            "current-path-extension",
            "current-path-extension-desc",
            "measured-month",
            "measured-month-desc",
            "age-bucket",
            "age-bucket-desc",
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
        "--age-bucket",
        action="append",
        default=None,
        help="Only include stale artifacts in this age bucket; repeat or comma-separate values like 0-6d, 7-29d, 30-89d, 90d+, or unknown",
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
        "--current-path-stem",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file stem matches this value; repeat to include multiple stems",
    )
    parser.add_argument(
        "--current-path-stem-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file stem contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-extension",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact extension matches this value; repeat or comma-separate; use 'none' for extensionless or untracked paths",
    )
    parser.add_argument(
        "--current-path-extension-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact extension contains this text; repeat to include multiple matches",
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
        "--artifact-dir",
        action="append",
        default=None,
        help=(
            "Only include stale artifacts whose artifact directory matches this path; "
            "repeat to include multiple paths"
        ),
    )
    parser.add_argument(
        "--artifact-dir-contains",
        action="append",
        default=None,
        help=(
            "Only include stale artifacts whose artifact directory contains this text; "
            "repeat to include multiple matches"
        ),
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
        "--artifact-stem",
        action="append",
        default=None,
        help="Only include stale artifacts with this file name without extension; repeat to include multiple stems",
    )
    parser.add_argument(
        "--artifact-stem-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file name without extension contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--artifact-extension",
        action="append",
        default=None,
        help="Only include stale artifacts with this file extension; repeat or comma-separate; use 'none' for extensionless paths",
    )
    parser.add_argument(
        "--artifact-extension-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file extension contains this text; repeat to include multiple matches",
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
        "--status-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose status contains this text; repeat to include multiple matches",
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
        "--absolute-paths",
        action="store_true",
        help=(
            "With --paths-only, print paths resolved under the docs directory "
            "so cleanup scripts can run from any working directory"
        ),
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
    parser.add_argument(
        "--json-summary",
        action="store_true",
        help="Emit machine-readable stale artifact totals and summary groups",
    )
    parser.add_argument(
        "--json-lines",
        action="store_true",
        help="Emit one machine-readable stale artifact JSON object per line",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Emit matching stale artifacts as CSV for spreadsheet cleanup review",
    )
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
    parser.add_argument(
        "--summary-sort",
        choices=("size", "size-desc", "size-asc", "count", "count-desc", "count-asc", "name", "name-desc"),
        default="size",
        help="With --summary-only or --json-summary, sort grouping rows by total size, count, or bucket name; use *-asc or *-desc for explicit direction",
    )
    parser.add_argument(
        "--summary-min-count",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with at least this many artifacts",
    )
    parser.add_argument(
        "--summary-max-count",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with no more than this many artifacts",
    )
    parser.add_argument(
        "--summary-min-size-bytes",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with at least this many bytes",
    )
    parser.add_argument(
        "--summary-max-size-bytes",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with no more than this many bytes",
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


def age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days < 7:
        return "0-6d"
    if age_days < 30:
        return "7-29d"
    if age_days < 90:
        return "30-89d"
    return "90d+"


def descending_text_key(value: Any) -> tuple[int, ...]:
    return tuple(-ord(character) for character in str(value))


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
    current_path_stems: list[str] | None = None,
    current_path_stem_contains: list[str] | None = None,
    current_path_extensions: list[str] | None = None,
    current_path_extension_contains: list[str] | None = None,
    track_state: str = "any",
    measured_months: list[str] | None = None,
    age_buckets: list[str] | None = None,
    artifact_paths: list[str] | None = None,
    artifact_path_contains: list[str] | None = None,
    artifact_dirs: list[str] | None = None,
    artifact_dir_contains: list[str] | None = None,
    artifact_names: list[str] | None = None,
    artifact_name_contains: list[str] | None = None,
    artifact_stems: list[str] | None = None,
    artifact_stem_contains: list[str] | None = None,
    artifact_extensions: list[str] | None = None,
    artifact_extension_contains: list[str] | None = None,
    detail_pages: list[str] | None = None,
    detail_page_contains: list[str] | None = None,
    detail_page_names: list[str] | None = None,
    detail_page_name_contains: list[str] | None = None,
    statuses: list[str] | None = None,
    status_contains: list[str] | None = None,
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
    age_buckets = normalize_filter_values(age_buckets)
    current_paths = normalize_filter_values(current_paths)
    current_path_contains = normalize_filter_values(current_path_contains)
    current_path_names = normalize_filter_values(current_path_names)
    current_path_name_contains = normalize_filter_values(current_path_name_contains)
    current_path_stems = normalize_filter_values(current_path_stems)
    current_path_stem_contains = normalize_filter_values(current_path_stem_contains)
    current_path_extensions = normalize_filter_values(current_path_extensions)
    current_path_extension_contains = normalize_filter_values(current_path_extension_contains)
    artifact_paths = normalize_filter_values(artifact_paths)
    artifact_path_contains = normalize_filter_values(artifact_path_contains)
    artifact_dirs = normalize_filter_values(artifact_dirs)
    artifact_dir_contains = normalize_filter_values(artifact_dir_contains)
    artifact_names = normalize_filter_values(artifact_names)
    artifact_name_contains = normalize_filter_values(artifact_name_contains)
    artifact_stems = normalize_filter_values(artifact_stems)
    artifact_stem_contains = normalize_filter_values(artifact_stem_contains)
    artifact_extensions = normalize_filter_values(artifact_extensions)
    artifact_extension_contains = normalize_filter_values(artifact_extension_contains)
    detail_pages = normalize_filter_values(detail_pages)
    detail_page_contains = normalize_filter_values(detail_page_contains)
    detail_page_names = normalize_filter_values(detail_page_names)
    detail_page_name_contains = normalize_filter_values(detail_page_name_contains)
    status_contains = normalize_filter_values(status_contains)
    allowed_measured_months = None
    if measured_months is not None:
        allowed_measured_months = {month.strip() for month in measured_months if month.strip()}
        invalid_months = [month for month in allowed_measured_months if len(month) != 7 or month[4] != "-"]
        if invalid_months:
            raise ValueError("measured_month values must use YYYY-MM")
    allowed_age_buckets = None
    if age_buckets is not None:
        allowed_age_buckets = {bucket.lower() for bucket in age_buckets}
        invalid_age_buckets = sorted(allowed_age_buckets - {bucket.lower() for bucket in AGE_BUCKET_ORDER})
        if invalid_age_buckets:
            raise ValueError("age_bucket values must be one of: 0-6d, 7-29d, 30-89d, 90d+, unknown")

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

    age_reference = now or datetime.now(UTC)
    if age_reference.tzinfo is None:
        age_reference = age_reference.replace(tzinfo=UTC)
    age_reference = age_reference.astimezone(UTC)

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
    allowed_current_path_stems = (
        None if current_path_stems is None else {Path(stem).stem for stem in current_path_stems}
    )
    current_path_stem_needles = (
        None if current_path_stem_contains is None else [needle.lower() for needle in current_path_stem_contains]
    )
    allowed_current_path_extensions = (
        None
        if current_path_extensions is None
        else {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in current_path_extensions
            if extension.lower() != "none"
        }
    )
    allow_extensionless_current_paths = current_path_extensions is not None and any(
        extension.lower() == "none" for extension in current_path_extensions
    )
    current_path_extension_needles = (
        None
        if current_path_extension_contains is None
        else [needle.lower() for needle in current_path_extension_contains]
    )
    allowed_artifact_paths = None if artifact_paths is None else set(artifact_paths)
    slug_needles = None if slug_contains is None else [needle.lower() for needle in slug_contains]
    artifact_path_needles = (
        None if artifact_path_contains is None else [needle.lower() for needle in artifact_path_contains]
    )
    allowed_artifact_dirs = None if artifact_dirs is None else {str(Path(path)) for path in artifact_dirs}
    artifact_dir_needles = (
        None if artifact_dir_contains is None else [needle.lower() for needle in artifact_dir_contains]
    )
    allowed_artifact_names = None if artifact_names is None else {Path(name).name for name in artifact_names}
    artifact_name_needles = (
        None if artifact_name_contains is None else [needle.lower() for needle in artifact_name_contains]
    )
    allowed_artifact_stems = None if artifact_stems is None else {Path(stem).stem for stem in artifact_stems}
    artifact_stem_needles = (
        None if artifact_stem_contains is None else [needle.lower() for needle in artifact_stem_contains]
    )
    allowed_artifact_extensions = (
        None
        if artifact_extensions is None
        else {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in artifact_extensions
            if extension.lower() != "none"
        }
    )
    allow_extensionless_artifacts = artifact_extensions is not None and any(
        extension.lower() == "none" for extension in artifact_extensions
    )
    artifact_extension_needles = (
        None if artifact_extension_contains is None else [needle.lower() for needle in artifact_extension_contains]
    )
    allowed_detail_pages = None if detail_pages is None else set(detail_pages)
    detail_page_needles = None if detail_page_contains is None else [needle.lower() for needle in detail_page_contains]
    allowed_detail_page_names = None if detail_page_names is None else {Path(name).name for name in detail_page_names}
    detail_page_name_needles = (
        None if detail_page_name_contains is None else [needle.lower() for needle in detail_page_name_contains]
    )
    allowed_statuses = normalize_status_filters(statuses)
    status_needles = None if status_contains is None else [needle.lower() for needle in status_contains]
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
        artifact_dir = str(Path(artifact_path).parent)
        if allowed_artifact_dirs is not None and artifact_dir not in allowed_artifact_dirs:
            continue
        if artifact_dir_needles is not None:
            if not any(needle in artifact_dir.lower() for needle in artifact_dir_needles):
                continue
        artifact_name = Path(artifact_path).name
        if allowed_artifact_names is not None and artifact_name not in allowed_artifact_names:
            continue
        if artifact_name_needles is not None and not any(
            needle in artifact_name.lower() for needle in artifact_name_needles
        ):
            continue
        artifact_stem = Path(artifact_path).stem
        if allowed_artifact_stems is not None and artifact_stem not in allowed_artifact_stems:
            continue
        if artifact_stem_needles is not None and not any(
            needle in artifact_stem.lower() for needle in artifact_stem_needles
        ):
            continue
        artifact_extension = Path(artifact_path).suffix.lower()
        if allowed_artifact_extensions is not None or allow_extensionless_artifacts:
            extension_matches = artifact_extension in (allowed_artifact_extensions or set())
            extensionless_matches = allow_extensionless_artifacts and artifact_extension == ""
            if not extension_matches and not extensionless_matches:
                continue
        if artifact_extension_needles is not None:
            artifact_extension_text = artifact_extension or "none"
            if not any(needle in artifact_extension_text for needle in artifact_extension_needles):
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
        if status_needles is not None and not any(needle in artifact_status for needle in status_needles):
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
        current_path_stem = Path(current_artifact_path or "").stem
        if allowed_current_path_stems is not None and current_path_stem not in allowed_current_path_stems:
            continue
        if current_path_stem_needles is not None:
            if not any(needle in current_path_stem.lower() for needle in current_path_stem_needles):
                continue
        current_path_extension = Path(current_artifact_path or "").suffix.lower()
        if allowed_current_path_extensions is not None or allow_extensionless_current_paths:
            current_extension_matches = current_path_extension in (allowed_current_path_extensions or set())
            current_extensionless_matches = allow_extensionless_current_paths and current_path_extension == ""
            if not current_extension_matches and not current_extensionless_matches:
                continue
        if current_path_extension_needles is not None:
            current_path_extension_text = current_path_extension or "none"
            if not any(needle in current_path_extension_text for needle in current_path_extension_needles):
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
        artifact_age_days = None
        if measured_timestamp is not None:
            artifact_age_days = max((age_reference - measured_timestamp).days, 0)
        artifact_age_bucket = age_bucket(artifact_age_days)
        if allowed_measured_months is not None and artifact_measured_month not in allowed_measured_months:
            continue
        if allowed_age_buckets is not None and artifact_age_bucket.lower() not in allowed_age_buckets:
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
        current_artifact_name = Path(current_artifact_path or "").name or None
        current_artifact_stem = Path(current_artifact_path or "").stem or None
        detail_page_name = Path(artifact_detail_page_path or "").name or None
        stale.append(
            {
                "artifact_path": artifact_path,
                "artifact_name": artifact_name,
                "artifact_stem": artifact_stem,
                "artifact_dir": artifact_dir,
                "artifact_extension": artifact_extension or "none",
                "slug": artifact.get("slug"),
                "label": artifact.get("label"),
                "backend": artifact.get("backend"),
                "model": artifact.get("model"),
                "status": artifact.get("status"),
                "measured_at": measured_at,
                "measured_month": artifact_measured_month,
                "age_days": artifact_age_days,
                "age_bucket": artifact_age_bucket,
                "age": format_age_days(artifact_age_days),
                "current_artifact_path": current_artifact_path,
                "current_artifact_name": current_artifact_name,
                "current_artifact_stem": current_artifact_stem,
                "current_artifact_extension": current_path_extension or "none",
                "track_state": "tracked" if current_artifact_path is not None else "untracked",
                "detail_page_path": artifact_detail_page_path,
                "detail_page_name": detail_page_name,
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
    if sort_by == "age":
        return sorted(
            stale,
            key=lambda entry: (
                -(entry.get("age_days") if entry.get("age_days") is not None else -1),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "age-asc":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("age_days") if entry.get("age_days") is not None else sys.maxsize,
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
    if sort_by == "path-desc":
        return sorted(stale, key=lambda entry: entry.get("artifact_path") or "", reverse=True)
    if sort_by == "artifact-name":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("artifact_path") or "").name),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-stem":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").stem,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-stem-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("artifact_path") or "").stem),
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
    if sort_by == "artifact-dir-desc":
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("artifact_path") or "").parent),
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by == "artifact-extension":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").suffix.lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-extension-desc":
        return sorted(
            stale,
            key=lambda entry: (
                *(-ord(character) for character in Path(entry.get("artifact_path") or "").suffix.lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page":
        return sorted(stale, key=lambda entry: entry.get("detail_page_path") or "")
    if sort_by == "detail-page-desc":
        return sorted(stale, key=lambda entry: entry.get("detail_page_path") or "", reverse=True)
    if sort_by == "detail-page-name":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("detail_page_path") or "").name),
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
    if sort_by == "status-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("status") or "unknown").lower()),
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
    if sort_by == "backend-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
                descending_text_key(str(entry.get("model") or "unknown").lower()),
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
    if sort_by == "model-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("model") or "unknown").lower()),
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
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
    if sort_by == "label-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("label") or "unknown").lower()),
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
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
    if sort_by == "slug-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("slug") or "untracked").lower()),
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
    if sort_by == "track-state-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("track_state") or "untracked").lower()),
                descending_text_key(str(entry.get("slug") or "untracked").lower()),
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
    if sort_by == "current-path-desc":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
            reverse=True,
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
    if sort_by == "current-path-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by == "current-path-stem":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").stem,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-stem-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").stem,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by == "current-path-extension":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").suffix.lower(),
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-extension-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").suffix.lower() == "",
                descending_text_key(Path(entry.get("current_artifact_path") or "").suffix.lower()),
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
    if sort_by == "measured-month-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_month") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "age-bucket":
        return sorted(
            stale,
            key=lambda entry: (
                AGE_BUCKET_ORDER.get(str(entry.get("age_bucket") or "unknown"), sys.maxsize),
                entry.get("age_days") if entry.get("age_days") is not None else sys.maxsize,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "age-bucket-desc":
        return sorted(
            stale,
            key=lambda entry: (
                -AGE_BUCKET_ORDER.get(str(entry.get("age_bucket") or "unknown"), sys.maxsize),
                -(entry.get("age_days") if entry.get("age_days") is not None else -1),
                entry.get("artifact_path") or "",
            ),
        )
    raise ValueError(
        "sort_by must be one of: size, size-asc, age, age-asc, measured-at, measured-at-desc, path, path-desc, artifact-name, artifact-name-desc, artifact-stem, artifact-stem-desc, artifact-dir, artifact-dir-desc, artifact-extension, artifact-extension-desc, detail-page, detail-page-desc, detail-page-name, detail-page-name-desc, status, status-desc, backend, backend-desc, model, model-desc, label, label-desc, slug, slug-desc, track-state, track-state-desc, current-path, current-path-desc, current-path-name, current-path-name-desc, current-path-extension, current-path-extension-desc, measured-month, measured-month-desc, age-bucket, age-bucket-desc"
    )


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    by_slug: dict[str, dict[str, Any]] = {}
    by_artifact_name: dict[str, dict[str, Any]] = {}
    by_artifact_stem: dict[str, dict[str, Any]] = {}
    by_artifact_dir: dict[str, dict[str, Any]] = {}
    by_artifact_extension: dict[str, dict[str, Any]] = {}
    by_status: dict[str, dict[str, Any]] = {}
    by_backend: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    by_current_artifact_path: dict[str, dict[str, Any]] = {}
    by_current_artifact_name: dict[str, dict[str, Any]] = {}
    by_current_artifact_stem: dict[str, dict[str, Any]] = {}
    by_current_artifact_extension: dict[str, dict[str, Any]] = {}
    by_track_state: dict[str, dict[str, Any]] = {}
    by_detail_page_path: dict[str, dict[str, Any]] = {}
    by_detail_page_name: dict[str, dict[str, Any]] = {}
    by_measured_month: dict[str, dict[str, Any]] = {}
    by_age_bucket: dict[str, dict[str, Any]] = {}
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

        artifact_stem = Path(entry.get("artifact_path") or "").stem or "unknown"
        artifact_stem_bucket = by_artifact_stem.setdefault(
            artifact_stem,
            {
                "artifact_stem": artifact_stem,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_stem_bucket["count"] += 1
        artifact_stem_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_stem_bucket["total_size"] = format_bytes(artifact_stem_bucket["total_size_bytes"])

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

        artifact_extension = Path(entry.get("artifact_path") or "").suffix.lower() or "none"
        artifact_extension_bucket = by_artifact_extension.setdefault(
            artifact_extension,
            {
                "artifact_extension": artifact_extension,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_extension_bucket["count"] += 1
        artifact_extension_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_extension_bucket["total_size"] = format_bytes(artifact_extension_bucket["total_size_bytes"])

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

        current_artifact_stem = Path(entry.get("current_artifact_path") or "").stem or "untracked"
        current_stem_bucket = by_current_artifact_stem.setdefault(
            current_artifact_stem,
            {
                "current_artifact_stem": current_artifact_stem,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_stem_bucket["count"] += 1
        current_stem_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_stem_bucket["total_size"] = format_bytes(current_stem_bucket["total_size_bytes"])

        current_artifact_extension = Path(entry.get("current_artifact_path") or "").suffix.lower() or "none"
        current_extension_bucket = by_current_artifact_extension.setdefault(
            current_artifact_extension,
            {
                "current_artifact_extension": current_artifact_extension,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_extension_bucket["count"] += 1
        current_extension_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_extension_bucket["total_size"] = format_bytes(current_extension_bucket["total_size_bytes"])

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

        age_bucket_name = str(entry.get("age_bucket") or age_bucket(entry.get("age_days")))
        age_bucket_entry = by_age_bucket.setdefault(
            age_bucket_name,
            {
                "age_bucket": age_bucket_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        age_bucket_entry["count"] += 1
        age_bucket_entry["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        age_bucket_entry["total_size"] = format_bytes(age_bucket_entry["total_size_bytes"])

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
        "by_artifact_stem": sorted(
            by_artifact_stem.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_stem"]),
        ),
        "by_artifact_dir": sorted(
            by_artifact_dir.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_dir"]),
        ),
        "by_artifact_extension": sorted(
            by_artifact_extension.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_extension"]),
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
        "by_current_artifact_stem": sorted(
            by_current_artifact_stem.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_stem"]),
        ),
        "by_current_artifact_extension": sorted(
            by_current_artifact_extension.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_extension"]),
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
        "by_age_bucket": sorted(
            by_age_bucket.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["age_bucket"]),
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
            "- {artifact_path} [{slug}] status {status} measured {measured_at} ({age}; {artifact_size}){current_suffix}{detail_suffix}".format(
                artifact_path=entry["artifact_path"],
                slug=entry.get("slug") or "untracked",
                status=status,
                measured_at=entry.get("measured_at") or "unknown",
                age=entry.get("age") or format_age_days(entry.get("age_days")),
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
    output_root: Path | None = None,
    separator: str = "\n",
) -> str:
    paths = []

    def append_path_once(path: str) -> None:
        if output_root is not None:
            path = str((output_root / path).resolve())
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


def render_json_lines(stale: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(entry, sort_keys=True) for entry in stale)


def render_json_summary(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
) -> str:
    if summary_limit is not None and summary_limit < 0:
        raise ValueError("summary_limit must be non-negative")
    if summary_sort not in {"size", "size-desc", "size-asc", "count", "count-desc", "count-asc", "name", "name-desc"}:
        raise ValueError("summary_sort must be one of: size, size-desc, size-asc, count, count-desc, count-asc, name, name-desc")
    if summary_min_count is not None and summary_min_count < 0:
        raise ValueError("summary_min_count must be non-negative")
    if summary_max_count is not None and summary_max_count < 0:
        raise ValueError("summary_max_count must be non-negative")
    if summary_min_count is not None and summary_max_count is not None and summary_min_count > summary_max_count:
        raise ValueError("summary_min_count cannot exceed summary_max_count")
    if summary_min_size_bytes is not None and summary_min_size_bytes < 0:
        raise ValueError("summary_min_size_bytes must be non-negative")
    if summary_max_size_bytes is not None and summary_max_size_bytes < 0:
        raise ValueError("summary_max_size_bytes must be non-negative")
    if (
        summary_min_size_bytes is not None
        and summary_max_size_bytes is not None
        and summary_min_size_bytes > summary_max_size_bytes
    ):
        raise ValueError("summary_min_size_bytes cannot exceed summary_max_size_bytes")
    allowed_groups = set(SUMMARY_GROUPS)
    selected_groups = normalize_summary_groups(groups)
    unknown_groups = sorted(selected_groups - allowed_groups)
    if unknown_groups:
        raise ValueError(f"summary groups must be one of: {', '.join(SUMMARY_GROUPS)}")

    summary = stale_summary(stale)
    rendered: dict[str, Any] = {
        "count": summary["count"],
        "total_size_bytes": summary["total_size_bytes"],
        "total_size": summary["total_size"],
    }
    for group in SUMMARY_GROUPS:
        if group not in selected_groups:
            continue
        summary_key = SUMMARY_GROUP_KEYS[group]
        rendered[summary_key] = limit_summary_buckets(
            summary[summary_key],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    return json.dumps(rendered, indent=2)


def render_csv(stale: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "artifact_path",
        "artifact_name",
        "artifact_stem",
        "artifact_dir",
        "artifact_extension",
        "slug",
        "label",
        "backend",
        "model",
        "status",
        "measured_at",
        "measured_month",
        "age_days",
        "age_bucket",
        "age",
        "current_artifact_path",
        "current_artifact_name",
        "current_artifact_stem",
        "current_artifact_extension",
        "track_state",
        "detail_page_path",
        "detail_page_name",
        "artifact_size_bytes",
        "artifact_size",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for entry in stale:
        row = {
            **entry,
            "artifact_name": entry.get("artifact_name") or Path(entry.get("artifact_path") or "").name,
            "artifact_stem": entry.get("artifact_stem") or Path(entry.get("artifact_path") or "").stem,
            "artifact_dir": entry.get("artifact_dir") or str(Path(entry.get("artifact_path") or "").parent),
            "current_artifact_name": entry.get("current_artifact_name")
            or Path(entry.get("current_artifact_path") or "").name,
            "current_artifact_stem": entry.get("current_artifact_stem")
            or Path(entry.get("current_artifact_path") or "").stem,
            "current_artifact_extension": entry.get("current_artifact_extension")
            or Path(entry.get("current_artifact_path") or "").suffix.lower()
            or "none",
            "detail_page_name": entry.get("detail_page_name")
            or Path(entry.get("detail_page_path") or "").name,
        }
        writer.writerow(row)
    return output.getvalue()


def limit_summary_buckets(
    buckets: list[dict[str, Any]],
    limit: int | None,
    *,
    sort_by: str = "size",
    min_count: int | None = None,
    max_count: int | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
) -> list[dict[str, Any]]:
    if min_count is not None and min_count < 0:
        raise ValueError("summary_min_count must be non-negative")
    if max_count is not None and max_count < 0:
        raise ValueError("summary_max_count must be non-negative")
    if min_count is not None and max_count is not None and min_count > max_count:
        raise ValueError("summary_min_count cannot exceed summary_max_count")
    if min_size_bytes is not None and min_size_bytes < 0:
        raise ValueError("summary_min_size_bytes must be non-negative")
    if max_size_bytes is not None and max_size_bytes < 0:
        raise ValueError("summary_max_size_bytes must be non-negative")
    if min_size_bytes is not None and max_size_bytes is not None and min_size_bytes > max_size_bytes:
        raise ValueError("summary_min_size_bytes cannot exceed summary_max_size_bytes")
    if sort_by not in {"size", "size-desc", "size-asc", "count", "count-desc", "count-asc", "name", "name-desc"}:
        raise ValueError("summary_sort must be one of: size, size-desc, size-asc, count, count-desc, count-asc, name, name-desc")
    filtered_buckets = buckets
    if min_count is not None:
        filtered_buckets = [bucket for bucket in filtered_buckets if bucket["count"] >= min_count]
    if max_count is not None:
        filtered_buckets = [bucket for bucket in filtered_buckets if bucket["count"] <= max_count]
    if min_size_bytes is not None:
        filtered_buckets = [
            bucket for bucket in filtered_buckets if bucket["total_size_bytes"] >= min_size_bytes
        ]
    if max_size_bytes is not None:
        filtered_buckets = [
            bucket for bucket in filtered_buckets if bucket["total_size_bytes"] <= max_size_bytes
        ]
    if sort_by != "size":
        filtered_buckets = sorted(filtered_buckets, key=lambda bucket: summary_bucket_sort_key(bucket, sort_by))
    if limit is None:
        return filtered_buckets
    if limit < 0:
        raise ValueError("summary_limit must be non-negative")
    return filtered_buckets[:limit]


def summary_bucket_sort_key(bucket: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
    name = str(next((value for key, value in bucket.items() if key not in {"count", "total_size_bytes", "total_size"}), ""))
    if sort_by in {"count", "count-desc"}:
        return (-bucket["count"], -bucket["total_size_bytes"], name)
    if sort_by == "count-asc":
        return (bucket["count"], bucket["total_size_bytes"], name)
    if sort_by == "name-desc":
        return (*(-ord(character) for character in name), -len(name))
    if sort_by == "name":
        return (name,)
    if sort_by == "size-asc":
        return (bucket["total_size_bytes"], name)
    return (-bucket["total_size_bytes"], name)


def append_omitted_summary_buckets(
    lines: list[str],
    buckets: list[dict[str, Any]],
    shown_buckets: list[dict[str, Any]],
    *,
    limit: int | None,
    sort_by: str = "size",
    min_count: int | None = None,
    max_count: int | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
) -> None:
    buckets = limit_summary_buckets(
        buckets,
        None,
        sort_by=sort_by,
        min_count=min_count,
        max_count=max_count,
        min_size_bytes=min_size_bytes,
        max_size_bytes=max_size_bytes,
    )
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
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
) -> str:
    if summary_limit is not None and summary_limit < 0:
        raise ValueError("summary_limit must be non-negative")
    if summary_sort not in {"size", "size-desc", "size-asc", "count", "count-desc", "count-asc", "name", "name-desc"}:
        raise ValueError("summary_sort must be one of: size, size-desc, size-asc, count, count-desc, count-asc, name, name-desc")
    if summary_min_count is not None and summary_min_count < 0:
        raise ValueError("summary_min_count must be non-negative")
    if summary_max_count is not None and summary_max_count < 0:
        raise ValueError("summary_max_count must be non-negative")
    if summary_min_count is not None and summary_max_count is not None and summary_min_count > summary_max_count:
        raise ValueError("summary_min_count cannot exceed summary_max_count")
    if summary_min_size_bytes is not None and summary_min_size_bytes < 0:
        raise ValueError("summary_min_size_bytes must be non-negative")
    if summary_max_size_bytes is not None and summary_max_size_bytes < 0:
        raise ValueError("summary_max_size_bytes must be non-negative")
    if (
        summary_min_size_bytes is not None
        and summary_max_size_bytes is not None
        and summary_min_size_bytes > summary_max_size_bytes
    ):
        raise ValueError("summary_min_size_bytes cannot exceed summary_max_size_bytes")
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
        shown_buckets = limit_summary_buckets(
            summary["by_slug"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_slug"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-name" in selected_groups and summary["by_artifact_name"]:
        lines.append("By artifact name:")
    if "artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-stem" in selected_groups and summary["by_artifact_stem"]:
        lines.append("By artifact stem:")
    if "artifact-stem" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_stem"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_stem}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_stem=bucket["artifact_stem"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_stem"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-dir" in selected_groups and summary["by_artifact_dir"]:
        lines.append("By artifact directory:")
    if "artifact-dir" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_dir"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_dir"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-extension" in selected_groups and summary["by_artifact_extension"]:
        lines.append("By artifact extension:")
    if "artifact-extension" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_extension"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_extension}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_extension=bucket["artifact_extension"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_extension"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "status" in selected_groups and summary["by_status"]:
        lines.append("By status:")
    if "status" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_status"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_status"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "backend" in selected_groups and summary["by_backend"]:
        lines.append("By backend:")
    if "backend" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_backend"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_backend"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "model" in selected_groups and summary["by_model"]:
        lines.append("By model:")
    if "model" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_model"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_model"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "label" in selected_groups and any(bucket["label"] != "unknown" for bucket in summary["by_label"]):
        lines.append("By label:")
        shown_buckets = limit_summary_buckets(
            summary["by_label"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_label"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact" in selected_groups and summary["by_current_artifact_path"]:
        lines.append("By current artifact:")
    if "current-artifact" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_path"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_path"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-name" in selected_groups and summary["by_current_artifact_name"]:
        lines.append("By current artifact name:")
    if "current-artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-stem" in selected_groups and summary["by_current_artifact_stem"]:
        lines.append("By current artifact stem:")
    if "current-artifact-stem" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_stem"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_stem}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_stem=bucket["current_artifact_stem"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_stem"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-extension" in selected_groups and summary["by_current_artifact_extension"]:
        lines.append("By current artifact extension:")
    if "current-artifact-extension" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_extension"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_extension}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_extension=bucket["current_artifact_extension"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_extension"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "track-state" in selected_groups and summary["by_track_state"]:
        lines.append("By track state:")
    if "track-state" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_track_state"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_track_state"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page" in selected_groups and summary["by_detail_page_path"]:
        lines.append("By detail page:")
    if "detail-page" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_path"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_path"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page-name" in selected_groups and summary["by_detail_page_name"]:
        lines.append("By detail page name:")
    if "detail-page-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "measured-month" in selected_groups and summary["by_measured_month"]:
        lines.append("By measured month:")
    if "measured-month" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_measured_month"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
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
        append_omitted_summary_buckets(
            lines,
            summary["by_measured_month"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "age-bucket" in selected_groups and summary["by_age_bucket"]:
        lines.append("By age bucket:")
    if "age-bucket" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_age_bucket"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {age_bucket}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    age_bucket=bucket["age_bucket"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_age_bucket"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.json and args.paths_only:
        raise ValueError("--json and --paths-only cannot be used together")
    if args.json_summary and args.json:
        raise ValueError("--json-summary and --json cannot be used together")
    if args.json_summary and args.paths_only:
        raise ValueError("--json-summary and --paths-only cannot be used together")
    if args.json_lines and args.json:
        raise ValueError("--json-lines and --json cannot be used together")
    if args.json_lines and args.json_summary:
        raise ValueError("--json-lines and --json-summary cannot be used together")
    if args.json_lines and args.paths_only:
        raise ValueError("--json-lines and --paths-only cannot be used together")
    if args.csv and args.json:
        raise ValueError("--csv and --json cannot be used together")
    if args.csv and args.json_summary:
        raise ValueError("--csv and --json-summary cannot be used together")
    if args.csv and args.json_lines:
        raise ValueError("--csv and --json-lines cannot be used together")
    if args.csv and args.paths_only:
        raise ValueError("--csv and --paths-only cannot be used together")
    if args.count_only and args.json:
        raise ValueError("--count-only and --json cannot be used together")
    if args.count_only and args.json_summary:
        raise ValueError("--count-only and --json-summary cannot be used together")
    if args.count_only and args.json_lines:
        raise ValueError("--count-only and --json-lines cannot be used together")
    if args.count_only and args.csv:
        raise ValueError("--count-only and --csv cannot be used together")
    if args.count_only and args.paths_only:
        raise ValueError("--count-only and --paths-only cannot be used together")
    if args.summary_only and args.json:
        raise ValueError("--summary-only and --json cannot be used together")
    if args.summary_only and args.json_summary:
        raise ValueError("--summary-only and --json-summary cannot be used together")
    if args.summary_only and args.json_lines:
        raise ValueError("--summary-only and --json-lines cannot be used together")
    if args.summary_only and args.csv:
        raise ValueError("--summary-only and --csv cannot be used together")
    if args.summary_only and args.paths_only:
        raise ValueError("--summary-only and --paths-only cannot be used together")
    if args.summary_only and args.count_only:
        raise ValueError("--summary-only and --count-only cannot be used together")
    if args.summary_group and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-group requires --summary-only or --json-summary")
    if args.summary_limit is not None and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-limit requires --summary-only or --json-summary")
    if args.summary_min_count is not None and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-min-count requires --summary-only or --json-summary")
    if args.summary_max_count is not None and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-max-count requires --summary-only or --json-summary")
    if args.summary_min_size_bytes is not None and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-min-size-bytes requires --summary-only or --json-summary")
    if args.summary_max_size_bytes is not None and not (args.summary_only or args.json_summary):
        raise ValueError("--summary-max-size-bytes requires --summary-only or --json-summary")
    if args.include_detail_pages and not args.paths_only:
        raise ValueError("--include-detail-pages requires --paths-only")
    if args.detail_pages_only and not args.paths_only:
        raise ValueError("--detail-pages-only requires --paths-only")
    if args.absolute_paths and not args.paths_only:
        raise ValueError("--absolute-paths requires --paths-only")
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
        age_buckets=args.age_bucket,
        current_paths=args.current_path,
        current_path_contains=args.current_path_contains,
        current_path_names=args.current_path_name,
        current_path_name_contains=args.current_path_name_contains,
        current_path_stems=args.current_path_stem,
        current_path_stem_contains=args.current_path_stem_contains,
        current_path_extensions=args.current_path_extension,
        current_path_extension_contains=args.current_path_extension_contains,
        track_state=args.track_state,
        artifact_paths=args.artifact_path,
        artifact_path_contains=args.artifact_path_contains,
        artifact_dirs=args.artifact_dir,
        artifact_dir_contains=args.artifact_dir_contains,
        artifact_names=args.artifact_name,
        artifact_name_contains=args.artifact_name_contains,
        artifact_stems=args.artifact_stem,
        artifact_stem_contains=args.artifact_stem_contains,
        artifact_extensions=args.artifact_extension,
        artifact_extension_contains=args.artifact_extension_contains,
        detail_pages=args.detail_page,
        detail_page_contains=args.detail_page_contains,
        detail_page_names=args.detail_page_name,
        detail_page_name_contains=args.detail_page_name_contains,
        statuses=args.status,
        status_contains=args.status_contains,
        sort_by=args.sort,
    )
    limited_stale = limit_artifacts(stale, args.limit)
    if args.count_only:
        print(len(stale))
    elif args.summary_only:
        print(
            render_summary(
                stale,
                groups=args.summary_group,
                summary_limit=args.summary_limit,
                summary_sort=args.summary_sort,
                summary_min_count=args.summary_min_count,
                summary_max_count=args.summary_max_count,
                summary_min_size_bytes=args.summary_min_size_bytes,
                summary_max_size_bytes=args.summary_max_size_bytes,
            )
        )
    elif args.json_summary:
        print(
            render_json_summary(
                stale,
                groups=args.summary_group,
                summary_limit=args.summary_limit,
                summary_sort=args.summary_sort,
                summary_min_count=args.summary_min_count,
                summary_max_count=args.summary_max_count,
                summary_min_size_bytes=args.summary_min_size_bytes,
                summary_max_size_bytes=args.summary_max_size_bytes,
            )
        )
    elif args.paths_only:
        rendered_paths = render_paths(
            limited_stale,
            include_detail_pages=args.include_detail_pages,
            detail_pages_only=args.detail_pages_only,
            existing_root=args.results_dir.parent if args.existing_paths_only else None,
            missing_root=args.results_dir.parent if args.missing_paths_only else None,
            output_root=args.results_dir.parent if args.absolute_paths else None,
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
    elif args.json_lines:
        print(render_json_lines(limited_stale))
    elif args.csv:
        sys.stdout.write(render_csv(limited_stale))
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
