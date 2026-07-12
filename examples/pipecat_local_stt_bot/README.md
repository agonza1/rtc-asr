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

Switch the Compose bot between the sidecar adapters with `LOCAL_STT_SERVICE=local` or `LOCAL_STT_SERVICE=rtc-asr`. Use `LOCAL_STT_SERVICE=pipecat-whisper` only for the built-in Whisper baseline path and install any extra Whisper runtime dependencies required by your platform.

The bot connects to:

```text
ws://rtc-asr:8080/v1/stt/stream
```

For a local Python run, start `rtc-asr` first, then run the bot with a loopback websocket URL:

```bash
ASR_BACKEND=faster-whisper ASR_MODEL_SIZE=base.en ASR_DEVICE=cpu ASR_COMPUTE_TYPE=int8 ASR_PRELOAD_MODEL=true uvicorn src.main:app --host 0.0.0.0 --port 8080
RTC_ASR_WS_URL=ws://127.0.0.1:8080/v1/stt/stream python examples/pipecat_local_stt_bot/bot.py
```

## 30 Second Console Capture

Use `capture_console_transcription.py` when QA or demo production needs a short terminal artifact that shows Local STT transcript events appearing while the Pipecat local STT path is running. The helper streams a local mono PCM16 WAV over the same Local STT v1 websocket contract used by the bot, prints timestamped partial/final transcript events, and writes a clean text log without terminal control characters.

Start `rtc-asr` first:

```bash
ASR_BACKEND=faster-whisper ASR_MODEL_SIZE=base.en ASR_DEVICE=cpu ASR_COMPUTE_TYPE=int8 ASR_PRELOAD_MODEL=true uvicorn src.main:app --host 0.0.0.0 --port 8080
```

Then capture about 30 seconds of console transcription output from the repo root:

```bash
RTC_ASR_WS_URL=ws://127.0.0.1:8080/v1/stt/stream python examples/pipecat_local_stt_bot/capture_console_transcription.py \
  --duration-seconds 30 \
  --input-wav tests/fixtures/smoke.wav \
  --output artifacts/pipecat_local_stt_bot/console-transcription-30s.log
```

The default fixture is public test audio, not private microphone input. Because it is intentionally short, the helper repeats it to reach the requested capture length; pass another local 16 kHz mono PCM16 WAV with `--input-wav` for a more natural demo. Keep realtime pacing enabled for screen recording so the terminal output lands over roughly the requested duration.

Expected log shape:

```text
# pipecat_local_stt_bot console transcription capture: source=tests/fixtures/smoke.wav, target_duration=30.0s, url=ws://127.0.0.1:8080/v1/stt/stream
[14:02:11 +000.8s] partial rev=1 audio=600ms | hello
[14:02:40 +031.2s] final   rev=8 audio=30000ms | hello hello hello
# wrote clean console log to artifacts/pipecat_local_stt_bot/console-transcription-30s.log
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

Use `LocalStreamingSTTService` when you want the explicit Local STT v1 configuration object. That is the default and can be selected with `LOCAL_STT_SERVICE=local`. Use `RtcAsrSTTService` for the same sidecar path with repo defaults by setting `LOCAL_STT_SERVICE=rtc-asr`. Use Pipecat's built-in Whisper STT baseline with `LOCAL_STT_SERVICE=pipecat-whisper` and `PIPECAT_WHISPER_MODEL=base.en` when you want local/offline segmented transcription inside Pipecat rather than a warmed streaming sidecar.

Pipecat Whisper is local/offline, but it is a segmented STT baseline. The Local STT plugin is for streaming sidecar STT with benchmarkable first-partial, partial-cadence, and finalization metrics. Keep the same audio fixture and model size when comparing it with the `rtc-asr` sidecar path.

## Latency Metrics

Inspect sidecar benchmark artifacts for first visible partial, partial cadence, finalization after audio end, missing partial count, CPU utilization, peak RSS, and thermal observations. Keep `rtc-asr` warmed before collecting numbers so the result measures ASR serving, not model startup.

## Troubleshooting

- Connection failures: confirm `rtc-asr` is healthy with `curl -f http://localhost:8080/ready` and that Compose service discovery uses `ws://rtc-asr:8080/v1/stt/stream`.
- Protocol errors: send a Local STT v1 `start` message before binary audio and a `finalize` message at end of speech.
- Wrong sample rates: resample to 16 kHz mono PCM16 before audio reaches `LocalStreamingSTTService`.
- Missing interim transcripts: keep `interim_results=true`, set `partial_interval_ms=100`, and verify `partial_window_seconds=1.0` is not starved by tiny audio chunks.
