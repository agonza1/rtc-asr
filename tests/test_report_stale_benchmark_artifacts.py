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
render_paths = report_module.render_paths
render_summary = report_module.render_summary
stale_artifacts = report_module.stale_artifacts
stale_summary = report_module.stale_summary
detail_page_path = report_module.detail_page_path
limit_artifacts = report_module.limit_artifacts
normalize_status_filters = report_module.normalize_status_filters


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
            "model": None,
            "backend": None,
            "status": "legacy",
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


def test_stale_summary_groups_artifact_size_by_slug() -> None:
    stale = [
        {"artifact_path": "benchmark-results/base-old.json", "slug": "base", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/base-older.json", "slug": "base", "artifact_size_bytes": 15},
        {"artifact_path": "benchmark-results/qwen.json", "slug": "qwen", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_slug"] == [
        {
            "slug": "base",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "slug": "untracked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "slug": "qwen",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


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


def test_stale_artifacts_can_filter_by_measured_before_timestamp() -> None:
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
                "artifact_path": "benchmark-results/cutoff.json",
                "status": "legacy",
                "measured_at": "2026-06-20T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, measured_before="2026-06-20")

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/old.json"]


def test_stale_artifacts_uses_stricter_cutoff_when_age_and_measured_before_are_set() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/old.json",
                "status": "legacy",
                "measured_at": "2026-06-20T00:00:00Z",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        older_than_days=14,
        measured_before="2026-06-15T00:00:00Z",
        now=datetime(2026, 7, 1, tzinfo=UTC),
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/oldest.json"]


def test_stale_artifacts_rejects_invalid_measured_before_timestamp() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, measured_before="not a timestamp")
    except ValueError as error:
        assert str(error) == "measured_before must be an ISO timestamp or date"
    else:
        raise AssertionError("invalid measured-before filters should fail")


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


def test_stale_artifacts_can_filter_by_maximum_size() -> None:
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

    stale = stale_artifacts(manifest, max_size_bytes=99)

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/tiny.json",
        "benchmark-results/missing-size.json",
    ]


def test_stale_artifacts_can_filter_by_track_slug() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/small.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, slugs=["base", "small"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/small.json",
        "benchmark-results/base.json",
    ]


def test_stale_artifacts_can_filter_by_label_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "label": "Qwen MPS",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/parakeet.json",
                "status": "legacy",
                "label": "Parakeet MLX",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/unlabeled.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, labels=["mlx", "QWEN"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/parakeet.json",
        "benchmark-results/qwen.json",
    ]


def test_stale_artifacts_can_filter_by_backend() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper.json",
                "status": "legacy",
                "backend": "faster-whisper",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "backend": "qwen-asr",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/missing-backend.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, backends=["QWEN-ASR", "parakeet"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/qwen.json"]
    assert stale[0]["backend"] == "qwen-asr"


def test_stale_artifacts_can_filter_by_model_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "model": "base.en",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/missing-model.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, models=["qwen3", "small.en"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/qwen.json"]
    assert stale[0]["model"] == "Qwen/Qwen3-ASR-0.6B"


def test_stale_artifacts_can_filter_by_current_artifact_path() -> None:
    manifest = {
        "tracks": [
            {
                "slug": "base",
                "artifact_path": "benchmark-results/base-current.json",
            },
            {
                "slug": "qwen",
                "artifact_path": "benchmark-results/qwen-current.json",
            },
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-current.json",
                "status": "validated",
                "slug": "base",
                "artifact_size_bytes": 100,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        current_paths=["benchmark-results/base-current.json"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]
    assert stale[0]["current_artifact_path"] == "benchmark-results/base-current.json"


def test_stale_artifacts_can_filter_by_artifact_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        artifact_paths=["benchmark-results/base-old.json"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_status() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/legacy.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/blocked.json",
                "status": "blocked",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/preview.json",
                "status": "preview",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, statuses=["blocked", "PREVIEW"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/preview.json",
        "benchmark-results/blocked.json",
    ]


def test_stale_artifacts_status_any_includes_every_status() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/legacy.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/blocked.json",
                "status": "blocked",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/preview.json",
                "status": "preview",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, statuses=["any"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/preview.json",
        "benchmark-results/blocked.json",
        "benchmark-results/legacy.json",
    ]


def test_stale_artifacts_status_filter_defaults_to_legacy() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/legacy.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/blocked.json",
                "status": "blocked",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest)

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/legacy.json"]


def test_normalize_status_filters_treats_any_as_unfiltered() -> None:
    assert normalize_status_filters(None) == {"legacy"}
    assert normalize_status_filters(["blocked", "PREVIEW"]) == {"blocked", "preview"}
    assert normalize_status_filters(["legacy", "ANY"]) is None


def test_stale_artifacts_rejects_negative_minimum_size() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, min_size_bytes=-1)
    except ValueError as error:
        assert str(error) == "min_size_bytes must be non-negative"
    else:
        raise AssertionError("negative minimum sizes should fail")


def test_stale_artifacts_rejects_invalid_maximum_size_filters() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, max_size_bytes=-1)
    except ValueError as error:
        assert str(error) == "max_size_bytes must be non-negative"
    else:
        raise AssertionError("negative maximum sizes should fail")

    try:
        stale_artifacts({"tracks": [], "artifacts": []}, min_size_bytes=100, max_size_bytes=99)
    except ValueError as error:
        assert str(error) == "min_size_bytes cannot exceed max_size_bytes"
    else:
        raise AssertionError("inverted size ranges should fail")


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

    assert "Found 1 stale benchmark artifact (75 B, 75 bytes):" in rendered
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
    assert "Found 1 stale benchmark artifact (90 B, 90 bytes):" in rendered
    assert "... 1 more stale artifact omitted by --limit." in rendered


def test_render_text_can_report_omitted_limited_artifact_size() -> None:
    stale = [
        {"artifact_path": "benchmark-results/large.json", "artifact_size_bytes": 90},
        {"artifact_path": "benchmark-results/small.json", "artifact_size_bytes": 10},
    ]

    rendered = render_text(stale[:1], total_count=len(stale), total_size_bytes=100)

    assert "... 1 more stale artifact (10 B, 10 bytes) omitted by --limit." in rendered


def test_render_text_reports_zero_limit_omits_all_matches() -> None:
    rendered = render_text([], total_count=2)

    assert (
        rendered
        == "Found 2 stale benchmark artifacts, but 0 are shown because --limit omitted all matches."
    )


def test_render_paths_outputs_one_artifact_path_per_line() -> None:
    rendered = render_paths(
        [
            {"artifact_path": "benchmark-results/oldest.json"},
            {"artifact_path": "benchmark-results/old.json"},
        ]
    )

    assert rendered == "benchmark-results/oldest.json\nbenchmark-results/old.json"


def test_render_paths_can_include_detail_pages() -> None:
    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "detail_page_path": "benchmark-results/pages/oldest.html",
            },
            {"artifact_path": "benchmark-results/no-page.json"},
        ],
        include_detail_pages=True,
    )

    assert rendered == (
        "benchmark-results/oldest.json\n"
        "benchmark-results/pages/oldest.html\n"
        "benchmark-results/no-page.json"
    )


def test_render_paths_can_output_detail_pages_only() -> None:
    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "detail_page_path": "benchmark-results/pages/oldest.html",
            },
            {"artifact_path": "benchmark-results/no-page.json"},
        ],
        detail_pages_only=True,
    )

    assert rendered == "benchmark-results/pages/oldest.html"


def test_render_paths_can_filter_to_existing_paths(tmp_path) -> None:
    docs_root = tmp_path / "docs"
    (docs_root / "benchmark-results" / "pages").mkdir(parents=True)
    (docs_root / "benchmark-results" / "oldest.json").write_text("{}", encoding="utf-8")
    (docs_root / "benchmark-results" / "pages" / "oldest.html").write_text("", encoding="utf-8")

    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "detail_page_path": "benchmark-results/pages/oldest.html",
            },
            {
                "artifact_path": "benchmark-results/missing.json",
                "detail_page_path": "benchmark-results/pages/missing.html",
            },
        ],
        include_detail_pages=True,
        existing_root=docs_root,
    )

    assert rendered == (
        "benchmark-results/oldest.json\n"
        "benchmark-results/pages/oldest.html"
    )


def test_render_summary_groups_stale_artifacts_by_slug() -> None:
    rendered = render_summary(
        [
            {"artifact_path": "benchmark-results/base-old.json", "slug": "base", "artifact_size_bytes": 20},
            {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
            {"artifact_path": "benchmark-results/base-older.json", "slug": "base", "artifact_size_bytes": 15},
        ]
    )

    assert rendered == (
        "Found 3 stale benchmark artifacts (65 B, 65 bytes).\n"
        "- base: 2 artifacts (35 B, 35 bytes)\n"
        "- untracked: 1 artifact (30 B, 30 bytes)"
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


def test_main_fail_on_stale_honors_max_size_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "artifact_size_bytes": 100,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--max-size-bytes", "99"]) == 0
    assert report_module.main(["--fail-on-stale", "--max-size-bytes", "100"]) == 1


def test_main_paths_only_can_include_detail_pages(monkeypatch, capsys) -> None:
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

    assert report_module.main(["--paths-only", "--include-detail-pages"]) == 0

    assert capsys.readouterr().out == (
        "benchmark-results/old.json\nbenchmark-results/pages/old.html\n"
    )


def test_main_paths_only_can_output_detail_pages_only(monkeypatch, capsys) -> None:
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

    assert report_module.main(["--paths-only", "--detail-pages-only"]) == 0

    assert capsys.readouterr().out == "benchmark-results/pages/old.html\n"


def test_main_paths_only_can_filter_to_existing_paths(monkeypatch, tmp_path, capsys) -> None:
    results_dir = tmp_path / "docs" / "benchmark-results"
    pages_dir = results_dir / "pages"
    pages_dir.mkdir(parents=True)
    (results_dir / "old.json").write_text("{}", encoding="utf-8")
    (pages_dir / "old.html").write_text("", encoding="utf-8")

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
                },
                {
                    "artifact_path": "benchmark-results/missing.json",
                    "status": "legacy",
                    "artifact_size_bytes": 20,
                },
            ],
        },
    )

    assert (
        report_module.main(
            [
                "--results-dir",
                str(results_dir),
                "--paths-only",
                "--include-detail-pages",
                "--existing-paths-only",
            ]
        )
        == 0
    )

    assert capsys.readouterr().out == (
        "benchmark-results/old.json\nbenchmark-results/pages/old.html\n"
    )


def test_main_rejects_detail_pages_without_paths_only() -> None:
    try:
        report_module.main(["--include-detail-pages"])
    except ValueError as error:
        assert str(error) == "--include-detail-pages requires --paths-only"
    else:
        raise AssertionError("--include-detail-pages should require --paths-only")


def test_main_rejects_detail_pages_only_without_paths_only() -> None:
    try:
        report_module.main(["--detail-pages-only"])
    except ValueError as error:
        assert str(error) == "--detail-pages-only requires --paths-only"
    else:
        raise AssertionError("--detail-pages-only should require --paths-only")


def test_main_rejects_detail_page_path_modes_together() -> None:
    try:
        report_module.main(["--paths-only", "--include-detail-pages", "--detail-pages-only"])
    except ValueError as error:
        assert str(error) == "--detail-pages-only cannot be combined with --include-detail-pages"
    else:
        raise AssertionError("detail page path modes should be mutually exclusive")


def test_main_rejects_existing_paths_only_without_paths_only() -> None:
    try:
        report_module.main(["--existing-paths-only"])
    except ValueError as error:
        assert str(error) == "--existing-paths-only requires --paths-only"
    else:
        raise AssertionError("--existing-paths-only should require --paths-only")


def test_main_fail_on_stale_honors_measured_before_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/recent.json",
                    "status": "legacy",
                    "measured_at": "2026-06-20T00:00:00Z",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--measured-before", "2026-06-10"]) == 0
    assert report_module.main(["--fail-on-stale", "--measured-before", "2026-06-21"]) == 1


def test_main_fail_on_stale_honors_slug_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "slug": "base",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--slug", "small"]) == 0
    assert report_module.main(["--fail-on-stale", "--slug", "base"]) == 1


def test_main_fail_on_stale_honors_label_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "label": "Faster Whisper Base",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--label", "qwen"]) == 0
    assert report_module.main(["--fail-on-stale", "--label", "whisper"]) == 1


def test_main_fail_on_stale_honors_backend_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "backend": "faster-whisper",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--backend", "qwen-asr"]) == 0
    assert report_module.main(["--fail-on-stale", "--backend", "faster-whisper"]) == 1


def test_main_fail_on_stale_honors_model_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "model": "base.en",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--model", "small.en"]) == 0
    assert report_module.main(["--fail-on-stale", "--model", "base"]) == 1


def test_main_fail_on_stale_honors_current_path_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [
                {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
            ],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base-current.json",
                    "status": "validated",
                    "slug": "base",
                    "artifact_size_bytes": 100,
                },
                {
                    "artifact_path": "benchmark-results/base-old.json",
                    "status": "legacy",
                    "slug": "base",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--current-path", "benchmark-results/qwen.json"]) == 0
    assert (
        report_module.main(
            ["--fail-on-stale", "--current-path", "benchmark-results/base-current.json"]
        )
        == 1
    )


def test_main_fail_on_stale_honors_artifact_path_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base-old.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--artifact-path", "benchmark-results/qwen.json"]) == 0
    assert (
        report_module.main(["--fail-on-stale", "--artifact-path", "benchmark-results/base-old.json"])
        == 1
    )


def test_main_fail_on_stale_honors_status_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/blocked.json",
                    "status": "blocked",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale"]) == 0
    assert report_module.main(["--fail-on-stale", "--status", "blocked"]) == 1


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
        "... 1 more stale artifact (10 B, 10 bytes) omitted by --limit."
        in capsys.readouterr().out
    )


def test_main_paths_only_honors_filters_and_limits(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "label": "Faster Whisper",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "label": "Faster Whisper",
                    "artifact_size_bytes": 10,
                },
                {
                    "artifact_path": "benchmark-results/qwen.json",
                    "status": "legacy",
                    "label": "Qwen",
                    "artifact_size_bytes": 100,
                },
            ],
        },
    )

    assert report_module.main(["--paths-only", "--label", "whisper", "--limit", "1"]) == 0

    assert capsys.readouterr().out == "benchmark-results/large.json\n"


def test_main_count_only_reports_total_matches_before_limit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "label": "Faster Whisper",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "label": "Faster Whisper",
                    "artifact_size_bytes": 10,
                },
                {
                    "artifact_path": "benchmark-results/qwen.json",
                    "status": "legacy",
                    "label": "Qwen",
                    "artifact_size_bytes": 100,
                },
            ],
        },
    )

    assert report_module.main(["--count-only", "--label", "whisper", "--limit", "1"]) == 0

    assert capsys.readouterr().out == "2\n"


def test_main_summary_only_reports_totals_before_limit(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "slug": "base",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "slug": "base",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--summary-only", "--limit", "1"]) == 0

    assert capsys.readouterr().out == (
        "Found 2 stale benchmark artifacts (100 B, 100 bytes).\n"
        "- base: 2 artifacts (100 B, 100 bytes)\n"
    )


def test_main_rejects_paths_only_with_json() -> None:
    try:
        report_module.main(["--paths-only", "--json"])
    except ValueError as error:
        assert str(error) == "--json and --paths-only cannot be used together"
    else:
        raise AssertionError("paths-only JSON output should be rejected")


def test_main_rejects_count_only_with_structured_output_modes() -> None:
    try:
        report_module.main(["--count-only", "--json"])
    except ValueError as error:
        assert str(error) == "--count-only and --json cannot be used together"
    else:
        raise AssertionError("count-only JSON output should be rejected")

    try:
        report_module.main(["--count-only", "--paths-only"])
    except ValueError as error:
        assert str(error) == "--count-only and --paths-only cannot be used together"
    else:
        raise AssertionError("count-only path output should be rejected")


def test_main_rejects_summary_only_with_structured_output_modes() -> None:
    for args, expected in [
        (["--summary-only", "--json"], "--summary-only and --json cannot be used together"),
        (["--summary-only", "--paths-only"], "--summary-only and --paths-only cannot be used together"),
        (["--summary-only", "--count-only"], "--summary-only and --count-only cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")
