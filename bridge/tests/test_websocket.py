import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from wefit_bridge.config import Config, load_config
from wefit_bridge.events import KEYS, KeyEvent
from wefit_bridge.pipeline import build_pipeline, run
from wefit_bridge.sinks import make_sink
from wefit_bridge.sinks.websocket import WebSocketPortError, WebSocketSink
from wefit_bridge.transport.fake import FakeTransport


async def receive(ws, count, timeout=5.0):
    messages = []
    async with asyncio.timeout(timeout):
        while len(messages) < count:
            messages.append(json.loads(await ws.recv()))
    return messages


def test_sends_presses_as_game_moves_and_skips_releases():
    async def main():
        sink = WebSocketSink(port=0)
        await sink.start()
        try:
            async with connect(f"ws://127.0.0.1:{sink.port}") as ws:
                async with asyncio.timeout(2):
                    while not sink.clients:
                        await asyncio.sleep(0.01)
                for key in ("up", "down", "left", "right"):
                    sink.emit(KeyEvent(key, True, 1.0))
                    sink.emit(KeyEvent(key, False, 1.1))
                return await receive(ws, 4)
        finally:
            sink.close()

    messages = asyncio.run(main())
    assert [m["move"] for m in messages] == ["JUMP", "DUCK", "LEFT", "RIGHT"]
    assert messages[0] == {"move": "JUMP", "key": "up", "t": 1.0}


def test_emit_without_clients_is_a_no_op():
    async def main():
        sink = WebSocketSink(port=0)
        await sink.start()
        sink.emit(KeyEvent("up", True, 0.0))
        sink.close()

    asyncio.run(main())


def test_busy_port_raises_a_clear_error():
    async def main():
        first = WebSocketSink(port=0)
        await first.start()
        try:
            with pytest.raises(WebSocketPortError, match="--ws-port"):
                await WebSocketSink(port=first.port).start()
        finally:
            first.close()

    asyncio.run(main())


def test_config_and_factory(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('sinks = ["websocket"]\n[websocket]\nhost = "0.0.0.0"\nport = 9001\n')
    config = load_config(path)
    sink = make_sink("websocket", config)
    assert (sink.host, sink.port) == ("0.0.0.0", 9001)
    assert (make_sink("websocket").host, make_sink("websocket").port) == ("127.0.0.1", 8765)


def test_fake_controller_end_to_end_over_websocket():
    """Scripted controller -> gesture detection -> WebSocket -> a game client."""
    sink = WebSocketSink(port=0)
    pipeline = build_pipeline(Config(transport="fake"), sinks=[sink])
    for key in KEYS:
        direction = getattr(pipeline.detector.config, key)
        direction.cooldown_s = 0.2
        direction.rest_s = 0.1
    transport = FakeTransport(rate_hz=100, gesture_every_s=0.4, pulse_s=0.1)

    async def main():
        task = asyncio.create_task(run(transport, pipeline))
        async with asyncio.timeout(2):
            while sink._server is None:
                await asyncio.sleep(0.01)
        try:
            async with connect(f"ws://127.0.0.1:{sink.port}") as ws:
                return await receive(ws, 4)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    moves = [m["move"] for m in asyncio.run(main())]
    # FakeTransport plays up, right, down, left; the client may join mid-cycle
    cycle = ["JUMP", "RIGHT", "DUCK", "LEFT"]
    start = cycle.index(moves[0])
    assert moves == (cycle[start:] + cycle[:start])
    assert sink._server is None  # closed when the bridge stops
