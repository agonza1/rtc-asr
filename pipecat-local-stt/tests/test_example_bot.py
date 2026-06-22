from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


EXAMPLE_PATH = Path(__file__).resolve().parents[2] / "examples" / "pipecat_local_stt_bot" / "bot.py"


def load_example_module():
    spec = importlib.util.spec_from_file_location("pipecat_local_stt_example_bot", EXAMPLE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_example_bot_defaults_match_local_stt_hot_path(monkeypatch) -> None:
    module = load_example_module()
    monkeypatch.delenv("RTC_ASR_WS_URL", raising=False)

    settings = module.BotSettings.from_env()

    assert settings.ws_url == "ws://rtc-asr:8080/v1/stt/stream"
    assert settings.sample_rate == 16000
    assert settings.channels == 1
    assert settings.frame_ms == 20
    assert settings.partial_interval_ms == 100
    assert settings.partial_window_seconds == 1.0


def test_example_bot_builds_both_sidecar_service_choices(monkeypatch) -> None:
    module = load_example_module()

    monkeypatch.setenv("RTC_ASR_WS_URL", "ws://127.0.0.1:8080/v1/stt/stream")
    local_settings = module.BotSettings.from_env()
    local_service = module.build_stt(local_settings)

    assert local_service.config.url == "ws://127.0.0.1:8080/v1/stt/stream"
    assert local_service.config.partial_interval_ms == 100

    monkeypatch.setenv("LOCAL_STT_SERVICE", "rtc-asr")
    wrapper_settings = module.BotSettings.from_env()
    wrapper_service = module.build_stt(wrapper_settings)

    assert wrapper_service.config.url == "ws://127.0.0.1:8080/v1/stt/stream"
    assert wrapper_service.config.frame_ms == 20
