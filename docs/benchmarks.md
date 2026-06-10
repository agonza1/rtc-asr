# Performance Benchmarks

This page tracks validated single-node benchmark runs for the current `rtc-asr` service.
The benchmark harness now runs 10 samples per model and reports mean, p90, p95, min, and max
for REST and streaming latencies. Each sample runs the existing REST loop plus one full streaming
session, so the published numbers are less noisy than the original one-off snapshots.

## At a Glance

| Model | Backend | Sample Count | REST Mean / P90 | Streaming Partial Mean / P90 | Final Mean | Accuracy |
| --- | --- | ---: | --- | --- | --- | --- |
| `tiny.en` | `faster-whisper` | 10 | see snapshot below | see snapshot below | see snapshot below | see snapshot below |
| `Qwen/Qwen3-ASR-0.6B` | `qwen-asr` | 10 | see snapshot below | see snapshot below | see snapshot below | see snapshot below |

The rows below are the latest validated snapshots currently checked into the repo. Rerun the commands in
*Reproduce* to refresh them with the 10-sample harness output.

## Latest Validated Runs

### Faster-Whisper CPU Baseline

Measured on June 3, 2026.

Environment:

- Host: macOS 26.5 arm64
- Python: 3.14.4
- Backend: `faster-whisper`
- Model: `tiny.en`
- Device: CPU / `int8`
- Streaming chunk size: 250 ms
- Streaming partial window: 2.0 s
- Audio: 7.28 s synthesized speech clip generated locally with `say`

Measured results:

- REST `POST /api/transcribe`: 263.7 ms mean, 269.1 ms p95, 258.7 ms min, 269.1 ms max
- REST real-time factor: 0.036
- WebSocket partial latency: 177.5 ms mean, 308.6 ms p95, 129.1 ms first partial, 155.2 ms last partial
- WebSocket final latency after `stop`: 261.3 ms

Representative transcript:

```text
the quick-brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTCSR service.
```

### Qwen Compose CPU Baseline

Measured on June 8, 2026 against the Docker Compose stack.

Environment:

- Host: macOS 26.5.1 arm64
- Python benchmark client: 3.14.4
- Execution mode: `docker compose`
- Backend: `qwen-asr`
- Model: `Qwen/Qwen3-ASR-0.6B`
- Device: CPU / `float32`
- Audio: 7.28 s synthesized speech clip from `say`
- Reference transcript: `The quick brown fox jumps over the lazy dog. This is a realtime ASR latency benchmark for the rtc asr service.`

Measured results:

- REST `POST /api/transcribe`: 5482.2 ms mean, 5904.4 ms p95, 5221.7 ms min, 5904.4 ms max
- REST real-time factor: 0.753
- WebSocket partial latency: 3696.1 ms mean, 6314.4 ms p95, 1468.2 ms first partial, 5436.3 ms last partial
- WebSocket final latency after `stop`: 0.9 ms
- REST transcript: `The quick brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTC ASR service.`
- Streaming final transcript: `The quick brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTC ASR service.`
- Accuracy (normalized WER): `0.095`
- Accuracy (normalized CER): `0.0`

Interpretation notes:

- The measured Qwen CPU path is still substantially slower than the `faster-whisper` `tiny.en` CPU baseline, but it remained below real time across a longer synthesized utterance.
- The main accuracy miss is word-boundary normalization: `realtime` became `real-time`, which increases WER while leaving normalized CER at `0.0`.
- The very small `final_ms` value reflects that most of the work already happened during the streaming partial passes.

Versioned artifact:

- `docs/benchmark-results/qwen-compose-2026-06-08.json`

## Reproduce

### Faster-Whisper Baseline

Run the local baseline with 10 samples per model:

```bash
make benchmark
```

Or invoke the harness directly against an already-running server:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8090 \
  --ws-url ws://127.0.0.1:8090/ws/stream \
  --sample-count 10
```

### Qwen Compose Baseline

Use the checked-in Compose workflow:

Useful benchmark flags:

- `--audio-file /path/to/sample.wav` to benchmark a specific clip
- `--chunk-ms 100` to test a tighter streaming cadence
- `--partial-interval-chunks 2` to reduce partial-event frequency
- `--binary-frames` to measure raw PCM websocket frames instead of JSON base64
- `--spawn-server` to let the harness boot a local uvicorn server
- `--ultravox-prompt "Return only the transcript."` to benchmark a non-default Ultravox system prompt
- `--partial-window 1.0` to compare a smaller streaming window
- `--max-buffer 4.0` to clamp the per-stream websocket buffer budget

```bash
make benchmark-compose-qwen
```

What that target does:

- creates a writable local Hugging Face cache at `.cache/huggingface`
- reuses a cached `python:3.11-slim` base image when present; otherwise it tries Docker Hub first and falls back to `mirror.gcr.io/library/python:3.11-slim` only if the default image is not cached locally and the pull fails; explicit `PYTHON_BASE_IMAGE` overrides are used as-is
- builds the image with a CPU PyTorch wheel from the official PyTorch CPU index so Compose does not pull the much larger CUDA stack for the default CPU path
- starts `docker compose` with `ASR_BACKEND=qwen-asr`, `ASR_QWEN_MODEL=Qwen/Qwen3-ASR-0.6B`, `ASR_DEVICE=cpu`, and `ASR_QWEN_DTYPE=float32`
- waits for `GET /ready` to return `200`
- runs the benchmark client against `http://127.0.0.1:8080` with `--sample-count 10`

Equivalent manual commands:

```bash
mkdir -p .cache/huggingface
ASR_BACKEND=qwen-asr \
ASR_QWEN_MODEL=Qwen/Qwen3-ASR-0.6B \
ASR_DEVICE=cpu \
ASR_QWEN_DTYPE=float32 \
PYTHON_BASE_IMAGE=python:3.11-slim docker compose up -d --build

until curl -fsS http://127.0.0.1:8080/ready >/dev/null; do sleep 5; done

.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8080 \
  --ws-url ws://127.0.0.1:8080/ws/stream \
  --sample-count 10
```

## Methodology Notes

- `tests/benchmark.py` now emits 10-sample benchmark summaries and retains per-sample REST/streaming data under `samples`.
- The harness records simple accuracy metadata in addition to latency metrics.
- When benchmarking synthesized speech without an explicit reference file, the harness uses the synthesized prompt text as the reference transcript.
- The harness also records live backend metadata from `GET /api/models`, so benchmark artifacts reflect the actual running service even when the client is pointed at an already-running container.
- Word error rate and character error rate are normalized after lowercasing and punctuation stripping.

## Remaining Gaps

Still not covered by this document:

- concurrent REST or WebSocket load
- GPU-backed Qwen measurements
- memory and CPU saturation curves
- corpus-level WER across more than a single synthesized utterance
- longer multi-turn streaming sessions
