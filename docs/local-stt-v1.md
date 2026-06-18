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

Rules:

- Binary audio MUST NOT be base64-wrapped.
- Audio payloads SHOULD contain an even number of bytes.
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
