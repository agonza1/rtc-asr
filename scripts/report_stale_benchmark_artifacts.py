#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import json
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


def parse_args() -> argparse.Namespace:
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
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def stale_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    current_paths = {
        track["artifact_path"]
        for track in manifest.get("tracks", [])
        if track.get("artifact_path")
    }
    stale: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        artifact_path = artifact.get("artifact_path")
        if not artifact_path or artifact_path in current_paths:
            continue
        if artifact.get("status") != "legacy":
            continue
        stale.append(
            {
                "artifact_path": artifact_path,
                "slug": artifact.get("slug"),
                "label": artifact.get("label"),
                "measured_at": artifact.get("measured_at"),
                "artifact_size_bytes": artifact.get("artifact_size_bytes"),
                "artifact_size": format_bytes(artifact.get("artifact_size_bytes")),
            }
        )
    return sorted(
        stale,
        key=lambda entry: (
            -(entry.get("artifact_size_bytes") or 0),
            entry.get("artifact_path") or "",
        ),
    )


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    return {
        "count": len(stale),
        "total_size_bytes": total_size_bytes,
        "total_size": format_bytes(total_size_bytes),
        "artifacts": stale,
    }


def render_text(stale: list[dict[str, Any]]) -> str:
    if not stale:
        return "No stale benchmark artifacts found."
    summary = stale_summary(stale)
    lines = [
        "Found {count} stale benchmark artifacts ({size}, {bytes} bytes):".format(
            count=summary["count"],
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    lines.extend(
        "- {artifact_path} [{slug}] measured {measured_at} ({artifact_size})".format(
            artifact_path=entry["artifact_path"],
            slug=entry.get("slug") or "untracked",
            measured_at=entry.get("measured_at") or "unknown",
            artifact_size=entry.get("artifact_size") or format_bytes(entry.get("artifact_size_bytes")),
        )
        for entry in stale
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args.results_dir, args.tracks)
    stale = stale_artifacts(manifest)
    if args.json:
        print(json.dumps(stale_summary(stale), indent=2))
    else:
        print(render_text(stale))


if __name__ == "__main__":
    main()
