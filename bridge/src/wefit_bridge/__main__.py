"""Standalone bridge: python -m wefit_bridge --transport usb|ble|fake [--sink console|keyboard|websocket]"""

import argparse
import asyncio
import logging
import sys

from .config import TRANSPORTS, Config, load_config
from .latency import make_tracker
from .pipeline import build_pipeline, run
from .sinks import SINKS
from .sinks.websocket import WebSocketPortError
from .startup import StartupFailed
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


README_SECTION = "Fusion mode and ground-referenced gestures"


def startup_failure_message(error: StartupFailed, argv: list[str]) -> str:
    """What to print when a startup check stops the bridge, and what to run instead."""
    if error.step != "reference":
        return f"Startup failed: {error.reason}"
    # The same command without --gravity, so the transport, port and sinks carry over
    command = " ".join(["python -m wefit_bridge", *(a for a in argv if a != "--gravity")])
    return (
        f"Startup failed: the initial world reference could not be set ({error.reason}).\n"
        "Ground-referenced mode was not started. To run with the fixed sensor orientation\n"
        "from tuning.toml instead, run:\n"
        "\n"
        f"  {command}\n"
        "\n"
        "The sensor mode is chosen in this order: the --gravity flag (always NDOF), then\n"
        'fusion_mode = "imu" or "ndof" in tuning.toml, otherwise IMU.\n'
        f'All the options are in README.md, section "{README_SECTION}".'
    )


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
    parser.add_argument(
        "--gravity",
        action="store_true",
        help="ground-referenced gestures: NDOF mode, no fixed sensor orientation; "
        "overrides fusion_mode in tuning.toml",
    )
    parser.add_argument(
        "--no-latency-log",
        action="store_true",
        help="do not record sample timing to logs/raw/ or print the latency summary",
    )
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

    if args.gravity:
        config.gravity = True
    if args.no_latency_log:
        config.latency_log = False

    try:
        pipeline = build_pipeline(config)
    except TuningError as e:
        parser.exit(1, f"{e}\n")

    try:
        transport = make_transport(config)
        asyncio.run(run(transport, pipeline, tracker=make_tracker(config, transport)))
    except KeyboardInterrupt:
        pass
    except WebSocketPortError as e:
        parser.exit(1, f"{e}\n")
    except StartupFailed as e:
        parser.exit(1, f"\n{startup_failure_message(e, sys.argv[1:])}\n")


if __name__ == "__main__":
    main()
