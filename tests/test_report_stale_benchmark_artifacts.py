import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = SCRIPTS_DIR / "report_stale_benchmark_artifacts.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_report_stale_benchmark_artifacts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
report_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_report_stale_benchmark_artifacts", report_module)
SPEC.loader.exec_module(report_module)

format_bytes = report_module.format_bytes
render_text = report_module.render_text
stale_artifacts = report_module.stale_artifacts
stale_summary = report_module.stale_summary
detail_page_path = report_module.detail_page_path
limit_artifacts = report_module.limit_artifacts


def test_stale_artifacts_excludes_current_track_artifact() -> None:
    manifest = {
        "tracks": [{"artifact_path": "benchmark-results/current.json", "slug": "demo"}],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/current.json",
                "status": "validated",
                "slug": "demo",
                "artifact_size_bytes": 100,
            },
            {
                "artifact_path": "benchmark-results/older.json",
                "status": "legacy",
                "slug": "demo",
                "label": "Demo",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 75,
            },
            {
                "artifact_path": "benchmark-results/blocked.json",
                "status": "blocked",
                "slug": "demo",
                "artifact_size_bytes": 25,
            },
        ],
    }

    assert stale_artifacts(manifest) == [
        {
            "artifact_path": "benchmark-results/older.json",
            "slug": "demo",
            "label": "Demo",
            "measured_at": "2026-06-10T00:00:00Z",
            "current_artifact_path": "benchmark-results/current.json",
            "detail_page_path": "benchmark-results/pages/older.html",
            "artifact_size_bytes": 75,
            "artifact_size": "75 B",
        }
    ]


def test_stale_artifacts_orders_largest_first_and_summarizes_total() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/small.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/large.json",
                "status": "legacy",
                "artifact_size_bytes": 90,
            },
        ],
    }

    stale = stale_artifacts(manifest)

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    summary = stale_summary(stale)

    assert summary["total_size_bytes"] == 100
    assert summary["total_size"] == "100 B"


def test_stale_artifacts_can_sort_oldest_measured_first() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/newer.json",
                "status": "legacy",
                "measured_at": "2026-06-20T00:00:00Z",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/older.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 100,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="measured-at")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/a.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="path")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/a.json",
        "benchmark-results/z.json",
    ]


def test_stale_artifacts_rejects_unknown_sort_order() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, sort_by="unknown")
    except ValueError as error:
        assert str(error) == "sort_by must be one of: size, measured-at, path"
    else:
        raise AssertionError("unknown stale artifact sort orders should fail")


def test_stale_artifacts_can_filter_by_age() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/old.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-25T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        older_than_days=14,
        now=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/old.json"]


def test_stale_artifacts_can_filter_by_minimum_size() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/tiny.json",
                "status": "legacy",
                "artifact_size_bytes": 99,
            },
            {
                "artifact_path": "benchmark-results/large.json",
                "status": "legacy",
                "artifact_size_bytes": 100,
            },
            {
                "artifact_path": "benchmark-results/missing-size.json",
                "status": "legacy",
            },
        ],
    }

    stale = stale_artifacts(manifest, min_size_bytes=100)

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/large.json"]


def test_stale_artifacts_rejects_negative_minimum_size() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, min_size_bytes=-1)
    except ValueError as error:
        assert str(error) == "min_size_bytes must be non-negative"
    else:
        raise AssertionError("negative minimum sizes should fail")


def test_format_bytes_uses_binary_units() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(75) == "75 B"
    assert format_bytes(1536) == "1.5 KiB"
    assert format_bytes(2 * 1024 * 1024) == "2.0 MiB"


def test_detail_page_path_matches_prerendered_artifact_page() -> None:
    assert (
        detail_page_path("benchmark-results/faster-whisper-base.en-int8-2026-06-20.json")
        == "benchmark-results/pages/faster-whisper-base.en-int8-2026-06-20.html"
    )
    assert detail_page_path("benchmark-results/readme.txt") is None
    assert detail_page_path(None) is None


def test_render_text_summarizes_stale_artifacts() -> None:
    rendered = render_text(
        [
            {
                "artifact_path": "benchmark-results/older.json",
                "slug": "demo",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 75,
                "current_artifact_path": "benchmark-results/current.json",
                "detail_page_path": "benchmark-results/pages/older.html",
            }
        ]
    )

    assert "Found 1 stale benchmark artifacts (75 B, 75 bytes):" in rendered
    assert (
        "benchmark-results/older.json [demo] measured 2026-06-10T00:00:00Z (75 B); "
        "current: benchmark-results/current.json; detail: benchmark-results/pages/older.html"
    ) in rendered


def test_limit_artifacts_keeps_largest_entries_and_text_mentions_omissions() -> None:
    stale = [
        {"artifact_path": "benchmark-results/large.json", "artifact_size_bytes": 90},
        {"artifact_path": "benchmark-results/small.json", "artifact_size_bytes": 10},
    ]

    limited = limit_artifacts(stale, 1)
    rendered = render_text(limited, total_count=len(stale))

    assert limited == [stale[0]]
    assert "Found 1 stale benchmark artifacts (90 B, 90 bytes):" in rendered
    assert "... 1 more stale artifacts omitted by --limit." in rendered


def test_render_text_can_report_omitted_limited_artifact_size() -> None:
    stale = [
        {"artifact_path": "benchmark-results/large.json", "artifact_size_bytes": 90},
        {"artifact_path": "benchmark-results/small.json", "artifact_size_bytes": 10},
    ]

    rendered = render_text(stale[:1], total_count=len(stale), total_size_bytes=100)

    assert "... 1 more stale artifacts (10 B, 10 bytes) omitted by --limit." in rendered


def test_render_text_reports_zero_limit_omits_all_matches() -> None:
    rendered = render_text([], total_count=2)

    assert (
        rendered
        == "Found 2 stale benchmark artifacts, but 0 are shown because --limit omitted all matches."
    )


def test_limit_artifacts_rejects_negative_limits() -> None:
    try:
        limit_artifacts([], -1)
    except ValueError as error:
        assert str(error) == "limit must be non-negative"
    else:
        raise AssertionError("negative limits should fail")


def test_main_can_fail_when_matching_stale_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/old.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale"]) == 1


def test_main_fail_on_stale_honors_filters(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/tiny.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--min-size-bytes", "100"]) == 0


def test_main_json_reports_total_matching_size_when_limited(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--json", "--limit", "1"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["total_size_bytes"] == 90
    assert payload["total_matching_count"] == 2
    assert payload["total_matching_size_bytes"] == 100
    assert payload["total_matching_size"] == "100 B"


def test_main_text_reports_total_matching_size_when_limited(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--limit", "1"]) == 0

    assert (
        "... 1 more stale artifacts (10 B, 10 bytes) omitted by --limit."
        in capsys.readouterr().out
    )
