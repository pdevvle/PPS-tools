# Extract a block of sectors (default 5x5 of 600 m) from the region download: OSM features in block metres and a 4 m height grid.
# The block is shaped and cut into sectors by bake.js, so neighbouring sectors share their edges exactly.
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
import json, math, glob, os, subprocess, sys
from prep import elev

NAME, LAT0, LON0, N = 'newriver', 33.9180, -112.13855, 5      # block centre = the New River sector's centre
SEC=600; HALF=SEC*N/2; MARGIN=120; STEP=4
kx=111320*math.cos(math.radians(LAT0)); ky=110574
P=lambda la,lo:[round((lo-LON0)*kx,1), round(-(la-LAT0)*ky,1)]
LL=lambda x,z:(LAT0-z/ky, LON0+x/kx)
E=HALF+MARGIN
S_,N_=LL(0,E)[0],LL(0,-E)[0]; W_,E_=LL(-E,0)[1],LL(E,0)[1]

# elevation tiles at zoom 15 for the block, zoom 13 for 5 km of landscape around it
def need(Z,s,w,n,e):
    t=2**Z; tx=lambda lo:int((lo+180)/360*t); ty=lambda la:int((1-math.log(math.tan(math.radians(la))+1/math.cos(math.radians(la)))/math.pi)/2*t)
    return [(x,y) for x in range(tx(w),tx(e)+1) for y in range(ty(n),ty(s)+1)]
CH=5000; cs,cn=LL(0,CH)[0],LL(0,-CH)[0]; cw,ce=LL(-CH,0)[1],LL(CH,0)[1]
for Z,box in ((15,(S_,W_,N_,E_)),(13,(cs,cw,cn,ce))):
    for x,y in need(Z,*box):
        f=f't{Z}_{x}_{y}.png'
        if not os.path.exists(f): subprocess.run(['curl','-sS','-m','40','-o',f,f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png'],check=True)

els={}
for f in sorted(glob.glob('reg_*.json'))+['newriver.json','anthem.json','pois.json','context.json']:
    for e in json.load(open(f))['elements']: els[(e['type'],e['id'])]=e
inside=lambda p,m=0:abs(p[0])<=E+m and abs(p[1])<=E+m
D={'name':NAME,'center':[LAT0,LON0],'sector':SEC,'n':N,'half':HALF,'margin':MARGIN,'buildings':[],'roads':[],'barriers':[],'areas':[],'water':[],'pois':[],'trees':[]}
def poi_kind(t):
    v=t.get('shop') or t.get('amenity')
    if not v: return None
    for k,s in {'food':{'supermarket','convenience','restaurant','fast_food','cafe','ice_cream','bakery','greengrocer'},'medicine':{'pharmacy','dentist','doctors','clinic','hospital','veterinary'},
                'tools':{'doityourself','hardware','car_repair','swimming_pool','garden_centre','trade'},'fuel':{'fuel'},'gear':{'fire_station','police'},
                'shelter':{'bank','post_office','jewelry','dry_cleaning','hairdresser','school','place_of_worship','community_centre','library'}}.items():
        if v in s: return k
for (typ,_),el in els.items():
    t=el.get('tags',{})
    if typ=='node':
        p=P(el['lat'],el['lon'])
        if not inside(p): continue
        if t.get('natural')=='tree': D['trees'].append(p); continue
        k=poi_kind(t)
        if k and t.get('amenity') not in ('waste_disposal','charging_station','fountain','shelter','bench','parking_entrance'): D['pois'].append({'p':p,'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
        continue
    g=[P(q['lat'],q['lon']) for q in el.get('geometry',[]) if q]
    if len(g)<2 or not any(inside(p,400) for p in g): continue
    if 'building' in t:
        if not any(inside(p) for p in g): continue
        b={'pts':g[:-1] if g[0]==g[-1] else g,'type':t['building']}
        if t.get('building:levels'):
            try: b['levels']=float(t['building:levels'].split(';')[0])
            except: pass
        if t.get('name'): b['name']=t['name']
        k=poi_kind(t)
        if k: b['loot']=k; b['what']=t.get('shop') or t.get('amenity')
        D['buildings'].append(b); continue
    if 'highway' in t:
        r={'pts':g,'cls':t['highway'],'lanes':t.get('lanes'),'surface':t.get('surface')}
        for k in ('bridge','tunnel','layer','name','oneway'):
            if t.get(k): r[k]=t[k]
        D['roads'].append(r); continue
    if 'barrier' in t: D['barriers'].append({'pts':g,'kind':t['barrier']}); continue
    if 'waterway' in t:
        w={'pts':g,'kind':t['waterway']}
        for k in ('intermittent','tunnel','layer','name'):
            if t.get(k): w[k]=t[k]
        D['water'].append(w); continue
    area=t.get('landuse') or t.get('leisure') or t.get('natural') or (t.get('amenity') if t.get('amenity')=='parking' else None)
    if area and g[0]==g[-1]:
        D['areas'].append({'pts':g[:-1],'kind':area,**({'name':t['name']} if t.get('name') else {})})
        k=poi_kind(t)
        if k: cx=sum(p[0] for p in g)/len(g); cz=sum(p[1] for p in g)/len(g); D['pois'].append({'p':[round(cx,1),round(cz,1)],'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
# terrain: 4 m grid over the block and its margin, relative to the lowest point
nx=int(2*E/STEP)+1; H=[]
for j in range(nx):
    for i in range(nx):
        la,lo=LL(-E+i*STEP,-E+j*STEP); H.append(elev(la,lo))
lo=min(H); D['terrain']={'step':STEP,'nx':nx,'nz':nx,'x0':-E,'z0':-E,'base':round(lo,1),'h':[round(h-lo,2) for h in H]}
# the landscape 5 km around, 50 m grid
cst=50; cn_=int(2*CH/cst)+1; D['context']={'half':CH,'step':cst,'n':cn_,'h':[round(elev(*LL(-CH+i*cst,-CH+j*cst),13)-lo,1) for j in range(cn_) for i in range(cn_)]}
json.dump(D,open(f'block_{NAME}.json','w'),separators=(',',':'))
print(f'block_{NAME}.json', {k:len(v) for k,v in D.items() if isinstance(v,list)}, 'grid',nx,'relief',round(max(H)-lo,1))
