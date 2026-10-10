"""Where key events go. The only code that knows about the game side."""

from typing import Protocol

from ..events import KeyEvent


class Sink(Protocol):
    def emit(self, event: KeyEvent) -> None: ...

    def close(self) -> None: ...


def make_sink(name: str) -> Sink:
    if name == "console":
        from .console import ConsoleSink

        return ConsoleSink()
    if name == "keyboard":
        from .keyboard import KeyboardSink

        return KeyboardSink()
    raise ValueError(f"unknown sink: {name!r} (expected 'console' or 'keyboard')")
