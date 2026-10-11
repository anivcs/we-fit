"""Ground-referenced frame: turns sensor-frame acceleration into right / forward / up.

Up comes from gravity, through the BNO055's quaternion, so the controller can be held or
worn any way round. Right cannot come from a sensor (the magnetometer finds north, not
the screen), so it is captured once from a sideways movement at startup.

The quaternion is taken to rotate sensor-frame vectors into the world frame, with world
+Z pointing up. That is the BNO055's documented convention, but it has not been checked
on our hardware yet (open item O1 in .claude/docs/gravity-proposal.md).
"""

import math
from dataclasses import dataclass

Vector = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]

QUAT_NORM_TOLERANCE = 0.02  # a healthy quaternion has length 1


@dataclass(slots=True)
class GravityConfig:
    """The [gravity] table in tuning.toml."""

    mag_min_ut: float = 20.0  # field strength below this is suspicious
    mag_max_ut: float = 80.0  # and above this; Earth's field is 25 to 65
    still_ms2: float = 0.5  # linear acceleration below this counts as still
    reference_timeout_s: float = 10.0  # how long to wait for the "shuffle right"


def magnitude(v) -> float:
    return math.sqrt(sum(c * c for c in v))


def quat_valid(q: Quaternion) -> bool:
    """False for the all-zero quaternion the chip reports before fusion has started."""
    return abs(magnitude(q) - 1.0) <= QUAT_NORM_TOLERANCE


def rotate(q: Quaternion, v: Vector) -> Vector:
    """Rotate v by the unit quaternion q (w, x, y, z): sensor frame -> world frame."""
    w, x, y, z = q
    vx, vy, vz = v
    # v' = v + 2w(u x v) + 2u x (u x v), with u = (x, y, z)
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    return (
        vx + 2 * (w * cx + y * cz - z * cy),
        vy + 2 * (w * cy + z * cx - x * cz),
        vz + 2 * (w * cz + x * cy - y * cx),
    )


def conjugate(q: Quaternion) -> Quaternion:
    w, x, y, z = q
    return w, -x, -y, -z


@dataclass(frozen=True, slots=True)
class WorldFrame:
    """Where the player's right is, as a horizontal unit vector in the world frame."""

    right: tuple[float, float]

    @classmethod
    def from_horizontal(cls, x: float, y: float) -> "WorldFrame":
        length = math.hypot(x, y)
        return cls((x / length, y / length))

    def to_controller(self, accel: Vector, quat: Quaternion) -> Vector:
        """Sensor-frame acceleration -> (right, forward, up), the frame gestures use."""
        wx, wy, wz = rotate(quat, accel)
        rx, ry = self.right
        # forward = up x right
        return wx * rx + wy * ry, -wx * ry + wy * rx, wz
