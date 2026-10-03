-- =====================================================================================
-- DCS Replay Helper -- milestone 0 spike hook
-- =====================================================================================
-- Install as:  <Saved Games>\DCS\Scripts\Hooks\ReplayHelperSpike.lua   (restart DCS)
--
-- Purpose: find out what the hooks Lua state can see and do while a .trk replay plays,
-- before the real hook is written. Everything it learns goes to dcs.log under the tag
-- REPLAYHELPER, and to tools/spike_client.py over UDP:
--
--   hook -> client   127.0.0.1:47810   STATE at ~10 Hz, plus replies and reports
--   client -> hook   127.0.0.1:47811   one command per datagram
--
-- Commands:
--   PING                     -> PONG <version>
--   PAUSE | RESUME           DCS.setPause(true|false)
--   ARM <model t>            pause the sim on the first frame at or past t (checked every frame)
--   DISARM                   forget the armed stop
--   PROBE                    report which APIs, globals and Lua states are reachable
--   FINDCMDS [subdir]        scan the DCS install for time-acceleration iCommand ids
--   LOCMD <id> [value]       call LoSetCommand from this (hooks) state
--   LOCMDX <id> [value]      call LoSetCommand inside the export state via net.dostring_in
--
-- Safety: this runs inside DCS's GUI state. Any error at file scope would silently drop the
-- whole hook, and an error in a callback can break the menus, so every DCS call is pcall'd
-- and nothing runs outside a mission.
-- =====================================================================================

local TAG     = "REPLAYHELPER"
local VERSION = "spike-1"

local HOST       = "127.0.0.1"
local STATE_PORT = 47810   -- hook -> client
local CMD_PORT   = 47811   -- client -> hook

local STATE_INTERVAL     = 0.1    -- real seconds between STATE packets
local SPEED_WINDOW       = 0.5    -- real seconds per speed sample
local STOPPED_RATIO      = 0.004  -- below this the sim is paused, not in slow motion (1/64x = 0.0156)
local MAX_CMDS_PER_FRAME = 16

-- -------------------------------------------------------------------------------------
-- helpers
-- -------------------------------------------------------------------------------------
local function say(msg)
    pcall(log.write, TAG, log.INFO, tostring(msg))
end

local function sayf(fmt, ...)
    local ok, msg = pcall(string.format, fmt, ...)
    say(ok and msg or fmt)
end

-- Text that goes on the wire or into the log stays on one line.
local function oneline(v)
    return (tostring(v):gsub("[\r\n]+", " "))
end

-- Call f if it is a function; nil on any failure.
local function call(f, ...)
    if type(f) ~= "function" then return nil end
    local ok, v = pcall(f, ...)
    if ok then return v end
    return nil
end

local function dcs_fn(name)
    if type(DCS) ~= "table" then return nil end
    return DCS[name]
end

local function install_root()
    local root = "."
    if type(lfs) == "table" then root = call(lfs.currentdir) or "." end
    if not root:match("[/\\]$") then root = root .. "\\" end
    return root
end

-- -------------------------------------------------------------------------------------
-- UDP link
-- -------------------------------------------------------------------------------------
local link = { tried = false, out = nil, inp = nil }

local function require_socket()
    local ok, mod = pcall(require, "socket")
    if ok and type(mod) == "table" then return mod end
    -- package.path only knows LuaSocket once some other script has added it.
    local root = install_root()
    package.path  = package.path  .. ";" .. root .. "LuaSocket\\?.lua"
    package.cpath = package.cpath .. ";" .. root .. "LuaSocket\\?.dll"
    ok, mod = pcall(require, "socket")
    if ok and type(mod) == "table" then return mod end
    return nil, mod
end

local function send(line)
    if link.out then pcall(link.out.send, link.out, line) end
end

-- Send to the client and keep a copy in dcs.log.
local function report(line)
    send(line)
    say(line)
end

local function open_link()
    link.tried = true
    local socket, err = require_socket()
    if not socket then
        sayf("LuaSocket not available (%s) -- UDP link disabled", oneline(err))
        return
    end

    local ok, s = pcall(socket.udp)
    if ok and s then
        pcall(s.settimeout, s, 0)
        if pcall(s.setpeername, s, HOST, STATE_PORT) then link.out = s end
    end

    ok, s = pcall(socket.udp)
    if ok and s then
        pcall(s.settimeout, s, 0)
        local okb, res, berr = pcall(s.setsockname, s, HOST, CMD_PORT)
        if okb and res then
            link.inp = s
        else
            sayf("cannot bind command port %d (%s)", CMD_PORT, oneline(berr or res))
        end
    end

    sayf("UDP link: state -> %s:%d %s, commands <- %s:%d %s",
        HOST, STATE_PORT, link.out and "ok" or "FAILED",
        HOST, CMD_PORT, link.inp and "ok" or "FAILED")
    report("HELLO " .. VERSION)
end

-- -------------------------------------------------------------------------------------
-- sim state
-- -------------------------------------------------------------------------------------
local sim = {
    in_mission    = false,
    first_frame   = false,
    sample_m      = nil,   -- model/real time at the start of the current speed sample
    sample_r      = nil,
    raw           = nil,   -- last raw speed sample
    speed         = nil,   -- last confirmed speed (two samples agreeing within 15%)
    next_state_rt = 0,
    start_tod     = nil,   -- mission start, seconds of day (local map time)
    date          = nil,   -- YYYY-MM-DD
    theatre       = nil,
}

local stop = { target = nil }

local function model_time()
    return call(dcs_fn("getModelTime"))
end

local function read_mission_info()
    local mis = call(dcs_fn("getCurrentMission"))
    local m = type(mis) == "table" and mis.mission or nil
    if type(m) ~= "table" then return end
    sim.start_tod = tonumber(m.start_time)
    local d = m.date
    if type(d) == "table" then
        sim.date = string.format("%04d-%02d-%02d",
            tonumber(d.Year) or 0, tonumber(d.Month) or 0, tonumber(d.Day) or 0)
    end
    sim.theatre = m.theatre
end

local function reset_sim()
    sim.first_frame = true
    sim.sample_m, sim.sample_r = nil, nil
    sim.raw, sim.speed = nil, nil
    sim.next_state_rt = 0
    stop.target = nil
end

-- Speed is measured, never inferred from the keys or commands we sent.
local function measure(m, r)
    if not sim.sample_r then
        sim.sample_m, sim.sample_r = m, r
        return
    end
    local dr = r - sim.sample_r
    if dr < SPEED_WINDOW then return end

    local raw = (m - sim.sample_m) / dr
    sim.sample_m, sim.sample_r = m, r
    if raw < STOPPED_RATIO then
        sim.raw, sim.speed = raw, 0
        return
    end
    if sim.raw and sim.raw > 0 and math.abs(raw - sim.raw) <= 0.15 * sim.raw then
        sim.speed = (raw + sim.raw) / 2
    end
    sim.raw = raw
end

-- The stop line. Runs every frame, before anything is throttled: at 4x and 60 fps one
-- frame is ~0.07 s of model time, whereas a UDP round trip to the client would be ~100 ms
-- of real time.
local function check_stop(m)
    if stop.target and m >= stop.target then
        local target = stop.target
        stop.target = nil
        call(dcs_fn("setPause"), true)
        report(string.format("ARRIVED t=%.3f target=%.3f over=%.3f speed=%.3f",
            m, target, m - target, sim.speed or -1))
    end
end

-- -------------------------------------------------------------------------------------
-- probe
-- -------------------------------------------------------------------------------------
local function sorted_keys(t, want_type)
    local names = {}
    if type(t) ~= "table" then return names end
    for k, v in pairs(t) do
        if type(k) == "string" and (not want_type or type(v) == want_type) then
            names[#names + 1] = k
        end
    end
    table.sort(names)
    return names
end

local function report_list(prefix, names)
    if #names == 0 then
        report(prefix .. " (none)")
        return
    end
    local chunk = {}
    for i, name in ipairs(names) do
        chunk[#chunk + 1] = name
        if #chunk == 15 or i == #names then
            report(prefix .. " " .. table.concat(chunk, " "))
            chunk = {}
        end
    end
end

local function resolve_lo(name)
    if type(_G[name]) == "function" then return _G[name], "_G" end
    if type(_G.Export) == "table" and type(_G.Export[name]) == "function" then
        return _G.Export[name], "Export"
    end
    return nil
end

local function dostring_in(state, code)
    if type(net) ~= "table" or type(net.dostring_in) ~= "function" then
        return nil, "net.dostring_in unavailable"
    end
    local ok, res, extra = pcall(net.dostring_in, state, code)
    if not ok then return nil, res end
    return res, extra
end

local function probe()
    report("PROBE begin " .. VERSION)
    report("PROBE lua " .. tostring(_VERSION))
    report_list("PROBE DCS.fn", sorted_keys(DCS, "function"))

    for _, name in ipairs({ "Export", "LoSetCommand", "LoGetModelTime", "LoGetMissionStartTime",
                            "LoGetWorldObjects", "LoGetSelfData", "net", "timer", "lfs", "socket" }) do
        report(string.format("PROBE global %s %s", name, type(_G[name])))
    end
    if type(_G.Export) == "table" then report_list("PROBE Export.fn", sorted_keys(_G.Export, "function")) end
    if type(net) == "table" then report_list("PROBE net.fn", sorted_keys(net, "function")) end

    local lo = {}
    for _, k in ipairs(sorted_keys(_G, "function")) do
        if k:sub(1, 2) == "Lo" then lo[#lo + 1] = k end
    end
    report_list("PROBE _G.Lo*", lo)

    report(string.format("PROBE clock model=%s real=%s paused=%s track=%s multiplayer=%s",
        tostring(model_time()), tostring(call(dcs_fn("getRealTime"))),
        tostring(call(dcs_fn("getPause"))), tostring(call(dcs_fn("isTrackPlaying"))),
        tostring(call(dcs_fn("isMultiplayer")))))
    report("PROBE mission name=" .. oneline(call(dcs_fn("getMissionName")))
        .. " file=" .. oneline(call(dcs_fn("getMissionFilename"))))

    read_mission_info()
    report(string.format("PROBE mission start_time=%s date=%s theatre=%s",
        tostring(sim.start_tod), tostring(sim.date), tostring(sim.theatre)))

    for _, name in ipairs({ "LoGetMissionStartTime", "LoGetModelTime" }) do
        local f, where = resolve_lo(name)
        if f then report(string.format("PROBE %s (%s) = %s", name, where, oneline(call(f)))) end
    end

    -- What the other Lua states can see. Read-only code: absolute and model time from the
    -- mission scripting state, and whether LoSetCommand exists there.
    local code = "return tostring(timer and timer.getAbsTime and timer.getAbsTime()) .. ' '"
        .. " .. tostring(timer and timer.getTime and timer.getTime()) .. ' LoSetCommand='"
        .. " .. type(LoSetCommand)"
    for _, state in ipairs({ "mission", "export", "config", "server" }) do
        local res, extra = dostring_in(state, code)
        report(string.format("PROBE dostring_in %s -> %s | %s", state, oneline(res), oneline(extra)))
    end
    report("PROBE end")
end

-- -------------------------------------------------------------------------------------
-- command id search
-- -------------------------------------------------------------------------------------
-- Time acceleration is an input command (iCommandAccelerate & co.), not an API call. Its
-- numeric id is defined somewhere in the install's Lua; find every iCommand whose name
-- mentions "accel" or "decel" (Accelerate, Decelerate, NoAcceleration) and any number
-- assigned to it.
local MAX_FILES, MAX_DEPTH, MAX_HITS = 6000, 6, 80

local function is_speed_name(s)
    s = s:lower()
    return s:find("accel", 1, true) ~= nil or s:find("decel", 1, true) ~= nil
end

local function find_commands(subdir)
    if type(lfs) ~= "table" or type(lfs.dir) ~= "function" then
        report("FIND unavailable: no lfs")
        return
    end
    local root = install_root()
    local dirs = { "Scripts", "Config" }
    if subdir and #subdir > 0 then dirs = { subdir } end

    local started = call(dcs_fn("getRealTime")) or 0
    local files, hits, seen = 0, 0, {}

    local function scan_file(path, short)
        local fh = io.open(path, "r")
        if not fh then return end
        for line in fh:lines() do
            if hits >= MAX_HITS then break end
            if line:find("iCommand", 1, true) and is_speed_name(line) then
                for name, rest in line:gmatch("(iCommand[%w_]*)([^,;}]*)") do
                    if is_speed_name(name) then
                        local value = rest:match("^%s*=%s*(%-?%d+)")
                        local key = name .. "=" .. tostring(value)
                        if not seen[key] then
                            seen[key] = true
                            hits = hits + 1
                            report(string.format("CMDID %s=%s file=%s", name, value or "?", short))
                        end
                    end
                end
            end
        end
        fh:close()
    end

    local function walk(dir, short, depth)
        if depth > MAX_DEPTH or files >= MAX_FILES or hits >= MAX_HITS then return end
        local ok, iter, obj = pcall(lfs.dir, dir)
        if not ok then return end
        for entry in iter, obj do
            if files >= MAX_FILES or hits >= MAX_HITS then break end
            if entry ~= "." and entry ~= ".." then
                local path = dir .. "\\" .. entry
                local mode = call(lfs.attributes, path, "mode")
                if mode == "directory" then
                    walk(path, short .. "\\" .. entry, depth + 1)
                elseif mode == "file" and entry:lower():match("%.lua$") then
                    files = files + 1
                    pcall(scan_file, path, short .. "\\" .. entry)
                end
            end
        end
    end

    for _, d in ipairs(dirs) do
        local ok, err = pcall(walk, root .. d, d, 1)
        if not ok then report("FIND error in " .. d .. ": " .. oneline(err)) end
    end
    local elapsed = (call(dcs_fn("getRealTime")) or started) - started
    report(string.format("FIND done: %d lua files, %d hits, %.1fs, root=%s dirs=%s",
        files, hits, elapsed, root, table.concat(dirs, ",")))
end

-- -------------------------------------------------------------------------------------
-- commands
-- -------------------------------------------------------------------------------------
local function parse_cmd_args(arg)
    local id, value = arg:match("^(%-?%d+)%s*(%S*)$")
    return tonumber(id), tonumber(value)
end

local handlers = {}

handlers.PING = function()
    send("PONG " .. VERSION)
end

handlers.PAUSE = function()
    call(dcs_fn("setPause"), true)
end

handlers.RESUME = function()
    call(dcs_fn("setPause"), false)
end

handlers.ARM = function(arg)
    local t = tonumber(arg)
    if not t then
        send("ERR ARM needs a model time")
        return
    end
    local now = model_time()
    if now and t <= now then
        report(string.format("ERR behind target=%.3f now=%.3f", t, now))
        return
    end
    stop.target = t
    report(string.format("ARMED target=%.3f now=%.3f", t, now or -1))
end

handlers.DISARM = function()
    stop.target = nil
    send("DISARMED")
end

handlers.PROBE = function()
    probe()
end

handlers.FINDCMDS = function(arg)
    find_commands(arg)
end

handlers.LOCMD = function(arg)
    local id, value = parse_cmd_args(arg)
    if not id then
        send("ERR LOCMD needs a command id")
        return
    end
    local f, where = resolve_lo("LoSetCommand")
    if not f then
        report("LOCMD unavailable: no LoSetCommand in the hooks state (try LOCMDX)")
        return
    end
    local ok, err
    if value then ok, err = pcall(f, id, value) else ok, err = pcall(f, id) end
    report(string.format("LOCMD id=%d value=%s via=%s ok=%s err=%s speed_before=%.3f",
        id, tostring(value), where, tostring(ok), oneline(err), sim.speed or -1))
end

handlers.LOCMDX = function(arg)
    local id, value = parse_cmd_args(arg)
    if not id then
        send("ERR LOCMDX needs a command id")
        return
    end
    local args = value and string.format("%d, %s", id, tostring(value)) or string.format("%d", id)
    local code = "if type(LoSetCommand) ~= 'function' then return 'no LoSetCommand' end "
        .. "local ok, err = pcall(LoSetCommand, " .. args .. ") "
        .. "return 'ok=' .. tostring(ok) .. ' err=' .. tostring(err)"
    local res, extra = dostring_in("export", code)
    report(string.format("LOCMDX id=%d value=%s -> %s | %s speed_before=%.3f",
        id, tostring(value), oneline(res), oneline(extra), sim.speed or -1))
end

local function dispatch(line)
    line = tostring(line):gsub("%s+$", "")
    local word, arg = line:match("^(%S+)%s*(.*)$")
    if not word then return end
    local h = handlers[word:upper()]
    if h then
        h(arg)
    else
        send("ERR unknown command " .. oneline(word))
    end
end

-- -------------------------------------------------------------------------------------
-- per frame
-- -------------------------------------------------------------------------------------
local function on_frame()
    if not sim.in_mission then return end
    if not link.tried then open_link() end

    if link.inp then
        for _ = 1, MAX_CMDS_PER_FRAME do
            local ok, data = pcall(link.inp.receive, link.inp)
            if not ok or not data then break end
            local okh, err = pcall(dispatch, data)
            if not okh then sayf("command '%s' failed: %s", oneline(data), oneline(err)) end
        end
    end

    local m = model_time()
    if type(m) ~= "number" then return end

    if sim.first_frame then
        sim.first_frame = false
        sayf("first frame: model=%.3f track=%s start_time=%s date=%s theatre=%s",
            m, tostring(call(dcs_fn("isTrackPlaying"))), tostring(sim.start_tod),
            tostring(sim.date), tostring(sim.theatre))
    end

    check_stop(m)

    local r = call(dcs_fn("getRealTime"))
    if type(r) ~= "number" then return end
    measure(m, r)

    if r >= sim.next_state_rt then
        sim.next_state_rt = r + STATE_INTERVAL
        send(string.format(
            "STATE t=%.3f rt=%.3f speed=%.3f raw=%.3f paused=%s track=%s stop=%.3f start_tod=%s date=%s",
            m, r, sim.speed or -1, sim.raw or -1,
            tostring(call(dcs_fn("getPause"))), tostring(call(dcs_fn("isTrackPlaying"))),
            stop.target or -1, tostring(sim.start_tod), tostring(sim.date)))
    end
end

-- -------------------------------------------------------------------------------------
-- callbacks
-- -------------------------------------------------------------------------------------
local frame_error_logged = false
local callbacks = {}

function callbacks.onMissionLoadEnd()
    sim.in_mission = true
    reset_sim()
    pcall(read_mission_info)
    sayf("mission loaded: start_time=%s date=%s theatre=%s track=%s",
        tostring(sim.start_tod), tostring(sim.date), tostring(sim.theatre),
        tostring(call(dcs_fn("isTrackPlaying"))))
end

function callbacks.onSimulationStop()
    sim.in_mission = false
    stop.target = nil
    say("simulation stopped")
end

function callbacks.onSimulationPause()
    sayf("onSimulationPause at model=%s", tostring(model_time()))
end

function callbacks.onSimulationResume()
    sayf("onSimulationResume at model=%s", tostring(model_time()))
end

function callbacks.onSimulationFrame()
    local ok, err = pcall(on_frame)
    if not ok and not frame_error_logged then
        frame_error_logged = true
        sayf("frame error (logged once): %s", oneline(err))
    end
end

local ok, err = pcall(DCS.setUserCallbacks, callbacks)
sayf("loaded %s (callbacks %s)", VERSION, ok and "registered" or ("FAILED: " .. oneline(err)))
