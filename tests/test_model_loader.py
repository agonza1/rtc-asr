from __future__ import annotations

import builtins
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from src.audio_processor import AudioProcessor
from src.config import AppConfig
from src.model_loader import ASRUnavailableError, ParakeetAdapter, QwenASRAdapter, build_transcriber

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smoke.wav"


@pytest.mark.parametrize("backend", ["qwen", "qwen-asr", "qwen3-asr"])
def test_build_transcriber_accepts_qwen_aliases(backend: str) -> None:
    transcriber = build_transcriber(
        AppConfig(asr_backend=backend),
        AudioProcessor(),
    )

    assert isinstance(transcriber, QwenASRAdapter)
    assert transcriber.model_name == "Qwen/Qwen3-ASR-0.6B"


@pytest.mark.parametrize("backend", ["parakeet", "parakeet-asr"])
def test_build_transcriber_accepts_parakeet_aliases(backend: str) -> None:
    transcriber = build_transcriber(
        AppConfig(asr_backend=backend),
        AudioProcessor(),
    )

    assert isinstance(transcriber, ParakeetAdapter)
    assert transcriber.model_name == "nvidia/parakeet-tdt-0.6b-v3"


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
        config=AppConfig(
            asr_backend="qwen-asr",
            asr_device="cuda:0",
            asr_qwen_model="Qwen/Qwen3-ASR-1.7B",
            asr_qwen_dtype="auto",
            asr_qwen_max_new_tokens=512,
            asr_qwen_max_inference_batch_size=4,
        ),
        audio_processor=AudioProcessor(),
    )

    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result == {
        "text": "hello world",
        "language": "English",
        "duration_ms": 125,
        "backend": "qwen-asr",
        "model": "Qwen/Qwen3-ASR-1.7B",
    }
    assert calls["model_name"] == "Qwen/Qwen3-ASR-1.7B"
    assert calls["kwargs"] == {
        "dtype": fake_torch.bfloat16,
        "device_map": "cuda:0",
        "max_new_tokens": 512,
        "max_inference_batch_size": 4,
    }
    audio_samples, audio_sample_rate = calls["audio"]
    assert audio_sample_rate == 16000
    assert getattr(audio_samples, "shape", (0,))[0] > 0
    assert calls["language"] == "English"


def test_parakeet_adapter_transcribe_uses_transformers_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_pipeline(task: str, **kwargs: object):
        calls["task"] = task
        calls["kwargs"] = kwargs

        def run(audio: dict[str, object]) -> dict[str, str]:
            calls["audio"] = audio
            return {"text": " Yesterday it worked. "}

        return run

    fake_transformers = ModuleType("transformers")
    fake_transformers.pipeline = fake_pipeline
    fake_torch = ModuleType("torch")
    fake_torch.bfloat16 = object()
    fake_torch.float32 = object()

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    adapter = ParakeetAdapter(
        config=AppConfig(
            asr_backend="parakeet",
            asr_device="cpu",
            asr_parakeet_model="nvidia/parakeet-tdt-0.6b-v3",
            asr_parakeet_dtype="auto",
        ),
        audio_processor=AudioProcessor(),
    )

    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result == {
        "text": "Yesterday it worked.",
        "language": "en",
        "duration_ms": 125,
        "backend": "parakeet",
        "model": "nvidia/parakeet-tdt-0.6b-v3",
    }
    assert calls["task"] == "automatic-speech-recognition"
    assert calls["kwargs"] == {
        "model": "nvidia/parakeet-tdt-0.6b-v3",
        "device": "cpu",
        "dtype": fake_torch.float32,
    }
    audio = calls["audio"]
    assert audio["sampling_rate"] == 16000
    assert getattr(audio["array"], "shape", (0,))[0] > 0


def test_qwen_adapter_raises_when_dependency_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name in {"qwen_asr", "torch"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = QwenASRAdapter(
        config=AppConfig(asr_backend="qwen-asr"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match="qwen-asr backend is not installed"):
        adapter.preload()


def test_qwen_adapter_raises_actionable_error_for_transformers_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name == "qwen_asr":
            raise TypeError("check_model_inputs() missing 1 required positional argument: 'func'")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr("src.model_loader._installed_package_version", lambda name: "5.10.0.dev0")

    adapter = QwenASRAdapter(
        config=AppConfig(asr_backend="qwen-asr"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match=r"transformers version \(5\.10\.0\.dev0\)"):
        adapter.preload()


def test_parakeet_adapter_raises_when_dependency_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name in {"transformers", "torch"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = ParakeetAdapter(
        config=AppConfig(asr_backend="parakeet"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match="parakeet backend requires transformers and torch"):
        adapter.preload()


def test_app_config_reads_qwen_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_BACKEND", "qwen")
    monkeypatch.setenv("ASR_QWEN_MODEL", "Qwen/Qwen3-ASR-1.7B")
    monkeypatch.setenv("ASR_QWEN_DTYPE", "float32")
    monkeypatch.setenv("ASR_QWEN_DEVICE_MAP", "cpu")
    monkeypatch.setenv("ASR_QWEN_MAX_NEW_TOKENS", "1024")
    monkeypatch.setenv("ASR_QWEN_MAX_INFERENCE_BATCH_SIZE", "3")

    config = AppConfig.from_env()

    assert config.asr_backend == "qwen"
    assert config.asr_qwen_model == "Qwen/Qwen3-ASR-1.7B"
    assert config.asr_qwen_dtype == "float32"
    assert config.asr_qwen_device_map == "cpu"
    assert config.asr_qwen_max_new_tokens == 1024
    assert config.asr_qwen_max_inference_batch_size == 3


def test_app_config_reads_parakeet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_BACKEND", "parakeet")
    monkeypatch.setenv("ASR_PARAKEET_MODEL", "nvidia/parakeet-tdt-0.6b-v3")
    monkeypatch.setenv("ASR_PARAKEET_DTYPE", "float32")

    config = AppConfig.from_env()

    assert config.asr_backend == "parakeet"
    assert config.asr_parakeet_model == "nvidia/parakeet-tdt-0.6b-v3"
    assert config.asr_parakeet_dtype == "float32"
