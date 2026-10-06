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
    assert any("loaded spike-7 (callbacks registered)" in line for line in hook.logs())


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_state_after_mission_load(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO spike-7"
    hook.run(0.5)
    state = hook.last_state()
    assert state["start_tod"] == "59400"
    assert state["date"] == "2018-02-01"
    assert state["track"] == "true"
    assert float(state["t"]) == pytest.approx(0.5, abs=0.1)  # STATE goes out every 0.1 s


def test_ping(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("PING") == ["PONG spike-7"]


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
    assert replies[0] == "PROBE begin spike-7"
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


def fake_install(hook: Hook, root: Path) -> None:
    """Point the hook's lfs and io.open at a directory standing in for the DCS install."""
    lua = hook.lua
    lua.globals().PY_ROOT = str(root)
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


def test_findcmds_scans_install(hook: Hook, tmp_path: Path) -> None:
    (tmp_path / "Scripts" / "Input").mkdir(parents=True)
    (tmp_path / "Scripts" / "Input" / "defs.lua").write_text(
        "iCommandAccelerate = 52,\niCommandDecelerate = 53,\niCommandPause = 54,\n")
    (tmp_path / "Config" / "Input").mkdir(parents=True)
    (tmp_path / "Config" / "Input" / "keyboard.lua").write_text(
        "{combos = {{key = 'Z', reformers = {'LCtrl'}}}, down = iCommandAccelerate, name = _('Time accelerate')},\n")
    (tmp_path / "Config" / "readme.txt").write_text("iCommandAccelerate = 99\n")

    fake_install(hook, tmp_path)
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


# Rounds 4-5: a mock world for the camera, behaving as DCS did in a replay. The camera starts
# in the lead's cockpit. F2 (8) moves it 30 m behind the player's aircraft, looking along +x;
# in F2, 8 steps to the next blue aircraft in id order. Next/previous object (181/180) do
# nothing. dispatchDigitalAction and LoSetCommand in the export state switch views;
# Export.LoSetCommand in the hooks state is accepted but does nothing. The two blue A-10Cs fly 40 m apart; a red aircraft and a ground
# unit are not in the F2 cycle.
WORLD = """
MOCK.units = {
    [0x1005700] = { Name = "A-10C_2", UnitName = "fubar 1-1", GroupName = "Player", Coalition = "Enemies",
                    Type = { level1 = 1 }, Flags = { Human = true }, Position = { x = 1000, y = 500, z = 40 } },
    [0x1005000] = { Name = "A-10C_2", UnitName = "A-10C #001", GroupName = "A-10C #001", Coalition = "Enemies",
                    Type = { level1 = 1 }, Flags = {}, Position = { x = 1000, y = 500, z = 0 } },
    [0x1006000] = { Name = "Su-25T", UnitName = "Frogfoot", GroupName = "Red", Coalition = "Allies",
                    Type = { level1 = 1 }, Flags = {}, Position = { x = -6000, y = 300, z = 0 } },
    [0x1000100] = { Name = "Ural-375", UnitName = "Truck", GroupName = "Convoy", Coalition = "Allies",
                    Type = { level1 = 2 }, Flags = {}, Position = { x = 990, y = 0, z = 10 } },
}
MOCK.cycle, MOCK.view = { 0x1005000, 0x1005700 }, nil
MOCK.commands = {}
local AXES = { x = { x = 1, y = 0, z = 0 }, y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }
local function look_at(id)
    local p = MOCK.units[id].Position
    MOCK.cam = { p = { x = p.x - 30, y = p.y, z = p.z }, x = AXES.x, y = AXES.y, z = AXES.z }
end
-- In the lead's cockpit, looking ahead (the wingman is 40 m to the side, not ahead).
MOCK.cam = { p = { x = 1001, y = 500, z = 40 }, x = AXES.x, y = AXES.y, z = AXES.z }
local function switch(id)
    table.insert(MOCK.commands, id)
    local n = #MOCK.cycle
    if id ~= 8 then return end
    if MOCK.view == nil then
        MOCK.view = 2  -- the player's own aircraft
    else
        MOCK.view = MOCK.view % n + 1
    end
    look_at(MOCK.cycle[MOCK.view])
end
Export = {
    LoGetCameraPosition = function() return MOCK.cam end,
    LoGetWorldObjects = function() return MOCK.units end,
    LoSetCommand = function(id) table.insert(MOCK.commands, -id) end,  -- ignored in a replay
}
DCS.dispatchDigitalAction = switch
net = { dostring_in = function(state, code)
    if state ~= "export" then return "", false end
    local f = assert(loadstring(code))
    setfenv(f, setmetatable({ LoSetCommand = switch }, { __index = _G }))
    return f(), true
end }
"""


@pytest.fixture
def world(hook: Hook) -> Hook:
    hook.lua.execute(WORLD)
    hook.load_mission()
    return hook


def focus_lines(hook: Hook, seconds: float = 1.0) -> list[str]:
    hook.clear()
    hook.run(seconds)
    return [s for s in hook.sent() if s.startswith("FOCUS")]


def test_cam_in_the_cockpit_views_nothing(world: Hook) -> None:
    replies = world.cmd("CAM")
    assert replies[0] == "CAM p=(1001.0,500.0,40.0) x=(1.000,0.000,0.000) units=4 near=3 via=Export/Export"
    assert replies[1] == "CAM aimed none"
    assert replies[3].startswith('CAM nearest id=16799488/0x1005700 A-10C_2 unit="fubar 1-1"')
    assert "dist=1.0 off=180.0" in replies[3]


def test_cam_reports_the_unit_in_the_line_of_sight(world: Hook) -> None:
    world.lua.execute("MOCK.view = 1")
    world.mock.cam = world.lua.eval("{ p = { x = 970, y = 500, z = 0 }, x = { x = 1, y = 0, z = 0 },"
                                    " y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }")
    replies = world.cmd("CAM")
    # The wingman is dead ahead; the lead, 40 m to the side, is not the one viewed.
    assert replies[1].startswith('CAM aimed id=16797696/0x1005000 A-10C_2 unit="A-10C #001"')
    assert "dist=30.0 off=0.0" in replies[1]
    assert replies[2].startswith("CAM best id=16797696/0x1005000")
    assert replies[3].startswith("CAM nearest id=16797696/0x1005000")
    assert replies[-1] == "CAM axes to nearest: x=0.0 y=90.0 z=90.0 deg"


def test_objects_lists_aircraft_or_all_units(world: Hook) -> None:
    replies = world.cmd("OBJECTS")
    assert replies[0] == "OBJECTS units=4 listed=3 (aircraft) via=Export"
    assert [r.split()[1] for r in replies[1:-1]] == [
        "id=16797696/0x1005000", "id=16799488/0x1005700", "id=16801792/0x1006000"]
    assert 'unit="fubar 1-1" group="Player" Enemies air=true human=true' in replies[2]
    assert replies[-1] == "OBJECTS end"
    assert world.cmd("OBJECTS all")[0] == "OBJECTS units=4 listed=4 (all) via=Export"


@pytest.mark.parametrize("route", ["", "digital ", "export "])
def test_view_switches_by_digital_action_or_export_state(world: Hook, route: str) -> None:
    name = route.strip() or "digital"
    assert world.cmd(f"VIEW {route}8") == [f"VIEW id=8 value=nil via={name} ok=true err=nil"]
    world.clear()
    world.run(0.5)
    after = [s for s in world.sent() if s.startswith("VIEW-AFTER")]
    assert after[1].startswith(f"VIEW-AFTER {name} id=8 aimed id=16799488/0x1005700")  # F2: own aircraft


def test_view_from_the_hooks_state_does_nothing(world: Hook) -> None:
    assert world.cmd("VIEW hooks 8") == ["VIEW id=8 value=nil via=hooks ok=true err=nil"]
    world.clear()
    world.run(0.5)
    assert "VIEW-AFTER hooks id=8 aimed none" in world.sent()
    assert world.cmd("VIEW digital x") == ["ERR VIEW needs a command id"]


def test_next_object_does_nothing(world: Hook) -> None:
    world.cmd("VIEW 8")
    world.run(0.5)
    world.cmd("VIEW 181")
    world.clear()
    world.run(0.5)
    assert any(s.startswith("VIEW-AFTER digital id=181 aimed id=16799488/0x1005700") for s in world.sent())


def test_focus_steps_with_f2_to_the_target(world: Hook) -> None:
    start = world.cmd("FOCUS 0x1005000")
    assert start[0].startswith("FOCUS start digital every 0.15s target id=16797696/0x1005000")
    assert start[1].startswith("FOCUS-STEP 0 digital viewed none, best id=16777472/0x1000100")  # cockpit
    steps = focus_lines(world)
    assert steps[0].startswith("FOCUS-STEP 1 digital viewed id=16799488/0x1005700")  # F2: own aircraft
    assert steps[1].startswith("FOCUS-STEP 2 digital viewed id=16797696/0x1005000")
    assert steps[2].startswith("FOCUS-DONE ok target=0x1005000 steps=2 time=0.3")
    assert steps[2].endswith("visited=none,0x1005700")
    assert list(world.mock.commands.values()) == [8, 8]


def test_focus_fast_through_the_export_state(world: Hook) -> None:
    assert world.cmd("FOCUS A-10C #001 fast export")[0].startswith(
        "FOCUS start export every 0.05s target id=16797696")
    assert focus_lines(world)[-1].startswith("FOCUS-DONE ok target=0x1005000 steps=2 time=0.1")
    assert list(world.mock.commands.values()) == [8, 8]


def test_focus_steps_on_from_the_unit_in_view(world: Hook) -> None:
    world.cmd("FOCUS 0x1005000")
    focus_lines(world)
    world.lua.execute("MOCK.commands = {}")
    lines = world.cmd("FOCUS fubar") + focus_lines(world)  # from the wingman, one step on
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005700 steps=1")
    assert list(world.mock.commands.values()) == [8]
    world.lua.execute("MOCK.commands = {}")
    lines = world.cmd("FOCUS fubar")  # already there: done in the same frame
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005700 steps=0")
    assert list(world.mock.commands.values()) == []


def test_focus_by_decimal_id_and_unknown_name(world: Hook) -> None:
    assert world.cmd("FOCUS 16797696")[0].startswith("FOCUS start digital every 0.15s target id=16797696")
    assert world.cmd("FOCUS nobody") == ["FOCUS no unit matches nobody"]


def test_focus_gives_up_after_a_full_cycle(world: Hook) -> None:
    lines = world.cmd("FOCUS Frogfoot") + focus_lines(world, 2.0)  # red: not in the F2 cycle
    done = [s for s in lines if s.startswith("FOCUS-DONE")]
    assert done == ["FOCUS-DONE fail reason=cycled target=0x1006000 steps=3 time=0.45 "
                    "visited=none,0x1005700,0x1005000"]


def test_focus_through_the_hooks_state_never_gets_there(world: Hook) -> None:
    world.cmd("FOCUS 0x1005000 hooks")
    done = [s for s in focus_lines(world, 15.0) if s.startswith("FOCUS-DONE")]
    assert len(done) == 1
    assert done[0].startswith("FOCUS-DONE fail reason=max_steps target=0x1005000 steps=80 ")
    assert done[0].endswith("visited=" + ",".join(["none"] * 81))


def test_focus_can_be_cancelled(world: Hook) -> None:
    world.cmd("FOCUS Frogfoot")
    assert world.cmd("FOCUS")[0].startswith("FOCUS-DONE cancelled target=0x1006000 steps=1")
    assert world.cmd("FOCUS") == ["FOCUS nothing to cancel"]


def test_focus_without_a_camera(hook: Hook) -> None:
    hook.lua.execute(WORLD + "Export.LoGetCameraPosition = nil; net = nil")
    hook.load_mission()
    assert hook.cmd("CAM") == ["CAM unavailable: no camera position (LoGetCameraPosition)"]
    done = [s for s in hook.cmd("FOCUS 0x1005000") if s.startswith("FOCUS-DONE")]
    assert done[0].startswith("FOCUS-DONE fail reason=no_camera_position_(LoGetCameraPosition)")


def test_camera_commands_without_export(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("OBJECTS") == ["OBJECTS unavailable: no units (LoGetWorldObjects)"]
    assert hook.cmd("FOCUS 0x1005000") == ["FOCUS unavailable: no units (LoGetWorldObjects)"]


def test_camera_and_units_through_the_export_state(hook: Hook) -> None:
    # This state has only LoSetCommand; the getters are globals in the export state, which
    # net.dostring_in reaches (a unit name with a tab in it must not break the parsing).
    hook.lua.execute(WORLD + """
        MOCK.units[0x1005000].UnitName = "A-10C\t#001"
        local getters = { LoGetCameraPosition = Export.LoGetCameraPosition,
                          LoGetWorldObjects = Export.LoGetWorldObjects }
        Export.LoGetCameraPosition, Export.LoGetWorldObjects = nil, nil
        local inner = net.dostring_in
        net = { dostring_in = function(state, code)
            if state ~= "export" then return "", false end
            local f = assert(loadstring(code))
            local env = setmetatable({}, { __index = function(_, k)
                if getters[k] then return getters[k] end
                return _G[k]
            end })
            env.LoSetCommand = nil
            setfenv(f, env)
            local ok = f()
            if code:find("pcall(LoSetCommand", 1, true) then return inner(state, code) end
            return ok, true
        end }
    """)
    hook.load_mission()
    replies = hook.cmd("CAM")
    assert replies[0].endswith("units=4 near=3 via=export-state/export-state")
    assert replies[1] == "CAM aimed none"  # in the cockpit
    assert 'unit="fubar 1-1" group="Player" Enemies air=true human=true' in hook.cmd("OBJECTS")[2]
    lines = hook.cmd("FOCUS A-10C #001") + focus_lines(hook)
    assert lines[3].startswith('FOCUS-STEP 2 digital viewed id=16797696/0x1005000 A-10C_2 unit="A-10C #001"')
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005000")


# Round 7: speeds. Everything moves along +x as a function of the mock clocks: objects with
# model time (MOCK.m, so they stop when the sim is paused), the camera with real time (MOCK.r,
# so it flies on while paused, as the free camera does). The weapon appears at model time 5,
# 20 m from the F-16 that "fired" it; DCS lists it only under 'ballistic'.
WORLD7 = """
MOCK.cam0, MOCK.cam_v = { x = 0, y = 100, z = 0 }, { x = 0, y = 0, z = 0 }
MOCK.args = {}
local bodies = {
    [0x1001] = { Name = "F-16C_50", UnitName = "Viper 1-1", GroupName = "Viper", Coalition = "Allies",
                 Type = { level1 = 1, level2 = 1, level3 = 1, level4 = 2 }, Flags = { Human = true },
                 p0 = { x = 0, y = 1000, z = 0 }, v = { x = 200, y = 0, z = 0 } },
    [0x1002] = { Name = "Ka-50", UnitName = "Hokum 1-1", GroupName = "Hokum", Coalition = "Enemies",
                 Type = { level1 = 1, level2 = 2, level3 = 3, level4 = 4 }, Flags = {},
                 p0 = { x = 5000, y = 200, z = 0 }, v = { x = 50, y = 0, z = 0 } },
    [0x1003] = { Name = "Ural-375", UnitName = "Truck", GroupName = "Convoy", Coalition = "Enemies",
                 Type = { level1 = 2 }, Flags = {}, p0 = { x = 10, y = 0, z = 10 }, v = { x = 10, y = 0, z = 0 } },
}
local weapons = {
    [0x2001] = { Name = "AIM-120C", Coalition = "Allies", Type = { level1 = 4, level2 = 4, level3 = 5, level4 = 7 },
                 p0 = { x = 1000, y = 995, z = 0 }, v = { x = 600, y = 0, z = 0 }, t0 = 5 },
}
local function at(b, t)
    local p, v = b.p0, b.v
    return { x = p.x + v.x * t, y = p.y + v.y * t, z = p.z + v.z * t }
end
Export = {
    LoGetCameraPosition = function()
        local p, v, r = MOCK.cam0, MOCK.cam_v, MOCK.r
        return { p = { x = p.x + v.x * r, y = p.y + v.y * r, z = p.z + v.z * r },
                 x = { x = 1, y = 0, z = 0 }, y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }
    end,
    LoGetWorldObjects = function(kind)
        table.insert(MOCK.args, tostring(kind))
        local out = {}
        for id, b in pairs(kind == "ballistic" and weapons or bodies) do
            if not b.t0 or MOCK.m >= b.t0 then
                out[id] = { Name = b.Name, UnitName = b.UnitName, GroupName = b.GroupName, Coalition = b.Coalition,
                            Type = b.Type, Flags = b.Flags, Position = at(b, b.t0 and MOCK.m - b.t0 or MOCK.m) }
            end
        end
        return out
    end,
}
"""


@pytest.fixture
def speeds(hook: Hook) -> Hook:
    hook.lua.execute(WORLD7)
    hook.load_mission()
    return hook


def fields(line: str) -> dict[str, str]:
    """The key=value words of a report line (speed= keeps only its number)."""
    return dict(w.split("=", 1) for w in line.split() if "=" in w)


@pytest.mark.parametrize("cam_vx,fwd", [(100, 100), (-40, -40), (0, 0)])
def test_camv_is_the_camera_speed_along_its_forward_axis(speeds: Hook, cam_vx: float, fwd: float) -> None:
    speeds.lua.execute(f"MOCK.cam_v.x = {cam_vx}")
    speeds.run(1.0)
    reply = fields(speeds.cmd("CAMV")[0])
    assert float(reply["speed"]) == pytest.approx(abs(cam_vx), abs=0.01)
    assert float(reply["fwd"]) == pytest.approx(fwd, abs=0.01)
    speeds.run(0.5)
    state = speeds.last_state()
    assert float(state["camv"]) == pytest.approx(abs(cam_vx), abs=0.01)
    assert float(state["camfwd"]) == pytest.approx(fwd, abs=0.01)


def test_camv_keeps_measuring_while_the_sim_is_paused(speeds: Hook) -> None:
    speeds.lua.execute("MOCK.cam_v.x = 25")
    speeds.cmd("PAUSE")
    speeds.run(1.0)
    assert speeds.mock.paused is True
    assert float(fields(speeds.cmd("CAMV")[0])["speed"]) == pytest.approx(25, abs=0.01)
    paused = fields(speeds.cmd("CAMV")[0])
    assert paused["paused"] == "true" and "accel" in paused


def test_camv_unknown_without_a_camera(hook: Hook) -> None:
    hook.load_mission()
    hook.run(1.0)
    assert hook.cmd("CAMV")[0].startswith("CAMV unknown")
    hook.run(0.5)
    assert hook.last_state()["camv"] == "-"


def test_locmd_after_reports_the_camera_speed(speeds: Hook) -> None:
    speeds.lua.execute("MOCK.cam_v.x = 10; DCS.dispatchDigitalAction = function() end")
    speeds.run(1.0)
    speeds.cmd("DIGITAL 1234")
    speeds.clear()
    speeds.run(1.0)
    after = [s for s in speeds.sent() if s.startswith("LOCMD-AFTER")]
    assert "camv=10.00 camfwd=10.00" in after[0]


def mover_lines(replies: list[str]) -> dict[str, dict[str, str]]:
    """MOV lines by unit name or weapon name."""
    out = {}
    for line in replies:
        if line.startswith("MOV "):
            unit = line.split('unit="', 1)[1].split('"', 1)[0]
            name = fields(line)["name"]
            out[name if unit in ("nil", "") else unit] = fields(line) | {"line": line}  # weapons have no unit
    return out


def test_track_measures_aircraft_helicopter_and_missile_speeds(speeds: Hook) -> None:
    assert speeds.cmd("TRACK on") == ["TRACK on"]
    speeds.run(8.0)
    replies = speeds.cmd("MOVERS")
    head = replies[0]
    assert head.startswith("MOVERS listed=3 plane=1 heli=1 air=0 weapon=1 paused=false")
    assert "weapon_types=4/4/5/7=1" in head
    movers = mover_lines(replies)
    assert set(movers) == {"Viper 1-1", "Hokum 1-1", "AIM-120C"}  # the truck is neither
    assert movers["Viper 1-1"]["kind"] == "plane"
    assert movers["Hokum 1-1"]["kind"] == "heli"
    assert movers["AIM-120C"]["kind"] == "weapon"
    assert "speed=200.0 m/s 389 kt 720 km/h" in movers["Viper 1-1"]["line"]
    assert "need=" not in movers["Viper 1-1"]["line"]  # no time acceleration reported by this mock
    assert "speed=50.0 m/s" in movers["Hokum 1-1"]["line"]
    assert "speed=600.0 m/s" in movers["AIM-120C"]["line"]
    assert 'group="Viper"' in movers["Viper 1-1"]["line"]
    assert movers["Viper 1-1"]["human"] == "true"
    assert movers["AIM-120C"]["type"] == "4/4/5/7"
    assert replies[-1] == "MOVERS end"
    assert "ballistic" in list(speeds.mock.args.values())


def test_a_weapon_is_attributed_to_the_nearest_aircraft_of_its_side(speeds: Hook) -> None:
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    movers = mover_lines(speeds.cmd("MOVERS"))
    assert movers["AIM-120C"]["line"].endswith("from=Viper 1-1/Viper")
    # Still the same later, when the shooter is far away.
    speeds.run(20.0)
    movers = mover_lines(speeds.cmd("MOVERS"))
    assert movers["AIM-120C"]["line"].endswith("from=Viper 1-1/Viper")


def test_a_weapon_with_no_aircraft_near_has_no_origin(speeds: Hook) -> None:
    speeds.lua.execute("MOCK.cam0.x = 0")
    speeds.lua.execute(r"""
        local f = Export.LoGetWorldObjects
        Export.LoGetWorldObjects = function(kind)
            local out = f(kind)
            if kind ~= "ballistic" then out[0x1001].Coalition = "Enemies" end  -- not the missile's side
            return out
        end
    """)
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    assert mover_lines(speeds.cmd("MOVERS"))["AIM-120C"]["line"].endswith("from=-")


def test_movers_say_what_camera_speed_keeps_up_at_the_current_acceleration(speeds: Hook) -> None:
    speeds.lua.execute("Export.LoGetModelTimeAcceleration = function() return 0.25 end")
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    movers = mover_lines(speeds.cmd("MOVERS"))
    assert movers["Viper 1-1"]["need"] == "50.0"  # 200 m/s of model time at a quarter of real time
    assert movers["AIM-120C"]["need"] == "150.0"
    assert fields(speeds.cmd("CAMV")[0])["accel"] == "0.250"


def test_movers_while_paused_keep_the_last_speed_and_say_how_old_it_is(speeds: Hook) -> None:
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    speeds.cmd("PAUSE")
    speeds.run(3.0)
    replies = speeds.cmd("MOVERS")
    assert "paused=true" in replies[0]
    viper = mover_lines(replies)["Viper 1-1"]
    assert "speed=200.0 m/s" in viper["line"]
    assert float(viper["age"].rstrip("s")) == pytest.approx(0.2, abs=0.25)  # the last sample before the pause


def test_movers_sorted_by_distance_to_the_camera_and_limited_by_radius(speeds: Hook) -> None:
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    replies = speeds.cmd("MOVERS")
    dists = [float(fields(r)["dist"]) for r in replies if r.startswith("MOV ")]
    assert dists == sorted(dists) and len(dists) == 3
    replies = speeds.cmd("MOVERS 3000")
    assert replies[0].startswith("MOVERS listed=2 ")
    assert "radius=3000" in replies[0]


def test_movers_need_tracking(speeds: Hook) -> None:
    assert speeds.cmd("MOVERS")[0].startswith("MOVERS tracking is off")
    speeds.cmd("TRACK on")
    speeds.cmd("TRACK off")
    assert speeds.cmd("TRACK")[0].startswith("TRACK off samples=0")
    assert speeds.cmd("TRACK maybe") == ["ERR TRACK needs on or off"]


def test_a_jump_is_not_a_speed(speeds: Hook) -> None:
    speeds.cmd("TRACK on")
    speeds.run(2.0)
    speeds.lua.execute("MOCK.m = MOCK.m + 100")  # position moves 20 km between two samples
    speeds.run(0.5)
    movers = mover_lines(speeds.cmd("MOVERS"))
    assert "speed=200.0 m/s" in movers["Viper 1-1"]["line"]  # then 200 m/s again after the jump
    speeds.cmd("TRACK off")
    speeds.cmd("TRACK on")
    speeds.run(0.1)
    speeds.lua.execute("MOCK.m = MOCK.m + 1000")
    speeds.run(0.3)
    line = mover_lines(speeds.cmd("MOVERS"))["Viper 1-1"]["line"]
    assert "speed=" in line


def test_weapons_through_the_export_state(hook: Hook) -> None:
    # No Export.LoGetWorldObjects in this state: the export state's copy is called as
    # LoGetWorldObjects('ballistic') and its answer parsed.
    hook.lua.execute(WORLD7 + r"""
        local getters = { LoGetCameraPosition = Export.LoGetCameraPosition, LoGetWorldObjects = Export.LoGetWorldObjects }
        Export.LoGetCameraPosition, Export.LoGetWorldObjects = nil, nil
        net = { dostring_in = function(state, code)
            if state ~= "export" then return "", false end
            local f = assert(loadstring(code))
            setfenv(f, setmetatable({}, { __index = function(_, k) return getters[k] or _G[k] end }))
            return f(), true
        end }
    """)
    hook.load_mission()
    hook.cmd("TRACK on")
    hook.run(8.0)
    assert list(hook.mock.args.values()).count("ballistic") > 0
    movers = mover_lines(hook.cmd("MOVERS"))
    assert movers["AIM-120C"]["kind"] == "weapon"
    assert "speed=600.0 m/s" in movers["AIM-120C"]["line"]
    assert movers["Hokum 1-1"]["kind"] == "heli"


def test_tracking_restarts_with_the_track(speeds: Hook) -> None:
    speeds.cmd("TRACK on")
    speeds.run(8.0)
    speeds.lua.execute("MOCK.m = 0")  # the track starts again
    speeds.run(0.5)
    replies = speeds.cmd("MOVERS")
    assert replies[0].startswith("MOVERS listed=2 plane=1 heli=1 air=0 weapon=0")  # the missile is not fired yet


def test_findcam_lists_camera_speed_bindings(hook: Hook, tmp_path: Path) -> None:
    (tmp_path / "Config" / "Input" / "View").mkdir(parents=True)
    (tmp_path / "Config" / "Input" / "View" / "keyboard.lua").write_text(
        "  {combos = {{key = 'Num*', reformers = {'LAlt'}}}, down = iCommandViewCamForward, "
        "name = _('F11 Camera Moving Forward')},\n"
        "{down = iCommandViewCameraSpeedUp, name = _('Camera speed up')},\n"
        "{down = iCommandViewAir, name = _('F2 view')},\n"
        "{combos = {{key = 'MOUSE_WHEEL_UP'}}, down = iCommandViewCamWheelFaster, name = _('Camera F11 wheel')},\n"
        "{down = iCommandPlaneGear, name = _('Gear')},\n")
    (tmp_path / "Config" / "View").mkdir(parents=True)
    (tmp_path / "Config" / "View" / "View.lua").write_text("Cameras = {\n  speed = 5.0,\n  fov = 60,\n}\n")
    (tmp_path / "Config" / "options.lua").write_text("speed = 1\ncamera = 'x'\n")
    fake_install(hook, tmp_path)
    hook.load_mission()
    replies = hook.cmd("FINDCAM")
    assert ("CAMCMD Config\\Input\\View\\keyboard.lua:1 {combos = {{key = 'Num*', reformers = "
            "{'LAlt'}}}, down = iCommandViewCamForward, name = _('F11 Camera Moving Forward')},") in replies
    assert ("CAMCMD Config\\Input\\View\\keyboard.lua:2 {down = iCommandViewCameraSpeedUp, "
            "name = _('Camera speed up')},") in replies
    assert any(r.startswith("CAMCMD Config\\Input\\View\\keyboard.lua:4 {combos = {{key = 'MOUSE_WHEEL_UP'") for r in replies)
    assert "CAMCMD Config\\View\\View.lua:2 speed = 5.0," in replies
    assert not any("iCommandViewAir" in r or "Gear" in r or "options.lua" in r or "fov" in r for r in replies)
    assert replies[-1].startswith("FINDCAM done: 3 lua files, 4 hits")


def test_findcam_without_lfs(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("FINDCAM") == ["FINDCAM unavailable: no lfs"]
