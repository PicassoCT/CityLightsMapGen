-- Authoritative per-map identity, read directly in every Lua VM.
-- No client messages, random country guesses, or per-frame metadata traffic.
local M = {}
function M.Read()
    if not VFS.FileExists("mosaic/map_config.lua", VFS.MAP) then return nil end
    local c = VFS.Include("mosaic/map_config.lua", nil, VFS.MAP)
    assert(type(c) == "table" and c.schema == 1, "Unsupported MOSAIC map context")
    for _, key in ipairs({"country", "country_code", "city", "region", "culture", "landscape", "generation_digest"}) do
        assert(type(c[key]) == "string" and #c[key] > 0, "Missing map context: " .. key)
    end
    assert(c.culture == "arabic" or c.culture == "asian" or c.culture == "western" or c.culture == "international", "Invalid map culture")
    assert(type(c.rainy) == "boolean" and type(c.day_color) == "table" and #c.day_color == 3, "Invalid landscape weather")
    assert(type(c.sun_max_altitude) == "number" and (c.equatorial_sign == -1 or c.equatorial_sign == 1), "Invalid map sun")
    assert(type(c.house_types) == "table" and type(c.sin_city) == "boolean", "Invalid architectural policy")
    assert(c.placement == "manual" and (c.balance == "mirror-x" or c.balance == "opportunity-graph"), "Invalid placement contract")
    assert(c.size == Game.mapSizeX and c.size == Game.mapSizeZ, "Map context dimensions do not match terrain")
    return c
end
return M
