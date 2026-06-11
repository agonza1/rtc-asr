# rtc-asr

`rtc-asr` is a lightweight FastAPI service for low-latency transcription over REST and WebSockets. The core contract stays stable while you swap ASR backends underneath it, which makes it useful as a thin speech layer in RTC stacks, voice agents, and local benchmarking.

The service currently supports `faster-whisper`, `qwen-asr`, `parakeet`, and `parakeet-nemo` backends behind the same API surface.

> Benchmark status: the repo includes checked-in latency baselines for validated local and Compose-backed runs. Treat untracked GPU, load, and accuracy claims as provisional until the corresponding artifacts are committed.

## What It Ships Today

- `GET /health` for liveness plus active backend/model metadata
- `GET /ready` for preload status and degraded startup reporting
- `GET /api/models` for backend/model capability metadata that RTC clients can inspect
- `POST /api/transcribe` for one-shot base64 audio requests
- `POST /api/transcribe/file` for uploaded file transcription
- `ws://.../ws/stream` for buffered streaming transcription with `ready`, `partial`, `final`, `canceled`, and `error` events
- Shared client helpers in `src/rtc_client.py` and `src/streaming.py`

## Quick Start

### Local Python

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
```

The default local dependency set is pinned for the repo's `qwen-asr` stack. If you want to run the Hugging Face Parakeet path outside Docker Compose, upgrade that local runtime first:

```bash
pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2
```

### Docker Compose

```bash
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
```

## Operator Defaults

```env
HOST=0.0.0.0
PORT=8080
SAMPLE_RATE=16000
STREAM_MAX_BUFFER_BYTES=1048576
ASR_BACKEND=faster-whisper
ASR_MODEL_SIZE=small.en
ASR_DEVICE=cpu
ASR_PRELOAD_MODEL=true
ASR_FAIL_FAST=false
```

Backend-specific variables are available for Qwen, Parakeet, and NeMo Parakeet. See [API Reference](./docs/api-reference.md) and [Troubleshooting](./docs/troubleshooting.md) for backend-specific behavior.

If `ASR_DEVICE` is unset but `CUDA_VISIBLE_DEVICES` exposes a GPU, the service defaults to `cuda`. Legacy aliases `MODEL_NAME` and `AUDIO_SAMPLE_RATE` are still accepted for compatibility.

## Streaming Contract

The realtime path is the main integration surface.

1. Open `ws://localhost:8080/ws/stream`.
2. Send a `start` event with `language`, `sample_rate`, and optional partial/buffer controls.
3. Send audio as either JSON `audio` events with base64 payloads or raw binary websocket frames.
4. Receive `partial` events on the configured cadence.
5. Send `stop` to receive the final transcript, or `cancel` to discard the buffered utterance.

Example start event:

```json
{
  "type": "start",
  "language": "en",
  "sample_rate": 16000,
  "partial_interval_chunks": 1,
  "partial_window_seconds": 2.0,
  "max_buffer_seconds": 30.0
}
```

Example ready event:

```json
{
  "type": "ready",
  "stream_id": 1,
  "backend": "faster-whisper",
  "model": "small.en",
  "language": "en",
  "sample_rate": 16000,
  "partial_interval_chunks": 1,
  "max_buffer_bytes": 1048576
}
```

After a `final` event, the socket stays open so the client can start the next utterance without reconnecting.

## Audio Assumptions

- Preferred transport is mono PCM16 chunks over binary websocket frames.
- JSON base64 audio events are still supported for simpler clients.
- A `sample_rate` must be supplied in the `start` event for raw PCM streams.
- `50` to `200` ms chunks are the best starting point for low-latency RTC clients.
- The service decodes and resamples once through the shared audio processor before handing audio to the configured backend.
- `partial_window_seconds` and `max_buffer_seconds` let clients cap how much buffered audio feeds partials and finals.

## Verification

```bash
python -m compileall src tests
pytest tests/test_client.py tests/test_model_loader.py tests/test_smoke.py -v
curl http://localhost:8080/health
curl -f http://localhost:8080/ready
curl http://localhost:8080/api/models
```

## Benchmarks

Use the checked-in benchmark flow when you need reproducible latency artifacts:

```bash
make benchmark-faster-whisper-matrix
make benchmark-qwen-mps
make benchmark-compose-qwen
make benchmark-compose-parakeet
make benchmark-compose-parakeet-nemo
make benchmark-site-check
```

## Documentation

- [Docs Index](./docs/index.md)
- [API Reference](./docs/api-reference.md)
- [Pipecat Integration](./docs/pipecat-integration.md)
- [LiveKit Integration](./docs/livekit-integration.md)
- [Benchmarks](./docs/benchmarks.md)
- [Troubleshooting](./docs/troubleshooting.md)
