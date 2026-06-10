from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest


MODULE_PATH = Path(__file__).with_name("benchmark.py")
SPEC = importlib.util.spec_from_file_location("rtc_asr_benchmark", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_benchmark", benchmark)
SPEC.loader.exec_module(benchmark)

compute_accuracy_metrics = benchmark.compute_accuracy_metrics
normalize_text = benchmark.normalize_text
resolve_reference_text = benchmark.resolve_reference_text
summarize_latencies = benchmark.summarize_latencies


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


def test_parse_args_rejects_zero_or_negative_runtime_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--partial-interval-chunks", "0"])
    with pytest.raises(SystemExit):
        benchmark.parse_args()

    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--rest-runs", "0"])
    with pytest.raises(SystemExit):
        benchmark.parse_args()

    monkeypatch.setattr(sys, "argv", ["benchmark.py", "--request-retry-delay", "-0.5"])
    with pytest.raises(SystemExit):
        benchmark.parse_args()


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
            "--request-retries",
            "5",
            "--request-retry-delay",
            "0.25",
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
    assert args.request_retries == 5
    assert args.request_retry_delay == 0.25
    assert args.output == Path("docs/benchmark-results/ultravox-compose-test.json")


def test_makefile_faster_whisper_benchmark_targets_use_shared_ten_sample_count_and_serialization() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "FASTER_WHISPER_BASE_MODEL ?= base.en" in makefile
    assert "FASTER_WHISPER_SMALL_MODEL ?= small.en" in makefile
    assert "FASTER_WHISPER_COMPUTE_TYPE ?= int8" in makefile
    assert "benchmark: venv" in makefile
    assert "benchmark-faster-whisper-base: venv" in makefile
    assert "benchmark-faster-whisper-small: venv" in makefile
    assert ".NOTPARALLEL: benchmark-faster-whisper-matrix benchmark-compose-matrix" in makefile
    assert "benchmark-faster-whisper-matrix: benchmark-faster-whisper-base benchmark-faster-whisper-small" in makefile
    for model_var in ("BASE", "SMALL"):
        line = next(
            line
            for line in makefile.splitlines()
            if f"faster-whisper-$(FASTER_WHISPER_{model_var}_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json" in line
        )
        assert "--sample-count $(BENCHMARK_SAMPLE_COUNT)" in line
        assert "--compute-type $(FASTER_WHISPER_COMPUTE_TYPE)" in line


def test_makefile_venv_target_repairs_broken_virtualenvs_before_benchmarks() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    venv_block = makefile.split("venv:\n", 1)[1].split("\n\n", 1)[0]
    assert 'if [ -x $(PYTHON) ] && $(PYTHON) -c "import sys" >/dev/null 2>&1; then \\' in venv_block
    assert 'echo "  Rebuilding $(VENV) because the interpreter is missing or broken..."; \\' in venv_block
    assert "rm -rf $(VENV); \\" in venv_block
    assert "python3 -m venv $(VENV); \\" in venv_block
    assert "$(PIP) install --upgrade pip; \\" in venv_block
    assert "$(PIP) install -r requirements.txt; \\" in venv_block
    assert '@echo "  ✓ Virtualenv ready at $(VENV)"' in venv_block


def test_makefile_compose_benchmark_targets_use_shared_ten_sample_count() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "BENCHMARK_SAMPLE_COUNT ?= 10" in makefile
    assert "BENCHMARK_REQUEST_RETRIES ?= 3" in makefile
    assert "benchmark-compose-matrix: benchmark-compose-qwen benchmark-compose-parakeet benchmark-compose-parakeet-nemo benchmark-compose-ultravox" in makefile
    assert "PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 8" in makefile
    assert "QWEN_MLX_TEXT_MODEL ?= Qwen/Qwen3-0.6B-MLX-4bit" in makefile
    assert "benchmark-qwen-mlx-text:" in makefile
    assert "MLX_VENV ?= .venv-mlx" in makefile
    assert "$(MLX_PYTHON) -m pip install --upgrade pip mlx-lm psutil" in makefile
    assert "scripts/benchmark_mlx_text.py --model $(QWEN_MLX_TEXT_MODEL)" in makefile
    for target_name, target in (("benchmark-compose-qwen: venv", "qwen"), ("benchmark-compose-parakeet: venv", "parakeet"), ("benchmark-compose-parakeet-nemo: venv", "parakeet-nemo-110m"), ("benchmark-compose-ultravox: venv", "ultravox")):
        assert target_name in makefile
        line = next(
            line
            for line in makefile.splitlines()
            if f"/{target}-compose-$(BENCHMARK_RESULT_DATE).json" in line
        )
        assert "--sample-count $(BENCHMARK_SAMPLE_COUNT)" in line
        assert "--request-retries $(BENCHMARK_REQUEST_RETRIES)" in line
        assert "--request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY)" in line


def test_makefile_compose_benchmark_targets_cleanup_compose_stack() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

<<<<<<< HEAD
    for target, backend in (("benchmark-compose-qwen", "qwen-asr"), ("benchmark-compose-parakeet", "parakeet"), ("benchmark-compose-parakeet-nemo", "parakeet-nemo"), ("benchmark-compose-ultravox", "ultravox")):
        block = makefile.split(f"{target}: venv\n", 1)[1].split("\n\n", 1)[0]
        assert "@{ set -e; \\" in block
        assert "trap cleanup EXIT INT TERM" in block
        assert "cleanup() { docker compose down >/dev/null 2>&1 || true; }" in block
        assert "docker compose up -d --build; \\" in block
        assert "Compose stack ready: $(COMPOSE_URL)/ready" in block
        assert block.rstrip().endswith("; }")
        assert f"--backend {backend}" in block


def test_checked_in_benchmark_artifacts_include_current_harness_metadata() -> None:
    artifact_expectations = {
        "faster-whisper-base.en-int8-2026-06-10.json": {
            "partial_interval_chunks": 1,
            "binary_frames": False,
            "partial_window_seconds": 2.0,
            "max_buffer_seconds": None,
            "request_retries": 3,
            "request_retry_delay": 2.0,
        },
        "faster-whisper-small.en-int8-2026-06-10.json": {
            "partial_interval_chunks": 1,
            "binary_frames": False,
            "partial_window_seconds": 2.0,
            "max_buffer_seconds": None,
            "request_retries": 3,
            "request_retry_delay": 2.0,
        },
        "parakeet-compose-2026-06-10.json": {
            "partial_interval_chunks": 1,
            "binary_frames": False,
            "partial_window_seconds": 2.0,
            "max_buffer_seconds": None,
            "request_retries": 3,
            "request_retry_delay": 2.0,
        },
        "parakeet-nemo-110m-compose-2026-06-09.json": {
            "partial_interval_chunks": 8,
            "binary_frames": False,
            "partial_window_seconds": 2.0,
            "max_buffer_seconds": None,
            "request_retries": 3,
            "request_retry_delay": 2.0,
        },
    }

    results_dir = Path("docs") / "benchmark-results"
    for artifact_name, expected_values in artifact_expectations.items():
        benchmark_metadata = json.loads((results_dir / artifact_name).read_text(encoding="utf-8"))["benchmark"]
        for key, expected in expected_values.items():
            assert benchmark_metadata[key] == expected


def test_checked_in_benchmark_artifacts_include_streaming_sample_binary_frame_metadata() -> None:
    results_dir = Path("docs") / "benchmark-results"
    validated_artifacts = [
        "faster-whisper-base.en-int8-2026-06-10.json",
        "faster-whisper-small.en-int8-2026-06-10.json",
        "parakeet-compose-2026-06-10.json",
        "parakeet-nemo-110m-compose-2026-06-09.json",
    ]

    for artifact_name in validated_artifacts:
        payload = json.loads((results_dir / artifact_name).read_text(encoding="utf-8"))
        benchmark_binary_frames = payload["benchmark"]["binary_frames"]
        streaming_samples = payload["samples"]["streaming"]
        assert streaming_samples, f"{artifact_name} should contain streaming samples"
        for sample in streaming_samples:
            assert isinstance(sample["binary_frames"], bool)
            assert sample["binary_frames"] == benchmark_binary_frames


def test_benchmarks_doc_validated_artifact_rows_reference_checked_in_current_schema_artifacts() -> None:
    benchmarks_doc = (Path("docs") / "benchmarks.md").read_text(encoding="utf-8")
    results_dir = Path("docs") / "benchmark-results"
    required_metadata_keys = {
        "partial_interval_chunks",
        "binary_frames",
        "partial_window_seconds",
        "max_buffer_seconds",
        "request_retries",
        "request_retry_delay",
    }

    validated_rows = [
        line
        for line in benchmarks_doc.splitlines()
        if line.startswith("| `")
        and "| validated artifact" in line
        and "text-generation feasibility benchmark" not in line
    ]
    assert validated_rows

    for row in validated_rows:
        artifact_name = row.split("`docs/benchmark-results/", 1)[1].split("`", 1)[0]
        artifact_path = results_dir / artifact_name
        assert artifact_path.exists(), f"documented artifact missing: {artifact_name}"

        benchmark_metadata = json.loads(artifact_path.read_text(encoding="utf-8"))["benchmark"]
        missing_keys = required_metadata_keys.difference(benchmark_metadata)
        assert not missing_keys, f"{artifact_name} missing metadata keys: {sorted(missing_keys)}"
=======
    for target in ("benchmark-compose-qwen", "benchmark-compose-parakeet", "benchmark-compose-ultravox"):
        block = makefile.split(f"{target}:\n", 1)[1].split("\n\n", 1)[0]
        assert "trap cleanup EXIT INT TERM" in block
        assert "cleanup() { docker compose down >/dev/null 2>&1 || true; }" in block
>>>>>>> 6af194e (Auto-clean compose benchmark targets)


def test_benchmarks_doc_legacy_artifact_rows_reference_checked_in_legacy_schema_artifacts() -> None:
    benchmarks_doc = (Path("docs") / "benchmarks.md").read_text(encoding="utf-8")
    results_dir = Path("docs") / "benchmark-results"

    legacy_rows = [
        line
        for line in benchmarks_doc.splitlines()
        if line.startswith("| `") and "| validated legacy artifact" in line
    ]
    assert legacy_rows

    for row in legacy_rows:
        artifact_name = row.split("`docs/benchmark-results/", 1)[1].split("`", 1)[0]
        artifact_path = results_dir / artifact_name
        assert artifact_path.exists(), f"documented legacy artifact missing: {artifact_name}"

        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert payload["backend"]["name"] == "qwen-asr"
        assert payload["rest"]["runs"] == 5
        assert payload["streaming"]["chunk_ms"] == 250
        assert payload["streaming"]["ready"]["partial_interval_chunks"] == 1
        assert set(payload["service"]["capabilities"]["streaming"]["audio_frame_formats"]) == {"json-base64", "binary"}


def test_post_transcribe_with_retries_retries_transient_read_errors() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.calls = 0

        async def post(self, path: str, json: dict[str, object]) -> httpx.Response:
            self.calls += 1
            assert path == "/api/transcribe"
            assert json["language"] == "en"
            if self.calls == 1:
                raise httpx.ReadError("dropped")
            return httpx.Response(200, json={"text": "ok"}, request=httpx.Request("POST", "http://example.test/api/transcribe"))

    async def scenario() -> None:
        client = FakeClient()
        response = await benchmark.post_transcribe_with_retries(
            client,
            {"language": "en"},
            attempts=2,
            retry_delay=0,
            stage="REST warmup",
        )
        assert response.json() == {"text": "ok"}
        assert client.calls == 2

    asyncio.run(scenario())


def test_post_transcribe_with_retries_raises_stage_aware_error_after_exhaustion() -> None:
    class FakeClient:
        async def post(self, path: str, json: dict[str, object]) -> httpx.Response:
            assert path == "/api/transcribe"
            raise httpx.ReadError("socket closed")

    async def scenario() -> None:
        with pytest.raises(
            benchmark.BenchmarkRequestError,
            match=r"REST sample 2/5 failed after 2 attempt\(s\): ReadError: socket closed",
        ):
            await benchmark.post_transcribe_with_retries(
                FakeClient(),
                {"language": "en"},
                attempts=2,
                retry_delay=0,
                stage="REST sample 2/5",
            )

    asyncio.run(scenario())


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
