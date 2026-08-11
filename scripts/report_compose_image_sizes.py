#!/usr/bin/env python3
"""Report Docker image sizes for the supported Compose runtime tags."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any, Iterable, Sequence

DEFAULT_IMAGES = (
    "realtime-asr:faster-whisper-cpu",
    "realtime-asr:qwen-cpu",
    "realtime-asr:parakeet-transformers-cpu",
    "realtime-asr:parakeet-nemo-cpu",
)

SORT_CHOICES = (
    "input",
    "tag",
    "size-asc",
    "size-desc",
    "created-asc",
    "created-desc",
    "age-asc",
    "age-desc",
    "present-first",
    "missing-first",
    "known-size-first",
    "unknown-size-first",
    "known-created-first",
    "unknown-created-first",
    "duplicate-id-first",
    "unique-id-first",
)
SORT_CHOICE_SET = set(SORT_CHOICES)
OUTPUT_FORMAT_CHOICES = (
    "markdown",
    "json",
    "csv",
    "summary-json",
    "summary-csv",
    "summary-markdown",
)
OUTPUT_FORMAT_CHOICE_SET = set(OUTPUT_FORMAT_CHOICES)
OUTPUT_FORMAT_ALIASES = {
    "md": "markdown",
    "table": "markdown",
    "markdown-table": "markdown",
    "md-table": "markdown",
    "table-md": "markdown",
    "rows": "markdown",
    "json-summary": "summary-json",
    "summary": "summary-json",
    "csv-summary": "summary-csv",
    "md-summary": "summary-markdown",
    "markdown-summary": "summary-markdown",
    "summary-md": "summary-markdown",
    "summary-markdown-table": "summary-markdown",
    "summary-table": "summary-markdown",
    "summary-md-table": "summary-markdown",
    "table-summary": "summary-markdown",
    "table-summary-md": "summary-markdown",
}
SORT_ALIASES = {
    "as-listed": "input",
    "by-input": "input",
    "by-input-order": "input",
    "input-order": "input",
    "listed": "input",
    "requested": "input",
    "by-name": "tag",
    "by-tag": "tag",
    "by-image-name": "tag",
    "name": "tag",
    "name-asc": "tag",
    "tag-name": "tag",
    "tag-asc": "tag",
    "image-name": "tag",
    "image-name-asc": "tag",
    "by-largest": "size-desc",
    "largest-to-smallest": "size-desc",
    "by-size": "size-desc",
    "by-size-desc": "size-desc",
    "largest": "size-desc",
    "largest-image": "size-desc",
    "largest-image-first": "size-desc",
    "largest-first": "size-desc",
    "biggest": "size-desc",
    "biggest-first": "size-desc",
    "heaviest": "size-desc",
    "heaviest-first": "size-desc",
    "by-smallest": "size-asc",
    "smallest-to-largest": "size-asc",
    "by-size-asc": "size-asc",
    "smallest": "size-asc",
    "smallest-image": "size-asc",
    "smallest-image-first": "size-asc",
    "smallest-first": "size-asc",
    "lightest": "size-asc",
    "lightest-first": "size-asc",
    "by-created": "created-desc",
    "by-created-desc": "created-desc",
    "by-newest": "created-desc",
    "newest-to-oldest": "created-desc",
    "newest": "created-desc",
    "newest-image": "created-desc",
    "newest-image-first": "created-desc",
    "created": "created-desc",
    "created-first": "created-desc",
    "newest-first": "created-desc",
    "newest-created": "created-desc",
    "newest-created-first": "created-desc",
    "newer": "created-desc",
    "newer-first": "created-desc",
    "latest": "created-desc",
    "latest-first": "created-desc",
    "recent": "created-desc",
    "recent-first": "created-desc",
    "by-freshest": "age-asc",
    "by-age-asc": "age-asc",
    "by-freshness": "age-asc",
    "freshest": "age-asc",
    "freshest-first": "age-asc",
    "freshness": "age-asc",
    "freshness-first": "age-asc",
    "youngest": "age-asc",
    "youngest-first": "age-asc",
    "by-oldest": "created-asc",
    "oldest-to-newest": "created-asc",
    "by-created-asc": "created-asc",
    "oldest": "created-asc",
    "oldest-image": "created-asc",
    "oldest-image-first": "created-asc",
    "oldest-first": "created-asc",
    "oldest-created": "created-asc",
    "oldest-created-first": "created-asc",
    "older": "created-asc",
    "older-first": "created-asc",
    "earliest": "created-asc",
    "earliest-first": "created-asc",
    "age": "age-desc",
    "age-first": "age-desc",
    "by-age": "age-desc",
    "by-age-desc": "age-desc",
    "freshest-age": "age-asc",
    "freshest-age-first": "age-asc",
    "youngest-age": "age-asc",
    "youngest-age-first": "age-asc",
    "newest-age": "age-asc",
    "newest-age-first": "age-asc",
    "stale-age": "age-desc",
    "stale-age-first": "age-desc",
    "stale": "age-desc",
    "stale-first": "age-desc",
    "stale-images": "age-desc",
    "stale-images-first": "age-desc",
    "staleness": "age-desc",
    "staleness-first": "age-desc",
    "stalest-age": "age-desc",
    "stalest-age-first": "age-desc",
    "stalest": "age-desc",
    "stalest-first": "age-desc",
    "old-images": "age-desc",
    "old-images-first": "age-desc",
    "oldest-images": "age-desc",
    "oldest-images-first": "age-desc",
    "oldest-age": "age-desc",
    "oldest-age-first": "age-desc",
    "oldest-by-age": "age-desc",
    "oldest-by-age-first": "age-desc",
    "by-present": "present-first",
    "present": "present-first",
    "present-images": "present-first",
    "present-first": "present-first",
    "available": "present-first",
    "available-first": "present-first",
    "existing": "present-first",
    "existing-first": "present-first",
    "by-missing": "missing-first",
    "missing": "missing-first",
    "missing-images": "missing-first",
    "missing-first": "missing-first",
    "absent": "missing-first",
    "absent-first": "missing-first",
    "unavailable": "missing-first",
    "unavailable-first": "missing-first",
    "known-size": "known-size-first",
    "known-sizes": "known-size-first",
    "known-size-first": "known-size-first",
    "known-image-size": "known-size-first",
    "known-image-sizes": "known-size-first",
    "known-image-size-first": "known-size-first",
    "known-image-sizes-first": "known-size-first",
    "sized": "known-size-first",
    "sized-first": "known-size-first",
    "sized-images": "known-size-first",
    "sized-images-first": "known-size-first",
    "unknown-size": "unknown-size-first",
    "unknown-sizes": "unknown-size-first",
    "unknown-size-first": "unknown-size-first",
    "missing-size": "unknown-size-first",
    "missing-size-first": "unknown-size-first",
    "known-created": "known-created-first",
    "created-known": "known-created-first",
    "created-known-first": "known-created-first",
    "known-created-first": "known-created-first",
    "known-creation": "known-created-first",
    "known-creation-first": "known-created-first",
    "known-created-time": "known-created-first",
    "known-created-time-first": "known-created-first",
    "known-image-created": "known-created-first",
    "known-image-created-first": "known-created-first",
    "timestamped": "known-created-first",
    "timestamped-first": "known-created-first",
    "dated": "known-created-first",
    "dated-first": "known-created-first",
    "unknown-created": "unknown-created-first",
    "created-unknown": "unknown-created-first",
    "created-unknown-first": "unknown-created-first",
    "unknown-created-first": "unknown-created-first",
    "unknown-creation": "unknown-created-first",
    "unknown-creation-first": "unknown-created-first",
    "missing-created-time": "unknown-created-first",
    "missing-created-time-first": "unknown-created-first",
    "missing-created": "unknown-created-first",
    "missing-created-first": "unknown-created-first",
    "duplicates": "duplicate-id-first",
    "duplicate": "duplicate-id-first",
    "duplicate-id": "duplicate-id-first",
    "duplicate-ids": "duplicate-id-first",
    "duplicate-id-first": "duplicate-id-first",
    "duplicate-image-id": "duplicate-id-first",
    "duplicate-image-ids": "duplicate-id-first",
    "duplicate-image-id-first": "duplicate-id-first",
    "duplicate-image-ids-first": "duplicate-id-first",
    "shared-id": "duplicate-id-first",
    "shared-ids": "duplicate-id-first",
    "shared-id-first": "duplicate-id-first",
    "shared-image-id": "duplicate-id-first",
    "shared-image-id-first": "duplicate-id-first",
    "same-id": "duplicate-id-first",
    "same-id-first": "duplicate-id-first",
    "same-image-id": "duplicate-id-first",
    "same-image-id-first": "duplicate-id-first",
    "unique-id": "unique-id-first",
    "unique-ids": "unique-id-first",
    "unique-id-first": "unique-id-first",
    "unique-image-id": "unique-id-first",
    "unique-image-ids": "unique-id-first",
    "unique-image-id-first": "unique-id-first",
    "unique-image-ids-first": "unique-id-first",
    "single-id": "unique-id-first",
    "single-id-first": "unique-id-first",
    "single-image-id": "unique-id-first",
    "single-image-id-first": "unique-id-first",
}
UTC_DATETIME_MIN = datetime.min.replace(tzinfo=UTC)
UTC_DATETIME_MAX = datetime.max.replace(tzinfo=UTC)
BYTE_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "k": 1000,
    "kb": 1000,
    "kilobyte": 1000,
    "kilobytes": 1000,
    "kib": 1024,
    "kibibyte": 1024,
    "kibibytes": 1024,
    "m": 1000**2,
    "mb": 1000**2,
    "megabyte": 1000**2,
    "megabytes": 1000**2,
    "mib": 1024**2,
    "mebibyte": 1024**2,
    "mebibytes": 1024**2,
    "g": 1000**3,
    "gb": 1000**3,
    "gigabyte": 1000**3,
    "gigabytes": 1000**3,
    "gib": 1024**3,
    "gibibyte": 1024**3,
    "gibibytes": 1024**3,
    "t": 1000**4,
    "tb": 1000**4,
    "terabyte": 1000**4,
    "terabytes": 1000**4,
    "tib": 1024**4,
    "tebibyte": 1024**4,
    "tebibytes": 1024**4,
}
AGE_DAY_UNITS = {
    "": 1.0,
    "d": 1.0,
    "day": 1.0,
    "days": 1.0,
    "h": 1.0 / 24.0,
    "hr": 1.0 / 24.0,
    "hrs": 1.0 / 24.0,
    "hour": 1.0 / 24.0,
    "hours": 1.0 / 24.0,
    "w": 7.0,
    "wk": 7.0,
    "wks": 7.0,
    "week": 7.0,
    "weeks": 7.0,
}


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
    if sort_by == "size-asc":
        return sorted(records, key=lambda record: (record.size_bytes is None, record.size_bytes or 0))
    if sort_by == "size-desc":
        return sorted(records, key=lambda record: (record.size_bytes is not None, record.size_bytes or 0), reverse=True)
    if sort_by == "created-asc":
        return sorted(records, key=created_asc_sort_key)
    if sort_by == "created-desc":
        return sorted(records, key=created_desc_sort_key, reverse=True)
    if sort_by == "age-asc":
        return sorted(records, key=lambda record: (image_age_days(record) is None, image_age_days(record) or 0))
    if sort_by == "age-desc":
        return sorted(records, key=lambda record: (image_age_days(record) is not None, image_age_days(record) or 0), reverse=True)
    if sort_by == "present-first":
        return sorted(records, key=lambda record: (not record.present, record.tag))
    if sort_by == "missing-first":
        return sorted(records, key=lambda record: (record.present, record.tag))
    if sort_by == "known-size-first":
        return sorted(records, key=lambda record: (not (record.present and record.size_bytes is not None), record.tag))
    if sort_by == "unknown-size-first":
        return sorted(records, key=lambda record: (not (record.present and record.size_bytes is None), record.tag))
    if sort_by == "known-created-first":
        return sorted(
            records,
            key=lambda record: (not (record.present and parse_created_datetime(record.created) is not None), record.tag),
        )
    if sort_by == "unknown-created-first":
        return sorted(
            records,
            key=lambda record: (not (record.present and parse_created_datetime(record.created) is None), record.tag),
        )
    if sort_by in {"duplicate-id-first", "unique-id-first"}:
        duplicate_ids = {
            group["image_id"]
            for group in records_with_duplicate_image_ids(records)
            if isinstance(group.get("image_id"), str)
        }

        def duplicate_id_key(record: ImageSizeRecord) -> tuple[bool, str]:
            has_duplicate_id = bool(record.present and record.image_id in duplicate_ids)
            selected = has_duplicate_id if sort_by == "duplicate-id-first" else not has_duplicate_id
            return (not selected, record.tag)

        return sorted(records, key=duplicate_id_key)
    raise ValueError(f"unknown sort mode: {sort_by}")


def parse_sort_choice(value: str) -> str:
    normalized = normalize_choice_token(value)
    normalized = SORT_ALIASES.get(normalized, normalized)
    if normalized not in SORT_CHOICE_SET:
        choices = ", ".join(SORT_CHOICES)
        raise argparse.ArgumentTypeError(f"invalid sort mode: {value!r}; choose one of: {choices}")
    return normalized


def parse_output_format(value: str) -> str:
    normalized = normalize_choice_token(value)
    normalized = OUTPUT_FORMAT_ALIASES.get(normalized, normalized)
    if normalized not in OUTPUT_FORMAT_CHOICE_SET:
        choices = ", ".join(OUTPUT_FORMAT_CHOICES)
        raise argparse.ArgumentTypeError(f"invalid output format: {value!r}; choose one of: {choices}")
    return normalized


def normalize_choice_token(value: str) -> str:
    return re.sub(r"[\s_/]+", "-", value.strip().lower())


def parse_positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a positive finite number: {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive finite number: {value!r}")
    return parsed


def parse_age_days(value: str) -> float:
    match = re.fullmatch(r"\s*(-?(?:\d+(?:[,_]\d{3})+|\d+)(?:\.\d+)?)\s*([a-zA-Z]*)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError("age must be a positive finite value in days, hours, or weeks")

    amount_text, unit_text = match.groups()
    amount = float(amount_text.replace(",", "").replace("_", ""))
    if not math.isfinite(amount) or amount <= 0:
        raise argparse.ArgumentTypeError(f"age must be a positive finite value: {value!r}")

    multiplier = AGE_DAY_UNITS.get(unit_text.lower())
    if multiplier is None:
        raise argparse.ArgumentTypeError("age unit must be one of: hours, days, weeks")

    return amount * multiplier


def parse_nonnegative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a nonnegative integer: {value!r}") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError(f"must be a nonnegative integer: {value!r}")
    return parsed


def parse_size_mb(value: str) -> float:
    match = re.fullmatch(r"\s*(-?(?:\d+(?:[,_]\d{3})+|\d+)(?:\.\d+)?)\s*([a-zA-Z]*)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError("size must be megabytes or a value with B, K, KB, KiB, MB, MiB, GB, GiB, TB, or TiB")

    amount_text, unit_text = match.groups()
    amount = float(amount_text.replace(",", "").replace("_", ""))
    if not math.isfinite(amount) or amount <= 0:
        raise argparse.ArgumentTypeError(f"size must be a positive finite value: {value!r}")

    unit = unit_text.lower()
    multiplier = BYTE_SIZE_UNITS.get(unit if unit else "mb")
    if multiplier is None:
        raise argparse.ArgumentTypeError("size unit must be one of: B, K, KB, KiB, MB, MiB, GB, GiB, TB, TiB")

    return amount * multiplier / 1_000_000


def normalize_image_args(positional_images: Sequence[str], option_images: Sequence[str] | None = None) -> list[str]:
    images = [
        image.strip()
        for value in (*positional_images, *(option_images or ()))
        for image in value.split(",")
        if image.strip()
    ]
    return images or list(DEFAULT_IMAGES)


def records_to_json(
    records: Iterable[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    record_list = list(records)
    summary = records_summary(
        record_list,
        max_missing=max_missing,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
        max_deduplicated_total_size_mb=max_deduplicated_total_size_mb,
        max_age_days=max_age_days,
    )
    payload = [
        {
            "tag": record.tag,
            "present": record.present,
            "image_id": record.image_id,
            "size_bytes": record.size_bytes,
            "size_mb": record.size_mb,
            "created": record.created,
            "age_days": image_age_days(record),
        }
        for record in record_list
    ]
    payload.append({"summary": summary})
    return json.dumps(payload, indent=2, sort_keys=True)


def records_to_csv(records: Iterable[ImageSizeRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=("tag", "present", "image_id", "size_bytes", "size_mb", "created", "age_days"),
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
                "age_days": f"{age_days:.1f}" if (age_days := image_age_days(record)) is not None else "",
            }
        )
    return output.getvalue().rstrip("\n")


def records_summary(
    records: Sequence[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    present_sizes = [record.size_bytes for record in records if record.present and record.size_bytes is not None]
    total_bytes = sum(present_sizes)
    deduplicated_total_bytes = deduplicated_present_size_bytes(records)
    median_size_bytes = round(median(present_sizes)) if present_sizes else None
    missing = [record.tag for record in records if not record.present]
    unknown_size = [record.tag for record in records if record.present and record.size_bytes is None]
    unknown_created = [record.tag for record in records if record.present and parse_created_datetime(record.created) is None]
    largest = max(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    smallest = min(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    records_with_created = [
        (created, record)
        for record in records
        if record.present and (created := parse_created_datetime(record.created)) is not None
    ]
    newest = max(records_with_created, key=lambda item: item[0], default=(None, None))[1]
    oldest = min(records_with_created, key=lambda item: item[0], default=(None, None))[1]
    duplicate_image_id_groups = records_with_duplicate_image_ids(records)
    known_image_ids = [record.image_id for record in records if record.present and record.image_id]
    unique_image_ids = sorted(set(known_image_ids))
    summary = {
        "requested": len(records),
        "present": len(records) - len(missing),
        "present_percent": round((len(records) - len(missing)) / len(records) * 100, 1) if records else 0.0,
        "missing": len(missing),
        "missing_percent": round(len(missing) / len(records) * 100, 1) if records else 0.0,
        "missing_tags": missing,
        "unknown_size": len(unknown_size),
        "unknown_size_percent": round(len(unknown_size) / len(records) * 100, 1) if records else 0.0,
        "unknown_size_tags": unknown_size,
        "unknown_created": len(unknown_created),
        "unknown_created_percent": round(len(unknown_created) / len(records) * 100, 1) if records else 0.0,
        "unknown_created_tags": unknown_created,
        "total_size_bytes": total_bytes,
        "total_size_mb": round(total_bytes / 1_000_000, 1) if total_bytes else 0.0,
        "deduplicated_total_size_bytes": deduplicated_total_bytes,
        "deduplicated_total_size_mb": round(deduplicated_total_bytes / 1_000_000, 1) if deduplicated_total_bytes else 0.0,
        "duplicate_size_savings_bytes": max(0, total_bytes - deduplicated_total_bytes),
        "duplicate_size_savings_mb": round(max(0, total_bytes - deduplicated_total_bytes) / 1_000_000, 1),
        "average_present_size_bytes": round(total_bytes / len(present_sizes)) if present_sizes else None,
        "average_present_size_mb": round(total_bytes / len(present_sizes) / 1_000_000, 1) if present_sizes else None,
        "median_present_size_bytes": median_size_bytes,
        "median_present_size_mb": round(median_size_bytes / 1_000_000, 1) if median_size_bytes is not None else None,
        "range_present_size_bytes": (
            largest.size_bytes - smallest.size_bytes
            if largest and largest.size_bytes is not None and smallest and smallest.size_bytes is not None
            else None
        ),
        "range_present_size_mb": (
            round((largest.size_bytes - smallest.size_bytes) / 1_000_000, 1)
            if largest and largest.size_bytes is not None and smallest and smallest.size_bytes is not None
            else None
        ),
        "largest_present_tag": largest.tag if largest else None,
        "largest_present_size_bytes": largest.size_bytes if largest else None,
        "largest_present_size_mb": largest.size_mb if largest else None,
        "smallest_present_tag": smallest.tag if smallest else None,
        "smallest_present_size_bytes": smallest.size_bytes if smallest else None,
        "smallest_present_size_mb": smallest.size_mb if smallest else None,
        "newest_present_tag": newest.tag if newest else None,
        "newest_present_created": newest.created if newest else None,
        "oldest_present_tag": oldest.tag if oldest else None,
        "oldest_present_created": oldest.created if oldest else None,
        "duplicate_image_ids": len(duplicate_image_id_groups),
        "duplicate_image_id_groups": duplicate_image_id_groups,
        "known_image_ids": len(known_image_ids),
        "unique_image_ids": len(unique_image_ids),
        "duplicate_image_id_tag_refs": sum(len(group["tags"]) for group in duplicate_image_id_groups),
    }
    if max_size_mb is not None:
        over_budget = records_over_size_budget(records, max_size_mb)
        over_budget_excess_bytes = sum(
            max(0, int(record.size_bytes - max_size_mb * 1_000_000))
            for record in over_budget
            if record.size_bytes is not None
        )
        largest_budget_utilization_percent = (
            round((largest.size_bytes or 0) / (max_size_mb * 1_000_000) * 100, 1)
            if largest and largest.size_bytes is not None and max_size_mb > 0
            else None
        )
        summary.update(
            {
                "image_size_budget_mb": max_size_mb,
                "largest_image_budget_utilization_percent": largest_budget_utilization_percent,
                "over_budget": bool(over_budget),
                "over_budget_count": len(over_budget),
                "over_budget_tags": [record.tag for record in over_budget],
                "over_budget_excess_bytes": over_budget_excess_bytes,
                "over_budget_excess_mb": round(over_budget_excess_bytes / 1_000_000, 1),
            }
        )
    if max_missing is not None:
        missing_budget_excess = max(0, len(missing) - max_missing)
        summary.update(
            {
                "missing_image_budget": max_missing,
                "missing_over_budget": len(missing) > max_missing,
                "missing_budget_excess": missing_budget_excess,
            }
        )
    if max_total_size_mb is not None:
        total_budget_excess_bytes = max(0, int(total_bytes - max_total_size_mb * 1_000_000))
        summary.update(
            {
                "total_image_size_budget_mb": max_total_size_mb,
                "total_budget_utilization_percent": (
                    round(total_bytes / (max_total_size_mb * 1_000_000) * 100, 1)
                    if max_total_size_mb > 0
                    else None
                ),
                "total_over_budget": total_bytes > max_total_size_mb * 1_000_000,
                "total_budget_excess_bytes": total_budget_excess_bytes,
                "total_budget_excess_mb": round(total_budget_excess_bytes / 1_000_000, 1),
            }
        )
    if max_deduplicated_total_size_mb is not None:
        deduplicated_total_budget_excess_bytes = max(
            0,
            int(deduplicated_total_bytes - max_deduplicated_total_size_mb * 1_000_000),
        )
        summary.update(
            {
                "deduplicated_total_image_size_budget_mb": max_deduplicated_total_size_mb,
                "deduplicated_total_budget_utilization_percent": (
                    round(deduplicated_total_bytes / (max_deduplicated_total_size_mb * 1_000_000) * 100, 1)
                    if max_deduplicated_total_size_mb > 0
                    else None
                ),
                "deduplicated_total_over_budget": (
                    deduplicated_total_bytes > max_deduplicated_total_size_mb * 1_000_000
                ),
                "deduplicated_total_budget_excess_bytes": deduplicated_total_budget_excess_bytes,
                "deduplicated_total_budget_excess_mb": round(
                    deduplicated_total_budget_excess_bytes / 1_000_000,
                    1,
                ),
            }
        )
    if max_age_days is not None:
        now = now or datetime.now(UTC)
        over_age = records_over_age_budget(records, max_age_days, now=now)
        oldest_age_record = oldest_image_age_record(records, now=now)
        freshest_age_record = freshest_image_age_record(records, now=now)
        oldest_age = oldest_image_age_days(records, now=now)
        summary.update(
            {
                "image_age_budget_days": max_age_days,
                "oldest_image_age_budget_utilization_percent": (
                    round(oldest_age / max_age_days * 100, 1)
                    if oldest_age is not None and max_age_days > 0
                    else None
                ),
                "over_age": bool(over_age),
                "over_age_count": len(over_age),
                "over_age_tags": [record.tag for record in over_age],
                "freshest_image_age_tag": freshest_age_record.tag if freshest_age_record else None,
                "freshest_image_age_days": freshest_image_age_days(records, now=now),
                "oldest_image_age_tag": oldest_age_record.tag if oldest_age_record else None,
                "oldest_image_age_days": oldest_age,
            }
        )
    return summary


def records_summary_to_json(
    records: Sequence[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    return json.dumps(
        records_summary(
            records,
            max_missing=max_missing,
            max_size_mb=max_size_mb,
            max_total_size_mb=max_total_size_mb,
            max_deduplicated_total_size_mb=max_deduplicated_total_size_mb,
            max_age_days=max_age_days,
        ),
        indent=2,
        sort_keys=True,
    )


def summary_csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True)
    return str(value)


def records_summary_to_csv(
    records: Sequence[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    summary = records_summary(
        records,
        max_missing=max_missing,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
        max_deduplicated_total_size_mb=max_deduplicated_total_size_mb,
        max_age_days=max_age_days,
    )
    output = io.StringIO()
    fieldnames = sorted(summary)
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerow({key: summary_csv_value(value) for key, value in summary.items()})
    return output.getvalue().rstrip("\n")


def records_summary_to_markdown(
    records: Sequence[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    summary = records_summary(
        records,
        max_missing=max_missing,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
        max_deduplicated_total_size_mb=max_deduplicated_total_size_mb,
        max_age_days=max_age_days,
    )
    rows = [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Requested images | {summary['requested']} |",
        f"| Present images | {summary['present']} ({summary['present_percent']:.1f}%) |",
        f"| Missing images | {summary['missing']} ({summary['missing_percent']:.1f}%) |",
        f"| Total present image size | {summary['total_size_mb']:.1f} MB |",
        f"| Deduplicated present image size | {summary['deduplicated_total_size_mb']:.1f} MB |",
        f"| Shared-image size savings | {summary['duplicate_size_savings_mb']:.1f} MB |",
        f"| Average present image size | {format_optional_mb(summary['average_present_size_mb'])} |",
        f"| Median present image size | {format_optional_mb(summary['median_present_size_mb'])} |",
        f"| Largest present image | {format_tag_mb(summary['largest_present_tag'], summary['largest_present_size_mb'])} |",
        f"| Smallest present image | {format_tag_mb(summary['smallest_present_tag'], summary['smallest_present_size_mb'])} |",
        f"| Newest present image | {format_tag_value(summary['newest_present_tag'], summary['newest_present_created'])} |",
        f"| Oldest present image | {format_tag_value(summary['oldest_present_tag'], summary['oldest_present_created'])} |",
        f"| Unknown sizes | {format_tag_list(summary['unknown_size'], summary['unknown_size_tags'])} |",
        f"| Unknown creation times | {format_tag_list(summary['unknown_created'], summary['unknown_created_tags'])} |",
        f"| Duplicate image IDs | {summary['duplicate_image_ids']} |",
        f"| Known image ID references | {summary['known_image_ids']} |",
        f"| Unique image IDs | {summary['unique_image_ids']} |",
        f"| Duplicate image ID tag refs | {summary['duplicate_image_id_tag_refs']} |",
    ]
    if max_size_mb is not None:
        rows.append(
            "| Per-image size budget | {budget:.1f} MB; {count} over; {excess:.1f} MB excess |".format(
                budget=summary["image_size_budget_mb"],
                count=summary["over_budget_count"],
                excess=summary["over_budget_excess_mb"],
            )
        )
    if max_missing is not None:
        rows.append(
            "| Missing image budget | {budget}; {count} missing; {excess} over |".format(
                budget=summary["missing_image_budget"],
                count=summary["missing"],
                excess=summary["missing_budget_excess"],
            )
        )
    if max_total_size_mb is not None:
        rows.append(
            "| Total image size budget | {budget:.1f} MB; {utilization} utilization; {excess:.1f} MB excess |".format(
                budget=summary["total_image_size_budget_mb"],
                utilization=format_optional_percent(summary["total_budget_utilization_percent"]),
                excess=summary["total_budget_excess_mb"],
            )
        )
    if max_deduplicated_total_size_mb is not None:
        rows.append(
            "| Deduplicated total image size budget | {budget:.1f} MB; {utilization} utilization; {excess:.1f} MB excess |".format(
                budget=summary["deduplicated_total_image_size_budget_mb"],
                utilization=format_optional_percent(summary["deduplicated_total_budget_utilization_percent"]),
                excess=summary["deduplicated_total_budget_excess_mb"],
            )
        )
    if max_age_days is not None:
        rows.append(
            "| Image age budget | {budget:.1f} days; {count} over; {utilization} oldest utilization; freshest {freshest}; oldest {oldest} |".format(
                budget=summary["image_age_budget_days"],
                count=summary["over_age_count"],
                utilization=format_optional_percent(summary["oldest_image_age_budget_utilization_percent"]),
                freshest=format_tag_days(summary["freshest_image_age_tag"], summary["freshest_image_age_days"]),
                oldest=format_tag_days(summary["oldest_image_age_tag"], summary["oldest_image_age_days"]),
            )
        )
    if summary["missing_tags"]:
        rows.append(f"| Missing tags | {markdown_cell(', '.join(summary['missing_tags']))} |")
    if summary.get("over_budget_tags"):
        rows.append(f"| Tags over size budget | {markdown_cell(', '.join(summary['over_budget_tags']))} |")
    if summary.get("over_age_tags"):
        rows.append(f"| Tags over age budget | {markdown_cell(', '.join(summary['over_age_tags']))} |")
    if summary["duplicate_image_id_groups"]:
        rows.append(f"| Duplicate groups | {markdown_cell(format_duplicate_image_id_groups(summary['duplicate_image_id_groups']))} |")
    return "\n".join(rows)


def format_optional_mb(value: float | None) -> str:
    return "" if value is None else f"{value:.1f} MB"


def format_optional_percent(value: float | None) -> str:
    return "" if value is None else f"{value:.1f}%"


def format_optional_days(value: float | None) -> str:
    return "" if value is None else f"{value:.1f} days"


def format_tag_value(tag: str | None, value: Any) -> str:
    if tag is None or value is None:
        return ""
    return markdown_cell(f"{tag} ({value})")


def format_tag_mb(tag: str | None, value: float | None) -> str:
    if tag is None or value is None:
        return ""
    return markdown_cell(f"{tag} ({value:.1f} MB)")


def format_tag_days(tag: str | None, value: float | None) -> str:
    if tag is None or value is None:
        return ""
    return markdown_cell(f"{tag} ({value:.1f} days)")


def format_tag_list(count: int, tags: Sequence[str]) -> str:
    if not tags:
        return str(count)
    return markdown_cell(f"{count}: {', '.join(tags)}")


def format_duplicate_image_id_groups(groups: Sequence[dict[str, Any]]) -> str:
    return "; ".join(
        "{image_id}: {tags}".format(
            image_id=group["image_id"],
            tags=", ".join(group["tags"]),
        )
        for group in groups
    )


def records_over_size_budget(records: Sequence[ImageSizeRecord], max_size_mb: float) -> list[ImageSizeRecord]:
    max_size_bytes = max_size_mb * 1_000_000
    return [
        record
        for record in records
        if record.present and record.size_bytes is not None and record.size_bytes > max_size_bytes
    ]


def parse_created_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    value = truncate_fractional_seconds(value)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def truncate_fractional_seconds(value: str) -> str:
    fraction_start = value.find(".")
    if fraction_start == -1:
        return value

    timezone_markers = (
        index
        for index in (
            value.find("+", fraction_start),
            value.find("-", fraction_start),
            value.find("Z", fraction_start),
        )
        if index != -1
    )
    fraction_end = min(timezone_markers, default=len(value))
    fraction = value[fraction_start + 1 : fraction_end]
    if len(fraction) <= 6:
        return value
    return f"{value[: fraction_start + 1]}{fraction[:6]}{value[fraction_end:]}"


def image_age_days(record: ImageSizeRecord, now: datetime | None = None) -> float | None:
    created = parse_created_datetime(record.created)
    if created is None:
        return None
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    return max(0.0, round((now.astimezone(UTC) - created).total_seconds() / 86400, 1))


def created_sort_datetime(record: ImageSizeRecord) -> datetime | None:
    return parse_created_datetime(record.created)


def created_asc_sort_key(record: ImageSizeRecord) -> tuple[bool, datetime]:
    created = created_sort_datetime(record)
    return created is None, created or UTC_DATETIME_MIN


def created_desc_sort_key(record: ImageSizeRecord) -> tuple[bool, datetime]:
    created = created_sort_datetime(record)
    return created is not None, created or UTC_DATETIME_MIN


def records_over_age_budget(
    records: Sequence[ImageSizeRecord],
    max_age_days: float,
    now: datetime | None = None,
) -> list[ImageSizeRecord]:
    return [
        record
        for record in records
        if record.present
        and (age_days := image_age_days(record, now=now)) is not None
        and age_days > max_age_days
    ]


def oldest_image_age_days(records: Sequence[ImageSizeRecord], now: datetime | None = None) -> float | None:
    oldest_record = oldest_image_age_record(records, now=now)
    return image_age_days(oldest_record, now=now) if oldest_record else None


def freshest_image_age_days(records: Sequence[ImageSizeRecord], now: datetime | None = None) -> float | None:
    freshest_record = freshest_image_age_record(records, now=now)
    return image_age_days(freshest_record, now=now) if freshest_record else None


def oldest_image_age_record(records: Sequence[ImageSizeRecord], now: datetime | None = None) -> ImageSizeRecord | None:
    ages = [
        (age_days, record)
        for record in records
        if record.present and (age_days := image_age_days(record, now=now)) is not None
    ]
    return max(ages, key=lambda item: item[0], default=(None, None))[1]


def freshest_image_age_record(records: Sequence[ImageSizeRecord], now: datetime | None = None) -> ImageSizeRecord | None:
    ages = [
        (age_days, record)
        for record in records
        if record.present and (age_days := image_age_days(record, now=now)) is not None
    ]
    return min(ages, key=lambda item: item[0], default=(None, None))[1]


def records_with_duplicate_image_ids(records: Sequence[ImageSizeRecord]) -> list[dict[str, Any]]:
    tags_by_image_id: dict[str, list[str]] = {}
    for record in records:
        if record.present and record.image_id:
            tags_by_image_id.setdefault(record.image_id, []).append(record.tag)
    return [
        {"image_id": image_id, "tags": tags}
        for image_id, tags in tags_by_image_id.items()
        if len(tags) > 1
    ]


def deduplicated_present_size_bytes(records: Sequence[ImageSizeRecord]) -> int:
    seen_image_ids: set[str] = set()
    total = 0
    for record in records:
        if not record.present or record.size_bytes is None:
            continue
        if record.image_id:
            if record.image_id in seen_image_ids:
                continue
            seen_image_ids.add(record.image_id)
        total += record.size_bytes
    return total


def markdown_cell(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def records_to_markdown(
    records: Sequence[ImageSizeRecord],
    max_missing: int | None = None,
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_deduplicated_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    rows = [
        "| Image | Present | Size MB | Image ID | Created | Age days |",
        "| --- | --- | ---: | --- | --- | ---: |",
    ]
    for record in records:
        rows.append(
            "| {tag} | {present} | {size} | {image_id} | {created} | {age_days} |".format(
                tag=markdown_cell(record.tag),
                present="yes" if record.present else "no",
                size=f"{record.size_mb:.1f}" if record.size_mb is not None else "",
                image_id=markdown_cell(record.image_id),
                created=markdown_cell(record.created),
                age_days=f"{age_days:.1f}" if (age_days := image_age_days(record)) is not None else "",
            )
        )
    total_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    deduplicated_total_bytes = deduplicated_present_size_bytes(records)
    if total_bytes:
        rows.append(
            "| {tag} | {present} | {size:.1f} | {image_id} | {created} | {age_days} |".format(
                tag="Total present images",
                present="",
                size=round(total_bytes / 1_000_000, 1),
                image_id="",
                created="",
                age_days="",
            )
        )
    if deduplicated_total_bytes and deduplicated_total_bytes != total_bytes:
        rows.append(
            "| {tag} | {present} | {size:.1f} | {image_id} | {created} | {age_days} |".format(
                tag="Deduplicated present images",
                present="",
                size=round(deduplicated_total_bytes / 1_000_000, 1),
                image_id="",
                created="",
                age_days="",
            )
        )
    missing = [record.tag for record in records if not record.present]
    rows.append("")
    rows.append(
        "Summary: {present}/{requested} images present ({present_percent:.1f}%), {missing} missing.".format(
            present=len(records) - len(missing),
            requested=len(records),
            present_percent=(len(records) - len(missing)) / len(records) * 100 if records else 0.0,
            missing=len(missing),
        )
    )
    largest = max(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    if largest and largest.size_mb is not None:
        rows.append(f"Largest present image: {format_tag_mb(largest.tag, largest.size_mb)}")
    smallest = min(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    if smallest and smallest.size_mb is not None:
        rows.append(f"Smallest present image: {format_tag_mb(smallest.tag, smallest.size_mb)}")
    records_with_created = [
        (created, record)
        for record in records
        if record.present and (created := parse_created_datetime(record.created)) is not None
    ]
    newest = max(records_with_created, key=lambda item: item[0], default=(None, None))[1]
    oldest = min(records_with_created, key=lambda item: item[0], default=(None, None))[1]
    if newest:
        rows.append(f"Newest present image: {format_tag_value(newest.tag, newest.created)}")
    if oldest:
        rows.append(f"Oldest present image: {format_tag_value(oldest.tag, oldest.created)}")
    present_sizes = [record.size_bytes for record in records if record.present and record.size_bytes is not None]
    if present_sizes:
        average_size_mb = sum(present_sizes) / len(present_sizes) / 1_000_000
        rows.append(f"Average present image size: {average_size_mb:.1f} MB")
        median_size_mb = median(present_sizes) / 1_000_000
        rows.append(f"Median present image size: {median_size_mb:.1f} MB")
        rows.append(f"Present image size range: {(max(present_sizes) - min(present_sizes)) / 1_000_000:.1f} MB")
    if max_size_mb is not None:
        over_budget = records_over_size_budget(records, max_size_mb)
        over_budget_excess_mb = sum(
            max(0.0, (record.size_bytes or 0) / 1_000_000 - max_size_mb)
            for record in over_budget
        )
        largest_budget_utilization_percent = (
            max(present_sizes) / (max_size_mb * 1_000_000) * 100
            if present_sizes and max_size_mb > 0
            else None
        )
        rows.append(
            "Image size budget: {budget:.1f} MB, {count} image{plural} over budget, {excess:.1f} MB total excess.".format(
                budget=max_size_mb,
                count=len(over_budget),
                plural="" if len(over_budget) == 1 else "s",
                excess=over_budget_excess_mb,
            )
        )
        if largest_budget_utilization_percent is not None:
            rows.append(f"Largest image budget utilization: {largest_budget_utilization_percent:.1f}%")
    if max_missing is not None:
        rows.append(
            "Missing image budget: {budget}, {missing} missing, {excess} over.".format(
                budget=max_missing,
                missing=len(missing),
                excess=max(0, len(missing) - max_missing),
            )
        )
    if max_total_size_mb is not None:
        total_budget_excess_mb = max(0.0, total_bytes / 1_000_000 - max_total_size_mb)
        rows.append(
            "Total image size budget: {budget:.1f} MB, current total {total:.1f} MB, {excess:.1f} MB over.".format(
                budget=max_total_size_mb,
                total=round(total_bytes / 1_000_000, 1) if total_bytes else 0.0,
                excess=total_budget_excess_mb,
            )
        )
        if max_total_size_mb > 0:
            rows.append(f"Total image size budget utilization: {total_bytes / (max_total_size_mb * 1_000_000) * 100:.1f}%")
    if max_deduplicated_total_size_mb is not None:
        deduplicated_total_budget_excess_mb = max(
            0.0,
            deduplicated_total_bytes / 1_000_000 - max_deduplicated_total_size_mb,
        )
        rows.append(
            "Deduplicated total image size budget: {budget:.1f} MB, current deduplicated total {total:.1f} MB, {excess:.1f} MB over.".format(
                budget=max_deduplicated_total_size_mb,
                total=round(deduplicated_total_bytes / 1_000_000, 1) if deduplicated_total_bytes else 0.0,
                excess=deduplicated_total_budget_excess_mb,
            )
        )
        if max_deduplicated_total_size_mb > 0:
            rows.append(
                "Deduplicated total image size budget utilization: {utilization:.1f}%".format(
                    utilization=deduplicated_total_bytes / (max_deduplicated_total_size_mb * 1_000_000) * 100
                )
            )
    if max_age_days is not None:
        over_age = records_over_age_budget(records, max_age_days)
        freshest_age_record = freshest_image_age_record(records)
        oldest_age_days = oldest_image_age_days(records)
        rows.append(
            "Image age budget: {budget:.1f} days, {count} image{plural} older than budget.".format(
                budget=max_age_days,
                count=len(over_age),
                plural="" if len(over_age) == 1 else "s",
            )
        )
        if freshest_age_record is not None:
            freshest_age_days = image_age_days(freshest_age_record)
            if freshest_age_days is not None:
                rows.append(f"Freshest present image age: {format_tag_days(freshest_age_record.tag, freshest_age_days)}")
        if oldest_age_days is not None:
            oldest_age_record = oldest_image_age_record(records)
            if oldest_age_record is not None:
                rows.append(f"Oldest present image age: {format_tag_days(oldest_age_record.tag, oldest_age_days)}")
            else:
                rows.append(f"Oldest present image age: {oldest_age_days:.1f} days")
            if max_age_days > 0:
                rows.append(f"Oldest image age budget utilization: {oldest_age_days / max_age_days * 100:.1f}%")
    if missing:
        rows.append("Missing images: {tags}".format(tags=markdown_cell(", ".join(missing))))
    unknown_size = [record.tag for record in records if record.present and record.size_bytes is None]
    if unknown_size:
        rows.append(
            "Images with unknown size: {count}/{requested} ({percent:.1f}%): {tags}".format(
                count=len(unknown_size),
                requested=len(records),
                percent=len(unknown_size) / len(records) * 100 if records else 0.0,
                tags=markdown_cell(", ".join(unknown_size)),
            )
        )
    unknown_created = [record.tag for record in records if record.present and parse_created_datetime(record.created) is None]
    if unknown_created:
        rows.append(
            "Images with unknown creation time: {count}/{requested} ({percent:.1f}%): {tags}".format(
                count=len(unknown_created),
                requested=len(records),
                percent=len(unknown_created) / len(records) * 100 if records else 0.0,
                tags=markdown_cell(", ".join(unknown_created)),
            )
        )
    duplicate_image_id_groups = records_with_duplicate_image_ids(records)
    known_image_ids = [record.image_id for record in records if record.present and record.image_id]
    if known_image_ids:
        rows.append(
            "Unique image IDs: {unique}/{known} present image references with IDs.".format(
                unique=len(set(known_image_ids)),
                known=len(known_image_ids),
            )
        )
    if duplicate_image_id_groups:
        rows.append(
            "Shared-image size savings: {savings:.1f} MB.".format(
                savings=round(max(0, total_bytes - deduplicated_total_bytes) / 1_000_000, 1)
            )
        )
        rows.append(
            "Duplicate image IDs: {groups}".format(
                groups=markdown_cell(format_duplicate_image_id_groups(duplicate_image_id_groups))
            )
        )
    return "\n".join(rows)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "images",
        nargs="*",
        default=[],
        help="Docker image tags to inspect. Defaults to the supported Compose backend tags.",
    )
    parser.add_argument(
        "--image",
        "--images",
        "--tag",
        "--tags",
        "--image-tag",
        "--image-tags",
        dest="option_images",
        action="append",
        help="Docker image tag to inspect. May be repeated or comma-separated.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of markdown.")
    parser.add_argument("--csv", action="store_true", help="Emit CSV rows instead of markdown.")
    parser.add_argument(
        "--format",
        "--output-format",
        dest="output_format",
        type=parse_output_format,
        help=(
            "Emit one output format: markdown, json, csv, summary-json, summary-csv, "
            "or summary-markdown."
        ),
    )
    parser.add_argument(
        "--sort",
        "--sort-by",
        dest="sort_by",
        type=parse_sort_choice,
        default="input",
        help=(
            "Order output records by input order, image tag, image size, image creation time, "
            "image age, presence, known or unknown size, known or unknown creation time, "
            "or shared image IDs."
        ),
    )
    parser.add_argument(
        "--summary-only",
        "--summary",
        "--json-summary",
        "--summary-json",
        "--json-summary-output",
        "--summary-json-output",
        dest="summary_only",
        action="store_true",
        help="Emit only the aggregate image count and size summary as JSON.",
    )
    parser.add_argument(
        "--summary-csv",
        "--csv-summary",
        "--summary-csv-output",
        "--csv-summary-output",
        dest="summary_csv",
        action="store_true",
        help="Emit only the aggregate image count and size summary as a single CSV row.",
    )
    parser.add_argument(
        "--summary-markdown",
        "--markdown-summary",
        "--summary-md",
        "--md-summary",
        "--markdown-summary-output",
        "--summary-markdown-output",
        "--summary-md-output",
        "--md-summary-output",
        "--summary-table",
        "--table-summary",
        dest="summary_markdown",
        action="store_true",
        help="Emit only the aggregate image count and size summary as a compact markdown table.",
    )
    parser.add_argument(
        "--max-size-mb",
        "--max-size",
        "--size-budget",
        "--size-budget-mb",
        "--max-image-size-mb",
        "--max-image-size",
        "--image-size-budget",
        "--image-size-budget-mb",
        type=parse_size_mb,
        dest="max_size_mb",
        help="Exit non-zero when any present image is larger than this size budget. Bare numbers are decimal megabytes.",
    )
    parser.add_argument(
        "--max-missing",
        "--max-missing-images",
        "--missing-budget",
        "--missing-image-budget",
        "--missing-images-budget",
        type=parse_nonnegative_int,
        dest="max_missing",
        help="Exit non-zero when more than this many requested images are absent.",
    )
    parser.add_argument(
        "--max-total-size-mb",
        "--max-total-size",
        "--total-budget",
        "--total-budget-mb",
        "--total-image-size-budget",
        "--max-total-image-size-mb",
        "--total-size-budget",
        "--total-image-size-budget-mb",
        type=parse_size_mb,
        dest="max_total_size_mb",
        help="Exit non-zero when all present images exceed this combined size budget. Bare numbers are decimal megabytes.",
    )
    parser.add_argument(
        "--max-deduplicated-total-size-mb",
        "--max-deduplicated-total-size",
        "--deduplicated-total-budget",
        "--deduplicated-total-budget-mb",
        "--dedupe-total-budget",
        "--dedupe-total-budget-mb",
        "--unique-total-budget",
        "--unique-total-budget-mb",
        type=parse_size_mb,
        dest="max_deduplicated_total_size_mb",
        help=(
            "Exit non-zero when unique present image IDs exceed this combined size budget. "
            "Bare numbers are decimal megabytes."
        ),
    )
    parser.add_argument(
        "--max-age-days",
        "--max-age",
        "--age-budget",
        "--age-budget-days",
        "--older-than",
        "--older-than-days",
        "--image-age-budget",
        "--image-age-budget-days",
        "--max-image-age-days",
        "--image-max-age-days",
        "--stale-image-age-days",
        "--stale-after-days",
        "--fail-on-stale-after-days",
        type=parse_age_days,
        dest="max_age_days",
        help="Exit non-zero when any present image creation timestamp is older than this age. Bare numbers are days.",
    )
    parser.add_argument(
        "--require-present",
        "--fail-on-missing",
        "--fail-on-missing-image",
        "--fail-on-missing-images",
        "--require-images-present",
        "--require-all-present",
        "--all-images-present",
        dest="require_present",
        action="store_true",
        help="Exit non-zero when any requested image is absent.",
    )
    parser.add_argument(
        "--require-any-present",
        "--fail-on-all-missing",
        "--any-image-present",
        "--require-at-least-one-present",
        dest="require_any_present",
        action="store_true",
        help="Exit non-zero when none of the requested images are present.",
    )
    parser.add_argument(
        "--require-size",
        "--fail-on-unknown-size",
        "--require-image-size",
        "--fail-on-unknown-image-size",
        "--require-known-size",
        "--require-known-image-size",
        dest="require_size",
        action="store_true",
        help="Exit non-zero when a present image does not report a Docker image size.",
    )
    parser.add_argument(
        "--require-created",
        "--fail-on-unknown-created",
        "--require-created-time",
        "--require-image-created",
        "--fail-on-unknown-created-time",
        "--fail-on-unknown-image-created",
        "--require-known-created",
        "--require-known-created-time",
        "--require-known-image-created",
        dest="require_created",
        action="store_true",
        help="Exit non-zero when a present image does not report a Docker creation timestamp.",
    )
    parser.add_argument(
        "--require-complete-metadata",
        "--require-image-metadata",
        "--require-known-metadata",
        "--fail-on-unknown-metadata",
        "--fail-on-incomplete-metadata",
        dest="require_complete_metadata",
        action="store_true",
        help="Exit non-zero when a present image does not report both Docker image size and creation timestamp.",
    )
    parser.add_argument(
        "--require-image-id",
        "--require-known-image-id",
        "--require-id",
        "--require-known-id",
        "--known-image-id",
        "--known-id",
        "--fail-on-unknown-image-id",
        "--fail-on-unknown-id",
        "--fail-on-missing-image-id",
        "--fail-on-missing-id",
        dest="require_image_id",
        action="store_true",
        help="Exit non-zero when a present image does not report a Docker image ID.",
    )
    parser.add_argument(
        "--require-unique-image-ids",
        "--fail-on-duplicate-image-ids",
        "--fail-on-shared-image-id",
        "--fail-on-shared-image-ids",
        "--fail-on-shared-image",
        "--fail-on-shared-images",
        "--require-distinct-image-ids",
        "--require-unique-images",
        "--unique-image-ids",
        "--distinct-image-ids",
        dest="require_unique_image_ids",
        action="store_true",
        help="Exit non-zero when multiple requested tags point at the same Docker image ID.",
    )
    args = parser.parse_args(argv)
    if args.output_format == "json":
        args.json = True
    elif args.output_format == "csv":
        args.csv = True
    elif args.output_format == "summary-json":
        args.summary_only = True
    elif args.output_format == "summary-csv":
        args.summary_csv = True
    elif args.output_format == "summary-markdown":
        args.summary_markdown = True
    if args.require_complete_metadata:
        args.require_size = True
        args.require_created = True
    args.images = normalize_image_args(args.images, args.option_images)
    delattr(args, "option_images")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records = sort_records(inspect_images(args.images), args.sort_by)
    if args.summary_csv:
        output = records_summary_to_csv(
            records,
            max_missing=args.max_missing,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_deduplicated_total_size_mb=args.max_deduplicated_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.summary_markdown:
        output = records_summary_to_markdown(
            records,
            max_missing=args.max_missing,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_deduplicated_total_size_mb=args.max_deduplicated_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.summary_only:
        output = records_summary_to_json(
            records,
            max_missing=args.max_missing,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_deduplicated_total_size_mb=args.max_deduplicated_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.csv:
        output = records_to_csv(records)
    else:
        output = (
            records_to_json(
                records,
                max_missing=args.max_missing,
                max_size_mb=args.max_size_mb,
                max_total_size_mb=args.max_total_size_mb,
                max_deduplicated_total_size_mb=args.max_deduplicated_total_size_mb,
                max_age_days=args.max_age_days,
            )
            if args.json
            else records_to_markdown(
                records,
                max_missing=args.max_missing,
                max_size_mb=args.max_size_mb,
                max_total_size_mb=args.max_total_size_mb,
                max_deduplicated_total_size_mb=args.max_deduplicated_total_size_mb,
                max_age_days=args.max_age_days,
            )
        )
    print(output)
    missing_records = [record for record in records if not record.present]
    any_present = any(record.present for record in records)
    unknown_size_records = [record for record in records if record.present and record.size_bytes is None]
    unknown_created_records = [
        record for record in records if record.present and parse_created_datetime(record.created) is None
    ]
    unknown_image_id_records = [record for record in records if record.present and not record.image_id]
    duplicate_image_id_groups = records_with_duplicate_image_ids(records)
    oversized_records = records_over_size_budget(records, args.max_size_mb) if args.max_size_mb is not None else []
    over_age_records = records_over_age_budget(records, args.max_age_days) if args.max_age_days is not None else []
    total_size_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    deduplicated_total_size_bytes = deduplicated_present_size_bytes(records)
    total_over_budget = (
        args.max_total_size_mb is not None and total_size_bytes > args.max_total_size_mb * 1_000_000
    )
    deduplicated_total_over_budget = (
        args.max_deduplicated_total_size_mb is not None
        and deduplicated_total_size_bytes > args.max_deduplicated_total_size_mb * 1_000_000
    )
    missing_over_budget = args.max_missing is not None and len(missing_records) > args.max_missing
    if args.require_present and missing_records:
        print(
            "Missing required images: {tags}".format(tags=", ".join(record.tag for record in missing_records)),
            file=sys.stderr,
        )
    if args.require_any_present and records and not any_present:
        print(
            "No requested images are present: {tags}".format(tags=", ".join(record.tag for record in records)),
            file=sys.stderr,
        )
    if missing_over_budget:
        print(
            "Missing image count over {budget}: {count} missing ({tags})".format(
                budget=args.max_missing,
                count=len(missing_records),
                tags=", ".join(record.tag for record in missing_records),
            ),
            file=sys.stderr,
        )
    if args.require_size and unknown_size_records:
        print(
            "Images with unknown size: {tags}".format(tags=", ".join(record.tag for record in unknown_size_records)),
            file=sys.stderr,
        )
    if args.require_created and unknown_created_records:
        print(
            "Images with unknown creation time: {tags}".format(
                tags=", ".join(record.tag for record in unknown_created_records)
            ),
            file=sys.stderr,
        )
    if args.require_image_id and unknown_image_id_records:
        print(
            "Images with unknown image ID: {tags}".format(
                tags=", ".join(record.tag for record in unknown_image_id_records)
            ),
            file=sys.stderr,
        )
    if args.require_unique_image_ids and duplicate_image_id_groups:
        print(
            "Duplicate image IDs: {groups}".format(
                groups="; ".join(
                    "{image_id}: {tags}".format(
                        image_id=group["image_id"],
                        tags=", ".join(group["tags"]),
                    )
                    for group in duplicate_image_id_groups
                )
            ),
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
    if deduplicated_total_over_budget:
        print(
            "Deduplicated total image size over {budget:.1f} MB: {total:.1f} MB".format(
                budget=args.max_deduplicated_total_size_mb,
                total=round(deduplicated_total_size_bytes / 1_000_000, 1),
            ),
            file=sys.stderr,
        )
    if over_age_records:
        print(
            "Images older than {budget:.1f} days: {tags}".format(
                budget=args.max_age_days,
                tags=", ".join(
                    f"{record.tag} ({age_days:.1f} days)"
                    for record in over_age_records
                    if (age_days := image_age_days(record)) is not None
                ),
            ),
            file=sys.stderr,
        )
    if (
        (args.require_present and missing_records)
        or (args.require_any_present and records and not any_present)
        or missing_over_budget
        or (args.require_size and unknown_size_records)
        or (args.require_created and unknown_created_records)
        or (args.require_image_id and unknown_image_id_records)
        or (args.require_unique_image_ids and duplicate_image_id_groups)
        or oversized_records
        or over_age_records
        or total_over_budget
        or deduplicated_total_over_budget
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
