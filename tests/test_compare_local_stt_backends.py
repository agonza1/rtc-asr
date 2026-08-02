from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "compare_local_stt_backends.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_compare_local_stt_backends", MODULE_PATH)
compare_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_compare_local_stt_backends", compare_module)
assert SPEC.loader is not None
SPEC.loader.exec_module(compare_module)


def write_artifact(
    path: Path,
    *,
    backend: str,
    decoder_mode: str,
    first_interim_p95: float,
    final_after_finalize_p95: float = 80.0,
    send_aggregate_ms: int = 80,
    concurrency: int = 1,
    protocol_errors_p95: float = 0.0,
    partial_cadence_p95: float | None = 100.0,
    partial_cadence_jitter_p95: float | None = 8.0,
    audio_end_finalization_rtf_p95: float | None = 0.08,
    audio_send_duration_p95: float | None = 1000.0,
    send_receive_overlap_p95: float | None = 800.0,
    pcm16_normalization_p95: float | None = 1.0,
    decoder_compute_rtf_p95: float | None = 0.35,
    final_transcript: str = "hello from the voice agent",
    peak_rss_mb: float | None = 512.5,
    cpu_utilization_percent: float | None = 42.0,
    machine: str = "arm64",
    model: str = "tiny-fixture",
    expected_final_transcript: str | None = None,
    scenario: str | None = "voice-agent-80ms-aggregation",
    frame_ms: int = 20,
    realtime_pace: bool = True,
) -> Path:
    partial_cadence_summary = (
        {"p50": partial_cadence_p95 - 10.0, "p95": partial_cadence_p95, "p99": partial_cadence_p95 + 10.0}
        if partial_cadence_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    partial_cadence_jitter_summary = (
        {
            "p50": max(0.0, partial_cadence_jitter_p95 - 2.0),
            "p95": partial_cadence_jitter_p95,
            "p99": partial_cadence_jitter_p95 + 2.0,
        }
        if partial_cadence_jitter_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    decoder_compute_summary = (
        {"p50": max(0.0, decoder_compute_rtf_p95 - 0.05), "p95": decoder_compute_rtf_p95, "p99": decoder_compute_rtf_p95 + 0.05}
        if decoder_compute_rtf_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    audio_end_finalization_rtf_summary = (
        {
            "p50": max(0.0, audio_end_finalization_rtf_p95 - 0.01),
            "p95": audio_end_finalization_rtf_p95,
            "p99": audio_end_finalization_rtf_p95 + 0.01,
        }
        if audio_end_finalization_rtf_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    audio_send_duration_summary = (
        {
            "p50": max(0.0, audio_send_duration_p95 - 10.0),
            "p95": audio_send_duration_p95,
            "p99": audio_send_duration_p95 + 10.0,
        }
        if audio_send_duration_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    send_receive_overlap_summary = (
        {
            "p50": max(0.0, send_receive_overlap_p95 - 10.0),
            "p95": send_receive_overlap_p95,
            "p99": send_receive_overlap_p95 + 10.0,
        }
        if send_receive_overlap_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    pcm16_normalization_summary = (
        {
            "p50": max(0.0, pcm16_normalization_p95 - 0.2),
            "p95": pcm16_normalization_p95,
            "p99": pcm16_normalization_p95 + 0.2,
        }
        if pcm16_normalization_p95 is not None
        else {"p50": None, "p95": None, "p99": None}
    )
    path.write_text(
        json.dumps(
            {
                "kind": "local-stt-v1-latency-benchmark",
                "benchmark": {
                    "command": (
                        "python scripts/bench_local_stt_stream.py --scenario voice-agent-80ms-aggregation "
                        "--send-aggregate-ms 80"
                    ),
                },
                "target": {"transport": "tcp_ws", "url": "ws://localhost/v1/stt/stream"},
                "workload": {
                    "kind": "local-stt-v1-streaming",
                    "live_voice_agent_profile": (
                        realtime_pace
                        and frame_ms == 20
                        and send_aggregate_ms in {80, 100, 120, 140, 160}
                    ),
                },
                "audio": {
                    "source": "fixtures/voice-agent.wav",
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": frame_ms,
                    "duration_ms": 1000,
                    "send_aggregate_ms": send_aggregate_ms,
                },
                "settings": {
                    "partial_interval_ms": 100,
                    "receive_timeout_seconds": 5,
                    "realtime_pace": realtime_pace,
                    "send_aggregate_ms": send_aggregate_ms,
                    "concurrency": concurrency,
                    "scenario": scenario,
                    "metadata": (
                        {"expected_final_transcript": expected_final_transcript}
                        if expected_final_transcript is not None
                        else {}
                    ),
                },
                "environment": {
                    "platform": "TestOS",
                    "machine": machine,
                    "processor": "TestCPU",
                    "cpu_logical_cores": 8,
                    "memory_total_mb": 32768.0,
                    "peak_rss_mb": peak_rss_mb,
                    "cpu_utilization_percent": cpu_utilization_percent,
                },
                "runs": 5,
                "samples": [
                    {
                        "backend": backend,
                        "model": model,
                        "decoder_modes": [decoder_mode],
                        "decoder_mode_counts": {decoder_mode: 3},
                        "final_transcript": final_transcript,
                    }
                ],
                "summary": {
                    "time_to_first_interim_ms": {
                        "p50": first_interim_p95 - 10,
                        "p95": first_interim_p95,
                        "p99": first_interim_p95 + 10,
                    },
                    "time_to_final_after_finalize_ms": {
                        "p50": final_after_finalize_p95 - 10,
                        "p95": final_after_finalize_p95,
                        "p99": final_after_finalize_p95 + 10,
                    },
                    "audio_send_queue_depth_p95_ms": {"p50": 1.0, "p95": 2.0, "p99": 3.0},
                    "asr_queue_delay_p95_ms": {"p50": 3.0, "p95": 4.0, "p99": 5.0},
                    "audio_end_finalization_rtf": audio_end_finalization_rtf_summary,
                    "audio_send_duration_ms": audio_send_duration_summary,
                    "send_receive_overlap_ms": send_receive_overlap_summary,
                    "partial_cadence_p95_ms": partial_cadence_summary,
                    "partial_cadence_jitter_ms": partial_cadence_jitter_summary,
                    "pcm16_normalization_p95_ms": pcm16_normalization_summary,
                    "decoder_compute_rtf": decoder_compute_summary,
                    "protocol_errors": {
                        "p50": 0.0,
                        "p95": protocol_errors_p95,
                        "p99": protocol_errors_p95,
                    },
                },
            }
        ),
        encoding="utf8",
    )
    return path


def test_compare_backends_recommends_supported_when_candidate_clears_latency_gate(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        final_after_finalize_p95=90.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        final_after_finalize_p95=85.0,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
        min_first_partial_win_ms=50.0,
    )

    assert comparison["candidate_status"] == "supported"
    assert comparison["blocking_gaps"] == []
    assert comparison["p95_deltas_ms"]["time_to_first_interim_ms"] == 70.0
    assert comparison["backends"]["vosk:stateful"]["transcript_sanity"] == {
        "runs_with_final_transcript": 1,
        "empty_final_transcript_runs": 0,
        "unique_final_transcripts": ["hello from the voice agent"],
        "expected_final_transcript": None,
        "expected_match_runs": None,
        "expected_mismatch_runs": None,
    }
    assert comparison["backends"]["vosk:stateful"]["resource_metrics"] == {
        "peak_rss_mb": 512.5,
        "cpu_utilization_percent": 42.0,
    }
    assert comparison["backends"]["vosk:stateful"]["model"] == "tiny-fixture"
    assert comparison["batched_transcription_role"] == "nice_to_have_context_only"
    assert comparison["recommendation"] == "Keep vosk:stateful as a supported low-latency backend."


def test_compare_backends_keeps_candidate_experimental_for_input_mismatch(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        send_aggregate_ms=80,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        send_aggregate_ms=160,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "benchmark_input:audio.send_aggregate_ms: baseline=80 candidate=160" in comparison["blocking_gaps"]
    assert "benchmark_input:settings.send_aggregate_ms: baseline=80 candidate=160" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Re-run backend benchmarks with matching audio, pacing, scenario settings, and hardware."
    )


def test_compare_backends_keeps_candidate_experimental_for_concurrency_mismatch(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        concurrency=1,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        concurrency=3,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "benchmark_input:settings.concurrency: baseline=1 candidate=3" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Re-run backend benchmarks with matching audio, pacing, scenario settings, and hardware."
    )


def test_compare_backends_keeps_candidate_experimental_for_hardware_mismatch(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        machine="arm64",
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        machine="x86_64",
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "benchmark_input:environment.machine: baseline='arm64' candidate='x86_64'" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Re-run backend benchmarks with matching audio, pacing, scenario settings, and hardware."
    )


def test_compare_backends_treats_missing_legacy_concurrency_as_single_session(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        concurrency=1,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        concurrency=1,
    )
    baseline_payload = json.loads(baseline.read_text(encoding="utf8"))
    del baseline_payload["settings"]["concurrency"]
    baseline.write_text(json.dumps(baseline_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "supported"
    assert not any("settings.concurrency" in gap for gap in comparison["blocking_gaps"])


def test_compare_backends_keeps_candidate_experimental_for_finalization_regression(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        final_after_finalize_p95=80.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        final_after_finalize_p95=130.0,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "finalization_regression" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Keep vosk:stateful experimental until final transcript latency no longer regresses."
    )


def test_compare_backends_keeps_candidate_experimental_for_final_transcript_mismatch(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        final_transcript="hello hello final tail",
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        final_transcript="hello final tail",
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "final_transcript_mismatch:vosk:stateful" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Keep vosk:stateful experimental until final transcripts match the baseline "
        "and expected voice-agent phrase sanity checks."
    )


def test_compare_backends_blocks_candidate_when_expected_repeated_phrase_is_missing(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
        final_transcript="hello hello final tail",
        expected_final_transcript="hello hello final tail",
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        final_transcript="hello final tail",
        expected_final_transcript="hello hello final tail",
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    candidate_sanity = comparison["backends"]["vosk:stateful"]["transcript_sanity"]
    assert comparison["candidate_status"] == "experimental"
    assert candidate_sanity["expected_final_transcript"] == "hello hello final tail"
    assert candidate_sanity["expected_match_runs"] == 0
    assert candidate_sanity["expected_mismatch_runs"] == 1
    assert "expected_final_transcript_mismatch:vosk:stateful" in comparison["blocking_gaps"]


def test_compare_backends_requires_voice_agent_streaming_scenario(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        scenario="batch-context",
        frame_ms=40,
        send_aggregate_ms=200,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "missing_voice_agent_streaming_scenario:vosk:stateful" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Run both backends through a voice-agent streaming scenario with 20 ms frames and 80-160 ms aggregation."
    )


def test_compare_backends_accepts_midrange_voice_agent_aggregation(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
        send_aggregate_ms=120,
        scenario="voice-agent-120ms-aggregation",
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        send_aggregate_ms=120,
        scenario="voice-agent-120ms-aggregation",
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "supported"
    assert not any("missing_voice_agent_streaming_scenario" in gap for gap in comparison["blocking_gaps"])


def test_compare_backends_requires_realtime_paced_voice_agent_stream(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        realtime_pace=False,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "missing_voice_agent_streaming_scenario:vosk:stateful" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Run both backends through a voice-agent streaming scenario with 20 ms frames and 80-160 ms aggregation."
    )


def test_compare_backends_rejects_legacy_streaming_target(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
    )
    candidate_payload = json.loads(candidate.read_text(encoding="utf8"))
    candidate_payload["target"] = {"transport": "tcp_ws", "url": "ws://localhost/ws/stream"}
    candidate_payload["workload"] = {"kind": "legacy-buffered-streaming"}
    candidate.write_text(json.dumps(candidate_payload), encoding="utf8")

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "missing_local_stt_v1_streaming_workload:vosk:stateful" in comparison["blocking_gaps"]
    assert "missing_local_stt_v1_streaming_target:vosk:stateful" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Run both backends through the Local STT v1 streaming benchmark instead of batch or legacy transport artifacts."
    )


def test_compare_backends_keeps_candidate_experimental_for_empty_final_transcript(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=220.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=140.0,
        final_transcript=" ",
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "missing_final_transcript:vosk:stateful" in comparison["blocking_gaps"]
    assert "empty_final_transcript:vosk:stateful" in comparison["blocking_gaps"]


def test_format_markdown_report_includes_backend_decision_evidence(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
        final_after_finalize_p95=90.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        final_after_finalize_p95=85.0,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    markdown = compare_module.format_markdown_report(comparison)

    assert "# Local STT v1 Backend Comparison" in markdown
    assert "Candidate status: supported" in markdown
    assert "Recommendation: Keep vosk:stateful as a supported low-latency backend." in markdown
    assert "Batched transcription role: nice_to_have_context_only" in markdown
    assert "| time_to_first_interim_ms | 80 ms |" in markdown
    assert "| faster-whisper:rolling_window | tiny-fixture |" in markdown
    assert "| vosk:stateful | tiny-fixture |" in markdown
    assert "not provided" in markdown
    assert "hello from the voice agent" in markdown
    assert "- none" in markdown


def test_cli_creates_report_parent_directories(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
        final_after_finalize_p95=90.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        final_after_finalize_p95=85.0,
    )
    output = tmp_path / "reports" / "nested" / "comparison.json"
    markdown_output = tmp_path / "reports" / "nested" / "comparison.md"

    status = compare_module.main(
        [
            "--baseline",
            "faster-whisper:rolling_window",
            "--candidate",
            "vosk:stateful",
            "--output",
            str(output),
            "--markdown-output",
            str(markdown_output),
            str(baseline),
            str(candidate),
        ]
    )

    assert status == 0
    assert json.loads(output.read_text(encoding="utf8"))["candidate_status"] == "supported"
    markdown = markdown_output.read_text(encoding="utf8")
    assert "Candidate status: supported" in markdown
    assert "Run context:" in markdown
    assert "Command: python scripts/bench_local_stt_stream.py" in markdown
    assert "Model: tiny-fixture" in markdown
    assert "Hardware: cpu_logical_cores=8, machine=arm64, memory_total_mb=32768.0" in markdown
    assert "Resource metrics: cpu_utilization_percent=42.0, peak_rss_mb=512.5" in markdown
    assert "Settings: concurrency=1" in markdown
    assert "partial_interval_ms=100" in markdown
    assert "| partial_cadence_p95_ms | 0 ms |" in markdown
    assert "| audio_end_finalization_rtf | 0 |" in markdown
    assert "| audio_send_duration_ms | 0 ms |" in markdown
    assert "| send_receive_overlap_ms | 0 ms |" in markdown
    assert "| pcm16_normalization_p95_ms | 0 ms |" in markdown
    assert "| decoder_compute_rtf | 0 |" in markdown


def test_compare_backends_keeps_candidate_experimental_for_missing_live_duration_or_compute_metrics(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        audio_end_finalization_rtf_p95=None,
        audio_send_duration_p95=None,
        send_receive_overlap_p95=None,
        partial_cadence_p95=None,
        pcm16_normalization_p95=None,
        decoder_compute_rtf_p95=None,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
    )

    assert comparison["candidate_status"] == "experimental"
    assert "missing_metric:vosk:stateful:audio_end_finalization_rtf" in comparison["blocking_gaps"]
    assert "missing_metric:vosk:stateful:audio_send_duration_ms" in comparison["blocking_gaps"]
    assert "missing_metric:vosk:stateful:send_receive_overlap_ms" in comparison["blocking_gaps"]
    assert "missing_metric:vosk:stateful:partial_cadence_p95_ms" in comparison["blocking_gaps"]
    assert "missing_metric:vosk:stateful:pcm16_normalization_p95_ms" in comparison["blocking_gaps"]
    assert "missing_metric:vosk:stateful:decoder_compute_rtf" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == (
        "Run backend benchmarks with complete streaming latency, cadence, and decoder compute metrics."
    )


def test_compare_backends_can_require_resource_metrics(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        peak_rss_mb=None,
        cpu_utilization_percent=None,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
        require_resource_metrics=True,
    )

    assert comparison["candidate_status"] == "experimental"
    assert comparison["resource_metrics_required"] is True
    assert "missing_resource_metric:vosk:stateful:peak_rss_mb" in comparison["blocking_gaps"]
    assert "missing_resource_metric:vosk:stateful:cpu_utilization_percent" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == "Re-run backend benchmarks with service resource monitoring enabled."


def test_compare_backends_can_require_concurrent_session_load(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
        concurrency=1,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
        concurrency=1,
    )

    comparison = compare_module.compare_artifacts(
        [baseline, candidate],
        baseline_key="faster-whisper:rolling_window",
        candidate_key="vosk:stateful",
        min_concurrency=2,
    )

    assert comparison["candidate_status"] == "experimental"
    assert comparison["min_concurrency"] == 2
    assert "insufficient_concurrency:faster-whisper:rolling_window: required>=2 actual=1" in comparison["blocking_gaps"]
    assert "insufficient_concurrency:vosk:stateful: required>=2 actual=1" in comparison["blocking_gaps"]
    assert comparison["recommendation"] == "Run backend benchmarks at the required concurrent-session load."


def test_main_writes_markdown_report(tmp_path: Path) -> None:
    baseline = write_artifact(
        tmp_path / "rolling.json",
        backend="faster-whisper",
        decoder_mode="rolling_window",
        first_interim_p95=230.0,
    )
    candidate = write_artifact(
        tmp_path / "vosk.json",
        backend="vosk",
        decoder_mode="stateful",
        first_interim_p95=150.0,
    )
    report_path = tmp_path / "backend-comparison.md"

    assert compare_module.main(
        [
            "--baseline",
            "faster-whisper:rolling_window",
            "--candidate",
            "vosk:stateful",
            "--markdown-output",
            str(report_path),
            "--require-resource-metrics",
            str(baseline),
            str(candidate),
        ]
    ) == 0

    markdown = report_path.read_text(encoding="utf8")
    assert "Baseline: faster-whisper:rolling_window" in markdown
    assert "Candidate: vosk:stateful" in markdown
    assert "Minimum concurrency: 1" in markdown
    assert "Resource metrics required: True" in markdown
    assert "Blocking gaps:" in markdown
