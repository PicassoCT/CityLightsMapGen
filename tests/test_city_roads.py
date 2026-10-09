import copy
import math
import os
import tempfile
import unittest
from pathlib import Path

from mosaic_mapgen.export import export, lua
from mosaic_mapgen.geography import load_city
from mosaic_mapgen.profiles import Config
from mosaic_mapgen.runtime_package import ADAPTER, RUNTIME, build_original, lua_runtime

ROOT = Path(__file__).resolve().parents[1]


class CityRoadTests(unittest.TestCase):
    def test_shared_module_copies_are_identical(self):
        runtime = (RUNTIME / 'city_roads.lua').read_bytes()
        self.assertEqual(runtime, (ADAPTER / 'scripts/lib_city_roads.lua').read_bytes())
        if os.environ.get('MOSAIC_SOURCE'):
            game = Path(os.environ['MOSAIC_SOURCE'])
            self.assertEqual(runtime, (game / 'scripts/lib_city_roads.lua').read_bytes())
            self.assertEqual((ADAPTER / 'luarules/gadgets/game_city_roads.lua').read_bytes(),
                             (game / 'luarules/gadgets/game_city_roads.lua').read_bytes())
            self.assertEqual((ADAPTER / 'luaui/widgets_map/gui_city_roads.lua').read_text(),
                             'local CITY_ROADS_MAP_WIDGET=true\n' + (game / 'luaui/widgets_mosaic/gui_city_roads.lua').read_text())

    def test_reversed_geometry_and_imported_numbers(self):
        runtime, include = lua_runtime()
        runtime.execute(b'math.random=function() error("address RNG") end')
        roads = include(b'citylights/city_roads.lua')
        network = {'schema': 1, 'generation': 'map', 'roads': [
            {'id': 'a', 'name': 'Café Straße', 'points': [[0, 0], [500, 0]]},
            {'id': 'b', 'name': 'Café Straße', 'points': [[1000, 0], [500, 0]]},
            {'id': 'c', 'name': 'Café Straße', 'points': [[0, 1000], [500, 1000]]}]}
        plots = [{'x': 100, 'z': 100, 'house_number': '1', 'street_name': 'Café Straße'},
                 {'x': 200, 'z': 100}, {'x': 300, 'z': -100}]
        convert = lambda value: runtime.eval(lua(value).encode())
        canonical = roads[b'normalize'](convert(network))
        first = roads[b'assign'](canonical, convert(plots))
        network['roads'].reverse()
        for road in network['roads']:
            road['points'].reverse()
        second = roads[b'assign'](roads[b'normalize'](convert(network)), convert(list(reversed(plots))))
        self.assertEqual(first[b'200:100'][b'house_number'], b'3')
        self.assertEqual(first[b'300:-100'][b'house_number'], b'2')
        self.assertEqual(first[b'100:100'][b'street_id'], first[b'200:100'][b'street_id'])
        self.assertEqual(roads[b'encode'](canonical), roads[b'encode'](roads[b'normalize'](convert(network))))
        for key, address in first.items():
            self.assertEqual(dict(address.items()), dict(second[key].items()))

    def test_osm_addresses_and_roads_reach_offline_map_files(self):
        source = load_city(ROOT / 'examples/berlin-fixture.geojson')
        config = Config.load(ROOT / 'examples/berlin.json')
        west, south, east, north = source['bbox']
        cosine = math.cos((south + north) * math.pi / 360)
        scale = min(7552 / ((east-west)*cosine), 7552/(north-south))
        x0 = (8192-(east-west)*cosine*scale)/2
        z0 = (8192-(north-south)*scale)/2
        # A known dry plot from this fixture, expressed as geographic source.
        lon = west+(880-x0)/(cosine*scale)
        lat = north-(1072-z0)/scale
        source['features'].append({'type': 'Feature', 'id': 'addressed-house',
            'properties': {'building': 'house', 'addr:street': 'Café Straße', 'addr:housenumber': '17B'},
            'geometry': {'type': 'Point', 'coordinates': [lon, lat]}})
        for feature in source['features']:
            if feature['properties'].get('highway'):
                feature['properties']['name'] = 'Café Straße'
                break
        generated = build_original(config, source)
        house = next(u for u in generated.units if u['source_id'] == 'addressed-house')
        self.assertEqual(house['address']['street_name'], 'Café Straße')
        self.assertEqual(house['address']['house_number'], '17B')
        self.assertEqual(house['address']['number_source'], 'osm')
        self.assertTrue(any(r['name'] == 'Café Straße' for r in generated.roads['roads']))
        for road in generated.roads['roads']:
            for x, z in road['points']:
                self.assertTrue(0 <= x <= 8192 and 0 <= z <= 8192)
        reordered = copy.deepcopy(source)
        reordered['features'].reverse()
        other = build_original(config, reordered)
        self.assertEqual(generated.units, other.units)
        self.assertEqual(generated.roads, other.roads)
        self.assertEqual(generated.metadata['generation_digest'], other.metadata['generation_digest'])
        with tempfile.TemporaryDirectory() as directory:
            export(generated, directory)
            runtime, _ = lua_runtime()
            road_file = Path(directory) / 'map/mosaic/roads.lua'
            network = runtime.execute(road_file.read_bytes())
            self.assertEqual(network[b'generation'], b'map')
            self.assertEqual(len(network[b'roads']), len(generated.roads['roads']))
            placements = runtime.execute((Path(directory) / 'map/mosaic/placements.lua').read_bytes())
            imported = next(u for _, u in placements.items() if u[b'source_id'] == b'addressed-house')
            self.assertEqual(imported[b'address'][b'house_number'], b'17B')


if __name__ == '__main__':
    unittest.main()
