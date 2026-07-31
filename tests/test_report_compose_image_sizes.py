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
        }
    ]


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


def test_main_allows_missing_images_unless_required(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
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
