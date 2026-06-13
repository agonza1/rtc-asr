from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_mlx_text.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_benchmark_mlx_text", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_benchmark_mlx_text", benchmark_module)
SPEC.loader.exec_module(benchmark_module)


def test_run_benchmark_serializes_mlx_generate_output(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {"prompts": []}

    fake_mlx_lm = ModuleType("mlx_lm")

    def fake_load(model_name: str):
        calls["model_name"] = model_name
        return object(), object()

    def fake_generate(model, tokenizer, prompt=None, max_tokens: int = 0, verbose: bool = False):
        assert model is not None
        assert tokenizer is not None
        calls["prompts"].append(prompt)
        calls["max_tokens"] = max_tokens
        calls["verbose"] = verbose
        return {"text": f"Reply for {prompt}"}

    fake_mlx_lm.load = fake_load
    fake_mlx_lm.generate = fake_generate
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx_lm)

    output_path = tmp_path / "artifact.json"
    exit_code = benchmark_module.main(
        [
            "--model",
            "Qwen/Qwen3-0.6B-MLX-4bit",
            "--sample-count",
            "2",
            "--max-tokens",
            "32",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "mlx-text-benchmark"
    assert payload["backend"] == {
        "name": "mlx-lm",
        "model": "Qwen/Qwen3-0.6B-MLX-4bit",
        "device": "apple-silicon",
        "quantization": "4bit",
    }
    assert payload["benchmark"]["sample_count"] == 2
    assert payload["benchmark"]["max_tokens"] == 32
    assert len(payload["samples"]) == 2
    assert payload["samples"][0]["output_text"].startswith("Reply for")
    assert payload["summary"]["mean_ms"] >= 0
    assert calls["model_name"] == "Qwen/Qwen3-0.6B-MLX-4bit"
    assert calls["max_tokens"] == 32
    assert calls["verbose"] is False
    assert len(calls["prompts"]) == 2


def test_run_benchmark_raises_actionable_error_when_mlx_is_missing(monkeypatch) -> None:
    monkeypatch.delitem(sys.modules, "mlx_lm", raising=False)
    real_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "mlx_lm":
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", fake_import)

    try:
        benchmark_module.run_benchmark(
            model_name="Qwen/Qwen3-0.6B-MLX-4bit",
            sample_count=1,
            max_tokens=8,
        )
    except RuntimeError as exc:
        assert "mlx-lm is required" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when mlx_lm is unavailable")

