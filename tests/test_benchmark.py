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


def test_makefile_faster_whisper_benchmark_targets_use_shared_ten_sample_count_and_serialization() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "FASTER_WHISPER_BASE_MODEL ?= base.en" in makefile
    assert "FASTER_WHISPER_SMALL_MODEL ?= small.en" in makefile
    assert "FASTER_WHISPER_COMPUTE_TYPE ?= int8" in makefile
    assert "benchmark: venv" in makefile
    assert "benchmark-faster-whisper-base: venv" in makefile
    assert "benchmark-faster-whisper-small: venv" in makefile
    assert "benchmark-faster-whisper-base-low-latency-sweep: venv" in makefile
    assert "benchmark-faster-whisper-small-low-latency-sweep: venv" in makefile
    assert "benchmark-qwen-mps-low-latency-sweep: venv" in makefile
    assert "benchmark-compose-qwen-low-latency-sweep: venv" in makefile
    assert "benchmark-compose-parakeet-low-latency-sweep: venv" in makefile
    assert "benchmark-compose-parakeet-nemo-low-latency-sweep: venv" in makefile
    assert "benchmark-all-asr-low-latency-sweep:" in makefile
    assert ".NOTPARALLEL: benchmark-faster-whisper-matrix benchmark-faster-whisper-base-low-latency-sweep benchmark-faster-whisper-small-low-latency-sweep benchmark-qwen-mps-low-latency-sweep benchmark-compose-qwen-low-latency-sweep benchmark-compose-parakeet-low-latency-sweep benchmark-compose-parakeet-nemo-low-latency-sweep benchmark-all-asr-low-latency-sweep benchmark-compose-matrix" in makefile
    assert "benchmark-faster-whisper-matrix: benchmark-faster-whisper-base benchmark-faster-whisper-small" in makefile
    for model_var in ("BASE", "SMALL"):
        line = next(
            line
            for line in makefile.splitlines()
            if f"faster-whisper-$(FASTER_WHISPER_{model_var}_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json" in line
        )
        assert "--sample-count $(BENCHMARK_SAMPLE_COUNT)" in line
        assert "--compute-type $(FASTER_WHISPER_COMPUTE_TYPE)" in line

    sweep_block = makefile.split("benchmark-faster-whisper-base-low-latency-sweep: venv\n", 1)[1].split("\n\n", 1)[0]
    assert "LOW_LATENCY_SWEEP_SAMPLE_COUNT ?= 5" in makefile
    assert "LOW_LATENCY_SWEEP_REST_RUNS ?= 3" in makefile
    assert "LOW_LATENCY_SWEEP_CHUNK_MS ?= 80 100 200 250" in makefile
    assert "LOW_LATENCY_SWEEP_PARTIAL_WINDOWS ?= 1.0 2.0" in makefile
    assert "LOW_LATENCY_SWEEP_BINARY_FRAMES ?= false" in makefile
    assert "set -e;" in sweep_block
    assert "--sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT)" in sweep_block
    assert "--rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS)" in sweep_block
    assert "--chunk-ms $$chunk" in sweep_block
    assert "--partial-window $$window" in sweep_block
    assert "$$frame_flag" in sweep_block


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


def test_makefile_mlx_venv_target_repairs_broken_virtualenvs_before_benchmarks() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    mlx_venv_block = makefile.split("mlx-venv:\n", 1)[1].split("\n\n", 1)[0]
    assert 'if [ -x $(MLX_PYTHON) ] && $(MLX_PYTHON) -c "import sys" >/dev/null 2>&1; then \\' in mlx_venv_block
    assert 'echo "  Rebuilding $(MLX_VENV) because the interpreter is missing or broken..."; \\' in mlx_venv_block
    assert "rm -rf $(MLX_VENV); \\" in mlx_venv_block
    assert "python3 -m venv $(MLX_VENV); \\" in mlx_venv_block
    assert "$(MLX_PYTHON) -m pip install --upgrade pip mlx-lm psutil; \\" in mlx_venv_block
    assert '@echo "  ✓ MLX virtualenv ready at $(MLX_VENV)"' in mlx_venv_block

def test_makefile_exposes_benchmark_site_sync_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "benchmark-site:" in makefile
    assert "benchmark-site-check:" in makefile
    assert ".PHONY: help venv mlx-venv setup build run dev test benchmark benchmark-faster-whisper-matrix benchmark-faster-whisper-base benchmark-faster-whisper-small benchmark-faster-whisper-base-low-latency-sweep benchmark-faster-whisper-small-low-latency-sweep benchmark-qwen-mps benchmark-qwen-mps-low-latency-sweep benchmark-compose-matrix benchmark-compose-qwen benchmark-compose-qwen-low-latency-sweep benchmark-compose-parakeet benchmark-compose-parakeet-low-latency-sweep benchmark-compose-parakeet-nemo benchmark-compose-parakeet-nemo-low-latency-sweep benchmark-all-asr-low-latency-sweep benchmark-qwen-mlx-text benchmark-pipecat-e2e benchmark-site benchmark-site-check clean lint docs start stop status" in makefile
    assert 'make benchmark-site-check - Fail when docs/benchmark-results/manifest.json is stale' in makefile
    block = makefile.split("benchmark-site-check:\n", 1)[1].split("\n\n", 1)[0]
    assert "scripts/build_benchmark_manifest.py --results-dir $(BENCHMARK_RESULTS_DIR) --output $(BENCHMARK_RESULTS_DIR)/manifest.json --check" in block
    assert "scripts/prerender_benchmark_homepage.py --manifest $(BENCHMARK_RESULTS_DIR)/manifest.json --homepage docs/index.html --check" in block
    assert '@echo "  ✓ Benchmark site manifest is up to date"' in block


def test_makefile_qwen_mps_target_forces_runtime_env() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "benchmark-qwen-mps: venv" in makefile
    assert "qwen-mps-" in makefile
    line = next(
        line
        for line in makefile.splitlines()
        if "qwen-mps-$(BENCHMARK_RESULT_DATE).json" in line
    )
    assert "ASR_BACKEND=qwen-asr ASR_DEVICE=mps" in line
    assert "ASR_QWEN_DEVICE_MAP=" in line
    assert "ASR_QWEN_MODEL=$(QWEN_MPS_MODEL)" in line
    assert "ASR_QWEN_DTYPE=$(QWEN_MPS_DTYPE)" in line
    assert "--backend qwen-asr" in line
    assert "--device mps" in line


def test_makefile_compose_benchmark_targets_use_shared_ten_sample_count() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "BENCHMARK_SAMPLE_COUNT ?= 10" in makefile
    assert "BENCHMARK_REQUEST_RETRIES ?= 3" in makefile
    assert "benchmark-compose-matrix: benchmark-compose-qwen benchmark-compose-parakeet benchmark-compose-parakeet-nemo" in makefile
    assert "PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 8" in makefile
    assert "QWEN_MLX_TEXT_MODEL ?= Qwen/Qwen3-0.6B-MLX-4bit" in makefile
    assert "MLX_VENV ?= .venv-mlx" in makefile
    assert "benchmark-qwen-mlx-text: mlx-venv" in makefile
    assert "benchmark-pipecat-e2e: venv" in makefile
    assert "$(MLX_PYTHON) -m pip install --upgrade pip mlx-lm psutil" in makefile
    assert "scripts/benchmark_mlx_text.py --model $(QWEN_MLX_TEXT_MODEL)" in makefile
    for target_name, target in (("benchmark-compose-qwen: venv", "qwen"), ("benchmark-compose-parakeet: venv", "parakeet"), ("benchmark-compose-parakeet-nemo: venv", "parakeet-nemo-110m")):
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

    for target, backend in (("benchmark-compose-qwen", "qwen-asr"), ("benchmark-compose-parakeet", "parakeet"), ("benchmark-compose-parakeet-nemo", "parakeet-nemo")):
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
        "qwen-mps-2026-06-10.json": {
            "partial_interval_chunks": 1,
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


def test_run_ws_benchmark_reports_first_partial_and_gap_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "chunk one"},
            {"type": "partial", "text": "chunk two"},
            {"type": "final", "text": "done"},
        ]
    )

    perf_values = iter([1.0, 1.0, 1.0, 1.05, 2.0, 2.0, 2.0, 2.0, 2.08, 3.0, 3.1])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"abcdefgh",
            8,
            250,
            partial_interval_chunks=1,
            connect_fn=fake_connect,
        )

        assert result["partial_audio_offsets_ms"] == [250, 500]
        assert result["partial_end_to_end_ms"] == [300.0, 580.0]
        assert result["first_partial_audio_ms"] == 250
        assert result["first_partial_end_to_end_ms"] == 300.0
        assert result["partial_gap_ms"] == [280.0]
        assert result["partial_gap_mean_ms"] == 280.0
        assert result["partial_gap_p95_ms"] == 280.0
        assert result["time_to_final_from_audio_end_ms"] == 1100.0

    asyncio.run(scenario())


def test_run_ws_benchmark_keeps_partial_end_to_end_monotonic_under_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "chunk one"},
            {"type": "partial", "text": "chunk two"},
            {"type": "final", "text": "done"},
        ]
    )

    perf_values = iter([1.0, 1.0, 1.0, 3.5, 4.0, 4.0, 4.0, 4.0, 4.02, 5.0, 5.1])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"abcdefgh",
            8,
            250,
            partial_interval_chunks=1,
            connect_fn=fake_connect,
        )

        assert result["partial_audio_offsets_ms"] == [250, 500]
        assert result["partial_end_to_end_ms"] == [2750.0, 2770.0]
        assert result["partial_gap_ms"] == [20.0]
        assert result["first_partial_end_to_end_ms"] == 2750.0

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


def test_run_ws_benchmark_tolerates_missing_partial_for_eligible_chunk() -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "final", "text": "done"},
        ]
    )

    async def fake_wait_for(awaitable, timeout: float):
        awaitable.close()
        raise TimeoutError

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"ab",
            4,
            250,
            partial_event_timeout_seconds=0.01,
            connect_fn=fake_connect,
        )

        assert result["partial_mean_ms"] is None
        assert result["final_transcript"] == "done"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(benchmark.asyncio, "wait_for", fake_wait_for)
        asyncio.run(scenario())


def test_run_ws_benchmark_counts_late_partial_against_original_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "stale", "chunks_received": 1},
            {"type": "partial", "text": "fresh", "chunks_received": 2},
            {"type": "final", "text": "done"},
        ]
    )

    call_count = 0

    async def fake_wait_for(awaitable, timeout: float):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            awaitable.close()
            raise TimeoutError
        return await awaitable

    perf_values = iter([1.0, 1.0, 1.0, 2.0, 2.0, 2.0, 2.0, 2.15, 2.15, 2.24, 3.0, 3.1])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"abcd",
            4,
            250,
            partial_interval_chunks=1,
            partial_event_timeout_seconds=0.5,
            connect_fn=fake_connect,
        )

        assert result["partial_audio_offsets_ms"] == [250, 500]
        assert result["partial_end_to_end_ms"] == [1400.0, 1640.0]
        assert result["first_partial_audio_ms"] == 250
        assert result["first_partial_end_to_end_ms"] == 1400.0
        assert result["last_partial"] == "fresh"
        assert result["final_transcript"] == "done"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(benchmark.asyncio, "wait_for", fake_wait_for)
        asyncio.run(scenario())

def test_run_ws_benchmark_records_late_partial_before_final(monkeypatch: pytest.MonkeyPatch) -> None:
    websocket = FakeBenchmarkWebSocket(
        [
            {"type": "ready", "stream_id": 11},
            {"type": "partial", "text": "chunk", "chunks_received": 1},
            {"type": "partial", "text": "still partial", "chunks_received": 1},
            {"type": "final", "text": "done"},
        ]
    )

    perf_values = iter([1.0, 1.0, 1.0, 1.0, 1.05, 2.0, 2.1, 2.12])
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    def fake_connect(_: str) -> FakeBenchmarkWebSocket:
        return websocket

    async def scenario() -> None:
        result = await benchmark.run_ws_benchmark(
            "ws://example.test/ws/stream",
            b"ab",
            4,
            250,
            partial_event_timeout_seconds=0.01,
            connect_fn=fake_connect,
        )

        assert result["partial_audio_offsets_ms"] == [250]
        assert result["partial_end_to_end_ms"] == [300.0]
        assert result["last_partial"] == "chunk"
        assert result["final_transcript"] == "done"

    asyncio.run(scenario())


def test_run_pipecat_e2e_benchmark_aggregates_source_frames_and_reports_end_to_end_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_chunks: list[bytes] = []

    class FakeEvent:
        def __init__(self, event_type: str, text: str) -> None:
            self.type = event_type
            self.text = text

    class FakePipecatClient:
        def __init__(self, ws_url: str, connect_fn=None) -> None:
            self.ws_url = ws_url
            self.connect_fn = connect_fn

        async def start(self, **kwargs: object) -> dict[str, object]:
            assert kwargs["sample_rate"] == 10
            assert kwargs["partial_interval_chunks"] == 1
            assert kwargs["partial_window_seconds"] == 1.5
            return {"type": "ready", "stream_id": 9, **kwargs}

        async def send_audio(self, chunk: bytes, *, response_timeout: float = 0.1):
            assert response_timeout == 0.5
            sent_chunks.append(chunk)
            if len(sent_chunks) == 1:
                return None
            if len(sent_chunks) == 2:
                return FakeEvent("partial", "first")
            return FakeEvent("partial", "second")

        async def stop(self) -> FakeEvent:
            return FakeEvent("final", "done")

        async def close(self) -> None:
            return None

    perf_values = iter([1.0, 2.0, 2.03, 3.0, 3.0, 3.02, 4.0, 4.2])
    monkeypatch.setattr(benchmark, "AsyncASRClient", FakePipecatClient)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    async def scenario() -> None:
        result = await benchmark.run_pipecat_e2e_benchmark(
            "ws://example.test/ws/stream",
            b"abcdefghijkl",
            10,
            200,
            source_frame_ms=100,
            partial_interval_chunks=1,
            partial_window_seconds=1.5,
            partial_event_timeout_seconds=0.5,
        )

        assert sent_chunks == [b"abcd", b"efgh", b"ijkl"]
        assert result["transport"] == "pipecat-e2e"
        assert result["chunks"] == 3
        assert result["source_frame_count"] == 6
        assert result["aggregation_frame_count"] == 2
        assert result["partial_audio_offsets_ms"] == [400.0, 600.0]
        assert result["partial_end_to_end_ms"] == [430.0, 620.0]
        assert result["partial_gap_ms"] == [190.0]
        assert result["expected_partial_events"] == 3
        assert result["observed_partial_events"] == 2
        assert result["missing_partial_events"] == 1
        assert result["final_transcript"] == "done"
        assert result["final_event_received"] is True

    asyncio.run(scenario())


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

