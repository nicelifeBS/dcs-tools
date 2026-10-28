-- =====================================================================================
-- DCS Replay Helper -- hook
-- =====================================================================================
-- Install as:  <Saved Games>\DCS\Scripts\Hooks\ReplayHelper.lua   (restart DCS)
--
-- Reports the replay clock to the Replay Helper app, pauses the sim on an exact model time,
-- changes time acceleration, and puts the F2 view on a given aircraft.
--
-- Object speeds are position changes (DCS exports no velocity): see the free camera section.
--
-- Speed and views are DCS input commands sent through DCS.dispatchDigitalAction, the only
-- route that reaches them during a replay (LoSetCommand from this state is ignored; see
-- SPIKE.md rounds 4-6): iCommandAccelerate 53, iCommandDecelerate 191, iCommandNoAcceleration
-- 246, iCommandViewAir 8. 8 is F2: from another view it shows the player's aircraft, in F2 it
-- steps to the next aircraft (all aircraft, by DCS id). No call sets the viewed unit or says
-- which it is, so FOCUS steps F2 and works out the viewed unit from the camera: the one
-- straight ahead (LoGetCameraPosition's x axis is forward), with the camera not inside
-- another unit (the cockpit).
--
--   hook -> app   127.0.0.1:47810
--     HELLO <version>
--     STATE t=<model s> rt=<real s> speed=<measured> accel=<commanded> paused=<bool>
--           track=<bool> stop=<armed target or -1> start_tod=<mission start, s of day or -1>
--           date=<YYYY-MM-DD or -> theatre=<name or -> cam=<m/s or -> [tgt=<id> tgt_along=<m/s or ->
--           tgt_side=<m/s or ->]                                               (~10 Hz)
--             cam: the free camera's speed along its view axis per second of model time, signed
--             tgt_*: the WATCHed object's speed along the camera's view axis, and across it
--     ARMED target=<t> now=<t>         ARRIVED t=<t> target=<t> over=<s>
--     DISARMED reason=<request|restart|mission_end>
--     FOCUSED id=<dcs id> steps=<n>
--     FOCUS-FAILED id=<dcs id or -> reason=<not_found|unavailable|no_camera|cycled|max_steps|
--                                          cancelled|restart|mission_end>
--     OBJ id=<dcs id> kind=<plane|heli|air|weapon> type=<> unit=<> group=<> coalition=<> human=<bool>
--         speed=<m/s> along=<m/s> side=<m/s> dist=<m> ahead=<m> age=<s>    (text %XX-encoded, - unknown)
--     OBJ-END count=<n> total=<n> t=<model s>
--     PONG <version>                   ERR <text>
--
--   app -> hook   127.0.0.1:47811
--     PING | PAUSE | RESUME | ARMSTOP <model t> | DISARM
--     SPEED UP|DOWN|NORMAL             one time-acceleration step; the result shows in accel=
--     FOCUS <dcs id> [unit name]       F2 on that aircraft (by id, else by unit name);
--                                      FOCUS alone cancels
--     TRACK on|off                     measure object speeds (needed by OBJECTS and WATCH)
--     OBJECTS [radius m]               answer with OBJ lines and OBJ-END
--     WATCH <dcs id>                   put that object's speed along the camera axis in STATE;
--                                      WATCH alone stops
--
-- The stop is checked here, every frame, because a round trip to the app costs ~100 ms of
-- real time -- 0.4 s of model time at 4x. Measured in DCS: 0.002 s late at 1x, 0.015 s at 4x.
--
-- Safety: this runs in DCS's GUI Lua state. An error at file scope silently drops the hook
-- and an error in a callback can break the menus, so every DCS call is pcall'd and nothing
-- runs outside a mission.
-- =====================================================================================

local TAG     = "REPLAYHELPER"
local VERSION = "0.3.0"

local HOST       = "127.0.0.1"
local STATE_PORT = 47810   -- hook -> app
local CMD_PORT   = 47811   -- app -> hook

local STATE_INTERVAL     = 0.1    -- real seconds between STATE packets
local SPEED_WINDOW       = 0.5    -- real seconds per speed sample
local STOPPED_RATIO      = 0.004  -- below this the sim is paused, not in slow motion (1/64x = 0.0156)
local RESTART_JUMP       = 1.0    -- model time going back by more than this means the track restarted
local MAX_CMDS_PER_FRAME = 16

local ACTION_SPEED = { UP = 53, DOWN = 191, NORMAL = 246 }  -- iCommandAccelerate & co.
local ACTION_VIEW_AIR  = 8      -- iCommandViewAir: F2
local FOCUS_STEP_S     = 0.1    -- real seconds between F2 steps (0.05 was enough in DCS)
local FOCUS_MAX_STEPS  = 150
local VIEW_MAX_DIST    = 5000   -- metres: a unit further from the camera is not the one viewed
local VIEW_MAX_OFF     = 15     -- degrees off the camera axis: 0-2 usually, 7 seen just after a switch
local INSIDE_DIST      = 10     -- metres: a camera this close to another unit is in its cockpit
local CAMV_WINDOW      = 0.25   -- real seconds per free-camera speed sample
local CAMV_MAX         = 5000   -- m/s: faster than this is a view jump, not a speed
local TRACK_INTERVAL   = 0.2    -- real seconds between object samples
local TRACK_MIN_DT     = 0.1    -- model seconds a speed is measured over; less is a pause, or noise
local TRACK_MAX_SPEED  = 3000   -- m/s: faster between two samples is a respawn or a jump, not a speed
local MAX_OBJECTS      = 100    -- objects listed per OBJECTS request

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

-- One token on the wire: no whitespace, nothing outside a safe set.
local function token(v)
    if v == nil then return "-" end
    local s = tostring(v):gsub("%s+", "_"):gsub("[^%w_%-%.]", "")
    if #s == 0 then return "-" end
    return s
end

-- One token on the wire that keeps its text: everything outside [A-Za-z0-9_.~-] as %XX.
local function enc(v)
    if v == nil then return "-" end
    local s = tostring(v):gsub("[^%w_%-%.~]", function(c) return string.format("%%%02X", c:byte()) end)
    if #s == 0 then return "-" end
    return s
end

local function opt(v, fmt)
    if v == nil then return "-" end
    return string.format(fmt or "%.2f", v)
end

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

local function export_fn(name)
    if type(Export) == "table" and type(Export[name]) == "function" then return Export[name] end
    return nil
end

local function action(id)
    local f = dcs_fn("dispatchDigitalAction")
    if type(f) ~= "function" then return false end
    return (pcall(f, id))
end

-- -------------------------------------------------------------------------------------
-- UDP link
-- -------------------------------------------------------------------------------------
local link = { tried = false, out = nil, inp = nil }

local function require_socket()
    local ok, mod = pcall(require, "socket")
    if ok and type(mod) == "table" then return mod end
    -- package.path only knows LuaSocket once some other script has added it.
    local root = "."
    if type(lfs) == "table" then root = call(lfs.currentdir) or "." end
    if not root:match("[/\\]$") then root = root .. "\\" end
    package.path  = package.path  .. ";" .. root .. "LuaSocket\\?.lua"
    package.cpath = package.cpath .. ";" .. root .. "LuaSocket\\?.dll"
    ok, mod = pcall(require, "socket")
    if ok and type(mod) == "table" then return mod end
    return nil, mod
end

local function send(line)
    if link.out then pcall(link.out.send, link.out, line) end
end

local function open_link()
    link.tried = true
    local socket, err = require_socket()
    if not socket then
        sayf("LuaSocket not available (%s) -- link disabled", tostring(err))
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
            sayf("cannot bind command port %d (%s)", CMD_PORT, tostring(berr or res))
        end
    end

    sayf("link: state -> %s:%d %s, commands <- %s:%d %s",
        HOST, STATE_PORT, link.out and "ok" or "FAILED",
        HOST, CMD_PORT, link.inp and "ok" or "FAILED")
    send("HELLO " .. VERSION)
end

-- -------------------------------------------------------------------------------------
-- sim state
-- -------------------------------------------------------------------------------------
local sim = {
    in_mission    = false,
    last_m        = nil,   -- model time on the previous frame (restart detection)
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

local function commanded_accel()
    local v = call(export_fn("LoGetModelTimeAcceleration"))
    return type(v) == "number" and v or -1
end

local function read_mission_info()
    sim.start_tod, sim.date, sim.theatre = nil, nil, nil
    local mis = call(dcs_fn("getCurrentMission"))
    local m = type(mis) == "table" and mis.mission or nil
    if type(m) ~= "table" then return end
    sim.start_tod = tonumber(m.start_time)
    local d = m.date
    if type(d) == "table" and tonumber(d.Year) then
        sim.date = string.format("%04d-%02d-%02d",
            tonumber(d.Year) or 0, tonumber(d.Month) or 0, tonumber(d.Day) or 0)
    end
    sim.theatre = m.theatre
end

local function reset_clock()
    sim.last_m = nil
    sim.sample_m, sim.sample_r = nil, nil
    sim.raw, sim.speed = nil, nil
    sim.next_state_rt = 0
end

local function disarm(reason)
    if stop.target then
        stop.target = nil
        send("DISARMED reason=" .. reason)
        sayf("stop disarmed (%s)", reason)
    end
end

-- Speed is measured, never inferred from the keys the app sent.
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

local function check_stop(m)
    if stop.target and m >= stop.target then
        local target = stop.target
        stop.target = nil
        call(dcs_fn("setPause"), true)
        send(string.format("ARRIVED t=%.3f target=%.3f over=%.3f", m, target, m - target))
        sayf("stop reached: t=%.3f target=%.3f", m, target)
    end
end

-- -------------------------------------------------------------------------------------
-- camera: which aircraft is in view, and F2 stepping to one
-- -------------------------------------------------------------------------------------
local function vec(t)
    if type(t) ~= "table" then return nil end
    local x, y, z = tonumber(t.x), tonumber(t.y), tonumber(t.z)
    if x and y and z then return { x = x, y = y, z = z } end
    return nil
end

-- Angle in degrees between d and the unit vector-ish axis a.
local function angle_deg(d, a)
    local ld = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z)
    local la = math.sqrt(a.x * a.x + a.y * a.y + a.z * a.z)
    if ld == 0 or la == 0 then return 180 end
    local c = (d.x * a.x + d.y * a.y + d.z * a.z) / (ld * la)
    return math.deg(math.acos(math.max(-1, math.min(1, c))))
end

-- id -> { name, pos } for every unit DCS exports; nil if it exports none.
local function world_units()
    local objs = call(export_fn("LoGetWorldObjects"))
    if type(objs) ~= "table" then return nil end
    local units = {}
    for id, o in pairs(objs) do
        if type(o) == "table" and tonumber(id) then
            units[tonumber(id)] = { unit = o.UnitName, pos = vec(o.Position) }
        end
    end
    return units
end

-- The id of the unit in view, or nil (cockpit, free camera, nothing ahead). Second value: a
-- reason when it can't be told at all.
local function viewed_id(units)
    local cam = call(export_fn("LoGetCameraPosition"))
    local p, x = type(cam) == "table" and vec(cam.p), type(cam) == "table" and vec(cam.x)
    if not (p and x) then return nil, "no_camera" end
    -- The nearest unit close to the line of sight: a unit further down the same line (a
    -- formation ahead, a ship below) is not the one F2 is showing.
    local best, best_dist, nearest, nearest_dist
    for id, u in pairs(units) do
        if u.pos then
            local d = { x = u.pos.x - p.x, y = u.pos.y - p.y, z = u.pos.z - p.z }
            local dist = math.sqrt(d.x * d.x + d.y * d.y + d.z * d.z)
            if dist <= VIEW_MAX_DIST then
                if angle_deg(d, x) <= VIEW_MAX_OFF and (not best_dist or dist < best_dist) then
                    best, best_dist = id, dist
                end
                if not nearest_dist or dist < nearest_dist then nearest, nearest_dist = id, dist end
            end
        end
    end
    if not best then return nil end
    if nearest ~= best and nearest_dist < INSIDE_DIST then return nil end  -- in a cockpit
    return best
end

local focus = { target = nil }

local function focus_end(line)
    focus.target = nil
    send(line)
end

local function focus_fail(reason)
    if focus.target then
        sayf("focus on %d failed: %s", focus.target, reason)
        focus_end(string.format("FOCUS-FAILED id=%d reason=%s", focus.target, reason))
    end
end

-- One F2 step per FOCUS_STEP_S until the target is in view. A full cycle (back to the first
-- unit seen) means F2 can't reach it.
local function focus_tick(r)
    if not focus.target or r < focus.next_rt then return end
    local units = world_units()
    if not units then
        focus_fail("unavailable")
        return
    end
    if not units[focus.target] then
        focus_fail("not_found")  -- destroyed or despawned meanwhile
        return
    end
    local id, why = viewed_id(units)
    if why then
        focus_fail(why)
        return
    end
    if id == focus.target then
        focus_end(string.format("FOCUSED id=%d steps=%d", focus.target, focus.steps))
        return
    end
    if id then
        focus.waited = false
        if focus.first == nil then
            focus.first = id
        elseif id == focus.first then
            focus_fail("cycled")
            return
        end
    elseif focus.steps > 0 and not focus.waited then
        -- Nothing in view just after an F2 step: the camera may still be swinging onto the
        -- next aircraft. Look once more before stepping past it.
        focus.waited = true
        focus.next_rt = r + FOCUS_STEP_S
        return
    end
    if focus.steps >= FOCUS_MAX_STEPS then
        focus_fail("max_steps")
        return
    end
    if not action(ACTION_VIEW_AIR) then
        focus_fail("unavailable")
        return
    end
    focus.steps = focus.steps + 1
    focus.next_rt = r + FOCUS_STEP_S
end

-- -------------------------------------------------------------------------------------
-- free camera speed and object speeds (SPIKE.md rounds 7-8)
-- -------------------------------------------------------------------------------------
-- The free camera (F11) flies along its view axis at a set speed, in replay (model) time.
-- DCS reports neither that speed nor an object's, so both are position changes: the camera's
-- over real time, divided by the time acceleration; an object's over model time.
local function vsub(a, b) return { x = a.x - b.x, y = a.y - b.y, z = a.z - b.z } end
local function vdot(a, b) return a.x * b.x + a.y * b.y + a.z * b.z end
local function vlen(a) return math.sqrt(vdot(a, a)) end

local function camera()
    local cam = call(export_fn("LoGetCameraPosition"))
    local p, x = type(cam) == "table" and vec(cam.p), type(cam) == "table" and vec(cam.x)
    if p and x then return { p = p, x = x } end
    return nil
end

-- model: the camera's speed along its view axis per second of model time, signed (negative:
-- flying backward). This is the number to compare with an object's `along`.
local camv = { p = nil, r = nil, model = nil, at = nil }

local function camv_reset()
    camv.p, camv.r, camv.model, camv.at = nil, nil, nil, nil
end

local function camv_tick(r)
    if camv.r and r - camv.r < CAMV_WINDOW then return end
    local cam = camera()
    if not cam then
        camv_reset()
        return
    end
    if camv.p and camv.r then
        local dt, axis, accel = r - camv.r, vlen(cam.x), commanded_accel()
        if dt > 0 and axis > 0 and accel > 0 then
            local fwd = vdot(vsub(cam.p, camv.p), cam.x) / axis / dt
            if math.abs(fwd) <= CAMV_MAX then
                camv.model, camv.at = fwd / accel, r
            else
                camv.model = nil  -- a view change moved the camera
            end
        end
    end
    camv.p, camv.r = cam.p, r
end

-- track.mov[id] = { u = unit, kind, pos, m, v, speed, vm }: v is the velocity in m/s from the
-- last two positions at least TRACK_MIN_DT of model time apart, and survives a pause (vm says
-- when it was measured).
local track = { on = false, next_rt = 0, last_m = nil, mov = {} }

local function track_reset()
    track.last_m, track.mov, track.next_rt = nil, {}, 0
end

-- plane, heli, "air" (other air objects), weapon (from the ballistic list), else nil.
local function kind_of(u)
    if u.weapon then return "weapon" end
    if u.l1 == 1 then
        if u.l2 == 1 then return "plane" end
        if u.l2 == 2 then return "heli" end
        return "air"
    end
    return nil
end

local function object_list(arg)
    local objs = call(export_fn("LoGetWorldObjects"), arg)
    if type(objs) ~= "table" then return nil end
    local list = {}
    for id, o in pairs(objs) do
        if type(o) == "table" and tonumber(id) then
            local t = type(o.Type) == "table" and o.Type or {}
            list[#list + 1] = {
                id = tonumber(id), name = o.Name, unit = o.UnitName, group = o.GroupName,
                coalition = o.Coalition, human = type(o.Flags) == "table" and o.Flags.Human or false,
                pos = vec(o.Position), weapon = arg == "ballistic", l1 = t.level1, l2 = t.level2,
            }
        end
    end
    return list
end

local function track_tick(m, r)
    if not track.on or r < track.next_rt then return end
    track.next_rt = r + TRACK_INTERVAL
    if track.last_m and m < track.last_m - RESTART_JUMP then track_reset() end
    if track.last_m and m - track.last_m < TRACK_MIN_DT then return end  -- paused: keep what we have

    local list = object_list(nil)
    if not list then return end
    for _, w in ipairs(object_list("ballistic") or {}) do list[#list + 1] = w end

    local now = {}
    for _, u in ipairs(list) do
        local kind = kind_of(u)
        if kind and u.pos then
            local prev = track.mov[u.id]
            local e = { u = u, kind = kind, pos = u.pos, m = m }
            if prev then
                e.v, e.speed, e.vm = prev.v, prev.speed, prev.vm
                local dt = m - prev.m
                if dt >= TRACK_MIN_DT then
                    local d = vsub(u.pos, prev.pos)
                    local v = { x = d.x / dt, y = d.y / dt, z = d.z / dt }
                    local speed = vlen(v)
                    if speed <= TRACK_MAX_SPEED then
                        e.v, e.speed, e.vm = v, speed, m
                    else
                        e.v, e.speed, e.vm = nil, nil, nil
                    end
                else
                    e.pos, e.m = prev.pos, prev.m  -- not enough time yet: measure from the older sample
                end
            end
            now[u.id] = e
        end
    end
    track.mov, track.last_m = now, m
end

-- The object's motion as seen from the camera. along: its velocity on the camera's view axis,
-- signed -- the speed the free camera must have to keep up, negative meaning flying backward.
-- side: the rest of its speed, which the camera cannot follow. ahead: its offset on the axis.
local function motion(e, cam)
    local out = { speed = e.speed }
    if cam and cam.p then out.dist = vlen(vsub(e.pos, cam.p)) end
    local axis = cam and vlen(cam.x) or 0
    if e.v and axis > 0 then
        out.along = vdot(e.v, cam.x) / axis
        out.side = math.sqrt(math.max(0, e.speed * e.speed - out.along * out.along))
        out.ahead = vdot(vsub(e.pos, cam.p), cam.x) / axis
    end
    return out
end

local watch = { id = nil }

local function watch_fields()
    if not watch.id then return "" end
    local e = track.mov[watch.id]
    local mo = e and motion(e, camera()) or {}
    return string.format(" tgt=%d tgt_along=%s tgt_side=%s", watch.id, opt(mo.along), opt(mo.side))
end

-- -------------------------------------------------------------------------------------
-- commands
-- -------------------------------------------------------------------------------------
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

-- Forward only: a target at or behind the playhead is refused, never "reached" at once.
handlers.ARMSTOP = function(arg)
    local t = arg:match("^%s*(%-?%d+%.?%d*)%s*$")
    t = tonumber(t)
    if not t then
        send("ERR ARMSTOP needs a model time")
        return
    end
    local now = model_time()
    if type(now) ~= "number" then
        send("ERR ARMSTOP no model time")
        return
    end
    if t <= now then
        send(string.format("ERR behind target=%.3f now=%.3f", t, now))
        return
    end
    stop.target = t
    send(string.format("ARMED target=%.3f now=%.3f", t, now))
end

handlers.DISARM = function()
    if stop.target then
        disarm("request")
    else
        send("DISARMED reason=request")
    end
end

handlers.SPEED = function(arg)
    local id = ACTION_SPEED[tostring(arg):upper():match("^%s*(%a+)%s*$") or ""]
    if not id then
        send("ERR SPEED needs UP, DOWN or NORMAL")
        return
    end
    if not action(id) then send("ERR SPEED unavailable: no DCS.dispatchDigitalAction") end
end

-- TRACK on|off: measure object speeds (about 5 world-object reads a second).
handlers.TRACK = function(arg)
    local word = tostring(arg):lower():match("^%s*(%a*)%s*$") or ""
    if word == "on" then
        if not track.on then track.on, track.next_rt = true, 0 end
    elseif word == "off" then
        track.on = false
        watch.id = nil
        track_reset()
    else
        send("ERR TRACK needs on or off")
    end
end

-- OBJECTS [radius]: one OBJ line per aircraft, helicopter and weapon (nearest to the camera
-- first), then OBJ-END. Speeds are m/s; "-" is unknown (not measured yet).
handlers.OBJECTS = function(arg)
    if not track.on then
        send("ERR OBJECTS needs TRACK on")
        return
    end
    local radius = tonumber(tostring(arg):match("^%s*(%d+%.?%d*)%s*$"))
    local now_m = model_time() or 0
    local cam = camera()
    local list = {}
    for _, e in pairs(track.mov) do
        local mo = motion(e, cam)
        if not radius or not mo.dist or mo.dist <= radius then
            list[#list + 1] = { e = e, mo = mo }
        end
    end
    table.sort(list, function(a, b)
        if a.mo.dist and b.mo.dist and a.mo.dist ~= b.mo.dist then return a.mo.dist < b.mo.dist end
        return a.e.u.id < b.e.u.id
    end)
    local n = math.min(#list, MAX_OBJECTS)
    for i = 1, n do
        local e, mo, u = list[i].e, list[i].mo, list[i].e.u
        send(string.format(
            "OBJ id=%d kind=%s type=%s unit=%s group=%s coalition=%s human=%s speed=%s along=%s side=%s dist=%s ahead=%s age=%s",
            u.id, e.kind, enc(u.name), enc(u.unit), enc(u.group), enc(u.coalition), tostring(u.human == true),
            opt(mo.speed, "%.2f"), opt(mo.along, "%.2f"), opt(mo.side, "%.2f"), opt(mo.dist, "%.0f"),
            opt(mo.ahead, "%.0f"), opt(e.vm and now_m - e.vm, "%.1f")))
    end
    send(string.format("OBJ-END count=%d total=%d t=%.3f", n, #list, now_m))
end

-- WATCH <id>: report that object's speed along the camera view axis in every STATE
-- (tgt_along=, tgt_side=); WATCH alone stops. Turns TRACK on.
handlers.WATCH = function(arg)
    local id = tonumber(tostring(arg):match("^%s*(%d+)%s*$"))
    if not id then
        watch.id = nil
        if not tostring(arg):match("^%s*$") then send("ERR WATCH needs a DCS id") end
        return
    end
    watch.id = id
    if not track.on then track.on, track.next_rt = true, 0 end
end

-- FOCUS <dcs id> [unit name]: the id is tried first, then an exact unit name.
handlers.FOCUS = function(arg)
    local id, name = tostring(arg):match("^%s*(%d+)%s*(.-)%s*$")
    if focus.target then focus_fail("cancelled") end
    if not id then
        if not arg:match("^%s*$") then send("ERR FOCUS needs a DCS id") end
        return
    end
    id = tonumber(id)
    local units = world_units()
    if not units then
        send(string.format("FOCUS-FAILED id=%d reason=unavailable", id))
        return
    end
    if not units[id] and name ~= "" then
        for uid, u in pairs(units) do
            if u.unit == name then id = uid break end
        end
    end
    if not units[id] then
        send(string.format("FOCUS-FAILED id=%d reason=not_found", id))
        return
    end
    if type(dcs_fn("dispatchDigitalAction")) ~= "function" then
        send(string.format("FOCUS-FAILED id=%d reason=unavailable", id))
        return
    end
    focus.target, focus.steps, focus.first, focus.waited = id, 0, nil, false
    focus.next_rt = call(dcs_fn("getRealTime")) or 0  -- the first check runs this frame
end

local function dispatch(line)
    line = tostring(line):gsub("%s+$", "")
    local word, arg = line:match("^(%S+)%s*(.*)$")
    if not word then return end
    local h = handlers[word:upper()]
    if h then
        h(arg)
    else
        send("ERR unknown command " .. token(word))
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
            if not okh then sayf("command failed: %s", tostring(err)) end
        end
    end

    local m = model_time()
    if type(m) ~= "number" then return end

    -- A track that ends and is replayed starts again at t=0. A stop armed for the old pass
    -- would fire at a moment nobody asked for in the new one.
    if sim.last_m and m < sim.last_m - RESTART_JUMP then
        sayf("model time went back %.3f -> %.3f: track restarted", sim.last_m, m)
        disarm("restart")
        focus_fail("restart")
        track_reset()
        camv_reset()
        reset_clock()
        pcall(read_mission_info)
    end
    sim.last_m = m

    check_stop(m)

    local r = call(dcs_fn("getRealTime"))
    if type(r) ~= "number" then return end
    measure(m, r)
    camv_tick(r)
    track_tick(m, r)
    focus_tick(r)

    if r >= sim.next_state_rt then
        sim.next_state_rt = r + STATE_INTERVAL
        send(string.format(
            "STATE t=%.3f rt=%.3f speed=%.3f accel=%.3f paused=%s track=%s stop=%.3f start_tod=%s date=%s theatre=%s cam=%s%s",
            m, r, sim.speed or -1, commanded_accel(),
            tostring(call(dcs_fn("getPause")) == true), tostring(call(dcs_fn("isTrackPlaying")) == true),
            stop.target or -1, sim.start_tod and string.format("%.3f", sim.start_tod) or "-1",
            token(sim.date), token(sim.theatre), opt(camv.model, "%.3f"), watch_fields()))
    end
end

-- -------------------------------------------------------------------------------------
-- callbacks
-- -------------------------------------------------------------------------------------
local frame_error_logged = false
local callbacks = {}

function callbacks.onMissionLoadEnd()
    sim.in_mission = true
    stop.target = nil
    focus.target = nil
    watch.id = nil
    track.on = false
    track_reset()
    camv_reset()
    reset_clock()
    pcall(read_mission_info)
    sayf("mission loaded: start_time=%s date=%s theatre=%s track=%s",
        tostring(sim.start_tod), tostring(sim.date), tostring(sim.theatre),
        tostring(call(dcs_fn("isTrackPlaying"))))
end

function callbacks.onSimulationStop()
    disarm("mission_end")
    focus_fail("mission_end")
    watch.id = nil
    track.on = false
    sim.in_mission = false
end

function callbacks.onSimulationFrame()
    local ok, err = pcall(on_frame)
    if not ok and not frame_error_logged then
        frame_error_logged = true
        sayf("frame error (logged once): %s", tostring(err))
    end
end

local ok, err = pcall(DCS.setUserCallbacks, callbacks)
sayf("loaded %s (callbacks %s)", VERSION, ok and "registered" or ("FAILED: " .. tostring(err)))
