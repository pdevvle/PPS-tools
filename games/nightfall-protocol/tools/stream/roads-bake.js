// Road pass over a baked block: node roads-bake.js <block dir> <osm roads json>
// Reads the full OSM road download for the block (tools/osm/roadfetch.sh) and adds to each sector file:
//  - per road piece: OSM way id, lanes, speed limit, turn lanes, what it is made of (surf)
//  - the driveways, tracks and paths the region download left out, painted into the movement grid
//  - rk: junctions, stop and yield signs, inferred traffic signals, stop bars, crosswalks, turn arrows,
//    speed limit, exit, guide and route signs, the freeway's cable median barrier, gates and cattle guards
// It records what it changed (rk.undo) so it can be rerun over its own output.
// Map data (c) OpenStreetMap contributors, ODbL.
const fs=require('fs'), zlib=require('zlib'), C=require('./sector-core.js');
const [dir,osmFile]=process.argv.slice(2);
const IDX=JSON.parse(fs.readFileSync(`${dir}/index.json`,'utf8')), SEC=IDX.sector, NB=IDX.n, HALF=IDX.half, NS=IDX.navStep, NK=C.NAVKIND;
const [LAT0,LON0]=IDX.center, kx=111320*Math.cos(LAT0*Math.PI/180), ky=110574, r1=v=>Math.round(v*10)/10, r2=v=>Math.round(v*100)/100;
const P=(la,lo)=>[r1((lo-LON0)*kx),r1(-(la-LAT0)*ky)];
const S=[]; for(let r=0;r<NB;r++) for(let c=0;c<NB;c++) S.push(JSON.parse(fs.readFileSync(`${dir}/s_${c}_${r}.json`,'utf8')));
const secAt=(x,z)=>{ const c=Math.floor((x+HALF)/SEC), r=Math.floor((z+HALF)/SEC); return c>=0&&r>=0&&c<NB&&r<NB?S[r*NB+c]:null; };
const unb64=(s,T)=>{ const b=Buffer.from(s,'base64'); return new T(b.buffer,b.byteOffset,b.byteLength/T.BYTES_PER_ELEMENT); };
const b64=a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength).toString('base64');
const hash=n=>{ let x=(n*2654435761)>>>0; x^=x>>>15; x=Math.imul(x,2246822519)>>>0; x^=x>>>13; return (x>>>0)/4294967296; };

// ---------- undo an earlier pass ----------
for(const s of S){ s.kindA=unb64(s.nav.kind,Uint8Array).slice(); s.spA=unb64(s.nav.sp,Uint8Array).slice();
  if(s.rk){ const u=s.rk.undo; for(let i=0;i<u.nav.length;i+=3){ s.kindA[u.nav[i]]=u.nav[i+1]; s.spA[u.nav[i]]=u.nav[i+2]; } s.plants.push(...u.plants); s.roads=s.roads.filter(r=>!r.added); for(const r of s.roads){ if('pv0' in r) r.paved=r.pv0; for(const k of ['id','lanes','lf','lb','ms','turn','surf','ref','pv0']) delete r[k]; } delete s.rk; }
  s.undoNav=new Map(); s.undoPlants=[]; s.rk={junctions:[],signs:[],signals:[],bars:[],walks:[],arrows:[],medians:[],gates:[],grids:[]}; }

// ---------- the OSM roads ----------
const els=JSON.parse(fs.readFileSync(osmFile,'utf8')).elements, nodes=new Map();
for(const e of els) if(e.type==='node') nodes.set(e.id,{...e,p:P(e.lat,e.lon)});
const RANK={motorway:7,trunk:6,primary:6,secondary:5,tertiary:4,motorway_link:4,trunk_link:4,primary_link:4,secondary_link:4,tertiary_link:3,unclassified:3,residential:3,living_street:2,service:1,track:1};
const MPH={motorway:75,motorway_link:45,trunk:65,primary:55,secondary:45,tertiary:35,unclassified:35,residential:25,track:15,service:15};
const WAYW={driveway:3.2,parking_aisle:6,alley:4};
const ways=[];
for(const e of els){ if(e.type!=='way'||!e.geometry) continue; const t=e.tags||{}, cls=t.highway; if(!cls||/proposed|construction|platform|corridor|elevator/.test(cls)||t.area==='yes') continue;
  let pts=e.geometry.map(g=>P(g.lat,g.lon)), nd=e.nodes.slice(), oneway=['yes','1','true'].includes(t.oneway)||t.junction==='roundabout'?1:t.oneway==='-1'?-1:0;
  if(oneway===-1){ pts.reverse(); nd.reverse(); oneway=1; }
  const lanes=+t.lanes||0, w={id:e.id,t,cls,pts,nodes:nd,oneway,rank:RANK[cls]??-1,name:t.name||'',ref:t.ref||'',lanes,
    lf:+t['lanes:forward']||(oneway?lanes:0)||0, lb:+t['lanes:backward']||0, ms:parseInt(t.maxspeed)||0, turn:t['turn:lanes']||t['turn:lanes:forward']||'', turnB:t['turn:lanes:backward']||''};
  if(!w.lf&&!oneway&&lanes>=2){ w.lf=Math.ceil(lanes/2); w.lb=Math.floor(lanes/2); }
  w.drive=C.isDrive({cls}); w.w=t.service&&WAYW[t.service]||(cls==='track'?3.5:C.roadW({cls}));
  // what it is made of; untagged driveways in rural New River are mostly gravel or dirt
  let surf=C.roadSurf({cls,surface:t.surface});
  if(!t.surface){ if(cls==='service'&&t.service!=='parking_aisle'){ const h=hash(e.id); surf=h<.5?'gravel':h<.8?'dirt':'asphalt'; } else if(cls==='track'&&/grade1|grade2/.test(t.tracktype||'')) surf='gravel'; else if(/path|footway|bridleway/.test(cls)) surf='dirt'; }
  w.surf=surf; w.paved=surf==='asphalt'||surf==='concrete';
  w.L=[0]; for(let i=1;i<pts.length;i++) w.L.push(w.L[i-1]+Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])); w.len=w.L[w.L.length-1];
  ways.push(w); }
const sec=w=>C.roadSection({cls:w.cls,w:w.w,oneway:w.oneway?'yes':'',lf:w.lf,lb:w.lb,lanes:w.lanes,surf:w.surf});
for(const w of ways) w.sec=sec(w);
// position and direction along a way at arc length s
function along(w,s){ s=Math.max(0,Math.min(w.len,s)); let k=0; while(k<w.pts.length-2&&w.L[k+1]<s) k++; const a=w.pts[k], b=w.pts[k+1], l=(w.L[k+1]-w.L[k])||1, t=(s-w.L[k])/l;
  return {x:a[0]+(b[0]-a[0])*t,z:a[1]+(b[1]-a[1])*t,tx:(b[0]-a[0])/l,tz:(b[1]-a[1])/l}; }
const yawTo=(x,z)=>Math.atan2(x,z);   // a sign whose face points along (x,z)

// ---------- match the baked road pieces to OSM ways ----------
const GI=new C.SegIndex(16); for(const w of ways) for(let k=1;k<w.pts.length;k++) GI.add(w.pts[k-1],w.pts[k],w,1);
function wayOf(rd){ const samp=C.densify(rd.pts,4); let best=null,bd=1e9; const seen=new Set();
  for(const [x,z] of samp) for(const [,,w] of GI.near(x,z)) if(w.cls===rd.cls&&!seen.has(w)){ seen.add(w); let s=0; for(const [px,pz] of samp) s+=C.polyDist(px,pz,[...w.pts,...w.pts.slice().reverse()]); s/=samp.length; if(s<bd){ bd=s; best=w; } }
  return bd<1.2?best:null; }
const matched=new Set();
for(const s of S) for(const rd of s.roads){ const w=wayOf(rd); if(w){ matched.add(w); Object.assign(rd,{id:w.id,lanes:w.lanes||undefined,lf:w.lf||undefined,lb:w.lb||undefined,ms:w.ms||MPH[w.cls]||25,turn:w.turn||undefined,ref:w.ref||undefined,surf:w.surf}); }
  else { rd.surf=C.roadSurf(rd); rd.ms=MPH[rd.cls]||25; } }

// ---------- movement grid edits ----------
function heightIn(s,x,z){ const H=s.Hn||(s.Hn=unb64(s.H,Int16Array)), n=s.hn, fx=(x-s.x0+4)/4, fz=(z-s.z0+4)/4, i=Math.max(0,Math.min(n-2,Math.floor(fx))), j=Math.max(0,Math.min(n-2,Math.floor(fz))), u=fx-i, v=fz-j, h=(a,b)=>H[b*n+a]/100;
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; }
const KEEP=new Set([NK.building,NK.wall,NK.water,NK.steep,NK.low,NK.pier]);
function paintRoad(rd,pts,s){ const kind=!rd.drive?NK.path:rd.paved?NK.asphalt:NK.dirt, surf=kind===NK.asphalt?1:kind===NK.path?.95:.86, pad=rd.w/2+.3, ns=s.nav.n;
  for(let k=0;k<pts.length-1;k++){ const a=pts[k], b=pts[k+1];
    const i0=Math.max(0,Math.floor((Math.min(a[0],b[0])-pad-s.x0)/NS)), i1=Math.min(ns-1,Math.floor((Math.max(a[0],b[0])+pad-s.x0)/NS)), j0=Math.max(0,Math.floor((Math.min(a[1],b[1])-pad-s.z0)/NS)), j1=Math.min(ns-1,Math.floor((Math.max(a[1],b[1])+pad-s.z0)/NS));
    for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++){ const x=s.x0+(i+.5)*NS, z=s.z0+(j+.5)*NS; if(C.segDist(x,z,a,b)[0]>=pad) continue; const id=j*ns+i, old=s.kindA[id];
      if(KEEP.has(old)||old===NK.asphalt||(kind!==NK.asphalt&&(old===NK.lot||old===NK.path))) continue;
      const e=2, gx=(heightIn(s,x+e,z)-heightIn(s,x-e,z))/(2*e), gz=(heightIn(s,x,z+e)-heightIn(s,x,z-e))/(2*e), sl=Math.atan(Math.hypot(gx,gz))*180/Math.PI;
      if(!s.undoNav.has(id)) s.undoNav.set(id,[old,s.spA[id]]); s.kindA[id]=kind; s.spA[id]=Math.round(surf*(sl<4?1:Math.max(.28,1-(sl-4)/30))*250); } } }
// a baked unpaved-tagged road that the bake took as paved (or the other way round) is repainted
for(const s of S) for(const rd of s.roads){ const paved=rd.surf==='asphalt'||rd.surf==='concrete'; if(rd.bridge<0&&rd.drive&&paved!==rd.paved){ rd.pv0=rd.paved; rd.paved=paved; paintRoad(rd,rd.pts,s); } }
// the roads the region download left out
let added=0;
for(const w of ways){ if(matched.has(w)||w.len<4||w.rank<1&&w.drive) continue; if(!w.pts.some(([x,z])=>Math.abs(x)<HALF&&Math.abs(z)<HALF)) continue;
  for(const s of S){ for(const p of C.clipLine(w.pts,s.x0,s.z0,s.x0+SEC,s.z0+SEC)){
    const rd={cls:w.cls,surface:w.t.surface||'',oneway:w.oneway?'yes':'',name:w.name,paved:w.paved,drive:w.drive,w:w.w,bridge:-1,pts:p.pts.map(q=>[r1(q[0]),r1(q[1])]),cutStart:p.cutStart,cutEnd:p.cutEnd,added:1,id:w.id,surf:w.surf,ms:w.ms||MPH[w.cls]||15};
    s.roads.push(rd); paintRoad(rd,rd.pts,s); added++;
    // plants growing in the new road go
    const keep=[]; for(const pl of s.plants){ let d=1e9; for(let k=0;k<rd.pts.length-1;k++) d=Math.min(d,C.segDist(pl[1],pl[3],rd.pts[k],rd.pts[k+1])[0]); if(d<rd.w/2+(pl[0]===1?1.2:.5)) s.undoPlants.push(pl); else keep.push(pl); } s.plants=keep; } } }

// boulders big enough to reach onto a road are rolled off it (the bake kept plants 1.2 m off the centreline width, not their size)
for(const s of S){ const keep=[]; for(const pl of s.plants){ let gone=false; if(pl[0]===3) for(const rd of s.roads){ if(!rd.drive) continue; const reach=rd.w/2+.6+Math.max(pl[4],pl[6])*.95; let d=1e9; for(let k=0;k<rd.pts.length-1&&d>=reach;k++) d=Math.min(d,C.segDist(pl[1],pl[3],rd.pts[k],rd.pts[k+1])[0]); if(d<reach){ gone=true; break; } }
  if(gone) s.undoPlants.push(pl); else keep.push(pl); } s.plants=keep; }

// ---------- junctions ----------
const at=new Map(); ways.forEach(w=>{ if(w.rank<0) return; w.nodes.forEach((n,k)=>{ if(!at.has(n)) at.set(n,[]); at.get(n).push([w,k]); }); });
const junctions=[];
for(const [nid,list] of at){ const arms=[]; for(const [w,k] of list){ if(k>0) arms.push({w,k,sg:-1}); if(k<w.nodes.length-1) arms.push({w,k,sg:1}); }
  if(arms.length<3) continue; const J=list[0][0].pts[list[0][1]]; if(Math.abs(J[0])>HALF+40||Math.abs(J[1])>HALF+40) continue;
  for(const a of arms){ const w=a.w, s0=w.L[a.k], q=along(w,s0+a.sg*Math.min(6,a.sg>0?w.len-s0:s0)); let dx=q.x-J[0], dz=q.z-J[1]; const l=Math.hypot(dx,dz)||1; a.ax=dx/l; a.az=dz/l;
    a.incoming=!w.oneway||a.sg<0; a.hw=w.sec.pave/2; a.paved=w.paved; }
  junctions.push({id:nid,x:J[0],z:J[1],arms,maxR:Math.max(...arms.map(a=>a.w.rank))}); }
const jById=new Map(junctions.map(j=>[j.id,j]));
// junction nodes a few metres apart (ramp terminals, a side road meeting both halves of a divided road) are one intersection:
// merge them; each outside arm keeps its own node, the short links inside become part of the crossing
for(const j of junctions) j.cross=j.arms.filter(a=>a.w.rank>=2).length>=3;
{ const par=new Map(junctions.map(j=>[j.id,j.id])), find=x=>{ while(par.get(x)!==x) x=par.get(x); return x; };
  for(const j of junctions){ if(!j.cross) continue; for(const a of j.arms){ const w=a.w; if(w.rank<2) continue;
    for(let k=a.k+a.sg;k>=0&&k<w.nodes.length;k+=a.sg){ if(Math.abs(w.L[k]-w.L[a.k])>30) break; const o=jById.get(w.nodes[k]); if(o&&o.cross){ a.inner=o; par.set(find(j.id),find(o.id)); break; } } } }
  const groups=new Map(); for(const j of junctions){ const r=find(j.id); if(!groups.has(r)) groups.set(r,[]); groups.get(r).push(j); }
  const merged=[]; for(const mem of groups.values()){ for(const m of mem) for(const a of m.arms){ a.jx=m.x; a.jz=m.z; }
    if(mem.length===1){ mem[0].members=mem; mem[0].links=[]; merged.push(mem[0]); continue; }
    const arms=[], links=[]; for(const m of mem) for(const a of m.arms) (a.inner&&mem.includes(a.inner)?links:arms).push(a);
    merged.push({id:mem[0].id,x:mem.reduce((t,m)=>t+m.x,0)/mem.length,z:mem.reduce((t,m)=>t+m.z,0)/mem.length,arms,links,members:mem,maxR:Math.max(...mem.map(m=>m.maxR))}); }
  junctions.length=0; junctions.push(...merged); jById.clear(); for(const j of junctions) for(const m of j.members) jById.set(m.id,j); }
// stops, give ways and signals mapped in OSM
for(const n of nodes.values()){ const hw=n.tags&&n.tags.highway; if(!['stop','give_way','traffic_signals'].includes(hw)) continue;
  let best=null,bd=60; for(const j of junctions){ const d=Math.hypot(j.x-n.p[0],j.z-n.p[1]); if(d<bd){ bd=d; best=j; } } if(!best) continue;
  if(hw==='traffic_signals'){ if(bd<35) best.mapped='signals'; continue; }
  // which arm: the one pointing toward the node
  let arm=null,ad=1e9; for(const a of best.arms){ const dx=n.p[0]-best.x, dz=n.p[1]-best.z, l=Math.hypot(dx,dz)||1, c=-(dx/l*a.ax+dz/l*a.az); if(c<ad){ ad=c; arm=a; } }
  best.mapped=best.mapped||'stops'; if(arm&&arm.incoming) arm.ctl=hw==='stop'?'stop':'yield'; }
const shortName=n=>n.replace(/^North /,'N ').replace(/^South /,'S ').replace(/^East /,'E ').replace(/^West /,'W ').replace(/ Avenue$/,' Ave').replace(/ Road$/,' Rd').replace(/ Street$/,' St').replace(/ Lane$/,' Ln').replace(/ Drive$/,' Dr').replace(/ Boulevard$/,' Blvd').replace(/ Highway$/,' Hwy').replace(/ Parkway$/,' Pkwy').replace(/ Way$/,' Way');
const add=(x,z,list,item)=>{ const s=secAt(x,z); if(s) s.rk[list].push(item); };
// furniture stands off the pavement: nudge it outward until it clears every road
const PI=new C.SegIndex(24); for(const w of ways){ if(w.rank<0) continue; for(let k=1;k<w.pts.length;k++) PI.add(w.pts[k-1],w.pts[k],w,w.w/2+4); }
const edgeOf=w=>Math.max(w.paved?w.sec.pave/2+.6:w.w/2+.3,w.w/2);
const clearAt=(x,z,pad)=>{ for(const [a,b,w] of PI.near(x,z)) if(C.segDist(x,z,a,b)[0]<edgeOf(w)+pad) return false; return true; };
const nudge=(x,z,nx,nz,pad=.25)=>{ for(let k=0;k<=14;k++){ const px=x+nx*k*.5, pz=z+nz*k*.5; if(clearAt(px,pz,pad)) return [px,pz]; } return null; };
const hull=P=>{ P=P.slice().sort((a,b)=>a[0]-b[0]||a[1]-b[1]); const cr=(o,a,b)=>(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0]), lo=[], up=[];
  for(const p of P){ while(lo.length>=2&&cr(lo[lo.length-2],lo[lo.length-1],p)<=0) lo.pop(); lo.push(p); } for(const p of P.reverse()){ while(up.length>=2&&cr(up[up.length-2],up[up.length-1],p)<=0) up.pop(); up.push(p); }
  return lo.slice(0,-1).concat(up.slice(0,-1)); };
const junctionOut=[];
for(const j of junctions){ const hasMoto=j.arms.some(a=>a.w.cls==='motorway'); if(hasMoto) continue;
  const major=j.arms.filter(a=>a.w.rank>=4), R0=a=>Math.max(...j.arms.filter(b=>b!==a&&Math.abs(b.ax*a.ax+b.az*a.az)<.9).map(b=>b.hw),2.5)+1;
  let mode=j.mapped==='signals'?'signals':j.mapped?'mapped':major.length>=3&&new Set(major.map(a=>a.w.name||a.w.cls)).size>=2&&!major.every(a=>/_link/.test(a.w.cls))?'signals':'infer';
  if(mode==='infer'){ const real=j.arms.filter(a=>a.w.rank>=1&&a.w.t.service!=='driveway'&&a.w.t.service!=='parking_aisle'), top=Math.max(...real.map(a=>a.w.rank));
    const named=new Set(real.map(a=>a.w.name).filter(Boolean));
    if(real.length>=4&&real.every(a=>a.w.rank===top)&&top>=3&&named.size>=2) real.forEach(a=>{ if(a.incoming) a.ctl='stop'; a.all=1; });
    else { // the through road is the straightest pair of the highest-ranked arms; everything else coming in stops
      let thru=[],bs=-1e9; for(let i=0;i<real.length;i++) for(let k=i+1;k<real.length;k++){ const p=real[i], q=real[k], sc=Math.min(p.w.rank,q.w.rank)*10-(p.ax*q.ax+p.az*q.az)*4+(p.w.name&&p.w.name===q.w.name?3:0); if(sc>bs){ bs=sc; thru=[p,q]; } }
      for(const a of real){ if(!a.incoming||thru.includes(a)||a.inner) continue; if(a.w.rank>=3||(top>=3&&hash(a.w.id+j.id)<.45)) a.ctl='stop'; } } }
  // a driveway or track joining a road isn't a crossing: the road's paint runs on past it
  const minor=j.arms.filter(a=>a.w.rank>=2).length<=2&&mode!=='signals'&&!j.arms.some(a=>a.ctl&&a.w.rank>=2);
  const paved=!minor&&j.arms.filter(a=>a.paved&&a.w.rank>=2).length>=2, Rj=Math.max(...j.arms.filter(a=>a.w.rank>=1).map(a=>a.hw),2);
  const ctl=j.arms.some(a=>a.ctl)||mode==='signals';
  junctionOut.push(j); j.R=Rj+1; j.mode=mode;
  // the paved box of the crossing: each arm's full width out to where the other roads' edges are, wrapped in a hull
  let box=[]; if(paved){ for(const a of j.arms){ if(a.w.rank<2||!a.paved) continue; const ext=R0(a)-.6, rx=a.az, rz=-a.ax;
    for(const sd of [-1,1]) box.push([a.jx+a.ax*ext+rx*sd*a.hw,a.jz+a.az*ext+rz*sd*a.hw],[a.jx+a.ax*.5+rx*sd*a.hw,a.jz+a.az*.5+rz*sd*a.hw]); }
    for(const a of j.links) for(const sd of [-1,1]) box.push([a.jx+a.az*sd*a.hw,a.jz-a.ax*sd*a.hw]); }
  box=box.length>=3?hull(box).flatMap(p=>[r2(p[0]),r2(p[1])]):[];
  for(const s of S) if(j.x>s.x0-40&&j.x<s.x0+SEC+40&&j.z>s.z0-40&&j.z<s.z0+SEC+40) s.rk.junctions.push([r2(j.x),r2(j.z),box.length?1:0,r2(minor?0:Rj+(ctl?5:1.5)+Math.max(0,...j.members.map(m=>Math.hypot(m.x-j.x,m.z-j.z)))),box]);
  for(const a of j.arms){ const R=R0(a), rx=a.az, rz=-a.ax, w=a.w, hwA=a.hw, cross=j.arms.filter(b=>b.w.name&&b.w.name!==w.name).map(b=>b.w.name)[0], inner=false, jx=a.jx, jz=a.jz;
    // half of the road the incoming traffic uses
    const inHalf=w.oneway?[-hwA,hwA]:[0,hwA];
    if(mode==='signals'&&!inner){
      if(a.incoming){ const ext=Math.max(0,...j.members.map(m=>-(m.x-jx)*a.ax-(m.z-jz)*a.az)), far=ext+Math.max(...j.arms.filter(b=>Math.abs(b.ax*a.ax+b.az*a.az)<.9).map(b=>b.hw),3)+1.5, q=nudge(jx-a.ax*far+rx*(hwA+.9),jz-a.az*far+rz*(hwA+.9),rx,rz,.45);
        if(q){ const [px,pz]=q, base=(px-jx)*rx+(pz-jz)*rz;
          // heads hang over the incoming lanes; distances are along the arm from the pole
          const heads=w.sec.lanes.filter(l=>w.oneway||l.dir===(a.sg<0?1:-1)).map(l=>r2(base-(a.sg<0?l.o:-l.o))), hs=heads.length?heads:[r2(base-hwA*.5)];
          add(px,pz,'signals',{x:r2(px),z:r2(pz),y:r2(yawTo(a.ax,a.az)),L:r2(Math.max(...hs)+1.2),h:hs,n:cross?shortName(cross):''}); }
        if(a.paved){ const bx=jx+a.ax*(R+4), bz=jz+a.az*(R+4); add(bx,bz,'bars',[r2(bx+rx*inHalf[0]),r2(bz+rz*inHalf[0]),r2(bx+rx*(inHalf[1]-.3)),r2(bz+rz*(inHalf[1]-.3))]); } }
      if(a.paved){ const cx=jx+a.ax*(R+1.6), cz=jz+a.az*(R+1.6); add(cx,cz,'walks',[r2(cx),r2(cz),r2(yawTo(a.ax,a.az)),r2(hwA*2),3]); } }
    else if(a.ctl){ const q=nudge(jx+a.ax*(R+1.4)+rx*(hwA+.6),jz+a.az*(R+1.4)+rz*(hwA+.6),rx,rz);
      if(q) add(q[0],q[1],'signs',{k:a.ctl,x:r2(q[0]),z:r2(q[1]),y:r2(yawTo(a.ax,a.az)),n:[w.name?shortName(w.name):'',cross?shortName(cross):''],all:a.all||undefined});
      if(a.paved&&w.rank>=3){ const bx=jx+a.ax*(R+.6), bz=jz+a.az*(R+.6); add(bx,bz,'bars',[r2(bx+rx*inHalf[0]),r2(bz+rz*inHalf[0]),r2(bx+rx*(inHalf[1]-.3)),r2(bz+rz*(inHalf[1]-.3))]); } }
    // an exit ramp arriving here: wrong-way traffic from the junction is told not to enter
    if(/_link$/.test(w.cls)&&w.oneway&&a.incoming&&!inner) for(const sd of [1,-1]){ const q=nudge(jx+a.ax*(R+3)+rx*sd*(hwA+.6),jz+a.az*(R+3)+rz*sd*(hwA+.6),rx*sd,rz*sd); if(q) add(q[0],q[1],'signs',{k:'dne',x:r2(q[0]),z:r2(q[1]),y:r2(yawTo(-a.ax,-a.az))}); }
    // turn arrows painted on the lanes coming in
    const turns=(a.sg<0?w.turn:w.turnB); if(turns&&a.paved&&a.incoming){ const T=turns.split('|'), ls=w.sec.lanes.filter(l=>w.oneway||l.dir===(a.sg<0?1:-1)).sort((p,q)=>(a.sg<0?p.o-q.o:q.o-p.o));   // left to right as the driver sees them
      T.forEach((t,i)=>{ const ln=ls[i]; if(!ln||!t||t==='none') return; for(const d of [R+10,R+40]){ const s0=a.sg<0?w.L[a.k]-d:w.L[a.k]+d; if(s0<0||s0>w.len) continue; const q=along(w,s0), x=q.x+(-q.tz)*ln.o, z=q.z+q.tx*ln.o; add(x,z,'arrows',[r2(x),r2(z),r2(yawTo(-a.ax,-a.az)),t.split(';')[0]]); } }); } } }

// ---------- speed limits, exits and route signs ----------
const placed=[]; function speedSign(x,z,tx,tz,mph,off){ if(placed.some(p=>Math.hypot(p[0]-x,p[1]-z)<220&&p[2]*tx+p[3]*tz>.7)) return; placed.push([x,z,tx,tz]);
  const q=nudge(x+(-tz)*off,z+tx*off,-tz,tx); if(q) add(q[0],q[1],'signs',{k:'speed',x:r2(q[0]),z:r2(q[1]),y:r2(yawTo(-tx,-tz)),t:String(mph)}); }
// mapped speed signs first; OSM direction is the way the sign faces
for(const n of nodes.values()){ if(!n.tags||n.tags.traffic_sign!=='maxspeed') continue; let best=null,bd=25; for(const w of ways){ if(w.rank<2) continue; const d=C.polyDist(n.p[0],n.p[1],[...w.pts,...w.pts.slice().reverse()]); if(d<bd){ bd=d; best=w; } } if(!best) continue;
  let s0=0,dd=1e9; for(let i=0;i<=best.len;i+=2){ const q=along(best,i), d=Math.hypot(q.x-n.p[0],q.z-n.p[1]); if(d<dd){ dd=d; s0=i; } } const q=along(best,s0), dg=+n.tags.direction;
  let dir=1; if(!isNaN(dg)){ const fx=Math.sin(dg*Math.PI/180), fz=-Math.cos(dg*Math.PI/180); dir=fx*q.tx+fz*q.tz>0?-1:1; } if(best.oneway) dir=1;
  speedSign(q.x,q.z,q.tx*dir,q.tz*dir,parseInt(n.tags.maxspeed)||best.ms||MPH[best.cls],best.sec.pave/2+1.6); }
const isJ=new Set(junctionOut.flatMap(j=>j.members.map(m=>m.id)));
for(const w of ways){ if(w.rank<3||w.len<60||/_link/.test(w.cls)) continue; const mph=w.ms||MPH[w.cls];
  for(const dir of w.oneway?[1]:[1,-1]){ const ks=w.nodes.map((n,k)=>k).filter(k=>isJ.has(w.nodes[k])&&jById.get(w.nodes[k]).maxR>=(w.cls==='residential'?4:w.rank));
    for(const k of ks){ const s0=w.L[k]+dir*60; if(s0<10||s0>w.len-10) continue; const q=along(w,s0); speedSign(q.x,q.z,q.tx*dir,q.tz*dir,mph,w.sec.pave/2+1.6); } } }
// freeway: exit gore signs, advance guide signs, route shields after the on-ramps, delineators are drawn at run time
const motoAt=new Map(); for(const w of ways) if(w.cls==='motorway') w.nodes.forEach((n,k)=>motoAt.set(n,[w,k]));
function walkMoto(w,k,dist){ let s=w.L[k]+dist, guard=0; while(guard++<20){ if(s>=0&&s<=w.len) return {w,q:along(w,s)}; if(s<0){ const prev=ways.find(v=>v.cls==='motorway'&&v.nodes[v.nodes.length-1]===w.nodes[0]); if(!prev) return null; s+=prev.len; w=prev; } else { const next=ways.find(v=>v.cls==='motorway'&&v.nodes[0]===w.nodes[w.nodes.length-1]); if(!next) return null; s-=w.len; w=next; } } return null; }
for(const l of ways){ if(l.cls!=='motorway_link') continue; const st=motoAt.get(l.nodes[0]), en=motoAt.get(l.nodes[l.nodes.length-1]);
  if(st){ const [m,k]=st, jn=nodes.get(l.nodes[0]), ref=(jn&&jn.tags&&jn.tags.ref)||[...nodes.values()].find(n=>n.tags&&n.tags.highway==='motorway_junction'&&Math.hypot(n.p[0]-m.pts[k][0],n.p[1]-m.pts[k][1])<120)?.tags.ref||'';
    const dest=l.t.destination||ways.find(v=>v.cls==='motorway_link'&&v.nodes[0]===l.nodes[l.nodes.length-1]&&v.t.destination)?.t.destination||'';
    for(let s=10;s<Math.min(l.len,320);s+=2){ const q=along(l,s); let d=1e9; for(const v of ways) if(v.cls==='motorway') d=Math.min(d,C.polyDist(q.x,q.z,[...v.pts,...v.pts.slice().reverse()])); if(d>m.sec.pave/2+l.sec.pave/2+2.5){ const x=q.x+q.tz*(l.sec.pave/2+2.2), z=q.z-q.tx*(l.sec.pave/2+2.2); add(x,z,'signs',{k:'gore',x:r2(x),z:r2(z),y:r2(yawTo(-q.tx,-q.tz)),t:ref}); break; } }
    for(const back of [-420,-120]){ const g=walkMoto(m,k,back); if(!g) continue; const q=g.q, off=g.w.w/2+2.5, x=q.x-q.tz*off, z=q.z+q.tx*off; add(x,z,'signs',{k:'guide',x:r2(x),z:r2(z),y:r2(yawTo(-q.tx,-q.tz)),t:dest||'Exit',r:ref,d:back<-200?'1/4 MILE':''}); } }
  if(en){ const [m,k]=en, g=walkMoto(m,k,320); if(g){ const q=g.q, off=g.w.w/2+2.2, x=q.x-q.tz*off, z=q.z+q.tx*off, dir=Math.abs(q.tz)>Math.abs(q.tx)?(q.tz<0?'NORTH':'SOUTH'):(q.tx>0?'EAST':'WEST');
      add(x,z,'signs',{k:'shield',x:r2(x),z:r2(z),y:r2(yawTo(-q.tx,-q.tz)),t:(m.ref.match(/\d+/)||['17'])[0],d:dir}); speedSign(q.x+q.tx*60,q.z+q.tz*60,q.tx,q.tz,m.ms||75,m.sec.pave/2+2.4); } }
  // on-ramp entrance: route marker and destination where the ramp leaves the cross road
  if(en&&l.t.destination&&!st){ const q=along(l,25), off=l.sec.pave/2+1.4, x=q.x-q.tz*off, z=q.z+q.tx*off, ref=(l.t['destination:ref']||'').match(/\d+/);
    add(x,z,'signs',{k:'trail',x:r2(x),z:r2(z),y:r2(yawTo(-q.tx,-q.tz)),t:ref?ref[0]:'17',d:(l.t['destination:ref']||'').replace(/^I[- ]?\d+\s*/,'').toUpperCase(),n:l.t.destination}); } }
// the cable barrier down the freeway's median: midway between the two carriageways where they run side by side
{ const moto=ways.filter(w=>w.cls==='motorway'), done=[];
  for(const w of moto){ let run=[]; const flush=()=>{ if(run.length>=3){ for(const s of S){ for(const p of C.clipLine(run,s.x0,s.z0,s.x0+SEC,s.z0+SEC)) s.rk.medians.push({k:'cable',pts:p.pts.map(q=>[r1(q[0]),r1(q[1])])}); } } run=[]; };
    for(let s=0;s<=w.len;s+=6){ const q=along(w,s), lx=q.tz, lz=-q.tx; let best=null,bd=80;   // left of travel
      for(const v of moto){ if(v===w) continue; for(let k=1;k<v.pts.length;k++){ const [d,px,pz]=C.segDist(q.x,q.z,v.pts[k-1],v.pts[k]); const vx=v.pts[k][0]-v.pts[k-1][0], vz=v.pts[k][1]-v.pts[k-1][1], vl=Math.hypot(vx,vz)||1;
        if(d<bd&&d>14&&(px-q.x)*lx+(pz-q.z)*lz>0&&(vx*q.tx+vz*q.tz)/vl<-.8){ bd=d; best=[px,pz]; } } }
      const m=best&&[(q.x+best[0])/2,(q.z+best[1])/2], onBridge=m&&IDX.bridges.some(b=>C.polyDist(m[0],m[1],[...b.d,...b.d.slice().reverse()])<b.hw+4);
      if(!m||onBridge||done.some(p=>p[2]!==w&&Math.hypot(p[0]-m[0],p[1]-m[1])<10)){ flush(); continue; } done.push([m[0],m[1],w]); run.push(m); }
    flush(); } }
// gates and cattle guards on the roads
for(const n of nodes.values()){ const b=n.tags&&n.tags.barrier; if(b!=='gate'&&b!=='cattle_grid') continue; const l=at.get(n.id); if(!l) continue; const [w,k]=l[0], q=along(w,w.L[k]);
  add(n.p[0],n.p[1],b==='gate'?'gates':'grids',[r2(n.p[0]),r2(n.p[1]),r2(Math.atan2(q.tx,q.tz)),r2(w.w),hash(n.id)<.7?1:0]); }

// ---------- write ----------
let sum={added,signs:0,signals:0,junctions:junctionOut.length,medians:0,changed:0};
for(const s of S){ s.rk.undo={nav:[...s.undoNav].flatMap(([i,[k,v]])=>[i,k,v]),plants:s.undoPlants}; sum.changed+=s.undoNav.size;
  s.nav.kind=b64(s.kindA); s.nav.sp=b64(s.spA); delete s.kindA; delete s.spA; delete s.undoNav; delete s.undoPlants; delete s.Hn;
  sum.signs+=s.rk.signs.length; sum.signals+=s.rk.signals.length; sum.medians+=s.rk.medians.length;
  const js=JSON.stringify(s); fs.writeFileSync(`${dir}/s_${s.c}_${s.r}.json`,js); const e=IDX.sectors.find(q=>q.c===s.c&&q.r===s.r); e.bytes=js.length; e.gz=zlib.gzipSync(js,{level:9}).length; e.plants=s.plants.length; }
IDX.roadKit={osm:osmFile.split('/').pop(),matched:matched.size,ways:ways.length};
fs.writeFileSync(`${dir}/index.json`,JSON.stringify(IDX));
console.log('ways',ways.length,'matched',matched.size,sum);
