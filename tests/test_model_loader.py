from __future__ import annotations

import builtins
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import pytest

from src.audio_processor import AudioProcessor
from src.config import AppConfig
from src.model_loader import ASRUnavailableError, ParakeetAdapter, ParakeetNemoAdapter, QwenASRAdapter, UltravoxAdapter, build_transcriber

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


@pytest.mark.parametrize("backend", ["parakeet-nemo", "parakeet-ctc"])
def test_build_transcriber_accepts_parakeet_nemo_aliases(backend: str) -> None:
    transcriber = build_transcriber(
        AppConfig(asr_backend=backend, asr_parakeet_model="nvidia/parakeet-tdt_ctc-110m"),
        AudioProcessor(),
    )

    assert isinstance(transcriber, ParakeetNemoAdapter)
    assert transcriber.model_name == "nvidia/parakeet-tdt_ctc-110m"


@pytest.mark.parametrize("backend", ["ultravox", "ultravox-asr"])
def test_build_transcriber_accepts_ultravox_aliases(backend: str) -> None:
    transcriber = build_transcriber(
        AppConfig(asr_backend=backend),
        AudioProcessor(),
    )

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
    monkeypatch.setattr("src.model_loader._installed_package_version", lambda name: "5.10.2")

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


def test_parakeet_nemo_adapter_transcribe_uses_nemo_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class FakeNemoModel:
        def to(self, device: str) -> None:
            calls["device"] = device

        def eval(self) -> None:
            calls["eval"] = True

        def float(self) -> None:
            calls["float"] = True

        def transcribe(self, paths: list[str], *, batch_size: int) -> list[str]:
            calls["paths"] = paths
            calls["batch_size"] = batch_size
            return [" Yesterday it worked. "]

    class FakeASRModel:
        @staticmethod
        def from_pretrained(model_name: str) -> FakeNemoModel:
            calls["model_name"] = model_name
            return FakeNemoModel()

    fake_models = ModuleType("nemo.collections.asr.models")
    fake_models.ASRModel = FakeASRModel

    monkeypatch.setitem(sys.modules, "nemo", ModuleType("nemo"))
    monkeypatch.setitem(sys.modules, "nemo.collections", ModuleType("nemo.collections"))
    monkeypatch.setitem(sys.modules, "nemo.collections.asr", ModuleType("nemo.collections.asr"))
    monkeypatch.setitem(sys.modules, "nemo.collections.asr.models", fake_models)

    adapter = ParakeetNemoAdapter(
        config=AppConfig(
            asr_backend="parakeet-nemo",
            asr_device="cpu",
            asr_parakeet_model="nvidia/parakeet-tdt_ctc-110m",
            asr_parakeet_dtype="auto",
        ),
        audio_processor=AudioProcessor(),
    )

    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result == {
        "text": "Yesterday it worked.",
        "language": "en",
        "duration_ms": 125,
        "backend": "parakeet-nemo",
        "model": "nvidia/parakeet-tdt_ctc-110m",
    }
    assert calls["model_name"] == "nvidia/parakeet-tdt_ctc-110m"
    assert calls["device"] == "cpu"
    assert calls["eval"] is True
    assert calls["float"] is True
    assert calls["batch_size"] == 1
    assert str(calls["paths"][0]).endswith(".wav")


def test_ultravox_adapter_transcribe_uses_transformers_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    def fake_pipeline(**kwargs: object):
        calls["kwargs"] = kwargs

        def run(payload: dict[str, object], *, max_new_tokens: int) -> str:
            calls["payload"] = payload
            calls["max_new_tokens"] = max_new_tokens
            return " Exact transcript only. "

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
            asr_device="cpu",
            asr_ultravox_model="fixie-ai/ultravox-v0_6-llama-3_1-8b",
            asr_ultravox_dtype="auto",
            asr_ultravox_max_new_tokens=64,
            asr_ultravox_prompt="Transcribe the spoken audio exactly and return only the transcript.",
        ),
        audio_processor=AudioProcessor(),
    )

    result = adapter.transcribe(FIXTURE_PATH.read_bytes(), language="en", sample_rate=16000)

    assert result == {
        "text": "Exact transcript only.",
        "language": "en",
        "duration_ms": 125,
        "backend": "ultravox",
        "model": "fixie-ai/ultravox-v0_6-llama-3_1-8b",
    }
    assert calls["kwargs"] == {
        "model": "fixie-ai/ultravox-v0_6-llama-3_1-8b",
        "device": "cpu",
        "dtype": fake_torch.float32,
        "trust_remote_code": True,
    }
    payload = calls["payload"]
    assert payload["sampling_rate"] == 16000
    assert payload["turns"] == [{"role": "system", "content": "Transcribe the spoken audio exactly and return only the transcript."}]
    assert getattr(payload["audio"], "shape", (0,))[0] > 0
    assert calls["max_new_tokens"] == 64


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


def test_parakeet_adapter_raises_actionable_error_for_qwen_pinned_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_transformers = ModuleType("transformers")
    fake_transformers.pipeline = lambda *args, **kwargs: None
    fake_torch = ModuleType("torch")
    fake_torch.float32 = object()

    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr("src.model_loader._installed_package_version", lambda name: "4.57.6")

    adapter = ParakeetAdapter(
        config=AppConfig(asr_backend="parakeet"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match=r"huggingface-hub==1\.18\.0 transformers==5\.10\.2"):
        adapter.preload()


def test_parakeet_nemo_adapter_raises_when_dependency_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name == "nemo.collections.asr.models":
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = ParakeetNemoAdapter(
        config=AppConfig(asr_backend="parakeet-nemo"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match="parakeet-nemo backend requires nemo_toolkit"):
        adapter.preload()


def test_ultravox_adapter_raises_when_dependency_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, globals: object = None, locals: object = None, fromlist: tuple[str, ...] = (), level: int = 0):
        if name in {"transformers", "torch"}:
            raise ImportError(name)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    adapter = UltravoxAdapter(
        config=AppConfig(asr_backend="ultravox"),
        audio_processor=AudioProcessor(),
    )

    with pytest.raises(ASRUnavailableError, match="ultravox backend requires transformers, torch, accelerate, and peft"):
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


@pytest.mark.parametrize("env_name", ["ASR_QWEN_MAX_NEW_TOKENS", "ASR_QWEN_MAX_INFERENCE_BATCH_SIZE"])
def test_app_config_rejects_non_positive_qwen_limits(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
) -> None:
    monkeypatch.setenv(env_name, "0")

    with pytest.raises(ValueError, match=rf"{env_name} must be a positive integer"):
        AppConfig.from_env()


def test_app_config_reads_ultravox_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_BACKEND", "ultravox")
    monkeypatch.setenv("ASR_ULTRAVOX_MODEL", "fixie-ai/ultravox-v0_6-llama-3_1-8b")
    monkeypatch.setenv("ASR_ULTRAVOX_DTYPE", "float32")
    monkeypatch.setenv("ASR_ULTRAVOX_MAX_NEW_TOKENS", "96")
    monkeypatch.setenv("ASR_ULTRAVOX_PROMPT", "Return only the transcript.")

    config = AppConfig.from_env()

    assert config.asr_backend == "ultravox"
    assert config.asr_ultravox_model == "fixie-ai/ultravox-v0_6-llama-3_1-8b"
    assert config.asr_ultravox_dtype == "float32"
    assert config.asr_ultravox_max_new_tokens == 96
    assert config.asr_ultravox_prompt == "Return only the transcript."


def test_app_config_rejects_non_positive_ultravox_max_new_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASR_ULTRAVOX_MAX_NEW_TOKENS", "0")

    with pytest.raises(ValueError, match=r"ASR_ULTRAVOX_MAX_NEW_TOKENS must be a positive integer"):
        AppConfig.from_env()
