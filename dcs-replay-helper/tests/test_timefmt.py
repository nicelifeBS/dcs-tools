import pytest

from replay_helper.timefmt import fmt_model, fmt_speed, fmt_tod


@pytest.mark.parametrize("t,expected", [
    (None, "--:--.-"), (0, "0:00.0"), (67.95, "1:08.0"), (62.94, "1:02.9"), (3599.96, "1:00:00.0"),
    (3725.4, "1:02:05.4"), (-1.5, "-0:01.5"),
])
def test_fmt_model(t, expected):
    assert fmt_model(t) == expected


@pytest.mark.parametrize("s,expected", [(None, "--:--:--"), (59400, "16:30:00"), (59462.95, "16:31:02"),
                                        (86400 + 61, "00:01:01")])
def test_fmt_tod(s, expected):
    assert fmt_tod(s) == expected


@pytest.mark.parametrize("x,expected", [(None, "?"), (1, "1x"), (4.0, "4x"), (3.98, "4x"), (0.5, "0.5x"),
                                        (0.25, "0.25x"), (2.4, "2.4x")])
def test_fmt_speed(x, expected):
    assert fmt_speed(x) == expected


from replay_helper.timefmt import parse_clock, tod_to_model  # noqa: E402


@pytest.mark.parametrize("text,expected", [
    ("67.95", 67.95), ("1:07.95", 67.95), ("0:01:07.95", 67.95), ("16:31:07", 59467), (" 5 ", 5),
    ("1:00:00", 3600),
])
def test_parse_clock(text, expected):
    assert parse_clock(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", ":", "1::2", "a:10", "1:60", "1:2:3:4", "-5", "nan", "1:inf", "x"])
def test_parse_clock_rejects(text):
    with pytest.raises(ValueError):
        parse_clock(text)


def test_tod_to_model():
    assert tod_to_model(59467, 59400) == 67
    assert tod_to_model(100, 86000) == 500  # replay running past midnight
    assert tod_to_model(59000, 59400) == -400
