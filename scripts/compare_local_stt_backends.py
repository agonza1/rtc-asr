from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from compare_local_stt_transports import (
    KEY_METRICS as TRANSPORT_KEY_METRICS,
    load_artifact,
    metric_percentiles,
)


DEFAULT_MIN_FIRST_PARTIAL_WIN_MS = 50.0
COMPARABLE_AUDIO_KEYS = ("source", "sample_rate", "channels", "format", "frame_ms", "duration_ms", "send_aggregate_ms")
COMPARABLE_SETTING_KEYS = (
    "partial_interval_ms",
    "receive_timeout_seconds",
    "realtime_pace",
    "send_aggregate_ms",
    "concurrency",
    "scenario",
)
BACKEND_KEY_METRICS = (
    *TRANSPORT_KEY_METRICS,
    "partial_cadence_p95_ms",
    "decoder_compute_rtf",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 backend benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--baseline", required=True, help="Baseline backend key, for example faster-whisper:rolling_window")
    parser.add_argument("--candidate", required=True, help="Candidate backend key, for example vosk:stateful")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
    parser.add_argument("--markdown-output", type=Path, help="Optional Markdown decision report output path")
    parser.add_argument(
        "--min-first-partial-win-ms",
        type=float,
        default=DEFAULT_MIN_FIRST_PARTIAL_WIN_MS,
        help="Minimum candidate P95 first-partial win required for a supported-backend recommendation",
    )
    parser.add_argument(
        "--require-resource-metrics",
        action="store_true",
        help="Require each backend artifact to include peak RSS and CPU utilization evidence",
    )
    return parser.parse_args(argv)


def backend_key(artifact: dict[str, Any]) -> str:
    samples = artifact.get("samples")
    sample: dict[str, Any] = {}
    if isinstance(samples, list) and samples and isinstance(samples[0], dict):
        sample = samples[0]
    backend = first_string(
        sample.get("backend"),
        artifact.get("backend"),
        nested_value(artifact, "target", "backend"),
        nested_value(artifact, "settings", "backend"),
        "unknown",
    )
    decoder_mode = first_string(
        first_decoder_mode(sample),
        nested_value(artifact, "local_stt_decoder", "default_mode"),
        nested_value(artifact, "target", "decoder_mode"),
        nested_value(artifact, "settings", "decoder_mode"),
        "unknown",
    )
    return f"{backend}:{decoder_mode}"


def first_decoder_mode(sample: dict[str, Any]) -> str | None:
    modes = sample.get("decoder_modes")
    if isinstance(modes, list):
        for mode in modes:
            if isinstance(mode, str) and mode:
                return mode
    mode_counts = sample.get("decoder_mode_counts")
    if isinstance(mode_counts, dict):
        for mode in sorted(mode_counts):
            if isinstance(mode, str) and mode:
                return mode
    return None


def first_string(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return "unknown"


def nested_value(mapping: dict[str, Any], *keys: str) -> Any:
    current: Any = mapping
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def comparable_snapshot(artifact: dict[str, Any]) -> dict[str, Any]:
    audio = artifact.get("audio") if isinstance(artifact.get("audio"), dict) else {}
    settings = artifact.get("settings") if isinstance(artifact.get("settings"), dict) else {}
    return {
        "audio": {key: audio.get(key) for key in COMPARABLE_AUDIO_KEYS},
        "settings": {key: settings.get(key) for key in COMPARABLE_SETTING_KEYS},
    }


def protocol_error_free(artifact: dict[str, Any]) -> bool:
    diagnostics = artifact.get("diagnostics") if isinstance(artifact.get("diagnostics"), dict) else {}
    if diagnostics.get("protocol_error_total") not in (None, 0, 0.0):
        return False
    summary = artifact.get("summary") if isinstance(artifact.get("summary"), dict) else {}
    errors = metric_percentiles(summary, "protocol_errors")
    return all(value in (None, 0.0) for value in errors.values())


def transcript_sanity(artifact: dict[str, Any]) -> dict[str, Any]:
    samples = artifact.get("samples")
    normalized_transcripts: list[str] = []
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            transcript = sample.get("final_transcript")
            if isinstance(transcript, str):
                normalized_transcripts.append(normalize_transcript(transcript))
    nonempty_transcripts = [transcript for transcript in normalized_transcripts if transcript]
    return {
        "runs_with_final_transcript": len(nonempty_transcripts),
        "empty_final_transcript_runs": len(normalized_transcripts) - len(nonempty_transcripts),
        "unique_final_transcripts": sorted(set(nonempty_transcripts)),
    }


def resource_metrics(artifact: dict[str, Any]) -> dict[str, float | None]:
    environment = artifact.get("environment") if isinstance(artifact.get("environment"), dict) else {}
    return {
        "peak_rss_mb": float_or_none(environment.get("peak_rss_mb")),
        "cpu_utilization_percent": float_or_none(environment.get("cpu_utilization_percent")),
    }


def float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def benchmark_command(artifact: dict[str, Any]) -> str | None:
    benchmark = artifact.get("benchmark")
    if isinstance(benchmark, dict) and isinstance(benchmark.get("command"), str):
        return benchmark["command"]
    command = artifact.get("benchmark_command")
    return command if isinstance(command, str) else None


def normalize_transcript(value: str) -> str:
    return " ".join(value.lower().split())


def compare_artifacts(
    paths: list[Path],
    *,
    baseline_key: str,
    candidate_key: str,
    min_first_partial_win_ms: float = DEFAULT_MIN_FIRST_PARTIAL_WIN_MS,
    require_resource_metrics: bool = False,
) -> dict[str, Any]:
    if min_first_partial_win_ms <= 0:
        raise ValueError("min_first_partial_win_ms must be positive")

    artifacts = [load_artifact(path) for path in paths]
    by_backend: dict[str, dict[str, Any]] = {}
    for path, artifact in zip(paths, artifacts, strict=True):
        key = backend_key(artifact)
        if key in by_backend:
            raise ValueError(f"duplicate benchmark artifact for backend {key}")
        summary = artifact.get("summary")
        if not isinstance(summary, dict):
            raise ValueError(f"{path} is missing summary")
        by_backend[key] = {
            "path": str(path),
            "metrics": {metric: metric_percentiles(summary, metric) for metric in BACKEND_KEY_METRICS},
            "target": artifact.get("target") or {},
            "audio": artifact.get("audio") or {},
            "settings": artifact.get("settings") or {},
            "environment": artifact.get("environment") or {},
            "benchmark_command": benchmark_command(artifact),
            "runs": artifact.get("runs"),
            "protocol_error_free": protocol_error_free(artifact),
            "comparable_snapshot": comparable_snapshot(artifact),
            "transcript_sanity": transcript_sanity(artifact),
            "resource_metrics": resource_metrics(artifact),
        }

    missing = [key for key in (baseline_key, candidate_key) if key not in by_backend]
    input_gaps = comparable_input_gaps(by_backend, baseline_key, candidate_key) if not missing else []
    p95_deltas = p95_deltas_ms(by_backend, baseline_key, candidate_key) if not missing else {}
    first_partial_win = p95_deltas.get("time_to_first_interim_ms")
    final_delta = p95_deltas.get("time_to_final_after_finalize_ms")
    candidate_errors = None if missing else not by_backend[candidate_key]["protocol_error_free"]
    baseline_errors = None if missing else not by_backend[baseline_key]["protocol_error_free"]
    transcript_gaps = transcript_sanity_gaps(by_backend, baseline_key, candidate_key) if not missing else []

    blockers = []
    blockers.extend(f"missing_backend:{key}" for key in missing)
    blockers.extend(input_gaps)
    if candidate_errors:
        blockers.append(f"protocol_errors:{candidate_key}")
    if baseline_errors:
        blockers.append(f"protocol_errors:{baseline_key}")
    blockers.extend(transcript_gaps)
    blockers.extend(missing_evidence_gaps(by_backend, baseline_key, candidate_key) if not missing else [])
    if require_resource_metrics and not missing:
        blockers.extend(resource_metric_gaps(by_backend, baseline_key, candidate_key))
    if first_partial_win is None:
        blockers.append("missing_time_to_first_interim_p95_delta")
    elif first_partial_win < min_first_partial_win_ms:
        blockers.append("insufficient_first_partial_win")
    if final_delta is not None and final_delta < 0:
        blockers.append("finalization_regression")

    recommendation = recommendation_text(blockers, candidate_key=candidate_key)
    return {
        "kind": "local-stt-v1-backend-latency-comparison",
        "baseline": baseline_key,
        "candidate": candidate_key,
        "candidate_status": "supported" if not blockers else "experimental",
        "recommendation": recommendation,
        "min_first_partial_win_ms": min_first_partial_win_ms,
        "resource_metrics_required": require_resource_metrics,
        "p95_deltas_ms": p95_deltas,
        "blocking_gaps": blockers,
        "backends": by_backend,
    }


def comparable_input_gaps(by_backend: dict[str, dict[str, Any]], baseline_key: str, candidate_key: str) -> list[str]:
    baseline = by_backend[baseline_key]["comparable_snapshot"]
    candidate = by_backend[candidate_key]["comparable_snapshot"]
    gaps: list[str] = []
    for section in ("audio", "settings"):
        for key, baseline_value in baseline[section].items():
            candidate_value = candidate[section].get(key)
            if baseline_value != candidate_value:
                gaps.append(
                    f"benchmark_input:{section}.{key}: baseline={baseline_value!r} candidate={candidate_value!r}"
                )
    return gaps


def p95_deltas_ms(by_backend: dict[str, dict[str, Any]], baseline_key: str, candidate_key: str) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for metric in BACKEND_KEY_METRICS:
        baseline = by_backend[baseline_key]["metrics"][metric]["p95"]
        candidate = by_backend[candidate_key]["metrics"][metric]["p95"]
        deltas[metric] = None if baseline is None or candidate is None else round(baseline - candidate, 1)
    return deltas


def missing_evidence_gaps(by_backend: dict[str, dict[str, Any]], baseline_key: str, candidate_key: str) -> list[str]:
    gaps: list[str] = []
    for backend_key in (baseline_key, candidate_key):
        metrics = by_backend[backend_key]["metrics"]
        for metric in BACKEND_KEY_METRICS:
            if all(metrics[metric][percentile] is None for percentile in ("p50", "p95", "p99")):
                gaps.append(f"missing_metric:{backend_key}:{metric}")
    return gaps


def resource_metric_gaps(by_backend: dict[str, dict[str, Any]], baseline_key: str, candidate_key: str) -> list[str]:
    gaps: list[str] = []
    for backend_key in (baseline_key, candidate_key):
        metrics = by_backend[backend_key]["resource_metrics"]
        for metric in ("peak_rss_mb", "cpu_utilization_percent"):
            if metrics[metric] is None:
                gaps.append(f"missing_resource_metric:{backend_key}:{metric}")
    return gaps


def transcript_sanity_gaps(by_backend: dict[str, dict[str, Any]], baseline_key: str, candidate_key: str) -> list[str]:
    baseline = by_backend[baseline_key]["transcript_sanity"]
    candidate = by_backend[candidate_key]["transcript_sanity"]
    baseline_transcripts = baseline["unique_final_transcripts"]
    candidate_transcripts = candidate["unique_final_transcripts"]
    gaps: list[str] = []
    if candidate["runs_with_final_transcript"] == 0:
        gaps.append(f"missing_final_transcript:{candidate_key}")
    if candidate["empty_final_transcript_runs"]:
        gaps.append(f"empty_final_transcript:{candidate_key}")
    if baseline_transcripts and candidate_transcripts and baseline_transcripts != candidate_transcripts:
        gaps.append(f"final_transcript_mismatch:{candidate_key}")
    return gaps


def recommendation_text(blockers: list[str], *, candidate_key: str) -> str:
    if not blockers:
        return f"Keep {candidate_key} as a supported low-latency backend."
    if any(blocker.startswith("missing_backend:") for blocker in blockers):
        return "Run the missing backend benchmark before deciding on Vosk stateful streaming."
    if any(blocker.startswith("benchmark_input:") for blocker in blockers):
        return "Re-run backend benchmarks with matching audio, pacing, and scenario settings."
    if any(blocker.startswith("protocol_errors:") for blocker in blockers):
        return "Fix streaming protocol errors before comparing backend latency."
    if any("final_transcript" in blocker for blocker in blockers):
        return f"Keep {candidate_key} experimental until final transcripts match the baseline sanity check."
    if any(blocker.startswith("missing_metric:") for blocker in blockers):
        return "Run backend benchmarks with complete streaming latency, cadence, and decoder compute metrics."
    if any(blocker.startswith("missing_resource_metric:") for blocker in blockers):
        return "Re-run backend benchmarks with service resource monitoring enabled."
    if "finalization_regression" in blockers:
        return f"Keep {candidate_key} experimental until final transcript latency no longer regresses."
    return f"Keep {candidate_key} experimental while searching for a stronger stateful backend."


def format_markdown_report(comparison: dict[str, Any]) -> str:
    lines = [
        "# Local STT v1 Backend Comparison",
        "",
        f"Baseline: {comparison['baseline']}",
        f"Candidate: {comparison['candidate']}",
        f"Candidate status: {comparison['candidate_status']}",
        f"Recommendation: {comparison['recommendation']}",
        f"Minimum first-partial P95 win: {_format_ms(comparison['min_first_partial_win_ms'])}",
        f"Resource metrics required: {comparison['resource_metrics_required']}",
        "",
        "P95 metric deltas (baseline minus candidate):",
        "",
        "| Metric | Delta |",
        "| --- | ---: |",
    ]
    for metric, value in comparison["p95_deltas_ms"].items():
        lines.append(f"| {metric} | {_format_metric_delta(metric, value)} |")

    lines.extend(
        [
            "",
            "Backend evidence:",
            "",
            "| Backend | Artifact | Runs | First partial p95 | Final after finalize p95 | Protocol clean | Final transcript runs | Unique final transcripts |",
            "| --- | --- | ---: | ---: | ---: | --- | ---: | --- |",
        ]
    )
    for backend, evidence in sorted(comparison["backends"].items()):
        metrics = evidence["metrics"]
        sanity = evidence["transcript_sanity"]
        lines.append(
            "| "
            + " | ".join(
                [
                    backend,
                    _format_optional_value(evidence.get("path")),
                    _format_optional_value(evidence.get("runs")),
                    _format_ms(metrics["time_to_first_interim_ms"]["p95"]),
                    _format_ms(metrics["time_to_final_after_finalize_ms"]["p95"]),
                    str(evidence["protocol_error_free"]),
                    str(sanity["runs_with_final_transcript"]),
                    _format_transcripts(sanity["unique_final_transcripts"]),
                ]
            )
            + " |"
        )

    lines.extend(["", "Blocking gaps:"])
    blockers = comparison["blocking_gaps"]
    if blockers:
        lines.extend(f"- {blocker}" for blocker in blockers)
    else:
        lines.append("- none")
    lines.extend(["", "Run context:", ""])
    for backend, evidence in sorted(comparison["backends"].items()):
        environment = evidence.get("environment") if isinstance(evidence.get("environment"), dict) else {}
        lines.extend(
            [
                f"## {backend}",
                "",
                f"- Artifact: {_format_optional_value(evidence.get('path'))}",
                f"- Command: {_format_optional_value(evidence.get('benchmark_command'))}",
                f"- Target: {_format_mapping(evidence.get('target'))}",
                f"- Audio: {_format_mapping(evidence.get('audio'))}",
                f"- Settings: {_format_mapping(evidence.get('settings'))}",
                f"- Hardware: {_format_hardware(environment)}",
                f"- Resource metrics: {_format_mapping(evidence.get('resource_metrics'))}",
                "",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _format_ms(value: object) -> str:
    if value is None:
        return "missing"
    if isinstance(value, int | float):
        return f"{value:g} ms"
    return str(value)


def _format_metric_delta(metric: str, value: object) -> str:
    if metric.endswith("_rtf"):
        if value is None:
            return "missing"
        if isinstance(value, int | float):
            return f"{value:g}"
        return str(value)
    return _format_ms(value)


def _format_optional_value(value: object) -> str:
    if value in (None, ""):
        return "missing"
    if isinstance(value, list):
        return ",".join(str(item) for item in value) if value else "none"
    return str(value)


def _format_transcripts(values: object) -> str:
    if not isinstance(values, list) or not values:
        return "missing"
    return " / ".join(str(value) for value in values)


def _format_mapping(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "missing"
    return ", ".join(f"{key}={value[key]}" for key in sorted(value))


def _format_hardware(environment: dict[str, Any]) -> str:
    hardware_keys = (
        "platform",
        "machine",
        "processor",
        "cpu_logical_cores",
        "memory_total_mb",
    )
    hardware = {key: environment.get(key) for key in hardware_keys if environment.get(key) is not None}
    return _format_mapping(hardware)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(
        args.artifacts,
        baseline_key=args.baseline,
        candidate_key=args.candidate,
        min_first_partial_win_ms=args.min_first_partial_win_ms,
        require_resource_metrics=args.require_resource_metrics,
    )
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    if args.markdown_output is not None:
        args.markdown_output.write_text(format_markdown_report(comparison), encoding="utf8")
    return 1 if comparison["blocking_gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
