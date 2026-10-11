"""Bridge configuration, loaded from TOML (see bridge/config.toml).

Gesture thresholds and delays are not here; they live in tuning.toml at the repo root.
"""

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
    websocket_host: str = "127.0.0.1"
    websocket_port: int = 8765
    latency_log: bool = True  # record sample timing to logs/raw/
    # None: read tuning.toml for the transport in use (see tuning.py)
    gestures: GestureConfig | None = None


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    config = Config()
    config.transport = raw.get("transport", config.transport)
    config.sinks = list(raw.get("sinks", config.sinks))
    config.key_hold_ms = int(raw.get("key_hold_ms", config.key_hold_ms))

    config.usb_port = raw.get("usb", {}).get("port", config.usb_port)

    ws = raw.get("websocket", {})
    config.websocket_host = ws.get("host", config.websocket_host)
    config.websocket_port = int(ws.get("port", config.websocket_port))

    config.latency_log = bool(raw.get("latency", {}).get("enabled", config.latency_log))

    ble = raw.get("ble", {})
    config.device_name = ble.get("name", config.device_name)
    config.device_address = ble.get("address", config.device_address)
    return config
