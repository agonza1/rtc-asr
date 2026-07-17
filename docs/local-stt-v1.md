# Local STT v1

`Local STT v1` is the lightweight vendor-neutral websocket contract shared by `rtc-asr` and the Pipecat Local STT plugin work. It is intentionally small: JSON control messages, binary PCM16 audio frames, and JSON transcript events for colocated local services.

This spec does not replace the current [`/ws/stream`](./api-reference.md) API yet. The existing `rtc-asr` websocket route and its `start` / `audio` / `stop` / `cancel` semantics remain valid. `Local STT v1` is the next protocol contract that downstream implementations will share.

## Design Goals

- Vendor-neutral. Do not emulate OpenAI, Deepgram, or any hosted provider schema.
- Local-first. Optimize for sidecar or same-host websocket hops.
- Low overhead. Audio is always raw binary PCM16 websocket data, never base64-wrapped.
- Explicit lifecycle. `start`, `finalize`, `cancel`, and `close` each have distinct meanings.
- Monotonic transcript updates. Partials and finals use the same `transcript` event with revision metadata.

## Audio Contract

Hot-path audio format:

- `sample_rate`: `16000`
- `channels`: `1`
- `format`: `pcm_s16le`
- `frame_ms`: `20`
- `bytes_per_frame`: `640`

Binary websocket frames carry raw little-endian PCM16 bytes. Clients may batch multiple 20 ms frames into one websocket write, but the payload still has to be binary PCM16 data.

The default server transport is TCP WebSocket, for example `ws://rtc-asr:8080/v1/stt/stream` in Docker Compose or `ws://localhost:8080/v1/stt/stream` for local benchmarks. Colocated deployments can opt into Unix-domain-socket WebSocket serving with `LOCAL_STT_SOCKET_MODE=uds` and `LOCAL_STT_UDS_PATH=/run/rtc-asr/stt.sock`; startup removes stale socket files and fails clearly if the path exists but is not a socket. The benchmark client also accepts `--transport uds_ws --uds-path /tmp/rtc-asr.sock` so same-host adapter work can measure the client path against a matching server socket. Checked-in production benchmark artifacts should continue to record `"transport": "tcp_ws"`; UDS comparison artifacts should record `"transport": "uds_ws"` and the socket path only when both endpoints are intentionally using the colocated socket. Treat UDS as optional: if p95 latency does not improve by at least 5 ms, TCP WebSocket is simpler and sufficient for most users.

Minimal Compose shape for a colocated UDS comparison:

```yaml
services:
  rtc-asr:
    environment:
      LOCAL_STT_SOCKET_MODE: uds
      LOCAL_STT_UDS_PATH: /run/rtc-asr/stt.sock
    volumes:
      - rtc_asr_socket:/run/rtc-asr

  pipecat:
    environment:
      LOCAL_STT_TRANSPORT: uds_ws
      LOCAL_STT_UDS_PATH: /run/rtc-asr/stt.sock
    volumes:
      - rtc_asr_socket:/run/rtc-asr

volumes:
  rtc_asr_socket:
```

Run the comparison only after both services share that socket volume, then keep the TCP WebSocket run as the baseline. UDS should stay an optimization knob, not the default deployment path.

Raw UDS framing is tracked separately as an experimental issue 88 transport. The tested frame shape is a 5 byte little-endian header (`uint8 frame_type`, `uint32 payload_len_le`) followed by JSON control, PCM16 audio, JSON event, error, ping, or pong payload bytes. The `/health` and `/api/models` protocol catalog exposes this as `raw_uds` with `status: codec_only` by default, plus `enabled`, `enable_env`, `path_env`, `plugin_config: {"transport": "raw_uds", "uds_path": "<socket>"}`, frame type codes, frame overhead, lifecycle fields, and protocol-error coverage for malformed JSON, oversized payloads, incomplete frames, and frame-length mismatches so benchmark harnesses can discover the exact opt-in knobs and copy target-contract metadata into artifacts. Set `LOCAL_STT_RAW_UDS_ENABLED=true` and `LOCAL_STT_RAW_UDS_PATH=/run/rtc-asr/stt.raw.sock` to serve the raw UDS listener as an opt-in benchmark path; startup removes stale socket files and fails clearly if the path exists but is not a socket. Keep raw UDS experimental unless comparison artifacts show a p95 first-interim win of at least 5 ms over UDS WebSocket.

Rules:

- Binary audio MUST NOT be base64-wrapped.
- Audio payloads SHOULD contain an even number of bytes.
- A single 20 ms mono 16 kHz PCM16 frame is 640 bytes.
- Servers default to `LOCAL_STT_ENABLE_PCM16_FAST_PATH=true`, `LOCAL_STT_REQUIRE_TARGET_SAMPLE_RATE=true`, and `LOCAL_STT_TARGET_SAMPLE_RATE=16000` so raw PCM16 frames bypass WAV/soundfile probing.
- Control messages MUST stay JSON objects.

## Connection Lifecycle

The protocol uses one websocket connection with at most one active utterance at a time.

1. Client opens a websocket.
2. Client sends `start` with protocol version and required audio settings.
3. Server validates the request and replies with `ready`.
4. Client streams binary PCM16 audio frames.
5. Server may emit zero or more `transcript` events while audio is arriving.
6. Client ends the utterance with either:
   - `finalize` to request one last final transcript.
   - `cancel` to discard buffered audio and skip a final transcript.
7. After `finalize` or `cancel`, the utterance is no longer active.
8. Client may send another `start` on the same websocket or send `close` to end the connection.
9. `close` is acknowledged with `closed`, then the websocket may close normally.

`ping` / `pong` are optional keepalive messages and do not affect utterance state.

## Realtime-Style Shim Mapping

The Local STT v1 lifecycle is intentionally small enough for Realtime-compatible voice shims to map onto it without provider-specific fields:

| Realtime-style action | Local STT v1 action | Notes |
| --- | --- | --- |
| Open input audio buffer for a turn | `start` | Include `client_stream_id` and optional `metadata` to correlate the downstream response or turn id. |
| `input_audio_buffer.append` with PCM16 audio | Binary websocket frame | Send raw mono 16 kHz PCM16 bytes directly; do not base64-wrap audio. |
| Interim ASR result | `transcript` with `is_final=false` | `revision` increases for each update, with `audio_received_ms` and `audio_transcribed_ms` describing coverage. |
| `input_audio_buffer.commit` | `finalize` | The server flushes the utterance and emits the final `transcript` with `is_final=true` and `speech_final=true`. |
| `input_audio_buffer.clear` or canceled response | `cancel` | The server discards buffered audio and should not emit a final transcript for that utterance. |
| Invalid control or audio payload | `error` | Fatal protocol errors end the active utterance unless the server marks them retryable. |

The checked-in protocol contract test exercises this mapping with only local test dependencies. It proves that a shim can use start, binary PCM16 audio, partial/final transcripts, finalize, cancel, and protocol error behavior without OpenClaw-specific code or hosted ASR assumptions.

## Client Messages

### `start`

```json
{
  "type": "start",
  "version": "local-stt.v1",
  "audio": {
    "sample_rate": 16000,
    "channels": 1,
    "format": "pcm_s16le",
    "frame_ms": 20,
    "bytes_per_frame": 640
  },
  "language": "en",
  "interim_results": true,
  "partial_interval_ms": 100,
  "partial_window_seconds": 1.5,
  "max_buffer_seconds": 10,
  "client_stream_id": "turn-abc",
  "metadata": {
    "turn_id": "a1"
  }
}
```

Required behavior:

- `version` MUST be `local-stt.v1`.
- `audio.sample_rate`, `audio.channels`, `audio.format`, and `audio.frame_ms` MUST match the hot-path contract above.
- Unknown optional fields MUST be ignored.
- Unsupported required values MUST return a protocol `error`.
- `partial_interval_ms` MAY request transcript cadence in milliseconds; servers MAY round it up to the nearest supported audio frame boundary.
- `partial_window_seconds` MAY bound how much trailing audio contributes to interim transcripts.
- `max_buffer_seconds` MAY bound how much audio a server keeps before it requires finalize/cancel.
- `client_stream_id` MAY carry a caller-chosen utterance/session id for downstream correlation.
- If the client includes `metadata`, servers MAY echo it back under `metadata.client_metadata` on `ready`, `transcript`, and `warning` events for turn correlation.

### `finalize`

```json
{ "type": "finalize" }
```

`finalize` tells the server to flush the current utterance and emit one final `transcript` with `is_final=true` and `speech_final=true`.

### `cancel`

```json
{ "type": "cancel" }
```

`cancel` discards the active utterance. The server should not emit a final transcript for canceled audio.

### `close`

```json
{ "type": "close" }
```

`close` ends the protocol session cleanly. The server acknowledges with `closed`.

### `ping`

```json
{
  "type": "ping",
  "ping_id": "heartbeat-1",
  "timestamp_ms": 1710000000
}
```

## Server Messages

### `ready`

```json
{
  "type": "ready",
  "version": "local-stt.v1",
  "audio": {
    "sample_rate": 16000,
    "channels": 1,
    "format": "pcm_s16le",
    "frame_ms": 20,
    "bytes_per_frame": 640
  },
  "interim_results": true,
  "metadata": {}
}
```

### `transcript`

```json
{
  "type": "transcript",
  "text": "hello world",
  "is_final": false,
  "speech_final": false,
  "revision": 1,
  "audio_received_ms": 1000,
  "audio_transcribed_ms": 900,
  "metadata": {}
}
```

Required fields:

- `text`: transcript text for the current revision.
- `is_final`: `false` for partials, `true` for the last transcript of the utterance.
- `speech_final`: `true` only when the server considers speech ended for this utterance.
- `revision`: monotonic positive integer per utterance.
- `audio_received_ms`: total audio duration accepted from the client.
- `audio_transcribed_ms`: duration covered by this transcript revision.
- `metadata`: implementation-specific optional metadata object.

Timing rules:

- `audio_transcribed_ms` MUST be less than or equal to `audio_received_ms`.
- Final transcripts typically report equal values for both timing fields.

### `warning`

```json
{
  "type": "warning",
  "code": "partial_dropped",
  "message": "Dropped one partial due to backpressure",
  "metadata": {
    "partial_revision": 2
  },
  "retryable": false
}
```

Warnings are non-fatal. Clients may continue the active utterance unless the server also emits an `error` or `closed`.

### `error`

```json
{
  "type": "error",
  "code": "unsupported_audio_format",
  "message": "audio.sample_rate must be 16000",
  "metadata": {
    "field": "audio.sample_rate"
  },
  "retryable": false,
  "fatal": true
}
```

Use protocol `error` events for invalid control messages, unsupported required fields, or other validation failures.

### `pong`

```json
{
  "type": "pong",
  "ping_id": "heartbeat-1",
  "timestamp_ms": 1710000000,
  "metadata": {}
}
```

### `closed`

```json
{
  "type": "closed",
  "reason": "client_close",
  "metadata": {}
}
```
