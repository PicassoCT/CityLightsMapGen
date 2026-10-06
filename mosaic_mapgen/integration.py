"""Fail-closed integration installer. No publication or game changes during map builds."""
import hashlib
import json
import re
from pathlib import Path

MARKER = "-- MOSAIC_MAPGEN_CONTEXT_V1"
LIB_HOOKS = {
    "getInstanceCultureOrDefaultToo": "return mosaicMapContext.culture",
    "getCountryByCulture": "return mosaicMapContext.country, mosaicMapContext.region",
    "getRegionByCulture": "return mosaicMapContext.region",
    "GetRegionByHash": "return mosaicMapContext.region",
    "GetCultureByRegion": "return mosaicMapContext.culture",
    "getRegionDayColorBy": "return makeVector(unpack(mosaicMapContext.day_color))",
    "getAzimuthByRegion": "return mosaicMapContext.sun_max_altitude, mosaicMapContext.equatorial_sign",
    "getManualCivilianBuildingMaps": "return true",
    "getManualObjectiveSpawnMapNames": "return true",
    "detectMapControlledPlacementComplete": "return GG.MapCompletedBuildingPlacement == true",
    "getMapDependentHouseTypes": "return mosaicMapContext.house_types",
    "mapOverideSinCity": "return mosaicMapContext.sin_city",
}
RAIN_FILES = ["luarules/gadgets/gfx_neonHolograms.lua", "luaui/widgets_mosaic/gfx_rain.lua", "luaui/widgets_mosaic/gfx_heathaze.lua"]

def function_hook(text,name,statement,local=False):
    pattern = rf"\b{'local ' if local else ''}function\s+{name}\s*\([^)]*\)"
    matches = list(re.finditer(pattern,text))
    if len(matches)!=1:
        raise ValueError(f"Expected one {name} function, found {len(matches)}; adapter must be reviewed for this MOSAIC revision")
    pos = matches[0].end()
    return text[:pos]+f"\n    if mosaicMapContext then {statement} end\n"+text[pos:]

def transform(files):
    if any(MARKER in text for text in files.values()):
        raise ValueError("Adapter patches already present; do not apply them twice")
    prefix = MARKER+'\nlocal mosaicMapContext = VFS.Include("scripts/mosaic_map_context.lua").Read()\n'
    library = files["scripts/lib_mosaic.lua"]
    for name,statement in LIB_HOOKS.items():
        library = function_hook(library,name,statement)
    needle = "if GG.boolRainyArea == nil then"
    if library.count(needle)!=1:
        raise ValueError("Unknown lib_mosaic rain-area initialization")
    library = library.replace(needle,"if mosaicMapContext then GG.boolRainyArea = mosaicMapContext.rainy end\n                "+needle)
    result = {"scripts/lib_mosaic.lua":prefix+library}
    for path in RAIN_FILES:
        result[path] = prefix+function_hook(files[path],"isRainyArea","return mosaicMapContext.rainy",local=True)
    ui = "luaui/widgets_mosaic/gui_cityname.lua"
    result[ui] = MARKER+'\nif VFS.FileExists("mosaic/map_config.lua", VFS.MAP) then return end\n'+files[ui]
    snipe = "luarules/gadgets/game_snipe_minigame.lua"
    needle = 'if msg and string.find(msg, "LOCATION:") then'
    if files[snipe].count(needle)!=1:
        raise ValueError("Unknown location-message handler")
    # Generated maps never accept a client's geographic identity as authoritative.
    result[snipe] = prefix+files[snipe].replace(needle,'if not mosaicMapContext and msg and string.find(msg, "LOCATION:") then')
    return result

def install_adapter(game_dir,apply=False):
    root = Path(game_dir).resolve()
    paths = ["scripts/lib_mosaic.lua",*RAIN_FILES,"luaui/widgets_mosaic/gui_cityname.lua","luarules/gadgets/game_snipe_minigame.lua"]
    original = {p:(root/p).read_bytes() for p in paths}
    text = {p:b.decode("utf-8").replace("\r\n","\n") for p,b in original.items()}
    patched = transform(text)
    templates = Path(__file__).parent/"templates"
    for source in sorted(templates.rglob("*.lua")):
        path = source.relative_to(templates).as_posix()
        if (root/path).exists():
            raise ValueError(f"Refusing to replace existing adapter file: {path}")
        patched[path] = source.read_text(encoding="utf-8")
    digest = hashlib.sha256(b"".join(original[p] for p in paths)).hexdigest()
    result = {"applied":False,"base_digest":digest,"files":list(patched),"compatibility":"All required anchors checked; run Lua tests and inspect in Recoil after applying"}
    if not apply:
        return result
    backup = root/".mosaic-mapgen-backup"/digest[:16]
    if backup.exists():
        raise ValueError("Backup directory already exists; inspect previous installation")
    backup.mkdir(parents=True)
    for p,b in original.items():
        dest = backup/p
        dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(b)
    (backup/"installation.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    written=[]
    try:
        for p,value in patched.items():
            dest = root/p
            dest.parent.mkdir(parents=True,exist_ok=True)
            dest.write_text(value,encoding="utf-8");written.append(p)
    except OSError:
        for p in written:
            if p in original:
                (root/p).write_bytes(original[p])
            else:
                (root/p).unlink(missing_ok=True)
        raise
    result.update(applied=True,backup=str(backup))
    return result
