# Realtime ASR Project - DREAMS

## Purpose
A minimalistic Docker service for real-time Automatic Speech Recognition (ASR) using Qwen3-ASR-1.7B model, enabling low-latency STT integration with Pipecat or LiveKit systems.

## Vision
Every voice interaction should have reliable, low-latency transcription available as a drop-in STT component.

## Beachhead
Enable Pipecat/LiveKit voice agents to use Qwen3-ASR-1.7B as their STT backend with minimal latency.

## MVP Wedge
A lightweight Docker service that:
- Loads Qwen3-ASR-1.7B model (~1.7GB)
- Streams audio chunks for real-time transcription
- Exposes REST/gRPC endpoints for external integration
- Supports multiple languages (en, es, fr, de, zh, etc.)
- Maintains sub-500ms latency for 16kHz audio

## Architecture
```
┌─────────────────────────────────────────────────────┐
│                   Client                             │
│              (Pipecat/LiveKit)                       │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│           Realtime ASR Service                       │
│  ┌──────────────┐  ┌──────────────────────────────┐ │
│  │  Audio In    │  │  Qwen3-ASR-1.7B              │ │
│  │  Stream      │◄─┤  Model Inference Engine       │ │
│  └──────────────┘  └──────────────────────────────┘ │
│  ┌──────────────┐  ┌──────────────────────────────┐ │
│  │  Whisper     │  │  WebRTC Audio                  │ │
│  │  (Fallback)  │  │  Transcoder                    │ │
│  └──────────────┘  └──────────────────────────────┘ │
│              ┌─────────────────────────────────┐    │
│              │  Transcription Buffer            │    │
│              │  (chunk-based streaming)         │    │
│              └─────────────────────────────────┘    │
│              ┌─────────────────────────────────┐    │
│              │  Output Stream                   │    │
│              │  (events/push notifications)     │    │
│              └─────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│              Output: Transcribed Text                 │
└─────────────────────────────────────────────────────┘
```

## Key Features
- **Low Latency**: Optimized chunking for real-time streaming
- **Multi-language**: Support for English, Spanish, French, German, Chinese, etc.
- **Small Footprint**: ~1.7GB model vs larger alternatives
- **Docker Native**: Simple `docker run` deployment
- **Fallback Support**: Graceful degradation to Whisper if needed
- **Multiple Protocols**: HTTP streaming, WebSocket, WebRTC

## Acceptance Criteria
- [ ] Service starts with `docker compose up`
- [ ] Model loads within 30 seconds
- [ ] Sub-500ms latency for 16kHz audio chunks
- [ ] Accurate transcription (>85% WER on English)
- [ ] Multiple language support via config
- [ ] REST endpoint `/api/transcribe`
- [ ] WebSocket endpoint `/ws/stream`
- [ ] Integration docs for Pipecat/LiveKit

## Blockers
- None yet

## Next Steps
1. Set up project scaffolding
2. Implement ASR inference layer
3. Create streaming audio handling
4. Build REST/WebSocket endpoints
5. Add Docker Compose setup
6. Write integration examples
