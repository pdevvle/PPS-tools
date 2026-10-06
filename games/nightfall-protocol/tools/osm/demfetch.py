# Fetch Terrarium elevation tiles (Terrain Tiles on AWS) for a box at a zoom, as t{z}_{x}_{y}.png for prep.elev.
#   python3 demfetch.py <zoom> <south> <west> <north> <east>
import math, os, subprocess, sys
z=int(sys.argv[1]); s,w,n,e=map(float,sys.argv[2:6]); N=2**z
tx=lambda lon:int((lon+180)/360*N); ty=lambda lat:int((1-math.log(math.tan(math.radians(lat))+1/math.cos(math.radians(lat)))/math.pi)/2*N)
todo=[(x,y) for x in range(tx(w),tx(e)+1) for y in range(ty(n),ty(s)+1) if not os.path.exists(f't{z}_{x}_{y}.png')]
print(len(todo),'tiles to fetch at zoom',z)
for x,y in todo:
    for k in range(5):
        if subprocess.run(['curl','-sSf','-m','60','-o',f't{z}_{x}_{y}.png',f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png']).returncode==0: break
    else: print('failed',z,x,y)
print('done')
