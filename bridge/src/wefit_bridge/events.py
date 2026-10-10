"""Game-facing output model: four boolean arrow keys."""

import json
from dataclasses import dataclass

KEYS = ("up", "down", "left", "right")


@dataclass(frozen=True, slots=True)
class KeyEvent:
    key: str
    pressed: bool
    t: float

    def to_json(self) -> str:
        return json.dumps({"type": "key", "key": self.key, "pressed": self.pressed, "t": self.t})
