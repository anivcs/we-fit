import itertools
import math

import numpy as np
import pytest

from wefit_bridge.__main__ import README_SECTION, startup_failure_message
from wefit_bridge.config import Config
from wefit_bridge.latency import LatencyTracker
from wefit_bridge.latency.motion import analyse_motion
from wefit_bridge.latency.recorder import load_session
from wefit_bridge.pipeline import build_pipeline
from wefit_bridge.protocol import (
    MODES,
    STATUS,
    Sample,
    Status,
    command_line,
    decode_status,
    encode_status,
    parse_status_line,
)
from wefit_bridge.startup import FieldMonitor, StartupFailed, StartupGuide
from wefit_bridge.transport import make_transport
from wefit_bridge.tuning import FILENAME, TuningError, load
from wefit_bridge.world import GravityConfig, WorldFrame, conjugate, rotate

PERIOD_S = 0.02
CALIBRATED = 0xFF
HALF = math.sqrt(0.5)
IDENTITY = (1.0, 0.0, 0.0, 0.0)
COUNTER = itertools.count()
# Six ways to hold the controller: each is the sensor's orientation in the world
MOUNTINGS = [
    IDENTITY,
    (HALF, HALF, 0.0, 0.0),  # rolled 90 degrees
    (HALF, 0.0, HALF, 0.0),  # pitched 90 degrees
    (HALF, 0.0, 0.0, HALF),  # turned 90 degrees
    (0.0, 1.0, 0.0, 0.0),  # upside down
    (0.5, 0.5, 0.5, 0.5),  # all three axes swapped round
]
NDOF = Status(uptime_ms=5000, mag=(20.0, 0.0, -40.0), mode=MODES["ndof"])
IMU = Status(uptime_ms=5000, mag=(0.0, 0.0, 0.0), mode=MODES["imu"])


class ListSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        pass


def sample(world_accel=(0.0, 0.0, 0.0), mount=IDENTITY, calib=CALIBRATED):
    """A sample from a sensor held at `mount` while the player accelerates in the world."""
    n = next(COUNTER)
    return Sample(
        seq=n % 65536,
        t_ms=n * 20 % 65536,
        accel=rotate(conjugate(mount), world_accel),
        quat=mount,
        calib=calib,
    )


def feed(target, world_accel, seconds, now, mount=IDENTITY, status=NDOF, calib=CALIBRATED):
    """Feed a steady signal to a pipeline or a guide. Returns (events or gestures, new now)."""
    out = []
    for _ in range(round(seconds / PERIOD_S)):
        result = target.on_sample(sample(world_accel, mount, calib), status, now) if isinstance(
            target, StartupGuide
        ) else target.on_sample(sample(world_accel, mount, calib), now, status)
        out += result if isinstance(result, list) else [result] if result else []
        now += PERIOD_S
    return out, now


def start_gravity(mount=IDENTITY, right=(9.0, 0.0, 0.0)):
    """A --gravity pipeline taken through its startup, with the player shuffling `right`."""
    sink = ListSink()
    pipeline = build_pipeline(Config(transport="fake", gravity=True), sinks=[sink], on_startup=lambda e: None)
    _, now = feed(pipeline, (0.0, 0.0, 0.0), 4.0, 0.0, mount)  # mode, calibration, field, hold still
    _, now = feed(pipeline, right, 0.1, now, mount)
    _, now = feed(pipeline, (0.0, 0.0, 0.0), 1.0, now, mount)
    assert pipeline.guide.done and pipeline.frame is not None
    assert sink.events == []  # nothing reaches the game during startup
    return pipeline, sink, now


# --- world frame --------------------------------------------------------------


def test_rotation_follows_the_right_hand_rule():
    quarter_turn_about_up = (HALF, 0.0, 0.0, HALF)
    assert rotate(quarter_turn_about_up, (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0))
    assert rotate(IDENTITY, (1.0, 2.0, 3.0)) == pytest.approx((1.0, 2.0, 3.0))


def test_world_frame_gives_right_forward_up():
    frame = WorldFrame.from_horizontal(0.0, 5.0)  # the player's right is world +y
    assert frame.to_controller((0.0, 3.0, 0.0), IDENTITY) == pytest.approx((3.0, 0.0, 0.0))
    assert frame.to_controller((0.0, 0.0, 3.0), IDENTITY) == pytest.approx((0.0, 0.0, 3.0))
    assert frame.to_controller((-3.0, 0.0, 0.0), IDENTITY) == pytest.approx((0.0, 3.0, 0.0))


@pytest.mark.parametrize("mount", MOUNTINGS)
def test_the_same_motion_gives_the_same_gestures_in_any_mounting(mount):
    pipeline, sink, now = start_gravity(mount)
    moves = {"up": (0, 0, 9.0), "left": (-9.0, 0, 0), "down": (0, 0, -9.0), "right": (9.0, 0, 0)}
    for world_accel in moves.values():
        _, now = feed(pipeline, world_accel, 0.1, now, mount)
        _, now = feed(pipeline, (0.0, 0.0, 0.0), 1.0, now, mount)
    assert [e.key for e in sink.events if e.pressed] == list(moves)


def test_right_is_wherever_the_player_shuffled():
    # The player faces the other way: their right is world -x
    pipeline, sink, now = start_gravity(right=(-9.0, 0.0, 0.0))
    feed(pipeline, (-9.0, 0.0, 0.0), 0.1, now)
    assert [e.key for e in sink.events if e.pressed] == ["right"]


# --- startup ------------------------------------------------------------------


def test_imu_mode_skips_the_ndof_checks_and_never_blocks_gestures():
    sink = ListSink()
    events = []
    pipeline = build_pipeline(Config(transport="fake"), sinks=[sink], on_startup=events.append)
    assert not pipeline.guide.blocking
    gestures, _ = feed(pipeline, (-9.0, 0.0, 0.0), 0.04, 0.0, status=IMU, calib=0)
    assert gestures == ["left"]
    assert [e.step for e in events] == ["mode", "calibration"]
    assert pipeline.session_info()["session"]["fusion_mode"] == "imu"


def test_old_firmware_is_accepted_in_imu_mode_and_refused_in_ndof():
    guide = StartupGuide("imu")
    events, _ = feed(guide, (0, 0, 0), 4.0, 0.0, status=None)
    assert events[0].status == "warn" and "Re-flash" in events[0].message
    assert guide.done and guide.failed is None

    guide = StartupGuide("ndof")
    feed(guide, (0, 0, 0), 4.0, 0.0, status=None)
    assert guide.failed.step == "mode" and "Re-flash" in guide.failed.message


def test_ndof_prompts_for_calibration_then_reports_it():
    guide = StartupGuide("ndof")
    events, now = feed(guide, (0, 0, 0), 0.1, 0.0, calib=0b00_01_00_00)  # gyro 1
    assert events[-1].message == "Hold the controller still."
    events, now = feed(guide, (0, 0, 0), 0.1, now, calib=0b00_11_00_00)  # gyro 3, mag 0
    assert events[-1].message == "Draw a figure 8 in the air."
    events, now = feed(guide, (0, 0, 0), 0.1, now, calib=0b11_11_00_11)
    assert events[0].status == "ok" and events[0].data["mag"] == 3


def test_ndof_gives_up_waiting_for_calibration_and_continues():
    guide = StartupGuide("ndof")
    feed(guide, (0, 0, 0), 25.0, 0.0, calib=0)
    assert guide.results["calibration"]["status"] == "warn"
    assert guide.done and guide.failed is None


@pytest.mark.parametrize("ut, status", [(45.0, "ok"), (212.0, "warn"), (5.0, "warn")])
def test_field_check(ut, status):
    guide = StartupGuide("ndof")
    now = 0.0
    for _ in range(150):
        # A fresh Status object each time, as the transports produce
        guide.on_sample(sample(), Status(0, (ut, 0.0, 0.0), MODES["ndof"]), now)
        now += PERIOD_S
    assert guide.results["field"]["status"] == status
    assert guide.results["field"]["median_ut"] == pytest.approx(ut)


@pytest.mark.parametrize(
    "motion, reason",
    [
        ((0.0, 0.0, 0.0), "no sideways movement"),
        ((0.0, 0.0, 9.0), "mostly up or down"),
    ],
)
def test_reference_fails_without_a_sideways_movement(motion, reason):
    pipeline = build_pipeline(Config(transport="fake", gravity=True), sinks=[], on_startup=lambda e: None)
    _, now = feed(pipeline, (0.0, 0.0, 0.0), 4.0, 0.0)
    with pytest.raises(StartupFailed, match=reason) as error:
        for _ in range(8):
            _, now = feed(pipeline, motion, 0.1, now)
            _, now = feed(pipeline, (0.0, 0.0, 0.0), 2.0, now)
    assert error.value.step == "reference"


def test_reference_fails_if_the_controller_never_stays_still():
    guide = StartupGuide("ndof", gravity=True)
    feed(guide, (2.0, 0.0, 0.0), 15.0, 0.0)
    assert guide.failed.data["reason"] == "the controller never stayed still"


def test_failure_message_gives_the_command_without_gravity_and_points_to_the_readme():
    error = StartupFailed("reference", "no sideways movement within 10 s")
    message = startup_failure_message(error, ["--transport", "ble", "--gravity", "--sink", "websocket"])
    assert "initial world reference could not be set (no sideways movement within 10 s)" in message
    assert "  python -m wefit_bridge --transport ble --sink websocket\n" in message
    assert "--gravity" in message and "tuning.toml" in message and "otherwise IMU" in message
    assert README_SECTION in message


def test_the_readme_has_the_section_the_failure_message_names():
    from wefit_bridge.tuning import REPO_ROOT

    assert f"## {README_SECTION}" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


# --- which mode wins -----------------------------------------------------------


def test_gravity_flag_beats_tuning_which_beats_the_imu_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def mode(text=None, **settings):
        if text is not None:
            (tmp_path / FILENAME).write_text(text)
        config = Config(transport="usb", **settings)
        build_pipeline(config, sinks=[])
        return config.fusion_mode, make_transport(config).mode

    assert mode("") == ("imu", MODES["imu"])
    assert mode('fusion_mode = "ndof"') == ("ndof", MODES["ndof"])
    assert mode('fusion_mode = "imu"', gravity=True) == ("ndof", MODES["ndof"])


def test_tuning_file_fusion_mode_and_gravity_table(tmp_path):
    path = tmp_path / FILENAME
    path.write_text('fusion_mode = "ndof"\n[gravity]\nmag_max_ut = 120\n')
    tuning = load("usb", path)
    assert tuning.fusion_mode == "ndof"
    assert tuning.gravity.mag_max_ut == 120.0
    assert tuning.gravity.still_ms2 == GravityConfig().still_ms2

    for text, message in [
        ('fusion_mode = "compass"', "expected one of imu, ndof"),
        ("[gravity]\nmag_maximum = 1", "unknown setting mag_maximum"),
    ]:
        path.write_text(text)
        with pytest.raises(TuningError, match=message):
            load("usb", path)


# --- protocol v2 --------------------------------------------------------------


def test_status_packet_and_line_carry_the_same_values():
    assert STATUS.size == 11
    status = Status(uptime_ms=123456, mag=(20.5, -3.25, -40.0), mode=MODES["ndof"])
    assert decode_status(encode_status(status)) == status
    assert parse_status_line("T,123456,328,-52,-640,12\r\n") == status
    assert status.mode_name == "ndof"
    assert status.field_ut == pytest.approx(45.06, abs=0.01)
    assert parse_status_line("T,1,2") is None
    assert command_line(MODES["ndof"]) == b"M,12\n"


# --- field monitor and logs ----------------------------------------------------


def test_field_excursion_is_logged_once_with_its_peak(caplog):
    monitor = FieldMonitor(GravityConfig())
    for i, ut in enumerate([45, 45, 150, 300, 200, 45, 45]):
        monitor.update(Status(0, (float(ut), 0.0, 0.0), MODES["ndof"]), now=i * 0.2)
    assert monitor.excursions == [{"start_s": 0.4, "peak_ut": 300.0, "duration_s": 0.6}]
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 2  # start and end


def test_session_logs_sensor_rows_gesture_history_and_startup(tmp_path):
    import json

    pipeline, _, now = start_gravity()
    tracker = LatencyTracker("fake", directory=tmp_path)
    tracker.info_source = pipeline.session_info
    for world_accel, seconds in [((0, 0, 0), 1.0), ((0, 0, 9.0), 0.1), ((0, 0, 0), 1.0), ((5.0, 0, 0), 0.1), ((0, 0, 0), 1.0)]:
        for _ in range(round(seconds / PERIOD_S)):
            s = sample(world_accel)
            gesture = pipeline.on_sample(s, now, NDOF)
            tracker.record(s, now, now, gesture, NDOF, pipeline.last_vector)
            now += PERIOD_S
    tracker.close()

    lines = [json.loads(line) for line in tracker.gestures_path.read_text().splitlines()]
    assert lines[0]["gesture_frame"] == "world" and lines[0]["fusion_mode"] == "ndof"
    assert [(g["key"], g["trigger_ms2"]) for g in lines[1:]] == [("up", 9.0), ("right", 5.0)]

    session = load_session(tracker.path)
    assert len(session.imu) == len(session.records)
    assert session.meta["startup"]["reference"]["ok"] is True
    assert set(session.meta["startup"]) == {"mode", "calibration", "field", "reference"}

    motion = analyse_motion(session)
    assert list(motion.directions["up"].fired) == pytest.approx([9.0])
    assert list(motion.directions["right"].fired) == pytest.approx([5.0])
    assert len(motion.directions["left"].missed) == 0
    assert motion.stats["field_median_ut"] == pytest.approx(44.7, abs=0.1)
    assert motion.stats["tilt_p95_deg"] == pytest.approx(0.0, abs=0.01)
    assert motion.stats["heading_rate_deg_min"] == pytest.approx(0.0, abs=0.01)
    assert np.all(motion.calib == 3)


def test_a_movement_under_the_threshold_is_a_near_miss(tmp_path):
    pipeline = build_pipeline(Config(transport="fake"), sinks=[], on_startup=lambda e: None)
    tracker = LatencyTracker("fake", directory=tmp_path)
    tracker.info_source = pipeline.session_info
    now = 0.0
    for accel, seconds in [((0, 0, 0), 1.0), ((0.0, 0.0, 5.0), 0.1), ((0, 0, 0), 1.0)]:
        for _ in range(round(seconds / PERIOD_S)):
            s = sample(accel, calib=0)
            tracker.record(s, now, now, pipeline.on_sample(s, now, IMU), IMU, pipeline.last_vector)
            now += PERIOD_S
    tracker.close()
    up = analyse_motion(load_session(tracker.path)).directions["up"]
    assert (up.threshold, list(up.missed), len(up.fired)) == (7.0, [5.0], 0)
