"""Gesture detection from linear acceleration.

Port of the logic in firstiterationsubwaysurfers.ino. Samples arrive in the sensor
frame and are turned into the controller frame first (see `orient`): +X right, -X left,
+Z up, -Z down.

Every direction has its own threshold and delays, so a jump and a lane change can be
chained without waiting:
  - cooldown applies per direction (a second "up" waits, a "right" right after "up" does not)
  - the rest gate applies per axis (see GestureDetector), so "up" never blocks "left"/"right"
  - with queue_size > 0 a deliberate repeat (a fresh spike in the direction just fired) skips
    the rest gate, and if the cooldown blocks it, it is queued and fires when the cooldown ends

The numbers people tune live in tuning.toml at the repo root, not here.
"""

from collections import deque
from dataclasses import dataclass, field

# Left/right move along X, up/down along Z
AXIS = {"up": "z", "down": "z", "left": "x", "right": "x"}

# Sensor axis name -> (index into the accel tuple, sign)
SENSOR_AXES = {
    "+x": (0, 1.0),
    "-x": (0, -1.0),
    "+y": (1, 1.0),
    "-y": (1, -1.0),
    "+z": (2, 1.0),
    "-z": (2, -1.0),
}


def orient(
    accel: tuple[float, float, float], right_axis: str, up_axis: str
) -> tuple[float, float, float]:
    """Sensor frame -> controller frame (x right, y the leftover axis, z up)."""
    ri, rs = SENSOR_AXES[right_axis]
    ui, us = SENSOR_AXES[up_axis]
    return rs * accel[ri], accel[3 - ri - ui], us * accel[ui]


@dataclass(slots=True)
class DirectionConfig:
    threshold: float = 4.0  # m/s^2
    rest_s: float = 0.15  # stillness its axis needs before this direction can fire
    cooldown_s: float = 0.5  # minimum time between two gestures in this direction
    queue_size: int = 0  # repeats held back by the cooldown that wait their turn; 0 = drop them
    queue_s: float = 0.4  # longest a held repeat waits before it is discarded as stale


@dataclass(slots=True)
class GestureConfig:
    up: DirectionConfig = field(default_factory=lambda: DirectionConfig(threshold=7.0))
    down: DirectionConfig = field(default_factory=DirectionConfig)
    left: DirectionConfig = field(default_factory=DirectionConfig)
    right: DirectionConfig = field(default_factory=DirectionConfig)
    rest_threshold: float = 1.0  # an axis below this counts as at rest
    right_axis: str = "+x"  # sensor axis pointing to the player's right
    up_axis: str = "+z"  # sensor axis pointing up

    def __post_init__(self):
        for name, value in (("right", self.right_axis), ("up", self.up_axis)):
            if value not in SENSOR_AXES:
                raise ValueError(
                    f"orientation {name} = {value!r}: expected one of {', '.join(SENSOR_AXES)}"
                )
        if self.right_axis[1] == self.up_axis[1]:
            raise ValueError(
                f"orientation: right ({self.right_axis}) and up ({self.up_axis}) "
                "must be on different axes"
            )


class GestureDetector:
    def __init__(self, config: GestureConfig | None = None):
        self.config = config or GestureConfig()
        self.reset()

    def reset(self) -> None:
        self._last: dict[str, float] = {}
        # Longest stillness each axis has had since it last fired
        self._rested = {"x": float("inf"), "z": float("inf")}
        self._rest_start: dict[str, float | None] = {"x": None, "z": None}
        self._fired = {"x": None, "z": None}  # last direction fired on each axis
        self._prev: str | None = None  # direction detected on the previous sample
        self._pending: dict[str, deque[float]] = {k: deque() for k in AXIS}

    def update(
        self, accel: tuple[float, float, float], now: float, oriented: bool = False
    ) -> str | None:
        """Return "up", "down", "left", "right", or None. One gesture at most.

        `oriented` means accel is already (right, forward, up), as world.WorldFrame gives
        it, so the fixed sensor orientation is not applied.
        """
        cfg = self.config
        x, y, z = accel if oriented else orient(accel, cfg.right_axis, cfg.up_axis)
        ax, ay, az = abs(x), abs(y), abs(z)

        # An axis re-arms only after it has been still, so the opposite-direction spike
        # as a motion stops is not read as a second gesture. The other axis is unaffected.
        for axis, magnitude in (("x", ax), ("z", az)):
            if magnitude < cfg.rest_threshold:
                if self._rest_start[axis] is None:
                    self._rest_start[axis] = now
                self._rested[axis] = max(self._rested[axis], now - self._rest_start[axis])
            else:
                self._rest_start[axis] = None

        gesture = None
        if z > cfg.up.threshold and az > ax and az > ay:
            gesture = "up"
        elif z < -cfg.down.threshold and az > ax and az > ay:
            gesture = "down"
        elif x > cfg.right.threshold and ax > ay and ax > az:
            gesture = "right"
        elif x < -cfg.left.threshold and ax > ay and ax > az:
            gesture = "left"
        edge = gesture is not None and gesture != self._prev  # a new spike, not the same one
        self._prev = gesture

        released = self._release(now)
        if gesture is None:
            return released
        axis = AXIS[gesture]
        direction: DirectionConfig = getattr(cfg, gesture)
        # A fresh spike in the direction just fired is a deliberate repeat, not a rebound
        # (a rebound points the other way), so it need not wait for the axis to rest.
        repeat = direction.queue_size > 0 and edge and self._fired[axis] == gesture
        rest_ok = self._rested[axis] >= direction.rest_s or repeat
        cooled = now - self._last.get(gesture, float("-inf")) >= direction.cooldown_s
        if not rest_ok:
            return released
        if released is not None or not cooled:
            # Only one gesture per sample, so a fresh spike that lost to a released repeat
            # waits one sample, even in a direction whose own queue is off.
            if edge and (direction.queue_size > 0 or cooled):
                self._enqueue(gesture, direction, now)
            return released
        self._fire(gesture, now)
        return gesture

    def _fire(self, gesture: str, now: float) -> None:
        axis = AXIS[gesture]
        self._last[gesture] = now
        self._fired[axis] = gesture
        self._rested[axis] = 0.0
        self._rest_start[axis] = None

    def _enqueue(self, gesture: str, direction: DirectionConfig, now: float) -> None:
        pending = self._pending[gesture]
        if len(pending) < max(direction.queue_size, 1):
            pending.append(now)

    def _release(self, now: float) -> str | None:
        """Fire the oldest queued repeat whose cooldown has ended. Stale ones are dropped."""
        oldest: tuple[float, str] | None = None
        for gesture, pending in self._pending.items():
            direction: DirectionConfig = getattr(self.config, gesture)
            while pending and now - pending[0] > direction.queue_s:
                pending.popleft()
            if pending and now - self._last.get(gesture, float("-inf")) >= direction.cooldown_s:
                if oldest is None or pending[0] < oldest[0]:
                    oldest = (pending[0], gesture)
        if oldest is None:
            return None
        self._pending[oldest[1]].popleft()
        self._fire(oldest[1], now)
        return oldest[1]
