# Realtime ASR Service - Makefile
# Convenience commands for development and deployment

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
MLX_VENV ?= .venv-mlx
MLX_PYTHON := $(MLX_VENV)/bin/python
UVICORN := $(VENV)/bin/uvicorn
COMPOSE_URL ?= http://127.0.0.1:8080
COMPOSE_WS_URL ?= ws://127.0.0.1:8080/ws/stream
QWEN_COMPOSE_MODEL ?= Qwen/Qwen3-ASR-0.6B
QWEN_COMPOSE_DTYPE ?= float32
QWEN_COMPOSE_MAX_NEW_TOKENS ?= 64
QWEN_MPS_MODEL ?= Qwen/Qwen3-ASR-0.6B
QWEN_MPS_DTYPE ?= auto
DEFAULT_PYTHON_BASE_IMAGE := python:3.11-slim
PYTHON_BASE_IMAGE ?= $(DEFAULT_PYTHON_BASE_IMAGE)
PYTHON_BASE_IMAGE_FALLBACK ?= mirror.gcr.io/library/python:3.11-slim
PARAKEET_COMPOSE_MODEL ?= nvidia/parakeet-tdt-0.6b-v3
PARAKEET_NEMO_COMPOSE_MODEL ?= nvidia/parakeet-tdt_ctc-110m
PARAKEET_COMPOSE_DTYPE ?= float32
ULTRAVOX_COMPOSE_MODEL ?= fixie-ai/ultravox-v0_6-llama-3_1-8b
ULTRAVOX_COMPOSE_DTYPE ?= float32
ULTRAVOX_MAX_NEW_TOKENS ?= 128
QWEN_MLX_TEXT_MODEL ?= Qwen/Qwen3-0.6B-MLX-4bit
QWEN_MLX_TEXT_MAX_TOKENS ?= 64
QWEN_MLX_TEXT_SAMPLE_COUNT ?= 3
BENCHMARK_RESULTS_DIR ?= docs/benchmark-results
BENCHMARK_RESULT_DATE ?= $(shell date -u +%Y-%m-%d)
BENCHMARK_SAMPLE_COUNT ?= 10
BENCHMARK_CHUNK_MS ?= 250
BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 1
PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 8
BENCHMARK_PARTIAL_WINDOW ?= 2.0
BENCHMARK_BINARY_FRAMES ?=
BENCHMARK_REQUEST_RETRIES ?= 3
BENCHMARK_REQUEST_RETRY_DELAY ?= 2.0
FASTER_WHISPER_BASE_MODEL ?= base.en
FASTER_WHISPER_SMALL_MODEL ?= small.en
FASTER_WHISPER_COMPUTE_TYPE ?= int8

.PHONY: help venv mlx-venv setup build run dev test benchmark benchmark-faster-whisper-matrix benchmark-faster-whisper-base benchmark-faster-whisper-small benchmark-qwen-mps benchmark-compose-matrix benchmark-compose-qwen benchmark-compose-parakeet benchmark-compose-parakeet-nemo benchmark-compose-ultravox benchmark-qwen-mlx-text benchmark-site benchmark-site-check clean lint docs start stop status
.NOTPARALLEL: benchmark-faster-whisper-matrix benchmark-compose-matrix

help:
	@echo "Realtime ASR Service - Available commands:"
	@echo ""
	@echo "  make venv           - Create or refresh the local virtualenv"
	@echo "  make setup          - Bootstrap .env and the local virtualenv"
	@echo "  make build          - Build Docker image"
	@echo "  make run            - Run service locally"
	@echo "  make dev            - Run service locally with reload"
	@echo "  make test           - Run the automated test suite"
	@echo "  make benchmark      - Run the default faster-whisper small.en latency benchmark"
	@echo "  make benchmark-faster-whisper-matrix - Run base.en and small.en local benchmarks with $(BENCHMARK_SAMPLE_COUNT) samples each"
	@echo "  make benchmark-faster-whisper-base - Run faster-whisper base.en with $(BENCHMARK_SAMPLE_COUNT) samples"
	@echo "  make benchmark-faster-whisper-small - Run faster-whisper small.en with $(BENCHMARK_SAMPLE_COUNT) samples"
	@echo "  make benchmark-qwen-mps - Run qwen-asr locally on Apple Silicon MPS"
	@echo "  make benchmark-compose-matrix - Run all Compose model benchmarks with $(BENCHMARK_SAMPLE_COUNT) samples each"
	@echo "  make benchmark-compose-qwen - Start compose, wait for readiness, and benchmark qwen-asr"
	@echo "  make benchmark-compose-parakeet - Start compose, wait for readiness, and benchmark parakeet"
	@echo "  make benchmark-compose-parakeet-nemo - Start compose and benchmark Parakeet 110M through NeMo"
	@echo "  make benchmark-compose-ultravox - Start compose, wait for readiness, and benchmark ultravox"
	@echo "  make lint           - Run linter"
	@echo "  make benchmark-site-check - Fail when docs/benchmark-results/manifest.json is stale"
	@echo "  make docs           - Build documentation snapshot"
	@echo "  make start          - Start docker compose stack"
	@echo "  make stop           - Stop docker compose stack"
	@echo "  make status         - Check service status"

venv:
	@echo "Preparing virtualenv..."
	@if [ -x $(PYTHON) ] && $(PYTHON) -c "import sys" >/dev/null 2>&1; then \
		echo "  ✓ Reusing existing virtualenv at $(VENV)"; \
	else \
		echo "  Rebuilding $(VENV) because the interpreter is missing or broken..."; \
		rm -rf $(VENV); \
		python3 -m venv $(VENV); \
		$(PIP) install --upgrade pip; \
		$(PIP) install -r requirements.txt; \
	fi
	@echo "  ✓ Virtualenv ready at $(VENV)"

mlx-venv:
	@echo "Preparing MLX virtualenv..."
	@if [ -x $(MLX_PYTHON) ] && $(MLX_PYTHON) -c "import sys" >/dev/null 2>&1; then \
		echo "  ✓ Reusing existing MLX virtualenv at $(MLX_VENV)"; \
	else \
		echo "  Rebuilding $(MLX_VENV) because the interpreter is missing or broken..."; \
		rm -rf $(MLX_VENV); \
		python3 -m venv $(MLX_VENV); \
		$(MLX_PYTHON) -m pip install --upgrade pip mlx-lm psutil; \
	fi
	@echo "  ✓ MLX virtualenv ready at $(MLX_VENV)"

setup: venv
	@echo "Bootstrapping local config..."
	@test -f .env || cp config.example .env
	@mkdir -p models
	@echo "  ✓ Local config ready (.env)"

build:
	@echo "Building Docker image..."
	@base_image="$(PYTHON_BASE_IMAGE)"; \
	if [ "$${base_image}" = "$(DEFAULT_PYTHON_BASE_IMAGE)" ]; then \
		if docker image inspect "$${base_image}" >/dev/null 2>&1; then \
			echo "Using cached default base image $${base_image}"; \
		elif ! docker pull "$${base_image}"; then \
			echo "Docker Hub pull failed for $${base_image}; retrying with $(PYTHON_BASE_IMAGE_FALLBACK)"; \
			base_image="$(PYTHON_BASE_IMAGE_FALLBACK)"; \
			docker pull "$${base_image}"; \
		fi; \
	else \
		echo "Using configured base image override $${base_image} without registry preflight"; \
	fi; \
	docker build --build-arg PYTHON_BASE_IMAGE="$${base_image}" -t realtime-asr:latest .
	@echo "  ✓ Image built: realtime-asr:latest"

run: venv
	@echo "Running service locally..."
	@echo "  Service will be available at http://localhost:8080"
	@$(UVICORN) src.main:app --host 0.0.0.0 --port 8080 --log-level info

dev: venv
	@echo "Running in development mode..."
	@$(UVICORN) src.main:app --host 0.0.0.0 --port 8080 --reload --log-level debug

start:
	@echo "Starting docker compose stack..."
	docker compose up -d --build
	@echo "  ✓ Service started"

stop:
	@echo "Stopping service..."
	docker compose down
	@echo "  ✓ Service stopped"

status:
	@echo "Checking service status..."
	docker compose ps
	@echo ""
	@echo "Liveness:"
	@curl -s http://localhost:8080/health 2>/dev/null || echo "  ⚠ Service not running locally"
	@echo ""
	@echo "Readiness:"
	@curl -s -f http://localhost:8080/ready 2>/dev/null || echo "  ⚠ Service is live but not ready"

test: venv
	@echo "Running test suite..."
	@$(PYTHON) -m pytest tests/test_smoke.py tests/test_client.py -v

benchmark: venv
	@$(MAKE) benchmark-faster-whisper-small

benchmark-faster-whisper-matrix: benchmark-faster-whisper-base benchmark-faster-whisper-small
	@echo "  ✓ faster-whisper benchmark matrix complete with $(BENCHMARK_SAMPLE_COUNT) samples per model"

benchmark-faster-whisper-base: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_BASE_MODEL) $(FASTER_WHISPER_COMPUTE_TYPE) latency benchmark..."
	@$(PYTHON) tests/benchmark.py --spawn-server --model $(FASTER_WHISPER_BASE_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_BASE_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json

benchmark-faster-whisper-small: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_SMALL_MODEL) $(FASTER_WHISPER_COMPUTE_TYPE) latency benchmark..."
	@$(PYTHON) tests/benchmark.py --spawn-server --model $(FASTER_WHISPER_SMALL_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_SMALL_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json

benchmark-qwen-mps: venv
	@echo "Running qwen-asr $(QWEN_MPS_MODEL) latency benchmark on Apple Silicon MPS..."
	@uname -s | grep -q '^Darwin$$' || (echo "benchmark-qwen-mps requires macOS." >&2; exit 1)
	@$(PYTHON) -c "import torch; assert getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available(), 'benchmark-qwen-mps requires torch.backends.mps.is_available()'"
	@mkdir -p .cache/huggingface
	@ASR_BACKEND=qwen-asr ASR_DEVICE=mps ASR_QWEN_MODEL=$(QWEN_MPS_MODEL) ASR_QWEN_DTYPE=$(QWEN_MPS_DTYPE) $(PYTHON) tests/benchmark.py --spawn-server --backend qwen-asr --model $(QWEN_MPS_MODEL) --device mps --qwen-dtype $(QWEN_MPS_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --chunk-ms $(BENCHMARK_CHUNK_MS) --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/qwen-mps-$(BENCHMARK_RESULT_DATE).json

benchmark-compose-matrix: benchmark-compose-qwen benchmark-compose-parakeet benchmark-compose-parakeet-nemo benchmark-compose-ultravox
	@echo "  ✓ Compose benchmark matrix complete with $(BENCHMARK_SAMPLE_COUNT) samples per backend"

benchmark-compose-qwen: venv
	@echo "Starting docker compose stack with qwen-asr on CPU..."
	@mkdir -p .cache/huggingface
	@{ set -e; \
	cleanup() { docker compose down >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT INT TERM; \
	base_image="$(PYTHON_BASE_IMAGE)"; \
	if [ "$${base_image}" = "$(DEFAULT_PYTHON_BASE_IMAGE)" ]; then \
		if docker image inspect "$${base_image}" >/dev/null 2>&1; then \
			echo "Using cached default base image $${base_image}"; \
		elif ! docker pull "$${base_image}"; then \
			echo "Docker Hub pull failed for $${base_image}; retrying with $(PYTHON_BASE_IMAGE_FALLBACK)"; \
			base_image="$(PYTHON_BASE_IMAGE_FALLBACK)"; \
			docker pull "$${base_image}"; \
		fi; \
	else \
		echo "Using configured base image override $${base_image} without registry preflight"; \
	fi; \
	ASR_BACKEND=qwen-asr ASR_QWEN_MODEL=$(QWEN_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_QWEN_DTYPE=$(QWEN_COMPOSE_DTYPE) ASR_QWEN_MAX_NEW_TOKENS=$(QWEN_COMPOSE_MAX_NEW_TOKENS) PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	$(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend qwen-asr --model $(QWEN_COMPOSE_MODEL) --qwen-dtype $(QWEN_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --chunk-ms $(BENCHMARK_CHUNK_MS) --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/qwen-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-parakeet: venv
	@echo "Starting docker compose stack with parakeet on CPU..."
	@mkdir -p .cache/huggingface
	@{ set -e; \
	cleanup() { docker compose down >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT INT TERM; \
	base_image="$(PYTHON_BASE_IMAGE)"; \
	if [ "$${base_image}" = "$(DEFAULT_PYTHON_BASE_IMAGE)" ]; then \
		if docker image inspect "$${base_image}" >/dev/null 2>&1; then \
			echo "Using cached default base image $${base_image}"; \
		elif ! docker pull "$${base_image}"; then \
			echo "Docker Hub pull failed for $${base_image}; retrying with $(PYTHON_BASE_IMAGE_FALLBACK)"; \
			base_image="$(PYTHON_BASE_IMAGE_FALLBACK)"; \
			docker pull "$${base_image}"; \
		fi; \
	else \
		echo "Using configured base image override $${base_image} without registry preflight"; \
	fi; \
	ENABLE_PARAKEET_RUNTIME=1 ASR_BACKEND=parakeet ASR_PARAKEET_MODEL=$(PARAKEET_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	$(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend parakeet --model $(PARAKEET_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --chunk-ms $(BENCHMARK_CHUNK_MS) --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/parakeet-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-parakeet-nemo: venv
	@echo "Starting docker compose stack with Parakeet 110M through NeMo on CPU..."
	@mkdir -p .cache/huggingface
	@{ set -e; \
	cleanup() { docker compose down >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT INT TERM; \
	base_image="$(PYTHON_BASE_IMAGE)"; \
	if [ "$${base_image}" = "$(DEFAULT_PYTHON_BASE_IMAGE)" ]; then \
		if docker image inspect "$${base_image}" >/dev/null 2>&1; then \
			echo "Using cached default base image $${base_image}"; \
		elif ! docker pull "$${base_image}"; then \
			echo "Docker Hub pull failed for $${base_image}; retrying with $(PYTHON_BASE_IMAGE_FALLBACK)"; \
			base_image="$(PYTHON_BASE_IMAGE_FALLBACK)"; \
			docker pull "$${base_image}"; \
		fi; \
	else \
		echo "Using configured base image override $${base_image} without registry preflight"; \
	fi; \
	ENABLE_NEMO_RUNTIME=1 ASR_BACKEND=parakeet-nemo ASR_PARAKEET_MODEL=$(PARAKEET_NEMO_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	$(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend parakeet-nemo --model $(PARAKEET_NEMO_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --chunk-ms $(BENCHMARK_CHUNK_MS) --partial-interval-chunks $(PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/parakeet-nemo-110m-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-ultravox: venv
	@echo "Starting docker compose stack with ultravox on CPU..."
	@mkdir -p .cache/huggingface
	@test -n "$(HF_TOKEN)$(HUGGINGFACE_HUB_TOKEN)" || (echo "Ultravox default model requires Hugging Face access. Export HF_TOKEN or HUGGINGFACE_HUB_TOKEN before running this target." >&2; exit 1)
	@{ set -e; \
	cleanup() { docker compose down >/dev/null 2>&1 || true; }; \
	trap cleanup EXIT INT TERM; \
	base_image="$(PYTHON_BASE_IMAGE)"; \
	if [ "$${base_image}" = "$(DEFAULT_PYTHON_BASE_IMAGE)" ]; then \
		if docker image inspect "$${base_image}" >/dev/null 2>&1; then \
			echo "Using cached default base image $${base_image}"; \
		elif ! docker pull "$${base_image}"; then \
			echo "Docker Hub pull failed for $${base_image}; retrying with $(PYTHON_BASE_IMAGE_FALLBACK)"; \
			base_image="$(PYTHON_BASE_IMAGE_FALLBACK)"; \
			docker pull "$${base_image}"; \
		fi; \
	else \
		echo "Using configured base image override $${base_image} without registry preflight"; \
	fi; \
	ASR_BACKEND=ultravox ASR_ULTRAVOX_MODEL=$(ULTRAVOX_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_ULTRAVOX_DTYPE=$(ULTRAVOX_COMPOSE_DTYPE) ASR_ULTRAVOX_MAX_NEW_TOKENS=$(ULTRAVOX_MAX_NEW_TOKENS) PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	$(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend ultravox --model $(ULTRAVOX_COMPOSE_MODEL) --ultravox-dtype $(ULTRAVOX_COMPOSE_DTYPE) --ultravox-max-new-tokens $(ULTRAVOX_MAX_NEW_TOKENS) --sample-count $(BENCHMARK_SAMPLE_COUNT) --chunk-ms $(BENCHMARK_CHUNK_MS) --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/ultravox-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-qwen-mlx-text: mlx-venv
	@echo "Benchmarking $(QWEN_MLX_TEXT_MODEL) with mlx-lm on Apple Silicon..."
	@test "$$(uname -s)-$$(uname -m)" = "Darwin-arm64" || (echo "MLX benchmarks require macOS on Apple Silicon." >&2; exit 1)
	@$(MLX_PYTHON) scripts/benchmark_mlx_text.py --model $(QWEN_MLX_TEXT_MODEL) --sample-count $(QWEN_MLX_TEXT_SAMPLE_COUNT) --max-tokens $(QWEN_MLX_TEXT_MAX_TOKENS) --output $(BENCHMARK_RESULTS_DIR)/qwen3-0.6b-mlx-4bit-text-$(BENCHMARK_RESULT_DATE).json

lint: venv
	@echo "Running linter..."
	@$(PYTHON) -m py_compile src/*.py tests/test_smoke.py tests/benchmark.py scripts/build_benchmark_manifest.py
	@echo "  ✓ Linting complete"

benchmark-site:
	@echo "Building benchmark site manifest..."
	@python3 scripts/build_benchmark_manifest.py --results-dir $(BENCHMARK_RESULTS_DIR) --output $(BENCHMARK_RESULTS_DIR)/manifest.json
	@echo "  ✓ Benchmark site manifest built"

benchmark-site-check:
	@python3 scripts/build_benchmark_manifest.py --results-dir $(BENCHMARK_RESULTS_DIR) --output $(BENCHMARK_RESULTS_DIR)/manifest.json --check
	@echo "  ✓ Benchmark site manifest is up to date"

docs: benchmark-site
	@echo "Building documentation..."
	@mkdir -p docs/_build
	@cp README.md docs/_build/
	@echo "  ✓ Documentation built"

clean:
	@echo "Cleaning build artifacts..."
	@rm -rf __pycache__
	@rm -rf *.pyc
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@echo "  ✓ Cleanup complete"
