#!/usr/bin/env python3
"""Report Docker image sizes for the supported Compose runtime tags."""

from __future__ import annotations

import argparse
import csv
import io
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


def records_to_json(
    records: Iterable[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
) -> str:
    record_list = list(records)
    summary = records_summary(record_list, max_size_mb=max_size_mb, max_total_size_mb=max_total_size_mb)
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


def records_to_csv(records: Iterable[ImageSizeRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=("tag", "present", "image_id", "size_bytes", "size_mb", "created"),
        lineterminator="\n",
    )
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "tag": record.tag,
                "present": "yes" if record.present else "no",
                "image_id": record.image_id or "",
                "size_bytes": record.size_bytes if record.size_bytes is not None else "",
                "size_mb": f"{record.size_mb:.1f}" if record.size_mb is not None else "",
                "created": record.created or "",
            }
        )
    return output.getvalue().rstrip("\n")


def records_summary(
    records: Sequence[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
) -> dict[str, Any]:
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
    if max_size_mb is not None:
        over_budget = records_over_size_budget(records, max_size_mb)
        summary.update(
            {
                "image_size_budget_mb": max_size_mb,
                "over_budget": bool(over_budget),
                "over_budget_count": len(over_budget),
                "over_budget_tags": [record.tag for record in over_budget],
            }
        )
    if max_total_size_mb is not None:
        summary.update(
            {
                "total_image_size_budget_mb": max_total_size_mb,
                "total_over_budget": total_bytes > max_total_size_mb * 1_000_000,
            }
        )
    return summary


def records_summary_to_json(
    records: Sequence[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
) -> str:
    return json.dumps(
        records_summary(records, max_size_mb=max_size_mb, max_total_size_mb=max_total_size_mb),
        indent=2,
        sort_keys=True,
    )


def records_over_size_budget(records: Sequence[ImageSizeRecord], max_size_mb: float) -> list[ImageSizeRecord]:
    max_size_bytes = max_size_mb * 1_000_000
    return [
        record
        for record in records
        if record.present and record.size_bytes is not None and record.size_bytes > max_size_bytes
    ]


def markdown_cell(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def records_to_markdown(
    records: Sequence[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
) -> str:
    rows = ["| Image | Present | Size MB | Image ID | Created |", "| --- | --- | ---: | --- | --- |"]
    for record in records:
        rows.append(
            "| {tag} | {present} | {size} | {image_id} | {created} |".format(
                tag=markdown_cell(record.tag),
                present="yes" if record.present else "no",
                size=f"{record.size_mb:.1f}" if record.size_mb is not None else "",
                image_id=markdown_cell(record.image_id),
                created=markdown_cell(record.created),
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
    if max_size_mb is not None:
        over_budget = records_over_size_budget(records, max_size_mb)
        rows.append(
            "Image size budget: {budget:.1f} MB, {count} image{plural} over budget.".format(
                budget=max_size_mb,
                count=len(over_budget),
                plural="" if len(over_budget) == 1 else "s",
            )
        )
    if max_total_size_mb is not None:
        rows.append(
            "Total image size budget: {budget:.1f} MB, current total {total:.1f} MB.".format(
                budget=max_total_size_mb,
                total=round(total_bytes / 1_000_000, 1) if total_bytes else 0.0,
            )
        )
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
    parser.add_argument("--csv", action="store_true", help="Emit CSV rows instead of markdown.")
    parser.add_argument(
        "--sort-by",
        choices=SORT_CHOICES,
        default="input",
        help="Order output records by input order, image tag, or descending image size.",
    )
    parser.add_argument(
        "--summary-only",
        "--json-summary",
        "--summary-json",
        dest="summary_only",
        action="store_true",
        help="Emit only the aggregate image count and size summary as JSON.",
    )
    parser.add_argument(
        "--max-size-mb",
        type=float,
        help="Exit non-zero when any present image is larger than this decimal-megabyte budget.",
    )
    parser.add_argument(
        "--max-total-size-mb",
        type=float,
        help="Exit non-zero when all present images exceed this combined decimal-megabyte budget.",
    )
    parser.add_argument(
        "--require-present",
        "--fail-on-missing",
        dest="require_present",
        action="store_true",
        help="Exit non-zero when any requested image is absent.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records = sort_records(inspect_images(args.images), args.sort_by)
    if args.summary_only:
        output = records_summary_to_json(
            records,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
        )
    elif args.csv:
        output = records_to_csv(records)
    else:
        output = (
            records_to_json(records, max_size_mb=args.max_size_mb, max_total_size_mb=args.max_total_size_mb)
            if args.json
            else records_to_markdown(records, max_size_mb=args.max_size_mb, max_total_size_mb=args.max_total_size_mb)
        )
    print(output)
    missing_records = [record for record in records if not record.present]
    oversized_records = records_over_size_budget(records, args.max_size_mb) if args.max_size_mb is not None else []
    total_size_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    total_over_budget = (
        args.max_total_size_mb is not None and total_size_bytes > args.max_total_size_mb * 1_000_000
    )
    if args.require_present and missing_records:
        print(
            "Missing required images: {tags}".format(tags=", ".join(record.tag for record in missing_records)),
            file=sys.stderr,
        )
    if args.max_size_mb is not None and oversized_records:
        print(
            "Images over {budget:.1f} MB: {tags}".format(
                budget=args.max_size_mb,
                tags=", ".join(
                    f"{record.tag} ({record.size_mb:.1f} MB)"
                    for record in oversized_records
                    if record.size_mb is not None
                ),
            ),
            file=sys.stderr,
        )
    if total_over_budget:
        print(
            "Total image size over {budget:.1f} MB: {total:.1f} MB".format(
                budget=args.max_total_size_mb,
                total=round(total_size_bytes / 1_000_000, 1),
            ),
            file=sys.stderr,
        )
    if (args.require_present and missing_records) or oversized_records or total_over_budget:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
