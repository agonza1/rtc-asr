from __future__ import annotations

import argparse
import importlib.util
import platform
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_mlx_text.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_mlx_text_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mlx_benchmark = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_mlx_text_benchmark", mlx_benchmark)
SPEC.loader.exec_module(mlx_benchmark)


def test_require_mlx_lm_rejects_non_apple_silicon(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")

    with pytest.raises(RuntimeError, match="MLX benchmarks require macOS on Apple Silicon"):
        mlx_benchmark.require_mlx_lm()


def test_render_prompt_disables_thinking_when_supported() -> None:
    calls: dict[str, object] = {}

    class FakeTokenizer:
        chat_template = "template"

        def apply_chat_template(self, messages, **kwargs):
            calls["messages"] = messages
            calls["kwargs"] = kwargs
            return "rendered"

    assert mlx_benchmark.render_prompt(FakeTokenizer(), "hello") == "rendered"
    assert calls["kwargs"]["enable_thinking"] is False


def test_run_benchmark_uses_mlx_lm_and_writes_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(platform, "system", lambda: "Darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name: str):
        if name == "mlx_lm":
            return SimpleNamespace()
        return real_find_spec(name)

    class FakeTokenizer:
        chat_template = None

        def encode(self, text: str) -> list[str]:
            return text.split()

    fake_mlx_lm = ModuleType("mlx_lm")
    fake_mlx_lm.load = lambda model: (object(), FakeTokenizer())
    fake_mlx_lm.generate = lambda model, tokenizer, prompt, max_tokens, verbose: "local tokens are fast"
    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    monkeypatch.setitem(sys.modules, "mlx_lm", fake_mlx_lm)

    result = mlx_benchmark.run_benchmark(argparse.Namespace(
        model="Qwen/Qwen3-0.6B-MLX-4bit",
        prompt="hello",
        sample_count=2,
        max_tokens=16,
        warmup_tokens=1,
    ))

    assert result["benchmark"]["task"] == "mlx-text-generation"
    assert result["benchmark"]["sample_count"] == 2
    assert result["model"]["id"] == "Qwen/Qwen3-0.6B-MLX-4bit"
    assert len(result["samples"]) == 2
    assert result["summary"]["output_tokens_mean"] == 4
