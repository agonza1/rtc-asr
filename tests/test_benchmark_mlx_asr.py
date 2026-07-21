from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_mlx_asr.py"
SPEC = importlib.util.spec_from_file_location("rtc_asr_benchmark_mlx_asr", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
benchmark_module = importlib.util.module_from_spec(SPEC)
sys.modules.setdefault("rtc_asr_benchmark_mlx_asr", benchmark_module)
SPEC.loader.exec_module(benchmark_module)


def test_run_benchmark_serializes_parakeet_mlx_output(monkeypatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {"commands": []}
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"RIFF")

    monkeypatch.setattr(benchmark_module.shutil, "which", lambda command: f"/mock/bin/{command}")
    monkeypatch.setattr(benchmark_module, "describe_environment", lambda: {"platform": "test"})

    def fake_run(command: list[str], *, check: bool, capture_output: bool, text: bool, **kwargs):
        assert check is True
        assert capture_output is True
        assert text is True
        calls["commands"].append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / "clip.json").write_text(json.dumps({"text": "hello from parakeet"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(benchmark_module.subprocess, "run", fake_run)

    output_path = tmp_path / "artifact.json"
    exit_code = benchmark_module.main(
        [
            "--model",
            "mlx-community/parakeet-tdt-0.6b-v3",
            "--sample-count",
            "2",
            "--audio-file",
            str(audio_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "mlx-asr-benchmark"
    assert payload["backend"] == {
        "name": "parakeet-mlx",
        "model": "mlx-community/parakeet-tdt-0.6b-v3",
        "device": "apple-silicon",
        "runtime": "mlx",
    }
    assert payload["benchmark"]["sample_count"] == 2
    assert payload["benchmark"]["command"] == "parakeet-mlx"
    assert payload["benchmark"]["speech_text"] is None
    assert len(payload["samples"]) == 2
    assert payload["samples"][0]["transcript"] == "hello from parakeet"
    assert payload["summary"]["mean_ms"] >= 0
    commands = calls["commands"]
    assert len(commands) == 2
    assert commands[0][0] == "/mock/bin/parakeet-mlx"
    assert "--model" in commands[0]
    assert "--output-format" in commands[0]


def test_run_benchmark_raises_actionable_error_when_cli_is_missing(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"RIFF")
    monkeypatch.setattr(benchmark_module.shutil, "which", lambda command: None)

    try:
        benchmark_module.run_benchmark(
            model_name="mlx-community/parakeet-tdt-0.6b-v3",
            sample_count=1,
            audio_file=audio_path,
            speech_text="hello world",
            command="parakeet-mlx",
        )
    except RuntimeError as exc:
        assert "parakeet-mlx is required" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when parakeet-mlx is unavailable")


def test_run_benchmark_falls_back_to_cli_adjacent_to_active_python(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"RIFF")
    cli_dir = tmp_path / "mlx-bin"
    cli_dir.mkdir()
    cli_path = cli_dir / "parakeet-mlx"
    cli_path.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(benchmark_module.shutil, "which", lambda command: None)
    monkeypatch.setattr(benchmark_module.sys, "executable", str(cli_dir / "python"))

    resolved = benchmark_module._resolve_cli("parakeet-mlx")

    assert resolved == str(cli_path)


def test_describe_environment_reports_mlx_host_capacity(monkeypatch) -> None:
    class FakeProcess:
        def memory_info(self) -> SimpleNamespace:
            return SimpleNamespace(rss=512 * 1024 * 1024)

    fake_psutil = SimpleNamespace(
        virtual_memory=lambda: SimpleNamespace(total=32768 * 1024 * 1024),
        Process=FakeProcess,
    )

    monkeypatch.setitem(sys.modules, "psutil", fake_psutil)
    monkeypatch.setattr(benchmark_module.platform, "platform", lambda: "TestOS")
    monkeypatch.setattr(benchmark_module.platform, "processor", lambda: "TestCPU")
    monkeypatch.setattr(benchmark_module.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(benchmark_module.os, "cpu_count", lambda: 10)
    monkeypatch.setattr(benchmark_module.os, "getpid", lambda: 4321)

    payload = benchmark_module.describe_environment()

    assert payload["platform"] == "TestOS"
    assert payload["processor"] == "TestCPU"
    assert payload["machine"] == "arm64"
    assert payload["cpu_logical_cores"] == 10
    assert payload["memory_total_mb"] == 32768.0
    assert payload["process_rss_mb"] == 512.0
    assert payload["process_metrics_pid"] == 4321
    assert payload["peak_rss_mb"] == 512.0


def test_coerce_transcript_prefers_explicit_empty_text_field() -> None:
    assert benchmark_module._coerce_transcript({"text": ""}) == ""


def test_run_benchmark_synthesizes_speech_when_audio_file_is_omitted(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    synthesized_path = tmp_path / "generated.wav"
    synthesized_path.write_bytes(b"RIFF")

    monkeypatch.setattr(benchmark_module.shutil, "which", lambda command: f"/mock/bin/{command}")
    monkeypatch.setattr(benchmark_module, "describe_environment", lambda: {"platform": "test"})

    class Scratch:
        def cleanup(self) -> None:
            return None

    monkeypatch.setattr(benchmark_module, "_resolve_audio_file", lambda audio_file, speech_text: (synthesized_path, Scratch()))

    def fake_run(command: list[str], *, check: bool, capture_output: bool, text: bool, **kwargs):
        calls.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        (output_dir / f"{Path(command[1]).stem}.json").write_text(json.dumps({"text": "spoken words"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(benchmark_module.subprocess, "run", fake_run)

    artifact = benchmark_module.run_benchmark(
        model_name="mlx-community/parakeet-tdt-0.6b-v3",
        sample_count=1,
        audio_file=None,
        speech_text="benchmark speech",
        command="parakeet-mlx",
    )

    assert artifact["benchmark"]["speech_text"] == "benchmark speech"
    assert artifact["benchmark"]["audio_file"] == "<synthesized-speech>"
    assert artifact["samples"][0]["transcript"] == "spoken words"
    assert calls[0][1].endswith("generated.wav")
