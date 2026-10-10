"""Blocking facade for game scripts.

    from wefit_bridge import Controller

    with Controller() as controller:
        while running:
            for event in controller.poll():
                ...  # event.key in ("up", "down", "left", "right"), event.pressed
"""

import asyncio
import queue
import threading
import time

from .config import Config
from .events import KEYS, KeyEvent
from .pipeline import build_pipeline, run
from .transport import make_transport


class _QueueSink:
    def __init__(self):
        self.events: queue.SimpleQueue[KeyEvent] = queue.SimpleQueue()
        self._lock = threading.Lock()
        self._active: str | None = None

    def emit(self, event: KeyEvent) -> None:
        with self._lock:
            if event.pressed:
                self._active = event.key
            elif self._active == event.key:
                self._active = None
        self.events.put(event)

    def close(self) -> None:
        pass

    def state(self) -> dict[str, bool]:
        with self._lock:
            return {key: key == self._active for key in KEYS}


class Controller:
    """Runs the BLE pipeline on a background thread; the game loop only polls.

    `config.sinks` is ignored here: events are delivered through poll()/state().
    """

    def __init__(self, config: Config | None = None):
        self._config = config or Config()
        self._sink = _QueueSink()
        self._pipeline = build_pipeline(self._config, sinks=[self._sink])
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        ready = threading.Event()

        def runner():
            loop = asyncio.new_event_loop()
            self._loop = loop
            self._task = loop.create_task(run(make_transport(self._config), self._pipeline))
            ready.set()
            try:
                loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                pass
            finally:
                loop.close()

        self._thread = threading.Thread(target=runner, name="wefit-bridge", daemon=True)
        self._thread.start()
        ready.wait()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._task.cancel)
        self._thread.join(timeout=5)
        self._thread = None

    def poll(self) -> list[KeyEvent]:
        """Return key events since the last call, oldest first. Never blocks."""
        events = []
        while True:
            try:
                events.append(self._sink.events.get_nowait())
            except queue.Empty:
                return events

    def state(self) -> dict[str, bool]:
        """Current key state. At most one value is True."""
        return self._sink.state()

    def reset(self) -> None:
        """Call at the start of each round."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._pipeline.reset, time.monotonic())

    def __enter__(self) -> "Controller":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
