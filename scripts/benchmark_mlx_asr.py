from __future__ import annotations

import argparse
import json
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIO_FILE = ROOT / "tests" / "fixtures" / "smoke.wav"


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Parakeet MLX ASR latency")
    parser.add_argument("--model", required=True, help="Parakeet MLX model identifier to load")
    parser.add_argument("--sample-count", type=positive_int, default=3, help="Number of transcription runs")
    parser.add_argument("--audio-file", type=Path, default=DEFAULT_AUDIO_FILE, help="Audio clip to transcribe")
    parser.add_argument("--command", default="parakeet-mlx", help="CLI entry point to execute")
    parser.add_argument("--output", type=Path, help="Optional JSON artifact path")
    return parser.parse_args(argv)


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * q)))
    return ordered[index]


def summarize(values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(statistics.mean(values), 1),
        "p95_ms": round(percentile(values, 0.95), 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
    }


def describe_environment() -> dict[str, Any]:
    memory_mb: float | None = None
    try:
        import psutil

        memory_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:
        memory_mb = None

    return {
        "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "machine": platform.machine(),
        "process_rss_mb": memory_mb,
    }


def _resolve_cli(command: str) -> str:
    resolved = shutil.which(command)
    if resolved:
        return resolved
    raise RuntimeError(f"{command} is required. Install it in .venv-mlx before running this benchmark.")


def _coerce_transcript(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for key in ("text", "transcript", "output"):
            value = payload.get(key)
            if value:
                return str(value).strip()
        segments = payload.get("segments")
        if isinstance(segments, list):
            parts = []
            for segment in segments:
                if isinstance(segment, dict) and segment.get("text"):
                    parts.append(str(segment["text"]).strip())
            if parts:
                return " ".join(parts).strip()
    return json.dumps(payload, sort_keys=True)


def _load_cli_output(output_dir: Path, audio_file: Path) -> dict[str, Any]:
    preferred = output_dir / f"{audio_file.stem}.json"
    candidate_paths = [preferred] if preferred.exists() else []
    if not candidate_paths:
        candidate_paths = sorted(output_dir.glob("*.json"))
    if len(candidate_paths) != 1:
        raise RuntimeError(f"Expected exactly one JSON artifact in {output_dir}, found {len(candidate_paths)}")
    return json.loads(candidate_paths[0].read_text(encoding="utf-8"))


def run_benchmark(*, model_name: str, sample_count: int, audio_file: Path, command: str) -> dict[str, Any]:
    cli = _resolve_cli(command)
    if not audio_file.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_file}")

    samples: list[dict[str, Any]] = []
    latencies_ms: list[float] = []

    for index in range(1, sample_count + 1):
        with tempfile.TemporaryDirectory(prefix="rtc_asr_parakeet_mlx_") as output_dir_text:
            output_dir = Path(output_dir_text)
            started = time.perf_counter()
            subprocess.run(
                [
                    cli,
                    str(audio_file),
                    "--model",
                    model_name,
                    "--output-dir",
                    str(output_dir),
                    "--output-format",
                    "json",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            latency_ms = round((time.perf_counter() - started) * 1000, 1)
            latencies_ms.append(latency_ms)
            cli_payload = _load_cli_output(output_dir, audio_file)
            transcript = _coerce_transcript(cli_payload)
            samples.append(
                {
                    "index": index,
                    "transcript": transcript,
                    "transcript_char_count": len(transcript),
                    "latency_ms": latency_ms,
                }
            )

    return {
        "kind": "mlx-asr-benchmark",
        "backend": {
            "name": "parakeet-mlx",
            "model": model_name,
            "device": "apple-silicon",
            "runtime": "mlx",
        },
        "benchmark": {
            "sample_count": sample_count,
            "audio_file": str(audio_file),
            "command": Path(cli).name,
        },
        "samples": samples,
        "summary": summarize(latencies_ms),
        "environment": describe_environment(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    artifact = run_benchmark(
        model_name=args.model,
        sample_count=args.sample_count,
        audio_file=args.audio_file,
        command=args.command,
    )
    payload = json.dumps(artifact, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
