from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from src.config import AppConfig
from src.main import create_app
from src.streaming import ASRWebSocketClient, StreamConfig, TranscriptEvent

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "smoke.wav"
DEFAULT_MAX_BUFFER_BYTES = AppConfig().stream_max_buffer_bytes


class FakeTranscriber:
    backend_name = "fake-whisper"
    model_name = "fixture-adapter"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.preload_calls = 0

    def is_loaded(self) -> bool:
        return self.preload_calls > 0

    def preload(self) -> None:
        self.preload_calls += 1

    def describe(self) -> dict[str, object]:
        return {
            "backend": self.backend_name,
            "model": self.model_name,
            "loaded": self.is_loaded(),
            "streaming": {
                "transport": "websocket",
                "path": "/ws/stream",
                "reusable_connection": True,
                "message_types": ["start", "audio", "stop"],
                "audio_frame_formats": ["json-base64", "binary"],
            },
        }

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


class FailingPreloadTranscriber(FakeTranscriber):
    def __init__(self, exc: Exception) -> None:
        super().__init__()
        self.exc = exc

    def preload(self) -> None:
        raise self.exc


class RecoveringPreloadTranscriber(FakeTranscriber):
    def __init__(self) -> None:
        super().__init__()
        self.loaded = False

    def is_loaded(self) -> bool:
        return self.loaded

    def preload(self) -> None:
        raise RuntimeError("model download failed")

    def transcribe(self, audio_data: bytes, *, language: str | None, sample_rate: int | None) -> dict[str, object]:
        self.loaded = True
        return super().transcribe(audio_data, language=language, sample_rate=sample_rate)


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


def test_ready_and_model_capabilities_smoke() -> None:
    transcriber = FakeTranscriber()
    with TestClient(create_app(transcriber=transcriber)) as client:
        ready = client.get("/ready")
        models = client.get("/api/models")

    assert ready.status_code == 200
    assert ready.json() == {
        "status": "ready",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "model_loaded": True,
        "preload_error": None,
    }
    assert models.status_code == 200
    assert models.json() == {
        "models": ["fixture-adapter"],
        "backend": "fake-whisper",
        "sample_rate": 16000,
        "capabilities": {
            "backend": "fake-whisper",
            "model": "fixture-adapter",
            "loaded": True,
            "streaming": {
                "transport": "websocket",
                "path": "/ws/stream",
                "reusable_connection": True,
                "message_types": ["start", "audio", "stop"],
                "audio_frame_formats": ["json-base64", "binary"],
            },
        },
    }
    assert transcriber.preload_calls == 1


def test_ready_returns_503_when_preload_is_degraded() -> None:
    transcriber = FailingPreloadTranscriber(RuntimeError("model download failed"))
    config = AppConfig(asr_fail_fast=False)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        ready = client.get("/ready")

    assert ready.status_code == 503
    assert ready.json() == {
        "status": "degraded",
        "service": "realtime-asr",
        "backend": "fake-whisper",
        "model": "fixture-adapter",
        "model_loaded": False,
        "preload_error": "model download failed",
    }


def test_ready_recovers_after_successful_transcription() -> None:
    transcriber = RecoveringPreloadTranscriber()
    config = AppConfig(asr_fail_fast=False)
    fixture_bytes = FIXTURE_PATH.read_bytes()

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        degraded_ready = client.get("/ready")
        transcribe = client.post(
            "/api/transcribe",
            json={
                "audio_data": base64.b64encode(fixture_bytes).decode("ascii"),
                "language": "en",
                "sample_rate": 16000,
            },
        )
        recovered_ready = client.get("/ready")

    assert degraded_ready.status_code == 503
    assert degraded_ready.json()["preload_error"] == "model download failed"
    assert transcribe.status_code == 200
    assert recovered_ready.status_code == 200
    assert recovered_ready.json()["preload_error"] is None
    assert recovered_ready.json()["model_loaded"] is True


def test_fail_fast_raises_for_non_asr_preload_failures() -> None:
    transcriber = FailingPreloadTranscriber(RuntimeError("invalid device"))
    config = AppConfig(asr_fail_fast=True)

    with pytest.raises(RuntimeError, match="invalid device"):
        with TestClient(create_app(config=config, transcriber=transcriber)):
            pass


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
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one),
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one) - len(chunk_two),
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(chunk_one) - len(chunk_two),
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


def test_websocket_stream_accepts_binary_audio_frames() -> None:
    transcriber = FakeTranscriber()
    first_chunk = b"first"
    second_chunk = b"second"

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_bytes(first_chunk)
            first_partial = websocket.receive_json()

            websocket.send_bytes(second_chunk)
            second_partial = websocket.receive_json()

            websocket.send_json({"type": "stop"})
            final_event = websocket.receive_json()

    assert first_partial == {
        "type": "partial",
        "stream_id": 1,
        "is_final": False,
        "chunks_received": 1,
        "buffered_bytes": len(first_chunk),
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
        "text": "fixture transcription 1",
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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "fixture transcription 2",
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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
        "text": "fixture transcription 2",
        "language": "en",
        "duration_ms": 125,
        "backend": "fake-whisper",
        "model": "fixture-adapter",
    }
    assert transcriber.calls == [
        {"audio_size": len(first_chunk), "language": "en", "sample_rate": 16000, "prefix": first_chunk[:4]},
        {
            "audio_size": len(first_chunk) + len(second_chunk),
            "language": "en",
            "sample_rate": 16000,
            "prefix": first_chunk[:4],
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
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
                "max_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES,
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(second_chunk),
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
                "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(second_chunk),
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


def test_websocket_stream_rejects_start_while_another_stream_is_active() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json({"type": "start", "language": "es", "sample_rate": 8000})
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Finish the active stream before starting a new one",
        "code": 1003,
    }
    assert transcriber.calls == []


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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk) - len(third_chunk),
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


@pytest.mark.parametrize("invalid_value", ["0", "-1"])
def test_stream_max_buffer_bytes_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: str,
) -> None:
    monkeypatch.setenv("STREAM_MAX_BUFFER_BYTES", invalid_value)

    with pytest.raises(ValueError, match="STREAM_MAX_BUFFER_BYTES must be a positive integer"):
        AppConfig.from_env()


def test_websocket_rejects_audio_before_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({
                "type": "audio",
                "audio_data": base64.b64encode(b"premature").decode("ascii"),
            })
            assert websocket.receive_json() == {
                "type": "error",
                "message": "Send a start event before audio chunks",
                "code": 1003,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1003
    assert transcriber.calls == []


def test_websocket_rejects_duplicate_start_events() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json({
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
            })
            assert websocket.receive_json() == {
                "type": "error",
                "message": "Finish the active stream before starting a new one",
                "code": 1003,
            }

            with pytest.raises(WebSocketDisconnect) as exc_info:
                websocket.receive_json()

    assert exc_info.value.code == 1003
    assert transcriber.calls == []


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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk),
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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
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
        "remaining_buffer_bytes": DEFAULT_MAX_BUFFER_BYTES - len(first_chunk) - len(second_chunk),
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



def test_websocket_stream_rejects_audio_that_exceeds_the_session_buffer_limit() -> None:
    transcriber = FakeTranscriber()
    config = AppConfig(stream_max_buffer_bytes=8)

    with TestClient(create_app(config=config, transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_json({"type": "start", "language": "en", "sample_rate": 16000})
            assert websocket.receive_json()["type"] == "ready"

            websocket.send_json(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(b"overflow!").decode("ascii"),
                }
            )
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Stream buffer exceeded 8 bytes; send stop and start a new stream",
        "code": 1009,
    }
    assert transcriber.calls == []


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


def test_websocket_stream_rejects_binary_audio_before_start() -> None:
    transcriber = FakeTranscriber()

    with TestClient(create_app(transcriber=transcriber)) as client:
        with client.websocket_connect("/ws/stream") as websocket:
            websocket.send_bytes(b"orphan-audio")
            error_event = websocket.receive_json()

    assert error_event == {
        "type": "error",
        "message": "Send a start event before audio chunks",
        "code": 1003,
    }
    assert transcriber.calls == []


def test_transcript_event_parses_remaining_buffer_bytes() -> None:
    event = TranscriptEvent.from_payload({
        "type": "partial",
        "text": "hel",
        "stream_id": 1,
        "buffered_bytes": 3,
        "remaining_buffer_bytes": 1021,
    })

    assert event.type == "partial"
    assert event.text == "hel"
    assert event.stream_id == 1
    assert event.buffered_bytes == 3
    assert event.remaining_buffer_bytes == 1021


def test_streaming_client_stops_after_error_event() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "error",
                        "message": "backend unavailable",
                        "code": 1011,
                    }
                ),
            ]
            self.sent: list[dict[str, object]] = []

        async def send(self, data: str) -> None:
            self.sent.append(json.loads(data))

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig(partial_event_timeout_seconds=0.01))

        assert [event.type for event in events] == ["ready", "error"]
        assert events[-1].text == "backend unavailable"
        assert client._websocket.sent == [
            {
                "type": "start",
                "language": "en",
                "sample_rate": 16000,
                "partial_interval_chunks": 1,
            },
            {
                "type": "audio",
                "audio_data": base64.b64encode(b"hel").decode("ascii"),
            },
        ]

    asyncio.run(scenario())


def test_streaming_client_drains_stale_partial_before_final() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "partial",
                        "stream_id": 1,
                        "is_final": False,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hel",
                    }
                ),
                json.dumps(
                    {
                        "type": "final",
                        "stream_id": 1,
                        "is_final": True,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hello",
                    }
                ),
            ]
            self.recv_calls = 0
            self.sent: list[dict[str, object]] = []

        async def send(self, data: str) -> None:
            self.sent.append(json.loads(data))

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig(partial_event_timeout_seconds=0.01))

        assert [event.type for event in events] == ["ready", "final"]
        assert events[-1].text == "hello"

    asyncio.run(scenario())


def test_streaming_client_stops_after_error_event() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "error",
                        "message": "model download failed",
                        "code": 1011,
                    }
                ),
            ]
            self.sent: list[object] = []

        async def send(self, data: str | bytes) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        events = await client.transcribe_once([b"hel"], config=StreamConfig())

        assert [event.type for event in events] == ["ready", "error"]
        assert client._websocket.sent == [
            json.dumps(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 1,
                }
            ),
            json.dumps(
                {
                    "type": "audio",
                    "audio_data": base64.b64encode(b"hel").decode("ascii"),
                }
            ),
        ]

    asyncio.run(scenario())


def test_streaming_client_can_send_binary_audio_frames() -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.responses = [
                json.dumps(
                    {
                        "type": "ready",
                        "stream_id": 1,
                        "backend": "fake-whisper",
                        "model": "fixture-adapter",
                        "language": "en",
                        "sample_rate": 16000,
                        "partial_interval_chunks": 1,
                    }
                ),
                json.dumps(
                    {
                        "type": "partial",
                        "stream_id": 1,
                        "is_final": False,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hel",
                    }
                ),
                json.dumps(
                    {
                        "type": "final",
                        "stream_id": 1,
                        "is_final": True,
                        "chunks_received": 1,
                        "buffered_bytes": 3,
                        "text": "hello",
                    }
                ),
            ]
            self.sent: list[object] = []

        async def send(self, data: str | bytes) -> None:
            self.sent.append(data)

        async def recv(self) -> str:
            return self.responses.pop(0)

        async def close(self) -> None:
            return None

    async def scenario() -> None:
        client = ASRWebSocketClient("ws://example.test/ws")
        client._websocket = FakeSocket()
        await client.transcribe_once([b"hel"], config=StreamConfig(send_binary_frames=True))

        assert client._websocket.sent == [
            json.dumps(
                {
                    "type": "start",
                    "language": "en",
                    "sample_rate": 16000,
                    "partial_interval_chunks": 1,
                }
            ),
            b"hel",
            json.dumps({"type": "stop"}),
        ]

    asyncio.run(scenario())
