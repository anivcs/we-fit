"""Bridge configuration, loaded from TOML (see config.example.toml)."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .gestures import GestureConfig
from .protocol import DEVICE_NAME

TRANSPORTS = ("usb", "ble", "fake")


@dataclass(slots=True)
class Config:
    transport: str = "usb"
    usb_port: str | None = None  # auto-detect when None
    device_name: str = DEVICE_NAME
    device_address: str | None = None
    key_hold_ms: int = 120
    sinks: list[str] = field(default_factory=lambda: ["console"])
    gestures: GestureConfig = field(default_factory=GestureConfig)


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = Config()
    config.transport = raw.get("transport", config.transport)
    config.sinks = list(raw.get("sinks", config.sinks))
    config.key_hold_ms = int(raw.get("key_hold_ms", config.key_hold_ms))

    config.usb_port = raw.get("usb", {}).get("port", config.usb_port)

    ble = raw.get("ble", {})
    config.device_name = ble.get("name", config.device_name)
    config.device_address = ble.get("address", config.device_address)

    g = raw.get("gestures", {})
    d = config.gestures
    config.gestures = GestureConfig(
        side_threshold=float(g.get("side_threshold", d.side_threshold)),
        up_threshold=float(g.get("up_threshold", d.up_threshold)),
        down_threshold=float(g.get("down_threshold", d.down_threshold)),
        rest_threshold=float(g.get("rest_threshold", d.rest_threshold)),
        rest_s=float(g.get("rest_ms", d.rest_s * 1000)) / 1000,
        cooldown_s=float(g.get("cooldown_ms", d.cooldown_s * 1000)) / 1000,
    )
    return config
