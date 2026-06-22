from __future__ import annotations

import py_compile
import importlib.util
import sys
from pathlib import Path


EXAMPLE_DIR = Path("examples") / "pipecat_local_stt_bot"
BOT_PATH = EXAMPLE_DIR / "bot.py"


def load_bot_module() -> object:
    package_src = str(Path("pipecat-local-stt") / "src")
    if package_src not in sys.path:
        sys.path.insert(0, package_src)
    spec = importlib.util.spec_from_file_location("pipecat_local_stt_bot_example", BOT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("pipecat_local_stt_bot_example", module)
    spec.loader.exec_module(module)
    return module


def test_pipecat_local_stt_bot_example_documents_sidecar_contract() -> None:
    readme = (EXAMPLE_DIR / "README.md").read_text(encoding="utf-8")

    assert "browser/client -> Pipecat transport -> LocalStreamingSTTService -> rtc-asr /v1/stt/stream" in readme
    assert "This is not WebRTC-to-ASR" in readme
    assert "This is not Deepgram/OpenAI-compatible" in readme
    assert "ws://rtc-asr:8080/v1/stt/stream" in readme
    assert "language=en" in readme
    assert "LOCAL_STT_LANGUAGE=" in readme
    assert "sample_rate=16000" in readme
    assert "channels=1" in readme
    assert "format=pcm_s16le" in readme
    assert "frame_ms=20" in readme
    assert "partial_interval_ms=100" in readme
    assert "partial_window_seconds=1.0" in readme
    assert "max_buffer_seconds=10.0" in readme
    assert "LOCAL_STT_MAX_BUFFER_SECONDS" in readme
    assert "LOCAL_STT_SERVICE=local" in readme
    assert "LOCAL_STT_SERVICE=rtc-asr" in readme
    assert "Pipecat Whisper is local/offline" in readme
    assert "Connection failures" in readme
    assert "Wrong sample rates" in readme
    assert "Missing interim transcripts" in readme


def test_pipecat_local_stt_bot_example_compose_uses_sidecar_service_discovery() -> None:
    compose = (EXAMPLE_DIR / "docker-compose.yml").read_text(encoding="utf-8")
    requirements = (EXAMPLE_DIR / "requirements.txt").read_text(encoding="utf-8")

    assert "rtc-asr:" in compose
    assert "pipecat-local-stt-bot:" in compose
    assert "condition: service_healthy" in compose
    assert "RTC_ASR_WS_URL: ws://rtc-asr:8080/v1/stt/stream" in compose
    assert 'LOCAL_STT_SAMPLE_RATE: "16000"' in compose
    assert 'LOCAL_STT_CHANNELS: "1"' in compose
    assert 'LOCAL_STT_FRAME_MS: "20"' in compose
    assert 'LOCAL_STT_PARTIAL_INTERVAL_MS: "100"' in compose
    assert 'LOCAL_STT_MAX_BUFFER_SECONDS: "10.0"' in compose
    assert "pipecat-ai[webrtc]>=1.3.0" in requirements
    assert "pipecat-local-stt" in requirements


def test_pipecat_local_stt_bot_example_is_syntax_valid() -> None:
    py_compile.compile(str(EXAMPLE_DIR / "bot.py"), doraise=True)
    bot_source = (EXAMPLE_DIR / "bot.py").read_text(encoding="utf-8")

    assert "LocalStreamingSTTService" in bot_source
    assert "RtcAsrSTTService" in bot_source
    assert "LOCAL_STT_SERVICE" in bot_source
    assert "def build_stt" in bot_source
    assert "transport.input()" in bot_source
    assert "context_aggregator.user()" in bot_source
    assert "transport.output()" in bot_source


def test_pipecat_local_stt_bot_example_reads_environment_at_runtime(monkeypatch) -> None:
    module = load_bot_module()

    monkeypatch.setenv("LOCAL_STT_SERVICE", "rtc-asr")
    monkeypatch.setenv("RTC_ASR_WS_URL", "ws://127.0.0.1:8080/v1/stt/stream")
    monkeypatch.setenv("LOCAL_STT_LANGUAGE", "")
    monkeypatch.setenv("LOCAL_STT_SAMPLE_RATE", "8000")
    monkeypatch.setenv("LOCAL_STT_CHANNELS", "2")
    monkeypatch.setenv("LOCAL_STT_FRAME_MS", "40")
    monkeypatch.setenv("LOCAL_STT_PARTIAL_INTERVAL_MS", "250")
    monkeypatch.setenv("LOCAL_STT_PARTIAL_WINDOW_SECONDS", "1.5")
    monkeypatch.setenv("LOCAL_STT_MAX_BUFFER_SECONDS", "6.0")

    settings = module.BotSettings.from_env()

    assert settings.service == "rtc-asr"
    assert settings.ws_url == "ws://127.0.0.1:8080/v1/stt/stream"
    assert settings.language is None
    assert settings.sample_rate == 8000
    assert settings.channels == 2
    assert settings.frame_ms == 40
    assert settings.partial_interval_ms == 250
    assert settings.partial_window_seconds == 1.5
    assert settings.max_buffer_seconds == 6.0


def test_pipecat_local_stt_bot_example_selects_supported_sidecar_services() -> None:
    module = load_bot_module()

    assert module.build_stt(module.BotSettings(service="local")).__class__.__name__ == "LocalStreamingSTTService"
    assert module.build_stt(module.BotSettings(service="rtc-asr")).__class__.__name__ == "RtcAsrSTTService"


def test_pipecat_local_stt_bot_example_applies_tuning_to_rtc_asr_service() -> None:
    module = load_bot_module()

    stt = module.build_stt(
        module.BotSettings(
            service="rtc-asr",
            sample_rate=8000,
            channels=2,
            frame_ms=40,
            partial_interval_ms=250,
            partial_window_seconds=1.5,
            max_buffer_seconds=6.0,
            language="es",
        )
    )

    assert stt.config.language == "es"
    assert stt.config.sample_rate == 8000
    assert stt.config.channels == 2
    assert stt.config.frame_ms == 40
    assert stt.config.partial_interval_ms == 250
    assert stt.config.partial_window_seconds == 1.5
    assert stt.config.max_buffer_seconds == 6.0


def test_pipecat_local_stt_bot_example_rejects_unknown_service() -> None:
    module = load_bot_module()

    try:
        module.build_stt(module.BotSettings(service="whisper"))
    except ValueError as exc:
        assert "LOCAL_STT_SERVICE" in str(exc)
    else:
        raise AssertionError("Unknown LOCAL_STT_SERVICE should fail fast")
