# Download the OpenStreetMap data the region file is built from, one kind of feature per request, retrying across
# the Overpass mirrors (they often answer 504 under load). Writes reg_*.json (the corridor, everything including
# buildings) and wide_*.json (the 100-mile realm: major roads, places, water, land use, points of interest).
#   python3 fetch_osm.py [corridor|realm|all]
# Files already on disk are kept. Fetch once and keep the files: the public servers have usage limits.
import json, os, subprocess, sys, time

CORRIDOR=(33.80,-112.24,34.09,-112.04)
REALM=(33.2173,-113.0115,34.6727,-111.2685)   # 100 miles square around the corridor's centre (prep_region.py)
# the mirrors to try, in order; OVERPASS=url1,url2 overrides (from some networks only one of them answers)
MIRRORS=os.environ.get('OVERPASS','https://maps.mail.ru/osm/tools/overpass/api/interpreter,https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter').split(',')
AMENITY='pharmacy|fuel|hospital|clinic|doctors|fire_station|police|school|veterinary|dentist|restaurant|fast_food|place_of_worship|community_centre|library'

def tiles(b,n):   # split a box into n x n
    s,w,N,e=b; return [(i,j,(s+(N-s)*i/n,w+(e-w)*j/n,s+(N-s)*(i+1)/n,w+(e-w)*(j+1)/n)) for i in range(n) for j in range(n)]
bb=lambda b:','.join(f'{v:.5f}' for v in b)

def jobs(which):
    out=[]
    if which in ('corridor','all'):
        for i,j,b in tiles(CORRIDOR,2):
            B=bb(b)
            out+=[(f'reg_roads_{i}{j}.json',f'way["highway"]({B});out body geom;'),
                  (f'reg_buildings_{i}{j}.json',f'way["building"]({B});out body center geom;')]
        B=bb(CORRIDOR)
        out+=[('reg_pois.json',f'(nwr["shop"]({B});nwr["amenity"~"^({AMENITY})$"]({B});nwr["man_made"~"^(water_well|water_tower|storage_tank)$"]({B}););out body center geom;'),
              ('reg_places.json',f'(node["place"]({B});node["natural"="peak"]({B}););out body;'),
              ('reg_land.json',f'(way["landuse"~"^(residential|retail|commercial|industrial|farmland|farmyard)$"]({B});way["waterway"~"^(river|stream)$"]({B});nwr["natural"="water"]({B}););out body geom;')]
    if which in ('realm','all'):
        for i,j,b in tiles(REALM,3):
            B=bb(b)
            out+=[(f'wide_roads_{i}{j}.json',f'way["highway"~"^(motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified)$"]({B});out body geom;'),
                  (f'wide_land_{i}{j}.json',f'way["landuse"~"^(residential|retail|commercial|industrial|farmland)$"]({B});out body geom;'),
                  (f'wide_pois_{i}{j}.json',f'(nwr["shop"]({B});nwr["amenity"~"^({AMENITY})$"]({B});nwr["man_made"~"^(water_well|water_tower|storage_tank)$"]({B}););out tags center;')]
        B=bb(REALM)
        out+=[('wide_places.json',f'(node["place"~"^(city|town|village|hamlet|suburb)$"]({B});node["natural"="peak"]["name"]({B}););out body;'),
              ('wide_water.json',f'(way["waterway"="river"]({B});way["natural"="water"]({B}););out body geom;')]
    return out

def fetch(f,q,tries=30):
    for k in range(tries):
        for u in MIRRORS:
            r=subprocess.run(['curl','-sS','-m','300','-A','pps-tools-prototype/0.1','-G','--data-urlencode',f'data=[out:json][timeout:240];{q}',u,'-o',f+'.tmp'],capture_output=True)
            try:
                d=json.load(open(f+'.tmp'))
                if 'elements' in d and 'runtime error' not in d.get('remark',''):
                    os.replace(f+'.tmp',f); print('ok',f,len(d['elements']),'elements',os.path.getsize(f)//1024,'KB',flush=True); return True
            except Exception: pass
        time.sleep(min(60,5+5*k))
    print('FAILED',f,flush=True); return False

if __name__=='__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    todo=[(f,q) for f,q in jobs(sys.argv[1] if len(sys.argv)>1 else 'all') if not os.path.exists(f)]
    print(len(todo),'requests to make',flush=True)
    bad=[f for f,q in todo if not fetch(f,q)]
    print('DONE' if not bad else f'DONE with {len(bad)} failed: {bad}')
