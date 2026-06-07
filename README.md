# Realtime ASR Service

Realtime speech recognition service with REST transcription endpoints and a buffered WebSocket streaming protocol.

![Status](https://img.shields.io/badge/status-mvp%20in%20progress-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Benchmark status: latency, throughput, and accuracy figures in this repository are not yet validated. Treat performance-related material as provisional until the real ASR path and benchmark harness are complete.

## Current Scope

- `GET /health` reports liveness and active backend metadata
- `GET /ready` reports preload readiness and startup degradation state
- `POST /api/transcribe` accepts base64 audio payloads and routes them through the configured transcriber
- `POST /api/transcribe/file` accepts uploaded audio files
- `GET /api/models` reports the active backend/model configuration
- `ws://.../ws/stream` accepts `start`, `audio`, and `stop` events, plus raw binary audio frames after `start`, and emits buffered `partial`/`final` transcript events
- smoke tests inject a fake transcriber, so local verification does not need to download a Whisper or Qwen model

## Quick Start

### Local Python

```bash
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

### Docker

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
```

## REST API

```bash
# Health check
curl http://localhost:8080/health

# Readiness check
curl http://localhost:8080/ready

# List models
curl http://localhost:8080/api/models

# Transcribe audio
curl -X POST http://localhost:8080/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio": "base64_audio_data", "language": "en", "sample_rate": 16000}'
```

## WebSocket Streaming

Connect to `ws://localhost:8080/ws/stream` and send JSON events:

```json
{ "type": "start", "language": "en", "sample_rate": 16000 }
```

```json
{ "type": "audio", "audio_data": "base64_encoded_pcm_or_audio_chunk" }
```

```json
{ "type": "stop" }
```

The server replies with:

```json
{ "type": "ready", "stream_id": 1, "backend": "faster-whisper", "model": "small.en" }
```

```json
{ "type": "partial", "stream_id": 1, "text": "hello", "chunks_received": 1, "is_final": false }
```

```json
{ "type": "final", "stream_id": 1, "text": "hello world", "chunks_received": 2, "is_final": true }
```

After a `final` event, the connection stays open so the client can send another `start` event for the next utterance without reconnecting.

## Configuration

Preferred environment variables:

```env
HOST=0.0.0.0
PORT=8080
SAMPLE_RATE=16000
ASR_BACKEND=faster-whisper
ASR_MODEL_SIZE=small.en
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_VAD_FILTER=true
ASR_PRELOAD_MODEL=true
ASR_FAIL_FAST=false
ASR_QWEN_MODEL=Qwen/Qwen3-ASR-0.6B
ASR_QWEN_DTYPE=auto
ASR_QWEN_MAX_NEW_TOKENS=256
ASR_QWEN_MAX_INFERENCE_BATCH_SIZE=1
```

For compatibility with the recovered scaffold, `MODEL_NAME` and `AUDIO_SAMPLE_RATE` are still accepted as aliases for `ASR_MODEL_SIZE` and `SAMPLE_RATE`. If `ASR_DEVICE` is unset but `CUDA_VISIBLE_DEVICES` exposes a GPU, the service now defaults the backend device to `cuda`. Set `ASR_BACKEND=qwen-asr` (or `qwen`) to load the official `qwen-asr` package with `ASR_QWEN_MODEL` such as `Qwen/Qwen3-ASR-1.7B`; the service keeps the same REST and websocket contract while swapping providers underneath.

## Verification

```bash
python -m compileall src tests
pytest tests/test_model_loader.py tests/test_smoke.py -v
```

## Documentation

- [API Reference](./docs/api-reference.md)
- [Pipecat Integration](./docs/pipecat-integration.md)
- [LiveKit Integration](./docs/livekit-integration.md)
- [Benchmarks](./docs/benchmarks.md)
- [Troubleshooting](./docs/troubleshooting.md)
