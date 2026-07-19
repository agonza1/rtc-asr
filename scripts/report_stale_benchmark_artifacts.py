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
        choices=("size", "measured-at", "path", "status"),
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
        "--current-path",
        action="append",
        default=None,
        help="Only include stale artifacts whose track currently points at this artifact path; repeat to include multiple paths",
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
    normalized = {status.lower() for status in statuses}
    return None if "any" in normalized else normalized


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
    current_paths: list[str] | None = None,
    track_state: str = "any",
    artifact_paths: list[str] | None = None,
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
    current_artifact_paths = {track["artifact_path"] for track in tracks}
    current_path_by_slug = {track.get("slug"): track.get("artifact_path") for track in tracks if track.get("slug")}
    allowed_backends = None if backends is None else {backend.lower() for backend in backends}
    allowed_current_paths = None if current_paths is None else set(current_paths)
    allowed_artifact_paths = None if artifact_paths is None else set(artifact_paths)
    allowed_statuses = normalize_status_filters(statuses)
    stale: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        artifact_path = artifact.get("artifact_path")
        if not artifact_path or artifact_path in current_artifact_paths:
            continue
        if allowed_artifact_paths is not None and artifact_path not in allowed_artifact_paths:
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
        if track_state == "tracked" and current_artifact_path is None:
            continue
        if track_state == "untracked" and current_artifact_path is not None:
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
                "current_artifact_path": current_artifact_path,
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
    if sort_by == "status":
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("status") or "unknown"),
                entry.get("slug") or "untracked",
                entry.get("artifact_path") or "",
            ),
        )
    raise ValueError("sort_by must be one of: size, measured-at, path, status")


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    by_slug: dict[str, dict[str, Any]] = {}
    by_status: dict[str, dict[str, Any]] = {}
    by_backend: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
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

    return {
        "count": len(stale),
        "total_size_bytes": total_size_bytes,
        "total_size": format_bytes(total_size_bytes),
        "by_slug": sorted(
            by_slug.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["slug"]),
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
) -> str:
    paths = []
    for entry in stale:
        if not detail_pages_only:
            artifact_path = entry["artifact_path"]
            if existing_root is None or (existing_root / artifact_path).exists():
                if missing_root is None or not (missing_root / artifact_path).exists():
                    paths.append(artifact_path)
        detail_path = entry.get("detail_page_path")
        if (include_detail_pages or detail_pages_only) and detail_path:
            if existing_root is not None and not (existing_root / detail_path).exists():
                continue
            if missing_root is not None and (missing_root / detail_path).exists():
                continue
            paths.append(detail_path)
    return "\n".join(paths)


def render_summary(stale: list[dict[str, Any]]) -> str:
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
    for bucket in summary["by_slug"]:
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
    if summary["by_status"]:
        lines.append("By status:")
    for bucket in summary["by_status"]:
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
    if summary["by_backend"]:
        lines.append("By backend:")
    for bucket in summary["by_backend"]:
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
    if summary["by_model"]:
        lines.append("By model:")
    for bucket in summary["by_model"]:
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
    if args.include_detail_pages and not args.paths_only:
        raise ValueError("--include-detail-pages requires --paths-only")
    if args.detail_pages_only and not args.paths_only:
        raise ValueError("--detail-pages-only requires --paths-only")
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
        min_size_bytes=args.min_size_bytes,
        max_size_bytes=args.max_size_bytes,
        slugs=args.slug,
        labels=args.label,
        backends=args.backend,
        models=args.model,
        current_paths=args.current_path,
        track_state=args.track_state,
        artifact_paths=args.artifact_path,
        statuses=args.status,
        sort_by=args.sort,
    )
    limited_stale = limit_artifacts(stale, args.limit)
    if args.count_only:
        print(len(stale))
    elif args.summary_only:
        print(render_summary(stale))
    elif args.paths_only:
        print(
            render_paths(
                limited_stale,
                include_detail_pages=args.include_detail_pages,
                detail_pages_only=args.detail_pages_only,
                existing_root=args.results_dir.parent if args.existing_paths_only else None,
                missing_root=args.results_dir.parent if args.missing_paths_only else None,
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
