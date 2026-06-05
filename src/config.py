"""Application configuration for the realtime ASR service."""

from __future__ import annotations

import os
from dataclasses import dataclass


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
            sample_rate=int(_first_env("SAMPLE_RATE", "AUDIO_SAMPLE_RATE") or str(defaults.sample_rate)),
            stream_max_buffer_bytes=stream_max_buffer_bytes,
            asr_backend=os.getenv("ASR_BACKEND", defaults.asr_backend),
            asr_model_size=_first_env("ASR_MODEL_SIZE", "MODEL_NAME") or defaults.asr_model_size,
            asr_device=_default_asr_device(defaults.asr_device),
            asr_compute_type=os.getenv("ASR_COMPUTE_TYPE", defaults.asr_compute_type),
            asr_vad_filter=_env_flag("ASR_VAD_FILTER", defaults.asr_vad_filter),
        )
