"""Import snapshots; a Google Maps URL is a viewport selector, never a tile source."""
import json
import math
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


def google_center(url: str) -> tuple[float, float]:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    if not re.fullmatch(r"(?:www\.)?google\.(?:com|de|co\.uk|fr|es|it|co\.jp)", host):
        raise ValueError("Use a full Google Maps URL with @latitude,longitude or a numeric query; shortened links are unsupported")
    match = re.search(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", parsed.path)
    if not match:
        query = urllib.parse.parse_qs(parsed.query)
        match = re.fullmatch(r"(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", (query.get("q") or query.get("query") or [""])[0])
    if not match:
        raise ValueError("Google Maps view must contain numeric coordinates; supply --radius-m explicitly")
    lat, lon = map(float, match.groups())
    if not (-85 <= lat <= 85 and -180 <= lon <= 180):
        raise ValueError("Coordinates outside supported latitude/longitude range")
    return lat, lon


def viewport_bounds(center, radius_m):
    if not 100 <= radius_m <= 10000:
        raise ValueError("radius-m must be 100..10000 metres")
    lat, lon = center
    dy = radius_m / 111320
    dx = dy / math.cos(math.radians(lat))
    bounds = [lon-dx, lat-dy, lon+dx, lat+dy]
    validate_bounds(bounds)
    return bounds


def validate_bounds(bounds):
    if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
        raise ValueError("bbox must contain four finite WGS84 coordinates")
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
        raise ValueError("Invalid bbox; antimeridian crossing is unsupported")


def overpass_to_geojson(data, bounds):
    features = []
    for el in sorted(data.get("elements", []), key=lambda e: (e["type"], e["id"])):
        tags = el.get("tags", {})
        if el["type"] == "node" and tags:
            geometry = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way" and el.get("geometry"):
            coords = [[p["lon"], p["lat"]] for p in el["geometry"]]
            closed = len(coords) >= 4 and coords[0] == coords[-1]
            geometry = {"type": "Polygon" if closed and not tags.get("highway") else "LineString", "coordinates": [coords] if closed and not tags.get("highway") else coords}
        else:
            continue
        features.append({"type": "Feature", "id": f'{el["type"]}/{el["id"]}', "properties": tags, "geometry": geometry})
    return {"type": "FeatureCollection", "bbox": bounds, "features": features,
            "source": {"provider": "OpenStreetMap", "license": "ODbL-1.0", "attribution": "© OpenStreetMap contributors", "url": "https://www.openstreetmap.org/copyright", "limitations": "Way/node import; multipolygon relations are not imported. Review coastlines and missing complex buildings."}}


def fetch_osm(center, radius_m, destination, endpoint="https://overpass-api.de/api/interpreter"):
    """One bounded request saved to disk; builds never contact the network."""
    bounds = viewport_bounds(center, radius_m)
    west, south, east, north = bounds
    box = f"({south},{west},{north},{east})"
    query = '[out:json][timeout:90];(' + ''.join(
        f'{kind}["{tag}"]{box};' for kind, tag in [
            ("way", "highway"), ("way", "building"), ("way", "natural"),
            ("way", "landuse"), ("way", "waterway"), ("way", "amenity"),
            ("node", "amenity"), ("way", "power"), ("way", "military")]) + ');out geom;'
    request = urllib.request.Request(endpoint, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "MOSAIC-map-generator/0.1", "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=110) as response:
        raw = response.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError("Overpass response exceeds 64 MiB; reduce viewport")
    data = json.loads(raw)
    if data.get("remark"):
        raise ValueError(f'Overpass returned incomplete data: {data["remark"]}')
    snapshot = overpass_to_geojson(data, bounds)
    Path(destination).write_text(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2)+"\n", encoding="utf-8")


def load_city(path):
    path = Path(path)
    if path.suffix.lower() == ".osm":
        root = ET.parse(path).getroot()
        nodes = {n.get("id"): [float(n.get("lon")), float(n.get("lat"))] for n in root.findall("node")}
        b = root.find("bounds")
        if b is None:
            raise ValueError("OSM XML requires explicit bounds")
        bounds = [float(b.get(k)) for k in ["minlon", "minlat", "maxlon", "maxlat"]]
        elements = []
        for n in root.findall("node"):
            tags = {t.get("k"): t.get("v") for t in n.findall("tag")}
            if tags:
                elements.append({"type": "node", "id": int(n.get("id")), "lon": float(n.get("lon")), "lat": float(n.get("lat")), "tags": tags})
        for w in root.findall("way"):
            refs = [n.get("ref") for n in w.findall("nd")]
            if not all(r in nodes for r in refs):
                raise ValueError(f'OSM way {w.get("id")} references missing nodes')
            elements.append({"type": "way", "id": int(w.get("id")), "tags": {t.get("k"):t.get("v") for t in w.findall("tag")},
                             "geometry": [{"lon": nodes[r][0], "lat": nodes[r][1]} for r in refs]})
        data = overpass_to_geojson({"elements": elements}, bounds)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") != "FeatureCollection" or not data.get("features"):
        raise ValueError("Input must be a nonempty GeoJSON FeatureCollection or OSM XML snapshot")
    validate_bounds(data.get("bbox", []))
    if not data.get("source", {}).get("attribution") or not data.get("source", {}).get("license"):
        raise ValueError("Input requires source.attribution and source.license")
    ids = []
    for feature in data["features"]:
        if feature.get("id") is None:
            raise ValueError("Each feature needs a stable unique id")
        ids.append(str(feature["id"]))
        geometry = feature.get("geometry") or {}
        kind = geometry.get("type")
        coords = geometry.get("coordinates")
        if kind not in ("Point", "LineString", "Polygon", "MultiPolygon"):
            raise ValueError(f"Unsupported geometry: {kind}")
        def verify(value):
            if not isinstance(value, list) or not value:
                raise ValueError("Empty/invalid coordinates")
            if isinstance(value[0], (float, int)):
                if len(value) < 2 or not all(math.isfinite(v) for v in value[:2]):
                    raise ValueError("Non-finite coordinate")
                if not (-180 <= value[0] <= 180 and -85 <= value[1] <= 85):
                    raise ValueError("Invalid WGS84 coordinate")
            else:
                for part in value:
                    verify(part)
        verify(coords)
        if kind == "LineString" and len(coords) < 2:
            raise ValueError("LineString requires two vertices")
        polygons = [coords] if kind == "Polygon" else coords if kind == "MultiPolygon" else []
        for polygon in polygons:
            for ring in polygon:
                if len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("Polygon rings must be closed with at least four vertices")
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate feature ids")
    data["features"] = sorted(data["features"], key=lambda f: str(f["id"]))
    return data


def projector(bounds, size, margin):
    west, south, east, north = bounds
    cosine = math.cos(math.radians((south+north)/2))
    scale = min((size/2 - 2*margin) / ((east-west)*cosine), (size-2*margin)/(north-south))
    width, height = (east-west)*cosine*scale, (north-south)*scale
    x0, z0 = (size/2-width)/2, (size-height)/2
    def project(point):
        return (x0+(point[0]-west)*cosine*scale, z0+(north-point[1])*scale)
    return project
