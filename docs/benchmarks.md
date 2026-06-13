# Low-Latency ASR Benchmarks

The GitHub Pages homepage at `docs/index.html` reads `docs/benchmark-results/manifest.json` and renders a public low-latency ASR dashboard with ranking, derived operator scores, and a homepage comparison flow limited to publishable artifacts. The manifest is built from two checked-in sources of truth:

- benchmark artifacts under `docs/benchmark-results/*.json`
- the tracked benchmark registry in `docs/benchmark-results/tracks.json`

Run `make benchmark-site` after changing either source so the homepage and this document stay aligned. The homepage stays latency-first, while this notes page can add official benchmark WER references once they are clearly labeled as upstream model-card data rather than repo-measured runs.

## Accuracy Publishing Policy

Issue #46 resolves to a simple public-facing rule:

- The homepage comparison stays latency-first. It should rank and compare only streaming/REST responsiveness, stability, and sample coverage from checked-in artifacts.
- WER/CER should appear only when backed by an annotated, reproducible benchmark dataset. Local smoke clips and exploratory sweeps are useful for latency debugging, but they are not a publishable source of truth for accuracy.
- When official accuracy coverage lands, keep it on a methodology/details surface first, with the homepage linking out rather than mixing unofficial and official quality numbers in the same primary table.
- On this page, WER/CER can appear only as clearly labeled upstream benchmark references tied to a named Hugging Face model card, benchmark dataset, and source link. They are not substitutes for checked-in repo evaluation artifacts.

Recommended source-of-truth path for this repo:

- Start with reproducible clean/reference corpora such as Common Voice or FLEURS so runs can be repeated and labeled ground truth is explicit.
- Treat telephony/noisy evaluation as a second methodology track. If we add codec/noise degradation, publish it as a separate benchmark lane with its own notes instead of blending it into the clean/reference leaderboard.
- Keep every published accuracy result tied to a named dataset, a checked-in run artifact, and documented preprocessing so readers can tell official benchmark runs apart from local preview experiments.

## Benchmark Lane Registry

| Track | Backend | Model | Lane | Runtime | Status | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `faster-whisper-base` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json` |
| `pipecat-e2e-faster-whisper-base` | `faster-whisper` | `base.en` | Pipecat E2E Local Python CPU | `cpu / int8` | blocked integration artifact | `docs/benchmark-results/faster-whisper-base.en-int8-pipecat-e2e-2026-06-13.json` |
| `faster-whisper-base-c80-w075-json-preview` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | legacy preview artifact | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `faster-whisper-small` | `faster-whisper` | `small.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-compose` | `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `parakeet-nemo-compose` | `parakeet-nemo` | `nvidia/parakeet-tdt_ctc-110m` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `parakeet-mlx` | `parakeet-mlx` | `mlx-community/parakeet-tdt-0.6b-v3` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-mlx-110m` | `parakeet-mlx` | `mlx-community/parakeet-tdt_ctc-110m` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `qwen-mps` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Local Python Apple Silicon | `mps / auto` | validated artifact | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `qwen-compose` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU | `cpu / float32` | validated legacy artifact | `docs/benchmark-results/qwen-compose-2026-06-08.json` |

Status details from the track registry:

- `faster-whisper-base`: validated 10-sample local CPU baseline.
- `pipecat-e2e-faster-whisper-base`: checked-in single-sample Pipecat E2E artifact using `20 ms` source frames bridged into `100 ms` websocket chunks; intentionally kept off the homepage until more E2E lanes exist.
- `faster-whisper-base-c80-w075-json-preview`: exploratory 1-sample low-latency preview at `80 ms` chunks and a `0.75 s` partial window; first visible partial arrived at `1.7 s`, but finalization remained extremely slow at about `46.9 s`.
- `faster-whisper-small`: validated 10-sample local CPU baseline using the default service model.
- `parakeet-compose`: validated 10-sample Compose CPU artifact.
- `parakeet-nemo-compose`: validated 10-sample Compose CPU artifact with an 8-chunk partial cadence.
- `parakeet-mlx`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt-0.6b-v3`, documented here ahead of track registration; its `1971.9 ms` mean latency is faster than the `parakeet-compose` CPU lane (`2388.3 ms`) but slower than the `parakeet-nemo-compose` CPU lane (`331.4 ms`).
- `parakeet-mlx-110m`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt_ctc-110m`, documented here ahead of track registration; its `1360.7 ms` mean latency is faster than both `parakeet-compose` CPU (`2388.3 ms`) and `parakeet-mlx` 0.6B MLX (`1971.9 ms`), but slower than the `parakeet-nemo-compose` CPU lane (`331.4 ms`).
- `qwen-mps`: validated 10-sample local Apple Silicon MPS artifact.
- `qwen-compose`: single-sample legacy artifact remains published because the June 10, 2026 refresh restarted during first generation and REST warmup failed with `httpx.ReadError`.

## Current Artifact-Backed Comparison

These rows match the current manifest entries used on the homepage, plus two doc-only Parakeet MLX CLI preview artifacts. Every distinct runtime setup keeps its own row here, even when multiple lanes share the same underlying model or upstream WER reference. The latency and throughput fields come from checked-in repo artifacts. The `Official WER reference` column is different: it points to upstream Hugging Face benchmark/model-card numbers for the underlying model, not to repo-measured runs. That keeps local latency claims separate from external quality claims while still giving readers a public benchmark anchor.

| Track | Samples | REST Mean / P95 | REST RTF | Partial Mean / P95 | Final Mean / P95 | Official WER reference | Artifact |
| --- | ---: | --- | ---: | --- | --- | --- | --- |
| `parakeet-nemo-compose` | 10 | 331.4 ms / 511.5 ms | 0.046 | 148.5 ms / 245.8 ms | 379.0 ms / 633.5 ms | `2.4 / 5.2` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt_ctc-110m` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `faster-whisper-base-c80-w075-json-preview` | 1 | 537.4 ms / 537.4 ms | 0.074 | 15.4 ms / 15.4 ms | 46867.0 ms / 46867.0 ms | `4.25 / 10.35` on LibriSpeech `clean / other` for `openai/whisper-base.en` ([HF discussion diff](https://huggingface.co/openai/whisper-base.en/discussions/18/files)) | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `faster-whisper-base` | 10 | 573.3 ms / 741.1 ms | 0.079 | 553.0 ms / 2451.5 ms | 560.2 ms / 761.2 ms | `4.25 / 10.35` on LibriSpeech `clean / other` for `openai/whisper-base.en` ([HF discussion diff](https://huggingface.co/openai/whisper-base.en/discussions/18/files)) | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-10.json` |
| `qwen-mps` | 10 | 1186.2 ms / 1261.2 ms | 0.163 | 352.0 ms / 445.5 ms | 1189.6 ms / 1248.2 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `faster-whisper-small` | 10 | 1378.3 ms / 1531.1 ms | 0.189 | 1023.2 ms / 1202.4 ms | 1420.6 ms / 1514.0 ms | `3.05 / 7.25` on LibriSpeech `clean / other` for `openai/whisper-small.en` ([HF discussion diff](https://huggingface.co/openai/whisper-small.en/discussions/17/files)) | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-mlx-110m` | 3 | 1360.7 ms / 1716.2 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `2.4 / 5.2` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt_ctc-110m` via the upstream `nvidia/parakeet-tdt_ctc-110m` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `parakeet-mlx` | 3 | 1971.9 ms / 2595.8 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `1.93 / 3.59` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt-0.6b-v3` via the upstream `nvidia/parakeet-tdt-0.6b-v3` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-compose` | 10 | 2388.3 ms / 4098.1 ms | 0.328 | 1715.1 ms / 2968.7 ms | 2215.8 ms / 3080.4 ms | `1.93 / 3.59` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt-0.6b-v3` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `qwen-compose` | 1 | 5482.2 ms / 5904.4 ms | 0.753 | 3696.1 ms / 6314.4 ms | 0.9 ms / 0.9 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-compose-2026-06-08.json` |

Notes:

- These WER references are model-level upstream benchmarks. They do not capture this repo's runtime choices such as CPU vs MPS, chunk/window cadence, websocket framing, warmup state, or transport overhead.
- The `parakeet-mlx` and `parakeet-mlx-110m` rows are local CLI preview artifacts rather than running websocket service benchmarks, so only end-to-end latency is available today; the service-style RTF, partial, and final columns are intentionally left `n/a`, and those rows are not yet part of `docs/benchmark-results/manifest.json` or the homepage leaderboard.
- The two `faster-whisper-base*` rows share the same Hugging Face WER reference because they use the same `openai/whisper-base.en` backbone under different local serving settings.
- The docs now surface official benchmark references only; local diagnostic WER from our small internal sample set remains intentionally unpublished.

## Pipecat E2E Integration Track

This repo now keeps Pipecat end-to-end results as a separate integration lane instead of mixing them into the backend-only homepage leaderboard. The checked-in artifact below uses a local `faster-whisper` base lane with `20 ms` Pipecat-style source frames aggregated into `100 ms` websocket chunks. That lets us capture metrics the homepage does not currently rank on its own: first useful partial timing, partial cadence/jitter, final closeout after audio end, and missing partial counts across the bridge.

| Track | Samples | First Visible Partial | Partial Mean / P95 | Partial Gap Mean / P95 | Final Mean | Missing Partials | Artifact |
| --- | ---: | --- | --- | --- | --- | ---: | --- |
| `pipecat-e2e-faster-whisper-base` | 1 | 564.8 ms | 29.7 ms / 64.8 ms | 367.9 ms / 658.9 ms | 22619.0 ms | 37 | `docs/benchmark-results/faster-whisper-base.en-int8-pipecat-e2e-2026-06-13.json` |

The artifact stays tracked in `docs/benchmark-results/tracks.json`, but it is intentionally excluded from `docs/index.html` because there is only one Pipecat E2E lane today. That keeps backend-only and integration-level claims separate until there are comparable E2E artifacts across multiple backends.

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

- `chunk_ms`: `80`, `100`, `200`, `250`
- `partial_window_seconds`: `1.0`, `2.0`
- `binary_frames`: `false`

A repeatable all-model sweep is wired into the Makefile:

```bash
make benchmark-all-asr-low-latency-sweep
```

That aggregate target always fans out to the faster-whisper base/small local sweeps plus the qwen/parakeet/parakeet-nemo Compose CPU sweeps. On macOS it also includes the qwen MPS sweep; on non-Apple hosts the MPS-only lane is skipped so the portable CPU matrix can still complete. Each sweep uses the same smaller exploratory contract (`5` samples, `3` REST runs) across `80/100/200/250 ms` chunks and `1.0/2.0 s` partial windows so the benchmark matrix stays consistent across all published ASR lanes.

Run the local baseline benchmarks:

```bash
make benchmark-faster-whisper-matrix
make benchmark-qwen-mps
make benchmark-parakeet-mlx
make benchmark-parakeet-mlx-110m
make benchmark-all-asr-low-latency-sweep
```

Run the Compose CPU baselines that currently have checked-in artifacts:

```bash
make benchmark-compose-parakeet
make benchmark-compose-parakeet-nemo BENCHMARK_RESULT_DATE=2026-06-09
make benchmark-compose-qwen
```


Benchmark artifacts now include extra streaming responsiveness metrics for low-latency analysis:

- `first_partial_end_to_end_*`: when a caller could first see a useful partial in real time
- `partial_gap_*`: cadence between visible partial updates
- `time_to_final_from_audio_end_ms`: per-sample finalization delay after audio stops
- `time_to_final_from_audio_end_*`: aggregated finalization delay summary used by the benchmark site (`final_*` remains a compatibility alias)

Rebuild the homepage manifest after artifact or track changes:

```bash
make benchmark-site
```
