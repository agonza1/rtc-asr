import argparse
import importlib.util
import io
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
parse_size_bytes = report_module.parse_size_bytes
parse_age_days = report_module.parse_age_days
format_age_days = report_module.format_age_days
render_text = report_module.render_text
render_paths = report_module.render_paths
render_json_lines = report_module.render_json_lines
render_json_summary = report_module.render_json_summary
render_summary_csv = report_module.render_summary_csv
render_summary_markdown = report_module.render_summary_markdown
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
measured_week = report_module.measured_week
measured_day = report_module.measured_day
measured_year = report_module.measured_year
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
    assert normalize_summary_groups(["status, backend", "measured-month, artifact-path"]) == {
        "status",
        "backend",
        "measured-month",
        "artifact-path",
    }


def test_parse_args_accepts_plural_summary_groups_alias() -> None:
    args = parse_args(["--summary-groups", "status, backend"])

    assert args.summary_group == ["status, backend"]


def test_parse_args_accepts_short_group_aliases() -> None:
    assert parse_args(["--group", "status"]).summary_group == ["status"]
    assert parse_args(["--groups", "status, backend"]).summary_group == ["status, backend"]


def test_summary_groups_accept_case_insensitive_values_and_aliases() -> None:
    assert normalize_summary_groups(
        [
            (
                "Status, CURRENT-PATH-NAME, DETAIL-PATH, DETAIL-PAGE-PATH, TRACK-STATUS, "
                "YEAR, CALENDAR-YEAR, MONTH, CALENDAR-MONTH, DAY, CALENDAR-DAY, "
                "CALENDAR-DATE, AGE-RANGE"
            )
        ]
    ) == {
        "status",
        "current-artifact-name",
        "detail-page",
        "track-state",
        "measured-year",
        "measured-month",
        "measured-day",
        "age-bucket",
    }


def test_summary_groups_accept_underscore_values_and_aliases() -> None:
    assert normalize_summary_groups(["artifact_path, current_path_name, detail_page_path, track_status"]) == {
        "artifact-path",
        "current-artifact-name",
        "detail-page",
        "track-state",
    }


def test_summary_groups_accept_all_alias_with_specific_groups() -> None:
    assert normalize_summary_groups(["status, all"]) == set(report_module.SUMMARY_GROUPS)


def test_summary_groups_accept_current_path_aliases() -> None:
    assert normalize_summary_groups(
        [
            (
                "current-path, current-artifact-path, current-path-name, current-artifact-file-name, "
                "current-path-stem, current-artifact-file-stem, current-file-stem"
            )
        ]
    ) == {
        "current-artifact",
        "current-artifact-name",
        "current-artifact-stem",
    }


def test_summary_groups_accept_file_stem_aliases() -> None:
    assert normalize_summary_groups(
        [
            "artifact-file-stem, path-stem, path-file-stem, current-file-stem, "
            "artifact-path-stem, artifact-path-file-stem, detail-file-stem, "
            "detail-stem, detail-page-file-stem"
        ]
    ) == {
        "artifact-stem",
        "current-artifact-stem",
        "detail-page-stem",
    }


def test_summary_groups_accept_filename_aliases() -> None:
    assert normalize_summary_groups(
        [
            (
                "artifact-filename, artifact-basename, artifact-file-name, path-name, "
                "path-basename, path-filename, path-file-name, artifact-path-name, "
                "artifact-path-basename, artifact-path-filename, artifact-path-file-name"
            ),
            "current-filename, current-basename, current-file-name",
            (
                "detail-filename, detail-page-filename, detail-basename, detail-page-basename, "
                "detail-file-name, detail-page-file-name"
            ),
        ]
    ) == {
        "artifact-name",
        "current-artifact-name",
        "detail-page-name",
    }


def test_summary_groups_accept_directory_aliases() -> None:
    assert normalize_summary_groups(
        [
            "artifact-directory, artifact-dirname, artifact-folder, artifact-folder-name, "
            "path-dir, path-directory, path-dirname, path-folder, path-folder-name, "
            "artifact-path-dir, artifact-path-directory, artifact-path-dirname, "
            "artifact-path-folder, artifact-path-folder-name",
            (
                "current-artifact-directory, current-path-directory, current-artifact-dirname, "
                "current-path-dirname, current-artifact-folder, current-path-folder, "
                "current-artifact-folder-name, current-path-folder-name, current-directory, "
                "current-dir, current-dirname, current-folder, current-folder-name"
            ),
            (
                "detail-directory, detail-dir, detail-page-directory, detail-dirname, detail-page-dirname, "
                "detail-folder, detail-page-folder, detail-folder-name, detail-page-folder-name"
            ),
        ]
    ) == {
        "artifact-dir",
        "current-artifact-dir",
        "detail-page-dir",
    }


def test_summary_groups_accept_extension_aliases() -> None:
    assert normalize_summary_groups(
        [
            (
                "artifact-ext, artifact-file-ext, artifact-file-extension, path-extension, "
                "path-ext, path-file-ext, path-file-extension, artifact-path-extension, "
                "artifact-path-ext, artifact-path-file-ext, artifact-path-file-extension"
            ),
            "current-extension, current-ext, current-artifact-ext, current-file-ext",
            "current-file-extension, current-path-ext, current-path-file-ext, "
            "current-path-file-extension, current-path-extension",
            "detail-extension, detail-ext, detail-file-ext, detail-file-extension, detail-page-ext",
            "detail-page-file-ext, detail-page-file-extension",
        ]
    ) == {
        "artifact-extension",
        "current-artifact-extension",
        "detail-page-extension",
    }


def test_summary_groups_reject_unknown_values() -> None:
    with pytest.raises(ValueError) as exc_info:
        normalize_summary_groups(["status, typo"])

    assert "Unsupported summary group: typo." in str(exc_info.value)
    assert "Valid groups: slug, artifact-path, artifact-name" in str(exc_info.value)


def test_validate_summary_options_rejects_invalid_ranges() -> None:
    with pytest.raises(ValueError, match="summary_min_count cannot exceed summary_max_count"):
        validate_summary_options(summary_min_count=2, summary_max_count=1)

    with pytest.raises(ValueError, match="summary_min_size_bytes cannot exceed summary_max_size_bytes"):
        validate_summary_options(summary_min_size_bytes=20, summary_max_size_bytes=10)


def test_parse_args_accepts_average_size_summary_sort_aliases() -> None:
    for alias in [
        "average-size",
        "average-size-desc",
        "average-size-asc",
        "average",
        "average-desc",
        "average-asc",
        "average-bytes",
        "average-bytes-desc",
        "average-bytes-asc",
        "avg-size",
        "avg-size-desc",
        "avg-size-asc",
        "avg",
        "avg-desc",
        "avg-asc",
        "mean-size",
        "mean-size-desc",
        "mean-size-asc",
        "mean",
        "mean-desc",
        "mean-asc",
        "mean-bytes",
        "mean-bytes-desc",
        "mean-bytes-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_total_size_summary_sort_aliases() -> None:
    for alias in [
        "total-size",
        "total-size-desc",
        "total-size-asc",
        "total-bytes",
        "total-bytes-desc",
        "total-bytes-asc",
        "file-size",
        "file-size-desc",
        "file-size-asc",
        "file-bytes",
        "file-bytes-desc",
        "file-bytes-asc",
        "artifact-size",
        "artifact-size-desc",
        "artifact-size-asc",
        "artifact-bytes",
        "artifact-bytes-desc",
        "artifact-bytes-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_case_insensitive_summary_sort_aliases() -> None:
    assert parse_args(["--summary-sort", "LARGEST"]).summary_sort == "largest"
    assert parse_args(["--summary-sort", "Avg-Size-Asc"]).summary_sort == "avg-size-asc"


def test_parse_args_accepts_underscore_summary_sort_aliases() -> None:
    assert parse_args(["--summary-sort", "avg_bytes_asc"]).summary_sort == "avg-bytes-asc"
    assert parse_args(["--summary-sort", "largest_bytes_first"]).summary_sort == "largest-bytes-first"


def test_parse_args_accepts_least_count_summary_sort_aliases() -> None:
    for alias in ["least", "least-first", "least-artifacts", "least-artifacts-first"]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_render_json_summary_accepts_case_insensitive_summary_sort() -> None:
    stale = [
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
    ]

    summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="Avg-Bytes-Asc"))

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["base", "qwen"]


def test_render_json_summary_accepts_short_average_summary_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 80,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 120,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "slug": "qwen",
            "artifact_size_bytes": 60,
        },
    ]

    average = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="average"))
    avg_asc = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="avg-asc"))
    mean_desc = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="mean-desc"))

    assert [bucket["slug"] for bucket in average["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in avg_asc["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in mean_desc["by_slug"]] == ["base", "qwen"]
    assert average["by_slug"][0]["average_size"] == "100 B"


def test_render_json_summary_accepts_underscore_summary_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 80,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 120,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "slug": "qwen",
            "artifact_size_bytes": 60,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="avg_bytes_asc"))

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_exposes_average_size_for_buckets() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 80,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="average-size"))

    assert summary["by_slug"][0]["average_size_bytes"] == 60
    assert summary["by_slug"][0]["average_size"] == "60 B"


def test_render_summary_markdown_formats_group_table_with_shares() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "blocked",
            "slug": "qwen",
            "artifact_size_bytes": 60,
        },
    ]

    markdown = render_summary_markdown(
        stale,
        groups=["status"],
        summary_sort="count",
        include_share=True,
    )

    assert "| Group | Bucket | Count | Total size | Count share | Size share |" in markdown
    assert "| status | blocked | 1 | 60 B | 50.0 | 60.0 |" in markdown
    assert "| status | legacy | 1 | 40 B | 50.0 | 40.0 |" in markdown


def test_render_json_summary_formats_fractional_average_size() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 55,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="avg-bytes"))

    assert summary["by_slug"][0]["average_size_bytes"] == 47.5
    assert summary["by_slug"][0]["average_size"] == "47.5 B"


def test_render_json_summary_accepts_readable_size_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-small.json",
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
    ]

    largest = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="largest-first"))
    largest_bytes = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="largest-bytes-first"))
    top_bytes = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="top-bytes"))
    max_size = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="max-size"))
    max_bytes = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="max-bytes-first"))
    smallest = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="smallest-first"))
    bottom_size = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="bottom-size"))
    smallest_bytes = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="smallest-bytes-first"))
    min_size = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="min-size"))
    min_bytes = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="min-bytes-first"))

    assert [bucket["slug"] for bucket in largest["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in largest_bytes["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in top_bytes["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in max_size["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in max_bytes["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in smallest["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in bottom_size["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in smallest_bytes["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in min_size["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in min_bytes["by_slug"]] == ["base", "qwen"]


def test_render_json_summary_accepts_least_count_sort_aliases() -> None:
    stale = [
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
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "slug": "qwen",
            "artifact_size_bytes": 80,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="least-artifacts-first"))

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_total_count_sort_aliases() -> None:
    stale = [
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
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "slug": "qwen",
            "artifact_size_bytes": 80,
        },
    ]

    descending = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="file-count"))
    ascending = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="items-asc"))

    assert [bucket["slug"] for bucket in descending["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in ascending["by_slug"]] == ["qwen", "base"]


def test_parse_args_accepts_bytes_summary_sort_aliases() -> None:
    for alias in ["bytes", "bytes-desc", "bytes-asc"]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_disk_size_summary_sort_aliases() -> None:
    for alias in ["disk-size", "disk-size-desc", "disk-size-asc"]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_readable_size_summary_sort_aliases() -> None:
    for alias in [
        "biggest",
        "biggest-first",
        "largest",
        "largest-first",
        "largest-bytes",
        "largest-bytes-first",
        "top",
        "top-first",
        "top-size",
        "top-size-first",
        "top-bytes",
        "top-bytes-first",
        "max-size",
        "max-size-first",
        "max-bytes",
        "max-bytes-first",
        "smallest",
        "smallest-first",
        "smallest-bytes",
        "smallest-bytes-first",
        "bottom",
        "bottom-first",
        "bottom-size",
        "bottom-size-first",
        "bottom-bytes",
        "bottom-bytes-first",
        "min-size",
        "min-size-first",
        "min-bytes",
        "min-bytes-first",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_readable_count_summary_sort_aliases() -> None:
    for alias in [
        "total-count",
        "total-count-desc",
        "total-count-asc",
        "artifact-count",
        "artifact-count-desc",
        "artifact-count-asc",
        "file-count",
        "file-count-desc",
        "file-count-asc",
        "files",
        "files-desc",
        "files-asc",
        "items",
        "items-desc",
        "items-asc",
        "most",
        "most-first",
        "most-artifacts",
        "most-artifacts-first",
        "most-files",
        "most-files-first",
        "fewest",
        "fewest-first",
        "fewest-artifacts",
        "fewest-artifacts-first",
        "fewest-files",
        "fewest-files-first",
        "least-files",
        "least-files-first",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_readable_name_summary_sort_aliases() -> None:
    for alias in [
        "alphabetical",
        "alphabetical-first",
        "alphabetical-asc",
        "alphabetical-desc",
        "alpha",
        "alpha-first",
        "alpha-asc",
        "alpha-desc",
        "reverse-alphabetical",
        "reverse-alphabetical-first",
        "reverse-alpha",
        "reverse-alpha-first",
        "reverse-name",
        "reverse-name-first",
        "name-reverse",
        "name-reverse-first",
        "a-z",
        "z-a",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_age_bucket_summary_sort_aliases() -> None:
    for alias in [
        "age-bucket",
        "age-bucket-desc",
        "age-bucket-asc",
        "age-range",
        "age-range-desc",
        "age-range-asc",
        "stale-age-bucket",
        "stale-age-bucket-desc",
        "stale-age-bucket-asc",
        "staleness-bucket",
        "staleness-bucket-desc",
        "staleness-bucket-asc",
        "age",
        "age-desc",
        "age-asc",
        "older",
        "older-first",
        "newer",
        "newer-first",
        "stale",
        "stale-first",
        "stalest",
        "stalest-first",
        "freshest",
        "freshest-first",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_measured_year_summary_sort_aliases() -> None:
    for alias in [
        "year",
        "year-desc",
        "year-asc",
        "calendar-year",
        "calendar-year-desc",
        "calendar-year-asc",
        "measurement-year",
        "measurement-year-desc",
        "measurement-year-asc",
        "measured-at-year",
        "measured-at-year-desc",
        "measured-at-year-asc",
        "measured-year",
        "measured-year-desc",
        "measured-year-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_measured_month_summary_sort_aliases() -> None:
    for alias in [
        "month",
        "month-desc",
        "month-asc",
        "calendar-month",
        "calendar-month-desc",
        "calendar-month-asc",
        "measurement-month",
        "measurement-month-desc",
        "measurement-month-asc",
        "measured-at-month",
        "measured-at-month-desc",
        "measured-at-month-asc",
        "measured-month",
        "measured-month-desc",
        "measured-month-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_measured_day_summary_sort_aliases() -> None:
    for alias in [
        "date",
        "date-desc",
        "date-asc",
        "calendar-date",
        "calendar-date-desc",
        "calendar-date-asc",
        "day",
        "day-desc",
        "day-asc",
        "calendar-day",
        "calendar-day-desc",
        "calendar-day-asc",
        "measurement-date",
        "measurement-date-desc",
        "measurement-date-asc",
        "measurement-day",
        "measurement-day-desc",
        "measurement-day-asc",
        "measured-at-date",
        "measured-at-date-desc",
        "measured-at-date-asc",
        "measured-at-day",
        "measured-at-day-desc",
        "measured-at-day-asc",
        "measured-day",
        "measured-day-desc",
        "measured-day-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_parse_args_accepts_measured_week_summary_sort_aliases() -> None:
    for alias in [
        "week",
        "week-desc",
        "week-asc",
        "calendar-week",
        "calendar-week-desc",
        "calendar-week-asc",
        "iso-week",
        "iso-week-desc",
        "iso-week-asc",
        "measurement-week",
        "measurement-week-desc",
        "measurement-week-asc",
        "measured-at-week",
        "measured-at-week-desc",
        "measured-at-week-asc",
        "measured-week",
        "measured-week-desc",
        "measured-week-asc",
    ]:
        assert parse_args(["--summary-sort", alias]).summary_sort == alias


def test_render_json_summary_accepts_readable_name_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/zulu.json",
            "status": "legacy",
            "slug": "zulu",
            "artifact_size_bytes": 50,
        },
        {
            "artifact_path": "benchmark-results/alpha.json",
            "status": "legacy",
            "slug": "alpha",
            "artifact_size_bytes": 80,
        },
    ]

    alphabetical = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="alphabetical"))
    reverse_alphabetical = json.loads(
        render_json_summary(stale, groups=["slug"], summary_sort="reverse-alphabetical")
    )
    alpha = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="alpha"))
    reverse = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="reverse-name"))
    name_reverse = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="name-reverse"))

    assert [bucket["slug"] for bucket in alphabetical["by_slug"]] == ["alpha", "zulu"]
    assert [bucket["slug"] for bucket in alpha["by_slug"]] == ["alpha", "zulu"]
    assert [bucket["slug"] for bucket in reverse_alphabetical["by_slug"]] == ["zulu", "alpha"]
    assert [bucket["slug"] for bucket in reverse["by_slug"]] == ["zulu", "alpha"]
    assert [bucket["slug"] for bucket in name_reverse["by_slug"]] == ["zulu", "alpha"]


def test_render_json_summary_accepts_age_bucket_summary_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/new.json",
            "status": "legacy",
            "age_bucket": "0-6d",
            "artifact_size_bytes": 50,
        },
        {
            "artifact_path": "benchmark-results/old.json",
            "status": "legacy",
            "age_bucket": "90d+",
            "artifact_size_bytes": 80,
        },
        {
            "artifact_path": "benchmark-results/mid.json",
            "status": "legacy",
            "age_bucket": "30-89d",
            "artifact_size_bytes": 60,
        },
    ]

    stale_first = json.loads(render_json_summary(stale, groups=["age-bucket"], summary_sort="stale"))
    freshest_first = json.loads(render_json_summary(stale, groups=["age-bucket"], summary_sort="freshest"))
    older_first = json.loads(render_json_summary(stale, groups=["age-bucket"], summary_sort="older-first"))
    newer_first = json.loads(render_json_summary(stale, groups=["age-bucket"], summary_sort="newer-first"))
    age_range = json.loads(render_json_summary(stale, groups=["age-bucket"], summary_sort="age-range-asc"))

    assert [bucket["age_bucket"] for bucket in stale_first["by_age_bucket"]] == ["90d+", "30-89d", "0-6d"]
    assert [bucket["age_bucket"] for bucket in freshest_first["by_age_bucket"]] == ["0-6d", "30-89d", "90d+"]
    assert [bucket["age_bucket"] for bucket in older_first["by_age_bucket"]] == ["90d+", "30-89d", "0-6d"]
    assert [bucket["age_bucket"] for bucket in newer_first["by_age_bucket"]] == ["0-6d", "30-89d", "90d+"]
    assert [bucket["age_bucket"] for bucket in age_range["by_age_bucket"]] == ["0-6d", "30-89d", "90d+"]


def test_render_json_summary_groups_by_measured_day_aliases() -> None:
    assert measured_day("2026-06-20T23:59:59Z") == "2026-06-20"

    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "measured_at": "2026-06-20T10:00:00Z",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "measured_at": "2026-06-20T11:00:00Z",
            "artifact_size_bytes": 60,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "measured_at": "2026-06-21T10:00:00Z",
            "artifact_size_bytes": 80,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["date"], summary_sort="size"))

    assert summary["by_measured_day"] == [
        {
            "measured_day": "2026-06-20",
            "count": 2,
            "total_size_bytes": 100,
            "total_size": "100 B",
        },
        {
            "measured_day": "2026-06-21",
            "count": 1,
            "total_size_bytes": 80,
            "total_size": "80 B",
        },
    ]


def test_render_json_summary_groups_by_measured_week_aliases() -> None:
    assert measured_week("2026-06-20T23:59:59Z") == "2026-W25"

    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "measured_at": "2026-06-20T10:00:00Z",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "measured_at": "2026-06-21T11:00:00Z",
            "artifact_size_bytes": 60,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "measured_at": "2026-06-22T10:00:00Z",
            "artifact_size_bytes": 80,
        },
    ]

    summary = json.loads(render_json_summary(stale, groups=["calendar-week"], summary_sort="size"))

    assert summary["by_measured_week"] == [
        {
            "measured_week": "2026-W25",
            "count": 2,
            "total_size_bytes": 100,
            "total_size": "100 B",
        },
        {
            "measured_week": "2026-W26",
            "count": 1,
            "total_size_bytes": 80,
            "total_size": "80 B",
        },
    ]


def test_render_json_summary_accepts_measured_day_summary_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/early.json",
            "status": "legacy",
            "measured_at": "2026-06-20T10:00:00Z",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/late.json",
            "status": "legacy",
            "measured_at": "2026-06-21T11:00:00Z",
            "artifact_size_bytes": 60,
        },
    ]

    ascending = json.loads(render_json_summary(stale, groups=["date"], summary_sort="day-asc"))
    descending = json.loads(render_json_summary(stale, groups=["date"], summary_sort="measurement-date-desc"))

    assert [bucket["measured_day"] for bucket in ascending["by_measured_day"]] == [
        "2026-06-20",
        "2026-06-21",
    ]
    assert [bucket["measured_day"] for bucket in descending["by_measured_day"]] == [
        "2026-06-21",
        "2026-06-20",
    ]


def test_parse_args_accepts_readable_size_thresholds() -> None:
    args = parse_args(
        [
            "--min-size-bytes",
            "1.5KiB",
            "--max-size-bytes",
            "2 MB",
            "--summary-min-size-bytes",
            "3kb",
            "--summary-max-size-bytes",
            "4TiB",
        ]
    )

    assert args.min_size_bytes == 1536
    assert args.max_size_bytes == 2_000_000
    assert args.summary_min_size_bytes == 3000
    assert args.summary_max_size_bytes == 4 * 1024**4


def test_parse_args_accepts_long_readable_size_units() -> None:
    args = parse_args(
        [
            "--min-size-bytes",
            "1.5 kibibytes",
            "--max-size-bytes",
            "2 megabytes",
            "--summary-min-size-bytes",
            "3 kilobytes",
            "--summary-max-size-bytes",
            "4 tebibytes",
        ]
    )

    assert args.min_size_bytes == 1536
    assert args.max_size_bytes == 2_000_000
    assert args.summary_min_size_bytes == 3000
    assert args.summary_max_size_bytes == 4 * 1024**4


def test_parse_size_bytes_accepts_digit_separators() -> None:
    assert parse_size_bytes("1,024") == 1024
    assert parse_size_bytes("1_500 KB") == 1_500_000


def test_parse_size_bytes_accepts_long_unit_names() -> None:
    assert parse_size_bytes("1 byte") == 1
    assert parse_size_bytes("2 bytes") == 2
    assert parse_size_bytes("3 gigabytes") == 3_000_000_000
    assert parse_size_bytes("4 gibibytes") == 4 * 1024**3


def test_parse_args_accepts_readable_age_filter_aliases() -> None:
    args = parse_args(["--older-than", "2 months", "--newer-than", "1year"])

    assert args.older_than_days == 60
    assert args.newer_than_days == 365


def test_parse_age_days_accepts_day_suffixes() -> None:
    assert parse_age_days("7d") == 7
    assert parse_age_days("14 day") == 14
    assert parse_age_days("30 days") == 30


def test_parse_age_days_accepts_week_suffixes() -> None:
    assert parse_age_days("1w") == 7
    assert parse_age_days("2 wk") == 14
    assert parse_age_days("3 weeks") == 21


def test_parse_age_days_accepts_fractional_units() -> None:
    assert parse_age_days("1.5 weeks") == 11
    assert parse_age_days("0.5 months") == 15
    assert parse_age_days("1_000.5 days") == 1001


def test_parse_age_days_accepts_fortnight_suffixes() -> None:
    assert parse_age_days("1 fortnight") == 14
    assert parse_age_days("2 fortnights") == 28
    assert parse_age_days("3 biweeks") == 42


def test_parse_age_days_accepts_month_suffixes() -> None:
    assert parse_age_days("1mo") == 30
    assert parse_age_days("2 mon") == 60
    assert parse_age_days("3 months") == 90


def test_parse_age_days_accepts_quarter_suffixes() -> None:
    assert parse_age_days("1q") == 90
    assert parse_age_days("2 qtr") == 180
    assert parse_age_days("3 quarters") == 270


def test_parse_age_days_accepts_year_suffixes() -> None:
    assert parse_age_days("1y") == 365
    assert parse_age_days("2 yr") == 730
    assert parse_age_days("3 years") == 1095


def test_parse_args_accepts_track_status_filter_alias() -> None:
    assert parse_args(["--track-status", "tracked"]).track_state == "tracked"


def test_parse_args_accepts_current_directory_filter_short_aliases() -> None:
    for alias in [
        "--current-directory",
        "--current-dir",
        "--current-dirname",
        "--current-folder",
        "--current-folder-name",
    ]:
        assert parse_args([alias, "benchmark-results"]).current_path_dir == ["benchmark-results"]


def test_parse_args_accepts_current_directory_contains_short_aliases() -> None:
    for alias in [
        "--current-directory-contains",
        "--current-dir-contains",
        "--current-dirname-contains",
        "--current-folder-contains",
        "--current-folder-name-contains",
    ]:
        assert parse_args([alias, "benchmark"]).current_path_dir_contains == ["benchmark"]


def test_parse_size_bytes_rejects_unknown_units() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="size unit must be one of"):
        parse_size_bytes("1XB")


def test_parse_size_bytes_rejects_negative_values() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="size must not be negative"):
        parse_size_bytes("-1MiB")


def test_parse_age_days_rejects_extreme_values() -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="days must be no more than 365000"):
        parse_age_days("999999")


def test_parse_args_accepts_explicit_ascending_stale_sort_aliases() -> None:
    aliases = [
        "bytes-asc",
        "total-size-asc",
        "artifact-stem-asc",
        "artifact-file-stem-asc",
        "artifact-dir-asc",
        "artifact-dirname-asc",
        "artifact-extension-asc",
        "detail-page-asc",
        "detail-path-asc",
        "detail-page-path-asc",
        "detail-page-name-asc",
        "detail-page-basename-asc",
        "detail-page-filename-asc",
        "detail-page-stem-asc",
        "detail-page-dir-asc",
        "detail-dir-asc",
        "detail-dirname-asc",
        "detail-page-dirname-asc",
        "detail-page-extension-asc",
        "status-asc",
        "backend-asc",
        "model-asc",
        "label-asc",
        "slug-asc",
        "track-state-asc",
        "track-status-asc",
        "current-path-asc",
        "current-artifact-asc",
        "current-artifact-path-asc",
        "current-path-name-asc",
        "current-artifact-name-asc",
        "current-filename-asc",
        "current-basename-asc",
        "current-file-name-asc",
        "current-path-stem-asc",
        "current-artifact-stem-asc",
        "current-file-stem-asc",
        "current-path-dir-asc",
        "current-artifact-dir-asc",
        "current-path-dirname-asc",
        "current-artifact-dirname-asc",
        "current-directory-asc",
        "current-dir-asc",
        "current-dirname-asc",
        "current-folder-asc",
        "current-folder-name-asc",
        "current-extension-asc",
        "current-ext-asc",
        "current-path-ext-asc",
        "current-path-file-ext-asc",
        "current-path-file-extension-asc",
        "current-artifact-ext-asc",
        "current-file-ext-asc",
        "current-file-extension-asc",
        "current-path-extension-asc",
        "current-artifact-extension-asc",
        "measured-month-asc",
        "age-bucket-asc",
        "age-range-asc",
        "age-range-bucket-asc",
        "stale-age-bucket-asc",
        "staleness-bucket-asc",
        "artifact-filename-asc",
        "artifact-basename-asc",
        "artifact-file-name-asc",
        "artifact-path-name-asc",
        "artifact-path-basename-asc",
        "artifact-path-filename-asc",
        "artifact-path-file-name-asc",
        "artifact-path-stem-asc",
        "artifact-path-file-stem-asc",
        "artifact-path-dir-asc",
        "artifact-path-directory-asc",
        "artifact-path-dirname-asc",
        "artifact-path-folder-asc",
        "artifact-path-folder-name-asc",
        "artifact-path-extension-asc",
        "artifact-path-ext-asc",
        "artifact-path-file-ext-asc",
        "artifact-path-file-extension-asc",
        "artifact-ext-asc",
        "artifact-file-ext-asc",
        "artifact-file-extension-asc",
        "detail-extension-asc",
        "detail-filename-asc",
        "detail-basename-asc",
        "detail-file-name-asc",
        "detail-page-file-name-asc",
        "detail-file-stem-asc",
        "detail-stem-asc",
        "detail-page-file-stem-asc",
        "detail-ext-asc",
        "detail-file-ext-asc",
        "detail-file-extension-asc",
        "detail-page-ext-asc",
        "detail-page-file-ext-asc",
        "detail-page-file-extension-asc",
    ]

    for alias in aliases:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_size_stale_sort_aliases() -> None:
    for alias in [
        "bytes",
        "bytes-desc",
        "bytes-asc",
        "disk-size",
        "disk-size-desc",
        "disk-size-asc",
        "total-size",
        "total-size-desc",
        "total-size-asc",
        "total-bytes",
        "total-bytes-desc",
        "total-bytes-asc",
        "file-size",
        "file-size-desc",
        "file-size-asc",
        "file-bytes",
        "file-bytes-desc",
        "file-bytes-asc",
        "artifact-size",
        "artifact-size-desc",
        "artifact-size-asc",
        "artifact-bytes",
        "artifact-bytes-desc",
        "artifact-bytes-asc",
        "artifact-path",
        "artifact-path-desc",
        "artifact-path-asc",
        "biggest",
        "biggest-first",
        "heaviest",
        "heaviest-first",
        "largest",
        "largest-first",
        "largest-bytes",
        "largest-bytes-first",
        "top",
        "top-first",
        "top-size",
        "top-size-first",
        "top-bytes",
        "top-bytes-first",
        "max-size",
        "max-size-first",
        "max-bytes",
        "max-bytes-first",
        "lightest",
        "lightest-first",
        "smallest",
        "smallest-first",
        "smallest-bytes",
        "smallest-bytes-first",
        "bottom",
        "bottom-first",
        "bottom-size",
        "bottom-size-first",
        "bottom-bytes",
        "bottom-bytes-first",
        "min-size",
        "min-size-first",
        "min-bytes",
        "min-bytes-first",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_stale_artifacts_accept_total_bytes_sort_aliases() -> None:
    manifest = {
        "artifacts": [
            {
                "artifact_path": "benchmark-results/small.json",
                "status": "legacy",
                "artifact_size_bytes": 25,
            },
            {
                "artifact_path": "benchmark-results/large.json",
                "status": "legacy",
                "artifact_size_bytes": 75,
            },
        ],
        "tracks": [],
    }

    descending = stale_artifacts(manifest, sort_by="total-bytes")
    ascending = stale_artifacts(manifest, sort_by="total-bytes-asc")
    artifact_size = stale_artifacts(manifest, sort_by="artifact-size")
    artifact_bytes_asc = stale_artifacts(manifest, sort_by="artifact-bytes-asc")
    max_size = stale_artifacts(manifest, sort_by="max-size")
    min_bytes = stale_artifacts(manifest, sort_by="min-bytes-first")
    top_bytes = stale_artifacts(manifest, sort_by="top-bytes")
    bottom_size = stale_artifacts(manifest, sort_by="bottom-size")

    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in artifact_size] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in artifact_bytes_asc] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in max_size] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in min_bytes] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in top_bytes] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in bottom_size] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]


def test_parse_args_accepts_readable_measured_time_sort_aliases() -> None:
    for alias in [
        "oldest",
        "oldest-first",
        "earliest",
        "earliest-first",
        "newest",
        "newest-first",
        "latest",
        "latest-first",
        "recent",
        "recent-first",
        "most-recent",
        "most-recent-first",
        "year",
        "year-asc",
        "year-desc",
        "calendar-year",
        "calendar-year-asc",
        "calendar-year-desc",
        "measurement-year",
        "measurement-year-asc",
        "measurement-year-desc",
        "measured-at-year",
        "measured-at-year-asc",
        "measured-at-year-desc",
        "month",
        "month-asc",
        "month-desc",
        "calendar-month",
        "calendar-month-asc",
        "calendar-month-desc",
        "measurement-month",
        "measurement-month-asc",
        "measurement-month-desc",
        "measured-at-month",
        "measured-at-month-asc",
        "measured-at-month-desc",
        "week",
        "week-asc",
        "week-desc",
        "calendar-week",
        "calendar-week-asc",
        "calendar-week-desc",
        "iso-week",
        "iso-week-asc",
        "iso-week-desc",
        "measurement-week",
        "measurement-week-asc",
        "measurement-week-desc",
        "measured-at-week",
        "measured-at-week-asc",
        "measured-at-week-desc",
        "measured-week",
        "measured-week-asc",
        "measured-week-desc",
        "date",
        "date-asc",
        "date-desc",
        "calendar-date",
        "calendar-date-asc",
        "calendar-date-desc",
        "day",
        "day-asc",
        "day-desc",
        "calendar-day",
        "calendar-day-asc",
        "calendar-day-desc",
        "measurement-date",
        "measurement-date-asc",
        "measurement-date-desc",
        "measurement-day",
        "measurement-day-asc",
        "measurement-day-desc",
        "measured-at-date",
        "measured-at-date-asc",
        "measured-at-date-desc",
        "measured-at-day",
        "measured-at-day-asc",
        "measured-at-day-desc",
        "measured-day",
        "measured-day-asc",
        "measured-day-desc",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_measured_month_filter_aliases() -> None:
    args = parse_args(["--month", "2026-06", "--measurement-month", "2026-07"])

    assert args.measured_month == ["2026-06", "2026-07"]


def test_stale_artifacts_accept_measured_month_sort_aliases() -> None:
    manifest = {
        "artifacts": [
            {
                "artifact_path": "benchmark-results/june.json",
                "status": "legacy",
                "measured_at": "2026-06-20T00:00:00Z",
            },
            {
                "artifact_path": "benchmark-results/july.json",
                "status": "legacy",
                "measured_at": "2026-07-01T00:00:00Z",
            },
        ],
        "tracks": [],
    }

    ascending = stale_artifacts(manifest, sort_by="month")
    descending = stale_artifacts(manifest, sort_by="measurement-month-desc")

    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/june.json",
        "benchmark-results/july.json",
    ]
    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/july.json",
        "benchmark-results/june.json",
    ]


def test_stale_artifacts_accept_measured_day_sort_aliases() -> None:
    manifest = {
        "artifacts": [
            {
                "artifact_path": "benchmark-results/early.json",
                "status": "legacy",
                "measured_at": "2026-06-20T23:00:00Z",
            },
            {
                "artifact_path": "benchmark-results/late.json",
                "status": "legacy",
                "measured_at": "2026-06-21T01:00:00Z",
            },
        ],
        "tracks": [],
    }

    ascending = stale_artifacts(manifest, sort_by="day")
    descending = stale_artifacts(manifest, sort_by="measurement-date-desc")

    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/early.json",
        "benchmark-results/late.json",
    ]
    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/late.json",
        "benchmark-results/early.json",
    ]


def test_stale_artifacts_accept_measured_week_sort_aliases() -> None:
    manifest = {
        "artifacts": [
            {
                "artifact_path": "benchmark-results/week-25.json",
                "status": "legacy",
                "measured_at": "2026-06-20T23:00:00Z",
            },
            {
                "artifact_path": "benchmark-results/week-26.json",
                "status": "legacy",
                "measured_at": "2026-06-22T01:00:00Z",
            },
        ],
        "tracks": [],
    }

    ascending = stale_artifacts(manifest, sort_by="week")
    descending = stale_artifacts(manifest, sort_by="measurement-week-desc")

    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/week-25.json",
        "benchmark-results/week-26.json",
    ]
    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/week-26.json",
        "benchmark-results/week-25.json",
    ]


def test_stale_artifacts_accept_measured_year_sort_aliases() -> None:
    manifest = {
        "artifacts": [
            {
                "artifact_path": "benchmark-results/old-b.json",
                "status": "legacy",
                "measured_at": "2025-12-20T00:00:00Z",
            },
            {
                "artifact_path": "benchmark-results/new.json",
                "status": "legacy",
                "measured_at": "2026-01-01T00:00:00Z",
            },
            {
                "artifact_path": "benchmark-results/old-a.json",
                "status": "legacy",
                "measured_at": "2025-06-01T00:00:00Z",
            },
        ],
        "tracks": [],
    }

    ascending = stale_artifacts(manifest, sort_by="year")
    descending = stale_artifacts(manifest, sort_by="measurement-year-desc")

    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/old-a.json",
        "benchmark-results/old-b.json",
        "benchmark-results/new.json",
    ]
    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/new.json",
        "benchmark-results/old-a.json",
        "benchmark-results/old-b.json",
    ]


def test_parse_args_accepts_readable_path_sort_aliases() -> None:
    for alias in [
        "alphabetical",
        "alphabetical-first",
        "alphabetical-asc",
        "alphabetical-desc",
        "alpha",
        "alpha-first",
        "alpha-asc",
        "alpha-desc",
        "reverse-alphabetical",
        "reverse-alphabetical-first",
        "reverse-alpha",
        "reverse-alpha-first",
        "reverse-path",
        "reverse-path-first",
        "path-reverse",
        "path-reverse-first",
        "a-z",
        "z-a",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_basename_stale_sort_aliases() -> None:
    for alias in [
        "path-name",
        "path-name-asc",
        "path-name-desc",
        "path-basename",
        "path-basename-asc",
        "path-basename-desc",
        "path-filename",
        "path-filename-asc",
        "path-filename-desc",
        "path-file-name",
        "path-file-name-asc",
        "path-file-name-desc",
        "artifact-basename",
        "artifact-basename-asc",
        "artifact-basename-desc",
        "artifact-file-name",
        "artifact-file-name-asc",
        "artifact-file-name-desc",
        "current-basename",
        "current-basename-asc",
        "current-basename-desc",
        "current-file-name",
        "current-file-name-asc",
        "current-file-name-desc",
        "detail-basename",
        "detail-basename-asc",
        "detail-basename-desc",
        "detail-file-name",
        "detail-file-name-asc",
        "detail-file-name-desc",
        "detail-page-file-name",
        "detail-page-file-name-asc",
        "detail-page-file-name-desc",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_file_stem_stale_sort_aliases() -> None:
    for alias in [
        "path-stem",
        "path-stem-asc",
        "path-stem-desc",
        "path-file-stem",
        "path-file-stem-asc",
        "path-file-stem-desc",
        "artifact-file-stem",
        "artifact-file-stem-asc",
        "artifact-file-stem-desc",
        "current-file-stem",
        "current-file-stem-asc",
        "current-file-stem-desc",
        "detail-file-stem",
        "detail-file-stem-asc",
        "detail-file-stem-desc",
        "detail-stem",
        "detail-stem-asc",
        "detail-stem-desc",
        "detail-page-file-stem",
        "detail-page-file-stem-asc",
        "detail-page-file-stem-desc",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_file_extension_sort_aliases() -> None:
    for alias in [
        "path-extension",
        "path-extension-asc",
        "path-extension-desc",
        "path-ext",
        "path-ext-asc",
        "path-ext-desc",
        "path-file-ext",
        "path-file-ext-asc",
        "path-file-ext-desc",
        "path-file-extension",
        "path-file-extension-asc",
        "path-file-extension-desc",
        "current-path-file-ext",
        "current-path-file-ext-asc",
        "current-path-file-ext-desc",
        "current-path-file-extension",
        "current-path-file-extension-asc",
        "current-path-file-extension-desc",
        "detail-page-file-ext",
        "detail-page-file-ext-asc",
        "detail-page-file-ext-desc",
        "detail-page-file-extension",
        "detail-page-file-extension-asc",
        "detail-page-file-extension-desc",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_directory_stale_sort_aliases() -> None:
    for alias in [
        "path-dir",
        "path-dir-asc",
        "path-dir-desc",
        "path-directory",
        "path-directory-asc",
        "path-directory-desc",
        "path-dirname",
        "path-dirname-asc",
        "path-dirname-desc",
        "path-folder",
        "path-folder-asc",
        "path-folder-desc",
        "path-folder-name",
        "path-folder-name-asc",
        "path-folder-name-desc",
        "artifact-directory",
        "artifact-directory-asc",
        "artifact-directory-desc",
        "artifact-dirname",
        "artifact-dirname-asc",
        "artifact-dirname-desc",
        "artifact-folder",
        "artifact-folder-asc",
        "artifact-folder-desc",
        "artifact-folder-name",
        "artifact-folder-name-asc",
        "artifact-folder-name-desc",
        "current-artifact-directory",
        "current-artifact-directory-asc",
        "current-artifact-directory-desc",
        "current-artifact-dirname",
        "current-artifact-dirname-asc",
        "current-artifact-dirname-desc",
        "current-artifact-folder",
        "current-artifact-folder-asc",
        "current-artifact-folder-desc",
        "current-artifact-folder-name",
        "current-artifact-folder-name-asc",
        "current-artifact-folder-name-desc",
        "current-path-directory",
        "current-path-directory-asc",
        "current-path-directory-desc",
        "current-path-dirname",
        "current-path-dirname-asc",
        "current-path-dirname-desc",
        "current-path-folder",
        "current-path-folder-asc",
        "current-path-folder-desc",
        "current-path-folder-name",
        "current-path-folder-name-asc",
        "current-path-folder-name-desc",
        "detail-directory",
        "detail-directory-asc",
        "detail-directory-desc",
        "detail-dir",
        "detail-dir-asc",
        "detail-dir-desc",
        "detail-dirname",
        "detail-dirname-asc",
        "detail-dirname-desc",
        "detail-folder",
        "detail-folder-asc",
        "detail-folder-desc",
        "detail-folder-name",
        "detail-folder-name-asc",
        "detail-folder-name-desc",
        "detail-page-directory",
        "detail-page-directory-asc",
        "detail-page-directory-desc",
        "detail-page-dirname",
        "detail-page-dirname-asc",
        "detail-page-dirname-desc",
        "detail-page-folder",
        "detail-page-folder-asc",
        "detail-page-folder-desc",
        "detail-page-folder-name",
        "detail-page-folder-name-asc",
        "detail-page-folder-name-desc",
    ]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_case_insensitive_stale_sort_aliases() -> None:
    assert parse_args(["--sort", "Newest-First"]).sort == "newest-first"
    assert parse_args(["--sort", "CURRENT-ARTIFACT-NAME-DESC"]).sort == "current-artifact-name-desc"
    assert parse_args(["--sort", "CURRENT-ARTIFACT-FILE-EXTENSION-DESC"]).sort == (
        "current-artifact-file-extension-desc"
    )
    assert parse_args(["--sort", "AGE-RANGE-DESC"]).sort == "age-range-desc"


def test_parse_args_accepts_underscore_stale_sort_aliases() -> None:
    assert parse_args(["--sort", "current_artifact_name_desc"]).sort == "current-artifact-name-desc"
    assert parse_args(["--sort", "artifact_file_extension_asc"]).sort == "artifact-file-extension-asc"


def test_parse_args_accepts_readable_age_sort_aliases() -> None:
    for alias in ["stale", "stale-first", "stalest", "stalest-first", "freshest", "freshest-first"]:
        assert parse_args(["--sort", alias]).sort == alias


def test_parse_args_accepts_current_artifact_filter_aliases() -> None:
    args = parse_args(
        [
            "--current-artifact",
            "benchmark-results/current.json",
            "--current-artifact-contains",
            "current",
            "--current-artifact-name",
            "current.json",
            "--current-artifact-file-name",
            "latest.json",
            "--current-artifact-name-contains",
            "current",
            "--current-artifact-file-name-contains",
            "latest",
            "--current-artifact-stem",
            "current",
            "--current-artifact-file-stem",
            "winner",
            "--current-file-stem",
            "latest",
            "--current-artifact-stem-contains",
            "curr",
            "--current-artifact-file-stem-contains",
            "win",
            "--current-file-stem-contains",
            "late",
            "--current-artifact-dir",
            "benchmark-results",
            "--current-artifact-directory",
            "benchmark-results/current",
            "--current-path-directory",
            "benchmark-results/path",
            "--current-artifact-dirname",
            "benchmark-results/current-dirname",
            "--current-path-dirname",
            "benchmark-results/path-dirname",
            "--current-artifact-folder",
            "benchmark-results/current-folder",
            "--current-path-folder",
            "benchmark-results/path-folder",
            "--current-artifact-folder-name",
            "benchmark-results/current-folder-name",
            "--current-path-folder-name",
            "benchmark-results/path-folder-name",
            "--current-artifact-dir-contains",
            "benchmark",
            "--current-artifact-directory-contains",
            "current",
            "--current-path-directory-contains",
            "path",
            "--current-artifact-dirname-contains",
            "dirname-current",
            "--current-path-dirname-contains",
            "dirname-path",
            "--current-artifact-folder-contains",
            "folder-current",
            "--current-path-folder-contains",
            "folder-path",
            "--current-artifact-folder-name-contains",
            "folder-name-current",
            "--current-path-folder-name-contains",
            "folder-name-path",
            "--current-artifact-extension",
            ".json",
            "--current-extension",
            "json.gz",
            "--current-ext",
            "webm",
            "--current-artifact-ext",
            "jsonl",
            "--current-artifact-file-ext",
            "aiff",
            "--current-artifact-file-extension",
            "aifc",
            "--current-file-ext",
            "wav",
            "--current-file-extension",
            "csv",
            "--current-path-ext",
            "txt",
            "--current-path-file-ext",
            "flac",
            "--current-path-file-extension",
            "opus",
            "--current-artifact-extension-contains",
            "json",
            "--current-extension-contains",
            "gz",
            "--current-ext-contains",
            "web",
            "--current-artifact-ext-contains",
            "jsonl",
            "--current-artifact-file-ext-contains",
            "aiff",
            "--current-artifact-file-extension-contains",
            "aifc",
            "--current-file-ext-contains",
            "wav",
            "--current-file-extension-contains",
            "csv",
            "--current-path-ext-contains",
            "txt",
            "--current-path-file-ext-contains",
            "flac",
            "--current-path-file-extension-contains",
            "opus",
        ]
    )

    assert args.current_path == ["benchmark-results/current.json"]
    assert args.current_path_contains == ["current"]
    assert args.current_path_name == ["current.json", "latest.json"]
    assert args.current_path_name_contains == ["current", "latest"]
    assert args.current_path_stem == ["current", "winner", "latest"]
    assert args.current_path_stem_contains == ["curr", "win", "late"]
    assert args.current_path_dir == [
        "benchmark-results",
        "benchmark-results/current",
        "benchmark-results/path",
        "benchmark-results/current-dirname",
        "benchmark-results/path-dirname",
        "benchmark-results/current-folder",
        "benchmark-results/path-folder",
        "benchmark-results/current-folder-name",
        "benchmark-results/path-folder-name",
    ]
    assert args.current_path_dir_contains == [
        "benchmark",
        "current",
        "path",
        "dirname-current",
        "dirname-path",
        "folder-current",
        "folder-path",
        "folder-name-current",
        "folder-name-path",
    ]
    assert args.current_path_extension == [
        ".json",
        "json.gz",
        "webm",
        "jsonl",
        "aiff",
        "aifc",
        "wav",
        "csv",
        "txt",
        "flac",
        "opus",
    ]
    assert args.current_path_extension_contains == [
        "json",
        "gz",
        "web",
        "jsonl",
        "aiff",
        "aifc",
        "wav",
        "csv",
        "txt",
        "flac",
        "opus",
    ]


def test_parse_args_accepts_artifact_directory_and_extension_filter_aliases() -> None:
    args = parse_args(
        [
            "--path",
            "benchmark-results/stale.json",
            "--path-contains",
            "stale",
            "--artifact-directory",
            "benchmark-results",
            "--artifact-dirname",
            "benchmark-results/archive",
            "--artifact-folder",
            "benchmark-results/folder",
            "--artifact-folder-name",
            "benchmark-results/folder-name",
            "--path-directory",
            "benchmark-results/path",
            "--path-dirname",
            "benchmark-results/path-dirname",
            "--path-folder",
            "benchmark-results/path-folder",
            "--path-folder-name",
            "benchmark-results/path-folder-name",
            "--artifact-directory-contains",
            "bench",
            "--artifact-dirname-contains",
            "archive",
            "--artifact-folder-contains",
            "folder",
            "--artifact-folder-name-contains",
            "folder-name",
            "--path-directory-contains",
            "path",
            "--path-dirname-contains",
            "path-dirname",
            "--path-folder-contains",
            "path-folder",
            "--path-folder-name-contains",
            "path-folder-name",
            "--artifact-ext",
            ".json",
            "--artifact-file-ext",
            "json.gz",
            "--artifact-file-extension",
            "jsonl",
            "--path-ext",
            "wav",
            "--path-file-ext",
            "flac",
            "--path-file-extension",
            "opus",
            "--artifact-ext-contains",
            "json",
            "--artifact-file-ext-contains",
            "gz",
            "--artifact-file-extension-contains",
            "jsonl",
            "--path-ext-contains",
            "wav",
            "--path-file-ext-contains",
            "flac",
            "--path-file-extension-contains",
            "opus",
        ]
    )

    assert args.artifact_path == ["benchmark-results/stale.json"]
    assert args.artifact_path_contains == ["stale"]
    assert args.artifact_dir == [
        "benchmark-results",
        "benchmark-results/archive",
        "benchmark-results/folder",
        "benchmark-results/folder-name",
        "benchmark-results/path",
        "benchmark-results/path-dirname",
        "benchmark-results/path-folder",
        "benchmark-results/path-folder-name",
    ]
    assert args.artifact_dir_contains == [
        "bench",
        "archive",
        "folder",
        "folder-name",
        "path",
        "path-dirname",
        "path-folder",
        "path-folder-name",
    ]
    assert args.artifact_extension == [".json", "json.gz", "jsonl", "wav", "flac", "opus"]
    assert args.artifact_extension_contains == ["json", "gz", "jsonl", "wav", "flac", "opus"]


def test_parse_args_accepts_file_stem_filter_aliases() -> None:
    args = parse_args(
        [
            "--artifact-file-stem",
            "stale",
            "--path-stem",
            "path-stale",
            "--path-file-stem",
            "path-file-stale",
            "--artifact-file-stem-contains",
            "old",
            "--path-stem-contains",
            "path-old",
            "--path-file-stem-contains",
            "path-file-old",
            "--detail-file-stem",
            "detail",
            "--detail-stem",
            "older-detail",
            "--detail-page-file-stem",
            "page-detail",
            "--detail-file-stem-contains",
            "detail",
            "--detail-stem-contains",
            "older",
            "--detail-page-file-stem-contains",
            "page",
        ]
    )

    assert args.artifact_stem == ["stale", "path-stale", "path-file-stale"]
    assert args.artifact_stem_contains == ["old", "path-old", "path-file-old"]
    assert args.detail_page_stem == ["detail", "older-detail", "page-detail"]
    assert args.detail_page_stem_contains == ["detail", "older", "page"]


def test_parse_args_accepts_file_name_filter_aliases() -> None:
    args = parse_args(
        [
            "--artifact-basename",
            "stale.json",
            "--artifact-filename",
            "older.json",
            "--artifact-file-name",
            "archive.json",
            "--path-name",
            "path.json",
            "--path-basename",
            "path-base.json",
            "--path-filename",
            "path-file.json",
            "--path-file-name",
            "path-file-name.json",
            "--artifact-basename-contains",
            "stale",
            "--artifact-filename-contains",
            "older",
            "--artifact-file-name-contains",
            "archive",
            "--path-name-contains",
            "path",
            "--path-basename-contains",
            "path-base",
            "--path-filename-contains",
            "path-file",
            "--path-file-name-contains",
            "path-file-name",
            "--current-basename",
            "current.json",
            "--current-filename",
            "latest.json",
            "--current-file-name",
            "winner.json",
            "--current-basename-contains",
            "current",
            "--current-filename-contains",
            "latest",
            "--current-file-name-contains",
            "winner",
            "--detail-basename",
            "stale.html",
            "--detail-filename",
            "older.html",
            "--detail-file-name",
            "archive.html",
            "--detail-page-file-name",
            "page-archive.html",
            "--detail-basename-contains",
            "stale",
            "--detail-filename-contains",
            "older",
            "--detail-file-name-contains",
            "archive",
            "--detail-page-file-name-contains",
            "page-archive",
        ]
    )

    assert args.artifact_name == [
        "stale.json",
        "older.json",
        "archive.json",
        "path.json",
        "path-base.json",
        "path-file.json",
        "path-file-name.json",
    ]
    assert args.artifact_name_contains == [
        "stale",
        "older",
        "archive",
        "path",
        "path-base",
        "path-file",
        "path-file-name",
    ]
    assert args.current_path_name == ["current.json", "latest.json", "winner.json"]
    assert args.current_path_name_contains == ["current", "latest", "winner"]
    assert args.detail_page_name == ["stale.html", "older.html", "archive.html", "page-archive.html"]
    assert args.detail_page_name_contains == ["stale", "older", "archive", "page-archive"]


def test_parse_args_accepts_detail_path_filter_aliases() -> None:
    args = parse_args(
        [
            "--detail-path",
            "benchmark-results/pages/stale.html",
            "--detail-page-path",
            "benchmark-results/pages/older.html",
            "--detail-path-contains",
            "stale",
            "--detail-page-path-contains",
            "older",
            "--detail-dir",
            "benchmark-results/pages",
            "--detail-directory",
            "benchmark-results/legacy-pages",
            "--detail-page-directory",
            "benchmark-results/archive-pages",
            "--detail-dirname",
            "benchmark-results/dirname-pages",
            "--detail-page-dirname",
            "benchmark-results/page-dirname-pages",
            "--detail-folder",
            "benchmark-results/folder-pages",
            "--detail-page-folder",
            "benchmark-results/page-folder-pages",
            "--detail-folder-name",
            "benchmark-results/folder-name-pages",
            "--detail-page-folder-name",
            "benchmark-results/page-folder-name-pages",
            "--detail-dir-contains",
            "pages",
            "--detail-directory-contains",
            "legacy",
            "--detail-page-directory-contains",
            "archive",
            "--detail-dirname-contains",
            "dirname",
            "--detail-page-dirname-contains",
            "page-dirname",
            "--detail-folder-contains",
            "folder",
            "--detail-page-folder-contains",
            "page-folder",
            "--detail-folder-name-contains",
            "folder-name",
            "--detail-page-folder-name-contains",
            "page-folder-name",
            "--detail-extension",
            ".html",
            "--detail-ext",
            "htm",
            "--detail-file-ext",
            "xhtml",
            "--detail-file-extension",
            "json",
            "--detail-page-ext",
            "none",
            "--detail-page-file-ext",
            "md",
            "--detail-page-file-extension",
            "txt",
            "--detail-extension-contains",
            "html",
            "--detail-ext-contains",
            "htm",
            "--detail-file-ext-contains",
            "xhtml",
            "--detail-file-extension-contains",
            "json",
            "--detail-page-ext-contains",
            "none",
            "--detail-page-file-ext-contains",
            "md",
            "--detail-page-file-extension-contains",
            "txt",
        ]
    )

    assert args.detail_page == ["benchmark-results/pages/stale.html", "benchmark-results/pages/older.html"]
    assert args.detail_page_contains == ["stale", "older"]
    assert args.detail_page_dir == [
        "benchmark-results/pages",
        "benchmark-results/legacy-pages",
        "benchmark-results/archive-pages",
        "benchmark-results/dirname-pages",
        "benchmark-results/page-dirname-pages",
        "benchmark-results/folder-pages",
        "benchmark-results/page-folder-pages",
        "benchmark-results/folder-name-pages",
        "benchmark-results/page-folder-name-pages",
    ]
    assert args.detail_page_dir_contains == [
        "pages",
        "legacy",
        "archive",
        "dirname",
        "page-dirname",
        "folder",
        "page-folder",
        "folder-name",
        "page-folder-name",
    ]
    assert args.detail_page_extension == [".html", "htm", "xhtml", "json", "none", "md", "txt"]
    assert args.detail_page_extension_contains == ["html", "htm", "xhtml", "json", "none", "md", "txt"]


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


def test_measured_year_uses_utc_year_or_unknown() -> None:
    assert measured_year("2026-12-31T23:30:00-02:00") == "2027"
    assert measured_year(None) == "unknown"


def test_age_bucket_uses_cleanup_review_ranges() -> None:
    assert age_bucket(None) == "unknown"
    assert age_bucket(6) == "0-6d"
    assert age_bucket(7) == "7-29d"
    assert age_bucket(30) == "30-89d"
    assert age_bucket(90) == "90d+"


def test_parse_args_accepts_age_bucket_filter_aliases() -> None:
    args = parse_args(
        [
            "--age-range",
            "0-6d",
            "--age-range-bucket",
            "7-29d",
            "--stale-age-bucket",
            "30-89d",
            "--staleness-bucket",
            "90d+",
        ]
    )

    assert args.age_bucket == ["0-6d", "7-29d", "30-89d", "90d+"]


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
            "measured_year": "2026",
            "measured_month": "2026-06",
            "measured_week": "2026-W24",
            "measured_day": "2026-06-10",
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


def test_stale_artifacts_can_filter_untracked_current_artifacts_with_none() -> None:
    manifest = {
        "tracks": [
            {"slug": "base", "artifact_path": "benchmark-results/current/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/orphan-old.json",
                "slug": "orphan",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest, current_paths=["none"])

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/archive/orphan-old.json",
    ]
    assert stale[0]["track_state"] == "untracked"


def test_stale_artifacts_can_filter_untracked_current_artifacts_with_readable_aliases() -> None:
    manifest = {
        "tracks": [
            {"slug": "base", "artifact_path": "benchmark-results/current/base-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/base-old.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
            {
                "artifact_path": "benchmark-results/archive/orphan-old.json",
                "slug": "orphan",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    missing = stale_artifacts(manifest, current_paths=["missing"])
    untracked = stale_artifacts(manifest, current_paths=["untracked"])

    assert [entry["artifact_path"] for entry in missing] == [
        "benchmark-results/archive/orphan-old.json",
    ]
    assert [entry["artifact_path"] for entry in untracked] == [
        "benchmark-results/archive/orphan-old.json",
    ]


def test_stale_artifacts_rejects_impossible_age_window() -> None:
    with pytest.raises(ValueError, match="newer_than_days cannot be less than older_than_days"):
        stale_artifacts({"tracks": [], "artifacts": []}, older_than_days=30, newer_than_days=7)


def test_stale_artifacts_rejects_too_large_older_than_days() -> None:
    with pytest.raises(ValueError, match="older_than_days is too large"):
        stale_artifacts({"tracks": [], "artifacts": []}, older_than_days=999999)


def test_stale_artifacts_accepts_readable_age_sort_aliases() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/fresh.json",
                "status": "legacy",
                "measured_at": "2026-06-19T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/stale.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale_first = stale_artifacts(manifest, now=datetime(2026, 6, 20, tzinfo=UTC), sort_by="stale-first")
    freshest_first = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="freshest-first",
    )

    assert [entry["artifact_path"] for entry in stale_first] == [
        "benchmark-results/stale.json",
        "benchmark-results/fresh.json",
    ]
    assert [entry["artifact_path"] for entry in freshest_first] == [
        "benchmark-results/fresh.json",
        "benchmark-results/stale.json",
    ]


def test_stale_artifacts_accepts_case_insensitive_sort_aliases() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/fresh.json",
                "status": "legacy",
                "measured_at": "2026-06-19T00:00:00Z",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/stale.json",
                "status": "legacy",
                "measured_at": "2026-06-10T00:00:00Z",
                "artifact_size_bytes": 20,
            },
        ],
    }

    stale = stale_artifacts(manifest, now=datetime(2026, 6, 20, tzinfo=UTC), sort_by="Freshest-First")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/fresh.json",
        "benchmark-results/stale.json",
    ]


def test_stale_artifacts_accepts_readable_path_sort_aliases() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/zulu.json",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/alpha.json",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    alphabetical = stale_artifacts(manifest, sort_by="alphabetical")
    alpha = stale_artifacts(manifest, sort_by="alpha")
    reverse = stale_artifacts(manifest, sort_by="reverse-alphabetical")
    path_reverse = stale_artifacts(manifest, sort_by="path-reverse")

    assert [entry["artifact_path"] for entry in alphabetical] == [
        "benchmark-results/alpha.json",
        "benchmark-results/zulu.json",
    ]
    assert [entry["artifact_path"] for entry in alpha] == [
        "benchmark-results/alpha.json",
        "benchmark-results/zulu.json",
    ]
    assert [entry["artifact_path"] for entry in reverse] == [
        "benchmark-results/zulu.json",
        "benchmark-results/alpha.json",
    ]
    assert [entry["artifact_path"] for entry in path_reverse] == [
        "benchmark-results/zulu.json",
        "benchmark-results/alpha.json",
    ]


def test_stale_artifacts_accepts_filename_sort_aliases() -> None:
    manifest = {
        "tracks": [
            {"slug": "base", "artifact_path": "benchmark-results/current/base-current.json"},
            {"slug": "qwen", "artifact_path": "benchmark-results/current/qwen-current.json"},
        ],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/archive/zulu.json",
                "slug": "qwen",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
            {
                "artifact_path": "benchmark-results/archive/alpha.json",
                "slug": "base",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
        ],
    }

    artifact_sorted = stale_artifacts(manifest, sort_by="artifact-filename")
    artifact_basename_sorted = stale_artifacts(manifest, sort_by="artifact-basename")
    artifact_file_name_sorted = stale_artifacts(manifest, sort_by="artifact-file-name")
    current_sorted = stale_artifacts(manifest, sort_by="current-filename-desc")
    current_basename_sorted = stale_artifacts(manifest, sort_by="current-basename-desc")
    current_file_name_sorted = stale_artifacts(manifest, sort_by="current-file-name-desc")
    detail_sorted = stale_artifacts(manifest, sort_by="detail-filename")
    detail_basename_sorted = stale_artifacts(manifest, sort_by="detail-basename")
    detail_file_name_sorted = stale_artifacts(manifest, sort_by="detail-file-name")
    detail_path_sorted = stale_artifacts(manifest, sort_by="detail-page-path")

    assert [entry["artifact_name"] for entry in artifact_sorted] == ["alpha.json", "zulu.json"]
    assert [entry["artifact_name"] for entry in artifact_basename_sorted] == ["alpha.json", "zulu.json"]
    assert [entry["artifact_name"] for entry in artifact_file_name_sorted] == ["alpha.json", "zulu.json"]
    assert [entry["current_artifact_name"] for entry in current_sorted] == [
        "qwen-current.json",
        "base-current.json",
    ]
    assert [entry["current_artifact_name"] for entry in current_basename_sorted] == [
        "qwen-current.json",
        "base-current.json",
    ]
    assert [entry["current_artifact_name"] for entry in current_file_name_sorted] == [
        "qwen-current.json",
        "base-current.json",
    ]
    assert [entry["detail_page_name"] for entry in detail_sorted] == ["alpha.html", "zulu.html"]
    assert [entry["detail_page_name"] for entry in detail_basename_sorted] == ["alpha.html", "zulu.html"]
    assert [entry["detail_page_name"] for entry in detail_file_name_sorted] == ["alpha.html", "zulu.html"]
    assert [entry["detail_page_name"] for entry in detail_path_sorted] == ["alpha.html", "zulu.html"]


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


def test_stale_artifacts_accepts_artifact_path_sort_aliases() -> None:
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

    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="artifact-path")] == [
        "benchmark-results/base-old.json",
        "benchmark-results/parakeet-old.json",
        "benchmark-results/qwen-old.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="artifact-path-desc")] == [
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


def test_stale_artifacts_accepts_size_sort_aliases() -> None:
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

    descending = stale_artifacts(manifest, sort_by="disk-size-desc")
    ascending = stale_artifacts(manifest, sort_by="disk-size-asc")
    largest = stale_artifacts(manifest, sort_by="largest")
    file_size = stale_artifacts(manifest, sort_by="file-size")
    file_bytes_desc = stale_artifacts(manifest, sort_by="file-bytes-desc")
    heaviest = stale_artifacts(manifest, sort_by="heaviest")
    heaviest_first = stale_artifacts(manifest, sort_by="heaviest-first")
    smallest = stale_artifacts(manifest, sort_by="smallest")
    file_size_asc = stale_artifacts(manifest, sort_by="file-size-asc")
    lightest = stale_artifacts(manifest, sort_by="lightest")
    lightest_first = stale_artifacts(manifest, sort_by="lightest-first")

    assert [entry["artifact_path"] for entry in descending] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in largest] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in file_size] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in file_bytes_desc] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in heaviest] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in heaviest_first] == [
        "benchmark-results/large.json",
        "benchmark-results/small.json",
    ]
    assert [entry["artifact_path"] for entry in ascending] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in smallest] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in file_size_asc] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in lightest] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]
    assert [entry["artifact_path"] for entry in lightest_first] == [
        "benchmark-results/small.json",
        "benchmark-results/large.json",
    ]


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


def test_render_json_summary_can_group_by_artifact_path() -> None:
    rendered = render_json_summary(
        [
            {
                "artifact_path": "benchmark-results/archive/base.json",
                "status": "legacy",
                "artifact_size_bytes": 70,
            },
            {
                "artifact_path": "benchmark-results/base.json",
                "status": "legacy",
                "artifact_size_bytes": 30,
            },
        ],
        groups=["artifact-path"],
    )

    summary = json.loads(rendered)

    assert summary["by_artifact_path"] == [
        {
            "artifact_path": "benchmark-results/archive/base.json",
            "count": 1,
            "total_size_bytes": 70,
            "total_size": "70 B",
        },
        {
            "artifact_path": "benchmark-results/base.json",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
    ]


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


def test_render_json_summary_accepts_total_size_sort_aliases() -> None:
    stale = [
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
    ]

    for alias in ["total-size", "total-size-desc", "total-bytes", "total-bytes-desc"]:
        descending_summary = json.loads(
            render_json_summary(stale, groups=["slug"], summary_sort=alias)
        )
        assert [bucket["slug"] for bucket in descending_summary["by_slug"]] == ["base", "qwen"]

    for alias in ["total-size-asc", "total-bytes-asc"]:
        ascending_summary = json.loads(
            render_json_summary(stale, groups=["slug"], summary_sort=alias)
        )
        assert [bucket["slug"] for bucket in ascending_summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_readable_size_sort_aliases() -> None:
    stale = [
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
    ]

    largest_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="heaviest"))
    smallest_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="lightest"))

    assert [bucket["slug"] for bucket in largest_summary["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in smallest_summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_readable_count_sort_aliases() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/base-a.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 10,
        },
        {
            "artifact_path": "benchmark-results/base-b.json",
            "status": "legacy",
            "slug": "base",
            "artifact_size_bytes": 10,
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
            "status": "legacy",
            "slug": "qwen",
            "artifact_size_bytes": 100,
        },
    ]

    for alias in ["most-artifacts", "most-files", "most-files-first"]:
        most_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort=alias))
        assert [bucket["slug"] for bucket in most_summary["by_slug"]] == ["base", "qwen"]

    for alias in ["fewest-artifacts", "fewest-files", "least-files"]:
        fewest_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort=alias))
        assert [bucket["slug"] for bucket in fewest_summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_bytes_sort_aliases() -> None:
    stale = [
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
    ]

    descending_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="bytes-desc"))
    ascending_summary = json.loads(render_json_summary(stale, groups=["slug"], summary_sort="bytes-asc"))

    assert [bucket["slug"] for bucket in descending_summary["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in ascending_summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_disk_size_sort_aliases() -> None:
    stale = [
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
    ]

    descending_summary = json.loads(
        render_json_summary(stale, groups=["slug"], summary_sort="disk-size-desc")
    )
    ascending_summary = json.loads(
        render_json_summary(stale, groups=["slug"], summary_sort="disk-size-asc")
    )

    assert [bucket["slug"] for bucket in descending_summary["by_slug"]] == ["base", "qwen"]
    assert [bucket["slug"] for bucket in ascending_summary["by_slug"]] == ["qwen", "base"]


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


def test_render_json_summary_accepts_avg_size_sort_alias() -> None:
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
        summary_sort="avg-size",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_mean_bytes_sort_alias() -> None:
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
        summary_sort="mean-bytes",
    )

    summary = json.loads(rendered)

    assert [bucket["slug"] for bucket in summary["by_slug"]] == ["qwen", "base"]


def test_render_json_summary_accepts_avg_bytes_sort_aliases() -> None:
    stale = [
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
    ]

    descending_summary = json.loads(
        render_json_summary(stale, groups=["slug"], summary_sort="avg-bytes")
    )
    ascending_summary = json.loads(
        render_json_summary(stale, groups=["slug"], summary_sort="avg-bytes-asc")
    )

    assert [bucket["slug"] for bucket in descending_summary["by_slug"]] == ["qwen", "base"]
    assert [bucket["slug"] for bucket in ascending_summary["by_slug"]] == ["base", "qwen"]


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
        "artifact_path,artifact_name,artifact_stem,artifact_dir,artifact_extension,slug,label,backend,model,status,measured_at,measured_year,measured_month,measured_week,measured_day,age_days,age_bucket,age,current_artifact_path,current_artifact_name,current_artifact_stem,current_artifact_dir,current_artifact_extension,track_state,detail_page_path,detail_page_name,detail_page_stem,detail_page_dir,detail_page_extension,artifact_size_bytes,artifact_size",
        'benchmark-results/large.json,large.json,large,benchmark-results,.json,base,"Faster, Whisper",,,legacy,2026-06-10T00:00:00Z,2026,2026-06,2026-W24,2026-06-10,10,7-29d,10 days,benchmark-results/current.json,current.json,current,benchmark-results,.json,tracked,benchmark-results/pages/large.html,large.html,large,benchmark-results/pages,.html,90,90 B',
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


def test_parse_args_accepts_json_lines_output_aliases() -> None:
    assert parse_args(["--jsonl"]).json_lines is True
    assert parse_args(["--ndjson"]).json_lines is True


def test_parse_args_accepts_json_summary_share_flag() -> None:
    assert parse_args(["--json-summary", "--summary-share"]).summary_share is True


def test_parse_args_accepts_summary_csv_output_flag() -> None:
    assert parse_args(["--summary-csv", "--summary-share"]).summary_csv is True


def test_render_summary_csv_includes_average_size_for_average_sorts() -> None:
    rendered = render_summary_csv(
        [
            {"artifact_path": "benchmark-results/base-a.json", "slug": "base", "artifact_size_bytes": 50},
            {"artifact_path": "benchmark-results/base-b.json", "slug": "base", "artifact_size_bytes": 70},
        ],
        groups=["slug"],
        summary_sort="average-size",
    )

    assert rendered.splitlines() == [
        "group,bucket,count,total_size_bytes,total_size,average_size_bytes,average_size,count_share_percent,size_share_percent",
        "slug,base,2,120,120 B,60.0,60 B,,",
    ]


def test_render_summary_markdown_includes_average_size_for_average_sorts() -> None:
    rendered = render_summary_markdown(
        [
            {"artifact_path": "benchmark-results/base-a.json", "slug": "base", "artifact_size_bytes": 50},
            {"artifact_path": "benchmark-results/base-b.json", "slug": "base", "artifact_size_bytes": 70},
        ],
        groups=["slug"],
        summary_sort="avg-size",
    )

    assert rendered.splitlines() == [
        "Found 2 stale benchmark artifacts (120 B, 120 bytes).",
        "",
        "| Group | Bucket | Count | Total size | Average size | Count share | Size share |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        "| slug | base | 2 | 120 B | 60 B | unknown | unknown |",
    ]


def test_parse_args_accepts_output_path() -> None:
    assert parse_args(["--output", "cleanup/report.txt"]).output == Path("cleanup/report.txt")


def test_parse_args_accepts_stdout_output_marker() -> None:
    assert parse_args(["--output", "-"]).output == Path("-")


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


def test_stale_artifacts_accepts_age_bucket_sort_aliases() -> None:
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
        ],
    }

    stale = stale_artifacts(
        manifest,
        now=datetime(2026, 6, 20, tzinfo=UTC),
        sort_by="age_range_bucket_desc",
    )

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/month-old.json",
        "benchmark-results/recent.json",
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


def test_stale_summary_groups_artifact_size_by_artifact_path() -> None:
    stale = [
        {"artifact_path": "benchmark-results/archive/base-old.json", "artifact_size_bytes": 20},
        {"artifact_path": "benchmark-results/base-old.json", "artifact_size_bytes": 30},
        {"artifact_path": "benchmark-results/qwen.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_artifact_path"] == [
        {
            "artifact_path": "benchmark-results/base-old.json",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "artifact_path": "benchmark-results/archive/base-old.json",
            "count": 1,
            "total_size_bytes": 20,
            "total_size": "20 B",
        },
        {
            "artifact_path": "benchmark-results/qwen.json",
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


def test_stale_summary_groups_artifact_size_by_measured_year() -> None:
    stale = [
        {
            "artifact_path": "benchmark-results/old-large.json",
            "measured_at": "2025-12-15T00:00:00Z",
            "artifact_size_bytes": 40,
        },
        {
            "artifact_path": "benchmark-results/new.json",
            "measured_at": "2026-01-01T00:00:00Z",
            "artifact_size_bytes": 30,
        },
        {
            "artifact_path": "benchmark-results/old-small.json",
            "measured_at": "2025-06-20",
            "artifact_size_bytes": 10,
        },
        {"artifact_path": "benchmark-results/unknown.json", "artifact_size_bytes": 5},
    ]

    summary = stale_summary(stale)

    assert summary["by_measured_year"] == [
        {
            "measured_year": "2025",
            "count": 2,
            "total_size_bytes": 50,
            "total_size": "50 B",
        },
        {
            "measured_year": "2026",
            "count": 1,
            "total_size_bytes": 30,
            "total_size": "30 B",
        },
        {
            "measured_year": "unknown",
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


def test_stale_artifacts_accepts_readable_measured_time_sort_aliases() -> None:
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
        ],
    }

    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="oldest")] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="earliest-first")] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="least-recent")] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="least-recent-first")] == [
        "benchmark-results/older.json",
        "benchmark-results/newer.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="newest")] == [
        "benchmark-results/newer.json",
        "benchmark-results/older.json",
    ]
    assert [entry["artifact_path"] for entry in stale_artifacts(manifest, sort_by="latest-first")] == [
        "benchmark-results/newer.json",
        "benchmark-results/older.json",
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


def test_stale_artifacts_can_sort_by_artifact_extension_descending_with_prefix_extensions() -> None:
    manifest = {
        "tracks": [],
        "artifacts": [
            {
                "artifact_path": "benchmark-results/short.a",
                "status": "legacy",
                "artifact_size_bytes": 20,
            },
            {
                "artifact_path": "benchmark-results/long.aa",
                "status": "legacy",
                "artifact_size_bytes": 10,
            },
        ],
    }

    stale = stale_artifacts(manifest, sort_by="path-extension-desc")

    assert [entry["artifact_path"] for entry in stale] == [
        "benchmark-results/long.aa",
        "benchmark-results/short.a",
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

    status_alias = stale_artifacts(manifest, sort_by="track-status-desc")

    assert [entry["artifact_path"] for entry in status_alias] == [
        "benchmark-results/untracked-b.json",
        "benchmark-results/untracked-a.json",
        "benchmark-results/qwen-old.json",
        "benchmark-results/base-old.json",
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


def test_stale_artifacts_accepts_current_artifact_sort_alias() -> None:
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
                "artifact_path": "benchmark-results/base-old.json",
                "status": "legacy",
                "slug": "base",
                "artifact_size_bytes": 20,
            },
        ],
    }

    assert stale_artifacts(manifest, sort_by="current-artifact") == stale_artifacts(
        manifest,
        sort_by="current-path",
    )


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
    assert format_bytes(3 * 1024**4) == "3.0 TiB"


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
        "By artifact path:\n"
        "- benchmark-results/untracked.json: 1 artifact (30 B, 30 bytes)\n"
        "- benchmark-results/base-old.json: 1 artifact (20 B, 20 bytes)\n"
        "- benchmark-results/base-older.json: 1 artifact (15 B, 15 bytes)\n"
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
        "By measured week:\n"
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


def test_main_paths_only_can_read_existing_manifest_from_stdin(monkeypatch, capsys) -> None:
    def fail_build_manifest(*args, **kwargs):
        raise AssertionError("--manifest - should skip manifest rebuild")

    monkeypatch.setattr(report_module, "build_manifest", fail_build_manifest)
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
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
            )
        ),
    )

    assert report_module.main(["--manifest", "-", "--paths-only"]) == 0

    assert capsys.readouterr().out == "benchmark-results/old.json\n"


def test_main_rejects_invalid_stdin_manifest(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))

    with pytest.raises(ValueError, match="stdin contains invalid JSON"):
        report_module.main(["--manifest", "-", "--paths-only"])


def test_main_rejects_non_object_existing_manifest(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        report_module.main(["--manifest", str(manifest_path), "--paths-only"])


def test_main_rejects_non_object_stdin_manifest(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))

    with pytest.raises(ValueError, match="stdin must contain a JSON object"):
        report_module.main(["--manifest", "-", "--paths-only"])


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
    assert (
        report_module.main(
            [
                "--fail-on-stale",
                "--artifact-status",
                "any",
                "--artifact-status-contains",
                "review",
            ]
        )
        == 1
    )


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
    assert (
        report_module.main(
            ["--fail-on-stale", "--current-artifact", "benchmark-results/base-current.json"]
        )
        == 1
    )
    assert (
        report_module.main(
            ["--fail-on-stale", "--current-artifact-path", "benchmark-results/base-current.json"]
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
    assert report_module.main(["--fail-on-stale", "--current-artifact-path-contains", "whisper"]) == 1


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
    assert report_module.main(["--fail-on-stale", "--artifact-status", "blocked"]) == 1


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
        "By artifact path:\n"
        "- benchmark-results/large.json: 1 artifact (90 B, 90 bytes)\n"
        "- benchmark-results/small.json: 1 artifact (10 B, 10 bytes)\n"
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
        "By measured week:\n"
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
        "artifact_path,artifact_name,artifact_stem,artifact_dir,artifact_extension,slug,label,backend,model,status,measured_at,measured_year,measured_month,measured_week,measured_day,age_days,age_bucket,age,current_artifact_path,current_artifact_name,current_artifact_stem,current_artifact_dir,current_artifact_extension,track_state,detail_page_path,detail_page_name,detail_page_stem,detail_page_dir,detail_page_extension,artifact_size_bytes,artifact_size\r\n"
        'benchmark-results/large.json,large.json,large,benchmark-results,.json,base,"Faster, Whisper",,,legacy,,unknown,unknown,unknown,unknown,,unknown,unknown,benchmark-results/base-current.json,base-current.json,base-current,benchmark-results,.json,tracked,benchmark-results/pages/large.html,large.html,large,benchmark-results/pages,.html,90,90 B\r\n'
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


def test_main_output_dash_writes_rendered_report_to_stdout(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.chdir(tmp_path)
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

    assert report_module.main(["--paths-only", "--output", "-"]) == 0

    assert capsys.readouterr().out == "benchmark-results/base.json\n"
    assert not Path("-").exists()


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
        assert str(error) == (
            "--summary-group requires --summary-only, --json-summary, --summary-csv, or --summary-markdown"
        )
    else:
        raise AssertionError("--summary-group without --summary-only should be rejected")


def test_main_rejects_summary_limit_without_summary_only() -> None:
    try:
        report_module.main(["--summary-limit", "1"])
    except ValueError as error:
        assert str(error) == (
            "--summary-limit requires --summary-only, --json-summary, --summary-csv, or --summary-markdown"
        )
    else:
        raise AssertionError("--summary-limit without --summary-only should be rejected")


def test_main_rejects_summary_range_filters_without_summary_output() -> None:
    for args, expected in [
        (
            ["--summary-min-count", "1"],
            "--summary-min-count requires --summary-only, --json-summary, --summary-csv, or --summary-markdown",
        ),
        (
            ["--summary-max-count", "1"],
            "--summary-max-count requires --summary-only, --json-summary, --summary-csv, or --summary-markdown",
        ),
        (
            ["--summary-min-size-bytes", "1"],
            "--summary-min-size-bytes requires --summary-only, --json-summary, --summary-csv, or --summary-markdown",
        ),
        (
            ["--summary-max-size-bytes", "1"],
            "--summary-max-size-bytes requires --summary-only, --json-summary, --summary-csv, or --summary-markdown",
        ),
    ]:
        try:
            report_module.main(args)
        except ValueError as error:
            assert str(error) == expected
        else:
            raise AssertionError(f"{args} should require summary output")
