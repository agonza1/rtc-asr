#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_benchmark_manifest import DEFAULT_RESULTS_DIR, DEFAULT_TRACKS_PATH, build_manifest


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
            }
        )
    return stale


def render_text(stale: list[dict[str, Any]]) -> str:
    if not stale:
        return "No stale benchmark artifacts found."
    total_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    lines = [f"Found {len(stale)} stale benchmark artifacts ({total_bytes} bytes):"]
    lines.extend(
        "- {artifact_path} [{slug}] measured {measured_at}".format(
            artifact_path=entry["artifact_path"],
            slug=entry.get("slug") or "untracked",
            measured_at=entry.get("measured_at") or "unknown",
        )
        for entry in stale
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    manifest = build_manifest(args.results_dir, args.tracks)
    stale = stale_artifacts(manifest)
    if args.json:
        print(json.dumps({"count": len(stale), "artifacts": stale}, indent=2))
    else:
        print(render_text(stale))


if __name__ == "__main__":
    main()
