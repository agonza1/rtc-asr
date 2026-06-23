from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, AsyncGenerator

try:  # pragma: no cover - exercised by downstream Pipecat installs.
    from pipecat.frames.frames import (  # type: ignore
        AudioRawFrame,
        CancelFrame,
        EndFrame,
        Frame,
        InterimTranscriptionFrame,
        InterruptionFrame,
        StartFrame,
        TranscriptionFrame,
        UserStoppedSpeakingFrame,
        VADUserStartedSpeakingFrame,
        VADUserStoppedSpeakingFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection  # type: ignore
    from pipecat.services.stt_service import STTService  # type: ignore
    from pipecat.services.settings import STTSettings  # type: ignore

    PIPECAT_AVAILABLE = True
except Exception:  # pragma: no cover - fallback is covered by local tests.
    PIPECAT_AVAILABLE = False

    class FrameDirection(Enum):
        DOWNSTREAM = "downstream"
        UPSTREAM = "upstream"

    class Frame:
        pass

    @dataclass(slots=True)
    class StartFrame(Frame):
        audio_in_sample_rate: int = 16000

    class EndFrame(Frame):
        pass

    class CancelFrame(Frame):
        pass

    class InterruptionFrame(Frame):
        pass

    class UserStoppedSpeakingFrame(Frame):
        pass

    class VADUserStartedSpeakingFrame(Frame):
        pass

    class VADUserStoppedSpeakingFrame(Frame):
        pass

    @dataclass(slots=True)
    class AudioRawFrame(Frame):
        audio: bytes
        sample_rate: int = 16000
        num_channels: int = 1
        user_id: str = ""

        @property
        def num_frames(self) -> int:
            return len(self.audio) // max(1, self.num_channels * 2)

    @dataclass(slots=True)
    class InterimTranscriptionFrame(Frame):
        text: str
        user_id: str
        timestamp: str
        language: str | None = None
        result: Any | None = None

    @dataclass(slots=True)
    class TranscriptionFrame(Frame):
        text: str
        user_id: str
        timestamp: str
        language: str | None = None
        result: Any | None = None
        finalized: bool = False

    @dataclass(slots=True)
    class STTSettings:
        model: str | None = None
        language: str | None = None

    class STTService:
        def __init__(self, *, audio_passthrough: bool = True, sample_rate: int | None = None, **_: Any) -> None:
            self._audio_passthrough = audio_passthrough
            self._sample_rate = sample_rate or 16000
            self._user_id = ""
            self.pushed_frames: list[tuple[Frame, FrameDirection]] = []

        @property
        def sample_rate(self) -> int:
            return self._sample_rate

        async def start(self, frame: StartFrame) -> None:
            self._sample_rate = getattr(frame, "audio_in_sample_rate", self._sample_rate)

        async def stop(self, frame: EndFrame) -> None:
            return None

        async def cancel(self, frame: CancelFrame) -> None:
            return None

        async def cleanup(self) -> None:
            return None

        async def process_generator(self, generator: AsyncGenerator[Frame | None, None]) -> None:
            async for frame in generator:
                if frame is not None:
                    await self.push_frame(frame)

        async def process_audio_frame(self, frame: AudioRawFrame, direction: FrameDirection) -> None:
            self._user_id = getattr(frame, "user_id", "")
            await self.process_generator(self.run_stt(frame.audio))

        async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
            if isinstance(frame, AudioRawFrame):
                await self.process_audio_frame(frame, direction)
                if self._audio_passthrough:
                    await self.push_frame(frame, direction)
            else:
                await self.push_frame(frame, direction)

        async def push_frame(
            self,
            frame: Frame,
            direction: FrameDirection = FrameDirection.DOWNSTREAM,
        ) -> None:
            self.pushed_frames.append((frame, direction))

        async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame | None, None]:
            yield None
