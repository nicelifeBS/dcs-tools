from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from conftest import wait_until  # noqa: E402
from replay_helper.dcs.link import DcsLink  # noqa: E402
from replay_helper.dcs.protocol import Armed, Arrived, Disarmed, Error, State  # noqa: E402
from replay_helper.dcs.speed import AutoKeyBackend, SpeedController  # noqa: E402
from replay_helper.seek import Phase, SeekController, SeekError  # noqa: E402


# --- unit: scripted link and speed controller ----------------------------------------------
class FakeLink(QObject):
    stateChanged = Signal(object)
    message = Signal(object)
    connectedChanged = Signal(bool)

    def __init__(self, t: float = 50.0, paused: bool = False) -> None:
        super().__init__()
        self.connected = True
        self.calls: list[str] = []
        self.state = State(t=t, rt=0, speed=1, accel=1, paused=paused, track=True, stop=None,
                           start_tod=59400, date=None, theatre=None)

    def model_time_now(self) -> float:
        return self.state.t

    def push(self, **changes) -> None:
        self.state = replace(self.state, **changes)
        self.stateChanged.emit(self.state)

    def say(self, msg) -> None:
        self.message.emit(msg)

    def pause(self) -> None:
        self.calls.append("pause")

    def resume(self) -> None:
        self.calls.append("resume")

    def arm_stop(self, t: float) -> None:
        self.calls.append(f"arm {t:g}")

    def disarm(self) -> None:
        self.calls.append("disarm")


class FakeSpeed(QObject):
    reached = Signal(float)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.busy = False
        self.targets: list[float] = []

    def set_target(self, x: float) -> None:
        self.targets.append(x)
        self.busy = True

    def finish(self) -> None:
        self.busy = False
        self.reached.emit(self.targets[-1])

    def cancel(self) -> None:
        self.busy = False


class Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(qapp):
    def make(**link_kwargs):
        link, speed, clock = FakeLink(**link_kwargs), FakeSpeed(), Clock()
        seek = SeekController(link, speed, clock=clock, tick_ms=0)
        events: list[tuple] = []
        seek.ready.connect(lambda e, s: events.append(("ready", e, s)))
        seek.segmentDone.connect(lambda t: events.append(("done", t)))
        seek.failed.connect(lambda m: events.append(("failed", m)))
        return link, speed, clock, seek, events
    return make


def go(link, speed, seek, *, event=70.0, preroll=5.0, postroll=0.0):
    """Drive a seek from a running replay up to READY."""
    seek.seek(event, preroll=preroll, postroll=postroll, seek_speed=4, playback_speed=1)
    link.push(paused=True)              # DCS confirms the pause
    speed.finish()                      # at 4x
    link.say(Armed(target=event - preroll, now=link.state.t))
    link.push(paused=False)             # running
    link.say(Arrived(t=event - preroll + 0.01, target=event - preroll, over=0.01))
    link.push(paused=True, t=event - preroll + 0.01)
    speed.finish()                      # back to playback speed


def test_full_seek_and_post_roll(rig) -> None:
    link, speed, clock, seek, events = rig()
    seek.seek(70, preroll=5, postroll=3, seek_speed=4, playback_speed=1)
    assert seek.phase is Phase.PAUSING and link.calls == ["pause"]
    link.push(paused=True)
    assert seek.phase is Phase.SPEEDING and speed.targets == [4]
    speed.finish()
    assert seek.phase is Phase.ARMING and link.calls[-1] == "arm 65"
    link.say(Armed(target=65, now=50))
    assert seek.phase is Phase.RUNNING and link.calls[-1] == "resume"
    link.push(paused=True)               # a stale STATE from before the resume: ignored
    assert seek.phase is Phase.RUNNING
    link.push(paused=False)
    link.say(Arrived(t=65.01, target=65, over=0.01))
    assert seek.phase is Phase.SLOWING and speed.targets == [4, 1]
    speed.finish()
    assert seek.phase is Phase.READY and events == [("ready", 70, 65)]

    seek.play()
    assert seek.phase is Phase.SEGMENT_ARMING and link.calls[-1] == "arm 73"
    link.say(Armed(target=73, now=65.01))
    assert seek.phase is Phase.SEGMENT and link.calls[-1] == "resume"
    link.push(paused=False)
    link.say(Arrived(t=73.02, target=73, over=0.02))
    assert seek.phase is Phase.IDLE and events[-1] == ("done", 73.02)


def test_skips_pausing_when_already_paused(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    assert seek.phase is Phase.SPEEDING and "pause" not in link.calls


def test_play_without_post_roll_just_resumes(rig) -> None:
    link, speed, clock, seek, events = rig()
    go(link, speed, seek)
    seek.play()
    assert seek.phase is Phase.IDLE and link.calls[-1] == "resume"


@pytest.mark.parametrize("event,preroll", [(40, 0), (54, 5), (50.1, 0)])
def test_refuses_targets_behind_the_playhead(rig, event, preroll) -> None:
    link, speed, clock, seek, events = rig()
    with pytest.raises(SeekError, match="only run forward"):
        seek.seek(event, preroll=preroll)
    assert seek.phase is Phase.IDLE and link.calls == []


def test_refuses_when_disconnected_or_negative(rig) -> None:
    link, speed, clock, seek, events = rig()
    with pytest.raises(SeekError, match="pre-roll and post-roll"):
        seek.seek(70, preroll=-1)
    link.connected = False
    with pytest.raises(SeekError, match="not connected"):
        seek.seek(70)


def test_replay_passes_preroll_point_while_pausing(rig) -> None:
    link, speed, clock, seek, events = rig()
    seek.seek(70, preroll=5)
    link.push(paused=True, t=66)
    assert events[0][0] == "failed" and "while pausing" in events[0][1]


def test_dcs_refuses_stop_as_behind(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    speed.finish()
    link.say(Error("behind target=65.000 now=66.000"))
    assert events == [("failed", "the replay is already past the target")]
    assert seek.phase is Phase.IDLE


def test_user_pause_mid_seek_fails_and_disarms(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    speed.finish()
    link.say(Armed(target=65, now=50))
    link.push(paused=False)
    link.push(paused=True)               # paused, but no ARRIVED
    assert events == [("failed", "the replay was paused before reaching the target")]
    assert "disarm" in link.calls


def test_track_restart_mid_seek(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    speed.finish()
    link.say(Armed(target=65, now=50))
    link.say(Disarmed("restart"))
    assert events == [("failed", "seek stopped: the track restarted")]


def test_lost_connection_mid_seek(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    link.connectedChanged.emit(False)
    assert events == [("failed", "lost the connection to DCS")]
    assert not speed.busy


def test_pause_not_confirmed_times_out(rig) -> None:
    link, speed, clock, seek, events = rig()
    seek.seek(70, preroll=5)
    clock.now = 2.0
    seek.tick()
    assert events == []
    clock.now = 3.5
    seek.tick()
    assert events == [("failed", "DCS did not pause in time")]


def test_speed_failure_ends_seek(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    speed.failed.emit("DCS did not react to 3 speed keys (UP)")
    assert events == [("failed", "could not set the speed: DCS did not react to 3 speed keys (UP)")]


def test_cancel_mid_seek(rig) -> None:
    link, speed, clock, seek, events = rig(paused=True)
    seek.seek(70, preroll=5, seek_speed=4)
    speed.finish()
    link.say(Armed(target=65, now=50))
    seek.cancel()
    assert link.calls[-2:] == ["disarm", "pause"]
    assert seek.phase is Phase.IDLE and events == []


def test_new_seek_replaces_ready(rig) -> None:
    link, speed, clock, seek, events = rig()
    go(link, speed, seek)
    seek.seek(90, preroll=5, seek_speed=4)
    assert seek.phase is Phase.SPEEDING and seek.stop_t == 85


# --- end to end against tools/fake_dcs.py, running 10x faster than real time ------------------
def test_seek_on_fake_dcs(qapp, fake_dcs_server) -> None:
    sim, state_port, cmd_port = fake_dcs_server(start=50.0, time_scale=10)
    link = DcsLink(state_port=state_port, cmd_port=cmd_port)
    assert link.start()
    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    speed = SpeedController(link, AutoKeyBackend(link))
    speed.max_speed = 4
    seek = SeekController(link, speed)
    ready, done, failed = [], [], []
    seek.ready.connect(lambda e, s: ready.append((e, s)))
    seek.segmentDone.connect(done.append)
    seek.failed.connect(failed.append)

    seek.seek(120.0, preroll=5.0, postroll=3.0, seek_speed=4, playback_speed=1)
    assert wait_until(qapp, lambda: ready or failed, timeout=10), "seek did not finish"
    assert not failed, failed
    # The fake's frame length depends on thread scheduling (x10 here), so allow a hiccup.
    assert sim.paused and 115.0 <= sim.t < 115.5
    assert sim.accel == 1  # playback speed set while paused
    assert sim.max_running_accel == 4  # never above the seek speed

    seek.play()
    assert wait_until(qapp, lambda: done or failed, timeout=10)
    assert not failed, failed
    assert sim.paused and 123.0 <= sim.t < 123.5
    speed.shutdown()
    link.stop()
