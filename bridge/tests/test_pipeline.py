import asyncio

from wefit_bridge.config import Config
from wefit_bridge.pipeline import build_pipeline, run
from wefit_bridge.protocol import Sample
from wefit_bridge.transport.fake import FakeTransport


class ListSink:
    def __init__(self):
        self.events = []
        self.closed = False

    def emit(self, event):
        self.events.append(event)

    def close(self):
        self.closed = True


def sample(accel, quat=(1.0, 0.0, 0.0, 0.0)):
    return Sample(seq=0, t_ms=0, accel=accel, quat=quat)


def make():
    sink = ListSink()
    return build_pipeline(Config(), sinks=[sink]), sink


def test_gesture_becomes_press_then_release():
    pipeline, sink = make()
    pipeline.on_sample(sample((-8.0, 0.0, 0.0)), now=0.0)
    pipeline.tick(now=0.2)
    assert [(e.key, e.pressed) for e in sink.events] == [("left", True), ("left", False)]


def test_reset_releases_key_rearms_and_rezeros():
    pipeline, sink = make()
    quat = (0.0, 1.0, 0.0, 0.0)
    pipeline.on_sample(sample((8.0, 0.0, 0.0), quat), now=0.0)
    pipeline.reset(now=0.05)
    assert [(e.key, e.pressed) for e in sink.events] == [("right", True), ("right", False)]
    assert pipeline.reference_quat == quat

    pipeline.on_sample(sample((0.0, 0.0, 8.0)), now=0.1)
    assert (sink.events[-1].key, sink.events[-1].pressed) == ("up", True)


def test_close_releases_held_key():
    pipeline, sink = make()
    pipeline.on_sample(sample((0.0, 0.0, -8.0)), now=0.0)
    pipeline.close(now=0.01)
    assert (sink.events[-1].key, sink.events[-1].pressed) == ("down", False)
    assert sink.closed


def test_fake_controller_end_to_end():
    pipeline, sink = make()
    transport = FakeTransport(rate_hz=100, gesture_every_s=0.4, pulse_s=0.1)
    pipeline.detector.config.cooldown_s = 0.2
    pipeline.detector.config.rest_s = 0.1

    async def main():
        task = asyncio.create_task(run(transport, pipeline))
        await asyncio.sleep(2.3)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())

    presses = [e.key for e in sink.events if e.pressed]
    assert presses[:4] == ["up", "right", "down", "left"]
    # Every press is followed by its own release
    assert len(sink.events) % 2 == 0
    assert all(a.key == b.key and a.pressed and not b.pressed
               for a, b in zip(sink.events[::2], sink.events[1::2]))
