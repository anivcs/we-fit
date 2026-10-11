"""Writes fixed-size binary rows per sample to logs/raw/ and keeps a rolling window in
memory for live stats. A session is one bridge run.

Each session is three files in logs/raw/: <stamp>_<transport>.bin (timing, rows of
metrics.RECORD), .imu.bin (sensor values, rows of metrics.IMU_RECORD, same row order)
and a small .json (transport, link, fusion mode, startup checks, tuning, summary).
Its gesture history goes to logs/runs/<stamp>_<transport>.jsonl, one line per gesture.

Times in the .json and .jsonl are seconds since the bridge started.
"""

import json
import logging
import platform
from collections import deque
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..clock import since_start
from ..events import KEYS
from ..gestures import AXIS
from ..protocol import ACCEL_SCALE, MAG_SCALE, QUAT_SCALE, SEQ_MODULO, T_MS_MODULO, Sample, Status
from ..tuning import REPO_ROOT
from .metrics import IMU_RECORD, RECORD, Summary, summarize

log = logging.getLogger(__name__)

LOG_DIR = REPO_ROOT / "logs"
RAW_DIR = LOG_DIR / "raw"  # git-ignored
RUNS_DIR = LOG_DIR / "runs"  # git-ignored: one gesture history per session
REPORT_DIR = LOG_DIR / "reports"  # committed
IMU_SUFFIX = ".imu.bin"
INT16 = (-32768, 32767)

SCHEMA = 1
FLUSH_ROWS = 256  # rows buffered between disk writes
LIVE_WINDOW_S = 30.0  # how far back live() looks
# A silence this long means the link was re-established, when the transport does not say
DEFAULT_EPOCH_GAP_S = 1.0


class LatencyTracker:
    def __init__(
        self,
        transport_name: str,
        transport=None,
        directory: Path = RAW_DIR,
        runs_directory: Path | None = None,
    ):
        self.transport_name = transport_name
        self._transport = transport
        # Set by pipeline.run(): returns the session's mode, startup results and tuning
        self.info_source = None
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
        self.imu_path = directory / f"{stem}{IMU_SUFFIX}"
        self._imu_file = open(self.imu_path, "ab")
        self._imu_buffer = np.zeros(FLUSH_ROWS, dtype=IMU_RECORD)
        if runs_directory is None:
            runs_directory = RUNS_DIR if directory == RAW_DIR else directory
        runs_directory.mkdir(parents=True, exist_ok=True)
        self.gestures_path = runs_directory / f"{stem}.jsonl"
        self._gestures_file = None  # opened at the first gesture, or at close
        self._t0_offset_s: float | None = None
        self._uptime_at_t0_s: float | None = None
        self._recent: deque[tuple] = deque()

        self._last: Sample | None = None
        self._last_rx = 0.0
        self._epoch = self._n = self._dev_ms = 0
        self._write_meta()
        log.info("latency log: %s", self.path)

    def record(
        self,
        sample: Sample,
        consumed: float,
        done: float,
        gesture: str | None,
        status: Status | None = None,
        vector: tuple[float, float, float] | None = None,
    ) -> None:
        """Log one sample. `consumed` and `done` are clock.now() around Pipeline.on_sample.

        `status` is the transport's latest status packet and `vector` the acceleration as
        (right, forward, up), as the gesture detector saw it.
        """
        rx = sample.rx or consumed
        last = self._last
        if last is None:
            self._t0 = rx
            self._t0_offset_s = since_start(rx)
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
        if status is not None and self._uptime_at_t0_s is None:
            # How long the board had been running when this session's first sample arrived
            self._uptime_at_t0_s = status.uptime_ms / 1000 - ((status.rx or rx) - self._t0)
        self._imu_buffer[self._buffered] = (
            np.clip(np.round(np.multiply(sample.accel, ACCEL_SCALE)), *INT16),
            np.clip(np.round(np.multiply(sample.quat, QUAT_SCALE)), *INT16),
            sample.calib,
            status.mode if status else 0,
            min(round(status.field_ut * MAG_SCALE), 0xFFFF) if status else 0,
        )
        if gesture:
            self._log_gesture(gesture, rx, vector)
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
        self._imu_buffer[: self._buffered].tofile(self._imu_file)
        self._imu_file.flush()
        self._buffered = 0

    def _log_gesture(self, gesture: str | None, rx: float, vector) -> None:
        """Append one line to the session's gesture history; the first line describes it."""
        if self._gestures_file is None:
            self._gestures_file = open(self.gestures_path, "a", encoding="utf-8")
            header = {"schema": SCHEMA, "transport": self.transport_name, **self._session()}
            self._gestures_file.write(json.dumps(header) + "\n")
        if gesture is not None:
            line = {"t_s": round(since_start(rx), 3), "key": gesture}
            if vector is not None:
                # Signed acceleration along the gesture's own axis when it fired
                line["trigger_ms2"] = round(vector[0 if AXIS[gesture] == "x" else 2], 2)
            self._gestures_file.write(json.dumps(line) + "\n")
        self._gestures_file.flush()

    def _session(self) -> dict:
        info = self.info_source() if self.info_source else {}
        return info.get("session", {})

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
        self._imu_file.close()
        self._log_gesture(None, 0.0, None)  # a session with no gestures still gets a file
        self._gestures_file.close()
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
            "imu_dtype": IMU_RECORD.descr,
            # Seconds from bridge start to the first sample, and the board's uptime then
            "t0_offset_s": self._t0_offset_s,
            "uptime_at_t0_s": self._uptime_at_t0_s,
            **(self.info_source() if self.info_source else {}),
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
    imu: np.ndarray | None = None  # rows of IMU_RECORD beside `records`; None for old logs

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
    records = np.fromfile(path, dtype=_dtype(meta["record_dtype"]))
    imu_path = path.with_name(path.stem + IMU_SUFFIX)
    imu = None
    if "imu_dtype" in meta and imu_path.is_file():
        imu = np.fromfile(imu_path, dtype=_dtype(meta["imu_dtype"]))
        # A killed run can leave one file a few rows ahead of the other
        rows = min(len(records), len(imu))
        records, imu = records[:rows], imu[:rows]
    return Session(path, meta, records, imu)


def _dtype(descr: list) -> np.dtype:
    """A dtype from its JSON form, where the shape of an array field became a list."""
    return np.dtype([tuple(tuple(v) if isinstance(v, list) else v for v in f) for f in descr])


def latest_session(transport: str, directory: Path = RAW_DIR) -> Path | None:
    """The newest session recorded over this transport. File names start with a UTC stamp."""
    paths = sorted(directory.glob(f"*_{transport}.bin"))
    return paths[-1] if paths else None
