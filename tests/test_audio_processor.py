from __future__ import annotations

import io
import wave

import numpy as np
import pytest

from src.audio_processor import AudioConfig, AudioProcessor


def test_pcm16_fast_path_bypasses_generic_decoders(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000))

    def fail_decoder(*args: object, **kwargs: object) -> object:
        raise AssertionError("generic decoder should not run for raw PCM16 fast path")

    monkeypatch.setattr(processor, "_decode_wav", fail_decoder)
    monkeypatch.setattr(processor, "_decode_with_soundfile", fail_decoder)

    audio = np.array([0, 16384, -32768, 32767], dtype="<i2").tobytes()

    decoded = processor.load_audio(audio, sample_rate=16000)

    assert decoded.sample_rate == 16000
    assert decoded.samples.dtype == np.float32
    assert decoded.samples.tolist() == pytest.approx([0.0, 0.5, -1.0, 32767 / 32768])


def test_pcm16_fast_path_rejects_non_target_sample_rate() -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000, require_target_sample_rate=True))

    with pytest.raises(ValueError, match="sample_rate must be 16000"):
        processor.load_audio(b"\x00\x00", sample_rate=8000)


@pytest.mark.parametrize("sample_rate", [0, -16000])
def test_load_audio_rejects_non_positive_sample_rate(sample_rate: int) -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000, require_target_sample_rate=False))

    with pytest.raises(ValueError, match="sample_rate must be a positive integer"):
        processor.load_audio(b"\x00\x00", sample_rate=sample_rate)


def test_resample_rejects_non_positive_sample_rates() -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000))

    with pytest.raises(ValueError, match="Audio sample rates must be positive integers"):
        processor._resample(np.zeros(1, dtype=np.float32), 0, 16000)


def test_wav_bytes_keep_generic_decoder_even_when_sample_rate_is_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000))
    called = False

    def fake_decode_wav(audio_data: bytes) -> tuple[np.ndarray, int]:
        nonlocal called
        called = True
        assert audio_data.startswith(b"RIFF")
        return np.zeros(2, dtype=np.float32), 16000

    monkeypatch.setattr(processor, "_decode_wav", fake_decode_wav)

    decoded = processor.load_audio(b"RIFF-not-real-wav", sample_rate=22050)

    assert called
    assert decoded.samples.tolist() == [0.0, 0.0]


def test_decode_wav_supports_pcm24_without_optional_soundfile(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = AudioProcessor(AudioConfig(sample_rate=16000))
    samples = [0, 0x400000, -0x800000, 0x7FFFFF]
    wav_bytes = _build_pcm24_wav(samples, sample_rate=16000)

    def fail_soundfile(*args: object, **kwargs: object) -> object:
        raise AssertionError("24-bit PCM WAV should decode without soundfile fallback")

    monkeypatch.setattr(processor, "_decode_with_soundfile", fail_soundfile)

    decoded = processor.load_audio(wav_bytes)

    assert decoded.sample_rate == 16000
    assert decoded.samples.dtype == np.float32
    assert decoded.samples.tolist() == pytest.approx([0.0, 0.5, -1.0, 0x7FFFFF / 8388608])


def _build_pcm24_wav(samples: list[int], *, sample_rate: int) -> bytes:
    frames = b"".join(sample.to_bytes(3, "little", signed=True) for sample in samples)
    with io.BytesIO() as buffer:
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(3)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(frames)
        return buffer.getvalue()
