# Realtime ASR Service - Makefile
# Convenience commands for development and deployment

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(PYTHON) -m pip
UVICORN := $(VENV)/bin/uvicorn
COMPOSE_URL ?= http://127.0.0.1:8080
COMPOSE_WS_URL ?= ws://127.0.0.1:8080/ws/stream
QWEN_COMPOSE_MODEL ?= Qwen/Qwen3-ASR-0.6B
QWEN_COMPOSE_DTYPE ?= float32

.PHONY: help venv setup build run dev test benchmark benchmark-compose-qwen clean lint docs start stop status

help:
	@echo "Realtime ASR Service - Available commands:"
	@echo ""
	@echo "  make venv           - Create or refresh the local virtualenv"
	@echo "  make setup          - Bootstrap .env and the local virtualenv"
	@echo "  make build          - Build Docker image"
	@echo "  make run            - Run service locally"
	@echo "  make dev            - Run service locally with reload"
	@echo "  make test           - Run the automated test suite"
	@echo "  make benchmark      - Run the reproducible latency benchmark"
	@echo "  make benchmark-compose-qwen - Start compose, wait for readiness, and benchmark qwen-asr"
	@echo "  make lint           - Run linter"
	@echo "  make docs           - Build documentation snapshot"
	@echo "  make start          - Start docker compose stack"
	@echo "  make stop           - Stop docker compose stack"
	@echo "  make status         - Check service status"

venv:
	@echo "Preparing virtualenv..."
	@rm -rf $(VENV)
	@python3 -m venv $(VENV)
	@$(PIP) install --upgrade pip
	@$(PIP) install -r requirements.txt
	@echo "  ✓ Virtualenv ready at $(VENV)"

setup: venv
	@echo "Bootstrapping local config..."
	@test -f .env || cp config.example .env
	@mkdir -p models
	@echo "  ✓ Local config ready (.env)"

build:
	@echo "Building Docker image..."
	docker build -t realtime-asr:latest .
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
	@echo "Running latency benchmark..."
	@$(PYTHON) tests/benchmark.py --spawn-server

benchmark-compose-qwen:
	@echo "Starting docker compose stack with qwen-asr on CPU..."
	@mkdir -p .cache/huggingface
	@test -x $(PYTHON) || (echo "Missing $(PYTHON); create a local client venv before running this target." >&2; exit 1)
	@ASR_BACKEND=qwen-asr ASR_QWEN_MODEL=$(QWEN_COMPOSE_MODEL) ASR_DEVICE=cpu ASR_QWEN_DTYPE=$(QWEN_COMPOSE_DTYPE) docker compose up -d --build
	@attempt=0; until curl -fsS $(COMPOSE_URL)/ready >/dev/null 2>&1; do attempt=$$((attempt + 1)); if [ $$attempt -ge 180 ]; then echo "Timed out waiting for readiness: $(COMPOSE_URL)/ready" >&2; exit 1; fi; sleep 5; done; echo "Compose stack ready: $(COMPOSE_URL)/ready"
	@$(PYTHON) tests/benchmark.py --url $(COMPOSE_URL) --ws-url $(COMPOSE_WS_URL)

lint: venv
	@echo "Running linter..."
	@$(PYTHON) -m py_compile src/*.py tests/test_smoke.py tests/benchmark.py
	@echo "  ✓ Linting complete"

docs:
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
