"""ASR backend abstraction and provider adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import metadata
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

        try:
            import torch
        except ImportError as exc:
            raise ASRUnavailableError(
                "The qwen-asr backend is not installed. Install requirements.txt to enable ASR_BACKEND=qwen-asr."
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

        self._pipeline = pipeline(
            "automatic-speech-recognition",
            model=self.model_name,
            device=self.config.asr_device,
            dtype=_resolve_torch_dtype(torch, self.config.asr_parakeet_dtype, self.config.asr_device),
        )
        return self._pipeline


BACKEND_ALIASES = {
    "faster-whisper": "faster-whisper",
    "whisper": "faster-whisper",
    "qwen": "qwen-asr",
    "qwen-asr": "qwen-asr",
    "qwen3-asr": "qwen-asr",
    "parakeet": "parakeet",
    "parakeet-asr": "parakeet",
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
    raise ASRUnavailableError(f"Unsupported ASR backend: {config.asr_backend}")
