from __future__ import annotations

import pytest

from replay_helper.dcs import protocol
from replay_helper.dcs.protocol import Armed, Arrived, Disarmed, Error, Focused, FocusFailed, Hello, Pong, State

STATE = ("STATE t=62.950 rt=156.703 speed=3.998 accel=4.000 paused=false track=true stop=67.950 "
         "start_tod=59400.000 date=2018-02-01 theatre=Caucasus")


def test_state() -> None:
    s = protocol.parse(STATE)
    assert s == State(t=62.95, rt=156.703, speed=3.998, accel=4.0, paused=False, track=True,
                      stop=67.95, start_tod=59400.0, date="2018-02-01", theatre="Caucasus")
    assert s.mission_tod == pytest.approx(59462.95)


def test_state_unknowns() -> None:
    s = protocol.parse("STATE t=1 rt=2 speed=-1.000 accel=-1.000 paused=true track=false stop=-1.000 "
                       "start_tod=-1 date=- theatre=-")
    assert (s.speed, s.accel, s.stop, s.start_tod, s.date, s.theatre) == (None,) * 6
    assert s.paused and not s.track
    assert s.mission_tod is None


def test_state_ignores_unknown_fields_and_tolerates_missing_optional_ones() -> None:
    s = protocol.parse("STATE t=1 rt=2 future=yes")
    assert s.t == 1 and s.speed is None and s.paused is False


@pytest.mark.parametrize("line,expected", [
    ("HELLO 0.1.0", Hello("0.1.0")),
    ("PONG 0.1.0", Pong("0.1.0")),
    ("ARMED target=67.950 now=2.699", Armed(67.95, 2.699)),
    ("ARRIVED t=95.015 target=95.000 over=0.015", Arrived(95.015, 95.0, 0.015)),
    ("DISARMED reason=restart", Disarmed("restart")),
    ("FOCUSED id=16797696 steps=3", Focused(16797696, 3)),
    ("FOCUS-FAILED id=16797696 reason=cycled", FocusFailed(16797696, "cycled")),
    ("FOCUS-FAILED id=- reason=unavailable", FocusFailed(None, "unavailable")),
    ("ERR behind target=70.000 now=72.853", Error("behind target=70.000 now=72.853")),
])
def test_messages(line, expected) -> None:
    assert protocol.parse(line) == expected


@pytest.mark.parametrize("line", ["", "   ", "BOGUS 1", "STATE rt=2", "STATE t=x rt=2", "ARRIVED t=1",
                                  "ARMED target=1", "FOCUSED steps=1", "FOCUSED id=x"])
def test_rejects_malformed(line) -> None:
    assert protocol.parse(line) is None


def test_commands() -> None:
    assert protocol.cmd_armstop(62.95) == "ARMSTOP 62.950"
    assert [protocol.cmd_ping(), protocol.cmd_pause(), protocol.cmd_resume(), protocol.cmd_disarm()] == [
        "PING", "PAUSE", "RESUME", "DISARM"]


def test_speed_and_focus_commands() -> None:
    assert protocol.cmd_speed("UP") == "SPEED UP"
    assert protocol.cmd_focus(16797696, "A-10C #001") == "FOCUS 16797696 A-10C #001"
    assert protocol.cmd_focus(16797696, "  two\nlines  here ") == "FOCUS 16797696 two lines here"
    assert protocol.cmd_focus(16797696) == "FOCUS 16797696"
    assert protocol.cmd_focus() == "FOCUS"


@pytest.mark.parametrize("version,takes", [("0.2.0", True), ("0.10.0", True), ("1.0", True),
                                           ("0.1.0", False), ("fake-0.2.0", True), ("fake-0.1.0", False),
                                           (None, False), ("", False), ("spike-6", False)])
def test_which_hooks_take_actions(version, takes) -> None:
    assert protocol.hook_takes_actions(version) is takes
