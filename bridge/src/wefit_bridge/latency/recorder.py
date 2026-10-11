"""Writes one fixed-size binary row per sample to logs/raw/ and keeps a rolling window
in memory for live stats.

Each session is two files: <stamp>_<transport>.bin (rows of metrics.RECORD) and a small
.json beside it (transport, link details, final summary).
"""

import json
import logging
import platform
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..events import KEYS
from ..protocol import SEQ_MODULO, T_MS_MODULO, Sample
from ..tuning import REPO_ROOT
from .metrics import RECORD, Summary, summarize

log = logging.getLogger(__name__)

LOG_DIR = REPO_ROOT / "logs"
RAW_DIR = LOG_DIR / "raw"  # git-ignored
REPORT_DIR = LOG_DIR / "reports"  # committed

SCHEMA = 1
FLUSH_ROWS = 256  # rows buffered between disk writes
LIVE_WINDOW_S = 30.0  # how far back live() looks
# A silence this long means the link was re-established, when the transport does not say
DEFAULT_EPOCH_GAP_S = 1.0


class LatencyTracker:
    def __init__(self, transport_name: str, transport=None, directory: Path = RAW_DIR):
        self.transport_name = transport_name
        self._transport = transport
        # Transports wait retry_delay_s before reconnecting, so a gap that long is a new run
        self._epoch_gap_s = getattr(transport, "retry_delay_s", DEFAULT_EPOCH_GAP_S)
        self._t0 = 0.0  # arrival of the first sample
        self._started = datetime.now(timezone.utc)

        directory.mkdir(parents=True, exist_ok=True)
        stem = f"{self._started:%Y%m%dT%H%M%SZ}_{transport_name}"
        self.path = directory / f"{stem}.bin"
        self._meta_path = directory / f"{stem}.json"
        self._file = open(self.path, "ab")
        self._buffer = np.zeros(FLUSH_ROWS, dtype=RECORD)
        self._buffered = 0
        self._recent: deque[tuple] = deque()

        self._last: Sample | None = None
        self._last_rx = 0.0
        self._epoch = self._n = self._dev_ms = 0
        self._write_meta()
        log.info("latency log: %s", self.path)

    def record(self, sample: Sample, consumed: float, done: float, gesture: str | None) -> None:
        """Log one sample. `consumed` and `done` are clock.now() around Pipeline.on_sample."""
        rx = sample.rx or consumed
        last = self._last
        if last is None:
            self._t0 = rx
            self._dev_ms = sample.t_ms
        elif rx - self._last_rx >= self._epoch_gap_s:
            # The board may have rebooted, so its seq and clock cannot be carried over
            self._epoch += 1
            self._n += 1
            self._dev_ms = sample.t_ms
        else:
            self._n += (sample.seq - last.seq) % SEQ_MODULO
            self._dev_ms += (sample.t_ms - last.t_ms) % T_MS_MODULO
        self._last, self._last_rx = sample, rx

        row = (
            self._epoch,
            self._n,
            self._dev_ms,
            round((rx - self._t0) * 1e6),
            round(max(consumed - rx, 0.0) * 1e6),
            round(max(done - rx, 0.0) * 1e6),
            KEYS.index(gesture) + 1 if gesture else 0,
        )
        self._buffer[self._buffered] = row
        self._buffered += 1
        if self._buffered == FLUSH_ROWS:
            self.flush()

        self._recent.append(row)
        oldest = row[3] - LIVE_WINDOW_S * 1e6
        while self._recent[0][3] < oldest:
            self._recent.popleft()

    def flush(self) -> None:
        self._buffer[: self._buffered].tofile(self._file)
        self._file.flush()
        self._buffered = 0

    def live(self) -> Summary:
        """Stats over the last LIVE_WINDOW_S. Cheap enough to call about once a second."""
        return self._summarize(np.array(list(self._recent), dtype=RECORD))

    def summary(self) -> Summary:
        """Stats over the whole session so far."""
        self.flush()
        return self._summarize(np.fromfile(self.path, dtype=RECORD))

    def log_summary(self) -> None:
        if self._file.closed:
            return  # close() already printed it
        log.info("%s\n  full report: python report.py", self.summary().brief())

    def close(self) -> None:
        if self._file.closed:
            return
        summary = self.summary()
        self._file.close()
        self._write_meta(summary)
        log.info("%s\n  full report: python report.py", summary.brief())

    def _summarize(self, records: np.ndarray) -> Summary:
        return summarize(
            records,
            self.transport_name,
            dropped=getattr(self._transport, "dropped", 0),
            corrupt=getattr(self._transport, "corrupt", 0),
        )

    def _write_meta(self, summary: Summary | None = None) -> None:
        info = getattr(self._transport, "info", None)
        meta = {
            "schema": SCHEMA,
            "transport": self.transport_name,
            "started_utc": self._started.isoformat(timespec="seconds"),
            "record_dtype": RECORD.descr,
            "link": {
                "port": getattr(self._transport, "port", None),
                "address": getattr(self._transport, "address", None),
            },
            "firmware": asdict(info) if is_dataclass(info) else None,
            "host": {"os": platform.platform(), "python": platform.python_version()},
            "summary": summary.to_dict() if summary else None,
        }
        self._meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")


@dataclass(slots=True)
class Session:
    path: Path
    meta: dict
    records: np.ndarray

    @property
    def transport(self) -> str:
        return self.meta["transport"]

    @property
    def name(self) -> str:
        return self.path.stem

    def summary(self) -> Summary:
        # Recomputed from the rows, so a session that was killed mid-run still reports
        saved = self.meta.get("summary") or {}
        return summarize(
            self.records, self.transport, saved.get("dropped", 0), saved.get("corrupt", 0)
        )


def load_session(path: str | Path) -> Session:
    """Load a session from its .bin or .json path."""
    path = Path(path).with_suffix(".bin")
    meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    dtype = np.dtype([tuple(field) for field in meta["record_dtype"]])
    return Session(path, meta, np.fromfile(path, dtype=dtype))


def latest_session(transport: str, directory: Path = RAW_DIR) -> Path | None:
    """The newest session recorded over this transport. File names start with a UTC stamp."""
    paths = sorted(directory.glob(f"*_{transport}.bin"))
    return paths[-1] if paths else None
