# Build the region file: a realm 100 miles square around the I-17 corridor, cut into 600 m sectors.
# The corridor (the detail box) keeps everything: buildings, every road and track, 100 m terrain. The rest of the
# realm has major roads, towns, water, land use and points of interest, on 400 m terrain.
# Inputs (in this folder): reg_*.json (regionfetch.sh, the corridor), wide_*.json (widefetch.sh, the realm),
# elevation tiles t10_*.png and t13_*.png (demfetch.py). Output: region_i17.json, copied to ../../data/region/.
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen Terrain Tiles on AWS.
import json, math, glob, collections, os
from prep import elev   # zoom-aware elevation sampler from the sector pipeline

# the corridor fixes the frame: its centre is the region frame's origin (33.945 N, 112.14 W), as before
S,W,N,E = 33.80, -112.24, 34.09, -112.04
lat0=(S+N)/2; lon0=(W+E)/2; kx=111320*math.cos(math.radians(lat0)); ky=110574
P=lambda la,lo:(round((lo-lon0)*kx,1), round(-(la-lat0)*ky,1))
SEC=600
DCOLS=int(2*round((E-W)/2*kx)//SEC); DROWS=int(2*round((N-S)/2*ky)//SEC); DX=DCOLS*SEC/2; DZ=DROWS*SEC/2   # detail box (30 x 53)
MILE=1609.344; REALM=100*MILE   # the realm: 100 miles on a side, whole sectors, lined up with the detail box
OC=math.ceil((REALM/2-DX)/SEC); OR=math.ceil((REALM/2-DZ)/SEC)
COLS=DCOLS+2*OC; ROWS=DROWS+2*OR; HX=COLS*SEC/2; HZ=ROWS*SEC/2
LL=lambda x,z:(lat0-z/ky, lon0+x/kx)
in_detail=lambda x,z:abs(x)<=DX and abs(z)<=DZ
inside=lambda x,z:abs(x)<=HX and abs(z)<=HZ
sec_of=lambda x,z:(min(COLS-1,max(0,int((x+HX)//SEC))), min(ROWS-1,max(0,int((z+HZ)//SEC))))
print(f'realm {COLS} x {ROWS} sectors ({2*HX/1000:.1f} x {2*HZ/1000:.1f} km), detail box at column {OC}, row {OR}')

# Downloads overlap, and some (the sector and context files) clip way geometry to their own box, leaving nulls.
# Keep every coordinate any copy knows, per OSM node id, so a clipped copy never hides a road another file has whole.
els={}; ncoord={}; src={}
files=[(f,'detail') for f in sorted(glob.glob('reg_*.json'))]+[(f,'wide') for f in sorted(glob.glob('wide_*.json'))]+[(f,'detail') for f in ('anthem.json','newriver.json','places.json','pois.json','context.json')]
for f,kind in files:
    if not os.path.exists(f): print('missing',f); continue
    for e in json.load(open(f))['elements']:
        k=(e['type'],e['id'])
        if e['type']=='way' and e.get('nodes') and e.get('geometry'):
            for n,q in zip(e['nodes'],e['geometry']):
                if q: ncoord[n]=(q['lat'],q['lon'])
        if k in els and e['type']=='way' and len([q for q in e.get('geometry',[]) if q])<len([q for q in els[k].get('geometry',[]) if q]): continue   # keep the fuller copy's tags and centre
        els[k]=e; src[k]=kind
for (typ,_),e in els.items():   # rebuild each way's geometry from the merged node coordinates
    if typ=='way' and e.get('nodes'): e['geometry']=[{'lat':ncoord[n][0],'lon':ncoord[n][1]} if n in ncoord else None for n in e['nodes']]
print(len(els),'elements from',len(files),'files')

def simp(pts,tol):
    if len(pts)<3: return pts
    a,b=pts[0],pts[-1]; dx,dz=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dz) or 1; best=-1; bi=0
    for i in range(1,len(pts)-1):
        dd=abs((pts[i][0]-a[0])*dz-(pts[i][1]-a[1])*dx)/L
        if dd>best: best,bi=dd,i
    return simp(pts[:bi+1],tol)[:-1]+simp(pts[bi:],tol) if best>tol else [a,b]

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

ways=[]; water=[]; lakes=[]; areas=[]; places=[]; peaks=[]; sites=[]; blds=[]
PLACE={'city','town','village','hamlet','suburb'}
for (typ,_),e in els.items():
    t=e.get('tags',{})
    if typ=='node':
        p=P(e['lat'],e['lon'])
        if not inside(*p): continue
        if t.get('place') in PLACE and t.get('name'):
            places.append({'name':t['name'],'kind':t['place'],'p':p,**({'pop':int(t['population'])} if str(t.get('population','')).isdigit() else {})}); continue
        if t.get('natural')=='peak':
            if t.get('name') or in_detail(*p): peaks.append({'name':t.get('name',''),'p':p})
            continue
    g=[P(q['lat'],q['lon']) for q in e.get('geometry',[]) if q] if 'geometry' in e else []
    c=None
    if 'center' in e: c=P(e['center']['lat'],e['center']['lon'])
    elif typ=='node': c=P(e['lat'],e['lon'])
    elif g: c=(round(sum(p[0] for p in g)/len(g),1), round(sum(p[1] for p in g)/len(g),1))
    v=t.get('shop') or t.get('amenity') or t.get('man_made')
    if v and c and inside(*c) and ('shop' in t or 'amenity' in t or 'man_made' in t):
        sites.append({'name':t.get('name',''),'what':v,'loot':loot_of(v),'p':[round(c[0]),round(c[1])]})
        if 'building' not in t: continue
    if typ!='way' or not g: continue
    if 'highway' in t:   # a way with nodes nobody downloaded is split at the gap rather than dropped
        run_n=[]; run_p=[]
        def flush():
            if len(run_p)>=2 and any(inside(*p) for p in run_p): ways.append({'nodes':run_n,'pts':run_p,'cls':t['highway'],'surface':t.get('surface','')})
        for n,q in zip(e.get('nodes',[]),e.get('geometry',[])):
            if q: run_n.append(n); run_p.append(P(q['lat'],q['lon'])); continue
            flush(); run_n=[]; run_p=[]
        flush(); continue
    if 'building' in t:
        if c and in_detail(*c):
            xs=[p[0] for p in g]; zs=[p[1] for p in g]; w=max(4,min(60,max(xs)-min(xs))); d=max(4,min(60,max(zs)-min(zs)))
            blds.append([round(c[0]),round(c[1]),round(w),round(d)])
        continue
    if not any(inside(*p) for p in g): continue
    fine=all(in_detail(*p) for p in g)   # outside the detail box, coarser shapes
    if 'waterway' in t: water.append({'kind':t['waterway'],'pts':[list(map(round,p)) for p in simp(g,8 if fine else 40)]}); continue
    if t.get('natural')=='water':
        if fine or len(g)>3 and abs(sum(g[i][0]*g[i-1][1]-g[i-1][0]*g[i][1] for i in range(len(g))))/2>40000:   # small ponds only in the corridor
            lakes.append({'pts':[list(map(round,p)) for p in simp(g,6 if fine else 30)]})
        continue
    if 'landuse' in t: areas.append({'kind':t['landuse'],'pts':[list(map(round,p)) for p in simp(g,8 if fine else 40)]}); continue
print(len(ways),'road pieces',len(sites),'sites',len(blds),'buildings',len(places),'places',len(peaks),'peaks')

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
            piece=w['pts'][start:i+1]
            inner=[list(map(round,p)) for p in simp(piece,4 if in_detail(*piece[0]) else 15)[1:-1]]
            if a!=b: edges.append([a,b,round(L),w['cls'],inner])
            start=i; L=0
# join loose ends: a dead end within SNAP m of another piece of the network (a seam between downloads, a road
# mapped to stop just short of the one it meets) gets a short link, so the pieces route as one
SNAP=12
deg=collections.Counter()
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
print('graph:',len(nodes),'nodes',len(edges),'edges,',snapped,'loose ends joined,',len(sizes),'pieces, largest',sizes[:5],f'({100*sizes[0]/max(1,sum(sizes)):.0f}% of junctions)')

# drawable roads, simplified by class; the realm texture draws the major ones, the corridor texture all of them
TOL={'motorway':6,'motorway_link':4,'trunk':6,'primary':6,'secondary':5,'tertiary':5,'unclassified':5,'residential':4,'track':6}
roads=[]
for w in ways:
    fine=any(in_detail(*p) for p in w['pts'])
    pts=[list(map(round,p)) for p in simp(w['pts'],TOL.get(w['cls'],5) if fine else 20)]
    r={'cls':w['cls'],'dirt':bool(w['cls']=='track' or any(s in w['surface'] for s in ('unpaved','dirt','gravel','ground','compacted'))),'pts':pts}
    if fine: r['d']=1
    roads.append(r)

# terrain: 400 m over the realm with a 4 km apron, 100 m over the detail box with a 3 km apron; heights above one base
def grid(x0,z0,x1,z1,step,zoom):
    nx=int((x1-x0)//step)+1; nz=int((z1-z0)//step)+1
    H=[elev(*LL(x0+i*step,z0+j*step),zoom) for j in range(nz) for i in range(nx)]
    fixed=0   # the tiles have the odd spike or pit; a sample far from all its neighbours takes their median
    for j in range(nz):
        for i in range(nx):
            nb=sorted(H[b*nx+a] for a,b in ((i-1,j),(i+1,j),(i,j-1),(i,j+1)) if 0<=a<nx and 0<=b<nz); m=nb[len(nb)//2]
            if abs(H[j*nx+i]-m)>250: H[j*nx+i]=m; fixed+=1
    if fixed: print(fixed,'elevation spikes smoothed at',step,'m')
    return {'step':step,'nx':nx,'nz':nz,'x0':x0,'z0':z0},H
dem,Hw=grid(-HX-4000,-HZ-4000,HX+4000,HZ+4000,400,10)
demf,Hf=grid(-DX-3000,-DZ-3000,DX+3000,DZ+3000,100,13)
lo=min(min(Hw),min(Hf))
dem['base']=demf['base']=round(lo); dem['h']=[round(h-lo,1) for h in Hw]; demf['h']=[round(h-lo,1) for h in Hf]
def hgt(x,z):
    for d in (demf,dem):
        fx=(x-d['x0'])/d['step']; fz=(z-d['z0'])/d['step']
        if d is demf and not (0<=fx<=d['nx']-1 and 0<=fz<=d['nz']-1): continue
        nx=d['nx']; i=max(0,min(nx-2,int(fx))); j=max(0,min(d['nz']-2,int(fz))); u=min(1,max(0,fx-i)); v=min(1,max(0,fz-j)); h=lambda a,b:d['h'][b*nx+a]
        return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v

# sectors: elevation range everywhere; buildings counted in the detail box, estimated from land use and sites outside it
b=[[0]*COLS for _ in range(ROWS)]; pois=[[0]*COLS for _ in range(ROWS)]; built=[[0.0]*COLS for _ in range(ROWS)]
for x,z,_,_ in blds: c,r=sec_of(x,z); b[r][c]+=1
for i,s in enumerate(sites): c,r=sec_of(*s['p']); pois[r][c]+=1
def in_poly(x,z,pts):
    k=False; n=len(pts)
    for i in range(n):
        x1,z1=pts[i]; x2,z2=pts[i-1]
        if (z1>z)!=(z2>z) and x<(x2-x1)*(z-z1)/(z2-z1)+x1: k=not k
    return k
Q=[(a+.5)/3 for a in range(3)]
for a in areas:
    if a['kind'] not in ('residential','retail','commercial','industrial'): continue
    xs=[p[0] for p in a['pts']]; zs=[p[1] for p in a['pts']]
    c0,r0=sec_of(min(xs),min(zs)); c1,r1=sec_of(max(xs),max(zs))
    for r in range(r0,r1+1):
        for c in range(c0,c1+1):
            x0=-HX+c*SEC; z0=-HZ+r*SEC
            hit=sum(in_poly(x0+u*SEC,z0+v*SEC,a['pts']) for u in Q for v in Q)
            built[r][c]=min(1,built[r][c]+hit/9)
TYPE={'town':'t','homes':'h','rough':'r','desert':'d'}
lo_,hi_,ty_,b_=[],[],[],[]
for r in range(ROWS):
    for c in range(COLS):
        x0=-HX+c*SEC; z0=-HZ+r*SEC; hs=[hgt(x0+u*SEC/4,z0+v*SEC/4) for u in range(5) for v in range(5)]
        l=round(min(hs)+lo); h=round(max(hs)+lo)
        if in_detail(x0+SEC/2,z0+SEC/2): n=b[r][c]
        else: n=round(built[r][c]*160+pois[r][c]*3)   # about 160 homes to a fully built 600 m sector
        t='town' if n>=40 else 'homes' if n>=6 else 'rough' if h-l>40 else 'desert'
        lo_.append(l); hi_.append(h); ty_.append(TYPE[t]); b_.append(n)
for p in places: p['sector']=list(sec_of(*p['p']))
for p in peaks: p['h']=round(hgt(*p['p'])+lo)

R={'name':'Central Arizona','v':2,'center':[lat0,lon0],'half':[HX,HZ],'sector':SEC,'cols':COLS,'rows':ROWS,
   'bbox':[round(LL(0,HZ)[0],4),round(LL(-HX,0)[1],4),round(LL(0,-HZ)[0],4),round(LL(HX,0)[1],4)],
   'detail':{'name':'I-17 corridor','bbox':[S,W,N,E],'half':[DX,DZ],'col':OC,'row':OR,'cols':DCOLS,'rows':DROWS},
   'dem':dem,'demFine':demf,'roads':roads,'graph':{'nodes':nodes,'edges':edges},'water':water,'lakes':lakes,'areas':areas,
   'home':list(P(33.9159,-112.1360)),'places':places,'peaks':peaks,'sites':sites,'buildings':blds,
   'sectors':{'lo':lo_,'hi':hi_,'type':''.join(ty_),'b':b_}}
json.dump(R,open('region_i17.json','w'),separators=(',',':'))
cnt=collections.Counter(ty_)
print('wrote region_i17.json',os.path.getsize('region_i17.json')//1024,'KB | sectors',dict(cnt),'| relief',round(lo),round(max(Hw)))
