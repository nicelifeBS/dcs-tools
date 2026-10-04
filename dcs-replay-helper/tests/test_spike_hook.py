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
    assert any("loaded spike-4 (callbacks registered)" in line for line in hook.logs())


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_state_after_mission_load(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO spike-4"
    hook.run(0.5)
    state = hook.last_state()
    assert state["start_tod"] == "59400"
    assert state["date"] == "2018-02-01"
    assert state["track"] == "true"
    assert float(state["t"]) == pytest.approx(0.5, abs=0.1)  # STATE goes out every 0.1 s


def test_ping(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("PING") == ["PONG spike-4"]


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
    assert replies[0] == "PROBE begin spike-4"
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


# Round 4: a mock world for the camera. F2 (8) puts the camera 30 m behind the first blue
# aircraft, looking along +x; next object (181) moves it to the next blue aircraft. The two
# blue A-10Cs fly 40 m apart; a red aircraft and a ground unit are not in the F2 cycle.
WORLD = """
MOCK.units = {
    [0x5701] = { Name = "A-10C_2", UnitName = "fubar 1-1", GroupName = "Player", Coalition = "Enemies",
                 Type = { level1 = 1 }, Flags = { Human = true }, Position = { x = 1000, y = 500, z = 40 } },
    [0x5001] = { Name = "A-10C_2", UnitName = "A-10C #001", GroupName = "A-10C #001", Coalition = "Enemies",
                 Type = { level1 = 1 }, Flags = {}, Position = { x = 1000, y = 500, z = 0 } },
    [0x6001] = { Name = "Su-25T", UnitName = "Frogfoot", GroupName = "Red", Coalition = "Allies",
                 Type = { level1 = 1 }, Flags = {}, Position = { x = -6000, y = 300, z = 0 } },
    [0x101]  = { Name = "Ural-375", UnitName = "Truck", GroupName = "Convoy", Coalition = "Allies",
                 Type = { level1 = 2 }, Flags = {}, Position = { x = 990, y = 0, z = 10 } },
}
MOCK.cycle, MOCK.view = { 0x5701, 0x5001 }, nil
MOCK.commands = {}
local function look_at(id)
    local p = MOCK.units[id].Position
    MOCK.cam = { p = { x = p.x - 30, y = p.y, z = p.z }, x = { x = 1, y = 0, z = 0 },
                 y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }
end
look_at(0x5001)
Export = {
    LoGetCameraPosition = function() return MOCK.cam end,
    LoGetWorldObjects = function() return MOCK.units end,
    LoSetCommand = function(id)
        table.insert(MOCK.commands, id)
        if id == 8 and MOCK.view == nil then
            MOCK.view = 1
        elseif id == 8 or id == 181 then
            MOCK.view = MOCK.view % #MOCK.cycle + 1
        else
            return
        end
        look_at(MOCK.cycle[MOCK.view])
    end,
}
"""


@pytest.fixture
def world(hook: Hook) -> Hook:
    hook.lua.execute(WORLD)
    hook.load_mission()
    return hook


def test_cam_reports_the_unit_in_the_line_of_sight(world: Hook) -> None:
    replies = world.cmd("CAM")
    assert replies[0] == "CAM p=(970.0,500.0,0.0) x=(1.000,0.000,0.000) units=4 near=3 via=Export/Export"
    # The wingman is dead ahead; the lead, 40 m to the side, is not the one viewed.
    assert replies[1].startswith('CAM aimed id=20481/0x5001 A-10C_2 unit="A-10C #001"')
    assert "dist=30.0 off=0.0" in replies[1]
    assert replies[2].startswith("CAM nearest id=20481/0x5001")
    assert replies[-1] == "CAM axes to nearest: x=0.0 y=90.0 z=90.0 deg"


def test_objects_lists_aircraft_or_all_units(world: Hook) -> None:
    replies = world.cmd("OBJECTS")
    assert replies[0] == "OBJECTS units=4 listed=3 (aircraft) via=Export"
    assert [r.split()[1] for r in replies[1:-1]] == ["id=20481/0x5001", "id=22273/0x5701", "id=24577/0x6001"]
    assert 'unit="fubar 1-1" group="Player" Enemies air=true human=true' in replies[2]
    assert replies[-1] == "OBJECTS end"
    assert world.cmd("OBJECTS all")[0] == "OBJECTS units=4 listed=4 (all) via=Export"


def test_view_reports_where_the_camera_went(world: Hook) -> None:
    assert world.cmd("VIEW 8")[0] == "VIEW id=8 value=nil via=Export ok=true err=nil"
    world.clear()
    world.run(0.5)
    after = [s for s in world.sent() if s.startswith("VIEW-AFTER")]
    assert after[1].startswith("VIEW-AFTER id=8 aimed id=22273/0x5701")  # F2: the lead
    assert world.cmd("VIEW x") == ["ERR VIEW needs a command id"]


def test_focus_steps_to_the_target(world: Hook) -> None:
    assert world.cmd("FOCUS 0x5001")[0].startswith("FOCUS start id=20481/0x5001")
    world.clear()
    world.run(1.0)
    steps = [s for s in world.sent() if s.startswith("FOCUS")]
    assert steps[0].startswith("FOCUS-STEP 0 viewed id=22273/0x5701")  # F2 lands on the lead
    assert steps[1].startswith("FOCUS-STEP 1 viewed id=20481/0x5001")
    assert steps[2].startswith("FOCUS-DONE ok target=0x5001 steps=1 time=0.3")
    assert steps[2].endswith("visited=0x5701")
    assert list(world.mock.commands.values()) == [8, 181]


def test_focus_by_name_and_decimal_id(world: Hook) -> None:
    assert world.cmd("FOCUS fubar")[0].startswith("FOCUS start id=22273/0x5701")
    world.run(1.0)
    assert world.cmd("FOCUS 20481")[0].startswith("FOCUS start id=20481/0x5001")
    assert world.cmd("FOCUS nobody") == ["FOCUS no unit matches nobody"]


def test_focus_gives_up_after_a_full_cycle(world: Hook) -> None:
    world.cmd("FOCUS Frogfoot")  # red: not in the F2 cycle
    world.clear()
    world.run(2.0)
    done = [s for s in world.sent() if s.startswith("FOCUS-DONE")]
    assert done == ["FOCUS-DONE fail reason=cycled target=0x6001 steps=2 time=0.45 visited=0x5701,0x5001"]


def test_focus_can_be_cancelled(world: Hook) -> None:
    world.cmd("FOCUS Frogfoot")
    assert world.cmd("FOCUS")[0].startswith("FOCUS-DONE cancelled target=0x6001 steps=0")
    assert world.cmd("FOCUS") == ["FOCUS nothing to cancel"]


def test_focus_without_a_camera(hook: Hook) -> None:
    hook.lua.execute(WORLD + "Export.LoGetCameraPosition = nil")
    hook.load_mission()
    assert hook.cmd("CAM") == ["CAM unavailable: no camera position (LoGetCameraPosition)"]
    hook.cmd("FOCUS 0x5001")
    hook.clear()
    hook.run(0.5)
    done = [s for s in hook.sent() if s.startswith("FOCUS-DONE")]
    assert done[0].startswith("FOCUS-DONE fail reason=no_camera_position_(LoGetCameraPosition)")


def test_camera_commands_without_export(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("OBJECTS") == ["OBJECTS unavailable: no units (LoGetWorldObjects)"]
    assert hook.cmd("FOCUS 0x5001") == ["FOCUS unavailable: no units (LoGetWorldObjects)"]


def test_camera_and_units_through_the_export_state(hook: Hook) -> None:
    # This state has only LoSetCommand; the getters are globals in the export state, which
    # net.dostring_in reaches (a unit name with a tab in it must not break the parsing).
    hook.lua.execute(WORLD + """
        MOCK.units[0x5001].UnitName = "A-10C\t#001"
        local getters = { LoGetCameraPosition = Export.LoGetCameraPosition,
                          LoGetWorldObjects = Export.LoGetWorldObjects }
        Export.LoGetCameraPosition, Export.LoGetWorldObjects = nil, nil
        net = { dostring_in = function(state, code)
            if state ~= "export" then return "", false end
            local f = assert(loadstring(code))
            setfenv(f, setmetatable(getters, { __index = _G }))
            return f(), true
        end }
    """)
    hook.load_mission()
    replies = hook.cmd("CAM")
    assert replies[0].endswith("units=4 near=3 via=export-state/export-state")
    assert replies[1].startswith('CAM aimed id=20481/0x5001 A-10C_2 unit="A-10C #001" group="A-10C #001"')
    assert "air=true human=false dist=30.0 off=0.0" in replies[1]
    assert 'unit="fubar 1-1" group="Player" Enemies air=true human=true' in hook.cmd("OBJECTS")[2]
    hook.cmd("FOCUS fubar")
    hook.clear()
    hook.run(1.0)
    assert any(s.startswith("FOCUS-DONE ok target=0x5701") for s in hook.sent())
