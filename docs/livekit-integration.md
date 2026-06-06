# LiveKit Integration Guide

This guide shows how to stream LiveKit audio into the current `rtc-asr` websocket API.

The shipped service uses the lightweight `faster-whisper` backend. Incremental transcripts come from `ws://.../ws/stream`; the HTTP `POST /api/stream` endpoint intentionally returns `501`, and there is no `/api/flush` endpoint.

## Protocol Summary

Each LiveKit speech stream should follow this websocket sequence:

```json
{ "type": "start", "language": "en", "sample_rate": 48000, "partial_interval_chunks": 1, "partial_window_seconds": 2.0 }
```

```json
{ "type": "audio", "audio_data": "base64_encoded_audio_chunk" }
```

```json
{ "type": "stop" }
```

Set `sample_rate` to the raw PCM rate you are sending. Many LiveKit rooms deliver 48kHz audio; the server will downsample to its configured 16kHz transcription path.

## Recommended Client Helper

Reuse `src/rtc_client.py` from this repo instead of hand-rolling websocket JSON in every agent.

```python
from livekit import rtc
from src.rtc_client import AsyncASRClient


class LiveKitASRStream:
    def __init__(self, ws_url: str = "ws://localhost:8080/ws/stream") -> None:
        self._client = AsyncASRClient(ws_url)

    async def start(self, *, language: str | None = "en", sample_rate: int = 48000) -> dict:
        return await self._client.start(
            language=language,
            sample_rate=sample_rate,
            partial_interval_chunks=1,
            partial_window_seconds=2.0,
            max_buffer_seconds=30.0,
        )

    async def push_frame(self, frame: rtc.AudioFrame) -> str:
        pcm16_chunk = memoryview(frame.data).tobytes()
        event = await self._client.send_audio(pcm16_chunk)
        return event.text

    async def finish(self) -> str:
        final_event = await self._client.stop()
        await self._client.close()
        return final_event.text
```

## Wiring Into A LiveKit Agent

Create one `LiveKitASRStream` per participant track or per utterance, depending on how your agent segments speech.

Typical flow:

1. Start the websocket when an audio track becomes active.
2. Feed each PCM frame into `push_frame()`.
3. Forward non-empty partial text to your captions/UI if you want low-latency updates.
4. Call `finish()` when the utterance ends and store the final transcript.

Minimal sketch:

```python
async def transcribe_track(audio_frames, language: str = "en") -> str:
    stream = LiveKitASRStream()
    await stream.start(language=language, sample_rate=48000)

    partial_text = ""
    async for frame in audio_frames:
        partial_text = await stream.push_frame(frame)
        if partial_text:
            print("partial:", partial_text)

    final_text = await stream.finish()
    print("final:", final_text)
    return final_text
```

## Operational Notes

- Use websocket streaming for partials; do not poll HTTP for chunk results.
- Keep the chunk cadence steady. Smaller PCM chunks reduce perceived latency but increase websocket overhead.
- If you already resample to 16kHz mono in the client, set `sample_rate=16000` in the `start` event.
- The server keeps a bounded rolling buffer for partials and a capped full buffer for the final transcript; tune `partial_window_seconds` and `max_buffer_seconds` in the `start` event if needed.

## Local Verification

```bash
pytest tests/test_client.py tests/test_smoke.py -v
python3 -m compileall src tests
```

If you want to sanity check the service manually first:

```bash
curl http://localhost:8080/health
curl -f http://localhost:8080/ready
```

## Related Docs

- [API Reference](./api-reference.md)
- [Pipecat Integration](./pipecat-integration.md)
- [Benchmarks](./benchmarks.md)
