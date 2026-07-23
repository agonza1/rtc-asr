"""Audio decoding and normalization helpers."""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass

import numpy as np


@dataclass(slots=True, frozen=True)
class AudioConfig:
    sample_rate: int = 16000
    enable_pcm16_fast_path: bool = True
    require_target_sample_rate: bool = True


@dataclass(slots=True, frozen=True)
class DecodedAudio:
    samples: np.ndarray
    sample_rate: int

    @property
    def duration_ms(self) -> int:
        if self.samples.size == 0:
            return 0
        return int(round((self.samples.shape[0] / self.sample_rate) * 1000))


class AudioProcessor:
    """Load supported audio bytes and normalize them to mono float32."""

    def __init__(self, config: AudioConfig | None = None):
        self.config = config or AudioConfig()

    def load_audio(self, audio_data: bytes, sample_rate: int | None = None) -> DecodedAudio:
        if not audio_data:
            raise ValueError("No audio data provided")
        if sample_rate is not None and sample_rate <= 0:
            raise ValueError("sample_rate must be a positive integer")

        if self._should_use_pcm16_fast_path(audio_data, sample_rate):
            return DecodedAudio(
                samples=self._decode_pcm16(audio_data),
                sample_rate=sample_rate or self.config.sample_rate,
            )

        try:
            samples, detected_rate = self._decode_wav(audio_data)
        except (wave.Error, ValueError):
            try:
                samples, detected_rate = self._decode_with_soundfile(audio_data)
            except ValueError:
                if sample_rate is None:
                    raise ValueError("Unsupported audio format; provide WAV data or specify sample_rate for raw PCM16 audio")
                samples = self._decode_pcm16(audio_data)
                detected_rate = sample_rate

        target_rate = self.config.sample_rate
        if detected_rate != target_rate:
            samples = self._resample(samples, detected_rate, target_rate)
            detected_rate = target_rate

        return DecodedAudio(samples=samples, sample_rate=detected_rate)

    def cleanup(self) -> None:
        return None

    def _decode_wav(self, audio_data: bytes) -> tuple[np.ndarray, int]:
        with wave.open(io.BytesIO(audio_data), "rb") as wav_file:
            frame_rate = wav_file.getframerate()
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.readframes(wav_file.getnframes())

        if sample_width == 1:
            pcm = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
            pcm = (pcm - 128.0) / 128.0
        elif sample_width == 2:
            pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
        elif sample_width == 3:
            pcm = self._decode_pcm24(frames)
        elif sample_width == 4:
            pcm = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"Unsupported WAV sample width: {sample_width}")

        if channels > 1:
            pcm = pcm.reshape(-1, channels).mean(axis=1)

        return pcm.astype(np.float32, copy=False), frame_rate

    def _decode_with_soundfile(self, audio_data: bytes) -> tuple[np.ndarray, int]:
        try:
            import soundfile as sf
        except ImportError as exc:
            raise ValueError("soundfile is not installed") from exc

        try:
            samples, sample_rate = sf.read(io.BytesIO(audio_data), dtype="float32", always_2d=False)
        except RuntimeError as exc:
            raise ValueError("soundfile could not decode audio") from exc

        if isinstance(samples, np.ndarray) and samples.ndim > 1:
            samples = samples.mean(axis=1)

        return np.asarray(samples, dtype=np.float32), int(sample_rate)

    def _decode_pcm16(self, audio_data: bytes) -> np.ndarray:
        if len(audio_data) % 2 != 0:
            raise ValueError("Raw PCM16 audio must contain an even number of bytes")
        return np.frombuffer(audio_data, dtype="<i2").astype(np.float32) / 32768.0

    def _decode_pcm24(self, audio_data: bytes) -> np.ndarray:
        if len(audio_data) % 3 != 0:
            raise ValueError("PCM24 audio must contain complete 3 byte samples")
        packed = np.frombuffer(audio_data, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float32) / 8388608.0

    def _should_use_pcm16_fast_path(self, audio_data: bytes, sample_rate: int | None) -> bool:
        if not self.config.enable_pcm16_fast_path or sample_rate is None:
            return False
        if audio_data.startswith(b"RIFF") or audio_data.startswith(b"FORM"):
            return False
        if self.config.require_target_sample_rate and sample_rate != self.config.sample_rate:
            raise ValueError(f"Raw PCM16 audio sample_rate must be {self.config.sample_rate}")
        return True

    def _resample(self, samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
        if source_rate <= 0 or target_rate <= 0:
            raise ValueError("Audio sample rates must be positive integers")
        if samples.size == 0:
            return samples.astype(np.float32, copy=False)

        duration_seconds = samples.shape[0] / source_rate
        target_length = max(int(round(duration_seconds * target_rate)), 1)

        source_positions = np.linspace(0.0, duration_seconds, num=samples.shape[0], endpoint=False)
        target_positions = np.linspace(0.0, duration_seconds, num=target_length, endpoint=False)
        resampled = np.interp(target_positions, source_positions, samples)
        return resampled.astype(np.float32, copy=False)
