function widget:GetInfo()
    return {name="MOSAIC generated location", desc="Display authoritative city, country and landscape", author="MOSAIC contributors", layer=100000, enabled=true}
end
local context = VFS.Include("scripts/mosaic_map_context.lua").Read()
if not context then return end
function widget:Initialize()
    WG.MosaicMapContext = context
end
function widget:DrawScreen()
    local _, height = Spring.GetViewGeometry()
    gl.Color(1,1,1,0.85)
    gl.Text(context.city .. " | " .. context.country .. " | " .. context.landscape, 20, height-40, 16, "o")
    if context.source_attribution then
        gl.Text(context.source_attribution .. " | " .. (context.source_license or ""), 20, height-62, 11, "o")
    end
    gl.Color(1,1,1,1)
end
function widget:Shutdown()
    if WG.MosaicMapContext == context then WG.MosaicMapContext = nil end
end
