local util=VFS.Include('citylights/util.lua',nil,VFS.MAP)
local core=VFS.Include('citylights/generator.lua',nil,VFS.MAP)
local profiles=VFS.Include('citylights/profiles.lua',nil,VFS.MAP)
local M={}
local function pack(v,bytes)
  local out={};for i=1,bytes do out[i]=string.char(v%256);v=math.floor(v/256) end
  return table.concat(out)
end
M.pack=pack
local function solid(rgb)
  local c=math.floor(rgb[1]/8)*2048+math.floor(rgb[2]/4)*32+math.floor(rgb[3]/8)
  return pack(c,2)..pack(c,2)..string.rep('\0',4)
end
local function read(path) return assert(VFS.LoadFile(path,VFS.MAP),'Missing packaged file '..path) end
local function minimap(plan,palette,checkpoint)
  local blocks={};for i,c in ipairs(palette) do blocks[i-1]=solid(c) end
  local out={};local size=1024
  while size>=4 do
    for z=0,size/4-1 do
      local row={}
      for x=0,size/4-1 do
        local cx=math.min(plan.n-1,math.floor((x*4+2)*plan.n/size))
        local cz=math.min(plan.n-1,math.floor((z*4+2)*plan.n/size))
        row[#row+1]=blocks[plan.classes[cz*plan.n+cx+1]]
      end
      out[#out+1]=table.concat(row)
    end
    size=size/2
    if checkpoint then checkpoint('minimap') end
  end
  return table.concat(out)
end
function M.files(plan,snapshot,options,checkpoint)
  local files={};local env=profiles.landscapes[plan.context.landscape]
  local palette={env.ground,{92,94,92},env.grass,env.forest,{37,67,82},{141,127,110}}
  local n=plan.size/8;local height={}
  for z=0,n do
    local row={}
    for x=0,n do row[#row+1]=pack(math.floor((core.height(plan,x*8,z*8)+32)/288*65535+0.5),2) end
    height[#height+1]=table.concat(row)
    if checkpoint and z%32==0 then checkpoint('terrain '..z..'/'..n) end
  end
  local tileIndex={}
  for z=0,n/4-1 do local row={};for x=0,n/4-1 do
    local cx=math.min(plan.n-1,math.floor(x*32/plan.cell));local cz=math.min(plan.n-1,math.floor(z*32/plan.cell))
    row[#row+1]=pack(plan.classes[cz*plan.n+cx+1],4)
  end;tileIndex[#tileIndex+1]=table.concat(row) end
  local chunks={table.concat(height),string.rep('\0',n*n/4),pack(1,4)..pack(6,4)..pack(6,4)..'city.smt\0'..table.concat(tileIndex),
    minimap(plan,palette,checkpoint),string.rep('\0',n*n/4),string.rep('\0',8)}
  local offsets,position={},80
  for _,chunk in ipairs(chunks) do offsets[#offsets+1]=pack(position,4);position=position+#chunk end
  local template=read('citylights/template.smf')
  files['maps/city.smf']=template:sub(1,20)..pack(tonumber(plan.context.generation_digest:sub(1,7),16),4)..template:sub(25,52)..table.concat(offsets)..pack(0,4)..table.concat(chunks)
  local tiles={};for _,color in ipairs(palette) do tiles[#tiles+1]=string.rep(solid(color),85) end
  files['maps/city.smt']='spring tilefile\0'..pack(1,4)..pack(6,4)..pack(32,4)..pack(1,4)..table.concat(tiles)
  local name='MOSAIC sector '..plan.context.generation_digest:sub(1,24)
  local teams={};for i,p in ipairs(plan.starts) do teams[i-1]={startpos={x=p[1],z=p[2]}} end
  files['mapinfo.lua']='return '..util.lua({name=name,shortname='MOSAIC Sector',version=core.VERSION,author='MOSAIC map generator',description=plan.context.city..'; '..plan.context.country..'; original city graph',
    mapfile='maps/city.smf',modtype=3,smf={minheight=-32,maxheight=256},teams=teams})..'\n'
  files['mosaic/map_config.lua']='return '..util.lua(plan.context)..'\n'
  files['mosaic/placements.lua']='return '..util.lua(plan.units)..'\n'
  files['mosaic/balance.lua']='return '..util.lua(plan.report)..'\n'
  files['mosaic/snapshot.json']=snapshot
  files['mosaic/request.lua']='return '..util.lua(options)..'\n'
  for _,path in ipairs(VFS.Include('citylights/adapter_files.lua',nil,VFS.MAP)) do files[path]=read('citylights/adapter/'..path) end
  local names={};for path in pairs(files) do names[#names+1]=path end;table.sort(names)
  local hashes={};for _,path in ipairs(names) do hashes[#hashes+1]=path..'\0'..util.hash(files[path])..'\n' end
  local digest=util.hash(table.concat(hashes))
  files['mosaic/manifest.lua']='return '..util.lua({file_hash= digest,generation_digest=plan.context.generation_digest,files=hashes})..'\n'
  return files,'maps/CityLights_'..plan.context.generation_digest:sub(1,32)..'.sdd',name,digest
end
function M.save(files,folder)
  assert(folder:match('^maps/CityLights_%x+%.sdd$'),'Invalid generated-map directory')
  local existing=io.open(folder..'/mapinfo.lua','rb')
  if existing then
    existing:close()
    for path,body in pairs(files) do
      local f=assert(io.open(folder..'/'..path,'rb'),'Incomplete existing generated-map cache')
      local stored=f:read('*a');f:close();assert(stored==body,'Existing generated-map cache differs; remove it before retrying')
    end
    return true
  end
  local names={};for path in pairs(files) do names[#names+1]=path end;table.sort(names)
  -- For a fresh cache, expose mapinfo only after every other file is complete.
  for _,path in ipairs(names) do if path~='mapinfo.lua' then
    local dir=folder..'/'..(path:match('^(.*)/') or '')
    assert(Spring.CreateDir(dir),'Cannot create map cache directory')
    local file=assert(io.open(folder..'/'..path,'wb'),'Cannot write map cache file');assert(file:write(files[path]));assert(file:close())
  end end
  local file=assert(io.open(folder..'/mapinfo.lua','wb'));assert(file:write(files['mapinfo.lua']));assert(file:close())
end
return M
