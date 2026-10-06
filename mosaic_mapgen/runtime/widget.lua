function widget:GetInfo() return {name='CityLights world-city startup',desc='Fetch, freeze, generate and agree a real-city map before internal reload',author='MOSAIC contributors',layer=10000000,enabled=true} end
local function include(name) return VFS.Include('citylights/'..name..'.lua',nil,VFS.MAP) end
local util,json,http,core,export,tdf=include('util'),include('json'),include('http'),include('generator'),include('export'),include('startscript')
local request,transfer,worker,plan,folder,mapname,filehash,localScript,reloadScript
local phase,message,chunks,commitTime='select','Choose a position on Earth',{},nil
local roomReady,helloTime=false,nil
local lat,lon,seed,radius=52.52,13.405,1,800
local landscape='temperate';local bounds
local world=include('world')
local view=include('view');local graphList
local function send(verb,body) Spring.SendLuaGaiaMsg('CLG1:'..verb..':'..body) end
local function fail(reason) phase='failed';message=tostring(reason):sub(1,240);send('FAIL',message) end
local function selected() return roomReady and Spring.GetLocalPlayerID()==Spring.GetGameRulesParam('citylights_controller') end
local function freeze(raw,options)
  json.decode(raw) -- fail before broadcasting a malformed/provider-error body
  local optjson=string.format('{"latitude":%.7f,"longitude":%.7f,"seed":%d,"landscape":"%s","bounds":[%.9f,%.9f,%.9f,%.9f]}',lat,lon,seed,landscape,unpack(bounds))
  local total=math.ceil(#raw/1400)
  send('BEGIN',util.hash(raw)..'|'..total..'|'..#raw..'|'..optjson)
  transfer={raw=raw,index=1,total=total}
end
local function packet(verb,body)
  if verb=='room' then roomReady=true
  elseif verb=='failed' then phase='failed';message=body
  elseif verb=='begin' then phase='receiving';chunks={};local _,_,_,opts=body:match('^(%x+)|(%d+)|(%d+)|(.+)$');request=json.decode(opts);message='Receiving the frozen geographic snapshot'
  elseif verb=='chunk' then local i,h=body:match('^(%d+)|(.+)$');chunks[tonumber(i)]=util.unhex(h)
  elseif verb=='build' then
    local raw=table.concat(chunks);assert(util.hash(raw)==body,'Snapshot agreement failed');chunks={}
    local data=json.decode(raw);request.snapshot_sha512=body;phase='generating'
    worker=coroutine.create(function()
      localScript=assert(VFS.LoadFile('script.txt',VFS.RAW),'Skylobby local script.txt missing; cannot preserve connection')
      local parsed=tdf.parse(localScript)
      local myname=Spring.GetPlayerInfo(Spring.GetLocalPlayerID())
      assert(parsed.myplayername==myname,'Local script.txt belongs to another session')
      plan=core.build(data,request,util.checkpoint)
      local files;files,folder,mapname,filehash=export.files(plan,raw,request,util.checkpoint)
      reloadScript=tdf.forMap(localScript,mapname,plan.starts)
      export.save(files,folder)
      -- Read back each file before announcing readiness.
      for path,expected in pairs(files) do
        local f=assert(io.open(folder..'/'..path,'rb'));local actual=f:read('*a');f:close();assert(util.hash(actual)==util.hash(expected),'Generated cache verification failed')
      end
      phase='waiting';message='Generated '..folder..'; waiting for matching peers';send('READY',filehash)
    end)
  elseif verb=='ready' then message='Player '..body..' verified their generated map'
  elseif verb=='arm' then assert(body==filehash and reloadScript,'Reload preflight mismatch');send('ARMED',body);phase='armed';message='All maps match; preparing internal reload'
  elseif verb=='commit' then assert(body==filehash,'Commit hash mismatch');commitTime=Spring.GetTimer();phase='handoff';message='Handing off to the agreed battlefield'
  end
end
function widget:Initialize()
  assert(VFS.CalculateHash and Spring.Reload and Spring.SendLuaGaiaMsg and io and io.open,'Engine lacks map bootstrap APIs')
  local okay,err=pcall(function()
    local expected=json.decode(assert(VFS.LoadFile('citylights/adapter-source.json',VFS.MAP)))
    for path,digest in pairs(expected.base_source_sha512) do
      local source=assert(VFS.LoadFile(path,VFS.MOD_BASE),'Required MOSAIC source missing: '..path)
      assert(util.hash(source:gsub('\r\n','\n'))==digest,'MOSAIC revision differs from packaged adapter: '..path)
    end
  end)
  if not okay then fail(err);return end
  local options=Spring.GetMapOptions();seed=tonumber(options.citylights_seed) or seed
  lat=tonumber(options.citylights_latitude) or lat;lon=tonumber(options.citylights_longitude) or lon;radius=tonumber(options.citylights_radius) or radius
  landscape=options.citylights_landscape or landscape
  widgetHandler:RegisterGlobal('CityLightsPacket',function(...) local okay,err=pcall(packet,...);if not okay then fail(err) end end)
end
function widget:Shutdown() widgetHandler:DeregisterGlobal('CityLightsPacket');if request and request.http then request.http.tcp:close() end;if graphList then gl.DeleteList(graphList) end end
function widget:Update()
  if phase=='select' and not roomReady and (not helloTime or Spring.DiffTimers(Spring.GetTimer(),helloTime)>=1) then
    helloTime=Spring.GetTimer();send('HELLO','ready')
  end
  if transfer then
    for _=1,4 do
      if transfer.index>transfer.total then transfer=nil;break end
      local i=transfer.index;send('CHUNK',i..'|'..util.hex(transfer.raw:sub((i-1)*1400+1,i*1400)));transfer.index=i+1
    end
  end
  if request and request.http then
    local okay,result=pcall(function()return request.http:step()end)
    if not okay then request=nil;fail(result)
    elseif result then request=nil;local ok,err=pcall(freeze,result);if not ok then fail(err) end end
  end
  if worker then
    local start=Spring.GetTimer()
    repeat
      local okay,stage=coroutine.resume(worker)
      if not okay then worker=nil;fail(stage);break end
      if coroutine.status(worker)=='dead' then worker=nil;break end
      message='Generating original city: '..tostring(stage)
    until Spring.DiffTimers(Spring.GetTimer(),start)>0.012
  end
  if commitTime then
    local reloadDelay=tdf.parse(localScript).ishost=='1' and 5 or 8
    if Spring.DiffTimers(Spring.GetTimer(),commitTime)>=reloadDelay then commitTime=nil;Spring.Reload(reloadScript) end
  end
end
local function viewport()
  local w,h=Spring.GetViewGeometry();local left,right=math.floor(w*0.08),math.floor(w*0.92)
  local bottom,top=math.floor(h*0.20),math.floor(h*0.82)
  return w,h,left,bottom,right,top
end
local function drawGraph(l,b,r,t)
  local angle=view.angle(plan.starts)
  if not graphList then graphList=gl.CreateList(function()
    local function vertex(x,z) local a,c=view.point(x,z,plan.size,angle);gl.Vertex(a,c) end
    local colors={{0.18,0.22,0.20},{0.42,0.45,0.45},{0.3,0.4,0.25},{0.14,0.3,0.21},{0.09,0.23,0.36},{0.4,0.36,0.3}}
    for z=0,plan.n-1 do for x=0,plan.n-1 do
      local c=colors[plan.classes[z*plan.n+x+1]+1];gl.Color(c[1],c[2],c[3],1)
      gl.BeginEnd(GL.QUADS,function() vertex(x*plan.cell,z*plan.cell);vertex((x+1)*plan.cell,z*plan.cell);vertex((x+1)*plan.cell,(z+1)*plan.cell);vertex(x*plan.cell,(z+1)*plan.cell) end)
    end end
    gl.Color(0.5,0.85,0.85,0.25)
    gl.BeginEnd(GL.LINES,function()
      for z=0,plan.n-1 do for x=0,plan.n-1 do
        local i=z*plan.n+x+1
        if plan.grid[i] then
          if x<plan.n-1 and plan.grid[i+1] then vertex((x+0.5)*plan.cell,(z+0.5)*plan.cell);vertex((x+1.5)*plan.cell,(z+0.5)*plan.cell) end
          if z<plan.n-1 and plan.grid[i+plan.n] then vertex((x+0.5)*plan.cell,(z+0.5)*plan.cell);vertex((x+0.5)*plan.cell,(z+1.5)*plan.cell) end
        end
      end end
    end)
    for _,u in ipairs(plan.units) do
      gl.Color(u.kind=='objective' and 1 or 0.7,u.kind=='objective' and 0.7 or 0.7,0.35,1)
      local x,z=view.point(u.x,u.z,plan.size,angle);gl.Rect(x-u.radius,z-u.radius,x+u.radius,z+u.radius)
    end
    for i,p in ipairs(plan.starts) do
      gl.Color(i==1 and 0.2 or 1,i==1 and 0.8 or 0.3,0.6,1)
      local x,z=view.point(p[1],p[2],plan.size,angle);gl.Rect(x-100,z-100,x+100,z+100)
    end
  end) end
  gl.PushMatrix();gl.Translate((l+r)/2,(b+t)/2,0)
  local scale=math.min(r-l,t-b)/(plan.size*1.42);gl.Scale(scale,scale,1);gl.CallList(graphList);gl.PopMatrix()
end
function widget:DrawScreen()
  local w,h,l,b,r,t=viewport();gl.Color(0.015,0.035,0.055,1);gl.Rect(0,0,w,h)
  gl.Color(0.08,0.18,0.23,1);gl.Rect(l,b,r,t)
  if plan then drawGraph(l,b,r,t) else
  gl.Color(0.2,0.35,0.4,1)
  gl.BeginEnd(GL.LINES,function()
    for x=-180,180,30 do local px=l+(x+180)/360*(r-l);gl.Vertex(px,b);gl.Vertex(px,t) end
    for y=-90,90,30 do local py=b+(y+90)/180*(t-b);gl.Vertex(l,py);gl.Vertex(r,py) end
  end)
  gl.Color(0.25,0.43,0.4,1)
  for _,ring in ipairs(world) do gl.BeginEnd(GL.LINE_STRIP,function()for _,p in ipairs(ring) do gl.Vertex(l+(p[1]+180)/360*(r-l),b+(p[2]+90)/180*(t-b)) end end) end
  gl.Color(1,0.7,0.22,1);local px,py=l+(lon+180)/360*(r-l),b+(lat+90)/180*(t-b);gl.Rect(px-4,py-4,px+4,py+4)
  end
  gl.Color(0.9,0.94,0.93,1);gl.Text('MOSAIC / CITYLIGHTS — CHOOSE THE THEATRE',l,h*0.9,24,'o')
  gl.Text(plan and string.format('Original city + movement graph / view rotation %.1f degrees / opportunity imbalance %.2f%%',view.angle(plan.starts)*180/math.pi,plan.report.relative_imbalance*100) or string.format('Latitude %.5f   Longitude %.5f   Radius %dm   Seed %d   Landscape %s',lat,lon,radius,seed,landscape),l,b-30,15,'o')
  gl.Text(message,l,h*0.12,15,'o')
  gl.Text(selected() and 'Click Earth to select. Enter: fetch and generate. L: landscape. Mouse wheel: district radius.' or 'Waiting for the room controller to select a location.',l,h*0.06,13,'o')
  gl.Color(1,1,1,1)
end
function widget:MousePress(x,y,button)
  local _,_,l,b,r,t=viewport()
  if phase=='select' and selected() and button==1 and x>=l and x<=r and y>=b and y<=t then lon=(x-l)/(r-l)*360-180;lat=(y-b)/(t-b)*180-90 end
  return true
end
function widget:MouseWheel(up,value) if phase=='select' and selected() then radius=math.max(100,math.min(3000,radius+(up and 100 or -100))) end;return true end
function widget:KeyPress(key)
  if key==27 then return false end -- preserve the engine quit menu
  if phase=='select' and selected() then
    if key==13 then
      local okay,err=pcall(function()local query;query,bounds=http.query(lat,lon,radius);request={http=http.start(query)};phase='fetching';message='Fetching geographic data from OpenStreetMap' end)
      if not okay then fail(err) end
    elseif key==108 then local list={'temperate','arid','tropical','alpine','mediterranean'};for i,v in ipairs(list) do if v==landscape then landscape=list[i%#list+1];break end end end
  end
  return true
end
function widget:GameSetup() return true,true end
function widget:CommandNotify() return true end
