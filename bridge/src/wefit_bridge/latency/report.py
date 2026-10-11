"""Static session report: one HTML file. Session and startup checks first, then
tuning, debug and latency.

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
from ..events import KEYS
from .metrics import METRICS, Analysis, Summary, analyse
from .motion import (
    BODY_MASS_KG,
    EXERCISE,
    KCAL_PER_GESTURE,
    NEAR_MISS_SHARE,
    Motion,
    analyse_motion,
    gesture_counts,
    kcal,
)
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
PEAK_BINS = 24
CALIB_NAMES = ("sys", "gyro", "accel", "mag")
STARTUP_STEPS = (
    ("mode", "Fusion mode check"),
    ("calibration", "Calibration at startup"),
    ("field", "Magnetic field at startup"),
    ("reference", "World reference"),
)
STATUS_TEXT = {"ok": "&#10003; OK", "warn": "&#9888; WARN", "fail": "&#10007; FAILED"}
DASH = "&ndash;"


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


def new_grid(title: str, rows: int, cols: int, height: float, **kwargs):
    """A figure of small multiples in the report's style. Returns (fig, 2-D array of axes)."""
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
    fig, axes = plt.subplots(rows, cols, figsize=(7.6, height), squeeze=False, **kwargs)
    fig.patch.set_facecolor(SURFACE)
    for ax in axes.flat:
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(colors=MUTED, length=0)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(AXIS)
    axes[0, 0].set_title(title, loc="left", color=INK, fontsize=11, fontweight="bold", pad=10)
    return fig, axes


def new_chart(title: str, xlabel: str, ylabel: str):
    fig, axes = new_grid(title, 1, 1, 3.1)
    ax = axes[0, 0]
    ax.set_xlabel(xlabel, color=INK_2)
    ax.set_ylabel(ylabel, color=INK_2)
    return fig, ax


def save(fig) -> str:
    import matplotlib.pyplot as plt

    out = io.StringIO()
    fig.savefig(out, format="svg", bbox_inches="tight", metadata={"Date": None})
    plt.close(fig)
    return out.getvalue()[out.getvalue().index("<svg") :]


def finish(fig, ax, series: int) -> str:
    if series > 1:  # one series is named by the page, so it needs no legend
        ax.legend(frameon=False, labelcolor=INK_2, loc="best")
    return save(fig)


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


# --- sensor charts ------------------------------------------------------------

TIME_LABEL = "time since the bridge started (s)"


def chart_peaks(motion: Motion, label: str, color: str) -> str:
    """One panel per direction: how hard each movement was, against its threshold."""
    fig, axes = new_grid(f"Movement strength by direction: {label}", 2, 2, 4.6)
    for ax, name in zip(axes.flat, KEYS):
        d = motion.directions[name]
        top = max([d.threshold, *d.fired, *d.missed]) * 1.15
        bins = np.linspace(NEAR_MISS_SHARE * d.threshold, top, PEAK_BINS + 1)
        ax.hist(d.fired, bins=bins, color=color, rwidth=0.85, label="fired")
        ax.hist(
            d.missed, bins=bins, histtype="step", color=INK_2, linewidth=1.5, label="did not fire"
        )
        ax.axvline(d.threshold, color=INK, linewidth=1, linestyle="--")
        ax.annotate(
            f"threshold {d.threshold:g}",
            (d.threshold, 1),
            xycoords=("data", "axes fraction"),
            xytext=(4, -10),
            textcoords="offset points",
            color=MUTED,
            fontsize=9,
        )
        ax.set_xlim(bins[0], bins[-1])
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.text(0, 1.02, f"{name} ({EXERCISE[name]})", transform=ax.transAxes, color=INK_2)
    for ax in axes[1]:
        ax.set_xlabel("peak acceleration (m/s²)", color=INK_2)
    for ax in axes[:, 0]:
        ax.set_ylabel("movements", color=INK_2)
    axes[0, 0].set_title(axes[0, 0].get_title(loc="left"), loc="left", color=INK, fontsize=11,
                         fontweight="bold", pad=22)
    fig.tight_layout()
    # Above the panels, so it can never sit on a bar
    fig.legend(*axes[0, 0].get_legend_handles_labels(), frameon=False, labelcolor=INK_2,
               loc="upper right", bbox_to_anchor=(0.98, 0.99), ncols=2)
    return save(fig)


def chart_calibration(motion: Motion, label: str, color: str) -> str:
    fig, axes = new_grid(f"Calibration level over time: {label}", 4, 1, 3.6, sharex=True)
    for ax, name, levels in zip(axes[:, 0], CALIB_NAMES, motion.calib.T):
        ax.step(motion.t_s, levels, where="post", color=color, linewidth=2)
        ax.set_ylim(-0.3, 3.3)
        ax.set_yticks([0, 3])
        ax.set_ylabel(name, color=INK_2, rotation=0, ha="right", va="center")
    axes[-1, 0].set_xlabel(TIME_LABEL, color=INK_2)
    axes[-1, 0].set_xlim(left=0)
    return save(fig)


def chart_series(
    title, ylabel, motions, labels, colors, x, y, band=None, zero=False, span=1.0
) -> str:
    """One line per session over time. `x` and `y` name Motion fields.

    `span` is the least the y axis shows, so a perfect flat line is not magnified into noise.
    """
    fig, ax = new_chart(title, TIME_LABEL, ylabel)
    for m, label, color in zip(motions, labels, colors):
        ax.plot(getattr(m, x), getattr(m, y), color=color, linewidth=2, label=label)
    if band is not None:
        ax.axhspan(*band, color=GRID, alpha=0.5, linewidth=0)
        ax.annotate("expected range", (0, band[1]), xycoords=("axes fraction", "data"),
                    xytext=(4, -11), textcoords="offset points", color=MUTED, fontsize=9)
    low, high = ax.get_ylim()
    if zero:
        ax.axhline(0, color=AXIS, linewidth=1)
        ax.set_ylim(min(low, -span), max(high, span))
    else:
        ax.set_ylim(0, max(high, span))
    ax.set_xlim(left=0)
    return finish(fig, ax, len(motions))


# --- page -------------------------------------------------------------------

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WeFit session report</title>
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
  small {{ color: {muted}; }}
  figcaption {{ color: {ink2}; font-size: 14px; margin-top: 6px; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; margin: 0; }}
  dt {{ font-weight: 600; }}
  dd {{ margin: 0; }}
  @media (max-width: 560px) {{ dl {{ grid-template-columns: 1fr; }} dd {{ margin-bottom: 8px; }} }}
</style>
</head>
<body>
<main>
<h1>WeFit controller session</h1>
<p class="sub">{sessions}</p>
<p>A session is one run of the bridge. Every time on this page is counted from the moment
the bridge started.</p>
{simulated}

<h2>Session</h2>
<div class="scroll">
<table>
<thead><tr><th></th>{head}</tr></thead>
<tbody>
{session_rows}
</tbody>
</table>
</div>
<p>Energy is a rough estimate (about &plusmn;50&nbsp;%) for a {mass}&nbsp;kg person: {kcal_note}.</p>

{sensor}

<h2>Latency</h2>
<p><strong>What is measured:</strong> the time from the ESP32 reading the motion sensor to the
bridge sending the key to the game. Browser rendering is not included yet.</p>
<p><strong>&ldquo;Above best case&rdquo;:</strong> the ESP32 and the PC have separate clocks, so
latency is measured relative to the fastest deliveries seen. The link's constant minimum
transit time is not in these numbers.</p>

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
{sensor_definitions}
{definitions}
</dl>
</main>
</body>
</html>
"""


SENSOR_DEFINITIONS = {
    "Fusion mode": "IMU: accelerometer + gyroscope. NDOF: the same plus the magnetometer, "
    "which holds the heading steady in a clean magnetic field.",
    "Gesture frame": "Fixed: the sensor axes named in tuning.toml [orientation]. World "
    "(--gravity): up from gravity, right from the startup shuffle.",
    "Calibration": "The sensor's own rating of each part, 0 (none) to 3 (full). "
    "sys is the overall rating and is meaningful in NDOF mode.",
    "Near miss": f"A movement that reached {NEAR_MISS_SHARE:.0%} of the threshold but did not "
    "fire: below the threshold, or blocked by the rest or cooldown delay.",
    "Rise time": "From the axis leaving rest to the threshold being crossed: the delay the "
    "threshold itself adds.",
    "Tilt error": "A still sensor should read zero acceleration once gravity is removed. "
    "What is left over shows how far the sensor's idea of 'up' has tilted.",
    "Heading drift": "How far the orientation turned about the vertical while the sensor "
    "was still. Hand tremor counts too; the cleanest reading is with the controller on a table.",
    "Magnetic field": "Strength at the sensor, NDOF mode only. Earth's field is 25 to 65 "
    "microtesla; much more means a magnet, speaker or battery bank nearby.",
}


def cell(value, digits: int = 1, unit: str = "") -> str:
    return DASH if value is None else f"{value:.{digits}f}{unit}"


def row(name: str, values: list[str]) -> str:
    return f"<tr><td>{name}</td>{''.join(f'<td>{v}</td>' for v in values)}</tr>"


def session_rows(sessions: list[Session], summaries: list[Summary]) -> str:
    metas = [s.meta for s in sessions]
    info = [m.get("session", {}) for m in metas]
    rows = [
        row("Connection", [TRANSPORT_LABEL.get(s.transport, s.transport) for s in sessions]),
        row("Fusion mode", [i.get("fusion_mode", "imu").upper() for i in info]),
        row(
            "Gesture frame",
            ["world (--gravity)" if i.get("gesture_frame") == "world" else "fixed" for i in info],
        ),
    ]
    for step, name in STARTUP_STEPS:
        values = []
        for meta in metas:
            result = meta.get("startup", {}).get(step)
            if result is None:
                values.append("not run")
                continue
            detail = html.escape(result["message"].split(": ", 1)[-1])
            detail = "" if detail == "OK" else f"<br><small>{detail}</small>"
            values.append(f"{STATUS_TEXT[result['status']]}{detail}")
        rows.append(row(name, values))
    rows.append(row("Duration", [f"{s.duration_s:.0f} s" for s in summaries]))
    counts = [gesture_counts(s) for s in sessions]
    for key in KEYS:
        rows.append(
            row(
                f"{key} ({EXERCISE[key]})",
                [
                    f"{c[key]}" + (f" &middot; {60 * c[key] / s.duration_s:.1f}/min" if s.duration_s else "")
                    for c, s in zip(counts, summaries)
                ],
            )
        )
    rows.append(row("Estimated energy", [f"{kcal(c):.1f} kcal" for c in counts]))
    return "\n".join(rows)


def sensor_part(sessions, motions, labels, colors) -> str:
    """The Tuning and Debug sections. Empty for sessions with no sensor log."""
    have = [(s, m, n, c) for s, m, n, c in zip(sessions, motions, labels, colors) if m is not None]
    if not have:
        return ""
    _, ms, names, cols = (list(v) for v in zip(*have))
    head = "".join(
        f'<th><span class="key" style="background:{c}"></span>{html.escape(n)}</th>'
        for n, c in zip(names, cols)
    )

    parts = ["<h2>Tuning</h2>",
             "<p>Compare each direction's movements with its threshold in tuning.toml. "
             "Thresholds are set per connection, so each connection has its own chart.</p>"]
    for m, name, color in zip(ms, names, cols):
        parts.append(
            f"<figure>{chart_peaks(m, name, color)}<figcaption>Filled bars fired a gesture; "
            "the outline did not. Outline to the right of the dashed line: real movements "
            "were blocked by the rest or cooldown delay. Outline just left of it: the "
            "threshold may be too high.</figcaption></figure>"
        )
        body = "\n".join(
            row(
                f"{key} ({EXERCISE[key]})",
                [
                    f"{d.threshold:g}",
                    str(len(d.fired)),
                    str(len(d.missed)),
                    cell(float(np.median(d.fired)) if len(d.fired) else None),
                    cell(float(np.median(d.rise_ms)) if len(d.rise_ms) else None, 0, " ms"),
                    cell(float(np.median(d.active_ms)) if len(d.active_ms) else None, 0, " ms"),
                ],
            )
            for key, d in m.directions.items()
        )
        parts.append(
            f'<div class="scroll"><table><thead><tr><th>{html.escape(name)}</th>'
            "<th>Threshold</th><th>Fired</th><th>Near misses</th>"
            "<th>Peak</th><th>Rise time</th><th>Duration</th>"
            f"</tr></thead><tbody>{body}</tbody></table></div>"
            "<p>Threshold and peak in m/s². Peak, rise time and duration are medians over "
            "the gestures that fired.</p>"
        )

    stats = [m.stats for m in ms]
    debug = [
        row("Lowest calibration (sys / gyro / accel / mag)",
            [" / ".join(str(s["calib_min"][n]) for n in CALIB_NAMES) for s in stats]),
        row("Magnetic field, median", [cell(s["field_median_ut"], 0, " µT") for s in stats]),
        row("Magnetic field outside limits", [cell(s["field_outside_pct"], 1, " %") for s in stats]),
        row("Magnetic excursions logged",
            [str(len(s.meta.get("mag_excursions", []))) for s, *_ in have]),
        row("Tilt error, p95", [cell(s["tilt_p95_deg"], 2, "°") for s in stats]),
        row("Heading drift while still", [cell(s["heading_rate_deg_min"], 2, " °/min") for s in stats]),
        row("Time spent still", [cell(s["still_pct"], 0, " %") for s in stats]),
        row("Board uptime when the session began",
            [cell(s.meta.get("uptime_at_t0_s"), 0, " s") for s, *_ in have]),
    ]
    parts += ["<h2>Debug</h2>",
              f'<div class="scroll"><table><thead><tr><th></th>{head}</tr></thead>'
              f"<tbody>{''.join(debug)}</tbody></table></div>"]
    for m, name, color in zip(ms, names, cols):
        parts.append(
            f"<figure>{chart_calibration(m, name, color)}<figcaption>3 is fully calibrated. "
            "A level that drops during play means the sensor lost confidence in that part."
            "</figcaption></figure>"
        )
    parts.append(
        "<figure>"
        + chart_series("Tilt error while still", "tilt error (degrees)", ms, names, cols,
                       "tilt_t_s", "tilt_deg")
        + "<figcaption>A rising line means the sensor's sense of 'up' is degrading, which "
        "leaks gravity into the gesture readings.</figcaption></figure>"
    )
    parts.append(
        "<figure>"
        + chart_series("Heading drift while still", "accumulated turn (degrees)", ms, names,
                       cols, "t_s", "heading_deg", zero=True)
        + "<figcaption>Flat is ideal. A steady slope is gyro drift; under --gravity, left and "
        "right start to fail as this approaches 45°.</figcaption></figure>"
    )
    with_field = [(m, n, c) for m, n, c in zip(ms, names, cols) if not np.isnan(m.field_ut).all()]
    if with_field:
        fm, fn, fc = (list(v) for v in zip(*with_field))
        parts.append(
            "<figure>"
            + chart_series("Magnetic field strength", "field strength (µT)", fm, fn, fc,
                           "t_s", "field_ut", band=fm[0].stats["field_limits"])
            + "<figcaption>Spikes above the band are magnets or electronics passing close to "
            "the sensor. They are logged and nothing reacts to them.</figcaption></figure>"
        )
    return "\n".join(parts)


def build(sessions: list[Session]) -> str:
    labels, colors = labels_for(sessions), colors_for(sessions)
    summaries = [s.summary() for s in sessions]
    analyses = [analyse(s.records) for s in sessions]
    motions = [analyse_motion(s) for s in sessions]

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
        session_rows=session_rows(sessions, summaries),
        mass=BODY_MASS_KG,
        kcal_note=", ".join(
            f"{EXERCISE[k]} {v:g} kcal" for k, v in KCAL_PER_GESTURE.items() if k != "left"
        ).replace("shuffle right", "side shuffle"),
        sensor=sensor_part(sessions, motions, labels, colors),
        sensor_definitions="\n".join(
            f"<dt>{name}</dt><dd>{html.escape(text)}</dd>"
            for name, text in SENSOR_DEFINITIONS.items()
        ),
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
