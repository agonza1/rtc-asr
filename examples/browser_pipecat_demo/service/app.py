from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.base import BaseHTTPMiddleware

from .pipecat_bridge import BridgeUnavailableError, PipecatDemoBridge

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
WEB_DIR = BASE_DIR / "web"
LOCAL_DEMO_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEMO_BUILD_TOKEN = "__RTC_ASR_DEMO_BUILD__"


def _is_local_demo_request(request: Request) -> bool:
    client_host = request.client.host if request.client is not None else ""
    host = request.headers.get("host") or client_host
    if host.startswith("[") and "]" in host:
        host = host[1 : host.find("]")]
    elif host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host in LOCAL_DEMO_HOSTS


class LocalDemoNoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.url.path.startswith("/rtc-asr") and _is_local_demo_request(request):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def _demo_cache_bust() -> int:
    files = [WEB_DIR / "index.html", WEB_DIR / "app.js", WEB_DIR / "styles.css"]
    return int(max(file.stat().st_mtime_ns for file in files))


def _demo_page_html() -> str:
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    return template.replace(DEMO_BUILD_TOKEN, str(_demo_cache_bust()))


class OfferRequest(BaseModel):
    type: str = Field(..., description="Browser SDP description type. Must be offer.")
    sdp: str = Field(..., min_length=1, description="Browser SDP offer.")
    pc_id: str | None = Field(None, description="Existing Pipecat peer connection id.")
    restart_pc: bool | None = Field(None, description="Whether Pipecat should restart the peer connection.")
    request_data: dict[str, Any] | None = Field(None, description="Optional caller metadata.")
    asr_model_option_id: str | None = Field(None, description="Demo ASR model option id selected by the browser.")
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
app.add_middleware(LocalDemoNoCacheMiddleware)
app.mount("/rtc-asr/assets", StaticFiles(directory=WEB_DIR), name="rtc-asr-assets")


@app.get("/rtc-asr", include_in_schema=False)
async def demo_page() -> HTMLResponse:
    return HTMLResponse(_demo_page_html())


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
            asr_model_option_id=request.asr_model_option_id,
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
