# Troubleshooting Guide

This guide focuses on the failure modes that actually exist in `rtc-asr` today: backend preload/runtime issues, audio contract mismatches, and websocket protocol mistakes.

## Quick Start

```bash
curl http://localhost:8080/health
curl -i http://localhost:8080/ready
curl http://localhost:8080/api/models
docker compose logs -f
pytest tests/test_client.py tests/test_smoke.py -v
```

## Common Issues

### 1. `GET /ready` returns `503`

This means the backend is not usable yet. With `ASR_PRELOAD_MODEL=true`, that usually means startup preload failed; with preload disabled, `/ready` only returns `503` after the first lazy load fails and records a degraded `preload_error`.

Check the payload first:

```bash
curl -i http://localhost:8080/ready
```

Look for `preload_error`, `backend`, and `model`.

Common causes:

- Missing backend dependencies for the selected `ASR_BACKEND`
- Incompatible local Hugging Face runtime for `parakeet`
- Missing model weights or unsupported device/runtime combination

Typical fixes:

```bash
pip install -r requirements.txt
docker compose build --no-cache
docker compose up -d
```

For local `parakeet` runs, upgrade the runtime pair explicitly:

```bash
pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2
```

### 2. `GET /health` is healthy but `model_loaded` is `false`

That is expected when preload is disabled and the backend has not been used yet. In that state `/health` reports `status=loading`, `ready=true`, and `/ready` stays `200` so the first request can trigger the lazy load.

Check:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
```

If you want eager validation at boot, set `ASR_PRELOAD_MODEL=true`. If you want startup to fail immediately on preload errors, also set `ASR_FAIL_FAST=true`.

### 3. Websocket stream closes with an `error` event

The websocket API is strict about event order and payload shape.

Common causes:

- audio before `start`
- `stop` or `cancel` without an active stream
- invalid JSON event payloads
- invalid base64 in JSON `audio` messages
- stream buffer growth beyond `STREAM_MAX_BUFFER_BYTES`

Recommended client behavior:

1. Send `start` first.
2. Prefer binary PCM16 websocket frames.
3. Keep chunk size around `50` to `200` ms.
4. Send `stop` once the utterance is complete.

### 4. REST transcription returns `400`

The HTTP route expects base64 audio bytes in `audio_data` or `audio`.

Example:

```bash
curl -X POST http://localhost:8080/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio_data":"BASE64_AUDIO","language":"en","sample_rate":16000}'
```

If you already have PCM bytes in a live RTC pipeline, use the websocket route instead of wrapping every chunk in JSON.

### 5. Parakeet backend fails locally but works in Compose benchmarks

That usually means your workstation still has the repo's default Qwen-compatible `transformers` pin installed.

The local Parakeet adapter requires a newer Hugging Face runtime than the default repo pin. Either:

- upgrade the local runtime pair, or
- use `make benchmark-compose-parakeet`, which applies the known-good container override for that backend.

### 6. Transcripts are delayed or partials feel stale

Check these settings in the `start` event:

```json
{
  "partial_interval_chunks": 1,
  "partial_window_seconds": 2.0,
  "max_buffer_seconds": 30.0
}
```

Lower `partial_interval_chunks` for more frequent updates, and keep your transport chunk cadence steady.

### 7. Need to verify the exact backend capabilities exposed to a client

Use:

```bash
curl http://localhost:8080/api/models
```

That response includes the active backend, model, audio assumptions, and websocket streaming capability metadata.

## Related Docs

- [README](../README.md)
- [API Reference](./api-reference.md)
- [Pipecat Integration](./pipecat-integration.md)
- [LiveKit Integration](./livekit-integration.md)
