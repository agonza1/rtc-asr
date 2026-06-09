"""Application configuration for the realtime ASR service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _cors_origins(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default

    origins = tuple(origin.strip() for origin in value.split(",") if origin.strip())
    return origins or default


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _default_asr_device(default: str) -> str:
    explicit = _first_env("ASR_DEVICE")
    if explicit:
        return explicit

    visible_devices = _first_env("CUDA_VISIBLE_DEVICES")
    if visible_devices and visible_devices.strip() not in {"", "-1", "none", "None"}:
        return "cuda"

    return default


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration loaded from environment variables."""

    app_name: str = "Realtime ASR Service"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: tuple[str, ...] = ("*",)
    sample_rate: int = 16000
    stream_max_buffer_bytes: int = 1024 * 1024
    asr_backend: str = "faster-whisper"
    asr_model_size: str = "tiny.en"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_vad_filter: bool = True
    asr_preload_model: bool = True
    asr_fail_fast: bool = False
    asr_qwen_model: str = "Qwen/Qwen3-ASR-0.6B"
    asr_qwen_dtype: str = "auto"
    asr_qwen_device_map: str | None = None
    asr_qwen_max_new_tokens: int = 256
    asr_qwen_max_inference_batch_size: int = 1
    asr_parakeet_model: str = "nvidia/parakeet-tdt-0.6b-v3"
    asr_parakeet_dtype: str = "auto"
    asr_ultravox_model: str = "fixie-ai/ultravox-v0_6-llama-3_1-8b"
    asr_ultravox_dtype: str = "auto"
    asr_ultravox_max_new_tokens: int = 128
    asr_ultravox_prompt: str = "Transcribe the spoken audio exactly and return only the transcript."

    @classmethod
    def from_env(cls) -> "AppConfig":
        defaults = cls()
        stream_max_buffer_bytes = int(
            os.getenv("STREAM_MAX_BUFFER_BYTES", str(defaults.stream_max_buffer_bytes))
        )
        if stream_max_buffer_bytes <= 0:
            raise ValueError("STREAM_MAX_BUFFER_BYTES must be a positive integer")

        return cls(
            app_name=os.getenv("APP_NAME", defaults.app_name),
            app_version=os.getenv("APP_VERSION", defaults.app_version),
            host=os.getenv("HOST", defaults.host),
            port=int(os.getenv("PORT", str(defaults.port))),
            cors_origins=_cors_origins(os.getenv("CORS_ORIGINS"), defaults.cors_origins),
            sample_rate=int(_first_env("SAMPLE_RATE", "AUDIO_SAMPLE_RATE") or str(defaults.sample_rate)),
            stream_max_buffer_bytes=stream_max_buffer_bytes,
            asr_backend=os.getenv("ASR_BACKEND", defaults.asr_backend),
            asr_model_size=_first_env("ASR_MODEL_SIZE", "MODEL_NAME") or defaults.asr_model_size,
            asr_device=_default_asr_device(defaults.asr_device),
            asr_compute_type=os.getenv("ASR_COMPUTE_TYPE", defaults.asr_compute_type),
            asr_vad_filter=_env_flag("ASR_VAD_FILTER", defaults.asr_vad_filter),
            asr_preload_model=_env_flag("ASR_PRELOAD_MODEL", defaults.asr_preload_model),
            asr_fail_fast=_env_flag("ASR_FAIL_FAST", defaults.asr_fail_fast),
            asr_qwen_model=os.getenv("ASR_QWEN_MODEL", defaults.asr_qwen_model),
            asr_qwen_dtype=os.getenv("ASR_QWEN_DTYPE", defaults.asr_qwen_dtype),
            asr_qwen_device_map=os.getenv("ASR_QWEN_DEVICE_MAP", defaults.asr_qwen_device_map),
            asr_qwen_max_new_tokens=int(
                os.getenv("ASR_QWEN_MAX_NEW_TOKENS", str(defaults.asr_qwen_max_new_tokens))
            ),
            asr_qwen_max_inference_batch_size=int(
                os.getenv(
                    "ASR_QWEN_MAX_INFERENCE_BATCH_SIZE",
                    str(defaults.asr_qwen_max_inference_batch_size),
                )
            ),
            asr_parakeet_model=os.getenv("ASR_PARAKEET_MODEL", defaults.asr_parakeet_model),
            asr_parakeet_dtype=os.getenv("ASR_PARAKEET_DTYPE", defaults.asr_parakeet_dtype),
            asr_ultravox_model=os.getenv("ASR_ULTRAVOX_MODEL", defaults.asr_ultravox_model),
            asr_ultravox_dtype=os.getenv("ASR_ULTRAVOX_DTYPE", defaults.asr_ultravox_dtype),
            asr_ultravox_max_new_tokens=int(
                os.getenv("ASR_ULTRAVOX_MAX_NEW_TOKENS", str(defaults.asr_ultravox_max_new_tokens))
            ),
            asr_ultravox_prompt=os.getenv("ASR_ULTRAVOX_PROMPT", defaults.asr_ultravox_prompt),
        )
