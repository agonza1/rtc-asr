from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import httpx
import numpy as np
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
summarize_partial_churn = benchmark.summarize_partial_churn


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


def test_summarize_partial_churn_reports_revision_and_ratio_metrics() -> None:
    summary = summarize_partial_churn(["hello world", "hello brave world", "yellow brave world"])

    assert summary["partial_revision_count"] == 2
    assert summary["partial_transcript_churn_char_mean"] > 0
    assert summary["partial_transcript_churn_char_p95"] >= summary["partial_transcript_churn_char_mean"]
    assert summary["partial_transcript_churn_word_mean"] > 0
    assert summary["partial_transcript_churn_word_p95"] >= summary["partial_transcript_churn_word_mean"]


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
    assert "LOW_LATENCY_SWEEP_CHUNK_MS ?= 80 100 160 200" in makefile
    assert "LOW_LATENCY_SWEEP_PARTIAL_WINDOWS ?= 0.75 1.0 1.5 2.0" in makefile
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
    assert 'if [ -x $(MLX_PYTHON) ] && $(MLX_PYTHON) -c "import fastapi, httpx, numpy, parakeet_mlx, soundfile, uvicorn, websockets" >/dev/null 2>&1; then \\' in mlx_venv_block
    assert 'echo "  Rebuilding $(MLX_VENV) because the MLX benchmark runtime is missing or broken..."; \\' in mlx_venv_block
    assert "rm -rf $(MLX_VENV); \\" in mlx_venv_block
    assert "python3 -m venv $(MLX_VENV); \\" in mlx_venv_block
    assert '$(MLX_PYTHON) -m pip install --upgrade pip fastapi "uvicorn[standard]" pydantic python-multipart websockets numpy soundfile httpx parakeet-mlx psutil; \\' in mlx_venv_block
    assert '@echo "  ✓ MLX virtualenv ready at $(MLX_VENV)"' in mlx_venv_block

def test_makefile_exposes_benchmark_site_sync_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "benchmark-site:" in makefile
    assert "benchmark-site-check:" in makefile
    assert ".PHONY: help venv mlx-venv setup build run dev test benchmark benchmark-faster-whisper-matrix benchmark-faster-whisper-base benchmark-faster-whisper-small benchmark-faster-whisper-base-low-latency-sweep benchmark-faster-whisper-small-low-latency-sweep benchmark-qwen-mps benchmark-qwen-mps-low-latency-sweep benchmark-compose-matrix benchmark-compose-qwen benchmark-compose-qwen-low-latency-sweep benchmark-compose-parakeet benchmark-compose-parakeet-low-latency-sweep benchmark-compose-parakeet-nemo benchmark-compose-parakeet-nemo-low-latency-sweep benchmark-all-asr-low-latency-sweep benchmark-parakeet-mlx benchmark-parakeet-mlx-110m benchmark-parakeet-mlx-service benchmark-parakeet-mlx-service-110m benchmark-pipecat-e2e benchmark-site benchmark-site-check clean lint docs start stop status" in makefile
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
    assert "PARAKEET_MLX_MODEL ?= mlx-community/parakeet-tdt-0.6b-v3" in makefile
    assert "PARAKEET_MLX_ARTIFACT_SLUG ?= parakeet-mlx" in makefile
    assert "PARAKEET_MLX_SERVICE_ARTIFACT_SLUG ?= parakeet-mlx-service" in makefile
    assert "MLX_VENV ?= .venv-mlx" in makefile
    assert "benchmark-parakeet-mlx: mlx-venv" in makefile
    assert "benchmark-parakeet-mlx-110m:" in makefile
    assert "benchmark-parakeet-mlx-service: mlx-venv" in makefile
    assert "benchmark-parakeet-mlx-service-110m:" in makefile
    assert "benchmark-pipecat-e2e: venv" in makefile
    assert "$(BENCHMARK_RESULTS_DIR)/$(BENCHMARK_PIPECAT_BACKEND)-$(BENCHMARK_PIPECAT_MODEL)-$(BENCHMARK_PIPECAT_COMPUTE_TYPE)-pipecat-e2e-$(BENCHMARK_RESULT_DATE).json" in makefile
    assert '$(MLX_PYTHON) -m pip install --upgrade pip fastapi "uvicorn[standard]" pydantic python-multipart websockets numpy soundfile httpx parakeet-mlx psutil' in makefile
    assert "scripts/benchmark_mlx_asr.py --model $(PARAKEET_MLX_MODEL)" in makefile
    assert "$(BENCHMARK_RESULTS_DIR)/$(PARAKEET_MLX_ARTIFACT_SLUG)-$(BENCHMARK_RESULT_DATE).json" in makefile
    assert "PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt_ctc-110m PARAKEET_MLX_ARTIFACT_SLUG=parakeet-mlx-110m" in makefile
    mlx_service_block = makefile.split("benchmark-parakeet-mlx-service: mlx-venv\n", 1)[1].split("\n\n", 1)[0]
    assert "trap cleanup EXIT INT TERM" in mlx_service_block
    assert "PYTHONPATH=. ASR_BACKEND=parakeet-mlx ASR_DEVICE=apple-silicon ASR_PRELOAD_MODEL=true ASR_PARAKEET_MODEL=$(PARAKEET_MLX_MODEL) ASR_PARAKEET_DTYPE=auto $(MLX_PYTHON) -m uvicorn src.main:app --host 127.0.0.1 --port 8090 --log-level warning" in mlx_service_block
    assert "curl -sf http://127.0.0.1:8090/ready >/dev/null" in mlx_service_block
    assert "PYTHONPATH=. $(MLX_PYTHON) tests/benchmark.py --url http://127.0.0.1:8090 --ws-url ws://127.0.0.1:8090/ws/stream --backend parakeet-mlx" in mlx_service_block
    assert "PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt_ctc-110m PARAKEET_MLX_SERVICE_ARTIFACT_SLUG=parakeet-mlx-110m-service" in makefile
    assert makefile.count("ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE=\"$${base_image}\" docker compose up -d --build; \\") == 6
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
        assert result["late_partial_events"] == 1
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
        assert result["partial_revision_count"] == 1
        assert result["last_partial"] == "still partial"
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


def test_run_pipecat_e2e_benchmark_counts_stale_send_audio_partial(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_chunks: list[bytes] = []

    class FakeEvent:
        def __init__(self, event_type: str, text: str, *, chunks_received: int = 0) -> None:
            self.type = event_type
            self.text = text
            self.chunks_received = chunks_received

    class FakePipecatClient:
        def __init__(self, ws_url: str, connect_fn=None) -> None:
            self.ws_url = ws_url
            self.connect_fn = connect_fn

        async def start(self, **kwargs: object) -> dict[str, object]:
            return {"type": "ready", "stream_id": 9, **kwargs}

        async def send_audio(self, chunk: bytes, *, response_timeout: float = 0.1):
            assert response_timeout == 0.5
            sent_chunks.append(chunk)
            if len(sent_chunks) == 1:
                return None
            if len(sent_chunks) == 2:
                return FakeEvent("partial", "stale", chunks_received=1)
            return None

        async def _recv_json_with_timeout(self, timeout: float):
            assert timeout >= 0
            return None

        async def stop(self) -> FakeEvent:
            return FakeEvent("final", "done", chunks_received=2)

        async def close(self) -> None:
            return None

    perf_values = iter([1.0, 1.05, 1.55, 2.0, 2.1, 2.2, 3.0, 3.02, 3.52, 4.0, 4.2])
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
            partial_event_timeout_seconds=0.5,
        )

        assert sent_chunks == [b"abcd", b"efgh", b"ijkl"]
        assert result["observed_partial_events"] == 1
        assert result["missing_partial_events"] == 2
        assert result["late_partial_events"] == 1
        assert result["late_partial_ratio"] == 1.0
        assert result["partial_audio_offsets_ms"] == [200.0]
        assert result["last_partial"] == "stale"
        assert result["final_transcript"] == "done"

    asyncio.run(scenario())


def test_run_pipecat_e2e_benchmark_records_late_partial_before_final(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_chunks: list[bytes] = []

    class FakeEvent:
        def __init__(self, event_type: str, text: str, *, chunks_received: int = 0) -> None:
            self.type = event_type
            self.text = text
            self.chunks_received = chunks_received

    class FakeWebSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.responses = [
                {"type": "partial", "text": "late", "chunks_received": 2},
                {"type": "final", "text": "done", "chunks_received": 2},
            ]

        async def send(self, data: str | bytes) -> None:
            if isinstance(data, str):
                self.sent.append(json.loads(data))

        async def recv(self) -> str:
            if not self.responses:
                raise RuntimeError("No benchmark websocket responses left")
            return json.dumps(self.responses.pop(0))

        async def close(self, code: int = 1000) -> None:
            return None

    class FakePipecatClient:
        def __init__(self, ws_url: str, connect_fn=None) -> None:
            self.ws_url = ws_url
            self.connect_fn = connect_fn
            self._websocket = FakeWebSocket()
            self._chunks_sent = 0
            self._send_binary_frames = False

        async def start(self, **kwargs: object) -> dict[str, object]:
            return {"type": "ready", "stream_id": 9, **kwargs}

        async def send_audio(self, chunk: bytes, *, response_timeout: float = 0.1):
            assert response_timeout == 0.5
            sent_chunks.append(chunk)
            if len(sent_chunks) == 1:
                return FakeEvent("partial", "first", chunks_received=1)
            return None

        async def _recv_json_with_timeout(self, timeout: float):
            assert timeout >= 0
            return None

        def _require_websocket(self):
            return self._websocket

        async def _recv_json(self, allow_error: bool = False):
            return json.loads(await self._websocket.recv())

        async def close(self) -> None:
            return None

    perf_values = iter([1.0, 1.02, 2.0, 2.01, 2.02, 2.03, 2.1, 2.15, 3.0])
    monkeypatch.setattr(benchmark, "AsyncASRClient", FakePipecatClient)
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(perf_values))

    async def scenario() -> None:
        result = await benchmark.run_pipecat_e2e_benchmark(
            "ws://example.test/ws/stream",
            b"abcdefgh",
            8,
            250,
            source_frame_ms=125,
            partial_interval_chunks=1,
            partial_event_timeout_seconds=0.5,
        )

        assert sent_chunks == [b"abcd", b"efgh"]
        assert result["observed_partial_events"] == 2
        assert result["missing_partial_events"] == 0
        assert result["late_partial_events"] == 0
        assert result["partial_audio_offsets_ms"] == [250.0, 500.0]
        assert result["partial_end_to_end_ms"] == [270.0, 650.0]
        assert result["last_partial"] == "late"
        assert result["final_transcript"] == "done"

    asyncio.run(scenario())


def test_resolve_service_model_prefers_scalar_identifier_fields() -> None:
    assert benchmark.resolve_service_model({"model": "top-level-model"}, "fallback-model") == "top-level-model"
    assert benchmark.resolve_service_model({"models": ["list-model"]}, "fallback-model") == "list-model"
    assert benchmark.resolve_service_model({"models": [{"id": "model-id", "model": "nested-model"}]}, "fallback-model") == "model-id"
    assert benchmark.resolve_service_model({"models": [{"model": "nested-model"}]}, "fallback-model") == "nested-model"
    assert benchmark.resolve_service_model({"models": [{}]}, "fallback-model") == "fallback-model"
    assert benchmark.resolve_service_model(None, "fallback-model") == "fallback-model"


def test_async_main_summarizes_final_metric_from_audio_end_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_service_metadata(_: str) -> dict[str, object]:
        return {
            "backend": "demo",
            "models": ["demo-v1"],
            "capabilities": {"device": "cpu", "compute_type": "int8"},
        }

    async def fake_run_rest_benchmark(*args, **kwargs) -> dict[str, object]:
        return {
            "durations_ms": [40.0],
            "mean_ms": 40.0,
            "p90_ms": 40.0,
            "p95_ms": 40.0,
            "min_ms": 40.0,
            "max_ms": 40.0,
            "rtf_mean": 0.1,
            "transcript": "done",
        }

    samples = iter([
        {
            "binary_frames": False,
            "partial_latencies_ms": [20.0],
            "partial_audio_offsets_ms": [250.0],
            "partial_end_to_end_ms": [350.0],
            "partial_gap_ms": [],
            "partial_mean_ms": 20.0,
            "partial_p90_ms": 20.0,
            "partial_p95_ms": 20.0,
            "partial_first_ms": 20.0,
            "partial_last_ms": 20.0,
            "first_partial_audio_ms": 250.0,
            "first_partial_end_to_end_ms": 350.0,
            "partial_gap_mean_ms": None,
            "partial_gap_p95_ms": None,
            "final_ms": 200.0,
            "time_to_final_from_audio_end_ms": 1100.0,
            "ready": {"type": "ready"},
            "last_partial": "p1",
            "final_transcript": "done",
            "expected_partial_events": 1,
            "observed_partial_events": 1,
            "missing_partial_events": 0,
            "late_partial_events": 0,
            "late_partial_ratio": 0.0,
            "partial_revision_count": 0,
            "partial_transcript_churn_char_mean": None,
            "partial_transcript_churn_char_p95": None,
            "partial_transcript_churn_word_mean": None,
            "partial_transcript_churn_word_p95": None,
            "bridge": None,
            "final_event_received": True,
            "closeout_event_type": "final",
            "transport": "direct",
            "source_frame_ms": None,
            "source_frame_count": None,
            "aggregation_frame_count": None,
        },
        {
            "binary_frames": False,
            "partial_latencies_ms": [30.0],
            "partial_audio_offsets_ms": [250.0],
            "partial_end_to_end_ms": [360.0],
            "partial_gap_ms": [],
            "partial_mean_ms": 30.0,
            "partial_p90_ms": 30.0,
            "partial_p95_ms": 30.0,
            "partial_first_ms": 30.0,
            "partial_last_ms": 30.0,
            "first_partial_audio_ms": 250.0,
            "first_partial_end_to_end_ms": 360.0,
            "partial_gap_mean_ms": None,
            "partial_gap_p95_ms": None,
            "final_ms": 300.0,
            "time_to_final_from_audio_end_ms": 1500.0,
            "ready": {"type": "ready"},
            "last_partial": "p2",
            "final_transcript": "done",
            "expected_partial_events": 1,
            "observed_partial_events": 1,
            "missing_partial_events": 0,
            "late_partial_events": 0,
            "late_partial_ratio": 0.0,
            "partial_revision_count": 0,
            "partial_transcript_churn_char_mean": None,
            "partial_transcript_churn_char_p95": None,
            "partial_transcript_churn_word_mean": None,
            "partial_transcript_churn_word_p95": None,
            "bridge": None,
            "final_event_received": True,
            "closeout_event_type": "final",
            "transport": "direct",
            "source_frame_ms": None,
            "source_frame_count": None,
            "aggregation_frame_count": None,
        },
    ])

    async def fake_run_ws_benchmark(*args, **kwargs) -> dict[str, object]:
        return next(samples)

    monkeypatch.setattr(benchmark, "benchmark_audio_path", lambda args: benchmark.FIXTURE_PATH)
    monkeypatch.setattr(benchmark, "resolve_reference_text", lambda args, synthesized=False: None)
    monkeypatch.setattr(benchmark, "load_audio", lambda path: (np.zeros(8, dtype=np.float32), 4))
    monkeypatch.setattr(benchmark, "make_wav_bytes", lambda samples, sample_rate: b"wav")
    monkeypatch.setattr(benchmark, "fetch_service_metadata", fake_fetch_service_metadata)
    monkeypatch.setattr(benchmark, "run_rest_benchmark", fake_run_rest_benchmark)
    monkeypatch.setattr(benchmark, "run_ws_benchmark", fake_run_ws_benchmark)

    args = argparse.Namespace(
        audio_file=None,
        speech_text=benchmark.DEFAULT_TEXT,
        reference_text=None,
        reference_file=None,
        spawn_server=False,
        backend="demo",
        model="demo-v1",
        sample_count=2,
        rest_runs=1,
        chunk_ms=250,
        partial_interval_chunks=1,
        partial_window=2.0,
        max_buffer=None,
        binary_frames=False,
        output=None,
        device="cpu",
        compute_type="int8",
        qwen_dtype=None,
        parakeet_dtype=None,
        mode="direct",
        url="http://127.0.0.1:8090",
        ws_url="ws://127.0.0.1:8090/ws/stream",
        pipecat_source_frame_ms=20,
        partial_event_timeout=0.1,
        request_retries=1,
        request_retry_delay=0.0,
    )

    result = asyncio.run(benchmark.async_main(args))

    assert result["streaming"]["final_latencies_ms"] == [1100.0, 1500.0]
    assert result["streaming"]["stop_to_final_latencies_ms"] == [200.0, 300.0]
    assert result["streaming"]["time_to_final_from_audio_end_mean_ms"] == 1300.0
    assert result["streaming"]["final_mean_ms"] == 1300.0
    assert result["streaming"]["final_p95_ms"] == 1500.0


def test_async_main_uses_service_model_id_and_parakeet_mlx_dtype(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_service_metadata(_: str) -> dict[str, object]:
        return {
            "backend": "parakeet-mlx",
            "model": "mlx-community/parakeet-tdt_ctc-110m",
            "models": [
                {
                    "id": "mlx-community/parakeet-tdt_ctc-110m",
                    "model": "mlx-community/parakeet-tdt_ctc-110m",
                    "capabilities": {"dtype": "auto"},
                }
            ],
            "capabilities": {"device": "apple-silicon", "dtype": "auto"},
        }

    async def fake_run_rest_benchmark(*args, **kwargs) -> dict[str, object]:
        return {
            "durations_ms": [40.0],
            "mean_ms": 40.0,
            "p90_ms": 40.0,
            "p95_ms": 40.0,
            "min_ms": 40.0,
            "max_ms": 40.0,
            "rtf_mean": 0.1,
            "transcript": "done",
        }

    async def fake_run_ws_benchmark(*args, **kwargs) -> dict[str, object]:
        return {
            "binary_frames": False,
            "partial_latencies_ms": [20.0],
            "partial_audio_offsets_ms": [250.0],
            "partial_end_to_end_ms": [350.0],
            "partial_gap_ms": [],
            "partial_mean_ms": 20.0,
            "partial_p90_ms": 20.0,
            "partial_p95_ms": 20.0,
            "partial_first_ms": 20.0,
            "partial_last_ms": 20.0,
            "first_partial_audio_ms": 250.0,
            "first_partial_end_to_end_ms": 350.0,
            "partial_gap_mean_ms": None,
            "partial_gap_p95_ms": None,
            "final_ms": 200.0,
            "time_to_final_from_audio_end_ms": 300.0,
            "ready": {"type": "ready"},
            "last_partial": "p1",
            "final_transcript": "done",
            "expected_partial_events": 1,
            "observed_partial_events": 1,
            "missing_partial_events": 0,
            "late_partial_events": 0,
            "late_partial_ratio": 0.0,
            "partial_revision_count": 0,
            "partial_transcript_churn_char_mean": None,
            "partial_transcript_churn_char_p95": None,
            "partial_transcript_churn_word_mean": None,
            "partial_transcript_churn_word_p95": None,
            "bridge": None,
            "final_event_received": True,
            "closeout_event_type": "final",
            "transport": "direct",
            "source_frame_ms": None,
            "source_frame_count": None,
            "aggregation_frame_count": None,
        }

    monkeypatch.setattr(benchmark, "benchmark_audio_path", lambda args: benchmark.FIXTURE_PATH)
    monkeypatch.setattr(benchmark, "resolve_reference_text", lambda args, synthesized=False: None)
    monkeypatch.setattr(benchmark, "load_audio", lambda path: (np.zeros(8, dtype=np.float32), 4))
    monkeypatch.setattr(benchmark, "make_wav_bytes", lambda samples, sample_rate: b"wav")
    monkeypatch.setattr(benchmark, "fetch_service_metadata", fake_fetch_service_metadata)
    monkeypatch.setattr(benchmark, "run_rest_benchmark", fake_run_rest_benchmark)
    monkeypatch.setattr(benchmark, "run_ws_benchmark", fake_run_ws_benchmark)

    args = argparse.Namespace(
        audio_file=None,
        speech_text=benchmark.DEFAULT_TEXT,
        reference_text=None,
        reference_file=None,
        spawn_server=False,
        backend="parakeet-mlx",
        model="fallback-model",
        sample_count=1,
        rest_runs=1,
        chunk_ms=250,
        partial_interval_chunks=1,
        partial_window=2.0,
        max_buffer=None,
        binary_frames=False,
        output=None,
        device="cpu",
        compute_type="int8",
        qwen_dtype=None,
        parakeet_dtype="float32",
        mode="direct",
        url="http://127.0.0.1:8090",
        ws_url="ws://127.0.0.1:8090/ws/stream",
        pipecat_source_frame_ms=20,
        partial_event_timeout=0.1,
        request_retries=1,
        request_retry_delay=0.0,
    )

    result = asyncio.run(benchmark.async_main(args))

    assert result["backend"]["model"] == "mlx-community/parakeet-tdt_ctc-110m"
    assert result["backend"]["parakeet_dtype"] == "auto"
    assert result["backend"]["compute_type"] is None


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

