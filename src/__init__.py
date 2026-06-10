"""Realtime ASR service package."""

from __future__ import annotations

from importlib import import_module

from .streaming import ASRWebSocketClient, StreamConfig, TranscriptEvent, transcribe_chunks

__all__ = [
    "ASRWebSocketClient",
    "StreamConfig",
    "TranscriptEvent",
    "app",
    "create_app",
    "model_loader",
    "transcribe_chunks",
]


def __getattr__(name: str):
    if name == "app":
        from .main import app

        return app
    if name == "create_app":
        from .main import create_app

        return create_app
    if name == "model_loader":
        return import_module(".model_loader", __name__)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
