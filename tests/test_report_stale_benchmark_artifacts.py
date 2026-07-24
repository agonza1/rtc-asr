import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
MODULE_PATH = SCRIPTS_DIR / "report_stale_benchmark_artifacts.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_report_stale_benchmark_artifacts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
report_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_report_stale_benchmark_artifacts", report_module)
SPEC.loader.exec_module(report_module)

format_bytes = report_module.format_bytes
format_age_days = report_module.format_age_days
render_text = report_module.render_text
render_paths = report_module.render_paths
render_json_lines = report_module.render_json_lines
render_json_summary = report_module.render_json_summary
render_summary_csv = report_module.render_summary_csv
render_csv = report_module.render_csv
render_markdown = report_module.render_markdown
render_summary = report_module.render_summary
stale_artifacts = report_module.stale_artifacts
stale_summary = report_module.stale_summary
detail_page_path = report_module.detail_page_path
limit_artifacts = report_module.limit_artifacts
normalize_status_filters = report_module.normalize_status_filters
normalize_filter_values = report_module.normalize_filter_values
normalize_summary_groups = report_module.normalize_summary_groups
validate_summary_options = report_module.validate_summary_options
measured_month = report_module.measured_month
age_bucket = report_module.age_bucket
parse_args = report_module.parse_args


def test_filter_values_accept_comma_separated_values() -> None:
    assert normalize_filter_values(["base, qwen", "parakeet"]) == ["base", "qwen", "parakeet"]


def test_status_filters_accept_comma_separated_values() -> None:
    assert normalize_status_filters(["legacy, blocked", "validated"]) == {
        "legacy",
        "blocked",
        "validated",
    }


def test_summary_groups_accept_comma_separated_values() -> None:
    assert normalize_summary_groups(["status, backend", "measured-month"]) == {
        "status",
        "backend",
        "measured-month",
    }


def test_summary_groups_accept_all_alias_with_specific_groups() -> None:
    assert normalize_summary_groups(["status, all"]) == set(report_module.SUMMARY_GROUPS)


def test_summary_groups_reject_unknown_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        normalize_summary_groups(["status, typo"])

    assert "Unsupported summary group: typo." in str(exc_info.value)
    assert "Valid groups: slug, artifact-name" in str(exc_info.value)


def test_validate_summary_options_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="summary_min_count cannot exceed summary_max_count"):
        validate_summary_options(summary_min_count=2, summary_max_count=1)

    with pytest.raises(ValueError, match="summary_min_size_bytes cannot exceed summary_max_size_bytes"):
        validate_summary_options(summary_min_size_bytes=20, summary_max_size_bytes=10)


def test_parse_args_accepts_average_size_summary_sort_aliases() -> None:
    for alias in ["average-size", "average-size-desc", "average-size-asc"]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_explicit_ascending_stale_sort_aliases() -> None:
    aliases = [
        "artifact-stem-asc",
        "artifact-dir-asc",
        "artifact-extension-asc",
        "detail-page-asc",
        "detail-page-name-asc",
        "detail-page-stem-asc",
        "detail-page-dir-asc",
        "detail-page-extension-asc",
        "status-asc",
        "backend-asc",
        "model-asc",
        "label-asc",
        "slug-asc",
        "track-state-asc",
        "current-path-asc",
        "current-path-name-asc",
        "current-path-stem-asc",
        "current-path-dir-asc",
        "current-path-extension-asc",
        "measured-month-asc",
        "age-bucket-asc",
    ]

    for alias in aliases:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_repo_relative_paths_mode() -> None:
    args = parse_args(["--paths-only", "--repo-relative-paths"])

    assert args.paths_only is True
    assert args.repo_relative_paths is True


def test_parse_args_accepts_existing_manifest_path() -> None:
    args = parse_args(["--manifest", "docs/benchmark-results/manifest.json"])

    assert args.manifest == Path("docs/benchmark-results/manifest.json")


def test_measured_month_uses_utc_month_or_unknown() -> None:
    assert measured_month("2026-06-30T23:30:00-02:00") == "2026-07"
    assert measured_month(None) == "unknown"


def test_age_bucket_uses_cleanup_review_ranges() -> None:
    assert age_bucket(None) == "unknown"
    assert age_bucket(6) == "0-6d"
    assert age_bucket(7) == "7-29d"
    assert age_bucket(30) == "30-89d"
    assert age_bucket(90) == "90d+"


def test_format_age_days_handles_plural_and_unknown() -> None:
    assert format_age_days(1) == "1 day"
    assert format_age_days(2) == "2 days"
    assert format_age_days(None) == "unknown"


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

    assert stale_artifacts(manifest, now=datetime(2026, 6, 20, tzinfo=UTC)) == [
        {
            "artifact_path": "benchmark-results/older.json",
            "artifact_name": "older.json",
            "artifact_stem": "older",
            "artifact_dir": "benchmark-results",
            "artifact_extension": ".json",
            "slug": "demo",
            "label": "Demo",
            "model": None,
            "backend": None,
            "status": "legacy",
            "measured_at": "2026-06-10T00:00:00Z",
            "measured_month": "2026-06",
            "age_days": 10,
            "age_bucket": "7-29d",
            "age": "10 days",
            "current_artifact_path": "benchmark-results/current.json",
            "current_artifact_name": "current.json",
            "current_artifact_stem": "current",
            "current_artifact_dir": "benchmark-results",
            "current_artifact_extension": ".json",
            "track_state": "tracked",
            "detail_page_path": "benchmark-results/pages/older.html",
            "detail_page_name": "older.html",
            "detail_page_stem": "older",
            "detail_page_dir": "benchmark-results/pages",
            "detail_page_extension": ".html",
            "artifact_size_bytes": 75,
            "artifact_size": "75 B",
        }
    ]


def test_stale_artifacts_accepts_comma_separated_repeated_filters() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base.json",
                "slug": "base",
                "backend": "faster-whisper",
                "model": "base.en",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "slug": "qwen",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "status": "legacy",
                "measured_at": "2026-07-01T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet.json",
                "slug": "parakeet",
                "backend": "parakeet-mlx",
                "model": "parakeet-tdt-0.6b-v2",
                "status": "legacy",
                "measured_at": "2026-07-01T00:00:00Z",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        slugs=["base, qwen"],
        backends=["faster-whisper, qwen-asr"],
        models=["base.en, Qwen"],
        measured_months=["2026-06, 2026-07"],
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen.json",
        "benchmark-results/base.json",
    ]


def test_stale_artifacts_can_filter_by_status_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy-candidate",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "blocked",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet.json",
                "status": "validated",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        statuses=["any"],
        status_contains=["legacy, block"],
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen.json",
        "benchmark-results/base.json",
    ]


def test_stale_artifacts_status_text_searches_all_statuses_by_default() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy-candidate",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "blocked",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest, status_contains=["block"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/qwen.json"]


def test_stale_artifacts_path_filters_accept_comma_separated_values() -> None:
    manifest = {
        "tracks": [
            {"slug": "base", "artifact_path": "benchmark-results/current/base-current.json"},
            {"slug": "qwen", "artifact_path": "benchmark-results/current/qwen-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "slug": "qwen",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/parakeet-old.json",
                "slug": "parakeet",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        artifact_paths=["benchmark-results/archive/base-old.json, benchmark-results/archive/qwen-old.json"],
        artifact_path_contains=["base, qwen"],
        current_paths=["benchmark-results/current/base-current.json, benchmark-results/current/qwen-current.json"],
        current_path_contains=["base, qwen"],
        current_path_name_contains=["base, qwen"],
        detail_pages=["benchmark-results/pages/base-old.html, benchmark-results/pages/qwen-old.html"],
        detail_page_contains=["base, qwen"],
        detail_page_name_contains=["base, qwen"],
        detail_page_stem_contains=["base, qwen"],
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_can_filter_by_current_artifact_directory() -> None:
    manifest = {
        "tracks": [
            {"slug": "base", "artifact_path": "benchmark-results/current/base-current.json"},
            {"slug": "qwen", "artifact_path": "benchmark-results/published/qwen-current.json"},
            {"slug": "parakeet", "artifact_path": "benchmark-results/current/parakeet-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "slug": "qwen",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/parakeet-old.json",
                "slug": "parakeet",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        current_path_dirs=["benchmark-results/current"],
        current_path_dir_contains=["current"],
        sort_by="current-path-dir",
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/archive/parakeet-old.json",
    ]
    assert stale[0]["current_artifact_dir"] == "benchmark-results/current"


def test_stale_artifacts_rejects_impossible_age_window() -> None:
    with pytest.raises(ValueError, match="newer_than_days cannot be less than older_than_days"):
        stale_artifacts({"tracks": [], "artifacts": []}, older_than_days=30, newer_than_days=7)


def test_stale_artifacts_can_filter_by_artifact_directory() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_dirs=["benchmark-results/archive"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_can_filter_by_artifact_directory_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/current/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_dir_contains=["ARCHIVE"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_can_filter_by_artifact_stem() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        artifact_stems=["base-old, qwen-old.json"],
        artifact_stem_contains=["old"],
        sort_by="artifact-stem",
    )

    assert [entry["artifact_stem"] for entry in stale] == ["base-old", "qwen-old"]


def test_stale_artifacts_can_sort_by_artifact_stem_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-stem-desc")

    assert [entry["artifact_stem"] for entry in stale] == [
        "qwen-old",
        "parakeet-old",
        "base-old",
    ]


def test_stale_artifacts_can_sort_by_path_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="path-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/parakeet-old.json",
        "benchmark-results/base-old.json",
    ]


def test_stale_artifacts_can_sort_by_artifact_name_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-name-desc")

    assert [entry["artifact_name"] for entry in stale] == [
        "qwen-old.json",
        "parakeet-old.json",
        "base-old.json",
    ]


def test_stale_artifacts_can_sort_by_detail_page_name_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="detail-page-name-desc")

    assert [entry["detail_page_name"] for entry in stale] == [
        "qwen-old.html",
        "parakeet-old.html",
        "base-old.html",
    ]


def test_stale_artifacts_can_sort_by_detail_page_stem_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="detail-page-stem-desc")

    assert [entry["detail_page_stem"] for entry in stale] == [
        "qwen-old",
        "parakeet-old",
        "base-old",
    ]


def test_stale_artifacts_can_sort_by_slug_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "slug": "qwen",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "slug": "parakeet",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="slug-desc")

    assert [entry["slug"] for entry in stale] == [
        "qwen",
        "parakeet",
        "base",
    ]


def test_stale_artifacts_can_sort_by_backend_descending_with_model_tiebreak() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "backend": "faster-whisper",
                "model": "base.en",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "backend": "parakeet",
                "model": "nvidia/parakeet-tdt-0.6b-v3",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/parakeet-small-old.json",
                "backend": "parakeet",
                "model": "nvidia/parakeet-tdt_ctc-110m",
                "status": "legacy",
                "artifact_size_bytes": 5,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="backend-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/parakeet-small-old.json",
        "benchmark-results/parakeet-old.json",
        "benchmark-results/base-old.json",
    ]


def test_stale_artifacts_can_sort_by_artifact_directory_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/current/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/parakeet-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-dir-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/current/qwen-old.json",
        "benchmark-results/archive/base-old.json",
        "benchmark-results/parakeet-old.json",
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


def test_render_json_lines_emits_one_sorted_object_per_artifact() -> None:
    rendered = render_json_lines(
        [
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
        ]
    )

    lines = rendered.splitlines()

    assert [json.loads(line)["artifact_path"] for line in lines] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert lines[0].startswith('{"artifact_path":')


def test_render_paths_can_emit_repo_relative_artifacts_and_detail_pages() -> None:
    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/base.json",
                "detail_page_path": "benchmark-results/pages/base.html",
            },
            {
                "artifact_path": "benchmark-results/base.json",
                "detail_page_path": "benchmark-results/pages/base.html",
            },
        ],
        include_detail_pages=True,
        path_prefix=Path("docs"),
    )

    assert rendered.splitlines() == [
        "docs/benchmark-results/base.json",
        "docs/benchmark-results/pages/base.html",
    ]


def test_render_json_summary_can_select_and_limit_groups() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug, status"],
        summary_limit=1,
    )

    summary = json.loads(rendered)

    assert summary == {
        "count": 2,
        "total_size_bytes": 100,
        "total_size": "100 B",
        "by_slug": [
            {
                "slug": "base",
                "count": 1,
                "total_size_bytes": 90,
                "total_size": "90 B",
            }
        ],
        "by_slug_omitted": {
            "count": 1,
            "total_size_bytes": 10,
            "total_size": "10 B",
        },
        "by_status": [
            {
                "status": "legacy",
                "count": 2,
                "total_size_bytes": 100,
                "total_size": "100 B",
            }
        ],
    }


def test_render_json_summary_can_include_group_share_percentages() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base-small.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 5,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        include_share=True,
    )

    summary = json.loads(rendered)

    assert summary["by_slug"] == [
        {
            "slug": "base",
            "count": 2,
            "total_size_bytes": 95,
            "total_size": "95 B",
            "count_share_percent": 66.7,
            "size_share_percent": 95.0,
        },
        {
            "slug": "qwen",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
            "count_share_percent": 33.3,
            "size_share_percent": 5.0,
        },
    ]


def test_render_summary_csv_emits_selected_groups_with_shares() -> None:
    rendered = render_summary_csv(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "blocked",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        include_share=True,
    )

    assert rendered.splitlines() == [
        "group,bucket,count,total_size_bytes,total_size,count_share_percent,size_share_percent",
        "slug,base,1,90,90 B,50.0,90.0",
        "slug,qwen,1,10,10 B,50.0,10.0",
    ]


def test_render_json_summary_can_filter_group_rows_by_min_count() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base-small.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 5,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_min_count=2,
    )

    summary = json.loads(rendered)

    assert summary["by_slug"] == [
        {
            "slug": "base",
            "count": 2,
            "total_size_bytes": 95,
            "total_size": "95 B",
        }
    ]


def test_render_json_summary_can_filter_group_rows_by_max_count() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base-small.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 5,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_max_count=1,
    )

    summary = json.loads(rendered)

    assert summary["by_slug"] == [
        {
            "slug": "qwen",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        }
    ]


def test_render_json_summary_can_filter_group_rows_by_min_size() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_min_size_bytes=50,
    )

    summary = json.loads(rendered)

    assert summary["by_slug"] == [
        {
            "slug": "base",
            "count": 1,
            "total_size_bytes": 90,
            "total_size": "90 B",
        }
    ]


def test_render_json_summary_can_filter_group_rows_by_max_size() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_max_size_bytes=50,
    )

    summary = json.loads(rendered)

    assert summary["by_slug"] == [
        {
            "slug": "qwen",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        }
    ]


def test_render_json_summary_can_sort_group_rows_by_count() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen-a.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-b.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="count",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_explicit_count_desc_sort() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen-a.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-b.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="count-desc",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_can_sort_group_rows_ascending() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen-a.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-b.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="size-asc",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_explicit_size_desc_sort() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="size-desc",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["base", "qwen"]


def test_render_json_summary_can_sort_group_rows_by_average_size() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 50,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 50,
            },
            {
                "artifact_path": "benchmark-results/qwen-large.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 80,
            },
        ],
        groups=["slug"],
        summary_sort="average-size",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_summary_can_sort_group_rows_by_average_size_ascending() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 50,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 50,
            },
            {
                "artifact_path": "benchmark-results/qwen-large.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 80,
            },
        ],
        groups=["slug"],
        summary_sort="average-size-asc",
    )

    assert rendered.splitlines()[1:3] == [
        "- base: 2 artifacts (100 B, 100 bytes)",
        "- qwen: 1 artifact (80 B, 80 bytes)",
    ]


def test_render_summary_can_sort_group_rows_by_count_ascending() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen-a.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-b.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="count-asc",
    )

    assert rendered.splitlines()[1:3] == [
        "- base: 1 artifact (90 B, 90 bytes)",
        "- qwen: 2 artifacts (20 B, 20 bytes)",
    ]


def test_render_summary_can_filter_group_rows_by_min_count() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base-small.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 5,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_min_count=2,
    )

    assert "- base: 2 artifacts (95 B, 95 bytes)" in rendered
    assert "- qwen:" not in rendered


def test_render_summary_can_filter_group_rows_by_max_count() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base-small.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 5,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_max_count=1,
    )

    assert "- qwen: 1 artifact (5 B, 5 bytes)" in rendered
    assert "- base:" not in rendered


def test_render_summary_can_filter_group_rows_by_min_size() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_min_size_bytes=50,
    )

    assert "- base: 1 artifact (90 B, 90 bytes)" in rendered
    assert "- qwen:" not in rendered


def test_render_summary_can_filter_group_rows_by_max_size() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 5,
            },
        ],
        groups=["slug"],
        summary_max_size_bytes=50,
    )

    assert "- qwen: 1 artifact (5 B, 5 bytes)" in rendered
    assert "- base:" not in rendered


def test_render_summary_can_sort_group_rows_by_name() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/zeta.json",
                "status": "legacy",
                "slug": "zeta",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="name",
    )

    assert rendered.splitlines()[1:3] == [
        "- base: 1 artifact (10 B, 10 bytes)",
        "- zeta: 1 artifact (90 B, 90 bytes)",
    ]


def test_render_json_summary_accepts_explicit_name_ascending_sort() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/zeta.json",
                "status": "legacy",
                "slug": "zeta",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="name-asc",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["base", "zeta"]


def test_render_summary_can_sort_group_rows_by_name_descending() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/alpha-short.json",
                "status": "legacy",
                "slug": "alpha",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/alpha-long.json",
                "status": "legacy",
                "slug": "alpha-long",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/zeta.json",
                "status": "legacy",
                "slug": "zeta",
                "artifact_size_bytes": 90,
            },
        ],
        groups=["slug"],
        summary_sort="name-desc",
    )

    assert rendered.splitlines()[1:4] == [
        "- zeta: 1 artifact (90 B, 90 bytes)",
        "- alpha-long: 1 artifact (20 B, 20 bytes)",
        "- alpha: 1 artifact (10 B, 10 bytes)",
    ]


def test_render_summary_can_group_by_age_bucket() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "age_days": 3,
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/older.json",
                "status": "legacy",
                "age_days": 45,
                "artifact_size_bytes": 90,
            },
        ],
        groups=["age-bucket"],
    )

    assert "By age bucket:" in rendered
    assert "- 30-89d: 1 artifact (90 B, 90 bytes)" in rendered
    assert "- 0-6d: 1 artifact (10 B, 10 bytes)" in rendered


def test_render_summary_sorts_age_bucket_names_by_bucket_order() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/month-old.json",
                "status": "legacy",
                "age_bucket": "30-89d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/week-old.json",
                "status": "legacy",
                "age_bucket": "7-29d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "age_bucket": "0-6d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "age_bucket": "90d+",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "age_bucket": "unknown",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["age-bucket"],
        summary_sort="name",
    )

    assert rendered.splitlines()[2:7] == [
        "- 0-6d: 1 artifact (10 B, 10 bytes)",
        "- 7-29d: 1 artifact (10 B, 10 bytes)",
        "- 30-89d: 1 artifact (10 B, 10 bytes)",
        "- 90d+: 1 artifact (10 B, 10 bytes)",
        "- unknown: 1 artifact (10 B, 10 bytes)",
    ]


def test_render_json_summary_sorts_age_bucket_names_descending_by_bucket_order() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/month-old.json",
                "status": "legacy",
                "age_bucket": "30-89d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/week-old.json",
                "status": "legacy",
                "age_bucket": "7-29d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "age_bucket": "0-6d",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "age_bucket": "90d+",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "age_bucket": "unknown",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["age-bucket"],
        summary_sort="name-desc",
    )

    summary = json.loads(rendered)

    assert [bucket["age_bucket"] for bucket in summary["by_age_bucket"]] == [
        "unknown",
        "90d+",
        "30-89d",
        "7-29d",
        "0-6d",
    ]


def test_render_json_summary_can_sort_group_rows_by_name_descending() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["slug"],
        summary_sort="name-desc",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_summary_omitted_size_follows_summary_sort() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-large.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/qwen-a.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/qwen-b.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/tiny.json",
                "status": "legacy",
                "slug": "tiny",
                "artifact_size_bytes": 1,
            },
        ],
        groups=["slug"],
        summary_limit=1,
        summary_sort="count",
    )

    assert rendered.splitlines() == [
        "Found 4 stale benchmark artifacts (111 B, 111 bytes).",
        "- qwen: 2 artifacts (20 B, 20 bytes)",
        "... 2 more buckets (91 B, 91 bytes) omitted by --summary-limit.",
    ]


def test_render_csv_emits_header_and_artifact_rows() -> None:
    rendered = render_csv(
        [
            {
                "artifact_path": "benchmark-results/large.json",
                "slug": "base",
                "label": "Faster, Whisper",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "measured_month": "2026-06",
                "age_days": 10,
                "age_bucket": "7-29d",
                "age": "10 days",
                "current_artifact_path": "benchmark-results/current.json",
                "track_state": "tracked",
                "detail_page_path": "benchmark-results/pages/large.html",
                "artifact_size_bytes": 90,
                "artifact_size": "90 B",
                "artifact_extension": ".json",
            }
        ]
    )

    assert rendered.splitlines() == [
        "artifact_path,artifact_name,artifact_stem,artifact_dir,artifact_extension,slug,label,backend,model,status,measured_at,measured_month,age_days,age_bucket,age,current_artifact_path,current_artifact_name,current_artifact_stem,current_artifact_dir,current_artifact_extension,track_state,detail_page_path,detail_page_name,detail_page_stem,detail_page_dir,detail_page_extension,artifact_size_bytes,artifact_size",
        'benchmark-results/large.json,large.json,large,benchmark-results,.json,base,"Faster, Whisper",,,legacy,2026-06-10T00:00:00Z,2026-06,10,7-29d,10 days,benchmark-results/current.json,current.json,current,benchmark-results,.json,tracked,benchmark-results/pages/large.html,large.html,large,benchmark-results/pages,.html,90,90 B',
    ]


def test_render_markdown_emits_review_table_and_escapes_pipes() -> None:
    rendered = render_markdown(
        [
            {
                "artifact_path": "benchmark-results/large|old.json",
                "status": "legacy",
                "age": "10 days",
                "current_artifact_path": "benchmark-results/current.json",
                "detail_page_path": "benchmark-results/pages/large.html",
                "artifact_size_bytes": 90,
                "artifact_size": "90 B",
            }
        ],
        total_count=2,
        total_size_bytes=111,
    )

    assert rendered.splitlines() == [
        "Found 1 stale benchmark artifact (90 B, 90 bytes).",
        "",
        "| Artifact | Status | Age | Size | Current artifact | Detail page |",
        "| --- | --- | ---: | ---: | --- | --- |",
        "| benchmark-results/large\\|old.json | legacy | 10 days | 90 B | benchmark-results/current.json | benchmark-results/pages/large.html |",
        "",
        "... 1 more stale artifact (21 B, 21 bytes) omitted by --limit.",
    ]


def test_parse_args_accepts_markdown_output_flag() -> None:
    assert parse_args(["--markdown"]).markdown is True


def test_parse_args_accepts_json_summary_share_flag() -> None:
    assert parse_args(["--json-summary", "--summary-share"]).summary_share is True


def test_parse_args_accepts_summary_csv_output_flag() -> None:
    assert parse_args(["--summary-csv", "--summary-share"]).summary_csv is True


def test_parse_args_accepts_output_path() -> None:
    assert parse_args(["--output", "cleanup/report.txt"]).output == Path("cleanup/report.txt")


def test_stale_artifacts_can_sort_smallest_first() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/medium.json",
                "status": "legacy",
                "artifact_size_bytes": 50,
            },
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

    stale = stale_artifacts(manifest, sort_by="size-asc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/small.json",
        "benchmark-results/medium.json",
        "benchmark-results/large.json",
    ]


def test_stale_artifacts_accepts_explicit_largest_first_sort_alias() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/medium.json",
                "status": "legacy",
                "artifact_size_bytes": 50,
            },
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

    stale = stale_artifacts(manifest, sort_by="size-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/large.json",
        "benchmark-results/medium.json",
        "benchmark-results/small.json",
    ]


def test_stale_artifacts_can_sort_by_age() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="age",
    )

    assert [(entry["artifact_path"], entry["age_days"]) for entry in stale] == [
        ("benchmark-results/oldest.json", 10),
        ("benchmark-results/recent.json", 2),
        ("benchmark-results/unknown.json", None),
    ]


def test_stale_artifacts_accepts_explicit_age_desc_sort_alias() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="age-desc",
    )

    assert [(entry["artifact_path"], entry["age_days"]) for entry in stale] == [
        ("benchmark-results/oldest.json", 10),
        ("benchmark-results/recent.json", 2),
    ]


def test_stale_artifacts_can_sort_by_age_ascending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="age-asc",
    )

    assert [(entry["artifact_path"], entry["age_days"]) for entry in stale] == [
        ("benchmark-results/recent.json", 2),
        ("benchmark-results/oldest.json", 10),
        ("benchmark-results/unknown.json", None),
    ]


def test_stale_artifacts_can_filter_by_age_bucket() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/month-old.json",
                "status": "legacy",
                "measured_at": "2026-05-20T00:00:00Z",
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
        age_buckets=["30-89d, unknown"],
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/unknown.json",
        "benchmark-results/month-old.json",
    ]


def test_stale_artifacts_can_filter_by_newer_than_days() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/older.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
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
        newer_than_days=7,
        now=datetime(2026, 6, 20, tzinfo=UTC),
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/recent.json"]


def test_stale_artifacts_rejects_negative_newer_than_days() -> None:
    with pytest.raises(ValueError) as exc_info:
        stale_artifacts({"tracks": [], "artifacts": []}, newer_than_days=-1)

    assert str(exc_info.value) == "newer_than_days must be non-negative"


def test_stale_artifacts_can_sort_by_age_bucket_then_age() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/month-old.json",
                "status": "legacy",
                "measured_at": "2026-05-20T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/recent.json",
                "status": "legacy",
                "measured_at": "2026-06-18T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/week-old.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="age-bucket",
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/recent.json",
        "benchmark-results/week-old.json",
        "benchmark-results/month-old.json",
        "benchmark-results/unknown.json",
    ]


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


def test_stale_summary_groups_artifact_size_by_artifact_name() -> None:
    stale = [
        {"artifact_path": "benchmark-results/archive/base-old.json", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/base-old.json", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/qwen.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_artifact_name"] == [
        {
            "artifact_name": "base-old.json",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "artifact_name": "qwen.json",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_artifact_stem() -> None:
    stale = [
        {"artifact_path": "benchmark-results/archive/base-old.json", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/base-old.csv", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/qwen.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_artifact_stem"] == [
        {
            "artifact_stem": "base-old",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "artifact_stem": "qwen",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_artifact_directory() -> None:
    stale = [
        {"artifact_path": "benchmark-results/archive/base-old.json", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/archive/qwen-old.json", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/base-old.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_artifact_dir"] == [
        {
            "artifact_dir": "benchmark-results/archive",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "artifact_dir": "benchmark-results",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_artifact_extension() -> None:
    stale = [
        {"artifact_path": "benchmark-results/base-old.json", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/archive/qwen-old.json", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/raw-audio.wav", "artifact_size_bytes": 15},
        {"artifact_path": "benchmark-results/README", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_artifact_extension"] == [
        {
            "artifact_extension": ".json",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "artifact_extension": ".wav",
            "count": 1,
            "total_size_bytes": 15,
            "total_size": "15 B",
        },
        {
            "artifact_extension": "none",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_status() -> None:
    stale = [
        {"artifact_path": "benchmark-results/legacy-large.json", "status": "legacy", "artifact_size_bytes": 40},
        {"artifact_path": "benchmark-results/blocked.json", "status": "blocked", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/legacy-small.json", "status": "legacy", "artifact_size_bytes": 10},
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_status"] == [
        {
            "status": "legacy",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "status": "blocked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "status": "unknown",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_backend() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-large.json",
            "backend": "faster-whisper",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "backend": "qwen-asr",
            "artifact_size_bytes": 30,
        },
        {
            "artifact_path": "benchmark-results/base-small.json",
            "backend": "faster-whisper",
            "artifact_size_bytes": 10,
        },
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_backend"] == [
        {
            "backend": "faster-whisper",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "backend": "qwen-asr",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "backend": "unknown",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_model() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-large.json",
            "model": "base.en",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "model": "Qwen/Qwen3-ASR-0.6B",
            "artifact_size_bytes": 30,
        },
        {
            "artifact_path": "benchmark-results/base-small.json",
            "model": "base.en",
            "artifact_size_bytes": 10,
        },
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_model"] == [
        {
            "model": "base.en",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "model": "Qwen/Qwen3-ASR-0.6B",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "model": "unknown",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_label() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-large.json",
            "label": "Faster Whisper",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "label": "Qwen MPS",
            "artifact_size_bytes": 30,
        },
        {
            "artifact_path": "benchmark-results/base-small.json",
            "label": "Faster Whisper",
            "artifact_size_bytes": 10,
        },
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_label"] == [
        {
            "label": "Faster Whisper",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "label": "Qwen MPS",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "label": "unknown",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_current_artifact_path() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "current_artifact_path": "benchmark-results/base-current.json",
            "artifact_size_bytes": 20,
        },
        {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/base-older.json",
            "current_artifact_path": "benchmark-results/base-current.json",
            "artifact_size_bytes": 15,
        },
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "current_artifact_path": "benchmark-results/qwen-current.json",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_current_artifact_path"] == [
        {
            "current_artifact_path": "benchmark-results/base-current.json",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "current_artifact_path": "untracked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "current_artifact_path": "benchmark-results/qwen-current.json",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_current_artifact_name() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "current_artifact_path": "benchmark-results/archive/base-current.json",
            "artifact_size_bytes": 20,
        },
        {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/base-older.json",
            "current_artifact_path": "benchmark-results/base-current.json",
            "artifact_size_bytes": 15,
        },
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "current_artifact_path": "benchmark-results/qwen-current.json",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_current_artifact_name"] == [
        {
            "current_artifact_name": "base-current.json",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "current_artifact_name": "untracked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "current_artifact_name": "qwen-current.json",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_current_artifact_stem() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "current_artifact_path": "benchmark-results/archive/base-current.json",
            "artifact_size_bytes": 20,
        },
        {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/base-older.json",
            "current_artifact_path": "benchmark-results/base-current.json",
            "artifact_size_bytes": 15,
        },
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "current_artifact_path": "benchmark-results/qwen-current.json",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_current_artifact_stem"] == [
        {
            "current_artifact_stem": "base-current",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "current_artifact_stem": "untracked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "current_artifact_stem": "qwen-current",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_track_state() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "track_state": "tracked",
            "artifact_size_bytes": 20,
        },
        {"artifact_path": "benchmark-results/untracked.json", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/base-older.json",
            "track_state": "tracked",
            "artifact_size_bytes": 15,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_track_state"] == [
        {
            "track_state": "tracked",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "track_state": "untracked",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_detail_page_path() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 20,
        },
        {
            "artifact_path": "benchmark-results/archive/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 15,
        },
        {"artifact_path": "benchmark-results/raw-audio.wav", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "detail_page_path": "benchmark-results/pages/qwen-old.html",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_detail_page_path"] == [
        {
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "detail_page_path": "missing",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "detail_page_path": "benchmark-results/pages/qwen-old.html",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_detail_page_name() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 20,
        },
        {
            "artifact_path": "benchmark-results/archive/base-old.json",
            "detail_page_path": "benchmark-results/archive/pages/base-old.html",
            "artifact_size_bytes": 15,
        },
        {"artifact_path": "benchmark-results/raw-audio.wav", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "detail_page_path": "benchmark-results/pages/qwen-old.html",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_detail_page_name"] == [
        {
            "detail_page_name": "base-old.html",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "detail_page_name": "missing",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "detail_page_name": "qwen-old.html",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_detail_page_stem() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 20,
        },
        {
            "artifact_path": "benchmark-results/archive/base-old.json",
            "detail_page_path": "benchmark-results/archive/pages/base-old.html",
            "artifact_size_bytes": 15,
        },
        {"artifact_path": "benchmark-results/raw-audio.wav", "artifact_size_bytes": 30},
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "detail_page_path": "benchmark-results/pages/qwen-old.html",
            "artifact_size_bytes": 5,
        },
    ]

    summary = stale_summary(stale)

    assert summary["by_detail_page_stem"] == [
        {
            "detail_page_stem": "base-old",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "detail_page_stem": "missing",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "detail_page_stem": "qwen-old",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_detail_page_directory() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 20,
        },
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "detail_page_path": "benchmark-results/pages/qwen-old.html",
            "artifact_size_bytes": 15,
        },
        {
            "artifact_path": "benchmark-results/archive/raw-audio.wav",
            "detail_page_path": "benchmark-results/archive/pages/raw-audio.html",
            "artifact_size_bytes": 30,
        },
        {"artifact_path": "benchmark-results/missing.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_detail_page_dir"] == [
        {
            "detail_page_dir": "benchmark-results/pages",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "detail_page_dir": "benchmark-results/archive/pages",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "detail_page_dir": "missing",
            "count": 1,
            "total_size_bytes": 5,
            "total_size": "5 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_detail_page_extension() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "detail_page_path": "benchmark-results/pages/base-old.html",
            "artifact_size_bytes": 20,
        },
        {
            "artifact_path": "benchmark-results/qwen-old.json",
            "detail_page_path": "benchmark-results/pages/qwen-old.HTML",
            "artifact_size_bytes": 15,
        },
        {
            "artifact_path": "benchmark-results/report.json",
            "detail_page_path": "benchmark-results/pages/report",
            "artifact_size_bytes": 30,
        },
        {"artifact_path": "benchmark-results/missing.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_detail_page_extension"] == [
        {
            "detail_page_extension": ".html",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
        {
            "detail_page_extension": "none",
            "count": 2,
            "total_size_bytes": 35,
            "total_size": "35 B",
        },
    ]


def test_stale_summary_groups_artifact_size_by_measured_month() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/june-large.json",
            "measured_at": "2026-06-15T00:00:00Z",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/july.json",
            "measured_at": "2026-07-01T00:00:00Z",
            "artifact_size_bytes": 30,
        },
        {
            "artifact_path": "benchmark-results/june-small.json",
            "measured_at": "2026-06-20",
            "artifact_size_bytes": 10,
        },
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_measured_month"] == [
        {
            "measured_month": "2026-06",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "measured_month": "2026-07",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "measured_month": "unknown",
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


def test_stale_artifacts_accepts_explicit_oldest_measured_first_sort_alias() -> None:
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

    stale = stale_artifacts(manifest, sort_by="measured-at-asc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_newest_measured_first() -> None:
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

    stale = stale_artifacts(manifest, sort_by="measured-at-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/newer.json",
        "benchmark-results/older.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_measured_month_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/july-b.json",
                "status": "legacy",
                "measured_at": "2026-07-10T00:00:00Z",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/june.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/july-a.json",
                "status": "legacy",
                "measured_at": "2026-07-01T00:00:00Z",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="measured-month")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/june.json",
        "benchmark-results/july-a.json",
        "benchmark-results/july-b.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_measured_month_descending_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/july-b.json",
                "status": "legacy",
                "measured_at": "2026-07-10T00:00:00Z",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/june.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/july-a.json",
                "status": "legacy",
                "measured_at": "2026-07-01T00:00:00Z",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="measured-month-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/unknown.json",
        "benchmark-results/july-a.json",
        "benchmark-results/july-b.json",
        "benchmark-results/june.json",
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


def test_stale_artifacts_accepts_explicit_path_ascending_sort_alias() -> None:
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

    stale = stale_artifacts(manifest, sort_by="path-asc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/a.json",
        "benchmark-results/z.json",
    ]


def test_stale_artifacts_can_sort_by_artifact_file_name_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-name")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_accepts_explicit_artifact_name_ascending_sort_alias() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-name-asc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_can_sort_by_artifact_directory_then_name() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/b.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/a.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-dir")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/z.json",
        "benchmark-results/archive/a.json",
        "benchmark-results/archive/b.json",
    ]


def test_stale_artifacts_can_sort_by_artifact_extension_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/audio.wav",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/a.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-extension")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/a.json",
        "benchmark-results/z.json",
        "benchmark-results/audio.wav",
    ]


def test_stale_artifacts_can_sort_by_artifact_extension_descending_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/audio.wav",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/a.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="artifact-extension-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/audio.wav",
        "benchmark-results/a.json",
        "benchmark-results/z.json",
    ]


def test_stale_artifacts_can_sort_by_detail_page_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/a.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="detail-page")

    assert [entry["detail_page_path"] for entry in stale] == [
        "benchmark-results/pages/a.html",
        "benchmark-results/pages/z.html",
    ]


def test_stale_artifacts_can_sort_by_detail_page_path_descending() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/a.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/z.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="detail-page-desc")

    assert [entry["detail_page_path"] for entry in stale] == [
        "benchmark-results/pages/z.html",
        "benchmark-results/pages/a.html",
    ]


def test_stale_artifacts_can_sort_by_detail_page_file_name_then_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="detail-page-name")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/archive/qwen-old.json",
    ]


def test_stale_artifacts_can_sort_by_status_slug_and_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z-preview.json",
                "status": "preview",
                "slug": "zeta",
                "artifact_size_bytes": 90,
            },
            {
                "artifact_path": "benchmark-results/b-legacy.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/a-legacy.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "artifact_size_bytes": 100,
            },
        ],
    }

    stale = stale_artifacts(manifest, statuses=["any"], sort_by="status")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/a-legacy.json",
        "benchmark-results/b-legacy.json",
        "benchmark-results/z-preview.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_backend_model_and_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "backend": "faster-whisper",
                "model": "base.en",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "backend": "faster-whisper",
                "model": "base.en",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="backend")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-a.json",
        "benchmark-results/base-b.json",
        "benchmark-results/qwen.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_model_backend_and_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/small.json",
                "status": "legacy",
                "backend": "faster-whisper",
                "model": "small.en",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "backend": "faster-whisper",
                "model": "base.en",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="model")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base.json",
        "benchmark-results/qwen.json",
        "benchmark-results/small.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_label_backend_and_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "label": "Qwen MPS",
                "backend": "qwen-asr",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "label": "Faster Whisper base",
                "backend": "faster-whisper",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "label": "Faster Whisper base",
                "backend": "faster-whisper",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="label")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-a.json",
        "benchmark-results/base-b.json",
        "benchmark-results/qwen.json",
        "benchmark-results/unknown.json",
    ]


def test_stale_artifacts_can_sort_by_slug_and_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/z-preview.json",
                "status": "legacy",
                "slug": "zeta",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="slug")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-a.json",
        "benchmark-results/base-b.json",
        "benchmark-results/untracked.json",
        "benchmark-results/z-preview.json",
    ]


def test_stale_artifacts_can_sort_by_track_state_slug_and_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked-b.json",
                "status": "legacy",
                "slug": "zeta",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked-a.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="track-state")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-old.json",
        "benchmark-results/qwen-old.json",
        "benchmark-results/untracked-a.json",
        "benchmark-results/untracked-b.json",
    ]


def test_stale_artifacts_can_sort_by_current_path_then_artifact_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/untracked.json",
        "benchmark-results/base-a.json",
        "benchmark-results/base-b.json",
        "benchmark-results/qwen-old.json",
    ]


def test_stale_artifacts_can_sort_by_current_path_descending_then_artifact_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-b.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-a.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/base-a.json",
        "benchmark-results/base-b.json",
        "benchmark-results/untracked.json",
    ]


def test_stale_artifacts_can_sort_by_current_artifact_file_name_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/tracks/z-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/tracks/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-name")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/untracked.json",
        "benchmark-results/base-old.json",
        "benchmark-results/small-old.json",
        "benchmark-results/qwen-old.json",
    ]


def test_stale_artifacts_can_sort_by_current_artifact_file_name_descending_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/tracks/z-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/tracks/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-name-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/small-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/untracked.json",
    ]


def test_stale_artifacts_can_sort_by_current_artifact_file_stem_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/tracks/z-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/tracks/base-current.wav"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-stem")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/untracked.json",
        "benchmark-results/base-old.json",
        "benchmark-results/small-old.json",
        "benchmark-results/qwen-old.json",
    ]
    assert [entry["current_artifact_stem"] for entry in stale] == [
        None,
        "base-current",
        "base-current",
        "z-current",
    ]


def test_stale_artifacts_can_sort_by_current_artifact_file_stem_descending_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/tracks/z-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/tracks/base-current.wav"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-stem-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/small-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/untracked.json",
    ]


def test_stale_artifacts_can_sort_by_current_artifact_extension_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.wav"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/current"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-extension")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/small-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/qwen-old.json",
    ]
    assert [entry["current_artifact_extension"] for entry in stale] == ["none", ".json", ".wav"]


def test_stale_artifacts_can_sort_by_current_artifact_extension_descending_then_path() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.wav"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/current"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="current-path-extension-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/base-old.json",
        "benchmark-results/small-old.json",
    ]


def test_stale_artifacts_can_filter_by_current_artifact_file_name() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_names=["tmp/base-current.json"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_current_artifact_file_name_text() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/faster-whisper-base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_name_contains=["WHISPER"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_current_artifact_file_stem() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/archive/base-current.wav"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_stems=["tmp/base-current.json"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_current_artifact_file_stem_text() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.json"},
            {"slug": "base", "artifact_path": "benchmark-results/faster-whisper-base-current.wav"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_stem_contains=["WHISPER"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_current_artifact_extension() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.wav"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
            {"slug": "small", "artifact_path": "benchmark-results/current"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/small-old.json",
                "status": "legacy",
                "slug": "small",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_extensions=["wav, none"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/qwen-old.json",
        "benchmark-results/small-old.json",
    ]


def test_stale_artifacts_can_filter_by_current_artifact_extension_text() -> None:
    manifest = {
        "tracks": [
            {"slug": "qwen", "artifact_path": "benchmark-results/qwen-current.wav"},
            {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "slug": "qwen",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_path_extension_contains=["WA"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/qwen-old.json"]


def test_stale_artifacts_can_filter_by_artifact_file_name() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_names=["base-old.json"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/base-old.json",
    ]


def test_stale_artifacts_artifact_file_name_filter_accepts_paths() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_names=["tmp/base-old.json"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_artifact_file_name_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper-base.en-int8-2026-06-15.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/faster-whisper-small.en-int8-2026-06-10.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-mps-2026-06-20.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_name_contains=["WHISPER"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/faster-whisper-base.en-int8-2026-06-15.json",
        "benchmark-results/archive/faster-whisper-small.en-int8-2026-06-10.json",
    ]


def test_stale_artifacts_can_filter_by_artifact_extension() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/raw-audio.wav",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/README",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_extensions=["json, none"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-old.json",
        "benchmark-results/README",
    ]
    assert [entry["artifact_extension"] for entry in stale] == [".json", "none"]


def test_stale_artifacts_can_filter_by_artifact_extension_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/raw-audio.wav",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/README",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, artifact_extension_contains=["JS, none"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/base-old.json",
        "benchmark-results/README",
    ]


def test_stale_artifacts_can_filter_by_detail_page_path() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        detail_pages=["benchmark-results/pages/base-old.html"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_detail_page_path_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        detail_page_contains=["PAGES/BASE"],
    )

    assert [entry["detail_page_path"] for entry in stale] == [
        "benchmark-results/pages/base-old.html"
    ]


def test_stale_artifacts_can_filter_by_detail_page_file_name() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, detail_page_names=["base-old.html"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/base-old.json",
        "benchmark-results/base-old.json",
    ]


def test_stale_artifacts_detail_page_file_name_filter_accepts_paths() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, detail_page_names=["tmp/base-old.html"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_detail_page_file_name_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper-base.en-int8-2026-06-15.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/faster-whisper-small.en-int8-2026-06-10.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-mps-2026-06-20.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, detail_page_name_contains=["WHISPER"])

    assert [entry["detail_page_path"] for entry in stale] == [
        "benchmark-results/pages/faster-whisper-base.en-int8-2026-06-15.html",
        "benchmark-results/pages/faster-whisper-small.en-int8-2026-06-10.html",
    ]


def test_stale_artifacts_can_filter_by_detail_page_file_stem() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, detail_page_stems=["tmp/base-old.html"])

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_detail_page_file_stem_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper-base.en-int8-2026-06-15.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/qwen-mps-2026-06-20.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, detail_page_stem_contains=["WHISPER"])

    assert [entry["detail_page_stem"] for entry in stale] == [
        "faster-whisper-base.en-int8-2026-06-15"
    ]


def test_stale_artifacts_can_filter_by_detail_page_directory() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.txt",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        detail_page_dirs=["benchmark-results/pages"],
        detail_page_dir_contains=["PAGES"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]


def test_stale_artifacts_can_filter_by_detail_page_extension() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.txt",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        statuses=["any"],
        detail_page_extensions=["html"],
        detail_page_extension_contains=["HT"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]
    assert stale[0]["detail_page_extension"] == ".html"


def test_stale_artifacts_can_sort_by_detail_page_directory_and_extension() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/qwen-old.txt",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    by_dir = stale_artifacts(manifest, statuses=["any"], sort_by="detail-page-dir-desc")
    by_extension = stale_artifacts(manifest, statuses=["any"], sort_by="detail-page-extension-desc")

    assert [entry["artifact_path"] for entry in by_dir] == [
        "benchmark-results/base-old.json",
        "benchmark-results/qwen-old.txt",
    ]
    assert [entry["artifact_path"] for entry in by_extension] == [
        "benchmark-results/base-old.json",
        "benchmark-results/qwen-old.txt",
    ]


def test_stale_artifacts_rejects_unknown_sort_order() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, sort_by="unknown")
    except ValueError as error:
        assert str(error).startswith("sort_by must be one of: size, size-desc, size-asc")
        assert "artifact-stem-asc" in str(error)
        assert "detail-page-extension-asc" in str(error)
        assert "current-path-extension-asc" in str(error)
        assert str(error).endswith("age-bucket, age-bucket-asc, age-bucket-desc")
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


def test_stale_artifacts_can_filter_by_measured_after_timestamp() -> None:
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
                "artifact_path": "benchmark-results/new.json",
                "status": "legacy",
                "measured_at": "2026-06-25T00:00:00Z",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, measured_after="2026-06-20")

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/new.json"]


def test_stale_artifacts_can_filter_by_measured_window() -> None:
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
                "artifact_path": "benchmark-results/window.json",
                "status": "legacy",
                "measured_at": "2026-06-15T00:00:00Z",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/new.json",
                "status": "legacy",
                "measured_at": "2026-06-20T00:00:00Z",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(
        manifest,
        measured_after="2026-06-12T00:00:00Z",
        measured_before="2026-06-18T00:00:00Z",
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/window.json"]


def test_stale_artifacts_can_filter_by_measured_month() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/june.json",
                "status": "legacy",
                "measured_at": "2026-06-30T23:30:00-02:00",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/july.json",
                "status": "legacy",
                "measured_at": "2026-07-10T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/unknown.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    stale = stale_artifacts(manifest, measured_months=["2026-07"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/june.json",
        "benchmark-results/july.json",
    ]


def test_stale_artifacts_rejects_invalid_measured_month_filter() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, measured_months=["2026"])
    except ValueError as error:
        assert str(error) == "measured_month values must use YYYY-MM"
    else:
        raise AssertionError("invalid measured-month filters should fail")


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


def test_stale_artifacts_rejects_invalid_measured_after_timestamp() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, measured_after="not a timestamp")
    except ValueError as error:
        assert str(error) == "measured_after must be an ISO timestamp or date"
    else:
        raise AssertionError("invalid measured-after filters should fail")


def test_stale_artifacts_rejects_empty_measured_window() -> None:
    try:
        stale_artifacts(
            {"tracks": [], "artifacts": []},
            measured_after="2026-06-20T00:00:00Z",
            measured_before="2026-06-20T00:00:00Z",
        )
    except ValueError as error:
        assert str(error) == "measured_after must be earlier than the effective measured-before cutoff"
    else:
        raise AssertionError("empty measured windows should fail")


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


def test_stale_artifacts_can_filter_by_track_slug_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/faster-whisper-base.json",
                "status": "legacy",
                "slug": "faster-whisper-base",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/faster-whisper-small.json",
                "status": "legacy",
                "slug": "faster-whisper-small",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen.json",
                "status": "legacy",
                "slug": "qwen-mps",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 40,
            },
        ],
    }

    stale = stale_artifacts(manifest, slug_contains=["WHISPER"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/faster-whisper-small.json",
        "benchmark-results/faster-whisper-base.json",
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


def test_stale_artifacts_can_filter_by_current_artifact_path_text() -> None:
    manifest = {
        "tracks": [
            {
                "slug": "base",
                "artifact_path": "benchmark-results/faster-whisper-base-current.json",
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
        current_path_contains=["WHISPER"],
    )

    assert [entry["artifact_path"] for entry in stale] == ["benchmark-results/base-old.json"]
    assert stale[0]["current_artifact_path"] == "benchmark-results/faster-whisper-base-current.json"


def test_stale_artifacts_can_filter_by_track_state() -> None:
    manifest = {
        "tracks": [
            {
                "slug": "base",
                "artifact_path": "benchmark-results/base-current.json",
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
            {
                "artifact_path": "benchmark-results/untracked.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
    }

    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, track_state="tracked")] == [
        "benchmark-results/base-old.json"
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, track_state="untracked")] == [
        "benchmark-results/untracked.json",
        "benchmark-results/qwen-old.json",
    ]


def test_stale_artifacts_rejects_unknown_track_state() -> None:
    try:
        stale_artifacts({"tracks": [], "artifacts": []}, track_state="detached")
    except ValueError as error:
        assert str(error) == "track_state must be one of: any, tracked, untracked"
    else:
        raise AssertionError("unknown track state filters should fail")


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


def test_stale_artifacts_can_filter_by_artifact_path_text() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/faster-whisper-base-old.json",
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
        artifact_path_contains=["ARCHIVE/FASTER"],
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/faster-whisper-base-old.json"
    ]


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
        "benchmark-results/older.json [demo] status unknown measured 2026-06-10T00:00:00Z (unknown; 75 B); "
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


def test_render_text_includes_status_for_mixed_cleanup_reviews() -> None:
    rendered = render_text(
        [
            {
                "artifact_path": "benchmark-results/blocked.json",
                "slug": "demo",
                "status": "blocked",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 75,
            }
        ]
    )

    assert "benchmark-results/blocked.json [demo] status blocked measured" in rendered


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


def test_render_paths_can_use_null_separators_for_safe_cleanup() -> None:
    rendered = render_paths(
        [
            {"artifact_path": "benchmark-results/oldest.json"},
            {"artifact_path": "benchmark-results/old.json"},
        ],
        separator="\0",
    )

    assert rendered == "benchmark-results/oldest.json\0benchmark-results/old.json"


def test_render_paths_can_output_absolute_paths(tmp_path) -> None:
    docs_root = tmp_path / "docs"

    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/oldest.json",
                "detail_page_path": "benchmark-results/pages/oldest.html",
            }
        ],
        include_detail_pages=True,
        output_root=docs_root,
    )

    assert rendered == (
        f"{docs_root / 'benchmark-results' / 'oldest.json'}\n"
        f"{docs_root / 'benchmark-results' / 'pages' / 'oldest.html'}"
    )


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


def test_render_paths_deduplicates_repeated_detail_pages() -> None:
    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "detail_page_path": "benchmark-results/pages/base-old.html",
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "detail_page_path": "benchmark-results/pages/base-old.html",
            },
        ],
        include_detail_pages=True,
    )

    assert rendered == (
        "benchmark-results/archive/base-old.json\n"
        "benchmark-results/pages/base-old.html\n"
        "benchmark-results/base-old.json"
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


def test_render_paths_deduplicates_detail_pages_only() -> None:
    rendered = render_paths(
        [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "detail_page_path": "benchmark-results/pages/base-old.html",
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "detail_page_path": "benchmark-results/pages/base-old.html",
            },
        ],
        detail_pages_only=True,
    )

    assert rendered == "benchmark-results/pages/base-old.html"


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


def test_render_paths_can_filter_to_missing_paths(tmp_path) -> None:
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
        missing_root=docs_root,
    )

    assert rendered == (
        "benchmark-results/missing.json\n"
        "benchmark-results/pages/missing.html"
    )


def test_render_summary_groups_stale_artifacts_by_slug() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "slug": "base",
                "backend": "faster-whisper",
                "model": "base.en",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/untracked.json",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/base-older.json",
                "slug": "base",
                "backend": "faster-whisper",
                "model": "base.en",
                "artifact_size_bytes": 15,
            },
        ]
    )

    assert rendered == (
        "Found 3 stale benchmark artifacts (65 B, 65 bytes).\n"
        "- base: 2 artifacts (35 B, 35 bytes)\n"
        "- untracked: 1 artifact (30 B, 30 bytes)\n"
        "By artifact name:\n"
        "- untracked.json: 1 artifact (30 B, 30 bytes)\n"
        "- base-old.json: 1 artifact (20 B, 20 bytes)\n"
        "- base-older.json: 1 artifact (15 B, 15 bytes)\n"
        "By artifact stem:\n"
        "- untracked: 1 artifact (30 B, 30 bytes)\n"
        "- base-old: 1 artifact (20 B, 20 bytes)\n"
        "- base-older: 1 artifact (15 B, 15 bytes)\n"
        "By artifact directory:\n"
        "- benchmark-results: 3 artifacts (65 B, 65 bytes)\n"
        "By artifact extension:\n"
        "- .json: 3 artifacts (65 B, 65 bytes)\n"
        "By status:\n"
        "- unknown: 3 artifacts (65 B, 65 bytes)\n"
        "By backend:\n"
        "- faster-whisper: 2 artifacts (35 B, 35 bytes)\n"
        "- qwen-asr: 1 artifact (30 B, 30 bytes)\n"
        "By model:\n"
        "- base.en: 2 artifacts (35 B, 35 bytes)\n"
        "- Qwen/Qwen3-ASR-0.6B: 1 artifact (30 B, 30 bytes)\n"
        "By current artifact:\n"
        "- untracked: 3 artifacts (65 B, 65 bytes)\n"
        "By current artifact name:\n"
        "- untracked: 3 artifacts (65 B, 65 bytes)\n"
        "By current artifact stem:\n"
        "- untracked: 3 artifacts (65 B, 65 bytes)\n"
        "By current artifact directory:\n"
        "- untracked: 3 artifacts (65 B, 65 bytes)\n"
        "By current artifact extension:\n"
        "- none: 3 artifacts (65 B, 65 bytes)\n"
        "By track state:\n"
        "- untracked: 3 artifacts (65 B, 65 bytes)\n"
        "By detail page:\n"
        "- missing: 3 artifacts (65 B, 65 bytes)\n"
            "By detail page name:\n"
            "- missing: 3 artifacts (65 B, 65 bytes)\n"
            "By detail page stem:\n"
            "- missing: 3 artifacts (65 B, 65 bytes)\n"
            "By detail page directory:\n"
        "- missing: 3 artifacts (65 B, 65 bytes)\n"
        "By detail page extension:\n"
        "- none: 3 artifacts (65 B, 65 bytes)\n"
        "By measured month:\n"
        "- unknown: 3 artifacts (65 B, 65 bytes)\n"
        "By age bucket:\n"
        "- unknown: 3 artifacts (65 B, 65 bytes)"
    )


def test_render_summary_includes_known_label_totals() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "label": "Faster Whisper",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-older.json",
                "label": "Faster Whisper",
                "artifact_size_bytes": 15,
            },
        ]
    )

    assert (
        "By label:\n"
        "- Faster Whisper: 2 artifacts (35 B, 35 bytes)"
    ) in rendered


def test_render_summary_can_focus_on_selected_groups() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "slug": "base",
                "status": "legacy",
                "backend": "faster-whisper",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/qwen-old.json",
                "slug": "qwen",
                "status": "blocked",
                "backend": "qwen-asr",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["status"],
    )

    assert rendered == (
        "Found 2 stale benchmark artifacts (30 B, 30 bytes).\n"
        "By status:\n"
        "- legacy: 1 artifact (20 B, 20 bytes)\n"
        "- blocked: 1 artifact (10 B, 10 bytes)"
    )


def test_render_summary_can_focus_on_artifact_directory() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/base-old.json",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["artifact-dir"],
    )

    assert rendered == (
        "Found 2 stale benchmark artifacts (30 B, 30 bytes).\n"
        "By artifact directory:\n"
        "- benchmark-results/archive: 1 artifact (20 B, 20 bytes)\n"
        "- benchmark-results: 1 artifact (10 B, 10 bytes)"
    )


def test_render_summary_can_focus_on_artifact_extension() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/raw-audio.wav",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["artifact-extension"],
    )

    assert rendered == (
        "Found 2 stale benchmark artifacts (30 B, 30 bytes).\n"
        "By artifact extension:\n"
        "- .json: 1 artifact (20 B, 20 bytes)\n"
        "- .wav: 1 artifact (10 B, 10 bytes)"
    )


def test_render_summary_can_focus_on_current_artifact_extension() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "current_artifact_path": "benchmark-results/base-current.json",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/raw-audio-old.json",
                "current_artifact_path": "benchmark-results/raw-audio-current.wav",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["current-artifact-extension"],
    )

    assert rendered == (
        "Found 2 stale benchmark artifacts (30 B, 30 bytes).\n"
        "By current artifact extension:\n"
        "- .json: 1 artifact (20 B, 20 bytes)\n"
        "- .wav: 1 artifact (10 B, 10 bytes)"
    )


def test_render_summary_can_focus_on_current_artifact_stem() -> None:
    rendered = render_summary(
        [
            {
                "artifact_path": "benchmark-results/base-old.json",
                "current_artifact_path": "benchmark-results/base-current.json",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/raw-audio-old.json",
                "current_artifact_path": "benchmark-results/raw-audio-current.wav",
                "artifact_size_bytes": 10,
            },
        ],
        groups=["current-artifact-stem"],
    )

    assert rendered == (
        "Found 2 stale benchmark artifacts (30 B, 30 bytes).\n"
        "By current artifact stem:\n"
        "- base-current: 1 artifact (20 B, 20 bytes)\n"
        "- raw-audio-current: 1 artifact (10 B, 10 bytes)"
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


def test_main_paths_only_can_use_null_separators(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/old-a.json",
                    "status": "legacy",
                    "artifact_size_bytes": 20,
                },
                {
                    "artifact_path": "benchmark-results/old-b.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--paths-only", "--null"]) == 0

    assert capsys.readouterr().out == "benchmark-results/old-a.json\0benchmark-results/old-b.json"


def test_main_paths_only_can_output_absolute_paths(monkeypatch, tmp_path, capsys) -> None:
    results_dir = tmp_path / "docs" / "benchmark-results"
    results_dir.mkdir(parents=True)
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

    assert report_module.main(["--results-dir", str(results_dir), "--paths-only", "--absolute-paths"]) == 0

    assert capsys.readouterr().out == f"{results_dir / 'old.json'}\n"


def test_main_paths_only_can_read_existing_manifest(monkeypatch, tmp_path, capsys) -> None:
    def fail_build_manifest(*args, **kwargs):
        raise AssertionError("--manifest should skip manifest rebuild")

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "tracks": [{"slug": "base", "artifact_path": "benchmark-results/current.json"}],
                "artifacts": [
                    {
                        "artifact_path": "benchmark-results/current.json",
                        "slug": "base",
                        "status": "validated",
                        "artifact_size_bytes": 100,
                    },
                    {
                        "artifact_path": "benchmark-results/old.json",
                        "slug": "base",
                        "status": "legacy",
                        "artifact_size_bytes": 10,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(report_module, "build_manifest", fail_build_manifest)

    assert report_module.main(["--manifest", str(manifest_path), "--paths-only"]) == 0

    assert capsys.readouterr().out == "benchmark-results/old.json\n"


def test_main_rejects_non_object_existing_manifest(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        report_module.main(["--manifest", str(manifest_path), "--paths-only"])


def test_main_null_paths_only_does_not_emit_newline_for_no_matches(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {"tracks": [], "artifacts": []},
    )

    assert report_module.main(["--paths-only", "--null"]) == 0

    assert capsys.readouterr().out == ""


def test_main_paths_only_does_not_emit_newline_for_no_matches(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {"tracks": [], "artifacts": []},
    )

    assert report_module.main(["--paths-only"]) == 0

    assert capsys.readouterr().out == ""


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


def test_main_paths_only_can_filter_to_missing_paths(monkeypatch, tmp_path, capsys) -> None:
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
                "--missing-paths-only",
            ]
        )
        == 0
    )

    assert capsys.readouterr().out == (
        "benchmark-results/missing.json\nbenchmark-results/pages/missing.html\n"
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


def test_main_rejects_absolute_paths_without_paths_only() -> None:
    try:
        report_module.main(["--absolute-paths"])
    except ValueError as error:
        assert str(error) == "--absolute-paths requires --paths-only"
    else:
        raise AssertionError("--absolute-paths should require --paths-only")


def test_main_rejects_null_separator_without_paths_only() -> None:
    try:
        report_module.main(["--null"])
    except ValueError as error:
        assert str(error) == "--null requires --paths-only"
    else:
        raise AssertionError("--null should require --paths-only")


def test_main_rejects_existing_paths_only_without_paths_only() -> None:
    try:
        report_module.main(["--existing-paths-only"])
    except ValueError as error:
        assert str(error) == "--existing-paths-only requires --paths-only"
    else:
        raise AssertionError("--existing-paths-only should require --paths-only")


def test_main_rejects_missing_paths_only_without_paths_only() -> None:
    try:
        report_module.main(["--missing-paths-only"])
    except ValueError as error:
        assert str(error) == "--missing-paths-only requires --paths-only"
    else:
        raise AssertionError("--missing-paths-only should require --paths-only")


def test_main_rejects_existing_and_missing_paths_only_together() -> None:
    try:
        report_module.main(["--paths-only", "--existing-paths-only", "--missing-paths-only"])
    except ValueError as error:
        assert str(error) == "--existing-paths-only cannot be combined with --missing-paths-only"
    else:
        raise AssertionError("existing and missing path modes should be mutually exclusive")


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


def test_main_fail_on_stale_honors_newer_than_days_filter(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 20, tzinfo=tz)

    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/old.json",
                    "status": "legacy",
                    "measured_at": "2026-06-01T00:00:00Z",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )
    monkeypatch.setattr(report_module, "datetime", FixedDateTime)

    assert report_module.main(["--fail-on-stale", "--newer-than-days", "7"]) == 0
    assert report_module.main(["--fail-on-stale", "--newer-than-days", "30"]) == 1


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


def test_main_fail_on_stale_honors_status_contains_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/blocked.json",
                    "status": "blocked-manual-review",
                    "artifact_size_bytes": 10,
                }
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--status", "any", "--status-contains", "legacy"]) == 0
    assert report_module.main(["--fail-on-stale", "--status", "any", "--status-contains", "review"]) == 1


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


def test_main_fail_on_stale_honors_current_path_text_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [
                {"slug": "base", "artifact_path": "benchmark-results/faster-whisper-base-current.json"},
            ],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/faster-whisper-base-current.json",
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

    assert report_module.main(["--fail-on-stale", "--current-path-contains", "qwen"]) == 0
    assert report_module.main(["--fail-on-stale", "--current-path-contains", "whisper"]) == 1


def test_main_fail_on_stale_honors_track_state_filter(monkeypatch) -> None:
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

    assert report_module.main(["--fail-on-stale", "--track-state", "untracked"]) == 0
    assert report_module.main(["--fail-on-stale", "--track-state", "tracked"]) == 1


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


def test_main_fail_on_stale_honors_artifact_path_text_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/archive/faster-whisper-base-old.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--artifact-path-contains", "qwen"]) == 0
    assert report_module.main(["--fail-on-stale", "--artifact-path-contains", "archive"]) == 1


def test_main_fail_on_stale_honors_artifact_name_text_filter(monkeypatch) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/faster-whisper-base-old.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--fail-on-stale", "--artifact-name-contains", "qwen"]) == 0
    assert report_module.main(["--fail-on-stale", "--artifact-name-contains", "whisper"]) == 1


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
    assert report_module.main(["--fail-on-stale", "--status", "legacy,blocked"]) == 1


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


def test_main_json_lines_honors_limit(monkeypatch, capsys) -> None:
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

    assert report_module.main(["--json-lines", "--limit", "1"]) == 0

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["artifact_path"] == "benchmark-results/large.json"


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


def test_main_paths_only_can_filter_by_artifact_directory(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/archive/base.json",
                    "status": "legacy",
                    "artifact_size_bytes": 20,
                },
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--paths-only", "--artifact-dir", "benchmark-results/archive"]) == 0

    assert capsys.readouterr().out == "benchmark-results/archive/base.json\n"


def test_main_paths_only_can_filter_by_detail_page_directory(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "artifact_size_bytes": 20,
                },
                {
                    "artifact_path": "benchmark-results/readme.txt",
                    "status": "legacy",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--paths-only", "--detail-page-dir", "benchmark-results/pages"]) == 0

    assert capsys.readouterr().out == "benchmark-results/base.json\n"


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


def test_main_total_bytes_only_reports_total_matching_bytes_before_limit(monkeypatch, capsys) -> None:
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

    assert report_module.main(["--total-bytes-only", "--label", "whisper", "--limit", "1"]) == 0

    assert capsys.readouterr().out == "100\n"


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
                    "model": "base.en",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "slug": "base",
                    "model": "base.en",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--summary-only", "--limit", "1"]) == 0

    assert capsys.readouterr().out == (
        "Found 2 stale benchmark artifacts (100 B, 100 bytes).\n"
        "- base: 2 artifacts (100 B, 100 bytes)\n"
        "By artifact name:\n"
        "- large.json: 1 artifact (90 B, 90 bytes)\n"
        "- small.json: 1 artifact (10 B, 10 bytes)\n"
        "By artifact stem:\n"
        "- large: 1 artifact (90 B, 90 bytes)\n"
        "- small: 1 artifact (10 B, 10 bytes)\n"
        "By artifact directory:\n"
        "- benchmark-results: 2 artifacts (100 B, 100 bytes)\n"
        "By artifact extension:\n"
        "- .json: 2 artifacts (100 B, 100 bytes)\n"
        "By status:\n"
        "- legacy: 2 artifacts (100 B, 100 bytes)\n"
        "By backend:\n"
        "- unknown: 2 artifacts (100 B, 100 bytes)\n"
        "By model:\n"
        "- base.en: 2 artifacts (100 B, 100 bytes)\n"
        "By current artifact:\n"
        "- untracked: 2 artifacts (100 B, 100 bytes)\n"
        "By current artifact name:\n"
        "- untracked: 2 artifacts (100 B, 100 bytes)\n"
        "By current artifact stem:\n"
        "- untracked: 2 artifacts (100 B, 100 bytes)\n"
        "By current artifact directory:\n"
        "- untracked: 2 artifacts (100 B, 100 bytes)\n"
        "By current artifact extension:\n"
        "- none: 2 artifacts (100 B, 100 bytes)\n"
        "By track state:\n"
        "- untracked: 2 artifacts (100 B, 100 bytes)\n"
        "By detail page:\n"
        "- benchmark-results/pages/large.html: 1 artifact (90 B, 90 bytes)\n"
        "- benchmark-results/pages/small.html: 1 artifact (10 B, 10 bytes)\n"
            "By detail page name:\n"
            "- large.html: 1 artifact (90 B, 90 bytes)\n"
            "- small.html: 1 artifact (10 B, 10 bytes)\n"
            "By detail page stem:\n"
            "- large: 1 artifact (90 B, 90 bytes)\n"
            "- small: 1 artifact (10 B, 10 bytes)\n"
            "By detail page directory:\n"
        "- benchmark-results/pages: 2 artifacts (100 B, 100 bytes)\n"
        "By detail page extension:\n"
        "- .html: 2 artifacts (100 B, 100 bytes)\n"
        "By measured month:\n"
        "- unknown: 2 artifacts (100 B, 100 bytes)\n"
        "By age bucket:\n"
        "- unknown: 2 artifacts (100 B, 100 bytes)\n"
    )


def test_main_summary_only_accepts_selected_groups(monkeypatch, capsys) -> None:
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
                    "model": "base.en",
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "slug": "base",
                    "model": "base.en",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--summary-only", "--summary-group", "model,detail-page-name"]) == 0

    assert capsys.readouterr().out == (
        "Found 2 stale benchmark artifacts (100 B, 100 bytes).\n"
        "By model:\n"
        "- base.en: 2 artifacts (100 B, 100 bytes)\n"
        "By detail page name:\n"
        "- large.html: 1 artifact (90 B, 90 bytes)\n"
        "- small.html: 1 artifact (10 B, 10 bytes)\n"
    )


def test_main_summary_only_can_limit_rows_per_group(monkeypatch, capsys) -> None:
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
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/qwen.json",
                    "status": "legacy",
                    "slug": "qwen",
                    "artifact_size_bytes": 20,
                },
                {
                    "artifact_path": "benchmark-results/small.json",
                    "status": "legacy",
                    "slug": "small",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--summary-only", "--summary-group", "slug", "--summary-limit", "1"]) == 0

    assert capsys.readouterr().out == (
        "Found 3 stale benchmark artifacts (120 B, 120 bytes).\n"
        "- base: 1 artifact (90 B, 90 bytes)\n"
        "... 2 more buckets (30 B, 30 bytes) omitted by --summary-limit.\n"
    )


def test_main_json_summary_reports_selected_groups(monkeypatch, capsys) -> None:
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
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/qwen.json",
                    "status": "legacy",
                    "slug": "qwen",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--json-summary", "--summary-group", "slug", "--summary-limit", "1"]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "count": 2,
        "total_size_bytes": 100,
        "total_size": "100 B",
        "by_slug": [
            {
                "slug": "base",
                "count": 1,
                "total_size_bytes": 90,
                "total_size": "90 B",
            }
        ],
        "by_slug_omitted": {
            "count": 1,
            "total_size_bytes": 10,
            "total_size": "10 B",
        },
    }


def test_main_json_summary_can_include_group_share_percentages(monkeypatch, capsys) -> None:
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
                    "artifact_size_bytes": 90,
                },
                {
                    "artifact_path": "benchmark-results/qwen.json",
                    "status": "legacy",
                    "slug": "qwen",
                    "artifact_size_bytes": 10,
                },
            ],
        },
    )

    assert report_module.main(["--json-summary", "--summary-group", "slug", "--summary-share"]) == 0

    output = json.loads(capsys.readouterr().out)

    assert output["by_slug"][0]["slug"] == "base"
    assert output["by_slug"][0]["count_share_percent"] == 50.0
    assert output["by_slug"][0]["size_share_percent"] == 90.0


def test_main_csv_reports_limited_artifact_rows(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [
                {"slug": "base", "artifact_path": "benchmark-results/base-current.json"},
            ],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/large.json",
                    "status": "legacy",
                    "slug": "base",
                    "label": "Faster, Whisper",
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

    assert report_module.main(["--csv", "--limit", "1"]) == 0

    assert capsys.readouterr().out == (
        "artifact_path,artifact_name,artifact_stem,artifact_dir,artifact_extension,slug,label,backend,model,status,measured_at,measured_month,age_days,age_bucket,age,current_artifact_path,current_artifact_name,current_artifact_stem,current_artifact_dir,current_artifact_extension,track_state,detail_page_path,detail_page_name,detail_page_stem,detail_page_dir,detail_page_extension,artifact_size_bytes,artifact_size\r\n"
        'benchmark-results/large.json,large.json,large,benchmark-results,.json,base,"Faster, Whisper",,,legacy,,unknown,,unknown,unknown,benchmark-results/base-current.json,base-current.json,base-current,benchmark-results,.json,tracked,benchmark-results/pages/large.html,large.html,large,benchmark-results/pages,.html,90,90 B\r\n'
    )


def test_main_output_writes_rendered_report_without_stdout(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(
        report_module,
        "build_manifest",
        lambda _results_dir, _tracks: {
            "tracks": [],
            "artifacts": [
                {
                    "artifact_path": "benchmark-results/base.json",
                    "status": "legacy",
                    "artifact_size_bytes": 90,
                }
            ],
        },
    )

    output_path = tmp_path / "cleanup" / "stale.txt"

    assert report_module.main(["--paths-only", "--output", str(output_path)]) == 0

    assert capsys.readouterr().out == ""
    assert output_path.read_text(encoding="utf-8") == "benchmark-results/base.json\n"


def test_main_null_paths_output_preserves_null_separators(monkeypatch, tmp_path, capsys) -> None:
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

    output_path = tmp_path / "stale.paths"

    assert report_module.main(["--paths-only", "--null", "--output", str(output_path)]) == 0

    assert capsys.readouterr().out == ""
    assert output_path.read_text(encoding="utf-8") == (
        "benchmark-results/large.json\0benchmark-results/small.json"
    )


def test_main_rejects_paths_only_with_json() -> None:
    try:
        report_module.main(["--paths-only", "--json"])
    except ValueError as error:
        assert str(error) == "--json and --paths-only cannot be used together"
    else:
        raise AssertionError("paths-only JSON output should be rejected")


def test_main_rejects_negative_limit_before_building_manifest(monkeypatch) -> None:
    def fail_build_manifest(*args, **kwargs):
        raise AssertionError("negative --limit should be rejected before manifest build")

    monkeypatch.setattr(report_module, "build_manifest", fail_build_manifest)

    try:
        report_module.main(["--limit=-1"])
    except ValueError as error:
        assert str(error) == "limit must be non-negative"
    else:
        raise AssertionError("negative --limit should be rejected")


def test_main_rejects_json_lines_with_other_output_modes() -> None:
    for args, expected in [
        (["--json-lines", "--json"], "--json-lines and --json cannot be used together"),
        (["--json-lines", "--json-summary"], "--json-lines and --json-summary cannot be used together"),
        (["--json-lines", "--paths-only"], "--json-lines and --paths-only cannot be used together"),
        (["--json-lines", "--count-only"], "--count-only and --json-lines cannot be used together"),
        (["--json-lines", "--total-bytes-only"], "--total-bytes-only and --json-lines cannot be used together"),
        (["--json-lines", "--summary-only"], "--summary-only and --json-lines cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")


def test_main_rejects_csv_with_other_output_modes() -> None:
    for args, expected in [
        (["--csv", "--json"], "--csv and --json cannot be used together"),
        (["--csv", "--json-summary"], "--csv and --json-summary cannot be used together"),
        (["--csv", "--json-lines"], "--csv and --json-lines cannot be used together"),
        (["--csv", "--paths-only"], "--csv and --paths-only cannot be used together"),
        (["--csv", "--count-only"], "--count-only and --csv cannot be used together"),
        (["--csv", "--total-bytes-only"], "--total-bytes-only and --csv cannot be used together"),
        (["--csv", "--summary-only"], "--summary-only and --csv cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")


def test_main_rejects_count_only_with_structured_output_modes() -> None:
    try:
        report_module.main(["--count-only", "--json"])
    except ValueError as error:
        assert str(error) == "--count-only and --json cannot be used together"
    else:
        raise AssertionError("count-only JSON output should be rejected")

    try:
        report_module.main(["--count-only", "--json-summary"])
    except ValueError as error:
        assert str(error) == "--count-only and --json-summary cannot be used together"
    else:
        raise AssertionError("count-only JSON summary output should be rejected")

    try:
        report_module.main(["--count-only", "--paths-only"])
    except ValueError as error:
        assert str(error) == "--count-only and --paths-only cannot be used together"
    else:
        raise AssertionError("count-only path output should be rejected")


def test_main_rejects_total_bytes_only_with_other_output_modes() -> None:
    for args, expected in [
        (["--total-bytes-only", "--json"], "--total-bytes-only and --json cannot be used together"),
        (
            ["--total-bytes-only", "--json-summary"],
            "--total-bytes-only and --json-summary cannot be used together",
        ),
        (["--total-bytes-only", "--paths-only"], "--total-bytes-only and --paths-only cannot be used together"),
        (["--total-bytes-only", "--count-only"], "--total-bytes-only and --count-only cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")


def test_main_rejects_summary_only_with_structured_output_modes() -> None:
    for args, expected in [
        (["--summary-only", "--json"], "--summary-only and --json cannot be used together"),
        (["--summary-only", "--json-summary"], "--summary-only and --json-summary cannot be used together"),
        (["--summary-only", "--paths-only"], "--summary-only and --paths-only cannot be used together"),
        (["--summary-only", "--count-only"], "--summary-only and --count-only cannot be used together"),
        (["--summary-only", "--total-bytes-only"], "--summary-only and --total-bytes-only cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")


def test_main_rejects_markdown_with_other_output_modes() -> None:
    for args, expected in [
        (["--markdown", "--json"], "--markdown and --json cannot be used together"),
        (["--markdown", "--json-summary"], "--markdown and --json-summary cannot be used together"),
        (["--markdown", "--json-lines"], "--markdown and --json-lines cannot be used together"),
        (["--markdown", "--csv"], "--markdown and --csv cannot be used together"),
        (["--markdown", "--paths-only"], "--markdown and --paths-only cannot be used together"),
        (["--markdown", "--count-only"], "--markdown and --count-only cannot be used together"),
        (["--markdown", "--total-bytes-only"], "--markdown and --total-bytes-only cannot be used together"),
        (["--markdown", "--summary-only"], "--markdown and --summary-only cannot be used together"),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should be rejected")


def test_main_rejects_summary_group_without_summary_only() -> None:
    try:
        report_module.main(["--summary-group", "model"])
    except ValueError as error:
        assert str(error) == "--summary-group requires --summary-only, --json-summary, or --summary-csv"
    else:
        raise AssertionError("--summary-group without --summary-only should be rejected")


def test_main_rejects_summary_limit_without_summary_only() -> None:
    try:
        report_module.main(["--summary-limit", "1"])
    except ValueError as error:
        assert str(error) == "--summary-limit requires --summary-only, --json-summary, or --summary-csv"
    else:
        raise AssertionError("--summary-limit without --summary-only should be rejected")


def test_main_rejects_summary_range_filters_without_summary_output() -> None:
    for args, expected in [
        (
            ["--summary-min-count", "1"],
            "--summary-min-count requires --summary-only, --json-summary, or --summary-csv",
        ),
        (
            ["--summary-max-count", "1"],
            "--summary-max-count requires --summary-only, --json-summary, or --summary-csv",
        ),
        (
            ["--summary-min-size-bytes", "1"],
            "--summary-min-size-bytes requires --summary-only, --json-summary, or --summary-csv",
        ),
        (
            ["--summary-max-size-bytes", "1"],
            "--summary-max-size-bytes requires --summary-only, --json-summary, or --summary-csv",
        ),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should require summary output")
