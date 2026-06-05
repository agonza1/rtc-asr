from __future__ import annotations

import base64
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from src.config import AppConfig
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
        self.calls.append(
            {
                "audio_size": len(audio_data),
                "language": language,
                "sample_rate": sample_rate,
                "prefix": audio_data[:4],
            }
        )
        return {
            "text": f"fixture transcription {len(self.calls)}",
            "language": language,
            "duration_ms": 125,
            "backend": self.backend_name,
            "model": self.model_name,
        }


class StableTextTranscriber(FakeTranscriber):
    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        result = super().transcribe(audio_data, language=language, sample_rate=sample_rate)
        result["text"] = "steady partial"
        return result


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
        "text": "fixture transcription 1",
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


def test_websocket_stream_emits_partial_and_final_events() -> None:
    transcriber = FakeTranscriber()
    chunk_one = b"first chunk"
    chunk_two = b" second chunk"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
            })
            ready = websocket.receive_json()
            assert ready == {
                "type": "ready",
                "stream_id": 1,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "en",
                "sample_rate": 16000,
                "partial_interval_chunks": 1,
            }

            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(chunk_one).decode("ascii"),
            })
            partial = websocket.receive_json()
            assert partial == {
                "type": "partial",
                "stream_id": 1,
                "is_final": False,
                "chunks_received": 1,
                "buffered_bytes": len(chunk_one),
                "text": "fixture transcription 1",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(chunk_two).decode("ascii"),
            })
            partial = websocket.receive_json()
            assert partial == {
                "type": "partial",
                "stream_id": 1,
                "is_final": False,
                "chunks_received": 2,
                "buffered_bytes": len(chunk_one) + len(chunk_two),
                "text": "fixture transcription 2",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()
            assert final_event == {
                "type": "final",
                "stream_id": 1,
                "is_final": True,
                "chunks_received": 2,
                "buffered_bytes": len(chunk_one) + len(chunk_two),
                "text": "fixture transcription 2",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

    assert transcriber.calls == [
        {
            "audio_size": len(chunk_one),
            "language": "en",
            "sample_rate": 16000,
            "prefix": chunk_one[:4],
        },
        {
            "audio_size": len(chunk_one) + len(chunk_two),
            "language": "en",
            "sample_rate": 16000,
            "prefix": chunk_one[:4],
        },
    ]


def test_websocket_stream_reuses_connection_for_multiple_utterances() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            websocket.send_json({"type": "stop"})
            first_final = websocket.receive_json()
            assert first_final == {
                "type": "final",
                "stream_id": 1,
                "is_final": True,
                "chunks_received": 1,
                "buffered_bytes": len(first_chunk),
                "text": "fixture transcription 1",
                "language": "en",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            second_ready = websocket.receive_json()
            assert second_ready == {
                "type": "ready",
                "stream_id": 2,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
                "language": "es",
                "sample_rate": 8000,
                "partial_interval_chunks": 1,
            }

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            second_partial = websocket.receive_json()
            assert second_partial == {
                "type": "partial",
                "stream_id": 2,
                "is_final": False,
                "chunks_received": 1,
                "buffered_bytes": len(second_chunk),
                "text": "fixture transcription 2",
                "language": "es",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

            websocket.send_json({"type": "stop"})
            second_final = websocket.receive_json()
            assert second_final == {
                "type": "final",
                "stream_id": 2,
                "is_final": True,
                "chunks_received": 1,
                "buffered_bytes": len(second_chunk),
                "text": "fixture transcription 2",
                "language": "es",
                "duration_ms": 125,
                "backend": "fake-whisper",
                "model": "fixture-adapter",
            }

    assert transcriber.calls == [
        {"audio_size": len(first_chunk), "language": "en", "sample_rate": 16000, "prefix": first_chunk[:4]},
        {"audio_size": len(second_chunk), "language": "es", "sample_rate": 8000, "prefix": second_chunk[:4]},
    ]


def test_websocket_stream_ids_reset_for_a_new_connection() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            first_ready = websocket.receive_json()

        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            second_ready = websocket.receive_json()

    assert first_ready["stream_id"] == 1
    assert second_ready["stream_id"] == 1
    assert first_ready["language"] == "en"
    assert second_ready["language"] == "es"


def test_websocket_stream_retranscribes_on_stop_when_partial_interval_skips_latest_chunk() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 2,
                }
            )
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            assert websocket.receive_json()["type"] == "partial"

            third_chunk = b"third"
            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(third_chunk).decode("ascii"),
                }
            )
            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 3,
        "buffered_bytes": len(first_chunk) + len(second_chunk) + len(third_chunk),
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
        {
            "audio_size": len(first_chunk) + len(second_chunk) + len(third_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
    ]


def test_legacy_env_aliases_and_cuda_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_NAME", "small.en")
    monkeypatch.delenv("ASR_MODEL_SIZE", raising=False)
    monkeypatch.setenv("AUDIO_SAMPLE_RATE", "22050")
    monkeypatch.delenv("SAMPLE_RATE", raising=False)
    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "0")
    monkeypatch.delenv("ASR_DEVICE", raising=False)

    config = AppConfig.from_env()

    assert config.asr_model_size == "small.en"
    assert config.sample_rate == 22050
    assert config.asr_device == "cuda"


def test_websocket_stream_emits_partial_updates_when_text_is_stable() -> None:
    transcriber = StableTextTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(first_chunk).decode("ascii"),
                }
            )
            first_partial = websocket.receive_json()

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(second_chunk).decode("ascii"),
                }
            )
            second_partial = websocket.receive_json()

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert first_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 1,
        "buffered_bytes": len(first_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert second_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert final_event == {
        "type": "final",
        "stream_id": 1,
        "is_final": True,
        "chunks_received": 2,
        "buffered_bytes": len(first_chunk) + len(second_chunk),
        "text": "steady partial",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {
            "audio_size": len(first_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
        },
    ]


def test_websocket_stream_error_payload_includes_close_code() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "stop"})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Send a start event before stopping the stream",
        "code": 1003,
    }
