import asyncio
import dataclasses

import numpy as np
import pytest

from wefit_bridge.config import Config, load_config
from wefit_bridge.latency import HUD_FIELDS, METRICS, LatencyTracker, Summary, make_tracker
from wefit_bridge.latency.metrics import RECORD, clock_check, link_delay_ms, summarize
from wefit_bridge.latency.recorder import load_session
from wefit_bridge.pipeline import build_pipeline, run
from wefit_bridge.protocol import SEQ_MODULO, T_MS_MODULO, Sample
from wefit_bridge.transport.fake import FakeTransport

PERIOD_S = 0.02


def sample(seq, t_ms, rx):
    return Sample(
        seq=seq % SEQ_MODULO,
        t_ms=t_ms % T_MS_MODULO,
        accel=(0.0, 0.0, 0.0),
        quat=(1.0, 0.0, 0.0, 0.0),
        rx=rx,
    )


def stream(seconds=60.0, drift_ppm=0.0, delay_ms=None, seed=1):
    """Device times (ms) and host arrival times (us) for a steady controller."""
    count = int(seconds / PERIOD_S)
    host_s = np.arange(count) * PERIOD_S
    dev_ms = np.round(host_s * 1000 * (1 + drift_ppm / 1e6))
    if delay_ms is None:
        delay_ms = np.random.default_rng(seed).uniform(0, 10, count)
    return dev_ms, (host_s * 1000 + delay_ms) * 1000


def records_for(dev_ms, rx_us):
    records = np.zeros(len(dev_ms), dtype=RECORD)
    records["n"] = np.arange(len(dev_ms))
    records["dev_ms"] = dev_ms
    records["rx_us"] = rx_us
    return records


def test_delay_and_drift_are_recovered():
    dev_ms, rx_us = stream(drift_ppm=200.0)
    delay, drift = link_delay_ms(dev_ms, rx_us)
    assert drift == pytest.approx(200.0, abs=50.0)
    assert np.median(delay) == pytest.approx(5.0, abs=1.0)


def test_summary_percentiles():
    summary = summarize(records_for(*stream()), "usb")
    assert summary.latency_p50_ms == pytest.approx(5.0, abs=0.7)
    assert summary.latency_p99_ms == pytest.approx(9.9, abs=0.7)
    assert summary.latency_max_ms == pytest.approx(10.0, abs=0.7)
    assert summary.jitter_ms == pytest.approx(10 / 12**0.5, abs=0.3)
    assert summary.sample_rate_hz == pytest.approx(1 / PERIOD_S, abs=0.1)
    assert summary.loss_pct == 0


def test_too_few_samples_gives_an_empty_summary():
    assert summarize(np.zeros(1, dtype=RECORD), "usb").latency_p50_ms is None


def test_tracker_unwraps_counts_loss_and_survives_a_reconnect(tmp_path):
    tracker = LatencyTracker("usb", directory=tmp_path)
    start = SEQ_MODULO - 2
    # seq and t_ms both wrap here, and one sample (start + 3) never arrives
    for i in (0, 1, 2, 4):
        rx = 100.0 + i * PERIOD_S
        tracker.record(sample(start + i, start + i * 20, rx), rx, rx, None)
    # Five seconds of silence, then the board comes back counting from zero
    tracker.record(sample(0, 0, 105.0), 105.0, 105.0, "left")
    tracker.close()

    session = load_session(tracker.path)
    assert session.transport == "usb"
    assert session.path.stat().st_size == 5 * RECORD.itemsize
    assert list(session.records["n"][:4]) == [0, 1, 2, 4]
    assert list(np.diff(session.records["dev_ms"][:4].astype(int))) == [20, 20, 40]
    assert list(session.records["epoch"]) == [0, 0, 0, 0, 1]

    summary = session.summary()
    assert summary.loss_pct == pytest.approx(100 / 6)
    assert summary.interruptions == 1
    assert summary.gestures == 1


def test_clock_check_passes_across_a_timestamp_wrap():
    dev_ms, rx_us = stream(seconds=6.0, drift_ppm=50.0)
    samples = [sample(i, T_MS_MODULO - 1000 + int(d), r / 1e6) for i, (d, r) in enumerate(zip(dev_ms, rx_us))]
    result = clock_check(samples)
    assert result.ok, result.describe()
    assert result.spread_ms == pytest.approx(9.5, abs=1.5)


def test_clock_check_fails_for_a_clock_at_half_speed():
    dev_ms, rx_us = stream(seconds=6.0)
    samples = [sample(i, int(d / 2), r / 1e6) for i, (d, r) in enumerate(zip(dev_ms, rx_us))]
    assert not clock_check(samples).ok


def test_clock_check_needs_samples():
    result = clock_check([])
    assert not result.ok and result.drift_ppm is None


def test_fake_run_writes_a_log_and_live_stats(tmp_path):
    pipeline = build_pipeline(Config(transport="fake"), sinks=[])
    transport = FakeTransport(rate_hz=100, gesture_every_s=0.4, pulse_s=0.1)
    tracker = LatencyTracker("fake", transport, directory=tmp_path)
    live = []

    async def main():
        task = asyncio.create_task(run(transport, pipeline, tracker=tracker))
        await asyncio.sleep(1.5)
        live.append(tracker.live())
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())

    assert live[0].samples > 10
    session = load_session(tracker.path)
    assert session.meta["summary"]["transport"] == "fake"
    assert session.summary().gestures >= 1
    assert session.summary().latency_p50_ms is not None


def test_report_is_written(tmp_path):
    from wefit_bridge.latency.report import write_report

    tracker = LatencyTracker("fake", directory=tmp_path)
    dev_ms, rx_us = stream(seconds=30.0)
    for i, (d, r) in enumerate(zip(dev_ms, rx_us)):
        tracker.record(sample(i, int(d), r / 1e6), r / 1e6, r / 1e6, None)
    tracker.close()

    page = write_report([load_session(tracker.path)], tmp_path).read_text(encoding="utf-8")
    assert page.count("<svg") == 3
    assert all(metric.label in page for metric in METRICS.values())


def test_metric_table_and_hud_fields_match_the_summary():
    fields = {f.name for f in dataclasses.fields(Summary)}
    assert set(METRICS) <= fields
    assert set(HUD_FIELDS) <= set(METRICS)


def test_logging_is_on_by_default_and_can_be_turned_off(tmp_path):
    assert Config().latency_log
    assert make_tracker(Config(transport="fake", latency_log=False), None) is None

    path = tmp_path / "config.toml"
    path.write_text("[latency]\nenabled = false\n")
    assert not load_config(path).latency_log
