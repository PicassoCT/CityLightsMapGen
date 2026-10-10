import copy
import hashlib
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image
from mosaic_mapgen.export import lua, write_terrain, SMF, SMT, MINIMAP_BYTES
from mosaic_mapgen.geography import load_city
from mosaic_mapgen.profiles import Config
from mosaic_mapgen.runtime_package import RUNTIME, lua_runtime, build_original, package_map
from test_integration import compatible_files

ROOT = Path(__file__).resolve().parents[1]

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.r, self.include = lua_runtime()

    def table(self, value):
        return self.r.eval(lua(value).encode())

    def test_all_runtime_sources_parse_in_lua51(self):
        parser = self.r.eval(b'function(s) local f,e=loadstring(s); assert(f,e);return true end')
        for path in RUNTIME.glob('*.lua'):
            with self.subTest(path=path.name): self.assertTrue(parser(path.read_bytes()))

    def test_json_is_data_only_and_strict(self):
        decode = self.include(b'citylights/json.lua')[b'decode']
        data = decode(b' { "a": [null, false, 1.5e2], "name": "\\uD83C\\uDF0D" } ')
        self.assertEqual(data[b'name'], '🌍'.encode())
        self.assertEqual(data[b'a'][3], 150)
        for bad in [b'{"a":1,"a":2}', b'1.e2', b'01', b'1e999', b'{"a":os.execute("x")}', b'"\\uD800"', b'[1,]']:
            with self.subTest(bad=bad), self.assertRaises(Exception): decode(bad)

    def test_local_startscript_preserves_credentials_and_host_roles(self):
        tdf = self.include(b'citylights/startscript.lua')
        client = b'[GAME]{IsHost=0;HostIP=192.0.2.1;HostPort=8452;MyPlayerName=Alice;MyPasswd=a//b/*c*/d;MapHash=123;}'
        starts = self.table([[700, 800], [7400, 7300]])
        result = tdf[b'parse'](tdf[b'forMap'](client, b'MOSAIC sector abc', starts))
        for key, val in [(b'mypasswd', b'a//b/*c*/d'), (b'hostip', b'192.0.2.1'), (b'hostport', b'8452'), (b'ishost', b'0')]: self.assertEqual(result[key], val)
        self.assertIsNone(result[b'maphash'])
        host = b'[GAME]{/* comment */IsHost=1;MyPlayerName=Bob;[TEAM0]{AllyTeam=2;}[TEAM1]{AllyTeam=7;}}'
        result = tdf[b'parse'](tdf[b'forMap'](host,b'MOSAIC sector abc',starts))
        self.assertEqual(result[b'team0'][b'startposx'],b'700')
        self.assertEqual(result[b'team1'][b'startposz'],b'7300')
        self.assertEqual(result[b'startpostype'],b'0')
        with self.assertRaises(Exception): tdf[b'forMap'](b'[GAME]{IsHost=1;MyPlayerName=X;[TEAM0]{AllyTeam=0;}}',b'test',starts)

    def room(self):
        events=[]
        emit=lambda verb,body: events.append((verb,body))
        room=self.include(b'citylights/coordinator.lua')[b'new'](self.table({0:True,1:True}),0,emit)
        def receive(msg,player=0): return room[b'receive'](room,msg,player)
        receive(b'CLG1:HELLO:ready');receive(b'CLG1:HELLO:ready',1)
        return room,receive,events

    def snapshot(self,receive):
        raw=b'{"elements":[]}';digest=hashlib.sha512(raw).hexdigest().encode()
        receive(b'CLG1:BEGIN:'+digest+b'|1|'+str(len(raw)).encode()+b'|{}')
        receive(b'CLG1:CHUNK:1|'+raw.hex().encode())

    def test_protocol_requires_every_client_before_reload(self):
        room,receive,events=self.room();self.snapshot(receive)
        self.assertEqual(room[b'phase'],b'generating')
        digest=b'a'*128
        receive(b'CLG1:READY:'+digest)
        self.assertEqual(room[b'phase'],b'generating')
        receive(b'CLG1:READY:'+digest,1)
        self.assertEqual(room[b'phase'],b'arming')
        receive(b'CLG1:ARMED:'+digest)
        self.assertNotIn(b'commit',[v for v,_ in events])
        receive(b'CLG1:ARMED:'+digest,1)
        self.assertEqual(room[b'phase'],b'committed')

    def test_protocol_rejects_divergence_and_malformed_packets(self):
        room,receive,_=self.room();self.snapshot(receive)
        receive(b'CLG1:READY:'+b'a'*128);receive(b'CLG1:READY:'+b'b'*128,1)
        self.assertEqual(room[b'phase'],b'failed')
        room,receive,_=self.room()
        self.assertFalse(receive(b'CLG1:FAIL:outsider',99))
        receive(b'CLG1:BEGIN:'+b'a'*128+b'|1|2|{}')
        receive(b'CLG1:CHUNK:invalid')
        self.assertEqual(room[b'phase'],b'failed')
        room,receive,_=self.room()
        receive(b'CLG1:BEGIN:'+b'a'*128+b'|1|2|{}');receive(b'CLG1:CHUNK:1|7b7d')
        self.assertEqual(room[b'phase'],b'failed')

    def test_graph_blocked_separation_fails_and_view_does_not_change_starts(self):
        graph=self.include(b'citylights/graph.lua');n=24
        grid={i:18 for i in range(1,n*n+1) if (i-1)%n!=n//2}
        objectives=[{'id':'a','x':200,'z':300,'radius':64}]
        with self.assertRaises(Exception): graph[b'find'](self.table(grid),n,64,self.table(objectives),0.08)
        starts=self.table([[500,1000],[7000,7500]])
        view=self.include(b'citylights/view.lua');angle=view[b'angle'](starts)
        a=view[b'point'](500,1000,8192,angle);b=view[b'point'](7000,7500,8192,angle)
        self.assertAlmostEqual(a[1],b[1],places=8)
        self.assertGreater(b[0],a[0]);self.assertEqual(starts[1][1],500)

    def test_native_lua_export_offsets_tiles_and_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg=Config.load(ROOT/'examples/berlin.json')
            dummy=SimpleNamespace(surface=np.zeros((1024,1024),dtype=np.uint8),height=np.full((1025,1025),32,dtype=np.float32),config=cfg,metadata={'generation_digest':'1'*64})
            write_terrain(dummy,temp)
            template=(Path(temp)/'city.smf').read_bytes()[:80]
            self.r.globals().VFS[b'LoadFile']=lambda path,*_: template if path==b'citylights/template.smf' else b'-- adapter'
            previous=self.r.globals().VFS[b'Include']
            self.r.globals().VFS[b'Include']=lambda path,*_: self.table([]) if path==b'citylights/adapter_files.lua' else previous(path)
            plan=self.table({'size':8192,'cell':64,'n':128,'classes':[0]*(128*128),'context':{'landscape':'temperate','city':'Test','country':'Test','generation_digest':'a'*128},'starts':[[800,4096],[7392,4096]],'units':[],'roads':{'schema':1,'generation':'map','roads':[]},'report':{'passed':True}})
            export=self.include(b'citylights/export.lua')
            files,folder,name,digest=export[b'files'](plan,b'{}',self.table({}))
            info=self.r.execute(files[b'mapinfo.lua'])
            self.assertEqual(name,info[b'name']+b' '+info[b'version'])
            smf=files[b'maps/city.smf'];h=SMF.unpack_from(smf);n=h[3]
            self.assertEqual(h[0],b'spring map file\0');self.assertEqual(n,1024)
            self.assertEqual(h[11]-h[10],(n+1)**2*2)
            self.assertEqual(h[14]-h[13],MINIMAP_BYTES)
            self.assertEqual(len(smf),h[15]+8)
            smt=files[b'maps/city.smt'];self.assertEqual(SMT.unpack_from(smt),(b'spring tilefile\0',1,6,32,1))
            self.assertEqual(len(smt),32+6*680)
            raw=smt[32:32+512]
            hdr=struct.pack('<7I',124,0x81007,32,32,len(raw),0,0)+bytes(44)
            hdr+=struct.pack('<II4s5I',32,4,b'DXT1',0,0,0,0,0)+struct.pack('<5I',0x1000,0,0,0,0)
            self.assertEqual(Image.open(io.BytesIO(b'DDS '+hdr+raw)).size,(32,32))
            entries=sorted((path,body) for path,body in files.items() if path!=b'mosaic/manifest.lua')
            expected=hashlib.sha512(b''.join(path+b'\0'+hashlib.sha512(body).hexdigest().encode()+b'\n' for path,body in entries)).hexdigest().encode()
            self.assertEqual(digest,expected)

class OriginalCityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=Config.load(ROOT/'examples/berlin.json');cls.city=load_city(ROOT/'examples/berlin-fixture.geojson')
        cls.generated=build_original(cls.config,copy.deepcopy(cls.city))

    def test_source_is_unmirrored_and_opportunities_reachable(self):
        g=self.generated
        self.assertFalse(np.array_equal(g.surface,np.fliplr(g.surface)))
        self.assertEqual(g.metadata['balance'],'opportunity-graph')
        self.assertTrue(g.report['passed']);self.assertLessEqual(g.report['relative_imbalance'],0.08)
        self.assertEqual(len(g.starts),2)
        for row in g.report['objective_access']: self.assertTrue(all(v>=0 for v in row['access']))
        ids=[u['source_id'] for u in g.units if not u['source_id'].startswith('procedural/')]
        self.assertEqual(len(ids),len(set(ids)))

    def test_generation_is_order_independent(self):
        city=copy.deepcopy(self.city);city['features'].reverse()
        other=build_original(self.config,city)
        self.assertEqual(other.metadata,self.generated.metadata)
        self.assertEqual(other.units,self.generated.units);self.assertEqual(other.starts,self.generated.starts)

    def test_package_reproducibility_and_no_game_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'game';files=compatible_files()
            files.update({'luarules/main.lua':"VFS.Include('luarules/gadgets.lua',nil,VFS.ZIP_ONLY)",'luaui/mosaicwidgets.lua':'WIDGET_DIRNAME_MAP = VFS.MAP','LICENSE':'test license'})
            for path,text in files.items(): target=root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
            a=package_map(root,Path(temp)/'a');b=package_map(root,Path(temp)/'b')
            self.assertEqual(Path(a['archive']).read_bytes(),Path(b['archive']).read_bytes())
            with zipfile.ZipFile(a['archive']) as z:
                self.assertIsNone(z.testzip())
                for path in ['luagaia/main.lua','luagaia/draw.lua','luarules/gadgets.lua','luaui/widgets_map/gui_citylights_startup.lua','citylights/adapter/scripts/lib_mosaic.lua','citylights/world.lua']: self.assertIn(path,z.namelist())
                self.assertGreater(len(z.read('citylights/world.lua')),10000)
            for path,text in files.items(): self.assertEqual((root/path).read_text(),text)
            (root/'luarules/main.lua').write_text('-- incompatible')
            with self.assertRaises(ValueError):package_map(root,Path(temp)/'bad')
            self.assertFalse((Path(temp)/'bad').exists())

if __name__=='__main__': unittest.main()
