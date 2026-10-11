"""Blocking facade for game scripts.

    from wefit_bridge import Controller

    with Controller() as controller:
        while running:
            for event in controller.poll():
                ...  # event.key in ("up", "down", "left", "right"), event.pressed
"""

import asyncio
import logging
import queue
import threading
from collections.abc import Callable

from .clock import now
from .config import Config
from .events import KEYS, KeyEvent
from .latency import make_tracker
from .pipeline import build_pipeline, run
from .startup import StartupEvent, StartupFailed, log_event
from .transport import make_transport

log = logging.getLogger(__name__)


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

    `on_startup` receives each StartupEvent (prompts such as "Shuffle RIGHT once" and
    the result of each check) so the game can show them. It is called on the bridge's
    thread. The default logs them to the terminal.
    """

    def __init__(
        self,
        config: Config | None = None,
        on_startup: Callable[[StartupEvent], None] = log_event,
    ):
        self._config = config or Config()
        self._sink = _QueueSink()
        self._pipeline = build_pipeline(self._config, sinks=[self._sink], on_startup=on_startup)
        # Set if a startup check stopped the bridge (see startup_done / startup_error)
        self.startup_error: StartupFailed | None = None
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
            transport = make_transport(self._config)
            tracker = make_tracker(self._config, transport)
            self._task = loop.create_task(run(transport, self._pipeline, tracker=tracker))
            ready.set()
            try:
                loop.run_until_complete(self._task)
            except asyncio.CancelledError:
                pass
            except StartupFailed as e:
                self.startup_error = e
                log.error("startup failed: %s", e.reason)
            finally:
                loop.close()

        self._thread = threading.Thread(target=runner, name="wefit-bridge", daemon=True)
        self._thread.start()
        ready.wait()

    def stop(self) -> None:
        if self._thread is None:
            return
        if not self._loop.is_closed():  # closed already if a startup check failed
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

    @property
    def startup_done(self) -> bool:
        """True once the startup checks have finished and gestures can arrive."""
        guide = self._pipeline.guide
        return guide is None or (guide.done and guide.failed is None)

    def reset(self) -> None:
        """Call at the start of each round."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._pipeline.reset, now())

    def __enter__(self) -> "Controller":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
