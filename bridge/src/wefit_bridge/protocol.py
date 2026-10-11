"""BLE wire format. Must match .claude/docs/protocol.md and firmware/include/protocol.h."""

import struct
from dataclasses import dataclass, field

PROTOCOL_VERSION = 2

DEVICE_NAME = "WeFit"
SERVICE_UUID = "7e3f0001-6b1c-4f6a-9d2e-5a1c0f3b9a10"
SAMPLE_CHAR_UUID = "7e3f0002-6b1c-4f6a-9d2e-5a1c0f3b9a10"
INFO_CHAR_UUID = "7e3f0003-6b1c-4f6a-9d2e-5a1c0f3b9a10"
STATUS_CHAR_UUID = "7e3f0004-6b1c-4f6a-9d2e-5a1c0f3b9a10"
COMMAND_CHAR_UUID = "7e3f0005-6b1c-4f6a-9d2e-5a1c0f3b9a10"

ACCEL_SCALE = 100.0  # 1 LSB = 0.01 m/s^2
QUAT_SCALE = 16384.0  # 1 LSB = 1/16384
MAG_SCALE = 16.0  # 1 LSB = 1/16 microtesla

# Fusion modes: name -> the BNO055's OPR_MODE value, which is what goes on the wire
MODES = {"imu": 0x08, "ndof": 0x0C}
MODE_NAMES = {value: name for name, value in MODES.items()}
FLAG_NDOF = 0x01  # Sample.flags bit 0 (BLE only; the USB sample line has no flags)

SAMPLE = struct.Struct("<HH3h4hBB")  # 20 bytes
# seq and t_ms are both u16 on the wire; unwrap them with these
SEQ_MODULO = 1 << 16
T_MS_MODULO = 1 << 16
INFO = struct.Struct("<BHH")  # 5 bytes
STATUS = struct.Struct("<I3hB")  # 11 bytes


@dataclass(frozen=True, slots=True)
class Sample:
    seq: int
    t_ms: int
    accel: tuple[float, float, float]  # m/s^2, gravity removed, sensor frame
    quat: tuple[float, float, float, float]  # w, x, y, z
    calib: int = 0
    flags: int = 0
    # Host clock (clock.now) when the bytes arrived; 0.0 = not stamped. Not on the wire.
    rx: float = field(default=0.0, compare=False)


@dataclass(frozen=True, slots=True)
class Info:
    protocol_version: int
    fw_version: int
    sample_rate_hz: int


@dataclass(frozen=True, slots=True)
class Status:
    """Slow telemetry, sent a few times a second beside the samples."""

    uptime_ms: int  # device millis(), not truncated
    mag: tuple[float, float, float]  # microtesla, sensor frame; zeros in IMU mode
    mode: int  # BNO055 OPR_MODE, see MODES
    # Host clock (clock.now) when the bytes arrived; 0.0 = not stamped. Not on the wire.
    rx: float = field(default=0.0, compare=False)

    @property
    def mode_name(self) -> str:
        return MODE_NAMES.get(self.mode, f"0x{self.mode:02x}")

    @property
    def field_ut(self) -> float:
        """Magnetic field strength. 0.0 when the magnetometer is off."""
        return sum(v * v for v in self.mag) ** 0.5


def decode_sample(data: bytes, rx: float = 0.0) -> Sample:
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
        rx=rx,
    )


def encode_sample(sample: Sample) -> bytes:
    return SAMPLE.pack(
        sample.seq % SEQ_MODULO,
        sample.t_ms % T_MS_MODULO,
        *(round(v * ACCEL_SCALE) for v in sample.accel),
        *(round(v * QUAT_SCALE) for v in sample.quat),
        sample.calib,
        sample.flags,
    )


SERIAL_PREFIX = "S,"
SERIAL_BAUD = 115200


def parse_sample_line(line: str, rx: float = 0.0) -> Sample | None:
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
        rx=rx,
    )


def decode_info(data: bytes) -> Info:
    if len(data) != INFO.size:
        raise ValueError(f"info must be {INFO.size} bytes, got {len(data)}")
    return Info(*INFO.unpack(data))


STATUS_PREFIX = "T,"
COMMAND_PREFIX = "M,"


def decode_status(data: bytes, rx: float = 0.0) -> Status:
    if len(data) != STATUS.size:
        raise ValueError(f"status must be {STATUS.size} bytes, got {len(data)}")
    uptime_ms, mx, my, mz, mode = STATUS.unpack(data)
    return Status(uptime_ms, (mx / MAG_SCALE, my / MAG_SCALE, mz / MAG_SCALE), mode, rx)


def encode_status(status: Status) -> bytes:
    return STATUS.pack(status.uptime_ms, *(round(v * MAG_SCALE) for v in status.mag), status.mode)


def parse_status_line(line: str, rx: float = 0.0) -> Status | None:
    """Parse one USB serial line: T,uptime_ms,mx,my,mz,mode (raw integers)."""
    line = line.strip()
    if not line.startswith(STATUS_PREFIX):
        return None
    try:
        uptime_ms, mx, my, mz, mode = (int(v) for v in line[2:].split(","))
    except ValueError:
        return None
    return Status(uptime_ms, (mx / MAG_SCALE, my / MAG_SCALE, mz / MAG_SCALE), mode, rx)


def command_line(mode: int) -> bytes:
    """The USB serial line that asks the firmware for a fusion mode."""
    return f"{COMMAND_PREFIX}{mode}\n".encode("ascii")
