# Deployment Guide

This guide describes the deployment paths that `rtc-asr` supports today and the additional controls required before exposing it in production.

`rtc-asr` is a model-serving sidecar: it accepts normalized audio over HTTP or WebSocket and runs one configured ASR backend. It does not provide TLS, authentication, rate limiting, a model registry, or a WebRTC media edge. Put those responsibilities in the surrounding platform.

## Deployment status

The repository currently ships:

- a Python 3.11 application entrypoint;
- a CPU-oriented Dockerfile;
- a Docker Compose stack for the ASR service and optional browser Pipecat demo;
- liveness and readiness endpoints;
- persistent Hugging Face cache mounting in Compose;
- native local paths for Apple Silicon MLX backends.

The repository does **not** currently publish an official production image, Kubernetes/Helm manifests, Prometheus metrics, or an authenticated public API. Treat the checked-in Compose stack as a local/reference deployment rather than a complete internet-facing production platform.

## Choose a runtime

| Target | Recommended backend | Deployment path | Notes |
| --- | --- | --- | --- |
| General CPU | `faster-whisper` with `base.en` and `int8` | Python or Docker Compose | Best default production-style baseline |
| CPU comparison | `qwen-asr`, `parakeet`, or `parakeet-nemo` | Backend-specific Compose build | Higher memory/startup cost; validate on the intended host |
| Apple Silicon | `parakeet-mlx` or `voxtral-mlx` | Native Python MLX environment | The checked-in Linux container is not the MLX deployment path |
| NVIDIA GPU | Backend-specific | Custom CUDA image | The checked-in Dockerfile installs CPU-only PyTorch and is not GPU-ready |

Resource requirements vary by backend and model. Do not use a single CPU, RAM, or GPU recommendation for every profile. Benchmark the exact backend, model, device, concurrency, and audio cadence before setting production limits.

## Prerequisites

For the default CPU Compose path:

- Docker Engine with the Compose plugin;
- enough disk space for the image and model cache;
- outbound access to the selected model registry during initial download, unless weights are pre-baked;
- port `8080` for the ASR service;
- port `8090` only when running the optional browser demo.

For local Python, use Python 3.11 or newer and install `requirements.txt` in a virtual environment.

## Quick start: CPU Compose

```bash
git clone https://github.com/agonza1/rtc-asr.git
cd rtc-asr
make setup
```

`make setup` creates `.env` from `config.example` when it does not already exist. For a warmed production-style CPU baseline, set:

```env
ASR_BACKEND=faster-whisper
ASR_MODEL_SIZE=base.en
ASR_DEVICE=cpu
ASR_COMPUTE_TYPE=int8
ASR_PRELOAD_MODEL=true
ASR_FAIL_FAST=true
```

Start only the ASR service:

```bash
docker compose up -d --build asr-service
docker compose ps
docker compose logs -f asr-service
```

Validate liveness, readiness, and the active model:

```bash
curl -f http://127.0.0.1:8080/health
curl -f http://127.0.0.1:8080/ready
curl -f http://127.0.0.1:8080/api/models
```

`docker compose up -d --build` without a service name also starts the browser Pipecat demo at `http://127.0.0.1:8090/rtc-asr`. That demo is intended for local validation, not as a production frontend.

## Local Python

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp config.example .env
ASR_PRELOAD_MODEL=true ASR_FAIL_FAST=true \
  uvicorn src.main:app --host 0.0.0.0 --port 8080 --env-file .env
```

The default dependency set is pinned for the Qwen-compatible runtime. The Transformers Parakeet path needs the documented newer Hugging Face pair:

```bash
pip install --upgrade --no-deps huggingface-hub==1.18.0 transformers==5.10.2
```

See `README.md` and `docs/troubleshooting.md` before selecting a non-default backend.

## Configuration

Copy `config.example` to `.env` for Compose. Docker Compose reads `.env` automatically; if you use a differently named file, pass it explicitly with `--env-file`.

### Core service settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Application listen address outside the Compose override |
| `PORT` | `8080` | Application listen port |
| `HOST_PORT` | `8080` | Host port published by Compose; the container still listens on `PORT=8080` |
| `CORS_ORIGINS` | `*` | Comma-separated browser origins; restrict this when browser access is required |
| `SAMPLE_RATE` | `16000` | Default audio sample rate |
| `STREAM_MAX_BUFFER_BYTES` | `1048576` | Maximum buffered audio per stream |
| `ASR_PRELOAD_MODEL` | `false` | Load and validate the model during startup |
| `ASR_FAIL_FAST` | `false` | Exit startup when preload fails |

Use both preload settings in production so a pod/container cannot receive traffic before its model is usable.

### Default faster-whisper settings

| Variable | Default |
| --- | --- |
| `ASR_BACKEND` | `faster-whisper` |
| `ASR_MODEL_SIZE` | `base.en` |
| `ASR_DEVICE` | `cpu` |
| `ASR_COMPUTE_TYPE` | `int8` |
| `ASR_VAD_FILTER` | `true` |

`MODEL_NAME` remains a compatibility alias for `ASR_MODEL_SIZE`, and `AUDIO_SAMPLE_RATE` remains an alias for `SAMPLE_RATE`. New deployments should use the primary names.

### Local STT transport

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOCAL_STT_SOCKET_MODE` | `tcp` | `tcp` or colocated `uds` WebSocket serving |
| `LOCAL_STT_UDS_PATH` | `/run/rtc-asr/stt.sock` | Unix socket path when `LOCAL_STT_SOCKET_MODE=uds` |
| `LOCAL_STT_RAW_UDS_ENABLED` | `false` | Enables the experimental raw UDS listener |
| `LOCAL_STT_RAW_UDS_PATH` | `/run/rtc-asr/stt.raw.sock` | Experimental raw UDS socket path |
| `LOCAL_STT_TARGET_SAMPLE_RATE` | `16000` | Required Local STT sample rate |

Keep TCP WebSocket as the default unless a colocated benchmark proves that UDS materially improves p95 latency. Keep raw UDS experimental.

Backend-specific Qwen, Parakeet, NeMo, and Voxtral variables are documented in `config.example`, `README.md`, and `docs/troubleshooting.md`.

## Backend-specific Compose builds

The Dockerfile has optional dependency lanes controlled by build arguments.

Keep `ASR_PRELOAD_MODEL=true` and `ASR_FAIL_FAST=true` in `.env` for these profiles.

Transformers Parakeet:

```bash
ENABLE_PARAKEET_RUNTIME=1 \
ASR_BACKEND=parakeet \
docker compose up -d --build asr-service
```

NeMo Parakeet:

```bash
ENABLE_NEMO_RUNTIME=1 \
ASR_BACKEND=parakeet-nemo \
docker compose up -d --build asr-service
```

Use the benchmark targets in the `Makefile` to reproduce the repository's known backend-specific build combinations before converting them into an environment-specific production image.

## Apple Silicon MLX

Run MLX backends natively on an Apple Silicon host:

```bash
make mlx-venv
. .venv-mlx/bin/activate
ASR_BACKEND=parakeet-mlx \
ASR_DEVICE=apple-silicon \
ASR_PRELOAD_MODEL=true \
ASR_FAIL_FAST=true \
uvicorn src.main:app --host 127.0.0.1 --port 8080
```

For experimental Voxtral MLX, use `ASR_BACKEND=voxtral-mlx` and review its model and transcription-delay settings in `config.example`.

## NVIDIA GPU deployments

The checked-in Dockerfile installs PyTorch from the CPU wheel index. Setting `CUDA_VISIBLE_DEVICES` or adding a Compose GPU reservation does not turn that image into a CUDA runtime.

A GPU deployment needs a separately validated image that includes:

- a compatible NVIDIA CUDA runtime base;
- a CUDA-enabled PyTorch build;
- NVIDIA Container Toolkit on the host;
- the dependencies for the selected ASR backend;
- an explicit GPU resource reservation and scheduling policy;
- model-specific memory and concurrency limits.

Do not document or publish a GPU profile until it is built and exercised in CI or on the target host.

## Production image workflow

Build and publish immutable tags to the registry used by your environment:

```bash
docker build -t registry.example.com/rtc-asr:0.1.0 .
docker push registry.example.com/rtc-asr:0.1.0
```

Prefer a release tag or image digest over `latest`. The current image is CPU-oriented.

For a production Compose host, use the published image, mount a persistent model cache, and bind the application to a private interface or place it behind an authenticated proxy. Do not run the browser demo unless it is explicitly needed.

## Model download, preload, and warm-up

Most backends have substantial cold-start cost from downloading weights, loading the model, compiling kernels, and warming caches.

Production sequence:

1. Persist or pre-bake the model cache.
2. Set `ASR_PRELOAD_MODEL=true` and `ASR_FAIL_FAST=true`.
3. Wait for `GET /ready` to return `200` before routing traffic.
4. Send one representative warm-up transcription before measuring latency or shifting production traffic.
5. Keep the process resident; do not use scale-to-zero when predictable first-request latency matters.

The Compose stack stores Hugging Face data under `./.cache/huggingface` on the host. Protect any `HF_TOKEN` or `HUGGINGFACE_HUB_TOKEN` through your normal secret manager; do not commit them to `.env`.

## Health and readiness

| Endpoint | Use | Behavior |
| --- | --- | --- |
| `GET /health` | Liveness and diagnostic metadata | Reports backend/model state without acting as a strict traffic gate |
| `GET /ready` | Readiness and startup gate | Returns `503` when the configured preloaded backend is unavailable |
| `GET /api/models` | Capability inspection | Reports the active backend, model, preload state, and protocol catalog |

For Kubernetes or another orchestrator, use `/health` for liveness and `/ready` for startup/readiness. Allow enough startup time for the selected model to download and preload. The reference Compose health check allows up to ten minutes for model startup.

## API and streaming endpoints

- `POST /api/transcribe`: base64-encoded one-shot audio;
- `POST /api/transcribe/file`: uploaded audio file;
- `WebSocket /v1/stt/stream`: recommended Local STT v1 path for new integrations;
- `WebSocket /ws/stream`: legacy buffered WebSocket path.

The Local STT v1 protocol is still advertised as preview by the service. Pin client and server versions together until that status changes. See `docs/local-stt-v1.md` for the exact lifecycle and PCM16 contract.

## Security boundary

`rtc-asr` currently has no built-in authentication, authorization, TLS termination, or rate limiting. Do not expose port `8080` directly to the public internet.

Use one or more of:

- a private VPC/VNet, cluster network, or localhost-only binding;
- an authenticated API gateway or reverse proxy;
- mTLS between services;
- network policies or security groups;
- request size, connection, and rate limits at the edge;
- `wss://` termination for remote WebSocket clients.

Set `CORS_ORIGINS` to an explicit comma-separated allowlist if browsers call the service. CORS is not an authentication mechanism.

For WebSocket proxies/load balancers, enable connection upgrades, set an idle timeout longer than the expected session, and drain existing connections during rollout.

## Kubernetes requirements

This repository does not currently ship a production Kubernetes manifest or Helm chart. A deployment maintained by the consuming environment should include:

- an image pulled from a real registry using an immutable tag/digest;
- one model-serving process per container unless multi-process memory use has been measured;
- startup and readiness probes on `/ready`;
- a liveness probe on `/health`;
- model-specific CPU, memory, and optional GPU requests/limits;
- node selectors/tolerations for accelerator workloads;
- a persistent or pre-baked model cache when restart download time is unacceptable;
- secrets for gated model access;
- a Service plus TLS/authenticated ingress or an internal-only service boundary;
- WebSocket-aware timeouts and graceful connection draining;
- a rolling strategy sized for the memory cost of temporarily running old and new models together.

Do not copy generic resource numbers across backends. Measure peak RSS/GPU memory and sustained concurrency first.

## Scaling and capacity

The service loads one configured backend/model per process. Adding Uvicorn workers can load another full model copy, so prefer one worker per container and scale replicas only after measuring memory and model thread-safety.

Capacity planning should include:

- cold and warmed startup time;
- REST mean/p95 and Local STT first-interim/final latency;
- concurrent streams per replica;
- peak RSS or GPU memory;
- CPU/GPU utilization and thermal behavior;
- WebSocket connection duration and reconnect behavior;
- model-download pressure during rollout.

The application does not currently expose admission-control or Prometheus metrics. Use external connection/request limits and validate overload behavior before increasing replicas.

## Observability

Current operational signals are:

- container/application logs;
- `/health` and `/ready`;
- `/api/models` backend and preload metadata;
- the checked-in benchmark tooling and artifacts.

There is no `/metrics` or `/api/metrics` endpoint today. Do not configure Prometheus scraping until metrics instrumentation is implemented. At the platform layer, collect container CPU, memory, GPU, restart, probe, and network metrics.

## Rollback

Rollback with immutable image references, not mutable `latest` tags. The checked-in Compose file builds locally and does not declare a pullable `image:` for `asr-service`; keep rollback conceptual until an environment-specific Compose override pins a registry image such as `image: ${RTC_ASR_IMAGE}`.

For Kubernetes, use the platform's normal rollout history and verify `/ready` before restoring traffic.

Model caches are rebuildable and are not a substitute for container images. Back up environment-specific configuration and secret-manager state through the surrounding platform; the ASR service itself does not own durable application data.

## Troubleshooting

```bash
docker compose ps
docker compose logs -f asr-service
curl -i http://127.0.0.1:8080/health
curl -i http://127.0.0.1:8080/ready
curl -i http://127.0.0.1:8080/api/models
docker stats
```

Common causes of a `503` readiness response are missing backend dependencies, incompatible runtime versions, inaccessible model weights, or an unsupported device/backend combination. The response includes `preload_error`, `backend`, and `model` fields.

See:

- [README](./README.md)
- [API Reference](./docs/api-reference.md)
- [Local STT v1](./docs/local-stt-v1.md)
- [Pipecat Integration](./docs/pipecat-integration.md)
- [LiveKit Integration](./docs/livekit-integration.md)
- [Troubleshooting](./docs/troubleshooting.md)

## Production readiness checklist

- [ ] Backend/model/device combination benchmarked on the target hardware
- [ ] Immutable image published to the environment's registry
- [ ] Model cache persistence or pre-baking strategy selected
- [ ] Preload and fail-fast enabled
- [ ] Startup, readiness, and liveness probes configured
- [ ] Private network or authenticated TLS proxy in front of the service
- [ ] CORS restricted when browser access is required
- [ ] Request, connection, and upload limits configured externally
- [ ] WebSocket upgrade, idle timeout, and connection draining verified
- [ ] Platform CPU/memory/GPU/log monitoring configured
- [ ] Load, overload, restart, and rollback behavior tested
