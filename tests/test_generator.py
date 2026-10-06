import copy
import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from mosaic_mapgen.geography import google_center,load_city,overpass_to_geojson
from mosaic_mapgen.profiles import Config
from mosaic_mapgen.generator import generate
from mosaic_mapgen.balance import audit
from mosaic_mapgen.export import export,SMF,SMT,MINIMAP_BYTES,dxt1

ROOT = Path(__file__).resolve().parents[1]

class MapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.city=load_city(ROOT/"examples/berlin-fixture.geojson")
        cls.config=Config.load(ROOT/"examples/berlin.json")
        cls.generated=generate(cls.config,cls.city)

    def test_exact_mirror_and_reachable_objectives(self):
        g=self.generated
        self.assertTrue(g.report["passed"],g.report)
        np.testing.assert_array_equal(g.height,np.fliplr(g.height))
        for left,right in zip(g.units[::2],g.units[1::2]):
            self.assertEqual(left["name"],right["name"])
            self.assertEqual(left["x"]+right["x"],g.config.size)
            self.assertEqual(left["z"],right["z"])
            self.assertEqual(right["facing"],(-left["facing"])%4)
        for pair in g.report["objective_access"]:
            self.assertEqual(pair["own_access"][0],pair["own_access"][1])
            self.assertEqual(pair["enemy_access"][0],pair["enemy_access"][1])
            self.assertIsNotNone(pair["own_access"][0])

    def test_feature_order_does_not_change_output(self):
        city=copy.deepcopy(self.city)
        city["features"].reverse()
        other=generate(self.config,city)
        self.assertEqual(self.generated.metadata,other.metadata)
        self.assertEqual(self.generated.units,other.units)
        np.testing.assert_array_equal(self.generated.height,other.height)

    def test_seed_changes_layout_but_never_identity(self):
        config=Config(**dict(self.config.to_dict(),seed=self.config.seed+1))
        other=generate(config,self.city)
        self.assertNotEqual(self.generated.units,other.units)
        self.assertEqual(other.metadata["country"],"Germany")
        self.assertEqual(other.metadata["landscape"],"temperate")
        self.assertTrue(other.report["passed"],other.report)

    def test_audit_rejects_damage_and_overlapping_units(self):
        g=self.generated
        height=g.height.copy();height[0,0]+=1
        units=copy.deepcopy(g.units);units[1]["x"]=units[0]["x"]
        result=audit(height,g.surface,units,g.starts,g.config)
        self.assertFalse(result["passed"])
        self.assertTrue(any("mirrored" in f for f in result["failures"]))
        self.assertTrue(any("Overlapping" in f for f in result["failures"]))

    def test_blocked_corridor_rejected(self):
        g=self.generated
        height=g.height.copy();height[g.config.size//16,:]=-12
        result=audit(height,g.surface,g.units,g.starts,g.config)
        self.assertFalse(result["passed"])
        self.assertTrue(any("corridor" in f for f in result["failures"]))

    def test_export_reproducible_and_binary_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,b=Path(tmp)/"a",Path(tmp)/"b"
            za,zb=export(self.generated,a),export(self.generated,b)
            self.assertEqual(za.read_bytes(),zb.read_bytes())
            smf=(a/"map/maps/city.smf").read_bytes()
            h=SMF.unpack_from(smf)
            self.assertEqual(h[0],b"spring map file\x00")
            self.assertEqual(h[1],1)
            n=h[3]; self.assertEqual(n*8,self.config.size)
            self.assertEqual(h[11]-h[10],(n+1)**2*2)
            self.assertEqual(h[12]-h[11],n*n//4)
            self.assertEqual(h[14]-h[13],MINIMAP_BYTES)
            self.assertEqual(h[15]-h[14],n*n//4)
            self.assertEqual(struct.unpack_from("<2i",smf,h[15]),(0,0))
            files,tiles=struct.unpack_from("<2i",smf,h[12])
            self.assertEqual(files,1)
            self.assertEqual(struct.unpack_from("<i",smf,h[12]+8)[0],tiles)
            filename_end=smf.index(b"\0",h[12]+12)
            indexes=np.frombuffer(smf[filename_end+1:h[13]],dtype="<i4")
            self.assertEqual(len(indexes),n*n//16)
            self.assertTrue((indexes<tiles).all())
            smt=(a/"map/maps/city.smt").read_bytes()
            self.assertEqual(SMT.unpack_from(smt),(b"spring tilefile\0",1,tiles,32,1))
            self.assertEqual(len(smt),32+tiles*680)
            manifest=json.loads((a/"manifest.json").read_text())
            for path,spec in manifest["files"].items():
                self.assertEqual(hashlib.sha256((a/path).read_bytes()).hexdigest(),spec["sha256"])
            with self.assertRaises(ValueError):
                export(self.generated,a)

    def test_bc1_decodes_in_independent_image_reader(self):
        rgb=np.full((32,32,3),(73,128,203),dtype=np.uint8)
        block=dxt1(rgb)
        # Wrap raw BC1 in DDS so Pillow validates the actual compressed pixels.
        header=struct.pack("<7I",124,0x81007,32,32,len(block),0,0)+bytes(44)
        header+=struct.pack("<II4s5I",32,4,b"DXT1",0,0,0,0,0)+struct.pack("<5I",0x1000,0,0,0,0)
        import io
        decoded=np.array(Image.open(io.BytesIO(b"DDS "+header+block)).convert("RGB"))
        self.assertLess(np.abs(decoded.astype(int)-rgb).max(),9)

    def test_google_url_selector(self):
        self.assertEqual(google_center("https://www.google.com/maps/@52.52,13.405,15z"),(52.52,13.405))
        self.assertEqual(google_center("https://www.google.de/maps?q=52.52,13.405"),(52.52,13.405))
        for invalid in ("https://evil.com/maps/@52,13","https://maps.app.goo.gl/example","https://www.google.com/maps?q=Berlin"):
            with self.assertRaises(ValueError):google_center(invalid)

    def test_country_and_climate_are_independent(self):
        desert=Config(city="Dubai",country_code="AE",landscape="arid",latitude=25.2)
        self.assertEqual(desert.metadata("x")["country"],"United Arab Emirates")
        self.assertEqual(desert.culture,"arabic")
        self.assertFalse(desert.metadata("x")["rainy"])
        south=Config(city="Cape Town",country_code="ZA",landscape="mediterranean",latitude=-33.9)
        self.assertEqual(south.metadata("x")["equatorial_sign"],-1)
        custom=Config(city="Kathmandu",country_code="NP",country="Nepal",region="CentralAsia",culture="asian",landscape="alpine",latitude=27.7)
        self.assertEqual(custom.country,"Nepal")
        with self.assertRaises(ValueError):Config(city="Unknown",country_code="XX",landscape="temperate",latitude=0)

    def test_snapshot_missing_ids_or_attribution_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"bad.json"
            city=copy.deepcopy(self.city);del city["features"][0]["id"]
            path.write_text(json.dumps(city))
            with self.assertRaises(ValueError):load_city(path)
            city=copy.deepcopy(self.city);city["source"]={}
            path.write_text(json.dumps(city))
            with self.assertRaises(ValueError):load_city(path)

    def test_osm_nodes_and_closed_ways(self):
        data={"elements":[{"id":1,"type":"node","lat":52,"lon":13,"tags":{"amenity":"hospital"}},
            {"id":2,"type":"way","tags":{"building":"yes"},"geometry":[{"lon":13,"lat":52},{"lon":13.01,"lat":52},{"lon":13.01,"lat":52.01},{"lon":13,"lat":52}]}]}
        converted=overpass_to_geojson(data,[13,52,13.1,52.1])
        self.assertEqual([f["geometry"]["type"] for f in converted["features"]],["Point","Polygon"])

if __name__=="__main__":unittest.main()
