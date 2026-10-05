from __future__ import annotations

import pytest

pytest.importorskip("PySide6.QtCore")

from replay_helper.dcs.protocol import Arrived, Disarmed, Error  # noqa: E402
from replay_helper.seek import Phase, SeekController  # noqa: E402
from replay_helper.stops import BookmarkStops, Stop  # noqa: E402
from test_seek import Clock, FakeLink, FakeSpeed, go  # noqa: E402

BOOKMARKS = [(70.0, "merge"), (100.0, "splash"), (130.0, "egress")]


@pytest.fixture
def rig(qapp):
    def make(bookmarks=BOOKMARKS, preroll=5.0, **link_kwargs):
        link, speed = FakeLink(**link_kwargs), FakeSpeed()
        seek = SeekController(link, speed, clock=Clock(), tick_ms=0)
        stops = BookmarkStops(link, seek)
        reached: list[tuple[Stop, float]] = []
        stops.reached.connect(lambda stop, t: reached.append((stop, t)))
        stops.set_preroll(preroll)
        stops.set_bookmarks(bookmarks)
        link.push()  # the first STATE
        return link, speed, seek, stops, reached
    return make


def test_arms_before_the_next_bookmark_and_moves_on(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    assert stops.armed == Stop(65.0, 70.0, "merge") and link.calls == ["arm 65"]
    link.push(t=60.0)  # playing: nothing to change
    assert link.calls == ["arm 65"]

    link.say(Arrived(t=65.01, target=65.0, over=0.01))  # the hook paused there
    assert reached == [(Stop(65.0, 70.0, "merge"), 65.01)]
    assert stops.armed == Stop(95.0, 100.0, "splash") and link.calls[-1] == "arm 95"
    assert "pause" not in link.calls and "resume" not in link.calls  # Play is up to the user


def test_keeps_an_armed_stop_as_the_replay_closes_in(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    link.push(t=64.9)  # within the arming lead of 65, but the hook still has it
    assert stops.armed.t == 65.0 and link.calls == ["arm 65"]


def test_skips_bookmarks_whose_pre_roll_point_has_passed(rig) -> None:
    link, speed, seek, stops, reached = rig(t=66.0)  # 4 s before "merge": too late to stop 5 s before
    assert stops.armed.label == "splash"
    link.push(t=129.0)
    assert stops.armed is None and link.calls[-1] == "disarm"  # nothing left ahead


def test_zero_pre_roll_stops_at_the_bookmark(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0, preroll=0.0)
    assert stops.armed == Stop(70.0, 70.0, "merge")


def test_switching_off_and_on(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    stops.set_enabled(False)
    assert stops.armed is None and link.calls[-1] == "disarm"
    link.push(t=51.0)
    assert link.calls[-1] == "disarm"
    stops.set_enabled(True)
    assert link.calls[-1] == "arm 65"


def test_pre_roll_and_bookmark_changes_move_the_stop(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    stops.set_preroll(10.0)
    assert link.calls[-1] == "arm 60"
    stops.set_bookmarks([(80.0, "merge")])  # re-synced: every time shifts
    assert link.calls[-1] == "arm 70" and stops.armed == Stop(70.0, 80.0, "merge")
    stops.set_bookmarks([])
    assert stops.armed is None and link.calls[-1] == "disarm"


def test_leaves_the_stop_to_a_seek_and_skips_its_target(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    link.calls.clear()
    go(link, speed, seek, event=100.0)  # jump to "splash", past "merge"
    assert seek.phase is Phase.READY
    # Only the seek's own stop while it ran; then the bookmark after the target.
    assert [c for c in link.calls if c.startswith("arm")] == ["arm 95", "arm 125"]
    assert stops.armed == Stop(125.0, 130.0, "egress") and reached == []

    seek.play()
    assert link.calls[-1] == "resume" and stops.armed.label == "egress"


def test_a_seek_to_a_time_skips_bookmarks_before_it(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    go(link, speed, seek, event=72.0, preroll=5.0)  # paused at 67: "merge" at 70 is inside the pre-roll
    assert stops.armed.label == "splash"


def test_track_restart_brings_earlier_bookmarks_back(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    go(link, speed, seek, event=100.0)
    link.push(t=1.0, paused=False)  # the track started over
    assert stops.armed == Stop(65.0, 70.0, "merge")


def test_hook_dropping_or_refusing_the_stop(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    link.say(Disarmed("mission_end"))
    assert stops.armed is None
    link.push(t=50.1)
    assert stops.armed.label == "merge"
    link.say(Error("behind target=65.000 now=65.100"))  # passed while ARMSTOP was on its way
    assert stops.armed is None
    link.push(t=65.1)
    assert stops.armed.label == "splash"


def test_nothing_while_disconnected(rig) -> None:
    link, speed, seek, stops, reached = rig(t=50.0)
    link.connected = False
    link.connectedChanged.emit(False)
    assert stops.armed is None
    calls = list(link.calls)
    stops.set_preroll(2.0)
    assert link.calls == calls
