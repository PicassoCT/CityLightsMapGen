"""Build-time tooling. Players execute the Lua packaged in the Spring map."""
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from .profiles import Config, COUNTRIES, LANDSCAPES, HOUSE_WEIGHTS, OBJECTIVES
from .export import lua, write_terrain
from .integration import transform, RAIN_FILES

RUNTIME = Path(__file__).parent / "runtime"
ADAPTER = Path(__file__).parent / "templates"

def bindings():
    return {"profiles.lua": "return " + lua({"countries": COUNTRIES, "landscapes": LANDSCAPES,
        "houses": HOUSE_WEIGHTS, "objectives": OBJECTIVES, "fallbacks": ["objective_market", "objective_hospital", "objective_industrialcomplex", "objective_university", "objective_powerplant", "objective_combatoutpost"]}),
        "package_identity.lua": 'return "development-source"'}

def lua_runtime():
    try:
        from lupa.lua51 import LuaRuntime
    except ImportError as exc:
        raise ValueError("Build-time Lua runtime missing: install .[runtime] or .[test]. Players need neither Python nor this package.") from exc
    runtime = LuaRuntime(unpack_returned_tuples=True, encoding=None)
    cache, extra = {}, bindings()
    def include(path, *_):
        name = path.decode().removeprefix("citylights/")
        if name not in cache:
            cache[name] = runtime.execute((extra.get(name) or (RUNTIME / name).read_text()).encode())
        return cache[name]
    runtime.globals().VFS = runtime.table_from({b"MAP": b"map", b"Include": include,
        b"CalculateHash": lambda content, kind: hashlib.sha512(content).hexdigest().encode()})
    return runtime, include

def build_original(config, source):
    from .generator import Generated
    runtime, include = lua_runtime()
    if config.size != 8192:
        raise ValueError("Map-contained prototype currently uses an 8192-unit container")
    west, south, east, north = source["bbox"]
    options = {"latitude": config.latitude, "longitude": (west + east) / 2, "bounds": source["bbox"],
        "seed": config.seed, "landscape": config.landscape, "country_code": config.country_code,
        "country": config.country, "region": config.region, "culture": config.culture,
        "city": config.city, "province": config.province, "max_buildings": config.max_buildings,
        "min_buildings": config.min_buildings, "objective_count": config.objective_pairs * 2}
    try:
        plan = include(b"citylights/generator.lua")[b"build"](runtime.eval(lua(source).encode()), runtime.eval(lua(options).encode()))
    except Exception as exc:
        raise ValueError(f"City generation failed: {exc}") from exc
    def python_value(v):
        if isinstance(v, bytes): return v.decode()
        if hasattr(v, "items"):
            items = list(v.items())
            if items and all(type(k) is int for k, _ in items) and sorted(k for k, _ in items) == list(range(1, len(items) + 1)):
                return [python_value(v[i]) for i in range(1, len(items) + 1)]
            return {python_value(k): python_value(val) for k, val in items}
        return v
    classes = np.array([plan[b"classes"][i] for i in range(1, 128 * 128 + 1)], dtype=np.uint8).reshape(128, 128)
    surface = classes.repeat(8, axis=0).repeat(8, axis=1)
    height = np.pad(np.where(surface == 4, -12, 32).astype(np.float32), ((0, 1), (0, 1)), mode="edge")
    return Generated(config, source, python_value(plan[b"context"]), height, surface,
        python_value(plan[b"units"]), python_value(plan[b"starts"]), python_value(plan[b"report"]))

def package_map(game_dir, destination, world_file=None):
    root, out = Path(game_dir), Path(destination)
    if out.exists() and any(out.iterdir()): raise ValueError("Output directory must be empty")
    required = ["scripts/lib_mosaic.lua", *RAIN_FILES, "luaui/widgets_mosaic/gui_cityname.lua", "luarules/gadgets/game_snipe_minigame.lua"]
    original = {p: (root / p).read_text(encoding="utf-8") for p in required}
    patched = transform(original)
    for p in sorted(ADAPTER.rglob("*.lua")): patched[p.relative_to(ADAPTER).as_posix()] = p.read_text()
    patched["MOSAIC-LICENSE.txt"] = (root / "LICENSE").read_text()
    patched["SOURCE-LICENSE.txt"] = "City data: OpenStreetMap contributors, ODbL-1.0, https://www.openstreetmap.org/copyright\nGame overlays modified by CityLights; retain upstream MOSAIC licensing. Sources are included as Lua.\n"
    assets = {"citylights/adapter/" + p: text.encode() for p, text in patched.items()}
    assets["citylights/adapter_files.lua"] = ("return " + lua(sorted(patched))).encode()
    assets.update({"citylights/" + p.name: p.read_bytes() for p in sorted(RUNTIME.glob("*.lua"))})
    assets.update({"citylights/" + name: text.encode() for name, text in bindings().items()})
    rings = []
    if world_file:
        for f in json.loads(Path(world_file).read_text())["features"]:
            g = f["geometry"]; polygons = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for polygon in polygons: rings.append([[round(x, 4), round(y, 4)] for x, y, *_ in polygon[0]])
        assets["citylights/world.lua"] = ("return " + lua(rings)).encode()
    with tempfile.TemporaryDirectory() as temp:
        config = Config(city="CityLights startup", country_code="DE", landscape="temperate", latitude=0)
        dummy = SimpleNamespace(surface=np.zeros((1024, 1024), dtype=np.uint8), height=np.full((1025, 1025), 32, dtype=np.float32), config=config, metadata={"generation_digest": "1" * 64})
        write_terrain(dummy, temp)
        assets["maps/startup.smf"] = (Path(temp) / "city.smf").read_bytes()
        assets["maps/city.smt"] = (Path(temp) / "city.smt").read_bytes()
        assets["citylights/template.smf"] = assets["maps/startup.smf"][:80]
    assets["luagaia/main.lua"] = (RUNTIME / "gaia_main.lua").read_bytes()
    assets["luagaia/draw.lua"] = (RUNTIME / "gaia_draw.lua").read_bytes()
    assets["luarules/gadgets.lua"] = (RUNTIME / "staging_rules.lua").read_bytes()
    assets["luaui/widgets_map/gui_citylights_startup.lua"] = (RUNTIME / "widget.lua").read_bytes()
    game_main = (root / "luarules/main.lua").read_text()
    widgets = (root / "luaui/mosaicwidgets.lua").read_text()
    if "luarules/gadgets.lua" not in game_main.lower() or "VFS.ZIP_ONLY" not in game_main: raise ValueError("Game gadget bootstrap changed; review map staging compatibility")
    if "WIDGET_DIRNAME_MAP" not in widgets or "VFS.MAP" not in widgets: raise ValueError("Game does not load map widgets")
    base_sources = {**original, "luarules/main.lua": game_main, "luaui/mosaicwidgets.lua": widgets}
    assets["citylights/adapter-source.json"] = json.dumps({"repository": "https://github.com/PicassoCT/MOSAIC", "base_source_sha512": {p: hashlib.sha512(s.encode()).hexdigest() for p, s in base_sources.items()}, "source_sha256": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in original.items()}}, sort_keys=True).encode()
    assets["MOSAIC-LICENSE.txt"] = (root / "LICENSE").read_bytes()
    digest = hashlib.sha512(b"".join(p.encode() + b"\0" + hashlib.sha512(b).digest() for p, b in sorted(assets.items()))).hexdigest()
    assets["citylights/package_identity.lua"] = ("return " + lua(digest)).encode()
    name = "MOSAIC CityLights World " + digest[:12]
    assets["mapinfo.lua"] = ("return " + lua({"name": name, "version": "0.2.0", "shortname": "CityLights World", "description": "Experimental world-city startup; player-hosted MOSAIC and LuaSocket required", "author": "MOSAIC contributors", "modtype": 3, "mapfile": "maps/startup.smf", "smf": {"minheight": -32, "maxheight": 256}, "teams": {0: {"startpos": {"x": 800, "z": 4096}}, 1: {"startpos": {"x": 7392, "z": 4096}}}})).encode()
    options = [{"key": "citylights_seed", "name": "Generation seed", "type": "number", "def": 1, "min": 0, "max": 2147483646, "step": 1},
        {"key": "citylights_latitude", "name": "Initial latitude", "type": "number", "def": 52.52, "min": -90, "max": 90, "step": 0.0001},
        {"key": "citylights_longitude", "name": "Initial longitude", "type": "number", "def": 13.405, "min": -180, "max": 180, "step": 0.0001},
        {"key": "citylights_radius", "name": "District radius (metres)", "type": "number", "def": 800, "min": 100, "max": 3000, "step": 100},
        {"key": "citylights_landscape", "name": "Landscape theme", "type": "list", "def": "temperate", "items": [{"key": k, "name": k.title()} for k in LANDSCAPES]}]
    assets["mapoptions.lua"] = ("return " + lua(options)).encode()
    assets["SOURCE-LICENSE.txt"] = b"City data: OpenStreetMap contributors, ODbL-1.0, https://www.openstreetmap.org/copyright\nWorld outlines when bundled: Natural Earth, public domain, https://www.naturalearthdata.com/about/terms-of-use/\nGame overlays retain upstream MOSAIC licensing and provenance.\n"
    out.mkdir(parents=True, exist_ok=True); package = out / "CityLightsWorld.sdd"
    for path, body in sorted(assets.items()):
        target = package / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(body)
    archive = out / "MOSAIC_CityLights_World.sdz"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path, body in sorted(assets.items()):
            entry = zipfile.ZipInfo(path, (1980, 1, 1, 0, 0, 0)); entry.compress_type = zipfile.ZIP_DEFLATED; entry.external_attr = 0o100644 << 16; z.writestr(entry, body)
    return {"archive": str(archive), "unpacked": str(package), "map_name": name, "package_identity": digest,
        "engine_smoke_test": "required; not performed by packager", "coastlines_bundled": True}
