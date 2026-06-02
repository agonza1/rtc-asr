from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient

from src.main import create_app

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smoke.wav"


class FakeTranscriber:
    backend_name = "fake-whisper"
    model_name = "fixture-adapter"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def is_loaded(self) -> bool:
        return True

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        self.calls.append({
            "audio_size": len(audio_data),
            "language": language,
            "sample_rate": sample_rate,
            "prefix": audio_data[:4],
        })
        return {
            "text": "fixture transcription",
            "language": language,
            "duration_ms": 125,
            "backend": self.backend_name,
            "model": self.model_name,
        }


def test_health_smoke() -> None:
    transcriber = FakeTranscriber()
    with TestClient(create_app(transcriber=transcriber)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "model_loaded": True,
    }


def test_transcribe_smoke_fixture() -> None:
    fixture_bytes = FIXTURE_PATH.read_bytes()
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        response = client.post(
            "/api/transcribe",
            json={
                "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                "language": "en",
                "sample_rate": 16000,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "text": "fixture transcription",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(fixture_bytes),
            "language": "en",
            "sample_rate": 16000,
            "prefix": b"RIFF",
        }
    ]
