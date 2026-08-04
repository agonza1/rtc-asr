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
)
SORT_CHOICE_SET = set(SORT_CHOICES)
SORT_ALIASES = {
    "largest": "size-desc",
    "largest-first": "size-desc",
    "biggest": "size-desc",
    "biggest-first": "size-desc",
    "heaviest": "size-desc",
    "heaviest-first": "size-desc",
    "smallest": "size-asc",
    "smallest-first": "size-asc",
    "lightest": "size-asc",
    "lightest-first": "size-asc",
    "newest": "created-desc",
    "newest-first": "created-desc",
    "latest": "created-desc",
    "latest-first": "created-desc",
    "oldest": "created-asc",
    "oldest-first": "created-asc",
    "earliest": "created-asc",
    "earliest-first": "created-asc",
    "freshest-age": "age-asc",
    "freshest-age-first": "age-asc",
    "youngest-age": "age-asc",
    "youngest-age-first": "age-asc",
    "stalest-age": "age-desc",
    "stalest-age-first": "age-desc",
    "oldest-age": "age-desc",
    "oldest-age-first": "age-desc",
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
    raise ValueError(f"unknown sort mode: {sort_by}")


def parse_sort_choice(value: str) -> str:
    normalized = value.lower().replace("_", "-")
    normalized = SORT_ALIASES.get(normalized, normalized)
    if normalized not in SORT_CHOICE_SET:
        choices = ", ".join(SORT_CHOICES)
        raise argparse.ArgumentTypeError(f"invalid sort mode: {value!r}; choose one of: {choices}")
    return normalized


def parse_positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a positive finite number: {value!r}") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive finite number: {value!r}")
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


def records_to_json(
    records: Iterable[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    record_list = list(records)
    summary = records_summary(
        record_list,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
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
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_age_days: float | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    present_sizes = [record.size_bytes for record in records if record.present and record.size_bytes is not None]
    total_bytes = sum(present_sizes)
    median_size_bytes = round(median(present_sizes)) if present_sizes else None
    missing = [record.tag for record in records if not record.present]
    unknown_size = [record.tag for record in records if record.present and record.size_bytes is None]
    unknown_created = [record.tag for record in records if record.present and record.created is None]
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
    records_with_created = [record for record in records if record.present and record.created]
    newest = max(records_with_created, key=lambda record: created_sort_datetime(record) or UTC_DATETIME_MIN, default=None)
    oldest = min(records_with_created, key=lambda record: created_sort_datetime(record) or UTC_DATETIME_MAX, default=None)
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
    if max_age_days is not None:
        now = now or datetime.now(UTC)
        over_age = records_over_age_budget(records, max_age_days, now=now)
        summary.update(
            {
                "image_age_budget_days": max_age_days,
                "over_age": bool(over_age),
                "over_age_count": len(over_age),
                "over_age_tags": [record.tag for record in over_age],
                "oldest_image_age_days": oldest_image_age_days(records, now=now),
            }
        )
    return summary


def records_summary_to_json(
    records: Sequence[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    return json.dumps(
        records_summary(
            records,
            max_size_mb=max_size_mb,
            max_total_size_mb=max_total_size_mb,
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
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    summary = records_summary(
        records,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
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
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
    max_age_days: float | None = None,
) -> str:
    summary = records_summary(
        records,
        max_size_mb=max_size_mb,
        max_total_size_mb=max_total_size_mb,
        max_age_days=max_age_days,
    )
    rows = [
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Requested images | {summary['requested']} |",
        f"| Present images | {summary['present']} ({summary['present_percent']:.1f}%) |",
        f"| Missing images | {summary['missing']} ({summary['missing_percent']:.1f}%) |",
        f"| Total present image size | {summary['total_size_mb']:.1f} MB |",
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
    if max_total_size_mb is not None:
        rows.append(
            "| Total image size budget | {budget:.1f} MB; {utilization} utilization; {excess:.1f} MB excess |".format(
                budget=summary["total_image_size_budget_mb"],
                utilization=format_optional_percent(summary["total_budget_utilization_percent"]),
                excess=summary["total_budget_excess_mb"],
            )
        )
    if max_age_days is not None:
        rows.append(
            "| Image age budget | {budget:.1f} days; {count} over; oldest {oldest} |".format(
                budget=summary["image_age_budget_days"],
                count=summary["over_age_count"],
                oldest=format_optional_days(summary["oldest_image_age_days"]),
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
    ages = [
        age_days
        for record in records
        if record.present and (age_days := image_age_days(record, now=now)) is not None
    ]
    return max(ages, default=None)


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


def markdown_cell(value: str | None) -> str:
    if not value:
        return ""
    return value.replace("\\", "\\\\").replace("|", "\\|")


def records_to_markdown(
    records: Sequence[ImageSizeRecord],
    max_size_mb: float | None = None,
    max_total_size_mb: float | None = None,
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
        rows.append(f"Largest present image: {largest.tag} ({largest.size_mb:.1f} MB)")
    smallest = min(
        (record for record in records if record.present and record.size_bytes is not None),
        key=lambda record: record.size_bytes or 0,
        default=None,
    )
    if smallest and smallest.size_mb is not None:
        rows.append(f"Smallest present image: {smallest.tag} ({smallest.size_mb:.1f} MB)")
    records_with_created = [record for record in records if record.present and record.created]
    newest = max(records_with_created, key=lambda record: created_sort_datetime(record) or UTC_DATETIME_MIN, default=None)
    oldest = min(records_with_created, key=lambda record: created_sort_datetime(record) or UTC_DATETIME_MAX, default=None)
    if newest:
        rows.append(f"Newest present image: {newest.tag} ({newest.created})")
    if oldest:
        rows.append(f"Oldest present image: {oldest.tag} ({oldest.created})")
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
    if max_age_days is not None:
        over_age = records_over_age_budget(records, max_age_days)
        oldest_age_days = oldest_image_age_days(records)
        rows.append(
            "Image age budget: {budget:.1f} days, {count} image{plural} older than budget.".format(
                budget=max_age_days,
                count=len(over_age),
                plural="" if len(over_age) == 1 else "s",
            )
        )
        if oldest_age_days is not None:
            rows.append(f"Oldest present image age: {oldest_age_days:.1f} days")
    if missing:
        rows.append("Missing images: {tags}".format(tags=", ".join(missing)))
    unknown_size = [record.tag for record in records if record.present and record.size_bytes is None]
    if unknown_size:
        rows.append(
            "Images with unknown size: {count}/{requested} ({percent:.1f}%): {tags}".format(
                count=len(unknown_size),
                requested=len(records),
                percent=len(unknown_size) / len(records) * 100 if records else 0.0,
                tags=", ".join(unknown_size),
            )
        )
    unknown_created = [record.tag for record in records if record.present and record.created is None]
    if unknown_created:
        rows.append(
            "Images with unknown creation time: {count}/{requested} ({percent:.1f}%): {tags}".format(
                count=len(unknown_created),
                requested=len(records),
                percent=len(unknown_created) / len(records) * 100 if records else 0.0,
                tags=", ".join(unknown_created),
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
            "Duplicate image IDs: {groups}".format(
                groups="; ".join(
                    "{image_id}: {tags}".format(
                        image_id=group["image_id"],
                        tags=", ".join(group["tags"]),
                    )
                    for group in duplicate_image_id_groups
                )
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
    parser.add_argument("--csv", action="store_true", help="Emit CSV rows instead of markdown.")
    parser.add_argument(
        "--sort",
        "--sort-by",
        dest="sort_by",
        type=parse_sort_choice,
        default="input",
        help="Order output records by input order, image tag, image size, image creation time, or image age.",
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
        "--summary-csv",
        "--csv-summary",
        dest="summary_csv",
        action="store_true",
        help="Emit only the aggregate image count and size summary as a single CSV row.",
    )
    parser.add_argument(
        "--summary-markdown",
        "--markdown-summary",
        dest="summary_markdown",
        action="store_true",
        help="Emit only the aggregate image count and size summary as a compact markdown table.",
    )
    parser.add_argument(
        "--max-size-mb",
        "--max-image-size-mb",
        "--image-size-budget-mb",
        type=parse_size_mb,
        dest="max_size_mb",
        help="Exit non-zero when any present image is larger than this size budget. Bare numbers are decimal megabytes.",
    )
    parser.add_argument(
        "--max-total-size-mb",
        "--total-image-size-budget-mb",
        type=parse_size_mb,
        dest="max_total_size_mb",
        help="Exit non-zero when all present images exceed this combined size budget. Bare numbers are decimal megabytes.",
    )
    parser.add_argument(
        "--max-age-days",
        "--image-age-budget-days",
        type=parse_positive_float,
        dest="max_age_days",
        help="Exit non-zero when any present image creation timestamp is older than this many days.",
    )
    parser.add_argument(
        "--require-present",
        "--fail-on-missing",
        dest="require_present",
        action="store_true",
        help="Exit non-zero when any requested image is absent.",
    )
    parser.add_argument(
        "--require-any-present",
        "--fail-on-all-missing",
        dest="require_any_present",
        action="store_true",
        help="Exit non-zero when none of the requested images are present.",
    )
    parser.add_argument(
        "--require-size",
        "--fail-on-unknown-size",
        dest="require_size",
        action="store_true",
        help="Exit non-zero when a present image does not report a Docker image size.",
    )
    parser.add_argument(
        "--require-created",
        "--fail-on-unknown-created",
        dest="require_created",
        action="store_true",
        help="Exit non-zero when a present image does not report a Docker creation timestamp.",
    )
    parser.add_argument(
        "--require-unique-image-ids",
        "--fail-on-duplicate-image-ids",
        dest="require_unique_image_ids",
        action="store_true",
        help="Exit non-zero when multiple requested tags point at the same Docker image ID.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    records = sort_records(inspect_images(args.images), args.sort_by)
    if args.summary_csv:
        output = records_summary_to_csv(
            records,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.summary_markdown:
        output = records_summary_to_markdown(
            records,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.summary_only:
        output = records_summary_to_json(
            records,
            max_size_mb=args.max_size_mb,
            max_total_size_mb=args.max_total_size_mb,
            max_age_days=args.max_age_days,
        )
    elif args.csv:
        output = records_to_csv(records)
    else:
        output = (
            records_to_json(
                records,
                max_size_mb=args.max_size_mb,
                max_total_size_mb=args.max_total_size_mb,
                max_age_days=args.max_age_days,
            )
            if args.json
            else records_to_markdown(
                records,
                max_size_mb=args.max_size_mb,
                max_total_size_mb=args.max_total_size_mb,
                max_age_days=args.max_age_days,
            )
        )
    print(output)
    missing_records = [record for record in records if not record.present]
    any_present = any(record.present for record in records)
    unknown_size_records = [record for record in records if record.present and record.size_bytes is None]
    unknown_created_records = [record for record in records if record.present and record.created is None]
    duplicate_image_id_groups = records_with_duplicate_image_ids(records)
    oversized_records = records_over_size_budget(records, args.max_size_mb) if args.max_size_mb is not None else []
    over_age_records = records_over_age_budget(records, args.max_age_days) if args.max_age_days is not None else []
    total_size_bytes = sum(record.size_bytes or 0 for record in records if record.present)
    total_over_budget = (
        args.max_total_size_mb is not None and total_size_bytes > args.max_total_size_mb * 1_000_000
    )
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
        or (args.require_size and unknown_size_records)
        or (args.require_created and unknown_created_records)
        or (args.require_unique_image_ids and duplicate_image_id_groups)
        or oversized_records
        or over_age_records
        or total_over_budget
    ):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
