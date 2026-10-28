from __future__ import annotations

import pytest

from conftest import load_fake_dcs
from replay_helper.dcs import protocol

fake = load_fake_dcs()


def run(sim, seconds: float, fps: int = 60) -> list[str]:
    out = []
    for _ in range(int(seconds * fps)):
        sim.frame(1 / fps)
        out += sim.drain()
    return out


def test_speed_ladder_matches_dcs() -> None:
    sim = fake.FakeDcs()
    seen = []
    for _ in range(3):
        sim.handle("KEY UP")
        seen.append(sim.accel)
    assert seen == [2, 3, 4]  # +1x per step above 1x, as measured in DCS
    sim.handle("KEY NORMAL")
    sim.handle("KEY DOWN")
    sim.handle("KEY DOWN")
    assert sim.accel == 0.25
    sim.handle("KEY UP")
    assert sim.accel == 0.5


def test_stop_and_forward_only() -> None:
    sim = fake.FakeDcs()
    sim.handle("KEY UP")
    sim.handle("KEY UP")
    sim.handle("KEY UP")
    sim.handle("ARMSTOP 10")
    assert sim.drain()[-1] == "ARMED target=10.000 now=0.000"
    out = run(sim, 5)
    arrived = [line for line in out if line.startswith("ARRIVED")]
    assert len(arrived) == 1 and sim.paused
    assert 10 <= sim.t <= 10 + 4 / 60 + 1e-9
    sim.handle("ARMSTOP 5")
    assert sim.drain()[-1].startswith("ERR behind target=5.000")


def test_pauses_at_end_of_track() -> None:
    sim = fake.FakeDcs(start=115.0, duration=117.1)
    run(sim, 3)
    assert sim.paused and sim.t == pytest.approx(117.1)
    sim.handle("RESUME")
    assert sim.paused


def test_state_line_parses() -> None:
    from replay_helper.dcs import protocol

    sim = fake.FakeDcs(start=62.95, paused=True)
    s = protocol.parse(sim.state_line())
    assert s.t == 62.95 and s.paused and s.accel == 1 and s.speed == 0 and s.start_tod == 59400


def test_speed_commands_like_hook_0_2() -> None:
    sim = fake.FakeDcs()
    sim.handle("SPEED UP")
    sim.handle("SPEED UP")
    assert sim.accel == 3
    sim.handle("SPEED NORMAL")
    sim.handle("SPEED DOWN")
    assert sim.accel == 0.5


def test_focus() -> None:
    sim = fake.FakeDcs(aircraft={16797696})
    sim.drain()
    sim.handle("FOCUS 16797696 A-10C #001")
    assert sim.drain() == ["FOCUSED id=16797696 steps=1"] and sim.focused == 16797696
    sim.handle("FOCUS 42")
    assert sim.drain() == ["FOCUS-FAILED id=42 reason=not_found"]
    sim.handle("FOCUS")
    assert sim.drain() == []


def test_camera_inputs_like_dcs() -> None:
    sim = fake.FakeDcs()
    sim.handle("CAM FASTER 1")
    assert sim.camv == 5.0
    sim.handle("CAM FASTER 2")
    assert sim.camv == pytest.approx(6.05)
    sim.handle("CAM SLOWER 1")
    assert sim.camv == pytest.approx(5.5)
    sim.handle("CAM WHEEL -9")  # wheel: 1.13 m/s a notch, across zero
    assert sim.camv == pytest.approx(5.5 - 9 * 1.13)
    sim.handle("PAUSE")
    sim.handle("CAM WHEEL 5")  # ignored while paused
    assert sim.camv == pytest.approx(5.5 - 9 * 1.13)


def test_objects_and_watch() -> None:
    sim = fake.FakeDcs(start=10.0)
    sim.drain()
    sim.handle("OBJECTS")
    assert sim.drain() == ["ERR OBJECTS needs TRACK on"]
    sim.handle("TRACK on")
    sim.handle("OBJECTS 2000")
    lines = sim.drain()
    assert lines[-1].startswith("OBJ-END") and 1 < len(lines) < 6
    sim.handle("WATCH 16798208")
    state = protocol.parse(sim.state_line())
    assert (state.tgt, state.tgt_along) == (16798208, 50.0)
    assert all(isinstance(protocol.parse(line), protocol.Obj) for line in lines[:-1])
