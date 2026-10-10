"""Prints one JSON object per key event."""

from ..events import KeyEvent


class ConsoleSink:
    def emit(self, event: KeyEvent) -> None:
        print(event.to_json(), flush=True)

    def close(self) -> None:
        pass
