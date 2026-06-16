from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from .pipecat_bridge import BridgeUnavailableError, PipecatDemoBridge

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "web"


class OfferRequest(BaseModel):
    type: str = Field(..., description="Browser SDP description type. Must be offer.")
    sdp: str = Field(..., min_length=1, description="Browser SDP offer.")

    @field_validator("type")
    @classmethod
    def validate_offer_type(cls, value: str) -> str:
        if value != "offer":
            raise ValueError("type must be offer")
        return value


bridge = PipecatDemoBridge()
app = FastAPI(title="rtc-asr Browser Pipecat Demo")
app.mount("/rtc-asr/assets", StaticFiles(directory=WEB_DIR), name="rtc-asr-assets")


@app.get("/rtc-asr", include_in_schema=False)
async def demo_page() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/rtc-asr/config")
async def demo_config() -> dict[str, str]:
    return bridge.config()


@app.post("/rtc-asr/offer")
async def create_offer(request: OfferRequest) -> dict[str, object]:
    logger.info("browser_pipecat_demo_offer_received", extra={"sdp_length": len(request.sdp)})
    try:
        session = await bridge.create_session(offer_type=request.type, offer_sdp=request.sdp)
    except BridgeUnavailableError as exc:
        logger.info("browser_pipecat_demo_bridge_unavailable")
        raise HTTPException(
            status_code=501,
            detail={
                "error": exc.error_code,
                "message": str(exc),
                "bridge_status": bridge.bridge_status,
            },
        ) from exc

    return {
        "session_id": session.session_id,
        "type": "answer",
        "sdp": session.answer_sdp,
        "state": session.state.value,
    }


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

