"""Native Spring SMF/SMT writer. No external map compiler is required."""
import hashlib
import json
import struct
import zipfile
from pathlib import Path
import numpy as np
from PIL import Image
from .generator import rgb_surface, preview

SMF = struct.Struct("<16s7i2f7i")
SMT = struct.Struct("<16s4i")
MINIMAP_BYTES = 699048

def lua(value):
    if value is None:
        return "nil"
    if isinstance(value,bool):
        return "true" if value else "false"
    if isinstance(value,(int,float)):
        return str(value)
    if isinstance(value,str):
        # Lua 5.1 supports decimal byte escapes, not JSON Unicode escapes.
        return '"'+''.join(f"\\{b:03d}" if b<32 or b in (34,92) or b>=127 else chr(b) for b in value.encode("utf-8"))+'"'
    if isinstance(value,dict):
        return "{\n"+",\n".join(f"[{lua(k)}]={lua(v)}" for k,v in sorted(value.items()))+"\n}"
    if isinstance(value,(list,tuple)):
        return "{"+",".join(map(lua,value))+"}"
    raise TypeError(type(value))

def dxt1(rgb):
    """Deterministic bounding-box BC1 encoder for flat procedural terrain colours."""
    h,w,_ = rgb.shape
    if h%4 or w%4:
        raise ValueError("DXT1 dimensions must be divisible by four")
    blocks = rgb.reshape(h//4,4,w//4,4,3).transpose(0,2,1,3,4).reshape(-1,16,3).astype(np.int32)
    lo,hi = blocks.min(axis=1),blocks.max(axis=1)
    def pack565(c):
        return ((c[:,0]>>3)<<11)|((c[:,1]>>2)<<5)|(c[:,2]>>3)
    c0,c1 = pack565(hi),pack565(lo)
    def unpack565(c):
        return np.stack(((c>>11)*255//31,((c>>5)&63)*255//63,(c&31)*255//31),axis=1)
    a,b = unpack565(c0),unpack565(c1)
    palette = np.stack((a,b,(2*a+b)//3,(a+2*b)//3),axis=1)
    error = ((blocks[:,:,None,:]-palette[:,None,:,:])**2).sum(axis=3)
    # Equal endpoints use three-colour mode; code 3 is transparent, never use it.
    error[c0==c1,:,2:] = 10**9
    index = error.argmin(axis=2).astype(np.uint32)
    bits = (index << (2*np.arange(16,dtype=np.uint32))).sum(axis=1,dtype=np.uint32)
    dtype = np.dtype([("a","<u2"),("b","<u2"),("bits","<u4")])
    out = np.empty(len(blocks),dtype=dtype)
    out["a"],out["b"],out["bits"] = c0,c1,bits
    return out.tobytes()

def write_terrain(generated, directory):
    directory = Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    surface = generated.surface
    n = surface.shape[0]
    cells = surface.reshape(n//4,4,n//4,4).transpose(0,2,1,3).reshape(-1,16)
    unique,inverse = np.unique(cells,axis=0,return_inverse=True)
    tiles = bytearray()
    for tile in unique:
        rgb = rgb_surface(tile.reshape(4,4),generated.config.landscape)
        image = Image.fromarray(rgb).resize((32,32),Image.Resampling.NEAREST)
        for size in (32,16,8,4):
            tiles.extend(dxt1(np.array(image.resize((size,size),Image.Resampling.BOX))))
    assert len(tiles)==len(unique)*680
    (directory/"city.smt").write_bytes(SMT.pack(b"spring tilefile\0",1,len(unique),32,1)+tiles)
    minimap = Image.fromarray(rgb_surface(surface,generated.config.landscape)).resize((1024,1024),Image.Resampling.BOX)
    mini = b"".join(dxt1(np.array(minimap.resize((size,size),Image.Resampling.BOX))) for size in (1024,512,256,128,64,32,16,8,4))
    assert len(mini)==MINIMAP_BYTES
    chunks = [np.rint((generated.height+32)/288*65535).clip(0,65535).astype("<u2").tobytes(),
              bytes(n*n//4), struct.pack("<3i",1,len(unique),len(unique))+b"city.smt\0"+inverse.astype("<i4").tobytes(),
              mini, bytes(n*n//4), struct.pack("<2i",0,0)]
    offsets = []
    position = SMF.size
    for chunk in chunks:
        offsets.append(position);position+=len(chunk)
    mapid = int(generated.metadata["generation_digest"][:8],16) & 0x7fffffff
    header = SMF.pack(b"spring map file\0",1,mapid,n,n,8,8,32,-32,256,*offsets,0)
    (directory/"city.smf").write_bytes(header+b"".join(chunks))

def export(generated, destination):
    if not generated.report["passed"]:
        raise ValueError("Balance validation failed: "+"; ".join(generated.report["failures"]))
    output = Path(destination)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output directory must be empty; refusing to overwrite a previous build")
    output.mkdir(parents=True,exist_ok=True)
    package = output/"map"
    (package/"mosaic").mkdir(parents=True)
    write_terrain(generated,package/"maps")
    mode = "mirrored" if generated.metadata["balance"] == "mirror-x" else "original city"
    name = f'MOSAIC {generated.config.city} {mode} {generated.metadata["generation_digest"][:8]}'
    info = {"name":name,"shortname":"MOSAIC City","version":"0.2.0", "description":f'{generated.config.country}; {generated.config.landscape}; {mode} competitive city',
            "author":"MOSAIC map generator","mapfile":"maps/city.smf","modtype":3,
            "smf":{"minheight":-32,"maxheight":256},"atmosphere":{"fogcolor":[0.68,0.72,0.76],"fogstart":0.6,"fogend":1.0},
            "lighting":{"groundambientcolor":[0.5,0.5,0.5],"grounddiffusecolor":[0.8,0.8,0.8],"unitambientcolor":[0.5,0.5,0.5],"unitdiffusecolor":[0.8,0.8,0.8]},
            "teams":{str(i):{"startpos":{"x":p[0],"z":p[1]}} for i,p in enumerate(generated.starts)},
            "custom":{"mosaic_generated":True,"country":generated.config.country,"culture":generated.config.culture,"landscape":generated.config.landscape}}
    # Numeric team keys in Lua are zero-based engine team indexes.
    info["teams"] = {i:{"startpos":{"x":p[0],"z":p[1]}} for i,p in enumerate(generated.starts)}
    (package/"mapinfo.lua").write_text("return "+lua(info)+"\n",encoding="utf-8")
    (package/"mosaic"/"map_config.lua").write_text("return "+lua(generated.metadata)+"\n",encoding="utf-8")
    (package/"mosaic"/"placements.lua").write_text("return "+lua(generated.units)+"\n",encoding="utf-8")
    (package/"SOURCE-LICENSE.json").write_text(json.dumps(generated.source["source"],indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    preview(generated,output/"preview.png")
    (output/"balance.json").write_text(json.dumps(generated.report,indent=2)+"\n",encoding="utf-8")
    (output/"resolved-config.json").write_text(json.dumps(generated.config.to_dict(),indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    archive = output/"MOSAIC_city.sdz"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED,compresslevel=9) as zf:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                entry = zipfile.ZipInfo(path.relative_to(package).as_posix(),(1980,1,1,0,0,0))
                entry.compress_type=zipfile.ZIP_DEFLATED
                entry.external_attr=0o100644<<16
                zf.writestr(entry,path.read_bytes(),compresslevel=9)
    manifest = {"schema":1,"generation":generated.metadata,"source":generated.source["source"],"files":{}}
    for path in sorted(output.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(output).as_posix()] = {"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"bytes":path.stat().st_size}
    (output/"manifest.json").write_text(json.dumps(manifest,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    return archive
