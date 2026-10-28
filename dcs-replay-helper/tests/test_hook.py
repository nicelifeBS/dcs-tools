"""Runs the DCS hook (src/replay_helper/hook/ReplayHelper.lua) in Lua 5.1 against a mocked DCS hooks environment."""

from __future__ import annotations

import pytest

pytest.importorskip("lupa.lua51")

from pathlib import Path  # noqa: E402

from lua_harness import Hook  # noqa: E402

HOOK = Path(__file__).resolve().parents[1] / "src" / "replay_helper" / "hook" / "ReplayHelper.lua"


def fields(line: str) -> dict[str, str]:
    return dict(kv.split("=", 1) for kv in line.split()[1:])


@pytest.fixture
def hook() -> Hook:
    h = Hook(HOOK)
    # DCS reports the commanded acceleration through Export; the tests set MOCK.accel.
    h.lua.execute("MOCK.accel = 1; Export = { LoGetModelTimeAcceleration = function() return MOCK.accel end }")
    return h


def test_loads_and_registers_callbacks(hook: Hook) -> None:
    assert "loaded 0.3.0 (callbacks registered)" in hook.logs()


def test_silent_outside_a_mission(hook: Hook) -> None:
    hook.run(1.0)
    assert hook.sent() == []


def test_hello_and_state(hook: Hook) -> None:
    hook.load_mission()
    assert hook.sent()[0] == "HELLO 0.3.0"
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
    assert hook.cmd("PING") == ["PONG 0.3.0"]


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


# --- speed and focus (DCS.dispatchDigitalAction) ----------------------------------------
# A mock world that behaves as DCS did in the spike (SPIKE.md rounds 4-6). The camera starts in
# the player's cockpit. Action 8 (F2) from there shows the player's aircraft, 30 m behind it
# along +x; in F2 it steps to the next aircraft by id. A ground unit is never in the cycle. The
# MiG is 4 km ahead on the same line as the others, so it is near every camera's line of sight.
WORLD = """
MOCK.actions = {}
MOCK.units = {
    [0x1003500] = { Name = "MiG-29A", UnitName = "Red-1", Type = { level1 = 1 }, Position = { x = 5000, y = 3000, z = 0 } },
    [0x1006f00] = { Name = "F-4E-45MC", UnitName = "fubar 1-1 | nicelife", Type = { level1 = 1 },
                    Position = { x = 1000, y = 3000, z = 40 } },
    [0x1005000] = { Name = "A-10C_2", UnitName = "Hog-1", Type = { level1 = 1 }, Position = { x = 1000, y = 3000, z = 0 } },
    [0x1000100] = { Name = "Ural-375", UnitName = "Truck", Type = { level1 = 2 }, Position = { x = 990, y = 0, z = 10 } },
}
MOCK.cycle, MOCK.view = { 0x1003500, 0x1005000, 0x1006f00 }, nil
local AXES = { x = { x = 1, y = 0, z = 0 }, y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }
local function look_at(id)
    local p = MOCK.units[id].Position
    MOCK.cam = { p = { x = p.x - 30, y = p.y, z = p.z }, x = AXES.x, y = AXES.y, z = AXES.z }
end
MOCK.cam = { p = { x = 1001, y = 3000, z = 40 }, x = AXES.x, y = AXES.y, z = AXES.z }  -- cockpit
DCS.dispatchDigitalAction = function(id)
    table.insert(MOCK.actions, id)
    if id == 53 then MOCK.accel = MOCK.accel < 1 and MOCK.accel * 2 or MOCK.accel + 1
    elseif id == 191 then MOCK.accel = MOCK.accel <= 1 and MOCK.accel / 2 or MOCK.accel - 1
    elseif id == 246 then MOCK.accel = 1
    elseif id == 8 then
        if MOCK.view == nil then MOCK.view = 3 else MOCK.view = MOCK.view % #MOCK.cycle + 1 end
        look_at(MOCK.cycle[MOCK.view])
    end
end
Export.LoGetCameraPosition = function() return MOCK.cam end
Export.LoGetWorldObjects = function() return MOCK.units end
"""


@pytest.fixture
def world(hook: Hook) -> Hook:
    hook.lua.execute(WORLD)
    hook.load_mission()
    return hook


def replies(hook: Hook, seconds: float) -> list[str]:
    hook.clear()
    hook.run(seconds)
    return [s for s in hook.sent() if not s.startswith("STATE ")]


def test_speed_steps_through_dcs_actions(world: Hook) -> None:
    for step, accel in (("UP", 2), ("up", 3), ("DOWN", 2), ("NORMAL", 1), ("DOWN", 0.5)):
        assert world.cmd(f"SPEED {step}") == []
        assert world.mock.accel == accel
    assert list(world.mock.actions.values()) == [53, 53, 191, 246, 191]
    assert world.cmd("SPEED FAST") == ["ERR SPEED needs UP, DOWN or NORMAL"]


def test_speed_without_digital_actions(hook: Hook) -> None:
    hook.load_mission()
    assert hook.cmd("SPEED UP") == ["ERR SPEED unavailable: no DCS.dispatchDigitalAction"]


def test_focus_steps_f2_from_the_cockpit_to_the_aircraft(world: Hook) -> None:
    assert world.cmd(f"FOCUS {0x1005000}") == []
    # cockpit -> F2 on the player's F-4E -> next by id wraps to the MiG -> the A-10C
    assert replies(world, 1.0) == [f"FOCUSED id={0x1005000} steps=3"]
    assert list(world.mock.actions.values()) == [8, 8, 8]


def test_focus_when_already_in_view_sends_nothing(world: Hook) -> None:
    world.cmd(f"FOCUS {0x1005000}")
    world.run(1.0)
    world.lua.execute("MOCK.actions = {}")
    assert world.cmd(f"FOCUS {0x1005000}") == [f"FOCUSED id={0x1005000} steps=0"]
    assert list(world.mock.actions.values()) == []


def test_focus_by_unit_name_when_the_id_is_unknown(world: Hook) -> None:
    world.cmd("FOCUS 12345 Red-1")
    assert replies(world, 1.0) == [f"FOCUSED id={0x1003500} steps=2"]


def test_focus_on_a_unit_f2_never_reaches(world: Hook) -> None:
    world.cmd(f"FOCUS {0x1000100}")  # the truck
    assert replies(world, 2.0) == [f"FOCUS-FAILED id={0x1000100} reason=cycled"]


def test_focus_refusals(world: Hook) -> None:
    assert world.cmd("FOCUS 777") == ["FOCUS-FAILED id=777 reason=not_found"]
    assert world.cmd("FOCUS 777 Nobody") == ["FOCUS-FAILED id=777 reason=not_found"]
    assert world.cmd("FOCUS x") == ["ERR FOCUS needs a DCS id"]


def test_focus_without_a_camera(world: Hook) -> None:
    world.lua.execute("Export.LoGetCameraPosition = nil")
    assert world.cmd(f"FOCUS {0x1005000}") == [f"FOCUS-FAILED id={0x1005000} reason=no_camera"]


def test_focus_without_world_objects(hook: Hook) -> None:
    hook.lua.execute(WORLD + "Export.LoGetWorldObjects = nil")
    hook.load_mission()
    assert hook.cmd(f"FOCUS {0x1005000}") == [f"FOCUS-FAILED id={0x1005000} reason=unavailable"]


def test_focus_is_cancelled_by_a_new_one_or_by_a_bare_focus(world: Hook) -> None:
    world.cmd(f"FOCUS {0x1000100}")
    assert world.cmd(f"FOCUS {0x1005000}")[0] == f"FOCUS-FAILED id={0x1000100} reason=cancelled"
    assert world.cmd("FOCUS") == [f"FOCUS-FAILED id={0x1005000} reason=cancelled"]
    assert world.cmd("FOCUS") == []
    assert replies(world, 1.0) == []


def test_focus_target_lost_meanwhile(world: Hook) -> None:
    world.cmd(f"FOCUS {0x1005000}")
    world.lua.execute("MOCK.units[0x1005000] = nil")
    assert replies(world, 0.5) == [f"FOCUS-FAILED id={0x1005000} reason=not_found"]


def test_focus_ends_with_the_mission(world: Hook) -> None:
    world.cmd(f"FOCUS {0x1000100}")
    world.clear()
    world.mock.cb.onSimulationStop()
    assert world.sent() == [f"FOCUS-FAILED id={0x1000100} reason=mission_end"]


def test_focus_looks_again_while_the_camera_swings_onto_an_aircraft(world: Hook) -> None:
    # After each F2 step, the first camera reading points 30 deg away: nothing in view yet.
    world.lua.execute("""
        local inner = DCS.dispatchDigitalAction
        DCS.dispatchDigitalAction = function(id) inner(id); MOCK.swinging = true end
        local get = Export.LoGetCameraPosition
        Export.LoGetCameraPosition = function()
            local cam = get()
            if MOCK.swinging and MOCK.view ~= nil then
                MOCK.swinging = false
                return { p = cam.p, x = { x = 0.866, y = 0.5, z = 0 } }
            end
            return cam
        end
    """)
    world.cmd(f"FOCUS {0x1005000}")
    assert replies(world, 2.0) == [f"FOCUSED id={0x1005000} steps=3"]  # no step skipped past it
    assert list(world.mock.actions.values()) == [8, 8, 8]


# --- free camera speed and object speeds ----------------------------------------------------
# A Viper flying 200 m/s along +x with a Hokum at 50 m/s and a missile at 600 m/s; the camera
# looks along +x or -x and flies at MOCK.camv m/s along its view axis (model time).
FLYERS = """
MOCK.camv, MOCK.look = 0, 1
MOCK.units = {
    [10] = { Name = "F-16C_50", UnitName = "Viper 1-1 | Ace", GroupName = "Viper", Coalition = "blue",
             Flags = { Human = true }, Type = { level1 = 1, level2 = 1 }, Position = { x = 1000, y = 3000, z = 0 } },
    [11] = { Name = "Mi-24P", UnitName = "Hokum 1-1", GroupName = "Hokum", Coalition = "red",
             Type = { level1 = 1, level2 = 2 }, Position = { x = 1000, y = 2000, z = 500 } },
    [12] = { Name = "Ural-375", UnitName = "Truck", Type = { level1 = 2 }, Position = { x = 0, y = 0, z = 0 } },
}
MOCK.weapons = { [20] = { Name = "AIM-120C", Coalition = "blue", Type = { level1 = 4, level2 = 4 },
                          Position = { x = 1000, y = 3500, z = 0 } } }
MOCK.cam0 = { x = 0, y = 3000, z = -100 }
Export.LoGetWorldObjects = function(kind)
    if kind == "ballistic" then return MOCK.weapons end
    return MOCK.units
end
Export.LoGetCameraPosition = function()
    return { p = { x = MOCK.cam0.x, y = MOCK.cam0.y, z = MOCK.cam0.z },
             x = { x = MOCK.look, y = 0, z = 0 }, y = { x = 0, y = 1, z = 0 }, z = { x = 0, y = 0, z = 1 } }
end
-- every frame: units and the camera move for the model time that passed
function MOCK.run(seconds, speed, fps)
    local dt = 1 / fps
    for _ = 1, math.floor(seconds * fps + 0.5) do
        local m0 = MOCK.m
        MOCK.r = MOCK.r + dt
        if not MOCK.paused then MOCK.m = MOCK.m + dt * speed end
        local d = MOCK.m - m0
        for id, v in pairs({ [10] = 200, [11] = 50 }) do
            if MOCK.units[id] then MOCK.units[id].Position.x = MOCK.units[id].Position.x + v * d end
        end
        MOCK.weapons[20].Position.x = MOCK.weapons[20].Position.x + 600 * d
        MOCK.cam0.x = MOCK.cam0.x + MOCK.look * MOCK.camv * d
        MOCK.cb.onSimulationFrame()
    end
end
"""


@pytest.fixture
def flyers(hook: Hook) -> Hook:
    hook.lua.execute(FLYERS)
    hook.load_mission()
    return hook


def objects(hook: Hook) -> dict[int, dict[str, str]]:
    lines = hook.cmd("OBJECTS")
    assert lines[-1].startswith("OBJ-END")
    return {int(f["id"]): f for f in (fields(line) for line in lines[:-1])}


def test_objects_need_tracking(flyers: Hook) -> None:
    assert flyers.cmd("OBJECTS") == ["ERR OBJECTS needs TRACK on"]
    assert flyers.cmd("TRACK maybe") == ["ERR TRACK needs on or off"]


def test_objects_list_aircraft_helicopters_and_weapons_with_speeds(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(2.0)
    objs = objects(flyers)
    assert set(objs) == {10, 11, 20}  # the truck is none of the three
    assert objs[10]["kind"] == "plane" and objs[11]["kind"] == "heli" and objs[20]["kind"] == "weapon"
    assert float(objs[10]["speed"]) == pytest.approx(200, abs=0.5)
    assert float(objs[11]["speed"]) == pytest.approx(50, abs=0.5)
    assert float(objs[20]["speed"]) == pytest.approx(600, abs=0.5)
    assert objs[10]["unit"] == "Viper%201-1%20%7C%20Ace" and objs[10]["group"] == "Viper"
    assert objs[10]["human"] == "true" and objs[11]["human"] == "false"
    assert objs[10]["coalition"] == "blue" and objs[20]["unit"] == "-"


def test_object_speed_along_the_camera_view_axis(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(2.0)
    objs = objects(flyers)
    assert float(objs[10]["along"]) == pytest.approx(200, abs=0.5)  # looking along the flight path
    assert float(objs[10]["side"]) == pytest.approx(0, abs=0.5)
    assert float(objs[11]["along"]) == pytest.approx(50, abs=0.5)
    flyers.lua.execute("MOCK.look = -1")  # turned round: the camera must fly backward to keep up
    objs = objects(flyers)
    assert float(objs[10]["along"]) == pytest.approx(-200, abs=0.5)
    assert objs[10]["ahead"] != "-"


def test_objects_are_nearest_first_and_a_radius_filters(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(1.0)
    lines = flyers.cmd("OBJECTS")
    dists = [float(fields(line)["dist"]) for line in lines[:-1]]
    assert dists == sorted(dists)
    near = flyers.cmd(f"OBJECTS {dists[0] + 1:.0f}")
    assert len(near) == 2 and fields(near[-1])["total"] == "1"


def test_object_speed_is_kept_through_a_pause_and_aged(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(2.0)
    flyers.cmd("PAUSE")
    flyers.run(3.0)
    obj = objects(flyers)[10]
    assert float(obj["speed"]) == pytest.approx(200, abs=0.5)
    assert float(obj["age"]) < 0.5  # model time stood still, so the measurement is as fresh as it was


def test_speed_unknown_until_the_object_has_moved(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(0.05)
    assert objects(flyers)[10]["speed"] == "-"


def test_a_jump_is_not_a_speed(flyers: Hook) -> None:
    flyers.cmd("TRACK on")
    flyers.run(1.0)
    flyers.lua.execute("MOCK.units[10].Position.x = MOCK.units[10].Position.x + 90000")
    flyers.run(0.25)
    speed = objects(flyers)[10]["speed"]
    assert speed == "-" or float(speed) == pytest.approx(200, abs=1)


def test_camera_speed_in_state_is_per_model_second_and_signed(flyers: Hook) -> None:
    flyers.lua.execute("MOCK.camv = 40")
    flyers.run(1.5)
    assert float(flyers.last_state()["cam"]) == pytest.approx(40, abs=0.5)
    flyers.lua.execute("MOCK.accel = 2")
    flyers.run(1.5, speed=2.0)
    assert float(flyers.last_state()["cam"]) == pytest.approx(40, abs=0.5)  # not 80
    flyers.lua.execute("MOCK.camv = -12")
    flyers.run(1.5, speed=2.0)
    assert float(flyers.last_state()["cam"]) == pytest.approx(-12, abs=0.5)


def test_camera_speed_unknown_without_a_camera(hook: Hook) -> None:
    hook.load_mission()
    hook.run(1.0)
    assert hook.last_state()["cam"] == "-"


def test_a_view_change_is_not_a_camera_speed(flyers: Hook) -> None:
    flyers.run(1.0)
    flyers.lua.execute("MOCK.cam0.x = MOCK.cam0.x + 90000")
    flyers.run(0.3)
    assert flyers.last_state()["cam"] == "-" or abs(float(flyers.last_state()["cam"])) < 5000


def test_watch_puts_the_target_speed_in_state(flyers: Hook) -> None:
    assert flyers.cmd("WATCH 10") == []
    flyers.run(2.0)
    s = flyers.last_state()
    assert s["tgt"] == "10"
    assert float(s["tgt_along"]) == pytest.approx(200, abs=0.5)
    assert float(s["tgt_side"]) == pytest.approx(0, abs=0.5)
    flyers.lua.execute("MOCK.look = -1")
    flyers.run(0.5)
    assert float(flyers.last_state()["tgt_along"]) == pytest.approx(-200, abs=0.5)
    flyers.cmd("WATCH")
    flyers.run(0.5)
    assert "tgt" not in flyers.last_state()


def test_watch_of_an_object_that_is_gone(flyers: Hook) -> None:
    flyers.cmd("WATCH 10")
    flyers.run(1.0)
    flyers.lua.execute("MOCK.units[10] = nil")
    flyers.run(1.0)
    s = flyers.last_state()
    assert s["tgt"] == "10" and s["tgt_along"] == "-"
    assert flyers.cmd("WATCH x") == ["ERR WATCH needs a DCS id"]


def test_tracking_stops_with_the_mission_and_a_restart(flyers: Hook) -> None:
    flyers.cmd("WATCH 10")
    flyers.run(3.0)
    flyers.lua.execute("MOCK.m = 0")  # the track starts over
    flyers.run(0.05)
    assert flyers.last_state()["tgt_along"] == "-"  # speeds are measured afresh
    flyers.mock.cb.onSimulationStop()
    flyers.mock.cb.onMissionLoadEnd()
    flyers.mock.cb.onSimulationFrame()
    assert flyers.cmd("OBJECTS") == ["ERR OBJECTS needs TRACK on"]
