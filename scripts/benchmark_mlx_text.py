from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from itertools import cycle, islice
from pathlib import Path
from typing import Any


DEFAULT_PROMPTS = (
    "Summarize why low-latency speech recognition matters for realtime agents.",
    "List three operational risks when ASR partials arrive too slowly.",
    "Explain how an MLX benchmark complements websocket ASR latency artifacts.",
)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark MLX text generation latency")
    parser.add_argument("--model", required=True, help="MLX model identifier to load")
    parser.add_argument("--sample-count", type=positive_int, default=3, help="Number of prompts to run")
    parser.add_argument("--max-tokens", type=positive_int, default=64, help="Maximum tokens to generate per sample")
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


def _coerce_text(result: Any) -> str:
    if isinstance(result, str):
        return result.strip()
    if isinstance(result, dict):
        for key in ("text", "response", "output"):
            value = result.get(key)
            if value is not None:
                return str(value).strip()
    text = getattr(result, "text", None)
    if text is not None:
        return str(text).strip()
    return str(result).strip()


def run_benchmark(*, model_name: str, sample_count: int, max_tokens: int) -> dict[str, Any]:
    try:
        from mlx_lm import generate, load
    except ImportError as exc:
        raise RuntimeError("mlx-lm is required. Install it in .venv-mlx before running this benchmark.") from exc

    load_started = time.perf_counter()
    model, tokenizer = load(model_name)
    load_latency_ms = round((time.perf_counter() - load_started) * 1000, 1)

    samples: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    prompt_iter = islice(cycle(DEFAULT_PROMPTS), sample_count)
    for index, prompt in enumerate(prompt_iter, start=1):
        started = time.perf_counter()
        try:
            result = generate(model, tokenizer, prompt=prompt, max_tokens=max_tokens, verbose=False)
        except TypeError:
            result = generate(model, tokenizer, prompt, max_tokens=max_tokens, verbose=False)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        latencies_ms.append(latency_ms)
        text = _coerce_text(result)
        samples.append(
            {
                "index": index,
                "prompt": prompt,
                "output_text": text,
                "output_char_count": len(text),
                "latency_ms": latency_ms,
            }
        )

    return {
        "kind": "mlx-text-benchmark",
        "backend": {
            "name": "mlx-lm",
            "model": model_name,
            "device": "apple-silicon",
            "quantization": "4bit" if "4bit" in model_name.lower() else None,
        },
        "benchmark": {
            "sample_count": sample_count,
            "max_tokens": max_tokens,
            "prompt_catalog": list(DEFAULT_PROMPTS),
            "load_latency_ms": load_latency_ms,
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
        max_tokens=args.max_tokens,
    )
    payload = json.dumps(artifact, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


