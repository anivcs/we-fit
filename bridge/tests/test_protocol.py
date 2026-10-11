import pytest

from wefit_bridge.protocol import (
    INFO,
    SAMPLE,
    Sample,
    decode_info,
    decode_sample,
    encode_sample,
    parse_sample_line,
)


def test_sizes_match_firmware_structs():
    assert SAMPLE.size == 20
    assert INFO.size == 5


def test_sample_round_trip():
    sample = Sample(
        seq=42,
        t_ms=1234,
        accel=(1.25, -2.5, 9.81),
        quat=(0.5, -0.5, 0.5, -0.5),
        calib=0b11_10_01_00,
        flags=0,
    )
    decoded = decode_sample(encode_sample(sample))
    assert decoded.seq == 42
    assert decoded.t_ms == 1234
    assert decoded.accel == pytest.approx(sample.accel, abs=0.01)
    assert decoded.quat == pytest.approx(sample.quat, abs=1e-4)
    assert decoded.calib == sample.calib


def test_wrong_length_rejected():
    with pytest.raises(ValueError):
        decode_sample(b"\x00" * 19)
    with pytest.raises(ValueError):
        decode_info(b"\x00" * 4)


def test_usb_line_parses_to_the_same_sample_as_ble():
    sample = decode_sample(SAMPLE.pack(7, 1000, 125, -250, 981, 16384, 0, 0, 0, 3, 0))
    line = "S,7,1000,125,-250,981,16384,0,0,0,3\r\n"
    assert parse_sample_line(line) == sample
    assert sample.accel == (1.25, -2.5, 9.81)


@pytest.mark.parametrize("line", ["", "BNO055 CONNECTED!", "S,1,2,3", "S,a,b,c,d,e,f,g,h,i,j"])
def test_non_sample_lines_are_ignored(line):
    assert parse_sample_line(line) is None


def test_info_decode():
    info = decode_info(INFO.pack(2, 7, 50))
    assert (info.protocol_version, info.fw_version, info.sample_rate_hz) == (2, 7, 50)
