"""BLE wire format. Must match .claude/docs/protocol.md and firmware/include/protocol.h."""

import struct
from dataclasses import dataclass

PROTOCOL_VERSION = 1

DEVICE_NAME = "WeFit"
SERVICE_UUID = "7e3f0001-6b1c-4f6a-9d2e-5a1c0f3b9a10"
SAMPLE_CHAR_UUID = "7e3f0002-6b1c-4f6a-9d2e-5a1c0f3b9a10"
INFO_CHAR_UUID = "7e3f0003-6b1c-4f6a-9d2e-5a1c0f3b9a10"

ACCEL_SCALE = 100.0  # 1 LSB = 0.01 m/s^2
QUAT_SCALE = 16384.0  # 1 LSB = 1/16384

SAMPLE = struct.Struct("<HH3h4hBB")  # 20 bytes
INFO = struct.Struct("<BHH")  # 5 bytes


@dataclass(frozen=True, slots=True)
class Sample:
    seq: int
    t_ms: int
    accel: tuple[float, float, float]  # m/s^2, gravity removed, sensor frame
    quat: tuple[float, float, float, float]  # w, x, y, z
    calib: int = 0
    flags: int = 0


@dataclass(frozen=True, slots=True)
class Info:
    protocol_version: int
    fw_version: int
    sample_rate_hz: int


def decode_sample(data: bytes) -> Sample:
    if len(data) != SAMPLE.size:
        raise ValueError(f"sample must be {SAMPLE.size} bytes, got {len(data)}")
    seq, t_ms, ax, ay, az, qw, qx, qy, qz, calib, flags = SAMPLE.unpack(data)
    return Sample(
        seq=seq,
        t_ms=t_ms,
        accel=(ax / ACCEL_SCALE, ay / ACCEL_SCALE, az / ACCEL_SCALE),
        quat=(qw / QUAT_SCALE, qx / QUAT_SCALE, qy / QUAT_SCALE, qz / QUAT_SCALE),
        calib=calib,
        flags=flags,
    )


def encode_sample(sample: Sample) -> bytes:
    return SAMPLE.pack(
        sample.seq & 0xFFFF,
        sample.t_ms & 0xFFFF,
        *(round(v * ACCEL_SCALE) for v in sample.accel),
        *(round(v * QUAT_SCALE) for v in sample.quat),
        sample.calib,
        sample.flags,
    )


SERIAL_PREFIX = "S,"
SERIAL_BAUD = 115200


def parse_sample_line(line: str) -> Sample | None:
    """Parse one USB serial line: S,seq,t_ms,ax,ay,az,qw,qx,qy,qz,calib (raw integers).

    Returns None for anything else, so firmware log lines can share the port.
    """
    line = line.strip()
    if not line.startswith(SERIAL_PREFIX):
        return None
    try:
        seq, t_ms, ax, ay, az, qw, qx, qy, qz, calib = (int(v) for v in line[2:].split(","))
    except ValueError:
        return None
    return Sample(
        seq=seq,
        t_ms=t_ms,
        accel=(ax / ACCEL_SCALE, ay / ACCEL_SCALE, az / ACCEL_SCALE),
        quat=(qw / QUAT_SCALE, qx / QUAT_SCALE, qy / QUAT_SCALE, qz / QUAT_SCALE),
        calib=calib,
    )


def decode_info(data: bytes) -> Info:
    if len(data) != INFO.size:
        raise ValueError(f"info must be {INFO.size} bytes, got {len(data)}")
    return Info(*INFO.unpack(data))
