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
    assert "Summary: 1/2 images present, 1 missing." in markdown
    assert "Largest present image: realtime-asr:faster-whisper-cpu (1234.6 MB)" in markdown
    assert "Missing images: realtime-asr:qwen-cpu" in markdown


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
                "missing": 0,
                "missing_tags": [],
                "present": 1,
                "requested": 1,
                "total_size_bytes": 987_654_321,
                "total_size_mb": 987.7,
                "largest_present_tag": "realtime-asr:parakeet-nemo-cpu",
                "largest_present_size_bytes": 987_654_321,
                "largest_present_size_mb": 987.7,
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
        "missing": 1,
        "missing_tags": ["realtime-asr:qwen-cpu"],
        "present": 1,
        "requested": 2,
        "total_size_bytes": 1_234_567_890,
        "total_size_mb": 1234.6,
        "largest_present_tag": "realtime-asr:faster-whisper-cpu",
        "largest_present_size_bytes": 1_234_567_890,
        "largest_present_size_mb": 1234.6,
    }


def test_sort_records_orders_by_tag_and_size_desc() -> None:
    records = [
        reporter.ImageSizeRecord(
            tag="realtime-asr:qwen-cpu",
            image_id="qwen",
            size_bytes=200,
            created=None,
            present=True,
        ),
        reporter.ImageSizeRecord(
            tag="realtime-asr:faster-whisper-cpu",
            image_id="faster",
            size_bytes=100,
            created=None,
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
        "missing": 0,
        "missing_tags": [],
        "present": 1,
        "requested": 1,
        "total_size_bytes": 100_000_000,
        "total_size_mb": 100.0,
        "largest_present_tag": "present:image",
        "largest_present_size_bytes": 100_000_000,
        "largest_present_size_mb": 100.0,
    }


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
