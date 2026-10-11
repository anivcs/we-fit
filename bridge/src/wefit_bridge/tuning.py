"""Loads gesture tuning from tuning.toml. Edit that file, not this one."""

import logging
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

from .events import KEYS
from .gestures import DirectionConfig, GestureConfig
from .protocol import MODES
from .world import GravityConfig

log = logging.getLogger(__name__)

FILENAME = "tuning.toml"
PROFILES = ("usb", "ble")
# This file is <repo>/bridge/src/wefit_bridge/tuning.py in the editable install
REPO_ROOT = Path(__file__).resolve().parents[3]


class TuningError(ValueError):
    pass


@dataclass(slots=True)
class Tuning:
    """Everything tuning.toml holds for one transport."""

    gestures: GestureConfig = field(default_factory=GestureConfig)
    fusion_mode: str = "imu"  # used when --gravity is not given
    gravity: GravityConfig = field(default_factory=GravityConfig)


def find_tuning() -> Path | None:
    """tuning.toml in the current folder, else the one at the repo root."""
    for folder in (Path.cwd(), REPO_ROOT):
        if (folder / FILENAME).is_file():
            return folder / FILENAME
    return None


def _check_names(table: dict, allowed: tuple[str, ...], where: str) -> None:
    unknown = sorted(set(table) - set(allowed))
    if unknown:
        raise ValueError(f"{where}: unknown setting {', '.join(unknown)} (valid: {', '.join(allowed)})")


def _number(table: dict, name: str, default: float, where: str) -> float:
    value = table.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where}: {name} = {value!r} must be a number")
    is_threshold = name.endswith("threshold")
    if value < 0 or (is_threshold and value == 0):
        limit = "greater than 0" if is_threshold else "0 or more"
        raise ValueError(f"{where}: {name} = {value} must be {limit}")
    return float(value)


def load_tuning(transport: str, path: str | Path | None = None) -> GestureConfig:
    """Gesture settings for one transport. Missing file or settings mean the defaults."""
    return load(transport, path).gestures


def load(transport: str, path: str | Path | None = None) -> Tuning:
    """All settings for one transport. Missing file or settings mean the defaults."""
    defaults = GestureConfig()
    if transport not in PROFILES:
        return Tuning()  # "fake" plays a fixed script, so it keeps fixed settings
    path = Path(path) if path else find_tuning()
    if path is None:
        log.info("no %s found; using built-in gesture defaults", FILENAME)
        return Tuning()

    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
        _check_names(raw, ("fusion_mode", "orientation", "gravity", *PROFILES), "top level")

        fusion_mode = raw.get("fusion_mode", "imu")
        if fusion_mode not in MODES:
            raise ValueError(
                f"fusion_mode = {fusion_mode!r}: expected one of {', '.join(MODES)}"
            )

        gravity_names = tuple(f.name for f in fields(GravityConfig))
        gravity_table = raw.get("gravity", {})
        _check_names(gravity_table, gravity_names, "[gravity]")
        gravity_defaults = GravityConfig()
        gravity = GravityConfig(
            **{
                name: _number(gravity_table, name, getattr(gravity_defaults, name), "[gravity]")
                for name in gravity_names
            }
        )

        orientation = raw.get("orientation", {})
        _check_names(orientation, ("right", "up"), "[orientation]")

        profile = raw.get(transport, {})
        where = f"[{transport}]"
        _check_names(profile, ("rest_threshold", *KEYS), where)

        directions = {}
        for key in KEYS:
            default: DirectionConfig = getattr(defaults, key)
            row = profile.get(key, {})
            row_where = f"{where} {key}"
            _check_names(row, ("threshold", "rest_ms", "cooldown_ms"), row_where)
            directions[key] = DirectionConfig(
                threshold=_number(row, "threshold", default.threshold, row_where),
                rest_s=_number(row, "rest_ms", default.rest_s * 1000, row_where) / 1000,
                cooldown_s=_number(row, "cooldown_ms", default.cooldown_s * 1000, row_where) / 1000,
            )

        config = GestureConfig(
            **directions,
            rest_threshold=_number(profile, "rest_threshold", defaults.rest_threshold, where),
            right_axis=orientation.get("right", defaults.right_axis),
            up_axis=orientation.get("up", defaults.up_axis),
        )
    except ValueError as e:  # includes tomllib.TOMLDecodeError
        raise TuningError(f"{path}: {e}") from None

    log.info("gesture tuning: %s %s", path, where)
    return Tuning(config, fusion_mode, gravity)
