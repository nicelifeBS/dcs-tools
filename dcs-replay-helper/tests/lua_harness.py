"""Loads a DCS hook script into Lua 5.1 (via lupa) with a mocked DCS hooks environment."""

from __future__ import annotations

from pathlib import Path

from lupa import lua51

HOOK_DIR = Path(__file__).resolve().parents[1] / "hook"

# The hooks state as a hook sees it: DCS, log, LuaSocket (via package.preload) and lfs.
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
    def __init__(self, path: Path) -> None:
        self.lua = lua51.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCK_ENV)
        self.mock = self.lua.globals().MOCK
        self.lua.execute(path.read_text(encoding="utf-8"))

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
