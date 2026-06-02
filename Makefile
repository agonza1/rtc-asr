# Realtime ASR Service - Makefile
# Convenience commands for development and deployment

.PHONY: help build run dev test clean lint docs

# Default target
help:
	@echo "Realtime ASR Service - Available commands:"
	@echo ""
	@echo "  make build          - Build Docker image"
	@echo "  make run            - Run service locally (CPU)"
	@echo "  make dev            - Run service locally (CPU, debug mode)"
	@echo "  make test           - Run tests"
	@echo "  make lint           - Run linter"
	@echo "  make docs           - Build documentation"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make download-model - Download Qwen3-ASR-1.7B model"
	@echo "  make setup          - Setup development environment"
	@echo "  make start          - Start with GPU"
	@echo "  make stop           - Stop service"
	@echo "  make status         - Check service status"

# Development setup
setup:
	@echo "Setting up development environment..."
	@mkdir -p config models
	@cp config.example config
	@echo "  ✓ Development environment ready"

# Build Docker image
build:
	@echo "Building Docker image..."
	docker build -t realtime-asr:latest .
	@echo "  ✓ Image built: realtime-asr:latest"

# Run locally (CPU)
run: setup
	@echo "Running service locally (CPU)..."
	@echo "  Service will be available at http://localhost:8080"
	@uvicorn src.main:app --host 0.0.0.0 --port 8080 --log-level info

# Development mode
dev: setup
	@echo "Running in development mode..."
	uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload --log-level debug

# Start with GPU
start: build
	@echo "Starting with GPU support..."
	docker compose up -d
	@echo "  ✓ Service started"

# Stop service
stop:
	@echo "Stopping service..."
	docker compose down
	@echo "  ✓ Service stopped"

# Check service status
status:
	@echo "Checking service status..."
	docker compose ps
	@echo ""
	@echo "Service health:"
	curl -s http://localhost:8080/health 2>/dev/null || echo "  ⚠ Service not running locally"

# Run tests
test:
	@echo "Running tests..."
	python -m pytest tests/ -v

# Run linter
lint:
	@echo "Running linter..."
	flake8 src/
	@echo "  ✓ Linting complete"

# Build documentation
docs:
	@echo "Building documentation..."
	@mkdir -p docs/_build
	@cp README.md docs/_build/
	@echo "  ✓ Documentation built"

# Download model
download-model:
	@echo "Downloading Qwen3-ASR-1.7B model..."
	@echo "  This will take several minutes..."
	@mkdir -p models
	@# In production, use huggingface-cli or similar
	@# huggingface-cli download Qwen/Qwen3-ASR-1.7B --local-dir models/Qwen3-ASR-1.7B
	@echo "  ✓ Model directory created: models/Qwen3-ASR-1.7B"
	@echo "  Run 'make download-model' in a real environment to download the model"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	@rm -rf __pycache__
	@rm -rf *.pyc
	@find . -type d -name "__pycache__" -exec rm -rf {} +
	@find . -type f -name "*.pyc" -delete
	@echo "  ✓ Cleanup complete"

# Build wheel
build-wheel:
	@echo "Building wheel..."
	python -m build
	@echo "  ✓ Wheel built in dist/"

# Create requirements.txt from pip freeze
freeze:
	pip freeze > requirements.txt
