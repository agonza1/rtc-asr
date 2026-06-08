from __future__ import annotations

import asyncio
import base64
import json
import importlib
import sys

import pytest

from src.rtc_client import AsyncASRClient


class FakeWebSocket:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = [json.dumps(response) for response in responses]
        self.sent: list[object] = []
        self.closed_with: int | None = None

    async def send(self, data: str | bytes) -> None:
        if isinstance(data, bytes):
            self.sent.append(data)
            return
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if not self.responses:
            raise RuntimeError('No fake websocket responses left')
        return self.responses.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


def test_importing_rtc_client_does_not_load_main_module() -> None:
    sys.modules.pop("src", None)
    sys.modules.pop("src.main", None)
    sys.modules.pop("src.rtc_client", None)

    rtc_client = importlib.import_module("src.rtc_client")

    assert rtc_client.AsyncASRClient is not None
    assert "src.main" not in sys.modules


def test_async_asr_client_stream_flow() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 2,
            'partial_window_seconds': 1.5,
            'max_buffer_seconds': 6.0,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
        {
            'type': 'final',
            'is_final': True,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hello',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        ready_event = await client.start(
            language='en',
            sample_rate=16000,
            partial_interval_chunks=2,
            partial_window_seconds=1.5,
            max_buffer_seconds=6.0,
        )
        first_event = await client.send_audio(b'hel')
        second_event = await client.send_audio(b'lo')
        final_event = await client.stop()
        await client.close()

        assert ready_event['type'] == 'ready'
        assert first_event is None
        assert second_event is not None
        assert second_event.text == 'hel'
        assert second_event.is_final is False
        assert final_event.text == 'hello'
        assert final_event.is_final is True
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 2,
                'partial_window_seconds': 1.5,
                'max_buffer_seconds': 6.0,
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'hel').decode('ascii'),
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'lo').decode('ascii'),
            },
            {'type': 'stop'},
        ]
        assert websocket.closed_with == 1000

    asyncio.run(scenario())


def test_async_asr_client_can_send_binary_audio_frames() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hel',
        },
        {
            'type': 'final',
            'is_final': True,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'text': 'hello',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start(send_binary_frames=True)
        partial_event = await client.send_audio(b'hel')
        final_event = await client.stop()
        await client.close()

        assert partial_event is not None
        assert partial_event.text == 'hel'
        assert final_event.text == 'hello'
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            b'hel',
            {'type': 'stop'},
        ]
        assert websocket.closed_with == 1000

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("param_name", "param_value"),
    [("partial_window_seconds", 0), ("max_buffer_seconds", -1), ("partial_window_seconds", True)],
)
def test_async_asr_client_rejects_invalid_optional_window_settings(param_name: str, param_value: object) -> None:
    async def scenario() -> None:
        client = AsyncASRClient("ws://example.test/ws/stream")
        with pytest.raises(ValueError, match=rf"{param_name} must be a positive number"):
            await client.start(**{param_name: param_value})

    asyncio.run(scenario())


def test_async_asr_client_tolerates_missing_partial_event() -> None:
    class SlowPartialWebSocket(FakeWebSocket):
        def __init__(self) -> None:
            super().__init__([
                {
                    'type': 'ready',
                    'backend': 'fake-whisper',
                    'model': 'fixture-adapter',
                    'language': 'en',
                    'sample_rate': 16000,
                    'partial_interval_chunks': 1,
                },
                {
                    'type': 'final',
                    'is_final': True,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hello',
                },
            ])
            self.recv_calls = 0

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return await super().recv()

    websocket = SlowPartialWebSocket()

    async def fake_connect(_: str) -> SlowPartialWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel', response_timeout=0.01)
        final_event = await client.stop()
        await client.close()

        assert partial_event is None
        assert final_event.text == 'hello'

    asyncio.run(scenario())


def test_async_asr_client_drains_stale_partial_before_final() -> None:
    class DelayedPartialWebSocket(FakeWebSocket):
        def __init__(self) -> None:
            super().__init__([
                {
                    'type': 'ready',
                    'backend': 'fake-whisper',
                    'model': 'fixture-adapter',
                    'language': 'en',
                    'sample_rate': 16000,
                    'partial_interval_chunks': 1,
                },
                {
                    'type': 'partial',
                    'is_final': False,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hel',
                },
                {
                    'type': 'final',
                    'is_final': True,
                    'chunks_received': 1,
                    'buffered_bytes': 3,
                    'text': 'hello',
                },
            ])
            self.recv_calls = 0

        async def recv(self) -> str:
            self.recv_calls += 1
            if self.recv_calls == 2:
                await asyncio.sleep(0.05)
            return await super().recv()

    websocket = DelayedPartialWebSocket()

    async def fake_connect(_: str) -> DelayedPartialWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel', response_timeout=0.01)
        final_event = await client.stop()
        await client.close()

        assert partial_event is None
        assert final_event.type == 'final'
        assert final_event.text == 'hello'

    asyncio.run(scenario())


def test_async_asr_client_can_cancel_stream() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'partial',
            'is_final': False,
            'stream_id': 7,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'remaining_buffer_bytes': 1021,
            'text': 'hel',
        },
        {
            'type': 'canceled',
            'stream_id': 7,
            'chunks_received': 1,
            'buffered_bytes': 3,
            'remaining_buffer_bytes': 1021,
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        partial_event = await client.send_audio(b'hel')
        canceled_event = await client.cancel()
        await client.close()

        assert partial_event is not None
        assert partial_event.stream_id == 7
        assert partial_event.remaining_buffer_bytes == 1021
        assert canceled_event.type == 'canceled'
        assert canceled_event.stream_id == 7
        assert canceled_event.remaining_buffer_bytes == 1021
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            {
                'type': 'audio',
                'audio_data': base64.b64encode(b'hel').decode('ascii'),
            },
            {'type': 'cancel'},
        ]

    asyncio.run(scenario())


def test_async_asr_client_cancel_returns_error_event() -> None:
    websocket = FakeWebSocket([
        {
            'type': 'ready',
            'backend': 'fake-whisper',
            'model': 'fixture-adapter',
            'language': 'en',
            'sample_rate': 16000,
            'partial_interval_chunks': 1,
        },
        {
            'type': 'error',
            'stream_id': 7,
            'message': 'Send a start event before canceling the stream',
        },
    ])

    async def fake_connect(_: str) -> FakeWebSocket:
        return websocket

    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream', connect_fn=fake_connect)
        await client.start()
        error_event = await client.cancel()
        await client.close()

        assert error_event.type == 'error'
        assert error_event.stream_id == 7
        assert error_event.text == 'Send a start event before canceling the stream'
        assert websocket.sent == [
            {
                'type': 'start',
                'language': 'en',
                'sample_rate': 16000,
                'partial_interval_chunks': 1,
            },
            {'type': 'cancel'},
        ]

    asyncio.run(scenario())


def test_async_asr_client_rejects_invalid_start_arguments() -> None:
    async def scenario() -> None:
        client = AsyncASRClient('ws://example.test/ws/stream')

        with pytest.raises(ValueError, match='sample_rate must be a positive integer'):
            await client.start(sample_rate=0)

        with pytest.raises(ValueError, match='partial_interval_chunks must be a positive integer'):
            await client.start(partial_interval_chunks=0)

    asyncio.run(scenario())
