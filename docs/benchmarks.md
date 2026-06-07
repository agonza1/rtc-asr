# Performance Benchmarks

Measured on June 3, 2026 with the checked-in `tests/benchmark.py` harness. These figures validate the current single-node latency baseline for the `faster-whisper` `tiny.en` CPU path; they are not a substitute for broader load, GPU, or accuracy testing.

## Latest Baseline

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

```
the quick-brown fox jumps over the lazy dog. This is a real-time ASR latency benchmark for the RTCSR service.
```

## Reproduce

Run the existing faster-whisper baseline locally:

```bash
make benchmark
```

Invoke the harness directly against an already-running server:

```bash
.venv/bin/python tests/benchmark.py --url http://127.0.0.1:8090 --ws-url ws://127.0.0.1:8090/ws/stream
```

Benchmark Qwen side-by-side with the whisper path by letting the harness spawn each backend with explicit settings:

```bash
.venv/bin/python tests/benchmark.py --spawn-server --backend faster-whisper --model tiny.en --device cpu --compute-type int8
.venv/bin/python tests/benchmark.py --spawn-server --backend qwen-asr --model Qwen/Qwen3-ASR-0.6B --device cpu --qwen-dtype float32
```

Useful options:

- `--audio-file /path/to/sample.wav` to benchmark a specific clip
- `--chunk-ms 100` to test a tighter streaming cadence
- `--spawn-server` to let the harness boot a local uvicorn server
- `--backend qwen-asr` to compare the alternate backend with the same harness
- `--device cuda` to measure GPU-backed runs once the host is provisioned
- `--partial-window 1.0` to compare a smaller streaming window

## Interpretation

These numbers are low-latency enough for the current MVP path because the rolling-window stream keeps the first and last partials in the same band across the full 7.28 s utterance instead of drifting upward with buffer length. Interim latency stays around 130-180 ms for most chunks, while the final result still uses the full buffered utterance.

## Remaining Gaps

Still not covered by this document:

- Concurrent REST or WebSocket load
- GPU-specific measurements
- Memory and CPU saturation curves
- Accuracy / WER against a labeled corpus
- Longer multi-turn streaming sessions
