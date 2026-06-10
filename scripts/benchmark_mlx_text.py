from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import statistics
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_MODEL = "Qwen/Qwen3-0.6B-MLX-4bit"
DEFAULT_PROMPT = "Return one concise sentence explaining why low-latency local inference matters for voice AI tests."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a local MLX text-generation model")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="MLX model id to load")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt used for each generation sample")
    parser.add_argument("--sample-count", type=int, default=3, help="Number of generation samples to run")
    parser.add_argument("--max-tokens", type=int, default=64, help="Maximum generated tokens per sample")
    parser.add_argument("--warmup-tokens", type=int, default=8, help="Short warmup generation length")
    parser.add_argument("--output", type=Path, help="Optional JSON artifact path")
    return parser.parse_args()


def require_mlx_lm() -> None:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("MLX benchmarks require macOS on Apple Silicon.")
    if importlib.util.find_spec("mlx_lm") is None:
        raise RuntimeError("Missing mlx-lm. Run `make benchmark-qwen-mlx-text` to prepare `.venv-mlx`, or install `mlx-lm` in the selected Python environment.")


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("Cannot summarize an empty latency series")
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * 0.95)))
    return {
        "mean_ms": round(statistics.mean(values), 1),
        "p95_ms": round(ordered[p95_index], 1),
        "min_ms": round(min(values), 1),
        "max_ms": round(max(values), 1),
    }


def rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    return round(psutil.Process().memory_info().rss / (1024 * 1024), 1)


def render_prompt(tokenizer: Any, prompt: str) -> str:
    messages = [{"role": "user", "content": prompt}]
    if getattr(tokenizer, "chat_template", None) is None:
        return prompt
    try:
        return tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
    except TypeError:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)


def count_tokens(tokenizer: Any, text: str) -> int:
    try:
        return len(tokenizer.encode(text))
    except Exception:
        return 0


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    require_mlx_lm()
    from mlx_lm import generate, load

    load_started = time.perf_counter()
    model, tokenizer = load(args.model)
    load_ms = (time.perf_counter() - load_started) * 1000
    prompt = render_prompt(tokenizer, args.prompt)

    if args.warmup_tokens > 0:
        generate(model, tokenizer, prompt=prompt, max_tokens=args.warmup_tokens, verbose=False)

    samples: list[dict[str, Any]] = []
    durations: list[float] = []
    output_token_counts: list[int] = []
    for index in range(max(args.sample_count, 1)):
        started = time.perf_counter()
        text = generate(model, tokenizer, prompt=prompt, max_tokens=args.max_tokens, verbose=False)
        elapsed_ms = (time.perf_counter() - started) * 1000
        output_tokens = count_tokens(tokenizer, text)
        durations.append(elapsed_ms)
        output_token_counts.append(output_tokens)
        samples.append({
            "sample": index + 1,
            "generation_ms": round(elapsed_ms, 1),
            "output_tokens": output_tokens,
            "tokens_per_second": round(output_tokens / (elapsed_ms / 1000), 2) if elapsed_ms > 0 else None,
            "text": text.strip(),
        })

    total_tokens = sum(output_token_counts)
    total_seconds = sum(durations) / 1000
    return {
        "environment": {
            "date_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "processor": platform.processor() or platform.machine(),
        },
        "benchmark": {
            "task": "mlx-text-generation",
            "sample_count": max(args.sample_count, 1),
            "max_tokens": args.max_tokens,
            "warmup_tokens": args.warmup_tokens,
            "prompt": args.prompt,
        },
        "model": {
            "id": args.model,
            "runtime": "mlx-lm",
            "precision": "4-bit",
        },
        "load": {
            "load_ms": round(load_ms, 1),
            "rss_after_load_mb": rss_mb(),
        },
        "summary": {
            **summarize(durations),
            "output_tokens_mean": round(statistics.mean(output_token_counts), 1) if output_token_counts else 0,
            "tokens_per_second_overall": round(total_tokens / total_seconds, 2) if total_seconds > 0 else None,
            "rss_after_benchmark_mb": rss_mb(),
        },
        "samples": samples,
    }


def main() -> int:
    args = parse_args()
    try:
        result = run_benchmark(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
