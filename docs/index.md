# Documentation Index

`rtc-asr` is a modular transcription service for RTC and voice-agent workloads. Start with the benchmark notes when you need a decision on live-ASR tradeoffs, then drop into the API or integration guides only for implementation details.

## Quick Links

- [Overview & Installation](../../README.md)
- [API Reference](./api-reference.md)
- [Local STT v1](./local-stt-v1.md)
- [Pipecat Integration](./pipecat-integration.md)
- [Browser Pipecat Demo](../examples/browser_pipecat_demo/README.md)
- [LiveKit Integration](./livekit-integration.md)
- [Benchmarks](./benchmarks.md)
- [Troubleshooting](./troubleshooting.md)

## Recommended Reading Order

- Start with [Benchmarks](./benchmarks.md) if you are deciding which ASR lane deserves a closer look.
- Use the [README](../../README.md) for local setup and operator defaults.
- Use the [API Reference](./api-reference.md) for the current service contract, and [Local STT v1](./local-stt-v1.md) when you need the shared next-step websocket protocol for colocated plugins or sidecars.
- Use the [Pipecat](./pipecat-integration.md) or [LiveKit](./livekit-integration.md) guide when you are wiring an RTC client around that service contract. Use the [Browser Pipecat Demo](../examples/browser_pipecat_demo/README.md) when you need the local browser -> Pipecat -> `rtc-asr` sidecar path and Docker Compose commands.
- Use [Troubleshooting](./troubleshooting.md) for preload, backend runtime, and streaming failure modes.

## Architecture Snapshot

- FastAPI exposes health, readiness, model metadata, file/REST transcription, and websocket streaming routes.
- `AudioProcessor` normalizes uploaded files and streaming PCM into the service target sample rate.
- `build_transcriber()` selects a backend adapter from environment configuration.
- Client helpers in `src/rtc_client.py` and `src/streaming.py` keep the websocket protocol reusable across RTC integrations.

## Repository Layout

Use this map when you need to figure out whether something is core service code, benchmark plumbing, or an example:

- `src/`: main `rtc-asr` service implementation
- `tests/`: service, protocol, and benchmark tests
- `docs/`: primary written documentation
- `docs/benchmark-results/`: checked-in benchmark artifacts plus generated benchmark-site assets
- `examples/browser_pipecat_demo/`: browser-facing Pipecat demo app
- `examples/pipecat_local_stt_bot/`: example Pipecat bot wired to the Local STT flow
- `pipecat-local-stt/`: separate package for reusable Pipecat Local STT adapter code
- `scripts/`: benchmark manifest builders, homepage prerendering, and repo helpers

Two similarly named paths serve different purposes:

- `pipecat-local-stt/` is package code you can reuse
- `examples/pipecat_local_stt_bot/` is an example application you can run or adapt

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
- `src/protocols/local_stt_v1.py`: vendor-neutral Local STT message schema and validators
- `pipecat-local-stt/src/`: standalone Pipecat Local STT adapter package implementation
- `examples/browser_pipecat_demo/`: local browser, Pipecat SmallWebRTC, and `rtc-asr` sidecar example
- `examples/pipecat_local_stt_bot/`: Local STT example bot wiring for Pipecat
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

## Appendix: Reference WER Notes

The docs screen keeps the same reference WER values shown in the benchmark notes. These are upstream benchmark or model-card values for the underlying models, not official rtc-asr measurements, and they may vary slightly across hardware, runtime, quantization, decoding, and setup.

| Runtime lane | Reference WER |
| --- | --- |
| `faster-whisper-base` | `4.25 / 10.35` on LibriSpeech `clean / other` for `openai/whisper-base.en` |
| `faster-whisper-small` | `3.05 / 7.25` on LibriSpeech `clean / other` for `openai/whisper-small.en` |
| `parakeet-mlx` and `parakeet-compose` | `1.93 / 3.59` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt-0.6b-v3` |
| `parakeet-mlx-110m`, `parakeet-mlx-service-110m`, and `parakeet-nemo-compose` | `2.4 / 5.2` on LibriSpeech `clean / other` for `nvidia/parakeet-tdt_ctc-110m` |
| `qwen-mps` and `qwen-compose` | `2.11 / 4.55` on LibriSpeech `clean / other` for `Qwen/Qwen3-ASR-0.6B` |

Use [Benchmarks](./benchmarks.md) for the full artifact-backed comparison matrix, source links, and the methodology note that keeps these external WER references separate from local latency measurements. Distinct runtime setups stay split into separate rows there even when they share the same upstream model benchmark reference.
