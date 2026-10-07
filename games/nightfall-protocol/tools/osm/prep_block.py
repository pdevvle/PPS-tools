# Extract a block of sectors from OSM downloads: features in frame metres and a 4 m height grid.
#   python3 prep_block.py [name nx nz cx cz]   e.g. prep_block.py corridor 5 10 0 -1500
# The frame is always centred on the New River sector (so every block shares one coordinate system); the block is
# nx by nz sectors of 600 m centred on (cx,cz) in that frame. The block is shaped and cut into sectors by bake.js,
# so neighbouring sectors share their edges exactly. Inputs: raw/cor_*.json (corridorfetch.sh), and the older
# reg_*.json / newriver.json / anthem.json downloads when present. Elevation tiles are fetched into raw/.
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
import json, math, glob, os, subprocess, sys
here=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,here)
from prep import elev

a=sys.argv[1:]
NAME=a[0] if a else 'newriver'; NX=int(a[1]) if len(a)>1 else 5; NZ=int(a[2]) if len(a)>2 else 5; CXB=float(a[3]) if len(a)>3 else 0.; CZB=float(a[4]) if len(a)>4 else 0.
LAT0, LON0 = 33.9180, -112.13855      # the frame: the New River sector's centre
SEC=600; MARGIN=120; STEP=4
X0=CXB-NX*SEC/2; Z0=CZB-NZ*SEC/2; X1=X0+NX*SEC; Z1=Z0+NZ*SEC
kx=111320*math.cos(math.radians(LAT0)); ky=110574
P=lambda la,lo:[round((lo-LON0)*kx,1), round(-(la-LAT0)*ky,1)]
LL=lambda x,z:(LAT0-z/ky, LON0+x/kx)
os.chdir(os.path.join(here,'raw')) if os.path.isdir(os.path.join(here,'raw')) else os.chdir(here)

# elevation tiles at zoom 15 for the block, zoom 13 for the landscape 5 km round it
def need(Z,s,w,n,e):
    t=2**Z; tx=lambda lo:int((lo+180)/360*t); ty=lambda la:int((1-math.log(math.tan(math.radians(la))+1/math.cos(math.radians(la)))/math.pi)/2*t)
    return [(x,y) for x in range(tx(w),tx(e)+1) for y in range(ty(n),ty(s)+1)]
CH=max(X1-X0,Z1-Z0)/2+5000; CCX=(X0+X1)/2; CCZ=(Z0+Z1)/2
for Z,(x0,z0,x1,z1) in ((15,(X0-MARGIN-50,Z0-MARGIN-50,X1+MARGIN+50,Z1+MARGIN+50)),(13,(CCX-CH-100,CCZ-CH-100,CCX+CH+100,CCZ+CH+100))):
    s,w=LL(x0,z1); n,e=LL(x1,z0)
    for x,y in need(Z,s,w,n,e):
        f=f't{Z}_{x}_{y}.png'
        if not os.path.exists(f): subprocess.run(['curl','-sS','-m','40','-o',f,f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{Z}/{x}/{y}.png'],check=True)

els={}
for f in sorted(glob.glob('cor_*.json'))+sorted(glob.glob('reg_*.json'))+['newriver.json','anthem.json','pois.json','context.json']:
    if not os.path.exists(f): continue
    for e in json.load(open(f))['elements']: els[(e['type'],e['id'])]=e
inside=lambda p,m=0:X0-MARGIN-m<=p[0]<=X1+MARGIN+m and Z0-MARGIN-m<=p[1]<=Z1+MARGIN+m
D={'name':NAME,'center':[LAT0,LON0],'sector':SEC,'nx':NX,'nz':NZ,'x0':X0,'z0':Z0,'n':NX,'half':NX*SEC/2,'margin':MARGIN,'buildings':[],'roads':[],'barriers':[],'areas':[],'water':[],'pois':[],'trees':[]}
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
    if typ=='relation':
        for m in el.get('members',[]):
            if m.get('role')=='outer' and m.get('geometry'):
                g=[P(q['lat'],q['lon']) for q in m['geometry'] if q]
                if len(g)>=4 and g[0]==g[-1] and any(inside(p,400) for p in g): D['areas'].append({'pts':g[:-1],'kind':'water'})
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
        if t.get('area')=='yes' or t['highway'] in ('proposed','construction','platform'): continue
        r={'pts':g,'cls':t['highway'],'lanes':t.get('lanes'),'surface':t.get('surface')}
        for k in ('bridge','tunnel','layer','name','oneway'):
            if t.get(k): r[k]=t[k]
        D['roads'].append(r); continue
    if 'barrier' in t: D['barriers'].append({'pts':g,'kind':t['barrier']}); continue
    if 'waterway' in t:
        if t['waterway'] not in ('river','stream','canal','ditch','drain'): continue
        w={'pts':g,'kind':t['waterway'] if t['waterway'] in ('river','stream') else 'stream'}
        for k in ('intermittent','tunnel','layer','name'):
            if t.get(k): w[k]=t[k]
        D['water'].append(w); continue
    area=t.get('landuse') or t.get('leisure') or t.get('natural') or (t.get('amenity') if t.get('amenity')=='parking' else None)
    if area and g[0]==g[-1]:
        D['areas'].append({'pts':g[:-1],'kind':area,**({'name':t['name']} if t.get('name') else {})})
        k=poi_kind(t)
        if k: cx=sum(p[0] for p in g)/len(g); cz=sum(p[1] for p in g)/len(g); D['pois'].append({'p':[round(cx,1),round(cz,1)],'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
# terrain: 4 m grid over the block and its margin, relative to the lowest point
gx=int((X1-X0+2*MARGIN)/STEP)+1; gz=int((Z1-Z0+2*MARGIN)/STEP)+1; H=[]
for j in range(gz):
    for i in range(gx):
        la,lo=LL(X0-MARGIN+i*STEP,Z0-MARGIN+j*STEP); H.append(elev(la,lo))
lo=min(H); D['terrain']={'step':STEP,'nx':gx,'nz':gz,'x0':X0-MARGIN,'z0':Z0-MARGIN,'base':round(lo,1),'h':[round(h-lo,2) for h in H]}
# the landscape round it, 50 m grid, centred on the block
cst=50; cn_=int(2*CH/cst)+1; D['context']={'cx':CCX,'cz':CCZ,'half':CH,'step':cst,'n':cn_,'h':[round(elev(*LL(CCX-CH+i*cst,CCZ-CH+j*cst),13)-lo,1) for j in range(cn_) for i in range(cn_)]}
out=os.path.join(here,f'block_{NAME}.json'); json.dump(D,open(out,'w'),separators=(',',':'))
print(out, {k:len(v) for k,v in D.items() if isinstance(v,list)}, 'grid',gx,gz,'relief',round(max(H)-lo,1))
