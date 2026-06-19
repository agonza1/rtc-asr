from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from examples.browser_pipecat_demo.service import app as app_module
from examples.browser_pipecat_demo.service.app import app
from examples.browser_pipecat_demo.service.pipecat_bridge import (
    PipecatDependencyMissingError,
    PipecatDemoBridge,
    PipecatRuntime,
    RTCASRAudioRelay,
    TranscriptEvent,
)


@dataclass
class FakePipecatRequest:
    sdp: str
    type: str
    pc_id: str | None = None
    restart_pc: bool | None = None
    request_data: Any | None = None


class FakeRequestHandler:
    async def handle_web_request(self, request: FakePipecatRequest, callback: Any) -> dict[str, str]:
        return {
            "sdp": "v=0\r\nfake-answer",
            "type": "answer",
            "pc_id": request.pc_id or "pc_fake",
        }


class FakeFrameProcessor:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass


class FakeFrameDirection:
    DOWNSTREAM = object()


class FakeInputAudioRawFrame:
    def __init__(self, audio: bytes, sample_rate: int = 16000, num_channels: int = 1) -> None:
        self.audio = audio
        self.sample_rate = sample_rate
        self.num_channels = num_channels


def fake_runtime_loader() -> PipecatRuntime:
    return PipecatRuntime(
        request_cls=FakePipecatRequest,
        request_handler_cls=FakeRequestHandler,
        transport_cls=object,
        transport_params_cls=object,
        pipeline_cls=object,
        frame_processor_cls=FakeFrameProcessor,
        frame_direction_cls=FakeFrameDirection,
        input_audio_frame_cls=FakeInputAudioRawFrame,
        pipeline_worker_cls=object,
        pipeline_params_cls=object,
        worker_runner_cls=object,
    )


def test_pipecat_demo_requirements_match_worker_api_minimum() -> None:
    requirements = (Path("examples") / "browser_pipecat_demo" / "requirements.txt").read_text(encoding="utf-8")

    assert "pipecat-ai[webrtc]>=1.3.0" in requirements
    assert "pipecat-ai[webrtc]>=0.0.86" not in requirements


def test_demo_page_serves_static_app() -> None:
    client = TestClient(app)

    response = client.get("/rtc-asr")

    assert response.status_code == 200
    assert "Browser WebRTC to local Pipecat edge" in response.text
    assert "Uploaded audio file" in response.text
    assert "ASR rollover" in response.text
    assert "/rtc-asr/assets/app.js?v=" in response.text
    assert "/rtc-asr/assets/styles.css?v=" in response.text
    assert "__RTC_ASR_DEMO_BUILD__" not in response.text
    assert "window.location.reload" not in response.text
    assert "/rtc-asr/manifest.webmanifest" in response.text
    assert 'id="asr-model-select"' in response.text
    assert "ASR model" in response.text
    assert 'id="install-help"' not in response.text
    assert "Silero VAD + smart turn" in response.text
    assert '<span class="smart-toggle" aria-hidden="true">' not in response.text
    assert '<span class="smart-toggle-slider" aria-hidden="true"></span>' in response.text
    assert '<ul id="final-log" class="log-list final-log"></ul>' in response.text
    assert '<ul id="event-log" class="log-list event-log" aria-live="polite"></ul>' in response.text


def test_demo_manifest_and_service_worker_are_served() -> None:
    client = TestClient(app)

    manifest_response = client.get("/rtc-asr/manifest.webmanifest")
    service_worker_response = client.get("/rtc-asr/sw.js")

    assert manifest_response.status_code == 200
    assert manifest_response.headers["content-type"].startswith("application/manifest+json")
    assert '"display": "standalone"' in manifest_response.text
    assert '"src": "/rtc-asr/assets/icons/icon-512.png"' in manifest_response.text

    assert service_worker_response.status_code == 200
    assert service_worker_response.headers["service-worker-allowed"] == "/rtc-asr"
    assert 'const CACHE_NAME = "rtc-asr-demo-shell-v3";' in service_worker_response.text
    assert '"/rtc-asr/assets/icons/apple-touch-icon.png"' in service_worker_response.text
    assert "const cacheFallback = () => caches.match(request, { ignoreSearch: true });" in service_worker_response.text
    assert "event.respondWith(fetch(request).catch(cacheFallback));" in service_worker_response.text

    app_js_response = client.get("/rtc-asr/assets/app.js")

    assert app_js_response.status_code == 200
    assert 'navigator.serviceWorker.register("/rtc-asr/sw.js", { scope: "/rtc-asr" })' in app_js_response.text
    assert "partial captured on stop" in app_js_response.text
    assert "state.lastPartialTranscript || elements.partialText.textContent" not in app_js_response.text
    assert 'message.type === "speech_started"' in app_js_response.text
    assert 'message.type === "sentence_boundary"' in app_js_response.text
    assert "beforeinstallprompt" not in app_js_response.text
    assert "deferredInstallPrompt" not in app_js_response.text


def missing_runtime_loader() -> PipecatRuntime:
    raise PipecatDependencyMissingError(
        "Install the demo WebRTC extras with "
        "`pip install -r examples/browser_pipecat_demo/requirements.txt` "
        "to enable Pipecat SmallWebRTC."
    )


def test_demo_config_reports_dependency_status(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bridge = PipecatDemoBridge(runtime_loader=missing_runtime_loader)
    monkeypatch.setattr(app_module, "bridge", fake_bridge)
    client = TestClient(app_module.app)

    response = client.get("/rtc-asr/config")

    assert response.status_code == 200
    assert response.json() == {
        "service": "browser-pipecat-demo",
        "route": "/rtc-asr",
        "pipecat_transport": "smallwebrtc",
        "rtc_asr_ws_url": "ws://127.0.0.1:8080/v1/stt/stream",
        "rtc_asr_chunk_ms": 100,
        "rtc_asr_max_utterance_seconds": 24.0,
        "asr_model_options": [
            {
                "id": "faster-whisper-base.en-int8",
                "label": "Faster-Whisper Base English int8",
                "backend": "faster-whisper",
                "model": "base.en",
                "device": "cpu",
                "compute_type": "int8",
            },
            {
                "id": "parakeet-mlx-110m",
                "label": "Parakeet 110M MLX",
                "backend": "parakeet-mlx",
                "model": "mlx-community/parakeet-tdt_ctc-110m",
                "device": "apple-silicon",
                "compute_type": "auto",
            },
            {
                "id": "parakeet-nemo-110m",
                "label": "Parakeet 110M NeMo",
                "backend": "parakeet-nemo",
                "model": "nvidia/parakeet-tdt_ctc-110m",
                "device": "cpu",
                "compute_type": "auto",
            },
            {
                "id": "parakeet-v3",
                "label": "Parakeet TDT 0.6B v3",
                "backend": "parakeet",
                "model": "nvidia/parakeet-tdt-0.6b-v3",
                "device": "cpu",
                "compute_type": "auto",
            },
            {
                "id": "qwen3-asr-0.6b",
                "label": "Qwen3 ASR 0.6B",
                "backend": "qwen-asr",
                "model": "Qwen/Qwen3-ASR-0.6B",
                "device": "cpu",
                "compute_type": "auto",
            },
        ],
        "default_asr_model_option_id": "faster-whisper-base.en-int8",
        "asr_model_label": "Faster-Whisper Base English int8",
        "asr_backend": "faster-whisper",
        "asr_model": "base.en",
        "bridge_status": "dependency_missing",
        "can_start_session": False,
        "default_use_smart_turn": True,
        "dependency_message": "Install the demo WebRTC extras with "
        "`pip install -r examples/browser_pipecat_demo/requirements.txt` "
        "to enable Pipecat SmallWebRTC.",
    }


def test_offer_returns_answer_with_fake_pipecat_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bridge = PipecatDemoBridge(
        runtime_loader=fake_runtime_loader,
        request_handler=FakeRequestHandler(),
    )
    monkeypatch.setattr(app_module, "bridge", fake_bridge)
    client = TestClient(app_module.app)

    response = client.post(
        "/rtc-asr/offer",
        json={
            "type": "offer",
            "sdp": "v=0",
            "use_smart_turn": True,
            "asr_model_option_id": "parakeet-mlx-110m",
            "request_data": {"demo_audio_source": "mic"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "session_id": payload["session_id"],
        "type": "answer",
        "sdp": "v=0\r\nfake-answer",
        "state": "connected",
        "pc_id": "pc_fake",
    }

    session = fake_bridge.get_session(payload["session_id"])
    assert session is not None
    assert session.metadata["use_smart_turn_requested"] == "true"
    assert session.metadata["smart_turn_mode"] == "requested"
    assert session.metadata["asr_model_option_id"] == "parakeet-mlx-110m"
    assert session.metadata["asr_model_label"] == "Parakeet 110M MLX"
    assert session.metadata["asr_backend"] == "parakeet-mlx"
    assert session.metadata["asr_model"] == "mlx-community/parakeet-tdt_ctc-110m"


@pytest.mark.anyio
async def test_asr_relay_batches_audio_into_configured_chunks() -> None:
    sent_chunks: list[bytes] = []
    app_messages: list[dict[str, object]] = []

    class FakeASRClient:
        def __init__(self, ws_url: str) -> None:
            self.ws_url = ws_url

        async def start(self, **kwargs: Any) -> dict[str, object]:
            return {"type": "ready"}

        async def send_audio(self, chunk: bytes, **kwargs: Any) -> None:
            sent_chunks.append(chunk)

        async def finalize(self) -> Any:
            return type(
                "FakeEvent",
                (),
                {
                    "type": "final",
                    "text": "",
                    "is_final": True,
                    "chunks_received": len(sent_chunks),
                    "stream_id": 1,
                    "buffered_bytes": 0,
                    "remaining_buffer_bytes": 0,
                    "revision": 1,
                    "audio_received_ms": None,
                    "audio_transcribed_ms": None,
                },
            )()

        async def close(self) -> None:
            return None

    relay = RTCASRAudioRelay(
        session_id="session_1",
        rtc_asr_ws_url="ws://example.test/ws",
        chunk_ms=100,
        max_utterance_seconds=24.0,
        smart_turn_enabled=False,
        send_app_message=app_messages.append,
        mark_failed=lambda message: None,
        asr_client_factory=FakeASRClient,
    )
    frame = FakeInputAudioRawFrame(audio=b"x" * 6400, sample_rate=16000, num_channels=1)

    await relay.handle_audio_frame(frame)

    assert [len(chunk) for chunk in sent_chunks] == [3200, 3200]
    assert app_messages[0]["type"] == "status"


@pytest.mark.anyio
async def test_asr_relay_starts_new_sentence_on_pause_boundary() -> None:
    app_messages: list[dict[str, object]] = []
    starts: list[str] = []
    finalizes: list[str] = []

    class FakeASRClient:
        def __init__(self, ws_url: str) -> None:
            self.ws_url = ws_url
            self.events: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
            self.partial_sent = False
            self.current_stream_id = ""

        async def start(self, **kwargs: Any) -> dict[str, object]:
            self.current_stream_id = str(kwargs.get("client_stream_id"))
            starts.append(self.current_stream_id)
            return {"type": "ready"}

        async def send_audio(self, chunk: bytes, **kwargs: Any) -> None:
            if not self.partial_sent:
                self.partial_sent = True
                await self.events.put(
                    TranscriptEvent(
                        type="partial",
                        text="hello there",
                        stream_id=1,
                        is_final=False,
                        chunks_received=1,
                        buffered_bytes=len(chunk),
                        remaining_buffer_bytes=3200,
                        revision=1,
                    )
                )

        async def finalize(self) -> None:
            finalizes.append(self.current_stream_id)
            self.partial_sent = False
            await self.events.put(
                TranscriptEvent(
                    type="final",
                    text="hello there",
                    stream_id=1,
                    is_final=True,
                    chunks_received=1,
                    buffered_bytes=0,
                    remaining_buffer_bytes=0,
                    revision=2,
                )
            )

        async def recv_event(self) -> TranscriptEvent:
            return await self.events.get()

        async def close(self) -> None:
            return None

    relay = RTCASRAudioRelay(
        session_id="session_turns",
        rtc_asr_ws_url="ws://example.test/ws",
        chunk_ms=100,
        max_utterance_seconds=24.0,
        smart_turn_enabled=True,
        send_app_message=app_messages.append,
        mark_failed=lambda message: None,
        asr_client_factory=FakeASRClient,
    )
    speech_frame = FakeInputAudioRawFrame(audio=struct.pack("<h", 2000) * 1600)
    pause_frame = FakeInputAudioRawFrame(audio=bytes(8000))

    await relay.handle_audio_frame(speech_frame)
    await asyncio.sleep(0.05)
    await relay.handle_audio_frame(pause_frame)
    await asyncio.sleep(0.05)

    assert len(starts) >= 2
    assert finalizes == [starts[0]]
    assert any(message.get("type") == "speech_started" for message in app_messages)
    assert any(message.get("type") == "speech_paused" for message in app_messages)
    assert any(message.get("type") == "sentence_boundary" for message in app_messages)

    await relay.close()


@pytest.mark.anyio
async def test_asr_relay_reports_websocket_start_failure() -> None:
    app_messages: list[dict[str, object]] = []
    failures: list[str] = []

    class FailingASRClient:
        def __init__(self, ws_url: str) -> None:
            self.ws_url = ws_url

        async def start(self, **kwargs: Any) -> dict[str, object]:
            raise RuntimeError("connect failed")

    relay = RTCASRAudioRelay(
        session_id="session_1",
        rtc_asr_ws_url="ws://example.test/ws",
        chunk_ms=100,
        max_utterance_seconds=24.0,
        smart_turn_enabled=False,
        send_app_message=app_messages.append,
        mark_failed=failures.append,
        asr_client_factory=FailingASRClient,
    )
    frame = FakeInputAudioRawFrame(audio=b"x" * 3200, sample_rate=16000, num_channels=1)

    with pytest.raises(RuntimeError, match="connect failed"):
        await relay.handle_audio_frame(frame)

    assert failures == ["ASR websocket start failed: connect failed"]
    assert app_messages == [
        {
            "type": "error",
            "message": "ASR websocket start failed: connect failed",
            "session_id": "session_1",
        }
    ]
