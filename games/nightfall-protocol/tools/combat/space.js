// ---------- a generated building as free space for combat ----------
// No grid in the rules: units stand at any point. The interiors generator's walls, doors and windows (on its 1 m cell
// edges) become line segments, its furniture becomes boxes, yard walls become thick segments. Sight and shots are rays
// against them; cover is whatever really stands between a unit and the shooter, close to the unit. Movement runs over a
// hidden 0.5 m cost field with 16 directions (so ranges are near-round) and paths are pulled straight afterwards.
//
// Frame: the building's local frame (u along the footprint's main axis, v across it), metres, x=u, z=v; 12 m of yard
// around the footprint. Runs in Node for tests; no rendering in here.
(function(root,factory){ const m=factory(); if(typeof module==='object'&&module.exports) module.exports=m; else root.InteriorSpace=m; })(this,function(){
const DIRS=[[1,0],[0,1],[-1,0],[0,-1]];
const R=.3, NS=.5, EYE=1.5, FY=.15, YARD=.8, PAVED=1, LOW=.6, BUCKET=2, LEAN=.7, COVER_REACH=1.1;
const COV={none:0,half:1,full:2};
// how much of a round's push a wall soaks up, by its build-up (the interiors' WALLMAT); 0: stops it. A round has 3.
const PIERCE={stud:1,frame:2};
const EPS=1e-9;
function rngOf(str){ let h=2166136261>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,16777619); } let a=h>>>0; return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }

// ---------- 2D geometry ----------
const cross=(ax,az,bx,bz)=>ax*bz-az*bx;
// where segment p→q meets segment a→b, as the fraction t along p→q, or -1
function segSeg(px,pz,qx,qz,ax,az,bx,bz){ const rx=qx-px, rz=qz-pz, sx=bx-ax, sz=bz-az, d=cross(rx,rz,sx,sz); if(Math.abs(d)<EPS) return -1;
  const t=cross(ax-px,az-pz,sx,sz)/d, u=cross(ax-px,az-pz,rx,rz)/d; return (t>=-1e-7&&t<=1+1e-7&&u>=-1e-7&&u<=1+1e-7)?t:-1; }
// where segment p→q enters box b (slab clipping), or -1
function segBox(px,pz,qx,qz,b){ let t0=0,t1=1; const dx=qx-px, dz=qz-pz;
  for(const [p,d,lo,hi] of [[px,dx,b.x0,b.x1],[pz,dz,b.z0,b.z1]]){ if(Math.abs(d)<EPS){ if(p<lo||p>hi) return -1; continue; } let a=(lo-p)/d, c=(hi-p)/d; if(a>c){ const k=a; a=c; c=k; } t0=Math.max(t0,a); t1=Math.min(t1,c); if(t0>t1) return -1; }
  return t0; }
function ptSeg(px,pz,ax,az,bx,bz){ const dx=bx-ax, dz=bz-az, L=dx*dx+dz*dz||1; let t=((px-ax)*dx+(pz-az)*dz)/L; t=Math.max(0,Math.min(1,t)); const x=ax+dx*t, z=az+dz*t; return {d:Math.hypot(px-x,pz-z),x,z}; }
function ptBox(px,pz,b){ const x=Math.max(b.x0,Math.min(b.x1,px)), z=Math.max(b.z0,Math.min(b.z1,pz)); return {d:Math.hypot(px-x,pz-z),x,z}; }
function segSegDist(ax,az,bx,bz,cx,cz,dx,dz){ if(segSeg(ax,az,bx,bz,cx,cz,dx,dz)>=0) return 0; return Math.min(ptSeg(ax,az,cx,cz,dx,dz).d,ptSeg(bx,bz,cx,cz,dx,dz).d,ptSeg(cx,cz,ax,az,bx,bz).d,ptSeg(dx,dz,ax,az,bx,bz).d); }
const grow=(b,r)=>({x0:b.x0-r,z0:b.z0-r,x1:b.x1+r,z1:b.z1+r});

function fromGenerated(G,opt={}){
  const margin=opt.margin==null?12:opt.margin, {M,O,Fn}=G;
  const X0=M.u0-margin, Z0=M.v0-margin, X1=M.u0+M.W+margin, Z1=M.v0+M.H+margin;
  const insideAt=(x,z)=>{ const i=Math.floor(x-M.u0), j=Math.floor(z-M.v0); return i>=0&&j>=0&&i<M.W&&j<M.H&&!!M.mask[j*M.W+i]; };
  // ---------- obstacles ----------
  const obs=[];   // {id, kind:'edge'|'yard'|'item', seg:[ax,az,bx,bz] | box, e, it, h, t}
  const edgeSeg=e=>{ const o=e.key[0], [p,q]=e.key.slice(1).split(',').map(Number); return o==='v'?[M.u0+p,M.v0+q,M.u0+p,M.v0+q+1]:[M.u0+p,M.v0+q,M.u0+p+1,M.v0+q]; };
  for(const e of O.edges.values()){ if(e.type==='none'||e.type==='open') continue; const s=edgeSeg(e); obs.push({id:obs.length,kind:'edge',seg:s,e,ext:!!e.ext}); }
  for(const w of (G.site.walls||[])){ const a=M.toL(w[0],w[1]), b=M.toL(w[2],w[3]); if(Math.hypot(b[0]-a[0],b[1]-a[1])<.05) continue; obs.push({id:obs.length,kind:'yard',seg:[a[0],a[1],b[0],b[1]],h:w[4],t:Math.max(.1,w[5]/2)}); }
  const lows=[];
  for(const it of Fn.items){ let i0=1e9,i1=-1e9,j0=1e9,j1=-1e9; for(const c of it.cells){ const i=c%M.W, j=(c/M.W)|0; i0=Math.min(i0,i); i1=Math.max(i1,i); j0=Math.min(j0,j); j1=Math.max(j1,j); }
    const box={x0:M.u0+i0+.08,z0:M.v0+j0+.08,x1:M.u0+i1+1-.08,z1:M.v0+j1+1-.08};
    if(it.spec.h<.3) lows.push(box); else obs.push({id:obs.length,kind:'item',box,it,h:it.spec.h}); }
  const roads=(G.site.roads||[]).map(r=>({w:r.w,pts:r.pts.map(p=>M.toL(p[0],p[1]))}));
  // ---------- what each obstacle does, from its current state ----------
  // door states: the change record's doors, keyed by floor like the interiors renderer reads them ('0:v5,12')
  const doorSt=opt.doors||{}, wallSt=opt.walls||{}, LV=(G.level||0)+':';
  const doorState=e=>doorSt[LV+e.key]!==undefined?doorSt[LV+e.key]:(e.door.state==='broken'?'broken':e.door.state==='barricaded'?'barricaded':e.door.open?'open':'closed');
  // solid: keeps bodies R away. cross: a body may pass through it (at extra effective metres).
  function props(o){
    if(o.kind==='item'){ if(o.destroyed||o.flat) return {solid:false,sight:true,shot:true,cover:0,cross:true,extra:1};   // blown apart or lying flat: clutter
      const cv=COV[o.cover||o.it.spec.cover]||0, tall=cv===2&&o.h>=EYE; return {solid:true,sight:!tall,shot:!tall,cover:cv,cross:false}; }
    if(o.kind==='yard'){ const tall=o.h>=EYE; return {solid:true,sight:!tall,shot:!tall,cover:o.h>=1.2?2:1,cross:false}; }
    const e=o.e;
    switch(e.type){
      case 'wall': { const dm=wallSt[LV+e.key], s=dm?dm.s||0:0;
        if(s>=3) return {solid:false,sight:true,shot:true,cover:1,cross:true,extra:1,opening:true,breach:true};   // breached: a way through
        if(s>=2) return {solid:true,sight:true,shot:true,cover:1,cross:false};                                   // holed: see and shoot through
        return {solid:true,sight:false,shot:false,cover:2,cross:false,pierce:PIERCE[e.mat]||0}; }
      case 'door': case 'gdoor': { const s=doorState(e);
        if(s==='open'||s==='broken') return {solid:false,sight:true,shot:true,cover:0,cross:true,extra:0,opening:true};
        if(s==='closed') return {solid:false,sight:false,shot:false,cover:2,cross:e.type==='door',extra:1,opens:true,opening:true,pierce:1};
        return {solid:true,sight:false,shot:false,cover:2,cross:false,opening:true}; }
      case 'window': { const s=e.win.state; if(s==='boarded') return {solid:true,sight:false,shot:false,cover:2,cross:false,opening:true};
        return {solid:false,sight:true,shot:true,cover:1,cross:true,extra:s==='intact'?5:4,glass:s==='intact',climb:true,opening:true}; }
      case 'counter': return {solid:false,sight:true,shot:true,cover:1,cross:true,extra:3,climb:true,opening:true};
      default: return {solid:true,sight:false,shot:false,cover:2,cross:false};
    } }
  // ---------- spatial hash ----------
  const BW=Math.ceil((X1-X0)/BUCKET), BH=Math.ceil((Z1-Z0)/BUCKET), buckets=Array.from({length:BW*BH},()=>[]);
  const bboxOf=o=>o.box?o.box:{x0:Math.min(o.seg[0],o.seg[2]),z0:Math.min(o.seg[1],o.seg[3]),x1:Math.max(o.seg[0],o.seg[2]),z1:Math.max(o.seg[1],o.seg[3])};
  const fileObs=(o,add)=>{ const b=grow(bboxOf(o),R+(o.t||0)+.05); for(let j=Math.max(0,Math.floor((b.z0-Z0)/BUCKET));j<=Math.min(BH-1,Math.floor((b.z1-Z0)/BUCKET));j++) for(let i=Math.max(0,Math.floor((b.x0-X0)/BUCKET));i<=Math.min(BW-1,Math.floor((b.x1-X0)/BUCKET));i++){ const L=buckets[j*BW+i], k=L.indexOf(o); if(add&&k<0) L.push(o); if(!add&&k>=0) L.splice(k,1); } };
  for(const o of obs){ const b=grow(bboxOf(o),R+(o.t||0)+.05); for(let j=Math.max(0,Math.floor((b.z0-Z0)/BUCKET));j<=Math.min(BH-1,Math.floor((b.z1-Z0)/BUCKET));j++) for(let i=Math.max(0,Math.floor((b.x0-X0)/BUCKET));i<=Math.min(BW-1,Math.floor((b.x1-X0)/BUCKET));i++) buckets[j*BW+i].push(o); }
  let stamp=1; const seen=new Uint32Array(obs.length+1);
  // every obstacle near the segment p→q (buckets along it, each obstacle once)
  function near(px,pz,qx,qz,fn){ stamp++; const x0=Math.min(px,qx), x1=Math.max(px,qx), z0=Math.min(pz,qz), z1=Math.max(pz,qz);
    const i0=Math.max(0,Math.floor((x0-X0)/BUCKET)), i1=Math.min(BW-1,Math.floor((x1-X0)/BUCKET)), j0=Math.max(0,Math.floor((z0-Z0)/BUCKET)), j1=Math.min(BH-1,Math.floor((z1-Z0)/BUCKET));
    const long=(i1-i0+1)*(j1-j0+1)>12, L=Math.hypot(qx-px,qz-pz)||1, nx=-(qz-pz)/L, nz=(qx-px)/L;
    for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++){
      if(long){ const cx=X0+(i+.5)*BUCKET-px, cz=Z0+(j+.5)*BUCKET-pz; if(Math.abs(cx*nx+cz*nz)>BUCKET*.75) continue; }   // only buckets the line runs through
      for(const o of buckets[j*BW+i]){ if(seen[o.id]===stamp) continue; seen[o.id]=stamp; if(fn(o)===false) return; } } }
  const hitT=(o,px,pz,qx,qz)=>o.box?segBox(px,pz,qx,qz,o.box):segSeg(px,pz,qx,qz,o.seg[0],o.seg[1],o.seg[2],o.seg[3]);
  // ---------- sight and shots ----------
  function sight(p,q,o2){ const shot=o2&&o2.shot, col=o2&&o2.collect; let ok=true;
    near(p[0],p[1],q[0],q[1],o=>{ const t=hitT(o,p[0],p[1],q[0],q[1]); if(t<0) return; const pr=props(o); if(!(shot?pr.shot:pr.sight)){ ok=false; return false; } if(col&&pr.opening) col.push(o); });
    return ok; }
  // a round fired from p at q that may punch through thin walls and doors: null if something stops it, else how many it went through
  function shotThrough(p,q){ let push=3, walls=0, ok=true; const hits=[];
    near(p[0],p[1],q[0],q[1],o=>{ const t=hitT(o,p[0],p[1],q[0],q[1]); if(t>=0) hits.push([t,o]); });
    hits.sort((a,b)=>a[0]-b[0]);
    for(const [,o] of hits){ const pr=props(o); if(pr.shot) continue; if(!pr.pierce){ ok=false; break; } push-=pr.pierce; walls++; if(push<0){ ok=false; break; } }
    return ok?{walls}:null; }
  // how far a ray goes before something stops sight (for drawing what a unit sees)
  function castRay(p,ang,maxD){ const qx=p[0]+Math.sin(ang)*maxD, qz=p[1]+Math.cos(ang)*maxD; let best=1;
    near(p[0],p[1],qx,qz,o=>{ const t=hitT(o,p[0],p[1],qx,qz); if(t>=0&&t<best&&!props(o).sight) best=t; }); return best*maxD; }
  // cover at p against a shooter at s: the best cover among things the shot line crosses within reach of p
  function coverFrom(p,s){ const dx=s[0]-p[0], dz=s[1]-p[1], L=Math.hypot(dx,dz)||1, k=Math.min(L,COVER_REACH)/L, qx=p[0]+dx*k, qz=p[1]+dz*k; let v=0;
    near(p[0],p[1],qx,qz,o=>{ if(hitT(o,p[0],p[1],qx,qz)>=0) v=Math.max(v,props(o).cover); }); return v; }
  // ---------- bodies and steps ----------
  const inBounds=(x,z)=>x>X0+R&&z>Z0+R&&x<X1-R&&z<Z1-R;
  function clearAt(x,z,r){ r=r==null?R:r; if(!inBounds(x,z)) return false; let ok=true;
    near(x-r,z-r,x+r,z+r,o=>{ const pr=props(o); if(!pr.solid) return; const d=o.box?ptBox(x,z,o.box).d:ptSeg(x,z,o.seg[0],o.seg[1],o.seg[2],o.seg[3]).d-(o.t||0); if(d<r-1e-6){ ok=false; return false; } }); return ok; }
  // can a body walk straight from a to b; which openings it goes through and what they cost
  function walk(a,b){ let ok=true, extra=0; const crossed=[];
    near(a[0]-R,a[1]-R,b[0]+R,b[1]+R,o=>{ const pr=props(o);
      if(pr.solid){ const d=o.box?(segBox(a[0],a[1],b[0],b[1],grow(o.box,R-1e-6))>=0?0:1):segSegDist(a[0],a[1],b[0],b[1],o.seg[0],o.seg[1],o.seg[2],o.seg[3])-(o.t||0)-(R-1e-6); if(d<=0){ ok=false; return false; } return; }
      if(hitT(o,a[0],a[1],b[0],b[1])>=0){ if(!pr.cross){ ok=false; return false; } extra+=pr.extra||0; crossed.push(o); } });
    return {ok,extra,crossed}; }
  const speedAt=(x,z)=>{ if(insideAt(x,z)){ for(const b of lows) if(x>=b.x0&&x<=b.x1&&z>=b.z0&&z<=b.z1) return LOW; return 1; }
    for(const r of roads) for(let k=0;k<r.pts.length-1;k++) if(ptSeg(x,z,r.pts[k][0],r.pts[k][1],r.pts[k+1][0],r.pts[k+1][1]).d<r.w/2) return PAVED; return YARD; };
  // ---------- the hidden cost field ----------
  const NW=Math.floor((X1-X0)/NS), NH=Math.floor((Z1-Z0)/NS), NN=NW*NH;
  const nx=n=>X0+(n%NW+.5)*NS, nz=n=>Z0+(((n/NW)|0)+.5)*NS;
  const nodeAt=(x,z)=>{ const i=Math.floor((x-X0)/NS), j=Math.floor((z-Z0)/NS); return i<0||j<0||i>=NW||j>=NH?-1:j*NW+i; };
  const free=new Uint8Array(NN), speed=new Float32Array(NN);
  for(let n=0;n<NN;n++){ const x=nx(n), z=nz(n); if(clearAt(x,z)){ free[n]=1; speed[n]=speedAt(x,z); } }
  const OFF=[[1,0],[0,1],[-1,0],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1],[1,2],[2,1],[-1,2],[-2,1],[1,-2],[2,-1],[-1,-2],[-2,-1]];
  // Openings are portals: a door, window or counter links the nearest nodes on its two sides through its middle.
  // Ordinary steps never cross an opening, so every route goes through the centre of a doorway, never across a jamb.
  const portals=new Map();   // node -> [[m, length, [obstacle]]]
  function addPortal(o){ const mx=(o.seg[0]+o.seg[2])/2, mz=(o.seg[1]+o.seg[3])/2, n=DIRS[o.e.dir];
    const side=s=>{ const px=mx+n[0]*.6*s, pz=mz+n[1]*.6*s, n0=nodeAt(px,pz); if(n0<0) return -1; let best=-1, bd=1e9; const i0=n0%NW, j0=(n0/NW)|0;
      for(let dj=-2;dj<=2;dj++) for(let di=-2;di<=2;di++){ const m=(j0+dj)*NW+i0+di; if(m<0||m>=NN||!free[m]) continue; const d=Math.hypot(nx(m)-px,nz(m)-pz); if(d>.9||d>=bd) continue; const w=walkGeom([nx(m),nz(m)],[mx,mz]); if(!w||w.some(x=>x!==o)) continue; best=m; bd=d; }
      return best; };
    const a=side(1), b=side(-1); if(a<0||b<0) return; const L=Math.hypot(nx(a)-mx,nz(a)-mz)+Math.hypot(nx(b)-mx,nz(b)-mz);
    for(const [u,v] of [[a,b],[b,a]]){ if(!portals.has(u)) portals.set(u,[]); portals.get(u).push([v,L,[o]]); links[u]=undefined; } o.portal=true; }
  const links=new Array(NN);
  for(const o of obs) if(o.kind==='edge'&&o.e.type!=='wall') addPortal(o);   // geometry of each step, cached: [m, length, openings crossed]
  function linksOf(n){ let L=links[n]; if(L) return L; L=[]; const i=n%NW, j=(n/NW)|0, a=[nx(n),nz(n)];
    for(const [di,dj] of OFF){ const ii=i+di, jj=j+dj; if(ii<0||jj<0||ii>=NW||jj>=NH) continue; const m=jj*NW+ii; if(!free[m]) continue;
      const w=walkGeom(a,[nx(m),nz(m)]); if(!w||w.length) continue; L.push([m,Math.hypot(di,dj)*NS,w]); }
    for(const pl of portals.get(n)||[]) L.push(pl);
    links[n]=L; return L; }
  // geometry-only step test between two field nodes (ignores door states, which change): null if a body walking it
  // would come within R of anything solid, else the openings it crosses
  function walkGeom(a,b){ let ok=true; const crossed=[], ax=a[0], az=a[1], bx=b[0], bz=b[1];
    near(ax-R,az-R,bx+R,bz+R,o=>{ if(o.kind==='edge'&&(o.e.type!=='wall'||o.portal)){ if(segSeg(ax,az,bx,bz,o.seg[0],o.seg[1],o.seg[2],o.seg[3])>=0) crossed.push(o); return; }
      const hit=o.box?segBox(ax,az,bx,bz,grow(o.box,R-1e-6))>=0:segSegDist(ax,az,bx,bz,o.seg[0],o.seg[1],o.seg[2],o.seg[3])<(o.t||0)+R-1e-6;
      if(hit){ ok=false; return false; } });
    return ok?crossed:null; }
  function stepCost(n,m,len,crossed){ let extra=0; for(const o of crossed){ const pr=props(o); if(!pr.cross) return -1; extra+=pr.extra||0; } return len/((speed[n]+speed[m])/2)+extra; }
  // Dijkstra from a point over the field, up to a budget in effective metres. `others`: points other bodies stand on.
  function field(start,budget,others){ budget=budget||24; const cost=new Float64Array(NN).fill(Infinity), prev=new Int32Array(NN).fill(-1), via=new Int32Array(NN).fill(-1), blocked=new Uint8Array(NN);
    for(const p of others||[]){ const n0=nodeAt(p[0],p[1]); if(n0<0) continue; const i0=n0%NW, j0=(n0/NW)|0; for(let dj=-2;dj<=2;dj++) for(let di=-2;di<=2;di++){ const m=(j0+dj)*NW+i0+di; if(m>=0&&m<NN&&Math.hypot(nx(m)-p[0],nz(m)-p[1])<2*R+.05) blocked[m]=1; } }
    const h=[]; const push=(c,n)=>{ h.push([c,n]); let i=h.length-1; while(i){ const q=(i-1)>>1; if(h[q][0]<=h[i][0]) break; [h[q],h[i]]=[h[i],h[q]]; i=q; } };
    const pop=()=>{ const top=h[0], last=h.pop(); if(h.length){ h[0]=last; let i=0; for(;;){ const l=2*i+1, r=l+1; let s=i; if(l<h.length&&h[l][0]<h[s][0]) s=l; if(r<h.length&&h[r][0]<h[s][0]) s=r; if(s===i) break; [h[s],h[i]]=[h[i],h[s]]; i=s; } } return top; };
    // join the start point to the nodes around it
    const n0=nodeAt(start[0],start[1]), sp=speedAt(start[0],start[1]);
    if(n0>=0){ const i0=n0%NW, j0=(n0/NW)|0; for(let dj=-2;dj<=2;dj++) for(let di=-2;di<=2;di++){ const m=(j0+dj)*NW+i0+di; if(m<0||m>=NN||!free[m]||blocked[m]) continue; const q=[nx(m),nz(m)], d=Math.hypot(q[0]-start[0],q[1]-start[1]); if(d>1.2) continue;
      const w=walk(start,q); if(!w.ok) continue; const c=d/((sp+speed[m])/2)+w.extra; if(c<cost[m]){ cost[m]=c; prev[m]=-2; push(c,m); } } }
    while(h.length){ const [g,n]=pop(); if(g>cost[n]) continue;
      for(const [m,len,crossed] of linksOf(n)){ if(blocked[m]) continue; const k=stepCost(n,m,len,crossed); if(k<0) continue; const c=g+k; if(c>budget+1e-6) continue; if(c<cost[m]-1e-9){ cost[m]=c; prev[m]=n; via[m]=crossed.length?crossed[0].id:-1; push(c,m); } } }
    return {start:[start[0],start[1]],budget,cost,prev,via,blocked}; }
  // the cost of standing at an exact point: from the best node around it that can walk straight there
  function costTo(F,p){ if(!clearAt(p[0],p[1])) return null; const n0=nodeAt(p[0],p[1]); if(n0<0) return null; let best=null; const sp=speedAt(p[0],p[1]);
    const d0=Math.hypot(p[0]-F.start[0],p[1]-F.start[1]); if(d0<1.2){ const w=walk(F.start,p); if(w.ok) best={cost:d0/sp+w.extra,node:-2}; }
    const i0=n0%NW, j0=(n0/NW)|0;
    for(let dj=-2;dj<=2;dj++) for(let di=-2;di<=2;di++){ const m=(j0+dj)*NW+i0+di; if(m<0||m>=NN||!isFinite(F.cost[m])) continue; const q=[nx(m),nz(m)], d=Math.hypot(q[0]-p[0],q[1]-p[1]); if(d>1.2) continue;
      if(best&&F.cost[m]+d>=best.cost) continue; const w=walk(q,p); if(!w.ok) continue; const c=F.cost[m]+d/((speed[m]+sp)/2)+w.extra; if(!best||c<best.cost) best={cost:c,node:m}; }
    if(best&&best.cost>F.budget+1e-6) return Object.assign(best,{over:true});
    return best; }
  // the route to p: field nodes back to the start, through the middle of every doorway and window, pulled straight between them
  function pathTo(F,p){ const ct=costTo(F,p); if(!ct||ct.over) return null;
    const chain=[]; for(let n=ct.node;n>=0;n=F.prev[n]) chain.push(n); chain.reverse();
    const mid=o=>({x:(o.seg[0]+o.seg[2])/2,z:(o.seg[1]+o.seg[3])/2,through:o});
    const out=[{x:F.start[0],z:F.start[1]}];
    const hop=(a,b)=>{ for(const o of walk(a,b).crossed) out.push(mid(o)); };
    if(chain.length){ hop(F.start,[nx(chain[0]),nz(chain[0])]);
      chain.forEach((n,k)=>{ if(k&&F.via[n]>=0) out.push(mid(obs[F.via[n]])); out.push({x:nx(n),z:nz(n)}); });
      hop([nx(chain[chain.length-1]),nz(chain[chain.length-1])],p); }
    else hop(F.start,p);
    out.push({x:p[0],z:p[1]});
    // pull straight: from each kept point jump to the furthest later one a clear walk reaches, never past a pinned opening
    const keep=[out[0]]; let i=0;
    while(i<out.length-1){ let j=i+1;
      for(let k=out.length-1;k>i+1;k--){ let pinned=false; for(let q=i+1;q<k;q++) if(out[q].through){ pinned=true; break; } if(pinned) continue;
        const w=walk([out[i].x,out[i].z],[out[k].x,out[k].z]); if(w.ok&&w.crossed.every(o=>o===out[i].through||o===out[k].through)){ j=k; break; } }
      keep.push(out[j]); i=j; }
    return {cost:ct.cost,points:keep}; }
  // ---------- cover: where to stand, and snapping to it ----------
  const coverObs=o=>{ const pr=props(o); return pr.cover>0&&(o.kind!=='edge'||o.e.type!=='door'||doorState(o.e)!=='open'); };
  function nearestCover(x,z,r){ let best=null; near(x-r,z-r,x+r,z+r,o=>{ if(!coverObs(o)) return; const q=o.box?ptBox(x,z,o.box):ptSeg(x,z,o.seg[0],o.seg[1],o.seg[2],o.seg[3]); const d=q.d-(o.t||0); if(d<r&&(!best||d<best.d)) best={o,d,x:q.x,z:q.z}; }); return best; }
  // a click near cover moves to just behind it
  function snap(p,r){ r=r==null?.9:r; const c=nearestCover(p[0],p[1],r); if(!c) return p; let dx=p[0]-c.x, dz=p[1]-c.z, L=Math.hypot(dx,dz);
    if(L<1e-3){ if(c.o.seg){ const sx=c.o.seg[2]-c.o.seg[0], sz=c.o.seg[3]-c.o.seg[1], SL=Math.hypot(sx,sz)||1; dx=-sz/SL; dz=sx/SL; L=1; } else return p; }
    const k=(R+.06+(c.o.t||0))/L, q=[c.x+dx*k,c.z+dz*k]; return clearAt(q[0],q[1])?q:p; }
  // spots along every piece of cover, both sides, every metre: what the AI chooses among
  const coverSpots=[];
  (function(){ const add=(x,z)=>{ if(!clearAt(x,z)) return; for(const s of coverSpots) if(Math.abs(s[0]-x)<.45&&Math.abs(s[1]-z)<.45) return; coverSpots.push([x,z]); };
    const off=R+.08;
    for(const o of obs){ if(o.kind==='edge'&&o.e.type==='door') continue;
      if(o.box){ const b=o.box; for(let x=b.x0+.5;x<b.x1;x+=1){ add(x,b.z0-off); add(x,b.z1+off); } for(let z=b.z0+.5;z<b.z1;z+=1){ add(b.x0-off,z); add(b.x1+off,z); } continue; }
      const [ax,az,bx,bz]=o.seg, L=Math.hypot(bx-ax,bz-az), ux=(bx-ax)/L, uz=(bz-az)/L, t=(o.t||0)+off;
      for(let s=.5;s<L;s+=1){ const x=ax+ux*s, z=az+uz*s; add(x-uz*t,z+ux*t); add(x+uz*t,z-ux*t); } } })();
  // stepping out from cover to see or shoot (XCOM's lean): sideways, perpendicular to the line to the target
  function leans(p,t){ if(coverFrom(p,t)===0) return []; const dx=t[0]-p[0], dz=t[1]-p[1], L=Math.hypot(dx,dz)||1, out=[];
    for(const s of [1,-1]){ const q=[p[0]-dz/L*LEAN*s,p[1]+dx/L*LEAN*s]; if(!clearAt(q[0],q[1],R*.8)) continue; const w=walk(p,q); if(w.ok&&!w.crossed.length) out.push(q); }
    return out; }
  // ---------- doors, windows and the way in ----------
  function entries(){ const out=[]; for(const o of obs){ if(o.kind!=='edge'||!o.ext) continue; const e=o.e; if(!/door|window/.test(e.type)) continue;
      const mx=(o.seg[0]+o.seg[2])/2, mz=(o.seg[1]+o.seg[3])/2, n=DIRS[e.dir], d=.65;
      const role=e.type==='window'?'window':(O.extDoors.find(x=>x.edges.includes(e))||{}).role||'side';
      out.push({o,e,key:e.key,kind:e.type==='window'?'window':e.type==='gdoor'?'garage':'door',role,out:[mx+n[0]*d,mz+n[1]*d],in:[mx-n[0]*d,mz-n[1]*d],dir:e.dir}); }
    return out; }
  function setDoor(key,state){ const d=O.extDoors.find(x=>x.edges.some(e=>e.key===key)); const keys=d?d.edges.map(e=>e.key):[key]; for(const k of keys) doorSt[LV+k]=state; }
  function setWindow(key,state){ const e=O.edges.get(key); if(e&&e.win) e.win.state=state; }
  const cellCentre=c=>[M.u0+(c%M.W)+.5,M.v0+((c/M.W)|0)+.5];
  const people=(G.D.people||[]).map(p=>({p:cellCentre(p.c),side:p.side,boss:!!p.boss}));
  function frontApproach(){ const d=O.front||O.extDoors[0]; if(!d) return null; const e=d.edges[0], en=entries().find(x=>x.e===e); return en; }
  // roles for the generator's people: a sentry at a street-side window looking out, the boss, the rest in camp
  function posted(seedStr){ const r=rngOf(seedStr||G.seedStr||'roles'), out=people.map(p=>({p:p.p.slice(),side:p.side,boss:p.boss,role:p.boss?'boss':'camp',face:r()*Math.PI*2}));
    const fa=frontApproach(), wins=entries().filter(e=>e.kind==='window'&&e.e.win.state!=='boarded'&&clearAt(e.in[0],e.in[1])&&!out.some(p=>Math.hypot(p.p[0]-e.in[0],p.p[1]-e.in[1])<1));
    const dd=p=>fa?Math.hypot(p[0]-fa.in[0],p[1]-fa.in[1]):0;
    wins.sort((a,b)=>((fa&&b.dir===fa.dir)-(fa&&a.dir===fa.dir))||dd(a.in)-dd(b.in));
    const s=out.find(p=>!p.boss); if(s&&wins.length){ s.p=wins[0].in.slice(); s.role='sentry'; s.face=Math.atan2(DIRS[wins[0].dir][0],DIRS[wins[0].dir][1]); s.window=wins[0].key; }
    // the generator places people on cell centres, which can sit tight against furniture: nudge each to clear floor
    for(const p of out) if(!clearAt(p.p[0],p.p[1])){ let best=null; for(let k=1;k<=24&&!best;k++){ const a=k*2.4, rr=.25+k*.06, q=[p.p[0]+Math.sin(a)*rr,p.p[1]+Math.cos(a)*rr]; if(clearAt(q[0],q[1])&&insideAt(q[0],q[1])) best=q; } if(best) p.p=best; }
    return out; }
  // ---------- explosions ----------
  // furniture blown apart stops being cover or an obstacle; the floor under it becomes rubble (slow)
  function destroyItem(o){ if(o.kind!=='item'||o.destroyed) return; o.destroyed=true; lows.push(o.box); const b=grow(o.box,1.6);
    for(let j=Math.max(0,Math.floor((b.z0-Z0)/NS));j<=Math.min(NH-1,Math.floor((b.z1-Z0)/NS));j++) for(let i=Math.max(0,Math.floor((b.x0-X0)/NS));i<=Math.min(NW-1,Math.floor((b.x1-X0)/NS));i++){
      const n=j*NW+i, x=nx(n), z=nz(n); free[n]=clearAt(x,z)?1:0; speed[n]=free[n]?speedAt(x,z):0; links[n]=undefined; } }
  function refreshField(box){ const b=grow(box,1.6);
    for(let j=Math.max(0,Math.floor((b.z0-Z0)/NS));j<=Math.min(NH-1,Math.floor((b.z1-Z0)/NS));j++) for(let i=Math.max(0,Math.floor((b.x0-X0)/NS));i<=Math.min(NW-1,Math.floor((b.x1-X0)/NS));i++){
      const n=j*NW+i, x=nx(n), z=nz(n); free[n]=clearAt(x,z)?1:0; speed[n]=free[n]?speedAt(x,z):0; links[n]=undefined; } }
  // Follow the interiors physics: props a grenade scattered or someone overturned sit where the change record says,
  // with the cover it says (rec.moved['level:id'] = {cells, cover, box:[x0,y0,z0,x1,y1,z1]}). A prop that no longer
  // blocks any cell lies flat: no cover, walkable.
  function syncMoves(rec){ const moved=(rec&&rec.moved)||{}; let n=0;
    for(const o of obs){ if(o.kind!=='item') continue; const mv=moved[LV+o.it.id]; if(!mv||o.mv===mv) continue;
      const old=o.box; fileObs(o,false); o.mv=mv; const b=mv.box; o.box={x0:b[0]+.04,z0:b[2]+.04,x1:b[3]-.04,z1:b[5]-.04}; o.h=b[4]-FY; o.cover=mv.cover; o.flat=!mv.cells||!mv.cells.length;
      if(o.flat) lows.push(o.box); fileObs(o,true); refreshField(old); refreshField(o.box); n++; }
    return n; }
  // Follow wall damage from the change record (rec.walls['level:key'] = {s}: 2 holed, 3 breached). A breached wall
  // becomes a way through; nodes near it are re-checked.
  function syncWalls(){ let n=0; for(const o of obs){ if(o.kind!=='edge'||o.e.type!=='wall'||o.portal) continue; const dm=wallSt[LV+o.e.key]; if(!dm||(dm.s||0)<3) continue;
      addPortal(o); const b=bboxOf(o); refreshField({x0:b.x0,z0:b.z0,x1:b.x1,z1:b.z1}); n++; } return n; }
  // what a blast at c reaches within r: furniture, doors and windows the blast can see (walls and closed doors shelter)
  function blastReach(c,r){ const items=[], openings=[], cand=[];
    near(c[0]-r,c[1]-r,c[0]+r,c[1]+r,o=>{ cand.push(o); });   // gather first: sight() searches the hash too, so it can't run inside near()
    for(const o of cand){ const q=o.box?ptBox(c[0],c[1],o.box):ptSeg(c[0],c[1],o.seg[0],o.seg[1],o.seg[2],o.seg[3]); if(q.d>r) continue;
      // look at the near face from a hair outside it, so the thing itself doesn't count as in the way
      const L=Math.max(q.d,1e-6), p=q.d<.05?[c[0],c[1]]:[q.x+(c[0]-q.x)/L*.06,q.z+(c[1]-q.z)/L*.06]; if(!sight(c,p,{shot:true})) continue;
      if(o.kind==='item'&&!o.destroyed) items.push(o); else if(o.kind==='edge'&&/door|window/.test(o.e.type)) openings.push(o); }
    return {items,openings}; }
  // doors between rooms, for watching doorways
  const innerDoors=()=>obs.filter(o=>o.kind==='edge'&&!o.ext&&/door/.test(o.e.type));
  return {G,R,EYE,FY,LV,destroyItem,blastReach,innerDoors,syncMoves,syncWalls,shotThrough,wallSt,X0,Z0,X1,Z1,obs,props,doorSt,doorState,sight,castRay,coverFrom,clearAt,walk,speedAt,field,costTo,pathTo,snap,nearestCover,coverSpots,leans,entries,setDoor,setWindow,people,posted,frontApproach,
    insideAt, floorY:(x,z)=>insideAt(x,z)?FY:0, NS, NW, NH, nodeX:nx, nodeZ:nz, nodeAt, free};
}
return {fromGenerated,R,EYE,DIRS,segSeg,segBox,ptSeg};
});
