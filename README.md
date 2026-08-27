# WebRTC TestLab dialogue-v1 audio

Deterministic two-minute male/female conversation audio for WebRTC TestLab.

- Channel 0: male speaker
- Channel 1: female speaker
- Exact shared 120-second timeline
- No active-speech overlap
- Generated offline with Kokoro 0.9.4; no runtime TTS

The consuming runner verifies the SHA-256 in `manifest.json` before decoding the asset.
