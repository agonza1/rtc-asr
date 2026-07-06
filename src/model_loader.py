"""ASR backend abstraction and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
import tempfile
from typing import Any, Protocol

from .audio_processor import AudioProcessor
from .config import AppConfig


class ASRUnavailableError(RuntimeError):
    """Raised when the configured ASR backend cannot serve a request."""


class Transcriber(Protocol):
    backend_name: str
    model_name: str

    def is_loaded(self) -> bool: ...

    def preload(self) -> None: ...

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]: ...

    def describe(self) -> dict[str, Any]: ...


@dataclass(slots=True)
class FasterWhisperAdapter:
    """Lazy faster-whisper wrapper used by the transcription endpoints."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="faster-whisper")
    model_name: str = field(init=False)
    _model: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_model_size

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        model = self._load_model()
        segments, info = model.transcribe(
            decoded_audio.samples,
            language=language,
            vad_filter=self.config.asr_vad_filter,
        )

        text = " ".join(
            segment.text.strip()
            for segment in segments
            if getattr(segment, "text", "").strip()
        ).strip()
        language_code = getattr(info, "language", None) or language
        probability = getattr(info, "language_probability", None)

        return {
            "text": text,
            "language": language_code,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
            "language_probability": probability,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "compute_type": self.config.asr_compute_type,
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRUnavailableError(
                "The faster-whisper backend is not installed. Install requirements.txt to enable /api/transcribe."
            ) from exc

        self._model = WhisperModel(
            self.config.asr_model_size,
            device=self.config.asr_device,
            compute_type=self.config.asr_compute_type,
        )
        return self._model


@dataclass(slots=True)
class QwenASRAdapter:
    """Lazy qwen-asr wrapper used by the transcription endpoints."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="qwen-asr")
    model_name: str = field(init=False)
    _model: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_qwen_model

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        model = self._load_model()
        results = model.transcribe(
            audio=(decoded_audio.samples, decoded_audio.sample_rate),
            language=_normalize_qwen_language(language),
        )
        result = results[0] if isinstance(results, list) else results
        text = getattr(result, "text", "") or ""
        detected_language = getattr(result, "language", None) or language

        return {
            "text": text.strip(),
            "language": detected_language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": self.config.asr_qwen_dtype,
            "device_map": self._device_map(),
            "max_new_tokens": self.config.asr_qwen_max_new_tokens,
            "max_inference_batch_size": self.config.asr_qwen_max_inference_batch_size,
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            import torch
            from qwen_asr import Qwen3ASRModel
        except ImportError as exc:
            raise ASRUnavailableError(
                "The qwen-asr backend is not installed. Install requirements.txt to enable ASR_BACKEND=qwen-asr."
            ) from exc
        except TypeError as exc:
            message = str(exc)
            if "check_model_inputs" not in message:
                raise
            transformers_version = _installed_package_version("transformers") or "unknown"
            raise ASRUnavailableError(
                "The qwen-asr backend is incompatible with the installed transformers "
                f"version ({transformers_version}). Install the repo-pinned qwen stack with "
                "`pip install -r requirements.txt` so qwen-asr can use transformers==4.57.6."
            ) from exc

        kwargs = {
            "dtype": _resolve_torch_dtype(torch, self.config.asr_qwen_dtype, self.config.asr_device),
            "device_map": self._device_map(),
            "max_new_tokens": self.config.asr_qwen_max_new_tokens,
            "max_inference_batch_size": self.config.asr_qwen_max_inference_batch_size,
        }
        self._model = Qwen3ASRModel.from_pretrained(self.model_name, **kwargs)
        return self._model

    def _device_map(self) -> str:
        if self.config.asr_qwen_device_map:
            return self.config.asr_qwen_device_map
        return self.config.asr_device


@dataclass(slots=True)
class ParakeetAdapter:
    """Transformers pipeline wrapper for NVIDIA Parakeet ASR models."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="parakeet")
    model_name: str = field(init=False)
    _pipeline: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_parakeet_model

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def preload(self) -> None:
        self._load_pipeline()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        pipeline = self._load_pipeline()
        result = pipeline(
            {"array": decoded_audio.samples, "sampling_rate": decoded_audio.sample_rate}
        )
        text = _extract_pipeline_text(result)

        return {
            "text": text,
            "language": language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": self.config.asr_parakeet_dtype,
            "implementation": "transformers.pipeline",
            "task": "automatic-speech-recognition",
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise ASRUnavailableError(
                "The parakeet backend requires transformers and torch. Install requirements.txt to enable ASR_BACKEND=parakeet."
            ) from exc

        self._ensure_local_runtime_compatibility()
        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=self.model_name,
            device=self.config.asr_device,
            dtype=_resolve_torch_dtype(torch, self.config.asr_parakeet_dtype, self.config.asr_device),
        )
        return self._pipeline

    def _ensure_local_runtime_compatibility(self) -> None:
        transformers_version = _installed_package_version("transformers") or "unknown"
        if not transformers_version.startswith("4."):
            return
        raise ASRUnavailableError(
            "The parakeet backend needs a newer Hugging Face runtime than the repo's default qwen-compatible "
            f"transformers pin ({transformers_version}). For local Parakeet runs, install "
            "`huggingface-hub==1.18.0 transformers==5.10.2` or use `make benchmark-compose-parakeet`."
        )


@dataclass(slots=True)
class ParakeetNemoAdapter:
    """NeMo wrapper for NVIDIA Parakeet CTC/TDT ASR models."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="parakeet-nemo")
    model_name: str = field(init=False)
    _model: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_parakeet_model

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        model = self._load_model()
        try:
            import soundfile as sf
        except ImportError as exc:
            raise ASRUnavailableError(
                "The parakeet-nemo backend requires soundfile. Install requirements.txt to enable ASR_BACKEND=parakeet-nemo."
            ) from exc

        with tempfile.NamedTemporaryFile(prefix="rtc_asr_parakeet_", suffix=".wav") as audio_file:
            sf.write(audio_file.name, decoded_audio.samples, decoded_audio.sample_rate)
            result = model.transcribe([audio_file.name], batch_size=1)
        text = _extract_nemo_text(result)

        return {
            "text": text,
            "language": language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": self.config.asr_parakeet_dtype,
            "implementation": "nemo.collections.asr.models.ASRModel",
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from nemo.collections.asr.models import ASRModel
        except ImportError as exc:
            raise ASRUnavailableError(
                "The parakeet-nemo backend requires nemo_toolkit[asr]. Install the NeMo ASR extra to enable ASR_BACKEND=parakeet-nemo."
            ) from exc

        model = ASRModel.from_pretrained(self.model_name)
        if hasattr(model, "to"):
            model.to(self.config.asr_device)
        if hasattr(model, "eval"):
            model.eval()
        dtype = self.config.asr_parakeet_dtype.strip().lower()
        if dtype == "float16" and self.config.asr_device.startswith("cuda") and hasattr(model, "half"):
            model.half()
        elif dtype in {"float32", "auto"} and hasattr(model, "float"):
            model.float()
        self._model = model
        return self._model


@dataclass(slots=True)
class ParakeetMLXAdapter:
    """MLX-backed Parakeet adapter for local Apple Silicon service benchmarks."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="parakeet-mlx")
    model_name: str = field(init=False)
    _model: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_parakeet_model

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        model = self._load_model()
        try:
            import soundfile as sf
        except ImportError as exc:
            raise ASRUnavailableError(
                "The parakeet-mlx backend requires soundfile. Install the MLX benchmark runtime to enable ASR_BACKEND=parakeet-mlx."
            ) from exc

        with tempfile.NamedTemporaryFile(prefix="rtc_asr_parakeet_mlx_", suffix=".wav") as audio_file:
            sf.write(audio_file.name, decoded_audio.samples, decoded_audio.sample_rate)
            result = model.transcribe(
                audio_file.name,
                dtype=_resolve_mlx_dtype(self.config.asr_parakeet_dtype),
            )
        text = _extract_mlx_text(result)

        return {
            "text": text,
            "language": language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": self.config.asr_parakeet_dtype,
            "implementation": "parakeet_mlx.from_pretrained",
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from parakeet_mlx import from_pretrained
        except ImportError as exc:
            raise ASRUnavailableError(
                "The parakeet-mlx backend requires parakeet-mlx. Install the MLX benchmark runtime to enable ASR_BACKEND=parakeet-mlx."
            ) from exc

        self._model = from_pretrained(
            self.model_name,
            dtype=_resolve_mlx_dtype(self.config.asr_parakeet_dtype),
        )
        return self._model


@dataclass(slots=True)
class VoxtralAdapter:
    """Experimental Transformers pipeline wrapper for Mistral Voxtral realtime ASR."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="voxtral")
    model_name: str = field(init=False)
    _pipeline: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_voxtral_model

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def preload(self) -> None:
        self._load_pipeline()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        pipeline = self._load_pipeline()
        generate_kwargs: dict[str, object] = {"max_new_tokens": self.config.asr_voxtral_max_new_tokens}
        if language:
            generate_kwargs["language"] = language
        kwargs = {"generate_kwargs": generate_kwargs}
        result = pipeline(
            {"array": decoded_audio.samples, "sampling_rate": decoded_audio.sample_rate},
            **kwargs,
        )

        return {
            "text": _extract_pipeline_text(result),
            "language": language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": self.config.asr_voxtral_dtype,
            "attn_implementation": self.config.asr_voxtral_attn_implementation,
            "max_new_tokens": self.config.asr_voxtral_max_new_tokens,
            "implementation": "transformers.pipeline",
            "task": "automatic-speech-recognition",
            "experimental": True,
            "model_card": "https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602",
            "runtime_aliases": [
                "voxtral",
                "voxtral-realtime",
                "voxtral-mini",
                "voxtral-mini-4b",
            ],
            "realtime_profile": {
                "provider": "mistralai",
                "family": "Voxtral Mini",
                "size": "4B",
                "recommended_backend": "voxtral-mini-4b",
                "serving_mode": "experimental_transformers_pipeline",
                "max_new_tokens": self.config.asr_voxtral_max_new_tokens,
                "streaming_contract": "local-stt-v1-compatible-buffered-decode",
            },
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        try:
            import torch
            from transformers import pipeline
        except ImportError as exc:
            raise ASRUnavailableError(
                "The voxtral backend requires transformers and torch. Install a Voxtral-compatible Hugging Face runtime to enable ASR_BACKEND=voxtral."
            ) from exc

        pipeline_kwargs: dict[str, object] = {
            "model": self.model_name,
            "device": self.config.asr_device,
            "dtype": _resolve_torch_dtype(torch, self.config.asr_voxtral_dtype, self.config.asr_device),
            "trust_remote_code": self.config.asr_voxtral_trust_remote_code,
        }
        if self.config.asr_voxtral_attn_implementation:
            pipeline_kwargs["model_kwargs"] = {
                "attn_implementation": self.config.asr_voxtral_attn_implementation,
            }

        self._pipeline = pipeline("automatic-speech-recognition", **pipeline_kwargs)
        return self._pipeline


@dataclass(slots=True)
class VoxtralMLXAdapter:
    """MLX-backed Voxtral Mini realtime adapter for Apple Silicon benchmarks."""

    config: AppConfig
    audio_processor: AudioProcessor
    backend_name: str = field(init=False, default="voxtral-mlx")
    model_name: str = field(init=False)
    _model: Any | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.model_name = self.config.asr_voxtral_mlx_model

    def is_loaded(self) -> bool:
        return self._model is not None

    def preload(self) -> None:
        self._load_model()

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, Any]:
        decoded_audio = self.audio_processor.load_audio(audio_data, sample_rate=sample_rate)
        model = self._load_model()
        try:
            import soundfile as sf
        except ImportError as exc:
            raise ASRUnavailableError(
                "The voxtral-mlx backend requires soundfile. Install the MLX benchmark runtime to enable ASR_BACKEND=voxtral-mlx."
            ) from exc

        with tempfile.NamedTemporaryFile(prefix="rtc_asr_voxtral_mlx_", suffix=".wav") as audio_file:
            sf.write(audio_file.name, decoded_audio.samples, decoded_audio.sample_rate)
            result = model.generate(
                audio_file.name,
                transcription_delay_ms=self.config.asr_voxtral_transcription_delay_ms,
            )

        return {
            "text": _extract_mlx_text(result),
            "language": language,
            "duration_ms": decoded_audio.duration_ms,
            "backend": self.backend_name,
            "model": self.model_name,
        }

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "device": self.config.asr_device,
            "implementation": "mlx_audio.stt.utils.load",
            "task": "automatic-speech-recognition",
            "experimental": True,
            "model_card": "https://huggingface.co/mlx-community/Voxtral-Mini-4B-Realtime-2602-4bit",
            "runtime_aliases": [
                "voxtral-mlx",
                "voxtral-mini-mlx",
                "voxtral-mini-4b-mlx",
                "voxtral-realtime-mlx",
            ],
            "realtime_profile": {
                "provider": "mlx-community",
                "family": "Voxtral Mini",
                "size": "4B",
                "quantization": "4bit",
                "recommended_backend": "voxtral-mlx",
                "serving_mode": "mlx_audio_file_generate",
                "transcription_delay_ms": self.config.asr_voxtral_transcription_delay_ms,
                "streaming_contract": "local-stt-v1-compatible-buffered-decode",
            },
            "loaded": self.is_loaded(),
            **_shared_capabilities(self.audio_processor),
        }

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        try:
            from mlx_audio.stt.utils import load
        except ImportError as exc:
            raise ASRUnavailableError(
                "The voxtral-mlx backend requires mlx-audio[stt]. Install the MLX benchmark runtime to enable ASR_BACKEND=voxtral-mlx."
            ) from exc

        self._model = load(self.model_name)
        return self._model


BACKEND_ALIASES = {
    "faster-whisper": "faster-whisper",
    "whisper": "faster-whisper",
    "qwen": "qwen-asr",
    "qwen-asr": "qwen-asr",
    "qwen3-asr": "qwen-asr",
    "parakeet": "parakeet",
    "parakeet-asr": "parakeet",
    "parakeet-nemo": "parakeet-nemo",
    "parakeet-ctc": "parakeet-nemo",
    "parakeet-mlx": "parakeet-mlx",
    "voxtral": "voxtral",
    "voxtral-mini": "voxtral",
    "voxtral-mini-4b": "voxtral",
    "voxtral-realtime": "voxtral",
    "voxtral-mlx": "voxtral-mlx",
    "voxtral-mini-mlx": "voxtral-mlx",
    "voxtral-mini-4b-mlx": "voxtral-mlx",
    "voxtral-realtime-mlx": "voxtral-mlx",
}


QWEN_LANGUAGE_ALIASES = {
    "ar": "Arabic",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fa": "Persian",
    "fi": "Finnish",
    "fil": "Filipino",
    "fr": "French",
    "hi": "Hindi",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sv": "Swedish",
    "th": "Thai",
    "tr": "Turkish",
    "vi": "Vietnamese",
    "yue": "Cantonese",
    "zh": "Chinese",
}


def _normalize_qwen_language(language: str | None) -> str | None:
    if language is None:
        return None
    return QWEN_LANGUAGE_ALIASES.get(language.lower(), language)


def _installed_package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _resolve_torch_dtype(torch: Any, configured_dtype: str, device: str) -> Any:
    dtype_name = configured_dtype.strip().lower()
    if dtype_name == "auto":
        dtype_name = "bfloat16" if device.startswith("cuda") else "float32"

    try:
        return getattr(torch, dtype_name)
    except AttributeError as exc:
        raise ASRUnavailableError(f"Unsupported dtype: {configured_dtype}") from exc


def _resolve_mlx_dtype(configured_dtype: str) -> Any:
    try:
        import mlx.core as mx
    except ImportError as exc:
        raise ASRUnavailableError(
            "The parakeet-mlx backend requires mlx. Install the MLX benchmark runtime to enable ASR_BACKEND=parakeet-mlx."
        ) from exc

    dtype_name = configured_dtype.strip().lower()
    if dtype_name == "auto":
        dtype_name = "bfloat16"

    try:
        return getattr(mx, dtype_name)
    except AttributeError as exc:
        raise ASRUnavailableError(f"Unsupported MLX dtype: {configured_dtype}") from exc


def _extract_nemo_text(result: Any) -> str:
    if isinstance(result, tuple) and result:
        return _extract_nemo_text(result[0])
    if isinstance(result, list) and result:
        return _extract_nemo_text(result[0])
    text = getattr(result, "text", None)
    if text is not None:
        return str(text).strip()
    return str(result).strip()


def _extract_mlx_text(result: Any) -> str:
    text = getattr(result, "text", None)
    if text is not None:
        return str(text).strip()
    return str(result).strip()


def _extract_pipeline_text(result: Any) -> str:
    if isinstance(result, dict):
        text = result.get("text", "")
        return str(text).strip()
    if isinstance(result, list) and result:
        return _extract_pipeline_text(result[0])
    return str(result).strip()


def _shared_capabilities(audio_processor: AudioProcessor) -> dict[str, Any]:
    return {
        "streaming": {
            "transport": "websocket",
            "path": "/ws/stream",
            "reusable_connection": True,
            "message_types": ["start", "audio", "stop", "cancel"],
            "audio_frame_formats": ["json-base64", "binary"],
            "event_types": ["ready", "partial", "final", "canceled", "error"],
        },
        "audio": {
            "target_sample_rate": audio_processor.config.sample_rate,
            "channels": 1,
            "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"],
        },
    }


def build_transcriber(config: AppConfig, audio_processor: AudioProcessor) -> Transcriber:
    backend = BACKEND_ALIASES.get(config.asr_backend, config.asr_backend)
    if backend == "faster-whisper":
        return FasterWhisperAdapter(config=config, audio_processor=audio_processor)
    if backend == "qwen-asr":
        return QwenASRAdapter(config=config, audio_processor=audio_processor)
    if backend == "parakeet":
        return ParakeetAdapter(config=config, audio_processor=audio_processor)
    if backend == "parakeet-nemo":
        return ParakeetNemoAdapter(config=config, audio_processor=audio_processor)
    if backend == "parakeet-mlx":
        return ParakeetMLXAdapter(config=config, audio_processor=audio_processor)
    if backend == "voxtral":
        return VoxtralAdapter(config=config, audio_processor=audio_processor)
    if backend == "voxtral-mlx":
        return VoxtralMLXAdapter(config=config, audio_processor=audio_processor)
    raise ASRUnavailableError(f"Unsupported ASR backend: {config.asr_backend}")
