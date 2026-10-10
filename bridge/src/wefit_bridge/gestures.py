"""Gesture detection from linear acceleration.

Port of the logic in firstiterationsubwaysurfers.ino. Axes are the sensor frame:
+X right, -X left, +Z up, -Z down.

The delays are independent per direction, so a jump and a lane change can be chained
without waiting:
  - cooldown applies per direction (a second "up" waits, a "right" right after "up" does not)
  - the rest gate applies per axis (see GestureDetector), so "up" never blocks "left"/"right"
"""

from dataclasses import dataclass

# Left/right move along X, up/down along Z
AXIS = {"up": "z", "down": "z", "left": "x", "right": "x"}


@dataclass(slots=True)
class GestureConfig:
    side_threshold: float = 4.0  # m/s^2
    up_threshold: float = 7.0
    down_threshold: float = 4.0
    rest_threshold: float = 1.0  # an axis below this counts as at rest
    rest_s: float = 0.15  # stillness an axis needs before it can fire again
    cooldown_s: float = 0.5  # minimum time between two gestures in the same direction


class GestureDetector:
    def __init__(self, config: GestureConfig | None = None):
        self.config = config or GestureConfig()
        self.reset()

    def reset(self) -> None:
        self._last: dict[str, float] = {}
        self._ready = {"x": True, "z": True}
        self._rest_start: dict[str, float | None] = {"x": None, "z": None}

    def update(self, accel: tuple[float, float, float], now: float) -> str | None:
        """Return "up", "down", "left", "right", or None. One gesture at most."""
        cfg = self.config
        x, y, z = accel
        ax, ay, az = abs(x), abs(y), abs(z)

        # An axis re-arms only after it has been still, so the opposite-direction spike
        # as a motion stops is not read as a second gesture. The other axis is unaffected.
        for axis, magnitude in (("x", ax), ("z", az)):
            if magnitude < cfg.rest_threshold:
                if self._rest_start[axis] is None:
                    self._rest_start[axis] = now
                if now - self._rest_start[axis] >= cfg.rest_s:
                    self._ready[axis] = True
            else:
                self._rest_start[axis] = None

        gesture = None
        if z > cfg.up_threshold and az > ax and az > ay:
            gesture = "up"
        elif z < -cfg.down_threshold and az > ax and az > ay:
            gesture = "down"
        elif x > cfg.side_threshold and ax > ay and ax > az:
            gesture = "right"
        elif x < -cfg.side_threshold and ax > ay and ax > az:
            gesture = "left"

        if gesture is None:
            return None
        axis = AXIS[gesture]
        if not self._ready[axis] or now - self._last.get(gesture, float("-inf")) < cfg.cooldown_s:
            return None

        self._last[gesture] = now
        self._ready[axis] = False
        return gesture
