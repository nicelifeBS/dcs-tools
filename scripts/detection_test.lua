-- CONFIGURATION
local hostileGroupName = "RedSAMs"
local zoneName = "WatchZone"
local altitudeThreshold = 20 -- meters AGL
local checkInterval = 2 -- seconds

-- Get the zone from ME
local zone = trigger.misc.getZone(zoneName)

-- State flag
local blueWasInZone = false

-- Get altitude above ground
local function getUnitAGL(unit)
    if not unit or not unit:isExist() then return 0 end
    local pos = unit:getPoint()
    local terrainAlt = land.getHeight({x = pos.x, y = pos.z})
    return pos.y - terrainAlt
end

-- Check if a point is inside the zone
local function isInZone(point, zone)
    local dx = point.x - zone.point.x
    local dz = point.z - zone.point.z
    return (dx * dx + dz * dz) <= (zone.radius * zone.radius)
end

-- Check if any Blue aircraft is in the zone
local function anyBlueAircraftInZone()
    local units = coalition.getPlayers(coalition.side.BLUE)
    for _, unit in pairs(units) do
        if unit:isExist() and unit:getDesc().category == Unit.Category.AIRPLANE then
            local pos = unit:getPoint()
            if isInZone(pos, zone) then
                return true
            end
        end
    end
    return false
end

-- Check if any Blue aircraft is in zone AND above threshold
local function anyBlueAircraftInZoneAboveThreshold()
    local units = coalition.getPlayers(coalition.side.BLUE)
    for _, unit in pairs(units) do
        if unit:isExist() and unit:getDesc().category == Unit.Category.AIRPLANE then
            local pos = unit:getPoint()
            if isInZone(pos, zone) then
                local agl = getUnitAGL(unit)
                if agl >= altitudeThreshold then
                    return true
                end
            end
        end
    end
    return false
end

-- Main monitor loop
local function monitorZone()
    local group = Group.getByName(hostileGroupName)
    if not group or not group:isExist() then return end

    local blueInZoneNow = anyBlueAircraftInZone()

    -- Entry message
    if blueInZoneNow and not blueWasInZone then
        trigger.action.outTextForCoalition(coalition.side.BLUE, "Blue unit has entered the zone", 5)
    end

    blueWasInZone = blueInZoneNow

    -- ROE logic
    if anyBlueAircraftInZoneAboveThreshold() then
        group:getController():setOption(AI.Option.Ground.id.ROE, AI.Option.Ground.val.ROE.WEAPON_HOLD)
        group:getController():setOption(AI.Option.Ground.id.ROE, AI.Option.Ground.val.ROE.OPEN_FIRE)
    else
        group:getController():setOption(AI.Option.Ground.id.ROE, AI.Option.Ground.val.ROE.WEAPON_HOLD)
    end

    timer.scheduleFunction(monitorZone, nil, timer.getTime() + checkInterval)
end

-- Start monitoring
monitorZone()

-- Event handler for missile fire
local function onEventMissileFired(event)
    if event.id == world.event.S_EVENT_SHOT and event.initiator then
        local shooterCoalition = coalition.getCoalition(event.initiator)
        if shooterCoalition == coalition.side.RED then
            trigger.action.outTextForCoalition(coalition.side.BLUE, "Missile launch detected!", 4)
        end
    end
end

-- Register the event
world.addEventHandler({ onEvent = onEventMissileFired })
