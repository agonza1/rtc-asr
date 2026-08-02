from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


LATENCY_METRICS = [
    "time_to_first_interim_ms",
    "partial_cadence_p95_ms",
    "time_to_final_after_finalize_ms",
    "audio_end_finalization_rtf",
    "decoder_compute_rtf",
    "asr_decode_p95_ms",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two Local STT v1 streaming benchmark artifacts and produce a real-time ASR recommendation."
    )
    parser.add_argument("--baseline", type=Path, required=True, help="Current default/rolling-window artifact JSON")
    parser.add_argument("--candidate", type=Path, required=True, help="Candidate backend artifact JSON, for example Vosk stateful")
    parser.add_argument("--candidate-name", default="candidate", help="Human-readable candidate backend label")
    parser.add_argument("--baseline-name", default="baseline", help="Human-readable baseline backend label")
    parser.add_argument(
        "--latency-win-percent",
        type=float,
        default=10.0,
        help="Minimum p95 latency improvement required on key live metrics",
    )
    parser.add_argument("--output", type=Path, help="Optional path for JSON comparison output")
    return parser.parse_args(argv)


def load_artifact(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def compare_artifacts(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_path: Path,
    candidate_path: Path,
    baseline_name: str,
    candidate_name: str,
    latency_win_percent: float = 10.0,
) -> dict[str, Any]:
    benchmark_input_gaps = compare_benchmark_inputs(baseline, candidate)
    metric_comparison = {
        metric: compare_metric(baseline, candidate, metric)
        for metric in LATENCY_METRICS
    }
    transcript = compare_transcripts(baseline, candidate)
    success = compare_success(baseline, candidate)
    recommendation = recommend(
        metric_comparison=metric_comparison,
        transcript=transcript,
        success=success,
        benchmark_input_gaps=benchmark_input_gaps,
        candidate_name=candidate_name,
        latency_win_percent=latency_win_percent,
    )
    return {
        "kind": "local-stt-v1-streaming-backend-comparison",
        "baseline": describe_artifact(baseline, baseline_path, baseline_name),
        "candidate": describe_artifact(candidate, candidate_path, candidate_name),
        "comparison": metric_comparison,
        "success": success,
        "transcript_sanity": transcript,
        "benchmark_input_gaps": benchmark_input_gaps,
        "recommendation": recommendation,
    }


def compare_benchmark_inputs(baseline: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    baseline_audio = normalized_audio(baseline)
    candidate_audio = normalized_audio(candidate)
    baseline_settings = normalized_settings(baseline)
    candidate_settings = normalized_settings(candidate)
    baseline_environment = normalized_environment(baseline)
    candidate_environment = normalized_environment(candidate)
    gaps = []
    for key in ("source", "sample_rate", "channels", "format", "frame_ms", "duration_ms", "send_aggregate_ms"):
        baseline_value = baseline_audio.get(key)
        candidate_value = candidate_audio.get(key)
        if baseline_value != candidate_value:
            gaps.append(f"benchmark_input:audio.{key}: baseline={baseline_value!r} candidate={candidate_value!r}")
    for key in (
        "partial_interval_ms",
        "receive_timeout_seconds",
        "realtime_pace",
        "send_aggregate_ms",
        "concurrency",
        "scenario",
    ):
        baseline_value = baseline_settings.get(key)
        candidate_value = candidate_settings.get(key)
        if baseline_value != candidate_value:
            gaps.append(f"benchmark_input:settings.{key}: baseline={baseline_value!r} candidate={candidate_value!r}")
    for key in ("platform", "machine", "processor", "cpu_logical_cores", "memory_total_mb"):
        baseline_value = baseline_environment.get(key)
        candidate_value = candidate_environment.get(key)
        if baseline_value != candidate_value:
            gaps.append(f"benchmark_input:environment.{key}: baseline={baseline_value!r} candidate={candidate_value!r}")
    return gaps


def normalized_audio(artifact: dict[str, Any]) -> dict[str, Any]:
    audio = artifact.get("audio", {}) if isinstance(artifact.get("audio"), dict) else {}
    return {
        "source": audio.get("source"),
        "sample_rate": audio.get("sample_rate"),
        "channels": audio.get("channels"),
        "format": audio.get("format"),
        "frame_ms": audio.get("frame_ms"),
        "duration_ms": audio.get("duration_ms"),
        "send_aggregate_ms": audio.get("send_aggregate_ms"),
    }


def normalized_settings(artifact: dict[str, Any]) -> dict[str, Any]:
    settings = artifact.get("settings", {}) if isinstance(artifact.get("settings"), dict) else {}
    concurrency = settings.get("concurrency")
    if concurrency is None:
        concurrency = artifact.get("concurrency")
    if concurrency is None:
        concurrency = 1
    return {
        "partial_interval_ms": settings.get("partial_interval_ms"),
        "receive_timeout_seconds": settings.get("receive_timeout_seconds"),
        "realtime_pace": settings.get("realtime_pace"),
        "send_aggregate_ms": settings.get("send_aggregate_ms"),
        "concurrency": concurrency,
        "scenario": settings.get("scenario"),
    }


def normalized_environment(artifact: dict[str, Any]) -> dict[str, Any]:
    environment = artifact.get("environment", {}) if isinstance(artifact.get("environment"), dict) else {}
    return {
        "platform": environment.get("platform"),
        "machine": environment.get("machine"),
        "processor": environment.get("processor"),
        "cpu_logical_cores": environment.get("cpu_logical_cores"),
        "memory_total_mb": environment.get("memory_total_mb"),
    }


def compare_metric(baseline: dict[str, Any], candidate: dict[str, Any], metric: str) -> dict[str, float | None]:
    baseline_p95 = summary_value(baseline, metric, "p95")
    candidate_p95 = summary_value(candidate, metric, "p95")
    delta = None
    improvement_percent = None
    if baseline_p95 is not None and candidate_p95 is not None:
        delta = round(candidate_p95 - baseline_p95, 3)
        if baseline_p95 > 0:
            improvement_percent = round(((baseline_p95 - candidate_p95) / baseline_p95) * 100, 2)
    return {
        "baseline_p95": baseline_p95,
        "candidate_p95": candidate_p95,
        "delta_ms_or_rtf": delta,
        "candidate_improvement_percent": improvement_percent,
    }


def summary_value(artifact: dict[str, Any], metric: str, percentile: str) -> float | None:
    value = artifact.get("summary", {}).get(metric, {}).get(percentile)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def compare_success(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float | None]:
    return {
        "baseline_successful_runs_p95": summary_value(baseline, "successful_runs", "p95"),
        "candidate_successful_runs_p95": summary_value(candidate, "successful_runs", "p95"),
        "baseline_protocol_errors_p95": summary_value(baseline, "protocol_errors", "p95"),
        "candidate_protocol_errors_p95": summary_value(candidate, "protocol_errors", "p95"),
    }


def compare_transcripts(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    baseline_texts = final_transcripts(baseline)
    candidate_texts = final_transcripts(candidate)
    baseline_words = token_set(" ".join(baseline_texts))
    candidate_words = token_set(" ".join(candidate_texts))
    shared_words = baseline_words & candidate_words
    union_words = baseline_words | candidate_words
    overlap = round(len(shared_words) / len(union_words), 3) if union_words else None
    return {
        "baseline_final_transcripts": baseline_texts,
        "candidate_final_transcripts": candidate_texts,
        "exact_match": bool(baseline_texts and baseline_texts == candidate_texts),
        "word_overlap_ratio": overlap,
        "candidate_has_final_transcript": bool(candidate_texts and all(text.strip() for text in candidate_texts)),
    }


def final_transcripts(artifact: dict[str, Any]) -> list[str]:
    samples = artifact.get("samples", [])
    if not isinstance(samples, list):
        return []
    return [
        sample["final_transcript"]
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("final_transcript"), str)
    ]


def token_set(text: str) -> set[str]:
    return {token.strip(".,!?;:\"'()[]{}").lower() for token in text.split() if token.strip(".,!?;:\"'()[]{}")}


def recommend(
    *,
    metric_comparison: dict[str, dict[str, float | None]],
    transcript: dict[str, Any],
    success: dict[str, float | None],
    benchmark_input_gaps: list[str],
    candidate_name: str,
    latency_win_percent: float,
) -> dict[str, Any]:
    key_metrics = ["time_to_first_interim_ms", "time_to_final_after_finalize_ms"]
    missing = [
        metric
        for metric in key_metrics
        if metric_comparison[metric]["candidate_improvement_percent"] is None
    ]
    wins = [
        metric
        for metric in key_metrics
        if (metric_comparison[metric]["candidate_improvement_percent"] or 0.0) >= latency_win_percent
    ]
    protocol_errors = success["candidate_protocol_errors_p95"] or 0.0
    transcript_ok = bool(transcript["candidate_has_final_transcript"]) and (
        transcript["exact_match"] or (transcript["word_overlap_ratio"] is not None and transcript["word_overlap_ratio"] >= 0.8)
    )

    if benchmark_input_gaps:
        decision = "keep_experimental"
        rationale = "Re-run backend benchmarks with matching audio, pacing, concurrency, scenario, and hardware before comparing live latency."
    elif missing:
        decision = "keep_experimental"
        rationale = f"Missing comparable live p95 metrics for {', '.join(missing)}."
    elif len(wins) == len(key_metrics) and transcript_ok and protocol_errors == 0:
        decision = "support_low_latency_backend"
        rationale = f"{candidate_name} clears the live latency gate without transcript or protocol regressions."
    else:
        decision = "keep_experimental"
        rationale = f"{candidate_name} does not yet clear the live latency, transcript, and protocol-error gate."

    return {
        "decision": decision,
        "rationale": rationale,
        "latency_win_percent_gate": latency_win_percent,
        "required_live_metrics": key_metrics,
        "batched_transcription_role": "nice_to_have_context_only",
        "blocking_gaps": benchmark_input_gaps,
    }


def describe_artifact(artifact: dict[str, Any], path: Path, name: str) -> dict[str, Any]:
    samples = artifact.get("samples", [])
    first_sample = samples[0] if isinstance(samples, list) and samples and isinstance(samples[0], dict) else {}
    settings = artifact.get("settings", {}) if isinstance(artifact.get("settings"), dict) else {}
    audio = artifact.get("audio", {}) if isinstance(artifact.get("audio"), dict) else {}
    return {
        "name": name,
        "artifact_path": str(path),
        "backend": first_sample.get("backend"),
        "model": first_sample.get("model"),
        "decoder_modes": first_sample.get("decoder_modes", []),
        "sample_rate": audio.get("sample_rate"),
        "frame_ms": audio.get("frame_ms"),
        "send_aggregate_ms": audio.get("send_aggregate_ms") or settings.get("send_aggregate_ms"),
        "partial_interval_ms": settings.get("partial_interval_ms"),
        "realtime_pace": settings.get("realtime_pace"),
        "concurrency": normalized_settings(artifact)["concurrency"],
        "scenario": settings.get("scenario"),
        "metadata": settings.get("metadata", {}),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = compare_artifacts(
        baseline=load_artifact(args.baseline),
        candidate=load_artifact(args.candidate),
        baseline_path=args.baseline,
        candidate_path=args.candidate,
        baseline_name=args.baseline_name,
        candidate_name=args.candidate_name,
        latency_win_percent=args.latency_win_percent,
    )
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
