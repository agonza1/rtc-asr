# Documentation Index

Welcome to the Realtime ASR Service documentation.

## Quick Links

- [Overview & Installation](../../README.md)
- [API Reference](./api-reference.md)
- [Pipecat Integration](./pipecat-integration.md)
- [LiveKit Integration](./livekit-integration.md)
- [Benchmarks](./benchmarks.md)
- [Troubleshooting](./troubleshooting.md)

## Documentation Structure

```
docs/
├── index.md                    # This file
├── api-reference.md           # API endpoints and examples
├── benchmarks.md              # Performance benchmarks
├── integrations/
│   ├── pipecat-integration.md # Pipecat voice AI framework
│   └── livekit-integration.md # LiveKit WebRTC SDK
└── troubleshooting.md         # Common issues and solutions
```

## Getting Started

1. **Read the README** - Overview and quick start
2. **Review API Reference** - Understand available endpoints
3. **Choose Integration** - Pipecat or LiveKit
4. **Check Benchmarks** - Review validation status and planned measurement methodology
5. **Follow Troubleshooting** - Common issues to watch for

## Architecture Overview

### Components

```
┌─────────────────────────────────────────┐
│         Realtime ASR Service              │
├─────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────────┐ │
│  │  Model Layer  │  │  Inference API   │ │
│  │ Qwen3-ASR    │  │    FastAPI       │ │
│  │   1.7B       │  │  (Uvicorn)      │ │
│  └──────────────┘  └──────────────────┘ │
│  ┌──────────────┐  ┌──────────────────┐ │
│  │   WebSocket  │  │   Streaming      │ │
│  │   Server     │  │   Handler        │ │
│  └──────────────┘  └──────────────────┘ │
└─────────────────────────────────────────┘
```

### Data Flow

```
Audio Input → Preprocessing → Model Inference → Postprocessing → Output
   │              │                 │                  │
   │            AudioProcessor    Qwen3-ASR        TextFrame
   │              │                 │                  │
   └──────────────┼─────────────────┼──────────────────┘
                  │
        Buffer Management
```

## Development Workflow

1. **Clone Repository**
   ```bash
   git clone https://github.com/qwen/realtime-asr.git
   cd realtime-asr
   ```

2. **Setup Environment**
   ```bash
   make setup
   make dev
   ```

3. **Create Application**
   ```python
   # Using Pipecat
   from pipecat.stt import STT
   stt = STT(language="en", model="qwen")
   ```

4. **Deploy to Production**
   ```bash
   make build
   docker compose up -d
   ```

## Production Checklist

- [ ] Health check passes
- [ ] Model loaded successfully
- [ ] WebSocket endpoint responds
- [ ] Error handling tested
- [ ] Metrics endpoint accessible
- [ ] Logging configured
- [ ] Rate limiting enabled
- [ ] CORS configured

## Testing

### Unit Tests

```bash
make test
```

### Integration Tests

```bash
# Test API
curl http://localhost:8080/health

# Test transcription
curl -X POST http://localhost:8080/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio": "base64_data"}'
```

### Performance Tests

```bash
# Run benchmark
python tests/benchmark.py
```

## Resources

### External Resources

- [Qwen Model Documentation](https://github.com/QwenLM/Qwen3-ASR-1.7B)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Pipecat Documentation](https://pipecat.dev/)
- [LiveKit Documentation](https://livekit.io/docs/)
- [PyTorch Documentation](https://pytorch.org/docs/)

### Community

- GitHub: [qwen/realtime-asr](https://github.com/qwen/realtime-asr)
- Issues: [Open an issue](https://github.com/qwen/realtime-asr/issues)
- Slack: [qwen.ai/slack](https://qwen.ai/slack)

## License

MIT License

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md)

## Version

v1.0.0 - Initial Release
