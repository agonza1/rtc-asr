# Realtime ASR Service

Realtime speech recognition service with REST transcription endpoints and a buffered WebSocket streaming protocol.

![Status](https://img.shields.io/badge/status-mvp%20in%20progress-yellow)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

> Benchmark status: the repository includes validated single-node CPU baselines for `faster-whisper` and Compose-backed `qwen-asr`, plus reproducible Compose benchmark paths for Parakeet and Ultravox. Treat pending Parakeet/Ultravox numbers, broader load, GPU, and corpus-level accuracy claims as provisional until their result artifacts are checked in.

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
# default local install keeps the repo's qwen-compatible transformers pin
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

If you want to run `ASR_BACKEND=parakeet` outside Docker Compose, upgrade the local Hugging Face runtime first:

```bash
pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2
```

### Docker

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
# qwen-asr Compose benchmark path
make benchmark-compose-qwen
make benchmark-compose-parakeet
make benchmark-compose-ultravox
```

The Parakeet compose benchmark target overrides the container image to a known-good Hugging Face pair, `transformers==5.10.2` plus `huggingface_hub==1.18.0`, which recognizes NVIDIA's upstream `parakeet_tdt` architecture while leaving the default qwen-compatible local dependency pin untouched. Use the same override command from *Local Python* if you want to run `ASR_BACKEND=parakeet` directly on your workstation.

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
ASR_PARAKEET_MODEL=nvidia/parakeet-tdt-0.6b-v3
ASR_PARAKEET_DTYPE=auto
ASR_ULTRAVOX_MODEL=fixie-ai/ultravox-v0_6-llama-3_1-8b
ASR_ULTRAVOX_DTYPE=auto
ASR_ULTRAVOX_MAX_NEW_TOKENS=128
ASR_ULTRAVOX_PROMPT=Transcribe the spoken audio exactly and return only the transcript.
```

For compatibility with the recovered scaffold, `MODEL_NAME` and `AUDIO_SAMPLE_RATE` are still accepted as aliases for `ASR_MODEL_SIZE` and `SAMPLE_RATE`. If `ASR_DEVICE` is unset but `CUDA_VISIBLE_DEVICES` exposes a GPU, the service now defaults the backend device to `cuda`. Set `ASR_BACKEND=qwen-asr` (or `qwen`) to load the official `qwen-asr` package with `ASR_QWEN_MODEL` such as `Qwen/Qwen3-ASR-1.7B`; `requirements.txt` installs `torch` alongside `qwen-asr` so fresh environments can preload that backend without extra manual steps. Set `ASR_BACKEND=parakeet` to route the same REST and websocket contract through the Hugging Face `transformers` automatic-speech-recognition pipeline using `ASR_PARAKEET_MODEL` and `ASR_PARAKEET_DTYPE`, but upgrade the local Hugging Face runtime first or use `make benchmark-compose-parakeet`. Set `ASR_BACKEND=ultravox` to load the Ultravox speech-in/text-out pipeline with `ASR_ULTRAVOX_MODEL`, `ASR_ULTRAVOX_DTYPE`, `ASR_ULTRAVOX_MAX_NEW_TOKENS`, and `ASR_ULTRAVOX_PROMPT`.

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
