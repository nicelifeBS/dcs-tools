"""Runs hook/spike/ReplayHelperSpike.lua in Lua 5.1 against a mocked DCS hooks environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("lupa.lua51")

from lua_harness import HOOK_DIR, Hook  # noqa: E402

HOOK = HOOK_DIR / "spike" / "ReplayHelperSpike.lua"


@pytest.fixture
def hook() -> Hook:
    return Hook(HOOK)



def test_loads_and_registers_callbacks(hook: Hook) -> None:
    assert any("loaded spike-3 (callbacks registered)" in line for line in hook.logs())


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_state_after_mission_load(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO spike-3"
    hook.run(0.5)
    state = hook.last_state()
    assert state["start_tod"] == "59400"
    assert state["date"] == "2018-02-01"
    assert state["track"] == "true"
    assert float(state["t"]) == pytest.approx(0.5, abs=0.1)  # STATE goes out every 0.1 s


def test_ping(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("PING") == ["PONG spike-3"]


def test_pause_resume(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("PAUSE")
    assert hook.mock.paused is True
    hook.cmd("RESUME")
    assert hook.mock.paused is False


def test_measures_speed(hook: Hook) -> None:
    hook.load_mission()
    hook.run(3.0, speed=4.0)
    assert float(hook.last_state()["speed"]) == pytest.approx(4.0, rel=0.02)
    hook.cmd("PAUSE")
    hook.run(1.5)
    assert float(hook.last_state()["speed"]) == 0.0


def test_arm_behind_is_refused(hook: Hook) -> None:
    hook.load_mission()
    hook.run(10.0)
    replies = hook.cmd("ARM 5")
    assert replies and replies[0].startswith("ERR behind")


def test_arm_stops_within_one_frame(hook: Hook) -> None:
    hook.load_mission()
    hook.run(1.0)
    assert hook.cmd("ARM 62.95")[0].startswith("ARMED target=62.950")
    hook.clear()
    hook.run(30.0, speed=4.0, fps=60)
    assert hook.mock.paused is True
    arrived = [s for s in hook.sent() if s.startswith("ARRIVED ")]
    assert len(arrived) == 1
    fields = dict(kv.split("=", 1) for kv in arrived[0].split()[1:])
    assert 0 <= float(fields["over"]) <= 4.0 / 60 + 1e-6
    assert float(hook.last_state()["stop"]) == -1


def test_disarm(hook: Hook) -> None:
    hook.load_mission()
    hook.cmd("ARM 3")
    assert hook.cmd("DISARM") == ["DISARMED"]
    hook.run(5.0)
    assert hook.mock.paused is False


def test_probe_survives_minimal_environment(hook: Hook) -> None:
    hook.load_mission()
    replies = hook.cmd("PROBE")
    assert replies[0] == "PROBE begin spike-3"
    assert replies[-1] == "PROBE end"
    assert "PROBE mission start_time=59400 date=2018-02-01 theatre=Caucasus" in replies
    assert "PROBE global LoSetCommand nil" in replies


def test_locmd_reports_missing_function(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("LOCMD 52")[0].startswith("LOCMD unavailable")


def test_locmd_calls_export_function(hook: Hook) -> None:
    hook.lua.execute("Export = { LoSetCommand = function(id, v) MOCK.locmd = { id, v } end }")
    hook.load_mission()
    reply = hook.cmd("LOCMD 52")[0]
    assert "via=Export ok=true" in reply
    assert "accel_before=-1.000" in reply  # no LoGetModelTimeAcceleration in this mock
    assert hook.mock.locmd[1] == 52


def test_state_and_locmd_report_commanded_accel(hook: Hook) -> None:
    # A mock DCS where accelerate (id 52) doubles the commanded rate the clock runs at.
    hook.lua.execute("""
        MOCK.accel = 1
        Export = {
            LoSetCommand = function(id) if id == 52 then MOCK.accel = MOCK.accel * 2 end end,
            LoGetModelTimeAcceleration = function() return MOCK.accel end,
        }
    """)
    hook.load_mission()
    hook.run(1.0)
    assert hook.last_state()["accel"] == "1.000"

    assert "accel_before=1.000" in hook.cmd("LOCMD 52")[0]
    hook.clear()
    hook.run(1.0, speed=2.0)
    after = [s for s in hook.sent() if s.startswith("LOCMD-AFTER ")]
    assert len(after) == 1
    assert after[0].startswith("LOCMD-AFTER id=52 accel=2.000")
    assert hook.last_state()["accel"] == "2.000"


def test_locmdx_reports_missing_net(hook: Hook) -> None:
    hook.load_mission()
    assert "net.dostring_in unavailable" in hook.cmd("LOCMDX 52")[0]


def test_unknown_command(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("BOGUS")[0] == "ERR unknown command BOGUS"


def test_findcmds_scans_install(hook: Hook, tmp_path: Path) -> None:
    (tmp_path / "Scripts" / "Input").mkdir(parents=True)
    (tmp_path / "Scripts" / "Input" / "defs.lua").write_text(
        "iCommandAccelerate = 52,\niCommandDecelerate = 53,\niCommandPause = 54,\n")
    (tmp_path / "Config" / "Input").mkdir(parents=True)
    (tmp_path / "Config" / "Input" / "keyboard.lua").write_text(
        "{combos = {{key = 'Z', reformers = {'LCtrl'}}}, down = iCommandAccelerate, name = _('Time accelerate')},\n")
    (tmp_path / "Config" / "readme.txt").write_text("iCommandAccelerate = 99\n")

    lua = hook.lua
    lua.globals().PY_ROOT = str(tmp_path)
    lua.globals().PY_listdir = lambda p: lua.table_from([".", ".."] + sorted(os.listdir(p)))
    lua.globals().PY_mode = lambda p: (
        "directory" if os.path.isdir(p) else "file" if os.path.isfile(p) else None)
    # The hook builds Windows paths; translate them for this filesystem.
    lua.execute(r"""
        local function fix(p) return (p:gsub("\\", "/")) end
        lfs = {
            currentdir = function() return PY_ROOT .. "\\" end,
            dir = function(p)
                local list, i = PY_listdir(fix(p)), 0
                return function() i = i + 1; return list[i] end, nil
            end,
            attributes = function(p, what) return PY_mode(fix(p)) end,
        }
        local real_open = io.open
        io.open = function(p, mode) return real_open(fix(p), mode) end
    """)
    hook.load_mission()
    replies = hook.cmd("FINDCMDS")
    assert "CMDID iCommandAccelerate=52 file=Scripts\\Input\\defs.lua" in replies
    assert "CMDID iCommandDecelerate=53 file=Scripts\\Input\\defs.lua" in replies
    assert "CMDID iCommandAccelerate=? file=Config\\Input\\keyboard.lua" in replies
    assert not any("iCommandPause" in r or "=99" in r for r in replies)
    assert replies[-1].startswith("FIND done: 2 lua files, 3 hits")


def test_globals_finds_engine_ids_here_and_one_table_down(hook: Hook) -> None:
    hook.lua.execute("""
        iCommandAccelerate = 52
        iCommandPause = 54
        Input = { iCommandDecelerate = 53, iCommandNoAcceleration = 55 }
    """)
    hook.load_mission()
    replies = hook.cmd("GLOBALS")
    assert replies[0] == ("GLOBALS hooks Input.iCommandDecelerate=53 "
                          "Input.iCommandNoAcceleration=55 iCommandAccelerate=52")
    # The other Lua states are reached through net.dostring_in, which this mock lacks.
    assert replies[1] == "GLOBALS config nil | net.dostring_in unavailable"
    assert replies[-1] == "GLOBALS done"


def test_globals_runs_the_same_scan_in_other_states(hook: Hook) -> None:
    # net.dostring_in runs the code in a separate state; emulate one where the id is a global.
    hook.lua.execute("""
        net = { dostring_in = function(state, code)
            local env = { pairs = pairs, ipairs = ipairs, type = type, tostring = tostring,
                          pcall = pcall, table = table }
            env._G = env
            if state == "export" then env.iCommandAccelerate = 52 end
            local f = assert(loadstring(code))
            setfenv(f, env)
            return f(), true
        end }
    """)
    hook.load_mission()
    replies = hook.cmd("GLOBALS accel")
    assert "GLOBALS export iCommandAccelerate=52 | true" in replies
    assert "GLOBALS mission (none) | true" in replies


def test_globals_only_passes_words_into_generated_code(hook: Hook) -> None:
    hook.lua.execute("MOCK.boom = false; iCommandAccelerate = 1")
    hook.load_mission()
    replies = hook.cmd("GLOBALS accel\") MOCK.boom = true --")
    assert hook.mock.boom is False
    # The payload is split into the plain words accel/mock/boom/true and searched for.
    assert replies[0].startswith("GLOBALS hooks MOCK.boom=false")
    assert "iCommandAccelerate=1" in replies[0]


def test_digital_dispatch(hook: Hook) -> None:
    hook.lua.execute("DCS.dispatchDigitalAction = function(id) MOCK.digital = id end")
    hook.load_mission()
    reply = hook.cmd("DIGITAL 52")[0]
    assert reply.startswith("DIGITAL id=52 value=nil ok=true")
    assert hook.mock.digital == 52
    hook.clear()
    hook.run(1.0)
    assert any(s.startswith("LOCMD-AFTER digital id=52") for s in hook.sent())


def test_digital_unavailable(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("DIGITAL 52")[0] == "DIGITAL unavailable: no DCS.dispatchDigitalAction"


@pytest.mark.parametrize("arg", ["0000022317A6DEA0", "52abc", "52 1 2", "52 x", "abc"])
def test_command_ids_must_be_whole_numbers(hook: Hook, arg: str) -> None:
    hook.lua.execute("Export = { LoSetCommand = function(id) MOCK.locmd = id end }")
    hook.load_mission()
    assert hook.cmd("LOCMD " + arg) == ["ERR LOCMD needs a command id"]
    assert hook.mock.locmd is None


def test_command_value_is_optional_number(hook: Hook) -> None:
    hook.lua.execute("Export = { LoSetCommand = function(id, v) MOCK.locmd = { id, v } end }")
    hook.load_mission()
    assert "ok=true" in hook.cmd("LOCMD 52 0.25")[0]
    assert hook.mock.locmd[1] == 52 and hook.mock.locmd[2] == 0.25
