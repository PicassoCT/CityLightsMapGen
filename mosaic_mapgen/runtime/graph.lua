-- Integer-weight movement graph; camera direction is a result, never a balance input.
local M={}
local function heap()
  local nodes,costs={},{}
  return function(node,cost)
    local i=#nodes+1
    while i>1 do local p=math.floor(i/2);if costs[p]<=cost then break end;nodes[i],costs[i]=nodes[p],costs[p];i=p end
    nodes[i],costs[i]=node,cost
  end,function()
    if #nodes==0 then return end
    local node,cost=nodes[1],costs[1];local last,lc=nodes[#nodes],costs[#costs]
    nodes[#nodes],costs[#costs]=nil,nil
    if #nodes>0 then
      local i=1
      while i*2<=#nodes do
        local j=i*2;if j+1<=#nodes and costs[j+1]<costs[j] then j=j+1 end
        if costs[j]>=lc then break end;nodes[i],costs[i]=nodes[j],costs[j];i=j
      end
      nodes[i],costs[i]=last,lc
    end
    return node,cost
  end
end
function M.distances(grid,n,start)
  local dist={};if not grid[start] then return dist end
  local push,pop=heap();push(start,0);dist[start]=0
  while true do
    local u,cost=pop();if not u then return dist end
    if cost==dist[u] then
      local x=(u-1)%n;local z=math.floor((u-1)/n)
      local neighbours={};if x>0 then neighbours[#neighbours+1]=u-1 end;if x<n-1 then neighbours[#neighbours+1]=u+1 end
      if z>0 then neighbours[#neighbours+1]=u-n end;if z<n-1 then neighbours[#neighbours+1]=u+n end
      for _,v in ipairs(neighbours) do if grid[v] then
        local c=cost+grid[u]+grid[v]
        if not dist[v] or c<dist[v] then dist[v]=c;push(v,c) end
      end end
    end
  end
end
function M.access(dist,obj,n,cell,clearance)
  local cx,cz=math.floor(obj.x/cell),math.floor(obj.z/cell)
  local r=math.ceil((obj.radius+clearance)/cell)+1;local best
  for z=math.max(0,cz-r),math.min(n-1,cz+r) do for x=math.max(0,cx-r),math.min(n-1,cx+r) do
    local d=dist[z*n+x+1];if d and (not best or d<best) then best=d end
  end end
  return best
end
function M.find(grid,n,cell,objectives,tolerance,checkpoint)
  assert(#objectives>0,"No opportunities to balance")
  local candidates,seen={},{}
  -- Rotate the deployment axis around three inset rectangular perimeters.
  -- No sine/cosine, random order or floating-point tie-breaking in the search.
  for _,inset in ipairs({2,4,8}) do
    local side=n-1-2*inset; local ring={}
    for t=0,side-1 do ring[#ring+1]={inset+t,inset} end
    for t=0,side-1 do ring[#ring+1]={n-1-inset,inset+t} end
    for t=0,side-1 do ring[#ring+1]={n-1-inset-t,n-1-inset} end
    for t=0,side-1 do ring[#ring+1]={inset,n-1-inset-t} end
    for k=0,31 do
      local i=math.floor(k*#ring/64)+1;local a,b=ring[i],ring[(i-1+#ring/2)%#ring+1]
      local ua,ub=a[2]*n+a[1]+1,b[2]*n+b[1]+1
      if grid[ua] and grid[ub] and not seen[ua..':'..ub] then
        seen[ua..':'..ub]=true;candidates[#candidates+1]={ua,ub}
      end
    end
  end
  local best
  for ci,pair in ipairs(candidates) do
    local da=M.distances(grid,n,pair[1]);local db=M.distances(grid,n,pair[2])
    if da[pair[2]] then
      local oa,ob,total=0,0,0;local reach=true;local access={}
      for _,o in ipairs(objectives) do
        local a,b=M.access(da,o,n,cell,32),M.access(db,o,n,cell,32)
        if not a or not b then reach=false;break end
        local w=o.value or 1;local va,vb=w/(1+a/20),w/(1+b/20)
        oa,ob,total=oa+va,ob+vb,total+w
        access[#access+1]={id=o.id,value=w,access={a,b}}
      end
      if reach then
        local score=math.abs(oa-ob)/math.max(oa,ob)
        -- Break ties by candidate order; all clients traverse identical integer graphs.
        if not best or score<best.score then best={score=score,pair=pair,opportunity={oa,ob},objective_access=access} end
      end
    end
    if checkpoint then checkpoint('deployment '..ci..'/'..#candidates) end
  end
  assert(best,"No connected opposing deployments reach every objective")
  best.passed=best.score<=tolerance
  best.starts={}
  for _,u in ipairs(best.pair) do best.starts[#best.starts+1]={((u-1)%n+0.5)*cell,(math.floor((u-1)/n)+0.5)*cell} end
  best.mode='opportunity-graph';best.relative_imbalance=best.score;best.threshold=tolerance
  best.limits='Weighted static movement-distance opportunity, not engine pathfinding, unit-cover simulation or faction win-rate. Exact equality is not guaranteed.'
  return best
end
return M
