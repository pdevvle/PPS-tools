# Build the pilot region file: 600 m sector grid, sites, a travel graph from real roads, terrain and scenery.
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
import json, math, glob, collections, os
from prep import elev   # zoom-aware elevation sampler from the sector pipeline

S,W,N,E = 33.80, -112.24, 34.09, -112.04
lat0=(S+N)/2; lon0=(W+E)/2; kx=111320*math.cos(math.radians(lat0)); ky=110574
P=lambda la,lo:(round((lo-lon0)*kx,1), round(-(la-lat0)*ky,1))
HX=round((E-W)/2*kx); HZ=round((N-S)/2*ky); SEC=600
COLS=int(2*HX//SEC); ROWS=int(2*HZ//SEC); HX=COLS*SEC/2; HZ=ROWS*SEC/2

# Downloads overlap, and some (the sector and context files) clip way geometry to their own box, leaving nulls.
# Keep every coordinate any copy knows, per OSM node id, so a clipped copy never hides a road another file has whole.
els={}; ncoord={}
for f in sorted(glob.glob('reg_*.json'))+['anthem.json','newriver.json','places.json','pois.json','context.json']:   # earlier sector downloads fill gaps
    if not os.path.exists(f): print('missing',f); continue
    for e in json.load(open(f))['elements']:
        k=(e['type'],e['id'])
        if e['type']=='way' and e.get('nodes') and e.get('geometry'):
            for n,q in zip(e['nodes'],e['geometry']):
                if q: ncoord[n]=(q['lat'],q['lon'])
        if k in els and e['type']=='way' and len([q for q in e.get('geometry',[]) if q])<len([q for q in els[k].get('geometry',[]) if q]): continue   # keep the fuller copy's tags and centre
        els[k]=e
for (typ,_),e in els.items():   # rebuild each way's geometry from the merged node coordinates
    if typ=='way' and e.get('nodes'): e['geometry']=[{'lat':ncoord[n][0],'lon':ncoord[n][1]} if n in ncoord else None for n in e['nodes']]
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
    if 'highway' in t:   # a way with nodes nobody downloaded is split at the gap rather than dropped
        run_n=[]; run_p=[]
        for n,q in zip(e.get('nodes',[]),e.get('geometry',[])):
            if q: run_n.append(n); run_p.append(P(q['lat'],q['lon'])); continue
            if len(run_p)>=2: ways.append({'nodes':run_n,'pts':run_p,'cls':t['highway'],'surface':t.get('surface','')})
            run_n=[]; run_p=[]
        if len(run_p)>=2: ways.append({'nodes':run_n,'pts':run_p,'cls':t['highway'],'surface':t.get('surface','')})
        continue
    if 'building' in t:
        if inside(*c):
            xs=[p[0] for p in g]; zs=[p[1] for p in g]; w=max(4,min(60,max(xs)-min(xs))); d=max(4,min(60,max(zs)-min(zs)))
            blds.append([round(c[0]),round(c[1]),round(w),round(d)])
        continue
    if 'waterway' in t: water.append({'kind':t['waterway'],'pts':[list(map(round,p)) for p in simp(g,8)]}); continue
    if t.get('natural')=='water': lakes.append({'pts':[list(map(round,p)) for p in simp(g,6)]}); continue
    if 'landuse' in t: areas.append({'kind':t['landuse'],'pts':[list(map(round,p)) for p in simp(g,8)]}); continue

# travel graph: split ways at shared OSM nodes; edge = (a, b, length m, class, [inner points along the road, a to b])
use=collections.Counter()
for w in ways:
    for i,n in enumerate(w['nodes']): use[n]+= 2 if i in (0,len(w['nodes'])-1) else 1
nid={}; nodes=[]; edges=[]
def node(osm,p):
    if osm not in nid: nid[osm]=len(nodes); nodes.append([round(p[0]),round(p[1])])
    return nid[osm]
for w in ways:
    start=0; L=0
    for i in range(1,len(w['pts'])):
        L+=math.dist(w['pts'][i-1],w['pts'][i])
        if use[w['nodes'][i]]>1 or i==len(w['pts'])-1:
            a=node(w['nodes'][start],w['pts'][start]); b=node(w['nodes'][i],w['pts'][i])
            inner=[list(map(round,p)) for p in simp(w['pts'][start:i+1],4)[1:-1]]
            if a!=b: edges.append([a,b,round(L),w['cls'],inner])
            start=i; L=0
# join loose ends: a dead end within SNAP m of another piece of the network (a seam between downloads, a road
# mapped to stop just short of the one it meets) gets a short link, so the pieces route as one
SNAP=12
deg=collections.Counter(); 
for e in edges: deg[e[0]]+=1; deg[e[1]]+=1
parent=list(range(len(nodes)))
def find(i):
    while parent[i]!=i: parent[i]=parent[parent[i]]; i=parent[i]
    return i
for e in edges: parent[find(e[0])]=find(e[1])
grid=collections.defaultdict(list)
for i,(x,z) in enumerate(nodes):
    if deg[i]: grid[(int(x//SNAP),int(z//SNAP))].append(i)
snapped=0
for i,(x,z) in enumerate(nodes):
    if deg[i]!=1: continue
    best=None; bd=SNAP
    for gx in range(int(x//SNAP)-1,int(x//SNAP)+2):
        for gz in range(int(z//SNAP)-1,int(z//SNAP)+2):
            for j in grid[(gx,gz)]:
                if find(j)==find(i): continue
                d=math.dist(nodes[i],nodes[j])
                if d<bd: bd=d; best=j
    if best is not None:
        edges.append([i,best,max(1,round(bd)),'link',[]]); parent[find(i)]=find(best); snapped+=1
comp=collections.Counter(find(i) for i in range(len(nodes)) if deg[i])
sizes=sorted(comp.values(),reverse=True)
print('graph:',len(nodes),'nodes',len(edges),'edges,',snapped,'loose ends joined,',len(sizes),'pieces, largest',sizes[:5],f'({100*sizes[0]/sum(sizes):.0f}% of junctions)')
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
