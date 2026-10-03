"""Runs hook/ReplayHelper.lua in Lua 5.1 against a mocked DCS hooks environment."""

from __future__ import annotations

import pytest

pytest.importorskip("lupa.lua51")

from lua_harness import HOOK_DIR, Hook  # noqa: E402

HOOK = HOOK_DIR / "ReplayHelper.lua"


def fields(line: str) -> dict[str, str]:
    return dict(kv.split("=", 1) for kv in line.split()[1:])


@pytest.fixture
def hook() -> Hook:
    h = Hook(HOOK)
    # DCS reports the commanded acceleration through Export; the tests set MOCK.accel.
    h.lua.execute("MOCK.accel = 1; Export = { LoGetModelTimeAcceleration = function() return MOCK.accel end }")
    return h


def test_loads_and_registers_callbacks(hook: Hook) -> None:
    assert "loaded 0.1.0 (callbacks registered)" in hook.logs()


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_hello_and_state(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO 0.1.0"
    hook.lua.execute("MOCK.accel = 4")
    hook.run(2.0, speed=4.0)
    state = hook.last_state()
    assert float(state["t"]) == pytest.approx(8.0, abs=0.5)
    assert float(state["speed"]) == pytest.approx(4.0, rel=0.02)
    assert state["accel"] == "4.000"
    assert state["paused"] == "false"
    assert state["track"] == "true"
    assert state["stop"] == "-1.000"
    assert state["start_tod"] == "59400.000"
    assert state["date"] == "2018-02-01"
    assert state["theatre"] == "Caucasus"


def test_state_without_export_or_mission_data(hook: Hook) -> None:
    hook.lua.execute("Export = nil; DCS.getCurrentMission = function() return nil end")
    hook.load_mission()
    hook.run(0.5)
    state = hook.last_state()
    assert state["accel"] == "-1.000"
    assert state["start_tod"] == "-1"
    assert state["date"] == "-"
    assert state["theatre"] == "-"


def test_theatre_is_one_token(hook: Hook) -> None:
    hook.lua.execute("""
        DCS.getCurrentMission = function()
            return { mission = { start_time = 0, theatre = "Some Map, Beta" } }
        end
    """)
    hook.load_mission()
    hook.run(0.2)
    assert hook.last_state()["theatre"] == "Some_Map_Beta"


def test_ping(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("PING") == ["PONG 0.1.0"]


def test_pause_resume(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("PAUSE")
    assert hook.mock.paused is True
    hook.cmd("resume")
    assert hook.mock.paused is False


@pytest.mark.parametrize("arg", ["", "abc", "5x", "1 2"])
def test_armstop_needs_a_number(hook: Hook, arg: str) -> None:
    hook.load_mission()
    assert hook.cmd(f"ARMSTOP {arg}") == ["ERR ARMSTOP needs a model time"]


@pytest.mark.parametrize("target", ["5", "10"])
def test_armstop_is_forward_only(hook: Hook, target: str) -> None:
    hook.load_mission()
    hook.run(10.0)
    reply = hook.cmd(f"ARMSTOP {target}")[0]
    assert reply.startswith(f"ERR behind target={float(target):.3f} now=")
    hook.run(1.0)
    assert hook.mock.paused is False


def test_armstop_pauses_within_one_frame_at_4x(hook: Hook) -> None:
    hook.load_mission()
    hook.run(1.0)
    reply = hook.cmd("ARMSTOP 62.95")[0]
    assert reply.startswith("ARMED target=62.950 now=")
    hook.run(0.2)
    assert hook.last_state()["stop"] == "62.950"
    hook.clear()
    hook.lua.execute("MOCK.accel = 4")
    hook.run(30.0, speed=4.0, fps=60)
    assert hook.mock.paused is True
    arrived = [s for s in hook.sent() if s.startswith("ARRIVED ")]
    assert len(arrived) == 1
    f = fields(arrived[0])
    assert f["target"] == "62.950"
    assert 0 <= float(f["over"]) <= 4.0 / 60 + 1e-6
    assert hook.last_state()["stop"] == "-1.000"


def test_new_armstop_replaces_old(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("ARMSTOP 50")
    hook.cmd("ARMSTOP 5")
    hook.clear()
    hook.run(6.0)
    arrived = [s for s in hook.sent() if s.startswith("ARRIVED ")]
    assert len(arrived) == 1 and fields(arrived[0])["target"] == "5.000"


def test_disarm(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("ARMSTOP 3")
    assert hook.cmd("DISARM") == ["DISARMED reason=request"]
    hook.run(5.0)
    assert hook.mock.paused is False
    assert hook.cmd("DISARM") == ["DISARMED reason=request"]  # idempotent


def test_track_restart_drops_the_armed_stop(hook: Hook) -> None:
    hook.load_mission()
    hook.run(30.0)
    hook.cmd("ARMSTOP 40")
    hook.clear()
    hook.lua.execute("MOCK.m = 0")  # the track ended and DCS replays it from the start
    hook.run(0.1)
    assert "DISARMED reason=restart" in hook.sent()
    hook.run(45.0)
    assert not any(s.startswith("ARRIVED") for s in hook.sent())
    assert hook.mock.paused is False


def test_mission_end_disarms_and_goes_quiet(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("ARMSTOP 40")
    hook.clear()
    hook.mock.cb.onSimulationStop()
    assert hook.sent() == ["DISARMED reason=mission_end"]
    hook.clear()
    hook.run(1.0)
    assert hook.sent() == []


def test_unknown_command(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("FLY away") == ["ERR unknown command FLY"]


def test_commands_wait_for_a_mission(hook: Hook) -> None:
    hook.lua.execute("table.insert(MOCK.inbox, 'PAUSE')")
    hook.run(0.5)
    assert hook.mock.paused is False
