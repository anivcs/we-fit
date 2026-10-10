import random

import pytest

from wefit_bridge.events import KEYS, KeyEvent
from wefit_bridge.keys import KeyState


def test_press_then_auto_release():
    keys = KeyState(hold_s=0.12)
    assert keys.press("left", 0.0) == [KeyEvent("left", True, 0.0)]
    assert keys.tick(0.05) == []
    assert keys.snapshot() == {"up": False, "down": False, "left": True, "right": False}
    assert keys.tick(0.12) == [KeyEvent("left", False, 0.12)]
    assert keys.active is None


def test_new_press_releases_the_old_key_first():
    keys = KeyState(hold_s=1.0)
    keys.press("left", 0.0)
    assert keys.press("up", 0.1) == [KeyEvent("left", False, 0.1), KeyEvent("up", True, 0.1)]


def test_release_when_idle_is_a_no_op():
    assert KeyState().release(0.0) == []


def test_unknown_key_rejected():
    with pytest.raises(ValueError):
        KeyState().press("jump", 0.0)


def test_never_more_than_one_key_down():
    rng = random.Random(0)
    keys = KeyState(hold_s=0.12)
    down: set[str] = set()
    now = 0.0
    for _ in range(5000):
        now += rng.uniform(0.0, 0.2)
        events = keys.press(rng.choice(KEYS), now) if rng.random() < 0.5 else keys.tick(now)
        for event in events:
            if event.pressed:
                down.add(event.key)
            else:
                down.remove(event.key)
            assert len(down) <= 1
