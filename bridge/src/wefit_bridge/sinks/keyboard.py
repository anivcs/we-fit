"""Presses real OS arrow keys, so any game that reads the keyboard works unchanged.

Needs the optional dependency: pip install -e "bridge[keyboard]"
"""

from ..events import KeyEvent


class KeyboardSink:
    def __init__(self):
        from pynput.keyboard import Controller, Key

        self._keyboard = Controller()
        self._keys = {"up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right}
        self._down: set[str] = set()

    def emit(self, event: KeyEvent) -> None:
        key = self._keys[event.key]
        if event.pressed:
            self._keyboard.press(key)
            self._down.add(event.key)
        else:
            self._keyboard.release(key)
            self._down.discard(event.key)

    def close(self) -> None:
        for name in list(self._down):
            self._keyboard.release(self._keys[name])
        self._down.clear()
