# API Reference

## Base URL

```
http://localhost:8080
```

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
      "reusable_connection": true
    }
  }
}
```

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

3. Finish the stream:

```json
{
  "type": "stop"
}
```

Server events:

```json
{
  "type": "ready",
  "backend": "faster-whisper",
  "model": "small.en",
  "language": "en",
  "sample_rate": 16000,
  "partial_interval_chunks": 1
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
- Invalid event ordering or invalid base64 audio results in a websocket `error` event followed by connection close.

## Errors

HTTP errors follow FastAPI's default schema:

```json
{
  "detail": "audio_data must be valid base64-encoded audio bytes"
}
```
