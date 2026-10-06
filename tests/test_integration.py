import os
import tempfile
import unittest
from pathlib import Path
from mosaic_mapgen.integration import transform,LIB_HOOKS,RAIN_FILES,install_adapter
from mosaic_mapgen.profiles import Config
from mosaic_mapgen.export import lua
try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime=None

ROOT=Path(__file__).resolve().parents[1]
TEMPLATES=ROOT/"mosaic_mapgen/templates"

def compatible_files():
    library="\n".join(f'function {name}() return "legacy" end' for name in LIB_HOOKS)
    library+='\nfunction isRaining() if GG.boolRainyArea == nil then GG.boolRainyArea=false end end\n'
    return {"scripts/lib_mosaic.lua":library,**{p:'local function isRainyArea() return true end\n' for p in RAIN_FILES},
        "luaui/widgets_mosaic/gui_cityname.lua":'function widget:GetInfo() return {name="legacy location"} end\n',
        "luarules/gadgets/game_snipe_minigame.lua":'function gadget:RecvLuaMsg(msg) if msg and string.find(msg, "LOCATION:") then GG.Location="client" end end\n'}

class InstallerTests(unittest.TestCase):
    def test_incompatible_revision_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            files=compatible_files();files["scripts/lib_mosaic.lua"]="-- incompatible\n"
            for p,text in files.items():
                (root/p).parent.mkdir(parents=True,exist_ok=True);(root/p).write_text(text)
            with self.assertRaises(ValueError):install_adapter(root,True)
            for p,text in files.items():self.assertEqual((root/p).read_text(),text)
            self.assertFalse((root/".mosaic-mapgen-backup").exists())

    def test_dry_run_backups_and_double_install_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for p,text in compatible_files().items():
                (root/p).parent.mkdir(parents=True,exist_ok=True);(root/p).write_text(text)
            result=install_adapter(root)
            self.assertFalse(result["applied"])
            self.assertFalse((root/"scripts/mosaic_map_context.lua").exists())
            result=install_adapter(root,True)
            self.assertTrue(result["applied"])
            self.assertEqual((Path(result["backup"])/"scripts/lib_mosaic.lua").read_text(),compatible_files()["scripts/lib_mosaic.lua"])
            with self.assertRaises(ValueError):install_adapter(root,True)

@unittest.skipIf(LuaRuntime is None,"Install test extra for actual Lua 5.1 execution")
class LuaTests(unittest.TestCase):
    def runtime(self,has_context=True):
        r=LuaRuntime(unpack_returned_tuples=True)
        config=Config(city="Berlin",country_code="DE",province="Berlin",landscape="temperate",latitude=52.52).metadata("source")
        config["generation_digest"]="a"*64
        r.globals().context=r.eval(lua(config)) if has_context else None
        r.execute('''
            Game={mapSizeX=8192,mapSizeZ=8192,mapName="Dubai-spoof"}; GG={}; WG={}; widget={}; gadget={}
            rules={}; created={}; params={}; UnitDefNames={house_western0={id=1},objective_hospital={id=2}}
            Spring={GetGaiaTeamID=function() return 0 end, GetGameRulesParam=function(k) return rules[k] end,
              SetGameRulesParam=function(k,v) rules[k]=v end, SetUnitRulesParam=function(id,k,v) params[id]=v end,
              GetGroundHeight=function() return 32 end,
              CreateUnit=function(name,x,y,z,facing,team) created[#created+1]={name=name,x=x,z=z,facing=facing}; return #created end}
            gadgetHandler={IsSyncedCode=function() return true end}
            VFS={MAP=7,FileExists=function() return context~=nil end}
            VFS.Include=function(path,env,mode)
              if path=="mosaic/map_config.lua" then assert(mode==VFS.MAP); return context end
              if path=="mosaic/placements.lua" then assert(mode==VFS.MAP); return placements end
              if path=="scripts/mosaic_map_context.lua" then return reader end
              error("unexpected include "..path)
            end
        ''')
        r.globals().reader=r.execute((TEMPLATES/"scripts/mosaic_map_context.lua").read_text())
        return r

    def test_context_dimension_drift_is_rejected(self):
        r=self.runtime()
        self.assertEqual(r.eval('reader.Read().country'),"Germany")
        r.execute('Game.mapSizeX=4096')
        with self.assertRaises(Exception):r.eval('reader.Read()')

    def test_every_hook_overrides_and_client_location_is_ignored(self):
        r=self.runtime()
        r.execute('makeVector=function(x,y,z) return {x=x,y=y,z=z} end')
        patched=transform(compatible_files())
        r.execute(patched["scripts/lib_mosaic.lua"])
        self.assertEqual(r.eval('getCountryByCulture()'),("Germany","Europe"))
        self.assertEqual(r.eval('getInstanceCultureOrDefaultToo()'),"western")
        self.assertEqual(r.eval('getRegionDayColorBy().x'),154)
        altitude,sign=r.eval('getAzimuthByRegion()')
        self.assertAlmostEqual(altitude,55.862)
        self.assertEqual(sign,1)
        r.execute('GG.MapCompletedBuildingPlacement=true')
        self.assertTrue(r.eval('detectMapControlledPlacementComplete()'))
        r.execute(patched["luarules/gadgets/game_snipe_minigame.lua"])
        r.execute('GG.Location="authoritative"; gadget:RecvLuaMsg("LOCATION:|wrong|wrong")')
        self.assertEqual(r.eval('GG.Location'),"authoritative")

    def test_non_generated_map_keeps_legacy_location(self):
        r=self.runtime(False)
        patched=transform(compatible_files())
        r.execute(patched["scripts/lib_mosaic.lua"])
        self.assertEqual(r.eval('getCountryByCulture()'),"legacy")
        r.execute(patched["luarules/gadgets/game_snipe_minigame.lua"])
        r.execute('gadget:RecvLuaMsg("LOCATION:|legacy")')
        self.assertEqual(r.eval('GG.Location'),"client")

    def test_spawn_order_completion_and_reload_no_duplicates(self):
        r=self.runtime()
        plan=[{"id":"objective-0-L","name":"objective_hospital","x":1024,"z":2048,"facing":1,"kind":"objective"},
              {"id":"objective-0-R","name":"objective_hospital","x":7168,"z":2048,"facing":3,"kind":"objective"},
              {"id":"building-0-L","name":"house_western0","x":2048,"z":3072,"facing":0,"kind":"building"}]
        r.globals().placements=r.eval(lua(plan))
        code=(TEMPLATES/"luarules/gadgets/game_mosaic_generated_map.lua").read_text()
        r.execute(code);r.execute('gadget:Initialize(); gadget:GameFrame(1)')
        self.assertEqual(r.eval('#created'),3)
        self.assertEqual(r.eval('created[1].name'),"objective_hospital")
        self.assertTrue(r.eval('GG.MapCompletedBuildingPlacement'))
        self.assertEqual(r.eval('GG.Location.country'),"Germany")
        r.execute('gadget={}')
        r.execute(code);r.execute('gadget:Initialize(); gadget:GameFrame(2)')
        self.assertEqual(r.eval('#created'),3)

    def test_missing_unit_rejected_before_partial_spawn(self):
        r=self.runtime()
        r.globals().placements=r.eval(lua([{"id":"bad","name":"missing","x":1024,"z":1024,"kind":"building","facing":0}]))
        r.execute((TEMPLATES/"luarules/gadgets/game_mosaic_generated_map.lua").read_text())
        with self.assertRaises(Exception):r.execute('gadget:Initialize()')
        self.assertEqual(r.eval('#created'),0)

    def test_all_shipped_lua_parses(self):
        r=self.runtime()
        compile_lua=r.eval('function(s) local f,e=loadstring(s); return f~=nil,e end')
        for path in TEMPLATES.rglob("*.lua"):
            okay,error=compile_lua(path.read_text())
            self.assertTrue(okay,(path,error))

    @unittest.skipUnless(os.getenv("MOSAIC_SOURCE"),"Set MOSAIC_SOURCE to verify a real game checkout")
    def test_real_game_lua_parses_and_installs_on_isolated_copy(self):
        root=Path(os.environ["MOSAIC_SOURCE"])
        files={p:(root/p).read_text() for p in compatible_files()}
        patched=transform(files)
        r=self.runtime()
        compile_lua=r.eval('function(s) local f,e=loadstring(s); return f~=nil,e end')
        for path,value in patched.items():
            okay,error=compile_lua(value)
            self.assertTrue(okay,(path,error))
        r.execute('UnitDefNames.protagonsafehouse={id=1}; UnitDefNames.antagonsafehouse={id=2}; UnitDefs={{buildOptions={}},{buildOptions={}}}; function unitCanBuild() return {} end; function makeVector(x,y,z) return {x=x,y=y,z=z} end')
        r.execute(patched["scripts/lib_mosaic.lua"])
        self.assertEqual(r.eval('GG.GameConfig.game.culture'),"western")
        self.assertEqual(r.eval('getCountryByCulture("arabic",128)'),("Germany","Europe"))
        with tempfile.TemporaryDirectory() as tmp:
            for p,value in files.items():
                dest=Path(tmp)/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(value)
            result=install_adapter(tmp,True)
            self.assertTrue(result["applied"])

if __name__=="__main__":unittest.main()
