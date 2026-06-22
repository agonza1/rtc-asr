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
extract_system_signals = manifest_module.extract_system_signals
render_manifest = manifest_module.render_manifest

PRERENDER_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prerender_benchmark_homepage.py"
PRERENDER_SPEC = importlib.util.spec_from_file_location("rtc_asr_prerender_benchmark_homepage", PRERENDER_MODULE_PATH)
assert PRERENDER_SPEC is not None and PRERENDER_SPEC.loader is not None
prerender_module = importlib.util.module_from_spec(PRERENDER_SPEC)
sys.modules.setdefault("rtc_asr_prerender_benchmark_homepage", prerender_module)
PRERENDER_SPEC.loader.exec_module(prerender_module)
detail_page_path = prerender_module.detail_page_path
render_detail_page = prerender_module.render_detail_page
render_homepage = prerender_module.render_homepage
measurement_technique = prerender_module.measurement_technique

RESULTS_DIR = Path("docs") / "benchmark-results"
TRACKS_PATH = RESULTS_DIR / "tracks.json"
DOCS_PATH = Path("docs") / "benchmarks.md"
DOCS_INDEX_PATH = Path("docs") / "index.md"
HOMEPAGE_PATH = Path("docs") / "index.html"


def load_tracks() -> dict[str, object]:
    return json.loads(TRACKS_PATH.read_text(encoding="utf-8"))


def test_manifest_keeps_latest_artifact_per_benchmark() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    assert manifest["summary"]["asr_count"] == 8
    assert manifest["summary"]["tracked_count"] == 8
    assert manifest["summary"]["validated_count"] == 7
    assert manifest["summary"]["legacy_count"] == 0
    assert manifest["summary"]["blocked_count"] == 1

    tracks = {entry["slug"]: entry for entry in manifest["tracks"]}
    assert tracks["parakeet-mlx-service-110m"]["artifact_path"].endswith("parakeet-mlx-110m-service-2026-06-21.json")
    assert tracks["qwen-mps"]["artifact_path"].endswith("qwen-mps-2026-06-21.json")
    assert tracks["qwen-mps"]["status"] == "validated"
    assert tracks["faster-whisper-base"]["artifact_path"].endswith("faster-whisper-base.en-int8-2026-06-20.json")
    assert tracks["faster-whisper-base"]["accuracy"]["word_error_rate_mean"] is None
    assert tracks["qwen-compose"]["artifact_path"].endswith("qwen-compose-2026-06-21.json")
    assert tracks["qwen-compose"]["runtime"] == "cpu / float16"
    assert tracks["qwen-compose"]["target_sample_count"] == 10
    assert tracks["pipecat-e2e-faster-whisper-base"]["artifact_path"].endswith("faster-whisper-base.en-int8-pipecat-e2e-2026-06-19.json")
    assert tracks["pipecat-e2e-faster-whisper-base"]["status"] == "blocked"
    assert tracks["qwen-mps"]["official_wer_reference"] == "2.11 / 4.55 LibriSpeech clean / other (Qwen/Qwen3-ASR-0.6B)"
    assert len(tracks["qwen-mps"]["artifact_sha256"]) == 64
    assert tracks["qwen-mps"]["artifact_size_bytes"] > 0



def test_historical_detail_pages_keep_track_context() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)
    artifact = next(
        entry
        for entry in manifest["artifacts"]
        if entry["artifact_path"].endswith("qwen-mps-2026-06-20.json")
    )

    assert artifact["label"] == "Qwen MPS"
    assert artifact["lane"] == "Local Python Apple Silicon"
    assert artifact["status"] == "legacy"
    assert artifact["derived"]["confidence_score"] == 85.0

    detail = render_detail_page(artifact, None)

    assert "Qwen MPS" in detail
    assert "Local Python Apple Silicon" in detail
    assert "Status: legacy" in detail
    assert "unknown · Qwen/Qwen3-ASR-0.6B" not in detail

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

    assert tracks["faster-whisper-base"]["artifact_path"].endswith("faster-whisper-base.en-int8-2026-06-20.json")
    assert tracks["qwen-compose"]["artifact_path"].endswith("qwen-compose-2026-06-21.json")


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
    assert all(len(entry["artifact_sha256"]) == 64 for entry in manifest["asr_benchmarks"])
    assert all(entry["artifact_size_bytes"] > 0 for entry in manifest["asr_benchmarks"])
    runtimes = {entry["runtime"] for entry in manifest["asr_benchmarks"]}
    assert runtimes == {"cpu / int8", "cpu / float16"}


def test_manifest_skips_non_asr_artifacts(tmp_path: Path) -> None:
    payload = json.loads((RESULTS_DIR / "faster-whisper-base.en-int8-2026-06-15.json").read_text(encoding="utf-8"))
    (tmp_path / "faster-whisper-base.en-int8-2026-06-15.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "parakeet-mlx-2026-06-13.json").write_text(
        json.dumps({
            "kind": "mlx-asr-benchmark",
            "backend": {"name": "parakeet-mlx", "model": "mlx-community/parakeet-tdt-0.6b-v3"},
            "benchmark": {"sample_count": 1},
            "samples": [{"transcript": "hello", "latency_ms": 12.3}],
            "summary": {"mean_ms": 12.3},
        }),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, TRACKS_PATH)

    assert manifest["summary"]["artifact_file_count"] == 1
    assert all("parakeet-mlx" not in entry["artifact_path"] for entry in manifest["artifacts"])


def test_manifest_exposes_derived_asr_scores() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    qwen_mps = next(entry for entry in manifest["tracks"] if entry["slug"] == "qwen-mps")
    derived = qwen_mps["derived"]

    assert derived["overall_score"] is not None
    assert derived["partial_backlog_score"] is not None
    assert derived["confidence_score"] == 100.0
    assert derived["sample_coverage_pct"] == 100.0

    summary = manifest["summary"]
    assert summary["backend_count"] >= 3
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
                    "mode": "v1-stt-stream",
                    "chunk_ms": 80,
                    "partial_interval_chunks": 2,
                    "partial_window_seconds": 0.75,
                    "binary_frames": True,
                    "partial_event_timeout_seconds": 0.25,
                    "final_event_timeout_seconds": 3.5,
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
                    "live_metrics_comparable": True,
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
        "transport": "v1-stt-stream",
        "path": "/v1/stt/stream",
        "partial_interval_chunks": 2,
        "partial_window_seconds": 0.75,
        "binary_frames": True,
        "sample_rate": None,
        "live_metrics_comparable": True,
        "partial_event_timeout_seconds": 0.25,
        "final_event_timeout_seconds": 3.5,
    }
    assert track["streaming"]["first_partial_end_to_end_mean_ms"] == 185
    assert track["streaming"]["partial_gap_mean_ms"] == 95
    assert manifest["summary"]["highlights"]["fastest_first_partial"]["slug"] == "demo-track"
    assert manifest["summary"]["highlights"]["tightest_partial_cadence"]["slug"] == "demo-track"
    assert manifest["summary"]["highlights"]["lowest_partial_backlog"]["slug"] == "demo-track"
    assert manifest["summary"]["highlights"]["fastest_final"]["label"] == "Fastest streaming finalization delay"




def test_manifest_preserves_system_signals_for_homepage_cards() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)
    track = next(entry for entry in manifest["tracks"] if entry["slug"] == "parakeet-mlx-service-110m")

    assert track["system"]["platform"] == "macOS-26.5.1-arm64-arm-64bit-Mach-O"
    assert track["system"]["processor"] == "arm"
    assert track["system"]["peak_rss_mb"] is None
    assert track["system"]["memory_total_mb"] == 24576.0

    coverage = manifest["summary"]["system_coverage"]
    assert coverage["memory_total_mb_count"] == 16
    assert coverage["process_rss_mb_count"] == 10
    assert coverage["peak_rss_mb_count"] == 10
    assert coverage["accelerator_count"] == 0
    assert coverage["cpu_utilization_percent_count"] == 5
    assert coverage["package_power_watts_count"] == 0
    assert coverage["energy_per_audio_second_j_count"] == 0
    assert coverage["thermal_peak_celsius_count"] == 0
    assert coverage["thermal_observation_count"] == 0


def test_manifest_counts_thermal_state_as_system_evidence() -> None:
    system = extract_system_signals({"environment": {"thermal_state": "stable after 5 minutes"}})

    assert system["thermal_observation"] == "stable after 5 minutes"


def test_manifest_preserves_energy_per_audio_second_metadata() -> None:
    system = extract_system_signals({"metrics": {"energy_per_audio_second_j": 2.4}})

    assert system["energy_per_audio_second_j"] == 2.4


def test_manifest_preserves_nested_memory_metadata_aliases() -> None:
    system = extract_system_signals(
        {
            "memory": {"total_mb": 32768.0, "rss_peak_mb": 512.5},
            "metrics": {"memory": {"process_rss_mb": 180.25}},
        }
    )

    assert system["memory_total_mb"] == 32768.0
    assert system["process_rss_mb"] == 180.25
    assert system["peak_rss_mb"] == 512.5


def test_manifest_preserves_nested_cpu_metadata_aliases() -> None:
    nested_system = extract_system_signals({"metrics": {"cpu": {"percent": 42.5}}})
    top_level_system = extract_system_signals({"cpu": {"utilization_percent": 37.25}})

    assert nested_system["cpu_utilization_percent"] == 42.5
    assert top_level_system["cpu_utilization_percent"] == 37.25


def test_manifest_preserves_nested_power_and_thermal_metadata() -> None:
    system = extract_system_signals(
        {
            "metrics": {
                "power": {"package_watts": 8.6, "energy_per_audio_second_j": 2.9},
                "thermal": {"peak_celsius": 64.2, "state": "warm but stable"},
            }
        }
    )

    assert system["package_power_watts"] == 8.6
    assert system["energy_per_audio_second_j"] == 2.9
    assert system["thermal_peak_celsius"] == 64.2
    assert system["thermal_observation"] == "warm but stable"


def test_manifest_preserves_accelerator_metadata_aliases() -> None:
    environment_system = extract_system_signals({"environment": {"accelerator": "Apple Neural Engine"}})
    metrics_system = extract_system_signals({"metrics": {"gpu": "Apple M-series GPU"}})
    structured_system = extract_system_signals(
        {"metrics": {"accelerator": {"name": "Apple Neural Engine"}, "gpu": {"model": "M-series GPU"}}}
    )

    assert environment_system["accelerator"] == "Apple Neural Engine"
    assert metrics_system["accelerator"] == "Apple M-series GPU"
    assert structured_system["accelerator"] == "Apple Neural Engine"


def test_docs_index_does_not_fallback_partial_mean_into_first_visible_partial() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert "entry.streaming.first_partial_end_to_end_mean_ms ?? null" in html
    assert 'if (status === "blocked") return "blocked";' in html
    assert "function formatPercent(value)" in html
    assert "Audio-end finalization" in html
    assert "entry.streaming.first_partial_end_to_end_mean_ms ?? entry.streaming.partial_mean_ms" not in html
    assert "const baselineEntries = comparableEntries(primary);" in html
    assert 'const firstPartialBaselineLabel = baselineEntries.length !== primary.length ? "vs validated fastest" : "vs fastest";' in html
    assert 'Partial backlog latency' in html
    assert 'title="Time from audio end until the final transcript returns; this is closeout delay, not total clip duration."' in html
    assert 'title="Diagnostic latency for chunk-triggered partial updates after streaming is already underway; this is not perceived first-response latency, so read it alongside partial gap and late partial ratio."' in html
    assert 'title="Buffered audio window used when generating partial transcripts."' in html
    assert 'late_partial_ratio' in html
    assert 'partial_transcript_churn_word_mean' in html
    assert 'Late partial ratio' in html
    assert 'Word churn' in html
    assert "Math.min(...ranked.map((entry) => numeric(firstVisiblePartial(entry), 0)))" not in html
    assert "keeps REST throughput in a supporting role" in html
    assert "sample coverage" in html
    assert "The homepage stays latency-only." in html
    assert "benchmark notes and artifact detail pages" in html
    assert "reference WER sourced from upstream evaluations" not in html


def test_docs_index_prioritizes_validated_entries_in_rankings() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert 'if (entry.status === "validated") return 0;' in html
    assert 'const scoreDelta = scoreRank(left) - scoreRank(right);' in html
    assert 'return -overall;' in html
    assert 'const ranked = sortEntries(primaryEntries(entries)).slice(0, 3);' in html
    assert 'function primaryEntries(entries)' in html
    assert 'function secondaryEntries(entries)' in html


def test_render_homepage_omits_unpublished_registry_gap_copy() -> None:
    homepage = """<!-- BEGIN GENERATED:static-summary -->\nold\n<!-- END GENERATED:static-summary -->\n<!-- BEGIN GENERATED:generated-at -->\nold\n<!-- END GENERATED:generated-at -->"""
    manifest = {
        "summary": {"validated_count": 1, "tracked_count": 2},
        "tracks": [
            {
                "slug": "validated",
                "label": "Validated Lane",
                "status": "validated",
                "status_detail": "publishable",
                "artifact_path": "docs/benchmark-results/validated.json",
                "lane": "local",
                "runtime": "cpu / int8",
                "backend": "demo",
                "model": "demo-v1",
                "rest": {"mean_ms": 10},
                "streaming": {
                    "first_partial_end_to_end_mean_ms": 20,
                    "partial_mean_ms": 30,
                    "partial_gap_mean_ms": 5,
                    "final_mean_ms": 40,
                },
            },
            {
                "slug": "unpublished",
                "label": "Unpublished Lane",
                "status": "validated",
                "status_detail": "waiting on artifact",
                "artifact_path": None,
                "lane": "ci",
                "runtime": "cpu / int8",
                "backend": "demo",
                "model": "demo-v2",
                "run_command": "make benchmark-demo",
                "rest": {},
                "streaming": {},
            },
        ],
    }

    html = render_homepage(manifest, homepage)

    assert 'Unpublished Lane' not in html
    assert 'waiting on artifact' not in html


def test_render_homepage_keeps_historical_supporting_artifacts_discoverable() -> None:
    homepage = """<!-- BEGIN GENERATED:static-summary -->\nold\n<!-- END GENERATED:static-summary -->\n<!-- BEGIN GENERATED:generated-at -->\nold\n<!-- END GENERATED:generated-at -->"""
    manifest = {
        "summary": {},
        "tracks": [
            {
                "slug": "qwen-mps",
                "label": "Qwen MPS",
                "status": "validated",
                "status_detail": "Validated paced /v1/stt/stream local Apple Silicon MPS artifact refreshed on 2026-06-21.",
                "artifact_path": "benchmark-results/qwen-mps-2026-06-21.json",
                "lane": "Local Python Apple Silicon",
                "runtime": "mps / auto",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "rest": {"mean_ms": 10},
                "streaming": {
                    "live_metrics_comparable": True,
                    "first_partial_end_to_end_mean_ms": 20,
                    "partial_mean_ms": 30,
                    "partial_gap_mean_ms": 5,
                    "final_mean_ms": 40,
                },
                "contract": {"path": "/v1/stt/stream", "transport": "v1-stt-stream"},
                "derived": {"overall_score": 90.0},
                "measured_at": "2026-06-21T14:11:13Z",
            },
        ],
        "artifacts": [
            {
                "slug": "qwen-mps",
                "label": "Qwen MPS",
                "status": "legacy",
                "status_detail": "Historical supporting artifact for Qwen MPS; current tracked artifact is qwen-mps-2026-06-21.json.",
                "artifact_path": "benchmark-results/qwen-mps-2026-06-20.json",
                "lane": "Local Python Apple Silicon",
                "runtime": "mps / auto",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "rest": {"mean_ms": 12},
                "streaming": {
                    "live_metrics_comparable": False,
                    "first_partial_end_to_end_mean_ms": 25,
                    "partial_mean_ms": 35,
                    "partial_gap_mean_ms": 7,
                    "final_mean_ms": 45,
                },
                "contract": {"path": "/ws/stream", "transport": "direct"},
                "derived": {"overall_score": 60.0},
                "measured_at": "2026-06-20T12:39:19Z",
            },
        ],
    }

    html = render_homepage(manifest, homepage)

    assert "Historical and differently scoped artifacts remain available through the appendix and detail pages." in html
    assert "Artifacts kept out of the primary ranking" not in html
    assert "qwen-mps-2026-06-20.html" not in html


def test_docs_index_live_labels_match_streaming_framing() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert 'Recommended default' in html
    assert 'Primary ranking scope' in html
    assert 'Best live numbers' in html
    assert 'data-label="Partial backlog latency"' in html
    assert 'data-label="Audio-end finalization"' in html
    assert 'data-label="REST throughput context"' in html
    assert 'function artifactHashLabel(entry)' in html
    assert '${artifactHashLabel(entry)}' in html
    assert 'Artifact-backed benchmark summary' not in html
    assert 'function historicalSupportingEntries(manifest, currentEntries)' in html
    assert 'const historicalSecondary = historicalSupportingEntries(manifest, visibleTracks);' in html


def test_docs_parakeet_mlx_row_matches_checked_in_artifact_summary() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    artifact = json.loads((RESULTS_DIR / "parakeet-mlx-2026-06-13.json").read_text(encoding="utf-8"))

    mean_ms = artifact["summary"]["mean_ms"]
    p95_ms = artifact["summary"]["p95_ms"]
    row = next(
        line
        for line in docs_text.splitlines()
        if line.startswith("| `parakeet-mlx` | 3 |")
        and "docs/benchmark-results/parakeet-mlx-2026-06-13.json" in line
    )

    assert f"| `parakeet-mlx` | 3 | {mean_ms} ms / {p95_ms} ms |" in row
    assert f"its `{mean_ms} ms` mean latency" in docs_text


def test_docs_parakeet_mlx_110m_row_matches_checked_in_artifact_summary() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    artifact = json.loads((RESULTS_DIR / "parakeet-mlx-110m-2026-06-13.json").read_text(encoding="utf-8"))

    mean_ms = artifact["summary"]["mean_ms"]
    p95_ms = artifact["summary"]["p95_ms"]
    row = next(
        line
        for line in docs_text.splitlines()
        if line.startswith("| `parakeet-mlx-110m` | 3 |")
        and "docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json" in line
    )

    assert f"| `parakeet-mlx-110m` | 3 | {mean_ms} ms / {p95_ms} ms |" in row
    assert f"its `{mean_ms} ms` mean latency" in docs_text


def test_docs_parakeet_mlx_service_110m_row_matches_checked_in_artifact_summary() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    artifact = json.loads((RESULTS_DIR / "parakeet-mlx-110m-service-2026-06-21.json").read_text(encoding="utf-8"))

    mean_ms = artifact["rest"]["mean_ms"]
    p95_ms = artifact["rest"]["p95_ms"]
    row = next(
        line
        for line in docs_text.splitlines()
        if line.startswith("| `parakeet-mlx-service-110m` | 10 |")
        and "docs/benchmark-results/parakeet-mlx-110m-service-2026-06-21.json" in line
    )

    assert f"| `parakeet-mlx-service-110m` | 10 | {mean_ms} ms / {p95_ms} ms |" in row
    assert f"its `{mean_ms} ms` REST mean" in docs_text


def test_docs_and_tracks_registry_stay_aligned() -> None:
    docs_text = DOCS_PATH.read_text(encoding="utf-8")
    tracks = load_tracks()["tracks"]

    assert "docs/benchmark-results/tracks.json" in docs_text
    assert "docs/benchmark-results/manifest.json" in docs_text
    assert "## Accuracy Publishing Policy" in docs_text
    assert "FLEURS `en_us` and a pinned Common Voice English test split" in docs_text
    assert "qwen-compose-2026-06-07.json" not in docs_text
    assert "## Recommended Quality Methodology" in docs_text
    assert "Reference WER" in docs_text
    assert "should not show reference WER in the primary ranking table" in docs_text
    assert "not an official rtc-asr measurement" in docs_text
    assert "local diagnostic WER from our small internal sample set remains intentionally unpublished" in docs_text
    assert "BENCHMARK_RESULT_DATE=2026-06-19 make benchmark-compose-qwen" in docs_text
    assert "BENCHMARK_RESULT_DATE=2026-06-15 make benchmark-compose-qwen" not in docs_text

    for track in tracks:
        assert track["slug"] in docs_text
        assert track["status"] in docs_text
        assert track["model"] in docs_text
        if "artifact" in track:
            assert track["artifact"] in docs_text
        else:
            assert "no committed artifact" in docs_text


def test_docs_index_surfaces_reference_wer_notes() -> None:
    docs_index_text = DOCS_INDEX_PATH.read_text(encoding="utf-8")

    assert "[Local STT v1](./local-stt-v1.md)" in docs_index_text
    assert "shared next-step websocket protocol" in docs_index_text
    assert "src/protocols/local_stt_v1.py" in docs_index_text
    assert "## Appendix: Reference WER Notes" in docs_index_text
    assert "not official rtc-asr measurements" in docs_index_text
    assert "parakeet-mlx-service-110m" in docs_index_text
    assert "Qwen/Qwen3-ASR-0.6B" in docs_index_text


def test_detail_page_path_uses_artifact_stem() -> None:
    entry = {"artifact_path": "benchmark-results/demo-artifact-2026-06-14.json"}

    assert detail_page_path(entry) == "benchmark-results/pages/demo-artifact-2026-06-14.html"


def test_detail_page_measurement_technique_matches_streaming_contract() -> None:
    local_stt_entry = {"contract": {"path": "/v1/stt/stream", "transport": "v1-stt-stream"}}
    legacy_entry = {"contract": {"path": "/ws/stream", "transport": "direct"}}
    unknown_entry = {"contract": {"path": "/custom"}}

    assert measurement_technique(local_stt_entry) == "REST and Local STT v1 websocket ASR latency benchmark"
    assert measurement_technique(legacy_entry) == "REST and legacy buffered websocket ASR latency benchmark"
    assert measurement_technique(unknown_entry) == "REST and websocket ASR latency benchmark"


def test_benchmark_detail_pages_exist_for_artifact_backed_tracks() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)

    for track in manifest["tracks"]:
        if not track["artifact_path"]:
            continue
        detail_path = Path("docs") / detail_page_path(track)
        assert detail_path.exists()
        detail_html = detail_path.read_text(encoding="utf-8")
        assert "Artifact detail page" in detail_html
        assert "Back to benchmark homepage" in detail_html
        assert Path(track["artifact_path"]).name in detail_html
        assert "Download raw JSON artifact" in detail_html

    rss_detail = (Path('docs') / 'benchmark-results/pages/parakeet-mlx-110m-service-2026-06-21.html').read_text(encoding='utf-8')
    assert "System profile" in rss_detail
    assert "Efficiency signals" in rss_detail
    assert "Accuracy context" in rss_detail
    assert "Reproduction command" in rss_detail
    assert "Artifact integrity" in rss_detail
    assert "Artifact provenance" in rss_detail
    assert "Manifest path benchmark-results/parakeet-mlx-110m-service-2026-06-21.json" in rss_detail
    assert "SHA-256" in rss_detail
    assert '"@type": "Dataset"' in rss_detail
    assert '"@type": "DataDownload"' in rss_detail
    assert '"@type": "BreadcrumbList"' in rss_detail
    assert '"measurementTechnique": "REST and Local STT v1 websocket ASR latency benchmark"' in rss_detail
    assert '"url": "parakeet-mlx-110m-service-2026-06-21.html"' in rss_detail
    assert '"sha256":' in rss_detail
    assert '<meta name="description" content="Validated paced /v1/stt/stream local Apple Silicon MLX service artifact' in rss_detail
    assert '<link rel="canonical" href="parakeet-mlx-110m-service-2026-06-21.html">' in rss_detail
    assert 'aria-label="Breadcrumb"' in rss_detail
    assert "Benchmark homepage" in rss_detail
    assert "make benchmark-parakeet-mlx-service-110m" in rss_detail
    assert "Artifact does not record sustained thermal notes yet." in rss_detail

    legacy_qwen_detail = (Path("docs") / "benchmark-results/pages/qwen-mps-2026-06-20.html").read_text(encoding="utf-8")
    assert "Qwen MPS" in legacy_qwen_detail
    assert "Local Python Apple Silicon" in legacy_qwen_detail
    assert "Status: legacy" in legacy_qwen_detail
    assert "BENCHMARK_RESULT_DATE=2026-06-20 BENCHMARK_SAMPLE_COUNT=10 BENCHMARK_REST_RUNS=5 make benchmark-qwen-mps-legacy" in legacy_qwen_detail
    legacy_qwen_older_detail = (Path("docs") / "benchmark-results/pages/qwen-mps-2026-06-10.html").read_text(encoding="utf-8")
    assert "BENCHMARK_RESULT_DATE=2026-06-10 BENCHMARK_SAMPLE_COUNT=10 BENCHMARK_REST_RUNS=5 make benchmark-qwen-mps-legacy" in legacy_qwen_older_detail

    legacy_pipecat_detail = (Path("docs") / "benchmark-results/pages/faster-whisper-base.en-int8-pipecat-e2e-2026-06-17.html").read_text(encoding="utf-8")
    assert "Pipecat E2E Faster-Whisper Base" in legacy_pipecat_detail
    assert "Pipecat E2E Local Python CPU" in legacy_pipecat_detail
    assert "make benchmark-pipecat-e2e" in legacy_pipecat_detail


def test_render_detail_page_surfaces_optional_efficiency_metrics() -> None:
    entry = {
        'label': 'demo-artifact',
        'artifact_path': 'benchmark-results/demo-artifact-2026-06-14.json',
        'device': 'apple-silicon',
        'lane': 'demo lane',
        'backend': 'demo',
        'model': 'demo-v1',
        'runtime': 'local',
        'status': 'validated',
        'sample_count': 3,
        'measured_at': '2026-06-14T00:00:00Z',
        'status_detail': 'Demo artifact.',
        'rest': {'mean_ms': 42.0, 'p95_ms': 55.0, 'rtf_mean': 0.2},
        'streaming': {'partial_mean_ms': 21.0, 'partial_gap_mean_ms': 5.0, 'late_partial_ratio': 0.03, 'final_mean_ms': 30.0},
        'contract': {'chunk_ms': 250, 'partial_window_seconds': 2.0, 'partial_interval_chunks': 1, 'sample_rate': 16000, 'binary_frames': False},
        'derived': {'overall_score': 88.0, 'confidence_score': 91.0},
        'official_wer_reference': '3.1 / 7.2 Demo clean / other',
        'run_command': 'make benchmark-demo',
        'artifact_sha256': '1234567890abcdef',
        'artifact_size_bytes': 1536,
    }
    payload = {
        'environment': {
            'platform': 'macOS',
            'processor': 'arm64',
            'python': '3.14.5',
            'accelerator': 'Apple M-series GPU',
            'process_rss_mb': 23.6,
        },
        'metrics': {
            'cpu_utilization_percent': 38.2,
            'package_power_watts': 7.4,
            'energy_per_audio_second_j': 2.6,
            'thermal_peak_celsius': 63.5,
            'thermal_observation': 'Stable over 5 minutes.',
        },
    }

    detail_html = render_detail_page(entry, payload)

    assert 'System profile' in detail_html
    assert 'macOS' in detail_html
    assert 'Peak RSS n/a' in detail_html
    assert 'Process RSS 23.6 MB' in detail_html
    assert 'Accelerator Apple M-series GPU' in detail_html
    assert 'CPU 38.2%' in detail_html
    assert 'Power 7.4 W' in detail_html
    assert 'Energy/audio-sec 2.6 J' in detail_html

    integer_energy_payload = {'metrics': {'energy_per_audio_second_j': 3}}
    integer_energy_html = render_detail_page(entry, integer_energy_payload)
    assert 'Energy/audio-sec 3.0 J' in integer_energy_html

    nested_efficiency_payload = {
        'metrics': {
            'power': {'package_watts': 8.6, 'energy_per_audio_second_j': 2.9},
            'thermal': {'peak_celsius': 64.2, 'state': 'warm but stable'},
        }
    }
    nested_efficiency_html = render_detail_page(entry, nested_efficiency_payload)
    assert 'Power 8.6 W' in nested_efficiency_html
    assert 'Energy/audio-sec 2.9 J' in nested_efficiency_html
    assert 'Thermal 64.2 C' in nested_efficiency_html
    assert 'warm but stable' in nested_efficiency_html

    assert 'Thermal 63.5 C' in detail_html
    assert 'Sample rate 16000 Hz' in detail_html
    assert '3.1 / 7.2 Demo clean / other' in detail_html
    assert 'make benchmark-demo' in detail_html
    assert '1234567890abcdef' in detail_html
    assert '"contentSize": 1536' in detail_html
    assert '"variableMeasured": [' in detail_html
    assert '"audio-end finalization latency"' in detail_html
    assert '"contentUrl": "../demo-artifact-2026-06-14.json"' in detail_html
    assert 'download="demo-artifact-2026-06-14.json"' in detail_html
    assert 'Download raw JSON artifact' in detail_html
    assert '"@type": "BreadcrumbList"' in detail_html
    assert 'aria-label="Breadcrumb"' in detail_html
    assert 'Benchmark homepage' in detail_html
    assert 'Size 1.5 KB' in detail_html
    assert 'Integrity check: SHA-256 <code>1234567890abcdef</code>' in detail_html
    assert 'Artifact provenance' in detail_html
    assert 'Generated detail page demo-artifact-2026-06-14.html' in detail_html
    assert 'Shown as external context rather than an official rtc-asr measurement.' in detail_html
    assert 'Stable over 5 minutes.' in detail_html


def test_render_detail_page_surfaces_system_and_efficiency_signals() -> None:
    entry = {
        'label': 'Parakeet MLX',
        'status_detail': 'Local benchmark preview',
        'lane': 'apple-silicon',
        'backend': 'parakeet-mlx',
        'model': 'mlx-community/parakeet-tdt-0.6b-v3',
        'runtime': 'mlx',
        'device': 'apple-silicon',
        'status': 'validated',
        'sample_count': 3,
        'measured_at': '2026-06-13T22:55:00Z',
        'artifact_path': 'benchmark-results/parakeet-mlx-2026-06-13.json',
        'rest': {'mean_ms': 42.0, 'p95_ms': 55.0, 'rtf_mean': 0.2},
        'streaming': {'partial_mean_ms': 21.0, 'partial_gap_mean_ms': 5.0, 'late_partial_ratio': 0.03, 'final_mean_ms': 30.0},
        'contract': {'chunk_ms': 250, 'partial_window_seconds': 2.0, 'partial_interval_chunks': 1, 'binary_frames': False},
        'derived': {'overall_score': 88.0, 'confidence_score': 91.0},
    }
    payload = {
        'environment': {
            'platform': 'macOS',
            'processor': 'arm64',
            'python': '3.14.5',
            'cpu_logical_cores': 12,
            'memory_total_mb': 16384.0,
            'process_rss_mb': 23.6,
        },
        'metrics': {
            'cpu_utilization_percent': 38.2,
            'package_power_watts': 7.4,
            'thermal_peak_celsius': 63.5,
            'thermal_observation': 'Stable over 5 minutes.',
        },
    }

    detail_html = render_detail_page(entry, payload)

    assert 'System profile' in detail_html
    assert 'Peak RSS n/a' in detail_html
    assert 'Process RSS 23.6 MB' in detail_html
    assert 'Logical cores 12' in detail_html
    assert 'System RAM 16384.0 MB' in detail_html
    assert 'Stable over 5 minutes.' in detail_html

    memory_alias_html = render_detail_page(
        entry,
        {
            'memory': {'total_mb': 32768.0, 'peak_rss_mb': 512.5},
            'metrics': {'memory': {'process_rss_mb': 180.25}},
        },
    )
    assert 'System RAM 32768.0 MB' in memory_alias_html
    assert 'Peak RSS 512.5 MB' in memory_alias_html
    assert 'Process RSS 180.2 MB' in memory_alias_html


def test_homepage_head_includes_launch_seo_metadata() -> None:
    homepage = HOMEPAGE_PATH.read_text(encoding="utf-8")

    assert "<title>Real-Time ASR Latency Benchmarks for WebRTC Voice AI | WebRTC.ventures</title>" in homepage
    assert 'meta name="description" content="Compare low-latency ASR backends for WebRTC and Voice AI applications across first partial, partial cadence, audio-end finalization delay, throughput context, sample coverage, and benchmark methodology."' in homepage
    assert 'meta property="og:title" content="Real-Time ASR Latency Benchmarks for WebRTC Voice AI"' in homepage
    assert 'meta property="og:url" content="https://benchmarks.webrtc.ventures/asr-latency/"' in homepage
    assert 'link rel="canonical" href="https://benchmarks.webrtc.ventures/asr-latency/"' in homepage
    assert 'meta name="twitter:card" content="summary_large_image"' in homepage
    assert '"@type": "WebPage"' in homepage
    assert '"@type": "Dataset"' in homepage
    assert '"@type": "Organization"' in homepage
    assert '"@type": "FAQPage"' in homepage
    assert '"What does this benchmark actually measure?"' in homepage
    assert '"contentUrl": "https://benchmarks.webrtc.ventures/asr-latency/benchmark-results/manifest.json"' in homepage


def test_homepage_shell_keeps_operator_sections_and_manifest_hook() -> None:
    homepage = HOMEPAGE_PATH.read_text(encoding="utf-8")

    assert 'id="generated-at"' in homepage
    assert 'id="static-summary"' in homepage
    assert 'BEGIN GENERATED:generated-at' in homepage
    assert 'BEGIN GENERATED:static-summary' in homepage
    assert 'id="hero-side"' in homepage
    assert 'id="snapshot-grid"' in homepage
    assert 'id="story-grid"' in homepage
    assert 'id="comparison-wrap"' in homepage
    assert 'id="lane-grid"' in homepage
    assert 'id="contract-grid"' in homepage
    assert 'id="faq"' in homepage
    assert 'class="cta-grid"' in homepage
    assert 'class="faq-grid"' in homepage
    assert 'id="archive-grid"' in homepage
    assert "Published benchmark snapshot" in homepage
    assert "Choose the next decision path" in homepage
    assert "Launch FAQ for benchmark readers" in homepage
    assert "Turn the benchmark into a launch decision" in homepage
    assert "What does this benchmark actually measure?" in homepage
    assert "Benchmark appendix" in homepage
    assert "benchmark-results/manifest.json" in homepage
    assert "WebRTC.ventures benchmarks" in homepage
    assert "Built by WebRTC.ventures" in homepage
    assert "Reference WER" in homepage
    assert "external context rather than official rtc-asr measurements" in homepage
    assert "Open detail page" in homepage
    assert "SHA-256" in homepage
    assert 'function formatHostSummary(entry)' in homepage
    assert 'Host profile' in homepage
    assert 'Efficiency signals' in homepage


def test_manifest_artifacts_are_checked_in_or_explicitly_missing() -> None:
    manifest = build_manifest(RESULTS_DIR, TRACKS_PATH)
    tracked_artifacts = {track["artifact_path"] for track in manifest["tracks"] if track["artifact_path"]}
    manifest_artifacts = {artifact["artifact_path"] for artifact in manifest["artifacts"] if artifact["artifact_path"]}
    expected_files = {
        f"benchmark-results/{path.name}"
        for path in RESULTS_DIR.glob("*.json")
        if path.name not in {"manifest.json", "tracks.json"}
        and manifest_module.is_asr_payload(json.loads(path.read_text(encoding="utf-8")))
    }

    assert tracked_artifacts <= expected_files
    assert manifest_artifacts == expected_files


def test_render_manifest_matches_checked_in_output() -> None:
    generated = build_manifest(RESULTS_DIR, TRACKS_PATH)
    checked_in = json.loads((RESULTS_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert comparable_manifest(generated) == comparable_manifest(checked_in)


def test_manifest_write_preserves_generated_at_when_content_is_unchanged(tmp_path: Path) -> None:
    manifest = build_manifest(DEFAULT_RESULTS_DIR, TRACKS_PATH)
    manifest["generated_at"] = "2026-06-20T00:00:00Z"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(render_manifest(manifest), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--output", str(manifest_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    written = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert written["generated_at"] == "2026-06-20T00:00:00Z"
    assert comparable_manifest(written) == comparable_manifest(build_manifest(DEFAULT_RESULTS_DIR, TRACKS_PATH))


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


def test_prerender_check_fails_for_orphaned_detail_pages(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    manifest_path = repo_root / RESULTS_DIR / "manifest.json"
    homepage_path = repo_root / HOMEPAGE_PATH
    detail_dir = tmp_path / "pages"
    detail_dir.mkdir()
    (detail_dir / "orphaned-artifact.html").write_text("<html>old page</html>\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(PRERENDER_MODULE_PATH),
            "--manifest",
            str(manifest_path),
            "--homepage",
            str(homepage_path),
            "--detail-dir",
            str(detail_dir),
            "--check",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert f"Benchmark detail pages are stale: {detail_dir}" in result.stderr



def test_homepage_keeps_operator_sections_without_duplicate_matrix() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert "Advanced ASR comparison matrix" not in html
    assert "What matters for low-latency ASR" in html
    assert "Visible benchmark lanes" in html
    assert 'id="lane-toggle"' in html
    assert 'id="lane-panel" hidden' in html
    assert 'id="archive-toggle"' in html
    assert 'id="archive-panel" hidden' in html
    assert 'aria-expanded="false"' in html
    assert "Benchmark lanes" in html
    assert "Appendix" in html
    assert "Best operator balance" in html
    assert "entry.derived?.overall_score" in html


def test_homepage_filters_blocked_tracks_from_visible_results() -> None:
    html = Path("docs/index.html").read_text(encoding="utf-8")

    assert 'track.artifact_path && track.status !== "blocked"' in html
    assert "Tracked lanes without publishable artifacts stay out of the front-end comparison flow." in html


def test_homepage_initial_html_contains_prerendered_summary() -> None:
    homepage = HOMEPAGE_PATH.read_text(encoding="utf-8")

    assert "Launch readout" in homepage
    assert "The main ranking stays focused on fully comparable live lanes" in homepage
    assert "Recommended default" in homepage
    assert "Benchmark appendix" in homepage
    assert "Artifacts kept out of the primary ranking" not in homepage
    assert "Open detail page" in homepage
    assert "SHA-256" in homepage
    assert "open JSON" not in homepage
    assert "Loading benchmark manifest..." not in homepage


def test_manifest_surfaces_warning_counts_and_codes(tmp_path: Path) -> None:
    artifact_path = tmp_path / "demo-warnings-2026-06-20.json"
    artifact_path.write_text(
        json.dumps(
            {
                "backend": {"name": "demo", "model": "warn-v1", "device": "cpu", "compute_type": "int8"},
                "rest": {"mean_ms": 100, "p95_ms": 140, "rtf_mean": 0.4},
                "streaming": {"partial_mean_ms": 50, "partial_p95_ms": 80, "final_mean_ms": 120, "final_p95_ms": 180},
                "environment": {"date_utc": "2026-06-20T00:00:00Z"},
                "summary": {"warning_codes": ["stream_jitter", "partial_dropped"]},
                "samples": [
                    {"warnings_received": 1, "warning_codes": ["partial_dropped"]},
                    {"warnings_received": 2, "warning_codes": ["stream_canceled", "partial_dropped"]},
                ],
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
                        "slug": "demo-warnings",
                        "label": "demo warnings",
                        "backend": "demo",
                        "model": "warn-v1",
                        "device": "cpu",
                        "compute": "int8",
                        "lane": "local",
                        "status": "validated",
                        "status_detail": "warning coverage",
                        "target_sample_count": 2,
                        "run_command": "make benchmark",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = build_manifest(tmp_path, tracks_path)
    track = manifest["tracks"][0]
    detail = render_detail_page(track, json.loads(artifact_path.read_text(encoding="utf-8")))

    assert track["warnings"] == {
        "received_total": 3,
        "rate_per_sample": 1.5,
        "codes": ["partial_dropped", "stream_canceled", "stream_jitter"],
    }
    assert "<span class=\"label\">Warnings</span><div class=\"value\">3</div>" in detail
    assert "Rate 1.500 per sample · Codes: partial_dropped, stream_canceled, stream_jitter" in detail
