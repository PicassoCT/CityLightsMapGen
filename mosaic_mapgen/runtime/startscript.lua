-- Parse TDF as data; preserve local passwords/connection details, never transmit them.
local M={}
function M.parse(text)
  assert(type(text)=='string' and #text<4*1024*1024,"Invalid local start script")
  local pos=1
  local function ws()
    while true do
      local _,e=text:find('^%s*',pos);pos=(e or pos-1)+1
      if text:sub(pos,pos+1)=='//' then local nl=text:find('[\r\n]',pos+2);pos=nl or #text+1
      elseif text:sub(pos,pos+1)=='/*' then pos=assert(text:find('*/',pos+2,true),'Unclosed TDF comment')+2
      else return end
    end
  end
  local section
  section=function()
    local result={}; ws(); assert(text:sub(pos,pos)=='{',"Expected TDF section");pos=pos+1
    while true do
      ws(); local c=text:sub(pos,pos); assert(c~='',"Unclosed TDF section")
      if c=='}' then pos=pos+1; return result end
      if c=='[' then
        local e=assert(text:find(']',pos+1,true),"Unclosed TDF section name")
        local name=text:sub(pos+1,e-1):lower();pos=e+1;ws()
        assert(result[name]==nil,"Duplicate TDF section");result[name]=section()
      else
        local e=assert(text:find('=',pos,true),"Missing TDF equals")
        local key=text:sub(pos,e-1):match('^%s*(.-)%s*$'):lower();pos=e+1
        e=assert(text:find(';',pos,true),"Missing TDF semicolon")
        assert(key~='' and not key:find('[{}%[%]]') and result[key]==nil,"Invalid/duplicate TDF key")
        result[key]=text:sub(pos,e-1):match('^%s*(.-)%s*$');pos=e+1
      end
    end
  end
  ws(); assert(text:sub(pos,pos)=='['); local e=assert(text:find(']',pos,true))
  assert(text:sub(pos+1,e-1):lower()=='game',"Missing GAME section");pos=e+1
  local result=section();ws();assert(pos>#text,"Trailing TDF data");return result
end
function M.write(game)
  local function emit(t,name)
    local out={'['..name..']\n{\n'}; local keys={};for k in pairs(t) do keys[#keys+1]=k end;table.sort(keys)
    for _,k in ipairs(keys) do
      assert(k:match('^[%w_]+$'),"Invalid TDF key")
      if type(t[k])=='table' then out[#out+1]=emit(t[k],k)
      else local v=tostring(t[k]);assert(not v:find('[;{}\r\n]'),"Invalid TDF value");out[#out+1]=k..'='..v..';\n' end
    end
    out[#out+1]='}\n'; return table.concat(out)
  end
  return emit(game,'game')
end
function M.forMap(original,mapname,starts)
  local g=M.parse(original)
  assert(g.ishost=='0' or g.ishost=='1',"Local script has no explicit host role")
  assert(g.myplayername and g.myplayername~='',"Local player identity missing")
  g.mapname=mapname; g.maphash=nil; g.mapchecksum=nil;g.demofile=nil;g.savefile=nil
  if g.ishost=='1' then
    g.startpostype='0'; local allies={}
    for k,t in pairs(g) do if k:match('^team%d+$') then allies[t.allyteam]=true end end
    local ids={}; for k in pairs(allies) do ids[#ids+1]=tonumber(k) end;table.sort(ids)
    assert(#ids==2,"Generated-city bootstrap supports exactly two opposing allyteams")
    for k,t in pairs(g) do if k:match('^team%d+$') then
      local side=tonumber(t.allyteam)==ids[1] and 1 or 2
      t.startposx=starts[side][1];t.startposz=starts[side][2]
    end end
  else assert(g.hostip and g.hostport,"Local reconnect endpoint missing") end
  return M.write(g)
end
return M
