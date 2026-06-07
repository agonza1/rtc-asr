# Performance Benchmarks

This page tracks validated single-node benchmark runs for the current `rtc-asr` service. The numbers below are measured results from the checked-in `tests/benchmark.py` harness; they are useful baselines, not universal performance guarantees.

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

Measured on June 7, 2026 against the Docker Compose stack.

Environment:

- Host: macOS 26.5.1 arm64
- Python benchmark client: 3.14.4
- Execution mode: `docker compose`
- Backend: `qwen-asr`
- Model: `Qwen/Qwen3-ASR-0.6B`
- Device: CPU / `float32`
- Audio: 2.587 s synthesized speech clip from `say`
- Reference transcript: `Quick benchmark phrase for rtc asr.`

Measured results:

- REST `POST /api/transcribe`: 1691.4 ms mean, 1692.5 ms p95, 1690.3 ms min, 1692.5 ms max
- REST real-time factor: 0.654
- WebSocket partial latency: 1349.7 ms mean, 1863.0 ms p95, 749.9 ms first partial, 1863.0 ms last partial
- WebSocket final latency after `stop`: 0.7 ms
- REST transcript: `Quick benchmark phrase for RTCASR.`
- Streaming final transcript: `Quick benchmark phrase for RTCASR.`
- Accuracy (normalized WER): `0.333`
- Accuracy (normalized CER): `0.0`

Interpretation notes:

- The measured Qwen CPU path is substantially slower than the `faster-whisper` `tiny.en` CPU baseline, but it stayed below real time for this short utterance.
- The transcript collapsed `rtc asr` into `RTCASR`, which counts as a one-token word-boundary miss in normalized WER while preserving the underlying character sequence, hence `CER=0.0`.
- The very small `final_ms` value reflects that most of the work already happened during the streaming partial passes.

Versioned artifact:

- `docs/benchmark-results/qwen-compose-2026-06-07.json`

## Reproduce

### Faster-Whisper Baseline

Run the existing local baseline:

```bash
make benchmark
```

Or invoke the harness directly against an already-running server:

```bash
.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8090 \
  --ws-url ws://127.0.0.1:8090/ws/stream
```

### Qwen Compose Baseline

Use the checked-in Compose workflow:

```bash
make benchmark-compose-qwen
```

What that target does:

- creates a writable local Hugging Face cache at `.cache/huggingface`
- builds the image with a CPU PyTorch wheel from the official PyTorch CPU index so Compose does not pull the much larger CUDA stack for the default CPU path
- starts `docker compose` with `ASR_BACKEND=qwen-asr`, `ASR_QWEN_MODEL=Qwen/Qwen3-ASR-0.6B`, `ASR_DEVICE=cpu`, and `ASR_QWEN_DTYPE=float32`
- waits for `GET /ready` to return `200`
- runs the benchmark client against `http://127.0.0.1:8080`

Equivalent manual commands:

```bash
mkdir -p .cache/huggingface
ASR_BACKEND=qwen-asr \
ASR_QWEN_MODEL=Qwen/Qwen3-ASR-0.6B \
ASR_DEVICE=cpu \
ASR_QWEN_DTYPE=float32 \
docker compose up -d --build

until curl -fsS http://127.0.0.1:8080/ready >/dev/null; do sleep 5; done

.venv/bin/python tests/benchmark.py \
  --url http://127.0.0.1:8080 \
  --ws-url ws://127.0.0.1:8080/ws/stream \
  --speech-text 'Quick benchmark phrase for rtc asr.' \
  --rest-runs 2 \
  --chunk-ms 1000
```

## Methodology Notes

- `tests/benchmark.py` now records simple accuracy metadata in addition to latency metrics.
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
