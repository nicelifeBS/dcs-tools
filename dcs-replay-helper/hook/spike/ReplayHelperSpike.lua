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
--   LOCMD <id> [value]       call Export.LoSetCommand from this (hooks) state; reports the
--                            commanded and measured speed again 0.6 s later (LOCMD-AFTER)
--   LOCMDX <id> [value]      call LoSetCommand inside the export state via net.dostring_in
--   DIGITAL <id> [value]     call DCS.dispatchDigitalAction; reports like LOCMD
--   GLOBALS [words]          list globals (and keys one table down) whose names contain any of
--                            the words (default: accel decel), here and in the config, mission,
--                            export and server states. The iCommand ids are engine-supplied
--                            globals, not text in any Lua file, so this is how to find them.
--
-- Round 4 (spike-4): can the hook put the F2 view on a given unit, and tell which unit the
-- camera is on? No API does either directly, so:
--   CAM                      report the camera and the unit it is aimed at: the one closest to
--                            the camera's line of sight (LoGetCameraPosition, LoGetWorldObjects)
--   OBJECTS [all]            list aircraft (or all units) with their DCS ids, unit and group names
--   VIEW [route] <id> [value]
--                            send a view command, then report CAM (VIEW-AFTER) 0.3 s later
--   FOCUS <id|0xhex|name> [route] [fast]
--                            iCommandViewAir (8) until the camera is on that unit, a full cycle
--                            or 80 steps: from the cockpit it gives F2 on the player's aircraft,
--                            in F2 the next aircraft. One step every 0.15 s, or 0.05 s with fast.
--                            FOCUS on its own cancels.
--   route: how a command is sent. digital (default): DCS.dispatchDigitalAction; export:
--   LoSetCommand in the export state; hooks: Export.LoSetCommand here. In a replay, hooks does
--   nothing to the view; digital and export switch views. Next/previous object (181/180) do
--   nothing by any route (round 5).
--
-- Round 7 (spike-7): can the app match the free camera's speed to an aircraft, helicopter or
-- missile? Three questions: what speed does each object have (also while paused), what
-- speed does the camera have, and which input command changes the camera's speed.
--   CAMV                     camera speed in m/s (CAMV speed=, fwd= signed along the camera's
--                            forward axis, age=): the change of LoGetCameraPosition().p over
--                            real time, so it works while the sim is paused. STATE has
--                            camv= and camfwd= too, and LOCMD-AFTER reports them
--   TRACK on|off             sample the aircraft, helicopters and weapons ~5 times a second
--                            (only while model time advances) and keep each one's velocity
--   MOVERS [radius m]        every tracked object, nearest to the camera first, with speed,
--                            unit, group and (weapons) the aircraft that probably fired it.
--                            Paused, it shows the last speed measured while the sim ran
--   FINDCAM [subdir]         scan Config (or subdir) for the free-camera / camera-speed
--                            bindings (keys and mouse wheel); then GLOBALS <name part> for the
--                            numeric ids
--
-- A unit counts as viewed only when it is within VIEW_MAX_OFF degrees of the camera's forward
-- axis and the camera is not inside another unit (its cockpit).
--
-- STATE carries both the measured speed (speed=, model/real time ratio) and the speed DCS
-- says it is commanding (accel=, Export.LoGetModelTimeAcceleration).
--
-- Safety: this runs inside DCS's GUI state. Any error at file scope would silently drop the
-- whole hook, and an error in a callback can break the menus, so every DCS call is pcall'd
-- and nothing runs outside a mission.
-- =====================================================================================

local TAG     = "REPLAYHELPER"
local VERSION = "spike-7"

local HOST       = "127.0.0.1"
local STATE_PORT = 47810   -- hook -> client
local CMD_PORT   = 47811   -- client -> hook

local STATE_INTERVAL     = 0.1    -- real seconds between STATE packets
local SPEED_WINDOW       = 0.5    -- real seconds per speed sample
local STOPPED_RATIO      = 0.004  -- below this the sim is paused, not in slow motion (1/64x = 0.0156)
local MAX_CMDS_PER_FRAME = 16
local AFTER_DELAY        = 0.6    -- real seconds before LOCMD reports its effect

-- View command ids (iCommand*), from a community-extracted table of LoSetCommand numbers.
local VIEW_AIR        = 8      -- iCommandViewAir: F2, and in F2 the next aircraft (round 5)
local VIEW_DELAY      = 0.3    -- real seconds before VIEW reports where the camera went
local FOCUS_DELAY     = 0.15   -- real seconds between FOCUS steps, for the camera to move
local FOCUS_FAST_DELAY = 0.05  -- the same with FOCUS ... fast
local FOCUS_MAX_STEPS = 80
local VIEW_MAX_DIST   = 5000   -- metres: a unit further from the camera is not the one viewed
local VIEW_MAX_OFF    = 5      -- degrees: F2 points at its unit (0.0 paused, up to 1.6 flying)
local INSIDE_DIST     = 10     -- metres: a camera this close to a unit is in its cockpit
local MAX_OBJECT_LINES = 100

-- Round 7
local CAMV_WINDOW      = 0.25  -- real seconds per camera speed sample
local TRACK_INTERVAL   = 0.2   -- real seconds between object samples
local TRACK_MIN_DT     = 0.02  -- model seconds: less than this is a pause, not motion
local TRACK_MAX_SPEED  = 3000  -- m/s: faster between two samples is a respawn, not a speed
local SHOOTER_MAX_DIST = 2000  -- metres: a weapon first seen this close to an aircraft of its side
local MAX_MOVER_LINES  = 100
local MAX_CAMCMD_HITS  = 120
local MS_TO_KT         = 1.943844

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

-- Export functions are reachable from the hooks state as Export.Lo*, not as bare globals.
local function resolve_lo(name)
    if type(_G[name]) == "function" then return _G[name], "_G" end
    if type(_G.Export) == "table" and type(_G.Export[name]) == "function" then
        return _G.Export[name], "Export"
    end
    return nil
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
local after = { at_rt = nil, label = nil }   -- pending LOCMD-AFTER report
local view_after = { at_rt = nil, label = nil }   -- pending VIEW-AFTER report
local focus = { target = nil }   -- a FOCUS in progress

local function commanded_accel()
    local f = resolve_lo("LoGetModelTimeAcceleration")
    local v = call(f)
    return type(v) == "number" and v or -1
end

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
    after.at_rt, after.label = nil, nil
    view_after.at_rt, view_after.label = nil, nil
    focus.target = nil
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
        report(string.format("ARRIVED t=%.3f target=%.3f over=%.3f speed=%.3f accel=%.3f",
            m, target, m - target, sim.speed or -1, commanded_accel()))
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

    report(string.format("PROBE clock model=%s real=%s accel=%s paused=%s track=%s multiplayer=%s",
        tostring(model_time()), tostring(call(dcs_fn("getRealTime"))), tostring(commanded_accel()),
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

-- Visit every .lua file under the dirs (below the install root) as visit(path, short_path);
-- visit returns true to stop the whole scan. Returns the number of files visited, or nil and a
-- reason.
local function walk_lua(dirs, visit)
    if type(lfs) ~= "table" or type(lfs.dir) ~= "function" then return nil, "no lfs" end
    local root = install_root()
    local files, stopped = 0, false

    local function walk(dir, short, depth)
        if depth > MAX_DEPTH or files >= MAX_FILES or stopped then return end
        local ok, iter, obj = pcall(lfs.dir, dir)
        if not ok then return end
        for entry in iter, obj do
            if files >= MAX_FILES or stopped then break end
            if entry ~= "." and entry ~= ".." then
                local path = dir .. "\\" .. entry
                local mode = call(lfs.attributes, path, "mode")
                if mode == "directory" then
                    walk(path, short .. "\\" .. entry, depth + 1)
                elseif mode == "file" and entry:lower():match("%.lua$") then
                    files = files + 1
                    local okv, done = pcall(visit, path, short .. "\\" .. entry)
                    if okv and done then stopped = true end
                end
            end
        end
    end

    for _, d in ipairs(dirs) do
        local ok, err = pcall(walk, root .. d, d, 1)
        if not ok then report("FIND error in " .. d .. ": " .. oneline(err)) end
    end
    return files, root
end

local function find_commands(subdir)
    if type(lfs) ~= "table" or type(lfs.dir) ~= "function" then
        report("FIND unavailable: no lfs")
        return
    end
    local dirs = { "Scripts", "Config" }
    if subdir and #subdir > 0 then dirs = { subdir } end

    local started = call(dcs_fn("getRealTime")) or 0
    local hits, seen = 0, {}

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

    local files, root = walk_lua(dirs, function(path, short)
        scan_file(path, short)
        return hits >= MAX_HITS
    end)
    local elapsed = (call(dcs_fn("getRealTime")) or started) - started
    report(string.format("FIND done: %d lua files, %d hits, %.1fs, root=%s dirs=%s",
        files, hits, elapsed, root, table.concat(dirs, ",")))
end

-- Round 7: the bindings behind the free camera (F11) and its speed. The binding lines carry
-- the command name and the label shown in Options > Controls, e.g.
--   {combos = {{key = 'Num*', reformers = {'LAlt'}}}, down = iCommandView..., name = _('Camera forward')}
-- so list every line that mentions the camera together with speed or movement, and any line
-- about speed in a view config file (View.lua has the camera's speed and acceleration). The
-- mouse wheel changes the free camera's speed too, so a camera line with a wheel counts.
local function camera_line(l, short)
    if l:find("camera", 1, true)
        and (l:find("speed", 1, true) or l:find("forward", 1, true) or l:find("backward", 1, true)
            or l:find("move", 1, true) or l:find("accel", 1, true) or l:find("wheel", 1, true)
            or l:find("mouse_z", 1, true)) then
        return true
    end
    return short:lower():find("view", 1, true) ~= nil and l:find("speed", 1, true) ~= nil
end

local function find_camera(subdir)
    if type(lfs) ~= "table" or type(lfs.dir) ~= "function" then
        report("FINDCAM unavailable: no lfs")
        return
    end
    local dirs = { "Config" }
    if subdir and #subdir > 0 then dirs = { subdir } end
    local hits = 0

    local files, root = walk_lua(dirs, function(path, short)
        local fh = io.open(path, "r")
        if not fh then return false end
        local n = 0
        for line in fh:lines() do
            n = n + 1
            if camera_line(line:lower(), short) then
                hits = hits + 1
                local text = line:gsub("^%s+", ""):gsub("%s+$", "")
                report(string.format("CAMCMD %s:%d %s", short, n, oneline(text:sub(1, 240))))
                if hits >= MAX_CAMCMD_HITS then break end
            end
        end
        fh:close()
        return hits >= MAX_CAMCMD_HITS
    end)
    report(string.format("FINDCAM done: %d lua files, %d hits, root=%s dirs=%s",
        files, hits, root, table.concat(dirs, ",")))
end

-- -------------------------------------------------------------------------------------
-- global search
-- -------------------------------------------------------------------------------------
-- %s is replaced with the quoted, lower-case search words. Kept self-contained so the same
-- source runs in this state and, through net.dostring_in, in the others.
local GLOBAL_SCAN = [[
local words = { %s }
local hits, seen = {}, {}
local function wanted(k)
    if type(k) ~= "string" then return false end
    local l = k:lower()
    for _, w in ipairs(words) do
        if l:find(w, 1, true) then return true end
    end
    return false
end
local function add(name, v)
    local s = name .. "=" .. tostring(v)
    if not seen[s] and #hits < 60 then
        seen[s] = true
        hits[#hits + 1] = s
    end
end
for k, v in pairs(_G) do
    if wanted(k) then add(tostring(k), v) end
    if type(k) == "string" and type(v) == "table" and v ~= _G then
        pcall(function()
            for k2, v2 in pairs(v) do
                if wanted(k2) then add(k .. "." .. k2, v2) end
            end
        end)
    end
end
if #hits == 0 then return "(none)" end
table.sort(hits)
return table.concat(hits, " ")
]]

local function find_globals(arg)
    -- Only plain words reach the generated code: anything else is a separator.
    local words = {}
    for w in tostring(arg or ""):lower():gmatch("[%w_]+") do words[#words + 1] = string.format("%q", w) end
    if #words == 0 then words = { '"accel"', '"decel"' } end
    local code = string.format(GLOBAL_SCAN, table.concat(words, ", "))

    local loader = loadstring or load
    local chunk, cerr = loader(code)
    if chunk then
        local ok, res = pcall(chunk)
        report("GLOBALS hooks " .. oneline(ok and res or ("error: " .. tostring(res))))
    else
        report("GLOBALS hooks compile error: " .. oneline(cerr))
    end
    for _, state in ipairs({ "config", "mission", "export", "server" }) do
        local res, extra = dostring_in(state, code)
        report(string.format("GLOBALS %s %s | %s", state, oneline(res), oneline(extra)))
    end
    report("GLOBALS done")
end

-- -------------------------------------------------------------------------------------
-- camera and units (round 4)
-- -------------------------------------------------------------------------------------
local function vec(t)
    if type(t) ~= "table" then return nil end
    local x, y, z = tonumber(t.x), tonumber(t.y), tonumber(t.z)
    if x and y and z then return { x = x, y = y, z = z } end
    return nil
end

local function vsub(a, b) return { x = a.x - b.x, y = a.y - b.y, z = a.z - b.z } end
local function vdot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end
local function vlen(a) return math.sqrt(vdot(a, a)) end

local function angle_deg(a, b)
    local la, lb = vlen(a), vlen(b)
    if la == 0 or lb == 0 then return 180 end
    local c = math.max(-1, math.min(1, vdot(a, b) / (la * lb)))
    return math.deg(math.acos(c))
end

-- Where the camera and units were read: "Export" (this state) or "export-state" (through
-- net.dostring_in, if this state can't see the functions).
local view_source = { camera = nil, units = nil }

-- In the export state the Lo* functions are globals. Both chunks return plain text.
local CAMERA_IN_EXPORT = [[
local c = type(LoGetCameraPosition) == "function" and LoGetCameraPosition()
if type(c) ~= "table" or type(c.p) ~= "table" or type(c.x) ~= "table" then return "" end
local y, z = c.y or c.x, c.z or c.x
return string.format("%.3f %.3f %.3f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f %.6f",
    c.p.x, c.p.y, c.p.z, c.x.x, c.x.y, c.x.z, y.x, y.y, y.z, z.x, z.y, z.z)
]]
-- ARG is replaced by the LoGetWorldObjects argument: nothing, or 'ballistic' for weapons.
local UNITS_IN_EXPORT = [[
local objs = type(LoGetWorldObjects) == "function" and LoGetWorldObjects(ARG)
if type(objs) ~= "table" then return "" end
local function clean(v) return (tostring(v or ""):gsub("[\t\r\n]", " ")) end
local out = {}
for id, o in pairs(objs) do
    local p, t = o.Position or {}, o.Type or {}
    out[#out + 1] = table.concat({ tostring(id), tostring(t.level1 or 0),
        tostring(o.Flags and o.Flags.Human or false), tostring(p.x or ""), tostring(p.y or ""),
        tostring(p.z or ""), clean(o.Name), clean(o.Coalition), clean(o.UnitName), clean(o.GroupName),
        tostring(t.level2 or 0), tostring(t.level3 or 0), tostring(t.level4 or 0) }, "\t")
end
return table.concat(out, "\n")
]]

local function nums(text)
    local t = {}
    for n in tostring(text or ""):gmatch("%S+") do t[#t + 1] = tonumber(n) end
    return t
end

-- { p, x, y, z }: position and orientation vectors. Which of x/y/z points forward is one of
-- the things this round checks; x is assumed.
local function camera()
    local cam = call((resolve_lo("LoGetCameraPosition")))
    if type(cam) == "table" then
        local c = { p = vec(cam.p), x = vec(cam.x), y = vec(cam.y), z = vec(cam.z) }
        if c.p and c.x then
            view_source.camera = "Export"
            return c
        end
    end
    local n = nums((dostring_in("export", CAMERA_IN_EXPORT)))
    if #n ~= 12 then return nil end
    view_source.camera = "export-state"
    return { p = { x = n[1], y = n[2], z = n[3] }, x = { x = n[4], y = n[5], z = n[6] },
             y = { x = n[7], y = n[8], z = n[9] }, z = { x = n[10], y = n[11], z = n[12] } }
end

local function by_id(a, b) return a.id < b.id end

-- Units as a list of plain records; nil if no state can see LoGetWorldObjects. kind is nil
-- for the units, or "ballistic" for weapons in flight (round 7: whether DCS lists missiles
-- there is one of the things the spike finds out).
local function units(kind)
    local list = {}
    local weapon = kind == "ballistic"
    local f = resolve_lo("LoGetWorldObjects")
    local objs = f and call(f, kind)
    if type(objs) == "table" then
        for id, o in pairs(objs) do
            if type(o) == "table" and tonumber(id) then
                local t = type(o.Type) == "table" and o.Type or {}
                list[#list + 1] = {
                    id = tonumber(id), name = o.Name, unit = o.UnitName, group = o.GroupName,
                    coalition = o.Coalition, air = t.level1 == 1,
                    human = type(o.Flags) == "table" and o.Flags.Human or false,
                    pos = vec(o.Position), weapon = weapon,
                    l1 = t.level1, l2 = t.level2, l3 = t.level3, l4 = t.level4,
                }
            end
        end
        view_source.units = "Export"
        table.sort(list, by_id)
        return list
    end
    local code = UNITS_IN_EXPORT:gsub("ARG", function() return weapon and "'ballistic'" or "" end)
    local text = dostring_in("export", code)
    if type(text) ~= "string" or text == "" then return nil end
    for line in text:gmatch("[^\n]+") do
        local f = {}
        for field in (line .. "\t"):gmatch("([^\t]*)\t") do f[#f + 1] = field end
        if tonumber(f[1]) then
            list[#list + 1] = {
                id = tonumber(f[1]), air = tonumber(f[2]) == 1, human = f[3] == "true",
                pos = vec({ x = f[4], y = f[5], z = f[6] }),
                name = f[7], coalition = f[8], unit = f[9], group = f[10], weapon = weapon,
                l1 = tonumber(f[2]), l2 = tonumber(f[11]), l3 = tonumber(f[12]), l4 = tonumber(f[13]),
            }
        end
    end
    view_source.units = "export-state"
    table.sort(list, by_id)
    return list
end

local function describe(u)
    if not u then return "none" end
    local s = string.format("id=%d/0x%x %s unit=%q group=%q %s air=%s human=%s",
        u.id, u.id, tostring(u.name), tostring(u.unit), tostring(u.group), tostring(u.coalition),
        tostring(u.air), tostring(u.human))
    if u.dist then s = s .. string.format(" dist=%.1f off=%.1f", u.dist, u.off) end
    return oneline(s)
end

-- Distance and angle off the camera's forward axis for every unit near the camera. Returns
-- the list sorted by angle (the first is the unit aimed at) and the nearest unit.
local function sight(cam, list)
    local near, nearest = {}, nil
    for _, u in ipairs(list) do
        if u.pos then
            local d = vsub(u.pos, cam.p)
            local dist = vlen(d)
            if dist <= VIEW_MAX_DIST then
                local r = {}
                for k, v in pairs(u) do r[k] = v end
                r.dist, r.off, r.d = dist, angle_deg(d, cam.x), d
                near[#near + 1] = r
                if not nearest or dist < nearest.dist then nearest = r end
            end
        end
    end
    table.sort(near, function(a, b)
        if a.off ~= b.off then return a.off < b.off end
        return a.dist < b.dist
    end)
    return near, nearest
end

-- The unit in view: straight ahead, with the camera not inside another unit. nil otherwise.
local function aimed_unit(near, nearest)
    local best = near[1]
    if not best or best.off > VIEW_MAX_OFF then return nil end
    if nearest and nearest ~= best and nearest.dist < INSIDE_DIST then return nil end
    return best
end

-- The unit the camera is viewing (nil if none), or nil and a reason it can't be told. The
-- third value is the closest candidate, for the log.
local function viewed()
    local cam = camera()
    if not cam then return nil, "no camera position (LoGetCameraPosition)" end
    local list = units()
    if not list then return nil, "no units (LoGetWorldObjects)" end
    local near, nearest = sight(cam, list)
    return aimed_unit(near, nearest), nil, near[1]
end

local function report_cam(prefix)
    local cam = camera()
    if not cam then
        report(prefix .. " unavailable: no camera position (LoGetCameraPosition)")
        return
    end
    local list = units()
    if not list then
        report(prefix .. " unavailable: no units (LoGetWorldObjects)")
        return
    end
    local near, nearest = sight(cam, list)
    report(string.format("%s p=(%.1f,%.1f,%.1f) x=(%.3f,%.3f,%.3f) units=%d near=%d via=%s/%s",
        prefix, cam.p.x, cam.p.y, cam.p.z, cam.x.x, cam.x.y, cam.x.z, #list, #near,
        tostring(view_source.camera), tostring(view_source.units)))
    report(prefix .. " aimed " .. describe(aimed_unit(near, nearest)))
    report(prefix .. " best " .. describe(near[1]))
    report(prefix .. " nearest " .. describe(nearest))
    for i = 2, math.min(3, #near) do report(prefix .. " next " .. describe(near[i])) end
    -- Which axis points at the nearest unit tells which one is forward.
    if nearest and cam.y and cam.z then
        report(string.format("%s axes to nearest: x=%.1f y=%.1f z=%.1f deg", prefix,
            angle_deg(nearest.d, cam.x), angle_deg(nearest.d, cam.y), angle_deg(nearest.d, cam.z)))
    end
end

-- -------------------------------------------------------------------------------------
-- camera speed (round 7)
-- -------------------------------------------------------------------------------------
-- The camera's own speed in the world: how far LoGetCameraPosition().p moved per real second.
-- Real time, not model time, because the free camera keeps flying while the sim is paused.
-- A view change (F-keys) jumps the camera and shows up as one huge sample.
local camv = { p = nil, r = nil, speed = nil, fwd = nil, at = nil }

local function camv_reset()
    camv.p, camv.r, camv.speed, camv.fwd, camv.at = nil, nil, nil, nil, nil
end

local function camv_tick(r)
    if camv.r and r - camv.r < CAMV_WINDOW then return end
    local cam = camera()
    if not (cam and cam.p) then
        camv_reset()
        return
    end
    if camv.p and camv.r then
        local dt = r - camv.r
        local d = vsub(cam.p, camv.p)
        local v = { x = d.x / dt, y = d.y / dt, z = d.z / dt }
        camv.speed = vlen(v)
        local axis = vlen(cam.x)
        camv.fwd = axis > 0 and vdot(v, cam.x) / axis or nil
        camv.at = r
    end
    camv.p, camv.r = cam.p, r
end

local function opt(v, fmt)
    if v == nil then return "-" end
    return string.format(fmt or "%.2f", v)
end

-- -------------------------------------------------------------------------------------
-- object speeds (round 7)
-- -------------------------------------------------------------------------------------
-- LoGetWorldObjects reports position and heading but no velocity, so a speed is the change in
-- position over model time between two samples. It stays valid while the sim is paused (the
-- last measured velocity is kept, and its age says how old it is).
local track = { on = false, next_rt = 0, last_m = nil, mov = {}, samples = 0 }

-- plane, heli, "air" for other air objects, weapon (from the ballistic list), else nil.
local function kind_of(u)
    if u.weapon then return "weapon" end
    if u.l1 == 1 then
        if u.l2 == 1 then return "plane" end
        if u.l2 == 2 then return "heli" end
        return "air"
    end
    return nil
end

local function track_reset()
    track.last_m, track.mov, track.samples, track.next_rt = nil, {}, 0, 0
end

-- The aircraft of the weapon's side nearest to where it first appears, as the Tacview events
-- do; "-" when none is close.
local function guess_shooter(w, carriers)
    local best, best_dist
    for _, c in ipairs(carriers) do
        if c.pos and w.pos and (w.coalition == nil or c.coalition == w.coalition) then
            local dist = vlen(vsub(c.pos, w.pos))
            if dist <= SHOOTER_MAX_DIST and (not best_dist or dist < best_dist) then
                best, best_dist = c, dist
            end
        end
    end
    if not best then return "-" end
    return string.format("%s/%s", tostring(best.unit), tostring(best.group))
end

local function track_tick(m, r)
    if not track.on or r < track.next_rt then return end
    track.next_rt = r + TRACK_INTERVAL
    if track.last_m and m < track.last_m - 1 then track_reset() end  -- the track restarted
    -- Paused (or a frame that did not advance the sim): nothing moved, keep what we have.
    if track.last_m and m - track.last_m < TRACK_MIN_DT then return end

    local list = units()
    if not list then return end
    local weapons = units("ballistic") or {}
    for _, w in ipairs(weapons) do list[#list + 1] = w end

    local carriers, now = {}, {}
    for _, u in ipairs(list) do
        local kind = kind_of(u)
        if kind == "plane" or kind == "heli" or kind == "air" then carriers[#carriers + 1] = u end
        if kind and u.pos then
            local prev = track.mov[u.id]
            local e = { u = u, kind = kind, pos = u.pos, m = m }
            if prev then
                e.from = prev.from
                e.v, e.speed, e.vm = prev.v, prev.speed, prev.vm
                local dt = m - prev.m
                if dt >= TRACK_MIN_DT then
                    local d = vsub(u.pos, prev.pos)
                    local v = { x = d.x / dt, y = d.y / dt, z = d.z / dt }
                    local speed = vlen(v)
                    if speed <= TRACK_MAX_SPEED then
                        e.v, e.speed, e.vm = v, speed, m
                    else
                        e.v, e.speed, e.vm = nil, nil, nil  -- a jump, not a speed
                    end
                else
                    e.pos, e.m = prev.pos, prev.m
                end
            end
            now[u.id] = e
        end
    end
    -- Weapons seen for the first time: who fired them.
    for id, e in pairs(now) do
        if e.kind == "weapon" and not track.mov[id] then e.from = guess_shooter(e.u, carriers) end
    end
    track.mov, track.last_m = now, m
    track.samples = track.samples + 1
end

local function type_levels(u)
    return string.format("%s/%s/%s/%s", tostring(u.l1), tostring(u.l2), tostring(u.l3), tostring(u.l4))
end

local function mover_line(e, now_m)
    local u = e.u
    local speed = e.speed and string.format("%.1f m/s %.0f kt %.0f km/h", e.speed,
        e.speed * MS_TO_KT, e.speed * 3.6) or "unknown"
    local v = e.v and string.format("(%.1f,%.1f,%.1f)", e.v.x, e.v.y, e.v.z) or "-"
    local line = string.format("MOV id=%d/0x%x kind=%s type=%s name=%s unit=%q group=%q %s human=%s speed=%s v=%s age=%s",
        u.id, u.id, e.kind, type_levels(u), tostring(u.name), tostring(u.unit), tostring(u.group),
        tostring(u.coalition), tostring(u.human), speed, v, e.vm and string.format("%.1fs", now_m - e.vm) or "-")
    if e.dist then line = line .. string.format(" dist=%.0f", e.dist) end
    if e.kind == "weapon" then line = line .. " from=" .. tostring(e.from or "-") end
    return oneline(line)
end

local ROUTES = { digital = true, export = true, hooks = true }
local DEFAULT_ROUTE = "digital"

-- Send a command id by one of three routes. Returns ok, error.
local function set_command(id, value, route)
    route = route or DEFAULT_ROUTE
    if route == "digital" then
        local f = dcs_fn("dispatchDigitalAction")
        if type(f) ~= "function" then return false, "no DCS.dispatchDigitalAction" end
        if value then return pcall(f, id, value) end
        return pcall(f, id)
    elseif route == "export" then
        local args = value and string.format("%d, %s", id, tostring(value)) or string.format("%d", id)
        local res, extra = dostring_in("export",
            "if type(LoSetCommand) ~= 'function' then return 'no LoSetCommand' end "
            .. "local ok, err = pcall(LoSetCommand, " .. args .. ") "
            .. "return ok and 'ok' or ('error ' .. tostring(err))")
        if res == "ok" then return true, nil end
        return false, tostring(res) .. " " .. tostring(extra)
    end
    local f = resolve_lo("LoSetCommand")
    if not f then return false, "no LoSetCommand" end
    if value then return pcall(f, id, value) end
    return pcall(f, id)
end

-- Leading route word, if any: "export 181" -> "export", "181".
local function split_route(arg)
    local word, rest = tostring(arg or ""):match("^%s*(%a+)%s+(.*)$")
    if word and ROUTES[word:lower()] then return word:lower(), rest end
    return nil, arg
end

local function find_unit(arg, list)
    local hex = arg:match("^0[xX](%x+)$")
    local id = hex and tonumber(hex, 16) or (arg:match("^%d+$") and tonumber(arg))
    if id then
        for _, u in ipairs(list) do
            if u.id == id then return u end
        end
        return nil
    end
    local want = arg:lower()
    local function has(s) return type(s) == "string" and s:lower():find(want, 1, true) ~= nil end
    for _, u in ipairs(list) do
        if u.air and (has(u.unit) or has(u.group) or has(u.name)) then return u end
    end
    for _, u in ipairs(list) do
        if has(u.unit) or has(u.group) or has(u.name) then return u end
    end
    return nil
end

local function focus_done(result)
    local r = call(dcs_fn("getRealTime")) or focus.started_rt
    report(string.format("FOCUS-DONE %s target=0x%x steps=%d time=%.2f visited=%s", result,
        focus.target, focus.steps, r - focus.started_rt,
        #focus.visited > 0 and table.concat(focus.visited, ",") or "-"))
    focus.target = nil
end

local function focus_tick(r)
    if not focus.target or r < focus.next_rt then return end
    local u, why, best = viewed()
    if why then
        focus_done("fail reason=" .. why:gsub("%s", "_"))
        return
    end
    report(string.format("FOCUS-STEP %d %s viewed %s", focus.steps, focus.route,
        u and describe(u) or ("none, best " .. describe(best))))
    local id = u and u.id
    if id == focus.target then
        focus_done("ok")
        return
    end
    if id then
        if focus.first == nil then
            focus.first = id
        elseif id == focus.first then
            focus_done("fail reason=cycled")
            return
        end
        focus.visited[#focus.visited + 1] = string.format("0x%x", id)
    else
        focus.visited[#focus.visited + 1] = "none"
    end
    if focus.steps >= FOCUS_MAX_STEPS then
        focus_done("fail reason=max_steps")
        return
    end
    local ok, err = set_command(VIEW_AIR, nil, focus.route)
    if not ok then
        focus_done("fail reason=command_" .. oneline(err):gsub("%s", "_"))
        return
    end
    focus.steps = focus.steps + 1
    focus.next_rt = r + focus.delay
end

-- -------------------------------------------------------------------------------------
-- commands
-- -------------------------------------------------------------------------------------
-- "<id>" or "<id> <value>", nothing else. A loose match once turned the memory address
-- 0000022317A6DEA0 into command 22317 and sent it to DCS.
local function parse_cmd_args(arg)
    local id, rest = arg:match("^(%-?%d+)(.*)$")
    if not id then return nil end
    if rest:match("^%s*$") then return tonumber(id), nil end
    local value = rest:match("^%s+(%-?%d+%.?%d*)%s*$")
    if not value then return nil end
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
    local accel_before = commanded_accel()
    local ok, err
    if value then ok, err = pcall(f, id, value) else ok, err = pcall(f, id) end
    report(string.format("LOCMD id=%d value=%s via=%s ok=%s err=%s accel_before=%.3f speed_before=%.3f",
        id, tostring(value), where, tostring(ok), oneline(err), accel_before, sim.speed or -1))
    after.at_rt = (call(dcs_fn("getRealTime")) or 0) + AFTER_DELAY
    after.label = string.format("id=%d", id)
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
    local accel_before = commanded_accel()
    local res, extra = dostring_in("export", code)
    report(string.format("LOCMDX id=%d value=%s -> %s | %s accel_before=%.3f speed_before=%.3f",
        id, tostring(value), oneline(res), oneline(extra), accel_before, sim.speed or -1))
    after.at_rt = (call(dcs_fn("getRealTime")) or 0) + AFTER_DELAY
    after.label = string.format("x id=%d", id)
end

handlers.DIGITAL = function(arg)
    local id, value = parse_cmd_args(arg)
    if not id then
        send("ERR DIGITAL needs a command id")
        return
    end
    local f = dcs_fn("dispatchDigitalAction")
    if type(f) ~= "function" then
        report("DIGITAL unavailable: no DCS.dispatchDigitalAction")
        return
    end
    local accel_before = commanded_accel()
    local ok, err
    if value then ok, err = pcall(f, id, value) else ok, err = pcall(f, id) end
    report(string.format("DIGITAL id=%d value=%s ok=%s err=%s accel_before=%.3f speed_before=%.3f",
        id, tostring(value), tostring(ok), oneline(err), accel_before, sim.speed or -1))
    after.at_rt = (call(dcs_fn("getRealTime")) or 0) + AFTER_DELAY
    after.label = string.format("digital id=%d", id)
end

handlers.CAMV = function()
    local r = call(dcs_fn("getRealTime")) or 0
    if camv.speed == nil then
        report("CAMV unknown: no camera position yet (LoGetCameraPosition), or no sample yet")
        return
    end
    report(string.format("CAMV speed=%.2f m/s fwd=%s m/s age=%.2fs paused=%s via=%s",
        camv.speed, opt(camv.fwd), r - (camv.at or r), tostring(call(dcs_fn("getPause"))),
        tostring(view_source.camera)))
end

handlers.TRACK = function(arg)
    local word = tostring(arg or ""):lower():match("^%s*(%a*)%s*$") or ""
    if word == "on" then
        track.on = true
        track.next_rt = 0
        report("TRACK on")
    elseif word == "off" then
        track.on = false
        track_reset()
        report("TRACK off")
    elseif word == "" then
        report(string.format("TRACK %s samples=%d tracked=%d", track.on and "on" or "off",
            track.samples, (function() local n = 0 for _ in pairs(track.mov) do n = n + 1 end return n end)()))
    else
        send("ERR TRACK needs on or off")
    end
end

handlers.MOVERS = function(arg)
    if not track.on then
        report("MOVERS tracking is off: TRACK on, let the replay run for a few seconds, then MOVERS")
        return
    end
    local radius = tonumber(tostring(arg or ""):match("^%s*(%d+%.?%d*)%s*$"))
    local now_m = model_time() or track.last_m or 0
    local cam = camera()
    local list, counts, types = {}, { plane = 0, heli = 0, air = 0, weapon = 0 }, {}
    for _, e in pairs(track.mov) do
        if cam and cam.p then e.dist = vlen(vsub(e.pos, cam.p)) else e.dist = nil end
        if not radius or not e.dist or e.dist <= radius then
            list[#list + 1] = e
            counts[e.kind] = counts[e.kind] + 1
            if e.kind == "weapon" then
                local key = type_levels(e.u)
                types[key] = (types[key] or 0) + 1
            end
        end
    end
    table.sort(list, function(a, b)
        if a.dist and b.dist and a.dist ~= b.dist then return a.dist < b.dist end
        return a.u.id < b.u.id
    end)
    local tlist = {}
    for key, n in pairs(types) do tlist[#tlist + 1] = key .. "=" .. n end
    table.sort(tlist)
    report(string.format("MOVERS listed=%d plane=%d heli=%d air=%d weapon=%d paused=%s samples=%d "
        .. "weapon_types=%s radius=%s", #list, counts.plane, counts.heli, counts.air, counts.weapon,
        tostring(call(dcs_fn("getPause"))), track.samples, #tlist > 0 and table.concat(tlist, ",") or "-",
        radius and tostring(radius) or "-"))
    for i, e in ipairs(list) do
        if i > MAX_MOVER_LINES then
            report(string.format("MOVERS ... %d more", #list - MAX_MOVER_LINES))
            break
        end
        report(mover_line(e, now_m))
    end
    report("MOVERS end")
end

handlers.FINDCAM = function(arg)
    find_camera(arg)
end

handlers.GLOBALS = function(arg)
    find_globals(arg)
end

handlers.CAM = function()
    report_cam("CAM")
end

handlers.OBJECTS = function(arg)
    local list = units()
    if not list then
        report("OBJECTS unavailable: no units (LoGetWorldObjects)")
        return
    end
    local all = tostring(arg or ""):lower() == "all"
    local cam = camera()
    local shown = {}
    for _, u in ipairs(list) do
        if all or u.air then
            if cam and u.pos then
                u.dist = vlen(vsub(u.pos, cam.p))
                u.off = angle_deg(vsub(u.pos, cam.p), cam.x)
            end
            shown[#shown + 1] = u
        end
    end
    report(string.format("OBJECTS units=%d listed=%d (%s) via=%s", #list, #shown,
        all and "all" or "aircraft", tostring(view_source.units)))
    for i, u in ipairs(shown) do
        if i > MAX_OBJECT_LINES then
            report(string.format("OBJECTS ... %d more", #shown - MAX_OBJECT_LINES))
            break
        end
        report("OBJ " .. describe(u))
    end
    report("OBJECTS end")
end

handlers.VIEW = function(arg)
    local route, rest = split_route(arg)
    route = route or DEFAULT_ROUTE
    local id, value = parse_cmd_args(rest)
    if not id then
        send("ERR VIEW needs a command id")
        return
    end
    local ok, err = set_command(id, value, route)
    report(string.format("VIEW id=%d value=%s via=%s ok=%s err=%s", id, tostring(value),
        route, tostring(ok), oneline(err)))
    if ok then
        view_after.at_rt = (call(dcs_fn("getRealTime")) or 0) + VIEW_DELAY
        view_after.label = string.format("VIEW-AFTER %s id=%d", route, id)
    end
end

handlers.FOCUS = function(arg)
    arg = tostring(arg or ""):match("^%s*(.-)%s*$")
    if arg == "" then
        if focus.target then focus_done("cancelled") else send("FOCUS nothing to cancel") end
        return
    end
    local list = units()
    if not list then
        report("FOCUS unavailable: no units (LoGetWorldObjects)")
        return
    end
    -- Trailing words: a route and/or "fast", in any order.
    local route, delay = DEFAULT_ROUTE, FOCUS_DELAY
    while true do
        local head, word = arg:match("^(.-)%s+(%a+)$")
        if not word then break end
        local w = word:lower()
        if ROUTES[w] then route = w
        elseif w == "fast" then delay = FOCUS_FAST_DELAY
        else break end
        arg = head
    end
    local u = find_unit(arg, list)
    if not u then
        report("FOCUS no unit matches " .. oneline(arg))
        return
    end
    local r = call(dcs_fn("getRealTime")) or 0
    focus.target, focus.steps, focus.first, focus.visited = u.id, 0, nil, {}
    focus.route, focus.delay = route, delay
    focus.started_rt, focus.next_rt = r, r  -- the first step runs this frame
    report(string.format("FOCUS start %s every %.2fs target %s", route, delay, describe(u)))
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
    camv_tick(r)
    track_tick(m, r)

    if view_after.at_rt and r >= view_after.at_rt then
        local label = view_after.label
        view_after.at_rt, view_after.label = nil, nil
        report_cam(label)
    end
    focus_tick(r)

    if after.at_rt and r >= after.at_rt then
        -- The measured speed needs a full sample window at the new rate to settle, so raw is
        -- the quicker signal here; accel is what DCS says it is commanding.
        report(string.format("LOCMD-AFTER %s accel=%.3f speed=%.3f raw=%.3f paused=%s camv=%s camfwd=%s",
            after.label, commanded_accel(), sim.speed or -1, sim.raw or -1,
            tostring(call(dcs_fn("getPause"))), opt(camv.speed), opt(camv.fwd)))
        after.at_rt, after.label = nil, nil
    end

    if r >= sim.next_state_rt then
        sim.next_state_rt = r + STATE_INTERVAL
        send(string.format(
            "STATE t=%.3f rt=%.3f speed=%.3f raw=%.3f accel=%.3f paused=%s track=%s stop=%.3f start_tod=%s date=%s camv=%s camfwd=%s",
            m, r, sim.speed or -1, sim.raw or -1, commanded_accel(),
            tostring(call(dcs_fn("getPause"))), tostring(call(dcs_fn("isTrackPlaying"))),
            stop.target or -1, tostring(sim.start_tod), tostring(sim.date),
            opt(camv.speed), opt(camv.fwd)))
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
    camv_reset()
    track_reset()
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
