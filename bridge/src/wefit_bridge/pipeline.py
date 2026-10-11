"""Sample -> gesture -> key events -> sinks."""

import asyncio
import logging
from collections.abc import Callable, Iterable
from dataclasses import asdict

from .clock import now as default_clock
from .clock import since_start
from .config import Config
from .gestures import GestureDetector, orient
from .keys import KeyState
from .protocol import Sample, Status
from .sinks import Sink, make_sink
from .startup import FieldMonitor, StartupEvent, StartupFailed, StartupGuide, log_event
from .tuning import load
from .world import WorldFrame

log = logging.getLogger(__name__)

TICK_S = 0.01


class Pipeline:
    """Synchronous and clock-free so it can be tested without hardware or asyncio."""

    def __init__(
        self,
        detector: GestureDetector,
        keys: KeyState,
        sinks: Iterable[Sink],
        guide: StartupGuide | None = None,
        on_startup: Callable[[StartupEvent], None] = log_event,
        monitor: FieldMonitor | None = None,
    ):
        self.detector = detector
        self.keys = keys
        self.sinks = list(sinks)
        self.guide = guide
        self.on_startup = on_startup
        self.monitor = monitor
        # Set by the startup guide under --gravity; None means the fixed [orientation]
        self.frame: WorldFrame | None = None
        self.ready_s: float | None = None  # when the startup checks finished
        self.last_sample: Sample | None = None
        # The last sample's acceleration as (right, forward, up), as the detector saw it
        self.last_vector: tuple[float, float, float] | None = None
        # Orientation captured at the last reset; unused by gestures today
        self.reference_quat: tuple[float, float, float, float] | None = None

    def on_sample(self, sample: Sample, now: float, status: Status | None = None) -> str | None:
        """Returns the gesture this sample fired, if any.

        `status` is the transport's latest status packet (fusion mode, magnetometer).
        Raises StartupFailed when a startup check that must pass does not.
        """
        self.last_sample = sample
        guide = self.guide
        if guide is not None and not guide.done:
            for event in guide.on_sample(sample, status, now):
                self.on_startup(event)
            if guide.failed is not None:
                raise StartupFailed(guide.failed.step, guide.failed.data["reason"])
            if guide.done:
                self.frame = guide.frame
                self.ready_s = round(since_start(now), 3)
                self.detector.reset()
            if guide.blocking:
                return None  # no key events until the checks have finished
        elif self.monitor is not None:
            self.monitor.update(status, now)

        if self.frame is not None:
            vector = self.frame.to_controller(sample.accel, sample.quat)
        else:
            cfg = self.detector.config
            vector = orient(sample.accel, cfg.right_axis, cfg.up_axis)
        self.last_vector = vector
        gesture = self.detector.update(vector, now, oriented=True)
        if gesture is not None:
            self._emit(self.keys.press(gesture, now))
        return gesture

    def session_info(self) -> dict:
        """What this run was: mode, frame, startup results, tuning. For the session log."""
        guide = self.guide
        return {
            "session": {
                "fusion_mode": guide.mode if guide else "imu",
                "gravity_flag": bool(guide and guide.gravity),
                "gesture_frame": "world" if self.frame is not None else "fixed",
                "ready_s": self.ready_s,
            },
            "limits": asdict(guide.config) if guide else {},
            "startup": dict(guide.results) if guide else {},
            "mag_excursions": list(self.monitor.excursions) if self.monitor else [],
            "tuning": asdict(self.detector.config),
        }

    def tick(self, now: float) -> None:
        self._emit(self.keys.tick(now))

    def reset(self, now: float) -> None:
        """Start a new round: drop held key, clear cooldown, re-zero orientation."""
        self._emit(self.keys.release(now))
        self.detector.reset()
        if self.last_sample is not None:
            self.reference_quat = self.last_sample.quat

    def close(self, now: float) -> None:
        if self.monitor is not None:
            self.monitor.close(now)
        self._emit(self.keys.release(now))
        for sink in self.sinks:
            sink.close()

    def _emit(self, events) -> None:
        for event in events:
            for sink in self.sinks:
                sink.emit(event)


def build_pipeline(
    config: Config,
    sinks: Iterable[Sink] | None = None,
    on_startup: Callable[[StartupEvent], None] = log_event,
) -> Pipeline:
    """Also settles config.fusion_mode, so make_transport() must be called after this."""
    if sinks is None:
        sinks = [make_sink(name, config) for name in config.sinks]
    sinks = list(sinks)
    tuning = load(config.transport)
    for sink in sinks:
        # Only the WebSocket sink talks to the game, so only it has game settings to send
        configure_game = getattr(sink, "configure_game", None)
        if configure_game is not None:
            configure_game(tuning.game)
    gestures = config.gestures or tuning.gestures
    # Order of authority: --gravity, then tuning.toml, then IMU
    config.fusion_mode = "ndof" if config.gravity else (config.fusion_mode or tuning.fusion_mode)
    if config.gravity:
        log.info("ground-referenced gestures (--gravity): NDOF, [orientation] is not used")
    return Pipeline(
        GestureDetector(gestures),
        KeyState(config.key_hold_ms / 1000),
        sinks,
        guide=StartupGuide(
            config.fusion_mode, config.gravity, gestures.right.threshold, tuning.gravity
        ),
        on_startup=on_startup,
        monitor=FieldMonitor(tuning.gravity, since_start) if config.fusion_mode == "ndof" else None,
    )


async def run(
    transport,
    pipeline: Pipeline,
    clock: Callable[[], float] = default_clock,
    tracker=None,
) -> None:
    """Feed samples from the transport into the pipeline until cancelled.

    `tracker` is a latency.LatencyTracker, or None to record nothing.
    """

    async def ticker():
        # Runs even when no samples arrive, so a lost link cannot leave a key down
        while True:
            await asyncio.sleep(TICK_S)
            pipeline.tick(clock())

    for sink in pipeline.sinks:
        start = getattr(sink, "start", None)
        if start is not None:
            await start()
        if tracker is not None and hasattr(sink, "on_game_exit"):
            sink.on_game_exit = tracker.log_summary
    if tracker is not None:
        tracker.info_source = pipeline.session_info

    tick_task = asyncio.create_task(ticker())
    try:
        async for sample in transport.samples():
            consumed = clock()
            status = getattr(transport, "status", None)
            gesture = pipeline.on_sample(sample, consumed, status)
            if tracker is not None:
                tracker.record(sample, consumed, clock(), gesture, status, pipeline.last_vector)
    finally:
        tick_task.cancel()
        pipeline.close(clock())
        if tracker is not None:
            tracker.close()
