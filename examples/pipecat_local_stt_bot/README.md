# Pipecat Local STT Bot

This minimal example wires a Pipecat WebRTC pipeline to the `rtc-asr` Local STT v1 sidecar. Pipecat owns the WebRTC media edge, context aggregation, LLM, TTS, and transport output. `rtc-asr` owns warmed local ASR inference on `ws://rtc-asr:8080/v1/stt/stream`.

## Architecture

```text
browser/client -> Pipecat transport -> LocalStreamingSTTService -> rtc-asr /v1/stt/stream
               -> context aggregator -> LLM -> TTS -> Pipecat transport output
```

This is not WebRTC-to-ASR. WebRTC stays inside Pipecat, which decodes microphone media into PCM frames before the STT service sees them.

This is not Deepgram/OpenAI-compatible. Local STT v1 is a small sidecar protocol: JSON control messages plus binary PCM16 audio frames over one websocket.

## Quick Start

From the repo root, start the sidecar and the example bot together:

```bash
PYTHON_BASE_IMAGE=python:3.11-slim docker compose -f examples/pipecat_local_stt_bot/docker-compose.yml up --build
```

The bot connects to:

```text
ws://rtc-asr:8080/v1/stt/stream
```

For a local Python run, start `rtc-asr` first, then run the bot with a loopback websocket URL:

```bash
ASR_BACKEND=faster-whisper ASR_MODEL_SIZE=base.en ASR_DEVICE=cpu ASR_COMPUTE_TYPE=int8 ASR_PRELOAD_MODEL=true uvicorn src.main:app --host 0.0.0.0 --port 8080
RTC_ASR_WS_URL=ws://127.0.0.1:8080/v1/stt/stream python examples/pipecat_local_stt_bot/bot.py
```

## Defaults

- `language=en` (set `LOCAL_STT_LANGUAGE=` to omit a language hint and let the sidecar auto-detect when supported)
- `sample_rate=16000`
- `channels=1`
- `format=pcm_s16le`
- `frame_ms=20`
- `partial_interval_ms=100`
- `partial_window_seconds=1.0`
- `max_buffer_seconds=10.0`

Tune `partial_interval_ms` upward when a low-power device shows high CPU use or noisy partial churn. Tune it downward only after confirming the sidecar has enough headroom and partial gaps stay stable.
Tune `LOCAL_STT_MAX_BUFFER_SECONDS` downward when you need a hard utterance-size cap for memory or latency tests.

## Service Choices

Use `LocalStreamingSTTService` when you want the explicit Local STT v1 configuration object. That is the default and can be selected with `LOCAL_STT_SERVICE=local`. Use `RtcAsrSTTService` for the same sidecar path with repo defaults by setting `LOCAL_STT_SERVICE=rtc-asr`. Use Pipecat's built-in Whisper STT baseline when you want local/offline segmented transcription inside Pipecat rather than a warmed streaming sidecar.

Pipecat Whisper is local/offline, but it is a segmented STT baseline. The Local STT plugin is for streaming sidecar STT with benchmarkable first-partial, partial-cadence, and finalization metrics.

## Latency Metrics

Inspect sidecar benchmark artifacts for first visible partial, partial cadence, finalization after audio end, missing partial count, CPU utilization, peak RSS, and thermal observations. Keep `rtc-asr` warmed before collecting numbers so the result measures ASR serving, not model startup.

## Troubleshooting

- Connection failures: confirm `rtc-asr` is healthy with `curl -f http://localhost:8080/ready` and that Compose service discovery uses `ws://rtc-asr:8080/v1/stt/stream`.
- Protocol errors: send a Local STT v1 `start` message before binary audio and a `finalize` message at end of speech.
- Wrong sample rates: resample to 16 kHz mono PCM16 before audio reaches `LocalStreamingSTTService`.
- Missing interim transcripts: keep `interim_results=true`, set `partial_interval_ms=100`, and verify `partial_window_seconds=1.0` is not starved by tiny audio chunks.
