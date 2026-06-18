from __future__ import annotations

import pytest

from src.protocols.local_stt_v1 import (
    HOT_PATH_BYTES_PER_FRAME,
    HOT_PATH_CHANNELS,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    HOT_PATH_SAMPLE_RATE,
    PROTOCOL_VERSION,
    ErrorMessage,
    LocalSttProtocolError,
    TranscriptMessage,
    parse_client_message,
    parse_server_message,
    build_hot_path_audio_format,
    build_ready_message,
    build_start_message,
    validate_audio_chunk,
)


def test_builders_emit_hot_path_messages_for_clients_and_servers() -> None:
    start = build_start_message(
        partial_interval_ms=100,
        partial_window_seconds=1.5,
        max_buffer_seconds=10,
        client_stream_id="turn-abc",
        metadata={"turn_id": "abc"},
    )
    ready = build_ready_message(metadata={"session_id": "session-1"})

    assert start.model_dump() == {
        "type": "start",
        "version": PROTOCOL_VERSION,
        "audio": build_hot_path_audio_format().model_dump(),
        "language": "en",
        "interim_results": True,
        "partial_interval_ms": 100,
        "partial_window_seconds": 1.5,
        "max_buffer_seconds": 10.0,
        "client_stream_id": "turn-abc",
        "metadata": {"turn_id": "abc"},
    }
    assert ready.model_dump() == {
        "type": "ready",
        "version": PROTOCOL_VERSION,
        "audio": build_hot_path_audio_format().model_dump(),
        "interim_results": True,
        "metadata": {"session_id": "session-1"},
    }


def test_start_message_validates_and_ignores_unknown_optional_fields() -> None:
    message = parse_client_message(
        {
            "type": "start",
            "version": PROTOCOL_VERSION,
            "audio": {
                "sample_rate": HOT_PATH_SAMPLE_RATE,
                "channels": HOT_PATH_CHANNELS,
                "format": HOT_PATH_PCM_FORMAT,
                "frame_ms": HOT_PATH_FRAME_MS,
                "bytes_per_frame": HOT_PATH_BYTES_PER_FRAME,
                "ignored": "value",
            },
            "language": "en",
            "interim_results": True,
            "partial_interval_ms": 100,
            "partial_window_seconds": 1.5,
            "max_buffer_seconds": 10,
            "client_stream_id": "turn-abc",
            "metadata": {"turn_id": "abc"},
            "extra_optional": "ignored",
        }
    )

    assert message.type == "start"
    assert message.version == PROTOCOL_VERSION
    assert message.audio.bytes_per_frame == HOT_PATH_BYTES_PER_FRAME
    assert message.partial_interval_ms == 100
    assert message.partial_window_seconds == pytest.approx(1.5)
    assert message.max_buffer_seconds == pytest.approx(10.0)
    assert message.client_stream_id == "turn-abc"
    assert message.metadata == {"turn_id": "abc"}
    assert "extra_optional" not in message.model_dump()
    assert "ignored" not in message.audio.model_dump()


def test_start_message_unsupported_required_audio_field_maps_to_protocol_error() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_client_message(
            {
                "type": "start",
                "version": PROTOCOL_VERSION,
                "audio": {
                    "sample_rate": 48000,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                },
            }
        )

    error_event = excinfo.value.as_event()
    assert error_event.model_dump() == {
        "type": "error",
        "code": "unsupported_audio_format",
        "message": f"audio: audio.sample_rate must be {HOT_PATH_SAMPLE_RATE}",
        "metadata": {},
        "retryable": False,
        "fatal": True,
    }


def test_transcript_message_validates_required_fields_and_ignores_unknown_optionals() -> None:
    message = parse_server_message(
        {
            "type": "transcript",
            "text": "hello world",
            "is_final": False,
            "speech_final": False,
            "revision": 1,
            "audio_received_ms": 1000,
            "audio_transcribed_ms": 900,
            "metadata": {"source": "fixture"},
            "language": "en",
            "extra_optional": "ignored",
        }
    )

    assert isinstance(message, TranscriptMessage)
    assert message.metadata == {"source": "fixture"}
    assert "extra_optional" not in message.model_dump()


@pytest.mark.parametrize(
    ("payload", "expected_cls"),
    [
        (
            {
                "type": "warning",
                "code": "partial_dropped",
                "message": "Dropped one partial due to backpressure",
                "metadata": {"partial_revision": 2},
                "ignored": True,
            },
            "warning",
        ),
        (
            {
                "type": "error",
                "code": "unsupported_audio_format",
                "message": "audio.sample_rate must be 16000",
                "metadata": {"field": "audio.sample_rate"},
                "fatal": True,
                "ignored": True,
            },
            "error",
        ),
    ],
)
def test_warning_and_error_messages_validate(payload: dict[str, object], expected_cls: str) -> None:
    message = parse_server_message(payload)
    assert message.type == expected_cls
    dumped = message.model_dump()
    assert "ignored" not in dumped
    assert dumped["metadata"]


def test_invalid_transcript_timing_maps_to_protocol_error() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_server_message(
            {
                "type": "transcript",
                "text": "hello world",
                "is_final": True,
                "speech_final": True,
                "revision": 2,
                "audio_received_ms": 100,
                "audio_transcribed_ms": 120,
                "metadata": {},
            }
        )

    assert excinfo.value.as_event().model_dump() == ErrorMessage(
        type="error",
        code="invalid_timing_metadata",
        message="audio_transcribed_ms must be less than or equal to audio_received_ms",
    ).model_dump()



def test_start_message_rejects_nonpositive_partial_window_seconds() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_client_message(
            {
                "type": "start",
                "version": PROTOCOL_VERSION,
                "audio": {
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                },
                "partial_window_seconds": 0,
            }
        )

    assert excinfo.value.as_event().code == "invalid_message"
    assert "partial_window_seconds" in excinfo.value.message



def test_unknown_message_type_maps_to_protocol_error() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_client_message({"type": "resume"})

    assert excinfo.value.as_event().model_dump() == ErrorMessage(
        type="error",
        code="unsupported_message_type",
        message="Unsupported Local STT v1 message type: resume",
    ).model_dump()


def test_start_message_rejects_legacy_protocol_version() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_client_message(
            {
                "type": "start",
                "version": "local-stt-v0",
                "audio": {
                    "sample_rate": HOT_PATH_SAMPLE_RATE,
                    "channels": HOT_PATH_CHANNELS,
                    "format": HOT_PATH_PCM_FORMAT,
                    "frame_ms": HOT_PATH_FRAME_MS,
                },
            }
        )

    assert excinfo.value.as_event().code == "invalid_message"
    assert "version" in excinfo.value.message


@pytest.mark.parametrize("payload", [None, "not-json", ["start"]])
def test_non_object_messages_map_to_protocol_error(payload: object) -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_server_message(payload)

    assert excinfo.value.as_event().model_dump() == ErrorMessage(
        type="error",
        code="invalid_message",
        message="Local STT v1 messages must be JSON objects",
    ).model_dump()


@pytest.mark.parametrize(
    ("chunk", "expected_code", "expected_message"),
    [
        (
            "aGVsbG8=",
            "audio_must_be_binary",
            "Audio frames must be sent as binary PCM16 websocket messages; Local STT v1 never base64-wraps audio",
        ),
        (b"", "invalid_audio_chunk", "Audio frames must not be empty"),
        (b"\x01", "invalid_audio_chunk", "PCM16 audio frames must contain an even number of bytes"),
        (123, "invalid_audio_chunk", "Audio frames must be bytes-like PCM16 payloads"),
    ],
)
def test_invalid_audio_chunks_map_to_protocol_error(
    chunk: object,
    expected_code: str,
    expected_message: str,
) -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        validate_audio_chunk(chunk)

    assert excinfo.value.as_event().model_dump() == ErrorMessage(
        type="error",
        code=expected_code,
        message=expected_message,
    ).model_dump()


def test_validate_audio_chunk_accepts_even_sized_bytes_like_payloads() -> None:
    payload = memoryview(b"\x00\x01\x02\x03")

    assert validate_audio_chunk(payload) == b"\x00\x01\x02\x03"
