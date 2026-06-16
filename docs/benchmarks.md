# Low-Latency ASR Benchmarks

The GitHub Pages homepage at `docs/index.html` reads `docs/benchmark-results/manifest.json` and renders a public low-latency ASR dashboard with ranking, derived operator scores, and a homepage comparison flow limited to publishable artifacts. The manifest is built from two checked-in sources of truth:

- benchmark artifacts under `docs/benchmark-results/*.json`
- the tracked benchmark registry in `docs/benchmark-results/tracks.json`

Run `make benchmark-site` after changing either source so the homepage and this document stay aligned. The homepage stays latency-first, and this notes page carries the issue #46 methodology decision about how reference WER should be labeled until the repo has its own reproducible quality track.

## Accuracy Publishing Policy

Issue #46 resolves to a simple public-facing rule:

- The homepage comparison stays latency-first and should not show reference WER in the primary ranking table.
- WER/CER should appear only when backed by an annotated, reproducible benchmark dataset and a repo-owned evaluation recipe. Local smoke clips and exploratory sweeps are useful for latency debugging, but they are not a publishable source of truth for accuracy.
- When official accuracy coverage lands, keep it on a separate methodology/details surface first instead of turning the latency ranking into an official repo accuracy claim.
- Upstream model-card WER is useful as background research, but it is not an official rtc-asr measurement and should be labeled as external reference data that may vary slightly across hardware, runtime, quantization, decoding, and setup.

Recommended source-of-truth path for this repo:

- Start with reproducible clean/reference corpora such as FLEURS `en_us` and a pinned Common Voice English test split so runs can be repeated and labeled ground truth is explicit.
- Treat telephony/noisy evaluation as a second methodology track. Candidate follow-ups that better reflect real-world degradation are Earnings-22 for accented long-form speech and CHiME-style noisy/far-field sets for robustness, but they should remain separate from the core latency matrix.
- If codec/noise degradation is added, publish the augmentation recipe as its own benchmark lane instead of blending it into the clean/reference leaderboard.
- Keep every published accuracy result tied to a named dataset, a checked-in run artifact, and documented preprocessing so readers can tell official benchmark runs apart from local preview experiments.

## Recommended Quality Methodology

Recommended publish order:

1. Add a small, reproducible reference-quality track that reports WER only on annotated public test data, with the exact dataset version, split, text normalization rules, and scoring command checked into the repo.
2. Keep the homepage ranking latency-first and publish reference WER only on the benchmark notes or artifact detail pages.
3. Add robustness tracks only after the clean/reference track is stable and reproducible.

Suggested datasets and boundaries:

- Core reference track: FLEURS English plus a pinned Common Voice English test split. These are easy to name, version, rerun, and explain.
- Real-world robustness track: Earnings-22 for accented long-form audio.
- Noise and distant-speech track: CHiME-style official sets, published separately because far-field noise robustness is a different question than buffered websocket latency.
- Telephony or codec degradation track: derived from an annotated source set with a checked-in degradation recipe, never mixed into the clean/reference score.

Required methodology fields for any future published WER:

- dataset name, version, split, and filtering rules
- transcript normalization rules
- segmentation policy for long-form audio
- exact evaluation command and scorer
- checked-in JSON artifact path and benchmark date
- note that the result is a dataset evaluation, not a direct proxy for homepage latency behavior

## Benchmark Lane Registry

| Track | Backend | Model | Lane | Runtime | Status | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `faster-whisper-base` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-15.json` |
| `faster-whisper-base-c80-w075-json-preview` | `faster-whisper` | `base.en` | Local Python CPU Sweep Preview | `cpu / int8` | preview artifact | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `pipecat-e2e-faster-whisper-base` | `faster-whisper` | `base.en` | Pipecat E2E Local Python CPU | `cpu / int8` | blocked integration artifact | `docs/benchmark-results/faster-whisper-base.en-int8-pipecat-e2e-2026-06-13.json` |
| `faster-whisper-small` | `faster-whisper` | `small.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-compose` | `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `parakeet-nemo-compose` | `parakeet-nemo` | `nvidia/parakeet-tdt_ctc-110m` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `parakeet-mlx-service-110m` | `parakeet-mlx` | `mlx-community/parakeet-tdt_ctc-110m` | Local Python Apple Silicon MLX Service | `apple-silicon / auto` | validated artifact | `docs/benchmark-results/parakeet-mlx-110m-service-2026-06-13.json` |
| `parakeet-mlx` | `parakeet-mlx` | `mlx-community/parakeet-tdt-0.6b-v3` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-mlx-110m` | `parakeet-mlx` | `mlx-community/parakeet-tdt_ctc-110m` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `qwen-mps` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Local Python Apple Silicon | `mps / auto` | validated artifact | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `qwen-compose` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU | `cpu / float16` | validated artifact | `docs/benchmark-results/qwen-compose-2026-06-15.json` |

Status details from the track registry:

- `faster-whisper-base`: validated 10-sample local CPU baseline refreshed on `2026-06-15` with a preloaded model.
- `faster-whisper-base-c80-w075-json-preview`: preview low-latency sweep artifact for the `80 ms` chunk / `0.75 s` partial-window JSON framing variant.
- `pipecat-e2e-faster-whisper-base`: checked-in single-sample Pipecat E2E artifact using `20 ms` source frames bridged into `100 ms` websocket chunks; kept off the homepage until comparable E2E lanes exist.
- `faster-whisper-small`: validated 10-sample local CPU baseline using the default service model.
- `parakeet-compose`: validated 10-sample Compose CPU artifact.
- `parakeet-nemo-compose`: validated 10-sample Compose CPU artifact with an 8-chunk partial cadence.
- `parakeet-mlx-service-110m`: validated 10-sample local Apple Silicon MLX service artifact using the shared REST and websocket harness; its `141.9 ms` REST mean keeps the warmed service lane grounded to the checked-in artifact.
- `parakeet-mlx`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt-0.6b-v3`; its `1971.9 ms` mean latency reflects the checked-in cold CLI preview.
- `parakeet-mlx-110m`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt_ctc-110m`; its `1360.7 ms` mean latency reflects the checked-in cold CLI preview.
- `qwen-mps`: validated 10-sample local Apple Silicon MPS artifact.
- `qwen-compose`: validated 5-sample Compose CPU artifact using `float16`, `3` REST runs per sample, and an `8`-chunk partial cadence.

## Current Artifact-Backed Comparison

These rows match the current manifest entries used on the homepage, plus two doc-only Parakeet MLX CLI preview artifacts. Every distinct runtime setup keeps its own row here, even when multiple lanes share the same underlying model or reference WER. Read the streaming fields first: first visible partial, partial cadence, and audio-end finalization are the operator-facing responsiveness signals. `REST Mean` and `REST RTF` stay here as throughput context for the same backend, but they are not the main live turn-taking score because total file time scales with clip duration. The `Reference WER` column is different: it is external source data for the underlying model, not an official rtc-asr measurement, and it may vary slightly across hardware, runtime, quantization, decoding, and setup. The new `parakeet-mlx-service-110m` row is the warmed service-style counterpart to the earlier cold CLI preview.

| Track | Samples | REST Mean / P95 | REST RTF | Partial Mean / P95 | Audio-end Final / P95 | Reference WER | Artifact |
| --- | ---: | --- | ---: | --- | --- | --- | --- |
| `parakeet-mlx-service-110m` | 10 | 141.9 ms / 170.0 ms | 0.020 | 74.5 ms / 96.9 ms | 210.6 ms / 246.3 ms | `2.4 / 5.2` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt_ctc-110m` via the upstream `nvidia/parakeet-tdt_ctc-110m` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-mlx-110m-service-2026-06-13.json` |
| `parakeet-nemo-compose` | 10 | 331.4 ms / 511.5 ms | 0.046 | 148.5 ms / 245.8 ms | 379.0 ms / 633.5 ms | `2.4 / 5.2` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt_ctc-110m` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-09.json` |
| `faster-whisper-base` | 10 | 558.4 ms / 726.1 ms | 0.077 | 12134.1 ms / 16250.0 ms | 13498.8 ms / 15429.3 ms | `4.25 / 10.35` on LibriSpeech `clean / other` for `openai/whisper-base.en` ([HF discussion diff](https://huggingface.co/openai/whisper-base.en/discussions/18/files)) | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-15.json` |
| `qwen-mps` | 10 | 1186.2 ms / 1261.2 ms | 0.163 | 352.0 ms / 445.5 ms | 1189.6 ms / 1248.2 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-mps-2026-06-10.json` |
| `faster-whisper-small` | 10 | 1378.3 ms / 1531.1 ms | 0.189 | 1023.2 ms / 1202.4 ms | 1420.6 ms / 1514.0 ms | `3.05 / 7.25` on LibriSpeech `clean / other` for `openai/whisper-small.en` ([HF discussion diff](https://huggingface.co/openai/whisper-small.en/discussions/17/files)) | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-mlx-110m` | 3 | 1360.7 ms / 1716.2 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `2.4 / 5.2` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt_ctc-110m` via the upstream `nvidia/parakeet-tdt_ctc-110m` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `parakeet-mlx` | 3 | 1971.9 ms / 2595.8 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `1.93 / 3.59` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt-0.6b-v3` via the upstream `nvidia/parakeet-tdt-0.6b-v3` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-compose` | 10 | 2388.3 ms / 4098.1 ms | 0.328 | 1715.1 ms / 2968.7 ms | 2215.8 ms / 3080.4 ms | `1.93 / 3.59` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt-0.6b-v3` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-compose-2026-06-10.json` |
| `qwen-compose` | 5 | 3799.0 ms / 4475.0 ms | 0.522 | 3118.4 ms / 4677.0 ms | 7318.6 ms / 8168.1 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-compose-2026-06-15.json` |

Notes:

- Treat the homepage and detail pages as the primary place to judge streaming responsiveness: `first_partial_end_to_end_*`, `partial_gap_*`, and `time_to_final_from_audio_end_*` tell the real turn-taking story more directly than raw end-to-end file duration.
- `Audio-end Final` is not TTFT and not total file transcription time. It is the delay from audio end (or `stop`) until the final transcript arrives.
- These WER references are external model-level benchmarks. They are not official rtc-asr measurements and may vary slightly across hardware, runtime, quantization, decoding, chunk/window cadence, websocket framing, warmup state, and transport overhead.
- The `parakeet-mlx` and `parakeet-mlx-110m` rows are local CLI preview artifacts rather than running websocket service benchmarks, so only end-to-end latency is available today; the service-style RTF, partial, and final columns are intentionally left `n/a`, and those preview rows are still kept outside `docs/benchmark-results/manifest.json` and the homepage leaderboard.
- The `parakeet-mlx-service-110m` row is the warmed service-style Apple Silicon MLX lane for the same 110M model, which makes it the right comparison point against `parakeet-nemo-compose` when you want steady-state runtime behavior instead of cold CLI startup cost.
- local diagnostic WER from our small internal sample set remains intentionally unpublished.

## Pipecat E2E Integration Track

This repo now keeps Pipecat end-to-end results as a separate integration lane instead of mixing them into the backend-only homepage leaderboard. The checked-in artifact below uses a local `faster-whisper` base lane with `20 ms` Pipecat-style source frames aggregated into `100 ms` websocket chunks. That lets us capture metrics the homepage does not currently rank on its own: first useful partial timing, partial cadence/jitter, final closeout after audio end, and missing partial counts across the bridge.

| Track | Samples | First Visible Partial | Partial Mean / P95 | Partial Gap Mean / P95 | Audio-end Final | Missing Partials | Artifact |
| --- | ---: | --- | --- | --- | --- | ---: | --- |
| `pipecat-e2e-faster-whisper-base` | 1 | 564.8 ms | 29.7 ms / 64.8 ms | 367.9 ms / 658.9 ms | 22619.0 ms | 37 | `docs/benchmark-results/faster-whisper-base.en-int8-pipecat-e2e-2026-06-13.json` |

The artifact stays tracked in `docs/benchmark-results/tracks.json`, but it is intentionally excluded from `docs/index.html` because there is only one Pipecat E2E lane today. That keeps backend-only and integration-level claims separate until there are comparable E2E artifacts across multiple backends.

## Recommended Low-Power Profiling Fields

The current checked-in artifacts already cover warmed service latency, first visible partial timing, finalization delay, and `RTF`. For low-power claims, add these fields to each benchmark lane as the next step:

- device, CPU, and RAM
- accelerator type: none, MPS, MLX, CUDA, or NPU
- wall latency: REST mean and P95, first partial, and final
- peak RSS memory
- CPU utilization
- package power when available
- sustained thermal behavior over `5` to `10` minutes
- dropped or late frames for bridged RTC lanes
- transcript churn across partial updates, including per-revision churn ratios

When testing buffered websocket ASR against RTC-shaped traffic, start with separate lanes for `80`, `100`, `160`, and `200` ms websocket chunks. Sweep `partial_window_seconds` across `0.75`, `1.0`, `1.5`, and `2.0` seconds when you want to compare responsiveness against transcript stability.

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

- `chunk_ms`: `80`, `100`, `160`, `200`
- `partial_window_seconds`: `0.75`, `1.0`, `1.5`, `2.0`
- `binary_frames`: `false`

A repeatable all-model sweep is wired into the Makefile:

```bash
make benchmark-all-asr-low-latency-sweep
```

That aggregate target always fans out to the faster-whisper base/small local sweeps plus the qwen/parakeet/parakeet-nemo Compose CPU sweeps. On macOS it also includes the qwen MPS sweep; on non-Apple hosts the MPS-only lane is skipped so the portable CPU matrix can still complete. Each sweep uses the same smaller exploratory contract (`5` samples, `3` REST runs) across `80/100/160/200 ms` chunks and `0.75/1.0/1.5/2.0 s` partial windows so the benchmark matrix stays consistent across all published ASR lanes.

Run the local baseline benchmarks:

```bash
make benchmark-faster-whisper-matrix
make benchmark-qwen-mps
make benchmark-parakeet-mlx
make benchmark-parakeet-mlx-110m
make benchmark-parakeet-mlx-service-110m
make benchmark-all-asr-low-latency-sweep
```

All checked-in service benchmarks are expected to run with the model preloaded. The shared `tests/benchmark.py` harness now enforces that default in two ways: spawned local servers start with `ASR_PRELOAD_MODEL=true`, and external-service runs fail unless `/api/models` reports `preload_enabled=true`. Only use `--allow-unpreloaded-service` for intentional cold-start diagnostics that should stay out of the main comparison lanes.

Run the Compose CPU baselines that currently have checked-in artifacts:

```bash
make benchmark-compose-parakeet
make benchmark-compose-parakeet-nemo BENCHMARK_RESULT_DATE=2026-06-09
BENCHMARK_SAMPLE_COUNT=5 BENCHMARK_REST_RUNS=3 BENCHMARK_PARTIAL_INTERVAL_CHUNKS=8 QWEN_COMPOSE_DTYPE=float16 BENCHMARK_RESULT_DATE=2026-06-15 make benchmark-compose-qwen
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
