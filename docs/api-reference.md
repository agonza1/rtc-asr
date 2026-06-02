# API Reference

## Overview

The Realtime ASR Service exposes multiple endpoints for speech recognition:

- **REST API**: For synchronous transcription requests
- **WebSocket API**: For real-time streaming
- **Streaming HTTP**: For partial results

## Base URL

```
http://localhost:8080
```

## Endpoints

### Health Check

```http
GET /health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "realtime-asr"
}
```

---

### List Models

```http
GET /api/models
```

**Response:**
```json
{
  "models": ["Qwen3-ASR-1.7B"],
  "languages": ["en", "es", "fr", "de", "zh", "ja", "ko", "it"],
  "sample_rate": 16000,
  "latency_ms": "<500ms"
}
```

---

### Synchronous Transcription

```http
POST /api/transcribe
Content-Type: application/json
```

**Request:**
```json
{
  "audio": "base64_encoded_audio_data",
  "language": "en",
  "sample_rate": 16000,
  "stream": false
}
```

**Response:**
```json
{
  "text": "Hello world, how are you today?",
  "language": "en",
  "duration_ms": 2500,
  "confidence": 0.95,
  "chunks": [
    {
      "offset": 0,
      "text": "Hello world"
    },
    {
      "offset": 1500,
      "text": ", how are you"
    },
    {
      "offset": 2400,
      "text": " today?"
    }
  ]
}
```

---

### File Transcription

```http
POST /api/transcribe/file
Content-Type: multipart/form-data
```

**Request:**
- `file`: Audio file (WAV, FLAC, MP3)
- `language`: Optional language code
- `sample_rate`: Optional sample rate

**Response:**
```json
{
  "filename": "recording.wav",
  "text": "This is a transcription of the audio file.",
  "language": "en",
  "duration_ms": 5000
}
```

---

### Streaming Transcription

```http
POST /api/stream
Content-Type: application/json
```

**Request:**
```json
{
  "audio": "base64_encoded_audio_chunk",
  "chunk_index": 0,
  "language": "en"
}
```

**Response:**
```json
{
  "chunk": 0,
  "partial_text": "Hello",
  "final_text": "Hello",
  "confidence": 0.92
}
```

---

### WebSocket Streaming

```http
WebSocket /ws/stream
```

**Protocol:**

1. **Connect:**
   ```json
   {
     "type": "connect"
   }
   ```

2. **Receive Welcome:**
   ```json
   {
     "type": "welcome",
     "message": "Connected to ASR stream",
     "status": "ready"
   }
   ```

3. **Send Audio Chunk:**
   ```json
   {
     "type": "audio",
     "audio": "base64_encoded_audio",
     "language": "en"
   }
   ```

4. **Receive Partial Result:**
   ```json
   {
     "type": "partial",
     "chunk": 0,
     "text": "Hello",
     "confidence": 0.92
   }
   ```

5. **Flush (Optional):**
   ```json
   {
     "type": "flush"
   }
   ```

6. **Receive Final Result:**
   ```json
   {
     "type": "complete",
     "text": "Hello, how are you today?",
     "duration_ms": 3500
   }
   ```

---

### WebSocket Events

| Event Type | Description |
|------------|-------------|
| `welcome` | Connection established |
| `partial` | Partial transcription result |
| `complete` | Final transcription result |
| `flush` | Request to flush buffer |
| `error` | Error occurred |

---

### Error Responses

**400 Bad Request:**
```json
{
  "detail": "Invalid audio format"
}
```

**404 Not Found:**
```json
{
  "detail": "Endpoint not found"
}
```

**500 Internal Server Error:**
```json
{
  "detail": "Model inference failed"
}
```

**503 Service Unavailable:**
```json
{
  "detail": "Service not initialized"
}
```

---

### Rate Limiting

Requests are limited to prevent abuse:

- **Rate**: 100 requests per minute
- **Headers**:
  - `X-RateLimit-Limit`: 100
  - `X-RateLimit-Remaining`: 99
  - `X-RateLimit-Reset`: Unix timestamp

**429 Too Many Requests:**
```json
{
  "detail": "Rate limit exceeded. Please retry after 60 seconds.",
  "retry_after": 60
}
```

---

### Authentication (Optional)

API keys can be configured via environment variable:

```bash
export ASR_API_KEY=your-api-key
export ASR_API_SECRET=your-api-secret
```

**Headers:**
```
Authorization: Bearer {api-key}
X-API-Key: {api-key}
```

**Response:**
```json
{
  "text": "...",
  "authenticated": true
}
```

---

### CORS Configuration

By default, CORS is enabled for all origins:

```javascript
{
  "allow_origins": ["*"],
  "allow_methods": ["*"],
  "allow_headers": ["*"]
}
```

To restrict origins, configure in `.env`:

```env
CORS_ORIGINS=http://localhost:3000,http://example.com
```

---

### Request Timing

Response headers include timing information:

```
X-Request-ID: abc123
X-Processing-Time: 145ms
X-Model: Qwen3-ASR-1.7B
```

---

### Metrics Endpoint

```http
GET /api/metrics
```

**Response:**
```json
{
  "requests_total": 1523,
  "requests_by_language": {
    "en": 1200,
    "es": 200,
    "fr": 123
  },
  "latency_p50_ms": 120,
  "latency_p95_ms": 450,
  "latency_p99_ms": 780,
  "errors_total": 12,
  "model": "Qwen3-ASR-1.7B"
}
```

---

### Usage Examples

#### Python Example

```python
import requests
import base64

# Synchronous transcription
def transcribe(audio_data, language="en"):
    url = "http://localhost:8080/api/transcribe"
    headers = {
        "Content-Type": "application/json"
    }
    payload = {
        "audio": base64.b64encode(audio_data).decode('utf-8'),
        "language": language
    }
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

# Streaming transcription
def stream_transcribe(audio_chunks):
    url = "http://localhost:8080/api/stream"
    
    for chunk in audio_chunks:
        payload = {
            "audio": base64.b64encode(chunk).decode('utf-8'),
            "chunk_index": len(audio_chunks)
        }
        response = requests.post(url, json=payload)
        yield response.json()
```

#### JavaScript Example

```javascript
const ASR_API = 'http://localhost:8080';

async function transcribe(audioData, language = 'en') {
  const response = await fetch(`${ASR_API}/api/transcribe`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      audio: Buffer.from(audioData).toString('base64'),
      language
    })
  });
  
  return await response.json();
}

async function streamTranscribe(audioStream) {
  const ws = new WebSocket(`${ASR_API}/ws/stream`);
  
  ws.onopen = () => {
    ws.send(JSON.stringify({ type: 'connect' }));
  };
  
  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    
    if (data.type === 'partial') {
      console.log('Partial:', data.text);
    }
    
    if (data.type === 'complete') {
      console.log('Complete:', data.text);
    }
  };
  
  // Send audio chunks...
  
  return ws;
}
```

---

## Next Steps

- See [Pipecat Integration](./pipecat-integration.md)
- See [LiveKit Integration](./livekit-integration.md)
- See [Performance Benchmarks](./benchmarks.md)
- See [Troubleshooting](./troubleshooting.md)
