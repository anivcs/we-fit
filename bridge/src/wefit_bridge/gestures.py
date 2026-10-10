"""Gesture detection from linear acceleration.

Port of the logic in firstiterationsubwaysurfers.ino. Axes are the sensor frame:
+X right, -X left, +Z up, -Z down.
"""

from dataclasses import dataclass


@dataclass(slots=True)
class GestureConfig:
    side_threshold: float = 4.0  # m/s^2
    up_threshold: float = 7.0
    down_threshold: float = 4.0
    rest_threshold: float = 1.0  # all axes below this counts as at rest
    rest_s: float = 0.15  # stillness required before the next gesture
    cooldown_s: float = 0.5


class GestureDetector:
    def __init__(self, config: GestureConfig | None = None):
        self.config = config or GestureConfig()
        self.reset()

    def reset(self) -> None:
        self._last = float("-inf")
        self._ready = True
        self._rest_start: float | None = None

    def update(self, accel: tuple[float, float, float], now: float) -> str | None:
        """Return "up", "down", "left", "right", or None. One gesture at most."""
        cfg = self.config
        x, y, z = accel
        ax, ay, az = abs(x), abs(y), abs(z)

        # Re-arm only after the sensor has been still, so the opposite-direction
        # spike at the end of a motion is not read as a second gesture
        if ax < cfg.rest_threshold and ay < cfg.rest_threshold and az < cfg.rest_threshold:
            if self._rest_start is None:
                self._rest_start = now
            if now - self._rest_start >= cfg.rest_s:
                self._ready = True
        else:
            self._rest_start = None

        if not self._ready or now - self._last < cfg.cooldown_s:
            return None

        gesture = None
        if z > cfg.up_threshold and az > ax and az > ay:
            gesture = "up"
        elif z < -cfg.down_threshold and az > ax and az > ay:
            gesture = "down"
        elif x > cfg.side_threshold and ax > ay and ax > az:
            gesture = "right"
        elif x < -cfg.side_threshold and ax > ay and ax > az:
            gesture = "left"

        if gesture is not None:
            self._last = now
            self._ready = False
        return gesture
