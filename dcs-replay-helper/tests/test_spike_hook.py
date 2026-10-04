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
    assert any("loaded spike-5 (callbacks registered)" in line for line in hook.logs())


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_state_after_mission_load(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO spike-5"
    hook.run(0.5)
    state = hook.last_state()
    assert state["start_tod"] == "59400"
    assert state["date"] == "2018-02-01"
    assert state["track"] == "true"
    assert float(state["t"]) == pytest.approx(0.5, abs=0.1)  # STATE goes out every 0.1 s


def test_ping(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("PING") == ["PONG spike-5"]


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
    assert replies[0] == "PROBE begin spike-5"
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


# Round 4: a mock world for the camera, behaving as DCS did in a replay. The camera starts in
# the lead's cockpit. F2 (8) moves it 30 m behind a blue aircraft, looking along +x; next (181)
# and previous (180) step through the blue aircraft in id order. dispatchDigitalAction and
# LoSetCommand in the export state switch views; Export.LoSetCommand in the hooks state is
# accepted but does nothing. The two blue A-10Cs fly 40 m apart; a red aircraft and a ground
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
    if id == 8 and MOCK.view == nil then
        MOCK.view = 2  -- the player's own aircraft
    elseif id == 8 or id == 181 then
        MOCK.view = MOCK.view % n + 1
    elseif id == 180 then
        MOCK.view = (MOCK.view - 2) % n + 1
    else
        return
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


def test_focus_steps_to_the_target(world: Hook) -> None:
    start = world.cmd("FOCUS 0x1005000")
    assert start[0].startswith("FOCUS start digital next target id=16797696/0x1005000")
    steps = focus_lines(world)
    assert steps[0].startswith("FOCUS-STEP 0 digital viewed id=16799488/0x1005700")  # F2: own aircraft
    assert steps[1].startswith("FOCUS-STEP 1 digital viewed id=16797696/0x1005000")
    assert steps[2].startswith("FOCUS-DONE ok target=0x1005000 steps=1 time=0.3")
    assert steps[2].endswith("visited=0x1005700")
    assert list(world.mock.commands.values()) == [8, 181]


def test_focus_through_the_export_state_and_backwards(world: Hook) -> None:
    assert world.cmd("FOCUS A-10C #001 prev export")[0].startswith("FOCUS start export prev target id=16797696")
    assert focus_lines(world)[-1].startswith("FOCUS-DONE ok target=0x1005000 steps=1")
    assert list(world.mock.commands.values()) == [8, 180]


def test_focus_starts_stepping_when_a_unit_is_already_in_view(world: Hook) -> None:
    world.cmd("FOCUS 0x1005000")
    focus_lines(world)
    world.lua.execute("MOCK.commands = {}")
    lines = world.cmd("FOCUS fubar") + focus_lines(world)  # on the wingman already: no F2, just next
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005700 steps=1")
    assert list(world.mock.commands.values()) == [181]
    world.lua.execute("MOCK.commands = {}")
    lines = world.cmd("FOCUS fubar")  # already there: done in the same frame
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005700 steps=0")
    assert list(world.mock.commands.values()) == []


def test_focus_by_decimal_id_and_unknown_name(world: Hook) -> None:
    assert world.cmd("FOCUS 16797696")[0].startswith("FOCUS start digital next target id=16797696/0x1005000")
    assert world.cmd("FOCUS nobody") == ["FOCUS no unit matches nobody"]


def test_focus_gives_up_after_a_full_cycle(world: Hook) -> None:
    world.cmd("FOCUS Frogfoot")  # red: not in the F2 cycle
    done = [s for s in focus_lines(world, 2.0) if s.startswith("FOCUS-DONE")]
    assert done == ["FOCUS-DONE fail reason=cycled target=0x1006000 steps=2 time=0.45 "
                    "visited=0x1005700,0x1005000"]


def test_focus_through_the_hooks_state_never_gets_there(world: Hook) -> None:
    world.cmd("FOCUS 0x1005000 hooks")
    done = [s for s in focus_lines(world, 15.0) if s.startswith("FOCUS-DONE")]
    assert len(done) == 1
    assert done[0].startswith("FOCUS-DONE fail reason=max_steps target=0x1005000 steps=80 ")
    assert done[0].endswith("visited=" + ",".join(["none"] * 81))


def test_focus_can_be_cancelled(world: Hook) -> None:
    world.cmd("FOCUS Frogfoot")
    assert world.cmd("FOCUS")[0].startswith("FOCUS-DONE cancelled target=0x1006000 steps=0")
    assert world.cmd("FOCUS") == ["FOCUS nothing to cancel"]


def test_focus_without_a_camera(hook: Hook) -> None:
    hook.lua.execute(WORLD + "Export.LoGetCameraPosition = nil; net = nil")
    hook.load_mission()
    assert hook.cmd("CAM") == ["CAM unavailable: no camera position (LoGetCameraPosition)"]
    hook.cmd("FOCUS 0x1005000")
    done = [s for s in focus_lines(hook, 0.5) if s.startswith("FOCUS-DONE")]
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
    hook.cmd("FOCUS A-10C #001")
    lines = focus_lines(hook)
    assert lines[1].startswith('FOCUS-STEP 1 digital viewed id=16797696/0x1005000 A-10C_2 unit="A-10C #001"')
    assert lines[-1].startswith("FOCUS-DONE ok target=0x1005000")
