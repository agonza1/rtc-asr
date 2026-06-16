from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class BridgeUnavailableError(RuntimeError):
    """Raised when the demo bridge cannot create a media session yet."""

    error_code = "PIPECAT_TRANSPORT_NOT_CONFIGURED"


class SessionState(str, Enum):
    STARTING = "starting"
    WAITING_FOR_PIPECAT = "waiting_for_pipecat"
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass(slots=True)
class DemoSession:
    session_id: str
    created_at: datetime
    state: SessionState
    offer_type: str
    offer_sdp_length: int
    answer_sdp: str | None = None
    error: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "offer_type": self.offer_type,
            "offer_sdp_length": self.offer_sdp_length,
            "has_answer": self.answer_sdp is not None,
            "error": self.error,
            "metadata": self.metadata,
        }


class PipecatDemoBridge:
    """Session facade for the local browser-to-Pipecat demo.

    The first iteration keeps this explicit: Pipecat's SmallWebRTC transport is
    the intended implementation point, but the transport is not yet a dependency
    of this repository. Returning a structured failure avoids a fake WebRTC
    success path while preserving the service boundary for the next PR.
    """

    def __init__(self, *, rtc_asr_ws_url: str | None = None) -> None:
        self.rtc_asr_ws_url = rtc_asr_ws_url or os.getenv(
            "RTC_ASR_WS_URL",
            "ws://127.0.0.1:8080/ws/stream",
        )
        self._sessions: dict[str, DemoSession] = {}

    @property
    def bridge_status(self) -> str:
        return "scaffold"

    def config(self) -> dict[str, str]:
        return {
            "service": "browser-pipecat-demo",
            "route": "/rtc-asr",
            "pipecat_transport": "smallwebrtc",
            "rtc_asr_ws_url": self.rtc_asr_ws_url,
            "bridge_status": self.bridge_status,
        }

    async def create_session(self, *, offer_type: str, offer_sdp: str) -> DemoSession:
        session = DemoSession(
            session_id=str(uuid4()),
            created_at=datetime.now(timezone.utc),
            state=SessionState.WAITING_FOR_PIPECAT,
            offer_type=offer_type,
            offer_sdp_length=len(offer_sdp),
            error=BridgeUnavailableError.error_code,
            metadata={"rtc_asr_ws_url": self.rtc_asr_ws_url},
        )
        self._sessions[session.session_id] = session
        raise BridgeUnavailableError(
            "Pipecat SmallWebRTC transport wiring is documented but not enabled in this first iteration."
        )

    def get_session(self, session_id: str) -> DemoSession | None:
        return self._sessions.get(session_id)

