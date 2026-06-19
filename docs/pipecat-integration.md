# Pipecat Integration Guide

This guide shows how to bridge Pipecat audio into the current `rtc-asr` websocket API.

The backend is configurable, but partials and finals are always emitted on `ws://.../ws/stream`; do not call `POST /api/stream`, and there is no `/api/flush` route.

## Protocol Summary

The current contract is buffered websocket ASR, not a true frame-synchronous streaming decoder API. Pipecat should stay responsible for WebRTC transport, jitter handling, audio decode, and media-edge timing. `rtc-asr` should stay responsible for normalized audio ingestion, partial refreshes over buffered windows, and final transcript generation.

## Why A Local STT Service Instead Of Only Pipecat Plugins

Existing Pipecat STT services are best when a pipeline can hand audio to a hosted provider or a provider-specific SDK and accept that provider contract as the integration boundary. This repo needed a different boundary: a warmed local ASR sidecar that can swap `faster-whisper`, Qwen, Parakeet, MLX, and future runtimes without changing the voice-agent pipeline.

The Local STT service keeps model loading, preload readiness, backend capability metadata, and benchmark artifact generation inside `rtc-asr`. The Pipecat adapter stays intentionally thin: it turns decoded PCM frames into Local STT websocket messages and maps transcript events back into Pipecat frames. That lets us benchmark local CPU and Apple Silicon paths as services, compare backends through one protocol, and keep Pipecat focused on RTC session orchestration rather than model lifecycle management.

Use native Pipecat/provider plugins when you want the provider experience directly. Use this sidecar when you want local inference, warmed latency measurements, backend portability, or a stable protocol that can be reused outside Pipecat.

Open one websocket per utterance or per continuous stream and use this event order:

```json
{ "type": "start", "language": "en", "sample_rate": 16000, "partial_interval_chunks": 1, "partial_window_seconds": 1.0, "max_buffer_seconds": 10.0 }
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
            partial_window_seconds=1.0,
            max_buffer_seconds=10.0,
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
2. Receive Pipecat `InputAudioRawFrame` values, which are typically decoded PCM frames at about `20` ms cadence.
3. Aggregate `4` to `8` source frames into one websocket chunk before calling `send_audio_chunk()`.
4. Forward non-empty `partial` text into your transcript or event pipeline.
5. Call `stop_stream()` when VAD or turn detection ends the segment and publish the returned final transcript.

Minimal processor sketch:

```python
class MyPipecatProcessor:
    def __init__(self) -> None:
        self._asr = PipecatASRBridge()
        self._pending = bytearray()

    async def on_segment_start(self) -> None:
        self._pending.clear()
        await self._asr.start_stream(language="en", sample_rate=16000)

    async def on_audio_frame(self, pcm16_frame: bytes) -> str:
        self._pending.extend(pcm16_frame)
        if len(self._pending) < 3200:
            return ""

        chunk = bytes(self._pending)
        self._pending.clear()
        return await self._asr.send_audio_chunk(chunk)

    async def on_segment_end(self) -> str:
        if self._pending:
            await self._asr.send_audio_chunk(bytes(self._pending))
            self._pending.clear()
        return await self._asr.stop_stream()
```

## Chunking Guidance

Start with `100` to `200` ms PCM16 websocket chunks for service benchmarking. Use `20` ms only at the RTC edge, then aggregate before websocket transmission unless you are intentionally measuring per-frame transport overhead.

| Chunk duration | RTC frames | Payload size at 16 kHz mono PCM16 |
| --- | --- | --- |
| `20` ms | `1` | `640` bytes |
| `80` ms | `4` | `2560` bytes |
| `100` ms | `5` | `3200` bytes |
| `160` ms | `8` | `5120` bytes |
| `200` ms | `10` | `6400` bytes |

`80` to `160` ms is the practical sweet spot for this architecture because it keeps perceived latency low, reduces websocket overhead, gives the backend enough context for steadier partials, maps cleanly from Pipecat's frame cadence, and avoids excessive ASR invocation rates on smaller devices.

## Architecture Boundary

Keep the media edge and the ASR service separate:

```text
Browser / mobile mic
  -> WebRTC / RTP / Opus
Pipecat transport
  -> decoded PCM frames, usually ~20 ms
Chunk aggregator
  -> binary PCM16 websocket frame every 80-160 ms
rtc-asr /ws/stream
  -> partial/final transcript events
Voice agent pipeline
```

That avoids turning `rtc-asr` into a media server. Pipecat handles WebRTC, jitter, decode, device integration, and frame timing. `rtc-asr` stays a simpler ASR benchmark and service layer.

## Local Benchmark

Run the Pipecat-style end-to-end benchmark harness against a local backend. By default it synthesizes a speech clip through the benchmark harness so the lane always exercises real spoken audio; you can still override it with a specific file when needed:

```bash
make benchmark-pipecat-e2e
make benchmark-pipecat-e2e BENCHMARK_PIPECAT_AUDIO_FILE=/absolute/path/to/speech.wav
```

`make benchmark-pipecat-e2e` now enables `--simulate-realtime` by default so the harness sleeps between source frames instead of blasting the full clip as fast as Python can enqueue websocket writes. That keeps first-partial and post-audio finalization numbers closer to what a Pipecat bridge sees during a real call.

The benchmark client also timestamps audio-end from the last websocket chunk send rather than from the later `stop` response. That means the checked-in JSON artifact contract captures Pipecat source-frame cadence, real-time pacing, bridge chunk size, framing mode, first visible partial timing, partial cadence or jitter, final closeout after audio end, and missing partial counts. The repo keeps these artifacts as a separate integration track instead of mixing them into the homepage leaderboard until there are comparable E2E artifacts across multiple backends.

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
