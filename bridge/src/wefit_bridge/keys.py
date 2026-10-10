"""Arrow-key state machine: at most one key down, released automatically."""

from .events import KEYS, KeyEvent


class KeyState:
    def __init__(self, hold_s: float = 0.12):
        self._hold_s = hold_s
        self._active: str | None = None
        self._release_at = 0.0

    @property
    def active(self) -> str | None:
        return self._active

    def snapshot(self) -> dict[str, bool]:
        return {key: key == self._active for key in KEYS}

    def press(self, key: str, now: float) -> list[KeyEvent]:
        if key not in KEYS:
            raise ValueError(f"unknown key: {key!r}")
        # Release-before-press keeps the one-key-at-a-time guarantee
        events = self.release(now)
        self._active = key
        self._release_at = now + self._hold_s
        events.append(KeyEvent(key, True, now))
        return events

    def tick(self, now: float) -> list[KeyEvent]:
        if self._active is not None and now >= self._release_at:
            return self.release(now)
        return []

    def release(self, now: float) -> list[KeyEvent]:
        if self._active is None:
            return []
        event = KeyEvent(self._active, False, now)
        self._active = None
        return [event]
