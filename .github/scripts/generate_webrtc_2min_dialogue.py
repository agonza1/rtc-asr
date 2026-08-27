from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro import KPipeline
from scipy.signal import resample_poly

SOURCE_RATE = 24_000
OUTPUT_RATE = 48_000
TARGET_SECONDS = 120.0
INITIAL_SILENCE_SECONDS = 0.5
MAX_BODY_SECONDS = 118.5
OUTPUT_DIR = Path("artifacts/webrtc-dialogue-2min")


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str
    pause_after_ms: int


DIALOGUE = [
    Turn("M", "When people hear WebRTC, they still picture browser-to-browser video calls. Why is it becoming important for voice AI?", 520),
    Turn("F", "Because it also works well from a client to a cloud service. It keeps audio interactive and solves connectivity, encryption, codec, and network adaptation problems that every real-time product otherwise rebuilds.", 560),
    Turn("M", "So the AI session does not need to be peer to peer.", 480),
    Turn("F", "Exactly. Media can terminate in the cloud while WebRTC provides ICE and NAT traversal, DTLS and SRTP encryption, codec negotiation, RTCP feedback, jitter buffering, and echo cancellation.", 620),
    Turn("M", "And the model can process audio while the person is still speaking.", 480),
    Turn("F", "Right. That supports faster responses, interruptions, and barge-in. OpenAI emphasizes that voice AI feels natural only when conversation moves at the speed of speech.", 600),
    Turn("M", "Which makes network behavior part of the product experience.", 480),
    Turn("F", "Yes. Jitter shifts turn timing, packet loss clips words, and long round trips create awkward pauses. Low and stable media latency matters as much as model speed.", 620),
    Turn("M", "Scaling WebRTC is not trivial, though.", 460),
    Turn("F", "No. Stateful ICE and DTLS sessions need stable ownership, media consumes ports, and global routing should keep the first hop close. OpenAI described separating relay and transceiver responsibilities to scale while preserving standard WebRTC behavior.", 700),
    Turn("M", "The data channel can carry transcripts, tool results, and control events beside the audio stream.", 520),
    Turn("F", "Exactly. An agent can keep listening while a tool runs. And for our benchmark, realistic speech is better than a beep: these synchronized male and female tracks include silence, changing energy, natural turns, and an exact two-minute loop.", 1100),
]

SPEAKERS = {
    "M": {"voice": "am_michael", "speed": 1.01, "label": "Male speaker"},
    "F": {"voice": "af_heart", "speed": 1.02, "label": "Female speaker"},
}


def silence(milliseconds: float, sample_rate: int = OUTPUT_RATE) -> np.ndarray:
    return np.zeros(round(milliseconds * sample_rate / 1_000), dtype=np.float32)


def normalize_speech(audio: np.ndarray, target_dbfs: float = -20.0) -> np.ndarray:
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if audio.size == 0:
        raise RuntimeError("The speech synthesizer returned an empty signal.")

    active = np.flatnonzero(np.abs(audio) > 2e-4)
    if active.size:
        margin = round(0.035 * SOURCE_RATE)
        audio = audio[max(0, int(active[0]) - margin) : min(audio.size, int(active[-1]) + margin + 1)]

    rms = float(np.sqrt(np.mean(np.square(audio), dtype=np.float64)))
    if rms > 0:
        desired_rms = 10 ** (target_dbfs / 20)
        peak = float(np.max(np.abs(audio)))
        gain = desired_rms / rms
        if peak > 0:
            gain = min(gain, 0.96 / peak)
        audio = audio * gain

    fade_samples = min(round(0.010 * SOURCE_RATE), audio.size // 2)
    if fade_samples > 0:
        fade = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        audio[:fade_samples] *= fade
        audio[-fade_samples:] *= fade[::-1]
    return audio.astype(np.float32, copy=False)


def synthesize_turn(pipeline: KPipeline, turn: Turn) -> np.ndarray:
    speaker = SPEAKERS[turn.speaker]
    chunks: list[np.ndarray] = []
    for _, _, audio in pipeline(turn.text, voice=str(speaker["voice"]), speed=float(speaker["speed"])):
        chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
        if chunk.size:
            chunks.append(chunk)
    if not chunks:
        raise RuntimeError(f"No audio generated for {speaker['label']}: {turn.text}")

    parts: list[np.ndarray] = []
    for index, chunk in enumerate(chunks):
        if index:
            parts.append(silence(75, SOURCE_RATE))
        parts.append(chunk)
    return normalize_speech(np.concatenate(parts))


def time_stretch_pair(male: np.ndarray, female: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    raw_seconds = male.size / OUTPUT_RATE
    if raw_seconds <= MAX_BODY_SECONDS:
        return male, female, 1.0

    tempo = raw_seconds / MAX_BODY_SECONDS
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        inputs = {"male": male, "female": female}
        outputs: dict[str, np.ndarray] = {}
        for label, audio in inputs.items():
            source_path = temp_dir / f"{label}-source.wav"
            target_path = temp_dir / f"{label}-stretched.wav"
            sf.write(source_path, audio, OUTPUT_RATE, subtype="FLOAT")
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(source_path),
                    "-filter:a", f"atempo={tempo:.9f}",
                    "-ar", str(OUTPUT_RATE), "-ac", "1", "-c:a", "pcm_f32le",
                    str(target_path),
                ],
                check=True,
            )
            rendered, rate = sf.read(target_path, dtype="float32", always_2d=False)
            if rate != OUTPUT_RATE:
                raise RuntimeError(f"Unexpected stretched sample rate: {rate}")
            outputs[label] = np.asarray(rendered, dtype=np.float32).reshape(-1)

    length = min(outputs["male"].size, outputs["female"].size)
    return outputs["male"][:length], outputs["female"][:length], tempo


def encode_mp3(source: Path, target: Path, bitrate: str, channels: int) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), "-codec:a", "libmp3lame", "-b:a", bitrate,
            "-ar", str(OUTPUT_RATE), "-ac", str(channels), str(target),
        ],
        check=True,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    pipeline = KPipeline(lang_code="a")

    male = np.zeros(0, dtype=np.float32)
    female = np.zeros(0, dtype=np.float32)
    raw_timeline: list[dict[str, object]] = []
    current_sample = 0

    for turn in DIALOGUE:
        native = synthesize_turn(pipeline, turn)
        rendered = resample_poly(native, 2, 1).astype(np.float32, copy=False)
        start_sample = current_sample
        end_sample = start_sample + rendered.size

        if turn.speaker == "M":
            male = np.concatenate((male, rendered))
            female = np.concatenate((female, np.zeros_like(rendered)))
        else:
            male = np.concatenate((male, np.zeros_like(rendered)))
            female = np.concatenate((female, rendered))

        raw_timeline.append({
            "speaker": turn.speaker,
            "label": SPEAKERS[turn.speaker]["label"],
            "voice": SPEAKERS[turn.speaker]["voice"],
            "text": turn.text,
            "rawStartSample": start_sample,
            "rawEndSample": end_sample,
            "pauseAfterMs": turn.pause_after_ms,
        })

        gap = silence(turn.pause_after_ms)
        male = np.concatenate((male, gap))
        female = np.concatenate((female, gap))
        current_sample = end_sample + gap.size

    if male.size != female.size:
        raise RuntimeError("Speaker timelines do not have identical raw lengths.")

    raw_body_samples = male.size
    male, female, tempo = time_stretch_pair(male, female)
    body_scale = male.size / raw_body_samples

    initial = np.zeros(round(INITIAL_SILENCE_SECONDS * OUTPUT_RATE), dtype=np.float32)
    male = np.concatenate((initial, male))
    female = np.concatenate((initial, female))

    target_samples = round(TARGET_SECONDS * OUTPUT_RATE)
    if male.size > target_samples or female.size > target_samples:
        male = male[:target_samples]
        female = female[:target_samples]
    else:
        male = np.pad(male, (0, target_samples - male.size))
        female = np.pad(female, (0, target_samples - female.size))

    if male.size != target_samples or female.size != target_samples:
        raise RuntimeError("Final endpoint tracks are not exactly two minutes.")

    left = male * 0.96 + female * 0.12
    right = male * 0.12 + female * 0.96
    stereo = np.column_stack((left, right)).astype(np.float32)
    peak = float(np.max(np.abs(stereo)))
    if peak > 0.98:
        stereo *= 0.98 / peak

    male_wav = OUTPUT_DIR / "webrtc-dialogue-2min-male.wav"
    female_wav = OUTPUT_DIR / "webrtc-dialogue-2min-female.wav"
    stereo_wav = OUTPUT_DIR / "webrtc-dialogue-2min-stereo.wav"
    sf.write(male_wav, male, OUTPUT_RATE, subtype="PCM_16")
    sf.write(female_wav, female, OUTPUT_RATE, subtype="PCM_16")
    sf.write(stereo_wav, stereo, OUTPUT_RATE, subtype="PCM_16")

    encode_mp3(male_wav, OUTPUT_DIR / "webrtc-dialogue-2min-male.mp3", "96k", 1)
    encode_mp3(female_wav, OUTPUT_DIR / "webrtc-dialogue-2min-female.mp3", "96k", 1)
    encode_mp3(stereo_wav, OUTPUT_DIR / "webrtc-dialogue-2min-stereo.mp3", "192k", 2)

    timeline = []
    initial_samples = initial.size
    for item in raw_timeline:
        start_sample = initial_samples + round(int(item["rawStartSample"]) * body_scale)
        end_sample = initial_samples + round(int(item["rawEndSample"]) * body_scale)
        timeline.append({
            "speaker": item["speaker"],
            "label": item["label"],
            "voice": item["voice"],
            "text": item["text"],
            "startSeconds": round(start_sample / OUTPUT_RATE, 3),
            "endSeconds": round(end_sample / OUTPUT_RATE, 3),
            "pauseAfterMsBeforeTempoAdjustment": item["pauseAfterMs"],
        })

    transcript = "\n\n".join(
        f"{'Male' if turn.speaker == 'M' else 'Female'}: {turn.text}" for turn in DIALOGUE
    ) + "\n"
    (OUTPUT_DIR / "webrtc-dialogue-2min-transcript.txt").write_text(transcript, encoding="utf-8")

    threshold = 1e-5
    overlap_samples = int(np.count_nonzero((np.abs(male) > threshold) & (np.abs(female) > threshold)))
    final_silence_samples = 0
    for index in range(target_samples - 1, -1, -1):
        if abs(float(male[index])) > threshold or abs(float(female[index])) > threshold:
            break
        final_silence_samples += 1

    manifest = {
        "profile": "webrtc-dialogue-v1",
        "durationSeconds": TARGET_SECONDS,
        "sampleRate": OUTPUT_RATE,
        "sampleCountPerEndpoint": target_samples,
        "loop": {"enabled": True, "startSeconds": 0, "endSeconds": TARGET_SECONDS},
        "speakerTracks": {
            "male": {"channels": 1, **SPEAKERS["M"], "wav": male_wav.name, "mp3": "webrtc-dialogue-2min-male.mp3"},
            "female": {"channels": 1, **SPEAKERS["F"], "wav": female_wav.name, "mp3": "webrtc-dialogue-2min-female.mp3"},
        },
        "stereoReference": {
            "channels": 2,
            "male": "left-biased (0.96 left, 0.12 right)",
            "female": "right-biased (0.12 left, 0.96 right)",
            "wav": stereo_wav.name,
            "mp3": "webrtc-dialogue-2min-stereo.mp3",
        },
        "generation": {
            "engine": "Kokoro 0.9.4",
            "rawBodySeconds": round(raw_body_samples / OUTPUT_RATE, 3),
            "renderedBodySeconds": round((target_samples - initial_samples - final_silence_samples) / OUTPUT_RATE, 3),
            "tempoAdjustment": round(tempo, 6),
        },
        "validation": {
            "exactDuration": male.size == target_samples and female.size == target_samples,
            "sharedTimeline": male.size == female.size,
            "overlapSamples": overlap_samples,
            "overlapSeconds": round(overlap_samples / OUTPUT_RATE, 6),
            "initialSilenceSeconds": INITIAL_SILENCE_SECONDS,
            "finalSilenceSeconds": round(final_silence_samples / OUTPUT_RATE, 3),
            "loopBoundarySilent": bool(final_silence_samples >= round(0.25 * OUTPUT_RATE)),
            "naturalTempoAdjustment": tempo <= 1.12,
        },
        "design": {
            "runtimeTtsRequired": False,
            "endpointTracksAreComplementary": True,
            "speechOverlap": False,
            "purpose": "Deterministic realistic speech for WebRTC transport and adaptation benchmarks",
        },
        "timeline": timeline,
        "sourceContext": [
            "OpenAI: How OpenAI delivers low-latency voice AI at scale, May 4 2026",
            "OpenAI: Advancing voice intelligence with new models in the API, May 7 2026",
        ],
    }
    (OUTPUT_DIR / "webrtc-dialogue-2min-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    validation = {
        "durationSeconds": TARGET_SECONDS,
        "sampleRate": OUTPUT_RATE,
        "maleChannels": 1,
        "femaleChannels": 1,
        "stereoReferenceChannels": 2,
        "overlapSamples": overlap_samples,
        "firstSampleMale": float(male[0]),
        "firstSampleFemale": float(female[0]),
        "lastSampleMale": float(male[-1]),
        "lastSampleFemale": float(female[-1]),
        "finalSilenceSeconds": round(final_silence_samples / OUTPUT_RATE, 3),
        "wordCount": sum(len(turn.text.split()) for turn in DIALOGUE),
        "tempoAdjustment": round(tempo, 6),
        "naturalTempoAdjustment": tempo <= 1.12,
    }
    (OUTPUT_DIR / "validation-report.json").write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(validation, indent=2))


if __name__ == "__main__":
    main()
