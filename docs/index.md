# Documentation Index

`rtc-asr` is a modular transcription service for RTC and voice-agent workloads. These docs focus on how to run the service, integrate it over the buffered websocket contract, and reproduce the current benchmark story without overstating the transport as a true frame-synchronous streaming decoder.

## Quick Links

- [Overview & Installation](../../README.md)
- [API Reference](./api-reference.md)
- [Pipecat Integration](./pipecat-integration.md)
- [LiveKit Integration](./livekit-integration.md)
- [Benchmarks](./benchmarks.md)
- [Troubleshooting](./troubleshooting.md)

## Recommended Reading Order

- Start with the [README](../../README.md) for local setup and operator defaults.
- Use the [API Reference](./api-reference.md) when you need exact request and event shapes.
- Use the [Pipecat](./pipecat-integration.md) or [LiveKit](./livekit-integration.md) guide when wiring a client.
- Use [Benchmarks](./benchmarks.md) when you need current latency artifacts or reproduction commands.
- Use [Troubleshooting](./troubleshooting.md) for preload, backend runtime, and streaming failure modes.

## Quality Methodology

Public benchmark landing pages in this repo stay latency-first.

- The homepage comparison and this docs index do not publish WER.
- Local smoke clips remain latency and streaming diagnostics only unless they have trustworthy labels and a checked-in evaluation recipe.
- Future public WER belongs on the benchmark methodology page, tied to a named annotated dataset, a pinned split, normalization rules, and a reproducible scoring command.
- The current recommended path is a clean/reference quality track first using FLEURS plus a pinned Common Voice English test split, with noisy or telephony-style robustness work kept as a separate follow-up track.

Use [Benchmarks](./benchmarks.md) for the full artifact-backed latency matrix and the issue #46 methodology note covering future official quality reporting.

## Architecture Snapshot

- FastAPI exposes health, readiness, model metadata, file/REST transcription, and websocket streaming routes.
- `AudioProcessor` normalizes uploaded files and streaming PCM into the service target sample rate.
- `build_transcriber()` selects a backend adapter from environment configuration.
- Client helpers in `src/rtc_client.py` and `src/streaming.py` keep the websocket protocol reusable across RTC integrations.

## Operator Checklist

Before shipping a backend configuration, verify:

- `GET /health` returns the expected backend and model.
- `GET /ready` returns `200` and `status=ready` for the target runtime.
- `GET /api/models` advertises the expected streaming capabilities.
- A websocket client can send `start`, binary audio frames, and `stop` and receive a final transcript.
- Focused tests pass for the touched area.

## Common Entry Points

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8080 --reload
curl http://localhost:8080/health
curl -f http://localhost:8080/ready
curl http://localhost:8080/api/models
pytest tests/test_client.py tests/test_smoke.py -v
```

## Source Map

- `src/main.py`: FastAPI routes and websocket session lifecycle
- `src/model_loader.py`: backend adapters and capability metadata
- `src/audio_processor.py`: decode and resample logic
- `src/rtc_client.py`: async websocket helper for integrations
- `src/streaming.py`: reusable higher-level streaming helpers
- `docs/benchmarks.md`: checked-in latency artifacts and reproduction flow

## External References

- [FastAPI](https://fastapi.tiangolo.com/)
- [Pipecat](https://pipecat.ai/)
- [LiveKit Docs](https://docs.livekit.io/)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)
- [NVIDIA Parakeet](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)

## Repo

- GitHub: [agonza1/rtc-asr](https://github.com/agonza1/rtc-asr)
