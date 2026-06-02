# Realtime ASR Service

Realtime speech recognition service for voice AI applications with REST and WebSocket interfaces.

![Status](https://img.shields.io/badge/status-ready-brightgreen)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Features

- ⚡ **Streaming-ready**: REST and WebSocket interfaces for transcription flows
- 🌐 **Multilingual**: Support for 10+ languages (English, Spanish, French, Chinese, Japanese, etc.)
- 🎯 **Streaming**: WebSocket API for continuous transcription
- 📦 **Containerized**: Docker-ready with GPU support
- 🔒 **Secure**: API key authentication support
- 📊 **Metrics**: Prometheus-compatible metrics endpoint
- 🔄 **Fallback**: Automatic Whisper fallback if model fails

> Benchmark status: latency, throughput, and accuracy figures in this repository are not yet validated. Treat performance-related material as provisional until the real ASR path and benchmark harness are complete.

## Quick Start

### Docker

```bash
# Build
docker compose build

# Run
docker compose up -d

# Check status
docker compose ps

# View logs
docker compose logs -f
```

### API

```bash
# Health check
curl http://localhost:8080/health

# List models
curl http://localhost:8080/api/models

# Transcribe audio
curl -X POST http://localhost:8080/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio": "base64_audio_data", "language": "en"}'
```

### WebSocket

```bash
# Connect to streaming
ws://localhost:8080/ws/stream
```

## Integration

### Pipecat

```python
from pipecat.stt import STT

stt_channel = STT(
    language="en",
    model="qwen",
    device="cuda"
)
```

### LiveKit

```python
from livekit.plugins import stt

asr_plugin = stt.create_stt_plugin(
    language="en",
    model="qwen"
)
```

See [Integration Guides](./docs/) for detailed instructions.

## Development

```bash
# Setup
make setup

# Run locally
make dev

# Run tests
make test

# Build wheel
make build-wheel
```

## Configuration

Edit `.env` for configuration:

```env
# Model
MODEL_NAME=Qwen3-ASR-1.7B
USE_WHISPER_FALLBACK=true

# Service
HOST=0.0.0.0
PORT=8080

# Audio
SAMPLE_RATE=16000
CHUNK_SIZE=1024

# GPU
CUDA_VISIBLE_DEVICES=0
```

## Documentation

- [API Reference](./docs/api-reference.md)
- [Pipecat Integration](./docs/pipecat-integration.md)
- [LiveKit Integration](./docs/livekit-integration.md)
- [Benchmarks](./docs/benchmarks.md)
- [Troubleshooting](./docs/troubleshooting.md)

## Performance

Validated benchmark results are not available yet.

- Do not rely on published latency, throughput, or WER claims in this repository.
- The production transcription path is being wired to a real ASR backend, and benchmark numbers will be published only after measurement is reproducible.
- See [Benchmarks](./docs/benchmarks.md) for the current validation status and planned harness.

## Requirements

- Python 3.10+
- Docker/Docker Compose
- GPU (optional, for best performance)

## License

MIT

## Support

- Issues: [GitHub Issues](https://github.com/qwen/realtime-asr/issues)
- Docs: [Documentation](./docs/)
- Support: support@qwen.ai
