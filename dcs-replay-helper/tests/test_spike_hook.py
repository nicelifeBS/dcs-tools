"""Runs hook/spike/ReplayHelperSpike.lua in Lua 5.1 against a mocked DCS hooks environment."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

lua51 = pytest.importorskip("lupa.lua51")

HOOK = Path(__file__).resolve().parents[1] / "hook" / "spike" / "ReplayHelperSpike.lua"

# The hooks state as the spike sees it: DCS, log, LuaSocket (via package.preload) and lfs.
# MOCK.run advances real time at a given fps; model time follows at `speed` unless paused.
MOCK_ENV = r"""
MOCK = { m = 0, r = 0, paused = false, track = true, sent = {}, inbox = {}, logs = {}, cb = nil }

log = { INFO = 1, write = function(tag, level, msg) table.insert(MOCK.logs, msg) end }

local udp = {}
udp.__index = udp
function udp:settimeout() return 1 end
function udp:setpeername() return 1 end
function udp:setsockname() return 1 end
function udp:send(s) table.insert(MOCK.sent, s); return #s end
function udp:receive()
    if #MOCK.inbox == 0 then return nil, "timeout" end
    return table.remove(MOCK.inbox, 1)
end
package.preload["socket"] = function() return { udp = function() return setmetatable({}, udp) end } end

DCS = {
    getModelTime = function() return MOCK.m end,
    getRealTime = function() return MOCK.r end,
    getPause = function() return MOCK.paused end,
    setPause = function(p) MOCK.paused = p end,
    isTrackPlaying = function() return MOCK.track end,
    getCurrentMission = function()
        return { mission = { start_time = 59400, theatre = "Caucasus",
                             date = { Day = 1, Month = 2, Year = 2018 } } }
    end,
    setUserCallbacks = function(cb) MOCK.cb = cb end,
}

function MOCK.run(seconds, speed, fps)
    local dt = 1 / fps
    for _ = 1, math.floor(seconds * fps + 0.5) do
        MOCK.r = MOCK.r + dt
        if not MOCK.paused then MOCK.m = MOCK.m + dt * speed end
        MOCK.cb.onSimulationFrame()
    end
end

function MOCK.cmd(line)
    table.insert(MOCK.inbox, line)
    MOCK.cb.onSimulationFrame()
end
"""


class Hook:
    def __init__(self) -> None:
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_ENV)
        self.mock = self.lua.globals().MOCK
        self.lua.execute(HOOK.read_text(encoding="utf-8"))

    def sent(self) -> list[str]:
        return list(self.mock.sent.values())

    def logs(self) -> list[str]:
        return list(self.mock.logs.values())

    def clear(self) -> None:
        self.lua.execute("MOCK.sent = {}")

    def load_mission(self) -> None:
        """Load a mission and run one frame, which opens the link and sends HELLO."""
        self.mock.cb.onMissionLoadEnd()
        self.mock.cb.onSimulationFrame()

    def run(self, seconds: float, speed: float = 1.0, fps: int = 60) -> None:
        self.mock.run(seconds, speed, fps)

    def cmd(self, line: str) -> list[str]:
        self.clear()
        self.mock.cmd(line)
        return [s for s in self.sent() if not s.startswith("STATE ")]

    def last_state(self) -> dict[str, str]:
        states = [s for s in self.sent() if s.startswith("STATE ")]
        assert states, "no STATE sent"
        return dict(kv.split("=", 1) for kv in states[-1].split()[1:])


@pytest.fixture
def hook() -> Hook:
    return Hook()


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
