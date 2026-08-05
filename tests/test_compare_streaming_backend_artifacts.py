from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_streaming_backend_artifacts.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_compare_streaming_backend_artifacts", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
compare_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_compare_streaming_backend_artifacts", compare_module)
SPEC.loader.exec_module(compare_module)


def artifact(
    *,
    backend: str,
    decoder_mode: str,
    first_partial: float,
    final: float,
    transcript: str,
    errors: int = 0,
    source: str = "fixtures/smoke.wav",
    sample_rate: int = 16000,
    channels: int = 1,
    audio_format: str = "pcm_s16le",
    frame_ms: int = 20,
    duration_ms: int = 1000,
    send_aggregate_ms: int = 80,
    partial_interval_ms: int = 100,
    receive_timeout_seconds: int = 5,
    realtime_pace: bool = True,
    scenario: str = "voice-agent-20ms-80ms",
    concurrency: int | None = 1,
    machine: str = "arm64",
    accelerator: str | None = None,
    peak_rss_mb: float | None = None,
    cpu_utilization_percent: float | None = None,
    package_power_watts: float | None = None,
    expected_final_transcript: str | None = None,
):
    settings = {
        "partial_interval_ms": partial_interval_ms,
        "receive_timeout_seconds": receive_timeout_seconds,
        "realtime_pace": realtime_pace,
        "send_aggregate_ms": send_aggregate_ms,
        "scenario": scenario,
        "metadata": {"fixture": source},
    }
    if concurrency is not None:
        settings["concurrency"] = concurrency
    payload = {
        "audio": {
            "source": source,
            "sample_rate": sample_rate,
            "channels": channels,
            "format": audio_format,
            "frame_ms": frame_ms,
            "duration_ms": duration_ms,
            "send_aggregate_ms": send_aggregate_ms,
        },
        "environment": {
            "platform": "TestOS",
            "machine": machine,
            "processor": "TestCPU",
            "cpu_logical_cores": 8,
            "memory_total_mb": 32768.0,
            "accelerator": accelerator,
            "peak_rss_mb": peak_rss_mb,
            "cpu_utilization_percent": cpu_utilization_percent,
            "package_power_watts": package_power_watts,
        },
        "settings": settings,
        "workload": {
            "kind": "local-stt-v1-streaming",
            "live_voice_agent_profile": (
                realtime_pace
                and sample_rate == 16000
                and frame_ms == 20
                and send_aggregate_ms in {80, 100, 120, 140, 160}
            ),
        },
        "samples": [
            {
                "backend": backend,
                "model": "tiny",
                "decoder_modes": [decoder_mode],
                "final_transcript": transcript,
            }
        ],
        "summary": {
            "time_to_first_interim_ms": {"p95": first_partial},
            "partial_cadence_p95_ms": {"p95": 100.0},
            "partial_cadence_jitter_ms": {"p95": 8.0},
            "time_to_final_after_finalize_ms": {"p95": final},
            "audio_end_finalization_rtf": {"p95": 0.2},
            "decoder_compute_rtf": {"p95": 0.1},
            "asr_decode_p95_ms": {"p95": 20.0},
            "successful_runs": {"p95": 1.0},
            "protocol_errors": {"p95": errors},
        },
    }
    if expected_final_transcript is not None:
        payload["expected_final_transcript"] = expected_final_transcript
    return payload


def test_compare_artifacts_recommends_support_when_candidate_wins_live_metrics() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["candidate"]["backend"] == "vosk"
    assert report["candidate"]["decoder_modes"] == ["stateful"]
    assert report["candidate"]["concurrency"] == 1
    assert report["candidate"]["resource_metrics"] == {
        "peak_rss_mb": None,
        "cpu_utilization_percent": None,
        "package_power_watts": None,
    }
    assert report["comparison"]["time_to_first_interim_ms"]["candidate_improvement_percent"] == 40.0
    assert report["transcript_sanity"]["exact_match"] is True
    assert report["benchmark_input_gaps"] == []
    assert report["recommendation"]["decision"] == "support_low_latency_backend"
    assert report["recommendation"]["batched_transcription_role"] == "nice_to_have_context_only"


def test_compare_artifacts_keeps_candidate_experimental_on_transcript_regression() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="please transfer me to billing",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=200.0,
            final=100.0,
            transcript="",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["transcript_sanity"]["candidate_has_final_transcript"] is False
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["transcript_blocking_gaps"] == [
        "transcript_sanity:candidate.missing_final_transcript"
    ]


def test_compare_artifacts_reports_missing_tail_and_repeated_token_drift() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="transfer transfer me to billing now",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=200.0,
            final=100.0,
            transcript="transfer me to billing billing",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    sanity = report["transcript_sanity"]
    assert sanity["word_overlap_ratio"] == 0.8
    assert sanity["baseline_word_count"] == 6
    assert sanity["candidate_word_count"] == 5
    assert sanity["word_count_delta"] == -1
    assert sanity["candidate_missing_token_counts"] == {"now": 1, "transfer": 1}
    assert sanity["candidate_extra_token_counts"] == {"billing": 1}


def test_compare_artifacts_reports_low_word_overlap_as_transcript_gap() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="please transfer me to billing",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=200.0,
            final=100.0,
            transcript="turn on the living room lights",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["transcript_sanity"]["word_overlap_ratio"] < 0.8
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["transcript_blocking_gaps"] == [
        "transcript_sanity:candidate.low_word_overlap"
    ]


def test_compare_artifacts_blocks_missing_final_transcript_in_any_candidate_run() -> None:
    baseline = artifact(
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_partial=500.0,
        final=300.0,
        transcript="hello world",
    )
    candidate = artifact(
        backend="vosk",
        decoder_mode="stateful",
        first_partial=200.0,
        final=100.0,
        transcript="hello world",
    )
    candidate["samples"].append({
        "backend": "vosk",
        "model": "tiny",
        "decoder_modes": ["stateful"],
    })

    report = compare_module.compare_artifacts(
        baseline=baseline,
        candidate=candidate,
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["transcript_sanity"]["candidate_sample_count"] == 2
    assert report["transcript_sanity"]["candidate_missing_final_transcript_runs"] == 1
    assert report["transcript_sanity"]["candidate_has_final_transcript"] is False
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["transcript_blocking_gaps"] == [
        "transcript_sanity:candidate.missing_final_transcript"
    ]


def test_compare_artifacts_blocks_expected_final_transcript_mismatch() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello hello final tail",
            expected_final_transcript="hello hello final tail",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=200.0,
            final=100.0,
            transcript="hello final tail",
            expected_final_transcript="hello hello final tail",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    sanity = report["transcript_sanity"]
    assert sanity["expected_final_transcript"] == "hello hello final tail"
    assert sanity["candidate_expected_match_runs"] == 0
    assert sanity["candidate_expected_mismatch_runs"] == 1
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["transcript_blocking_gaps"] == [
        "transcript_sanity:candidate.expected_final_transcript_mismatch"
    ]


def test_compare_artifacts_weighs_latency_win_against_resource_regression() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            peak_rss_mb=800.0,
            cpu_utilization_percent=100.0,
            package_power_watts=5.0,
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            peak_rss_mb=900.0,
            cpu_utilization_percent=140.0,
            package_power_watts=5.5,
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["resource_comparison"]["peak_rss_mb"] == {
        "baseline": 800.0,
        "candidate": 900.0,
        "delta": 100.0,
        "candidate_increase_percent": 12.5,
    }
    assert report["resource_comparison"]["cpu_utilization_percent"]["candidate_increase_percent"] == 40.0
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["resource_regressions"] == ["cpu_utilization_percent"]


def test_compare_artifacts_blocks_concurrency_mismatch() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            concurrency=None,
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            concurrency=3,
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["baseline"]["concurrency"] == 1
    assert report["candidate"]["concurrency"] == 3
    assert report["benchmark_input_gaps"] == [
        "benchmark_input:settings.concurrency: baseline=1 candidate=3"
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"
    assert report["recommendation"]["blocking_gaps"] == report["benchmark_input_gaps"]

def test_compare_artifacts_blocks_audio_and_pacing_mismatch() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            send_aggregate_ms=80,
            scenario="voice-agent-20ms-80ms",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            source="fixtures/different.wav",
            send_aggregate_ms=160,
            scenario="voice-agent-20ms-160ms",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == [
        "benchmark_input:audio.source: baseline='fixtures/smoke.wav' candidate='fixtures/different.wav'",
        "benchmark_input:audio.send_aggregate_ms: baseline=80 candidate=160",
        "benchmark_input:settings.send_aggregate_ms: baseline=80 candidate=160",
        "benchmark_input:settings.scenario: baseline='voice-agent-20ms-80ms' candidate='voice-agent-20ms-160ms'",
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"


def test_compare_artifacts_blocks_duration_timeout_and_hardware_mismatch() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            duration_ms=1000,
            receive_timeout_seconds=5,
            machine="arm64",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            duration_ms=2200,
            receive_timeout_seconds=10,
            machine="x86_64",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == [
        "benchmark_input:audio.duration_ms: baseline=1000 candidate=2200",
        "benchmark_input:settings.receive_timeout_seconds: baseline=5 candidate=10",
        "benchmark_input:environment.machine: baseline='arm64' candidate='x86_64'",
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"


def test_compare_artifacts_blocks_accelerator_mismatch() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            accelerator="cpu",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            accelerator="mps",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == [
        "benchmark_input:environment.accelerator: baseline='cpu' candidate='mps'"
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"


def test_compare_artifacts_blocks_non_live_voice_agent_workloads() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="rolling_window",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
            frame_ms=40,
            send_aggregate_ms=200,
            scenario="offline-ish-streaming",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="stateful",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
            frame_ms=40,
            send_aggregate_ms=200,
            scenario="offline-ish-streaming",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == [
        "benchmark_input:baseline.workload.live_voice_agent_profile: required=True actual=False",
        "benchmark_input:candidate.workload.live_voice_agent_profile: required=True actual=False",
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"


def test_compare_artifacts_requires_rolling_window_baseline_and_stateful_candidate() -> None:
    report = compare_module.compare_artifacts(
        baseline=artifact(
            backend="faster-whisper",
            decoder_mode="stateful",
            first_partial=500.0,
            final=300.0,
            transcript="hello world",
        ),
        candidate=artifact(
            backend="vosk",
            decoder_mode="rolling_window",
            first_partial=300.0,
            final=200.0,
            transcript="hello world",
        ),
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == [
        "benchmark_input:baseline.decoder_modes.rolling_window: required=True actual=['stateful']",
        "benchmark_input:candidate.decoder_modes.stateful: required=True actual=['rolling_window']",
    ]
    assert report["recommendation"]["decision"] == "keep_experimental"


def test_decoder_mode_gate_reads_mode_counts_when_modes_are_missing() -> None:
    baseline = artifact(
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_partial=500.0,
        final=300.0,
        transcript="hello world",
    )
    candidate = artifact(
        backend="vosk",
        decoder_mode="stateful",
        first_partial=300.0,
        final=200.0,
        transcript="hello world",
    )
    baseline["samples"][0].pop("decoder_modes")
    candidate["samples"][0].pop("decoder_modes")
    baseline["samples"][0]["decoder_mode_counts"] = {"rolling_window": 3}
    candidate["samples"][0]["decoder_mode_counts"] = {"stateful": 3}

    report = compare_module.compare_artifacts(
        baseline=baseline,
        candidate=candidate,
        baseline_path=Path("baseline.json"),
        candidate_path=Path("vosk.json"),
        baseline_name="default rolling-window",
        candidate_name="Vosk stateful",
    )

    assert report["benchmark_input_gaps"] == []
    assert report["baseline"]["decoder_modes"] == ["rolling_window"]
    assert report["candidate"]["decoder_modes"] == ["stateful"]
    assert report["recommendation"]["decision"] == "support_low_latency_backend"


def test_parse_args_accepts_review_friendly_path_aliases() -> None:
    args = compare_module.parse_args([
        "--baseline-artifact",
        "baseline.json",
        "--candidate-json",
        "candidate.json",
        "--json-output",
        "comparison.json",
    ])

    assert args.baseline == Path("baseline.json")
    assert args.candidate == Path("candidate.json")
    assert args.output == Path("comparison.json")


def test_parse_args_accepts_json_report_output_aliases() -> None:
    for alias in ("--output-json", "--report-json", "--json-report"):
        args = compare_module.parse_args([
            "--baseline-json",
            "baseline.json",
            "--candidate-json",
            "candidate.json",
            alias,
            "report.json",
        ])

        assert args.output == Path("report.json")


def test_parse_args_accepts_review_friendly_gate_and_label_aliases() -> None:
    args = compare_module.parse_args([
        "--baseline-json",
        "baseline.json",
        "--candidate-json",
        "candidate.json",
        "--baseline-label",
        "rolling window",
        "--candidate-backend",
        "Vosk stateful",
        "--latency-gate-percent",
        "15",
    ])

    assert args.baseline_name == "rolling window"
    assert args.candidate_name == "Vosk stateful"
    assert args.latency_win_percent == 15.0


def test_main_writes_comparison_report(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "reports" / "report.json"
    baseline.write_text(json.dumps(artifact(
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_partial=500.0,
        final=300.0,
        transcript="hello world",
    )))
    candidate.write_text(json.dumps(artifact(
        backend="vosk",
        decoder_mode="stateful",
        first_partial=300.0,
        final=200.0,
        transcript="hello world",
    )))

    exit_code = compare_module.main([
        "--baseline",
        str(baseline),
        "--candidate",
        str(candidate),
        "--candidate-name",
        "Vosk stateful",
        "--output",
        str(output),
    ])

    assert exit_code == 0
    saved = json.loads(output.read_text())
    assert saved["kind"] == "local-stt-v1-streaming-backend-comparison"
    assert saved["candidate"]["artifact_path"] == str(candidate)
