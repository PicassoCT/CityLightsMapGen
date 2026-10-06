-- LuaSocket only; cooperative I/O never blocks rendering or synchronized code.
local M={}
function M.decode(response)
  local split=assert(response:find('\r\n\r\n',1,true),'Incomplete HTTP headers')
  local headers,body=response:sub(1,split-1),response:sub(split+4)
  local status=tonumber(headers:match('^HTTP/%d%.%d (%d+)'))
  assert(status==200,'Geography provider HTTP '..tostring(status))
  if headers:lower():find('transfer%-encoding:%s*chunked') then
    local out,pos={},1
    while true do
      local e=assert(body:find('\r\n',pos,true),'Incomplete HTTP chunk')
      local n=assert(tonumber(body:sub(pos,e-1):match('^(%x+)'),16),'Invalid HTTP chunk')
      pos=e+2;if n==0 then break end
      assert(#body>=pos+n+1 and body:sub(pos+n,pos+n+1)=='\r\n','Truncated HTTP body')
      out[#out+1]=body:sub(pos,pos+n-1);pos=pos+n+2
    end
    body=table.concat(out)
  else
    local length=tonumber(headers:lower():match('content%-length:%s*(%d+)'))
    assert(not length or #body==length,'Truncated HTTP body')
  end
  assert(#body<=8*1024*1024,'District snapshot exceeds 8 MiB; reduce radius')
  return body
end
function M.query(lat,lon,radius)
  assert(lat>=-90 and lat<=90 and lon>=-180 and lon<=180 and radius>=100 and radius<=3000,'Invalid Earth viewport')
  local dy=radius/111320;local cosine=math.max(0.000001,math.cos(lat*math.pi/180))
  local dx=math.min(180,dy/cosine);local south,north=math.max(-90,lat-dy),math.min(90,lat+dy)
  local west,east=lon-dx,lon+dx;local boxes={}
  if west<-180 then boxes={{west+360,south,180,north},{-180,south,east,north}};west=west+360
  elseif east>180 then boxes={{west,south,180,north},{-180,south,east-360,north}};east=east-360
  else boxes={{west,south,east,north}} end
  local query=string.format('[out:json][timeout:90];is_in(%.7f,%.7f);area._["admin_level"="2"];out tags;(',lat,lon)
  for _,box in ipairs(boxes) do
    local extent=string.format('(%.7f,%.7f,%.7f,%.7f)',box[2],box[1],box[4],box[3])
    for _,kind in ipairs({'highway','building','natural','landuse','waterway','amenity','power','military'}) do query=query..'way["'..kind..'"]'..extent..';' end
    query=query..'node["amenity"]'..extent..';node["place"]'..extent..';'
  end
  return query..');out geom;',{west,south,east,north}
end
function M.start(query)
  assert(socket and socket.tcp,'Engine LuaSocket unavailable; network fetch cannot start')
  local tcp=assert(socket.tcp());tcp:settimeout(0)
  local req='POST /api/interpreter HTTP/1.1\r\nHost: overpass-api.de\r\nUser-Agent: MOSAIC-CityLights/0.2\r\nContent-Type: text/plain\r\nAccept-Encoding: identity\r\nConnection: close\r\nContent-Length: '..#query..'\r\n\r\n'..query
  local state={tcp=tcp,request=req,offset=1,response={},bytes=0,phase='connect',started=socket.gettime()}
  function state:step()
    if socket.gettime()-self.started>120 then self.tcp:close();error('Geography fetch timed out') end
    if self.phase=='connect' then
      local okay,err=self.tcp:connect('overpass-api.de',80)
      if okay or err=='already connected' then self.phase='send'
      elseif err~='timeout' and err~='Operation already in progress' then self.tcp:close();error('Geography connection: '..tostring(err)) end
    elseif self.phase=='send' then
      local sent,err,last=self.tcp:send(self.request,self.offset)
      self.offset=(sent or last or self.offset-1)+1
      if self.offset>#self.request then self.phase='read'
      elseif err and err~='timeout' then self.tcp:close();error('Geography send: '..err) end
    else
      for _=1,16 do
        local data,err,partial=self.tcp:receive(8192);data=data or partial
        if data and #data>0 then self.response[#self.response+1]=data;self.bytes=self.bytes+#data;assert(self.bytes<=9*1024*1024,'Geography response too large') end
        if err=='closed' then self.tcp:close();return M.decode(table.concat(self.response)) end
        if err=='timeout' then break end
        assert(not err,'Geography read: '..tostring(err))
      end
    end
  end
  return state
end
return M
