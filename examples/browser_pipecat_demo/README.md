# Browser Pipecat Demo

This example is a local browser-to-ASR proof of concept for the `rtc-asr` RTC edge pattern:

```text
Browser microphone
  -> native browser WebRTC
  -> local Pipecat SmallWebRTC service at /rtc-asr
  -> decoded PCM batches
  -> rtc-asr /v1/stt/stream
  -> transcript events back over a WebRTC data channel
```

The browser stays dependency-free. It owns microphone permission, native `RTCPeerConnection` setup, and transcript rendering. The local FastAPI service owns Pipecat WebRTC signaling, decoded audio frame handling, and forwarding 80 to 160 ms PCM chunks to `rtc-asr`.

## Current Scope

- Serves an installable static single-page app at `GET /rtc-asr` with a local PWA shell
- Uses native browser APIs: `getUserMedia`, `RTCPeerConnection`, `RTCDataChannel`, and browser-managed audio playback for repeatable file streaming
- Posts a browser SDP offer to `POST /rtc-asr/offer`
- Uses Pipecat's SmallWebRTC transport when `pipecat-ai[webrtc]` is installed
- Relays decoded PCM to `rtc-asr` over `/v1/stt/stream` in configurable low-latency chunks
- Sends partial, final, status, and error messages back to the browser over the data channel
- Returns a structured dependency error when the optional Pipecat WebRTC runtime is not installed

This remains an example app, not a production deployment recipe. It is intended for local iteration on the browser -> Pipecat -> `rtc-asr` boundary.

## Prerequisites

- Python 3.11 or newer
- A working `rtc-asr` checkout
- A local `rtc-asr` backend reachable at `RTC_ASR_WS_URL`
- A browser that allows microphone capture on `localhost`, `127.0.0.1`, or HTTPS origins

Most browsers block `getUserMedia` on plain HTTP remote hosts. Use `127.0.0.1`, `localhost`, or HTTPS while testing.

## Fastest Local Path

From the repository root, start the main `rtc-asr` backend in one terminal:

```bash
make dev
```

Then run the browser Pipecat demo service in another terminal:

```bash
. .venv/bin/activate
uvicorn examples.browser_pipecat_demo.service.app:app --host 127.0.0.1 --port 8090
```

Open:

```bash
open http://127.0.0.1:8090/rtc-asr
```

The demo can then be installed locally from a supported browser as a PWA shell. `make start` only starts the main `rtc-asr` backend compose service today; keep the demo service on the explicit `uvicorn` command until a compose-managed Pipecat demo service is added.

## Install

From the repository root, create or reuse the project virtualenv:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Install the example's optional Pipecat WebRTC runtime:

```bash
pip install -r examples/browser_pipecat_demo/requirements.txt
```

That example requirements file includes `pipecat-ai[webrtc]`. The dependency is kept out of the root requirements so the core `rtc-asr` service can still install without aiortc/Pipecat WebRTC extras.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `RTC_ASR_WS_URL` | `ws://127.0.0.1:8080/v1/stt/stream` | `rtc-asr` websocket target for transcript streaming |
| `RTC_ASR_CHUNK_MS` | `100` | PCM batch duration sent to `rtc-asr`; must be between `80` and `160` |
| `RTC_ASR_MAX_UTTERANCE_SECONDS` | `24` | Demo-side rollover guard for long continuous speech so one Local STT stream does not hit the default 1 MiB server buffer cap |
| `PIPECAT_ICE_SERVERS` | unset | Reserved for future STUN/TURN configuration; local `127.0.0.1` testing usually does not need it |

Example:

```bash
export RTC_ASR_WS_URL="ws://127.0.0.1:8080/v1/stt/stream"
export RTC_ASR_CHUNK_MS="100"
export RTC_ASR_MAX_UTTERANCE_SECONDS="24"
```

## Run the Demo

Recommended: use the compose stack so both services come up together:

```bash
make start
```

Open `http://127.0.0.1:8090/rtc-asr`.

If you want the manual split-terminal flow instead, start the main `rtc-asr` backend in one terminal:

```bash
make dev
```

Or use the compose stack:

```bash
make start
```

Start the browser Pipecat demo service in another terminal:

```bash
. .venv/bin/activate
uvicorn examples.browser_pipecat_demo.service.app:app --host 127.0.0.1 --port 8090
```

Open:

```text
http://127.0.0.1:8090/rtc-asr
```

Choose *Live microphone* for spoken input or *Uploaded audio file* for repeatable browser-side playback, then click **Start mic** or **Start file stream**. If you open the page in Chrome or another supported browser on `localhost` or `127.0.0.1`, the new **Install app** button lets you pin the demo locally as a PWA shell. The installed app still depends on the running local Pipecat demo service and `rtc-asr` backend.

The browser will:

1. Request microphone permission or load the selected audio clip into a browser audio graph
2. Create a native `RTCPeerConnection`
3. Create a transcript data channel
4. Add the microphone track or the browser playback track
5. Create a local SDP offer and wait briefly for ICE gathering
6. Send the offer to `/rtc-asr/offer`
7. Apply the Pipecat SDP answer with `setRemoteDescription()`
8. Stream live speech or real-time file playback through Pipecat into `rtc-asr`
9. Render transcript events received over the data channel

## Troubleshooting

### `PIPECAT_WEBRTC_DEPENDENCY_MISSING`

Install the example requirements:

```bash
pip install -r examples/browser_pipecat_demo/requirements.txt
```

### Long microphone session eventually errors or stops updating

The demo now rolls the Local STT stream before the default server buffer cap, but continuous speech is still segmented into multiple ASR utterances. If you want longer segments while testing, raise `RTC_ASR_MAX_UTTERANCE_SECONDS` and keep it below the server-side buffer limit for your sample rate.

### Bridge connects, but no transcript appears

Check that the main `rtc-asr` backend is running and that `RTC_ASR_WS_URL` points at its websocket endpoint:

```bash
curl http://127.0.0.1:8080/ready
```

### Microphone permission does not appear

Use `http://127.0.0.1:8090/rtc-asr`, `http://localhost:8090/rtc-asr`, or an HTTPS origin. Browser microphone APIs usually reject non-local plain HTTP origins.

### WebRTC fails outside localhost

This example is optimized for colocated local development. Remote browser-to-service paths may need STUN/TURN configuration and HTTPS; keep that as a separate deployment hardening step.

## Boundary

- Browser owns microphone permission, native WebRTC capture, and transcript display.
- Pipecat owns WebRTC session handling, jitter, decode, and audio frame timing.
- `rtc-asr` owns normalized audio ingestion and buffered partial/final transcript events.

## Repeatable Browser Benchmarking

When you need a real browser-originated stream instead of the synthetic websocket benchmark, switch the demo to *Uploaded audio file* and select a speech clip such as `tests/fixtures/smoke.wav`. The browser plays the file in real time, routes it through a WebRTC track, and sends it through the same Pipecat bridge path as live microphone capture.
