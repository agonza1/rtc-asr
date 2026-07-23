from __future__ import annotations

import pytest

from src.protocols.local_stt_v1 import (
    HOT_PATH_BYTES_PER_FRAME,
    HOT_PATH_CHANNELS,
    HOT_PATH_FRAME_MS,
    HOT_PATH_PCM_FORMAT,
    HOT_PATH_SAMPLE_RATE,
    PROTOCOL_VERSION,
    RAW_UDS_CLIENT_FRAME_TYPES,
    RAW_UDS_FRAME_DIRECTION,
    RAW_UDS_HEADER_BYTES,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RAW_UDS_SERVER_FRAME_TYPES,
    RawUdsFrameDecoder,
    RawUdsFrameType,
    ErrorMessage,
    LocalSttProtocolError,
    TranscriptMessage,
    parse_client_message,
    parse_server_message,
    build_hot_path_audio_format,
    build_ready_message,
    build_start_message,
    decode_raw_uds_frame,
    decode_raw_uds_json_payload,
    encode_raw_uds_audio_frame,
    encode_raw_uds_client_message,
    encode_raw_uds_frame,
    encode_raw_uds_json_frame,
    encode_raw_uds_protocol_error,
    encode_raw_uds_server_message,
    parse_raw_uds_client_frame,
    parse_raw_uds_server_frame,
    validate_audio_chunk,
)


def test_raw_uds_direction_constants_match_parsers() -> None:
    assert RAW_UDS_FRAME_DIRECTION == {
        "client_to_server": ["JSON_CONTROL", "AUDIO_PCM16", "PING", "PONG"],
        "server_to_client": ["JSON_EVENT", "ERROR", "PING", "PONG"],
    }
    assert RawUdsFrameType.JSON_EVENT not in RAW_UDS_CLIENT_FRAME_TYPES
    assert RawUdsFrameType.JSON_CONTROL not in RAW_UDS_SERVER_FRAME_TYPES


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
            "Audio frames must be sent as binary PCM16 transport payloads; Local STT v1 never base64-wraps audio",
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


def test_realtime_style_turn_lifecycle_maps_to_local_stt_v1_contract() -> None:
    start = parse_client_message(
        build_start_message(
            partial_interval_ms=100,
            partial_window_seconds=1.0,
            client_stream_id="response-1",
            metadata={"realtime_event": "input_audio_buffer.append"},
        ).model_dump()
    )
    audio = validate_audio_chunk(b"\x00\x00" * (HOT_PATH_SAMPLE_RATE // 10))
    partial = parse_server_message(
        {
            "type": "transcript",
            "text": "hello",
            "is_final": False,
            "speech_final": False,
            "revision": 1,
            "audio_received_ms": 100,
            "audio_transcribed_ms": 80,
            "metadata": {"client_stream_id": "response-1"},
        }
    )
    finalize = parse_client_message({"type": "finalize"})
    final = parse_server_message(
        {
            "type": "transcript",
            "text": "hello world",
            "is_final": True,
            "speech_final": True,
            "revision": 2,
            "audio_received_ms": 100,
            "audio_transcribed_ms": 100,
            "metadata": {"client_stream_id": "response-1"},
        }
    )
    cancel = parse_client_message({"type": "cancel"})

    assert start.type == "start"
    assert start.client_stream_id == "response-1"
    assert len(audio) == HOT_PATH_BYTES_PER_FRAME * 5
    assert partial.type == "transcript"
    assert not partial.is_final
    assert finalize.type == "finalize"
    assert final.is_final
    assert final.speech_final
    assert cancel.type == "cancel"


def test_protocol_package_exports_raw_uds_server_helpers() -> None:
    from src.protocols import RawUdsFrameDecoder as ExportedDecoder
    from src.protocols import encode_raw_uds_client_message as exported_encode_client_message
    from src.protocols import encode_raw_uds_protocol_error as exported_encode_protocol_error
    from src.protocols import parse_raw_uds_server_frame as exported_parse_server_frame

    assert ExportedDecoder is RawUdsFrameDecoder
    assert exported_encode_client_message is encode_raw_uds_client_message
    assert exported_encode_protocol_error is encode_raw_uds_protocol_error
    assert exported_parse_server_frame is parse_raw_uds_server_frame


def test_raw_uds_frame_codec_round_trips_binary_audio_payload() -> None:
    encoded = encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x01\x02\x03")

    assert encoded[:RAW_UDS_HEADER_BYTES] == b"\x02\x04\x00\x00\x00"
    decoded = decode_raw_uds_frame(encoded)

    assert decoded.frame_type == RawUdsFrameType.AUDIO_PCM16
    assert decoded.payload == b"\x00\x01\x02\x03"


def test_raw_uds_json_frame_codec_uses_compact_object_payload() -> None:
    encoded = encode_raw_uds_json_frame(RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "p1"})
    decoded = decode_raw_uds_frame(encoded)

    assert decoded.frame_type == RawUdsFrameType.JSON_CONTROL
    assert decoded.payload == b'{"type":"ping","ping_id":"p1"}'
    assert decode_raw_uds_json_payload(decoded) == {"type": "ping", "ping_id": "p1"}


def test_raw_uds_client_encoders_select_control_ping_and_audio_frames() -> None:
    start = decode_raw_uds_frame(encode_raw_uds_client_message(build_start_message().model_dump()))
    bare_ping = decode_raw_uds_frame(encode_raw_uds_client_message({"type": "ping"}))
    ping = decode_raw_uds_frame(encode_raw_uds_client_message({"type": "ping", "ping_id": "p1"}))
    bare_pong = decode_raw_uds_frame(encode_raw_uds_client_message({"type": "pong"}))
    pong = decode_raw_uds_frame(encode_raw_uds_client_message({"type": "pong", "ping_id": "server-1"}))
    metadata_pong = decode_raw_uds_frame(
        encode_raw_uds_client_message({"type": "pong", "metadata": {"server_ping": "server-2"}})
    )
    audio = decode_raw_uds_frame(encode_raw_uds_audio_frame(memoryview(b"\x00\x01")))

    assert start.frame_type == RawUdsFrameType.JSON_CONTROL
    assert bare_ping.frame_type == RawUdsFrameType.PING
    assert bare_ping.payload == b""
    assert parse_raw_uds_client_frame(bare_ping).type == "ping"
    assert ping.frame_type == RawUdsFrameType.PING
    assert decode_raw_uds_json_payload(ping) == {"type": "ping", "ping_id": "p1"}
    assert bare_pong.frame_type == RawUdsFrameType.PONG
    assert bare_pong.payload == b""
    assert parse_raw_uds_client_frame(bare_pong).type == "pong"
    assert pong.frame_type == RawUdsFrameType.PONG
    assert decode_raw_uds_json_payload(pong) == {"type": "pong", "ping_id": "server-1"}
    assert metadata_pong.frame_type == RawUdsFrameType.PONG
    assert decode_raw_uds_json_payload(metadata_pong) == {"type": "pong", "metadata": {"server_ping": "server-2"}}
    assert audio.frame_type == RawUdsFrameType.AUDIO_PCM16
    assert audio.payload == b"\x00\x01"


def test_raw_uds_server_helpers_support_server_initiated_ping_frames() -> None:
    encoded = encode_raw_uds_server_message({"type": "ping", "ping_id": "server-1"})
    frame = decode_raw_uds_frame(encoded)
    bare_ping = decode_raw_uds_frame(encode_raw_uds_server_message({"type": "ping", "metadata": {}}))

    assert frame.frame_type == RawUdsFrameType.PING
    assert parse_raw_uds_server_frame(frame).model_dump(exclude_none=True) == {
        "type": "ping",
        "ping_id": "server-1",
    }
    assert bare_ping.frame_type == RawUdsFrameType.PING
    assert bare_ping.payload == b""
    assert parse_raw_uds_server_frame(bare_ping).model_dump(exclude_none=True) == {"type": "ping"}


def test_raw_uds_client_encoder_accepts_issue_88_flat_start_payload() -> None:
    encoded = encode_raw_uds_client_message(
        {
            "type": "start",
            "protocol": "local-stt-v1",
            "sample_rate": 16000,
            "channels": 1,
            "format": "pcm_s16le",
            "frame_ms": 20,
        }
    )
    frame = decode_raw_uds_frame(encoded)

    assert frame.frame_type == RawUdsFrameType.JSON_CONTROL
    payload = decode_raw_uds_json_payload(frame)
    assert payload["version"] == PROTOCOL_VERSION
    assert payload["audio"] == {
        "sample_rate": HOT_PATH_SAMPLE_RATE,
        "channels": HOT_PATH_CHANNELS,
        "format": HOT_PATH_PCM_FORMAT,
        "frame_ms": HOT_PATH_FRAME_MS,
    }
    assert "protocol" not in payload
    assert parse_raw_uds_client_frame(frame).type == "start"


def test_raw_uds_audio_encoder_rejects_invalid_pcm16_payloads() -> None:
    with pytest.raises(LocalSttProtocolError) as excinfo:
        encode_raw_uds_audio_frame(b"\x00")

    assert excinfo.value.as_event().code == "invalid_audio_chunk"


def test_raw_uds_frame_decoder_buffers_socket_chunk_boundaries() -> None:
    decoder = RawUdsFrameDecoder()
    first = encode_raw_uds_json_frame(RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "p1"})
    second = encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x01\x02\x03")

    assert decoder.feed(first[:2]) == []
    assert decoder.buffered_bytes == 2
    assert decoder.feed(first[2:RAW_UDS_HEADER_BYTES]) == []
    frames = decoder.feed(first[RAW_UDS_HEADER_BYTES:] + second)

    assert [(frame.frame_type, frame.payload) for frame in frames] == [
        (RawUdsFrameType.JSON_CONTROL, b'{"type":"ping","ping_id":"p1"}'),
        (RawUdsFrameType.AUDIO_PCM16, b"\x00\x01\x02\x03"),
    ]
    assert decoder.buffered_bytes == 0


def test_raw_uds_frame_decoder_finish_rejects_partial_tail() -> None:
    decoder = RawUdsFrameDecoder()
    encoded = encode_raw_uds_json_frame(
        RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "truncated"}
    )

    assert decoder.feed(encoded[:-1]) == []
    assert decoder.buffered_bytes == len(encoded) - 1
    with pytest.raises(LocalSttProtocolError) as excinfo:
        decoder.finish()

    assert excinfo.value.as_event().code == "raw_uds_incomplete_frame"
    assert "buffered frame bytes" in excinfo.value.message
    assert decoder.buffered_bytes == 0
    frames = decoder.feed(encode_raw_uds_frame(RawUdsFrameType.PING, b""))

    assert frames[0].frame_type == RawUdsFrameType.PING


def test_raw_uds_frame_decoder_finish_accepts_empty_buffer() -> None:
    decoder = RawUdsFrameDecoder()

    decoder.finish()

    assert decoder.buffered_bytes == 0


def test_raw_uds_frame_decoder_rejects_oversized_payload_before_body_arrives() -> None:
    decoder = RawUdsFrameDecoder()
    header = bytes([RawUdsFrameType.AUDIO_PCM16]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little")

    with pytest.raises(LocalSttProtocolError) as excinfo:
        decoder.feed(header)

    assert excinfo.value.as_event().code == "raw_uds_payload_too_large"


def test_raw_uds_frame_decoder_clears_oversized_frame_after_error() -> None:
    decoder = RawUdsFrameDecoder()
    oversized_header = bytes([RawUdsFrameType.AUDIO_PCM16]) + (
        RAW_UDS_MAX_PAYLOAD_BYTES + 1
    ).to_bytes(4, "little")
    valid_ping = encode_raw_uds_json_frame(
        RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "after-error"}
    )

    with pytest.raises(LocalSttProtocolError):
        decoder.feed(oversized_header)

    assert decoder.buffered_bytes == 0
    frames = decoder.feed(valid_ping)
    decoded_frames = [(frame.frame_type, decode_raw_uds_json_payload(frame)) for frame in frames]
    assert decoded_frames == [
        (RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "after-error"})
    ]


def test_raw_uds_frame_decoder_clears_unknown_frame_after_error() -> None:
    decoder = RawUdsFrameDecoder()
    unknown_header = b"\xff\x00\x00\x00\x00"
    valid_ping = encode_raw_uds_json_frame(
        RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "after-unknown"}
    )

    with pytest.raises(LocalSttProtocolError):
        decoder.feed(unknown_header)

    assert decoder.buffered_bytes == 0
    frames = decoder.feed(valid_ping)
    decoded_frames = [(frame.frame_type, decode_raw_uds_json_payload(frame)) for frame in frames]
    assert decoded_frames == [
        (RawUdsFrameType.JSON_CONTROL, {"type": "ping", "ping_id": "after-unknown"})
    ]


def test_raw_uds_client_ping_frame_accepts_empty_payload() -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.PING, b""))

    message = parse_raw_uds_client_frame(frame)

    assert message.type == "ping"
    assert message.ping_id is None


def test_raw_uds_client_ping_frame_classifies_malformed_payload_as_control_error() -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.PING, b"{"))

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_client_frame(frame)

    error = excinfo.value.as_event()
    assert error.code == "raw_uds_malformed_json_control"
    assert error.metadata == {"original_code": "raw_uds_invalid_json"}


def test_raw_uds_client_ping_frame_classifies_schema_errors_as_control_error() -> None:
    frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.PING, {"type": "ping", "timestamp_ms": -1})
    )

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_client_frame(frame)

    error = excinfo.value.as_event()
    assert error.code == "raw_uds_malformed_json_control"
    assert error.metadata == {"original_code": "invalid_message"}
    assert "timestamp_ms" in error.message


def test_raw_uds_frame_decoder_rejects_length_mismatch() -> None:
    encoded = b"\x01\x04\x00\x00\x00{}"

    with pytest.raises(LocalSttProtocolError) as excinfo:
        decode_raw_uds_frame(encoded)

    assert excinfo.value.as_event().code == "raw_uds_frame_length_mismatch"


def test_raw_uds_frame_decoder_rejects_unknown_frame_type() -> None:
    encoded = b"\xff\x00\x00\x00\x00"

    with pytest.raises(LocalSttProtocolError) as excinfo:
        decode_raw_uds_frame(encoded)

    assert excinfo.value.as_event().code == "raw_uds_unsupported_frame_type"


def test_raw_uds_json_decoder_rejects_audio_frames() -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x00"))

    with pytest.raises(LocalSttProtocolError) as excinfo:
        decode_raw_uds_json_payload(frame)

    assert excinfo.value.as_event().code == "raw_uds_invalid_json_frame_type"


def test_raw_uds_client_frame_parser_maps_control_ping_and_audio() -> None:
    start_frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(
            RawUdsFrameType.JSON_CONTROL,
            build_start_message(partial_interval_ms=100).model_dump(),
        )
    )
    ping_frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.PING, {"ping_id": "p1"})
    )
    pong_frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.PONG, {"ping_id": "server-1"})
    )
    audio_frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x01"))

    start = parse_raw_uds_client_frame(start_frame)
    ping = parse_raw_uds_client_frame(ping_frame)
    pong = parse_raw_uds_client_frame(pong_frame)
    audio = parse_raw_uds_client_frame(audio_frame)

    assert start.type == "start"
    assert ping.type == "ping"
    assert ping.ping_id == "p1"
    assert pong.type == "pong"
    assert pong.ping_id == "server-1"
    assert audio == b"\x00\x01"


def test_raw_uds_client_frame_parser_accepts_issue_88_flat_start_payload() -> None:
    frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(
            RawUdsFrameType.JSON_CONTROL,
            {
                "type": "start",
                "protocol": "local-stt-v1",
                "sample_rate": 16000,
                "channels": 1,
                "format": "pcm_s16le",
                "frame_ms": 20,
                "partial_interval_ms": 100,
                "client_stream_id": "raw-uds-experiment",
            },
        )
    )

    start = parse_raw_uds_client_frame(frame)

    assert start.type == "start"
    assert start.version == "local-stt.v1"
    assert start.audio.sample_rate == 16000
    assert start.audio.frame_ms == 20
    assert start.partial_interval_ms == 100
    assert start.client_stream_id == "raw-uds-experiment"


def test_raw_uds_client_frame_parser_classifies_schema_bad_json_control() -> None:
    frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.JSON_CONTROL, {"type": "start"})
    )

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_client_frame(frame)

    error = excinfo.value.as_event()
    assert error.code == "raw_uds_malformed_json_control"
    assert error.metadata == {"original_code": "invalid_message"}


def test_raw_uds_client_frame_parser_classifies_syntax_bad_json_control() -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.JSON_CONTROL, b"{"))

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_client_frame(frame)

    error = excinfo.value.as_event()
    assert error.code == "raw_uds_malformed_json_control"
    assert error.metadata == {"original_code": "raw_uds_invalid_json"}


def test_raw_uds_client_frame_parser_rejects_server_frame_types() -> None:
    event_frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, build_ready_message().model_dump())
    )

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_client_frame(event_frame)

    assert excinfo.value.as_event().code == "raw_uds_invalid_client_frame_type"


def test_raw_uds_server_encoder_selects_event_error_and_pong_frame_types() -> None:
    ready = decode_raw_uds_frame(encode_raw_uds_server_message(build_ready_message().model_dump()))
    error = decode_raw_uds_frame(
        encode_raw_uds_server_message(
            ErrorMessage(type="error", code="bad", message="bad request").model_dump()
        )
    )
    pong = decode_raw_uds_frame(
        encode_raw_uds_server_message({"type": "pong", "ping_id": "p1", "metadata": {}})
    )

    assert ready.frame_type == RawUdsFrameType.JSON_EVENT
    assert error.frame_type == RawUdsFrameType.ERROR
    assert pong.frame_type == RawUdsFrameType.PONG
    assert decode_raw_uds_json_payload(pong)["ping_id"] == "p1"


def test_raw_uds_server_encoder_omits_empty_optional_fields() -> None:
    pong = decode_raw_uds_frame(
        encode_raw_uds_server_message({"type": "pong", "ping_id": "p1", "metadata": {}})
    )
    bare_pong = decode_raw_uds_frame(encode_raw_uds_server_message({"type": "pong", "metadata": {}}))

    assert pong.payload == b'{"type":"pong","ping_id":"p1"}'
    assert parse_raw_uds_server_frame(pong).ping_id == "p1"
    assert bare_pong.frame_type == RawUdsFrameType.PONG
    assert bare_pong.payload == b""
    parsed_bare_pong = parse_raw_uds_server_frame(bare_pong)
    assert parsed_bare_pong.type == "pong"
    assert parsed_bare_pong.ping_id is None


def test_raw_uds_protocol_error_encoder_emits_parseable_error_frame() -> None:
    exc = LocalSttProtocolError(
        "Raw UDS JSON frame payload must be valid UTF-8 JSON",
        code="raw_uds_invalid_json",
    )

    frame = decode_raw_uds_frame(encode_raw_uds_protocol_error(exc))
    message = parse_raw_uds_server_frame(frame)

    assert frame.frame_type == RawUdsFrameType.ERROR
    assert message.type == "error"
    assert message.code == "raw_uds_invalid_json"
    assert message.message == "Raw UDS JSON frame payload must be valid UTF-8 JSON"


def test_raw_uds_server_frame_parser_accepts_compact_error_payload() -> None:
    frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(
            RawUdsFrameType.ERROR,
            {"code": "raw_uds_malformed_json_control", "message": "bad control frame"},
        )
    )

    message = parse_raw_uds_server_frame(frame)

    assert message.type == "error"
    assert message.code == "raw_uds_malformed_json_control"
    assert message.message == "bad control frame"


def test_raw_uds_server_frame_parser_maps_event_error_and_empty_pong() -> None:
    ready_frame = decode_raw_uds_frame(encode_raw_uds_server_message(build_ready_message().model_dump()))
    error_payload = ErrorMessage(type="error", code="bad", message="bad request").model_dump()
    error_frame = decode_raw_uds_frame(encode_raw_uds_server_message(error_payload))
    empty_pong_frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.PONG, b""))
    closed_frame = decode_raw_uds_frame(
        encode_raw_uds_server_message({"type": "closed", "reason": "client_close", "metadata": {"turn_id": "t1"}})
    )

    ready = parse_raw_uds_server_frame(ready_frame)
    error = parse_raw_uds_server_frame(error_frame)
    pong = parse_raw_uds_server_frame(empty_pong_frame)
    closed = parse_raw_uds_server_frame(closed_frame)

    assert ready.type == "ready"
    assert error.type == "error"
    assert error.code == "bad"
    assert pong.type == "pong"
    assert pong.ping_id is None
    assert closed.type == "closed"
    assert closed.reason == "client_close"
    assert closed.metadata == {"turn_id": "t1"}


def test_raw_uds_server_frame_parser_rejects_client_frame_types() -> None:
    audio_frame = decode_raw_uds_frame(encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, b"\x00\x01"))

    with pytest.raises(LocalSttProtocolError) as excinfo:
        parse_raw_uds_server_frame(audio_frame)

    assert excinfo.value.as_event().code == "raw_uds_invalid_server_frame_type"
