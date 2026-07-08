# Edge ASR Latency Benchmarks

The GitHub Pages homepage at `docs/index.html` reads `docs/benchmark-results/manifest.json` and renders a public low-latency ASR dashboard with ranking, derived operator scores, and a homepage comparison flow limited to publishable artifacts. These benchmarks are scoped to real-time voice AI on practical local inference targets: CPU sidecars, Docker Compose CPU lanes, and small Apple Silicon deployments. They are edge-device and colocated-runtime benchmarks, not claims about what the same models could do on high-power GPUs, cloud accelerators, or larger dedicated inference servers.

The manifest is built from two checked-in sources of truth:

- benchmark artifacts under `docs/benchmark-results/*.json`
- the tracked benchmark registry in `docs/benchmark-results/tracks.json`

Run `make benchmark-site` after changing either source so the homepage and this document stay aligned. The homepage stays latency-first for edge/local deployments, and this notes page labels external reference WER separately until the repo has its own reproducible quality track.

Current publication policy: checked-in `/ws/stream` artifacts remain visible only as legacy supporting evidence. Paced `/v1/stt/stream` artifacts with `streaming.live_metrics_comparable == true` now populate the primary live leaderboard as they are regenerated.

## Accuracy Note

The homepage ranking is latency-first. Reference WER is shown only as external model-card or upstream benchmark context, not as an official rtc-asr accuracy claim.

Official WER/CER results should appear only after they are tied to a named dataset, a repo-owned evaluation recipe, and a checked-in run artifact.

## Scope Note

Use these results to choose a realistic local ASR lane for WebRTC and voice-agent turn-taking when the service is running near the media pipeline. A workstation GPU, datacenter accelerator, or tuned hosted inference stack may make slower local lanes perform much better than they do here. Those results should be published as separate high-power tracks instead of being mixed into the edge/local leaderboard.

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
| `faster-whisper-base` | `faster-whisper` | `base.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-20.json` |
| `faster-whisper-base-c80-w075-json-preview` | `faster-whisper` | `base.en` | Local Python CPU Sweep Preview | `cpu / int8` | preview artifact | `docs/benchmark-results/faster-whisper-base.en-int8-c80-w0_75-json-2026-06-10.json` |
| `pipecat-e2e-faster-whisper-base` | `faster-whisper` | `base.en` | Pipecat E2E Local Python CPU | `cpu / int8` | blocked integration artifact | `docs/benchmark-results/faster-whisper-base.en-int8-pipecat-e2e-2026-06-19.json` |
| `faster-whisper-small` | `faster-whisper` | `small.en` | Local Python CPU | `cpu / int8` | validated artifact | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-20.json` |
| `parakeet-compose` | `parakeet` | `nvidia/parakeet-tdt-0.6b-v3` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-compose-2026-06-20.json` |
| `parakeet-nemo-compose` | `parakeet-nemo` | `nvidia/parakeet-tdt_ctc-110m` | Docker Compose CPU | `cpu / float32` | validated artifact | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-21.json` |
| `parakeet-mlx-service-110m` | `parakeet-mlx` | `mlx-community/parakeet-tdt_ctc-110m` | Local Python Apple Silicon MLX Service | `apple-silicon / auto` | validated artifact | `docs/benchmark-results/parakeet-mlx-110m-service-2026-06-21.json` |
| `parakeet-mlx` | `parakeet-mlx` | `mlx-community/parakeet-tdt-0.6b-v3` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-mlx-110m` | `parakeet-mlx` | `mlx-community/parakeet-tdt_ctc-110m` | Local Apple Silicon MLX CLI | `apple-silicon / mlx` | preview artifact | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `qwen-mps` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Local Python Apple Silicon | `mps / auto` | validated artifact | `docs/benchmark-results/qwen-mps-2026-06-21.json` |
| `qwen-compose` | `qwen-asr` | `Qwen/Qwen3-ASR-0.6B` | Docker Compose CPU | `cpu / float16` | validated artifact | `docs/benchmark-results/qwen-compose-2026-06-21.json` |

Status details from the track registry:

- `faster-whisper-base`: validated 10-sample local CPU baseline refreshed on `2026-06-15` with a preloaded model.
- `faster-whisper-base-c80-w075-json-preview`: preview low-latency sweep artifact for the `80 ms` chunk / `0.75 s` partial-window JSON framing variant.
- `pipecat-e2e-faster-whisper-base`: checked-in single-sample Pipecat E2E artifact refreshed on `2026-06-19` using synthesized real-time speech normalized to `16 kHz`, `20 ms` source frames, and `100 ms` websocket chunks; kept off the homepage until comparable E2E lanes exist.
- `faster-whisper-small`: validated 10-sample local CPU baseline using the default service model.
- `parakeet-compose`: validated 10-sample Compose CPU artifact refreshed on `2026-06-20` with binary `/v1/stt/stream` framing and comparable live partial metrics.
- `parakeet-nemo-compose`: validated 10-sample Compose CPU artifact refreshed on `2026-06-21` with paced binary `/v1/stt/stream`; its `348.1 ms` first-partial mean and `622.1 ms` audio-end final mean make it the current Compose CPU reference for the 110M NeMo lane.
- `parakeet-mlx-service-110m`: validated 10-sample local Apple Silicon MLX service artifact refreshed on `2026-06-21` with paced binary `/v1/stt/stream`; its `150.1 ms` REST mean keeps the warmed service lane grounded to the checked-in artifact.
- `parakeet-mlx`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt-0.6b-v3`; its `1971.9 ms` mean latency reflects the checked-in cold CLI preview.
- `parakeet-mlx-110m`: preview 3-sample local Apple Silicon MLX CLI artifact for `mlx-community/parakeet-tdt_ctc-110m`; its `1360.7 ms` mean latency reflects the checked-in cold CLI preview.
- `qwen-mps`: validated 10-sample local Apple Silicon MPS artifact refreshed on `2026-06-21` with paced binary `/v1/stt/stream`; its `336.4 ms` first-partial mean and `1541.9 ms` audio-end final mean replace the earlier legacy `/ws/stream` reference.
- `qwen-compose`: validated 10-sample Compose CPU artifact refreshed on `2026-06-21` using `float16` with paced binary `/v1/stt/stream`; its `680.1 ms` first-partial mean keeps it directly comparable to the other live leaderboard lanes even though its backlog and finalization remain much slower.

## Current Artifact-Backed Comparison

These rows match the current manifest entries used on the homepage, plus two doc-only Parakeet MLX CLI preview artifacts. Every distinct runtime setup keeps its own row here, even when multiple lanes share the same underlying model or reference WER. Read the streaming fields first: ASR TTFB / first visible partial, partial cadence, and audio-end finalization are the operator-facing responsiveness signals. `REST Mean` and `REST RTF` stay here as throughput context for the same backend, but they are not the main live turn-taking score because total file time scales with clip duration. The `Reference WER` column is different: it is external source data for the underlying model, not an official rtc-asr measurement, and it may vary slightly across hardware, runtime, quantization, decoding, and setup. The new `parakeet-mlx-service-110m` row is the warmed service-style counterpart to the earlier cold CLI preview.

| Track | Samples | REST Mean / P95 | REST RTF | Partial Mean / P95 | Audio-end Final / P95 | Reference WER | Artifact |
| --- | ---: | --- | ---: | --- | --- | --- | --- |
| `parakeet-mlx-service-110m` | 10 | 150.1 ms / 197.6 ms | 0.021 | 119.4 ms / 166.9 ms | 251.8 ms / 268.0 ms | `2.4 / 5.2` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt_ctc-110m` via the upstream `nvidia/parakeet-tdt_ctc-110m` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-mlx-110m-service-2026-06-21.json` |
| `parakeet-nemo-compose` | 10 | 508.8 ms / 1001.7 ms | 0.070 | 107.1 ms / 178.8 ms | 622.1 ms / 862.0 ms | `2.4 / 5.2` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt_ctc-110m` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-nemo-110m-compose-2026-06-21.json` |
| `faster-whisper-base` | 10 | 558.4 ms / 726.1 ms | 0.077 | 12134.1 ms / 16250.0 ms | 13498.8 ms / 15429.3 ms | `4.25 / 10.35` on LibriSpeech `clean / other` for `openai/whisper-base.en` ([HF discussion diff](https://huggingface.co/openai/whisper-base.en/discussions/18/files)) | `docs/benchmark-results/faster-whisper-base.en-int8-2026-06-15.json` |
| `qwen-mps` | 10 | 1219.6 ms / 1286.6 ms | 0.168 | 2064.2 ms / 5041.0 ms | 1541.9 ms / 1691.8 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-mps-2026-06-21.json` |
| `faster-whisper-small` | 10 | 1378.3 ms / 1531.1 ms | 0.189 | 1023.2 ms / 1202.4 ms | 1420.6 ms / 1514.0 ms | `3.05 / 7.25` on LibriSpeech `clean / other` for `openai/whisper-small.en` ([HF discussion diff](https://huggingface.co/openai/whisper-small.en/discussions/17/files)) | `docs/benchmark-results/faster-whisper-small.en-int8-2026-06-10.json` |
| `parakeet-mlx-110m` | 3 | 1360.7 ms / 1716.2 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `2.4 / 5.2` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt_ctc-110m` via the upstream `nvidia/parakeet-tdt_ctc-110m` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt_ctc-110m)) | `docs/benchmark-results/parakeet-mlx-110m-2026-06-13.json` |
| `parakeet-mlx` | 3 | 1971.9 ms / 2595.8 ms | n/a (CLI artifact) | n/a (CLI artifact) | n/a (CLI artifact) | `1.93 / 3.59` on LibriSpeech `clean / other` for `mlx-community/parakeet-tdt-0.6b-v3` via the upstream `nvidia/parakeet-tdt-0.6b-v3` model card ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-mlx-2026-06-13.json` |
| `parakeet-compose` | 10 | 1302.6 ms / 2955.6 ms | 0.179 | 953.7 ms / 2464.6 ms | 2214.0 ms / 4809.8 ms | `1.93 / 3.59` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt-0.6b-v3` ([HF model card](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)) | `docs/benchmark-results/parakeet-compose-2026-06-20.json` |
| `qwen-compose` | 10 | 5589.9 ms / 9021.8 ms | 0.768 | 2196.9 ms / 5071.1 ms | 5802.5 ms / 6954.6 ms | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` ([HF README](https://huggingface.co/Qwen/Qwen3-ASR-0.6B/blob/main/README.md)) | `docs/benchmark-results/qwen-compose-2026-06-21.json` |

Notes:

- Treat the homepage and detail pages as the primary place to judge streaming responsiveness: `first_partial_end_to_end_*`, `partial_gap_*`, and `time_to_final_from_audio_end_*` tell the real turn-taking story more directly than raw end-to-end file duration.
- `Audio-end Final` is not TTFT and not total file transcription time. It is the delay from audio end (or `stop`) until the final transcript arrives.
- These WER references are external model-level benchmarks. They are not official rtc-asr measurements and may vary slightly across hardware, runtime, quantization, decoding, chunk/window cadence, websocket framing, warmup state, and transport overhead.
- The `parakeet-mlx` and `parakeet-mlx-110m` rows are local CLI preview artifacts rather than running websocket service benchmarks, so only end-to-end latency is available today; the service-style RTF, partial, and final columns are intentionally left `n/a`, and those preview rows are still kept outside `docs/benchmark-results/manifest.json` and the homepage leaderboard.
- The `parakeet-mlx-service-110m` row is the warmed service-style Apple Silicon MLX lane for the same 110M model, which makes it the right comparison point against `parakeet-nemo-compose` when you want steady-state runtime behavior instead of cold CLI startup cost.
- local diagnostic WER from our small internal sample set remains intentionally unpublished.

## Recommended Low-Power Profiling Fields

The current checked-in artifacts already cover warmed service latency, ASR TTFB / first visible partial timing, finalization delay, and `RTF`. For low-power claims, add these fields to each benchmark lane as the next step:

- device, CPU, and RAM
- accelerator type: none, MPS, MLX, CUDA, or NPU
- wall latency: REST mean and P95, ASR TTFB / first partial, and final
- peak RSS memory
- CPU utilization
- package power when available
- sustained thermal behavior over `5` to `10` minutes
- dropped or late frames for bridged RTC lanes
- transcript churn across partial updates, including per-revision churn ratios

Power and thermal values are optional because they usually come from platform tools outside the Python process; when supplied, the benchmark artifact records them under `environment.package_power_watts` and `environment.thermal_state`.

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
make benchmark-compose-parakeet-nemo-legacy BENCHMARK_RESULT_DATE=2026-06-19
BENCHMARK_SAMPLE_COUNT=5 BENCHMARK_REST_RUNS=3 BENCHMARK_PARTIAL_INTERVAL_CHUNKS=8 QWEN_COMPOSE_DTYPE=float16 BENCHMARK_RESULT_DATE=2026-06-19 make benchmark-compose-qwen-legacy
```


Benchmark artifacts now include extra streaming responsiveness metrics for low-latency analysis:

- `first_partial_end_to_end_*`: ASR TTFB-style timing for when a caller could first see a useful partial in real time
- `partial_gap_*`: cadence between visible partial updates
- `time_to_final_from_audio_end_ms`: per-sample finalization delay after audio stops
- `time_to_final_from_audio_end_*`: aggregated finalization delay summary used by the benchmark site (`final_*` remains a compatibility alias)

Rebuild the homepage manifest after artifact or track changes:

```bash
make benchmark-site
```
