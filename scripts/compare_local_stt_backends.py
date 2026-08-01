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
    KEY_METRICS,
    load_artifact,
    metric_percentiles,
)


DEFAULT_MIN_FIRST_PARTIAL_WIN_MS = 50.0
COMPARABLE_AUDIO_KEYS = ("source", "sample_rate", "channels", "format", "frame_ms", "duration_ms", "send_aggregate_ms")
COMPARABLE_SETTING_KEYS = ("partial_interval_ms", "receive_timeout_seconds", "realtime_pace", "send_aggregate_ms", "scenario")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Local STT v1 backend benchmark artifacts")
    parser.add_argument("artifacts", nargs="+", type=Path, help="Benchmark JSON artifacts from bench_local_stt_stream.py")
    parser.add_argument("--baseline", required=True, help="Baseline backend key, for example faster-whisper:rolling_window")
    parser.add_argument("--candidate", required=True, help="Candidate backend key, for example vosk:stateful")
    parser.add_argument("--output", type=Path, help="Optional JSON comparison output path")
    parser.add_argument(
        "--min-first-partial-win-ms",
        type=float,
        default=DEFAULT_MIN_FIRST_PARTIAL_WIN_MS,
        help="Minimum candidate P95 first-partial win required for a supported-backend recommendation",
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


def compare_artifacts(
    paths: list[Path],
    *,
    baseline_key: str,
    candidate_key: str,
    min_first_partial_win_ms: float = DEFAULT_MIN_FIRST_PARTIAL_WIN_MS,
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
            "metrics": {metric: metric_percentiles(summary, metric) for metric in KEY_METRICS},
            "target": artifact.get("target") or {},
            "audio": artifact.get("audio") or {},
            "settings": artifact.get("settings") or {},
            "environment": artifact.get("environment") or {},
            "runs": artifact.get("runs"),
            "protocol_error_free": protocol_error_free(artifact),
            "comparable_snapshot": comparable_snapshot(artifact),
        }

    missing = [key for key in (baseline_key, candidate_key) if key not in by_backend]
    input_gaps = comparable_input_gaps(by_backend, baseline_key, candidate_key) if not missing else []
    p95_deltas = p95_deltas_ms(by_backend, baseline_key, candidate_key) if not missing else {}
    first_partial_win = p95_deltas.get("time_to_first_interim_ms")
    final_delta = p95_deltas.get("time_to_final_after_finalize_ms")
    candidate_errors = None if missing else not by_backend[candidate_key]["protocol_error_free"]
    baseline_errors = None if missing else not by_backend[baseline_key]["protocol_error_free"]

    blockers = []
    blockers.extend(f"missing_backend:{key}" for key in missing)
    blockers.extend(input_gaps)
    if candidate_errors:
        blockers.append(f"protocol_errors:{candidate_key}")
    if baseline_errors:
        blockers.append(f"protocol_errors:{baseline_key}")
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
    for metric in KEY_METRICS:
        baseline = by_backend[baseline_key]["metrics"][metric]["p95"]
        candidate = by_backend[candidate_key]["metrics"][metric]["p95"]
        deltas[metric] = None if baseline is None or candidate is None else round(baseline - candidate, 1)
    return deltas


def recommendation_text(blockers: list[str], *, candidate_key: str) -> str:
    if not blockers:
        return f"Keep {candidate_key} as a supported low-latency backend."
    if any(blocker.startswith("missing_backend:") for blocker in blockers):
        return "Run the missing backend benchmark before deciding on Vosk stateful streaming."
    if any(blocker.startswith("benchmark_input:") for blocker in blockers):
        return "Re-run backend benchmarks with matching audio, pacing, and scenario settings."
    if any(blocker.startswith("protocol_errors:") for blocker in blockers):
        return "Fix streaming protocol errors before comparing backend latency."
    if "finalization_regression" in blockers:
        return f"Keep {candidate_key} experimental until final transcript latency no longer regresses."
    return f"Keep {candidate_key} experimental while searching for a stronger stateful backend."


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    comparison = compare_artifacts(
        args.artifacts,
        baseline_key=args.baseline,
        candidate_key=args.candidate,
        min_first_partial_win_ms=args.min_first_partial_win_ms,
    )
    encoded = json.dumps(comparison, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf8")
    else:
        print(encoded, end="")
    return 1 if comparison["blocking_gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
