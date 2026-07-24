from __future__ import annotations

import pytest

from pipecat_local_stt import LocalSTTConfig, RtcAsrSTTService
from pipecat_local_stt.protocol import (
    LocalSTTProtocolError,
    RAW_UDS_CLIENT_FRAME_TYPES,
    RAW_UDS_FRAME_DIRECTION,
    RAW_UDS_MAX_PAYLOAD_BYTES,
    RAW_UDS_SERVER_FRAME_TYPES,
    RawUdsFrame,
    RawUdsFrameDecoder,
    RawUdsFrameType,
    build_start_message,
    decode_raw_uds_frame,
    decode_raw_uds_json_payload,
    encode_raw_uds_frame,
    encode_raw_uds_json_frame,
    parse_raw_uds_server_frame,
    parse_transcript_event,
)


def test_build_start_message_uses_required_flat_local_stt_v1_shape() -> None:
    config = LocalSTTConfig(language="en", partial_interval_ms=100)

    payload = build_start_message(config, client_stream_id="turn-1", metadata={"k": "v"})

    assert payload == {
        "type": "start",
        "protocol": "local-stt-v1",
        "language": "en",
        "sample_rate": 16000,
        "channels": 1,
        "format": "pcm_s16le",
        "frame_ms": 20,
        "interim_results": True,
        "partial_interval_ms": 100,
        "partial_window_seconds": 1.0,
        "max_buffer_seconds": 10.0,
        "client_stream_id": "turn-1",
        "metadata": {"k": "v"},
    }


def test_parse_transcript_event_rejects_invalid_timing() -> None:
    with pytest.raises(ValueError, match="audio_transcribed_ms"):
        parse_transcript_event({
            "type": "transcript",
            "text": "hello",
            "is_final": False,
            "speech_final": False,
            "revision": 1,
            "audio_received_ms": 20,
            "audio_transcribed_ms": 40,
            "metadata": {},
        })


@pytest.mark.parametrize("field", ["is_final", "speech_final"])
def test_parse_transcript_event_rejects_non_boolean_final_flags(field: str) -> None:
    payload = {
        "type": "transcript",
        "text": "hello",
        "is_final": False,
        "speech_final": False,
        "revision": 1,
        "audio_received_ms": 40,
        "audio_transcribed_ms": 20,
        "metadata": {},
    }
    payload[field] = "false"

    with pytest.raises(LocalSTTProtocolError, match=f"{field} must be a boolean"):
        parse_transcript_event(payload)


@pytest.mark.parametrize("field", ["revision", "audio_received_ms", "audio_transcribed_ms"])
def test_parse_transcript_event_rejects_boolean_integer_fields(field: str) -> None:
    payload = {
        "type": "transcript",
        "text": "hello",
        "is_final": False,
        "speech_final": False,
        "revision": 1,
        "audio_received_ms": 40,
        "audio_transcribed_ms": 20,
        "metadata": {},
    }
    payload[field] = True

    with pytest.raises(LocalSTTProtocolError, match=f"{field} must be an integer, not a boolean"):
        parse_transcript_event(payload)


def test_rtc_asr_wrapper_exports_default_service_config() -> None:
    service = RtcAsrSTTService(url="ws://localhost:8080/v1/stt/stream", language="es")

    assert service.config.url == "ws://localhost:8080/v1/stt/stream"
    assert service.config.language == "es"


def test_rtc_asr_wrapper_accepts_stream_tuning_overrides() -> None:
    service = RtcAsrSTTService(
        url="ws://localhost:8080/v1/stt/stream",
        sample_rate=16000,
        channels=1,
        frame_ms=40,
        partial_interval_ms=250,
        partial_window_seconds=1.5,
    )

    assert service.config.sample_rate == 16000
    assert service.config.channels == 1
    assert service.config.frame_ms == 40
    assert service.config.partial_interval_ms == 250
    assert service.config.partial_window_seconds == 1.5


def test_rtc_asr_wrapper_accepts_optional_uds_transport() -> None:
    service = RtcAsrSTTService(
        transport="uds_ws",
        url="ws://localhost/v1/stt/stream",
        uds_path="/run/rtc-asr/stt.sock",
    )

    assert service.config.transport == "uds_ws"
    assert service.config.url == "ws://localhost/v1/stt/stream"
    assert service.config.uds_path == "/run/rtc-asr/stt.sock"


def test_rtc_asr_wrapper_accepts_optional_raw_uds_transport() -> None:
    service = RtcAsrSTTService(
        transport="raw_uds",
        url="ws://localhost/v1/stt/stream",
        uds_path="/run/rtc-asr/stt.raw.sock",
    )

    assert service.config.transport == "raw_uds"
    assert service.config.url == "ws://localhost/v1/stt/stream"
    assert service.config.uds_path == "/run/rtc-asr/stt.raw.sock"


def test_package_exports_raw_uds_codec_contract() -> None:
    import pipecat_local_stt as package

    encoded = package.encode_raw_uds_json_frame(package.RawUdsFrameType.JSON_CONTROL, {"type": "close"})
    decoded = package.decode_raw_uds_frame(encoded)
    decoder = package.RawUdsFrameDecoder()

    assert package.RAW_UDS_HEADER_BYTES == 5
    assert package.RAW_UDS_MAX_PAYLOAD_BYTES >= 8 * 1024 * 1024
    assert decoded.frame_type == package.RawUdsFrameType.JSON_CONTROL
    assert decoded.payload == b'{"type":"close"}'
    assert decoder.feed(encoded)[0] == decoded


def test_package_exports_raw_uds_json_decoder_and_server_parser() -> None:
    import pipecat_local_stt as package

    encoded = package.encode_raw_uds_json_frame(package.RawUdsFrameType.JSON_EVENT, {"type": "ready"})
    decoded = package.decode_raw_uds_frame(encoded)

    assert package.decode_raw_uds_json_payload(decoded) == {"type": "ready"}
    assert package.parse_raw_uds_server_frame(decoded) == {"type": "ready"}


@pytest.mark.parametrize("frame_type", [RawUdsFrameType.PING, RawUdsFrameType.PONG])
def test_raw_uds_server_parser_accepts_empty_keepalive_frames(frame_type: RawUdsFrameType) -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_frame(frame_type, b""))

    assert parse_raw_uds_server_frame(frame) == {"type": frame_type.name.lower()}


def test_raw_uds_server_parser_rejects_mismatched_keepalive_payload_type() -> None:
    frame = decode_raw_uds_frame(encode_raw_uds_json_frame(RawUdsFrameType.PING, {"type": "transcript"}))

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        parse_raw_uds_server_frame(frame)

    assert excinfo.value.code == "raw_uds_heartbeat_type_mismatch"


def test_raw_uds_server_parser_defaults_error_event_type() -> None:
    frame = decode_raw_uds_frame(
        encode_raw_uds_json_frame(RawUdsFrameType.ERROR, {"code": "raw_uds_payload_too_large"})
    )

    assert parse_raw_uds_server_frame(frame) == {
        "type": "error",
        "code": "raw_uds_payload_too_large",
    }


def test_package_exports_raw_uds_direction_catalog() -> None:
    import pipecat_local_stt as package

    assert RAW_UDS_FRAME_DIRECTION == {
        "client_to_server": ["JSON_CONTROL", "AUDIO_PCM16", "PING", "PONG"],
        "server_to_client": ["JSON_EVENT", "ERROR", "PING", "PONG"],
    }
    assert RawUdsFrameType.JSON_EVENT not in RAW_UDS_CLIENT_FRAME_TYPES
    assert RawUdsFrameType.JSON_CONTROL not in RAW_UDS_SERVER_FRAME_TYPES
    assert package.RAW_UDS_FRAME_DIRECTION == RAW_UDS_FRAME_DIRECTION
    assert package.RAW_UDS_CLIENT_FRAME_TYPES == RAW_UDS_CLIENT_FRAME_TYPES
    assert package.RAW_UDS_SERVER_FRAME_TYPES == RAW_UDS_SERVER_FRAME_TYPES


def test_raw_uds_json_payload_decoder_accepts_outbound_control_frames() -> None:
    encoded = encode_raw_uds_json_frame(RawUdsFrameType.JSON_CONTROL, {"type": "close"})
    frame = decode_raw_uds_frame(encoded)

    assert decode_raw_uds_json_payload(frame) == {"type": "close"}


def test_raw_uds_json_frame_codec_rejects_audio_frame_type() -> None:
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        encode_raw_uds_json_frame(RawUdsFrameType.AUDIO_PCM16, {"type": "close"})

    assert excinfo.value.code == "raw_uds_invalid_json_frame_type"


@pytest.mark.parametrize("payload", [["not-object"], "not-object", None])
def test_raw_uds_json_frame_codec_rejects_non_object_payloads(payload: object) -> None:
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        encode_raw_uds_json_frame(RawUdsFrameType.JSON_CONTROL, payload)

    assert excinfo.value.code == "raw_uds_invalid_json"
    assert excinfo.value.message == "Raw UDS JSON payload must be an object"


@pytest.mark.parametrize("payload", [b"{", b'["not-object"]', b"\xff"])
def test_raw_uds_json_payload_errors_are_protocol_errors(payload: bytes) -> None:
    frame = RawUdsFrame(frame_type=RawUdsFrameType.JSON_EVENT, payload=payload)

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decode_raw_uds_json_payload(frame)

    assert excinfo.value.code == "raw_uds_invalid_json"


def test_raw_uds_frame_decoder_buffers_socket_chunk_boundaries() -> None:
    decoder = RawUdsFrameDecoder()
    ready = encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"})
    pong = encode_raw_uds_frame(RawUdsFrameType.PONG, b"")

    assert decoder.feed(ready[:3]) == []
    assert decoder.buffered_bytes == 3
    frames = decoder.feed(ready[3:] + pong)

    assert frames == [
        decode_raw_uds_frame(ready),
        decode_raw_uds_frame(pong),
    ]
    assert decoder.buffered_bytes == 0


def test_raw_uds_frame_decoder_clears_error_state() -> None:
    decoder = RawUdsFrameDecoder()
    oversized = bytes([RawUdsFrameType.JSON_EVENT]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little")
    ready = encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"})

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decoder.feed(oversized)

    assert excinfo.value.code == "raw_uds_payload_too_large"
    assert decoder.buffered_bytes == 0
    assert decoder.feed(ready) == [decode_raw_uds_frame(ready)]


def test_raw_uds_frame_decoder_clears_unknown_type_error_state() -> None:
    decoder = RawUdsFrameDecoder()
    unknown = bytes([0x99]) + (0).to_bytes(4, "little")
    ready = encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"})

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decoder.feed(unknown)

    assert excinfo.value.code == "raw_uds_unsupported_frame_type"
    assert decoder.buffered_bytes == 0
    assert decoder.feed(ready) == [decode_raw_uds_frame(ready)]


def test_raw_uds_frame_codec_reports_stable_error_codes() -> None:
    oversized = bytes([RawUdsFrameType.JSON_EVENT]) + (RAW_UDS_MAX_PAYLOAD_BYTES + 1).to_bytes(4, "little")
    short_header = bytes([RawUdsFrameType.JSON_EVENT])
    truncated = bytes([RawUdsFrameType.JSON_EVENT]) + (4).to_bytes(4, "little") + b"ok"

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decode_raw_uds_frame(oversized)
    assert excinfo.value.code == "raw_uds_payload_too_large"

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decode_raw_uds_frame(short_header)
    assert excinfo.value.code == "raw_uds_incomplete_frame"

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decode_raw_uds_frame(truncated)
    assert excinfo.value.code == "raw_uds_frame_length_mismatch"


def test_raw_uds_frame_codec_rejects_boolean_frame_type() -> None:
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        encode_raw_uds_frame(True, b"{}")

    assert excinfo.value.code == "raw_uds_unsupported_frame_type"
    assert "Unsupported Raw UDS frame type: True" in excinfo.value.message

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        encode_raw_uds_json_frame(True, {"type": "ping"})

    assert excinfo.value.code == "raw_uds_unsupported_frame_type"
    assert "Unsupported Raw UDS frame type: True" in excinfo.value.message


@pytest.mark.parametrize("payload", [2, "not-bytes"])
def test_raw_uds_frame_codec_rejects_non_bytes_like_payloads(payload: object) -> None:
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        encode_raw_uds_frame(RawUdsFrameType.AUDIO_PCM16, payload)

    assert excinfo.value.code == "raw_uds_invalid_bytes"
    assert "Raw UDS frame payload must be bytes-like" in excinfo.value.message


@pytest.mark.parametrize("frame_bytes", [2, "not-bytes"])
def test_raw_uds_frame_decoder_rejects_non_bytes_like_frames(frame_bytes: object) -> None:
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decode_raw_uds_frame(frame_bytes)

    assert excinfo.value.code == "raw_uds_invalid_bytes"
    assert "Raw UDS frame must be bytes-like" in excinfo.value.message


def test_raw_uds_frame_decoder_finish_rejects_partial_tail() -> None:
    decoder = RawUdsFrameDecoder()
    ready = encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"})

    assert decoder.feed(ready[:-1]) == []
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decoder.finish()

    assert excinfo.value.code == "raw_uds_incomplete_frame"
    assert decoder.buffered_bytes == 0


@pytest.mark.parametrize("chunk", [2, "not-bytes"])
def test_raw_uds_frame_decoder_feed_rejects_non_bytes_like_socket_chunks(chunk: object) -> None:
    decoder = RawUdsFrameDecoder()

    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decoder.feed(chunk)

    assert excinfo.value.code == "raw_uds_invalid_bytes"
    assert "Raw UDS socket chunks must be bytes-like" in excinfo.value.message
    assert decoder.buffered_bytes == 0


@pytest.mark.parametrize("chunk", [2, "not-bytes"])
def test_raw_uds_frame_decoder_clears_partial_buffer_after_non_bytes_like_socket_chunk(chunk: object) -> None:
    decoder = RawUdsFrameDecoder()
    ready = encode_raw_uds_json_frame(RawUdsFrameType.JSON_EVENT, {"type": "ready"})
    pong = encode_raw_uds_frame(RawUdsFrameType.PONG, b"")

    assert decoder.feed(ready[:2]) == []
    assert decoder.buffered_bytes == 2
    with pytest.raises(LocalSTTProtocolError) as excinfo:
        decoder.feed(chunk)

    assert excinfo.value.code == "raw_uds_invalid_bytes"
    assert decoder.buffered_bytes == 0
    assert decoder.feed(pong) == [decode_raw_uds_frame(pong)]
