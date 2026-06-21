# Pipecat Integration Guide

This guide shows how to bridge Pipecat audio into the current `rtc-asr` Local STT v1 websocket API.

The backend is configurable, but new Pipecat integrations should use `ws://.../v1/stt/stream`. The older `ws://.../ws/stream` route remains available only for legacy buffered-websocket comparisons. Do not call `POST /api/stream`, and there is no `/api/flush` route.

## Protocol Summary

The current integration contract is Local STT v1: JSON control messages plus binary PCM16 audio frames on `ws://.../v1/stt/stream`. Pipecat should stay responsible for WebRTC transport, jitter handling, audio decode, and media-edge timing. `rtc-asr` should stay responsible for normalized audio ingestion, Local STT transcript events, backend readiness, and final transcript generation.

## Why A Local STT Service Instead Of Only Pipecat Plugins

Existing Pipecat STT services are best when a pipeline can hand audio to a hosted provider or a provider-specific SDK and accept that provider contract as the integration boundary. This repo needed a different boundary: a warmed local ASR sidecar that can swap `faster-whisper`, Qwen, Parakeet, MLX, and future runtimes without changing the voice-agent pipeline.

The Local STT service keeps model loading, preload readiness, backend capability metadata, and benchmark artifact generation inside `rtc-asr`. The Pipecat adapter stays intentionally thin: it turns decoded PCM frames into Local STT websocket messages and maps transcript events back into Pipecat frames. That lets us benchmark local CPU and Apple Silicon paths as services, compare backends through one protocol, and keep Pipecat focused on RTC session orchestration rather than model lifecycle management.

Use native Pipecat/provider plugins when you want the provider experience directly. Use this sidecar when you want local inference, warmed latency measurements, backend portability, or a stable protocol that can be reused outside Pipecat.

Open one websocket per utterance or per continuous stream and use this event order:

```json
{ "type": "start", "version": "local-stt.v1", "audio": { "sample_rate": 16000, "channels": 1, "format": "pcm_s16le", "frame_ms": 20, "bytes_per_frame": 640 }, "language": "en", "interim_results": true, "partial_interval_ms": 100, "partial_window_seconds": 1.0, "max_buffer_seconds": 10.0 }
```

```json
{ "type": "finalize" }
```

The server responds with:

- `ready` after `start`
- `transcript` events with `is_final=false` for partial updates
- one `transcript` event with `is_final=true` after `finalize`
- `error` before close if the event order or audio payload is invalid
- `closed` after the client sends `close`

After `start`, Pipecat sends raw binary PCM16 frames. Local STT v1 does not base64-wrap audio.

## Recommended Client Helper

This repo includes tested websocket helpers in `src/rtc_client.py` and `src/streaming.py`. If your Pipecat app lives in another repository, vendor one of those helpers instead of duplicating the websocket protocol.

```python
from src.rtc_client import AsyncLocalSttClient


class PipecatASRBridge:
    def __init__(self, ws_url: str = "ws://localhost:8080/v1/stt/stream") -> None:
        self._ws_url = ws_url
        self._client: AsyncLocalSttClient | None = None

    async def start_stream(self, *, language: str | None = "en", sample_rate: int = 16000) -> dict:
        self._client = AsyncLocalSttClient(self._ws_url)
        return await self._client.start(
            language=language,
            sample_rate=sample_rate,
            partial_interval_ms=100,
            partial_window_seconds=1.0,
            max_buffer_seconds=10.0,
        )

    async def send_audio_chunk(self, pcm16_chunk: bytes) -> str:
        if self._client is None:
            raise RuntimeError("Call start_stream() before send_audio_chunk()")
        await self._client.send_audio(pcm16_chunk)
        event = await self._client.recv_event(timeout=0.01)
        return "" if event is None else event.text

    async def stop_stream(self) -> str:
        if self._client is None:
            raise RuntimeError("Call start_stream() before stop_stream()")
        await self._client.finalize()
        final_event = None
        while final_event is None or not final_event.is_final:
            final_event = await self._client.recv_event()
        await self._client.close()
        self._client = None
        return final_event.text
```

## Wiring Into Pipecat

Pipecat APIs move between releases, so keep the websocket bridge stable and adapt only the processor wrapper to your installed Pipecat version.

Typical flow:

1. Start an `AsyncLocalSttClient` when Pipecat begins a new speech segment.
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
rtc-asr /v1/stt/stream
  -> Local STT transcript events
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
- [Browser Pipecat Demo](../examples/browser_pipecat_demo/README.md)
- [LiveKit Integration](./livekit-integration.md)
- [Troubleshooting](./troubleshooting.md)
- [README](../README.md)
