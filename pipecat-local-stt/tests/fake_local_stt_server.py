from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(slots=True)
class FakeLocalSTTServerConfig:
    interim_every_frames: int = 1
    decode_delay_s: float = 0.0
    force_disconnect_after_frames: int | None = None
    malformed_event_after_frames: int | None = None
    final_text: str = "hello world"


class FakeLocalSTTWebSocket:
    def __init__(self, config: FakeLocalSTTServerConfig | None = None) -> None:
        self.config = config or FakeLocalSTTServerConfig()
        self.sent: list[str | bytes] = []
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.closed = False
        self.finalize_count = 0
        self.binary_frames_received = 0

    async def send(self, data: str | bytes) -> None:
        if self.closed:
            raise ConnectionError("fake Local STT websocket is closed")
        self.sent.append(data)
        if isinstance(data, bytes):
            await self._handle_audio(data)
            return
        payload = json.loads(data)
        event_type = payload["type"]
        if event_type == "start":
            await self.incoming.put(json.dumps({"type": "ready", "metadata": payload.get("metadata", {})}))
        elif event_type == "finalize":
            self.finalize_count += 1
            await self._maybe_sleep()
            await self.incoming.put(
                json.dumps(
                    {
                        "type": "transcript",
                        "text": self.config.final_text,
                        "is_final": True,
                        "speech_final": True,
                        "revision": self.binary_frames_received + 1,
                        "audio_received_ms": self.binary_frames_received * 20,
                        "audio_transcribed_ms": self.binary_frames_received * 20,
                        "metadata": {"local_stt_generation": self._current_generation()},
                    }
                )
            )
        elif event_type == "cancel":
            await self.incoming.put(json.dumps({"type": "canceled"}))
        elif event_type == "close":
            await self.incoming.put(json.dumps({"type": "closed", "reason": "client_close"}))

    async def recv(self) -> str:
        if self.closed:
            raise ConnectionError("fake Local STT websocket is closed")
        return await self.incoming.get()

    async def close(self, code: int = 1000) -> None:
        self.closed = True

    def connect_fn(self) -> Callable[[str], object]:
        async def connect(_url: str) -> FakeLocalSTTWebSocket:
            return self

        return connect

    async def _handle_audio(self, data: bytes) -> None:
        self.binary_frames_received += 1
        if self.config.force_disconnect_after_frames == self.binary_frames_received:
            self.closed = True
            raise ConnectionError("forced fake Local STT disconnect")
        if self.config.malformed_event_after_frames == self.binary_frames_received:
            await self.incoming.put("{malformed-json")
            return
        if self.binary_frames_received % self.config.interim_every_frames != 0:
            return
        await self._maybe_sleep()
        await self.incoming.put(
            json.dumps(
                {
                    "type": "transcript",
                    "text": "hel",
                    "is_final": False,
                    "speech_final": False,
                    "revision": self.binary_frames_received,
                    "audio_received_ms": self.binary_frames_received * 20,
                    "audio_transcribed_ms": self.binary_frames_received * 20,
                    "metadata": {"local_stt_generation": self._current_generation()},
                }
            )
        )

    async def _maybe_sleep(self) -> None:
        if self.config.decode_delay_s > 0:
            await asyncio.sleep(self.config.decode_delay_s)

    def _current_generation(self) -> int:
        for item in reversed(self.sent):
            if isinstance(item, str):
                payload = json.loads(item)
                if payload.get("type") == "start":
                    metadata = payload.get("metadata", {})
                    return int(metadata.get("local_stt_generation", 0))
        return 0
