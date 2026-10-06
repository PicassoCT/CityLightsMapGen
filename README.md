# MOSAIC map generator

Generate a mirrored, playable Spring/Recoil map from a real city's geographic
snapshot. Buildings and objectives use MOSAIC's existing UnitDefs. Country,
city, architectural culture, landscape, rain eligibility and sun colour come
from explicit map metadata shared by simulation and UI.

## Quick start

Python 3.11 or newer is required. From the repository checkout:

```sh
python -m pip install -e '.[test]'
python -m unittest discover -s tests -v
python -m mosaic_mapgen build --city examples/berlin-fixture.geojson --config examples/berlin.json --out build/demo
```

The included Berlin district is an **invented CC0 test fixture**, not a
reconstruction of Berlin. The offline example needs no API key or downloads.

Outputs:

- `MOSAIC_city.sdz`: map archive, with SMF terrain and SMT texture tiles.
- `map/`: unpacked map archive for inspection.
- `preview.png`: terrain, placement bounds, objectives and starting positions.
- `balance.json`: clearance and objective travel-distance audit.
- `manifest.json`: source attribution, seed, resolved identity, digests and file checksums.
- `resolved-config.json`: exact generation settings.

## Select a city with Google Maps

Use a full Google Maps city-view URL as a **location selector**:

```sh
python -m mosaic_mapgen fetch --google-view 'https://www.google.com/maps/@52.52,13.405,15z' --radius-m 1800 --out berlin.geojson
python -m mosaic_mapgen build --city berlin.geojson --config examples/berlin.json --out build/berlin
```

Edit the configuration to describe the actual city. `latitude`, `country_code`
and `landscape` are explicit; an architectural culture cannot reliably identify
a country or a climate. The snapshot's bounding box controls the viewport;
zoom, bearing and tilted Google imagery are not used. Shortened links and
text-only searches are rejected with an actionable error.

Google tiles, screenshots, satellite pixels and elevation data are not imported.
The Google Maps Platform and EEA terms restrict creating content from Google
Maps content. Geography is fetched independently from OpenStreetMap using one
bounded Overpass request, or supplied as licensed GeoJSON/OSM XML. See
[Google terms](https://cloud.google.com/maps-platform/terms),
[EEA terms](https://cloud.google.com/terms/maps-platform/eea) and
[OSM attribution and license](https://www.openstreetmap.org/copyright).

Keep the snapshot: map builds run offline and never silently refetch changed
geography. OSM import supports tagged nodes and ways. Multipolygon relations,
administrative boundary resolution and coastlines extending outside the view
need preprocessing/review; the importer does not claim these are complete.

## Mirrored competitive balance

The source city is projected uniformly into the left half of the map with an
aspect-preserving border. The right half reflects it across the X axis. Terrain
heights, water, vegetation, roads, unit names, positions, facing and objective
pairs reflect together. Starts are a mirrored pair. Three wide, level streets
are inserted across the full map, including causeways where they cross water.

Tagged civic/industrial sites are preferred for objectives. Dense geographic
building lots are thinned to fit the game's model sizes. Deterministic infill
adds housing where the source has too few suitable lots. Buildings and
objectives receive level pads. Imported roads crossing water become bridges.
These are deliberate gameplay edits to the source geography.

The build fails unless all of these pass:

- Identical mirrored heightfields, surface classifications and clearance grids.
- Connected starts, and reachable objectives from both starts.
- Equal own-side and opposite-side travel distances for corresponding objective pairs.
- Three unobstructed cross-city routes.
- No intersecting declared building bounds, no out-of-bounds placements, and enough housing.

Navigation uses a conservative 32-unit four-neighbour grid with water, slope,
building radius and configured clearance checks. It is a static layout audit;
it cannot establish faction win-rate balance or replace Recoil pathfinding
and model-collision testing. The stock conservative radii are 160 for housing
and 256 for objectives. Oversized custom assets need larger radii and validation.
Heightfields use deterministic procedural relief appropriate to the selected
landscape, with imported water; they are **not geographic DEM elevation**.

## Country, architecture and landscape

Configuration example:

```json
{
  "city": "Dubai",
  "country_code": "AE",
  "province": "Dubai",
  "district": "City sector",
  "latitude": 25.2,
  "culture": "international",
  "landscape": "arid",
  "seed": 123,
  "size": 8192,
  "max_buildings": 120,
  "objective_pairs": 3
}
```

Country profiles provide names and default architecture for 36 ISO codes.
Unlisted countries require explicit `country`, `region` and `culture` fields;
they never fall back to a randomly selected country. `culture` can be `western`,
`arabic`, `asian` or `international`; it selects supported MOSAIC house families.
International cities mix the three families. Objectives map source functions
(hospital, university, market, prison, industry, power and military sites) to
existing game units. Objective meshes are the assets available in MOSAIC, which
are not a comprehensive set of country-specific architectural models.

Landscape profiles: `temperate`, `arid`, `tropical`, `alpine`, `mediterranean`.
They control terrain palette, relief, rain eligibility and regional daylight.
Hemisphere and latitude determine the sun arc. Region metadata identifies the
source country; renaming the map or changing the generation seed cannot change
that identity. The map uses water level zero, with water beds below zero.

## Install the MOSAIC game adapter

Generated maps need the accompanying **game integration** once. Metadata alone
does not override MOSAIC's existing hash-based guesses. The installer checks all
expected functions before writing, preserves original files in a local backup,
and rejects incompatible revisions and repeated installation.

Preview first, then apply to a dedicated MOSAIC checkout:

```sh
python -m mosaic_mapgen install-game-adapter --game-dir ../MOSAIC
python -m mosaic_mapgen install-game-adapter --game-dir ../MOSAIC --apply
```

The adapter:

- Reads `mosaic/map_config.lua` explicitly from the map archive in each Lua VM.
- Overrides culture before `getGameConfig()` initializes.
- Overrides country, region, rain eligibility, sun arc and daylight helpers.
- Enables MOSAIC's existing manual placement and objective lifecycle.
- Creates the checked placement list on frame one, in stable pair order.
- Registers houses in `GG.BuildingTable` and leaves objective income, security
  and restoration to the existing objective gadget.
- Publishes completion only after the whole placement succeeds; reloads do not
  recreate the initial map's objectives.
- Displays the authoritative country/city/landscape and suppresses the legacy
  city-name widget for generated maps.
- Ignores client `LOCATION:` messages for generated maps.

Metadata travels as archive bytes, with a few game-rule parameters at initialization.
There are no per-frame metadata messages, random country picks or client-driven
identity decisions. Nongenerated maps retain the legacy paths.

Copy the generated SDZ into the engine data directory's `maps/` folder. Select
the map in Skylobby with the patched MOSAIC game. Use fixed starts or the
mirrored starts shipped in `mapinfo.lua`; custom lobby start boxes can invalidate
the audited starting-position balance. This first version supports two sides,
not arbitrary multi-team start-zone layouts.

## Verification and release boundary

The native exporter follows the engine's
[SMF/SMT format](https://github.com/spring/spring/blob/develop/rts/Map/SMF/SMFFormat.h).
It encodes BC1 tiles, four tile mip levels and all nine minimap levels, and writes
stable map IDs and ZIP timestamps. Tests cover binary offsets, independent BC1
decoding, archive reproducibility, feature-order independence, broken layouts,
country/weather hooks, missing units, reload behaviour and installer guards.
Lua adapter tests execute under Lua 5.1 via the test extra.

To additionally check an actual game checkout:

```sh
MOSAIC_SOURCE=../MOSAIC python -m unittest discover -s tests -v
```

GitHub Actions runs Python and Lua tests on Windows and Linux, then uploads the
synthetic example artifacts. It does not publish a release or change MOSAIC.
An engine smoke test is still required: load terrain, inspect all units, move
both sides through corridors, test objective capture/destruction/restoration,
verify daylight/rain/location, and measure the 25-FPS zoomed-out target on
representative hardware. The offline audit makes no FPS or engine-runtime claim.
