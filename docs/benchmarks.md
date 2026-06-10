# Performance Benchmarks

This page tracks validated single-node benchmark runs for the current `rtc-asr` service.
The benchmark harness runs 10 samples per model by default and reports mean, p90, p95, min,
and max for REST and streaming latencies. Each sample runs the REST loop plus one full
streaming session, so published numbers are less noisy than one-off snapshots.

## Backend Result Matrix

| Backend | Model | Runtime Path | Samples | Validation Status | Result Artifact | REST Mean / P95 | Streaming Partial Mean / P95 | Final Mean | Accuracy |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| `faster-whisper` | `tiny.en` | local Python CPU / `int8` | 1 legacy snapshot | validated snapshot | inline below | 263.7 ms / 269.1 ms | 177.5 ms / 308.6 ms | 261.3 ms | representative transcript only |
| `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU / `float32` | 1 legacy snapshot | validated artifact | `docs/benchmark-results/qwen-compose-2026-06-08.json` | 5482.2 ms / 5904.4 ms | 3696.1 ms / 6314.4 ms | 0.9 ms | WER 0.095 / CER 0.0 |
| `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU / `float32` | 10 planned | benchmark path ready; validated artifact pending | run `make benchmark-compose-parakeet` | pending | pending | pending | pending |
| `ultravox` | `fixie-ai/ultravox-v0_6-llama-3_1-8b` | Docker Compose CPU / `float32` | 10 planned | benchmark path ready; validated artifact pending | run `make benchmark-compose-ultravox` | pending | pending | pending | pending |

Use the matrix as the source of truth for which backends have checked-in numbers. A backend should
move from `pending` to `validated artifact` only after its JSON output is committed under
`docs/benchmark-results/` and the measured results section below is updated from that artifact.

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

All Compose benchmark targets now write a dated JSON artifact under `docs/benchmark-results/`.
Override `BENCHMARK_RESULT_DATE` when you want a stable filename during repeated local runs.

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
  --sample-count 10 \
  --output docs/benchmark-results/faster-whisper-local-$(date -u +%Y-%m-%d).json
```

### Qwen Compose Baseline

Use the checked-in Compose workflow:

```bash
make benchmark-compose-qwen
```

Equivalent manual command against an already-running Qwen service:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8080 \
  --ws-url ws://127.0.0.1:8080/ws/stream \
  --backend qwen-asr \
  --model Qwen/Qwen3-ASR-0.6B \
  --qwen-dtype float32 \
  --sample-count 10 \
  --output docs/benchmark-results/qwen-compose-$(date -u +%Y-%m-%d).json
```

### Parakeet Compose Baseline

Use the Parakeet Compose target to generate the missing validated artifact:

```bash
make benchmark-compose-parakeet
```

The target sets `ENABLE_PARAKEET_RUNTIME=1`, `ASR_BACKEND=parakeet`,
`ASR_PARAKEET_MODEL=nvidia/parakeet-tdt-0.6b-v3`, `ASR_DEVICE=cpu`, and
`ASR_PARAKEET_DTYPE=float32`. It also writes
`docs/benchmark-results/parakeet-compose-<date>.json`.

Equivalent manual command against an already-running Parakeet service:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8080 \
  --ws-url ws://127.0.0.1:8080/ws/stream \
  --backend parakeet \
  --model nvidia/parakeet-tdt-0.6b-v3 \
  --parakeet-dtype float32 \
  --sample-count 10 \
  --output docs/benchmark-results/parakeet-compose-$(date -u +%Y-%m-%d).json
```

### Ultravox Compose Baseline

Use the Ultravox Compose target to generate the missing validated artifact:

```bash
HF_TOKEN=... make benchmark-compose-ultravox
```

The default Ultravox model depends on gated Hugging Face weights, so export `HF_TOKEN` or
`HUGGINGFACE_HUB_TOKEN` before running it. The target sets `ASR_BACKEND=ultravox`,
`ASR_ULTRAVOX_MODEL=fixie-ai/ultravox-v0_6-llama-3_1-8b`, `ASR_DEVICE=cpu`,
`ASR_ULTRAVOX_DTYPE=float32`, and `ASR_ULTRAVOX_MAX_NEW_TOKENS=128`. It writes
`docs/benchmark-results/ultravox-compose-<date>.json`.

Equivalent manual command against an already-running Ultravox service:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8080 \
  --ws-url ws://127.0.0.1:8080/ws/stream \
  --backend ultravox \
  --model fixie-ai/ultravox-v0_6-llama-3_1-8b \
  --ultravox-dtype float32 \
  --ultravox-max-new-tokens 128 \
  --sample-count 10 \
  --output docs/benchmark-results/ultravox-compose-$(date -u +%Y-%m-%d).json
```

### Useful Benchmark Flags

- `--audio-file /path/to/sample.wav` benchmarks a specific clip.
- `--reference-text "..."` or `--reference-file transcript.txt` controls WER/CER reference text.
- `--chunk-ms 100` tests a tighter streaming cadence.
- `--partial-interval-chunks 2` reduces partial-event frequency.
- `--binary-frames` measures raw PCM websocket frames instead of JSON base64.
- `--spawn-server` lets the harness boot a local uvicorn server.
- `--partial-window 1.0` compares a smaller streaming window.
- `--max-buffer 4.0` clamps the per-stream websocket buffer budget.
- `--output docs/benchmark-results/<name>.json` stores the exact benchmark artifact that should be reviewed before docs are updated.

## Methodology Notes

- `tests/benchmark.py` emits 10-sample benchmark summaries and retains per-sample REST/streaming data under `samples`.
- The harness records simple accuracy metadata in addition to latency metrics.
- When benchmarking synthesized speech without an explicit reference file, the harness uses the synthesized prompt text as the reference transcript.
- The harness records live backend metadata from `GET /api/models`, so benchmark artifacts reflect the actual running service even when the client is pointed at an already-running container.
- Word error rate and character error rate are normalized after lowercasing and punctuation stripping.
- Commit the JSON artifact first, then copy the summary values from that artifact into the matrix and latest validated run notes.

## Remaining Gaps

Still not covered by this document:

- checked-in validated Parakeet and Ultravox CPU result artifacts
- concurrent REST or WebSocket load
- GPU-backed Qwen, Parakeet, or Ultravox measurements
- memory and CPU saturation curves
- corpus-level WER across more than a single synthesized utterance
- longer multi-turn streaming sessions
