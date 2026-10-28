from __future__ import annotations

import math
from dataclasses import replace

import pytest

pytest.importorskip("PySide6.QtCore")

from PySide6.QtCore import QObject, Signal  # noqa: E402

from replay_helper.dcs import camera  # noqa: E402
from replay_helper.dcs.camera import Action, CameraMatcher, plan  # noqa: E402
from replay_helper.dcs.protocol import State  # noqa: E402


# --- the inputs as measured in DCS (SPIKE.md round 8) ----------------------------------------
def apply(cam: float, action: Action) -> float:
    """What DCS does with an input: keys are x1.1 / /1.1 (5 m/s from rest, never across zero), the
    wheel adds 1.13 m/s per notch (positive: forward) and crosses zero."""
    if action.kind == "faster":
        for _ in range(action.count):
            cam = camera.KEY_FIRST if cam < 0.5 else cam * 1.1
    elif action.kind == "slower":
        for _ in range(action.count):
            cam = cam / 1.1 if cam > 0 else cam
    else:
        cam += action.count * 1.13
    return cam


# --- plan ----------------------------------------------------------------------------------
@pytest.mark.parametrize("start", [0.0, 3.0, 40.0, 250.0, -15.0, -150.0])
@pytest.mark.parametrize("target", [0.0, 0.4, 2.0, 7.0, 45.0, 200.0, 310.0, -3.0, -40.0, -180.0])
def test_plan_converges(start, target) -> None:
    cam, rounds = start, 0
    while (action := plan(target, cam)) is not None:
        cam = apply(cam, action)
        rounds += 1
        assert rounds <= 30, f"{start} -> {target} stuck at {cam:.2f}"
    assert abs(cam - target) <= camera.TOLERANCE


def test_plan_picks_the_coarse_input_first_and_the_fine_one_last() -> None:
    assert plan(100, 100.5) is None
    assert plan(100, 80) == Action("faster", round(math.log(100 / 80) / math.log(1.1)))
    assert plan(50, 60) == Action("slower", round(math.log(60 / 50) / math.log(1.1)))
    assert plan(100, 97) == Action("wheel", 3)  # within 3 m/s: the wheel is finer
    assert plan(100, 103.4) == Action("wheel", -3)


def test_plan_from_rest() -> None:
    assert plan(200, 0) == Action("faster", 1)  # the first press gives 5 m/s
    assert plan(4, 0) == Action("wheel", 4)  # too small for a key press


def test_plan_goes_backward_with_the_wheel_only() -> None:
    assert plan(-40, -10) == Action("wheel", -27)
    assert plan(-40, 3) == Action("wheel", -38)
    assert plan(-40, 60) == Action("slower", 28)  # keys first, as far as they go
    assert plan(30, -100) == Action("wheel", camera.MAX_NOTCHES)  # then forward again


def test_plan_limits_a_round() -> None:
    assert plan(10000, 50).count == camera.MAX_KEYS
    assert plan(10000, 50, max_keys=8) == Action("faster", 8)
    assert plan(-40, 60, max_keys=5) == Action("slower", 5)
    assert plan(-1000, -5).count == -camera.MAX_NOTCHES


# --- Windows input ---------------------------------------------------------------------------
def test_camera_key_events() -> None:
    assert camera.camera_key_events(True) == [(0x38, False, False), (0x37, False, False),
                                              (0x37, True, False), (0x38, True, False)]
    divide = camera.camera_key_events(False)  # Num/ is an extended key
    assert divide[1] == (0x35, False, True) and divide[2] == (0x35, True, True)


def test_wheel_data() -> None:
    assert camera.wheel_data(1) == 120
    assert camera.wheel_data(-1) == 0xFFFFFF88


# --- the controller against a simulated camera -------------------------------------------------
class FakeLink(QObject):
    stateChanged = Signal(object)

    def __init__(self, paused: bool = False, accel: float = 1.0) -> None:
        super().__init__()
        self.connected = True
        self.reports_objects = True
        self.calls: list[str] = []
        self.state = State(t=0, rt=0, speed=accel, accel=accel, paused=paused, track=True, stop=None,
                           start_tod=None, date=None, theatre=None, cam=0.0)
        self.target: float | None = 200.0  # the watched object's tgt_along
        self.watched: int | None = None
        self.side = 0.0

    def watch(self, dcs_id) -> None:
        self.calls.append(f"watch {dcs_id}")
        self.watched = dcs_id

    def resume(self) -> None:
        self.calls.append("resume")
        self.state = replace(self.state, paused=False)

    def pause(self) -> None:
        self.calls.append("pause")
        self.state = replace(self.state, paused=True)

    def push(self, **changes) -> None:
        extra = {}
        if self.watched is not None:
            extra = {"tgt": self.watched, "tgt_along": self.target, "tgt_side": self.side}
        self.state = replace(self.state, **changes, **extra)
        self.stateChanged.emit(self.state)


class FakeSpeed(QObject):
    reached = Signal(float)
    failed = Signal(str)

    def __init__(self, link: FakeLink) -> None:
        super().__init__()
        self.link, self.targets, self.cancelled = link, [], False

    def set_target(self, speed: float) -> None:
        self.targets.append(speed)
        self.link.state = replace(self.link.state, accel=speed)
        self.reached.emit(speed)

    def cancel(self) -> None:
        self.cancelled = True


class SimInput:
    blocking = False

    def __init__(self, link: FakeLink, ignore: int = 0, error: str | None = None) -> None:
        self.link, self.ignore, self.error = link, ignore, error
        self.actions: list[Action] = []

    def _do(self, action: Action) -> None:
        if self.error:
            raise RuntimeError(self.error)
        self.actions.append(action)
        if self.link.state.paused:
            return  # DCS ignores the inputs while the replay is paused
        if self.ignore > 0:
            self.ignore -= 1
            return
        self.link.state = replace(self.link.state, cam=apply(self.link.state.cam, action))

    def faster(self, n: int) -> None:
        self._do(Action("faster", n))

    def slower(self, n: int) -> None:
        self._do(Action("slower", n))

    def wheel(self, n: int) -> None:
        self._do(Action("wheel", n))


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def rig(qapp):
    def make(paused: bool = False, accel: float = 1.0, with_speed: bool = True, **input_kwargs):
        link = FakeLink(paused, accel)
        speed = FakeSpeed(link) if with_speed else None
        inp = SimInput(link, **input_kwargs)
        clock = Clock()
        matcher = CameraMatcher(link, speed, inp, clock=clock)
        events: list[tuple[str, str]] = []
        matcher.matched.connect(lambda m: events.append(("matched", m)))
        matcher.failed.connect(lambda m: events.append(("failed", m)))
        matcher.progress.connect(lambda m: events.append(("progress", m)))

        def drive(seconds: float = 120.0) -> None:
            """10 STATE packets a second."""
            for _ in range(int(seconds * 10)):
                if not matcher.busy:
                    return
                clock.now += 0.1
                link.push()

        return link, speed, inp, matcher, events, drive

    return make


def outcome(events) -> list[str]:
    return [kind for kind, _ in events if kind != "progress"]


@pytest.mark.parametrize("target,start", [(200.0, 0.0), (45.0, 120.0), (-180.0, 0.0), (80.0, -20.0)])
def test_matches_the_object(rig, target, start) -> None:
    link, speed, inp, matcher, events, drive = rig()
    link.target = target
    link.state = replace(link.state, cam=start)
    matcher.start(42, "Viper 1-1")
    assert link.watched == 42
    drive()
    assert outcome(events) == ["matched"]
    assert abs(link.state.cam - target) <= camera.TOLERANCE
    assert link.calls[-1] == "watch None"  # watching stops
    assert "Viper 1-1" in events[-1][1] and not matcher.busy
    assert not any(c in link.calls for c in ("pause", "resume"))  # it was playing: left playing


def test_waits_for_the_camera_to_settle_before_judging(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    clock = matcher._clock
    link.state = replace(link.state, cam=190.0)
    matcher.start(1)
    for i in range(40):  # still ramping (190, 198, 190, ...): nothing is sent for the first 4 s
        clock.now += 0.1
        link.push(cam=190.0 + 8.0 * (i % 2))
    assert inp.actions == []
    for i in range(30):  # ... but it does not wait for ever
        clock.now += 0.1
        link.push(cam=190.0 + 8.0 * (i % 2))
    assert inp.actions != []


def test_judges_as_soon_as_the_camera_is_steady(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    clock = matcher._clock
    link.state = replace(link.state, cam=190.0)
    matcher.start(1)
    for _ in range(10):  # steady from the start: acts after the half second
        clock.now += 0.1
        link.push(cam=190.0)
    assert inp.actions != []


def test_from_a_pause_runs_slowly_and_pauses_again(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(paused=True, accel=2.0)
    matcher.start(7, "Hokum")
    assert speed.targets == [camera.SLOW_SPEED]
    assert link.calls[:2] == ["watch 7", "resume"]
    drive()
    assert outcome(events) == ["matched"]
    assert link.state.paused
    assert link.calls[-2:] == ["watch None", "pause"]
    assert speed.targets == [camera.SLOW_SPEED, 2.0]  # the playback speed it had


def test_paused_without_a_speed_controller_it_can_not_work(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(paused=True, with_speed=False)
    matcher.start(7)
    assert outcome(events) == ["failed"] and "paused" in events[-1][1]
    assert link.calls[-1] == "pause"  # stays paused


def test_pausing_during_the_match_stops_it(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    matcher.start(1)
    matcher._clock.now += 0.1
    link.push(paused=True)
    assert outcome(events) == ["failed"] and "paused" in events[-1][1]
    assert not matcher.busy


def test_no_object_speed(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    link.target = None  # DCS has not seen it move
    matcher.start(1)
    drive()
    assert outcome(events) == ["failed"] and "not known" in events[-1][1]


def test_no_camera(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    link.state = replace(link.state, cam=None)
    matcher.start(1)
    link.push(cam=None)
    drive()
    assert outcome(events) == ["failed"] and "free camera" in events[-1][1]


def test_dcs_ignoring_the_inputs_gives_up(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(ignore=10_000)
    matcher.start(1)
    drive(600)
    assert outcome(events) == ["failed"] and "gave up" in events[-1][1]
    assert len(inp.actions) == camera.MAX_ROUNDS


def test_a_dropped_input_is_repeated(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(ignore=2)
    matcher.start(1)
    drive()
    assert outcome(events) == ["matched"]


def test_input_error_fails(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(error="no window titled 'Digital Combat Simulator'")
    matcher.start(1)
    drive()
    assert outcome(events) == ["failed"] and "no window" in events[-1][1]


def test_old_hook_and_no_connection(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    link.reports_objects = False
    matcher.start(1)
    assert outcome(events) == ["failed"] and "hook" in events[-1][1]
    link.reports_objects, link.connected = True, False
    matcher.start(1)
    assert outcome(events) == ["failed", "failed"] and not matcher.busy


def test_cancel_restores_a_pause(rig) -> None:
    link, speed, inp, matcher, events, drive = rig(paused=True)
    matcher.start(1)
    matcher.cancel()
    assert outcome(events) == ["failed"] and events[-1][1] == "cancelled"
    assert link.state.paused and not matcher.busy


def test_the_cross_view_speed_is_reported(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    link.side = 40.0
    matcher.start(1, "Viper")
    drive()
    assert "40 m/s across the view" in events[-1][1]


def test_a_new_start_cancels_the_old(rig) -> None:
    link, speed, inp, matcher, events, drive = rig()
    matcher.start(1)
    matcher.start(2)
    assert outcome(events) == ["failed"] and events[0][1] == "cancelled"
    assert link.watched == 2
