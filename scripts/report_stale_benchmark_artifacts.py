#!/usr/bin/env python3
"""Report benchmark artifacts that are no longer current track evidence."""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from build_benchmark_manifest import DEFAULT_RESULTS_DIR, DEFAULT_TRACKS_PATH, build_manifest

SUMMARY_GROUPS = (
    "slug",
    "artifact-path",
    "artifact-name",
    "artifact-stem",
    "artifact-dir",
    "artifact-extension",
    "status",
    "backend",
    "model",
    "label",
    "current-artifact",
    "current-artifact-name",
    "current-artifact-stem",
    "current-artifact-dir",
    "current-artifact-extension",
    "track-state",
    "detail-page",
    "detail-page-name",
    "detail-page-stem",
    "detail-page-dir",
    "detail-page-extension",
    "measured-year",
    "measured-quarter",
    "measured-month",
    "measured-week",
    "measured-day",
    "age-bucket",
)

SUMMARY_GROUP_KEYS = {
    "slug": "by_slug",
    "artifact-path": "by_artifact_path",
    "artifact-name": "by_artifact_name",
    "artifact-stem": "by_artifact_stem",
    "artifact-dir": "by_artifact_dir",
    "artifact-extension": "by_artifact_extension",
    "status": "by_status",
    "backend": "by_backend",
    "model": "by_model",
    "label": "by_label",
    "current-artifact": "by_current_artifact_path",
    "current-artifact-name": "by_current_artifact_name",
    "current-artifact-stem": "by_current_artifact_stem",
    "current-artifact-dir": "by_current_artifact_dir",
    "current-artifact-extension": "by_current_artifact_extension",
    "track-state": "by_track_state",
    "track-status": "by_track_state",
    "detail-page": "by_detail_page_path",
    "detail-page-name": "by_detail_page_name",
    "detail-page-stem": "by_detail_page_stem",
    "detail-page-dir": "by_detail_page_dir",
    "detail-page-extension": "by_detail_page_extension",
    "measured-year": "by_measured_year",
    "measured-quarter": "by_measured_quarter",
    "measured-month": "by_measured_month",
    "measured-week": "by_measured_week",
    "measured-day": "by_measured_day",
    "age-bucket": "by_age_bucket",
}

SUMMARY_OUTPUT_REQUIREMENT = "--summary-only, --json-summary, --summary-csv, or --summary-markdown"

SUMMARY_GROUP_ALIASES = {
    "path-name": "artifact-name",
    "path-basename": "artifact-name",
    "path-filename": "artifact-name",
    "path-file-name": "artifact-name",
    "path-stem": "artifact-stem",
    "path-file-stem": "artifact-stem",
    "path-dir": "artifact-dir",
    "path-directory": "artifact-dir",
    "path-dirname": "artifact-dir",
    "path-folder": "artifact-dir",
    "path-folder-name": "artifact-dir",
    "path-extension": "artifact-extension",
    "path-ext": "artifact-extension",
    "path-file-ext": "artifact-extension",
    "path-file-extension": "artifact-extension",
    "filename": "artifact-name",
    "file-name": "artifact-name",
    "basename": "artifact-name",
    "file-stem": "artifact-stem",
    "stem": "artifact-stem",
    "directory": "artifact-dir",
    "dirname": "artifact-dir",
    "folder": "artifact-dir",
    "folder-name": "artifact-dir",
    "extension": "artifact-extension",
    "ext": "artifact-extension",
    "file-ext": "artifact-extension",
    "file-extension": "artifact-extension",
    "artifact-basename": "artifact-name",
    "artifact-filename": "artifact-name",
    "artifact-file-name": "artifact-name",
    "artifact-file-stem": "artifact-stem",
    "artifact-path-name": "artifact-name",
    "artifact-path-basename": "artifact-name",
    "artifact-path-filename": "artifact-name",
    "artifact-path-file-name": "artifact-name",
    "artifact-path-stem": "artifact-stem",
    "artifact-path-file-stem": "artifact-stem",
    "artifact-path-dir": "artifact-dir",
    "artifact-path-directory": "artifact-dir",
    "artifact-path-dirname": "artifact-dir",
    "artifact-path-folder": "artifact-dir",
    "artifact-path-folder-name": "artifact-dir",
    "artifact-path-extension": "artifact-extension",
    "artifact-path-ext": "artifact-extension",
    "artifact-path-file-ext": "artifact-extension",
    "artifact-path-file-extension": "artifact-extension",
    "current-path": "current-artifact",
    "current-artifact-path": "current-artifact",
    "current-basename": "current-artifact-name",
    "current-filename": "current-artifact-name",
    "current-file-name": "current-artifact-name",
    "current-artifact-file-name": "current-artifact-name",
    "current-path-name": "current-artifact-name",
    "current-path-stem": "current-artifact-stem",
    "current-file-stem": "current-artifact-stem",
    "current-artifact-file-stem": "current-artifact-stem",
    "current-path-dir": "current-artifact-dir",
    "artifact-directory": "artifact-dir",
    "artifact-dirname": "artifact-dir",
    "artifact-folder": "artifact-dir",
    "artifact-folder-name": "artifact-dir",
    "current-artifact-directory": "current-artifact-dir",
    "current-artifact-dirname": "current-artifact-dir",
    "current-artifact-folder": "current-artifact-dir",
    "current-artifact-folder-name": "current-artifact-dir",
    "current-path-directory": "current-artifact-dir",
    "current-path-dirname": "current-artifact-dir",
    "current-path-folder": "current-artifact-dir",
    "current-path-folder-name": "current-artifact-dir",
    "current-directory": "current-artifact-dir",
    "current-dir": "current-artifact-dir",
    "current-dirname": "current-artifact-dir",
    "current-folder": "current-artifact-dir",
    "current-folder-name": "current-artifact-dir",
    "detail-directory": "detail-page-dir",
    "detail-dir": "detail-page-dir",
    "detail-dirname": "detail-page-dir",
    "detail-folder": "detail-page-dir",
    "detail-folder-name": "detail-page-dir",
    "detail-page-directory": "detail-page-dir",
    "detail-page-dirname": "detail-page-dir",
    "detail-page-folder": "detail-page-dir",
    "detail-page-folder-name": "detail-page-dir",
    "artifact-ext": "artifact-extension",
    "artifact-file-ext": "artifact-extension",
    "artifact-file-extension": "artifact-extension",
    "current-extension": "current-artifact-extension",
    "current-ext": "current-artifact-extension",
    "current-artifact-ext": "current-artifact-extension",
    "current-artifact-file-ext": "current-artifact-extension",
    "current-artifact-file-extension": "current-artifact-extension",
    "current-file-ext": "current-artifact-extension",
    "current-file-extension": "current-artifact-extension",
    "current-path-ext": "current-artifact-extension",
    "current-path-file-ext": "current-artifact-extension",
    "current-path-file-extension": "current-artifact-extension",
    "current-path-extension": "current-artifact-extension",
    "detail-extension": "detail-page-extension",
    "detail-ext": "detail-page-extension",
    "detail-file-ext": "detail-page-extension",
    "detail-file-extension": "detail-page-extension",
    "detail-page-ext": "detail-page-extension",
    "detail-path": "detail-page",
    "detail-page-path": "detail-page",
    "detail-basename": "detail-page-name",
    "detail-page-basename": "detail-page-name",
    "detail-filename": "detail-page-name",
    "detail-page-filename": "detail-page-name",
    "detail-file-name": "detail-page-name",
    "detail-page-file-name": "detail-page-name",
    "detail-file-stem": "detail-page-stem",
    "detail-stem": "detail-page-stem",
    "detail-page-file-stem": "detail-page-stem",
    "detail-page-file-ext": "detail-page-extension",
    "detail-page-file-extension": "detail-page-extension",
    "track-status": "track-state",
    "year": "measured-year",
    "calendar-year": "measured-year",
    "measurement-year": "measured-year",
    "measured-at-year": "measured-year",
    "quarter": "measured-quarter",
    "calendar-quarter": "measured-quarter",
    "measurement-quarter": "measured-quarter",
    "measured-at-quarter": "measured-quarter",
    "month": "measured-month",
    "calendar-month": "measured-month",
    "measurement-month": "measured-month",
    "measured-at-month": "measured-month",
    "week": "measured-week",
    "calendar-week": "measured-week",
    "iso-week": "measured-week",
    "measured-at-iso-week": "measured-week",
    "measurement-iso-week": "measured-week",
    "measurement-week": "measured-week",
    "measured-at-week": "measured-week",
    "date": "measured-day",
    "calendar-date": "measured-day",
    "day": "measured-day",
    "calendar-day": "measured-day",
    "measurement-date": "measured-day",
    "measurement-day": "measured-day",
    "measured-date": "measured-day",
    "measured-at-date": "measured-day",
    "measured-at-day": "measured-day",
    "age-range": "age-bucket",
    "age-range-bucket": "age-bucket",
    "stale-age-bucket": "age-bucket",
    "staleness-bucket": "age-bucket",
}

STALE_SORT_ALIASES = {
    "biggest": "size",
    "biggest-first": "size",
    "heaviest": "size",
    "heaviest-first": "size",
    "largest-first": "size",
    "largest-bytes": "size",
    "largest-bytes-first": "size",
    "top": "size",
    "top-first": "size",
    "top-size": "size",
    "top-size-first": "size",
    "top-bytes": "size",
    "top-bytes-first": "size",
    "max-size": "size",
    "max-size-first": "size",
    "max-bytes": "size",
    "max-bytes-first": "size",
    "lightest": "size-asc",
    "lightest-first": "size-asc",
    "smallest-first": "size-asc",
    "smallest-bytes": "size-asc",
    "smallest-bytes-first": "size-asc",
    "bottom": "size-asc",
    "bottom-first": "size-asc",
    "bottom-size": "size-asc",
    "bottom-size-first": "size-asc",
    "bottom-bytes": "size-asc",
    "bottom-bytes-first": "size-asc",
    "min-size": "size-asc",
    "min-size-first": "size-asc",
    "min-bytes": "size-asc",
    "min-bytes-first": "size-asc",
    "total-bytes": "size",
    "total-bytes-desc": "size",
    "total-bytes-asc": "size-asc",
    "file-size": "size",
    "file-size-desc": "size",
    "file-size-asc": "size-asc",
    "file-bytes": "size",
    "file-bytes-desc": "size",
    "file-bytes-asc": "size-asc",
    "artifact-size": "size",
    "artifact-size-desc": "size",
    "artifact-size-asc": "size-asc",
    "artifact-bytes": "size",
    "artifact-bytes-desc": "size",
    "artifact-bytes-asc": "size-asc",
    "freshest": "age-asc",
    "freshest-first": "age-asc",
    "newest": "measured-at-desc",
    "newest-first": "measured-at-desc",
    "latest": "measured-at-desc",
    "latest-first": "measured-at-desc",
    "recent": "measured-at-desc",
    "recent-first": "measured-at-desc",
    "most-recent": "measured-at-desc",
    "most-recent-first": "measured-at-desc",
    "oldest": "measured-at",
    "oldest-first": "measured-at",
    "earliest": "measured-at",
    "earliest-first": "measured-at",
    "least-recent": "measured-at",
    "least-recent-first": "measured-at",
    "measurement-time": "measured-at",
    "measurement-time-asc": "measured-at",
    "measurement-time-desc": "measured-at-desc",
    "measured-time": "measured-at",
    "measured-time-asc": "measured-at",
    "measured-time-desc": "measured-at-desc",
    "timestamp": "measured-at",
    "timestamp-asc": "measured-at",
    "timestamp-desc": "measured-at-desc",
    "time": "measured-at",
    "time-asc": "measured-at",
    "time-desc": "measured-at-desc",
    "stale": "age",
    "stale-first": "age",
    "stalest": "age",
    "stalest-first": "age",
    "alphabetical": "path",
    "alphabetical-first": "path",
    "alphabetical-asc": "path-asc",
    "alphabetical-desc": "path-desc",
    "alpha": "path",
    "alpha-first": "path",
    "alpha-asc": "path-asc",
    "alpha-desc": "path-desc",
    "reverse-alphabetical": "path-desc",
    "reverse-alphabetical-first": "path-desc",
    "reverse-alpha": "path-desc",
    "reverse-alpha-first": "path-desc",
    "reverse-path": "path-desc",
    "reverse-path-first": "path-desc",
    "path-reverse": "path-desc",
    "path-reverse-first": "path-desc",
    "track-status": "track-state",
    "track-status-asc": "track-state-asc",
    "track-status-desc": "track-state-desc",
    "a-z": "path-asc",
    "z-a": "path-desc",
    "year": "measured-year",
    "year-asc": "measured-year-asc",
    "year-desc": "measured-year-desc",
    "calendar-year": "measured-year",
    "calendar-year-asc": "measured-year-asc",
    "calendar-year-desc": "measured-year-desc",
    "measurement-year": "measured-year",
    "measurement-year-asc": "measured-year-asc",
    "measurement-year-desc": "measured-year-desc",
    "measured-at-year": "measured-year",
    "measured-at-year-asc": "measured-year-asc",
    "measured-at-year-desc": "measured-year-desc",
    "quarter": "measured-quarter",
    "quarter-asc": "measured-quarter-asc",
    "quarter-desc": "measured-quarter-desc",
    "calendar-quarter": "measured-quarter",
    "calendar-quarter-asc": "measured-quarter-asc",
    "calendar-quarter-desc": "measured-quarter-desc",
    "measurement-quarter": "measured-quarter",
    "measurement-quarter-asc": "measured-quarter-asc",
    "measurement-quarter-desc": "measured-quarter-desc",
    "measured-at-quarter": "measured-quarter",
    "measured-at-quarter-asc": "measured-quarter-asc",
    "measured-at-quarter-desc": "measured-quarter-desc",
    "month": "measured-month",
    "month-asc": "measured-month-asc",
    "month-desc": "measured-month-desc",
    "calendar-month": "measured-month",
    "calendar-month-asc": "measured-month-asc",
    "calendar-month-desc": "measured-month-desc",
    "measurement-month": "measured-month",
    "measurement-month-asc": "measured-month-asc",
    "measurement-month-desc": "measured-month-desc",
    "measured-at-month": "measured-month",
    "measured-at-month-asc": "measured-month-asc",
    "measured-at-month-desc": "measured-month-desc",
    "week": "measured-week",
    "week-asc": "measured-week-asc",
    "week-desc": "measured-week-desc",
    "calendar-week": "measured-week",
    "calendar-week-asc": "measured-week-asc",
    "calendar-week-desc": "measured-week-desc",
    "iso-week": "measured-week",
    "iso-week-asc": "measured-week-asc",
    "iso-week-desc": "measured-week-desc",
    "measured-at-iso-week": "measured-week",
    "measured-at-iso-week-asc": "measured-week-asc",
    "measured-at-iso-week-desc": "measured-week-desc",
    "measurement-iso-week": "measured-week",
    "measurement-iso-week-asc": "measured-week-asc",
    "measurement-iso-week-desc": "measured-week-desc",
    "measurement-week": "measured-week",
    "measurement-week-asc": "measured-week-asc",
    "measurement-week-desc": "measured-week-desc",
    "measured-at-week": "measured-week",
    "measured-at-week-asc": "measured-week-asc",
    "measured-at-week-desc": "measured-week-desc",
    "date": "measured-day",
    "date-asc": "measured-day-asc",
    "date-desc": "measured-day-desc",
    "calendar-date": "measured-day",
    "calendar-date-asc": "measured-day-asc",
    "calendar-date-desc": "measured-day-desc",
    "day": "measured-day",
    "day-asc": "measured-day-asc",
    "day-desc": "measured-day-desc",
    "calendar-day": "measured-day",
    "calendar-day-asc": "measured-day-asc",
    "calendar-day-desc": "measured-day-desc",
    "measurement-date": "measured-day",
    "measurement-date-asc": "measured-day-asc",
    "measurement-date-desc": "measured-day-desc",
    "measurement-day": "measured-day",
    "measurement-day-asc": "measured-day-asc",
    "measurement-day-desc": "measured-day-desc",
    "measured-date": "measured-day",
    "measured-date-asc": "measured-day-asc",
    "measured-date-desc": "measured-day-desc",
    "measured-at-date": "measured-day",
    "measured-at-date-asc": "measured-day-asc",
    "measured-at-date-desc": "measured-day-desc",
    "measured-at-day": "measured-day",
    "measured-at-day-asc": "measured-day-asc",
    "measured-at-day-desc": "measured-day-desc",
    "age-range": "age-bucket",
    "age-range-asc": "age-bucket-asc",
    "age-range-desc": "age-bucket-desc",
    "age-range-bucket": "age-bucket",
    "age-range-bucket-asc": "age-bucket-asc",
    "age-range-bucket-desc": "age-bucket-desc",
    "stale-age-bucket": "age-bucket",
    "stale-age-bucket-asc": "age-bucket-asc",
    "stale-age-bucket-desc": "age-bucket-desc",
    "staleness-bucket": "age-bucket",
    "staleness-bucket-asc": "age-bucket-asc",
    "staleness-bucket-desc": "age-bucket-desc",
    "current-artifact": "current-path",
    "current-artifact-asc": "current-path-asc",
    "current-artifact-desc": "current-path-desc",
    "current-artifact-name": "current-path-name",
    "current-artifact-name-asc": "current-path-name-asc",
    "current-artifact-name-desc": "current-path-name-desc",
    "current-artifact-file-name": "current-path-name",
    "current-artifact-file-name-asc": "current-path-name-asc",
    "current-artifact-file-name-desc": "current-path-name-desc",
    "current-artifact-stem": "current-path-stem",
    "current-artifact-stem-asc": "current-path-stem-asc",
    "current-artifact-stem-desc": "current-path-stem-desc",
    "path-name": "artifact-name",
    "path-name-asc": "artifact-name-asc",
    "path-name-desc": "artifact-name-desc",
    "path-basename": "artifact-name",
    "path-basename-asc": "artifact-name-asc",
    "path-basename-desc": "artifact-name-desc",
    "path-filename": "artifact-name",
    "path-filename-asc": "artifact-name-asc",
    "path-filename-desc": "artifact-name-desc",
    "path-file-name": "artifact-name",
    "path-file-name-asc": "artifact-name-asc",
    "path-file-name-desc": "artifact-name-desc",
    "path-stem": "artifact-stem",
    "path-stem-asc": "artifact-stem-asc",
    "path-stem-desc": "artifact-stem-desc",
    "path-file-stem": "artifact-stem",
    "path-file-stem-asc": "artifact-stem-asc",
    "path-file-stem-desc": "artifact-stem-desc",
    "path-dir": "artifact-dir",
    "path-dir-asc": "artifact-dir-asc",
    "path-dir-desc": "artifact-dir-desc",
    "path-directory": "artifact-dir",
    "path-directory-asc": "artifact-dir-asc",
    "path-directory-desc": "artifact-dir-desc",
    "path-dirname": "artifact-dir",
    "path-dirname-asc": "artifact-dir-asc",
    "path-dirname-desc": "artifact-dir-desc",
    "path-folder": "artifact-dir",
    "path-folder-asc": "artifact-dir-asc",
    "path-folder-desc": "artifact-dir-desc",
    "path-folder-name": "artifact-dir",
    "path-folder-name-asc": "artifact-dir-asc",
    "path-folder-name-desc": "artifact-dir-desc",
    "path-extension": "artifact-extension",
    "path-extension-asc": "artifact-extension-asc",
    "path-extension-desc": "artifact-extension-desc",
    "path-ext": "artifact-extension",
    "path-ext-asc": "artifact-extension-asc",
    "path-ext-desc": "artifact-extension-desc",
    "path-file-ext": "artifact-extension",
    "path-file-ext-asc": "artifact-extension-asc",
    "path-file-ext-desc": "artifact-extension-desc",
    "path-file-extension": "artifact-extension",
    "path-file-extension-asc": "artifact-extension-asc",
    "path-file-extension-desc": "artifact-extension-desc",
    "current-file-stem": "current-path-stem",
    "current-file-stem-asc": "current-path-stem-asc",
    "current-file-stem-desc": "current-path-stem-desc",
    "current-artifact-file-stem": "current-path-stem",
    "current-artifact-file-stem-asc": "current-path-stem-asc",
    "current-artifact-file-stem-desc": "current-path-stem-desc",
    "current-artifact-dir": "current-path-dir",
    "current-artifact-dir-asc": "current-path-dir-asc",
    "current-artifact-dir-desc": "current-path-dir-desc",
    "current-artifact-directory": "current-path-dir",
    "current-artifact-directory-asc": "current-path-dir-asc",
    "current-artifact-directory-desc": "current-path-dir-desc",
    "current-artifact-dirname": "current-path-dir",
    "current-artifact-dirname-asc": "current-path-dir-asc",
    "current-artifact-dirname-desc": "current-path-dir-desc",
    "current-artifact-folder": "current-path-dir",
    "current-artifact-folder-asc": "current-path-dir-asc",
    "current-artifact-folder-desc": "current-path-dir-desc",
    "current-artifact-folder-name": "current-path-dir",
    "current-artifact-folder-name-asc": "current-path-dir-asc",
    "current-artifact-folder-name-desc": "current-path-dir-desc",
    "current-artifact-extension": "current-path-extension",
    "current-artifact-extension-asc": "current-path-extension-asc",
    "current-artifact-extension-desc": "current-path-extension-desc",
    "current-artifact-ext": "current-path-extension",
    "current-artifact-ext-asc": "current-path-extension-asc",
    "current-artifact-ext-desc": "current-path-extension-desc",
    "current-artifact-file-ext": "current-path-extension",
    "current-artifact-file-ext-asc": "current-path-extension-asc",
    "current-artifact-file-ext-desc": "current-path-extension-desc",
    "current-artifact-file-extension": "current-path-extension",
    "current-artifact-file-extension-asc": "current-path-extension-asc",
    "current-artifact-file-extension-desc": "current-path-extension-desc",
    "artifact-basename": "artifact-name",
    "artifact-basename-asc": "artifact-name-asc",
    "artifact-basename-desc": "artifact-name-desc",
    "artifact-filename": "artifact-name",
    "artifact-filename-asc": "artifact-name-asc",
    "artifact-filename-desc": "artifact-name-desc",
    "artifact-file-name": "artifact-name",
    "artifact-file-name-asc": "artifact-name-asc",
    "artifact-file-name-desc": "artifact-name-desc",
    "artifact-file-stem": "artifact-stem",
    "artifact-file-stem-asc": "artifact-stem-asc",
    "artifact-file-stem-desc": "artifact-stem-desc",
    "artifact-path-name": "artifact-name",
    "artifact-path-name-asc": "artifact-name-asc",
    "artifact-path-name-desc": "artifact-name-desc",
    "artifact-path-basename": "artifact-name",
    "artifact-path-basename-asc": "artifact-name-asc",
    "artifact-path-basename-desc": "artifact-name-desc",
    "artifact-path-filename": "artifact-name",
    "artifact-path-filename-asc": "artifact-name-asc",
    "artifact-path-filename-desc": "artifact-name-desc",
    "artifact-path-file-name": "artifact-name",
    "artifact-path-file-name-asc": "artifact-name-asc",
    "artifact-path-file-name-desc": "artifact-name-desc",
    "artifact-path-stem": "artifact-stem",
    "artifact-path-stem-asc": "artifact-stem-asc",
    "artifact-path-stem-desc": "artifact-stem-desc",
    "artifact-path-file-stem": "artifact-stem",
    "artifact-path-file-stem-asc": "artifact-stem-asc",
    "artifact-path-file-stem-desc": "artifact-stem-desc",
    "artifact-directory": "artifact-dir",
    "artifact-directory-asc": "artifact-dir-asc",
    "artifact-directory-desc": "artifact-dir-desc",
    "artifact-dirname": "artifact-dir",
    "artifact-dirname-asc": "artifact-dir-asc",
    "artifact-dirname-desc": "artifact-dir-desc",
    "artifact-folder": "artifact-dir",
    "artifact-folder-asc": "artifact-dir-asc",
    "artifact-folder-desc": "artifact-dir-desc",
    "artifact-folder-name": "artifact-dir",
    "artifact-folder-name-asc": "artifact-dir-asc",
    "artifact-folder-name-desc": "artifact-dir-desc",
    "artifact-path-dir": "artifact-dir",
    "artifact-path-dir-asc": "artifact-dir-asc",
    "artifact-path-dir-desc": "artifact-dir-desc",
    "artifact-path-directory": "artifact-dir",
    "artifact-path-directory-asc": "artifact-dir-asc",
    "artifact-path-directory-desc": "artifact-dir-desc",
    "artifact-path-dirname": "artifact-dir",
    "artifact-path-dirname-asc": "artifact-dir-asc",
    "artifact-path-dirname-desc": "artifact-dir-desc",
    "artifact-path-folder": "artifact-dir",
    "artifact-path-folder-asc": "artifact-dir-asc",
    "artifact-path-folder-desc": "artifact-dir-desc",
    "artifact-path-folder-name": "artifact-dir",
    "artifact-path-folder-name-asc": "artifact-dir-asc",
    "artifact-path-folder-name-desc": "artifact-dir-desc",
    "artifact-ext": "artifact-extension",
    "artifact-ext-asc": "artifact-extension-asc",
    "artifact-ext-desc": "artifact-extension-desc",
    "artifact-file-ext": "artifact-extension",
    "artifact-file-ext-asc": "artifact-extension-asc",
    "artifact-file-ext-desc": "artifact-extension-desc",
    "artifact-file-extension": "artifact-extension",
    "artifact-file-extension-asc": "artifact-extension-asc",
    "artifact-file-extension-desc": "artifact-extension-desc",
    "artifact-path-extension": "artifact-extension",
    "artifact-path-extension-asc": "artifact-extension-asc",
    "artifact-path-extension-desc": "artifact-extension-desc",
    "artifact-path-ext": "artifact-extension",
    "artifact-path-ext-asc": "artifact-extension-asc",
    "artifact-path-ext-desc": "artifact-extension-desc",
    "artifact-path-file-ext": "artifact-extension",
    "artifact-path-file-ext-asc": "artifact-extension-asc",
    "artifact-path-file-ext-desc": "artifact-extension-desc",
    "artifact-path-file-extension": "artifact-extension",
    "artifact-path-file-extension-asc": "artifact-extension-asc",
    "artifact-path-file-extension-desc": "artifact-extension-desc",
    "current-basename": "current-path-name",
    "current-basename-asc": "current-path-name-asc",
    "current-basename-desc": "current-path-name-desc",
    "current-filename": "current-path-name",
    "current-filename-asc": "current-path-name-asc",
    "current-filename-desc": "current-path-name-desc",
    "current-file-name": "current-path-name",
    "current-file-name-asc": "current-path-name-asc",
    "current-file-name-desc": "current-path-name-desc",
    "current-artifact-path": "current-path",
    "current-artifact-path-asc": "current-path-asc",
    "current-artifact-path-desc": "current-path-desc",
    "current-artifact-directory": "current-path-dir",
    "current-artifact-directory-asc": "current-path-dir-asc",
    "current-artifact-directory-desc": "current-path-dir-desc",
    "current-artifact-dirname": "current-path-dir",
    "current-artifact-dirname-asc": "current-path-dir-asc",
    "current-artifact-dirname-desc": "current-path-dir-desc",
    "current-artifact-folder": "current-path-dir",
    "current-artifact-folder-asc": "current-path-dir-asc",
    "current-artifact-folder-desc": "current-path-dir-desc",
    "current-artifact-folder-name": "current-path-dir",
    "current-artifact-folder-name-asc": "current-path-dir-asc",
    "current-artifact-folder-name-desc": "current-path-dir-desc",
    "current-path-directory": "current-path-dir",
    "current-path-directory-asc": "current-path-dir-asc",
    "current-path-directory-desc": "current-path-dir-desc",
    "current-path-dirname": "current-path-dir",
    "current-path-dirname-asc": "current-path-dir-asc",
    "current-path-dirname-desc": "current-path-dir-desc",
    "current-path-folder": "current-path-dir",
    "current-path-folder-asc": "current-path-dir-asc",
    "current-path-folder-desc": "current-path-dir-desc",
    "current-path-folder-name": "current-path-dir",
    "current-path-folder-name-asc": "current-path-dir-asc",
    "current-path-folder-name-desc": "current-path-dir-desc",
    "current-directory": "current-path-dir",
    "current-directory-asc": "current-path-dir-asc",
    "current-directory-desc": "current-path-dir-desc",
    "current-dir": "current-path-dir",
    "current-dir-asc": "current-path-dir-asc",
    "current-dir-desc": "current-path-dir-desc",
    "current-dirname": "current-path-dir",
    "current-dirname-asc": "current-path-dir-asc",
    "current-dirname-desc": "current-path-dir-desc",
    "current-folder": "current-path-dir",
    "current-folder-asc": "current-path-dir-asc",
    "current-folder-desc": "current-path-dir-desc",
    "current-folder-name": "current-path-dir",
    "current-folder-name-asc": "current-path-dir-asc",
    "current-folder-name-desc": "current-path-dir-desc",
    "current-extension": "current-path-extension",
    "current-extension-asc": "current-path-extension-asc",
    "current-extension-desc": "current-path-extension-desc",
    "current-ext": "current-path-extension",
    "current-ext-asc": "current-path-extension-asc",
    "current-ext-desc": "current-path-extension-desc",
    "current-artifact-ext": "current-path-extension",
    "current-artifact-ext-asc": "current-path-extension-asc",
    "current-artifact-ext-desc": "current-path-extension-desc",
    "current-artifact-file-ext": "current-path-extension",
    "current-artifact-file-ext-asc": "current-path-extension-asc",
    "current-artifact-file-ext-desc": "current-path-extension-desc",
    "current-artifact-file-extension": "current-path-extension",
    "current-artifact-file-extension-asc": "current-path-extension-asc",
    "current-artifact-file-extension-desc": "current-path-extension-desc",
    "current-file-ext": "current-path-extension",
    "current-file-ext-asc": "current-path-extension-asc",
    "current-file-ext-desc": "current-path-extension-desc",
    "current-file-extension": "current-path-extension",
    "current-file-extension-asc": "current-path-extension-asc",
    "current-file-extension-desc": "current-path-extension-desc",
    "current-path-ext": "current-path-extension",
    "current-path-ext-asc": "current-path-extension-asc",
    "current-path-ext-desc": "current-path-extension-desc",
    "current-path-file-ext": "current-path-extension",
    "current-path-file-ext-asc": "current-path-extension-asc",
    "current-path-file-ext-desc": "current-path-extension-desc",
    "current-path-file-extension": "current-path-extension",
    "current-path-file-extension-asc": "current-path-extension-asc",
    "current-path-file-extension-desc": "current-path-extension-desc",
    "detail-path": "detail-page",
    "detail-path-asc": "detail-page-asc",
    "detail-path-desc": "detail-page-desc",
    "detail-page-path": "detail-page",
    "detail-page-path-asc": "detail-page-asc",
    "detail-page-path-desc": "detail-page-desc",
    "detail-basename": "detail-page-name",
    "detail-basename-asc": "detail-page-name-asc",
    "detail-basename-desc": "detail-page-name-desc",
    "detail-page-basename": "detail-page-name",
    "detail-page-basename-asc": "detail-page-name-asc",
    "detail-page-basename-desc": "detail-page-name-desc",
    "detail-filename": "detail-page-name",
    "detail-filename-asc": "detail-page-name-asc",
    "detail-filename-desc": "detail-page-name-desc",
    "detail-page-filename": "detail-page-name",
    "detail-page-filename-asc": "detail-page-name-asc",
    "detail-page-filename-desc": "detail-page-name-desc",
    "detail-file-name": "detail-page-name",
    "detail-file-name-asc": "detail-page-name-asc",
    "detail-file-name-desc": "detail-page-name-desc",
    "detail-page-file-name": "detail-page-name",
    "detail-page-file-name-asc": "detail-page-name-asc",
    "detail-page-file-name-desc": "detail-page-name-desc",
    "detail-file-stem": "detail-page-stem",
    "detail-file-stem-asc": "detail-page-stem-asc",
    "detail-file-stem-desc": "detail-page-stem-desc",
    "detail-stem": "detail-page-stem",
    "detail-stem-asc": "detail-page-stem-asc",
    "detail-stem-desc": "detail-page-stem-desc",
    "detail-page-file-stem": "detail-page-stem",
    "detail-page-file-stem-asc": "detail-page-stem-asc",
    "detail-page-file-stem-desc": "detail-page-stem-desc",
    "detail-directory": "detail-page-dir",
    "detail-directory-asc": "detail-page-dir-asc",
    "detail-directory-desc": "detail-page-dir-desc",
    "detail-dir": "detail-page-dir",
    "detail-dir-asc": "detail-page-dir-asc",
    "detail-dir-desc": "detail-page-dir-desc",
    "detail-dirname": "detail-page-dir",
    "detail-dirname-asc": "detail-page-dir-asc",
    "detail-dirname-desc": "detail-page-dir-desc",
    "detail-folder": "detail-page-dir",
    "detail-folder-asc": "detail-page-dir-asc",
    "detail-folder-desc": "detail-page-dir-desc",
    "detail-folder-name": "detail-page-dir",
    "detail-folder-name-asc": "detail-page-dir-asc",
    "detail-folder-name-desc": "detail-page-dir-desc",
    "detail-page-directory": "detail-page-dir",
    "detail-page-directory-asc": "detail-page-dir-asc",
    "detail-page-directory-desc": "detail-page-dir-desc",
    "detail-page-dirname": "detail-page-dir",
    "detail-page-dirname-asc": "detail-page-dir-asc",
    "detail-page-dirname-desc": "detail-page-dir-desc",
    "detail-page-folder": "detail-page-dir",
    "detail-page-folder-asc": "detail-page-dir-asc",
    "detail-page-folder-desc": "detail-page-dir-desc",
    "detail-page-folder-name": "detail-page-dir",
    "detail-page-folder-name-asc": "detail-page-dir-asc",
    "detail-page-folder-name-desc": "detail-page-dir-desc",
    "detail-extension": "detail-page-extension",
    "detail-extension-asc": "detail-page-extension-asc",
    "detail-extension-desc": "detail-page-extension-desc",
    "detail-ext": "detail-page-extension",
    "detail-ext-asc": "detail-page-extension-asc",
    "detail-ext-desc": "detail-page-extension-desc",
    "detail-file-ext": "detail-page-extension",
    "detail-file-ext-asc": "detail-page-extension-asc",
    "detail-file-ext-desc": "detail-page-extension-desc",
    "detail-file-extension": "detail-page-extension",
    "detail-file-extension-asc": "detail-page-extension-asc",
    "detail-file-extension-desc": "detail-page-extension-desc",
    "detail-page-ext": "detail-page-extension",
    "detail-page-ext-asc": "detail-page-extension-asc",
    "detail-page-ext-desc": "detail-page-extension-desc",
    "detail-page-file-ext": "detail-page-extension",
    "detail-page-file-ext-asc": "detail-page-extension-asc",
    "detail-page-file-ext-desc": "detail-page-extension-desc",
    "detail-page-file-extension": "detail-page-extension",
    "detail-page-file-extension-asc": "detail-page-extension-asc",
    "detail-page-file-extension-desc": "detail-page-extension-desc",
}

AGE_BUCKET_ORDER = {
    "0-6d": 0,
    "7-29d": 1,
    "30-89d": 2,
    "90d+": 3,
    "unknown": 4,
}

MISSING_CURRENT_PATH_FILTER_VALUES = {"none", "missing", "untracked"}

BYTE_SIZE_UNITS = {
    "": 1,
    "b": 1,
    "byte": 1,
    "bytes": 1,
    "kb": 1000,
    "kilobyte": 1000,
    "kilobytes": 1000,
    "kib": 1024,
    "kibibyte": 1024,
    "kibibytes": 1024,
    "mb": 1000**2,
    "megabyte": 1000**2,
    "megabytes": 1000**2,
    "mib": 1024**2,
    "mebibyte": 1024**2,
    "mebibytes": 1024**2,
    "gb": 1000**3,
    "gigabyte": 1000**3,
    "gigabytes": 1000**3,
    "gib": 1024**3,
    "gibibyte": 1024**3,
    "gibibytes": 1024**3,
    "tb": 1000**4,
    "terabyte": 1000**4,
    "terabytes": 1000**4,
    "tib": 1024**4,
    "tebibyte": 1024**4,
    "tebibytes": 1024**4,
}

SUMMARY_SORTS = (
    "size",
    "size-desc",
    "size-asc",
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
    "avg-bytes",
    "avg-bytes-desc",
    "avg-bytes-asc",
    "mean-size",
    "mean-size-desc",
    "mean-size-asc",
    "mean",
    "mean-desc",
    "mean-asc",
    "mean-bytes",
    "mean-bytes-desc",
    "mean-bytes-asc",
    "per-file-size",
    "per-file-size-desc",
    "per-file-size-asc",
    "size-per-file",
    "size-per-file-desc",
    "size-per-file-asc",
    "bytes-per-file",
    "bytes-per-file-desc",
    "bytes-per-file-asc",
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
    "count",
    "count-desc",
    "count-asc",
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
    "least",
    "least-first",
    "least-artifacts",
    "least-artifacts-first",
    "least-files",
    "least-files-first",
    "bucket",
    "bucket-asc",
    "bucket-desc",
    "bucket-name",
    "bucket-name-asc",
    "bucket-name-desc",
    "name",
    "name-asc",
    "name-desc",
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
    "quarter",
    "quarter-desc",
    "quarter-asc",
    "calendar-quarter",
    "calendar-quarter-desc",
    "calendar-quarter-asc",
    "measurement-quarter",
    "measurement-quarter-desc",
    "measurement-quarter-asc",
    "measured-at-quarter",
    "measured-at-quarter-desc",
    "measured-at-quarter-asc",
    "measured-quarter",
    "measured-quarter-desc",
    "measured-quarter-asc",
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
    "measured-date",
    "measured-date-desc",
    "measured-date-asc",
    "measured-at-date",
    "measured-at-date-desc",
    "measured-at-date-asc",
    "measured-at-day",
    "measured-at-day-desc",
    "measured-at-day-asc",
    "measured-day",
    "measured-day-desc",
    "measured-day-asc",
    "week",
    "week-desc",
    "week-asc",
    "calendar-week",
    "calendar-week-desc",
    "calendar-week-asc",
    "iso-week",
    "iso-week-desc",
    "iso-week-asc",
    "measured-at-iso-week",
    "measured-at-iso-week-desc",
    "measured-at-iso-week-asc",
    "measurement-iso-week",
    "measurement-iso-week-desc",
    "measurement-iso-week-asc",
    "measurement-week",
    "measurement-week-desc",
    "measurement-week-asc",
    "measured-at-week",
    "measured-at-week-desc",
    "measured-at-week-asc",
    "measured-week",
    "measured-week-desc",
    "measured-week-asc",
)

SUMMARY_SORT_ALIASES = {
    "biggest": "size",
    "biggest-first": "size",
    "heaviest": "size",
    "heaviest-first": "size",
    "largest-first": "size",
    "largest-bytes": "size",
    "largest-bytes-first": "size",
    "top": "size",
    "top-first": "size",
    "top-size": "size",
    "top-size-first": "size",
    "top-bytes": "size",
    "top-bytes-first": "size",
    "max-size": "size",
    "max-size-first": "size",
    "max-bytes": "size",
    "max-bytes-first": "size",
    "artifact-size": "size",
    "artifact-size-desc": "size",
    "artifact-size-asc": "size-asc",
    "file-size": "size",
    "file-size-desc": "size",
    "file-size-asc": "size-asc",
    "artifact-bytes": "size",
    "artifact-bytes-desc": "size",
    "artifact-bytes-asc": "size-asc",
    "file-bytes": "size",
    "file-bytes-desc": "size",
    "file-bytes-asc": "size-asc",
    "per-file-size": "average-size",
    "per-file-size-desc": "average-size",
    "per-file-size-asc": "average-size-asc",
    "size-per-file": "average-size",
    "size-per-file-desc": "average-size",
    "size-per-file-asc": "average-size-asc",
    "bytes-per-file": "average-size",
    "bytes-per-file-desc": "average-size",
    "bytes-per-file-asc": "average-size-asc",
    "lightest": "size-asc",
    "lightest-first": "size-asc",
    "smallest-first": "size-asc",
    "smallest-bytes": "size-asc",
    "smallest-bytes-first": "size-asc",
    "bottom": "size-asc",
    "bottom-first": "size-asc",
    "bottom-size": "size-asc",
    "bottom-size-first": "size-asc",
    "bottom-bytes": "size-asc",
    "bottom-bytes-first": "size-asc",
    "min-size": "size-asc",
    "min-size-first": "size-asc",
    "min-bytes": "size-asc",
    "min-bytes-first": "size-asc",
    "most": "count",
    "most-first": "count",
    "most-artifacts": "count",
    "most-artifacts-first": "count",
    "most-files": "count",
    "most-files-first": "count",
    "fewest": "count-asc",
    "fewest-first": "count-asc",
    "fewest-artifacts": "count-asc",
    "fewest-artifacts-first": "count-asc",
    "fewest-files": "count-asc",
    "fewest-files-first": "count-asc",
    "total-count": "count",
    "total-count-desc": "count",
    "total-count-asc": "count-asc",
    "artifact-count": "count",
    "artifact-count-desc": "count",
    "artifact-count-asc": "count-asc",
    "file-count": "count",
    "file-count-desc": "count",
    "file-count-asc": "count-asc",
    "files": "count",
    "files-desc": "count",
    "files-asc": "count-asc",
    "items": "count",
    "items-desc": "count",
    "items-asc": "count-asc",
    "least": "count-asc",
    "least-first": "count-asc",
    "least-artifacts": "count-asc",
    "least-artifacts-first": "count-asc",
    "least-files": "count-asc",
    "least-files-first": "count-asc",
    "bucket": "name",
    "bucket-asc": "name-asc",
    "bucket-desc": "name-desc",
    "bucket-name": "name",
    "bucket-name-asc": "name-asc",
    "bucket-name-desc": "name-desc",
    "alphabetical": "name",
    "alphabetical-first": "name",
    "alphabetical-asc": "name-asc",
    "alphabetical-desc": "name-desc",
    "alpha": "name",
    "alpha-first": "name",
    "alpha-asc": "name-asc",
    "alpha-desc": "name-desc",
    "reverse-alphabetical": "name-desc",
    "reverse-alphabetical-first": "name-desc",
    "reverse-alpha": "name-desc",
    "reverse-alpha-first": "name-desc",
    "reverse-name": "name-desc",
    "reverse-name-first": "name-desc",
    "name-reverse": "name-desc",
    "name-reverse-first": "name-desc",
    "a-z": "name-asc",
    "z-a": "name-desc",
    "age-range": "age-bucket-desc",
    "age-range-desc": "age-bucket-desc",
    "age-range-asc": "age-bucket-asc",
    "stale-age-bucket": "age-bucket-desc",
    "stale-age-bucket-desc": "age-bucket-desc",
    "stale-age-bucket-asc": "age-bucket-asc",
    "staleness-bucket": "age-bucket-desc",
    "staleness-bucket-desc": "age-bucket-desc",
    "staleness-bucket-asc": "age-bucket-asc",
    "age": "age-bucket-desc",
    "age-desc": "age-bucket-desc",
    "age-asc": "age-bucket-asc",
    "older": "age-bucket-desc",
    "older-first": "age-bucket-desc",
    "newer": "age-bucket-asc",
    "newer-first": "age-bucket-asc",
    "stale": "age-bucket-desc",
    "stale-first": "age-bucket-desc",
    "stalest": "age-bucket-desc",
    "stalest-first": "age-bucket-desc",
    "freshest": "age-bucket-asc",
    "freshest-first": "age-bucket-asc",
    "year": "measured-year",
    "year-asc": "measured-year-asc",
    "year-desc": "measured-year-desc",
    "calendar-year": "measured-year",
    "calendar-year-asc": "measured-year-asc",
    "calendar-year-desc": "measured-year-desc",
    "measurement-year": "measured-year",
    "measurement-year-asc": "measured-year-asc",
    "measurement-year-desc": "measured-year-desc",
    "measured-at-year": "measured-year",
    "measured-at-year-asc": "measured-year-asc",
    "measured-at-year-desc": "measured-year-desc",
    "quarter": "measured-quarter",
    "quarter-asc": "measured-quarter-asc",
    "quarter-desc": "measured-quarter-desc",
    "calendar-quarter": "measured-quarter",
    "calendar-quarter-asc": "measured-quarter-asc",
    "calendar-quarter-desc": "measured-quarter-desc",
    "measurement-quarter": "measured-quarter",
    "measurement-quarter-asc": "measured-quarter-asc",
    "measurement-quarter-desc": "measured-quarter-desc",
    "measured-at-quarter": "measured-quarter",
    "measured-at-quarter-asc": "measured-quarter-asc",
    "measured-at-quarter-desc": "measured-quarter-desc",
    "month": "measured-month",
    "month-asc": "measured-month-asc",
    "month-desc": "measured-month-desc",
    "calendar-month": "measured-month",
    "calendar-month-asc": "measured-month-asc",
    "calendar-month-desc": "measured-month-desc",
    "measurement-month": "measured-month",
    "measurement-month-asc": "measured-month-asc",
    "measurement-month-desc": "measured-month-desc",
    "measured-at-month": "measured-month",
    "measured-at-month-asc": "measured-month-asc",
    "measured-at-month-desc": "measured-month-desc",
    "date": "measured-day",
    "date-asc": "measured-day-asc",
    "date-desc": "measured-day-desc",
    "calendar-date": "measured-day",
    "calendar-date-asc": "measured-day-asc",
    "calendar-date-desc": "measured-day-desc",
    "day": "measured-day",
    "day-asc": "measured-day-asc",
    "day-desc": "measured-day-desc",
    "calendar-day": "measured-day",
    "calendar-day-asc": "measured-day-asc",
    "calendar-day-desc": "measured-day-desc",
    "measurement-date": "measured-day",
    "measurement-date-asc": "measured-day-asc",
    "measurement-date-desc": "measured-day-desc",
    "measurement-day": "measured-day",
    "measurement-day-asc": "measured-day-asc",
    "measurement-day-desc": "measured-day-desc",
    "measured-date": "measured-day",
    "measured-date-asc": "measured-day-asc",
    "measured-date-desc": "measured-day-desc",
    "measured-at-date": "measured-day",
    "measured-at-date-asc": "measured-day-asc",
    "measured-at-date-desc": "measured-day-desc",
    "measured-at-day": "measured-day",
    "measured-at-day-asc": "measured-day-asc",
    "measured-at-day-desc": "measured-day-desc",
    "week": "measured-week",
    "week-asc": "measured-week-asc",
    "week-desc": "measured-week-desc",
    "calendar-week": "measured-week",
    "calendar-week-asc": "measured-week-asc",
    "calendar-week-desc": "measured-week-desc",
    "iso-week": "measured-week",
    "iso-week-asc": "measured-week-asc",
    "iso-week-desc": "measured-week-desc",
    "measured-at-iso-week": "measured-week",
    "measured-at-iso-week-asc": "measured-week-asc",
    "measured-at-iso-week-desc": "measured-week-desc",
    "measurement-iso-week": "measured-week",
    "measurement-iso-week-asc": "measured-week-asc",
    "measurement-iso-week-desc": "measured-week-desc",
    "measurement-week": "measured-week",
    "measurement-week-asc": "measured-week-asc",
    "measurement-week-desc": "measured-week-desc",
    "measured-at-week": "measured-week",
    "measured-at-week-asc": "measured-week-asc",
    "measured-at-week-desc": "measured-week-desc",
}


def format_bytes(size_bytes: int | None) -> str:
    if not size_bytes:
        return "0 B"

    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(size_bytes)
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def format_average_bytes(size_bytes: float) -> str:
    if size_bytes.is_integer():
        return format_bytes(int(size_bytes))
    if size_bytes < 1024:
        return f"{size_bytes:.1f} B"
    return format_bytes(size_bytes)


def parse_size_bytes(value: str) -> int:
    match = re.fullmatch(r"\s*(-?(?:\d+(?:[,_]\d{3})+|\d+)(?:\.\d+)?)\s*([a-zA-Z]*)\s*", value)
    if match is None:
        raise argparse.ArgumentTypeError("size must be bytes or a value with KB, KiB, MB, MiB, GB, GiB, TB, or TiB")

    amount_text, unit_text = match.groups()
    amount = float(amount_text.replace(",", "").replace("_", ""))
    if amount < 0:
        raise argparse.ArgumentTypeError("size must not be negative")

    unit = unit_text.lower()
    multiplier = BYTE_SIZE_UNITS.get(unit)
    if multiplier is None:
        raise argparse.ArgumentTypeError("size unit must be one of: B, KB, KiB, MB, MiB, GB, GiB, TB, TiB")

    return int(amount * multiplier)


def parse_age_days(value: str) -> int:
    match = re.fullmatch(
        r"\s*(-?(?:\d+(?:[,_]\d{3})+|\d+)(?:\.\d+)?)\s*(d|day|days|w|wk|wks|week|weeks|fortnight|fortnights|biweek|biweeks|biweekly|q|qtr|qtrs|quarter|quarters|mo|mon|month|months|y|yr|yrs|year|years)?\s*",
        value,
        flags=re.IGNORECASE,
    )
    if match is None:
        raise argparse.ArgumentTypeError(
            "age must be a number, optionally followed by days, weeks, quarters, months, or years"
        )

    amount_text, unit_text = match.groups()
    days = float(amount_text.replace(",", "").replace("_", ""))
    if unit_text:
        unit = unit_text.lower()
        if unit in {"w", "wk", "wks", "week", "weeks"}:
            days *= 7
        elif unit in {"fortnight", "fortnights", "biweek", "biweeks", "biweekly"}:
            days *= 14
        elif unit in {"q", "qtr", "qtrs", "quarter", "quarters"}:
            days *= 90
        elif unit in {"mo", "mon", "month", "months"}:
            days *= 30
        elif unit in {"y", "yr", "yrs", "year", "years"}:
            days *= 365
    if days < 0:
        raise argparse.ArgumentTypeError("days must be non-negative")
    if days > 365000:
        raise argparse.ArgumentTypeError("days must be no more than 365000")
    return math.ceil(days)


def format_age_days(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    noun = "day" if age_days == 1 else "days"
    return f"{age_days} {noun}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report stale benchmark artifacts")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=DEFAULT_RESULTS_DIR,
        help="Directory containing benchmark JSON artifacts",
    )
    parser.add_argument(
        "--tracks",
        type=Path,
        default=DEFAULT_TRACKS_PATH,
        help="JSON file listing tracked benchmark lanes",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help=(
            "Read an existing benchmark manifest JSON instead of rebuilding one from "
            "--results-dir and --tracks; use '-' to read from stdin"
        ),
    )
    parser.add_argument(
        "--older-than-days",
        "--older-than",
        "--min-age",
        "--at-least-age",
        type=parse_age_days,
        default=None,
        help="Only include stale artifacts measured before this minimum age, in days, weeks, months, or years",
    )
    parser.add_argument(
        "--newer-than-days",
        "--newer-than",
        "--max-age",
        "--at-most-age",
        type=parse_age_days,
        default=None,
        help="Only include stale artifacts measured within this maximum age, in days, weeks, months, or years",
    )
    parser.add_argument(
        "--measured-before",
        "--measured-until",
        "--measured-to",
        "--measured-before-date",
        default=None,
        help="Only include stale artifacts measured before this ISO timestamp or date",
    )
    parser.add_argument(
        "--measured-after",
        "--measured-since",
        "--measured-from",
        "--measured-after-date",
        default=None,
        help="Only include stale artifacts measured after this ISO timestamp or date",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only print the first N stale artifacts after filtering and sorting",
    )
    parser.add_argument(
        "--sort",
        type=normalize_cli_token,
        choices=(
            "size",
            "size-desc",
            "size-asc",
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
            "age",
            "age-desc",
            "age-asc",
            "stale",
            "stale-first",
            "stalest",
            "stalest-first",
            "freshest",
            "freshest-first",
            "measured-at",
            "measured-at-asc",
            "measured-at-desc",
            "oldest",
            "oldest-first",
            "earliest",
            "earliest-first",
            "least-recent",
            "least-recent-first",
            "measurement-time",
            "measurement-time-asc",
            "measurement-time-desc",
            "measured-time",
            "measured-time-asc",
            "measured-time-desc",
            "timestamp",
            "timestamp-asc",
            "timestamp-desc",
            "time",
            "time-asc",
            "time-desc",
            "newest",
            "newest-first",
            "latest",
            "latest-first",
            "recent",
            "recent-first",
            "most-recent",
            "most-recent-first",
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
            "path",
            "path-asc",
            "path-desc",
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
            "path-stem",
            "path-stem-asc",
            "path-stem-desc",
            "path-file-stem",
            "path-file-stem-asc",
            "path-file-stem-desc",
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
            "artifact-path",
            "artifact-path-asc",
            "artifact-path-desc",
            "artifact-name",
            "artifact-name-asc",
            "artifact-name-desc",
            "artifact-basename",
            "artifact-basename-asc",
            "artifact-basename-desc",
            "artifact-filename",
            "artifact-filename-asc",
            "artifact-filename-desc",
            "artifact-file-name",
            "artifact-file-name-asc",
            "artifact-file-name-desc",
            "artifact-dir",
            "artifact-dir-asc",
            "artifact-dir-desc",
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
            "artifact-ext",
            "artifact-ext-asc",
            "artifact-ext-desc",
            "artifact-file-ext",
            "artifact-file-ext-asc",
            "artifact-file-ext-desc",
            "artifact-file-extension",
            "artifact-file-extension-asc",
            "artifact-file-extension-desc",
            "artifact-extension",
            "artifact-extension-asc",
            "artifact-extension-desc",
            "detail-page",
            "detail-page-asc",
            "detail-page-desc",
            "detail-path",
            "detail-path-asc",
            "detail-path-desc",
            "detail-page-path",
            "detail-page-path-asc",
            "detail-page-path-desc",
            "detail-page-name",
            "detail-page-name-asc",
            "detail-page-name-desc",
            "detail-basename",
            "detail-basename-asc",
            "detail-basename-desc",
            "detail-page-basename",
            "detail-page-basename-asc",
            "detail-page-basename-desc",
            "detail-filename",
            "detail-filename-asc",
            "detail-filename-desc",
            "detail-page-filename",
            "detail-page-filename-asc",
            "detail-page-filename-desc",
            "detail-file-name",
            "detail-file-name-asc",
            "detail-file-name-desc",
            "detail-page-file-name",
            "detail-page-file-name-asc",
            "detail-page-file-name-desc",
            "detail-page-stem",
            "detail-page-stem-asc",
            "detail-page-stem-desc",
            "detail-file-stem",
            "detail-file-stem-asc",
            "detail-file-stem-desc",
            "detail-stem",
            "detail-stem-asc",
            "detail-stem-desc",
            "detail-page-file-stem",
            "detail-page-file-stem-asc",
            "detail-page-file-stem-desc",
            "detail-page-dir",
            "detail-page-dir-asc",
            "detail-page-dir-desc",
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
            "detail-extension",
            "detail-extension-asc",
            "detail-extension-desc",
            "detail-ext",
            "detail-ext-asc",
            "detail-ext-desc",
            "detail-file-ext",
            "detail-file-ext-asc",
            "detail-file-ext-desc",
            "detail-file-extension",
            "detail-file-extension-asc",
            "detail-file-extension-desc",
            "detail-page-ext",
            "detail-page-ext-asc",
            "detail-page-ext-desc",
            "detail-page-file-ext",
            "detail-page-file-ext-asc",
            "detail-page-file-ext-desc",
            "detail-page-file-extension",
            "detail-page-file-extension-asc",
            "detail-page-file-extension-desc",
            "detail-page-extension",
            "detail-page-extension-asc",
            "detail-page-extension-desc",
            "artifact-stem",
            "artifact-stem-asc",
            "artifact-stem-desc",
            "artifact-file-stem",
            "artifact-file-stem-asc",
            "artifact-file-stem-desc",
            "artifact-path-name",
            "artifact-path-name-asc",
            "artifact-path-name-desc",
            "artifact-path-basename",
            "artifact-path-basename-asc",
            "artifact-path-basename-desc",
            "artifact-path-filename",
            "artifact-path-filename-asc",
            "artifact-path-filename-desc",
            "artifact-path-file-name",
            "artifact-path-file-name-asc",
            "artifact-path-file-name-desc",
            "artifact-path-stem",
            "artifact-path-stem-asc",
            "artifact-path-stem-desc",
            "artifact-path-file-stem",
            "artifact-path-file-stem-asc",
            "artifact-path-file-stem-desc",
            "artifact-path-dir",
            "artifact-path-dir-asc",
            "artifact-path-dir-desc",
            "artifact-path-directory",
            "artifact-path-directory-asc",
            "artifact-path-directory-desc",
            "artifact-path-dirname",
            "artifact-path-dirname-asc",
            "artifact-path-dirname-desc",
            "artifact-path-folder",
            "artifact-path-folder-asc",
            "artifact-path-folder-desc",
            "artifact-path-folder-name",
            "artifact-path-folder-name-asc",
            "artifact-path-folder-name-desc",
            "artifact-path-extension",
            "artifact-path-extension-asc",
            "artifact-path-extension-desc",
            "artifact-path-ext",
            "artifact-path-ext-asc",
            "artifact-path-ext-desc",
            "artifact-path-file-ext",
            "artifact-path-file-ext-asc",
            "artifact-path-file-ext-desc",
            "artifact-path-file-extension",
            "artifact-path-file-extension-asc",
            "artifact-path-file-extension-desc",
            "status",
            "status-asc",
            "status-desc",
            "backend",
            "backend-asc",
            "backend-desc",
            "model",
            "model-asc",
            "model-desc",
            "label",
            "label-asc",
            "label-desc",
            "slug",
            "slug-asc",
            "slug-desc",
            "track-state",
            "track-state-asc",
            "track-state-desc",
            "track-status",
            "track-status-asc",
            "track-status-desc",
            "current-path",
            "current-path-asc",
            "current-path-desc",
            "current-artifact",
            "current-artifact-asc",
            "current-artifact-desc",
            "current-artifact-path",
            "current-artifact-path-asc",
            "current-artifact-path-desc",
            "current-path-name",
            "current-path-name-asc",
            "current-path-name-desc",
            "current-basename",
            "current-basename-asc",
            "current-basename-desc",
            "current-filename",
            "current-filename-asc",
            "current-filename-desc",
            "current-file-name",
            "current-file-name-asc",
            "current-file-name-desc",
            "current-artifact-name",
            "current-artifact-name-asc",
            "current-artifact-name-desc",
            "current-artifact-file-name",
            "current-artifact-file-name-asc",
            "current-artifact-file-name-desc",
            "current-path-stem",
            "current-path-stem-asc",
            "current-path-stem-desc",
            "current-artifact-stem",
            "current-artifact-stem-asc",
            "current-artifact-stem-desc",
            "current-artifact-file-stem",
            "current-artifact-file-stem-asc",
            "current-artifact-file-stem-desc",
            "current-file-stem",
            "current-file-stem-asc",
            "current-file-stem-desc",
            "current-path-dir",
            "current-path-dir-asc",
            "current-path-dir-desc",
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
            "current-directory",
            "current-directory-asc",
            "current-directory-desc",
            "current-dir",
            "current-dir-asc",
            "current-dir-desc",
            "current-dirname",
            "current-dirname-asc",
            "current-dirname-desc",
            "current-folder",
            "current-folder-asc",
            "current-folder-desc",
            "current-folder-name",
            "current-folder-name-asc",
            "current-folder-name-desc",
            "current-artifact-dir",
            "current-artifact-dir-asc",
            "current-artifact-dir-desc",
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
            "current-extension",
            "current-extension-asc",
            "current-extension-desc",
            "current-ext",
            "current-ext-asc",
            "current-ext-desc",
            "current-path-ext",
            "current-path-ext-asc",
            "current-path-ext-desc",
            "current-path-file-ext",
            "current-path-file-ext-asc",
            "current-path-file-ext-desc",
            "current-path-file-extension",
            "current-path-file-extension-asc",
            "current-path-file-extension-desc",
            "current-artifact-ext",
            "current-artifact-ext-asc",
            "current-artifact-ext-desc",
            "current-artifact-file-ext",
            "current-artifact-file-ext-asc",
            "current-artifact-file-ext-desc",
            "current-artifact-file-extension",
            "current-artifact-file-extension-asc",
            "current-artifact-file-extension-desc",
            "current-file-ext",
            "current-file-ext-asc",
            "current-file-ext-desc",
            "current-file-extension",
            "current-file-extension-asc",
            "current-file-extension-desc",
            "current-path-extension",
            "current-path-extension-asc",
            "current-path-extension-desc",
            "current-artifact-extension",
            "current-artifact-extension-asc",
            "current-artifact-extension-desc",
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
            "measured-year",
            "measured-year-asc",
            "measured-year-desc",
            "quarter",
            "quarter-asc",
            "quarter-desc",
            "calendar-quarter",
            "calendar-quarter-asc",
            "calendar-quarter-desc",
            "measurement-quarter",
            "measurement-quarter-asc",
            "measurement-quarter-desc",
            "measured-at-quarter",
            "measured-at-quarter-asc",
            "measured-at-quarter-desc",
            "measured-quarter",
            "measured-quarter-asc",
            "measured-quarter-desc",
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
            "measured-month",
            "measured-month-asc",
            "measured-month-desc",
            "week",
            "week-asc",
            "week-desc",
            "calendar-week",
            "calendar-week-asc",
            "calendar-week-desc",
            "iso-week",
            "iso-week-asc",
            "iso-week-desc",
            "measured-at-iso-week",
            "measured-at-iso-week-asc",
            "measured-at-iso-week-desc",
            "measurement-iso-week",
            "measurement-iso-week-asc",
            "measurement-iso-week-desc",
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
            "measured-date",
            "measured-date-asc",
            "measured-date-desc",
            "measured-at-date",
            "measured-at-date-asc",
            "measured-at-date-desc",
            "measured-at-day",
            "measured-at-day-asc",
            "measured-at-day-desc",
            "measured-day",
            "measured-day-asc",
            "measured-day-desc",
            "age-bucket",
            "age-bucket-asc",
            "age-bucket-desc",
            "age-range",
            "age-range-asc",
            "age-range-desc",
            "age-range-bucket",
            "age-range-bucket-asc",
            "age-range-bucket-desc",
            "stale-age-bucket",
            "stale-age-bucket-asc",
            "stale-age-bucket-desc",
            "staleness-bucket",
            "staleness-bucket-asc",
            "staleness-bucket-desc",
        ),
        default="size",
        help="Sort stale artifacts before applying --limit",
    )
    parser.add_argument(
        "--min-size-bytes",
        type=parse_size_bytes,
        default=None,
        help="Only include stale artifacts at least this large; accepts bytes or KB, KiB, MB, MiB, GB, GiB, TB, TiB",
    )
    parser.add_argument(
        "--max-size-bytes",
        type=parse_size_bytes,
        default=None,
        help="Only include stale artifacts no larger than this; accepts bytes or KB, KiB, MB, MiB, GB, GiB, TB, TiB",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=None,
        help="Only include stale artifacts for this benchmark track slug; repeat to include multiple slugs",
    )
    parser.add_argument(
        "--slug-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose track slug contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=None,
        help="Only include stale artifacts whose label contains this text; repeat to include multiple labels",
    )
    parser.add_argument(
        "--backend",
        action="append",
        default=None,
        help="Only include stale artifacts for this backend; repeat to include multiple backends",
    )
    parser.add_argument(
        "--model",
        action="append",
        default=None,
        help="Only include stale artifacts whose model contains this text; repeat to include multiple models",
    )
    parser.add_argument(
        "--measured-month",
        "--measured-months",
        "--month",
        "--months",
        "--calendar-month",
        "--calendar-months",
        "--measurement-month",
        "--measurement-months",
        "--measured-at-month",
        "--measured-at-months",
        action="append",
        default=None,
        help="Only include stale artifacts measured in this UTC YYYY-MM month; repeat to include multiple months",
    )
    parser.add_argument(
        "--measured-week",
        "--measured-weeks",
        "--week",
        "--weeks",
        "--calendar-week",
        "--calendar-weeks",
        "--iso-week",
        "--iso-weeks",
        "--measurement-week",
        "--measurement-weeks",
        "--measured-at-week",
        "--measured-at-weeks",
        action="append",
        default=None,
        help="Only include stale artifacts measured in this UTC YYYY-Www ISO week; repeat to include multiple weeks",
    )
    parser.add_argument(
        "--measured-day",
        "--measured-days",
        "--day",
        "--days",
        "--date",
        "--dates",
        "--measurement-day",
        "--measurement-days",
        "--measurement-date",
        "--measurement-dates",
        "--measured-date",
        "--measured-dates",
        "--calendar-day",
        "--calendar-days",
        "--calendar-date",
        "--calendar-dates",
        "--measured-at-day",
        "--measured-at-days",
        "--measured-at-date",
        "--measured-at-dates",
        action="append",
        default=None,
        help="Only include stale artifacts measured on this UTC YYYY-MM-DD day; repeat to include multiple days",
    )
    parser.add_argument(
        "--measured-year",
        "--measured-years",
        "--year",
        "--years",
        "--calendar-year",
        "--calendar-years",
        "--measurement-year",
        "--measurement-years",
        "--measured-at-year",
        "--measured-at-years",
        action="append",
        default=None,
        help="Only include stale artifacts measured in this UTC YYYY year; repeat to include multiple years",
    )
    parser.add_argument(
        "--measured-quarter",
        "--measured-quarters",
        "--quarter",
        "--quarters",
        "--calendar-quarter",
        "--calendar-quarters",
        "--measurement-quarter",
        "--measurement-quarters",
        "--measured-at-quarter",
        "--measured-at-quarters",
        action="append",
        default=None,
        help="Only include stale artifacts measured in this UTC YYYY-Qn quarter; repeat to include multiple quarters",
    )
    parser.add_argument(
        "--age-bucket",
        "--age-range",
        "--age-range-bucket",
        "--stale-age-bucket",
        "--staleness-bucket",
        action="append",
        default=None,
        help="Only include stale artifacts in this age bucket; repeat or comma-separate values like 0-6d, 7-29d, 30-89d, 90d+, or unknown",
    )
    parser.add_argument(
        "--current-path",
        "--current-artifact",
        "--current-artifact-path",
        action="append",
        default=None,
        help=(
            "Only include stale artifacts whose track currently points at this artifact path; "
            "repeat to include multiple paths; use 'none', 'missing', or 'untracked' for untracked artifacts"
        ),
    )
    parser.add_argument(
        "--current-path-contains",
        "--current-artifact-contains",
        "--current-artifact-path-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-name",
        "--current-artifact-name",
        "--current-artifact-file-name",
        "--current-basename",
        "--current-filename",
        "--current-file-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file name matches this name; repeat to include multiple names",
    )
    parser.add_argument(
        "--current-path-name-contains",
        "--current-artifact-name-contains",
        "--current-artifact-file-name-contains",
        "--current-basename-contains",
        "--current-filename-contains",
        "--current-file-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-stem",
        "--current-artifact-stem",
        "--current-artifact-file-stem",
        "--current-file-stem",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file stem matches this value; repeat to include multiple stems",
    )
    parser.add_argument(
        "--current-path-stem-contains",
        "--current-artifact-stem-contains",
        "--current-artifact-file-stem-contains",
        "--current-file-stem-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact file stem contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-dir",
        "--current-artifact-dir",
        "--current-path-directory",
        "--current-artifact-directory",
        "--current-directory",
        "--current-dir",
        "--current-path-dirname",
        "--current-artifact-dirname",
        "--current-dirname",
        "--current-path-folder",
        "--current-artifact-folder",
        "--current-folder",
        "--current-path-folder-name",
        "--current-artifact-folder-name",
        "--current-folder-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact directory matches this path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--current-path-dir-contains",
        "--current-artifact-dir-contains",
        "--current-path-directory-contains",
        "--current-artifact-directory-contains",
        "--current-directory-contains",
        "--current-dir-contains",
        "--current-path-dirname-contains",
        "--current-artifact-dirname-contains",
        "--current-dirname-contains",
        "--current-path-folder-contains",
        "--current-artifact-folder-contains",
        "--current-folder-contains",
        "--current-path-folder-name-contains",
        "--current-artifact-folder-name-contains",
        "--current-folder-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact directory contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--current-path-extension",
        "--current-artifact-extension",
        "--current-extension",
        "--current-ext",
        "--current-path-ext",
        "--current-path-file-ext",
        "--current-path-file-extension",
        "--current-artifact-ext",
        "--current-artifact-file-ext",
        "--current-artifact-file-extension",
        "--current-file-ext",
        "--current-file-extension",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact extension matches this value; repeat or comma-separate; use 'none' for extensionless or untracked paths",
    )
    parser.add_argument(
        "--current-path-extension-contains",
        "--current-artifact-extension-contains",
        "--current-extension-contains",
        "--current-ext-contains",
        "--current-path-ext-contains",
        "--current-path-file-ext-contains",
        "--current-path-file-extension-contains",
        "--current-artifact-ext-contains",
        "--current-artifact-file-ext-contains",
        "--current-artifact-file-extension-contains",
        "--current-file-ext-contains",
        "--current-file-extension-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose current track artifact extension contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--track-state",
        "--track-status",
        choices=("any", "tracked", "untracked"),
        default="any",
        help="Filter stale artifacts by whether their slug still maps to a current benchmark track",
    )
    parser.add_argument(
        "--artifact-path",
        "--path",
        action="append",
        default=None,
        help="Only include this stale artifact path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--artifact-path-contains",
        "--path-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose artifact path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--artifact-dir",
        "--artifact-directory",
        "--artifact-dirname",
        "--artifact-folder",
        "--artifact-folder-name",
        "--path-dir",
        "--path-directory",
        "--path-dirname",
        "--path-folder",
        "--path-folder-name",
        action="append",
        default=None,
        help=(
            "Only include stale artifacts whose artifact directory matches this path; "
            "repeat to include multiple paths"
        ),
    )
    parser.add_argument(
        "--artifact-dir-contains",
        "--artifact-directory-contains",
        "--artifact-dirname-contains",
        "--artifact-folder-contains",
        "--artifact-folder-name-contains",
        "--path-dir-contains",
        "--path-directory-contains",
        "--path-dirname-contains",
        "--path-folder-contains",
        "--path-folder-name-contains",
        action="append",
        default=None,
        help=(
            "Only include stale artifacts whose artifact directory contains this text; "
            "repeat to include multiple matches"
        ),
    )
    parser.add_argument(
        "--artifact-name",
        "--name",
        "--basename",
        "--filename",
        "--file-name",
        "--artifact-basename",
        "--artifact-filename",
        "--artifact-file-name",
        "--path-name",
        "--path-basename",
        "--path-filename",
        "--path-file-name",
        action="append",
        default=None,
        help="Only include stale artifacts with this file name; repeat to include multiple names",
    )
    parser.add_argument(
        "--artifact-name-contains",
        "--name-contains",
        "--basename-contains",
        "--filename-contains",
        "--file-name-contains",
        "--artifact-basename-contains",
        "--artifact-filename-contains",
        "--artifact-file-name-contains",
        "--path-name-contains",
        "--path-basename-contains",
        "--path-filename-contains",
        "--path-file-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--artifact-stem",
        "--stem",
        "--file-stem",
        "--artifact-file-stem",
        "--path-stem",
        "--path-file-stem",
        action="append",
        default=None,
        help="Only include stale artifacts with this file name without extension; repeat to include multiple stems",
    )
    parser.add_argument(
        "--artifact-stem-contains",
        "--stem-contains",
        "--file-stem-contains",
        "--artifact-file-stem-contains",
        "--path-stem-contains",
        "--path-file-stem-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file name without extension contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--artifact-extension",
        "--extension",
        "--ext",
        "--file-ext",
        "--file-extension",
        "--artifact-ext",
        "--artifact-file-ext",
        "--artifact-file-extension",
        "--path-extension",
        "--path-ext",
        "--path-file-ext",
        "--path-file-extension",
        action="append",
        default=None,
        help="Only include stale artifacts with this file extension; repeat or comma-separate; use 'none' for extensionless paths",
    )
    parser.add_argument(
        "--artifact-extension-contains",
        "--extension-contains",
        "--ext-contains",
        "--file-ext-contains",
        "--file-extension-contains",
        "--artifact-ext-contains",
        "--artifact-file-ext-contains",
        "--artifact-file-extension-contains",
        "--path-extension-contains",
        "--path-ext-contains",
        "--path-file-ext-contains",
        "--path-file-extension-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose file extension contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page",
        "--detail-path",
        "--detail-page-path",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page path matches this path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--detail-page-contains",
        "--detail-path-contains",
        "--detail-page-path-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page path contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page-name",
        "--detail-basename",
        "--detail-filename",
        "--detail-file-name",
        "--detail-page-file-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file name matches this name; repeat to include multiple names",
    )
    parser.add_argument(
        "--detail-page-name-contains",
        "--detail-basename-contains",
        "--detail-filename-contains",
        "--detail-file-name-contains",
        "--detail-page-file-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file name contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page-stem",
        "--detail-file-stem",
        "--detail-stem",
        "--detail-page-file-stem",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file stem matches this value; repeat to include multiple stems",
    )
    parser.add_argument(
        "--detail-page-stem-contains",
        "--detail-file-stem-contains",
        "--detail-stem-contains",
        "--detail-page-file-stem-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page file stem contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page-dir",
        "--detail-dir",
        "--detail-directory",
        "--detail-page-directory",
        "--detail-dirname",
        "--detail-page-dirname",
        "--detail-folder",
        "--detail-page-folder",
        "--detail-folder-name",
        "--detail-page-folder-name",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page directory matches this path; repeat to include multiple paths",
    )
    parser.add_argument(
        "--detail-page-dir-contains",
        "--detail-dir-contains",
        "--detail-directory-contains",
        "--detail-page-directory-contains",
        "--detail-dirname-contains",
        "--detail-page-dirname-contains",
        "--detail-folder-contains",
        "--detail-page-folder-contains",
        "--detail-folder-name-contains",
        "--detail-page-folder-name-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page directory contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--detail-page-extension",
        "--detail-extension",
        "--detail-ext",
        "--detail-file-ext",
        "--detail-file-extension",
        "--detail-page-ext",
        "--detail-page-file-ext",
        "--detail-page-file-extension",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page extension matches this value; repeat or comma-separate; use 'none' for artifacts without a detail page",
    )
    parser.add_argument(
        "--detail-page-extension-contains",
        "--detail-extension-contains",
        "--detail-ext-contains",
        "--detail-file-ext-contains",
        "--detail-file-extension-contains",
        "--detail-page-ext-contains",
        "--detail-page-file-ext-contains",
        "--detail-page-file-extension-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose generated detail page extension contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--status",
        "--artifact-status",
        action="append",
        default=None,
        help="Only include stale artifacts with this status; repeat to include multiple statuses; use 'any' for all statuses (default: legacy)",
    )
    parser.add_argument(
        "--status-contains",
        "--artifact-status-contains",
        action="append",
        default=None,
        help="Only include stale artifacts whose status contains this text; repeat to include multiple matches",
    )
    parser.add_argument(
        "--fail-on-stale",
        action="store_true",
        help="Exit non-zero when matching stale artifacts are found",
    )
    parser.add_argument(
        "--paths-only",
        action="store_true",
        help="Print one stale artifact path per line for cleanup scripts",
    )
    parser.add_argument(
        "--absolute-paths",
        action="store_true",
        help=(
            "With --paths-only, print paths resolved under the docs directory "
            "so cleanup scripts can run from any working directory"
        ),
    )
    parser.add_argument(
        "--repo-relative-paths",
        action="store_true",
        help=(
            "With --paths-only, print paths relative to the repository root, "
            "for example docs/benchmark-results/example.json"
        ),
    )
    parser.add_argument(
        "-0",
        "--null",
        action="store_true",
        help="With --paths-only, separate paths with NUL bytes for safe xargs -0 cleanup",
    )
    parser.add_argument(
        "--include-detail-pages",
        action="store_true",
        help="With --paths-only, also print matching prerendered detail page paths",
    )
    parser.add_argument(
        "--detail-pages-only",
        action="store_true",
        help="With --paths-only, only print matching prerendered detail page paths",
    )
    parser.add_argument(
        "--existing-paths-only",
        action="store_true",
        help="With --paths-only, only print artifact or detail page paths that exist on disk",
    )
    parser.add_argument(
        "--missing-paths-only",
        action="store_true",
        help="With --paths-only, only print artifact or detail page paths that are missing on disk",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument(
        "--json-summary",
        "--summary-json",
        action="store_true",
        dest="json_summary",
        help="Emit machine-readable stale artifact totals and summary groups",
    )
    parser.add_argument(
        "--summary-csv",
        "--csv-summary",
        action="store_true",
        dest="summary_csv",
        help="Emit stale artifact summary groups as CSV for spreadsheet cleanup review",
    )
    parser.add_argument(
        "--summary-markdown",
        "--markdown-summary",
        action="store_true",
        dest="summary_markdown",
        help="Emit stale artifact summary groups as a Markdown table for issues and PRs",
    )
    parser.add_argument(
        "--json-lines",
        "--jsonl",
        "--ndjson",
        action="store_true",
        dest="json_lines",
        help="Emit one machine-readable stale artifact JSON object per line",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Emit matching stale artifacts as CSV for spreadsheet cleanup review",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Emit matching stale artifacts as a Markdown table for issues and PRs",
    )
    parser.add_argument("--count-only", action="store_true", help="Print only the matching stale artifact count")
    parser.add_argument(
        "--total-bytes-only",
        action="store_true",
        help="Print only the total bytes across matching stale artifacts",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only stale artifact totals grouped by track slug",
    )
    parser.add_argument(
        "--group",
        "--groups",
        "--summary-group",
        "--summary-groups",
        dest="summary_group",
        action="append",
        default=None,
        help="With --summary-only, only print this grouping; repeat or comma-separate to include multiple groups; use 'all' for every grouping",
    )
    parser.add_argument(
        "--summary-limit",
        type=int,
        default=None,
        help="With --summary-only, print at most this many rows per grouping",
    )
    parser.add_argument(
        "--summary-sort",
        type=normalize_cli_token,
        choices=SUMMARY_SORTS,
        default="size",
        help=(
            "With --summary-only or --json-summary, sort grouping rows by total bytes, "
            "average size, count, or bucket name; use *-asc or *-desc for explicit direction"
        ),
    )
    parser.add_argument(
        "--summary-min-count",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with at least this many artifacts",
    )
    parser.add_argument(
        "--summary-max-count",
        type=int,
        default=None,
        help="With --summary-only or --json-summary, only print grouping rows with no more than this many artifacts",
    )
    parser.add_argument(
        "--summary-min-size",
        "--summary-min-size-bytes",
        dest="summary_min_size_bytes",
        type=parse_size_bytes,
        default=None,
        help=(
            "With --summary-only or --json-summary, only print grouping rows at least this large; "
            "accepts bytes or KB, KiB, MB, MiB, GB, GiB, TB, TiB"
        ),
    )
    parser.add_argument(
        "--summary-max-size",
        "--summary-max-size-bytes",
        dest="summary_max_size_bytes",
        type=parse_size_bytes,
        default=None,
        help=(
            "With --summary-only or --json-summary, only print grouping rows no larger than this; "
            "accepts bytes or KB, KiB, MB, MiB, GB, GiB, TB, TiB"
        ),
    )
    parser.add_argument(
        "--summary-share",
        "--summary-shares",
        "--include-summary-share",
        "--include-summary-shares",
        "--share",
        "--shares",
        dest="summary_share",
        action="store_true",
        help=(
            "With --json-summary, --summary-csv, or --summary-markdown, include count "
            "and byte share percentages for each grouping row"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write the rendered stale artifact report to this file instead of stdout; use '-' for stdout",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress rendered output while preserving the exit code, useful with --fail-on-stale in CI",
    )
    return parser.parse_args(argv)


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def parse_required_timestamp(value: str, *, field_name: str) -> datetime:
    parsed = parse_timestamp(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be an ISO timestamp or date")
    return parsed


def detail_page_path(artifact_path: str | None) -> str | None:
    if not artifact_path:
        return None
    artifact_name = Path(artifact_path).name
    if not artifact_name.endswith(".json"):
        return None
    return f"benchmark-results/pages/{Path(artifact_name).stem}.html"


def normalize_status_filters(statuses: list[str] | None) -> set[str] | None:
    if statuses is None:
        return {"legacy"}
    normalized = {
        status.strip().lower()
        for value in statuses
        for status in value.split(",")
        if status.strip()
    }
    return None if "any" in normalized else normalized


def normalize_filter_values(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    return [
        item.strip()
        for value in values
        for item in value.split(",")
        if item.strip()
    ]


def measured_month(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y-%m")


def measured_quarter(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    quarter = ((parsed.month - 1) // 3) + 1
    return f"{parsed.year}-Q{quarter}"


def measured_week(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    iso_year, iso_week, _ = parsed.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def measured_day(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y-%m-%d")


def measured_year(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%Y")


def valid_measured_month(value: str) -> bool:
    if len(value) != 7 or value[4] != "-":
        return False
    year, month = value.split("-", 1)
    return year.isdigit() and month.isdigit() and 1 <= int(month) <= 12


def valid_measured_week(value: str) -> bool:
    if len(value) != 8 or value[4:6] != "-W" or not value[:4].isdigit() or not value[6:].isdigit():
        return False
    try:
        datetime.fromisocalendar(int(value[:4]), int(value[6:]), 1)
    except ValueError:
        return False
    return True


def valid_measured_day(value: str) -> bool:
    if len(value) != 10 or value[4] != "-" or value[7] != "-" or not value.replace("-", "").isdigit():
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def age_bucket(age_days: int | None) -> str:
    if age_days is None:
        return "unknown"
    if age_days < 7:
        return "0-6d"
    if age_days < 30:
        return "7-29d"
    if age_days < 90:
        return "30-89d"
    return "90d+"


def descending_text_key(value: Any) -> tuple[int, ...]:
    return (*(-ord(character) for character in str(value)), 0)


def lowercase_cli_choice(value: str) -> str:
    return value.strip().lower()


def normalize_cli_token(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def normalize_stale_sort(sort_by: str) -> str:
    normalized = normalize_cli_token(sort_by)
    return STALE_SORT_ALIASES.get(normalized, normalized)


def normalize_summary_sort(sort_by: str) -> str:
    normalized = normalize_cli_token(sort_by)
    return SUMMARY_SORT_ALIASES.get(normalized, normalized)


def normalize_summary_groups(groups: list[str] | None) -> set[str]:
    selected_groups = {
        SUMMARY_GROUP_ALIASES.get(normalize_cli_token(group), normalize_cli_token(group))
        for value in (groups or list(SUMMARY_GROUPS))
        for group in value.split(",")
        if group.strip()
    }
    if "all" in selected_groups:
        selected_groups.remove("all")
        selected_groups.update(SUMMARY_GROUPS)
    invalid_groups = sorted(selected_groups - set(SUMMARY_GROUPS))
    if invalid_groups:
        valid_groups = ", ".join(SUMMARY_GROUPS)
        invalid_group_list = ", ".join(invalid_groups)
        raise ValueError(f"Unsupported summary group: {invalid_group_list}. Valid groups: {valid_groups}")
    return selected_groups


def manifest_source_label(path: Path) -> str:
    return "stdin" if str(path) == "-" else str(path)


def load_manifest_from_path(path: Path) -> dict[str, Any]:
    source = manifest_source_label(path)
    try:
        manifest_text = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source} contains invalid JSON: {error.msg}") from error
    if not isinstance(manifest, dict):
        raise ValueError(f"{source} must contain a JSON object")
    return manifest


def stale_artifacts(
    manifest: dict[str, Any],
    *,
    older_than_days: int | None = None,
    newer_than_days: int | None = None,
    measured_before: datetime | str | None = None,
    measured_after: datetime | str | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
    slugs: list[str] | None = None,
    slug_contains: list[str] | None = None,
    labels: list[str] | None = None,
    backends: list[str] | None = None,
    models: list[str] | None = None,
    current_paths: list[str] | None = None,
    current_path_contains: list[str] | None = None,
    current_path_names: list[str] | None = None,
    current_path_name_contains: list[str] | None = None,
    current_path_stems: list[str] | None = None,
    current_path_stem_contains: list[str] | None = None,
    current_path_dirs: list[str] | None = None,
    current_path_dir_contains: list[str] | None = None,
    current_path_extensions: list[str] | None = None,
    current_path_extension_contains: list[str] | None = None,
    track_state: str = "any",
    measured_years: list[str] | None = None,
    measured_quarters: list[str] | None = None,
    measured_months: list[str] | None = None,
    measured_weeks: list[str] | None = None,
    measured_days: list[str] | None = None,
    age_buckets: list[str] | None = None,
    artifact_paths: list[str] | None = None,
    artifact_path_contains: list[str] | None = None,
    artifact_dirs: list[str] | None = None,
    artifact_dir_contains: list[str] | None = None,
    artifact_names: list[str] | None = None,
    artifact_name_contains: list[str] | None = None,
    artifact_stems: list[str] | None = None,
    artifact_stem_contains: list[str] | None = None,
    artifact_extensions: list[str] | None = None,
    artifact_extension_contains: list[str] | None = None,
    detail_pages: list[str] | None = None,
    detail_page_contains: list[str] | None = None,
    detail_page_names: list[str] | None = None,
    detail_page_name_contains: list[str] | None = None,
    detail_page_stems: list[str] | None = None,
    detail_page_stem_contains: list[str] | None = None,
    detail_page_dirs: list[str] | None = None,
    detail_page_dir_contains: list[str] | None = None,
    detail_page_extensions: list[str] | None = None,
    detail_page_extension_contains: list[str] | None = None,
    statuses: list[str] | None = None,
    status_contains: list[str] | None = None,
    now: datetime | None = None,
    sort_by: str = "size",
) -> list[dict[str, Any]]:
    sort_by = normalize_stale_sort(sort_by)
    if min_size_bytes is not None and min_size_bytes < 0:
        raise ValueError("min_size_bytes must be non-negative")
    if max_size_bytes is not None and max_size_bytes < 0:
        raise ValueError("max_size_bytes must be non-negative")
    if min_size_bytes is not None and max_size_bytes is not None and min_size_bytes > max_size_bytes:
        raise ValueError("min_size_bytes cannot exceed max_size_bytes")
    if newer_than_days is not None and newer_than_days < 0:
        raise ValueError("newer_than_days must be non-negative")
    if older_than_days is not None and newer_than_days is not None and newer_than_days < older_than_days:
        raise ValueError("newer_than_days cannot be less than older_than_days")
    if track_state not in {"any", "tracked", "untracked"}:
        raise ValueError("track_state must be one of: any, tracked, untracked")
    slugs = normalize_filter_values(slugs)
    slug_contains = normalize_filter_values(slug_contains)
    labels = normalize_filter_values(labels)
    backends = normalize_filter_values(backends)
    models = normalize_filter_values(models)
    measured_years = normalize_filter_values(measured_years)
    measured_quarters = normalize_filter_values(measured_quarters)
    measured_months = normalize_filter_values(measured_months)
    measured_weeks = normalize_filter_values(measured_weeks)
    measured_days = normalize_filter_values(measured_days)
    age_buckets = normalize_filter_values(age_buckets)
    current_paths = normalize_filter_values(current_paths)
    current_path_contains = normalize_filter_values(current_path_contains)
    current_path_names = normalize_filter_values(current_path_names)
    current_path_name_contains = normalize_filter_values(current_path_name_contains)
    current_path_stems = normalize_filter_values(current_path_stems)
    current_path_stem_contains = normalize_filter_values(current_path_stem_contains)
    current_path_dirs = normalize_filter_values(current_path_dirs)
    current_path_dir_contains = normalize_filter_values(current_path_dir_contains)
    current_path_extensions = normalize_filter_values(current_path_extensions)
    current_path_extension_contains = normalize_filter_values(current_path_extension_contains)
    artifact_paths = normalize_filter_values(artifact_paths)
    artifact_path_contains = normalize_filter_values(artifact_path_contains)
    artifact_dirs = normalize_filter_values(artifact_dirs)
    artifact_dir_contains = normalize_filter_values(artifact_dir_contains)
    artifact_names = normalize_filter_values(artifact_names)
    artifact_name_contains = normalize_filter_values(artifact_name_contains)
    artifact_stems = normalize_filter_values(artifact_stems)
    artifact_stem_contains = normalize_filter_values(artifact_stem_contains)
    artifact_extensions = normalize_filter_values(artifact_extensions)
    artifact_extension_contains = normalize_filter_values(artifact_extension_contains)
    detail_pages = normalize_filter_values(detail_pages)
    detail_page_contains = normalize_filter_values(detail_page_contains)
    detail_page_names = normalize_filter_values(detail_page_names)
    detail_page_name_contains = normalize_filter_values(detail_page_name_contains)
    detail_page_stems = normalize_filter_values(detail_page_stems)
    detail_page_stem_contains = normalize_filter_values(detail_page_stem_contains)
    detail_page_dirs = normalize_filter_values(detail_page_dirs)
    detail_page_dir_contains = normalize_filter_values(detail_page_dir_contains)
    detail_page_extensions = normalize_filter_values(detail_page_extensions)
    detail_page_extension_contains = normalize_filter_values(detail_page_extension_contains)
    status_contains = normalize_filter_values(status_contains)
    allowed_measured_years = None
    if measured_years is not None:
        allowed_measured_years = {year.strip() for year in measured_years if year.strip()}
        invalid_years = [year for year in allowed_measured_years if len(year) != 4 or not year.isdigit()]
        if invalid_years:
            raise ValueError("measured_year values must use YYYY")
    allowed_measured_quarters = None
    if measured_quarters is not None:
        allowed_measured_quarters = {quarter.strip().upper() for quarter in measured_quarters if quarter.strip()}
        invalid_quarters = [
            quarter
            for quarter in allowed_measured_quarters
            if len(quarter) != 7
            or quarter[4:6] != "-Q"
            or not quarter[:4].isdigit()
            or quarter[6] not in {"1", "2", "3", "4"}
        ]
        if invalid_quarters:
            raise ValueError("measured_quarter values must use YYYY-Qn")
    allowed_measured_months = None
    if measured_months is not None:
        allowed_measured_months = {month.strip() for month in measured_months if month.strip()}
        invalid_months = [month for month in allowed_measured_months if not valid_measured_month(month)]
        if invalid_months:
            raise ValueError("measured_month values must use YYYY-MM")
    allowed_measured_weeks = None
    if measured_weeks is not None:
        allowed_measured_weeks = {week.strip() for week in measured_weeks if week.strip()}
        invalid_weeks = [week for week in allowed_measured_weeks if not valid_measured_week(week)]
        if invalid_weeks:
            raise ValueError("measured_week values must use YYYY-Www")
    allowed_measured_days = None
    if measured_days is not None:
        allowed_measured_days = {day.strip() for day in measured_days if day.strip()}
        invalid_days = [day for day in allowed_measured_days if not valid_measured_day(day)]
        if invalid_days:
            raise ValueError("measured_day values must use YYYY-MM-DD")
    allowed_age_buckets = None
    if age_buckets is not None:
        allowed_age_buckets = {bucket.lower() for bucket in age_buckets}
        invalid_age_buckets = sorted(allowed_age_buckets - {bucket.lower() for bucket in AGE_BUCKET_ORDER})
        if invalid_age_buckets:
            raise ValueError("age_bucket values must be one of: 0-6d, 7-29d, 30-89d, 90d+, unknown")

    cutoff = None
    if older_than_days is not None:
        if older_than_days < 0:
            raise ValueError("older_than_days must be non-negative")
        reference = now or datetime.now(UTC)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=UTC)
        try:
            cutoff = reference.astimezone(UTC) - timedelta(days=older_than_days)
        except OverflowError as error:
            raise ValueError("older_than_days is too large") from error
    if measured_before is not None:
        measured_before_cutoff = (
            parse_required_timestamp(measured_before, field_name="measured_before")
            if isinstance(measured_before, str)
            else measured_before
        )
        if measured_before_cutoff.tzinfo is None:
            measured_before_cutoff = measured_before_cutoff.replace(tzinfo=UTC)
        measured_before_cutoff = measured_before_cutoff.astimezone(UTC)
        cutoff = min(cutoff, measured_before_cutoff) if cutoff is not None else measured_before_cutoff
    lower_cutoff = None
    if measured_after is not None:
        lower_cutoff = (
            parse_required_timestamp(measured_after, field_name="measured_after")
            if isinstance(measured_after, str)
            else measured_after
        )
        if lower_cutoff.tzinfo is None:
            lower_cutoff = lower_cutoff.replace(tzinfo=UTC)
        lower_cutoff = lower_cutoff.astimezone(UTC)
    if cutoff is not None and lower_cutoff is not None and lower_cutoff >= cutoff:
        raise ValueError("measured_after must be earlier than the effective measured-before cutoff")

    age_reference = now or datetime.now(UTC)
    if age_reference.tzinfo is None:
        age_reference = age_reference.replace(tzinfo=UTC)
    age_reference = age_reference.astimezone(UTC)

    tracks = [track for track in manifest.get("tracks", []) if track.get("artifact_path")]
    current_artifact_paths = {track["artifact_path"] for track in tracks}
    current_path_by_slug = {track.get("slug"): track.get("artifact_path") for track in tracks if track.get("slug")}
    allowed_backends = None if backends is None else {backend.lower() for backend in backends}
    allowed_current_paths = (
        None
        if current_paths is None
        else {path for path in current_paths if path.lower() not in MISSING_CURRENT_PATH_FILTER_VALUES}
    )
    allow_missing_current_paths = current_paths is not None and any(
        path.lower() in MISSING_CURRENT_PATH_FILTER_VALUES for path in current_paths
    )
    current_path_needles = None if current_path_contains is None else [needle.lower() for needle in current_path_contains]
    allowed_current_path_names = (
        None if current_path_names is None else {Path(name).name for name in current_path_names}
    )
    current_path_name_needles = (
        None if current_path_name_contains is None else [needle.lower() for needle in current_path_name_contains]
    )
    allowed_current_path_stems = (
        None if current_path_stems is None else {Path(stem).stem for stem in current_path_stems}
    )
    current_path_stem_needles = (
        None if current_path_stem_contains is None else [needle.lower() for needle in current_path_stem_contains]
    )
    allowed_current_path_dirs = (
        None if current_path_dirs is None else {str(Path(path)) for path in current_path_dirs}
    )
    current_path_dir_needles = (
        None if current_path_dir_contains is None else [needle.lower() for needle in current_path_dir_contains]
    )
    allowed_current_path_extensions = (
        None
        if current_path_extensions is None
        else {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in current_path_extensions
            if extension.lower() != "none"
        }
    )
    allow_extensionless_current_paths = current_path_extensions is not None and any(
        extension.lower() == "none" for extension in current_path_extensions
    )
    current_path_extension_needles = (
        None
        if current_path_extension_contains is None
        else [needle.lower() for needle in current_path_extension_contains]
    )
    allowed_artifact_paths = None if artifact_paths is None else set(artifact_paths)
    slug_needles = None if slug_contains is None else [needle.lower() for needle in slug_contains]
    artifact_path_needles = (
        None if artifact_path_contains is None else [needle.lower() for needle in artifact_path_contains]
    )
    allowed_artifact_dirs = None if artifact_dirs is None else {str(Path(path)) for path in artifact_dirs}
    artifact_dir_needles = (
        None if artifact_dir_contains is None else [needle.lower() for needle in artifact_dir_contains]
    )
    allowed_artifact_names = None if artifact_names is None else {Path(name).name for name in artifact_names}
    artifact_name_needles = (
        None if artifact_name_contains is None else [needle.lower() for needle in artifact_name_contains]
    )
    allowed_artifact_stems = None if artifact_stems is None else {Path(stem).stem for stem in artifact_stems}
    artifact_stem_needles = (
        None if artifact_stem_contains is None else [needle.lower() for needle in artifact_stem_contains]
    )
    allowed_artifact_extensions = (
        None
        if artifact_extensions is None
        else {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in artifact_extensions
            if extension.lower() != "none"
        }
    )
    allow_extensionless_artifacts = artifact_extensions is not None and any(
        extension.lower() == "none" for extension in artifact_extensions
    )
    artifact_extension_needles = (
        None if artifact_extension_contains is None else [needle.lower() for needle in artifact_extension_contains]
    )
    allowed_detail_pages = None if detail_pages is None else set(detail_pages)
    detail_page_needles = None if detail_page_contains is None else [needle.lower() for needle in detail_page_contains]
    allowed_detail_page_names = None if detail_page_names is None else {Path(name).name for name in detail_page_names}
    detail_page_name_needles = (
        None if detail_page_name_contains is None else [needle.lower() for needle in detail_page_name_contains]
    )
    allowed_detail_page_stems = None if detail_page_stems is None else {Path(stem).stem for stem in detail_page_stems}
    detail_page_stem_needles = (
        None if detail_page_stem_contains is None else [needle.lower() for needle in detail_page_stem_contains]
    )
    allowed_detail_page_dirs = None if detail_page_dirs is None else {str(Path(path)) for path in detail_page_dirs}
    detail_page_dir_needles = (
        None if detail_page_dir_contains is None else [needle.lower() for needle in detail_page_dir_contains]
    )
    allowed_detail_page_extensions = (
        None
        if detail_page_extensions is None
        else {
            extension.lower() if extension.startswith(".") else f".{extension.lower()}"
            for extension in detail_page_extensions
            if extension.lower() != "none"
        }
    )
    allow_extensionless_detail_pages = detail_page_extensions is not None and any(
        extension.lower() == "none" for extension in detail_page_extensions
    )
    detail_page_extension_needles = (
        None
        if detail_page_extension_contains is None
        else [needle.lower() for needle in detail_page_extension_contains]
    )
    status_needles = None if status_contains is None else [needle.lower() for needle in status_contains]
    allowed_statuses = None if statuses is None and status_needles is not None else normalize_status_filters(statuses)
    stale: list[dict[str, Any]] = []
    for artifact in manifest.get("artifacts", []):
        artifact_path = artifact.get("artifact_path")
        if not artifact_path or artifact_path in current_artifact_paths:
            continue
        if allowed_artifact_paths is not None and artifact_path not in allowed_artifact_paths:
            continue
        if artifact_path_needles is not None:
            artifact_path_text = artifact_path.lower()
            if not any(needle in artifact_path_text for needle in artifact_path_needles):
                continue
        artifact_dir = str(Path(artifact_path).parent)
        if allowed_artifact_dirs is not None and artifact_dir not in allowed_artifact_dirs:
            continue
        if artifact_dir_needles is not None:
            if not any(needle in artifact_dir.lower() for needle in artifact_dir_needles):
                continue
        artifact_name = Path(artifact_path).name
        if allowed_artifact_names is not None and artifact_name not in allowed_artifact_names:
            continue
        if artifact_name_needles is not None and not any(
            needle in artifact_name.lower() for needle in artifact_name_needles
        ):
            continue
        artifact_stem = Path(artifact_path).stem
        if allowed_artifact_stems is not None and artifact_stem not in allowed_artifact_stems:
            continue
        if artifact_stem_needles is not None and not any(
            needle in artifact_stem.lower() for needle in artifact_stem_needles
        ):
            continue
        artifact_extension = Path(artifact_path).suffix.lower()
        if allowed_artifact_extensions is not None or allow_extensionless_artifacts:
            extension_matches = artifact_extension in (allowed_artifact_extensions or set())
            extensionless_matches = allow_extensionless_artifacts and artifact_extension == ""
            if not extension_matches and not extensionless_matches:
                continue
        if artifact_extension_needles is not None:
            artifact_extension_text = artifact_extension or "none"
            if not any(needle in artifact_extension_text for needle in artifact_extension_needles):
                continue
        artifact_detail_page_path = detail_page_path(artifact_path)
        if allowed_detail_pages is not None and artifact_detail_page_path not in allowed_detail_pages:
            continue
        if detail_page_needles is not None:
            detail_page_text = str(artifact_detail_page_path or "").lower()
            if not any(needle in detail_page_text for needle in detail_page_needles):
                continue
        detail_page_name = Path(artifact_detail_page_path or "").name
        if allowed_detail_page_names is not None and detail_page_name not in allowed_detail_page_names:
            continue
        if detail_page_name_needles is not None:
            if not any(needle in detail_page_name.lower() for needle in detail_page_name_needles):
                continue
        detail_page_stem = Path(artifact_detail_page_path or "").stem
        if allowed_detail_page_stems is not None and detail_page_stem not in allowed_detail_page_stems:
            continue
        if detail_page_stem_needles is not None:
            if not any(needle in detail_page_stem.lower() for needle in detail_page_stem_needles):
                continue
        detail_page_dir = str(Path(artifact_detail_page_path or "").parent)
        if allowed_detail_page_dirs is not None and detail_page_dir not in allowed_detail_page_dirs:
            continue
        if detail_page_dir_needles is not None:
            if not any(needle in detail_page_dir.lower() for needle in detail_page_dir_needles):
                continue
        detail_page_extension = Path(artifact_detail_page_path or "").suffix.lower()
        if allowed_detail_page_extensions is not None or allow_extensionless_detail_pages:
            extension_matches = detail_page_extension in (allowed_detail_page_extensions or set())
            extensionless_matches = allow_extensionless_detail_pages and detail_page_extension == ""
            if not extension_matches and not extensionless_matches:
                continue
        if detail_page_extension_needles is not None:
            detail_page_extension_text = detail_page_extension or "none"
            if not any(needle in detail_page_extension_text for needle in detail_page_extension_needles):
                continue
        artifact_status = str(artifact.get("status") or "").lower()
        if allowed_statuses is not None and artifact_status not in allowed_statuses:
            continue
        if status_needles is not None and not any(needle in artifact_status for needle in status_needles):
            continue
        if slugs is not None and artifact.get("slug") not in slugs:
            continue
        if labels is not None:
            artifact_label = str(artifact.get("label") or "").lower()
            if not any(label.lower() in artifact_label for label in labels):
                continue
        artifact_backend = str(artifact.get("backend") or "").lower()
        if allowed_backends is not None and artifact_backend not in allowed_backends:
            continue
        if models is not None:
            artifact_model = str(artifact.get("model") or "").lower()
            if not any(model.lower() in artifact_model for model in models):
                continue
        current_artifact_path = current_path_by_slug.get(artifact.get("slug"))
        if allowed_current_paths is not None or allow_missing_current_paths:
            current_path_matches = current_artifact_path in (allowed_current_paths or set())
            missing_current_path_matches = allow_missing_current_paths and current_artifact_path is None
            if not current_path_matches and not missing_current_path_matches:
                continue
        if current_path_needles is not None:
            current_path_text = str(current_artifact_path or "").lower()
            if not any(needle in current_path_text for needle in current_path_needles):
                continue
        current_path_name = Path(current_artifact_path or "").name
        if allowed_current_path_names is not None and current_path_name not in allowed_current_path_names:
            continue
        if current_path_name_needles is not None:
            if not any(needle in current_path_name.lower() for needle in current_path_name_needles):
                continue
        current_path_stem = Path(current_artifact_path or "").stem
        if allowed_current_path_stems is not None and current_path_stem not in allowed_current_path_stems:
            continue
        if current_path_stem_needles is not None:
            if not any(needle in current_path_stem.lower() for needle in current_path_stem_needles):
                continue
        current_path_dir = str(Path(current_artifact_path or "").parent)
        if allowed_current_path_dirs is not None and current_path_dir not in allowed_current_path_dirs:
            continue
        if current_path_dir_needles is not None:
            if not any(needle in current_path_dir.lower() for needle in current_path_dir_needles):
                continue
        current_path_extension = Path(current_artifact_path or "").suffix.lower()
        if allowed_current_path_extensions is not None or allow_extensionless_current_paths:
            current_extension_matches = current_path_extension in (allowed_current_path_extensions or set())
            current_extensionless_matches = allow_extensionless_current_paths and current_path_extension == ""
            if not current_extension_matches and not current_extensionless_matches:
                continue
        if current_path_extension_needles is not None:
            current_path_extension_text = current_path_extension or "none"
            if not any(needle in current_path_extension_text for needle in current_path_extension_needles):
                continue
        if track_state == "tracked" and current_artifact_path is None:
            continue
        if track_state == "untracked" and current_artifact_path is not None:
            continue
        if slug_needles is not None:
            artifact_slug = str(artifact.get("slug") or "").lower()
            if not any(needle in artifact_slug for needle in slug_needles):
                continue
        measured_at = artifact.get("measured_at")
        measured_timestamp = parse_timestamp(measured_at)
        artifact_measured_year = measured_year(measured_at)
        artifact_measured_quarter = measured_quarter(measured_at)
        artifact_measured_month = measured_month(measured_at)
        artifact_measured_week = measured_week(measured_at)
        artifact_measured_day = measured_day(measured_at)
        artifact_age_days = None
        if measured_timestamp is not None:
            artifact_age_days = max((age_reference - measured_timestamp).days, 0)
        artifact_age_bucket = age_bucket(artifact_age_days)
        if allowed_measured_years is not None and artifact_measured_year not in allowed_measured_years:
            continue
        if allowed_measured_quarters is not None and artifact_measured_quarter not in allowed_measured_quarters:
            continue
        if allowed_measured_months is not None and artifact_measured_month not in allowed_measured_months:
            continue
        if allowed_measured_weeks is not None and artifact_measured_week not in allowed_measured_weeks:
            continue
        if allowed_measured_days is not None and artifact_measured_day not in allowed_measured_days:
            continue
        if allowed_age_buckets is not None and artifact_age_bucket.lower() not in allowed_age_buckets:
            continue
        if cutoff is not None and (measured_timestamp is None or measured_timestamp >= cutoff):
            continue
        if lower_cutoff is not None and (measured_timestamp is None or measured_timestamp <= lower_cutoff):
            continue
        if newer_than_days is not None and (artifact_age_days is None or artifact_age_days > newer_than_days):
            continue
        artifact_size_bytes = artifact.get("artifact_size_bytes")
        if min_size_bytes is not None and (artifact_size_bytes or 0) < min_size_bytes:
            continue
        if max_size_bytes is not None and (artifact_size_bytes or 0) > max_size_bytes:
            continue
        current_artifact_name = Path(current_artifact_path or "").name or None
        current_artifact_stem = Path(current_artifact_path or "").stem or None
        current_artifact_dir = str(Path(current_artifact_path).parent) if current_artifact_path else None
        detail_page_name = Path(artifact_detail_page_path or "").name or None
        detail_page_stem = Path(artifact_detail_page_path or "").stem or None
        detail_page_dir = str(Path(artifact_detail_page_path).parent) if artifact_detail_page_path else None
        detail_page_extension = Path(artifact_detail_page_path or "").suffix.lower() or "none"
        stale.append(
            {
                "artifact_path": artifact_path,
                "artifact_name": artifact_name,
                "artifact_stem": artifact_stem,
                "artifact_dir": artifact_dir,
                "artifact_extension": artifact_extension or "none",
                "slug": artifact.get("slug"),
                "label": artifact.get("label"),
                "backend": artifact.get("backend"),
                "model": artifact.get("model"),
                "status": artifact.get("status"),
                "measured_at": measured_at,
                "measured_year": artifact_measured_year,
                "measured_quarter": artifact_measured_quarter,
                "measured_month": artifact_measured_month,
                "measured_week": artifact_measured_week,
                "measured_day": artifact_measured_day,
                "age_days": artifact_age_days,
                "age_bucket": artifact_age_bucket,
                "age": format_age_days(artifact_age_days),
                "current_artifact_path": current_artifact_path,
                "current_artifact_name": current_artifact_name,
                "current_artifact_stem": current_artifact_stem,
                "current_artifact_dir": current_artifact_dir,
                "current_artifact_extension": current_path_extension or "none",
                "track_state": "tracked" if current_artifact_path is not None else "untracked",
                "detail_page_path": artifact_detail_page_path,
                "detail_page_name": detail_page_name,
                "detail_page_stem": detail_page_stem,
                "detail_page_dir": detail_page_dir,
                "detail_page_extension": detail_page_extension,
                "artifact_size_bytes": artifact_size_bytes,
                "artifact_size": format_bytes(artifact_size_bytes),
            }
        )
    if sort_by in {
        "size",
        "size-desc",
        "bytes",
        "bytes-desc",
        "disk-size",
        "disk-size-desc",
        "total-size",
        "total-size-desc",
        "total-bytes",
        "total-bytes-desc",
        "heaviest",
        "largest",
    }:
        return sorted(
            stale,
            key=lambda entry: (
                -(entry.get("artifact_size_bytes") or 0),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {
        "size-asc",
        "bytes-asc",
        "disk-size-asc",
        "total-size-asc",
        "total-bytes-asc",
        "lightest",
        "smallest",
    }:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("artifact_size_bytes") or 0,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"age", "age-desc"}:
        return sorted(
            stale,
            key=lambda entry: (
                -(entry.get("age_days") if entry.get("age_days") is not None else -1),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "age-asc":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("age_days") if entry.get("age_days") is not None else sys.maxsize,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-at", "measured-at-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                parse_timestamp(entry.get("measured_at")) or datetime.max.replace(tzinfo=UTC),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-at-desc":
        return sorted(
            stale,
            key=lambda entry: (
                -(parse_timestamp(entry.get("measured_at")) or datetime.min.replace(tzinfo=UTC)).timestamp(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"path", "path-asc", "artifact-path", "artifact-path-asc"}:
        return sorted(stale, key=lambda entry: entry.get("artifact_path") or "")
    if sort_by in {"path-desc", "artifact-path-desc"}:
        return sorted(stale, key=lambda entry: entry.get("artifact_path") or "", reverse=True)
    if sort_by in {"artifact-name", "artifact-name-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("artifact_path") or "").name),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"artifact-stem", "artifact-stem-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").stem,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-stem-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("artifact_path") or "").stem),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"artifact-dir", "artifact-dir-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("artifact_path") or "").parent),
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-dir-desc":
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("artifact_path") or "").parent),
                Path(entry.get("artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by in {"artifact-extension", "artifact-extension-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").suffix.lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "artifact-extension-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("artifact_path") or "").suffix.lower() == "",
                descending_text_key(Path(entry.get("artifact_path") or "").suffix.lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"detail-page", "detail-page-asc"}:
        return sorted(stale, key=lambda entry: entry.get("detail_page_path") or "")
    if sort_by == "detail-page-desc":
        return sorted(stale, key=lambda entry: entry.get("detail_page_path") or "", reverse=True)
    if sort_by in {"detail-page-name", "detail-page-name-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("detail_page_path") or "").name),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"detail-page-stem", "detail-page-stem-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").stem,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page-stem-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in Path(entry.get("detail_page_path") or "").stem),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"detail-page-dir", "detail-page-dir-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("detail_page_path") or "").parent),
                Path(entry.get("detail_page_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page-dir-desc":
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("detail_page_path") or "").parent),
                Path(entry.get("detail_page_path") or "").name,
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by in {"detail-page-extension", "detail-page-extension-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").suffix.lower(),
                entry.get("detail_page_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "detail-page-extension-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("detail_page_path") or "").suffix.lower() == "",
                descending_text_key(Path(entry.get("detail_page_path") or "").suffix.lower()),
                entry.get("detail_page_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"status", "status-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("status") or "unknown").lower(),
                entry.get("slug") or "untracked",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "status-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("status") or "unknown").lower()),
                entry.get("slug") or "untracked",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"backend", "backend-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("backend") or "unknown").lower(),
                str(entry.get("model") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "backend-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
                descending_text_key(str(entry.get("model") or "unknown").lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"model", "model-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("model") or "unknown").lower(),
                str(entry.get("backend") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "model-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("model") or "unknown").lower()),
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"label", "label-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("label") or "unknown").lower(),
                str(entry.get("backend") or "unknown").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "label-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("label") or "unknown").lower()),
                descending_text_key(str(entry.get("backend") or "unknown").lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"slug", "slug-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("slug") or "untracked").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "slug-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("slug") or "untracked").lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"track-state", "track-state-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(entry.get("track_state") or "untracked").lower(),
                str(entry.get("slug") or "untracked").lower(),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "track-state-desc":
        return sorted(
            stale,
            key=lambda entry: (
                descending_text_key(str(entry.get("track_state") or "untracked").lower()),
                descending_text_key(str(entry.get("slug") or "untracked").lower()),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"current-path", "current-path-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-desc":
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("current_artifact_path") is None,
                descending_text_key(entry.get("current_artifact_path") or ""),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"current-path-name", "current-path-name-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-name-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by in {"current-path-stem", "current-path-stem-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").stem,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-stem-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").stem,
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by in {"current-path-dir", "current-path-dir-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("current_artifact_path") or "").parent),
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-dir-desc":
        return sorted(
            stale,
            key=lambda entry: (
                str(Path(entry.get("current_artifact_path") or "").parent),
                Path(entry.get("current_artifact_path") or "").name,
                entry.get("artifact_path") or "",
            ),
            reverse=True,
        )
    if sort_by in {"current-path-extension", "current-path-extension-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").suffix.lower(),
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "current-path-extension-desc":
        return sorted(
            stale,
            key=lambda entry: (
                Path(entry.get("current_artifact_path") or "").suffix.lower() == "",
                descending_text_key(Path(entry.get("current_artifact_path") or "").suffix.lower()),
                entry.get("current_artifact_path") or "",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-year", "measured-year-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_year") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-year-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_year") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-quarter", "measured-quarter-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_quarter") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-quarter-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_quarter") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-month", "measured-month-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_month") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-month-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_month") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-week", "measured-week-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_week") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-week-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_week") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"measured-day", "measured-day-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                entry.get("measured_day") or "unknown",
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "measured-day-desc":
        return sorted(
            stale,
            key=lambda entry: (
                tuple(-ord(character) for character in str(entry.get("measured_day") or "unknown")),
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by in {"age-bucket", "age-bucket-asc"}:
        return sorted(
            stale,
            key=lambda entry: (
                AGE_BUCKET_ORDER.get(str(entry.get("age_bucket") or "unknown"), sys.maxsize),
                entry.get("age_days") if entry.get("age_days") is not None else sys.maxsize,
                entry.get("artifact_path") or "",
            ),
        )
    if sort_by == "age-bucket-desc":
        return sorted(
            stale,
            key=lambda entry: (
                -AGE_BUCKET_ORDER.get(str(entry.get("age_bucket") or "unknown"), sys.maxsize),
                -(entry.get("age_days") if entry.get("age_days") is not None else -1),
                entry.get("artifact_path") or "",
            ),
        )
    raise ValueError(
        "sort_by must be one of: size, size-desc, size-asc, bytes, bytes-desc, bytes-asc, disk-size, disk-size-desc, disk-size-asc, total-size, total-size-desc, total-size-asc, largest, smallest, age, age-desc, age-asc, measured-at, measured-at-asc, measured-at-desc, oldest, oldest-first, earliest, earliest-first, least-recent, least-recent-first, newest, newest-first, latest, latest-first, recent, recent-first, most-recent, most-recent-first, path, path-asc, path-desc, artifact-path, artifact-path-asc, artifact-path-desc, artifact-name, artifact-name-asc, artifact-name-desc, artifact-stem, artifact-stem-asc, artifact-stem-desc, artifact-dir, artifact-dir-asc, artifact-dir-desc, artifact-extension, artifact-extension-asc, artifact-extension-desc, detail-page, detail-page-asc, detail-page-desc, detail-page-name, detail-page-name-asc, detail-page-name-desc, detail-page-stem, detail-page-stem-asc, detail-page-stem-desc, detail-page-dir, detail-page-dir-asc, detail-page-dir-desc, detail-page-extension, detail-page-extension-asc, detail-page-extension-desc, status, status-asc, status-desc, backend, backend-asc, backend-desc, model, model-asc, model-desc, label, label-asc, label-desc, slug, slug-asc, slug-desc, track-state, track-state-asc, track-state-desc, current-path, current-path-asc, current-path-desc, current-path-name, current-path-name-asc, current-path-name-desc, current-path-stem, current-path-stem-asc, current-path-stem-desc, current-path-dir, current-path-dir-asc, current-path-dir-desc, current-path-extension, current-path-extension-asc, current-path-extension-desc, measured-year, measured-year-asc, measured-year-desc, measured-quarter, measured-quarter-asc, measured-quarter-desc, measured-month, measured-month-asc, measured-month-desc, measured-week, measured-week-asc, measured-week-desc, measured-day, measured-day-asc, measured-day-desc, age-bucket, age-bucket-asc, age-bucket-desc"
    )


def stale_summary(stale: list[dict[str, Any]]) -> dict[str, Any]:
    total_size_bytes = sum(entry.get("artifact_size_bytes") or 0 for entry in stale)
    by_slug: dict[str, dict[str, Any]] = {}
    by_artifact_path: dict[str, dict[str, Any]] = {}
    by_artifact_name: dict[str, dict[str, Any]] = {}
    by_artifact_stem: dict[str, dict[str, Any]] = {}
    by_artifact_dir: dict[str, dict[str, Any]] = {}
    by_artifact_extension: dict[str, dict[str, Any]] = {}
    by_status: dict[str, dict[str, Any]] = {}
    by_backend: dict[str, dict[str, Any]] = {}
    by_model: dict[str, dict[str, Any]] = {}
    by_label: dict[str, dict[str, Any]] = {}
    by_current_artifact_path: dict[str, dict[str, Any]] = {}
    by_current_artifact_name: dict[str, dict[str, Any]] = {}
    by_current_artifact_stem: dict[str, dict[str, Any]] = {}
    by_current_artifact_dir: dict[str, dict[str, Any]] = {}
    by_current_artifact_extension: dict[str, dict[str, Any]] = {}
    by_track_state: dict[str, dict[str, Any]] = {}
    by_detail_page_path: dict[str, dict[str, Any]] = {}
    by_detail_page_name: dict[str, dict[str, Any]] = {}
    by_detail_page_stem: dict[str, dict[str, Any]] = {}
    by_detail_page_dir: dict[str, dict[str, Any]] = {}
    by_detail_page_extension: dict[str, dict[str, Any]] = {}
    by_measured_year: dict[str, dict[str, Any]] = {}
    by_measured_quarter: dict[str, dict[str, Any]] = {}
    by_measured_month: dict[str, dict[str, Any]] = {}
    by_measured_week: dict[str, dict[str, Any]] = {}
    by_measured_day: dict[str, dict[str, Any]] = {}
    by_age_bucket: dict[str, dict[str, Any]] = {}
    for entry in stale:
        slug = str(entry.get("slug") or "untracked")
        bucket = by_slug.setdefault(
            slug,
            {
                "slug": slug,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        bucket["count"] += 1
        bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        bucket["total_size"] = format_bytes(bucket["total_size_bytes"])

        artifact_path = str(entry.get("artifact_path") or "unknown")
        artifact_path_bucket = by_artifact_path.setdefault(
            artifact_path,
            {
                "artifact_path": artifact_path,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_path_bucket["count"] += 1
        artifact_path_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_path_bucket["total_size"] = format_bytes(artifact_path_bucket["total_size_bytes"])

        artifact_name = Path(entry.get("artifact_path") or "").name or "unknown"
        artifact_name_bucket = by_artifact_name.setdefault(
            artifact_name,
            {
                "artifact_name": artifact_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_name_bucket["count"] += 1
        artifact_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_name_bucket["total_size"] = format_bytes(artifact_name_bucket["total_size_bytes"])

        artifact_stem = Path(entry.get("artifact_path") or "").stem or "unknown"
        artifact_stem_bucket = by_artifact_stem.setdefault(
            artifact_stem,
            {
                "artifact_stem": artifact_stem,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_stem_bucket["count"] += 1
        artifact_stem_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_stem_bucket["total_size"] = format_bytes(artifact_stem_bucket["total_size_bytes"])

        artifact_dir = str(Path(entry.get("artifact_path") or "").parent) or "."
        artifact_dir_bucket = by_artifact_dir.setdefault(
            artifact_dir,
            {
                "artifact_dir": artifact_dir,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_dir_bucket["count"] += 1
        artifact_dir_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_dir_bucket["total_size"] = format_bytes(artifact_dir_bucket["total_size_bytes"])

        artifact_extension = Path(entry.get("artifact_path") or "").suffix.lower() or "none"
        artifact_extension_bucket = by_artifact_extension.setdefault(
            artifact_extension,
            {
                "artifact_extension": artifact_extension,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        artifact_extension_bucket["count"] += 1
        artifact_extension_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        artifact_extension_bucket["total_size"] = format_bytes(artifact_extension_bucket["total_size_bytes"])

        status = str(entry.get("status") or "unknown")
        status_bucket = by_status.setdefault(
            status,
            {
                "status": status,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        status_bucket["count"] += 1
        status_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        status_bucket["total_size"] = format_bytes(status_bucket["total_size_bytes"])

        backend = str(entry.get("backend") or "unknown")
        backend_bucket = by_backend.setdefault(
            backend,
            {
                "backend": backend,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        backend_bucket["count"] += 1
        backend_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        backend_bucket["total_size"] = format_bytes(backend_bucket["total_size_bytes"])

        model = str(entry.get("model") or "unknown")
        model_bucket = by_model.setdefault(
            model,
            {
                "model": model,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        model_bucket["count"] += 1
        model_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        model_bucket["total_size"] = format_bytes(model_bucket["total_size_bytes"])

        label = str(entry.get("label") or "unknown")
        label_bucket = by_label.setdefault(
            label,
            {
                "label": label,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        label_bucket["count"] += 1
        label_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        label_bucket["total_size"] = format_bytes(label_bucket["total_size_bytes"])

        current_artifact_path = str(entry.get("current_artifact_path") or "untracked")
        current_bucket = by_current_artifact_path.setdefault(
            current_artifact_path,
            {
                "current_artifact_path": current_artifact_path,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_bucket["count"] += 1
        current_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_bucket["total_size"] = format_bytes(current_bucket["total_size_bytes"])

        current_artifact_name = Path(entry.get("current_artifact_path") or "").name or "untracked"
        current_name_bucket = by_current_artifact_name.setdefault(
            current_artifact_name,
            {
                "current_artifact_name": current_artifact_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_name_bucket["count"] += 1
        current_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_name_bucket["total_size"] = format_bytes(current_name_bucket["total_size_bytes"])

        current_artifact_stem = Path(entry.get("current_artifact_path") or "").stem or "untracked"
        current_stem_bucket = by_current_artifact_stem.setdefault(
            current_artifact_stem,
            {
                "current_artifact_stem": current_artifact_stem,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_stem_bucket["count"] += 1
        current_stem_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_stem_bucket["total_size"] = format_bytes(current_stem_bucket["total_size_bytes"])

        current_artifact_dir = str(Path(entry.get("current_artifact_path") or "").parent) if entry.get("current_artifact_path") else "untracked"
        current_dir_bucket = by_current_artifact_dir.setdefault(
            current_artifact_dir,
            {
                "current_artifact_dir": current_artifact_dir,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_dir_bucket["count"] += 1
        current_dir_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_dir_bucket["total_size"] = format_bytes(current_dir_bucket["total_size_bytes"])

        current_artifact_extension = Path(entry.get("current_artifact_path") or "").suffix.lower() or "none"
        current_extension_bucket = by_current_artifact_extension.setdefault(
            current_artifact_extension,
            {
                "current_artifact_extension": current_artifact_extension,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        current_extension_bucket["count"] += 1
        current_extension_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        current_extension_bucket["total_size"] = format_bytes(current_extension_bucket["total_size_bytes"])

        track_state = str(entry.get("track_state") or "untracked")
        track_state_bucket = by_track_state.setdefault(
            track_state,
            {
                "track_state": track_state,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        track_state_bucket["count"] += 1
        track_state_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        track_state_bucket["total_size"] = format_bytes(track_state_bucket["total_size_bytes"])

        detail_page = str(entry.get("detail_page_path") or "missing")
        detail_bucket = by_detail_page_path.setdefault(
            detail_page,
            {
                "detail_page_path": detail_page,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_bucket["count"] += 1
        detail_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_bucket["total_size"] = format_bytes(detail_bucket["total_size_bytes"])

        detail_page_name = Path(entry.get("detail_page_path") or "").name or "missing"
        detail_name_bucket = by_detail_page_name.setdefault(
            detail_page_name,
            {
                "detail_page_name": detail_page_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_name_bucket["count"] += 1
        detail_name_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_name_bucket["total_size"] = format_bytes(detail_name_bucket["total_size_bytes"])

        detail_page_stem = Path(entry.get("detail_page_path") or "").stem or "missing"
        detail_stem_bucket = by_detail_page_stem.setdefault(
            detail_page_stem,
            {
                "detail_page_stem": detail_page_stem,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_stem_bucket["count"] += 1
        detail_stem_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_stem_bucket["total_size"] = format_bytes(detail_stem_bucket["total_size_bytes"])

        detail_page_dir = (
            str(Path(entry.get("detail_page_path") or "").parent)
            if entry.get("detail_page_path")
            else "missing"
        )
        detail_dir_bucket = by_detail_page_dir.setdefault(
            detail_page_dir,
            {
                "detail_page_dir": detail_page_dir,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_dir_bucket["count"] += 1
        detail_dir_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_dir_bucket["total_size"] = format_bytes(detail_dir_bucket["total_size_bytes"])

        detail_page_extension = Path(entry.get("detail_page_path") or "").suffix.lower() or "none"
        detail_extension_bucket = by_detail_page_extension.setdefault(
            detail_page_extension,
            {
                "detail_page_extension": detail_page_extension,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        detail_extension_bucket["count"] += 1
        detail_extension_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        detail_extension_bucket["total_size"] = format_bytes(detail_extension_bucket["total_size_bytes"])

        year = str(entry.get("measured_year") or measured_year(entry.get("measured_at")))
        year_bucket = by_measured_year.setdefault(
            year,
            {
                "measured_year": year,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        year_bucket["count"] += 1
        year_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        year_bucket["total_size"] = format_bytes(year_bucket["total_size_bytes"])

        quarter = str(entry.get("measured_quarter") or measured_quarter(entry.get("measured_at")))
        quarter_bucket = by_measured_quarter.setdefault(
            quarter,
            {
                "measured_quarter": quarter,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        quarter_bucket["count"] += 1
        quarter_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        quarter_bucket["total_size"] = format_bytes(quarter_bucket["total_size_bytes"])

        month = measured_month(entry.get("measured_at"))
        month_bucket = by_measured_month.setdefault(
            month,
            {
                "measured_month": month,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        month_bucket["count"] += 1
        month_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        month_bucket["total_size"] = format_bytes(month_bucket["total_size_bytes"])

        week = str(entry.get("measured_week") or measured_week(entry.get("measured_at")))
        week_bucket = by_measured_week.setdefault(
            week,
            {
                "measured_week": week,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        week_bucket["count"] += 1
        week_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        week_bucket["total_size"] = format_bytes(week_bucket["total_size_bytes"])

        day = str(entry.get("measured_day") or measured_day(entry.get("measured_at")))
        day_bucket = by_measured_day.setdefault(
            day,
            {
                "measured_day": day,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        day_bucket["count"] += 1
        day_bucket["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        day_bucket["total_size"] = format_bytes(day_bucket["total_size_bytes"])

        age_bucket_name = str(entry.get("age_bucket") or age_bucket(entry.get("age_days")))
        age_bucket_entry = by_age_bucket.setdefault(
            age_bucket_name,
            {
                "age_bucket": age_bucket_name,
                "count": 0,
                "total_size_bytes": 0,
                "total_size": "0 B",
            },
        )
        age_bucket_entry["count"] += 1
        age_bucket_entry["total_size_bytes"] += entry.get("artifact_size_bytes") or 0
        age_bucket_entry["total_size"] = format_bytes(age_bucket_entry["total_size_bytes"])

    return {
        "count": len(stale),
        "total_size_bytes": total_size_bytes,
        "total_size": format_bytes(total_size_bytes),
        "by_slug": sorted(
            by_slug.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["slug"]),
        ),
        "by_artifact_path": sorted(
            by_artifact_path.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_path"]),
        ),
        "by_artifact_name": sorted(
            by_artifact_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_name"]),
        ),
        "by_artifact_stem": sorted(
            by_artifact_stem.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_stem"]),
        ),
        "by_artifact_dir": sorted(
            by_artifact_dir.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_dir"]),
        ),
        "by_artifact_extension": sorted(
            by_artifact_extension.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["artifact_extension"]),
        ),
        "by_status": sorted(
            by_status.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["status"]),
        ),
        "by_backend": sorted(
            by_backend.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["backend"]),
        ),
        "by_model": sorted(
            by_model.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["model"]),
        ),
        "by_label": sorted(
            by_label.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["label"]),
        ),
        "by_current_artifact_path": sorted(
            by_current_artifact_path.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_path"]),
        ),
        "by_current_artifact_name": sorted(
            by_current_artifact_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_name"]),
        ),
        "by_current_artifact_stem": sorted(
            by_current_artifact_stem.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_stem"]),
        ),
        "by_current_artifact_dir": sorted(
            by_current_artifact_dir.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_dir"]),
        ),
        "by_current_artifact_extension": sorted(
            by_current_artifact_extension.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["current_artifact_extension"]),
        ),
        "by_track_state": sorted(
            by_track_state.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["track_state"]),
        ),
        "by_detail_page_path": sorted(
            by_detail_page_path.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_path"]),
        ),
        "by_detail_page_name": sorted(
            by_detail_page_name.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_name"]),
        ),
        "by_detail_page_stem": sorted(
            by_detail_page_stem.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_stem"]),
        ),
        "by_detail_page_dir": sorted(
            by_detail_page_dir.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_dir"]),
        ),
        "by_detail_page_extension": sorted(
            by_detail_page_extension.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["detail_page_extension"]),
        ),
        "by_measured_year": sorted(
            by_measured_year.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_year"]),
        ),
        "by_measured_quarter": sorted(
            by_measured_quarter.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_quarter"]),
        ),
        "by_measured_month": sorted(
            by_measured_month.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_month"]),
        ),
        "by_measured_week": sorted(
            by_measured_week.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_week"]),
        ),
        "by_measured_day": sorted(
            by_measured_day.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["measured_day"]),
        ),
        "by_age_bucket": sorted(
            by_age_bucket.values(),
            key=lambda entry: (-entry["total_size_bytes"], entry["age_bucket"]),
        ),
        "artifacts": stale,
    }


def limit_artifacts(stale: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    if limit is None:
        return stale
    if limit < 0:
        raise ValueError("limit must be non-negative")
    return stale[:limit]


def validate_summary_options(
    *,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
) -> None:
    summary_sort = normalize_summary_sort(summary_sort)
    if summary_limit is not None and summary_limit < 0:
        raise ValueError("summary_limit must be non-negative")
    if summary_sort not in SUMMARY_SORTS:
        raise ValueError(f"summary_sort must be one of: {', '.join(SUMMARY_SORTS)}")
    if summary_min_count is not None and summary_min_count < 0:
        raise ValueError("summary_min_count must be non-negative")
    if summary_max_count is not None and summary_max_count < 0:
        raise ValueError("summary_max_count must be non-negative")
    if summary_min_count is not None and summary_max_count is not None and summary_min_count > summary_max_count:
        raise ValueError("summary_min_count cannot exceed summary_max_count")
    if summary_min_size_bytes is not None and summary_min_size_bytes < 0:
        raise ValueError("summary_min_size_bytes must be non-negative")
    if summary_max_size_bytes is not None and summary_max_size_bytes < 0:
        raise ValueError("summary_max_size_bytes must be non-negative")
    if (
        summary_min_size_bytes is not None
        and summary_max_size_bytes is not None
        and summary_min_size_bytes > summary_max_size_bytes
    ):
        raise ValueError("summary_min_size_bytes cannot exceed summary_max_size_bytes")


def render_text(
    stale: list[dict[str, Any]],
    *,
    total_count: int | None = None,
    total_size_bytes: int | None = None,
) -> str:
    if not stale:
        if total_count:
            return (
                f"Found {total_count} stale benchmark artifacts, but 0 are shown "
                "because --limit omitted all matches."
            )
        return "No stale benchmark artifacts found."
    summary = stale_summary(stale)
    total_count = total_count if total_count is not None else summary["count"]
    shown_noun = "artifact" if summary["count"] == 1 else "artifacts"
    lines = [
        "Found {count} stale benchmark {noun} ({size}, {bytes} bytes):".format(
            count=summary["count"],
            noun=shown_noun,
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    for entry in stale:
        current_artifact_path = entry.get("current_artifact_path")
        current_suffix = f"; current: {current_artifact_path}" if current_artifact_path else ""
        detail_page_path = entry.get("detail_page_path")
        detail_suffix = f"; detail: {detail_page_path}" if detail_page_path else ""
        status = entry.get("status") or "unknown"
        lines.append(
            "- {artifact_path} [{slug}] status {status} measured {measured_at} ({age}; {artifact_size}){current_suffix}{detail_suffix}".format(
                artifact_path=entry["artifact_path"],
                slug=entry.get("slug") or "untracked",
                status=status,
                measured_at=entry.get("measured_at") or "unknown",
                age=entry.get("age") or format_age_days(entry.get("age_days")),
                artifact_size=entry.get("artifact_size") or format_bytes(entry.get("artifact_size_bytes")),
                current_suffix=current_suffix,
                detail_suffix=detail_suffix,
            )
        )
    if total_count > summary["count"]:
        suffix = ""
        if total_size_bytes is not None:
            omitted_size_bytes = max(total_size_bytes - summary["total_size_bytes"], 0)
            suffix = f" ({format_bytes(omitted_size_bytes)}, {omitted_size_bytes} bytes)"
        omitted_count = total_count - summary["count"]
        omitted_noun = "artifact" if omitted_count == 1 else "artifacts"
        lines.append(f"... {omitted_count} more stale {omitted_noun}{suffix} omitted by --limit.")
    return "\n".join(lines)


def render_paths(
    stale: list[dict[str, Any]],
    *,
    include_detail_pages: bool = False,
    detail_pages_only: bool = False,
    existing_root: Path | None = None,
    missing_root: Path | None = None,
    path_prefix: Path | None = None,
    output_root: Path | None = None,
    separator: str = "\n",
) -> str:
    paths = []

    def append_path_once(path: str) -> None:
        if path_prefix is not None:
            path = str(path_prefix / path)
        if output_root is not None:
            path = str((output_root / path).resolve())
        if path not in paths:
            paths.append(path)

    for entry in stale:
        if not detail_pages_only:
            artifact_path = entry["artifact_path"]
            if existing_root is None or (existing_root / artifact_path).exists():
                if missing_root is None or not (missing_root / artifact_path).exists():
                    append_path_once(artifact_path)
        detail_path = entry.get("detail_page_path")
        if (include_detail_pages or detail_pages_only) and detail_path:
            if existing_root is not None and not (existing_root / detail_path).exists():
                continue
            if missing_root is not None and (missing_root / detail_path).exists():
                continue
            append_path_once(detail_path)
    return separator.join(paths)


def render_json_lines(stale: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(entry, sort_keys=True) for entry in stale)


def render_json_summary(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
    include_share: bool = False,
) -> str:
    summary_sort = normalize_summary_sort(summary_sort)
    validate_summary_options(
        summary_limit=summary_limit,
        summary_sort=summary_sort,
        summary_min_count=summary_min_count,
        summary_max_count=summary_max_count,
        summary_min_size_bytes=summary_min_size_bytes,
        summary_max_size_bytes=summary_max_size_bytes,
    )
    allowed_groups = set(SUMMARY_GROUPS)
    selected_groups = normalize_summary_groups(groups)
    unknown_groups = sorted(selected_groups - allowed_groups)
    if unknown_groups:
        raise ValueError(f"summary groups must be one of: {', '.join(SUMMARY_GROUPS)}")

    summary = stale_summary(stale)
    rendered: dict[str, Any] = {
        "count": summary["count"],
        "total_size_bytes": summary["total_size_bytes"],
        "total_size": summary["total_size"],
    }
    for group in SUMMARY_GROUPS:
        if group not in selected_groups:
            continue
        summary_key = SUMMARY_GROUP_KEYS[group]
        filtered_buckets = limit_summary_buckets(
            summary[summary_key],
            None,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        buckets = filtered_buckets if summary_limit is None else filtered_buckets[:summary_limit]
        if is_average_summary_sort(summary_sort):
            buckets = with_summary_average_sizes(buckets)
        if include_share:
            buckets = with_summary_shares(
                buckets,
                total_count=summary["count"],
                total_size_bytes=summary["total_size_bytes"],
            )
        rendered[summary_key] = buckets
        if summary_limit is not None and len(filtered_buckets) > len(buckets):
            omitted_buckets = filtered_buckets[len(buckets) :]
            omitted_size_bytes = sum(bucket["total_size_bytes"] for bucket in omitted_buckets)
            rendered[f"{summary_key}_omitted"] = {
                "count": len(omitted_buckets),
                "total_size_bytes": omitted_size_bytes,
                "total_size": format_bytes(omitted_size_bytes),
            }
    return json.dumps(rendered, indent=2)


def render_summary_csv(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
    include_share: bool = False,
) -> str:
    summary_sort = normalize_summary_sort(summary_sort)
    validate_summary_options(
        summary_limit=summary_limit,
        summary_sort=summary_sort,
        summary_min_count=summary_min_count,
        summary_max_count=summary_max_count,
        summary_min_size_bytes=summary_min_size_bytes,
        summary_max_size_bytes=summary_max_size_bytes,
    )
    selected_groups = normalize_summary_groups(groups)
    summary = stale_summary(stale)
    output = io.StringIO()
    fieldnames = [
        "group",
        "bucket",
        "count",
        "total_size_bytes",
        "total_size",
    ]
    if is_average_summary_sort(summary_sort):
        fieldnames.extend(["average_size_bytes", "average_size"])
    fieldnames.extend(["count_share_percent", "size_share_percent"])
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for group in SUMMARY_GROUPS:
        if group not in selected_groups:
            continue
        summary_key = SUMMARY_GROUP_KEYS[group]
        bucket_key = summary_key.removeprefix("by_")
        buckets = limit_summary_buckets(
            summary[summary_key],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        if is_average_summary_sort(summary_sort):
            buckets = with_summary_average_sizes(buckets)
        if include_share:
            buckets = with_summary_shares(
                buckets,
                total_count=summary["count"],
                total_size_bytes=summary["total_size_bytes"],
            )
        for bucket in buckets:
            row = {
                "group": group,
                "bucket": bucket.get(bucket_key),
                "count": bucket["count"],
                "total_size_bytes": bucket["total_size_bytes"],
                "total_size": bucket["total_size"],
                "count_share_percent": bucket.get("count_share_percent", ""),
                "size_share_percent": bucket.get("size_share_percent", ""),
            }
            if is_average_summary_sort(summary_sort):
                row["average_size_bytes"] = bucket.get("average_size_bytes", "")
                row["average_size"] = bucket.get("average_size", "")
            writer.writerow(row)
    return output.getvalue()


def render_summary_markdown(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
    include_share: bool = False,
) -> str:
    summary_sort = normalize_summary_sort(summary_sort)
    validate_summary_options(
        summary_limit=summary_limit,
        summary_sort=summary_sort,
        summary_min_count=summary_min_count,
        summary_max_count=summary_max_count,
        summary_min_size_bytes=summary_min_size_bytes,
        summary_max_size_bytes=summary_max_size_bytes,
    )
    selected_groups = normalize_summary_groups(groups)
    summary = stale_summary(stale)
    include_average_size = is_average_summary_sort(summary_sort)
    header = "| Group | Bucket | Count | Total size |"
    divider = "| --- | --- | ---: | ---: |"
    if include_average_size:
        header += " Average size |"
        divider += " ---: |"
    header += " Count share | Size share |"
    divider += " ---: | ---: |"
    lines = [
        "Found {count} stale benchmark {noun} ({size}, {bytes} bytes).".format(
            count=summary["count"],
            noun="artifact" if summary["count"] == 1 else "artifacts",
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        ),
        "",
        header,
        divider,
    ]
    for group in SUMMARY_GROUPS:
        if group not in selected_groups:
            continue
        summary_key = SUMMARY_GROUP_KEYS[group]
        bucket_key = summary_key.removeprefix("by_")
        buckets = limit_summary_buckets(
            summary[summary_key],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        if include_average_size:
            buckets = with_summary_average_sizes(buckets)
        if include_share:
            buckets = with_summary_shares(
                buckets,
                total_count=summary["count"],
                total_size_bytes=summary["total_size_bytes"],
            )
        for bucket in buckets:
            average_size_cell = ""
            if include_average_size:
                average_size_cell = f" {markdown_cell(bucket.get('average_size', ''))} |"
            lines.append(
                (
                    "| {group} | {bucket} | {count} | {total_size} |"
                    "{average_size_cell} {count_share} | {size_share} |"
                ).format(
                    group=markdown_cell(group),
                    bucket=markdown_cell(bucket.get(bucket_key)),
                    count=bucket["count"],
                    total_size=markdown_cell(bucket["total_size"]),
                    average_size_cell=average_size_cell,
                    count_share=markdown_cell(bucket.get("count_share_percent", "")),
                    size_share=markdown_cell(bucket.get("size_share_percent", "")),
                )
            )
    return "\n".join(lines)


def is_average_summary_sort(sort_by: str) -> bool:
    return normalize_summary_sort(sort_by) in {
        "average-size",
        "average-size-desc",
        "average",
        "average-desc",
        "average-bytes",
        "average-bytes-desc",
        "avg-size",
        "avg-size-desc",
        "avg",
        "avg-desc",
        "avg-bytes",
        "avg-bytes-desc",
        "mean-size",
        "mean-size-desc",
        "mean",
        "mean-desc",
        "mean-bytes",
        "mean-bytes-desc",
        "average-size-asc",
        "average-asc",
        "average-bytes-asc",
        "avg-size-asc",
        "avg-asc",
        "avg-bytes-asc",
        "mean-size-asc",
        "mean-asc",
        "mean-bytes-asc",
    }


def with_summary_average_sizes(buckets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    averaged_buckets = []
    for bucket in buckets:
        averaged_bucket = dict(bucket)
        average_size_bytes = bucket["total_size_bytes"] / bucket["count"] if bucket["count"] else 0
        averaged_bucket["average_size_bytes"] = average_size_bytes
        averaged_bucket["average_size"] = format_average_bytes(average_size_bytes)
        averaged_buckets.append(averaged_bucket)
    return averaged_buckets


def with_summary_shares(
    buckets: list[dict[str, Any]],
    *,
    total_count: int,
    total_size_bytes: int,
) -> list[dict[str, Any]]:
    shared_buckets = []
    for bucket in buckets:
        shared_bucket = dict(bucket)
        shared_bucket["count_share_percent"] = (
            round((bucket["count"] / total_count) * 100, 1) if total_count else 0.0
        )
        shared_bucket["size_share_percent"] = (
            round((bucket["total_size_bytes"] / total_size_bytes) * 100, 1)
            if total_size_bytes
            else 0.0
        )
        shared_buckets.append(shared_bucket)
    return shared_buckets


def render_csv(stale: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "artifact_path",
        "artifact_name",
        "artifact_stem",
        "artifact_dir",
        "artifact_extension",
        "slug",
        "label",
        "backend",
        "model",
        "status",
        "measured_at",
        "measured_year",
        "measured_quarter",
        "measured_month",
        "measured_week",
        "measured_day",
        "age_days",
        "age_bucket",
        "age",
        "current_artifact_path",
        "current_artifact_name",
        "current_artifact_stem",
        "current_artifact_dir",
        "current_artifact_extension",
        "track_state",
        "detail_page_path",
        "detail_page_name",
        "detail_page_stem",
        "detail_page_dir",
        "detail_page_extension",
        "artifact_size_bytes",
        "artifact_size",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for entry in stale:
        row = {
            **entry,
            "artifact_name": entry.get("artifact_name") or Path(entry.get("artifact_path") or "").name,
            "artifact_stem": entry.get("artifact_stem") or Path(entry.get("artifact_path") or "").stem,
            "artifact_dir": entry.get("artifact_dir") or str(Path(entry.get("artifact_path") or "").parent),
            "measured_year": entry.get("measured_year") or measured_year(entry.get("measured_at")),
            "measured_quarter": entry.get("measured_quarter") or measured_quarter(entry.get("measured_at")),
            "measured_month": entry.get("measured_month") or measured_month(entry.get("measured_at")),
            "measured_week": entry.get("measured_week") or measured_week(entry.get("measured_at")),
            "measured_day": entry.get("measured_day") or measured_day(entry.get("measured_at")),
            "current_artifact_name": entry.get("current_artifact_name")
            or Path(entry.get("current_artifact_path") or "").name,
            "current_artifact_stem": entry.get("current_artifact_stem")
            or Path(entry.get("current_artifact_path") or "").stem,
            "current_artifact_dir": entry.get("current_artifact_dir")
            or (str(Path(entry.get("current_artifact_path")).parent) if entry.get("current_artifact_path") else ""),
            "current_artifact_extension": entry.get("current_artifact_extension")
            or Path(entry.get("current_artifact_path") or "").suffix.lower()
            or "none",
            "detail_page_name": entry.get("detail_page_name")
            or Path(entry.get("detail_page_path") or "").name,
            "detail_page_stem": entry.get("detail_page_stem")
            or Path(entry.get("detail_page_path") or "").stem,
            "detail_page_dir": entry.get("detail_page_dir")
            or (str(Path(entry.get("detail_page_path")).parent) if entry.get("detail_page_path") else ""),
            "detail_page_extension": entry.get("detail_page_extension")
            or Path(entry.get("detail_page_path") or "").suffix.lower()
            or "none",
        }
        writer.writerow(row)
    return output.getvalue()


def markdown_cell(value: Any) -> str:
    text = "unknown" if value is None or value == "" else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(
    stale: list[dict[str, Any]],
    *,
    total_count: int | None = None,
    total_size_bytes: int | None = None,
) -> str:
    if not stale:
        if total_count:
            return (
                f"Found {total_count} stale benchmark artifacts, but 0 are shown "
                "because --limit omitted all matches."
            )
        return "No stale benchmark artifacts found."

    summary = stale_summary(stale)
    total_count = total_count if total_count is not None else summary["count"]
    lines = [
        "Found {count} stale benchmark {noun} ({size}, {bytes} bytes).".format(
            count=summary["count"],
            noun="artifact" if summary["count"] == 1 else "artifacts",
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        ),
        "",
        "| Artifact | Status | Age | Size | Current artifact | Detail page |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for entry in stale:
        lines.append(
            "| {artifact_path} | {status} | {age} | {size} | {current} | {detail} |".format(
                artifact_path=markdown_cell(entry.get("artifact_path")),
                status=markdown_cell(entry.get("status")),
                age=markdown_cell(entry.get("age") or format_age_days(entry.get("age_days"))),
                size=markdown_cell(entry.get("artifact_size") or format_bytes(entry.get("artifact_size_bytes"))),
                current=markdown_cell(entry.get("current_artifact_path") or "untracked"),
                detail=markdown_cell(entry.get("detail_page_path") or "none"),
            )
        )
    if total_count > summary["count"]:
        suffix = ""
        if total_size_bytes is not None:
            omitted_size_bytes = max(total_size_bytes - summary["total_size_bytes"], 0)
            suffix = f" ({format_bytes(omitted_size_bytes)}, {omitted_size_bytes} bytes)"
        omitted_count = total_count - summary["count"]
        omitted_noun = "artifact" if omitted_count == 1 else "artifacts"
        lines.append("")
        lines.append(f"... {omitted_count} more stale {omitted_noun}{suffix} omitted by --limit.")
    return "\n".join(lines)


def limit_summary_buckets(
    buckets: list[dict[str, Any]],
    limit: int | None,
    *,
    sort_by: str = "size",
    min_count: int | None = None,
    max_count: int | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
) -> list[dict[str, Any]]:
    sort_by = normalize_summary_sort(sort_by)
    validate_summary_options(
        summary_limit=limit,
        summary_sort=sort_by,
        summary_min_count=min_count,
        summary_max_count=max_count,
        summary_min_size_bytes=min_size_bytes,
        summary_max_size_bytes=max_size_bytes,
    )
    filtered_buckets = buckets
    if min_count is not None:
        filtered_buckets = [bucket for bucket in filtered_buckets if bucket["count"] >= min_count]
    if max_count is not None:
        filtered_buckets = [bucket for bucket in filtered_buckets if bucket["count"] <= max_count]
    if min_size_bytes is not None:
        filtered_buckets = [
            bucket for bucket in filtered_buckets if bucket["total_size_bytes"] >= min_size_bytes
        ]
    if max_size_bytes is not None:
        filtered_buckets = [
            bucket for bucket in filtered_buckets if bucket["total_size_bytes"] <= max_size_bytes
        ]
    if sort_by != "size":
        filtered_buckets = sorted(filtered_buckets, key=lambda bucket: summary_bucket_sort_key(bucket, sort_by))
    if limit is None:
        return filtered_buckets
    return filtered_buckets[:limit]


def summary_bucket_sort_key(bucket: dict[str, Any], sort_by: str) -> tuple[Any, ...]:
    bucket_key = next(
        (
            key
            for key in bucket
            if key not in {"count", "total_size_bytes", "total_size", "average_size_bytes", "average_size"}
        ),
        "",
    )
    name = str(bucket.get(bucket_key, ""))
    average_size = bucket["total_size_bytes"] / bucket["count"] if bucket["count"] else 0
    if bucket_key == "age_bucket" and sort_by == "age-bucket-asc":
        return (AGE_BUCKET_ORDER.get(name, sys.maxsize), name)
    if bucket_key == "age_bucket" and sort_by == "age-bucket-desc":
        known_order = AGE_BUCKET_ORDER.get(name)
        return (-known_order if known_order is not None else sys.maxsize, name)
    if sort_by == "age-bucket-asc":
        return (name,)
    if sort_by == "age-bucket-desc":
        return (*(-ord(character) for character in name), -len(name))
    if sort_by in {
        "measured-year",
        "measured-year-asc",
        "measured-quarter",
        "measured-quarter-asc",
        "measured-month",
        "measured-month-asc",
        "measured-week",
        "measured-week-asc",
        "measured-day",
        "measured-day-asc",
    }:
        return (name,)
    if sort_by in {
        "measured-year-desc",
        "measured-quarter-desc",
        "measured-month-desc",
        "measured-week-desc",
        "measured-day-desc",
    }:
        return (*(-ord(character) for character in name), -len(name))
    if bucket_key == "age_bucket" and sort_by in {"name", "name-asc"}:
        return (AGE_BUCKET_ORDER.get(name, sys.maxsize), name)
    if bucket_key == "age_bucket" and sort_by == "name-desc":
        return (-AGE_BUCKET_ORDER.get(name, sys.maxsize), name)
    if sort_by in {
        "average-size",
        "average-size-desc",
        "average",
        "average-desc",
        "average-bytes",
        "average-bytes-desc",
        "avg-size",
        "avg-size-desc",
        "avg",
        "avg-desc",
        "avg-bytes",
        "avg-bytes-desc",
        "mean-size",
        "mean-size-desc",
        "mean",
        "mean-desc",
        "mean-bytes",
        "mean-bytes-desc",
    }:
        return (-average_size, -bucket["total_size_bytes"], name)
    if sort_by in {
        "average-size-asc",
        "average-asc",
        "average-bytes-asc",
        "avg-size-asc",
        "avg-asc",
        "avg-bytes-asc",
        "mean-size-asc",
        "mean-asc",
        "mean-bytes-asc",
    }:
        return (average_size, bucket["total_size_bytes"], name)
    if sort_by in {"count", "count-desc"}:
        return (-bucket["count"], -bucket["total_size_bytes"], name)
    if sort_by == "count-asc":
        return (bucket["count"], bucket["total_size_bytes"], name)
    if sort_by == "name-desc":
        return (*(-ord(character) for character in name), -len(name))
    if sort_by in {"name", "name-asc"}:
        return (name,)
    if sort_by in {
        "size-asc",
        "bytes-asc",
        "disk-size-asc",
        "total-size-asc",
        "total-bytes-asc",
        "smallest",
    }:
        return (bucket["total_size_bytes"], name)
    return (-bucket["total_size_bytes"], name)


def append_omitted_summary_buckets(
    lines: list[str],
    buckets: list[dict[str, Any]],
    shown_buckets: list[dict[str, Any]],
    *,
    limit: int | None,
    sort_by: str = "size",
    min_count: int | None = None,
    max_count: int | None = None,
    min_size_bytes: int | None = None,
    max_size_bytes: int | None = None,
) -> None:
    buckets = limit_summary_buckets(
        buckets,
        None,
        sort_by=sort_by,
        min_count=min_count,
        max_count=max_count,
        min_size_bytes=min_size_bytes,
        max_size_bytes=max_size_bytes,
    )
    if limit is None or len(buckets) <= len(shown_buckets):
        return
    omitted_count = len(buckets) - len(shown_buckets)
    omitted_size_bytes = sum(bucket["total_size_bytes"] for bucket in buckets[len(shown_buckets) :])
    noun = "bucket" if omitted_count == 1 else "buckets"
    lines.append(
        "... {count} more {noun} ({size}, {bytes} bytes) omitted by --summary-limit.".format(
            count=omitted_count,
            noun=noun,
            size=format_bytes(omitted_size_bytes),
            bytes=omitted_size_bytes,
        )
    )


def render_summary(
    stale: list[dict[str, Any]],
    *,
    groups: list[str] | None = None,
    summary_limit: int | None = None,
    summary_sort: str = "size",
    summary_min_count: int | None = None,
    summary_max_count: int | None = None,
    summary_min_size_bytes: int | None = None,
    summary_max_size_bytes: int | None = None,
) -> str:
    summary_sort = normalize_summary_sort(summary_sort)
    validate_summary_options(
        summary_limit=summary_limit,
        summary_sort=summary_sort,
        summary_min_count=summary_min_count,
        summary_max_count=summary_max_count,
        summary_min_size_bytes=summary_min_size_bytes,
        summary_max_size_bytes=summary_max_size_bytes,
    )
    allowed_groups = set(SUMMARY_GROUPS)
    selected_groups = normalize_summary_groups(groups)
    unknown_groups = sorted(selected_groups - allowed_groups)
    if unknown_groups:
        raise ValueError(f"summary groups must be one of: {', '.join(SUMMARY_GROUPS)}")

    summary = stale_summary(stale)
    total_noun = "artifact" if summary["count"] == 1 else "artifacts"
    lines = [
        "Found {count} stale benchmark {total_noun} ({size}, {bytes} bytes).".format(
            count=summary["count"],
            total_noun=total_noun,
            size=summary["total_size"],
            bytes=summary["total_size_bytes"],
        )
    ]
    if "slug" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_slug"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {slug}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    slug=bucket["slug"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_slug"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-path" in selected_groups and summary["by_artifact_path"]:
        lines.append("By artifact path:")
    if "artifact-path" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_path"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_path}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_path=bucket["artifact_path"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_path"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-name" in selected_groups and summary["by_artifact_name"]:
        lines.append("By artifact name:")
    if "artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_name=bucket["artifact_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-stem" in selected_groups and summary["by_artifact_stem"]:
        lines.append("By artifact stem:")
    if "artifact-stem" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_stem"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_stem}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_stem=bucket["artifact_stem"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_stem"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-dir" in selected_groups and summary["by_artifact_dir"]:
        lines.append("By artifact directory:")
    if "artifact-dir" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_dir"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_dir}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_dir=bucket["artifact_dir"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_dir"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "artifact-extension" in selected_groups and summary["by_artifact_extension"]:
        lines.append("By artifact extension:")
    if "artifact-extension" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_artifact_extension"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {artifact_extension}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    artifact_extension=bucket["artifact_extension"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_artifact_extension"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "status" in selected_groups and summary["by_status"]:
        lines.append("By status:")
    if "status" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_status"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {status}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    status=bucket["status"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_status"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "backend" in selected_groups and summary["by_backend"]:
        lines.append("By backend:")
    if "backend" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_backend"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {backend}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    backend=bucket["backend"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_backend"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "model" in selected_groups and summary["by_model"]:
        lines.append("By model:")
    if "model" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_model"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {model}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    model=bucket["model"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_model"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "label" in selected_groups and any(bucket["label"] != "unknown" for bucket in summary["by_label"]):
        lines.append("By label:")
        shown_buckets = limit_summary_buckets(
            summary["by_label"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {label}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    label=bucket["label"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_label"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact" in selected_groups and summary["by_current_artifact_path"]:
        lines.append("By current artifact:")
    if "current-artifact" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_path"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_path}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_path=bucket["current_artifact_path"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_path"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-name" in selected_groups and summary["by_current_artifact_name"]:
        lines.append("By current artifact name:")
    if "current-artifact-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_name=bucket["current_artifact_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-stem" in selected_groups and summary["by_current_artifact_stem"]:
        lines.append("By current artifact stem:")
    if "current-artifact-stem" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_stem"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_stem}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_stem=bucket["current_artifact_stem"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_stem"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-dir" in selected_groups and summary["by_current_artifact_dir"]:
        lines.append("By current artifact directory:")
    if "current-artifact-dir" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_dir"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_dir}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_dir=bucket["current_artifact_dir"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_dir"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "current-artifact-extension" in selected_groups and summary["by_current_artifact_extension"]:
        lines.append("By current artifact extension:")
    if "current-artifact-extension" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_current_artifact_extension"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {current_artifact_extension}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    current_artifact_extension=bucket["current_artifact_extension"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_current_artifact_extension"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "track-state" in selected_groups and summary["by_track_state"]:
        lines.append("By track state:")
    if "track-state" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_track_state"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {track_state}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    track_state=bucket["track_state"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_track_state"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page" in selected_groups and summary["by_detail_page_path"]:
        lines.append("By detail page:")
    if "detail-page" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_path"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_path}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_path=bucket["detail_page_path"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_path"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page-name" in selected_groups and summary["by_detail_page_name"]:
        lines.append("By detail page name:")
    if "detail-page-name" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_name"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_name}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_name=bucket["detail_page_name"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_name"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page-stem" in selected_groups and summary["by_detail_page_stem"]:
        lines.append("By detail page stem:")
    if "detail-page-stem" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_stem"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_stem}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_stem=bucket["detail_page_stem"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_stem"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page-dir" in selected_groups and summary["by_detail_page_dir"]:
        lines.append("By detail page directory:")
    if "detail-page-dir" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_dir"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_dir}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_dir=bucket["detail_page_dir"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_dir"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "detail-page-extension" in selected_groups and summary["by_detail_page_extension"]:
        lines.append("By detail page extension:")
    if "detail-page-extension" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_detail_page_extension"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {detail_page_extension}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    detail_page_extension=bucket["detail_page_extension"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_detail_page_extension"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "measured-quarter" in selected_groups and summary["by_measured_quarter"]:
        lines.append("By measured quarter:")
    if "measured-quarter" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_measured_quarter"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {measured_quarter}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    measured_quarter=bucket["measured_quarter"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_measured_quarter"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "measured-month" in selected_groups and summary["by_measured_month"]:
        lines.append("By measured month:")
    if "measured-month" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_measured_month"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {measured_month}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    measured_month=bucket["measured_month"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_measured_month"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "measured-week" in selected_groups and summary["by_measured_week"]:
        lines.append("By measured week:")
    if "measured-week" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_measured_week"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {measured_week}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    measured_week=bucket["measured_week"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_measured_week"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    if "age-bucket" in selected_groups and summary["by_age_bucket"]:
        lines.append("By age bucket:")
    if "age-bucket" in selected_groups:
        shown_buckets = limit_summary_buckets(
            summary["by_age_bucket"],
            summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
        for bucket in shown_buckets:
            bucket_noun = "artifact" if bucket["count"] == 1 else "artifacts"
            lines.append(
                "- {age_bucket}: {count} {bucket_noun} ({size}, {bytes} bytes)".format(
                    age_bucket=bucket["age_bucket"],
                    count=bucket["count"],
                    bucket_noun=bucket_noun,
                    size=bucket["total_size"],
                    bytes=bucket["total_size_bytes"],
                )
            )
        append_omitted_summary_buckets(
            lines,
            summary["by_age_bucket"],
            shown_buckets,
            limit=summary_limit,
            sort_by=summary_sort,
            min_count=summary_min_count,
            max_count=summary_max_count,
            min_size_bytes=summary_min_size_bytes,
            max_size_bytes=summary_max_size_bytes,
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit is not None and args.limit < 0:
        raise ValueError("limit must be non-negative")
    if args.json and args.paths_only:
        raise ValueError("--json and --paths-only cannot be used together")
    if args.json_summary and args.json:
        raise ValueError("--json-summary and --json cannot be used together")
    if args.summary_csv and args.json:
        raise ValueError("--summary-csv and --json cannot be used together")
    if args.summary_csv and args.json_summary:
        raise ValueError("--summary-csv and --json-summary cannot be used together")
    if args.summary_markdown and args.json_summary:
        raise ValueError("--summary-markdown and --json-summary cannot be used together")
    if args.summary_markdown and args.summary_csv:
        raise ValueError("--summary-markdown and --summary-csv cannot be used together")
    if args.summary_markdown and args.json:
        raise ValueError("--summary-markdown and --json cannot be used together")
    if args.json_summary and args.paths_only:
        raise ValueError("--json-summary and --paths-only cannot be used together")
    if args.summary_csv and args.paths_only:
        raise ValueError("--summary-csv and --paths-only cannot be used together")
    if args.summary_markdown and args.paths_only:
        raise ValueError("--summary-markdown and --paths-only cannot be used together")
    if args.json_lines and args.json:
        raise ValueError("--json-lines and --json cannot be used together")
    if args.json_lines and args.json_summary:
        raise ValueError("--json-lines and --json-summary cannot be used together")
    if args.json_lines and args.summary_csv:
        raise ValueError("--json-lines and --summary-csv cannot be used together")
    if args.json_lines and args.summary_markdown:
        raise ValueError("--json-lines and --summary-markdown cannot be used together")
    if args.json_lines and args.paths_only:
        raise ValueError("--json-lines and --paths-only cannot be used together")
    if args.csv and args.json:
        raise ValueError("--csv and --json cannot be used together")
    if args.csv and args.json_summary:
        raise ValueError("--csv and --json-summary cannot be used together")
    if args.csv and args.summary_csv:
        raise ValueError("--csv and --summary-csv cannot be used together")
    if args.csv and args.summary_markdown:
        raise ValueError("--csv and --summary-markdown cannot be used together")
    if args.csv and args.json_lines:
        raise ValueError("--csv and --json-lines cannot be used together")
    if args.csv and args.paths_only:
        raise ValueError("--csv and --paths-only cannot be used together")
    if args.count_only and args.json:
        raise ValueError("--count-only and --json cannot be used together")
    if args.count_only and args.json_summary:
        raise ValueError("--count-only and --json-summary cannot be used together")
    if args.count_only and args.summary_csv:
        raise ValueError("--count-only and --summary-csv cannot be used together")
    if args.count_only and args.summary_markdown:
        raise ValueError("--count-only and --summary-markdown cannot be used together")
    if args.count_only and args.json_lines:
        raise ValueError("--count-only and --json-lines cannot be used together")
    if args.count_only and args.csv:
        raise ValueError("--count-only and --csv cannot be used together")
    if args.count_only and args.paths_only:
        raise ValueError("--count-only and --paths-only cannot be used together")
    if args.total_bytes_only and args.json:
        raise ValueError("--total-bytes-only and --json cannot be used together")
    if args.total_bytes_only and args.json_summary:
        raise ValueError("--total-bytes-only and --json-summary cannot be used together")
    if args.total_bytes_only and args.summary_csv:
        raise ValueError("--total-bytes-only and --summary-csv cannot be used together")
    if args.total_bytes_only and args.summary_markdown:
        raise ValueError("--total-bytes-only and --summary-markdown cannot be used together")
    if args.total_bytes_only and args.json_lines:
        raise ValueError("--total-bytes-only and --json-lines cannot be used together")
    if args.total_bytes_only and args.csv:
        raise ValueError("--total-bytes-only and --csv cannot be used together")
    if args.total_bytes_only and args.paths_only:
        raise ValueError("--total-bytes-only and --paths-only cannot be used together")
    if args.total_bytes_only and args.count_only:
        raise ValueError("--total-bytes-only and --count-only cannot be used together")
    if args.summary_only and args.json:
        raise ValueError("--summary-only and --json cannot be used together")
    if args.summary_only and args.json_summary:
        raise ValueError("--summary-only and --json-summary cannot be used together")
    if args.summary_only and args.summary_csv:
        raise ValueError("--summary-only and --summary-csv cannot be used together")
    if args.summary_only and args.summary_markdown:
        raise ValueError("--summary-only and --summary-markdown cannot be used together")
    if args.summary_only and args.json_lines:
        raise ValueError("--summary-only and --json-lines cannot be used together")
    if args.summary_only and args.csv:
        raise ValueError("--summary-only and --csv cannot be used together")
    if args.summary_only and args.paths_only:
        raise ValueError("--summary-only and --paths-only cannot be used together")
    if args.summary_only and args.count_only:
        raise ValueError("--summary-only and --count-only cannot be used together")
    if args.summary_only and args.total_bytes_only:
        raise ValueError("--summary-only and --total-bytes-only cannot be used together")
    if args.markdown and args.json:
        raise ValueError("--markdown and --json cannot be used together")
    if args.markdown and args.json_summary:
        raise ValueError("--markdown and --json-summary cannot be used together")
    if args.markdown and args.summary_csv:
        raise ValueError("--markdown and --summary-csv cannot be used together")
    if args.markdown and args.summary_markdown:
        raise ValueError("--markdown and --summary-markdown cannot be used together")
    if args.markdown and args.json_lines:
        raise ValueError("--markdown and --json-lines cannot be used together")
    if args.markdown and args.csv:
        raise ValueError("--markdown and --csv cannot be used together")
    if args.markdown and args.paths_only:
        raise ValueError("--markdown and --paths-only cannot be used together")
    if args.markdown and args.count_only:
        raise ValueError("--markdown and --count-only cannot be used together")
    if args.markdown and args.total_bytes_only:
        raise ValueError("--markdown and --total-bytes-only cannot be used together")
    if args.markdown and args.summary_only:
        raise ValueError("--markdown and --summary-only cannot be used together")
    summary_output_requested = args.summary_only or args.json_summary or args.summary_csv or args.summary_markdown
    if args.summary_group and not summary_output_requested:
        raise ValueError(f"--summary-group requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_limit is not None and not summary_output_requested:
        raise ValueError(f"--summary-limit requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_min_count is not None and not summary_output_requested:
        raise ValueError(f"--summary-min-count requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_max_count is not None and not summary_output_requested:
        raise ValueError(f"--summary-max-count requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_min_size_bytes is not None and not summary_output_requested:
        raise ValueError(f"--summary-min-size-bytes requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_max_size_bytes is not None and not summary_output_requested:
        raise ValueError(f"--summary-max-size-bytes requires {SUMMARY_OUTPUT_REQUIREMENT}")
    if args.summary_share and not (args.json_summary or args.summary_csv or args.summary_markdown):
        raise ValueError("--summary-share requires --json-summary, --summary-csv, or --summary-markdown")
    if args.include_detail_pages and not args.paths_only:
        raise ValueError("--include-detail-pages requires --paths-only")
    if args.detail_pages_only and not args.paths_only:
        raise ValueError("--detail-pages-only requires --paths-only")
    if args.absolute_paths and not args.paths_only:
        raise ValueError("--absolute-paths requires --paths-only")
    if args.repo_relative_paths and not args.paths_only:
        raise ValueError("--repo-relative-paths requires --paths-only")
    if args.absolute_paths and args.repo_relative_paths:
        raise ValueError("--absolute-paths cannot be combined with --repo-relative-paths")
    if args.null and not args.paths_only:
        raise ValueError("--null requires --paths-only")
    if args.existing_paths_only and not args.paths_only:
        raise ValueError("--existing-paths-only requires --paths-only")
    if args.missing_paths_only and not args.paths_only:
        raise ValueError("--missing-paths-only requires --paths-only")
    if args.existing_paths_only and args.missing_paths_only:
        raise ValueError("--existing-paths-only cannot be combined with --missing-paths-only")
    if args.detail_pages_only and args.include_detail_pages:
        raise ValueError("--detail-pages-only cannot be combined with --include-detail-pages")
    if args.quiet and args.output:
        raise ValueError("--quiet cannot be combined with --output")

    if args.manifest is None:
        manifest = build_manifest(args.results_dir, args.tracks)
    else:
        manifest = load_manifest_from_path(args.manifest)
    stale = stale_artifacts(
        manifest,
        older_than_days=args.older_than_days,
        newer_than_days=args.newer_than_days,
        measured_before=args.measured_before,
        measured_after=args.measured_after,
        min_size_bytes=args.min_size_bytes,
        max_size_bytes=args.max_size_bytes,
        slugs=args.slug,
        slug_contains=args.slug_contains,
        labels=args.label,
        backends=args.backend,
        models=args.model,
        measured_years=args.measured_year,
        measured_quarters=args.measured_quarter,
        measured_months=args.measured_month,
        measured_weeks=args.measured_week,
        measured_days=args.measured_day,
        age_buckets=args.age_bucket,
        current_paths=args.current_path,
        current_path_contains=args.current_path_contains,
        current_path_names=args.current_path_name,
        current_path_name_contains=args.current_path_name_contains,
        current_path_stems=args.current_path_stem,
        current_path_stem_contains=args.current_path_stem_contains,
        current_path_dirs=args.current_path_dir,
        current_path_dir_contains=args.current_path_dir_contains,
        current_path_extensions=args.current_path_extension,
        current_path_extension_contains=args.current_path_extension_contains,
        track_state=args.track_state,
        artifact_paths=args.artifact_path,
        artifact_path_contains=args.artifact_path_contains,
        artifact_dirs=args.artifact_dir,
        artifact_dir_contains=args.artifact_dir_contains,
        artifact_names=args.artifact_name,
        artifact_name_contains=args.artifact_name_contains,
        artifact_stems=args.artifact_stem,
        artifact_stem_contains=args.artifact_stem_contains,
        artifact_extensions=args.artifact_extension,
        artifact_extension_contains=args.artifact_extension_contains,
        detail_pages=args.detail_page,
        detail_page_contains=args.detail_page_contains,
        detail_page_names=args.detail_page_name,
        detail_page_name_contains=args.detail_page_name_contains,
        detail_page_stems=args.detail_page_stem,
        detail_page_stem_contains=args.detail_page_stem_contains,
        detail_page_dirs=args.detail_page_dir,
        detail_page_dir_contains=args.detail_page_dir_contains,
        detail_page_extensions=args.detail_page_extension,
        detail_page_extension_contains=args.detail_page_extension_contains,
        statuses=args.status,
        status_contains=args.status_contains,
        sort_by=args.sort,
    )
    limited_stale = limit_artifacts(stale, args.limit)
    if args.count_only:
        rendered_output = f"{len(stale)}\n"
    elif args.total_bytes_only:
        rendered_output = f"{stale_summary(stale)['total_size_bytes']}\n"
    elif args.summary_only:
        rendered_output = (
            render_summary(
                stale,
                groups=args.summary_group,
                summary_limit=args.summary_limit,
                summary_sort=args.summary_sort,
                summary_min_count=args.summary_min_count,
                summary_max_count=args.summary_max_count,
                summary_min_size_bytes=args.summary_min_size_bytes,
                summary_max_size_bytes=args.summary_max_size_bytes,
            )
            + "\n"
        )
    elif args.json_summary:
        rendered_output = (
            render_json_summary(
                stale,
                groups=args.summary_group,
                summary_limit=args.summary_limit,
                summary_sort=args.summary_sort,
                summary_min_count=args.summary_min_count,
                summary_max_count=args.summary_max_count,
                summary_min_size_bytes=args.summary_min_size_bytes,
                summary_max_size_bytes=args.summary_max_size_bytes,
                include_share=args.summary_share,
            )
            + "\n"
        )
    elif args.summary_csv:
        rendered_output = render_summary_csv(
            stale,
            groups=args.summary_group,
            summary_limit=args.summary_limit,
            summary_sort=args.summary_sort,
            summary_min_count=args.summary_min_count,
            summary_max_count=args.summary_max_count,
            summary_min_size_bytes=args.summary_min_size_bytes,
            summary_max_size_bytes=args.summary_max_size_bytes,
            include_share=args.summary_share,
        )
    elif args.summary_markdown:
        rendered_output = (
            render_summary_markdown(
                stale,
                groups=args.summary_group,
                summary_limit=args.summary_limit,
                summary_sort=args.summary_sort,
                summary_min_count=args.summary_min_count,
                summary_max_count=args.summary_max_count,
                summary_min_size_bytes=args.summary_min_size_bytes,
                summary_max_size_bytes=args.summary_max_size_bytes,
                include_share=args.summary_share,
            )
            + "\n"
        )
    elif args.paths_only:
        rendered_paths = render_paths(
            limited_stale,
            include_detail_pages=args.include_detail_pages,
            detail_pages_only=args.detail_pages_only,
            existing_root=args.results_dir.parent if args.existing_paths_only else None,
            missing_root=args.results_dir.parent if args.missing_paths_only else None,
            path_prefix=args.results_dir.parent if args.repo_relative_paths else None,
            output_root=args.results_dir.parent if args.absolute_paths else None,
            separator="\0" if args.null else "\n",
        )
        if args.null:
            rendered_output = rendered_paths
        elif rendered_paths:
            rendered_output = f"{rendered_paths}\n"
        else:
            rendered_output = ""
    elif args.json:
        summary = stale_summary(limited_stale)
        summary["total_matching_count"] = len(stale)
        matching_summary = stale_summary(stale)
        summary["total_matching_size_bytes"] = matching_summary["total_size_bytes"]
        summary["total_matching_size"] = matching_summary["total_size"]
        rendered_output = f"{json.dumps(summary, indent=2)}\n"
    elif args.json_lines:
        rendered_output = f"{render_json_lines(limited_stale)}\n"
    elif args.csv:
        rendered_output = render_csv(limited_stale)
    elif args.markdown:
        matching_summary = stale_summary(stale)
        rendered_output = (
            render_markdown(
                limited_stale,
                total_count=len(stale),
                total_size_bytes=matching_summary["total_size_bytes"],
            )
            + "\n"
        )
    else:
        matching_summary = stale_summary(stale)
        rendered_output = (
            render_text(
                limited_stale,
                total_count=len(stale),
                total_size_bytes=matching_summary["total_size_bytes"],
            )
            + "\n"
        )
    if args.quiet:
        pass
    elif args.output and str(args.output) != "-":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered_output, encoding="utf-8")
    else:
        sys.stdout.write(rendered_output)
    return 1 if args.fail_on_stale and stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
