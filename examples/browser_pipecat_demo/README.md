# Browser Pipecat Demo

This example is a first-pass browser demo for the `rtc-asr` RTC edge pattern:

```text
Browser microphone
  -> native browser WebRTC
  -> local Pipecat-facing service at /rtc-asr
  -> future Pipecat SmallWebRTC transport
  -> future rtc-asr /ws/stream bridge
```

The demo intentionally keeps `rtc-asr` out of the browser. The browser speaks WebRTC to a local Pipecat edge service; that service is the place where decoded audio frames can later be aggregated and forwarded to `rtc-asr` over `/ws/stream`.

## Current Scope

- Serves a static single-page app at `GET /rtc-asr`
- Uses native browser APIs: `getUserMedia` and `RTCPeerConnection`
- Creates a browser SDP offer and posts it to `POST /rtc-asr/offer`
- Returns a structured `501` response until Pipecat SmallWebRTC transport wiring is enabled
- Provides smoke-testable config and session endpoints

This first iteration proves the local demo shape without adding Pipecat as a root dependency or changing the core `rtc-asr` service.

## Run Locally

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn examples.browser_pipecat_demo.service.app:app --host 127.0.0.1 --port 8090
```

Open:

```text
http://127.0.0.1:8090/rtc-asr
```

Microphone capture works on `localhost`, `127.0.0.1`, or HTTPS origins. Most browsers block `getUserMedia` on plain HTTP remote hosts.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `RTC_ASR_WS_URL` | `ws://127.0.0.1:8080/ws/stream` | Future bridge target for the ASR websocket |

## Expected Behavior Today

Clicking **Start mic** should:

1. Request microphone permission
2. Create a native `RTCPeerConnection`
3. Add the microphone audio track
4. Create a local SDP offer
5. Send that offer to `/rtc-asr/offer`
6. Show the structured `PIPECAT_TRANSPORT_NOT_CONFIGURED` response

That response is deliberate. It prevents the scaffold from pretending that the Pipecat media bridge is already active.

## Next Step

Wire `PipecatDemoBridge.create_session()` to Pipecat's SmallWebRTC transport. Once that transport returns a server SDP answer, the browser can call `setRemoteDescription()` and the bridge can relay decoded PCM frames to `rtc-asr` in `80` to `160` ms websocket chunks.

Keep the production boundary clear:

- Browser owns microphone permission and native WebRTC capture.
- Pipecat owns WebRTC session handling, jitter, decode, and audio frame timing.
- `rtc-asr` owns normalized audio ingestion and buffered partial/final transcript events.
