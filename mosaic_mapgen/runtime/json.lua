-- Data-only JSON decoder. Never evaluates downloaded Lua or JSON as code.
local M = {}
function M.decode(s)
  assert(type(s)=="string" and #s<=8*1024*1024, "Snapshot exceeds 8 MiB")
  local i, depth = 1, 0
  local function ws() local _,e=s:find("^[ \t\r\n]*",i); i=(e or i-1)+1 end
  local parse
  local function str()
    assert(s:sub(i,i)=='"',"Expected string"); i=i+1; local out={}
    while i<=#s do
      local c=s:sub(i,i); i=i+1
      if c=='"' then return table.concat(out) end
      if c=='\\' then
        local e=s:sub(i,i); i=i+1
        local escapes={['"']='"',['\\']='\\',['/']='/',b='\b',f='\f',n='\n',r='\r',t='\t'}
        if e=='u' then
          local h=s:sub(i,i+3); assert(h:match('^%x%x%x%x$'),"Invalid Unicode escape"); i=i+4
          local n=tonumber(h,16)
          if n>=0xD800 and n<=0xDBFF then
            assert(s:sub(i,i+1)=='\\u',"Missing low surrogate"); i=i+2
            local low=tonumber(s:sub(i,i+3),16); i=i+4
            assert(low and low>=0xDC00 and low<=0xDFFF,"Invalid low surrogate")
            n=0x10000+(n-0xD800)*1024+low-0xDC00
          else assert(n<0xDC00 or n>0xDFFF,"Unexpected low surrogate") end
          if n<128 then c=string.char(n)
          elseif n<2048 then c=string.char(192+math.floor(n/64),128+n%64)
          elseif n<65536 then c=string.char(224+math.floor(n/4096),128+math.floor(n/64)%64,128+n%64)
          else c=string.char(240+math.floor(n/262144),128+math.floor(n/4096)%64,128+math.floor(n/64)%64,128+n%64) end
        else c=assert(escapes[e],"Invalid escape") end
      else assert(c:byte()>=32,"Control byte in string") end
      out[#out+1]=c
    end
    error("Unterminated string")
  end
  parse=function()
    ws(); depth=depth+1; assert(depth<40,"Snapshot nesting limit")
    local c=s:sub(i,i); local value
    if c=='"' then value=str()
    elseif c=='{' or c=='[' then
      local object=c=='{'; local close=object and '}' or ']'; i=i+1; ws(); value={}
      if s:sub(i,i)~=close then
        while true do
          local key
          if object then key=str(); ws(); assert(s:sub(i,i)==':',"Expected colon"); i=i+1
          else key=#value+1 end
          assert(value[key]==nil,"Duplicate JSON key"); value[key]=parse(); ws()
          c=s:sub(i,i); if c==close then break end
          assert(c==',',"Expected comma"); i=i+1; ws()
        end
      end
      i=i+1
    elseif s:sub(i,i+3)=='true' then value=true; i=i+4
    elseif s:sub(i,i+4)=='false' then value=false; i=i+5
    elseif s:sub(i,i+3)=='null' then value=M.null; i=i+4
    else
      local token=s:match('^-?%d+%.?%d*[eE][+-]?%d+',i) or s:match('^-?%d+%.?%d*',i)
      assert(token and not token:match('^-?0%d') and not token:match('%.$') and not token:match('%.[eE]'),"Invalid number")
      value=tonumber(token); assert(value and value==value and math.abs(value)<math.huge,"Non-finite number"); i=i+#token
    end
    depth=depth-1; return value
  end
  local value=parse(); ws(); assert(i>#s,"Trailing JSON data"); return value
end
M.null={}
return M
