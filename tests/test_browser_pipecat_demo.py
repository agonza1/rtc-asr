from __future__ import annotations

from fastapi.testclient import TestClient

from examples.browser_pipecat_demo.service.app import app


def test_demo_page_serves_static_app() -> None:
    client = TestClient(app)

    response = client.get("/rtc-asr")

    assert response.status_code == 200
    assert "Browser WebRTC to local Pipecat edge" in response.text
    assert "/rtc-asr/assets/app.js" in response.text


def test_demo_config_reports_scaffold_status() -> None:
    client = TestClient(app)

    response = client.get("/rtc-asr/config")

    assert response.status_code == 200
    assert response.json() == {
        "service": "browser-pipecat-demo",
        "route": "/rtc-asr",
        "pipecat_transport": "smallwebrtc",
        "rtc_asr_ws_url": "ws://127.0.0.1:8080/ws/stream",
        "bridge_status": "scaffold",
    }


def test_offer_requires_offer_type() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "answer", "sdp": "v=0"})

    assert response.status_code == 422


def test_offer_requires_sdp() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "offer"})

    assert response.status_code == 422


def test_offer_returns_structured_not_configured_response() -> None:
    client = TestClient(app)

    response = client.post("/rtc-asr/offer", json={"type": "offer", "sdp": "v=0"})

    assert response.status_code == 501
    assert response.json() == {
        "detail": {
            "error": "PIPECAT_TRANSPORT_NOT_CONFIGURED",
            "message": "Pipecat SmallWebRTC transport wiring is documented but not enabled in this first iteration.",
            "bridge_status": "scaffold",
        }
    }


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

