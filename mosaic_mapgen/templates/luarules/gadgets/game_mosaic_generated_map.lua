function gadget:GetInfo()
    return {name="MOSAIC generated map", desc="Authoritative map identity and checked deterministic placement", author="MOSAIC contributors", layer=100000, enabled=true}
end
if not gadgetHandler:IsSyncedCode() then return end
local context = VFS.Include("scripts/mosaic_map_context.lua").Read()
if not context then return end
local placements = VFS.Include("mosaic/placements.lua", nil, VFS.MAP)
local complete = false
local gaia = Spring.GetGaiaTeamID()
local function location()
    return {country=context.country, region=context.region, province=context.province,
            cityname=context.city, citypart=context.citypart}
end
function gadget:Initialize()
    assert(type(placements) == "table" and #placements > 0, "Generated map has no placements")
    -- Validate the entire plan before creating a single unit.
    local seen = {}
    for _, p in ipairs(placements) do
        assert(UnitDefNames[p.name], "Generated map requires missing UnitDef: " .. tostring(p.name))
        assert(type(p.id) == "string" and not seen[p.id], "Duplicate generated placement id")
        seen[p.id] = true
        assert(type(p.x) == "number" and type(p.z) == "number" and p.x > 0 and p.x < Game.mapSizeX and p.z > 0 and p.z < Game.mapSizeZ, "Invalid generated placement position")
        assert(p.kind == "building" or p.kind == "objective", "Invalid generated unit kind")
        assert(p.facing >= 0 and p.facing <= 3, "Invalid generated facing")
    end
    GG.MosaicMapContext = context
    GG.InstanceCulture = context.culture
    GG.boolRainyArea = context.rainy
    GG.Location = location()
    GG.innerCityCenter = {x=Game.mapSizeX/2, z=Game.mapSizeZ/2}
    Spring.SetGameRulesParam("culture", context.culture, {public=true})
    Spring.SetGameRulesParam("mosaic_map_context_version", 1, {public=true})
    Spring.SetGameRulesParam("mosaic_map_digest", context.generation_digest, {public=true})
    -- Objectives have a game lifecycle (destroyed markers/restores); never
    -- respawn the map's initial plan on LuaRules reload.
    complete = Spring.GetGameRulesParam("mosaic_map_placement_complete") == 1
    if complete then GG.MapCompletedBuildingPlacement = true end
end
function gadget:GameFrame(frame)
    if complete or frame < 1 then return end
    for _, p in ipairs(placements) do
        local id = Spring.CreateUnit(p.name, p.x, Spring.GetGroundHeight(p.x,p.z), p.z, p.facing, gaia)
        if not id then
            -- Abort rather than marking a partial, asymmetric spawn successful.
            error("Generated placement failed: " .. p.id)
        end
        Spring.SetUnitRulesParam(id, "mosaic_generated_placement", p.id, {public=true})
        if p.kind == "building" then
            GG.BuildingTable = GG.BuildingTable or {}
            GG.BuildingTable[id] = {x=p.x,z=p.z,address=p.address}
            GG.GeneratedCityAddresses=GG.GeneratedCityAddresses or {}
            if p.address then GG.GeneratedCityAddresses[p.address.plot_key]=p.address end
        end
    end
    complete = true
    GG.MapCompletedBuildingPlacement = true
    Spring.SetGameRulesParam("mosaic_map_placement_complete", 1, {public=true})
end
