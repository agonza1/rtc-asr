import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "build_benchmark_manifest.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_build_benchmark_manifest", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
manifest_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_build_benchmark_manifest", manifest_module)
SPEC.loader.exec_module(manifest_module)
build_manifest = manifest_module.build_manifest

RESULTS_DIR = Path("docs") / "benchmark-results"
TRACKS_PATH = RESULTS_DIR / "tracks.json"
DOCS_PATH = Path("docs") / "benchmarks.md"


def load_tracks() -> dict[str, object]:
    return json.loads(TRACKS_PATH.read_text(encoding="utf-8"))


def test_manifest_keeps_latest_artifact_per_benchmark() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    assert manifest["summary"]["asr_count"] == 5
    assert manifest["summary"]["tracked_count"] == 6
    assert manifest["summary"]["validated_count"] == 4
    assert manifest["summary"]["legacy_count"] == 1
    assert manifest["summary"]["blocked_count"] == 1

    tracks = {entry["slug"]: entry for entry in manifest["tracks"]}
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
