"""Standalone bridge: python -m wefit_bridge --transport usb|ble|fake [--sink console|keyboard|websocket]"""

import argparse
import asyncio
import logging

from .config import TRANSPORTS, Config, load_config
from .pipeline import build_pipeline, run
from .sinks import SINKS
from .sinks.websocket import WebSocketPortError
from .transport import make_transport
from .tuning import TuningError


def scan() -> None:
    """Print the controllers this machine can see over USB and Bluetooth."""
    from bleak import BleakScanner

    from .protocol import DEVICE_NAME
    from .transport.usb import describe_ports, find_ports

    print("USB serial ports:")
    esp32_ports = find_ports()
    for line in describe_ports() or ["(none)"]:
        marker = "  <-- ESP32" if line.split(":")[0] in esp32_ports else ""
        print(f"  {line}{marker}")

    print(f"\nBluetooth devices named {DEVICE_NAME!r} (scanning 8 s):")
    try:
        found = asyncio.run(BleakScanner.discover(timeout=8.0, return_adv=True))
    except Exception as e:
        print(f"  scan failed: {e}")
        return
    matches = [
        (device.address, adv.rssi)
        for device, adv in found.values()
        if DEVICE_NAME in (device.name, adv.local_name)
    ]
    for address, rssi in matches:
        print(f"  address = {address}   signal = {rssi} dBm")
    if not matches:
        print("  (none)")


def main() -> None:
    parser = argparse.ArgumentParser(prog="wefit-bridge", description=__doc__)
    parser.add_argument("--config", help="path to a TOML config file")
    parser.add_argument("--transport", choices=TRANSPORTS, help="override the config")
    parser.add_argument("--port", help="USB serial port, e.g. COM5 (default: auto-detect)")
    parser.add_argument(
        "--sink",
        action="append",
        choices=SINKS,
        help="override the config; repeat for several",
    )
    parser.add_argument("--ws-host", help="websocket sink address (default: 127.0.0.1)")
    parser.add_argument("--ws-port", type=int, help="websocket sink port (default: 8765)")
    parser.add_argument("--scan", action="store_true", help="list visible controllers and exit")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.scan:
        scan()
        return

    config = load_config(args.config) if args.config else Config()
    if args.transport:
        config.transport = args.transport
    if args.port:
        config.usb_port = args.port
    if args.sink:
        config.sinks = args.sink
    if args.ws_host:
        config.websocket_host = args.ws_host
    if args.ws_port is not None:
        config.websocket_port = args.ws_port

    try:
        pipeline = build_pipeline(config)
    except TuningError as e:
        parser.exit(1, f"{e}\n")

    try:
        asyncio.run(run(make_transport(config), pipeline))
    except KeyboardInterrupt:
        pass
    except WebSocketPortError as e:
        parser.exit(1, f"{e}\n")


if __name__ == "__main__":
    main()
