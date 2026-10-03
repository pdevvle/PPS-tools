# Build the pilot region file: 600 m sector grid, sites, a travel graph from real roads, terrain and scenery.
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
import json, math, glob, collections
from prep import elev   # zoom-aware elevation sampler from the sector pipeline

S,W,N,E = 33.80, -112.24, 34.09, -112.04
lat0=(S+N)/2; lon0=(W+E)/2; kx=111320*math.cos(math.radians(lat0)); ky=110574
P=lambda la,lo:(round((lo-lon0)*kx,1), round(-(la-lat0)*ky,1))
HX=round((E-W)/2*kx); HZ=round((N-S)/2*ky); SEC=600
COLS=int(2*HX//SEC); ROWS=int(2*HZ//SEC); HX=COLS*SEC/2; HZ=ROWS*SEC/2

els={}
for f in sorted(glob.glob('reg_*.json'))+['anthem.json','newriver.json','places.json','pois.json','context.json']:   # earlier sector downloads fill gaps
    for e in json.load(open(f))['elements']: els[(e['type'],e['id'])]=e
print(len(els),'elements')

def simp(pts,tol):
    if len(pts)<3: return pts
    a,b=pts[0],pts[-1]; dx,dz=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dz) or 1; best=-1; bi=0
    for i in range(1,len(pts)-1):
        dd=abs((pts[i][0]-a[0])*dz-(pts[i][1]-a[1])*dx)/L
        if dd>best: best,bi=dd,i
    return simp(pts[:bi+1],tol)[:-1]+simp(pts[bi:],tol) if best>tol else [a,b]
inside=lambda x,z:abs(x)<=HX and abs(z)<=HZ
sec_of=lambda x,z:(min(COLS-1,max(0,int((x+HX)//SEC))), min(ROWS-1,max(0,int((z+HZ)//SEC))))

LOOT={'food':{'supermarket','convenience','restaurant','fast_food','cafe','bakery','greengrocer','farm','butcher'},
      'medicine':{'pharmacy','dentist','doctors','clinic','hospital','veterinary','chemist'},
      'tools':{'doityourself','hardware','car_repair','garden_centre','trade','agrarian','car_parts','farm_supply'},
      'fuel':{'fuel'}, 'gear':{'fire_station','police','outdoor','sports','hunting','weapons'},
      'water':{'water_well','water_tower','storage_tank'},
      'shelter':{'school','place_of_worship','community_centre','library'}}
def loot_of(v):
    for k,s in LOOT.items():
        if v in s: return k
    return 'goods'

roads=[]; ways=[]; water=[]; lakes=[]; areas=[]; places=[]; peaks=[]; sites=[]; blds=[]
for (typ,_),e in els.items():
    t=e.get('tags',{})
    if typ=='node':
        p=P(e['lat'],e['lon'])
        if not inside(*p): continue
        if 'place' in t and t.get('name'): places.append({'name':t['name'],'kind':t['place'],'p':p}); continue
        if t.get('natural')=='peak': peaks.append({'name':t.get('name',''),'ele':t.get('ele'),'p':p}); continue
    g=[P(q['lat'],q['lon']) for q in e.get('geometry',[]) if q] if 'geometry' in e else []
    c=None
    if 'center' in e: c=P(e['center']['lat'],e['center']['lon'])
    elif typ=='node': c=P(e['lat'],e['lon'])
    elif g: c=(round(sum(p[0] for p in g)/len(g),1), round(sum(p[1] for p in g)/len(g),1))
    v=t.get('shop') or t.get('amenity') or t.get('man_made')
    if v and c and inside(*c) and ('shop' in t or 'amenity' in t or 'man_made' in t):
        sites.append({'name':t.get('name',''),'what':v,'loot':loot_of(v),'p':c});
        if 'building' not in t: continue
    if typ!='way' or not g: continue
    if 'highway' in t:
        ways.append({'nodes':e.get('nodes',[]),'pts':g,'cls':t['highway'],'surface':t.get('surface','')}); continue
    if 'building' in t:
        if inside(*c):
            xs=[p[0] for p in g]; zs=[p[1] for p in g]; w=max(4,min(60,max(xs)-min(xs))); d=max(4,min(60,max(zs)-min(zs)))
            blds.append([round(c[0]),round(c[1]),round(w),round(d)])
        continue
    if 'waterway' in t: water.append({'kind':t['waterway'],'pts':[list(map(round,p)) for p in simp(g,8)]}); continue
    if t.get('natural')=='water': lakes.append({'pts':[list(map(round,p)) for p in simp(g,6)]}); continue
    if 'landuse' in t: areas.append({'kind':t['landuse'],'pts':[list(map(round,p)) for p in simp(g,8)]}); continue

# travel graph: split ways at shared OSM nodes; edge = (a, b, length m, class)
use=collections.Counter()
for w in ways:
    for i,n in enumerate(w['nodes']): use[n]+= 2 if i in (0,len(w['nodes'])-1) else 1
nid={}; nodes=[]; edges=[]
def node(osm,p):
    if osm not in nid: nid[osm]=len(nodes); nodes.append([round(p[0]),round(p[1])])
    return nid[osm]
for w in ways:
    if len(w['nodes'])!=len(w['pts']) or len(w['pts'])<2: continue
    start=0; L=0
    for i in range(1,len(w['pts'])):
        L+=math.dist(w['pts'][i-1],w['pts'][i])
        if use[w['nodes'][i]]>1 or i==len(w['pts'])-1:
            a=node(w['nodes'][start],w['pts'][start]); b=node(w['nodes'][i],w['pts'][i])
            if a!=b: edges.append([a,b,round(L),w['cls']])
            start=i; L=0
# drawable roads, simplified by class
TOL={'motorway':6,'motorway_link':4,'trunk':6,'primary':6,'secondary':5,'tertiary':5,'unclassified':5,'residential':4,'track':6}
for w in ways:
    pts=[list(map(round,p)) for p in simp(w['pts'],TOL.get(w['cls'],5))]
    roads.append({'cls':w['cls'],'dirt':bool(w['cls']=='track' or any(s in w['surface'] for s in ('unpaved','dirt','gravel','ground','compacted'))),'pts':pts})

# terrain: 100 m grid over the region plus a 3 km apron of real land around it
STEP=100; AP=3000; nx=int((2*HX+2*AP)//STEP)+1; nz=int((2*HZ+2*AP)//STEP)+1; H=[]
for j in range(nz):
    for i in range(nx):
        x=-HX-AP+i*STEP; z=-HZ-AP+j*STEP
        H.append(elev(lat0-z/ky, lon0+x/kx, 13))
lo=min(H)
dem={'step':STEP,'nx':nx,'nz':nz,'x0':-HX-AP,'z0':-HZ-AP,'base':round(lo),'h':[round(h-lo,1) for h in H]}
def hgt(x,z):
    fx=(x-dem['x0'])/STEP; fz=(z-dem['z0'])/STEP; i=max(0,min(nx-2,int(fx))); j=max(0,min(nz-2,int(fz))); u=fx-i; v=fz-j; h=lambda a,b:dem['h'][b*nx+a]
    return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v

# sectors
secs=[[{'b':0,'sites':[],'res':0} for _ in range(COLS)] for _ in range(ROWS)]
for b in blds: c,r=sec_of(b[0],b[1]); secs[r][c]['b']+=1
for i,s in enumerate(sites): c,r=sec_of(*s['p']); secs[r][c]['sites'].append(i); s['sector']=[c,r]
for r in range(ROWS):
    for c in range(COLS):
        x0=-HX+c*SEC; z0=-HZ+r*SEC; hs=[hgt(x0+a*SEC/4,z0+b*SEC/4) for a in range(5) for b in range(5)]
        s=secs[r][c]; s['lo']=round(min(hs)+lo); s['hi']=round(max(hs)+lo)
        s['type']='town' if s['b']>=40 else 'homes' if s['b']>=6 else 'rough' if s['hi']-s['lo']>40 else 'desert'
for p in places: p['sector']=list(sec_of(*p['p']))
for p in peaks: p['h']=round(hgt(*p['p'])+lo)

R={'name':'I-17 corridor','bbox':[S,W,N,E],'center':[lat0,lon0],'half':[HX,HZ],'sector':SEC,'cols':COLS,'rows':ROWS,
   'dem':dem,'roads':roads,'graph':{'nodes':nodes,'edges':edges},'water':water,'lakes':lakes,'areas':areas,
   'home':list(P(33.9159,-112.1360)),'places':places,'peaks':peaks,'sites':sites,'buildings':blds,
   'sectors':[[{k:v for k,v in s.items()} for s in row] for row in secs]}
json.dump(R,open('region_i17.json','w'),separators=(',',':'))
cnt=collections.Counter(s['type'] for row in secs for s in row)
print('grid',COLS,'x',ROWS,'| roads',len(roads),'| graph',len(nodes),'nodes',len(edges),'edges | sites',len(sites),'| buildings',len(blds),'| places',[p['name'] for p in places if p['kind'] in ('town','village','hamlet')],'| peaks',len(peaks),'| sectors',dict(cnt),'| relief',lo,max(H))
