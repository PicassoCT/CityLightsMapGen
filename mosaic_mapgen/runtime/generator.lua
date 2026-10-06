local util=VFS.Include('citylights/util.lua',nil,VFS.MAP)
local graph=VFS.Include('citylights/graph.lua',nil,VFS.MAP)
local profiles=VFS.Include('citylights/profiles.lua',nil,VFS.MAP)
local M={VERSION='0.2.0',CELL=64,SIZE=8192}
local function clamp(v,a,b) return math.max(a,math.min(b,v)) end
local function polygonInside(x,z,ring)
  local inside=false;local j=#ring
  for i=1,#ring do local a,b=ring[i],ring[j]
    if (a[2]>z)~=(b[2]>z) and x<(b[1]-a[1])*(z-a[2])/(b[2]-a[2])+a[1] then inside=not inside end
    j=i
  end
  return inside
end
function M.features(data)
  if data.type=='FeatureCollection' then return data.features end
  assert(type(data.elements)=='table' and not data.remark,'Incomplete geographic response')
  local out={}
  for _,e in ipairs(data.elements) do
    if e.type=='node' and e.tags and e.lon and e.lat then
      out[#out+1]={id='node/'..e.id,properties=e.tags,geometry={type='Point',coordinates={e.lon,e.lat}}}
    elseif e.type=='way' and e.geometry and #e.geometry>1 then
      local points={};for _,p in ipairs(e.geometry) do points[#points+1]={p.lon,p.lat} end
      local a,b=points[1],points[#points]
      local closed=#points>3 and a[1]==b[1] and a[2]==b[2] and not (e.tags or {}).highway
      out[#out+1]={id='way/'..e.id,properties=e.tags or {},geometry={type=closed and 'Polygon' or 'LineString',coordinates=closed and {points} or points}}
    end
  end
  return out
end
function M.identity(data,options)
  local country,iso,city
  for _,e in ipairs(data.elements or {}) do
    local t=e.tags or {};local code=t['ISO3166-1:alpha2'] or t['ISO3166-1']
    if e.type=='area' and t.admin_level=='2' and code and #code==2 then
      -- Country IDs, not response ordering, resolve overlapping claims deterministically.
      if not iso or code<iso then iso=code;country=t['name:en'] or t.name end
    end
    if t.place=='city' or t.place=='town' then local name=t['name:en'] or t.name;if name and (not city or name<city) then city=name end end
  end
  iso=options.country_code or iso;assert(iso and #iso==2,'No country resolved at selected point; ocean/border data may need an explicit country')
  local p=profiles.countries[iso] or {country or iso,'Earth','international'}
  local landscape=options.landscape or 'temperate';local env=assert(profiles.landscapes[landscape],'Unknown landscape')
  local culture=options.culture;if not culture or culture=='auto' then culture=p[3] end
  assert(profiles.houses[culture],'Unknown architectural culture')
  return {schema=1,generator_version=M.VERSION,city=options.city or city or string.format('Sector %.4f, %.4f',options.latitude,options.longitude),
    country=options.country or country or p[1],country_code=iso,region=options.region or p[2],province=options.province or '',citypart='Selected district',culture=culture,
    landscape=landscape,rainy=env.rainy,day_color=env.day_color,sun_max_altitude=90-math.abs(options.latitude)*0.65,
    equatorial_sign=options.latitude>=0 and 1 or -1,house_types={},sin_city=false,placement='manual',balance='opportunity-graph',size=M.SIZE,
    source_attribution='© OpenStreetMap contributors',source_license='ODbL-1.0',latitude=options.latitude,longitude=options.longitude,seed=options.seed}
end
function M.build(data,options,checkpoint)
  assert(type(options.latitude)=='number' and options.latitude>=-90 and options.latitude<=90 and options.longitude>=-180 and options.longitude<=180,'Invalid Earth coordinates')
  assert(options.seed>=0 and options.seed<2147483647 and options.seed==math.floor(options.seed),'Invalid seed')
  local features=M.features(data);assert(#features>0 and #features<=60000,'No geographic features, or district too dense')
  table.sort(features,function(a,b)return tostring(a.id)<tostring(b.id) end)
  local context=M.identity(data,options);local n=M.SIZE/M.CELL;local classes={}
  for i=1,n*n do classes[i]=0 end
  local bounds=assert(options.bounds or data.bbox,'Missing frozen viewport');local west,south,east,north=unpack(bounds)
  if east<west then east=east+360 end
  assert(east>west and north>south,'Empty geographic viewport')
  local cosine=math.max(0.000001,math.cos((south+north)*math.pi/360))
  local scale=math.min((M.SIZE-640)/((east-west)*cosine),(M.SIZE-640)/(north-south))
  local x0,z0=(M.SIZE-(east-west)*cosine*scale)/2,(M.SIZE-(north-south)*scale)/2
  local function project(p)
    local lon=p[1];if lon<west and east>180 then lon=lon+360 end
    return {math.floor(x0+(lon-west)*cosine*scale+0.5),math.floor(z0+(north-p[2])*scale+0.5)}
  end
  local function index(x,z) return clamp(math.floor(z/M.CELL),0,n-1)*n+clamp(math.floor(x/M.CELL),0,n-1)+1 end
  local buildings,objectives,layers={},{},{[2]={},[3]={},[4]={},[1]={}}
  for _,f in ipairs(features) do
    local t,g=f.properties or {},f.geometry;assert(g and g.coordinates,'Malformed feature geometry')
    local points=g.type=='Polygon' and g.coordinates[1] or g.coordinates
    if g.type=='Point' then points={g.coordinates} end
    if g.type=='MultiPolygon' then points=g.coordinates[1][1] end
    local ring,cx,cz={},0,0
    for _,p in ipairs(points) do local q=project(p);ring[#ring+1]=q;cx,cz=cx+q[1],cz+q[2] end
    cx,cz=math.floor(cx/#ring),math.floor(cz/#ring)
    local name
    for _,key in ipairs({'amenity','landuse','power','military'}) do local v=key=='military' and t[key] and 'military' or t[key];name=name or profiles.objectives[v] end
    if name then objectives[#objectives+1]={x=cx,z=cz,name=name,source_id=tostring(f.id)}
    elseif t.building and t.building~='no' then buildings[#buildings+1]={x=cx,z=cz,source_id=tostring(f.id)} end
    local cls
    if t.highway then cls=1 elseif t.waterway or t.water or t.natural=='water' or t.natural=='wetland' or t.landuse=='reservoir' then cls=4
    elseif t.natural=='wood' or t.landuse=='forest' then cls=3
    elseif t.leisure=='park' or t.landuse=='grass' or t.landuse=='meadow' or t.landuse=='farmland' then cls=2 end
    if cls then layers[cls][#layers[cls]+1]={ring=ring,line=g.type=='LineString'} end
  end
  for _,cls in ipairs({2,3,4,1}) do for _,f in ipairs(layers[cls]) do
    if f.line then
      for i=2,#f.ring do local a,b=f.ring[i-1],f.ring[i];local steps=math.max(1,math.ceil(math.max(math.abs(b[1]-a[1]),math.abs(b[2]-a[2]))/32))
        for k=0,steps do classes[index(a[1]+(b[1]-a[1])*k/steps,a[2]+(b[2]-a[2])*k/steps)]=cls end
      end
    else
      local minx,minz,maxx,maxz=M.SIZE,M.SIZE,0,0
      for _,p in ipairs(f.ring) do minx,minz,maxx,maxz=math.min(minx,p[1]),math.min(minz,p[2]),math.max(maxx,p[1]),math.max(maxz,p[2]) end
      for z=clamp(math.floor(minz/M.CELL),0,n-1),clamp(math.floor(maxz/M.CELL),0,n-1) do
        for x=clamp(math.floor(minx/M.CELL),0,n-1),clamp(math.floor(maxx/M.CELL),0,n-1) do
          if polygonInside((x+0.5)*M.CELL,(z+0.5)*M.CELL,f.ring) then classes[z*n+x+1]=cls end
        end
      end
    end
  end end
  if checkpoint then checkpoint('geography') end
  local rng=util.prng(options.seed);local units={};local count=options.max_buildings or 100
  local function place(c,radius,kind)
    local x,z=math.floor(c.x/32)*32+16,math.floor(c.z/32)*32+16
    if x<radius+160 or z<radius+160 or x>M.SIZE-radius-160 or z>M.SIZE-radius-160 then return false end
    for _,u in ipairs(units) do if math.abs(x-u.x)<radius+u.radius+64 and math.abs(z-u.z)<radius+u.radius+64 then return false end end
    local r=math.ceil((radius+32)/M.CELL)
    for rz=-r,r do for rx=-r,r do local cls=classes[index(x+rx*M.CELL,z+rz*M.CELL)];if cls==4 or cls==1 then return false end end end
    local name=c.name
    if kind=='building' then local die=rng(100);for _,w in ipairs(profiles.houses[context.culture]) do if die<w[2] then name=w[1];break end;die=die-w[2] end end
    units[#units+1]={id=kind..'-'..#units,name=name,x=x,z=z,radius=radius,kind=kind,facing=rng(4),source_id=c.source_id,value=1}
    return true
  end
  for _,c in ipairs(objectives) do if #units<(options.objective_count or 6) then place(c,256,'objective') end end
  -- Missing objective sites are explicit gameplay infill, never a duplicated city half.
  for attempt=1,5000 do
    if #units>=(options.objective_count or 6) then break end
    place({x=320+rng(M.SIZE-640),z=320+rng(M.SIZE-640),name=profiles.fallbacks[(#units%#profiles.fallbacks)+1],source_id='procedural/objective'},256,'objective')
  end
  local objs={};for _,u in ipairs(units) do if u.kind=='objective' then objs[#objs+1]=u end end
  assert(#objs>=2,'Insufficient dry objective sites')
  local houses=0
  for _,c in ipairs(buildings) do if houses<count and place(c,160,'building') then houses=houses+1 end end
  for attempt=1,5000 do
    if houses>=count then break end
    if place({x=320+rng(M.SIZE-640),z=320+rng(M.SIZE-640),source_id='procedural/infill'},160,'building') then houses=houses+1 end
  end
  assert(houses>=(options.min_buildings or 12),'Insufficient usable land for city housing')
  local grid={};for i,c in ipairs(classes) do if c~=4 then grid[i]=c==1 and 10 or 18 end end
  for _,u in ipairs(units) do local r=math.ceil((u.radius+32)/M.CELL)
    for z=math.floor(u.z/M.CELL)-r,math.floor(u.z/M.CELL)+r do for x=math.floor(u.x/M.CELL)-r,math.floor(u.x/M.CELL)+r do if z>=0 and z<n and x>=0 and x<n then grid[z*n+x+1]=nil end end end
  end
  local report=graph.find(grid,n,M.CELL,objs,options.balance_tolerance or 0.08,checkpoint)
  assert(report.passed,string.format('Best deployment has %.1f%% opportunity imbalance (limit %.1f%%); choose a different extent',report.score*100,report.threshold*100))
  report.building_count=houses;report.objective_count=#objs;report.failures={};report.source_geometry='original, unmirrored and unrotated'
  local packageIdentity=VFS.Include('citylights/package_identity.lua',nil,VFS.MAP)
  if data.source then context.source_attribution=data.source.attribution;context.source_license=data.source.license end
  context.generation_digest=util.hash(M.VERSION..'\n'..packageIdentity..'\n'..util.lua(options)..'\n'..util.lua(features)..'\n'..util.lua(context))
  context.source_digest=util.hash(util.lua(features));context.cityname=context.city
  return {classes=classes,units=units,starts=report.starts,context=context,report=report,n=n,size=M.SIZE,cell=M.CELL,grid=grid}
end
function M.height(plan,x,z)
  local i=clamp(math.floor(z/plan.cell),0,plan.n-1)*plan.n+clamp(math.floor(x/plan.cell),0,plan.n-1)+1
  return plan.classes[i]==4 and -12 or 32
end
return M
