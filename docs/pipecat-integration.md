# Pipecat Integration Guide

This guide shows how to integrate the Realtime ASR Service with Pipecat for real-time speech recognition.

## Overview

Pipecat is a Python framework for building voice AI applications. This integration allows you to use Qwen3-ASR-1.7B as the STT component in your Pipecat applications.

## Setup

### 1. Install Dependencies

```bash
pip install pipecat-sdk aiortc
```

### 2. Configure ASR Service

Make sure the ASR service is running:

```bash
docker compose up -d
```

### 3. Create STT Channel

```python
from pipecat.stt import STT
from pipecat.pipeline.processor import SyncProcessor
from pipecat.frames.audio import AudioFrame
from pipecat.frames.text import TextFrame
import base64
import json

class QwenASRProcessor(SyncProcessor):
    """
    Pipecat processor for Qwen3-ASR-1.7B
    """
    
    def __init__(self, asr_url="http://localhost:8080"):
        self.asr_url = asr_url
        self.client = None  # Initialize HTTP client
        
    async def on_start(self) -> bool:
        """Initialize ASR client."""
        self.client = self.create_http_client()
        return True
    
    def create_http_client(self):
        """Create HTTP client for ASR requests."""
        import requests
        return requests.Session()
    
    async def process(self, payload) -> list:
        """
        Process audio frames for transcription.
        
        Args:
            payload: List of AudioFrame objects
        
        Returns:
            List of TextFrame objects
        """
        if not payload:
            return []
        
        # Collect audio frames
        audio_frames = payload
        total_samples = sum(frame.samples for frame in audio_frames)
        
        if total_samples < 16000:  # Minimum 1 second of audio
            return payload
        
        # In production, combine frames and send to ASR
        # This is a simplified example
        return payload
    
    def on_destroy(self):
        """Cleanup resources."""
        if self.client:
            self.client.close()
```

### 4. Add to Pipeline

```python
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.player import VolumePlayer
from pipecat.pipeline recorder import PipelineRecorder

# Create STT channel
stt_channel = STT(
    language="en",
    model="whisper",  # Or use your Qwen model
    device="cuda"
)

# Create TTS channel
tts_channel = TTS(
    engine="edge-tts",
    voice="en-US-JennyNeural"
)

# Create pipeline
pipeline = Pipeline(
    stt_channel,
    tts_channel
)
```

## Streaming Integration

For low-latency streaming, use WebSockets:

```python
import websockets

class WebSocketASRProcessor(SyncProcessor):
    def __init__(self, ws_url="ws://localhost:8080/ws/stream"):
        self.ws_url = ws_url
        self.websocket = None
        self.buffer = bytearray()
    
    async def on_start(self) -> bool:
        """Connect to WebSocket."""
        self.websocket = await websockets.connect(self.ws_url)
        await self.websocket.send(json.dumps({"type": "connect"}))
        return True
    
    async def process(self, payload) -> list:
        """Process audio frames."""
        if not payload:
            return payload
        
        # Collect audio and send to WebSocket
        for frame in payload:
            # Convert audio to base64 and send
            audio_data = base64.b64encode(frame.data).decode('utf-8')
            message = json.dumps({
                "type": "audio",
                "audio": audio_data,
                "language": "en"
            })
            await self.websocket.send(message)
        
        return payload
    
    def on_destroy(self):
        """Close WebSocket connection."""
        if self.websocket:
            self.websocket.close()
```

## Advanced Configuration

### Using with Config Files

Create `config/pipecat.asr.json`:

```json
{
  "asr_service": {
    "url": "http://localhost:8080",
    "language": "en",
    "sample_rate": 16000,
    "fallback": true
  },
  "buffering": {
    "chunk_size_ms": 50,
    "max_latency_ms": 200
  },
  "transcription": {
    "max_length": 500,
    "min_confidence": 0.6
  }
}
```

### Load Configuration

```python
import json

with open("config/pipecat.asr.json") as f:
    config = json.load(f)

asr_config = STTChannelConfig(
    language=config["asr_service"]["language"],
    sample_rate=config["asr_service"]["sample_rate"],
    fallback=config["asr_service"]["fallback"]
)
```

## Error Handling

```python
class RobustASRProcessor(SyncProcessor):
    def __init__(self, asr_url="http://localhost:8080"):
        self.asr_url = asr_url
        self.retry_count = 0
        self.max_retries = 3
    
    async def process(self, payload) -> list:
        try:
            result = await self.transcribe_audio(payload)
            return result
        except Exception as e:
            self.retry_count += 1
            
            if self.retry_count <= self.max_retries:
                await asyncio.sleep(2 ** self.retry_count)
                return self.process(payload)
            
            # Return payload as-is on failure
            return payload
    
    async def transcribe_audio(self, payload):
        """Transcribe audio with error handling."""
        # Implementation...
        pass
```

## Performance Tips

1. **Use WebSocket** for streaming instead of REST API
2. **Buffer 100-200ms** of audio before sending
3. **Process in parallel** if using multiple microphones
4. **Monitor latency** with `/api/metrics` endpoint
5. **Use GPU** for faster inference

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Connection timeout | Check ASR service is running |
| Audio format error | Ensure 16kHz mono audio |
| High latency | Use WebSocket streaming |
| Language detection errors | Set explicit `language` parameter |

### Debug Mode

Enable debug logging:

```bash
docker compose down
LOG_LEVEL=debug docker compose up -d
```

## Next Steps

- See [LiveKit integration](./livekit-integration.md)
- See [API documentation](./api-reference.md)
- See [Performance benchmarks](./benchmarks.md)
