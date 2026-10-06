function RecvFromSynced(tag,verb,body)
  if tag=='citylights' and Script.LuaUI('CityLightsPacket') then Script.LuaUI.CityLightsPacket(verb,body) end
end
