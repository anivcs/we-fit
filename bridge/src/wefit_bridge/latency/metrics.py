"""Latency maths shared by the exit summary, the report and (later) an in-game HUD.

The ESP32 and the host do not share a clock, and nothing sets the ESP32's clock. The
host instead fits the mapping between the two from the samples themselves: the fastest
deliveries trace a straight line (offset + drift), and every sample's delay is measured
above that line. So "latency" here excludes the link's unknown best-case transit time.
"""

from dataclasses import asdict, dataclass

import numpy as np

from ..protocol import T_MS_MODULO, Sample

# One row per sample in logs/raw/*.bin
RECORD = np.dtype(
    [
        ("epoch", "<u2"),  # bumps each time the link is re-established
        ("n", "<u4"),  # sample index: seq unwrapped, so gaps are lost samples
        ("dev_ms", "<u4"),  # device clock when the sensor was read: t_ms unwrapped
        ("rx_us", "<u8"),  # host clock when the bytes arrived, since the first sample
        ("queue_us", "<u4"),  # arrival -> the pipeline picked the sample up
        ("done_us", "<u4"),  # arrival -> gesture decided and any key sent to the sinks
        ("key", "u1"),  # 0 = no gesture, else 1 + index into events.KEYS
    ]
)

# The link's best case is re-estimated once per window, which is what tracks clock drift
FLOOR_WINDOW_S = 10.0


@dataclass(frozen=True, slots=True)
class Metric:
    label: str
    unit: str
    definition: str


# Keyed by Summary field. The report prints these; a HUD can read the same table.
METRICS = {
    "latency_p50_ms": Metric(
        "Input latency, median", "ms", "Sensor read to key sent, for a typical sample."
    ),
    "latency_p95_ms": Metric("Input latency, p95", "ms", "19 in 20 samples are faster than this."),
    "latency_p99_ms": Metric("Input latency, p99", "ms", "99 in 100 samples are faster than this."),
    "latency_max_ms": Metric("Input latency, worst", "ms", "The slowest sample of the session."),
    "gesture_latency_p50_ms": Metric(
        "Gesture latency, median", "ms", "The same measure, only for samples that fired a gesture."
    ),
    "jitter_ms": Metric(
        "Jitter", "ms", "Standard deviation of input latency: how uneven the controller feels."
    ),
    "host_p50_ms": Metric(
        "Host share, median", "ms", "Arrival at the PC to key sent. The rest is the link."
    ),
    "loss_pct": Metric("Sample loss", "%", "Samples the controller sent that never arrived."),
    "longest_gap_ms": Metric(
        "Longest gap", "ms", "Longest stretch with no sample: the worst freeze."
    ),
    "sample_rate_hz": Metric(
        "Sample rate", "Hz", "How often the controller actually reads the sensor."
    ),
    "clock_drift_ppm": Metric(
        "Clock drift", "ppm", "ESP32 clock speed against the PC clock (+ = fast). Corrected for."
    ),
    "interruptions": Metric("Interruptions", "", "Times the link dropped and came back."),
}

# What an in-game HUD would show, in order
HUD_FIELDS = ("latency_p50_ms", "latency_p95_ms", "jitter_ms", "loss_pct")


@dataclass(slots=True)
class Summary:
    """Headline numbers for a set of records. None = not enough data."""

    transport: str = ""
    duration_s: float = 0.0
    samples: int = 0
    gestures: int = 0
    latency_p50_ms: float | None = None
    latency_p95_ms: float | None = None
    latency_p99_ms: float | None = None
    latency_max_ms: float | None = None
    gesture_latency_p50_ms: float | None = None
    jitter_ms: float | None = None
    host_p50_ms: float | None = None
    loss_pct: float | None = None
    longest_gap_ms: float | None = None
    sample_rate_hz: float | None = None
    clock_drift_ppm: float | None = None
    interruptions: int = 0
    dropped: int = 0  # discarded on the host because the consumer fell behind
    corrupt: int = 0  # arrived damaged

    def to_dict(self) -> dict:
        return asdict(self)

    def brief(self) -> str:
        """A few lines for the terminal."""
        if self.latency_p50_ms is None:
            return f"latency ({self.transport}): not enough samples"
        return "\n".join(
            [
                f"latency ({self.transport}, {self.duration_s:.0f} s, {self.samples} samples, "
                f"{self.gestures} gestures)",
                f"  input latency above the link's best case: p50 {self.latency_p50_ms:.1f} ms"
                f" | p95 {self.latency_p95_ms:.1f} | p99 {self.latency_p99_ms:.1f}"
                f" | worst {self.latency_max_ms:.1f}",
                f"  jitter {self.jitter_ms:.1f} ms | loss {self.loss_pct:.2f} %"
                f" | longest gap {self.longest_gap_ms:.0f} ms | {self.sample_rate_hz:.1f} Hz",
            ]
        )


def link_delay_ms(
    dev_ms, rx_us, window_s: float = FLOOR_WINDOW_S
) -> tuple[np.ndarray, float | None]:
    """Each sample's delay above the link's best case, and the device clock drift in ppm.

    Takes one unbroken run of samples. Drift is None when the run is too short to fit.
    """
    t = np.asarray(rx_us, dtype=float) / 1e6
    t -= t[0]
    dev = np.asarray(dev_ms, dtype=float)
    # Host elapsed minus device elapsed: a constant plus drift plus each sample's delay
    lag = t * 1000 - (dev - dev[0])

    starts = np.unique(np.searchsorted(t, np.arange(0.0, t[-1], window_s)))
    windows = np.split(np.arange(len(lag)), starts[1:])
    fastest = np.array([w[np.argmin(lag[w])] for w in windows])
    if len(fastest) >= 3:
        slope, intercept = np.polyfit(t[fastest], lag[fastest], 1)
        drift_ppm = float(-slope * 1000)  # lag falls when the device clock runs fast
    else:
        slope, intercept, drift_ppm = 0.0, 0.0, None
    delay = lag - (slope * t + intercept)
    return delay - delay.min(), drift_ppm


# Setup check (python check.py usb | bluetooth). Deliberately coarse: it catches a broken
# or missing device timestamp, not a few ppm of crystal error.
CLOCK_CHECK_WINDOWS = 5
CLOCK_DRIFT_LIMIT_PPM = 10_000.0  # 1 %
CLOCK_SPREAD_LIMIT_MS = 100.0


@dataclass(frozen=True, slots=True)
class ClockCheck:
    samples: int
    seconds: float
    drift_ppm: float | None  # ESP32 clock speed against the host clock, + = fast
    spread_ms: float  # p95 delay above the best case: how well one clock maps to the other

    @property
    def ok(self) -> bool:
        return (
            self.drift_ppm is not None
            and abs(self.drift_ppm) <= CLOCK_DRIFT_LIMIT_PPM
            and self.spread_ms <= CLOCK_SPREAD_LIMIT_MS
        )

    def describe(self) -> str:
        if self.drift_ppm is None:
            return f"too few samples to compare the clocks ({self.samples} in {self.seconds:.1f} s)"
        return (
            f"ESP32 clock runs {self.drift_ppm:+.0f} ppm against this PC, and maps onto the "
            f"PC clock to within {self.spread_ms:.1f} ms (p95), "
            f"from {self.samples} samples over {self.seconds:.1f} s"
        )


def clock_check(samples: list[Sample]) -> ClockCheck:
    """Compare the device clock with the host clock over a few seconds of samples."""
    rx_us = np.array([s.rx for s in samples]) * 1e6
    seconds = float(rx_us[-1] - rx_us[0]) / 1e6 if len(samples) else 0.0
    if len(samples) < 2 * CLOCK_CHECK_WINDOWS or seconds <= 0:
        return ClockCheck(len(samples), seconds, None, 0.0)
    dev_ms = np.unwrap([s.t_ms for s in samples], period=T_MS_MODULO)
    delay, drift = link_delay_ms(dev_ms, rx_us, window_s=seconds / CLOCK_CHECK_WINDOWS)
    return ClockCheck(len(samples), seconds, drift, float(np.percentile(delay, 95)))


@dataclass(slots=True)
class Analysis:
    """Per-sample series for one session, aligned with its records."""

    t_s: np.ndarray  # arrival time since the first sample
    latency_ms: np.ndarray  # sensor read -> key sent, above the link's best case
    interval_ms: np.ndarray  # spacing between consecutive arrivals (one shorter)
    drift_ppm: float | None
    lost: int


def analyse(records: np.ndarray) -> Analysis:
    latency = np.zeros(len(records))
    drift, longest, lost = None, 0, 0
    for epoch in np.unique(records["epoch"]):
        run = records["epoch"] == epoch
        rows = records[run]
        if len(rows) < 2:
            continue
        delay, run_drift = link_delay_ms(rows["dev_ms"], rows["rx_us"])
        latency[run] = delay + rows["done_us"] / 1000
        lost += int(rows["n"][-1]) - int(rows["n"][0]) + 1 - len(rows)
        if len(rows) > longest:
            longest, drift = len(rows), run_drift
    rx = records["rx_us"].astype(float)
    return Analysis(
        t_s=(rx - rx[0]) / 1e6 if len(rx) else rx,
        latency_ms=latency,
        interval_ms=np.diff(rx) / 1000,
        drift_ppm=drift,
        lost=lost,
    )


def summarize(
    records: np.ndarray, transport: str = "", dropped: int = 0, corrupt: int = 0
) -> Summary:
    summary = Summary(transport=transport, samples=len(records), dropped=dropped, corrupt=corrupt)
    if len(records) < 2:
        return summary
    a = analyse(records)
    fired = records["key"] > 0
    p50, p95, p99 = np.percentile(a.latency_ms, (50, 95, 99))

    # Rate from the device's own clock, over the unbroken runs only
    same_run = np.diff(records["epoch"]) == 0
    dev_ms = np.diff(records["dev_ms"].astype(float))[same_run].sum()
    sent = np.diff(records["n"].astype(float))[same_run].sum()

    summary.duration_s = float(a.t_s[-1])
    summary.gestures = int(fired.sum())
    summary.latency_p50_ms = float(p50)
    summary.latency_p95_ms = float(p95)
    summary.latency_p99_ms = float(p99)
    summary.latency_max_ms = float(a.latency_ms.max())
    if fired.any():
        summary.gesture_latency_p50_ms = float(np.median(a.latency_ms[fired]))
    summary.jitter_ms = float(a.latency_ms.std())
    summary.host_p50_ms = float(np.median(records["done_us"])) / 1000
    summary.loss_pct = 100 * a.lost / (len(records) + a.lost)
    summary.longest_gap_ms = float(a.interval_ms.max())
    summary.sample_rate_hz = float(1000 * sent / dev_ms) if dev_ms else None
    summary.clock_drift_ppm = a.drift_ppm
    summary.interruptions = int(records["epoch"][-1]) - int(records["epoch"][0])
    return summary
