"""Scripted controller for running the pipeline without hardware."""

import asyncio
import time
from collections.abc import AsyncIterator

from ..protocol import Sample, decode_sample, encode_sample

# Acceleration pulse (m/s^2) for each gesture, in the order they are played
SCRIPT = {
    "up": (0.0, 0.0, 9.0),
    "right": (9.0, 0.0, 0.0),
    "down": (0.0, 0.0, -9.0),
    "left": (-9.0, 0.0, 0.0),
}


class FakeTransport:
    def __init__(self, rate_hz: int = 50, gesture_every_s: float = 1.5, pulse_s: float = 0.1):
        self.rate_hz = rate_hz
        self.gesture_every_s = gesture_every_s
        self.pulse_s = pulse_s

    async def samples(self) -> AsyncIterator[Sample]:
        period = 1 / self.rate_hz
        pulses = list(SCRIPT.values())
        seq = 0
        start = time.monotonic()
        while True:
            # Wall clock, not seq * period: asyncio.sleep is coarse on Windows
            t = time.monotonic() - start
            cycle, offset = divmod(t, self.gesture_every_s)
            # Quiet for the first cycle, then one pulse at the start of each
            if cycle >= 1 and offset < self.pulse_s:
                accel = pulses[(int(cycle) - 1) % len(pulses)]
            else:
                accel = (0.0, 0.0, 0.0)

            sample = Sample(
                seq=seq & 0xFFFF,
                t_ms=int(t * 1000) & 0xFFFF,
                accel=accel,
                quat=(1.0, 0.0, 0.0, 0.0),
            )
            # Round-trip through the wire format so the fake exercises the real decoder
            yield decode_sample(encode_sample(sample))
            seq += 1
            await asyncio.sleep(period)
