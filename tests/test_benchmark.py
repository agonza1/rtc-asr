from __future__ import annotations

import argparse
from pathlib import Path
import sys

from tests.benchmark import compute_accuracy_metrics, normalize_text, resolve_reference_text, summarize_latencies


def test_normalize_text_strips_case_and_punctuation() -> None:
    assert normalize_text("Hello,   WORLD!") == "hello world"


def test_compute_accuracy_metrics_reports_word_and_character_error_rate() -> None:
    metrics = compute_accuracy_metrics("the quick brown fox", "the quick fox")

    assert metrics is not None
    assert metrics["word_error_rate"] == 0.25
    assert metrics["character_error_rate"] > 0
    assert metrics["exact_match"] is False


def test_resolve_reference_text_prefers_explicit_inputs(tmp_path: Path) -> None:
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("from file", encoding="utf-8")

    args = argparse.Namespace(reference_text="from text", reference_file=reference_file, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "from text"

    args = argparse.Namespace(reference_text=None, reference_file=reference_file, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "from file"

    args = argparse.Namespace(reference_text=None, reference_file=None, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "fallback"
    assert resolve_reference_text(args, synthesized=False) is None


def test_summarize_latencies_reports_mean_and_p90() -> None:
    summary = summarize_latencies([10.0, 20.0, 30.0], duration_s=2.0)

    assert summary["mean_ms"] == 20.0
    assert summary["p90_ms"] == 30.0
    assert summary["p95_ms"] == 30.0
    assert summary["min_ms"] == 10.0
    assert summary["max_ms"] == 30.0
    assert summary["rtf_mean"] == 0.01


def test_parse_args_accepts_ultravox_options(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark.py",
            "--backend",
            "ultravox",
            "--ultravox-dtype",
            "float32",
            "--ultravox-max-new-tokens",
            "96",
        ],
    )

    from tests.benchmark import parse_args

    args = parse_args()

    assert args.backend == "ultravox"
    assert args.ultravox_dtype == "float32"
    assert args.ultravox_max_new_tokens == 96
