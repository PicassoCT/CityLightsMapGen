local coordinator=VFS.Include('citylights/coordinator.lua',nil,VFS.MAP)
local room
function Initialize()
  local players,controller={},nil
  for _,id in ipairs(Spring.GetPlayerList()) do
    local name,active,spec=Spring.GetPlayerInfo(id)
    players[id]=true;if not spec and (not controller or id<controller) then controller=id end
  end
  assert(controller,'No human controller; headless/relay bootstrap is not supported')
  room=coordinator.new(players,controller,function(verb,body) SendToUnsynced('citylights',verb,body) end)
  Spring.SetGameRulesParam('citylights_controller',controller,{public=true})
  Spring.SetGameRulesParam('citylights_stage',1,{public=true})
end
function RecvLuaMsg(msg,player) return room and room:receive(msg,player) or false end
