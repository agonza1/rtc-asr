"""Realtime ASR service package."""

from __future__ import annotations

from .streaming import ASRWebSocketClient, StreamConfig, TranscriptEvent, transcribe_chunks

__all__ = [
    "ASRWebSocketClient",
    "StreamConfig",
    "TranscriptEvent",
    "app",
    "create_app",
    "transcribe_chunks",
]


def __getattr__(name: str):
    if name == "app":
        from .main import app

        return app
    if name == "create_app":
        from .main import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
