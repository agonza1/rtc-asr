from __future__ import annotations

from dataclasses import dataclass
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


def test_demo_page_serves_static_app() -> None:
    client = TestClient(app)

    response = client.get("/rtc-asr")

    assert response.status_code == 200
    assert "Browser WebRTC to local Pipecat edge" in response.text
    assert "Uploaded audio file" in response.text
    assert "/rtc-asr/assets/app.js" in response.text


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
        "bridge_status": "dependency_missing",
    }


def test_offer_requires_offer_type() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "answer", "sdp": "v=0"})

    assert response.status_code == 422


def test_offer_requires_sdp() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "offer"})

    assert response.status_code == 422


def test_offer_rejects_empty_sdp() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "offer", "sdp": ""})

    assert response.status_code == 422


def test_offer_returns_structured_dependency_response(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bridge = PipecatDemoBridge(runtime_loader=missing_runtime_loader)
    monkeypatch.setattr(app_module, "bridge", fake_bridge)
    client = TestClient(app_module.app)

    response = client.post("/rtc-asr/offer", json={"type": "offer", "sdp": "v=0"})

    assert response.status_code == 501
    assert response.json() == {
        "detail": {
            "error": "PIPECAT_WEBRTC_DEPENDENCY_MISSING",
            "message": "Install the demo WebRTC extras with "
            "`pip install -r examples/browser_pipecat_demo/requirements.txt` "
            "to enable Pipecat SmallWebRTC.",
            "bridge_status": "dependency_missing",
        }
    }


def test_offer_returns_answer_with_fake_pipecat_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_bridge = PipecatDemoBridge(
        runtime_loader=fake_runtime_loader,
        request_handler=FakeRequestHandler(),
    )
    monkeypatch.setattr(app_module, "bridge", fake_bridge)
    client = TestClient(app_module.app)

    response = client.post("/rtc-asr/offer", json={"type": "offer", "sdp": "v=0"})

    assert response.status_code == 200
    assert response.json() == {
        "session_id": response.json()["session_id"],
        "type": "answer",
        "sdp": "v=0\r\nfake-answer",
        "state": "connected",
        "pc_id": "pc_fake",
    }


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
            return None

        async def finalize(self) -> Any:
            return type(
                "FakeEvent",
                (),
                {
                    "type": "final",
                    "text": "",
                    "is_final": True,
                    "chunks_received": len(sent_chunks),
                },
            )()

        async def close(self) -> None:
            return None

    relay = RTCASRAudioRelay(
        session_id="session_1",
        rtc_asr_ws_url="ws://example.test/ws",
        chunk_ms=100,
        send_app_message=app_messages.append,
        mark_failed=lambda message: None,
        asr_client_factory=FakeASRClient,
    )
    frame = FakeInputAudioRawFrame(audio=b"x" * 6400, sample_rate=16000, num_channels=1)

    await relay.handle_audio_frame(frame)

    assert [len(chunk) for chunk in sent_chunks] == [3200, 3200]
    assert app_messages[0]["type"] == "status"


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


def test_unknown_session_returns_404() -> None:
    client = TestClient(app)

    response = client.get("/rtc-asr/session/missing")

    assert response.status_code == 404
    assert response.json() == {
        "detail": {
            "error": "SESSION_NOT_FOUND",
            "message": "No demo session exists for that id.",
        }
    }
