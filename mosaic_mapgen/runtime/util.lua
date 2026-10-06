local M={}
function M.lua(v)
  local t=type(v)
  if t=='string' then return string.format('%q',v) end
  if t=='number' then assert(v==v and math.abs(v)<math.huge); return tostring(v) end
  if t=='boolean' then return tostring(v) end
  assert(t=='table',"Unsupported serialization value")
  local keys={}; for k in pairs(v) do keys[#keys+1]=k end
  table.sort(keys,function(a,b) if type(a)==type(b) then return a<b end; return type(a)<type(b) end)
  local out={'{'}; for _,k in ipairs(keys) do out[#out+1]='['..M.lua(k)..']='..M.lua(v[k])..',' end
  out[#out+1]='}'; return table.concat(out)
end
function M.hex(s) return (s:gsub('.',function(c) return string.format('%02x',c:byte()) end)) end
function M.unhex(s)
  assert(#s%2==0 and not s:find('[^0-9a-f]'),"Invalid snapshot chunk")
  return (s:gsub('%x%x',function(h) return string.char(tonumber(h,16)) end))
end
function M.hash(s) assert(VFS.CalculateHash,"Engine lacks snapshot hashing"); return VFS.CalculateHash(s,1) end
function M.prng(seed)
  local state=seed%2147483647; if state==0 then state=1 end
  return function(n) state=(state*48271)%2147483647; return state%n end
end
function M.checkpoint(stage) if coroutine.running() then coroutine.yield(stage) end end
return M
