"""Application configuration for the realtime ASR service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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


def _positive_int_env(name: str, default: int) -> int:
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_int_first_env(*names: str, default: int) -> int:
    for name in names:
        value = os.getenv(name)
        if value:
            parsed = int(value)
            if parsed <= 0:
                raise ValueError(f"{name} must be a positive integer")
            return parsed
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
    local_stt_enable_pcm16_fast_path: bool = True
    local_stt_require_target_sample_rate: bool = True
    local_stt_target_sample_rate: int = 16000
    local_stt_socket_mode: Literal["tcp", "uds"] = "tcp"
    local_stt_uds_path: str = "/run/rtc-asr/stt.sock"
    local_stt_raw_uds_enabled: bool = False
    local_stt_raw_uds_path: str = "/run/rtc-asr/stt.raw.sock"
    asr_backend: str = "faster-whisper"
    asr_model_size: str = "base.en"
    asr_device: str = "cpu"
    asr_compute_type: str = "int8"
    asr_vad_filter: bool = True
    asr_preload_model: bool = False
    asr_fail_fast: bool = False
    asr_qwen_model: str = "Qwen/Qwen3-ASR-0.6B"
    asr_qwen_dtype: str = "auto"
    asr_qwen_device_map: str | None = None
    asr_qwen_max_new_tokens: int = 256
    asr_qwen_max_inference_batch_size: int = 1
    asr_parakeet_model: str = "nvidia/parakeet-tdt-0.6b-v3"
    asr_parakeet_dtype: str = "auto"
    asr_voxtral_model: str = "mistralai/Voxtral-Mini-4B-Realtime-2602"
    asr_voxtral_mlx_model: str = "mlx-community/Voxtral-Mini-4B-Realtime-2602-4bit"
    asr_voxtral_dtype: str = "auto"
    asr_voxtral_attn_implementation: str | None = None
    asr_voxtral_max_new_tokens: int = 128
    asr_voxtral_transcription_delay_ms: int = 480
    asr_voxtral_trust_remote_code: bool = True

    @classmethod
    def from_env(cls) -> "AppConfig":
        defaults = cls()
        stream_max_buffer_bytes = int(
            os.getenv("STREAM_MAX_BUFFER_BYTES", str(defaults.stream_max_buffer_bytes))
        )
        if stream_max_buffer_bytes <= 0:
            raise ValueError("STREAM_MAX_BUFFER_BYTES must be a positive integer")
        local_stt_socket_mode = os.getenv("LOCAL_STT_SOCKET_MODE", defaults.local_stt_socket_mode).strip().lower()
        if local_stt_socket_mode not in {"tcp", "uds"}:
            raise ValueError("LOCAL_STT_SOCKET_MODE must be 'tcp' or 'uds'")
        local_stt_uds_path = os.getenv("LOCAL_STT_UDS_PATH", defaults.local_stt_uds_path)
        if local_stt_socket_mode == "uds" and not local_stt_uds_path.strip():
            raise ValueError("LOCAL_STT_UDS_PATH is required when LOCAL_STT_SOCKET_MODE=uds")
        local_stt_raw_uds_path = os.getenv("LOCAL_STT_RAW_UDS_PATH", defaults.local_stt_raw_uds_path)
        if not local_stt_raw_uds_path.strip():
            raise ValueError("LOCAL_STT_RAW_UDS_PATH must not be empty")

        return cls(
            app_name=os.getenv("APP_NAME", defaults.app_name),
            app_version=os.getenv("APP_VERSION", defaults.app_version),
            host=os.getenv("HOST", defaults.host),
            port=_positive_int_env("PORT", defaults.port),
            cors_origins=_cors_origins(os.getenv("CORS_ORIGINS"), defaults.cors_origins),
            sample_rate=_positive_int_first_env(
                "SAMPLE_RATE",
                "AUDIO_SAMPLE_RATE",
                default=defaults.sample_rate,
            ),
            stream_max_buffer_bytes=stream_max_buffer_bytes,
            local_stt_enable_pcm16_fast_path=_env_flag(
                "LOCAL_STT_ENABLE_PCM16_FAST_PATH",
                defaults.local_stt_enable_pcm16_fast_path,
            ),
            local_stt_require_target_sample_rate=_env_flag(
                "LOCAL_STT_REQUIRE_TARGET_SAMPLE_RATE",
                defaults.local_stt_require_target_sample_rate,
            ),
            local_stt_target_sample_rate=_positive_int_env(
                "LOCAL_STT_TARGET_SAMPLE_RATE",
                defaults.local_stt_target_sample_rate,
            ),
            local_stt_socket_mode=local_stt_socket_mode,
            local_stt_uds_path=str(Path(local_stt_uds_path)),
            local_stt_raw_uds_enabled=_env_flag(
                "LOCAL_STT_RAW_UDS_ENABLED",
                defaults.local_stt_raw_uds_enabled,
            ),
            local_stt_raw_uds_path=str(Path(local_stt_raw_uds_path)),
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
            asr_qwen_max_new_tokens=_positive_int_env(
                "ASR_QWEN_MAX_NEW_TOKENS",
                defaults.asr_qwen_max_new_tokens,
            ),
            asr_qwen_max_inference_batch_size=_positive_int_env(
                "ASR_QWEN_MAX_INFERENCE_BATCH_SIZE",
                defaults.asr_qwen_max_inference_batch_size,
            ),
            asr_parakeet_model=os.getenv("ASR_PARAKEET_MODEL", defaults.asr_parakeet_model),
            asr_parakeet_dtype=os.getenv("ASR_PARAKEET_DTYPE", defaults.asr_parakeet_dtype),
            asr_voxtral_model=os.getenv("ASR_VOXTRAL_MODEL", defaults.asr_voxtral_model),
            asr_voxtral_mlx_model=os.getenv("ASR_VOXTRAL_MLX_MODEL", defaults.asr_voxtral_mlx_model),
            asr_voxtral_dtype=os.getenv("ASR_VOXTRAL_DTYPE", defaults.asr_voxtral_dtype),
            asr_voxtral_attn_implementation=os.getenv(
                "ASR_VOXTRAL_ATTN_IMPLEMENTATION",
                defaults.asr_voxtral_attn_implementation,
            ),
            asr_voxtral_max_new_tokens=_positive_int_env(
                "ASR_VOXTRAL_MAX_NEW_TOKENS",
                defaults.asr_voxtral_max_new_tokens,
            ),
            asr_voxtral_transcription_delay_ms=_positive_int_env(
                "ASR_VOXTRAL_TRANSCRIPTION_DELAY_MS",
                defaults.asr_voxtral_transcription_delay_ms,
            ),
            asr_voxtral_trust_remote_code=_env_flag(
                "ASR_VOXTRAL_TRUST_REMOTE_CODE",
                defaults.asr_voxtral_trust_remote_code,
            ),
        )
