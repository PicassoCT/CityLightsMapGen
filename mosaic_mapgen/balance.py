"""Measured clearance and reachable objective access on the actual generated terrain."""
from collections import deque
import numpy as np

CELL = 32

def navigation(height, units, size, clearance):
    n = size//CELL
    # Conservative: every sample in a navigation cell must be dry and not steep.
    corners = np.stack((height[:-1,:-1],height[1:,:-1],height[:-1,1:],height[1:,1:]))
    low = corners.min(axis=0).reshape(n,CELL//8,n,CELL//8).transpose(0,2,1,3).min(axis=(2,3))
    high = corners.max(axis=0).reshape(n,CELL//8,n,CELL//8).transpose(0,2,1,3).max(axis=(2,3))
    free = (low > 2) & ((high-low) < CELL*0.35)
    yy, xx = np.mgrid[:n,:n]
    x, z = (xx+0.5)*CELL, (yy+0.5)*CELL
    for unit in units:
        radius = unit["radius"]+clearance+CELL/2
        free[(np.abs(x-unit["x"]) <= radius) & (np.abs(z-unit["z"]) <= radius)] = False
    return free

def cell(point, grid):
    return (min(grid.shape[0]-1,max(0,int(point[1]//CELL))), min(grid.shape[1]-1,max(0,int(point[0]//CELL))))

def distances(grid, start):
    start = cell(start, grid)
    out = np.full(grid.shape, -1, dtype=np.int32)
    if not grid[start]:
        return out
    out[start] = 0
    queue = deque([start])
    while queue:
        z,x = queue.popleft()
        for rz,rx in ((z-1,x),(z+1,x),(z,x-1),(z,x+1)):
            if 0<=rz<grid.shape[0] and 0<=rx<grid.shape[1] and grid[rz,rx] and out[rz,rx]<0:
                out[rz,rx] = out[z,x]+1
                queue.append((rz,rx))
    return out

def access_distance(distance, unit, clearance):
    # Reach any free cell just outside a building's clearance perimeter.
    n = distance.shape[0]
    z,x = cell((unit["x"],unit["z"]), distance)
    radius = int((unit["radius"]+clearance)/CELL)+2
    section = distance[max(0,z-radius):min(n,z+radius+1),max(0,x-radius):min(n,x+radius+1)]
    valid = section[section>=0]
    return int(valid.min())*CELL if len(valid) else None

def audit(height, texture, units, starts, config):
    failures = []
    grid = navigation(height,units,config.size,config.clearance)
    if not np.array_equal(height,np.fliplr(height)):
        failures.append("Heightfield is not exactly mirrored")
    if not np.array_equal(texture,np.fliplr(texture)):
        failures.append("Surface classification is not exactly mirrored")
    if not np.array_equal(grid,np.fliplr(grid)):
        failures.append("Navigable clearance grid is not exactly mirrored")
    distances_a, distances_b = (distances(grid,p) for p in starts)
    objectives = [u for u in units if u["kind"]=="objective"]
    measurements = []
    for left, right in zip(objectives[::2],objectives[1::2]):
        own = [access_distance(distances_a,left,config.clearance),access_distance(distances_b,right,config.clearance)]
        enemy = [access_distance(distances_b,left,config.clearance),access_distance(distances_a,right,config.clearance)]
        measurements.append({"pair": left["pair"], "unit": left["name"], "own_access": own, "enemy_access": enemy})
        if any(v is None for v in own+enemy):
            failures.append(f'Objective pair {left["pair"]} is unreachable')
        elif own[0]!=own[1] or enemy[0]!=enemy[1]:
            failures.append(f'Objective pair {left["pair"]} has unequal mirrored travel distances')
    # Three separated reinforced traversal lanes must be unobstructed end to end.
    lanes = []
    for z in (config.size/4, config.size/2, 3*config.size/4):
        row = int(z//CELL)
        clear = bool(grid[row,:].all())
        lanes.append({"z":z,"clear":clear})
        if not clear:
            failures.append(f"Cross-city corridor at z={z} is blocked")
    if distances_a[cell(starts[1],grid)]<0:
        failures.append("Starts are disconnected")
    for i,u in enumerate(units):
        if not (u["radius"]<u["x"]<config.size-u["radius"] and u["radius"]<u["z"]<config.size-u["radius"]):
            failures.append(f'Unit {u["id"]} extends outside map')
        for v in units[i+1:]:
            if abs(u["x"]-v["x"]) < u["radius"]+v["radius"]+config.clearance and abs(u["z"]-v["z"]) < u["radius"]+v["radius"]+config.clearance:
                failures.append(f'Overlapping units: {u["id"]}, {v["id"]}')
    houses = sum(u["kind"]=="building" for u in units)
    if houses<config.min_buildings:
        failures.append(f"Only {houses} buildings; minimum is {config.min_buildings}")
    return {"passed":not failures,"failures":failures,"mode":"mirror-x","cell_size":CELL,
            "building_count":houses,"objective_count":len(objectives),"corridors":lanes,"objective_access":measurements,
            "limits":"Static grid clearance, not engine pathfinding or faction win-rate. Building model geometry can exceed declared conservative radius."}
