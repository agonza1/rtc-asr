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


def test_manifest_keeps_distinct_runtime_variants(tmp_path: Path) -> None:
    older = tmp_path / "variant-a-2026-06-09.json"
    newer = tmp_path / "variant-b-2026-06-10.json"
    older.write_text(
        json.dumps(
            {
                "backend": {
                    "name": "faster-whisper",
                    "model": "base.en",
                    "device": "cpu",
                    "compute_type": "int8",
                },
                "rest": {"mean_ms": 100, "p95_ms": 120, "rtf_mean": 0.5},
                "streaming": {"partial_mean_ms": 50, "partial_p95_ms": 75, "final_mean_ms": 90, "final_p95_ms": 110},
                "environment": {"date_utc": "2026-06-09T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )
    newer.write_text(
        json.dumps(
            {
                "backend": {
                    "name": "faster-whisper",
                    "model": "base.en",
                    "device": "cpu",
                    "compute_type": "float16",
                },
                "rest": {"mean_ms": 80, "p95_ms": 95, "rtf_mean": 0.4},
                "streaming": {"partial_mean_ms": 40, "partial_p95_ms": 60, "final_mean_ms": 70, "final_p95_ms": 90},
                "environment": {"date_utc": "2026-06-10T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path)

    assert manifest["summary"]["asr_count"] == 2
    runtimes = {entry["runtime"] for entry in manifest["asr_benchmarks"]}
    assert runtimes == {"cpu / int8", "cpu / float16"}
