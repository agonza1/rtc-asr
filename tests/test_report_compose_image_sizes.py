from __future__ import annotations

import argparse
import csv
import io
import json
import subprocess
from datetime import UTC, datetime
from typing import Any

import pytest

from scripts import report_compose_image_sizes as reporter


def test_records_to_markdown_reports_present_and_missing_images() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="realtime-asr:faster-whisper-cpu",
            image_id="abcdef123456",
            size_bytes=1_234_567_890,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:qwen-cpu",
            image_id=None,
            size_bytes=None,
            created=None,
            present=False,
        ),
    ]

    markdown = reporter.records_to_markdown(records)

    assert "| realtime-asr:faster-whisper-cpu | yes | 1234.6 | abcdef123456 | 2026-07-31T19:00:00Z |" in markdown
    assert "| realtime-asr:qwen-cpu | no |  |  |  |" in markdown
    assert "| Total present images |  | 1234.6 |  |  |" in markdown
    assert "Summary: 1/2 images present (50.0%), 1 missing." in markdown
    assert "Largest present image: realtime-asr:faster-whisper-cpu (1234.6 MB)" in markdown
    assert "Smallest present image: realtime-asr:faster-whisper-cpu (1234.6 MB)" in markdown
    assert "Newest present image: realtime-asr:faster-whisper-cpu (2026-07-31T19:00:00Z)" in markdown
    assert "Oldest present image: realtime-asr:faster-whisper-cpu (2026-07-31T19:00:00Z)" in markdown
    assert "Average present image size: 1234.6 MB" in markdown
    assert "Median present image size: 1234.6 MB" in markdown
    assert "Present image size range: 0.0 MB" in markdown
    assert "Missing images: realtime-asr:qwen-cpu" in markdown


def test_records_to_markdown_escapes_pipe_cells() -> None:
    record = reporter.ImageSizeRecord(
        tag="registry.local/realtime-asr:branch|preview",
        image_id="sha|preview",
        size_bytes=100_000_000,
        created="2026-07-31T19:00:00Z|main",
        present=True,
    )

    markdown = reporter.records_to_markdown([record])

    assert "| registry.local/realtime-asr:branch\\|preview | yes | 100.0 | sha\\|preview | 2026-07-31T19:00:00Z\\|main |" in markdown


def test_records_to_json_includes_bytes_decimal_megabytes_and_age(monkeypatch: pytest.MonkeyPatch) -> None:
    record = reporter.ImageSizeRecord(
        tag="realtime-asr:parakeet-nemo-cpu",
        image_id="fedcba654321",
        size_bytes=987_654_321,
        created="2026-07-31T19:00:00Z",
        present=True,
    )
    monkeypatch.setattr(reporter, "image_age_days", lambda record, now=None: 2.4)

    payload = json.loads(reporter.records_to_json([record]))

    assert payload == [
        {
            "tag": "realtime-asr:parakeet-nemo-cpu",
            "present": True,
            "image_id": "fedcba654321",
            "size_bytes": 987_654_321,
            "size_mb": 987.7,
            "created": "2026-07-31T19:00:00Z",
            "age_days": 2.4,
        },
        {
            "summary": {
                "average_present_size_bytes": 987_654_321,
                "average_present_size_mb": 987.7,
                "median_present_size_bytes": 987_654_321,
                "median_present_size_mb": 987.7,
                "range_present_size_bytes": 0,
                "range_present_size_mb": 0.0,
                "missing": 0,
                "missing_percent": 0.0,
                "missing_tags": [],
                "present": 1,
                "present_percent": 100.0,
                "requested": 1,
                "unknown_size": 0,
                "unknown_size_percent": 0.0,
                "unknown_size_tags": [],
                "unknown_created": 0,
                "unknown_created_percent": 0.0,
                "unknown_created_tags": [],
                "total_size_bytes": 987_654_321,
                "total_size_mb": 987.7,
                "largest_present_tag": "realtime-asr:parakeet-nemo-cpu",
                "largest_present_size_bytes": 987_654_321,
                "largest_present_size_mb": 987.7,
                "smallest_present_tag": "realtime-asr:parakeet-nemo-cpu",
                "smallest_present_size_bytes": 987_654_321,
                "smallest_present_size_mb": 987.7,
                "newest_present_tag": "realtime-asr:parakeet-nemo-cpu",
                "newest_present_created": "2026-07-31T19:00:00Z",
                "oldest_present_tag": "realtime-asr:parakeet-nemo-cpu",
                "oldest_present_created": "2026-07-31T19:00:00Z",
                "duplicate_image_ids": 0,
                "duplicate_image_id_groups": [],
                "known_image_ids": 1,
                "unique_image_ids": 1,
                "duplicate_image_id_tag_refs": 0,
            }
        },
    ]


def test_records_to_csv_emits_tabular_image_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="realtime-asr:faster-whisper-cpu",
            image_id="abcdef123456",
            size_bytes=1_234_567_890,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:qwen-cpu",
            image_id=None,
            size_bytes=None,
            created=None,
            present=False,
        ),
    ]
    monkeypatch.setattr(
        reporter,
        "image_age_days",
        lambda record, now=None: 2.4 if record.created else None,
    )

    assert reporter.records_to_csv(records).splitlines() == [
        "tag,present,image_id,size_bytes,size_mb,created,age_days",
        "realtime-asr:faster-whisper-cpu,yes,abcdef123456,1234567890,1234.6,2026-07-31T19:00:00Z,2.4",
        "realtime-asr:qwen-cpu,no,,,,,",
    ]


def test_records_summary_to_json_emits_only_aggregate_fields() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="realtime-asr:faster-whisper-cpu",
            image_id="abcdef123456",
            size_bytes=1_234_567_890,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:qwen-cpu",
            image_id=None,
            size_bytes=None,
            created=None,
            present=False,
        ),
    ]

    assert json.loads(reporter.records_summary_to_json(records)) == {
        "average_present_size_bytes": 1_234_567_890,
        "average_present_size_mb": 1234.6,
        "median_present_size_bytes": 1_234_567_890,
        "median_present_size_mb": 1234.6,
        "range_present_size_bytes": 0,
        "range_present_size_mb": 0.0,
        "missing": 1,
        "missing_percent": 50.0,
        "missing_tags": ["realtime-asr:qwen-cpu"],
        "present": 1,
        "present_percent": 50.0,
        "requested": 2,
        "unknown_size": 0,
        "unknown_size_percent": 0.0,
        "unknown_size_tags": [],
        "unknown_created": 0,
        "unknown_created_percent": 0.0,
        "unknown_created_tags": [],
        "total_size_bytes": 1_234_567_890,
        "total_size_mb": 1234.6,
        "largest_present_tag": "realtime-asr:faster-whisper-cpu",
        "largest_present_size_bytes": 1_234_567_890,
        "largest_present_size_mb": 1234.6,
        "smallest_present_tag": "realtime-asr:faster-whisper-cpu",
        "smallest_present_size_bytes": 1_234_567_890,
        "smallest_present_size_mb": 1234.6,
        "newest_present_tag": "realtime-asr:faster-whisper-cpu",
        "newest_present_created": "2026-07-31T19:00:00Z",
        "oldest_present_tag": "realtime-asr:faster-whisper-cpu",
        "oldest_present_created": "2026-07-31T19:00:00Z",
        "duplicate_image_ids": 0,
        "duplicate_image_id_groups": [],
        "known_image_ids": 1,
        "unique_image_ids": 1,
        "duplicate_image_id_tag_refs": 0,
    }


def test_records_summary_to_csv_emits_single_aggregate_row() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="first:image",
            image_id="shared123",
            size_bytes=100_000_000,
            created=None,
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="second:image",
            image_id="shared123",
            size_bytes=300_000_000,
            created=None,
            present=True,
        ),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    rows = list(csv.DictReader(io.StringIO(reporter.records_summary_to_csv(records))))

    assert len(rows) == 1
    assert rows[0]["requested"] == "3"
    assert rows[0]["present"] == "2"
    assert rows[0]["missing_tags"] == '["missing:image"]'
    assert rows[0]["duplicate_image_id_groups"] == '[{"image_id": "shared123", "tags": ["first:image", "second:image"]}]'
    assert rows[0]["total_size_mb"] == "400.0"


def test_records_summary_to_markdown_emits_compact_aggregate_table() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="first:image",
            image_id="shared123",
            size_bytes=100_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="second:image",
            image_id="shared123",
            size_bytes=300_000_000,
            created=None,
            present=True,
        ),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    markdown = reporter.records_summary_to_markdown(records, max_size_mb=200.0, max_total_size_mb=350.0)

    assert "| Metric | Value |" in markdown
    assert "| Present images | 2 (66.7%) |" in markdown
    assert "| Missing images | 1 (33.3%) |" in markdown
    assert "| Total present image size | 400.0 MB |" in markdown
    assert "| Largest present image | second:image (300.0 MB) |" in markdown
    assert "| Unknown creation times | 1: second:image |" in markdown
    assert "| Per-image size budget | 200.0 MB; 1 over; 100.0 MB excess |" in markdown
    assert "| Total image size budget | 350.0 MB; 114.3% utilization; 50.0 MB excess |" in markdown
    assert "| Known image ID references | 2 |" in markdown
    assert "| Unique image IDs | 1 |" in markdown
    assert "| Duplicate image ID tag refs | 2 |" in markdown
    assert "| Missing tags | missing:image |" in markdown
    assert "| Tags over size budget | second:image |" in markdown
    assert "| Duplicate groups | shared123: first:image, second:image |" in markdown


def test_records_summary_reports_average_present_image_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=300_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)

    assert summary["average_present_size_bytes"] == 200_000_000
    assert summary["average_present_size_mb"] == 200.0


def test_records_summary_reports_median_present_image_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="medium:image", image_id="medium", size_bytes=250_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=300_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["median_present_size_bytes"] == 250_000_000
    assert summary["median_present_size_mb"] == 250.0
    assert "Median present image size: 250.0 MB" in markdown


def test_records_summary_reports_present_image_size_range() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=300_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=None, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["range_present_size_bytes"] == 200_000_000
    assert summary["range_present_size_mb"] == 200.0
    assert "Present image size range: 200.0 MB" in markdown


def test_records_summary_reports_even_count_median_present_image_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=300_000_000, created=None, present=True),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["median_present_size_bytes"] == 200_000_000
    assert summary["median_present_size_mb"] == 200.0
    assert "Median present image size: 200.0 MB" in markdown


def test_records_summary_reports_smallest_present_image_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=300_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["smallest_present_tag"] == "small:image"
    assert summary["smallest_present_size_bytes"] == 100_000_000
    assert summary["smallest_present_size_mb"] == 100.0
    assert "Smallest present image: small:image (100.0 MB)" in markdown


def test_records_summary_reports_newest_and_oldest_present_images() -> None:
    records = [
        reporter.ImageSizeRecord(tag="old:image", image_id="old", size_bytes=100_000_000, created="2026-07-30T19:00:00Z", present=True),
        reporter.ImageSizeRecord(tag="new:image", image_id="new", size_bytes=300_000_000, created="2026-07-31T19:00:00Z", present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=200_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created="2026-08-01T19:00:00Z", present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["newest_present_tag"] == "new:image"
    assert summary["newest_present_created"] == "2026-07-31T19:00:00Z"
    assert summary["oldest_present_tag"] == "old:image"
    assert summary["oldest_present_created"] == "2026-07-30T19:00:00Z"
    assert "Newest present image: new:image (2026-07-31T19:00:00Z)" in markdown
    assert "Oldest present image: old:image (2026-07-30T19:00:00Z)" in markdown


def test_records_summary_and_markdown_order_created_times_by_instant_not_raw_string() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="early-offset:image",
            image_id="early",
            size_bytes=100_000_000,
            created="2026-07-31T20:00:00+02:00",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="later-zulu:image",
            image_id="later",
            size_bytes=200_000_000,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["newest_present_tag"] == "later-zulu:image"
    assert summary["oldest_present_tag"] == "early-offset:image"
    assert "Newest present image: later-zulu:image (2026-07-31T19:00:00Z)" in markdown
    assert "Oldest present image: early-offset:image (2026-07-31T20:00:00+02:00)" in markdown


def test_parse_created_datetime_accepts_docker_nanosecond_precision() -> None:
    parsed = reporter.parse_created_datetime("2026-07-31T19:00:00.123456789Z")

    assert parsed == datetime(2026, 7, 31, 19, 0, 0, 123456, tzinfo=UTC)


def test_image_age_days_accepts_docker_nanosecond_precision() -> None:
    record = reporter.ImageSizeRecord(
        tag="fresh:image",
        image_id="fresh",
        size_bytes=100_000_000,
        created="2026-07-31T12:00:00.987654321Z",
        present=True,
    )

    assert reporter.image_age_days(record, now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC)) == 1.0


def test_records_summary_reports_present_images_with_unknown_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="known:image", image_id="known", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=None, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["unknown_size"] == 1
    assert summary["unknown_size_percent"] == 33.3
    assert summary["unknown_size_tags"] == ["unknown:image"]
    assert "Images with unknown size: 1/3 (33.3%): unknown:image" in markdown


def test_records_summary_reports_present_images_with_unknown_creation_time() -> None:
    records = [
        reporter.ImageSizeRecord(tag="known:image", image_id="known", size_bytes=100_000_000, created="2026-07-31T19:00:00Z", present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=200_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["unknown_created"] == 1
    assert summary["unknown_created_percent"] == 33.3
    assert summary["unknown_created_tags"] == ["unknown:image"]
    assert "Images with unknown creation time: 1/3 (33.3%): unknown:image" in markdown


def test_records_summary_reports_duplicate_image_ids() -> None:
    records = [
        reporter.ImageSizeRecord(tag="first:image", image_id="shared123", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="second:image", image_id="shared123", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unique:image", image_id="unique123", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["duplicate_image_ids"] == 1
    assert summary["duplicate_image_id_groups"] == [
        {"image_id": "shared123", "tags": ["first:image", "second:image"]}
    ]
    assert summary["known_image_ids"] == 3
    assert summary["unique_image_ids"] == 2
    assert summary["duplicate_image_id_tag_refs"] == 2
    assert "Unique image IDs: 2/3 present image references with IDs." in markdown
    assert "Duplicate image IDs: shared123: first:image, second:image" in markdown


def test_records_summary_reports_size_budget_status() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records, max_size_mb=200.0)

    assert summary["image_size_budget_mb"] == 200.0
    assert summary["largest_image_budget_utilization_percent"] == 100.5
    assert summary["over_budget"] is True
    assert summary["over_budget_count"] == 1
    assert summary["over_budget_tags"] == ["large:image"]
    assert summary["over_budget_excess_bytes"] == 1_000_000
    assert summary["over_budget_excess_mb"] == 1.0


def test_records_summary_reports_total_size_budget_status() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records, max_total_size_mb=399.0)

    assert summary["total_image_size_budget_mb"] == 399.0
    assert summary["total_budget_utilization_percent"] == 100.3
    assert summary["total_over_budget"] is True
    assert summary["total_budget_excess_bytes"] == 1_000_000
    assert summary["total_budget_excess_mb"] == 1.0


def test_records_summary_reports_image_age_budget_status() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=199_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=201_000_000,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=1, created=None, present=True),
        reporter.ImageSizeRecord(
            tag="missing:image",
            image_id=None,
            size_bytes=None,
            created="2026-07-01T12:00:00Z",
            present=False,
        ),
    ]

    summary = reporter.records_summary(
        records,
        max_age_days=14.0,
        now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
    )

    assert summary["image_age_budget_days"] == 14.0
    assert summary["over_age"] is True
    assert summary["over_age_count"] == 1
    assert summary["over_age_tags"] == ["old:image"]
    assert summary["freshest_image_age_tag"] == "fresh:image"
    assert summary["freshest_image_age_days"] == 1.0
    assert summary["oldest_image_age_tag"] == "old:image"
    assert summary["oldest_image_age_days"] == 17.0


def test_records_to_markdown_reports_size_budget_status() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
    ]

    markdown = reporter.records_to_markdown(records, max_size_mb=200.0)

    assert "Image size budget: 200.0 MB, 1 image over budget, 1.0 MB total excess." in markdown
    assert "Largest image budget utilization: 100.5%" in markdown


def test_records_to_markdown_reports_total_size_budget_status() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
    ]

    markdown = reporter.records_to_markdown(records, max_total_size_mb=400.0)

    assert "Total image size budget: 400.0 MB, current total 400.0 MB, 0.0 MB over." in markdown
    assert "Total image size budget utilization: 100.0%" in markdown


def test_records_to_markdown_reports_image_age_budget_status(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=199_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=201_000_000,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
    ]
    monkeypatch.setattr(reporter, "image_age_days", lambda record, now=None: 1.0 if record.tag == "fresh:image" else 17.0)

    markdown = reporter.records_to_markdown(records, max_age_days=14.0)

    assert "Image age budget: 14.0 days, 1 image older than budget." in markdown
    assert "Freshest present image age: fresh:image (1.0 days)" in markdown
    assert "Oldest present image age: 17.0 days" in markdown


def test_records_summary_to_markdown_reports_oldest_image_age_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=199_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=201_000_000,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
    ]
    monkeypatch.setattr(reporter, "image_age_days", lambda record, now=None: 1.0 if record.tag == "fresh:image" else 17.0)

    markdown = reporter.records_summary_to_markdown(records, max_age_days=14.0)

    assert "| Image age budget | 14.0 days; 1 over; freshest fresh:image (1.0 days); oldest old:image (17.0 days) |" in markdown


def test_freshest_image_age_helpers_ignore_missing_and_unknown_creation_times() -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    records = [
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=199_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=201_000_000,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=1, created=None, present=True),
        reporter.ImageSizeRecord(
            tag="missing:image",
            image_id=None,
            size_bytes=None,
            created="2026-08-01T12:00:00Z",
            present=False,
        ),
    ]

    assert reporter.freshest_image_age_record(records, now=now) == records[0]
    assert reporter.freshest_image_age_days(records, now=now) == 1.0


def test_sort_records_orders_by_tag_size_and_created() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="realtime-asr:qwen-cpu",
            image_id="qwen",
            size_bytes=200,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:faster-whisper-cpu",
            image_id="faster",
            size_bytes=100,
            created="2026-07-30T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:missing",
            image_id=None,
            size_bytes=None,
            created=None,
            present=False,
        ),
    ]

    assert [record.tag for record in reporter.sort_records(records, "tag")] == [
        "realtime-asr:faster-whisper-cpu",
        "realtime-asr:missing",
        "realtime-asr:qwen-cpu",
    ]
    assert [record.tag for record in reporter.sort_records(records, "size-desc")] == [
        "realtime-asr:qwen-cpu",
        "realtime-asr:faster-whisper-cpu",
        "realtime-asr:missing",
    ]
    assert [record.tag for record in reporter.sort_records(records, "size-asc")] == [
        "realtime-asr:faster-whisper-cpu",
        "realtime-asr:qwen-cpu",
        "realtime-asr:missing",
    ]
    assert [record.tag for record in reporter.sort_records(records, "created-asc")] == [
        "realtime-asr:faster-whisper-cpu",
        "realtime-asr:qwen-cpu",
        "realtime-asr:missing",
    ]
    assert [record.tag for record in reporter.sort_records(records, "created-desc")] == [
        "realtime-asr:qwen-cpu",
        "realtime-asr:faster-whisper-cpu",
        "realtime-asr:missing",
    ]


def test_sort_records_orders_created_offsets_by_instant() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="early-offset:image",
            image_id="early",
            size_bytes=100,
            created="2026-07-31T20:00:00+02:00",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="later-zulu:image",
            image_id="later",
            size_bytes=200,
            created="2026-07-31T19:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="unknown:image",
            image_id="unknown",
            size_bytes=300,
            created=None,
            present=True,
        ),
    ]

    assert [record.tag for record in reporter.sort_records(records, "created-asc")] == [
        "early-offset:image",
        "later-zulu:image",
        "unknown:image",
    ]
    assert [record.tag for record in reporter.sort_records(records, "created-desc")] == [
        "later-zulu:image",
        "early-offset:image",
        "unknown:image",
    ]


def test_sort_records_orders_by_image_age(monkeypatch: pytest.MonkeyPatch) -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=200,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=100,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="unknown:image",
            image_id="unknown",
            size_bytes=300,
            created=None,
            present=True,
        ),
    ]
    monkeypatch.setattr(
        reporter,
        "image_age_days",
        lambda record, now=None: {"old:image": 17.0, "fresh:image": 1.0}.get(record.tag),
    )

    assert [record.tag for record in reporter.sort_records(records, "age-asc")] == [
        "fresh:image",
        "old:image",
        "unknown:image",
    ]
    assert [record.tag for record in reporter.sort_records(records, "age-desc")] == [
        "old:image",
        "fresh:image",
        "unknown:image",
    ]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("age-desc", "age-desc"),
        ("AGE-DESC", "age-desc"),
        ("age_desc", "age-desc"),
        ("created_asc", "created-asc"),
        ("SIZE-DESC", "size-desc"),
        ("largest", "size-desc"),
        ("heaviest_first", "size-desc"),
        ("smallest", "size-asc"),
        ("lightest-first", "size-asc"),
        ("newest", "created-desc"),
        ("latest_first", "created-desc"),
        ("oldest", "created-asc"),
        ("earliest-first", "created-asc"),
        ("freshest_age", "age-asc"),
        ("youngest-age-first", "age-asc"),
        ("stalest_age", "age-desc"),
        ("oldest-age-first", "age-desc"),
    ],
)
def test_parse_sort_choice_accepts_case_and_aliases(value: str, expected: str) -> None:
    assert reporter.parse_sort_choice(value) == expected


@pytest.mark.parametrize("value", ["1", "1.5", "0.001"])
def test_parse_positive_float_accepts_positive_finite_values(value: str) -> None:
    assert reporter.parse_positive_float(value) == float(value)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not-a-number"])
def test_parse_positive_float_rejects_nonpositive_nonfinite_and_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="must be a positive finite number"):
        reporter.parse_positive_float(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("250", 250.0),
        ("250MB", 250.0),
        ("1.5G", 1500.0),
        ("512 MiB", 536.870912),
        ("1_000 KB", 1.0),
    ],
)
def test_parse_size_mb_accepts_readable_size_units(value: str, expected: float) -> None:
    assert reporter.parse_size_mb(value) == expected


@pytest.mark.parametrize("value", ["0", "-1MB", "nan", "inf", "not-a-number"])
def test_parse_size_mb_rejects_nonpositive_nonfinite_and_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        reporter.parse_size_mb(value)


def test_records_over_size_budget_ignores_missing_and_unknown_sizes() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=None, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    assert reporter.records_over_size_budget(records, 200.0) == [records[1]]


def test_records_over_age_budget_ignores_missing_and_unknown_creation_times() -> None:
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    records = [
        reporter.ImageSizeRecord(
            tag="fresh:image",
            image_id="fresh",
            size_bytes=199_000_000,
            created="2026-07-31T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="old:image",
            image_id="old",
            size_bytes=201_000_000,
            created="2026-07-15T12:00:00Z",
            present=True,
        ),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=1, created=None, present=True),
        reporter.ImageSizeRecord(
            tag="missing:image",
            image_id=None,
            size_bytes=None,
            created="2026-07-01T12:00:00Z",
            present=False,
        ),
    ]

    assert reporter.records_over_age_budget(records, 14.0, now=now) == [records[1]]


def test_inspect_images_records_missing_images(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="not found")

    monkeypatch.setattr(reporter.subprocess, "run", fake_run)

    assert reporter.inspect_images(["missing:image"]) == [
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False)
    ]


def test_inspect_images_normalizes_docker_inspect_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        payload = [
            {
                "Id": "sha256:abcdef1234567890",
                "Size": 4321000000,
                "Created": "2026-07-31T19:00:00Z",
            }
        ]
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(reporter.subprocess, "run", fake_run)

    assert reporter.inspect_images(["present:image"]) == [
        reporter.ImageSizeRecord(
            tag="present:image",
            image_id="abcdef123456",
            size_bytes=4321000000,
            created="2026-07-31T19:00:00Z",
            present=True,
        )
    ]


def test_main_allows_missing_images_unless_required(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id=None, size_bytes=None, created=None, present=False)
        ],
    )

    assert reporter.main(["missing:image"]) == 0
    assert "| missing:image | no |" in capsys.readouterr().out

    assert reporter.main(["--require-present", "missing:image"]) == 1
    captured = capsys.readouterr()
    assert "Missing required images: missing:image" in captured.err


def test_main_summary_only_emits_summary_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(
                tag=images[0],
                image_id="abcdef123456",
                size_bytes=100_000_000,
                created=None,
                present=True,
            )
        ],
    )

    assert reporter.main(["--summary-only", "present:image"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "average_present_size_bytes": 100_000_000,
        "average_present_size_mb": 100.0,
        "median_present_size_bytes": 100_000_000,
        "median_present_size_mb": 100.0,
        "range_present_size_bytes": 0,
        "range_present_size_mb": 0.0,
        "missing": 0,
        "missing_percent": 0.0,
        "missing_tags": [],
        "present": 1,
        "present_percent": 100.0,
        "requested": 1,
        "unknown_size": 0,
        "unknown_size_percent": 0.0,
        "unknown_size_tags": [],
        "unknown_created": 1,
        "unknown_created_percent": 100.0,
        "unknown_created_tags": ["present:image"],
        "total_size_bytes": 100_000_000,
        "total_size_mb": 100.0,
        "largest_present_tag": "present:image",
        "largest_present_size_bytes": 100_000_000,
        "largest_present_size_mb": 100.0,
        "smallest_present_tag": "present:image",
        "smallest_present_size_bytes": 100_000_000,
        "smallest_present_size_mb": 100.0,
        "newest_present_tag": None,
        "newest_present_created": None,
        "oldest_present_tag": None,
        "oldest_present_created": None,
        "duplicate_image_ids": 0,
        "duplicate_image_id_groups": [],
        "known_image_ids": 1,
        "unique_image_ids": 1,
        "duplicate_image_id_tag_refs": 0,
    }


def test_main_summary_csv_emits_summary_row(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(
                tag=images[0],
                image_id="abcdef123456",
                size_bytes=100_000_000,
                created=None,
                present=True,
            )
        ],
    )

    assert reporter.main(["--summary-csv", "present:image"]) == 0

    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 1
    assert rows[0]["present"] == "1"
    assert rows[0]["total_size_mb"] == "100.0"
    assert rows[0]["unknown_created_tags"] == '["present:image"]'


def test_main_summary_markdown_emits_summary_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(
                tag=images[0],
                image_id="abcdef123456",
                size_bytes=100_000_000,
                created=None,
                present=True,
            )
        ],
    )

    assert reporter.main(["--summary-markdown", "present:image"]) == 0

    assert "| Present images | 1 (100.0%) |" in capsys.readouterr().out


def test_parse_args_accepts_json_summary_aliases() -> None:
    assert reporter.parse_args(["--json-summary"]).summary_only is True
    assert reporter.parse_args(["--summary-json"]).summary_only is True


def test_parse_args_accepts_csv_summary_aliases() -> None:
    assert reporter.parse_args(["--summary-csv"]).summary_csv is True
    assert reporter.parse_args(["--csv-summary"]).summary_csv is True


def test_parse_args_accepts_markdown_summary_aliases() -> None:
    assert reporter.parse_args(["--summary-markdown"]).summary_markdown is True
    assert reporter.parse_args(["--markdown-summary"]).summary_markdown is True


def test_parse_args_accepts_fail_on_missing_alias() -> None:
    assert reporter.parse_args(["--fail-on-missing"]).require_present is True


def test_parse_args_accepts_fail_on_all_missing_alias() -> None:
    assert reporter.parse_args(["--fail-on-all-missing"]).require_any_present is True


def test_parse_args_accepts_fail_on_unknown_size_alias() -> None:
    assert reporter.parse_args(["--fail-on-unknown-size"]).require_size is True


def test_parse_args_accepts_fail_on_unknown_created_alias() -> None:
    assert reporter.parse_args(["--fail-on-unknown-created"]).require_created is True


def test_parse_args_accepts_fail_on_duplicate_image_ids_alias() -> None:
    assert reporter.parse_args(["--fail-on-duplicate-image-ids"]).require_unique_image_ids is True


def test_main_csv_flag_emits_csv(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(
                tag=images[0],
                image_id="abcdef123456",
                size_bytes=100_000_000,
                created=None,
                present=True,
            )
        ],
    )

    assert reporter.main(["--csv", "present:image"]) == 0

    assert capsys.readouterr().out.splitlines() == [
        "tag,present,image_id,size_bytes,size_mb,created,age_days",
        "present:image,yes,abcdef123456,100000000,100.0,,",
    ]


def test_main_applies_sort_order_before_rendering(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=10, created=None, present=True),
            reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=20, created=None, present=True),
        ],
    )

    assert reporter.main(["--sort-by", "size-desc", "small:image", "large:image"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[2].startswith("| large:image |")
    assert lines[3].startswith("| small:image |")

    assert reporter.main(["--sort-by", "size-asc", "small:image", "large:image"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[2].startswith("| small:image |")
    assert lines[3].startswith("| large:image |")

    assert reporter.main(["--sort", "SIZE-DESC", "small:image", "large:image"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[2].startswith("| large:image |")
    assert lines[3].startswith("| small:image |")


def test_main_fails_when_present_image_exceeds_size_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id="large", size_bytes=250_000_001, created=None, present=True)
        ],
    )

    assert reporter.main(["--max-size-mb", "250", "large:image"]) == 1
    assert "Images over 250.0 MB: large:image (250.0 MB)" in capsys.readouterr().err
    assert reporter.main(["--max-size-mb", "251", "large:image"]) == 0


@pytest.mark.parametrize(
    ("option", "expected_attr"),
    [
        ("--max-image-size-mb", "max_size_mb"),
        ("--image-size-budget-mb", "max_size_mb"),
        ("--total-image-size-budget-mb", "max_total_size_mb"),
        ("--image-age-budget-days", "max_age_days"),
        ("--max-image-age-days", "max_age_days"),
        ("--image-max-age-days", "max_age_days"),
        ("--stale-image-age-days", "max_age_days"),
        ("--stale-after-days", "max_age_days"),
        ("--fail-on-stale-after-days", "max_age_days"),
    ],
)
def test_parse_args_accepts_image_budget_aliases(option: str, expected_attr: str) -> None:
    args = reporter.parse_args([option, "42"])

    assert getattr(args, expected_attr) == 42.0


def test_parse_args_accepts_readable_image_size_budgets() -> None:
    args = reporter.parse_args(["--max-size-mb", "1.5G", "--max-total-size-mb", "2GiB"])

    assert args.max_size_mb == 1500.0
    assert args.max_total_size_mb == 2147.483648


def test_main_fails_when_present_images_exceed_total_size_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
            reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_001, created=None, present=True),
        ],
    )

    assert reporter.main(["--max-total-size-mb", "400", "small:image", "large:image"]) == 1
    assert "Total image size over 400.0 MB: 400.0 MB" in capsys.readouterr().err
    assert reporter.main(["--max-total-size-mb", "401", "small:image", "large:image"]) == 0


def test_main_fails_when_present_image_size_is_required_but_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id="unknown", size_bytes=None, created=None, present=True)
        ],
    )

    assert reporter.main(["--require-size", "unknown:image"]) == 1
    assert "Images with unknown size: unknown:image" in capsys.readouterr().err
    assert reporter.main(["unknown:image"]) == 0


def test_main_fails_when_present_image_creation_time_is_required_but_unknown(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id="unknown", size_bytes=100_000_000, created=None, present=True)
        ],
    )

    assert reporter.main(["--require-created", "unknown:image"]) == 1
    assert "Images with unknown creation time: unknown:image" in capsys.readouterr().err
    assert reporter.main(["unknown:image"]) == 0


def test_main_fails_when_any_present_image_is_required_but_all_are_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=image, image_id=None, size_bytes=None, created=None, present=False)
            for image in images
        ],
    )

    assert reporter.main(["--require-any-present", "missing-one:image", "missing-two:image"]) == 1
    assert "No requested images are present: missing-one:image, missing-two:image" in capsys.readouterr().err
    assert reporter.main(["missing-one:image", "missing-two:image"]) == 0


def test_main_fails_when_unique_image_ids_are_required_but_tags_share_an_image(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(
                tag="first:image",
                image_id="shared123",
                size_bytes=100_000_000,
                created=None,
                present=True,
            ),
            reporter.ImageSizeRecord(
                tag="second:image",
                image_id="shared123",
                size_bytes=100_000_000,
                created=None,
                present=True,
            ),
        ],
    )

    assert reporter.main(["--require-unique-image-ids", "first:image", "second:image"]) == 1
    assert "Duplicate image IDs: shared123: first:image, second:image" in capsys.readouterr().err
    assert reporter.main(["first:image", "second:image"]) == 0


def test_main_summary_only_includes_size_budget_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id="large", size_bytes=250_000_001, created=None, present=True)
        ],
    )

    assert reporter.main(["--summary-only", "--max-size-mb", "250", "large:image"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["image_size_budget_mb"] == 250.0
    assert payload["largest_image_budget_utilization_percent"] == 100.0
    assert payload["over_budget"] is True
    assert payload["over_budget_count"] == 1
    assert payload["over_budget_tags"] == ["large:image"]
    assert payload["over_budget_excess_bytes"] == 1
    assert payload["over_budget_excess_mb"] == 0.0


def test_main_summary_only_includes_total_size_budget_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        reporter,
        "inspect_images",
        lambda images: [
            reporter.ImageSizeRecord(tag=images[0], image_id="large", size_bytes=250_000_001, created=None, present=True)
        ],
    )

    assert reporter.main(["--summary-only", "--max-total-size-mb", "250", "large:image"]) == 1

    payload = json.loads(capsys.readouterr().out)
    assert payload["total_image_size_budget_mb"] == 250.0
    assert payload["total_budget_utilization_percent"] == 100.0
    assert payload["total_over_budget"] is True
    assert payload["total_budget_excess_bytes"] == 1
    assert payload["total_budget_excess_mb"] == 0.0
