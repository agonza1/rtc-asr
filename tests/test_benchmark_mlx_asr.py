from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
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

    def fake_run(command: list[str], *, check: bool, capture_output: bool, text: bool):
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
            command="parakeet-mlx",
        )
    except RuntimeError as exc:
        assert "parakeet-mlx is required" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError when parakeet-mlx is unavailable")
