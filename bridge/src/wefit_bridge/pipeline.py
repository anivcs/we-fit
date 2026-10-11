"""Sample -> gesture -> key events -> sinks."""

import asyncio
import logging
import time
from collections.abc import Callable, Iterable

from .config import Config
from .gestures import GestureDetector
from .keys import KeyState
from .protocol import Sample
from .sinks import Sink, make_sink

log = logging.getLogger(__name__)

TICK_S = 0.01


class Pipeline:
    """Synchronous and clock-free so it can be tested without hardware or asyncio."""

    def __init__(self, detector: GestureDetector, keys: KeyState, sinks: Iterable[Sink]):
        self.detector = detector
        self.keys = keys
        self.sinks = list(sinks)
        self.last_sample: Sample | None = None
        # Orientation captured at the last reset; unused by gestures today
        self.reference_quat: tuple[float, float, float, float] | None = None

    def on_sample(self, sample: Sample, now: float) -> None:
        self.last_sample = sample
        gesture = self.detector.update(sample.accel, now)
        if gesture is not None:
            self._emit(self.keys.press(gesture, now))

    def tick(self, now: float) -> None:
        self._emit(self.keys.tick(now))

    def reset(self, now: float) -> None:
        """Start a new round: drop held key, clear cooldown, re-zero orientation."""
        self._emit(self.keys.release(now))
        self.detector.reset()
        if self.last_sample is not None:
            self.reference_quat = self.last_sample.quat

    def close(self, now: float) -> None:
        self._emit(self.keys.release(now))
        for sink in self.sinks:
            sink.close()

    def _emit(self, events) -> None:
        for event in events:
            for sink in self.sinks:
                sink.emit(event)


def build_pipeline(config: Config, sinks: Iterable[Sink] | None = None) -> Pipeline:
    if sinks is None:
        sinks = [make_sink(name, config) for name in config.sinks]
    return Pipeline(
        GestureDetector(config.gestures),
        KeyState(config.key_hold_ms / 1000),
        sinks,
    )


async def run(transport, pipeline: Pipeline, clock: Callable[[], float] = time.monotonic) -> None:
    """Feed samples from the transport into the pipeline until cancelled."""

    async def ticker():
        # Runs even when no samples arrive, so a lost link cannot leave a key down
        while True:
            await asyncio.sleep(TICK_S)
            pipeline.tick(clock())

    for sink in pipeline.sinks:
        start = getattr(sink, "start", None)
        if start is not None:
            await start()

    tick_task = asyncio.create_task(ticker())
    try:
        async for sample in transport.samples():
            pipeline.on_sample(sample, clock())
    finally:
        tick_task.cancel()
        pipeline.close(clock())
