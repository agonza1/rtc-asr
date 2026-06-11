# Low-Latency ASR Benchmarks

The GitHub Pages homepage at `docs/index.html` reads `docs/benchmark-results/manifest.json` and renders a public low-latency ASR dashboard with ranking, derived operator scores, and a homepage comparison flow limited to publishable artifacts. The manifest is built from two checked-in sources of truth:

- benchmark artifacts under `docs/benchmark-results/*.json`
- the tracked benchmark registry in `docs/benchmark-results/tracks.json`

Run `make benchmark-site` after changing either source so the homepage and this document stay aligned.

## Benchmark Lane Registry

| Track | Backend | Model | Lane | Runtime | Status | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `faster-whisper-base` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json` |
| `faster-whisper-base-c80-w075-json-preview` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | legacy preview artifact | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `faster-whisper-small` | `faster-whisper` | `small.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-compose` | `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `parakeet-nemo-compose` | `parakeet-nemo` | `nvidia/parakeet-tdt_ctc-110m` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `qwen-mps` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Local Python Apple Silicon | `mps / auto` | validated artifact | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `qwen-compose` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU | `cpu / float32` | validated legacy artifact | `docs/benchmark-results/qwen-compose-2026-06-08.json` |
| `ultravox-compose` | `ultravox` | `fixie-ai/ultravox-v0_6-llama-3_1-8b` | Docker Compose CPU | `cpu / float32` | blocked | no committed artifact |

Status details from the track registry:

- `faster-whisper-base`: validated 10-sample local CPU baseline.
- `faster-whisper-base-c80-w075-json-preview`: exploratory 1-sample low-latency preview at `80 ms` chunks and a `0.75 s` partial window; first visible partial arrived at `1.7 s`, but finalization remained extremely slow at about `46.9 s`.
- `faster-whisper-small`: validated 10-sample local CPU baseline using the default service model.
- `parakeet-compose`: validated 10-sample Compose CPU artifact.
- `parakeet-nemo-compose`: validated 10-sample Compose CPU artifact with an 8-chunk partial cadence.
- `qwen-mps`: validated 10-sample local Apple Silicon MPS artifact.
- `qwen-compose`: single-sample legacy artifact remains published because the June 10, 2026 refresh restarted during first generation and REST warmup failed with `httpx.ReadError`.
- `ultravox-compose`: blocked before validation because the default model loads gated `meta-llama/Llama-3.1-8B-Instruct` weights and Hugging Face returned `403` on June 10, 2026.

## Current Artifact-Backed Comparison

These rows match the current manifest entries used on the homepage.

| Track | Samples | REST Mean / P95 | REST RTF | Partial Mean / P95 | Final Mean / P95 | Accuracy | Artifact |
| --- | ---: | --- | ---: | --- | --- | --- | --- |
| `parakeet-nemo-compose` | 10 | 331.4 ms / 511.5 ms | 0.046 | 148.5 ms / 245.8 ms | 379.0 ms / 633.5 ms | WER 0.190 / CER 0.000 | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `faster-whisper-base-c80-w075-json-preview` | 1 | 537.4 ms / 537.4 ms | 0.074 | 15.4 ms / 15.4 ms | 46867.0 ms / 46867.0 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `faster-whisper-base` | 10 | 573.3 ms / 741.1 ms | 0.079 | 553.0 ms / 2451.5 ms | 560.2 ms / 761.2 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json` |
| `qwen-mps` | 10 | 1186.2 ms / 1261.2 ms | 0.163 | 352.0 ms / 445.5 ms | 1189.6 ms / 1248.2 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `faster-whisper-small` | 10 | 1378.3 ms / 1531.1 ms | 0.189 | 1023.2 ms / 1202.4 ms | 1420.6 ms / 1514.0 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-compose` | 10 | 2388.3 ms / 4098.1 ms | 0.328 | 1715.1 ms / 2968.7 ms | 2215.8 ms / 3080.4 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `qwen-compose` | 1 | 5482.2 ms / 5904.4 ms | 0.753 | 3696.1 ms / 6314.4 ms | 0.9 ms / 0.9 ms | WER 0.095 / CER 0.000 | `docs/benchmark-results/qwen-compose-2026-06-08.json` |

## Reproduce

Default artifact contract:

- `BENCHMARK_SAMPLE_COUNT=10`
- 5 REST runs per sample
- `250 ms` streaming chunks
- `partial_interval_chunks=1`
- `partial_window_seconds=2.0`
- `partial_event_timeout_seconds=0.1`
- JSON/base64 websocket framing by default (`BENCHMARK_BINARY_FRAMES` disabled)
- JSON output checked into `docs/benchmark-results/`

The tracked registry in `docs/benchmark-results/tracks.json` now also records the recommended low-latency sweep matrix:

- `chunk_ms`: `40`, `60`, `80`, `100`, `160`, `250`
- `partial_window_seconds`: `0.5`, `0.75`, `1.0`, `2.0`
- `binary_frames`: `false`, `true`

A repeatable starter sweep is wired into the Makefile for the fastest local lane:

```bash
make benchmark-faster-whisper-base-low-latency-sweep
```

That target currently defaults to a smaller exploratory contract (`5` samples, `3` REST runs) across `60/80/100 ms` chunks, `0.5/0.75/1.0 s` partial windows, and both websocket frame modes so fresh publishable artifacts can be generated without hand-editing commands.

Run the local baseline benchmarks:

```bash
make benchmark-faster-whisper-matrix
make benchmark-qwen-mps
```

Run the Compose CPU baselines that currently have checked-in artifacts:

```bash
make benchmark-compose-parakeet
make benchmark-compose-parakeet-nemo BENCHMARK_RESULT_DATE=2026-06-09
make benchmark-compose-qwen
```

Attempt the blocked Ultravox lane once access is available:

```bash
HF_TOKEN=... make benchmark-compose-ultravox
```

Benchmark artifacts now include extra streaming responsiveness metrics for low-latency analysis:

- `first_partial_end_to_end_*`: when a caller could first see a useful partial in real time
- `partial_gap_*`: cadence between visible partial updates
- `time_to_final_from_audio_end_ms`: finalization delay after audio stops

Rebuild the homepage manifest after artifact or track changes:

```bash
make benchmark-site
```
