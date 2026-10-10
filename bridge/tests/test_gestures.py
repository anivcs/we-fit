import pytest

from wefit_bridge.gestures import GestureDetector

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


def test_reset_rearms_immediately():
    detector = GestureDetector()
    assert detector.update((5.0, 0.0, 0.0), now=0.0) == "right"
    detector.reset()
    assert detector.update((-5.0, 0.0, 0.0), now=0.1) == "left"
