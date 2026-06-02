# Realtime ASR Service

Real-time speech recognition service using Qwen3-ASR-1.7B model. The service is under active MVP implementation; latency, throughput, and accuracy claims are targets until the real ASR implementation and benchmark harness are complete.

![Status](https://img.shields.io/badge/status-MVP%20scaffold-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

## Benchmark Status

Published benchmark figures in this repository are provisional and unvalidated. They should not be treated as accurate measured results until the real ASR implementation, benchmark harness, fixture set, and measurement environment are complete and documented.

## Features

- ⚡ **Real-time target**: Low-latency streaming, pending validated benchmarks
- 🌐 **Multilingual**: Support for 10+ languages (English, Spanish, French, Chinese, Japanese, etc.)
- 🎯 **Streaming**: WebSocket API for continuous transcription
- 📦 **Containerized**: Docker-ready with GPU support
- 🔒 **Secure**: API key authentication support
- 📊 **Metrics**: Prometheus-compatible metrics endpoint
- 🔄 **Fallback**: Automatic Whisper fallback if model fails

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

The figures below are provisional planning targets from the recovered scaffold, not validated measurements. Do not use them for production planning, vendor comparisons, or performance claims until measured results are available from the completed benchmark harness.

| Metric | Value |
|--------|-------|
| **Latency P50** | Provisional target: ~120ms |
| **Latency P99** | Provisional target: ~780ms |
| **Throughput** | Provisional target: 25 req/s (GPU), 5 req/s (CPU) |
| **WER** | Provisional target: ~8% (English) |

See [Benchmarks](./docs/benchmarks.md) for provisional details. Validated results will be published after the real ASR implementation and benchmark harness are complete.

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
