# Turn an Overpass JSON dump + Terrarium elevation tiles into a compact game sector (local metres).
# Map data (c) OpenStreetMap contributors, ODbL. Elevation: Mapzen/AWS Terrain Tiles.
import json, math, zlib, struct, sys

def png_rgb(path):
    data=open(path,'rb').read(); pos=8; chunks=[]; w=h=0; ct=bd=0
    while pos<len(data):
        ln=struct.unpack('>I',data[pos:pos+4])[0]; typ=data[pos+4:pos+8]; body=data[pos+8:pos+8+ln]; pos+=12+ln
        if typ==b'IHDR': w,h,bd,ct=struct.unpack('>IIBB',body[:10])
        elif typ==b'IDAT': chunks.append(body)
        elif typ==b'IEND': break
    raw=zlib.decompress(b''.join(chunks)); bpp={2:3,6:4}[ct]; stride=w*bpp
    out=bytearray(h*stride); prev=bytearray(stride); i=0
    for y in range(h):
        f=raw[i]; i+=1; line=bytearray(raw[i:i+stride]); i+=stride
        for x in range(stride):
            a=line[x-bpp] if x>=bpp else 0; b=prev[x]; c=prev[x-bpp] if x>=bpp else 0
            if f==1: line[x]=(line[x]+a)&255
            elif f==2: line[x]=(line[x]+b)&255
            elif f==3: line[x]=(line[x]+(a+b)//2)&255
            elif f==4:
                p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                line[x]=(line[x]+(a if pa<=pb and pa<=pc else b if pb<=pc else c))&255
        out[y*stride:(y+1)*stride]=line; prev=line
    return w,h,bpp,out

tiles={}
def elev(lat,lon,Z=15):
    n=2**Z; fx=(lon+180)/360*n; fy=(1-math.log(math.tan(math.radians(lat))+1/math.cos(math.radians(lat)))/math.pi)/2*n
    x,y=int(fx),int(fy)
    if (Z,x,y) not in tiles: tiles[(Z,x,y)]=png_rgb(f't{Z}_{x}_{y}.png')
    w,h,bpp,px=tiles[(Z,x,y)]; u=(fx-x)*256; v=(fy-y)*256
    def at(i,j):
        i=min(255,max(0,i)); j=min(255,max(0,j)); o=(j*256+i)*bpp; r,g,b=px[o],px[o+1],px[o+2]; return r*256+g+b/256-32768
    i,j=int(u-.5),int(v-.5); tx,ty=u-.5-i,v-.5-j
    return (at(i,j)*(1-tx)+at(i+1,j)*tx)*(1-ty)+(at(i,j+1)*(1-tx)+at(i+1,j+1)*tx)*ty

def build(src,bbox,name,out):
    s,w,n,e=bbox; lat0=(s+n)/2; lon0=(w+e)/2; kx=111320*math.cos(math.radians(lat0)); ky=110574
    P=lambda la,lo:[round((lo-lon0)*kx,1),round(-(la-lat0)*ky,1)]
    half=[round((e-w)/2*kx,1),round((n-s)/2*ky,1)]
    d=json.load(open(src)); S={'name':name,'center':[lat0,lon0],'half':half,'buildings':[],'roads':[],'barriers':[],'areas':[],'water':[],'pois':[],'trees':[]}
    def geom(el): return [P(g['lat'],g['lon']) for g in el.get('geometry',[]) if g]
    def poi_kind(t):
        v=t.get('shop') or t.get('amenity')
        if not v: return None
        food={'supermarket','convenience','restaurant','fast_food','cafe','ice_cream','bakery','greengrocer'}
        med={'pharmacy','dentist','doctors','clinic','hospital','veterinary'}
        tools={'doityourself','hardware','car_repair','swimming_pool','garden_centre','trade'}
        if v in food: return 'food'
        if v in med: return 'medicine'
        if v in tools: return 'tools'
        if v=='fuel': return 'fuel'
        if v in {'fire_station','police'}: return 'gear'
        if v in {'bank','post_office','jewelry','dry_cleaning','hairdresser','school','place_of_worship','community_centre','library'}: return 'shelter'
        return None
    for el in d['elements']:
        t=el.get('tags',{}); g=geom(el) if el['type']=='way' else None
        if el['type']=='node':
            p=P(el['lat'],el['lon'])
            if t.get('natural')=='tree': S['trees'].append(p); continue
            k=poi_kind(t)
            if k and t.get('amenity') not in ('waste_disposal','charging_station','fountain','shelter','bench','parking_entrance'): S['pois'].append({'p':p,'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
            continue
        if not g or len(g)<2: continue
        if 'building' in t:
            lv=t.get('building:levels'); ht=t.get('height')
            b={'pts':g[:-1] if g[0]==g[-1] else g,'type':t['building']}
            if lv: b['levels']=float(lv.split(';')[0])
            if ht: 
                try: b['height']=float(ht.split()[0])
                except: pass
            if t.get('name'): b['name']=t['name']
            k=poi_kind(t)
            if k: b['loot']=k; b['what']=t.get('shop') or t.get('amenity')
            S['buildings'].append(b); continue
        if 'highway' in t:
            S['roads'].append({'pts':g,'cls':t['highway'],'lanes':t.get('lanes'),'surface':t.get('surface')}); continue
        if 'barrier' in t: S['barriers'].append({'pts':g,'kind':t['barrier']}); continue
        if 'waterway' in t: S['water'].append({'pts':g,'kind':t['waterway']}); continue
        area=t.get('landuse') or t.get('leisure') or t.get('natural') or (t.get('amenity') if t.get('amenity') in ('parking',) else None)
        if area and g[0]==g[-1]:
            S['areas'].append({'pts':g[:-1],'kind':area})
            k=poi_kind(t)
            if k: 
                cx=sum(p[0] for p in g)/len(g); cz=sum(p[1] for p in g)/len(g); S['pois'].append({'p':[round(cx,1),round(cz,1)],'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
            continue
        k=poi_kind(t)
        if k:
            cx=sum(p[0] for p in g)/len(g); cz=sum(p[1] for p in g)/len(g); S['pois'].append({'p':[round(cx,1),round(cz,1)],'kind':k,'what':t.get('shop') or t.get('amenity'),'name':t.get('name','')})
    # terrain: heights on a 4 m grid (zoom-15 elevation is ~4 m per pixel here), relative to the sector's lowest point
    step=4; nx=int(2*half[0]/step)+1; nz=int(2*half[1]/step)+1; H=[]
    for j in range(nz):
        for i in range(nx):
            x=-half[0]+i*step; z=-half[1]+j*step
            H.append(elev(lat0-z/ky, lon0+x/kx))
    lo=min(H); S['terrain']={'step':step,'nx':nx,'nz':nz,'base':round(lo,1),'h':[round(h-lo,2) for h in H]}
    # context: the landscape 4 km around the sector (50 m grid, zoom-13 elevation) with major roads, towns and water
    CH=4000; cstep=50; cn=int(2*CH/cstep)+1; CHh=[]
    for j in range(cn):
        for i in range(cn):
            x=-CH+i*cstep; z=-CH+j*cstep; CHh.append(round(elev(lat0-z/ky, lon0+x/kx, 13)-lo,1))
    C={'half':CH,'step':cstep,'n':cn,'h':CHh,'roads':[],'areas':[],'water':[]}
    def simp(pts,tol=6):
        if len(pts)<3: return pts
        a,b=pts[0],pts[-1]; dx,dz=b[0]-a[0],b[1]-a[1]; L=math.hypot(dx,dz) or 1; best=-1; bi=0
        for i in range(1,len(pts)-1):
            dd=abs((pts[i][0]-a[0])*dz-(pts[i][1]-a[1])*dx)/L
            if dd>best: best,bi=dd,i
        return simp(pts[:bi+1],tol)[:-1]+simp(pts[bi:],tol) if best>tol else [a,b]
    for el in json.load(open('context.json'))['elements']:
        t=el.get('tags',{}); g=[P(q['lat'],q['lon']) for q in el.get('geometry',[]) if q]
        if not g or not any(abs(x)<CH and abs(z)<CH for x,z in g): continue
        g=[[round(x),round(z)] for x,z in simp(g)]
        if 'highway' in t: C['roads'].append({'pts':g,'cls':t['highway']})
        elif 'waterway' in t: C['water'].append({'pts':g})
        else: C['areas'].append({'pts':g,'kind':t.get('landuse') or t.get('leisure') or t.get('natural')})
    S['context']=C
    json.dump(S,open(out,'w'),separators=(',',':'))
    print(out, len(S['buildings']),'bld',len(S['roads']),'roads',len(S['pois']),'pois',len(S['areas']),'areas','relief',round(max(H)-lo,1),'m')

build('anthem.json',(33.8628,-112.14,33.8682,-112.1335),'Anthem town centre','sector_anthem.json')
build('newriver.json',(33.9153,-112.1418,33.9207,-112.1353),'New River','sector_newriver.json')
