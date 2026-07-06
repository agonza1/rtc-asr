# API Reference

## Base URL

```
http://localhost:8080
```

Supported backends: `faster-whisper`, `qwen-asr`, `parakeet`, `parakeet-mlx`, `parakeet-nemo`, experimental `voxtral`, and experimental `voxtral-mlx`. Aliases `whisper`, `qwen`, `qwen3-asr`, `parakeet-asr`, `parakeet-ctc`, `voxtral-realtime`, `voxtral-mini`, `voxtral-mini-4b`, `voxtral-realtime-mlx`, `voxtral-mini-mlx`, and `voxtral-mini-4b-mlx` resolve to the matching canonical backends. The HTTP and websocket response shapes stay stable across backends, but backend-specific metadata can vary.

## Health Check

```http
GET /health
```

Example response:

```json
{
  "status": "loading",
  "service": "realtime-asr",
  "backend": "faster-whisper",
  "model": "small.en",
  "ready": true,
  "model_loaded": false,
  "preload_enabled": false,
  "preload_error": null
}
```

## Readiness Check

```http
GET /ready
```

Example response:

```json
{
  "status": "ready",
  "service": "realtime-asr",
  "backend": "faster-whisper",
  "model": "small.en",
  "ready": true,
  "model_loaded": true,
  "preload_enabled": true,
  "preload_error": null
}
```

## List Models

```http
GET /api/models
```

Example response:

```json
{
  "backend": "faster-whisper",
  "model": "small.en",
  "sample_rate": 16000,
  "status": "ready",
  "ready": true,
  "preload_enabled": true,
  "preload_error": null,
  "streaming": {
    "transport": "websocket",
    "path": "/ws/stream",
    "reusable_connection": true,
    "message_types": ["start", "audio", "stop", "cancel"],
    "audio_frame_formats": ["json-base64", "binary"],
    "event_types": ["ready", "partial", "final", "canceled", "error"]
  },
  "audio": {
    "target_sample_rate": 16000,
    "channels": 1,
    "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"]
  },
  "models": [
    {
      "id": "small.en",
      "backend": "faster-whisper",
      "model": "small.en",
      "loaded": true,
      "streaming": {
        "transport": "websocket",
        "path": "/ws/stream",
        "reusable_connection": true,
        "message_types": ["start", "audio", "stop", "cancel"],
        "audio_frame_formats": ["json-base64", "binary"],
        "event_types": ["ready", "partial", "final", "canceled", "error"]
      },
      "audio": {
        "target_sample_rate": 16000,
        "channels": 1,
        "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"]
      },
      "capabilities": {
        "backend": "faster-whisper",
        "model": "small.en",
        "loaded": true,
        "streaming": {
          "transport": "websocket",
          "path": "/ws/stream",
          "reusable_connection": true,
          "message_types": ["start", "audio", "stop", "cancel"],
          "audio_frame_formats": ["json-base64", "binary"],
          "event_types": ["ready", "partial", "final", "canceled", "error"]
        },
        "audio": {
          "target_sample_rate": 16000,
          "channels": 1,
          "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"]
        }
      }
    }
  ],
  "capabilities": {
    "backend": "faster-whisper",
    "model": "small.en",
    "loaded": true,
    "streaming": {
      "transport": "websocket",
      "path": "/ws/stream",
      "reusable_connection": true,
      "message_types": ["start", "audio", "stop", "cancel"],
      "audio_frame_formats": ["json-base64", "binary"],
      "event_types": ["ready", "partial", "final", "canceled", "error"]
    },
    "audio": {
      "target_sample_rate": 16000,
      "channels": 1,
      "accepted_formats": ["wav", "pcm16", "other formats supported by soundfile when installed"]
    }
  }
}
```

Capability metadata changes by backend. The top-level `streaming` and `audio` keys provide the active transport contract clients can read without digging into nested capability blobs, while backend-specific details remain under `capabilities`. For example, Qwen exposes `dtype`, `device_map`, and generation settings, while Parakeet variants expose implementation-specific runtime fields. Voxtral also exposes `model_card`, `runtime_aliases`, `attn_implementation`, `max_new_tokens`, and `realtime_profile` so clients can discover the Mini 4B realtime alias without hard-coding issue notes.

## Synchronous Transcription

```http
POST /api/transcribe
Content-Type: application/json
```

Request body:

```json
{
  "audio_data": "base64_encoded_audio_data",
  "language": "en",
  "sample_rate": 16000
}
```

Example response:

```json
{
  "text": "hello world",
  "language": "en",
  "duration_ms": 2500,
  "backend": "faster-whisper",
  "model": "small.en",
  "language_probability": 0.98
}
```

`audio` is accepted as an alias for `audio_data`.

## File Transcription

```http
POST /api/transcribe/file
Content-Type: multipart/form-data
```

Form fields:

- `file`: required audio file
- `language`: optional language code
- `sample_rate`: optional sample rate override for raw PCM payloads

Example response:

```json
{
  "filename": "recording.wav",
  "transcription": {
    "text": "hello world",
    "language": "en",
    "duration_ms": 2500,
    "backend": "faster-whisper",
    "model": "small.en"
  }
}
```

## WebSocket Streaming

```http
WebSocket /ws/stream
```

Client event sequence:

The client may send audio either as JSON `audio` events with base64 payloads or as raw binary websocket frames after `start`. Binary frames are the preferred transport for RTC clients because they avoid base64 overhead.

1. Start the stream:

```json
{
  "type": "start",
  "language": "en",
  "sample_rate": 16000,
  "partial_interval_chunks": 1
}
```

2. Send one or more audio chunks as JSON base64 events or raw binary websocket frames after `start`:

```json
{
  "type": "audio",
  "audio_data": "base64_encoded_audio_chunk"
}
```

Or send the chunk bytes directly as a binary websocket frame once the stream is ready.

3. Cancel the stream early if needed:

```json
{
  "type": "cancel"
}
```

4. Finish the stream when you want a final transcript:

```json
{
  "type": "stop"
}
```

Server events:

```json
{
  "type": "ready",
  "stream_id": 1,
  "backend": "faster-whisper",
  "model": "small.en",
  "language": "en",
  "sample_rate": 16000,
  "partial_interval_chunks": 1,
  "max_buffer_bytes": 262144
}
```

```json
{
  "type": "partial",
  "is_final": false,
  "chunks_received": 1,
  "buffered_bytes": 1024,
  "text": "hello",
  "language": "en",
  "duration_ms": 320,
  "backend": "faster-whisper",
  "model": "small.en"
}
```

```json
{
  "type": "final",
  "is_final": true,
  "chunks_received": 2,
  "buffered_bytes": 2048,
  "text": "hello world",
  "language": "en",
  "duration_ms": 640,
  "backend": "faster-whisper",
  "model": "small.en"
}
```

Notes:

- Partial events are emitted against the buffered audio accumulated for the active stream on that connection.
- After a `final` event, the websocket remains open and can accept a new `start` event for the next stream.
- The current HTTP `POST /api/stream` route is still not implemented; use `/ws/stream` for streaming.
- Sending `cancel` returns a `canceled` event and clears the active stream without running a final transcription.
- Invalid event ordering or invalid base64 audio results in a websocket `error` event followed by connection close.
- `sample_rate` in the `start` event should match the raw PCM cadence you are sending.
- `partial_window_seconds` trims the audio window used for partial refreshes.
- `max_buffer_seconds` lets the client cap final-buffer growth below the server-wide `STREAM_MAX_BUFFER_BYTES` ceiling.

## Errors

HTTP errors follow FastAPI's default schema:

```json
{
  "detail": "audio_data must be valid base64-encoded audio bytes"
}
```

Common runtime errors:

- `503` when the configured backend is unavailable or failed preload
- `400` when the audio payload or stream parameters are invalid
- websocket `error` events with close code `1003`, `1009`, or `1011` for protocol violations, buffer overflow, or backend failures
