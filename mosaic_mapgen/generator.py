"""Offline generation from a pinned geographic snapshot."""
import hashlib
import json
import math
import random
from dataclasses import dataclass
import numpy as np
from PIL import Image, ImageDraw
from .profiles import LANDSCAPES, HOUSE_WEIGHTS, OBJECTIVES
from .geography import projector
from .balance import audit, CELL

# Surface classes: ground, asphalt, vegetation, forest, water, urban footprint.
PALETTE_FIXED = {1:(62,65,68), 4:(43,84,113), 5:(127,120,108)}

@dataclass
class Generated:
    config: object
    source: dict
    metadata: dict
    height: np.ndarray
    surface: np.ndarray
    units: list
    starts: list
    report: dict

def canonical(data):
    return json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()

def polygons(geometry):
    return [geometry["coordinates"]] if geometry["type"]=="Polygon" else geometry["coordinates"] if geometry["type"]=="MultiPolygon" else []

def centre(geometry, project):
    if geometry["type"] == "Point":
        return project(geometry["coordinates"])
    rings = polygons(geometry)
    points = rings[0][0][:-1] if rings else geometry["coordinates"]
    xy = [project(p) for p in points]
    return tuple(sum(p[i] for p in xy)/len(xy) for i in (0,1))

def objective_name(tags):
    for tag in ("amenity", "landuse", "power", "military"):
        value = "military" if tag=="military" and tags.get(tag) else tags.get(tag)
        if value in OBJECTIVES:
            return OBJECTIVES[value]
    return None

def rgb_surface(surface, landscape):
    profile = LANDSCAPES[landscape]
    palette = [profile["ground"],PALETTE_FIXED[1],profile["grass"],profile["forest"],PALETTE_FIXED[4],PALETTE_FIXED[5]]
    return np.array(palette,dtype=np.uint8)[surface]

def generate(config, source):
    source = dict(source)
    source["features"] = sorted(source["features"],key=lambda f:str(f["id"]))
    digest = hashlib.sha256(canonical(source)).hexdigest()
    metadata = config.metadata(digest)
    metadata["source_attribution"] = source["source"]["attribution"]
    metadata["source_license"] = source["source"]["license"]
    rng = random.Random(config.seed)
    size, n = config.size, config.size//8
    half = Image.new("L",(n//2,n),0)
    draw = ImageDraw.Draw(half)
    project = projector(source["bbox"],size,320)
    candidates, objective_candidates = [], []
    def pixel(p):
        x,z = project(p)
        return (x/8,z/8)
    # Deterministic category layering; roads override imported water as bridges.
    layers = {2:[],3:[],4:[],5:[],1:[]}
    for feature in source["features"]:
        tags, geom = feature["properties"],feature["geometry"]
        x,z = centre(geom,project)
        obj = objective_name(tags)
        if obj:
            objective_candidates.append((obj,x,z,str(feature["id"])))
        elif tags.get("building") and tags.get("building") != "no":
            candidates.append((x,z,str(feature["id"])))
        if tags.get("highway") or (tags.get("waterway") and geom["type"]=="LineString"):
            layers[1 if tags.get("highway") else 4].append(feature)
        elif tags.get("natural") in ("water","wetland","bay") or tags.get("water") or tags.get("landuse")=="reservoir":
            layers[4].append(feature)
        elif tags.get("natural")=="wood" or tags.get("landuse")=="forest":
            layers[3].append(feature)
        elif tags.get("landuse") in ("grass","meadow","recreation_ground","farmland") or tags.get("leisure")=="park":
            layers[2].append(feature)
        elif tags.get("building") and tags.get("building")!="no":
            layers[5].append(feature)
    for cls,features in layers.items():
        for f in features:
            geom = f["geometry"]
            for polygon in polygons(geom):
                draw.polygon([pixel(p) for p in polygon[0]],fill=cls)
                for hole in polygon[1:]:
                    draw.polygon([pixel(p) for p in hole],fill=0)
            if geom["type"]=="LineString":
                draw.line([pixel(p) for p in geom["coordinates"]], fill=cls,
                          width=max(1,config.road_width//8) if cls==1 else 6)
    lanes = (size/4,size/2,3*size/4)
    for z in lanes:
        draw.rectangle((0,(z-config.corridor_width/2)/8,n//2,(z+config.corridor_width/2)/8),fill=1)
    left_surface = np.array(half,dtype=np.uint8)
    surface = np.concatenate((left_surface,np.fliplr(left_surface)),axis=1)
    zz,xx = np.mgrid[0:n+1,0:n//2+1]
    phase = config.seed % 360 * math.pi/180
    relief = LANDSCAPES[config.landscape]["relief"]
    left_height = 30+relief*(0.5+0.25*np.sin(xx/71+phase)+0.25*np.cos(zz/83+phase))
    vertex_surface = np.pad(left_surface,((0,1),(0,1)),mode="edge")
    left_height[vertex_surface==4] = -12
    left_height[vertex_surface==1] = 32
    # Reinforce wide, level playable approaches along the three balancing lanes.
    for z in lanes:
        a,b = int((z-config.corridor_width/2)/8),int((z+config.corridor_width/2)/8)+1
        left_height[a:b,:] = 32
    units = []
    left_units = []
    startx = (int(size*0.1/CELL)+0.5)*CELL
    startz = size/2+CELL/2
    starts = [(startx,startz),(size-startx,startz)]
    def snap(value):
        return (int(value/CELL)+0.5)*CELL
    def acceptable(x,z,radius):
        if not (radius+config.clearance+64<x<size/2-radius-config.clearance-64 and radius+config.clearance+64<z<size-radius-config.clearance-64):
            return False
        if any(abs(z-lane) < radius+config.clearance+config.corridor_width/2+CELL for lane in lanes):
            return False
        if math.hypot(x-startx,z-startz) < radius+384:
            return False
        if any(abs(x-u["x"])<radius+u["radius"]+config.clearance and abs(z-u["z"])<radius+u["radius"]+config.clearance for u in left_units):
            return False
        a,b,c,d = int((z-radius)/8),int((z+radius)/8)+1,int((x-radius)/8),int((x+radius)/8)+1
        return bool((left_height[a:b,c:d]>5).all())
    def place(name,x,z,radius,kind,pair,source_id):
        # Mirror facing about X: north/south stay fixed, east/west exchange.
        facing = rng.randrange(4)
        left = {"id":f"{kind}-{pair}-L","pair":pair,"name":name,"x":x,"z":z,"radius":radius,"kind":kind,"facing":facing,"source_id":source_id}
        right = dict(left,id=f"{kind}-{pair}-R",x=size-x,facing=(-facing)%4)
        units.extend((left,right)); left_units.append(left)
        reach = radius+config.clearance+CELL
        a,b,c,d = int((z-reach)/8),int((z+reach)/8)+1,int((x-reach)/8),int((x+reach)/8)+1
        left_height[a:b,c:d] = 32
    used = set()
    fallbacks = ["objective_market","objective_hospital","objective_industrialcomplex","objective_university","objective_powerplant","objective_combatoutpost"]
    for pair in range(config.objective_pairs):
        preferred = [c for c in objective_candidates if c[3] not in used]
        chosen = None
        for name,x,z,identifier in preferred:
            x,z = snap(x),snap(z)
            if acceptable(x,z,256):
                chosen=(name,x,z,identifier);break
        if chosen is None:
            for _ in range(3000):
                x,z = snap(rng.uniform(400,size/2-400)),snap(rng.uniform(400,size-400))
                if acceptable(x,z,256):
                    chosen=(fallbacks[pair],x,z,"procedural/objective");break
        if chosen is None:
            raise ValueError("Not enough dry, clear terrain for objective pairs; enlarge map or reduce objectives")
        name,x,z,identifier = chosen
        used.add(identifier)
        place(name,x,z,256,"objective",pair,identifier)
    weights = HOUSE_WEIGHTS[config.culture]
    def house_name():
        die = rng.randrange(100)
        for name,weight in weights:
            if die<weight:
                return name
            die-=weight
        raise AssertionError("Invalid cultural profile weights")
    # Imported lots first; thin dense city footprints to the game's model size.
    rng.shuffle(candidates)
    extra = [(rng.uniform(300,size/2-300),rng.uniform(300,size-300),"procedural/infill") for _ in range(5000)]
    house_pair = 0
    for x,z,identifier in candidates+extra:
        if house_pair*2>=config.max_buildings:
            break
        x,z = snap(x),snap(z)
        if acceptable(x,z,160):
            place(house_name(),x,z,160,"building",house_pair,identifier)
            house_pair+=1
    height = np.concatenate((left_height,np.fliplr(left_height[:,:-1])),axis=1).astype(np.float32)
    report = audit(height,surface,units,starts,config)
    metadata["generation_digest"] = hashlib.sha256(canonical({"config":config.to_dict(),"source":digest})).hexdigest()
    return Generated(config,source,metadata,height,surface,units,starts,report)

def preview(generated, path):
    size = generated.config.size
    image = Image.fromarray(rgb_surface(generated.surface,generated.config.landscape)).resize((1024,1024),Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(image)
    scale = 1024/size
    for u in generated.units:
        x,z,r = u["x"]*scale,u["z"]*scale,u["radius"]*scale
        color = "#f1b943" if u["kind"]=="objective" else "#d7d1c5"
        draw.rectangle((x-r,z-r,x+r,z+r),fill=color,outline="#232930",width=1)
        if u["kind"]=="objective":
            draw.text((x-r,z),str(u["pair"]+1),fill="black")
    for i,(x,z) in enumerate(generated.starts):
        x,z = x*scale,z*scale
        draw.ellipse((x-10,z-10,x+10,z+10),fill="#58cbf5" if i==0 else "#ef645e",outline="white",width=2)
    draw.line((512,0,512,1024),fill="#edf2f2",width=1)
    draw.rectangle((0,0,1024,46),fill="#14202a")
    draw.text((12,8),f'{generated.config.city} | {generated.config.country} | {generated.config.landscape} | mirrored city',fill="white")
    draw.text((12,26),f'{generated.report["building_count"]} buildings | {generated.report["objective_count"]} objectives | three cross-city corridors',fill="#f1b943")
    draw.rectangle((0,1002,1024,1024),fill="#14202a")
    draw.text((12,1008),generated.source["source"]["attribution"]+" | "+generated.source["source"]["license"],fill="white")
    image.save(path)
