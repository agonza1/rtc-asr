# pipecat-local-stt

`pipecat-local-stt` provides `LocalStreamingSTTService`, a Pipecat STT service that streams raw PCM16 audio to a Local STT v1 websocket sidecar and maps transcript events back into Pipecat transcription frames.

It exists for local sidecar inference rather than as another hosted-provider wrapper. Pipecat remains responsible for RTC transport, VAD, pipeline orchestration, and downstream frames; `rtc-asr` remains responsible for warmed model lifecycle, backend selection, readiness, and benchmarkable ASR behavior. That keeps local CPU, Apple Silicon, and accelerator experiments portable across Pipecat apps without binding the ASR service to a provider-specific plugin contract.

```python
from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService

stt = LocalStreamingSTTService(
    LocalSTTConfig(
        url="ws://rtc-asr:8080/v1/stt/stream",
        sample_rate=16000,
        language="en",
        partial_interval_ms=100,
    )
)
```

Convenience wrapper:

```python
from pipecat_local_stt import RtcAsrSTTService

stt = RtcAsrSTTService(
    url="ws://rtc-asr:8080/v1/stt/stream",
    language="en",
)
```

Optional colocated Unix-domain-socket WebSocket transport uses the same Local STT v1 messages and remains an optimization knob to benchmark against TCP:

```python
stt = RtcAsrSTTService(
    transport="uds_ws",
    url="ws://localhost/v1/stt/stream",
    uds_path="/run/rtc-asr/stt.sock",
    language="en",
)
```

The experimental raw UDS client path uses the same `RtcAsrSTTService` API, but swaps WebSocket frames for the Local STT v1 length-prefixed raw UDS frame codec. Use it only after starting `rtc-asr` with `LOCAL_STT_RAW_UDS_ENABLED=true` and a matching `LOCAL_STT_RAW_UDS_PATH`, and keep it out of default deployments unless benchmark artifacts show a p95 first-interim win of at least 5 ms over UDS WebSocket:

```python
stt = RtcAsrSTTService(
    transport="raw_uds",
    uds_path="/run/rtc-asr/stt.raw.sock",
    language="en",
)
```

The package also exports the Raw UDS codec constants for probes and custom transports. `RAW_UDS_FRAME_DIRECTION` is a stable name catalog for deciding whether a frame type is valid client-to-server or server-to-client traffic:

```python
from pipecat_local_stt import RAW_UDS_FRAME_DIRECTION

assert RAW_UDS_FRAME_DIRECTION["client_to_server"] == ["JSON_CONTROL", "AUDIO_PCM16", "PING", "PONG"]
```

Place the service after `transport.input()` and before `context_aggregator.user()` in a Pipecat pipeline. The plugin does not implement RTC, VAD, LLM context aggregation, or TTS.

## Running Against `rtc-asr`

Start the `rtc-asr` sidecar before creating the Pipecat pipeline, and treat readiness as part of the voice-agent startup path:

```bash
ASR_BACKEND=faster-whisper \
ASR_MODEL_SIZE=base.en \
ASR_DEVICE=cpu \
ASR_COMPUTE_TYPE=int8 \
ASR_PRELOAD_MODEL=true \
uvicorn src.main:app --host 0.0.0.0 --port 8080

curl -f http://localhost:8080/ready
```

Use `ASR_PRELOAD_MODEL=true` for production-style local serving so model load and backend validation happen before the first caller hits the Pipecat pipeline. After `/ready` passes, send one short warm-up utterance before measuring latency or routing live traffic. Keep the sidecar process resident across calls; one-shot process startup numbers mostly measure model load, graph compilation, and first-request cache setup rather than steady-state ASR latency.

## Audio Chunking

Pipecat commonly emits decoded PCM frames at about `20` ms cadence. Aggregate those frames before forwarding them to `rtc-asr`:

| Chunk duration | Pipecat frames | PCM16 payload at 16 kHz mono |
| --- | --- | --- |
| `80` ms | `4` | `2560` bytes |
| `100` ms | `5` | `3200` bytes |
| `160` ms | `8` | `5120` bytes |

`80` to `160` ms is the practical default range for live Pipecat bridges. It keeps partials responsive while avoiding unnecessary websocket and ASR invocation overhead on low-power devices. Use smaller chunks only when you are intentionally measuring per-frame transport overhead.

## Benchmarking Notes

For fair Pipecat comparisons, benchmark the warmed sidecar path and keep backend, model, device, chunk duration, partial interval, audio fixture, and run count fixed between artifacts. The useful latency numbers are first visible partial, final after audio end, realtime factor, missing partial count, and transcript churn across interim updates.

See the repo-level [README](../README.md) and [Pipecat Integration Guide](../docs/pipecat-integration.md) for the full service contract and benchmark harness.
