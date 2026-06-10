# LiveKit Integration Guide

This guide shows how to stream LiveKit audio into the current `rtc-asr` websocket API without reimplementing the wire protocol in every agent.

The backend is configurable, but the transport contract is not: partials and finals come from `ws://.../ws/stream`, `POST /api/stream` intentionally returns `501`, and there is no `/api/flush` route.

## Protocol Summary

Each LiveKit speech stream should follow this websocket sequence:

```json
{ "type": "start", "language": "en", "sample_rate": 48000, "partial_interval_chunks": 1, "partial_window_seconds": 2.0, "max_buffer_seconds": 30.0 }
```

```json
{ "type": "stop" }
```

After `start`, send each PCM chunk as either a JSON `audio` event or a raw binary websocket frame. Prefer binary frames for LiveKit because the room data is already byte-oriented and avoids base64 inflation.

Set `sample_rate` to the raw PCM cadence you are sending. Many LiveKit rooms deliver 48kHz mono frames; the server will resample them to its configured backend target rate.

The default `STREAM_MAX_BUFFER_BYTES=1048576` still applies before `max_buffer_seconds`. At PCM16 mono 48kHz, that default cap only holds about `10.9` seconds of audio, so a `max_buffer_seconds=30.0` request is not enough by itself to guarantee a 30-second utterance. If you need longer buffers, either resample upstream to `16000` Hz or raise `STREAM_MAX_BUFFER_BYTES` to match the longer capture window.

## Recommended Client Helper

Reuse `src/rtc_client.py` or `src/streaming.py` from this repo instead of hand-rolling websocket JSON in every agent.

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
            send_binary_frames=True,
        )

    async def push_frame(self, frame: rtc.AudioFrame) -> str:
        pcm16_chunk = memoryview(frame.data).tobytes()
        event = await self._client.send_audio(pcm16_chunk)
        return "" if event is None else event.text

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
- Keep the chunk cadence steady. `50` to `200` ms is a good starting range.
- If you already resample to 16kHz mono in the client, set `sample_rate=16000` in the `start` event.
- The server keeps a bounded rolling buffer for partials and a capped full buffer for the final transcript; tune `partial_window_seconds` and `max_buffer_seconds` when long utterances matter, and raise `STREAM_MAX_BUFFER_BYTES` if your 48kHz PCM path needs to exceed the default ~10.9 second ceiling.
- Check `GET /api/models` during startup if your agent needs to branch on backend capabilities.

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
- [README](../README.md)
