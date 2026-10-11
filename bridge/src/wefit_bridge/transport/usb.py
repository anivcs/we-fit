"""USB serial transport: reads the sample lines the firmware prints on its USB port."""

import asyncio
import logging
from collections.abc import AsyncIterator

import serial
from serial.tools import list_ports

from ..clock import now
from ..protocol import (
    MODES,
    SERIAL_BAUD,
    SERIAL_PREFIX,
    STATUS_PREFIX,
    Sample,
    Status,
    command_line,
    parse_sample_line,
    parse_status_line,
)

log = logging.getLogger(__name__)

# USB vendor IDs of the serial chips found on ESP32 boards
ESP32_USB_VENDORS = {
    0x10C4: "CP210x",
    0x1A86: "CH340/CH9102",
    0x0403: "FTDI",
    0x303A: "Espressif",
}


COMMAND_RETRY_S = 0.5


def find_ports() -> list[str]:
    """Serial ports that look like an ESP32 board, e.g. ["COM5"]."""
    return [p.device for p in list_ports.comports() if p.vid in ESP32_USB_VENDORS]


def describe_ports() -> list[str]:
    """Every serial port on this machine, for error messages."""
    return [f"{p.device}: {p.description}" for p in list_ports.comports()]


def _read_line(conn) -> tuple[bytes, float]:
    # Stamped on the reader thread, before the hop back to the event loop
    raw = conn.readline()
    return raw, now()


class UsbTransport:
    def __init__(
        self,
        port: str | None = None,
        baud: int = SERIAL_BAUD,
        retry_delay_s: float = 1.0,
        mode: int = MODES["imu"],
    ):
        self.port = port
        self.baud = baud
        self.retry_delay_s = retry_delay_s
        self.mode = mode  # fusion mode to ask the firmware for
        self.status: Status | None = None  # latest status line
        self.corrupt = 0  # sample lines that failed to parse

    async def samples(self) -> AsyncIterator[Sample]:
        while True:
            port = self.port or next(iter(find_ports()), None)
            if port is None:
                log.warning("no ESP32 found on USB, looking again")
                await asyncio.sleep(self.retry_delay_s)
                continue

            try:
                # Opening the port resets most ESP32 boards; samples start ~3 s later
                with serial.Serial(port, self.baud, timeout=0.5) as conn:
                    log.info("controller connected on %s", port)
                    self.status = None
                    asked = 0.0
                    while True:
                        raw, rx = await asyncio.to_thread(_read_line, conn)
                        line = raw.decode("ascii", errors="ignore")
                        sample = parse_sample_line(line, rx)
                        if sample is not None:
                            # The board ignores input while it boots, so the mode is asked
                            # for once samples flow, and again until a status confirms it
                            wrong = self.status is None or self.status.mode != self.mode
                            if wrong and rx - asked >= COMMAND_RETRY_S:
                                conn.write(command_line(self.mode))
                                asked = rx
                            yield sample
                        elif line.startswith(STATUS_PREFIX):
                            self.status = parse_status_line(line, rx) or self.status
                        elif line.startswith(SERIAL_PREFIX):
                            self.corrupt += 1
            except serial.SerialException as e:
                log.warning("USB error on %s: %s", port, e)

            await asyncio.sleep(self.retry_delay_s)
