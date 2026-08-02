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
    concurrency: int | None = 1,
):
    settings = {
        "partial_interval_ms": 100,
        "realtime_pace": True,
        "scenario": "voice-agent-20ms-80ms",
        "metadata": {"fixture": "smoke.wav"},
    }
    if concurrency is not None:
        settings["concurrency"] = concurrency
    return {
        "audio": {
            "sample_rate": 16000,
            "frame_ms": 20,
            "send_aggregate_ms": 80,
        },
        "settings": settings,
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
            "time_to_final_after_finalize_ms": {"p95": final},
            "audio_end_finalization_rtf": {"p95": 0.2},
            "decoder_compute_rtf": {"p95": 0.1},
            "asr_decode_p95_ms": {"p95": 20.0},
            "successful_runs": {"p95": 1.0},
            "protocol_errors": {"p95": errors},
        },
    }


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


def test_main_writes_comparison_report(tmp_path) -> None:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    output = tmp_path / "report.json"
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
