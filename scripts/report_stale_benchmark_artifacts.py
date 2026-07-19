#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from build_benchmark_manifest import DEFAULT_RESULTS_DIR, DEFAULT_TRACKS_PATH, build_manifest


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
        "--limit",
        type=int,
        default=None,
        help="Only print the first N stale artifacts after filtering and sorting",
    )
    parser.add_argument(
        "--sort",
        choices=("size", "measured-at", "path"),
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
        "--status",
        action="append",
        default=None,
        help="Only include stale artifacts with this status; repeat to include multiple statuses (default: legacy)",
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
        "--include-detail-pages",
        action="store_true",
        help="With --paths-only, also print matching prerendered detail page paths",
    )
    parser.add_argument(
        "--detail-pages-only",
        action="store_true",
        help="With --paths-only, only print matching prerendered detail page paths",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
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


def stale_artifacts(
    manifest: dict[str, Any],
    *,
    older_than_days: int | None = None,
    measured_before: datetime | str | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
    slugs: list[str] | None = None,
    labels: list[str] | None = None,
    backends: list[str] | None = None,
    models: list[str] | None = None,
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

    tracks = [track for track in manifest.get("tracks", []) if track.get("artifact_path")]
    current_paths = {track["artifact_path"] for track in tracks}
    current_path_by_slug = {track.get("slug"): track.get("artifact_path") for track in tracks if track.get("slug")}
    allowed_backends = None if backends is None else {backend.lower() for backend in backends}
    allowed_statuses = {"legacy"} if statuses is None else {status.lower() for status in statuses}
    stale: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        artifact_path = artifact.get("artifact_path")
        if not artifact_path or artifact_path in current_paths:
            continue
        artifact_status = str(artifact.get("status") or "").lower()
        if artifact_status not in allowed_statuses:
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
        measured_at = artifact.get("measured_at")
        measured_timestamp = parse_timestamp(measured_at)
        if cutoff is not None and (measured_timestamp is None or measured_timestamp >= cutoff):
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
                "current_artifact_path": current_path_by_slug.get(artifact.get("slug")),
                "detail_page_path": detail_page_path(artifact_path),
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
    if sort_by == "measured-at":
        return sorted(
            stale,
            key=lambda entry: (
                parse_timestamp(entry.get("measured_at")) or datetime.max.replace(tzinfo=UTC),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "path":
        return sorted(stale, key=lambda entry: entry.get("artifact_path") or "")
    raise ValueError("sort_by must be one of: size, measured-at, path")


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    return {
        "count": len(stale),
        "total_size_bytes": total_size_bytes,
        "total_size": format_bytes(total_size_bytes),
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
    lines = [
        "Found {count} stale benchmark artifacts ({size}, {bytes} bytes):".format(
            count=summary["count"],
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    for entry in stale:
        current_artifact_path = entry.get("current_artifact_path")
        current_suffix = f"; current: {current_artifact_path}" if current_artifact_path else ""
        detail_page_path = entry.get("detail_page_path")
        detail_suffix = f"; detail: {detail_page_path}" if detail_page_path else ""
        lines.append(
            "- {artifact_path} [{slug}] measured {measured_at} ({artifact_size}){current_suffix}{detail_suffix}".format(
                artifact_path=entry["artifact_path"],
                slug=entry.get("slug") or "untracked",
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
        lines.append(f"... {total_count - summary['count']} more stale artifacts{suffix} omitted by --limit.")
    return "\n".join(lines)


def render_paths(
    stale: list[dict[str, Any]],
    *,
    include_detail_pages: bool = False,
    detail_pages_only: bool = False,
) -> str:
    paths = []
    for entry in stale:
        if not detail_pages_only:
            paths.append(entry["artifact_path"])
        detail_path = entry.get("detail_page_path")
        if (include_detail_pages or detail_pages_only) and detail_path:
            paths.append(detail_path)
    return "\n".join(paths)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.json and args.paths_only:
        raise ValueError("--json and --paths-only cannot be used together")
    if args.include_detail_pages and not args.paths_only:
        raise ValueError("--include-detail-pages requires --paths-only")
    if args.detail_pages_only and not args.paths_only:
        raise ValueError("--detail-pages-only requires --paths-only")
    if args.detail_pages_only and args.include_detail_pages:
        raise ValueError("--detail-pages-only cannot be combined with --include-detail-pages")

    manifest = build_manifest(args.results_dir, args.tracks)
    stale = stale_artifacts(
        manifest,
        older_than_days=args.older_than_days,
        measured_before=args.measured_before,
        min_size_bytes=args.min_size_bytes,
        max_size_bytes=args.max_size_bytes,
        slugs=args.slug,
        labels=args.label,
        backends=args.backend,
        models=args.model,
        statuses=args.status,
        sort_by=args.sort,
    )
    limited_stale = limit_artifacts(stale, args.limit)
    if args.paths_only:
        print(
            render_paths(
                limited_stale,
                include_detail_pages=args.include_detail_pages,
                detail_pages_only=args.detail_pages_only,
            )
        )
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
