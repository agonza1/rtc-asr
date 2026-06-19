# pipecat-local-stt

`pipecat-local-stt` provides `LocalStreamingSTTService`, a Pipecat STT service that streams raw PCM16 audio to a Local STT v1 websocket sidecar and maps transcript events back into Pipecat transcription frames.

```python
from pipecat_local_stt import LocalSTTConfig, LocalStreamingSTTService

stt = LocalStreamingSTTService(
    LocalSTTConfig(
        url="ws://rtc-asr:8080/v1/stt/stream",
        sample_rate=16000,
        language="en",
        partial_interval_ms=100,
    )
)
```

Convenience wrapper:

```python
from pipecat_local_stt import RtcAsrSTTService

stt = RtcAsrSTTService(
    url="ws://rtc-asr:8080/v1/stt/stream",
    language="en",
)
```

Place the service after `transport.input()` and before `context_aggregator.user()` in a Pipecat pipeline. The plugin does not implement RTC, VAD, LLM context aggregation, or TTS.
