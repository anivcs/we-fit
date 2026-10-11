import pytest

from wefit_bridge.gestures import DirectionConfig, GestureConfig, GestureDetector

REST = (0.0, 0.0, 0.0)


@pytest.mark.parametrize(
    "accel, expected",
    [
        ((0.0, 0.0, 8.0), "up"),
        ((0.0, 0.0, -5.0), "down"),
        ((5.0, 0.0, 0.0), "right"),
        ((-5.0, 0.0, 0.0), "left"),
    ],
)
def test_each_direction(accel, expected):
    assert GestureDetector().update(accel, now=0.0) == expected


def test_below_threshold_is_nothing():
    detector = GestureDetector()
    assert detector.update((3.9, 0.0, 0.0), now=0.0) is None
    assert detector.update((0.0, 0.0, 6.9), now=0.0) is None
    assert detector.update((0.0, 0.0, -3.9), now=0.0) is None


def test_y_dominant_is_nothing():
    assert GestureDetector().update((5.0, 9.0, 8.0), now=0.0) is None


def test_dominant_axis_wins_no_diagonals():
    assert GestureDetector().update((5.0, 0.0, 8.0), now=0.0) == "up"
    assert GestureDetector().update((-8.0, 0.0, 5.0), now=0.0) == "left"


def test_rebound_is_ignored_until_the_sensor_rests():
    detector = GestureDetector()
    assert detector.update((0.0, 0.0, 8.0), now=0.0) == "up"
    # Opposite spike as the motion stops, even after the cooldown has passed
    assert detector.update((0.0, 0.0, -8.0), now=0.6) is None
    # Still for 150 ms, then a real gesture
    assert detector.update(REST, now=0.7) is None
    assert detector.update(REST, now=0.9) is None
    assert detector.update((0.0, 0.0, -8.0), now=0.95) == "down"


def test_cooldown_blocks_even_after_rest():
    detector = GestureDetector()
    assert detector.update((5.0, 0.0, 0.0), now=0.0) == "right"
    assert detector.update(REST, now=0.05) is None
    assert detector.update(REST, now=0.25) is None
    assert detector.update((5.0, 0.0, 0.0), now=0.3) is None  # rested, but inside 500 ms
    assert detector.update((5.0, 0.0, 0.0), now=0.5) == "right"


@pytest.mark.parametrize(
    "first, second",
    [
        ((0.0, 0.0, 8.0), (5.0, 0.0, 0.0)),  # up then right
        ((0.0, 0.0, 8.0), (-5.0, 0.0, 0.0)),  # up then left
        ((5.0, 0.0, 0.0), (0.0, 0.0, 8.0)),  # right then up
        ((-5.0, 0.0, 0.0), (0.0, 0.0, -5.0)),  # left then down
    ],
)
def test_other_axis_is_not_delayed(first, second):
    detector = GestureDetector()
    assert detector.update(first, now=0.0) is not None
    # No cooldown and no rest needed for a gesture on the other axis
    assert detector.update(second, now=0.01) is not None


def test_same_direction_still_waits_for_cooldown_and_rest():
    detector = GestureDetector()
    assert detector.update((0.0, 0.0, 8.0), now=0.0) == "up"
    assert detector.update((0.0, 0.0, 8.0), now=0.2) is None
    assert detector.update(REST, now=0.3) is None
    assert detector.update(REST, now=0.5) is None
    assert detector.update((0.0, 0.0, 8.0), now=0.6) == "up"


def test_rebound_on_the_same_axis_is_still_blocked_after_a_gesture_on_the_other():
    detector = GestureDetector()
    assert detector.update((0.0, 0.0, 8.0), now=0.0) == "up"
    assert detector.update((5.0, 0.0, 0.0), now=0.02) == "right"
    # The z rebound from stopping the "up" has not rested yet
    assert detector.update((0.0, 0.0, -8.0), now=0.05) is None


def test_axis_stays_disarmed_while_it_keeps_moving():
    detector = GestureDetector()
    assert detector.update((0.0, 0.0, 8.0), now=0.0) == "up"
    # Z keeps moving while X sits still; X being at rest must not re-arm z
    for t in (0.1, 0.2, 0.3):
        assert detector.update((0.0, 0.0, 3.0), now=t) is None
    assert detector.update((0.0, 0.0, -8.0), now=0.4) is None


def test_jump_then_lane_change_in_quick_succession():
    detector = GestureDetector()
    samples = [
        (0.00, (0.0, 0.0, 8.0)),  # jump
        (0.03, (0.0, 0.0, 0.0)),
        (0.06, (5.0, 0.0, 0.0)),  # lane change while still in the air
        (0.09, (0.0, 0.0, 0.0)),
    ]
    got = [detector.update(accel, now=t) for t, accel in samples]
    assert got == ["up", None, "right", None]


def test_reset_rearms_immediately():
    detector = GestureDetector()
    assert detector.update((5.0, 0.0, 0.0), now=0.0) == "right"
    detector.reset()
    assert detector.update((-5.0, 0.0, 0.0), now=0.1) == "left"


def test_each_direction_has_its_own_threshold():
    config = GestureConfig(
        left=DirectionConfig(threshold=2.0), right=DirectionConfig(threshold=9.0)
    )
    assert GestureDetector(config).update((-3.0, 0.0, 0.0), now=0.0) == "left"
    assert GestureDetector(config).update((8.0, 0.0, 0.0), now=0.0) is None


def test_each_direction_has_its_own_cooldown():
    config = GestureConfig(
        left=DirectionConfig(cooldown_s=0.1, rest_s=0.0),
        right=DirectionConfig(cooldown_s=1.0, rest_s=0.0),
    )
    detector = GestureDetector(config)
    assert detector.update((-5.0, 0.0, 0.0), now=0.0) == "left"
    assert detector.update((5.0, 0.0, 0.0), now=0.0) == "right"
    assert detector.update((-5.0, 0.0, 0.0), now=0.2) == "left"
    assert detector.update((5.0, 0.0, 0.0), now=0.2) is None


def test_each_direction_has_its_own_rest_time():
    config = GestureConfig(down=DirectionConfig(rest_s=0.3), up=DirectionConfig(rest_s=0.05))
    detector = GestureDetector(config)
    assert detector.update((0.0, 0.0, 8.0), now=0.0) == "up"
    assert detector.update(REST, now=0.1) is None
    assert detector.update(REST, now=0.2) is None  # z has been still for 100 ms
    assert detector.update((0.0, 0.0, -8.0), now=0.25) is None  # down needs 300 ms
    assert detector.update(REST, now=0.3) is None
    assert detector.update(REST, now=0.7) is None
    assert detector.update((0.0, 0.0, -8.0), now=0.75) == "down"


@pytest.mark.parametrize(
    "right_axis, up_axis, accel, expected",
    [
        ("-x", "+z", (5.0, 0.0, 0.0), "left"),  # mounted mirrored
        ("+x", "-z", (0.0, 0.0, 8.0), "down"),  # mounted upside down
        ("+y", "+z", (0.0, 5.0, 0.0), "right"),  # rotated a quarter turn
        ("+z", "-x", (-8.0, 0.0, 0.0), "up"),  # on its side
        ("+z", "-x", (0.0, 0.0, -5.0), "left"),
    ],
)
def test_orientation_remaps_the_sensor_axes(right_axis, up_axis, accel, expected):
    config = GestureConfig(right_axis=right_axis, up_axis=up_axis)
    assert GestureDetector(config).update(accel, now=0.0) == expected


def test_leftover_axis_still_blocks_when_dominant():
    config = GestureConfig(right_axis="+y", up_axis="+z")
    # Sensor X is now the unused forward/back axis
    assert GestureDetector(config).update((9.0, 5.0, 0.0), now=0.0) is None


@pytest.mark.parametrize("right_axis, up_axis", [("+x", "-x"), ("x", "+z"), ("+x", "up")])
def test_bad_orientation_is_rejected(right_axis, up_axis):
    with pytest.raises(ValueError):
        GestureConfig(right_axis=right_axis, up_axis=up_axis)


def _queued(queue_s=0.6):
    d = DirectionConfig(rest_s=0.15, cooldown_s=0.5, queue_size=2, queue_s=queue_s)
    return GestureDetector(GestureConfig(down=d))


DOWN = (0.0, 0.0, -5.0)
BACK = (0.0, 0.0, 3.0)  # below the up threshold, above rest: the axis never rests


def test_rapid_repeats_are_queued_and_fire_after_the_cooldown():
    detector = _queued()
    assert detector.update(DOWN, now=0.0) == "down"
    assert detector.update(BACK, now=0.1) is None
    assert detector.update(DOWN, now=0.2) is None  # queued
    assert detector.update(BACK, now=0.3) is None
    assert detector.update(DOWN, now=0.4) is None  # queued
    assert detector.update(BACK, now=0.45) is None
    assert detector.update(BACK, now=0.5) == "down"  # first queued
    assert detector.update(BACK, now=1.0) == "down"  # second queued


def test_queue_is_bounded():
    detector = _queued(queue_s=2.0)
    assert detector.update(DOWN, now=0.0) == "down"
    for t in (0.1, 0.2, 0.3):
        detector.update(BACK, now=t - 0.05)
        assert detector.update(DOWN, now=t) is None
    assert detector.update(BACK, now=0.5) == "down"
    assert detector.update(BACK, now=1.0) == "down"
    assert detector.update(BACK, now=1.5) is None  # the third was over the limit


def test_stale_queued_repeat_is_dropped():
    detector = _queued()
    assert detector.update(DOWN, now=0.0) == "down"
    detector.update(BACK, now=0.1)
    assert detector.update(DOWN, now=0.2) is None  # queued
    assert detector.update(BACK, now=0.9) is None  # older than queue_s


def test_queue_off_keeps_the_old_behaviour():
    detector = GestureDetector()
    assert detector.update(DOWN, now=0.0) == "down"
    detector.update(BACK, now=0.1)
    assert detector.update(DOWN, now=0.2) is None
    assert detector.update(BACK, now=0.5) is None


def test_rebound_is_not_treated_as_a_repeat():
    detector = _queued()
    assert detector.update(DOWN, now=0.0) == "down"
    assert detector.update((0.0, 0.0, 8.0), now=0.1) is None  # opposite spike
    assert detector.update((0.0, 0.0, 0.0), now=0.6) is None


def test_other_direction_is_not_lost_when_a_queued_repeat_fires_in_the_same_sample():
    d = DirectionConfig(rest_s=0.15, cooldown_s=0.5, queue_size=2, queue_s=0.6)
    detector = GestureDetector(GestureConfig(down=d))  # left has no queue
    assert detector.update(DOWN, now=0.0) == "down"
    detector.update(BACK, now=0.1)
    assert detector.update(DOWN, now=0.2) is None  # queued
    detector.update(BACK, now=0.45)
    assert detector.update((-5.0, 0.0, 0.0), now=0.5) == "down"  # queued down wins the sample
    assert detector.update(REST, now=0.52) == "left"  # left fires on the next one
