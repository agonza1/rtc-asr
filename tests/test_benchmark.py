from __future__ import annotations

import argparse
from pathlib import Path

from tests.benchmark import compute_accuracy_metrics, normalize_text, resolve_reference_text


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
