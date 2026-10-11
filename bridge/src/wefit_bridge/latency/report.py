"""Static latency report: one HTML file with a table and three charts.

    python report.py                 newest USB and newest Bluetooth session, side by side
    python report.py usb             newest session over one transport (usb, ble or fake)
    python report.py logs/raw/<file> a specific session; give several to compare them
"""

import html
import io
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from ..config import TRANSPORTS
from .metrics import METRICS, Analysis, Summary, analyse
from .recorder import RAW_DIR, REPORT_DIR, Session, latest_session, load_session

# Colour follows the transport, never the order sessions were given in
PALETTE = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
TRANSPORT_COLOR = dict(zip(TRANSPORTS, PALETTE))
TRANSPORT_LABEL = {"usb": "USB cable", "ble": "Bluetooth", "fake": "Simulated controller"}

INK, INK_2, MUTED, GRID, AXIS, SURFACE = (
    "#0b0b0b",
    "#52514e",
    "#898781",
    "#e1e0d9",
    "#c3c2b7",
    "#fcfcfb",
)

CDF_POINTS = 400  # points per curve; the eye cannot use more
BUCKET_S = 1.0  # the timeline shows the worst sample in each bucket
SPACING_BINS = 60

DECIMALS = {"ms": 1, "%": 2, "Hz": 1, "ppm": 0, "": 0}


def pick_sessions(args: list[str]) -> list[Session]:
    if not args:
        hardware = [t for t in TRANSPORTS if t != "fake"]
        paths = [latest_session(t) for t in hardware]
        if not any(paths):
            paths = [latest_session("fake")]
    else:
        paths = [latest_session(a) if a in TRANSPORTS else Path(a) for a in args]
    sessions = [load_session(p) for p in paths if p is not None]
    return [s for s in sessions if len(s.records) >= 2]


def labels_for(sessions: list[Session]) -> list[str]:
    names = [TRANSPORT_LABEL.get(s.transport, s.transport) for s in sessions]
    if len(set(names)) < len(names):
        # Two sessions over the same transport: tell them apart by start time
        names = [f"{n} {started(s):%H:%M:%S}" for n, s in zip(names, sessions)]
    return names


def colors_for(sessions: list[Session]) -> list[str]:
    if len({s.transport for s in sessions}) == len(sessions):
        return [TRANSPORT_COLOR[s.transport] for s in sessions]
    return list(PALETTE[: len(sessions)])


def started(session: Session) -> datetime:
    return datetime.fromisoformat(session.meta["started_utc"])


def fmt(value, unit: str) -> str:
    if value is None:
        return "&ndash;"
    digits = DECIMALS.get(unit, 1)
    value = round(value, digits) + 0.0  # + 0.0 turns -0.0 into 0.0
    sign = "+" if unit == "ppm" and value > 0 else ""
    return f"{sign}{value:.{digits}f} {unit}".strip()


# --- charts -----------------------------------------------------------------


def new_chart(title: str, xlabel: str, ylabel: str):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"],
            "font.size": 10,
            "svg.fonttype": "none",  # keep text as text: smaller files, sharp at any zoom
            "svg.hashsalt": "wefit",  # same data -> same file
        }
    )
    fig, ax = plt.subplots(figsize=(7.6, 3.1))
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold", pad=10)
    ax.set_xlabel(xlabel, color=INK_2)
    ax.set_ylabel(ylabel, color=INK_2)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    return fig, ax


def finish(fig, ax, series: int) -> str:
    import matplotlib.pyplot as plt

    if series > 1:  # one series is named by the page, so it needs no legend
        ax.legend(frameon=False, labelcolor=INK_2, loc="best")
    out = io.StringIO()
    fig.savefig(out, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)
    return out.getvalue()[out.getvalue().index("<svg") :]


def chart_distribution(analyses: list[Analysis], labels, colors) -> str:
    fig, ax = new_chart("How latency is distributed", "input latency (ms)", "% of samples at or below")
    share = np.linspace(0, 100, CDF_POINTS)
    for a, label, color in zip(analyses, labels, colors):
        ax.plot(np.percentile(a.latency_ms, share), share, color=color, linewidth=2, label=label)
    # A single spike would squash the curve, so the axis stops just past the slowest p99
    limit = max(np.percentile(a.latency_ms, 99) for a in analyses) * 1.3
    ax.set_xlim(0, max(limit, 1.0))
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 50, 75, 95])
    return finish(fig, ax, len(analyses))


def chart_timeline(analyses: list[Analysis], labels, colors) -> str:
    fig, ax = new_chart(
        "Latency over the session", "time since start (s)", f"worst latency per {BUCKET_S:g} s (ms)"
    )
    for a, label, color in zip(analyses, labels, colors):
        bucket = (a.t_s // BUCKET_S).astype(int)
        worst = np.zeros(bucket.max() + 1)
        np.maximum.at(worst, bucket, a.latency_ms)
        ax.plot(np.arange(len(worst)) * BUCKET_S, worst, color=color, linewidth=1.5, label=label)
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    return finish(fig, ax, len(analyses))


def chart_spacing(analyses: list[Analysis], summaries: list[Summary], labels, colors) -> str:
    fig, ax = new_chart(
        "How evenly samples arrive", "gap between consecutive samples (ms)", "% of samples"
    )
    periods = [1000 / s.sample_rate_hz for s in summaries if s.sample_rate_hz]
    period = float(np.median(periods)) if periods else float(np.median(analyses[0].interval_ms))
    bins = np.linspace(0, 3 * period, SPACING_BINS + 1)
    for a, label, color in zip(analyses, labels, colors):
        # Gaps past the axis are counted in the last bin instead of vanishing
        counts, _ = np.histogram(np.clip(a.interval_ms, 0, bins[-1]), bins=bins)
        ax.stairs(100 * counts / max(counts.sum(), 1), bins, color=color, linewidth=2, label=label)
    ax.axvline(period, color=AXIS, linewidth=1, linestyle="--")
    ax.annotate(
        f"sensor period {period:.0f} ms",
        (period, ax.get_ylim()[1]),
        xytext=(4, -10),
        textcoords="offset points",
        color=MUTED,
        fontsize=9,
    )
    ax.set_xlim(0, bins[-1])
    ax.set_ylim(bottom=0)
    return finish(fig, ax, len(analyses))


# --- page -------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WeFit latency report</title>
<style>
  body {{ margin: 0; background: #f9f9f7; color: {ink};
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ max-width: 780px; margin: 0 auto; padding: 32px 16px 48px; }}
  h1 {{ font-size: 24px; margin: 0 0 4px; }}
  h2 {{ font-size: 16px; margin: 36px 0 8px; }}
  p, li, dd {{ color: {ink2}; }}
  p {{ margin: 6px 0; }}
  .sub {{ color: {muted}; margin: 0 0 20px; }}
  .scroll {{ overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
  th, td {{ padding: 6px 12px 6px 0; border-bottom: 1px solid {grid}; text-align: right;
            white-space: nowrap; }}
  th:first-child, td:first-child {{ text-align: left; }}
  thead th {{ color: {ink2}; font-weight: 600; border-bottom-color: {axis}; }}
  .key {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px;
          margin-right: 6px; }}
  figure {{ margin: 20px 0 0; background: {surface}; border: 1px solid {grid};
            border-radius: 8px; padding: 12px; }}
  figure svg {{ width: 100%; height: auto; display: block; }}
  figcaption {{ color: {ink2}; font-size: 14px; margin-top: 6px; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }}
  dt {{ font-weight: 600; }}
  dd {{ margin: 0; }}
  @media (max-width: 560px) {{ dl {{ grid-template-columns: 1fr; }} dd {{ margin-bottom: 8px; }} }}
</style>
</head>
<body>
<main>
<h1>WeFit controller latency</h1>
<p class="sub">{sessions}</p>

<p><strong>What is measured:</strong> the time from the ESP32 reading the motion sensor to the
bridge sending the key to the game. Browser rendering is not included yet.</p>
<p><strong>&ldquo;Above best case&rdquo;:</strong> the ESP32 and the PC have separate clocks, so
latency is measured relative to the fastest deliveries seen. The link's constant minimum
transit time is not in these numbers.</p>
{simulated}

<h2>Summary</h2>
<div class="scroll">
<table>
<thead><tr><th></th>{head}</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>

<figure>{distribution}
<figcaption>Read across from 50, 95 or 99 to get the percentiles. A curve further left is a
faster link; a steeper curve is a more consistent one.</figcaption></figure>

<figure>{timeline}
<figcaption>Spikes are moments a player could feel. A rising trend means something is falling
behind.</figcaption></figure>

<figure>{spacing}
<figcaption>A single peak at the sensor period is ideal. Bluetooth delivers samples in bursts,
which shows as a peak near zero and another at a multiple of the period.</figcaption></figure>

<h2>Definitions</h2>
<dl>
{definitions}
</dl>
</main>
</body>
</html>
"""


def build(sessions: list[Session]) -> str:
    labels, colors = labels_for(sessions), colors_for(sessions)
    summaries = [s.summary() for s in sessions]
    analyses = [analyse(s.records) for s in sessions]

    head = "".join(
        f'<th><span class="key" style="background:{c}"></span>{html.escape(n)}</th>'
        for n, c in zip(labels, colors)
    )
    counts = [
        ("Duration", [f"{s.duration_s:.0f} s" for s in summaries]),
        ("Samples", [f"{s.samples:,}" for s in summaries]),
        ("Gestures", [f"{s.gestures:,}" for s in summaries]),
    ]
    measured = [
        (m.label, [fmt(getattr(s, field), m.unit) for s in summaries])
        for field, m in METRICS.items()
    ]
    rows = "\n".join(
        f"<tr><td>{name}</td>{''.join(f'<td>{v}</td>' for v in values)}</tr>"
        for name, values in counts + measured
    )
    simulated = (
        "<p><strong>Simulated:</strong> a session here came from the scripted controller, "
        "not hardware. Its numbers show the PC's own timing only.</p>"
        if any(s.transport == "fake" for s in sessions)
        else ""
    )
    return PAGE.format(
        ink=INK,
        ink2=INK_2,
        muted=MUTED,
        grid=GRID,
        axis=AXIS,
        surface=SURFACE,
        sessions=" &middot; ".join(
            f"{html.escape(n)}, {started(s):%Y-%m-%d %H:%M} UTC" for n, s in zip(labels, sessions)
        ),
        simulated=simulated,
        head=head,
        rows=rows,
        distribution=chart_distribution(analyses, labels, colors),
        timeline=chart_timeline(analyses, labels, colors),
        spacing=chart_spacing(analyses, summaries, labels, colors),
        definitions="\n".join(
            f"<dt>{m.label}</dt><dd>{html.escape(m.definition)}</dd>" for m in METRICS.values()
        ),
    )


def write_report(sessions: list[Session], directory: Path = REPORT_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    newest = max(sessions, key=started)
    transports = "-".join(dict.fromkeys(s.transport for s in sessions))
    path = directory / f"{started(newest):%Y%m%dT%H%M%SZ}_{transports}.html"
    path.write_text(build(sessions), encoding="utf-8")
    return path


def main(args: list[str] | None = None) -> int:
    args = sys.argv[1:] if args is None else args
    if any(a in ("-h", "--help") for a in args):
        print(__doc__)
        return 0
    try:
        sessions = pick_sessions(args)
    except OSError as e:
        print(f"Could not read that session: {e}")
        return 1
    if not sessions:
        print(
            f"No latency logs with samples in {RAW_DIR}. Run the bridge first, for example: "
            "python -m wefit_bridge --transport usb"
        )
        return 1
    print(f"Report written to {write_report(sessions)}")
    return 0
