"""Startup health checks and the world-reference gesture.

StartupGuide is a state machine fed one sample at a time. It does no I/O: it returns
StartupEvent objects, and whoever owns the screen shows them. The terminal consumer is
`log_event`; a game can pass its own callable (see Controller(on_startup=...)).

Which steps run:
  mode         always
  calibration  always; waits and prompts only in NDOF mode
  field        NDOF mode only (IMU mode switches the magnetometer off)
  reference    --gravity only

In plain IMU mode nothing here delays gestures; that is today's behaviour.
"""

import logging
import statistics
from dataclasses import dataclass, field

from .protocol import MODES, Sample, Status
from .world import GravityConfig, WorldFrame, magnitude, quat_valid, rotate

log = logging.getLogger(__name__)

MODE_TIMEOUT_S = 3.0  # the firmware reports its mode five times a second
CALIBRATION_TIMEOUT_S = 20.0
FIELD_WINDOW_S = 2.0
STILL_S = 1.0  # stillness needed before the reference gesture
STILL_TIMEOUT_S = 10.0
SETTLE_S = 0.5  # stillness after the reference gesture, so its tail fires nothing
HORIZONTAL_SHARE = 0.7  # the reference movement must be at least this horizontal
FULLY_CALIBRATED = 3
MAG_CALIBRATED = 2

REFLASH = "Re-flash the firmware: pio run -d firmware -t upload"


class StartupFailed(RuntimeError):
    """A startup step failed in a way the bridge cannot continue from."""

    def __init__(self, step: str, reason: str):
        super().__init__(reason)
        self.step = step
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StartupEvent:
    step: str  # "mode" | "calibration" | "field" | "reference"
    status: str  # "prompt" | "ok" | "warn" | "fail"
    message: str  # one sentence, ready to show the player
    data: dict = field(default_factory=dict)  # the numbers behind it, for a UI

    def to_dict(self) -> dict:
        return {"step": self.step, "status": self.status, "message": self.message, **self.data}


def log_event(event: StartupEvent) -> None:
    """The terminal consumer: prompts stand out, results are one line each."""
    if event.status == "prompt":
        log.info(">>> %s", event.message)
    elif event.status == "ok":
        log.info("%s", event.message)
    else:
        log.warning("%s", event.message)


def calibration_levels(calib: int) -> dict[str, int]:
    """The BNO055 calibration byte as four levels, 0 (none) to 3 (full)."""
    return {
        "sys": calib >> 6 & 3,
        "gyro": calib >> 4 & 3,
        "accel": calib >> 2 & 3,
        "mag": calib & 3,
    }


class StartupGuide:
    def __init__(
        self,
        mode: str = "imu",
        gravity: bool = False,
        right_threshold: float = 4.0,
        config: GravityConfig | None = None,
    ):
        self.mode = mode
        self.gravity = gravity
        self.right_threshold = right_threshold
        self.config = config or GravityConfig()
        # Gestures are held back until the checks finish, except in plain IMU mode
        self.blocking = mode == "ndof" or gravity
        self.done = False
        self.failed: StartupEvent | None = None
        self.frame: WorldFrame | None = None
        self.results: dict[str, dict] = {}

        self._steps = ["mode", "calibration"]
        if mode == "ndof":
            self._steps.append("field")
        if gravity:
            self._steps.append("reference")
        self._step_start: float | None = None
        self._prompted: set[str] = set()
        self._fields: list[float] = []
        self._last_status: Status | None = None
        self._still_since: float | None = None
        self._phase = "still"  # reference: still -> move -> settle
        self._peak: tuple[float, float, float] | None = None  # horizontal size, x, y
        self._rejected = False

    def on_sample(self, sample: Sample, status: Status | None, now: float) -> list[StartupEvent]:
        """Advance with one sample and the latest status packet. Returns what to show."""
        events: list[StartupEvent] = []
        while not self.done:
            if self._step_start is None:
                self._step_start = now
            step = self._steps[0]
            finished = getattr(self, f"_{step}")(sample, status, now, events)
            if not finished:
                break
            self._steps.pop(0)
            self._step_start = None
            self.done = not self._steps
        for event in events:
            if event.status != "prompt":
                self.results[event.step] = event.to_dict()
        return events

    # Each step returns True once it has finished and emitted its result.

    def _mode(self, sample, status, now, events) -> bool:
        if status is not None and status.mode == MODES[self.mode]:
            events.append(
                StartupEvent("mode", "ok", f"fusion mode: {self.mode.upper()}", {"mode": self.mode})
            )
            return True
        if now - self._step_start < MODE_TIMEOUT_S:
            return False
        if self.mode == "imu":
            # Older firmware has no status packet and only runs IMU mode, which is what we want
            events.append(
                StartupEvent(
                    "mode",
                    "warn",
                    "fusion mode: IMU (assumed; this firmware does not report its mode. "
                    f"{REFLASH})",
                    {"mode": "imu"},
                )
            )
            return True
        self._fail(
            events,
            "mode",
            f"fusion mode: the controller did not switch to {self.mode.upper()}. {REFLASH}",
        )
        return True

    def _calibration(self, sample, status, now, events) -> bool:
        levels = calibration_levels(sample.calib)
        ready = True
        if self.mode == "ndof":
            ready = levels["gyro"] == FULLY_CALIBRATED and levels["mag"] >= MAG_CALIBRATED
            if not ready and now - self._step_start < CALIBRATION_TIMEOUT_S:
                if levels["gyro"] < FULLY_CALIBRATED:
                    self._prompt(events, "calibration", "Hold the controller still.")
                else:
                    self._prompt(events, "calibration", "Draw a figure 8 in the air.")
                return False
        text = " ".join(f"{name} {level}" for name, level in levels.items())
        events.append(
            StartupEvent(
                "calibration",
                "ok" if ready else "warn",
                f"calibration: {text}" + ("" if ready else "  (not fully calibrated; continuing)"),
                {**levels, "wait_s": round(now - self._step_start, 1)},
            )
        )
        return True

    def _field(self, sample, status, now, events) -> bool:
        if status is not None and status is not self._last_status:
            self._last_status = status
            self._fields.append(status.field_ut)
        if now - self._step_start < FIELD_WINDOW_S:
            return False
        if not self._fields:
            events.append(
                StartupEvent("field", "warn", "magnetic field: no reading from the controller")
            )
            return True
        median = statistics.median(self._fields)
        spread = (max(self._fields) - min(self._fields)) / 2
        cfg = self.config
        ok = cfg.mag_min_ut <= median <= cfg.mag_max_ut
        message = f"magnetic field: {median:.0f} uT (+/- {spread:.0f})"
        if median > cfg.mag_max_ut:
            message += "  too strong: move magnets, speakers or the battery bank away"
        elif median < cfg.mag_min_ut:
            message += "  too weak: the magnetometer may be shielded or not calibrated"
        events.append(
            StartupEvent(
                "field",
                "ok" if ok else "warn",
                message,
                {"median_ut": round(median, 1), "spread_ut": round(spread, 1)},
            )
        )
        return True

    def _reference(self, sample, status, now, events) -> bool:
        cfg = self.config
        valid = quat_valid(sample.quat)
        still = valid and magnitude(sample.accel) < cfg.still_ms2
        if not still:
            self._still_since = None
        elif self._still_since is None:
            self._still_since = now
        still_for = 0.0 if self._still_since is None else now - self._still_since

        if self._phase == "still":
            self._prompt(events, "reference", "Hold still.")
            if still_for >= STILL_S:
                self._phase = "move"
                self._step_start = now
                self._prompt(events, "reference:move", "Shuffle RIGHT once, quickly.")
            elif now - self._step_start >= STILL_TIMEOUT_S:
                reason = (
                    "the controller never stayed still"
                    if valid
                    else "the sensor is not reporting a valid orientation"
                )
                self._fail_reference(events, reason)
                return True
            return False

        if self._phase == "move":
            wx, wy, wz = rotate(sample.quat, sample.accel) if valid else (0.0, 0.0, 0.0)
            horizontal = (wx * wx + wy * wy) ** 0.5
            total = magnitude((wx, wy, wz))
            if horizontal >= self.right_threshold and horizontal >= HORIZONTAL_SHARE * total:
                if self._peak is None or horizontal > self._peak[0]:
                    self._peak = (horizontal, wx, wy)
                return False
            if self._peak is not None:
                # The push is over; its strongest sample points to the player's right
                self.frame = WorldFrame.from_horizontal(self._peak[1], self._peak[2])
                self._phase = "settle"
                self._still_since = None
                return False
            if total >= self.right_threshold:
                self._rejected = True  # a strong movement, but mostly a jump or a squat
            if now - self._step_start >= cfg.reference_timeout_s:
                reason = (
                    "the movement was mostly up or down, not sideways"
                    if self._rejected
                    else f"no sideways movement within {cfg.reference_timeout_s:.0f} s"
                )
                self._fail_reference(events, reason)
                return True
            return False

        # settle: wait out the stop at the end of the shuffle
        if still_for < SETTLE_S and now - self._step_start < 2 * cfg.reference_timeout_s:
            return False
        events.append(
            StartupEvent(
                "reference",
                "ok",
                "world reference: OK",
                {"ok": True, "right_world": [round(v, 4) for v in self.frame.right]},
            )
        )
        return True

    def _prompt(self, events, key: str, message: str) -> None:
        if (key, message) not in self._prompted:
            self._prompted.add((key, message))
            events.append(StartupEvent(key.split(":")[0], "prompt", message))

    def _fail_reference(self, events, reason: str) -> None:
        self._fail(events, "reference", f"world reference: FAILED ({reason})", reason)

    def _fail(self, events, step: str, message: str, reason: str | None = None) -> None:
        self.failed = StartupEvent(
            step, "fail", message, {"ok": False, "reason": reason or message}
        )
        events.append(self.failed)
        self._steps = [step]  # the caller stops here; nothing later runs


class FieldMonitor:
    """Watches magnetic field strength during play. It only reports; nothing reacts."""

    def __init__(self, config: GravityConfig, since_start=lambda t: t):
        self.config = config
        self.excursions: list[dict] = []
        self._since_start = since_start
        self._last: Status | None = None
        self._open: dict | None = None

    def update(self, status: Status | None, now: float) -> None:
        if status is None or status is self._last:
            return
        self._last = status
        strength = status.field_ut
        if strength == 0.0:
            return  # magnetometer off
        outside = not self.config.mag_min_ut <= strength <= self.config.mag_max_ut
        if outside and self._open is None:
            self._open = {"start": now, "peak": strength}
            log.warning(
                "magnetic field %.0f uT is outside %.0f-%.0f uT at %.1f s",
                strength,
                self.config.mag_min_ut,
                self.config.mag_max_ut,
                self._since_start(now),
            )
        elif outside:
            # Furthest from the allowed band, in either direction
            middle = (self.config.mag_min_ut + self.config.mag_max_ut) / 2
            if abs(strength - middle) > abs(self._open["peak"] - middle):
                self._open["peak"] = strength
        elif self._open is not None:
            self._close(now)

    def close(self, now: float) -> None:
        if self._open is not None:
            self._close(now)

    def _close(self, now: float) -> None:
        excursion = {
            "start_s": round(self._since_start(self._open["start"]), 2),
            "peak_ut": round(self._open["peak"], 1),
            "duration_s": round(now - self._open["start"], 2),
        }
        self._open = None
        self.excursions.append(excursion)
        log.warning(
            "magnetic field back in range after %.1f s (peak %.0f uT)",
            excursion["duration_s"],
            excursion["peak_ut"],
        )
