from __future__ import annotations

import builtins
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from src.audio_processor import AudioProcessor
from src.config import AppConfig
from src.model_loader import ASRUnavailableError, QwenASRAdapter, UltravoxAdapter, build_transcriber

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smoke.wav"


@pytest.mark.parametrize("backend", ["qwen", "qwen-asr", "qwen3-asr"])
def test_build_transcriber_accepts_qwen_aliases(backend: str) -> None:
    transcriber = build_transcriber(AppConfig(asr_backend=backend), AudioProcessor())
    assert isinstance(transcriber, QwenASRAdapter)


def test_build_transcriber_accepts_ultravox_alias() -> None:
    transcriber = build_transcriber(AppConfig(asr_backend="ultravox"), AudioProcessor())
    assert isinstance(transcriber, UltravoxAdapter)
    assert transcriber.model_name == "fixie-ai/ultravox-v0_6-llama-3_1-8b"


def test_qwen_adapter_transcribe_uses_qwen_package(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeModel:
        def transcribe(self, *, audio: tuple[object, int], language: str | None) -> list[SimpleNamespace]:
            calls["audio"] = audio
            calls["language"] = language
            return [SimpleNamespace(text=" hello world ", language="English")]

    class FakeQwen3ASRModel:
        @staticmethod
        def from_pretrained(model_name: str, **kwargs: object) -> FakeModel:
            calls["model_name"] = model_name
            calls["kwargs"] = kwargs
            return FakeModel()

    fake_qwen_asr = ModuleType("qwen_asr")
    fake_qwen_asr.Qwen3ASRModel = FakeQwen3ASRModel
    fake_torch = ModuleType("torch")
    fake_torch.bfloat16 = object()
    fake_torch.float32 = object()

    monkeypatch.setitem(sys.modules, "qwen_asr", fake_qwen_asr)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    adapter = QwenASRAdapter(
        config=AppConfig(asr_backend="qwen-asr", asr_device="cuda:0"),
        audio_processor=AudioProcessor(),
    )
    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result["text"] == "hello world"
    assert calls["language"] == "English"


def test_ultravox_adapter_transcribe_uses_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_pipeline(**kwargs: object):
        calls["kwargs"] = kwargs

        def run(payload: dict[str, object], *, max_new_tokens: int) -> dict[str, object]:
            calls["payload"] = payload
            calls["max_new_tokens"] = max_new_tokens
            return {"generated_text": [{"role": "assistant", "content": "  hello from ultravox  "}]}

        return run

    fake_transformers = ModuleType("transformers")
    fake_transformers.pipeline = fake_pipeline
    fake_torch = ModuleType("torch")
    fake_torch.bfloat16 = object()
    fake_torch.float32 = object()

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    adapter = UltravoxAdapter(
        config=AppConfig(
            asr_backend="ultravox",
            asr_ultravox_model="fixie-ai/ultravox-v0_6-llama-3_1-8b",
            asr_ultravox_dtype="auto",
            asr_ultravox_max_new_tokens=64,
            asr_ultravox_prompt="Transcribe exactly.",
            asr_device="cpu",
        ),
        audio_processor=AudioProcessor(),
    )

    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result == {
        "text": "hello from ultravox",
        "language": "en",
        "duration_ms": 125,
        "backend": "ultravox",
        "model": "fixie-ai/ultravox-v0_6-llama-3_1-8b",
    }
    assert calls["kwargs"] == {
        "model": "fixie-ai/ultravox-v0_6-llama-3_1-8b",
        "trust_remote_code": True,
        "device": "cpu",
        "torch_dtype": fake_torch.float32,
    }
    assert calls["payload"]["sampling_rate"] == 16000
    assert calls["payload"]["turns"] == [{"role": "system", "content": "Transcribe exactly."}]
    assert calls["max_new_tokens"] == 64


def test_ultravox_adapter_raises_when_dependency_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name in {"transformers", "torch"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    adapter = UltravoxAdapter(config=AppConfig(asr_backend="ultravox"), audio_processor=AudioProcessor())

    with pytest.raises(ASRUnavailableError, match="ultravox backend requires transformers and torch"):
        adapter.preload()


def test_app_config_reads_ultravox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_BACKEND", "ultravox")
    monkeypatch.setenv("ASR_ULTRAVOX_MODEL", "fixie-ai/ultravox-v0_6-llama-3_1-8b")
    monkeypatch.setenv("ASR_ULTRAVOX_DTYPE", "float32")
    monkeypatch.setenv("ASR_ULTRAVOX_MAX_NEW_TOKENS", "72")
    monkeypatch.setenv("ASR_ULTRAVOX_PROMPT", "Transcribe the clip.")

    config = AppConfig.from_env()

    assert config.asr_backend == "ultravox"
    assert config.asr_ultravox_model == "fixie-ai/ultravox-v0_6-llama-3_1-8b"
    assert config.asr_ultravox_dtype == "float32"
    assert config.asr_ultravox_max_new_tokens == 72
    assert config.asr_ultravox_prompt == "Transcribe the clip."
