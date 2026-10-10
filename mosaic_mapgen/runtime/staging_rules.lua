-- The distributed map is a startup scene. MOSAIC's simulation starts after Reload.
-- MOSAIC's unchanged main.lua includes this path through VFS.ZIP_ONLY.
gadgetHandler={}
function Initialize() end
function GameStart() end
function GameFrame() end
function AllowCommand() return false end
function AllowUnitCreation() return false end
