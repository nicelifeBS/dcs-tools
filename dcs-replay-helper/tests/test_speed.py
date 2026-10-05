from __future__ import annotations

import sys
import threading
from dataclasses import replace

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from conftest import load_fake_dcs, wait_until  # noqa: E402
from replay_helper.dcs.keys import KeyPressError, Step  # noqa: E402
from replay_helper.dcs.link import DcsLink  # noqa: E402
from replay_helper.dcs.protocol import State  # noqa: E402
from replay_helper.dcs.speed import AutoKeyBackend, SpeedController, is_ladder_speed, next_step  # noqa: E402

fake = load_fake_dcs()
U, D, N = Step.UP, Step.DOWN, Step.NORMAL


# --- pure logic ---------------------------------------------------------------------------
@pytest.mark.parametrize("accel,target,step", [
    (1, 1, None), (1, 4, U), (3, 4, U), (4, 2, N), (5, 1, N), (0.25, 2, N), (0.5, 1, N),
    (1, 0.25, D), (0.5, 0.25, D), (0.25, 0.5, U), (2, 0.5, N), (4, 4, None),
])
def test_next_step(accel, target, step) -> None:
    assert next_step(accel, target) is step


@pytest.mark.parametrize("x,ok", [(1, True), (4, True), (64, True), (0.5, True), (0.0625, True),
                                  (2.5, False), (0.3, False), (65, False), (0, False), (-1, False)])
def test_ladder(x, ok) -> None:
    assert is_ladder_speed(x) is ok


# --- controller against a simulated DCS ------------------------------------------------------
class FakeLink(QObject):
    stateChanged = Signal(object)

    def __init__(self, accel: float | None = 1.0) -> None:
        super().__init__()
        self.connected = True
        self.hook_version = "0.1.0"
        self.paused_calls = 0
        self.state = State(t=0, rt=0, speed=accel, accel=accel, paused=True, track=True, stop=None,
                           start_tod=59400, date=None, theatre=None)

    def push(self, **changes) -> None:
        self.state = replace(self.state, **changes)
        self.stateChanged.emit(self.state)

    def pause(self) -> None:
        self.paused_calls += 1
        self.push(paused=True)


class SimKeys:
    """DCS's reaction to the keys, with the speed ladder measured in the spike."""

    blocking = False

    def __init__(self, link: FakeLink, drop: int = 0, deaf: bool = False, error: str | None = None) -> None:
        self.link, self.drop, self.deaf, self.error = link, drop, deaf, error
        self.pressed: list[Step] = []

    def press(self, step: Step) -> None:
        if self.error:
            raise RuntimeError(self.error)
        self.pressed.append(step)
        if self.deaf or self.drop > 0:
            self.drop -= 1
            return
        a = self.link.state.accel
        a = {U: fake.accel_up, D: fake.accel_down, N: lambda _: 1.0}[step](a)
        self.link.push(accel=a)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(qapp):
    def make(accel: float | None = 1.0, **keys_kwargs):
        link = FakeLink(accel)
        keys = SimKeys(link, **keys_kwargs)
        clock = Clock()
        ctrl = SpeedController(link, keys, clock=clock, tick_ms=0)
        events: list[tuple[str, object]] = []
        ctrl.reached.connect(lambda x: events.append(("reached", x)))
        ctrl.failed.connect(lambda m: events.append(("failed", m)))
        ctrl.overspeed.connect(lambda x: events.append(("overspeed", x)))

        def drive(seconds: float = 10.0) -> None:
            """Let time pass: 10 STATE packets a second, as the hook sends them."""
            for _ in range(int(seconds * 10)):
                if not ctrl.busy:
                    return
                clock.now += 0.1
                link.push()
                ctrl.tick()

        return link, keys, ctrl, events, drive

    return make


@pytest.mark.parametrize("start,target,presses", [
    (1, 4, [U, U, U]),
    (4, 2, [N, U]),
    (1, 0.25, [D, D]),
    (0.25, 2, [N, U]),
    (3, 3, []),
])
def test_reaches_target(rig, start, target, presses) -> None:
    link, keys, ctrl, events, drive = rig(start)
    ctrl.set_target(target)
    drive()
    assert keys.pressed == presses
    assert link.state.accel == target
    assert events == [("reached", target)]
    assert not ctrl.busy


def test_retries_a_dropped_key(rig) -> None:
    link, keys, ctrl, events, drive = rig(drop=1)
    ctrl.set_target(2)
    drive()
    assert keys.pressed == [U, U]
    assert events == [("reached", 2.0)]


def test_gives_up_when_dcs_never_reacts(rig) -> None:
    link, keys, ctrl, events, drive = rig(deaf=True)
    ctrl.set_target(4)
    drive()
    assert keys.pressed == [U, U, U]
    assert events[0][0] == "failed" and "did not react to 3 speed steps" in events[0][1]
    assert not ctrl.busy and link.state.accel == 1


def test_reports_key_send_errors(rig) -> None:
    link, keys, ctrl, events, drive = rig(error="no window titled 'Digital Combat Simulator'")
    ctrl.set_target(2)
    drive()
    assert events == [("failed", "could not send the speed key: no window titled 'Digital Combat Simulator'")]


def test_fails_without_accel_report(rig) -> None:
    link, keys, ctrl, events, drive = rig(accel=None)
    ctrl.set_target(2)
    assert events[0][0] == "failed" and "does not report" in events[0][1]
    assert keys.pressed == []


def test_waits_while_disconnected(rig) -> None:
    link, keys, ctrl, events, drive = rig()
    link.connected = False
    ctrl.set_target(2)
    drive(1.0)
    assert keys.pressed == [] and ctrl.busy
    link.connected = True
    drive()
    assert events == [("reached", 2.0)]


def test_rejects_speeds_dcs_cannot_step_to(rig) -> None:
    link, keys, ctrl, events, drive = rig()
    for bad in (2.5, 0.3, 100):
        with pytest.raises(ValueError):
            ctrl.set_target(bad)
    assert not ctrl.busy


def test_new_target_while_busy(rig) -> None:
    link, keys, ctrl, events, drive = rig()
    ctrl.set_target(4)
    ctrl.set_target(2)
    drive()
    assert link.state.accel == 2
    assert events == [("reached", 2.0)]


def test_overspeed_pauses_and_steps_down(rig) -> None:
    link, keys, ctrl, events, drive = rig(accel=1)
    ctrl.max_speed = 4
    link.push(paused=False, accel=6, speed=1.0)  # someone pressed LCtrl+Z in DCS
    assert link.paused_calls == 1
    assert events[0] == ("overspeed", 6)
    drive()
    assert link.state.accel == 4
    assert keys.pressed == [N, U, U, U]


def test_overspeed_by_measurement(rig) -> None:
    link, keys, ctrl, events, drive = rig(accel=4)
    ctrl.max_speed = 4
    link.push(paused=False, speed=4.3)  # jitter: fine
    link.push(paused=False, speed=5.5)  # clearly too fast
    assert link.paused_calls == 1 and events[0] == ("overspeed", 5.5)


def test_blocking_backend_runs_in_a_worker_thread(qapp) -> None:
    link = FakeLink()
    threads = []

    class SlowKeys(SimKeys):
        blocking = True

        def press(self, step):
            threads.append(threading.current_thread().name)
            super().press(step)

    keys = SlowKeys(link)
    ctrl = SpeedController(link, keys, tick_ms=20)
    reached = []
    ctrl.reached.connect(reached.append)
    ctrl.set_target(3)
    assert wait_until(qapp, lambda: reached == [3.0])
    assert all(name.startswith("dcs-keys") for name in threads)
    ctrl.shutdown()


# --- end to end against tools/fake_dcs.py ----------------------------------------------------
def test_sets_speed_on_fake_dcs(qapp, fake_dcs_server) -> None:
    sim, state_port, cmd_port = fake_dcs_server(paused=True)
    link = DcsLink(state_port=state_port, cmd_port=cmd_port)
    assert link.start()
    assert wait_until(qapp, lambda: link.connected and link.hook_version)
    ctrl = SpeedController(link, AutoKeyBackend(link))
    reached = []
    ctrl.reached.connect(reached.append)
    ctrl.set_target(4)
    assert wait_until(qapp, lambda: reached == [4.0])
    assert sim.accel == 4 and link.state.paused  # set while paused: never ran above the target
    ctrl.set_target(1)
    assert wait_until(qapp, lambda: reached == [4.0, 1.0])
    ctrl.shutdown()
    link.stop()


# --- how a step reaches DCS ------------------------------------------------------------------
class SendLink:
    def __init__(self, version: str | None) -> None:
        self.hook_version = version
        self.sent: list[str] = []

    def send(self, line: str) -> None:
        self.sent.append(line)


@pytest.mark.parametrize("version", ["0.2.0", "fake-0.2.0"])
def test_steps_go_through_the_hook_when_it_takes_them(version) -> None:
    link = SendLink(version)
    backend = AutoKeyBackend(link)
    assert not backend.blocking  # no window focus, no worker thread
    backend.press(Step.DOWN)
    assert link.sent == ["SPEED DOWN"]
    assert "replay" in backend.hint


def test_older_hooks_get_keystrokes() -> None:
    link = SendLink("fake-0.1.0")
    backend = AutoKeyBackend(link)
    backend.press(Step.UP)
    assert link.sent == ["KEY UP"]  # an old fake DCS takes KEY
    link.hook_version = "0.1.0"
    assert backend.blocking and "Updating the DCS hook" in backend.hint
    if sys.platform != "win32":
        with pytest.raises(KeyPressError):
            backend.press(Step.UP)  # real keystrokes: Windows only
