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

SORT_CHOICES = ("input", "tag", "size-desc")


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


def sort_records(records: Sequence[ImageSizeRecord], sort_by: str) -> list[ImageSizeRecord]:
    if sort_by == "input":
        return list(records)
    if sort_by == "tag":
        return sorted(records, key=lambda record: record.tag)
    if sort_by == "size-desc":
        return sorted(records, key=lambda record: (record.size_bytes is not None, record.size_bytes or 0), reverse=True)
    raise ValueError(f"unknown sort mode: {sort_by}")


def records_to_json(records: Iterable[ImageSizeRecord]) -> str:
    record_list = list(records)
    summary = records_summary(record_list)
    payload = [
        {
            "tag": record.tag,
            "present": record.present,
            "image_id": record.image_id,
            "size_bytes": record.size_bytes,
            "size_mb": record.size_mb,
            "created": record.created,
        }
        for record in record_list
    ]
    payload.append({"summary": summary})
    return json.dumps(payload, indent=2, sort_keys=True)


def records_summary(records: Sequence[ImageSizeRecord]) -> dict[str, Any]:
    total_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    missing = [record.tag for record in records if not record.present]
    largest = max(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    summary = {
        "requested": len(records),
        "present": len(records) - len(missing),
        "missing": len(missing),
        "missing_tags": missing,
        "total_size_bytes": total_bytes,
        "total_size_mb": round(total_bytes / 1_000_000, 1) if total_bytes else 0.0,
        "largest_present_tag": largest.tag if largest else None,
        "largest_present_size_bytes": largest.size_bytes if largest else None,
        "largest_present_size_mb": largest.size_mb if largest else None,
    }
    return summary


def records_summary_to_json(records: Sequence[ImageSizeRecord]) -> str:
    return json.dumps(records_summary(records), indent=2, sort_keys=True)


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
    total_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    if total_bytes:
        rows.append(
            "| {tag} | {present} | {size:.1f} | {image_id} | {created} |".format(
                tag="Total present images",
                present="",
                size=round(total_bytes / 1_000_000, 1),
                image_id="",
                created="",
            )
        )
    missing = [record.tag for record in records if not record.present]
    rows.append("")
    rows.append(
        "Summary: {present}/{requested} images present, {missing} missing.".format(
            present=len(records) - len(missing),
            requested=len(records),
            missing=len(missing),
        )
    )
    largest = max(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    if largest and largest.size_mb is not None:
        rows.append(f"Largest present image: {largest.tag} ({largest.size_mb:.1f} MB)")
    if missing:
        rows.append("Missing images: {tags}".format(tags=", ".join(missing)))
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
    parser.add_argument(
        "--sort-by",
        choices=SORT_CHOICES,
        default="input",
        help="Order output records by input order, image tag, or descending image size.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Emit only the aggregate image count and size summary as JSON.",
    )
    parser.add_argument("--require-present", action="store_true", help="Exit non-zero when any requested image is absent.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records = sort_records(inspect_images(args.images), args.sort_by)
    if args.summary_only:
        output = records_summary_to_json(records)
    else:
        output = records_to_json(records) if args.json else records_to_markdown(records)
    print(output)
    return 1 if args.require_present and any(not record.present for record in records) else 0


if __name__ == "__main__":
    sys.exit(main())
