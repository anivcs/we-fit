import pytest

from wefit_bridge.gestures import GestureConfig
from wefit_bridge.tuning import FILENAME, PROFILES, REPO_ROOT, TuningError, load_tuning

EXAMPLE = """
[orientation]
right = "-y"
up = "+x"

[usb]
rest_threshold = 0.8
up = { threshold = 6.0, rest_ms = 100, cooldown_ms = 400 }

[ble]
up = { threshold = 9.0, rest_ms = 250, cooldown_ms = 700 }
left = { threshold = 3.0 }
"""


def write(tmp_path, text):
    path = tmp_path / FILENAME
    path.write_text(text)
    return path


def test_usb_and_bluetooth_have_separate_profiles(tmp_path):
    path = write(tmp_path, EXAMPLE)
    usb = load_tuning("usb", path)
    ble = load_tuning("ble", path)
    assert (usb.up.threshold, usb.up.rest_s, usb.up.cooldown_s) == (6.0, 0.1, 0.4)
    assert (ble.up.threshold, ble.up.rest_s, ble.up.cooldown_s) == (9.0, 0.25, 0.7)
    assert (usb.rest_threshold, ble.rest_threshold) == (0.8, 1.0)
    # Orientation is shared
    assert (usb.right_axis, usb.up_axis) == (ble.right_axis, ble.up_axis) == ("-y", "+x")


def test_missing_settings_fall_back_to_the_defaults(tmp_path):
    ble = load_tuning("ble", write(tmp_path, EXAMPLE))
    defaults = GestureConfig()
    assert ble.left.threshold == 3.0
    assert ble.left.cooldown_s == defaults.left.cooldown_s
    assert ble.down == defaults.down
    assert load_tuning("usb", write(tmp_path, "")) == defaults


def test_fake_transport_ignores_the_file(tmp_path):
    assert load_tuning("fake", write(tmp_path, EXAMPLE)) == GestureConfig()


@pytest.mark.parametrize(
    "text, message",
    [
        ("[usb]\nup = { treshold = 6.0 }", "unknown setting treshold"),
        ("[usb]\nsideways = { threshold = 6.0 }", "unknown setting sideways"),
        ("[wifi]\n", "unknown setting wifi"),
        ("[usb]\nup = { threshold = 0 }", "greater than 0"),
        ("[usb]\nup = { cooldown_ms = -5 }", "0 or more"),
        ('[usb]\nup = { rest_ms = "150" }', "must be a number"),
        ('[orientation]\nright = "x"', "expected one of"),
        ('[orientation]\nright = "+z"', "different axes"),
        ("[usb\n", FILENAME),
    ],
)
def test_mistakes_are_reported_with_the_file_name(tmp_path, text, message):
    with pytest.raises(TuningError, match=message) as error:
        load_tuning("usb", write(tmp_path, text))
    assert FILENAME in str(error.value)


@pytest.mark.parametrize("transport", PROFILES)
def test_the_checked_in_tuning_file_is_valid(transport):
    load_tuning(transport, REPO_ROOT / FILENAME)
