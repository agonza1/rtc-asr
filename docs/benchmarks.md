# Performance Benchmarks

This page tracks validated single-node benchmark runs for the current `rtc-asr` service.
The benchmark harness runs 10 samples per model by default and reports mean, p90, p95, min,
and max for REST and streaming latencies. Each sample runs the REST loop plus one full
streaming session, so published numbers are less noisy than one-off snapshots.

## Backend Result Matrix

| Backend | Model | Runtime Path | Samples | Validation Status | Result Artifact | REST Mean / P95 | Streaming Partial Mean / P95 | Final Mean | Accuracy |
| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| `faster-whisper` | `base.en` | local Python CPU / `int8` | 10 | validated artifact | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json` | 573.3 ms / 741.1 ms | 553.0 ms / 2451.5 ms | 560.2 ms | WER 0.095 / CER 0.0 |
| `faster-whisper` | `small.en` | local Python CPU / `int8` | 10 | validated artifact | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` | 1378.3 ms / 1531.1 ms | 1023.2 ms / 1202.4 ms | 1420.6 ms | WER 0.095 / CER 0.0 |
| `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU / `float32` | 1 legacy snapshot | validated legacy artifact; 10-sample refresh attempted on 2026-06-10 but service restarted during first generation and REST warmup failed with `httpx.ReadError` | `docs/benchmark-results/qwen-compose-2026-06-08.json` | 5482.2 ms / 5904.4 ms | 3696.1 ms / 6314.4 ms | 0.9 ms | WER 0.095 / CER 0.0 |
| `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU / `float32` | 10 | validated artifact | `docs/benchmark-results/parakeet-compose-2026-06-10.json` | 2388.3 ms / 4098.1 ms | 1715.1 ms / 2968.7 ms | 2215.8 ms | WER 0.095 / CER 0.0 |
| `ultravox` | `fixie-ai/ultravox-v0_6-llama-3_1-8b` | Docker Compose CPU / `float32` | 10 target | blocked before validation: current token can fetch `fixie-ai/ultravox`, but the model loads gated `meta-llama/Llama-3.1-8B-Instruct` and Hugging Face returned 403 on 2026-06-10 | run `HF_TOKEN=... make benchmark-compose-ultravox` after Llama access is granted | blocked | blocked | blocked | blocked |

Use the matrix as the source of truth for which backends have checked-in numbers. A backend should move to `validated artifact` only after its JSON output is committed under `docs/benchmark-results/` and the measured results section below is updated from that artifact. Blocked rows should name the exact external access or runtime failure observed during the 10-sample target run.

## Latest Validated Runs

### Faster-Whisper CPU Baselines

Measured on June 10, 2026 with the local benchmark harness.

Environment:

- Host: macOS 26.5.1 arm64
- Python benchmark client: 3.13.12
- Backend: `faster-whisper`
- Models: `base.en` and `small.en`
- Device: CPU / `int8`
- Samples: 10, with 5 REST runs per sample and one streaming session per sample
- Streaming chunk size: 250 ms
- Streaming partial window: 2.0 s
- Audio: 7.28 s synthesized speech clip generated locally with `say`
- Reference transcript: `The quick brown fox jumps over the lazy dog. This is a realtime ASR latency benchmark for the rtc asr service.`

Measured results:

| Model | REST Mean / P95 | REST RTF | Streaming Partial Mean / P95 | Streaming Final Mean / P95 | Accuracy |
| --- | --- | ---: | --- | --- | --- |
| `base.en` | 573.3 ms / 741.1 ms | 0.079 | 553.0 ms / 2451.5 ms | 560.2 ms / 761.2 ms | WER 0.095 / CER 0.0 |
| `small.en` | 1378.3 ms / 1531.1 ms | 0.189 | 1023.2 ms / 1202.4 ms | 1420.6 ms / 1514.0 ms | WER 0.095 / CER 0.0 |

Representative transcripts:

```text
base.en: The quick brown fox jumps over the lazy dog, this is a real-time ASR latency benchmark for the RTC ASR service.
small.en: The quick brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTC ASR service.
```

Interpretation notes:

- `base.en` is the faster local baseline while still producing the same normalized WER/CER as the larger local model on this clip.
- `small.en` is the default local service model for more realistic scenarios, but it is about 2.4x slower than `base.en` on REST mean latency in this CPU run.
- The accuracy miss for both models is word-boundary normalization: `realtime` became `real-time`, which increases WER while leaving normalized CER at `0.0`.

Versioned artifacts:

- `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json`
- `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json`

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

- The measured Qwen CPU path is still substantially slower than the validated `faster-whisper` `base.en` and `small.en` CPU baselines, but it remained below real time across a longer synthesized utterance.
- The main accuracy miss is word-boundary normalization: `realtime` became `real-time`, which increases WER while leaving normalized CER at `0.0`.
- The very small `final_ms` value reflects that most of the work already happened during the streaming partial passes.

Versioned artifact:

- `docs/benchmark-results/qwen-compose-2026-06-08.json`

Refresh note:

- A 10-sample Qwen refresh was attempted on June 10, 2026 with `make benchmark-compose-qwen BENCHMARK_RESULT_DATE=2026-06-10` on port `8093`. The service reached `/ready`, then restarted during the first generation request and the benchmark client failed REST warmup after bounded retries with `httpx.ReadError`. No replacement artifact was committed from that failed run.

### Parakeet Compose CPU Baseline

Measured on June 10, 2026 against the Docker Compose stack.

Environment:

- Host: macOS 26.5.1 arm64
- Python benchmark client: 3.13.12
- Execution mode: `docker compose`
- Backend: `parakeet`
- Model: `nvidia/parakeet-tdt-0.6b-v3`
- Device: CPU / `float32`
- Samples: 10, with 5 REST runs per sample and one streaming session per sample
- Audio: 7.28 s synthesized speech clip from `say`
- Reference transcript: `The quick brown fox jumps over the lazy dog. This is a realtime ASR latency benchmark for the rtc asr service.`

Measured results:

- REST `POST /api/transcribe`: 2388.3 ms mean, 4098.1 ms p95, 1696.4 ms min, 4731.3 ms max
- REST real-time factor: 0.328
- WebSocket partial latency: 1715.1 ms mean, 2968.7 ms p95, 899.4 ms min, 5581.7 ms max
- WebSocket final latency after `stop`: 2215.8 ms mean, 3080.4 ms p95, 1792.3 ms min, 3080.4 ms max
- REST transcript: `The quick brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTC ASR service.`
- Streaming final transcript: `The quick brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTC ASR service.`
- Accuracy (normalized WER mean): `0.095`
- Accuracy (normalized CER mean): `0.0`

Interpretation notes:

- Parakeet was faster than the June 8 Qwen legacy snapshot on the same synthesized clip, but this is a 10-sample artifact while the checked-in Qwen result is still a legacy single-sample artifact.
- The accuracy miss matches Qwen: `realtime` became `real-time`, increasing WER while normalized CER remained `0.0`.

Versioned artifact:

- `docs/benchmark-results/parakeet-compose-2026-06-10.json`

## Reproduce

All benchmark targets now use `BENCHMARK_SAMPLE_COUNT=10` by default and write a dated JSON artifact under `docs/benchmark-results/`. Override `BENCHMARK_SAMPLE_COUNT` only for local smoke checks; leave it at 10 for committed matrix results. Override `BENCHMARK_RESULT_DATE` when you want a stable filename during repeated local runs.

### Full Compose Matrix

Run every Docker Compose backend with the same 10-sample contract:

```bash
make benchmark-compose-matrix
```

This expands to `benchmark-compose-qwen`, `benchmark-compose-parakeet`, and `benchmark-compose-ultravox`. Each target emits REST mean/p95, streaming partial mean/p95, streaming final mean/p95, and WER/CER accuracy summaries in its JSON artifact. Ultravox still requires `HF_TOKEN` or `HUGGINGFACE_HUB_TOKEN` because the default weights are gated.

### Faster-Whisper Baseline

Run both local faster-whisper baselines with 10 samples per model:

```bash
make benchmark-faster-whisper-matrix
```

Run only the default local service model:

```bash
make benchmark
```

Or invoke the harness directly against an already-running server:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8090 \
  --ws-url ws://127.0.0.1:8090/ws/stream \
  --model small.en \
  --compute-type int8 \
  --sample-count 10 \
  --output docs/benchmark-results/faster-whisper-small.en-int8-$(date -u +%Y-%m-%d).json
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
- `--request-retries 5` and `--request-retry-delay 5.0` tune bounded REST retries for cold Compose runs.
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

- checked-in validated Ultravox CPU result artifact, blocked until the benchmark token has access to `meta-llama/Llama-3.1-8B-Instruct`
- refreshed 10-sample Qwen artifact; the June 10 refresh attempt restarted during first generation and failed REST warmup with `httpx.ReadError`
- concurrent REST or WebSocket load
- GPU-backed Qwen, Parakeet, or Ultravox measurements
- memory and CPU saturation curves
- corpus-level WER across more than a single synthesized utterance
- longer multi-turn streaming sessions
