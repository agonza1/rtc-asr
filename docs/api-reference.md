# API Reference

## Base URL

```
http://localhost:8080
```

Supported backends: `faster-whisper`, `qwen-asr`, `parakeet`, `parakeet-nemo`, and `ultravox`. Aliases `whisper`, `qwen`, and `qwen3-asr` resolve to the matching canonical backends. The HTTP and websocket response shapes stay stable across backends, but backend-specific metadata can vary.

## Health Check

```http
GET /health
```

Example response:

```json
{
  "status": "healthy",
  "service": "realtime-asr",
  "backend": "faster-whisper",
  "model": "small.en",
  "model_loaded": false
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
  "model_loaded": true,
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
  "models": ["small.en"],
  "backend": "faster-whisper",
  "sample_rate": 16000,
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
    }
  }
}
```

Capability metadata changes by backend. For example, Qwen exposes `dtype`, `device_map`, and generation settings, while Parakeet and Ultravox expose their own implementation-specific fields.

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
