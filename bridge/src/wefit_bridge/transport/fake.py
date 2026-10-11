"""Scripted controller for running the pipeline without hardware."""

import asyncio
from collections.abc import AsyncIterator

from ..clock import now
from ..protocol import (
    FLAG_NDOF,
    MODES,
    SEQ_MODULO,
    T_MS_MODULO,
    Sample,
    Status,
    decode_sample,
    decode_status,
    encode_sample,
    encode_status,
)
from ..world import conjugate, rotate

STATUS_EVERY = 10  # samples per status packet, as in the firmware
FULLY_CALIBRATED = 0xFF
FIELD_UT = (20.0, 0.0, -40.0)  # a plausible Earth field, 45 uT

# Acceleration pulse (m/s^2) for each gesture, in the order they are played.
# These are in the player's frame (x right, z up); `mount` turns them into the sensor's.
SCRIPT = {
    "up": (0.0, 0.0, 9.0),
    "right": (9.0, 0.0, 0.0),
    "down": (0.0, 0.0, -9.0),
    "left": (-9.0, 0.0, 0.0),
}


class FakeTransport:
    def __init__(
        self,
        rate_hz: int = 50,
        gesture_every_s: float = 1.5,
        pulse_s: float = 0.1,
        mode: int = MODES["imu"],
        mount: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        reference_at_s: float | None = None,
    ):
        # Under --gravity: stay quiet, shuffle right once at this time for the startup
        # reference, then start the script
        self.reference_at_s = reference_at_s
        self.rate_hz = rate_hz
        self.gesture_every_s = gesture_every_s
        self.pulse_s = pulse_s
        self.mode = mode
        self.mount = mount  # sensor orientation as a quaternion; identity = +x right, +z up
        self.status: Status | None = None

    async def samples(self) -> AsyncIterator[Sample]:
        period = 1 / self.rate_hz
        pulses = list(SCRIPT.values())
        seq = 0
        start = now()
        while True:
            # Wall clock, not seq * period: asyncio.sleep is coarse on Windows
            t = now() - start
            lead = self.reference_at_s
            cycle, offset = divmod(t if lead is None else max(t - lead, 0.0), self.gesture_every_s)
            # Quiet for the first cycle, then one pulse at the start of each
            if lead is not None and lead <= t < lead + self.pulse_s:
                accel = SCRIPT["right"]
            elif cycle >= 1 and offset < self.pulse_s:
                accel = pulses[(int(cycle) - 1) % len(pulses)]
            else:
                accel = (0.0, 0.0, 0.0)

            ndof = self.mode == MODES["ndof"]
            sample = Sample(
                seq=seq % SEQ_MODULO,
                t_ms=int(t * 1000) % T_MS_MODULO,
                accel=rotate(conjugate(self.mount), accel),
                quat=self.mount,
                calib=FULLY_CALIBRATED,
                flags=FLAG_NDOF if ndof else 0,
            )
            if seq % STATUS_EVERY == 0:
                status = Status(int(t * 1000), FIELD_UT if ndof else (0.0, 0.0, 0.0), self.mode)
                self.status = decode_status(encode_status(status), rx=now())
            # Round-trip through the wire format so the fake exercises the real decoder
            yield decode_sample(encode_sample(sample), rx=now())
            seq += 1
            await asyncio.sleep(period)
