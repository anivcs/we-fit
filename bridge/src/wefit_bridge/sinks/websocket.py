"""Serves gestures to the browser game over WebSocket.

The game connects with ?controller=ws://localhost:8765 and receives one JSON message per
gesture, e.g. {"move": "JUMP", "key": "up", "t": 15180.5}.
"""

import json
import logging

from websockets.asyncio.server import Server, ServerConnection, broadcast, serve

from ..events import KeyEvent

log = logging.getLogger(__name__)

# Must match the game's MOVES (frontend/src/moves.js)
MOVES = {"up": "JUMP", "down": "DUCK", "left": "LEFT", "right": "RIGHT"}

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class WebSocketPortError(RuntimeError):
    pass


class WebSocketSink:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.clients: set[ServerConnection] = set()
        self._server: Server | None = None
        # Called when the game page closes its connection; run() points this at the latency summary
        self.on_game_exit = None

    async def start(self) -> None:
        try:
            self._server = await serve(self._handle, self.host, self.port)
        except OSError as e:
            raise WebSocketPortError(
                f"Could not open the game WebSocket on {self.host}:{self.port} ({e}). "
                "Stop whatever is using that port, or pick another with --ws-port."
            ) from e
        # Port 0 asks the OS for a free port; report the real one
        self.port = self._server.sockets[0].getsockname()[1]
        log.info("game WebSocket listening on ws://%s:%d", self.host, self.port)

    async def _handle(self, connection: ServerConnection) -> None:
        self.clients.add(connection)
        log.info("game connected from %s:%d", *connection.remote_address[:2])
        try:
            # The game never sends anything we act on; just keep the connection open
            async for _ in connection:
                pass
        finally:
            self.clients.discard(connection)
            log.info("game disconnected")
            if self.on_game_exit is not None:
                self.on_game_exit()

    def emit(self, event: KeyEvent) -> None:
        # The game treats each move as a one-shot action, so key releases are not sent
        if not event.pressed:
            return
        message = json.dumps({"move": MOVES[event.key], "key": event.key, "t": event.t})
        broadcast(self.clients, message)

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
