"""Application configuration for the realtime ASR service."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class AppConfig:
    """Runtime configuration loaded from environment variables."""

    app_name: str = "Realtime ASR Service"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8080
    cors_origins: tuple[str, ...] = ("*",)
    sample_rate: int = 16000
    asr_backend: str = "faster-whisper"
    asr_model_size: str = "tiny.en"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_vad_filter: bool = True

    @classmethod
    def from_env(cls) -> "AppConfig":
        defaults = cls()
        return cls(
            app_name=os.getenv("APP_NAME", defaults.app_name),
            app_version=os.getenv("APP_VERSION", defaults.app_version),
            host=os.getenv("HOST", defaults.host),
            port=int(os.getenv("PORT", str(defaults.port))),
            sample_rate=int(os.getenv("SAMPLE_RATE", str(defaults.sample_rate))),
            asr_backend=os.getenv("ASR_BACKEND", defaults.asr_backend),
            asr_model_size=os.getenv("ASR_MODEL_SIZE", defaults.asr_model_size),
            asr_device=os.getenv("ASR_DEVICE", defaults.asr_device),
            asr_compute_type=os.getenv("ASR_COMPUTE_TYPE", defaults.asr_compute_type),
            asr_vad_filter=_env_flag("ASR_VAD_FILTER", defaults.asr_vad_filter),
        )
