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
COMPOSE_V1_WS_URL ?= ws://127.0.0.1:8080/v1/stt/stream
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
PARAKEET_MLX_MODEL ?= mlx-community/parakeet-tdt-0.6b-v3
PARAKEET_MLX_ARTIFACT_SLUG ?= parakeet-mlx
PARAKEET_MLX_SAMPLE_COUNT ?= 3
PARAKEET_MLX_SERVICE_ARTIFACT_SLUG ?= parakeet-mlx-service
BENCHMARK_RESULTS_DIR ?= docs/benchmark-results
BENCHMARK_RESULT_DATE ?= $(shell date -u +%Y-%m-%d)
BENCHMARK_SAMPLE_COUNT ?= 10
BENCHMARK_REST_RUNS ?= 5
BENCHMARK_CHUNK_MS ?= 250
BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 1
PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS ?= 8
BENCHMARK_PARTIAL_WINDOW ?= 2.0
BENCHMARK_BINARY_FRAMES ?=
BENCHMARK_PIPECAT_AUDIO_FILE ?=
BENCHMARK_PIPECAT_BACKEND ?= faster-whisper
BENCHMARK_PIPECAT_MODEL ?= base.en
BENCHMARK_PIPECAT_COMPUTE_TYPE ?= int8
BENCHMARK_PIPECAT_SOURCE_FRAME_MS ?= 20
BENCHMARK_PIPECAT_REALTIME_FLAG ?= --simulate-realtime
BENCHMARK_V1_SOURCE_FRAME_MS ?= 20
BENCHMARK_V1_AGGREGATION_MS ?= 100
BENCHMARK_V1_PARTIAL_INTERVAL_MS ?= 100
BENCHMARK_V1_REALTIME_FLAG ?= --simulate-realtime
BENCHMARK_REQUEST_RETRIES ?= 3
BENCHMARK_REQUEST_RETRY_DELAY ?= 2.0
FASTER_WHISPER_BASE_MODEL ?= base.en
FASTER_WHISPER_SMALL_MODEL ?= small.en
FASTER_WHISPER_COMPUTE_TYPE ?= int8
LOW_LATENCY_SWEEP_SAMPLE_COUNT ?= 5
LOW_LATENCY_SWEEP_REST_RUNS ?= 3
LOW_LATENCY_SWEEP_CHUNK_MS ?= 80 100 160 200
LOW_LATENCY_SWEEP_PARTIAL_WINDOWS ?= 0.75 1.0 1.5 2.0
LOW_LATENCY_SWEEP_BINARY_FRAMES ?= false

LOW_LATENCY_SWEEP_TARGETS := \
	benchmark-faster-whisper-base-low-latency-sweep \
	benchmark-faster-whisper-small-low-latency-sweep \
	benchmark-compose-qwen-low-latency-sweep \
	benchmark-compose-parakeet-low-latency-sweep \
	benchmark-compose-parakeet-nemo-low-latency-sweep

ifeq ($(shell uname -s),Darwin)
LOW_LATENCY_SWEEP_TARGETS += benchmark-qwen-mps-low-latency-sweep
endif

.PHONY: help venv mlx-venv setup build run dev test benchmark benchmark-faster-whisper-matrix benchmark-faster-whisper-base benchmark-faster-whisper-small benchmark-faster-whisper-base-low-latency-sweep benchmark-faster-whisper-small-low-latency-sweep benchmark-qwen-mps benchmark-qwen-mps-low-latency-sweep benchmark-compose-matrix benchmark-compose-qwen benchmark-compose-qwen-low-latency-sweep benchmark-compose-parakeet benchmark-compose-parakeet-low-latency-sweep benchmark-compose-parakeet-nemo benchmark-compose-parakeet-nemo-low-latency-sweep benchmark-all-asr-low-latency-sweep benchmark-parakeet-mlx benchmark-parakeet-mlx-110m benchmark-parakeet-mlx-service benchmark-parakeet-mlx-service-110m benchmark-pipecat-e2e benchmark-site benchmark-site-check clean lint docs start stop status
.NOTPARALLEL: benchmark-faster-whisper-matrix benchmark-faster-whisper-base-low-latency-sweep benchmark-faster-whisper-small-low-latency-sweep benchmark-qwen-mps-low-latency-sweep benchmark-compose-qwen-low-latency-sweep benchmark-compose-parakeet-low-latency-sweep benchmark-compose-parakeet-nemo-low-latency-sweep benchmark-all-asr-low-latency-sweep benchmark-compose-matrix

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
	@echo "  make benchmark-all-asr-low-latency-sweep - Run all ASR low-latency sweeps across $(LOW_LATENCY_SWEEP_CHUNK_MS) ms chunks and $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS) s windows"
	@echo "  make benchmark-faster-whisper-base-low-latency-sweep - Run faster-whisper base.en low-latency sweep"
	@echo "  make benchmark-faster-whisper-small-low-latency-sweep - Run faster-whisper small.en low-latency sweep"
	@echo "  make benchmark-qwen-mps - Run qwen-asr locally on Apple Silicon MPS"
	@echo "  make benchmark-qwen-mps-low-latency-sweep - Run qwen-asr low-latency sweep on Apple Silicon MPS"
	@echo "  make benchmark-pipecat-e2e - Run a Pipecat-style end-to-end streaming benchmark against a local backend"
	@echo "  make benchmark-compose-matrix - Run all Compose model benchmarks with $(BENCHMARK_SAMPLE_COUNT) samples each"
	@echo "  make benchmark-compose-qwen - Start compose, wait for readiness, and benchmark qwen-asr"
	@echo "  make benchmark-compose-qwen-low-latency-sweep - Start compose and sweep qwen-asr low-latency settings"
	@echo "  make benchmark-compose-parakeet - Start compose, wait for readiness, and benchmark parakeet"
	@echo "  make benchmark-compose-parakeet-low-latency-sweep - Start compose and sweep parakeet low-latency settings"
	@echo "  make benchmark-compose-parakeet-nemo - Start compose and benchmark Parakeet 110M through NeMo"
	@echo "  make benchmark-compose-parakeet-nemo-low-latency-sweep - Start compose and sweep Parakeet 110M through NeMo"
	@echo "  make benchmark-parakeet-mlx - Run a local Parakeet MLX ASR benchmark on Apple Silicon with synthesized speech by default"
	@echo "  make benchmark-parakeet-mlx-110m - Run the 110M Parakeet MLX ASR benchmark with its own artifact slug"
	@echo "  make benchmark-parakeet-mlx-service - Run the warmed MLX service benchmark through the /v1/stt/stream harness"
	@echo "  make benchmark-parakeet-mlx-service-110m - Run the warmed 110M MLX service benchmark through the /v1/stt/stream harness"
	@echo "  make lint           - Run linter"
	@echo "  make benchmark-site-check - Fail when docs/benchmark-results/manifest.json is stale"
	@echo "  make docs           - Build documentation snapshot"
	@echo "  make start          - Start docker compose stack, including the browser Pipecat demo"
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
	@if [ -x $(MLX_PYTHON) ] && $(MLX_PYTHON) -c "import fastapi, httpx, numpy, parakeet_mlx, soundfile, uvicorn, websockets" >/dev/null 2>&1; then \
		echo "  ✓ Reusing existing MLX virtualenv at $(MLX_VENV)"; \
	else \
		echo "  Rebuilding $(MLX_VENV) because the MLX benchmark runtime is missing or broken..."; \
		rm -rf $(MLX_VENV); \
		python3 -m venv $(MLX_VENV); \
		$(MLX_PYTHON) -m pip install --upgrade pip fastapi "uvicorn[standard]" pydantic python-multipart websockets numpy soundfile httpx parakeet-mlx psutil; \
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
	@echo "  ✓ Services started: http://127.0.0.1:8080 and http://127.0.0.1:8090/rtc-asr"

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
	@echo ""
	@echo "Pipecat demo:"
	@curl -s -f http://localhost:8090/rtc-asr/config 2>/dev/null || echo "  ⚠ Pipecat demo is not reachable locally"

test: venv
	@echo "Running test suite..."
	@$(PYTHON) -m pytest tests/test_smoke.py tests/test_client.py -v

benchmark: venv
	@$(MAKE) benchmark-faster-whisper-small

benchmark-faster-whisper-matrix: benchmark-faster-whisper-base benchmark-faster-whisper-small
	@echo "  ✓ faster-whisper benchmark matrix complete with $(BENCHMARK_SAMPLE_COUNT) samples per model"

benchmark-faster-whisper-base: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_BASE_MODEL) $(FASTER_WHISPER_COMPUTE_TYPE) latency benchmark..."
	@PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --mode v1-stt-stream --model $(FASTER_WHISPER_BASE_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_BASE_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json

benchmark-faster-whisper-small: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_SMALL_MODEL) $(FASTER_WHISPER_COMPUTE_TYPE) latency benchmark..."
	@PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --mode v1-stt-stream --model $(FASTER_WHISPER_SMALL_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_SMALL_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-$(BENCHMARK_RESULT_DATE).json

benchmark-faster-whisper-base-low-latency-sweep: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_BASE_MODEL) low-latency sweep..."
	@{ set -e; 	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do 		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do 			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do 				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; 				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); 				output="$(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_BASE_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; 				echo "  -> $$output"; 				PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --model $(FASTER_WHISPER_BASE_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; 			done; 		done; 	done; 	}

benchmark-faster-whisper-small-low-latency-sweep: venv
	@echo "Running faster-whisper $(FASTER_WHISPER_SMALL_MODEL) low-latency sweep..."
	@{ set -e; 	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do 		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do 			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do 				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; 				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); 				output="$(BENCHMARK_RESULTS_DIR)/faster-whisper-$(FASTER_WHISPER_SMALL_MODEL)-$(FASTER_WHISPER_COMPUTE_TYPE)-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; 				echo "  -> $$output"; 				PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --model $(FASTER_WHISPER_SMALL_MODEL) --compute-type $(FASTER_WHISPER_COMPUTE_TYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; 			done; 		done; 	done; 	}

benchmark-qwen-mps: venv
	@echo "Running qwen-asr $(QWEN_MPS_MODEL) latency benchmark on Apple Silicon MPS..."
	@uname -s | grep -q '^Darwin$$' || (echo "benchmark-qwen-mps requires macOS." >&2; exit 1)
	@$(PYTHON) -c "import torch; assert getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available(), 'benchmark-qwen-mps requires torch.backends.mps.is_available()'"
	@mkdir -p .cache/huggingface
	@ASR_BACKEND=qwen-asr ASR_DEVICE=mps ASR_QWEN_DEVICE_MAP= ASR_QWEN_MODEL=$(QWEN_MPS_MODEL) ASR_QWEN_DTYPE=$(QWEN_MPS_DTYPE) PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --mode v1-stt-stream --backend qwen-asr --model $(QWEN_MPS_MODEL) --device mps --qwen-dtype $(QWEN_MPS_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/qwen-mps-$(BENCHMARK_RESULT_DATE).json

benchmark-qwen-mps-low-latency-sweep: venv
	@echo "Running qwen-asr $(QWEN_MPS_MODEL) low-latency sweep on Apple Silicon MPS..."
	@uname -s | grep -q '^Darwin$$' || (echo "benchmark-qwen-mps-low-latency-sweep requires macOS." >&2; exit 1)
	@$(PYTHON) -c "import torch; assert getattr(torch.backends, 'mps', None) and torch.backends.mps.is_available(), 'benchmark-qwen-mps-low-latency-sweep requires torch.backends.mps.is_available()'"
	@mkdir -p .cache/huggingface
	@{ set -e; 	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do 		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do 			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do 				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; 				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); 				output="$(BENCHMARK_RESULTS_DIR)/qwen-mps-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; 				echo "  -> $$output"; 				ASR_BACKEND=qwen-asr ASR_DEVICE=mps ASR_QWEN_DEVICE_MAP= ASR_QWEN_MODEL=$(QWEN_MPS_MODEL) ASR_QWEN_DTYPE=$(QWEN_MPS_DTYPE) PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --backend qwen-asr --model $(QWEN_MPS_MODEL) --device mps --qwen-dtype $(QWEN_MPS_DTYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; 			done; 		done; 	done; 	}

benchmark-compose-matrix: benchmark-compose-qwen benchmark-compose-parakeet benchmark-compose-parakeet-nemo
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
	ASR_BACKEND=qwen-asr ASR_QWEN_MODEL=$(QWEN_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_QWEN_DTYPE=$(QWEN_COMPOSE_DTYPE) ASR_QWEN_MAX_NEW_TOKENS=$(QWEN_COMPOSE_MAX_NEW_TOKENS) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	PYTHONPATH=. $(PYTHON) tests/benchmark.py --mode v1-stt-stream --url $(COMPOSE_URL) --v1-ws-url $(COMPOSE_V1_WS_URL) --backend qwen-asr --model $(QWEN_COMPOSE_MODEL) --qwen-dtype $(QWEN_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/qwen-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-qwen-low-latency-sweep: venv
	@echo "Starting docker compose stack with qwen-asr on CPU for low-latency sweep..."
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
	ASR_BACKEND=qwen-asr ASR_QWEN_MODEL=$(QWEN_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_QWEN_DTYPE=$(QWEN_COMPOSE_DTYPE) ASR_QWEN_MAX_NEW_TOKENS=$(QWEN_COMPOSE_MAX_NEW_TOKENS) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do \
		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do \
			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do \
				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; \
				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); \
				output="$(BENCHMARK_RESULTS_DIR)/qwen-compose-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; \
				echo "  -> $$output"; \
				PYTHONPATH=. $(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend qwen-asr --model $(QWEN_COMPOSE_MODEL) --qwen-dtype $(QWEN_COMPOSE_DTYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; \
			done; \
		done; \
	done; }

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
	ENABLE_PARAKEET_RUNTIME=1 ASR_BACKEND=parakeet ASR_PARAKEET_MODEL=$(PARAKEET_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	PYTHONPATH=. $(PYTHON) tests/benchmark.py --mode v1-stt-stream --url $(COMPOSE_URL) --v1-ws-url $(COMPOSE_V1_WS_URL) --backend parakeet --model $(PARAKEET_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/parakeet-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-parakeet-low-latency-sweep: venv
	@echo "Starting docker compose stack with parakeet on CPU for low-latency sweep..."
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
	ENABLE_PARAKEET_RUNTIME=1 ASR_BACKEND=parakeet ASR_PARAKEET_MODEL=$(PARAKEET_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do \
		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do \
			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do \
				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; \
				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); \
				output="$(BENCHMARK_RESULTS_DIR)/parakeet-compose-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; \
				echo "  -> $$output"; \
				PYTHONPATH=. $(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend parakeet --model $(PARAKEET_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; \
			done; \
		done; \
	done; }

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
	ENABLE_NEMO_RUNTIME=1 ASR_BACKEND=parakeet-nemo ASR_PARAKEET_MODEL=$(PARAKEET_NEMO_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	PYTHONPATH=. $(PYTHON) tests/benchmark.py --mode v1-stt-stream --url $(COMPOSE_URL) --v1-ws-url $(COMPOSE_V1_WS_URL) --backend parakeet-nemo --model $(PARAKEET_NEMO_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/parakeet-nemo-110m-compose-$(BENCHMARK_RESULT_DATE).json; }

benchmark-compose-parakeet-nemo-low-latency-sweep: venv
	@echo "Starting docker compose stack with Parakeet 110M through NeMo on CPU for low-latency sweep..."
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
	ENABLE_NEMO_RUNTIME=1 ASR_BACKEND=parakeet-nemo ASR_PARAKEET_MODEL=$(PARAKEET_NEMO_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_PARAKEET_DTYPE=$(PARAKEET_COMPOSE_DTYPE) ASR_PRELOAD_MODEL=true PYTHON_BASE_IMAGE="$${base_image}" docker compose up -d --build; \
	attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"; \
	for chunk in $(LOW_LATENCY_SWEEP_CHUNK_MS); do \
		for window in $(LOW_LATENCY_SWEEP_PARTIAL_WINDOWS); do \
			for frame in $(LOW_LATENCY_SWEEP_BINARY_FRAMES); do \
				if [ "$$frame" = "true" ]; then frame_flag="--binary-frames"; frame_label="binary"; else frame_flag=""; frame_label="json"; fi; \
				window_slug=$$(printf '%s' "$$window" | tr '.' '_'); \
				output="$(BENCHMARK_RESULTS_DIR)/parakeet-nemo-110m-compose-c$${chunk}-w$${window_slug}-$${frame_label}-$(BENCHMARK_RESULT_DATE).json"; \
				echo "  -> $$output"; \
				PYTHONPATH=. $(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL) --backend parakeet-nemo --model $(PARAKEET_NEMO_COMPOSE_MODEL) --parakeet-dtype $(PARAKEET_COMPOSE_DTYPE) --sample-count $(LOW_LATENCY_SWEEP_SAMPLE_COUNT) --rest-runs $(LOW_LATENCY_SWEEP_REST_RUNS) --chunk-ms $$chunk --partial-interval-chunks $(PARAKEET_NEMO_BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $$window $$frame_flag --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output "$$output"; \
			done; \
		done; \
	done; }

benchmark-all-asr-low-latency-sweep: $(LOW_LATENCY_SWEEP_TARGETS)
	@echo "  ✓ all ASR low-latency sweeps complete"


benchmark-pipecat-e2e: venv
	@echo "Running Pipecat-style end-to-end benchmark..."
	@{ set -e; \
		if [ -n "$(BENCHMARK_PIPECAT_AUDIO_FILE)" ]; then \
			echo "  Using speech clip: $(BENCHMARK_PIPECAT_AUDIO_FILE)"; \
			audio_flag="--audio-file $(BENCHMARK_PIPECAT_AUDIO_FILE)"; \
		else \
			echo "  No BENCHMARK_PIPECAT_AUDIO_FILE set; synthesizing a speech clip via the benchmark harness."; \
			audio_flag=""; \
		fi; \
		PYTHONPATH=. $(PYTHON) tests/benchmark.py --spawn-server --mode pipecat-e2e --backend $(BENCHMARK_PIPECAT_BACKEND) --model $(BENCHMARK_PIPECAT_MODEL) --compute-type $(BENCHMARK_PIPECAT_COMPUTE_TYPE) $$audio_flag --sample-count 1 --rest-runs 1 --chunk-ms 100 --pipecat-source-frame-ms $(BENCHMARK_PIPECAT_SOURCE_FRAME_MS) --partial-interval-chunks $(BENCHMARK_PARTIAL_INTERVAL_CHUNKS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_PIPECAT_REALTIME_FLAG) $(BENCHMARK_BINARY_FRAMES) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/$(BENCHMARK_PIPECAT_BACKEND)-$(BENCHMARK_PIPECAT_MODEL)-$(BENCHMARK_PIPECAT_COMPUTE_TYPE)-pipecat-e2e-$(BENCHMARK_RESULT_DATE).json; \
	}

benchmark-parakeet-mlx: mlx-venv
	@echo "Benchmarking $(PARAKEET_MLX_MODEL) with parakeet-mlx on Apple Silicon..."
	@test "$$(uname -s)-$$(uname -m)" = "Darwin-arm64" || (echo "MLX benchmarks require macOS on Apple Silicon." >&2; exit 1)
	@$(MLX_PYTHON) scripts/benchmark_mlx_asr.py --model $(PARAKEET_MLX_MODEL) --sample-count $(PARAKEET_MLX_SAMPLE_COUNT) $(if $(BENCHMARK_MLX_AUDIO_FILE),--audio-file $(BENCHMARK_MLX_AUDIO_FILE),) --output $(BENCHMARK_RESULTS_DIR)/$(PARAKEET_MLX_ARTIFACT_SLUG)-$(BENCHMARK_RESULT_DATE).json

benchmark-parakeet-mlx-110m:
	@$(MAKE) benchmark-parakeet-mlx PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt_ctc-110m PARAKEET_MLX_ARTIFACT_SLUG=parakeet-mlx-110m

benchmark-parakeet-mlx-service: mlx-venv
	@echo "Benchmarking $(PARAKEET_MLX_MODEL) through the warmed MLX /v1/stt/stream harness..."
	@test "$$(uname -s)-$$(uname -m)" = "Darwin-arm64" || (echo "MLX benchmarks require macOS on Apple Silicon." >&2; exit 1)
	@{ set -e; 	cleanup() { if [ -n "$$server_pid" ] && kill -0 "$$server_pid" >/dev/null 2>&1; then kill "$$server_pid" >/dev/null 2>&1 || true; wait "$$server_pid" 2>/dev/null || true; fi; rm -f "$$log_file"; }; 	trap cleanup EXIT INT TERM; 	log_file="$$(mktemp -t rtc-asr-parakeet-mlx.XXXXXX.log)"; 	PYTHONPATH=. ASR_BACKEND=parakeet-mlx ASR_DEVICE=apple-silicon ASR_PRELOAD_MODEL=true ASR_PARAKEET_MODEL=$(PARAKEET_MLX_MODEL) ASR_PARAKEET_DTYPE=auto $(MLX_PYTHON) -m uvicorn src.main:app --host 127.0.0.1 --port 8090 --log-level warning >"$$log_file" 2>&1 & 	server_pid=$$!; 	for attempt in $$(seq 1 180); do 		if curl -sf http://127.0.0.1:8090/ready >/dev/null; then break; fi; 		if ! kill -0 "$$server_pid" >/dev/null 2>&1; then cat "$$log_file"; exit 1; fi; 		sleep 1; 	done; 	curl -sf http://127.0.0.1:8090/ready >/dev/null || (cat "$$log_file"; exit 1); 	PYTHONPATH=. $(MLX_PYTHON) tests/benchmark.py --mode v1-stt-stream --url http://127.0.0.1:8090 --v1-ws-url ws://127.0.0.1:8090/v1/stt/stream --backend parakeet-mlx --model $(PARAKEET_MLX_MODEL) --device apple-silicon --parakeet-dtype auto --sample-count $(BENCHMARK_SAMPLE_COUNT) --rest-runs $(BENCHMARK_REST_RUNS) --v1-source-frame-ms $(BENCHMARK_V1_SOURCE_FRAME_MS) --v1-aggregation-ms $(BENCHMARK_V1_AGGREGATION_MS) --v1-partial-interval-ms $(BENCHMARK_V1_PARTIAL_INTERVAL_MS) --partial-window $(BENCHMARK_PARTIAL_WINDOW) $(BENCHMARK_V1_REALTIME_FLAG) --request-retries $(BENCHMARK_REQUEST_RETRIES) --request-retry-delay $(BENCHMARK_REQUEST_RETRY_DELAY) --output $(BENCHMARK_RESULTS_DIR)/$(PARAKEET_MLX_SERVICE_ARTIFACT_SLUG)-$(BENCHMARK_RESULT_DATE).json; 	}

benchmark-parakeet-mlx-service-110m:
	@$(MAKE) benchmark-parakeet-mlx-service PARAKEET_MLX_MODEL=mlx-community/parakeet-tdt_ctc-110m PARAKEET_MLX_SERVICE_ARTIFACT_SLUG=parakeet-mlx-110m-service

lint: venv
	@echo "Running linter..."
	@$(PYTHON) -m py_compile src/*.py tests/test_smoke.py tests/benchmark.py scripts/build_benchmark_manifest.py scripts/prerender_benchmark_homepage.py scripts/benchmark_mlx_asr.py
	@echo "  ✓ Linting complete"

benchmark-site:
	@echo "Building benchmark site manifest..."
	@python3 scripts/build_benchmark_manifest.py --results-dir $(BENCHMARK_RESULTS_DIR) --output $(BENCHMARK_RESULTS_DIR)/manifest.json
	@python3 scripts/prerender_benchmark_homepage.py --manifest $(BENCHMARK_RESULTS_DIR)/manifest.json --homepage docs/index.html
	@echo "  ✓ Benchmark site manifest built"

benchmark-site-check:
	@python3 scripts/build_benchmark_manifest.py --results-dir $(BENCHMARK_RESULTS_DIR) --output $(BENCHMARK_RESULTS_DIR)/manifest.json --check
	@python3 scripts/prerender_benchmark_homepage.py --manifest $(BENCHMARK_RESULTS_DIR)/manifest.json --homepage docs/index.html --check
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
