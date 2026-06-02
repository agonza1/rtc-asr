# LiveKit Integration Guide

This guide shows how to integrate the Realtime ASR Service with LiveKit for real-time speech recognition.

## Overview

LiveKit is a WebRTC SDK for building real-time communication applications. This integration allows you to use Qwen3-ASR-1.7B as the STT component in your LiveKit rooms.

## Setup

### 1. Install LiveKit SDK

```bash
pip install livekit-agents livekit-plugins-whisper
```

### 2. Configure ASR Service

Make sure the ASR service is running:

```bash
docker compose up -d
```

### 3. Create Custom STT Plugin

Create a custom STT plugin for LiveKit:

```python
# livekit_asr.py
from livekit.agents import RTTNotifier, PluginBase
from livekit.plugins import stt as default_stt
from livekit import rtc
import aiohttp
import json
import base64

class QwenASRPlugin(PluginBase):
    """
    Custom LiveKit plugin using Qwen3-ASR-1.7B for speech recognition.
    """
    
    def __init__(self, asr_url: str = "http://localhost:8080", 
                 language: str = "en",
                 sample_rate: int = 16000):
        super().__init__()
        self.asr_url = asr_url
        self.language = language
        self.sample_rate = sample_rate
        self.client = None
    
    async def start(self):
        """Initialize ASR client."""
        self.client = aiohttp.ClientSession()
        await self._warmup_model()
    
    async def _warmup_model(self):
        """Warm up the ASR model."""
        try:
            # Send a warmup request
            async with self.client.post(
                f"{self.asr_url}/api/transcribe",
                json={"audio": "", "language": self.language}
            ) as response:
                response.raise_for_status()
        except Exception as e:
            print(f"Warmup failed: {e}")
    
    async def stop(self):
        """Cleanup resources."""
        if self.client:
            await self.client.close()
    
    async def transcribe(self, audio: rtc.AudioFrame) -> str:
        """
        Transcribe a single audio frame.
        
        Args:
            audio: LiveKit AudioFrame
        
        Returns:
            Transcribed text
        """
        # Convert AudioFrame to base64
        audio_bytes = audio.data
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')
        
        # Send to ASR service
        try:
            async with self.client.post(
                f"{self.asr_url}/api/stream",
                json={
                    "audio": audio_b64,
                    "chunk_index": getattr(self, '_chunk_index', 0)
                }
            ) as response:
                result = await response.json()
                self._chunk_index += 1
                return result.get("partial_text", "")
        except Exception as e:
            print(f"Transcription error: {e}")
            return ""
    
    async def transcribe_stream(self, audio_stream):
        """
        Stream audio for continuous transcription.
        
        Args:
            audio_stream: Async iterator of AudioFrame
        
        Yields:
            Transcription text
        """
        chunk_index = 0
        
        async for frame in audio_stream:
            # Process frame
            text = await self.transcribe(frame)
            
            if text:
                yield text
            
            # Send flush every few seconds
            if chunk_index > 0 and chunk_index % 10 == 0:
                await self._flush_buffer()
    
    async def _flush_buffer(self):
        """Flush buffered audio."""
        try:
            async with self.client.post(
                f"{self.asr_url}/api/flush"
            ) as response:
                result = await response.json()
                print(f"Flushed: {result.get('text', '')}")
        except Exception as e:
            print(f"Flush error: {e}")
```

### 4. Create LiveKit Agent

```python
# agent.py
from livekit.agents import Agent, RTTMSTranscription
from livekit.agents.metrics import AgentMetrics
import asyncio

class QwenASRAgent(Agent):
    """
    LiveKit agent with Qwen3-ASR-1.7B for STT.
    """
    
    def __init__(self):
        super().__init__()
        self.asr_plugin = QwenASRPlugin(
            asr_url="http://localhost:8080",
            language="en"
        )
        self._rttm = RTTMSTranscription()
    
    async def on_join(self):
        """Connect to ASR service."""
        await self.asr_plugin.start()
        await self._rttm.connect()
    
    async def on_leave(self):
        """Cleanup."""
        await self.asr_plugin.stop()
        await self._rttm.disconnect()
    
    async def transcribe_audio(self, audio_frame):
        """Transcribe audio frame."""
        text = await self.asr_plugin.transcribe(audio_frame)
        await self._rttm.add_result(text)
        return text
    
    async def handle_input(self, participant, track, frame):
        """Handle incoming audio track."""
        # Process audio frames
        async for text in self.asr_plugin.transcribe_stream(frame):
            await self._rttm.add_result(text)
        
        # Cleanup
        await self.asr_plugin.stop()
```

### 5. Run the Agent

```python
# main.py
from livekit import rt
from livekit.agents import cli

async def main():
    rtc = await rt.create_room()
    agent = QwenASRAgent()
    
    await rtc.join(as_agent=agent)
    
    # Add audio tracks
    async for participant, track in rtc.participants():
        if track.kind == rtc.TrackKind.AUDIO:
            await participant.replace_local_track(track)

if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration

Create `config/livekit.asr.yaml`:

```yaml
asr:
  url: http://localhost:8080
  language: en
  sample_rate: 16000
  chunk_size: 1024
  max_latency_ms: 500
  fallback: true

livekit:
  api_key: ${LIVEKIT_API_KEY}
  api_secret: ${LIVEKIT_API_SECRET}
  ws_url: wss://your-livekit-server

logging:
  level: info
  format: json

metrics:
  enabled: true
  port: 9090
```

## Streaming Configuration

For low-latency streaming:

```python
# streaming_config.py
import aiohttp
import asyncio

class StreamingConfig:
    def __init__(self):
        self.chunk_size = 1024  # 62.5ms at 16kHz
        self.max_latency = 500  # ms
        self.buffer_size = 2  # chunks
        self.ws_url = "ws://localhost:8080/ws/stream"
        self.http_url = "http://localhost:8080"
    
    async def stream_transcribe(self, audio_stream):
        """Stream transcription."""
        async with aiohttp.ClientSession() as session:
            async for frame in audio_stream:
                # Convert to base64
                audio_b64 = base64.b64encode(frame.data).decode('utf-8')
                
                # Send chunk
                async with session.post(
                    f"{self.http_url}/api/stream",
                    json={
                        "audio": audio_b64,
                        "chunk_index": self._chunk_index
                    }
                ) as response:
                    result = await response.json()
                    yield result.get("partial_text", "")
                
                self._chunk_index += 1
```

## Error Handling

```python
class RobustASRPlugin(QwenASRPlugin):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.retry_count = 0
        self.max_retries = 3
    
    async def transcribe(self, audio):
        try:
            return await super().transcribe(audio)
        except Exception as e:
            self.retry_count += 1
            
            if self.retry_count <= self.max_retries:
                await asyncio.sleep(2 ** self.retry_count)
                return await self.transcribe(audio)
            
            # Fallback to default STT
            from livekit.plugins import stt
            default_stt_plugin = stt.create_stt_plugin()
            return await default_stt_plugin.transcribe(audio)
```

## Performance Optimization

### 1. Use GPU

```bash
docker run --gpus all realtime-asr:latest
```

### 2. Enable batching

```python
# In your plugin
self.batch_size = 4  # Process 4 frames at once
```

### 3. Optimize WebSocket

```python
# Increase WebSocket buffer size
self.websocket_buffer_size = 64 * 1024  # 64KB
```

## Monitoring

### Health Check

```python
async def health_check():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8080/health") as response:
                return response.status == 200
    except:
        return False
```

### Metrics

```python
# metrics.py
from prometheus_client import Counter, Histogram, generate_latest

asr_requests = Counter('asr_requests_total', 'ASR requests')
asr_latency = Histogram('asr_latency_seconds', 'ASR latency')

async def transcribe_with_metrics(audio):
    start = time.time()
    result = await plugin.transcribe(audio)
    latency = time.time() - start
    
    asr_requests.inc()
    asr_latency.observe(latency)
    
    return result
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check ASR service is running |
| Audio format mismatch | Ensure 16kHz mono |
| High latency | Use WebSocket streaming |
| GPU not used | Add `--gpus all` to docker run |

## Testing

### Local Testing

```bash
# Start ASR service
docker compose up -d

# Test transcription
curl -X POST http://localhost:8080/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"audio": "base64_audio_data", "language": "en"}'
```

### Integration Tests

```python
# tests/test_integration.py
import pytest
from livekit.agents import RTTMSTranscription

@pytest.mark.asyncio
async def test_asr_integration():
    plugin = QwenASRPlugin()
    await plugin.start()
    
    # Test transcription
    audio_frame = rtc.AudioFrame(
        data=b"test audio data",
        samples=16000,
        sample_rate=16000,
        channel_layout="mono"
    )
    
    text = await plugin.transcribe(audio_frame)
    assert text is not None
    
    await plugin.stop()
```

## Next Steps

- See [Pipecat integration](./pipecat-integration.md)
- See [API Reference](./api-reference.md)
- See [Performance Benchmarks](./benchmarks.md)
