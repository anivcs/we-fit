"""Where key events go. The only code that knows about the game side."""

from typing import TYPE_CHECKING, Protocol

from ..events import KeyEvent

if TYPE_CHECKING:
    from ..config import Config

SINKS = ("console", "keyboard", "websocket")


class Sink(Protocol):
    # A sink may also define `async def start(self)`; run() awaits it before the first sample.
    def emit(self, event: KeyEvent) -> None: ...

    def close(self) -> None: ...


def make_sink(name: str, config: "Config | None" = None) -> Sink:
    if name == "console":
        from .console import ConsoleSink

        return ConsoleSink()
    if name == "keyboard":
        from .keyboard import KeyboardSink

        return KeyboardSink()
    if name == "websocket":
        from .websocket import WebSocketSink

        if config is None:
            return WebSocketSink()
        return WebSocketSink(host=config.websocket_host, port=config.websocket_port)
    raise ValueError(f"unknown sink: {name!r} (expected one of {SINKS})")
