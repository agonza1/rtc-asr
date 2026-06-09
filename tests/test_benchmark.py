from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("rtc_asr_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_benchmark", benchmark)
SPEC.loader.exec_module(benchmark)


class FakeBenchmarkWebSocket:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = [json.dumps(response) for response in responses]
        self.sent: list[object] = []

    async def __aenter__(self) -> "FakeBenchmarkWebSocket":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            self.sent.append(data)
            return
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if not self.responses:
            raise RuntimeError("No benchmark websocket responses left")
        return self.responses.pop(0)


def test_parse_args_accepts_binary_frame_and_window_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark.py",
            "--binary-frames",
            "--partial-interval-chunks",
            "3",
            "--max-buffer",
            "4.5",
        ],
    )

    args = benchmark.parse_args()

    assert args.binary_frames is True
    assert args.partial_interval_chunks == 3
    assert args.max_buffer == 4.5


def test_run_ws_benchmark_supports_binary_frames_and_window_overrides() -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "chunk two"},
            {"type": "final", "text": "done"},
        ]
    )

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"abcd",
            4,
            250,
            partial_interval_chunks=2,
            send_binary_frames=True,
            partial_window_seconds=1.5,
            max_buffer_seconds=6.0,
            connect_fn=fake_connect,
        )

        assert result["binary_frames"] is True
        assert result["chunks"] == 2
        assert result["last_partial"] == "chunk two"
        assert result["partial_first_ms"] is not None
        assert result["partial_last_ms"] is not None
        assert result["final_transcript"] == "done"
        assert websocket.sent == [
            {
                "type": "start",
                "language": "en",
                "sample_rate": 4,
                "partial_interval_chunks": 2,
                "partial_window_seconds": 1.5,
                "max_buffer_seconds": 6.0,
            },
            b"ab",
            b"cd",
            {"type": "stop"},
        ]

    asyncio.run(scenario())


def test_run_ws_benchmark_allows_sparse_partial_cadence() -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "final", "text": "done"},
        ]
    )

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"ab",
            4,
            250,
            partial_interval_chunks=2,
            connect_fn=fake_connect,
        )

        assert result["chunks"] == 1
        assert result["last_partial"] == ""
        assert result["partial_mean_ms"] is None
        assert result["partial_p95_ms"] is None
        assert result["final_transcript"] == "done"
        assert websocket.sent == [
            {
                "type": "start",
                "language": "en",
                "sample_rate": 4,
                "partial_interval_chunks": 2,
            },
            {
                "type": "audio",
                "audio_data": "YWI=",
            },
            {"type": "stop"},
        ]

    asyncio.run(scenario())


def test_run_ws_benchmark_rejects_non_ready_handshake() -> None:
    websocket = FakeBenchmarkWebSocket([
        {"type": "error", "message": "boot failed"},
    ])

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="Expected ready event"):
            await benchmark.run_ws_benchmark(
                "ws://example.test/ws/stream",
                b"ab",
                4,
                250,
                connect_fn=fake_connect,
            )

    asyncio.run(scenario())
