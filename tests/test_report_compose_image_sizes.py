from __future__ import annotations

import json
import subprocess
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


def test_records_to_json_includes_bytes_and_decimal_megabytes() -> None:
    record = reporter.ImageSizeRecord(
        tag="realtime-asr:parakeet-nemo-cpu",
        image_id="fedcba654321",
        size_bytes=987_654_321,
        created="2026-07-31T19:00:00Z",
        present=True,
    )

    payload = json.loads(reporter.records_to_json([record]))

    assert payload == [
        {
            "tag": "realtime-asr:parakeet-nemo-cpu",
            "present": True,
            "image_id": "fedcba654321",
            "size_bytes": 987_654_321,
            "size_mb": 987.7,
            "created": "2026-07-31T19:00:00Z",
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
                "unknown_size_tags": [],
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
            }
        },
    ]


def test_records_to_csv_emits_tabular_image_rows() -> None:
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

    assert reporter.records_to_csv(records).splitlines() == [
        "tag,present,image_id,size_bytes,size_mb,created",
        "realtime-asr:faster-whisper-cpu,yes,abcdef123456,1234567890,1234.6,2026-07-31T19:00:00Z",
        "realtime-asr:qwen-cpu,no,,,,",
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
        "unknown_size_tags": [],
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
    }


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


def test_records_summary_reports_present_images_with_unknown_size() -> None:
    records = [
        reporter.ImageSizeRecord(tag="known:image", image_id="known", size_bytes=100_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=None, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    summary = reporter.records_summary(records)
    markdown = reporter.records_to_markdown(records)

    assert summary["unknown_size"] == 1
    assert summary["unknown_size_tags"] == ["unknown:image"]
    assert "Images with unknown size: unknown:image" in markdown


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


def test_records_over_size_budget_ignores_missing_and_unknown_sizes() -> None:
    records = [
        reporter.ImageSizeRecord(tag="small:image", image_id="small", size_bytes=199_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="large:image", image_id="large", size_bytes=201_000_000, created=None, present=True),
        reporter.ImageSizeRecord(tag="unknown:image", image_id="unknown", size_bytes=None, created=None, present=True),
        reporter.ImageSizeRecord(tag="missing:image", image_id=None, size_bytes=None, created=None, present=False),
    ]

    assert reporter.records_over_size_budget(records, 200.0) == [records[1]]


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
        "unknown_size_tags": [],
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
    }


def test_parse_args_accepts_json_summary_aliases() -> None:
    assert reporter.parse_args(["--json-summary"]).summary_only is True
    assert reporter.parse_args(["--summary-json"]).summary_only is True


def test_parse_args_accepts_fail_on_missing_alias() -> None:
    assert reporter.parse_args(["--fail-on-missing"]).require_present is True


def test_parse_args_accepts_fail_on_unknown_size_alias() -> None:
    assert reporter.parse_args(["--fail-on-unknown-size"]).require_size is True


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
        "tag,present,image_id,size_bytes,size_mb,created",
        "present:image,yes,abcdef123456,100000000,100.0,",
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
