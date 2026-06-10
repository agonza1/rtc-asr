# Pipecat Integration Guide

This guide shows how to bridge Pipecat audio into the current `rtc-asr` streaming API.

The backend is configurable, but streaming partials and finals are always emitted on `ws://.../ws/stream`; do not call `POST /api/stream`, and there is no `/api/flush` route.

## Protocol Summary

Open one websocket per utterance or per continuous stream and use this event order:

```json
{ "type": "start", "language": "en", "sample_rate": 16000, "partial_interval_chunks": 1, "partial_window_seconds": 2.0, "max_buffer_seconds": 30.0 }
```

```json
{ "type": "stop" }
```

The server responds with:

- `ready` after `start`
- `partial` after each configured chunk interval
- `final` after `stop`
- `error` before close if the event order or audio payload is invalid

After `start`, Pipecat can send audio as JSON base64 events or raw binary websocket frames. Prefer binary frames when you already have PCM16 bytes available.

## Recommended Client Helper

This repo includes tested websocket helpers in `src/rtc_client.py` and `src/streaming.py`. If your Pipecat app lives in another repository, vendor one of those helpers instead of duplicating the websocket protocol.

```python
from src.rtc_client import AsyncASRClient


class PipecatASRBridge:
    def __init__(self, ws_url: str = "ws://localhost:8080/ws/stream") -> None:
        self._ws_url = ws_url
        self._client: AsyncASRClient | None = None

    async def start_stream(self, *, language: str | None = "en", sample_rate: int = 16000) -> dict:
        self._client = AsyncASRClient(self._ws_url)
        return await self._client.start(
            language=language,
            sample_rate=sample_rate,
            partial_interval_chunks=1,
            partial_window_seconds=2.0,
            max_buffer_seconds=30.0,
            send_binary_frames=True,
        )

    async def send_audio_chunk(self, pcm16_chunk: bytes) -> str:
        if self._client is None:
            raise RuntimeError("Call start_stream() before send_audio_chunk()")
        event = await self._client.send_audio(pcm16_chunk)
        return "" if event is None else event.text

    async def stop_stream(self) -> str:
        if self._client is None:
            raise RuntimeError("Call start_stream() before stop_stream()")
        final_event = await self._client.stop()
        await self._client.close()
        self._client = None
        return final_event.text
```

## Wiring Into Pipecat

Pipecat APIs move between releases, so keep the websocket bridge stable and adapt only the processor wrapper to your installed Pipecat version.

Typical flow:

1. Start an `AsyncASRClient` when Pipecat begins a new speech segment.
2. Convert each Pipecat audio frame to mono PCM16 bytes.
3. Call `send_audio_chunk()` for every chunk and forward non-empty `partial` text into your transcript/event pipeline.
4. Call `stop_stream()` when VAD or turn detection ends the segment and publish the returned final transcript.

Minimal processor sketch:

```python
class MyPipecatProcessor:
    def __init__(self) -> None:
        self._asr = PipecatASRBridge()

    async def on_segment_start(self) -> None:
        await self._asr.start_stream(language="en", sample_rate=16000)

    async def on_audio_chunk(self, pcm16_chunk: bytes) -> str:
        return await self._asr.send_audio_chunk(pcm16_chunk)

    async def on_segment_end(self) -> str:
        return await self._asr.stop_stream()
```

## Audio Format Notes

- Lowest-friction path: send raw mono PCM16 chunks as binary websocket frames and set `sample_rate` in the `start` event.
- The server can resample raw PCM16 if your Pipecat source is not already 16kHz.
- If you send WAV or another encoded format instead of raw PCM16, each websocket `audio_data` payload still needs to be a complete decodable chunk.
- Start with `50` to `200` ms chunks for a good latency/overhead balance.

## Local Verification

Start the service:

```bash
PYTHON_BASE_IMAGE=python:3.11-slim docker compose up -d --build
```

Then run the repo tests that cover the helper and websocket protocol:

```bash
pytest tests/test_client.py tests/test_smoke.py -v
python3 -m compileall src tests
```

## Related Docs

- [API Reference](./api-reference.md)
- [LiveKit Integration](./livekit-integration.md)
- [Troubleshooting](./troubleshooting.md)
- [README](../README.md)
