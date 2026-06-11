import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_benchmark_manifest.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_build_benchmark_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
manifest_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_build_benchmark_manifest", manifest_module)
SPEC.loader.exec_module(manifest_module)
DEFAULT_RESULTS_DIR = manifest_module.DEFAULT_RESULTS_DIR
build_manifest = manifest_module.build_manifest
comparable_manifest = manifest_module.comparable_manifest
render_manifest = manifest_module.render_manifest

RESULTS_DIR = Path("docs") / "benchmark-results"
TRACKS_PATH = RESULTS_DIR / "tracks.json"
DOCS_PATH = Path("docs") / "benchmarks.md"


def load_tracks() -> dict[str, object]:
    return json.loads(TRACKS_PATH.read_text(encoding="utf-8"))


def test_manifest_keeps_latest_artifact_per_benchmark() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    assert manifest["summary"]["asr_count"] == 7
    assert manifest["summary"]["tracked_count"] == 8
    assert manifest["summary"]["validated_count"] == 5
    assert manifest["summary"]["legacy_count"] == 2
    assert manifest["summary"]["blocked_count"] == 1

    tracks = {entry["slug"]: entry for entry in manifest["tracks"]}
    assert tracks["qwen-mps"]["artifact_path"].endswith("qwen-mps-2026-06-10.json")
    assert tracks["qwen-mps"]["status"] == "validated"
    assert tracks["faster-whisper-base"]["artifact_path"].endswith("faster-whisper-base.en-int8-2026-06-10.json")
    assert tracks["faster-whisper-base-c80-w075-json-preview"]["artifact_path"].endswith("faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json")
    assert tracks["qwen-compose"]["artifact_path"].endswith("qwen-compose-2026-06-08.json")
    assert tracks["ultravox-compose"]["artifact_path"] is None
    assert tracks["ultravox-compose"]["status"] == "blocked"


def test_checked_in_manifest_matches_generated_output() -> None:
    manifest_path = RESULTS_DIR / "manifest.json"
    checked_in = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated = build_manifest(RESULTS_DIR, TRACKS_PATH)

    assert checked_in["summary"] == generated["summary"]
    assert checked_in["tracks"] == generated["tracks"]
    assert checked_in["artifacts"] == generated["artifacts"]
    assert checked_in["asr_benchmarks"] == generated["asr_benchmarks"]


def test_manifest_prefers_explicit_track_artifact_for_same_runtime_family() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)
    tracks = {entry["slug"]: entry for entry in manifest["tracks"]}

    assert tracks["faster-whisper-base"]["artifact_path"].endswith("faster-whisper-base.en-int8-2026-06-10.json")
    assert tracks["faster-whisper-base-c80-w075-json-preview"]["artifact_path"].endswith("faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json")


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
    tracks_path = tmp_path / "tracks.json"
    tracks_path.write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "slug": "fw-int8",
                        "label": "fw-int8",
                        "backend": "faster-whisper",
                        "model": "base.en",
                        "device": "cpu",
                        "compute": "int8",
                        "lane": "local",
                        "status": "validated",
                        "status_detail": "ok",
                        "target_sample_count": 10,
                        "run_command": "make benchmark",
                    },
                    {
                        "slug": "fw-f16",
                        "label": "fw-f16",
                        "backend": "faster-whisper",
                        "model": "base.en",
                        "device": "cpu",
                        "compute": "float16",
                        "lane": "local",
                        "status": "validated",
                        "status_detail": "ok",
                        "target_sample_count": 10,
                        "run_command": "make benchmark",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, tracks_path)

    assert manifest["summary"]["asr_count"] == 2
    runtimes = {entry["runtime"] for entry in manifest["asr_benchmarks"]}
    assert runtimes == {"cpu / int8", "cpu / float16"}


def test_manifest_exposes_derived_asr_scores() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    qwen_mps = next(entry for entry in manifest["tracks"] if entry["slug"] == "qwen-mps")
    derived = qwen_mps["derived"]

    assert derived["overall_score"] is not None
    assert derived["live_caption_score"] is not None
    assert derived["confidence_score"] == 100.0
    assert derived["sample_coverage_pct"] == 100.0

    summary = manifest["summary"]
    assert summary["backend_count"] >= 4
    assert summary["lane_count"] >= 3
    assert summary["ranges"]["overall_score"] is not None
    assert summary["highlights"]["best_overall"] is not None
    assert summary["highlights"]["best_live_caption"] is not None


def test_manifest_surfaces_contract_and_first_partial_metrics(tmp_path: Path) -> None:
    artifact_path = tmp_path / "demo-2026-06-10.json"
    artifact_path.write_text(
        json.dumps(
            {
                "benchmark": {
                    "sample_count": 4,
                    "chunk_ms": 80,
                    "partial_interval_chunks": 2,
                    "partial_window_seconds": 0.75,
                    "binary_frames": True,
                },
                "backend": {"name": "demo", "model": "demo-v1", "device": "cpu", "compute_type": "int8"},
                "rest": {"mean_ms": 42, "p95_ms": 64, "rtf_mean": 0.2},
                "streaming": {
                    "partial_mean_ms": 21,
                    "partial_p95_ms": 32,
                    "first_partial_end_to_end_mean_ms": 185,
                    "first_partial_end_to_end_p95_ms": 220,
                    "partial_gap_mean_ms": 95,
                    "partial_gap_p95_ms": 110,
                    "final_mean_ms": 30,
                    "final_p95_ms": 45,
                },
                "environment": {"date_utc": "2026-06-10T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )
    tracks_path = tmp_path / "tracks.json"
    tracks_path.write_text(
        json.dumps(
            {
                "sample_contract": {"default_sample_count": 4},
                "tracks": [
                    {
                        "slug": "demo-track",
                        "label": "demo-track",
                        "backend": "demo",
                        "model": "demo-v1",
                        "device": "cpu",
                        "compute": "int8",
                        "lane": "local",
                        "status": "validated",
                        "status_detail": "demo artifact",
                        "target_sample_count": 4,
                        "run_command": "make benchmark",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, tracks_path)

    track = manifest["tracks"][0]
    assert track["contract"] == {
        "chunk_ms": 80,
        "partial_interval_chunks": 2,
        "partial_window_seconds": 0.75,
        "binary_frames": True,
    }
    assert track["streaming"]["first_partial_end_to_end_mean_ms"] == 185
    assert track["streaming"]["partial_gap_mean_ms"] == 95
    assert manifest["summary"]["highlights"]["fastest_first_partial"]["slug"] == "demo-track"
    assert manifest["summary"]["highlights"]["tightest_partial_cadence"]["slug"] == "demo-track"


def test_docs_and_tracks_registry_stay_aligned() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    tracks = load_tracks()["tracks"]

    assert "docs/benchmark-results/tracks.json" in docs_text
    assert "docs/benchmark-results/manifest.json" in docs_text
    assert "qwen-compose-2026-06-07.json" not in docs_text

    for track in tracks:
        assert track["slug"] in docs_text
        assert track["status"] in docs_text
        assert track["model"] in docs_text
        if "artifact" in track:
            assert track["artifact"] in docs_text
        else:
            assert "no committed artifact" in docs_text


def test_manifest_artifacts_are_checked_in_or_explicitly_missing() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)
    tracked_artifacts = {track["artifact_path"] for track in manifest["tracks"] if track["artifact_path"]}
    expected_files = {
        f"benchmark-results/{path.name}"
        for path in RESULTS_DIR.glob("*.json")
        if path.name not in {"manifest.json", "tracks.json", "qwen-compose-2026-06-07.json"}
    }

    assert tracked_artifacts == expected_files


def test_render_manifest_matches_checked_in_output() -> None:
    generated = build_manifest(RESULTS_DIR, TRACKS_PATH)
    checked_in = json.loads((RESULTS_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert comparable_manifest(generated) == comparable_manifest(checked_in)


def test_manifest_check_fails_when_checked_in_file_is_stale(tmp_path: Path) -> None:
    artifact_path = tmp_path / "demo-2026-06-10.json"
    artifact_path.write_text(
        json.dumps(
            {
                "backend": {"name": "demo", "model": "demo-v1", "device": "cpu", "compute_type": "int8"},
                "rest": {"mean_ms": 42, "p95_ms": 64, "rtf_mean": 0.2},
                "streaming": {"partial_mean_ms": 21, "partial_p95_ms": 32, "final_mean_ms": 30, "final_p95_ms": 45},
                "environment": {"date_utc": "2026-06-10T00:00:00Z"},
            }
        ),
        encoding="utf-8",
    )
    tracks_path = tmp_path / "tracks.json"
    tracks_path.write_text(
        json.dumps(
            {
                "sample_contract": {"sample_count": 10},
                "tracks": [
                    {
                        "slug": "demo-track",
                        "label": "demo-track",
                        "backend": "demo",
                        "model": "demo-v1",
                        "device": "cpu",
                        "compute": "int8",
                        "lane": "local",
                        "status": "validated",
                        "status_detail": "demo artifact",
                        "target_sample_count": 10,
                        "run_command": "make benchmark-site",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "--results-dir",
            str(tmp_path),
            "--tracks",
            str(tracks_path),
            "--output",
            str(manifest_path),
            "--check",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert f"Manifest is stale: {manifest_path}" in result.stderr


def test_manifest_check_succeeds_when_checked_in_file_matches_generated_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    generated = build_manifest(DEFAULT_RESULTS_DIR, TRACKS_PATH)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(render_manifest(generated), encoding="utf-8")

    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--output", str(manifest_path), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""



def test_homepage_highlights_advanced_asr_sections() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert "Advanced ASR comparison matrix" in html
    assert "What matters for low-latency ASR" in html
    assert "Visible benchmark lanes" in html
    assert "Best operator balance" in html
    assert "entry.derived?.overall_score" in html


def test_homepage_filters_blocked_tracks_from_visible_results() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert 'track.artifact_path && track.status !== "blocked"' in html
    assert "Tracked lanes without publishable artifacts stay out of the front-end comparison flow." in html
