from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.benchmark import compute_accuracy_metrics, normalize_text, resolve_reference_text, summarize_latencies

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


def test_normalize_text_strips_case_and_punctuation() -> None:
    assert normalize_text("Hello,   WORLD!") == "hello world"


def test_compute_accuracy_metrics_reports_word_and_character_error_rate() -> None:
    metrics = compute_accuracy_metrics("the quick brown fox", "the quick fox")

    assert metrics is not None
    assert metrics["word_error_rate"] == 0.25
    assert metrics["character_error_rate"] > 0
    assert metrics["exact_match"] is False


def test_resolve_reference_text_prefers_explicit_inputs(tmp_path: Path) -> None:
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("from file", encoding="utf-8")

    args = argparse.Namespace(reference_text="from text", reference_file=reference_file, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "from text"

    args = argparse.Namespace(reference_text=None, reference_file=reference_file, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "from file"

    args = argparse.Namespace(reference_text=None, reference_file=None, speech_text="fallback")
    assert resolve_reference_text(args, synthesized=True) == "fallback"
    assert resolve_reference_text(args, synthesized=False) is None


def test_summarize_latencies_reports_mean_and_p90() -> None:
    summary = summarize_latencies([10.0, 20.0, 30.0], duration_s=2.0)

    assert summary["mean_ms"] == 20.0
    assert summary["p90_ms"] == 30.0
    assert summary["p95_ms"] == 30.0
    assert summary["min_ms"] == 10.0
    assert summary["max_ms"] == 30.0
    assert summary["rtf_mean"] == 0.01


def test_parse_args_accepts_binary_frame_window_and_ultravox_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark.py",
            "--backend",
            "ultravox",
            "--ultravox-dtype",
            "float32",
            "--ultravox-max-new-tokens",
            "96",
            "--ultravox-prompt",
            "Return only the transcript.",
            "--binary-frames",
            "--partial-interval-chunks",
            "3",
            "--max-buffer",
            "4.5",
            "--output",
            "docs/benchmark-results/ultravox-compose-test.json",
        ],
    )

    args = benchmark.parse_args()

    assert args.backend == "ultravox"
    assert args.ultravox_dtype == "float32"
    assert args.ultravox_max_new_tokens == 96
    assert args.ultravox_prompt == "Return only the transcript."
    assert args.binary_frames is True
    assert args.partial_interval_chunks == 3
    assert args.max_buffer == 4.5
    assert args.output == Path("docs/benchmark-results/ultravox-compose-test.json")


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
        assert result["partial_p90_ms"] is None
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

def test_run_ws_benchmark_rejects_unexpected_partial_event() -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "final", "text": "too early"},
        ]
    )

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="Expected partial event"):
            await benchmark.run_ws_benchmark(
                "ws://example.test/ws/stream",
                b"abcd",
                4,
                250,
                connect_fn=fake_connect,
            )

    asyncio.run(scenario())

def test_run_ws_benchmark_rejects_non_final_stop_event() -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "chunk"},
            {"type": "partial", "text": "still partial"},
        ]
    )

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="Expected final event"):
            await benchmark.run_ws_benchmark(
                "ws://example.test/ws/stream",
                b"ab",
                4,
                250,
                connect_fn=fake_connect,
            )

    asyncio.run(scenario())
