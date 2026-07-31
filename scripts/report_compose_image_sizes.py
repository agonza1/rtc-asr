#!/usr/bin/env python3
"""Report Docker image sizes for the supported Compose runtime tags."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

DEFAULT_IMAGES = (
    "realtime-asr:faster-whisper-cpu",
    "realtime-asr:qwen-cpu",
    "realtime-asr:parakeet-transformers-cpu",
    "realtime-asr:parakeet-nemo-cpu",
)


@dataclass(frozen=True)
class ImageSizeRecord:
    tag: str
    image_id: str | None
    size_bytes: int | None
    created: str | None
    present: bool

    @property
    def size_mb(self) -> float | None:
        if self.size_bytes is None:
            return None
        return round(self.size_bytes / 1_000_000, 1)


def _normalize_inspect_entry(tag: str, entry: dict[str, Any]) -> ImageSizeRecord:
    image_id = str(entry.get("Id") or "")
    if image_id.startswith("sha256:"):
        image_id = image_id.removeprefix("sha256:")[:12]

    size = entry.get("Size")
    return ImageSizeRecord(
        tag=tag,
        image_id=image_id or None,
        size_bytes=size if isinstance(size, int) else None,
        created=entry.get("Created") if isinstance(entry.get("Created"), str) else None,
        present=True,
    )


def inspect_images(images: Sequence[str]) -> list[ImageSizeRecord]:
    records: list[ImageSizeRecord] = []
    for image in images:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            records.append(ImageSizeRecord(tag=image, image_id=None, size_bytes=None, created=None, present=False))
            continue

        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"docker image inspect returned invalid JSON for {image}: {exc}") from exc

        if not payload:
            records.append(ImageSizeRecord(tag=image, image_id=None, size_bytes=None, created=None, present=False))
            continue
        records.append(_normalize_inspect_entry(image, payload[0]))
    return records


def records_to_json(records: Iterable[ImageSizeRecord]) -> str:
    payload = [
        {
            "tag": record.tag,
            "present": record.present,
            "image_id": record.image_id,
            "size_bytes": record.size_bytes,
            "size_mb": record.size_mb,
            "created": record.created,
        }
        for record in records
    ]
    return json.dumps(payload, indent=2, sort_keys=True)


def records_to_markdown(records: Sequence[ImageSizeRecord]) -> str:
    rows = ["| Image | Present | Size MB | Image ID | Created |", "| --- | --- | ---: | --- | --- |"]
    for record in records:
        rows.append(
            "| {tag} | {present} | {size} | {image_id} | {created} |".format(
                tag=record.tag,
                present="yes" if record.present else "no",
                size=f"{record.size_mb:.1f}" if record.size_mb is not None else "",
                image_id=record.image_id or "",
                created=record.created or "",
            )
        )
    return "\n".join(rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        default=list(DEFAULT_IMAGES),
        help="Docker image tags to inspect. Defaults to the supported Compose backend tags.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of markdown.")
    parser.add_argument("--require-present", action="store_true", help="Exit non-zero when any requested image is absent.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records = inspect_images(args.images)
    output = records_to_json(records) if args.json else records_to_markdown(records)
    print(output)
    return 1 if args.require_present and any(not record.present for record in records) else 0


if __name__ == "__main__":
    sys.exit(main())
