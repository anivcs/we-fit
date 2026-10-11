"""Sensor-side analysis of a session: gesture peaks for tuning, calibration, tilt error,
heading drift and magnetic field. Reads the .imu.bin rows beside the timing rows.

Nothing here is logged by the bridge; it is all recomputed from the raw values, so a
change to this file re-analyses old sessions.
"""

from dataclasses import dataclass, field

import numpy as np

from ..events import KEYS
from ..gestures import SENSOR_AXES, GestureConfig
from ..protocol import ACCEL_SCALE, MAG_SCALE, QUAT_SCALE
from ..world import GravityConfig

G = 9.81
STILL_WINDOW_S = 0.5  # a sample is "still" only if this much time around it is quiet too
NEAR_MISS_SHARE = 0.5  # a movement this far towards the threshold counts as a near miss
BUCKET_S = 5.0  # tilt error is shown as one point per bucket

# Fun estimate, about +/- 50 %. Active energy only: mechanical work / muscle efficiency
# for a 70 kg person at 25 % efficiency. Jump: centre of mass raised 0.25 m. Squat:
# centre of mass travels 0.35 m. Side shuffle: up to 1.5 m/s and back to rest.
BODY_MASS_KG = 70
KCAL_PER_GESTURE = {"up": 0.16, "down": 0.23, "left": 0.15, "right": 0.15}
EXERCISE = {"up": "jump", "down": "squat", "left": "shuffle left", "right": "shuffle right"}

# Direction -> (column of the controller-frame vector, sign)
DIRECTION = {"right": (0, 1.0), "left": (0, -1.0), "up": (2, 1.0), "down": (2, -1.0)}


@dataclass(slots=True)
class DirectionStats:
    threshold: float
    fired: np.ndarray  # peak acceleration (m/s^2) of each movement that fired
    missed: np.ndarray  # peaks of movements past NEAR_MISS_SHARE that did not fire
    rise_ms: np.ndarray  # rest -> threshold, per fired gesture: the detection delay
    active_ms: np.ndarray  # time above the rest threshold, per fired gesture


@dataclass(slots=True)
class Motion:
    t_s: np.ndarray  # seconds since the bridge started, one per row
    duration_min: float
    directions: dict[str, DirectionStats]
    calib: np.ndarray  # (rows, 4): sys, gyro, accel, mag, each 0-3
    field_ut: np.ndarray  # magnetic field strength; NaN where the magnetometer is off
    tilt_t_s: np.ndarray  # bucket times for tilt_deg
    tilt_deg: np.ndarray  # tilt error implied by leftover acceleration while still
    heading_deg: np.ndarray  # rotation about vertical accumulated while still
    stats: dict = field(default_factory=dict)  # headline numbers for the debug table


def controller_vectors(session) -> np.ndarray:
    """Acceleration as (right, forward, up), the frame the gesture detector used."""
    accel = session.imu["accel"] / ACCEL_SCALE
    meta = session.meta
    right_world = (meta.get("startup", {}).get("reference") or {}).get("right_world")
    if meta.get("session", {}).get("gesture_frame") == "world" and right_world:
        w, x, y, z = (session.imu["quat"] / QUAT_SCALE).T
        u = np.stack([x, y, z], axis=1)
        cross = np.cross(u, accel)
        world = accel + 2 * (w[:, None] * cross + np.cross(u, cross))
        rx, ry = right_world
        return np.stack(
            [world[:, 0] * rx + world[:, 1] * ry, -world[:, 0] * ry + world[:, 1] * rx, world[:, 2]],
            axis=1,
        )
    tuning = meta.get("tuning") or {}
    defaults = GestureConfig()
    ri, rs = SENSOR_AXES[tuning.get("right_axis", defaults.right_axis)]
    ui, us = SENSOR_AXES[tuning.get("up_axis", defaults.up_axis)]
    return np.stack([rs * accel[:, ri], accel[:, 3 - ri - ui], us * accel[:, ui]], axis=1)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, stop) of each stretch of True."""
    edges = np.flatnonzero(np.diff(np.concatenate([[False], mask, [False]]).astype(np.int8)))
    return list(zip(edges[::2], edges[1::2]))


def _direction_stats(session, vectors, t_s, playing) -> dict[str, DirectionStats]:
    tuning = session.meta.get("tuning") or {}
    defaults = GestureConfig()
    rest = tuning.get("rest_threshold", defaults.rest_threshold)
    keys = session.records["key"]
    out = {}
    for name in KEYS:
        column, sign = DIRECTION[name]
        threshold = (tuning.get(name) or {}).get("threshold", getattr(defaults, name).threshold)
        value = sign * vectors[:, column]
        active = np.abs(vectors[:, column]) >= rest
        code = KEYS.index(name) + 1
        fired, missed, rise, active_ms = [], [], [], []
        for start, stop in _runs((value >= NEAR_MISS_SHARE * threshold) & playing):
            hits = np.flatnonzero(keys[start:stop] == code)
            if len(hits) == 0:
                missed.append(value[start:stop].max())
                continue
            fired.append(value[start:stop].max())
            # Walk out from the trigger sample to where the axis was last and next at rest
            trigger = first = last = start + hits[0]
            while first > 0 and active[first - 1]:
                first -= 1
            while last < len(active) - 1 and active[last + 1]:
                last += 1
            rise.append((t_s[trigger] - t_s[first]) * 1000)
            active_ms.append((t_s[last] - t_s[first]) * 1000)
        out[name] = DirectionStats(
            threshold, np.array(fired), np.array(missed), np.array(rise), np.array(active_ms)
        )
    return out


def analyse_motion(session) -> Motion | None:
    """None for sessions recorded before the sensor log existed, or with too few rows."""
    imu = session.imu
    if imu is None or len(imu) < 2:
        return None
    meta = session.meta
    records = session.records
    t_s = records["rx_us"] / 1e6 + (meta.get("t0_offset_s") or 0.0)
    limits = {**vars_of(GravityConfig()), **(meta.get("limits") or {})}

    vectors = controller_vectors(session)
    # Movements during the startup checks (the reference shuffle) are not gestures
    playing = t_s >= (meta.get("session", {}).get("ready_s") or 0.0)

    accel = imu["accel"] / ACCEL_SCALE
    quiet = np.linalg.norm(accel, axis=1) < limits["still_ms2"]
    rate = (len(t_s) - 1) / max(t_s[-1] - t_s[0], 1e-9)
    window = max(int(STILL_WINDOW_S * rate), 1)
    still = np.convolve(~quiet, np.ones(window), mode="same") == 0

    # Tilt: with the frame level, gravity is removed exactly and a still sensor reads 0.
    # A frame tilted by a small angle leaves g * sin(angle) behind.
    residual = np.linalg.norm(accel, axis=1)
    bucket = ((t_s - t_s[0]) // BUCKET_S).astype(int)
    tilt_t, tilt = [], []
    for b in np.unique(bucket[still]):
        rows = still & (bucket == b)
        tilt_t.append(t_s[0] + (b + 0.5) * BUCKET_S)
        tilt.append(np.degrees(np.arcsin(min(np.median(residual[rows]) / G, 1.0))))

    # Heading: rotation about the vertical between consecutive still samples. A sensor
    # that is not moving should not turn, so what accumulates is drift.
    w, x, y, z = (imu["quat"] / QUAT_SCALE).T
    yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    step = (np.diff(yaw) + np.pi) % (2 * np.pi) - np.pi
    counted = still[1:] & still[:-1] & (np.diff(records["epoch"]) == 0)
    heading = np.concatenate([[0.0], np.cumsum(np.where(counted, np.degrees(step), 0.0))])
    still_min = float(np.diff(t_s)[counted].sum()) / 60

    calib = np.stack([imu["calib"] >> shift & 3 for shift in (6, 4, 2, 0)], axis=1)
    field_ut = np.where(imu["mag_ut16"] > 0, imu["mag_ut16"] / MAG_SCALE, np.nan)
    measured = ~np.isnan(field_ut)
    outside = measured & ((field_ut < limits["mag_min_ut"]) | (field_ut > limits["mag_max_ut"]))

    stats = {
        "calib_min": dict(zip(("sys", "gyro", "accel", "mag"), calib.min(axis=0).tolist())),
        "field_median_ut": float(np.nanmedian(field_ut)) if measured.any() else None,
        "field_outside_pct": 100 * outside.sum() / measured.sum() if measured.any() else None,
        "field_limits": (limits["mag_min_ut"], limits["mag_max_ut"]),
        "still_pct": 100 * still.mean(),
        "tilt_p95_deg": float(np.percentile(tilt, 95)) if tilt else None,
        "heading_drift_deg": float(heading[-1]) if still_min else None,
        "heading_rate_deg_min": float(heading[-1] / still_min) if still_min else None,
    }
    return Motion(
        t_s=t_s,
        duration_min=float(t_s[-1] - t_s[0]) / 60,
        directions=_direction_stats(session, vectors, t_s, playing),
        calib=calib,
        field_ut=field_ut,
        tilt_t_s=np.array(tilt_t),
        tilt_deg=np.array(tilt),
        heading_deg=heading,
        stats=stats,
    )


def vars_of(config) -> dict:
    return {name: getattr(config, name) for name in config.__dataclass_fields__}


def gesture_counts(session) -> dict[str, int]:
    keys = session.records["key"]
    return {name: int((keys == i + 1).sum()) for i, name in enumerate(KEYS)}


def kcal(counts: dict[str, int]) -> float:
    return sum(KCAL_PER_GESTURE[name] * n for name, n in counts.items())
