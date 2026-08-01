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
    protocol_errors_p95: float = 0.0,
    final_transcript: str = "hello from the voice agent",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "kind": "local-stt-v1-latency-benchmark",
                "target": {"transport": "tcp_ws", "url": "ws://localhost/v1/stt/stream"},
                "audio": {
                    "source": "fixtures/voice-agent.wav",
                    "sample_rate": 16000,
                    "channels": 1,
                    "format": "pcm_s16le",
                    "frame_ms": 20,
                    "duration_ms": 1000,
                    "send_aggregate_ms": send_aggregate_ms,
                },
                "settings": {
                    "partial_interval_ms": 100,
                    "receive_timeout_seconds": 5,
                    "realtime_pace": True,
                    "send_aggregate_ms": send_aggregate_ms,
                    "scenario": "voice-agent-80ms-aggregation",
                },
                "runs": 5,
                "samples": [
                    {
                        "backend": backend,
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
    }
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
    assert comparison["recommendation"] == "Re-run backend benchmarks with matching audio, pacing, and scenario settings."


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
        "Keep vosk:stateful experimental until final transcripts match the baseline sanity check."
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
    assert "| time_to_first_interim_ms | 80 ms |" in markdown
    assert "| faster-whisper:rolling_window |" in markdown
    assert "| vosk:stateful |" in markdown
    assert "hello from the voice agent" in markdown
    assert "- none" in markdown


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
            str(baseline),
            str(candidate),
        ]
    ) == 0

    markdown = report_path.read_text(encoding="utf8")
    assert "Baseline: faster-whisper:rolling_window" in markdown
    assert "Candidate: vosk:stateful" in markdown
    assert "Blocking gaps:" in markdown
