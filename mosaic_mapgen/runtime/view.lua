-- Rotate the view alone: deployment axis is horizontal; geographic data is unchanged.
local M={}
function M.angle(starts)
  return -math.atan2(starts[2][2]-starts[1][2],starts[2][1]-starts[1][1])
end
function M.point(x,z,size,angle)
  x,z=x-size/2,z-size/2
  local c,s=math.cos(angle),math.sin(angle)
  return x*c-z*s,x*s+z*c
end
return M
