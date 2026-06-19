from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .pipecat_bridge import BridgeUnavailableError, PipecatDemoBridge

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "web"


class OfferRequest(BaseModel):
    type: str = Field(..., description="Browser SDP description type. Must be offer.")
    sdp: str = Field(..., min_length=1, description="Browser SDP offer.")
    pc_id: str | None = Field(None, description="Existing Pipecat peer connection id.")
    restart_pc: bool | None = Field(None, description="Whether Pipecat should restart the peer connection.")
    request_data: dict[str, Any] | None = Field(None, description="Optional caller metadata.")
    use_smart_turn: bool = Field(
        True,
        description='Whether to request Pipecat "Silero VAD + Smart Turn" mode for this session.',
    )

    @field_validator("type")
    @classmethod
    def validate_offer_type(cls, value: str) -> str:
        if value != "offer":
            raise ValueError("type must be offer")
        return value


class OfferResponse(BaseModel):
    session_id: str
    type: str
    sdp: str
    state: str
    pc_id: str


bridge = PipecatDemoBridge()
app = FastAPI(title="rtc-asr Browser Pipecat Demo")
app.mount("/rtc-asr/assets", StaticFiles(directory=WEB_DIR), name="rtc-asr-assets")


@app.get("/rtc-asr", include_in_schema=False)
async def demo_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/rtc-asr/manifest.webmanifest", include_in_schema=False)
async def demo_manifest() -> FileResponse:
    return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/rtc-asr/sw.js", include_in_schema=False)
async def demo_service_worker() -> FileResponse:
    return FileResponse(
        WEB_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/rtc-asr"},
    )


@app.get("/rtc-asr/config")
async def demo_config() -> dict[str, object]:
    return bridge.config()


@app.post("/rtc-asr/offer", response_model=OfferResponse)
async def create_offer(request: OfferRequest) -> OfferResponse:
    logger.info("browser_pipecat_demo_offer_received", extra={"sdp_length": len(request.sdp)})
    try:
        session = await bridge.create_session(
            offer_type=request.type,
            offer_sdp=request.sdp,
            pc_id=request.pc_id,
            restart_pc=request.restart_pc,
            request_data=request.request_data,
            use_smart_turn=request.use_smart_turn,
        )
    except BridgeUnavailableError as exc:
        logger.info("browser_pipecat_demo_bridge_unavailable")
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "error": exc.error_code,
                "message": str(exc),
                "bridge_status": exc.bridge_status,
            },
        ) from exc

    if session.answer_sdp is None or session.answer_type is None or session.pc_id is None:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "PIPECAT_BRIDGE_INCOMPLETE_ANSWER",
                "message": "Pipecat bridge created a session without a complete SDP answer.",
                "bridge_status": bridge.bridge_status,
            },
        )

    return OfferResponse(
        session_id=session.session_id,
        type=session.answer_type,
        sdp=session.answer_sdp,
        state=session.state.value,
        pc_id=session.pc_id,
    )


@app.get("/rtc-asr/session/{session_id}")
async def get_session(session_id: str) -> dict[str, object]:
    session = bridge.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=404,
            detail={
                "error": "SESSION_NOT_FOUND",
                "message": "No demo session exists for that id.",
            },
        )
    return session.as_dict()
