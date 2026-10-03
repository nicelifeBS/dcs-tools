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
