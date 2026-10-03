// ---------- a generated building as a combat world ----------
// Turns the output of the interiors generator (tools/interiors, owned by the interiors topic) into what combat asks
// of any ground: cells with a centre and a floor height, who can step where and at what cost, whether sight passes
// between two cells, and how much cover a cell has toward a shooter. No rendering in here; it runs in Node for tests.
//
// Frame: the building's local frame (u along the footprint's main axis, v across it), 1 m cells. The interior grid
// is padded by `margin` cells of yard on every side, so the squad can start outside and come in through a door or a
// window. Walls live on cell edges (the generator's `O.edges`); furniture fills cells (`Fn.occ`).
(function(root,factory){ const m=factory(); if(typeof module==='object'&&module.exports) module.exports=m; else root.InteriorWorld=m; })(this,function(){
const DIRS=[[1,0],[0,1],[-1,0],[0,-1]];
// same keys as the generator's edgeKey(); the tests check they agree
function edgeKey(i,j,d){ if(d===0) return 'v'+(i+1)+','+j; if(d===2) return 'v'+i+','+j; if(d===1) return 'h'+i+','+(j+1); return 'h'+i+','+j; }
function rngOf(str){ let h=2166136261>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,16777619); } let a=h>>>0; return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }
const FY=.15, EYE=1.5, YARD=.8, PAVED=1, DEBRIS=.6;

// What an edge does to movement, sight and cover, from its type and current state.
// extra: effective metres added to a step through it (opening a door, climbing a window).
function edgeProps(e,doorState){
  switch(e.type){
    case 'wall': return {move:false,sight:false,shot:false,cover:2};
    case 'door': case 'gdoor': {
      const s=doorState(e);
      if(s==='open'||s==='broken') return {move:true,sight:true,shot:true,cover:0,extra:0};
      if(s==='closed') return {move:e.type==='door',sight:false,shot:false,cover:2,extra:1,opens:true};
      return {move:false,sight:false,shot:false,cover:2};                                   // barricaded, locked
    }
    case 'window': {
      const s=e.win.state;
      if(s==='boarded') return {move:false,sight:false,shot:false,cover:2};
      return {move:true,sight:true,shot:true,cover:1,extra:s==='intact'?5:4,glass:s==='intact',climb:true};   // the sill is half cover
    }
    case 'counter': return {move:true,sight:true,shot:true,cover:1,extra:3,climb:true};      // vault the counter
    case 'open': case 'none': return {move:true,sight:true,shot:true,cover:0,extra:0};
    default: return {move:false,sight:false,shot:false,cover:2};
  }
}

function distToSeg(px,pz,ax,az,bx,bz){ const dx=bx-ax, dz=bz-az, L=dx*dx+dz*dz||1; let t=((px-ax)*dx+(pz-az)*dz)/L; t=Math.max(0,Math.min(1,t)); return Math.hypot(px-ax-dx*t,pz-az-dz*t); }

function fromGenerated(G,opt={}){
  const margin=opt.margin==null?12:opt.margin;
  const {M,O,Fn}=G, m=margin, W=M.W+2*m, H=M.H+2*m, N=W*H;
  const x0=M.u0-m, z0=M.v0-m;                       // local-frame corner of cell 0
  const inside=new Uint8Array(N), item=new Int32Array(N).fill(-1), speed=new Float32Array(N), outCover=new Uint8Array(N), outSight=new Uint8Array(N);
  const cx=c=>x0+(c%W)+.5, cz=c=>z0+((c/W)|0)+.5;
  const idx=(i,j)=>(i<0||j<0||i>=W||j>=H)?-1:j*W+i;
  const cellAt=(x,z)=>idx(Math.floor(x-x0),Math.floor(z-z0));
  for(let j=0;j<M.H;j++) for(let i=0;i<M.W;i++){ const g=j*M.W+i; if(!M.mask[g]) continue; const c=(j+m)*W+i+m; inside[c]=1; item[c]=Fn.occ[g]; }
  // outside: yard, paved where a road runs, yard walls block (the generator's site carries roads and walls nearby)
  const roads=(G.site.roads||[]).map(r=>({w:r.w,pts:r.pts.map(p=>M.toL(p[0],p[1]))}));
  const walls=(G.site.walls||[]).map(w=>({a:M.toL(w[0],w[1]),b:M.toL(w[2],w[3]),h:w[4],t:w[5]}));
  for(let c=0;c<N;c++){
    if(inside[c]){ const it=item[c]>=0?Fn.items[item[c]]:null; speed[c]=!it?1:it.spec.h<.3?DEBRIS:0; continue; }
    const x=cx(c), z=cz(c); let s=YARD;
    for(const r of roads){ for(let k=0;k<r.pts.length-1;k++) if(distToSeg(x,z,r.pts[k][0],r.pts[k][1],r.pts[k+1][0],r.pts[k+1][1])<r.w/2){ s=PAVED; break; } if(s===PAVED) break; }
    for(const w of walls){ if(distToSeg(x,z,w.a[0],w.a[1],w.b[0],w.b[1])<w.t/2+.45){ s=0; outCover[c]=Math.max(outCover[c],w.h>=1.2?2:1); if(w.h>=EYE) outSight[c]=1; } }
    speed[c]=s;
  }
  // door states: an override map (the same shape the interiors renderer reads as rec.doors) over the generated state
  const doorSt=opt.doors||{};
  const doorState=e=>doorSt[e.key]!==undefined?doorSt[e.key]:(e.door.state==='broken'?'broken':e.door.state==='barricaded'?'barricaded':e.door.open?'open':'closed');
  const edge=(c,d)=>{ const n=step(c,d); if(n<0||!(inside[c]||inside[n])) return null; const e=O.edges.get(edgeKey((c%W)-m,((c/W)|0)-m,d)); return e||null; };
  const props=e=>edgeProps(e,doorState);
  function step(c,d){ return idx((c%W)+DIRS[d][0],((c/W)|0)+DIRS[d][1]); }
  const passable=c=>c>=0&&speed[c]>0;
  const itemAt=c=>c>=0&&item[c]>=0?Fn.items[item[c]]:null;
  // a cell that stops sight: tall, solid furniture (shelving, coolers, wardrobes) or a yard wall above eye height
  const blocksSight=c=>{ if(c<0) return true; if(inside[c]){ const it=itemAt(c); return !!(it&&it.spec.cover==='full'&&it.spec.h>=EYE); } return !!outSight[c]; };
  // no frame to clip: diagonal steps and leaning out only where there is no edge, or an open archway
  const edgeFree=(c,d)=>{ const e=edge(c,d); return !e||e.type==='none'||e.type==='open'; };
  const COV={none:0,half:1,full:2};
  // cover a cell gets from one side: the edge on that side, else whatever stands in the next cell
  function coverDir(c,d){ const e=edge(c,d), n=step(c,d); let v=e?props(e).cover:0;
    if(n>=0&&(!e||v===0)){ const it=itemAt(n); if(it) v=Math.max(v,COV[it.spec.cover]||0); if(!inside[n]) v=Math.max(v,outCover[n]); }
    return v; }
  function coverFrom(c,sx,sz){ const dx=sx-cx(c), dz=sz-cz(c), L=Math.hypot(dx,dz)||1; let v=0; for(let d=0;d<4;d++){ if((DIRS[d][0]*dx+DIRS[d][1]*dz)/L>.38) v=Math.max(v,coverDir(c,d)); } return v; }
  const hasFullCover=c=>{ for(let d=0;d<4;d++) if(coverDir(c,d)===2) return true; return false; };
  // stepping between neighbours: orthogonal steps through an edge pay its extra cost; diagonals only across open floor
  function neighbours(c){ const out=[], i=c%W, j=(c/W)|0, sa=speed[c];
    for(let d=0;d<4;d++){ const n=step(c,d); if(!passable(n)) continue; const e=edge(c,d); let extra=0; if(e){ const p=props(e); if(!p.move) continue; extra=p.extra||0; } out.push([n,1/((sa+speed[n])/2)+extra]); }
    for(const [di,dj] of [[1,1],[1,-1],[-1,1],[-1,-1]]){ const n=idx(i+di,j+dj); if(!passable(n)) continue; const dx=di>0?0:2, dz=dj>0?1:3, a=idx(i+di,j), b=idx(i,j+dj);
      if(!passable(a)||!passable(b)||!edgeFree(c,dx)||!edgeFree(c,dz)||!edgeFree(a,dz)||!edgeFree(b,dx)) continue; out.push([n,Math.SQRT2/((sa+speed[n])/2)]); }
    return out; }
  // sight from cell centre to cell centre: walk the cells the line crosses and test every edge it goes through.
  // Through an exact corner it may pass if either way round is clear.
  function sight(a,b,opt2){ if(a===b) return true; const shot=opt2&&opt2.shot;
    let i=a%W, j=(a/W)|0; const ib=b%W, jb=(b/W)|0, dx=ib-i, dy=jb-j, si=Math.sign(dx), sj=Math.sign(dy);
    const tdx=dx?1/Math.abs(dx):Infinity, tdy=dy?1/Math.abs(dy):Infinity; let tx=dx?.5/Math.abs(dx):Infinity, ty=dy?.5/Math.abs(dy):Infinity;
    const DX=si>0?0:2, DY=sj>0?1:3;
    const col=opt2&&opt2.collect, thru=(f,d,t)=>{ if(t<0) return false; const e=edge(f,d); if(e){ const p=props(e); if(!(shot?p.shot:p.sight)) return false; if(col) col.push(e); } return t===b||!blocksSight(t); };
    let guard=W+H+4;
    while((i!==ib||j!==jb)&&guard--){ const c=j*W+i;
      if(Math.abs(tx-ty)<1e-9){ const ca=idx(i+si,j), cb=idx(i,j+sj), cd=idx(i+si,j+sj);
        if(!((thru(c,DX,ca)&&thru(ca,DY,cd))||(thru(c,DY,cb)&&thru(cb,DX,cd)))) return false; i+=si; j+=sj; tx+=tdx; ty+=tdy; }
      else if(tx<ty){ if(!thru(c,DX,idx(i+si,j))) return false; i+=si; tx+=tdx; }
      else { if(!thru(c,DY,idx(i,j+sj))) return false; j+=sj; ty+=tdy; } }
    return true; }
  // edges a straight orthogonal step crosses (for opening doors and breaking glass on the way)
  function edgeBetween(a,b){ for(let d=0;d<4;d++) if(step(a,d)===b) return edge(a,d); return null; }
  // exterior openings: where the squad can stack and come in
  function entries(){ const out=[];
    const add=(e,kind,role,door)=>{ const ci=(e.j+m)*W+e.i+m, co=step(ci,e.dir); out.push({key:e.key,kind,role,door,edge:e,inCell:ci,outCell:co,dir:e.dir}); };
    for(const d of O.extDoors) for(const e of d.edges) add(e,e.type==='gdoor'?'garage':'door',d.role,d);
    for(const e of O.windows) if(e.ext) add(e,'window','window',null);
    return out; }
  function setDoor(key,state){ const d=O.extDoors.find(x=>x.edges.some(e=>e.key===key)); const keys=d?d.edges.map(e=>e.key):[key]; for(const k of keys) doorSt[k]=state; }
  function setWindow(key,state){ const e=O.edges.get(key); if(e&&e.win) e.win.state=state; }
  const people=(G.D.people||[]).map(p=>({c:(((p.c/M.W)|0)+m)*W+(p.c%M.W)+m,side:p.side,boss:!!p.boss}));
  // the front door's outside cell and its outward direction, for placing the squad
  function frontApproach(){ const d=O.front||O.extDoors[0]; if(!d) return null; const e=d.edges[0], ci=(e.j+m)*W+e.i+m; return {door:d,inCell:ci,outCell:step(ci,e.dir),dir:e.dir}; }
  // Roles for the people the generator put inside (combat-tasks 7d): one raider stands sentry at a window on the
  // street side looking out; the boss keeps near the stash; the rest idle where they are. Deterministic per building.
  function posted(seedStr){ const r=rngOf(seedStr||G.seedStr||'roles'), out=people.map(p=>Object.assign({},p,{role:p.boss?'boss':'camp',face:r()*Math.PI*2}));
    const fa=frontApproach(), taken=new Set(out.map(p=>p.c)), wins=entries().filter(e=>e.kind==='window'&&e.edge.win.state!=='boarded'&&passable(e.inCell)&&!itemAt(e.inCell)&&!taken.has(e.inCell));
    const near=c=>fa?Math.hypot(cx(c)-cx(fa.inCell),cz(c)-cz(fa.inCell)):0;
    wins.sort((a,b)=>((fa&&b.dir===fa.dir)-(fa&&a.dir===fa.dir))||near(a.inCell)-near(b.inCell));
    const s=out.find(p=>!p.boss);
    if(s&&wins.length){ s.c=wins[0].inCell; s.role='sentry'; s.face=Math.atan2(DIRS[wins[0].dir][0],DIRS[wins[0].dir][1]); s.window=wins[0].key; }
    return out; }
  return {G,W,H,N,margin:m,x0,z0,FY,inside,speed,doorSt,cx,cz,idx,cellAt,step,edge,props,doorState,passable,itemAt,blocksSight,edgeFree,coverDir,coverFrom,hasFullCover,neighbours,sight,edgeBetween,entries,setDoor,setWindow,people,posted,frontApproach,
    floorY:c=>inside[c]?FY:0, isInside:c=>!!inside[c]};
}
return {fromGenerated,edgeKey,edgeProps,DIRS,EYE};
});
