// Nightfall sector core: everything about a block of real terrain that doesn't need a renderer.
// The offline bake (Node) runs it over a whole block so sector edges match; the browser reads its output.
// Coordinates are metres in the block frame: x east, z south, origin at the block centre.
(function(root){
const TAU=Math.PI*2;
function rng(seed){ let x=seed>>>0||1; return ()=>{ x=(Math.imul(x,1664525)+1013904223)>>>0; return x/4294967296; }; }
const inPoly=(x,z,pts)=>{ let c=false; for(let i=0,j=pts.length-1;i<pts.length;j=i++){ const [xi,zi]=pts[i],[xj,zj]=pts[j]; if(((zi>z)!==(zj>z)) && x<(xj-xi)*(z-zi)/(zj-zi)+xi) c=!c; } return c; };
const segDist=(x,z,a,b)=>{ const dx=b[0]-a[0], dz=b[1]-a[1], l=dx*dx+dz*dz||1; let t=((x-a[0])*dx+(z-a[1])*dz)/l; t=Math.max(0,Math.min(1,t)); const px=a[0]+t*dx, pz=a[1]+t*dz; return [Math.hypot(x-px,z-pz),px,pz,t]; };
const bbox=pts=>{ let a=1e9,b=1e9,c=-1e9,d=-1e9; for(const [x,z] of pts){ a=Math.min(a,x); b=Math.min(b,z); c=Math.max(c,x); d=Math.max(d,z); } return [a,b,c,d]; };
const centroid=pts=>[pts.reduce((s,p)=>s+p[0],0)/pts.length, pts.reduce((s,p)=>s+p[1],0)/pts.length];
const area=pts=>{ let s=0; for(let i=0,j=pts.length-1;i<pts.length;j=i++) s+=(pts[j][0]+pts[i][0])*(pts[j][1]-pts[i][1]); return Math.abs(s/2); };
function densify(pts,step){ const out=[]; for(let i=0;i<pts.length-1;i++){ const a=pts[i], b=pts[i+1], L=Math.hypot(b[0]-a[0],b[1]-a[1]), n=Math.max(1,Math.ceil(L/step)); for(let k=0;k<n;k++) out.push([a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n]); } out.push(pts[pts.length-1]); return out; }
function polyDist(x,z,pts){ let d=1e9; for(let i=0,j=pts.length-1;i<pts.length;j=i++) d=Math.min(d,segDist(x,z,pts[j],pts[i])[0]); return d; }
function clipRect(pts,x0,z0,x1,z1){ let out=pts; const E=[[p=>p[0]>=x0,(a,b)=>[x0,a[1]+(b[1]-a[1])*(x0-a[0])/(b[0]-a[0])]],[p=>p[0]<=x1,(a,b)=>[x1,a[1]+(b[1]-a[1])*(x1-a[0])/(b[0]-a[0])]],
    [p=>p[1]>=z0,(a,b)=>[a[0]+(b[0]-a[0])*(z0-a[1])/(b[1]-a[1]),z0]],[p=>p[1]<=z1,(a,b)=>[a[0]+(b[0]-a[0])*(z1-a[1])/(b[1]-a[1]),z1]]];
  for(const [ins,cut] of E){ const inp=out; out=[]; for(let i=0;i<inp.length;i++){ const a=inp[(i+inp.length-1)%inp.length], b=inp[i]; if(ins(b)){ if(!ins(a)) out.push(cut(a,b)); out.push(b); } else if(ins(a)) out.push(cut(a,b)); } } return out; }
// cut a polyline to a rectangle; returns the pieces inside, each tagged with whether its ends are real or cut
function clipLine(pts,x0,z0,x1,z1){ const out=[]; let cur=null;
  for(let i=0;i<pts.length-1;i++){ const a=pts[i], b=pts[i+1], dx=b[0]-a[0], dz=b[1]-a[1]; let t0=0,t1=1, ok=true;
    for(const [p,q] of [[-dx,a[0]-x0],[dx,x1-a[0]],[-dz,a[1]-z0],[dz,z1-a[1]]]){ if(p===0){ if(q<0){ ok=false; break; } } else { const t=q/p; if(p<0){ if(t>t1){ ok=false; break; } if(t>t0) t0=t; } else { if(t<t0){ ok=false; break; } if(t<t1) t1=t; } } }
    if(!ok){ cur=null; continue; }
    if(!cur){ cur={pts:[[a[0]+dx*t0,a[1]+dz*t0]],cutStart:t0>0,cutEnd:false}; out.push(cur); }
    cur.pts.push([a[0]+dx*t1,a[1]+dz*t1]); cur.cutEnd=t1<1; if(t1<1) cur=null; }
  return out.filter(p=>p.pts.length>=2); }
const segX=(a,b,c,d)=>{ const r0=b[0]-a[0], r1=b[1]-a[1], s0=d[0]-c[0], s1=d[1]-c[1], den=r0*s1-r1*s0; if(Math.abs(den)<1e-9) return null; const t=((c[0]-a[0])*s1-(c[1]-a[1])*s0)/den, u=((c[0]-a[0])*r1-(c[1]-a[1])*r0)/den; return t>=0&&t<=1&&u>=0&&u<=1?[a[0]+r0*t,a[1]+r1*t,t,u]:null; };
const ROADW={motorway:16,trunk:14,primary:14,secondary:13,tertiary:10,secondary_link:7,tertiary_link:6,motorway_link:8,residential:8,unclassified:7,service:5,track:4,footway:2,path:1.5,cycleway:2,pedestrian:3,steps:2};
const roadW=r=>ROADW[r.cls]||4;
const isDrive=r=>!['footway','path','cycleway','steps','pedestrian','bridleway'].includes(r.cls);
const isPaved=r=>!(/unpaved|dirt|gravel|ground|compacted|sand/.test(r.surface||'') || r.cls==='track');
const isBridge=r=>!!r.bridge && r.bridge!=='no';
// what a road is made of: asphalt, concrete, gravel, dirt or sand (rd.surf from the road pass wins over the OSM tag)
function roadSurf(r){ if(r.surf) return r.surf; const s=r.surface||'';
  if(/concrete|paving/.test(s)) return 'concrete'; if(/sand/.test(s)) return 'sand'; if(/gravel|compacted|pebble/.test(s)) return 'gravel'; if(/unpaved|dirt|ground|earth|mud/.test(s)||r.cls==='track') return 'dirt'; return 'asphalt'; }
// a paved road's cross-section, offsets in metres from the centreline, + to the right of the way's direction
// pave: paved width; lines: {o,c:'w'|'y',w,dash:[on,off]|null}; lanes: centres of travel lanes {o,dir:+1 with the way, -1 against}
function roadSection(r){
  const W=r.w||roadW(r), cls=r.cls, surf=roadSurf(r), one=r.oneway==='yes'||r.oneway==='1'||r.oneway==='true', lf=r.lf||0, lb=r.lb||0;
  if(surf!=='asphalt'&&surf!=='concrete') return {pave:W,lines:[],lanes:[],unpaved:true};
  const link=/_link$/.test(cls), L=[], lanes=[];
  if(cls==='motorway'||(one&&(link||['trunk','primary','secondary','tertiary'].includes(cls)))){
    const n=Math.max(1,lf||(cls==='motorway'?2:1)), lw=3.7, ls=cls==='motorway'?1.5:1.2, rs=cls==='motorway'?3:2.4, pave=Math.min(W,n*lw+ls+rs), x0=-pave/2+ls;
    L.push({o:x0,c:'y',w:.15,dash:null},{o:x0+n*lw,c:'w',w:.15,dash:null}); for(let i=1;i<n;i++) L.push({o:x0+i*lw,c:'w',w:.12,dash:[3,9]});
    for(let i=0;i<n;i++) lanes.push({o:x0+(i+.5)*lw,dir:1});
    return {pave,lines:L,lanes,ls,rs,x0,x1:x0+n*lw,rumble:cls==='motorway'}; }
  if(['trunk','primary','secondary','tertiary'].includes(cls)){
    const nf=Math.max(1,lf||1), nb=Math.max(1,lb||1), twl=r.lanes>=3&&nf+nb===2?1:(r.lanes>nf+nb?1:0), lw=3.6, sh=cls==='tertiary'?1.2:1.8, mid=twl?3.6:0;
    const pave=Math.min(W,(nf+nb)*lw+mid+2*sh), half=pave/2, m=mid/2;
    if(twl) for(const sg of [-1,1]) L.push({o:sg*(m-.1),c:'y',w:.12,dash:[3,9]},{o:sg*(m+.05),c:'y',w:.12,dash:null});
    else if(cls==='tertiary') L.push({o:0,c:'y',w:.12,dash:[3,9]},{o:.22,c:'y',w:.12,dash:null,near:1},{o:-.22,c:'y',w:.12,dash:null,near:1});
    else L.push({o:-.13,c:'y',w:.12,dash:null},{o:.13,c:'y',w:.12,dash:null});
    for(let i=1;i<nf;i++) L.push({o:m+i*lw,c:'w',w:.12,dash:[3,9]}); for(let i=1;i<nb;i++) L.push({o:-(m+i*lw),c:'w',w:.12,dash:[3,9]});
    L.push({o:half-sh,c:'w',w:.12,dash:null},{o:-(half-sh),c:'w',w:.12,dash:null});
    for(let i=0;i<nf;i++) lanes.push({o:m+(i+.5)*lw,dir:1}); for(let i=0;i<nb;i++) lanes.push({o:-(m+(i+.5)*lw),dir:-1});
    return {pave,lines:L,lanes,sh,mid}; }
  // residential, unclassified, service and the rest: no paint, pavement nearly edge to edge
  const pave=cls==='residential'||cls==='unclassified'?Math.min(W,7.4):W;
  return {pave,lines:[],lanes:one?[{o:0,dir:1}]:[{o:pave/4,dir:1},{o:-pave/4,dir:-1}]}; }
const bridgeY=(b,t)=>b.e0+(b.e1-b.e0)*t+b.raise+(b.long?.3*Math.sin(Math.PI*t):0);
// a bucket grid of line segments, so "what's near here" doesn't scan every road in the block
class SegIndex{ constructor(cell=32){ this.c=cell; this.m=new Map(); }
  add(a,b,item,pad=0){ const c=this.c, i0=Math.floor((Math.min(a[0],b[0])-pad)/c), i1=Math.floor((Math.max(a[0],b[0])+pad)/c), j0=Math.floor((Math.min(a[1],b[1])-pad)/c), j1=Math.floor((Math.max(a[1],b[1])+pad)/c);
    for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++){ const k=i*73856093^j*19349663; let l=this.m.get(k); if(!l) this.m.set(k,l=[]); l.push([a,b,item]); } }
  near(x,z){ return this.m.get(Math.floor(x/this.c)*73856093^Math.floor(z/this.c)*19349663)||[]; } }
class BoxIndex{ constructor(cell=48){ this.c=cell; this.m=new Map(); }
  add(bb,item){ const c=this.c; for(let j=Math.floor(bb[1]/c);j<=Math.floor(bb[3]/c);j++) for(let i=Math.floor(bb[0]/c);i<=Math.floor(bb[2]/c);i++){ const k=i*73856093^j*19349663; let l=this.m.get(k); if(!l) this.m.set(k,l=[]); l.push(item); } }
  near(x,z){ return this.m.get(Math.floor(x/this.c)*73856093^Math.floor(z/this.c)*19349663)||[]; } }

// ---------- the bake ----------
function bake(D,log=()=>{}){
  const T=D.terrain, H=Float32Array.from(T.h), st=T.step, NXg=T.nx, NZg=T.nz, X0=T.x0, Z0=T.z0, HALF=D.half;
  const heightAt=(x,z)=>{ const fx=(x-X0)/st, fz=(z-Z0)/st, i=Math.max(0,Math.min(NXg-2,Math.floor(fx))), j=Math.max(0,Math.min(NZg-2,Math.floor(fz))), u=Math.min(1,Math.max(0,fx-i)), v=Math.min(1,Math.max(0,fz-j)), h=(a,b)=>H[b*NXg+a];
    return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; };
  const forCells=(a,b,c,d,fn)=>{ const i0=Math.max(0,Math.floor((a-X0)/st)), i1=Math.min(NXg-1,Math.ceil((c-X0)/st)), j0=Math.max(0,Math.floor((b-Z0)/st)), j1=Math.min(NZg-1,Math.ceil((d-Z0)/st)); for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++) fn(j*NXg+i,X0+i*st,Z0+j*st); };
  const cellsNear=(pts,pad,fn)=>{ for(let k=0;k<pts.length-1;k++){ const a=pts[k], b=pts[k+1]; forCells(Math.min(a[0],b[0])-pad,Math.min(a[1],b[1])-pad,Math.max(a[0],b[0])+pad,Math.max(a[1],b[1])+pad,(id,x,z)=>{ const [dd,px,pz,t]=segDist(x,z,a,b); if(dd<pad) fn(id,dd,px,pz,k,t); }); } };
  const slopeAt=(x,z)=>{ const e=2, gx=(heightAt(x+e,z)-heightAt(x-e,z))/(2*e), gz=(heightAt(x,z+e)-heightAt(x,z-e))/(2*e); return Math.atan(Math.hypot(gx,gz))*180/Math.PI; };
  const lim=[-HALF,-HALF,HALF,HALF], rivers=D.water.filter(w=>w.kind==='river');
  // features
  const F={beds:[],lakes:[],pools:[],bridges:[],culverts:[]};
  for(const a of D.areas){
    if((a.kind==='scree'||a.kind==='sand') && rivers.some(w=>w.pts.some(p=>inPoly(p[0],p[1],a.pts)))) F.beds.push({pts:clipRect(a.pts,lim[0]-130,lim[1]-130,lim[2]+130,lim[3]+130),raw:a.pts});
    if(['water','reservoir','basin'].includes(a.kind)) F.lakes.push({raw:a.pts,name:a.name||''});
    if(a.kind==='swimming_pool') F.pools.push({pts:a.pts}); }
  F.beds=F.beds.filter(b=>b.pts.length>=3);
  const WASH=w=>w.kind==='river'?(F.beds.length&&w.name==='New River'?{hw:7,depth:.9}:{hw:11,depth:2.6}):{hw:5,depth:1.6};
  D.roads.forEach((r,i)=>{ r.id=i; if(isBridge(r)&&isDrive(r)) F.bridges.push({road:i,pts:r.pts,w:roadW(r),name:r.name||''}); });
  for(const w of D.water) for(const r of D.roads){ if(!isDrive(r)||isBridge(r)||!isPaved(r)||r.tunnel) continue;
    for(let i=1;i<w.pts.length;i++) for(let k=1;k<r.pts.length;k++){ const p=segX(w.pts[i-1],w.pts[i],r.pts[k-1],r.pts[k]); if(!p||Math.abs(p[0])>HALF||Math.abs(p[1])>HALF) continue;
      const rl=Math.hypot(r.pts[k][0]-r.pts[k-1][0],r.pts[k][1]-r.pts[k-1][1])||1;
      F.culverts.push({x:p[0],z:p[1],rx:(r.pts[k][0]-r.pts[k-1][0])/rl,rz:(r.pts[k][1]-r.pts[k-1][1])/rl,rhw:roadW(r)/2,...WASH(w)}); } }
  // 1. river beds
  for(const bed of F.beds){ const [a,b,c,d]=bbox(bed.pts); forCells(a,b,c,d,(id,x,z)=>{ if(inPoly(x,z,bed.pts)) H[id]-=Math.min(2.2,polyDist(x,z,bed.raw)*.45); }); }
  log('beds');
  // 2. paved road cores keep their crossings (culverts)
  const core=new Uint8Array(H.length), chan=new Uint8Array(H.length);
  for(const r of D.roads){ if(!isDrive(r)||isBridge(r)||!isPaved(r)||r.tunnel) continue; cellsNear(r.pts,roadW(r)/2+1.5,id=>{ core[id]=1; }); }
  // 3. washes run downhill
  for(const w of D.water){ const {hw,depth}=WASH(w), d=densify(w.pts,2).filter(([x,z])=>Math.abs(x)<HALF+D.margin&&Math.abs(z)<HALF+D.margin); if(d.length<2) continue;
    const raw=d.map(([x,z])=>heightAt(x,z)), bed=raw.map((_,i)=>{ let s=0,c=0; for(let q=-4;q<=4;q++){ s+=raw[Math.max(0,Math.min(raw.length-1,i+q))]; c++; } return s/c-depth; });
    for(let i=1;i<bed.length;i++) bed[i]=Math.min(bed[i],bed[i-1]);
    cellsNear(d,hw,(id,dd,px,pz,k,t)=>{ if(core[id]) return; const tg=bed[k]+(bed[k+1]-bed[k])*t+depth*(dd/hw)**2; if(tg<H[id]){ H[id]=tg; chan[id]=1; } }); }
  log('washes');
  // 4. lakes
  for(const L of F.lakes){ let lv=1e9; for(const [x,z] of L.raw) if(Math.abs(x)<HALF&&Math.abs(z)<HALF) lv=Math.min(lv,heightAt(x,z)); if(lv>1e8) lv=heightAt(...centroid(L.raw)); L.level=lv-.35;
    const [a,b,c,d]=bbox(L.raw); forCells(a-6,b-6,c+6,d+6,(id,x,z)=>{ const e=polyDist(x,z,L.raw); if(inPoly(x,z,L.raw)) H[id]=Math.min(H[id],L.level-Math.min(2.6,.5+e*.35)); else if(e<6){ const want=L.level+.35; if(H[id]<want) H[id]+=(want-H[id])*(1-e/6); } }); }
  // 5. bridges
  for(const b of F.bridges){ const d=densify(b.pts,2), L=[0]; for(let i=1;i<d.length;i++) L.push(L[i-1]+Math.hypot(d[i][0]-d[i-1][0],d[i][1]-d[i-1][1]));
    const len=L[L.length-1], long=len>40; Object.assign(b,{d,L,len,long,hw:b.w/2+.9,depth:long?1.5:.9});
    const tan=k=>{ const p=d[Math.max(0,k-1)], q=d[Math.min(d.length-1,k+1)], l=Math.hypot(q[0]-p[0],q[1]-p[1])||1; return [(q[0]-p[0])/l,(q[1]-p[1])/l]; };
    const endH=p=>{ let s=0,n=0; for(const dx of [-3,0,3]) for(const dz of [-3,0,3]){ s+=heightAt(p[0]+dx,p[1]+dz); n++; } return s/n; };
    b.e0=endH(d[0]); b.e1=endH(d[d.length-1]);
    b.over=D.roads.some(r=>r.id!==b.road&&isDrive(r)&&!isBridge(r)&&r.pts.some((p,i)=>i&&b.pts.some((q,k)=>{ if(!k) return false; const x=segX(r.pts[i-1],p,b.pts[k-1],q); return x&&Math.hypot(x[0]-b.pts[0][0],x[1]-b.pts[0][1])>3&&Math.hypot(x[0]-b.pts[b.pts.length-1][0],x[1]-b.pts[b.pts.length-1][1])>3; })));
    b.clear=(b.over?5.3:3.4)+b.depth; b.raise=0;
    let need=0; for(let k=0;k<d.length;k++){ if(L[k]<5||len-L[k]<5) continue; const [tx,tz]=tan(k); let g=-1e9; for(const o of [-b.hw,0,b.hw]) g=Math.max(g,heightAt(d[k][0]+tz*o,d[k][1]-tx*o)); need=Math.max(need,g+b.clear-(b.e0+(b.e1-b.e0)*L[k]/len)); }
    const dig=Math.min(need,3); b.raise=need-dig; b.ramp=Math.max(18,b.raise*11); b.ab=Math.min(4,len*.2); const slope=long?7:4;
    cellsNear(d,b.hw+3,(id,dd,px,pz,k,t)=>{ const s=L[k]+(L[k+1]-L[k])*t, y=bridgeY(b,s/len), f=dd<b.hw?1:1-(dd-b.hw)/3, e=Math.max(0,Math.min(1,(Math.min(s,len-s)-b.ab)/slope));
      const tg=e<=0?y-.2:(y-.2)*(1-e)+Math.min(H[id],y-b.clear)*e; H[id]+=(tg-H[id])*f; }); }
  log('bridges');
  // 6. roads graded; paved ones ramp onto decks, tracks ford washes
  const ends=F.bridges.flatMap(b=>[[b.d[0],bridgeY(b,0),b.ramp],[b.d[b.d.length-1],bridgeY(b,1),b.ramp]]);
  for(const r of D.roads){ if(!isDrive(r)||isBridge(r)) continue; const hw=roadW(r)/2;
    const S=[0]; for(let k=1;k<r.pts.length;k++) S.push(S[k-1]+Math.hypot(r.pts[k][0]-r.pts[k-1][0],r.pts[k][1]-r.pts[k-1][1]));
    const tot=S[S.length-1], ns=Math.max(2,Math.ceil(tot/4)+1), ss=[], raw=[];
    for(let q=0;q<ns;q++){ const s=tot*q/(ns-1); let k=0; while(k<r.pts.length-2&&S[k+1]<s) k++; const t=(s-S[k])/((S[k+1]-S[k])||1), x=r.pts[k][0]+(r.pts[k+1][0]-r.pts[k][0])*t, z=r.pts[k][1]+(r.pts[k+1][1]-r.pts[k][1])*t; ss.push([x,z]); raw.push(heightAt(x,z)); }
    const prof=raw.map((_,i)=>{ let s2=0,c=0; for(let q=-5;q<=5;q++){ s2+=raw[Math.max(0,Math.min(raw.length-1,i+q))]; c++; } return s2/c; });
    const mine=ends.filter(([p])=>[r.pts[0],r.pts[r.pts.length-1]].some(q=>Math.hypot(q[0]-p[0],q[1]-p[1])<3));
    for(let i=0;i<ns;i++) for(const [p,y,R] of mine){ const dd=Math.hypot(ss[i][0]-p[0],ss[i][1]-p[1]); if(dd<R){ const k=1-dd/R; prof[i]+=(y-prof[i])*k*k*(3-2*k); } }
    const profAt=(k,t)=>{ const s=S[k]+(S[k+1]-S[k])*t, f=s/(tot||1)*(ns-1), i=Math.min(ns-2,Math.floor(f)); return prof[i]+(prof[i+1]-prof[i])*(f-i); };
    const edits=[]; cellsNear(r.pts,hw+(mine.length?14:4),(id,dd,px,pz,k,t)=>{ if(chan[id]&&!core[id]) return; const tg=profAt(k,t), band=Math.max(3.2,Math.abs(tg-H[id])*2.2); if(dd>hw+.8+band) return; edits.push([id,tg,dd<hw+.8?1:1-(dd-hw-.8)/band]); });
    for(const [id,tg,f] of edits) H[id]+=(tg-H[id])*f; }
  log('roads');
  // 7. building pads
  for(const b of D.buildings){ if(b.pts.length<3) continue; const pad=b.pts.reduce((s2,[x,z])=>s2+heightAt(x,z),0)/b.pts.length, [a0,b0,c0,d0]=bbox(b.pts);
    forCells(a0-5,b0-5,c0+5,d0+5,(id,x,z)=>{ let dd=inPoly(x,z,b.pts)?0:1e9; if(dd) for(let k=0;k<b.pts.length;k++) dd=Math.min(dd,segDist(x,z,b.pts[k],b.pts[(k+1)%b.pts.length])[0]);
      const f=dd<1.5?1:dd>5?0:1-(dd-1.5)/3.5; H[id]+=(pad-H[id])*f; }); }
  // 8. pools
  for(const P of F.pools){ const hs=P.pts.map(([x,z])=>heightAt(x,z)); P.level=Math.max(...hs)+.08; P.low=Math.min(...hs); }
  log('shaped');

  // ---------- indexes for placement ----------
  const RI=new SegIndex(32); for(const r of D.roads){ const pad=roadW(r)/2+3; for(let k=1;k<r.pts.length;k++) RI.add(r.pts[k-1],r.pts[k],r,pad); }
  const nearRoad=(x,z,pad=0,drive=false)=>{ for(const [a,b,r] of RI.near(x,z)){ if(drive&&!isDrive(r)) continue; if(segDist(x,z,a,b)[0]<roadW(r)/2+pad) return true; } return false; };
  const nearestRoadPoint=(x,z)=>{ let best=[1e9,0,0]; for(const cell of [[0,0],[32,0],[-32,0],[0,32],[0,-32]]) for(const [a,b,r] of RI.near(x+cell[0],z+cell[1])){ if(!isDrive(r)) continue; const d=segDist(x,z,a,b); if(d[0]<best[0]) best=d; } return best; };
  const WI=new SegIndex(32); for(const w of D.water){ const hw=WASH(w).hw; for(let k=1;k<w.pts.length;k++) WI.add(w.pts[k-1],w.pts[k],hw,hw+10); }
  const washDist=(x,z)=>{ let best=1e9; for(const [a,b,hw] of WI.near(x,z)) best=Math.min(best,segDist(x,z,a,b)[0]-hw); return best; };
  const BI=new BoxIndex(48); D.buildings.forEach(b=>{ if(b.pts.length>=3){ b.bb=bbox(b.pts); BI.add([b.bb[0]-2,b.bb[1]-2,b.bb[2]+2,b.bb[3]+2],b); } });
  const nearBuilding=(x,z,pad)=>BI.near(x,z).some(b=>x>b.bb[0]-pad&&x<b.bb[2]+pad&&z>b.bb[1]-pad&&z<b.bb[3]+pad&&(pad>0||inPoly(x,z,b.pts)));
  const blockedA=new Set(['retail','commercial','parking','swimming_pool','pitch','playground','water','industrial']);
  const AI=new BoxIndex(64); D.areas.forEach(a=>{ a.bb=bbox(a.pts); AI.add(a.bb,a); });
  const areaAt=(x,z,pred)=>AI.near(x,z).some(a=>pred(a)&&x>a.bb[0]&&x<a.bb[2]&&z>a.bb[1]&&z<a.bb[3]&&inPoly(x,z,a.pts));
  const LI=new BoxIndex(64); F.lakes.forEach(l=>{ l.bb=bbox(l.raw); LI.add([l.bb[0]-4,l.bb[1]-4,l.bb[2]+4,l.bb[3]+4],l); });
  const inBed=(x,z)=>F.beds.some(b=>inPoly(x,z,b.pts));

  // ---------- walls: mapped barriers, and generated backyard block walls behind houses ----------
  const walls=[]; for(const w of D.barriers){ const fence=/fence|gate/.test(w.kind); for(let i=0;i<w.pts.length-1;i++) walls.push([...w.pts[i],...w.pts[i+1],fence?1.4:1.8,fence?.08:.2,fence?1:0]); }
  const houses=D.buildings.filter(b=>b.pts.length>=3&&(b.type==='house'||b.type==='detached'||(b.type==='yes'&&area(b.pts)>70&&area(b.pts)<450&&areaAt(...centroid(b.pts),a=>a.kind==='residential'))));
  const inAnyBuilding=(x,z)=>BI.near(x,z).some(b=>x>b.bb[0]-.5&&x<b.bb[2]+.5&&z>b.bb[1]-.5&&z<b.bb[3]+.5&&inPoly(x,z,b.pts));
  for(const h of houses){ const [cx,cz]=centroid(h.pts), [dist,rx,rz]=nearestRoadPoint(cx,cz); if(dist>60) continue; h.house=true;
    let fx=rx-cx, fz=rz-cz; const fl=Math.hypot(fx,fz)||1; fx/=fl; fz/=fl; const sx=-fz, sz=fx;
    const Fv=h.pts.map(([x,z])=>(x-cx)*fx+(z-cz)*fz), Sd=h.pts.map(([x,z])=>(x-cx)*sx+(z-cz)*sz);
    const fmin=Math.min(...Fv), fmax=Math.max(...Fv), smin=Math.min(...Sd)-1.6, smax=Math.max(...Sd)+1.6, back=fmin-8.5, side=fmin+(fmax-fmin)*.35, Wp=(s,f)=>[cx+sx*s+fx*f, cz+sz*s+fz*f];
    for(const [a,b] of [[Wp(smin,side),Wp(smin,back)],[Wp(smin,back),Wp(smax,back)],[Wp(smax,back),Wp(smax,side)]]){ const L=Math.hypot(b[0]-a[0],b[1]-a[1]), n=Math.max(1,Math.round(L/2));
      for(let i=0;i<n;i++){ const p=[a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n], q=[a[0]+(b[0]-a[0])*(i+1)/n,a[1]+(b[1]-a[1])*(i+1)/n], mx=(p[0]+q[0])/2, mz=(p[1]+q[1])/2;
        if(Math.abs(mx)>HALF-1||Math.abs(mz)>HALF-1||nearRoad(mx,mz,.8)||inAnyBuilding(mx,mz)) continue; walls.push([...p,...q,1.8,.2,0]); } } }
  log('walls');

  // ---------- plants ----------
  const r=rng(23), plants=[], step=6.5, P=(t,x,y,z,sx,sy,sz,rx,ry)=>plants.push([t,+x.toFixed(2),+y.toFixed(2),+z.toFixed(2),+sx.toFixed(2),+sy.toFixed(2),+sz.toFixed(2),+rx.toFixed(2),+ry.toFixed(2)]);
  for(let x=-HALF+3;x<HALF-3;x+=step) for(let z=-HALF+3;z<HALF-3;z+=step){
    const px=x+(r()-.5)*step, pz=z+(r()-.5)*step;
    if(nearBuilding(px,pz,1.5) || areaAt(px,pz,a=>blockedA.has(a.kind)) || nearRoad(px,pz,1.2)){ r(); r(); continue; }
    const tame=areaAt(px,pz,a=>a.kind==='residential'||a.kind==='park'||a.kind==='grass'), v=r(), y=heightAt(px,pz), s=.75+r()*.5, rot=r()*TAU, sl=slopeAt(px,pz), wd=washDist(px,pz);
    if(LI.near(px,pz).some(l=>!inPoly(px,pz,l.raw)&&polyDist(px,pz,l.raw)<3.5)){ if(v<.5) P(4,px,y,pz,s,s,s,0,rot); else if(v<.7) P(3,px,y,pz,s*.7,s*.5,s*.7,0,rot); continue; }
    if(LI.near(px,pz).some(l=>inPoly(px,pz,l.raw))) continue;
    if(inBed(px,pz)){ if(v<.08) P(3,px,y,pz,s*.6,s*.4,s*.6,0,rot); else if(v<.11) P(2,px,y,pz,s*.7,s*.7,s*.7,0,rot); continue; }
    if(wd<-1){ if(v<.12) P(3,px,y,pz,s*.5,s*.4,s*.5,0,rot); continue; }
    if(!tame && wd<7){ if(v<.45) P(1,px,y,pz,s*1.25,s*1.25,s*1.25,0,rot); else if(v<.8) P(2,px,y,pz,s*1.1,s*1.1,s*1.1,0,rot); continue; }
    if(!tame && sl>9){ if(v<.3) P(3,px,y,pz,s*(1+r()),s*(.8+r()*.7),s*(1+r()),r(),rot); else if(v<.42) P(0,px,y-.2,pz,s,s*(.8+r()*.5),s,0,rot); else if(v<.62) P(2,px,y,pz,s*.8,s*.8,s*.8,0,rot); continue; }
    if(tame){ if(v<.2) P(1,px,y,pz,s,s,s,0,rot); else if(v<.36) P(2,px,y,pz,s*.8,s*.8,s*.8,0,rot); else if(v<.4) P(3,px,y,pz,s*.6,s*.6,s*.6,0,rot); continue; }
    if(v<.06) P(0,px,y-.2,pz,s,s*(.8+r()*.5),s,0,rot); else if(v<.2) P(1,px,y,pz,s*1.1,s*1.1,s*1.1,0,rot); else if(v<.62) P(2,px,y,pz,s,s,s,0,rot); else if(v<.7) P(3,px,y,pz,s*(.6+r()),s*(.6+r()*.6),s*(.6+r()),0,rot); }
  for(const t of D.trees){ if(Math.abs(t[0])<HALF&&Math.abs(t[1])<HALF) P(1,t[0],heightAt(t[0],t[1]),t[1],1.2,1.2,1.2,0,r()*TAU); }
  log('plants '+plants.length);

  // ---------- movement grid (2 m) over the block ----------
  const NS=2, NX=Math.round(2*HALF/NS), N=NX*NX, surf=new Float32Array(N), kind=new Uint8Array(N), brush=new Float32Array(N), sp=new Float32Array(N);
  const NK=NAVKIND, cX=i=>-HALF+(i+.5)*NS;
  const cells=(a0,b0,c0,d0,fn)=>{ const i0=Math.max(0,Math.floor((a0+HALF)/NS)), i1=Math.min(NX-1,Math.floor((c0+HALF)/NS)), j0=Math.max(0,Math.floor((b0+HALF)/NS)), j1=Math.min(NX-1,Math.floor((d0+HALF)/NS)); for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++) fn(j*NX+i,cX(i),cX(j)); };
  const line=(pts,pad,fn)=>{ for(let k=0;k<pts.length-1;k++){ const a=pts[k], b=pts[k+1]; cells(Math.min(a[0],b[0])-pad,Math.min(a[1],b[1])-pad,Math.max(a[0],b[0])+pad,Math.max(a[1],b[1])+pad,(id,x,z)=>{ if(segDist(x,z,a,b)[0]<pad) fn(id,x,z); }); } };
  const set=(id,k,s)=>{ kind[id]=k; surf[id]=s; };
  for(let id=0;id<N;id++) set(id,NK.open,.72);
  for(const a of D.areas){ const k=['parking','retail','commercial','industrial'].includes(a.kind)?NK.lot:['residential','grass','park','playground','pitch'].includes(a.kind)?NK.yard:-1; if(k<0) continue; cells(...a.bb,(id,x,z)=>{ if(inPoly(x,z,a.pts)) set(id,k,k===NK.lot?1:.8); }); }
  for(const bed of F.beds){ const bb=bbox(bed.pts); cells(...bb,(id,x,z)=>{ if(inPoly(x,z,bed.pts)) set(id,NK.wash,.58); }); }
  for(const w of D.water) line(w.pts,WASH(w).hw*.8,id=>set(id,NK.wash,.58));
  for(const rd of [...D.roads].sort((a,b)=>roadW(a)-roadW(b))){ if(isBridge(rd)) continue; const k=!isDrive(rd)?NK.path:isPaved(rd)?NK.asphalt:NK.dirt; line(rd.pts,roadW(rd)/2+.3,id=>set(id,k,k===NK.asphalt?1:k===NK.path?.95:.86)); }
  const PW=[.25,.1,.16,.14,.2];
  for(const p of plants){ const rr=p[0]===1?1.8:1.2; cells(p[1]-rr,p[3]-rr,p[1]+rr,p[3]+rr,id=>{ brush[id]+=PW[p[0]]; }); }
  for(let j=0;j<NX;j++) for(let i=0;i<NX;i++){ const id=j*NX+i, x=cX(i), z=cX(j), sl=slopeAt(x,z), k=kind[id], road=k===NK.asphalt||k===NK.dirt||k===NK.path||k===NK.lot;
    const slopeF=sl<4?1:Math.max(.28,1-(sl-4)/30), brushF=road?1:Math.max(.42,1-brush[id]);
    if(!road&&brush[id]>.12&&(k===NK.open||k===NK.wash)) kind[id]=NK.brush; else if(!road&&sl>14&&k===NK.open) kind[id]=NK.hill;
    sp[id]=surf[id]*slopeF*brushF; if(sl>36&&!road){ kind[id]=NK.steep; sp[id]=0; } }
  for(const L of F.lakes) cells(...L.bb,(id,x,z)=>{ if(inPoly(x,z,L.raw)){ kind[id]=NK.water; sp[id]=SWIM; } });
  for(const Pl of F.pools) cells(...bbox(Pl.pts),(id,x,z)=>{ if(inPoly(x,z,Pl.pts)){ kind[id]=NK.water; sp[id]=SWIM; } });
  for(const b of D.buildings){ if(b.pts.length<3||b.type==='carport'||b.type==='roof') continue; cells(...b.bb,(id,x,z)=>{ if(inPoly(x,z,b.pts)){ kind[id]=NK.building; sp[id]=0; } }); }
  for(const w of walls) line([[w[0],w[1]],[w[2],w[3]]],1.05,id=>{ kind[id]=NK.wall; sp[id]=0; });
  // piers and the ground under decks without headroom
  const piers=[];
  for(const b of F.bridges){ const spans=b.long?Math.max(2,Math.round(b.len/24)):1, tan=k=>{ const p=b.d[Math.max(0,k-1)], q=b.d[Math.min(b.d.length-1,k+1)], l=Math.hypot(q[0]-p[0],q[1]-p[1])||1; return [(q[0]-p[0])/l,(q[1]-p[1])/l]; };
    b.piers=[];
    for(let q=1;q<spans;q++){ const s=b.ab+(b.len-2*b.ab)*q/spans; let k=0; while(k<b.d.length-1&&b.L[k+1]<s) k++; const [tx,tz]=tan(k), x=b.d[k][0]+tx*(s-b.L[k]), z=b.d[k][1]+tz*(s-b.L[k]);
      for(const o of (b.w>9?[-.62,0,.62]:[-.5,.5])){ const off=o*(b.hw-1.2), cx=x+tz*off, cz=z-tx*off; b.piers.push([+cx.toFixed(2),+cz.toFixed(2),+heightAt(cx,cz).toFixed(2)]); cells(cx-1.4,cz-1.4,cx+1.4,cz+1.4,(id,x2,z2)=>{ if(Math.hypot(x2-cx,z2-cz)<1.3){ kind[id]=NK.pier; sp[id]=0; } }); } }
    line(b.d,b.hw,(id,x,z)=>{ let best=null; for(let k=0;k<b.d.length-1;k++){ const sd=segDist(x,z,b.d[k],b.d[k+1]); if(sd[0]<=b.hw&&(!best||sd[0]<best[0])) best=[sd[0],b.L[k]+(b.L[k+1]-b.L[k])*sd[3]]; }
      if(best && bridgeY(b,best[1]/b.len)-b.depth-heightAt(x,z)<2.1){ kind[id]=NK.low; sp[id]=0; } }); }
  log('nav');
  // camps in the undercroft of long bridges
  const camps=F.bridges.filter(b=>b.len>90).map(b=>{ const s=b.ab+9; let k=0; while(k<b.d.length-1&&b.L[k+1]<s) k++; return {bridge:F.bridges.indexOf(b),k}; });
  return {H,NXg,NZg,X0,Z0,st,F,walls,plants,nav:{NS,NX,sp,kind},houses:new Set(houses),camps,WASH};
}
const NAVKIND={open:0,asphalt:1,dirt:2,path:3,lot:4,yard:5,wash:6,brush:7,hill:8,water:9,building:10,wall:11,steep:12,low:13,pier:14};
const NAVLABEL=['Open desert','Asphalt','Dirt road','Footpath','Paved lot','Yard','Sand wash','Brush','Hillside','Water','Building','Wall','Too steep','No headroom','Bridge pier'];
const SWIM=.2;
const api={TAU,rng,inPoly,segDist,bbox,centroid,area,densify,polyDist,clipRect,clipLine,segX,ROADW,roadW,isDrive,isPaved,isBridge,roadSurf,roadSection,bridgeY,SegIndex,BoxIndex,bake,NAVKIND,NAVLABEL,SWIM};
if(typeof module!=='undefined') module.exports=api; else root.SectorCore=api;
})(typeof self!=='undefined'?self:this);
