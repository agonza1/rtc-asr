import json
from pathlib import Path

from scripts.build_benchmark_manifest import build_manifest


def test_manifest_keeps_latest_artifact_per_benchmark() -> None:
    manifest = build_manifest(Path("docs") / "benchmark-results")

    assert manifest["summary"]["asr_count"] == 5
    assert manifest["summary"]["experiment_count"] == 1
    assert all(entry["backend"] != "ultravox" for entry in manifest["asr_benchmarks"])

    qwen_entries = [entry for entry in manifest["asr_benchmarks"] if entry["backend"] == "qwen-asr"]
    assert len(qwen_entries) == 1
    assert qwen_entries[0]["artifact_path"].endswith("qwen-compose-2026-06-08.json")


def test_checked_in_manifest_matches_generated_output() -> None:
    manifest_path = Path("docs") / "benchmark-results" / "manifest.json"
    checked_in = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated = build_manifest(Path("docs") / "benchmark-results")

    assert checked_in["summary"] == generated["summary"]
    assert checked_in["asr_benchmarks"] == generated["asr_benchmarks"]
    assert checked_in["experiments"] == generated["experiments"]
