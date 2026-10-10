"""Sanity checks for this machine: packages, USB, Bluetooth.

Run through check.py at the repo root. A failure message says what to do next.
"""

import asyncio
import functools
import importlib.util
import time

import pytest


def fail(message: str):
    pytest.fail(message, pytrace=False)


# --- Packages ---------------------------------------------------------------


@pytest.mark.parametrize(
    "module, package",
    [
        ("wefit_bridge", "wefit-bridge (this repo)"),
        ("bleak", "bleak"),
        ("serial", "pyserial"),
        ("websockets", "websockets"),
        ("pynput", "pynput"),
        ("platformio", "platformio"),
    ],
)
def test_package_is_installed(module, package):
    if importlib.util.find_spec(module) is None:
        fail(f"{package} is not installed. Run: pip install -r requirements.txt")


# --- USB --------------------------------------------------------------------


def usb_port() -> str:
    from wefit_bridge.transport.usb import describe_ports, find_ports

    ports = find_ports()
    if not ports:
        seen = "; ".join(describe_ports()) or "none"
        fail(
            "No ESP32 found on USB. Plug it in with a data cable (not charge-only) and "
            "install the CP210x or CH340 driver if Windows shows an unknown device. "
            f"Serial ports seen: {seen}"
        )
    return ports[0]


@pytest.mark.usb
def test_esp32_is_plugged_in():
    usb_port()


@pytest.mark.usb
def test_esp32_sends_samples_over_usb():
    import serial

    from wefit_bridge.protocol import SERIAL_BAUD, parse_sample_line

    port = usb_port()
    conn = None
    try:
        conn = serial.Serial(port, SERIAL_BAUD, timeout=0.5)
    except serial.SerialException:
        pass
    if conn is None:
        fail(f"{port} is in use. Close the serial monitor or any other program using it.")

    lines = []
    with conn:
        deadline = time.monotonic() + 10  # opening the port reboots the board
        while time.monotonic() < deadline:
            line = conn.readline().decode("ascii", errors="ignore").strip()
            if parse_sample_line(line) is not None:
                return
            if line:
                lines.append(line)

    if not lines:
        fail(f"{port} is silent. Flash the firmware: pio run -d firmware -t upload")
    fail(f"{port} sent no samples. Last lines from the board: {lines[-3:]}")


# --- Bluetooth --------------------------------------------------------------


@functools.cache
def bluetooth_scan() -> dict:
    """One 10 s scan shared by the Bluetooth checks: {address: (device, adv)}."""
    from bleak import BleakScanner

    return asyncio.run(BleakScanner.discover(timeout=10.0, return_adv=True))


def scan_or_fail() -> dict:
    error = None
    try:
        return bluetooth_scan()
    except Exception as e:
        error = e
    fail(f"Bluetooth is off or this machine has no Bluetooth adapter. Turn it on. ({error})")


def controller():
    from wefit_bridge.protocol import DEVICE_NAME

    for device, adv in scan_or_fail().values():
        if DEVICE_NAME in (device.name, adv.local_name):
            return device
    fail(
        f"No Bluetooth device named {DEVICE_NAME!r} found. Check that the ESP32 is powered, "
        "flashed, within a few metres, and not already connected to another laptop or phone."
    )


@pytest.mark.bluetooth
def test_bluetooth_is_enabled():
    scan_or_fail()


@pytest.mark.bluetooth
def test_esp32_is_visible_over_bluetooth():
    controller()


@pytest.mark.bluetooth
def test_esp32_sends_samples_over_bluetooth():
    from bleak import BleakClient

    from wefit_bridge.protocol import (
        INFO_CHAR_UUID,
        PROTOCOL_VERSION,
        SAMPLE_CHAR_UUID,
        decode_info,
        decode_sample,
    )

    device = controller()

    async def read():
        got_sample = asyncio.Event()

        def on_notify(_char, data):
            decode_sample(bytes(data))
            got_sample.set()

        async with BleakClient(device, timeout=15) as client:
            info = decode_info(bytes(await client.read_gatt_char(INFO_CHAR_UUID)))
            await client.start_notify(SAMPLE_CHAR_UUID, on_notify)
            await asyncio.wait_for(got_sample.wait(), timeout=5)
            return info

    info = error = None
    try:
        info = asyncio.run(read())
    except asyncio.TimeoutError:
        error = "Connected to the ESP32 but no samples arrived within 5 s."
    except Exception as e:
        error = f"Found the ESP32 but could not connect or read from it: {e}"
    if error:
        fail(error)

    if info.protocol_version != PROTOCOL_VERSION:
        fail(
            f"Firmware speaks protocol {info.protocol_version}, this code expects "
            f"{PROTOCOL_VERSION}. Re-flash: pio run -d firmware -t upload"
        )
