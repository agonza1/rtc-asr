from __future__ import annotations

import asyncio
import base64
import json

from src.rtc_client import AsyncASRClient


class FakeWebSocket:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = [json.dumps(response) for response in responses]
        self.sent: list[dict[str, object]] = []
        self.closed_with: int | None = None

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    async def recv(self) -> str:
        if not self.responses:
            raise RuntimeError('No fake websocket responses left')
        return self.responses.pop(0)

    async def close(self, code: int = 1000) -> None:
        self.closed_with = code


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
