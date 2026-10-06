-- Network state is synchronized; local file/network operations stay in LuaUI.
local util=VFS.Include('citylights/util.lua',nil,VFS.MAP)
local M={}
function M.new(players,controller,emit,hash)
  local self={phase='select',players=players,controller=controller,ready={},armed={},hello={},chunks={}}
  hash=hash or util.hash
  local function fail(reason) self.phase='failed';emit('failed',reason) end
  function self:receive(msg,player)
    if not self.players[player] or #msg>3500 then return false end
    local verb,body=msg:match('^CLG1:(%u+):(.*)$');if not verb then return false end
    if verb=='HELLO' and self.phase=='select' then
      self.hello[player]=true
      for id in pairs(self.players) do if not self.hello[id] then return true end end
      self.roomReady=true;emit('room','ready')
    elseif verb=='BEGIN' and self.phase=='select' and player==self.controller then
      if not self.roomReady then fail('A room client has not initialized the map generator');return true end
      local h,total,bytes,opts=body:match('^(%x+)|(%d+)|(%d+)|(.+)$');total,bytes=tonumber(total),tonumber(bytes)
      if not h or #h~=128 or not total or total<1 or total>6000 or not bytes or bytes>8*1024*1024 then fail('Invalid snapshot header');return true end
      self.digest,self.total,self.bytes,self.options=h,total,bytes,opts;self.phase='receiving';self.next=1;emit('begin',body)
    elseif verb=='CHUNK' and self.phase=='receiving' and player==self.controller then
      local i,hex=body:match('^(%d+)|([0-9a-f]+)$');i=tonumber(i)
      if not hex or i~=self.next or #hex>2800 or #hex%2~=0 then fail('Snapshot sequence mismatch');return true end
      self.chunks[i]=util.unhex(hex);self.next=i+1;emit('chunk',body)
      if i==self.total then
        local raw=table.concat(self.chunks)
        if #raw~=self.bytes or hash(raw)~=self.digest then fail('Frozen snapshot hash mismatch');return true end
        self.phase='generating';emit('build',self.digest)
      end
    elseif verb=='READY' and self.phase=='generating' then
      local digest=body:match('^(%x+)$');if not digest or #digest~=128 then fail('Invalid generated-map hash');return true end
      if self.fileDigest and self.fileDigest~=digest then fail('Clients generated different map files');return true end
      self.fileDigest=digest;self.ready[player]=true;emit('ready',tostring(player))
      for id in pairs(self.players) do if not self.ready[id] then return true end end
      self.phase='arming';emit('arm',digest)
    elseif verb=='ARMED' and self.phase=='arming' and body==self.fileDigest then
      self.armed[player]=true
      for id in pairs(self.players) do if not self.armed[id] then return true end end
      self.phase='committed';emit('commit',self.fileDigest)
    elseif verb=='FAIL' and self.phase~='committed' then fail('Player '..player..': '..body:sub(1,180)) end
    return true
  end
  return self
end
return M
