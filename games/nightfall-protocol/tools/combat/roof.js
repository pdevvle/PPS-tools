// ---------- the roof: a second level to fight on ----------
// Units carry a level, lv: 0 on the ground (inside or out), 1 on the roof. The roof is its own free space for moving
// (the building's footprint, edged by the outside walls as a parapet; holes are blocked, like furniture), so the
// same field, routes and snapping work up there. Sight between levels is decided here:
//   roof ↔ outside ground  over the edge, only from within EDGE m of it (you have to look over);
//   roof ↔ inside          only through a hole, from its rim, down to targets within DOWN m of the hole;
//   roof ↔ roof            the roof space's own sight.
// Holes come from a Breacher's charge set on the roof. Ladders on outside walls join the levels.
const RoofDeck=(()=>{
const EDGE=2.0, PEEK=1.1, DOWN=6.5, HOLE_R=1.0;
function make(G,w,SPACE,opt={}){
  const M=G.M, H=w.FY+G.wallH, holes=[], DIRS=[[1,0],[0,1],[-1,0],[0,-1]];
  const cellXY=c=>[M.u0+(c%M.W)+.5,M.v0+((c/M.W)|0)+.5];
  // outside walls become the parapet: solid segments the roof space cannot be walked off through
  const exts=[...G.O.edges.values()].filter(e=>e.ext).map(e=>({key:e.key,type:'wall',a:0,b:-1,dir:e.dir,i:e.i,j:e.j,ext:true,mat:'block',th:.15}));
  let space=null;
  function rebuild(){
    const items=holes.map((h,k)=>({id:k,key:'hole',cells:h.cells,f:0,i:0,j:0,spec:{h:1,cover:'none',w:1,d:1}}));
    const GR={site:{walls:[],roads:[]},M,O:{edges:new Map(exts.map(e=>[e.key,e])),extDoors:[],front:null},Fn:{items},D:{people:[]},level:0,seedStr:'roof'};
    space=SPACE.fromGenerated(GR,{margin:1});
    api.space=space; return space; }
  // ladders: [i, j, side] on an outside wall (side as the generator's direction index)
  const ladders=(opt.ladders||[]).map(([i,j,d],k)=>{ const e=G.O.edges.get(opt.edgeKey(i,j,d)); if(!e||!e.ext) throw new Error('roof: no outside wall for ladder '+k);
    const o=e.key[0], [p,q]=e.key.slice(1).split(',').map(Number), m=o==='v'?[M.u0+p,M.v0+q+.5]:[M.u0+p+.5,M.v0+q], n=DIRS[e.dir];
    return {k,e,m,n,foot:[m[0]+n[0]*.6,m[1]+n[1]*.6],top:[m[0]-n[0]*.65,m[1]-n[1]*.65],plane:[m[0]+n[0]*.12,m[1]+n[1]*.12],yaw:Math.atan2(-n[0],-n[1]),H}; });
  // where the line from a roof point toward q leaves the footprint, just past the wall
  function edgeExit(pa,q){ const dx=q[0]-pa[0], dz=q[1]-pa[1], L=Math.hypot(dx,dz); if(L<1e-6) return null;
    for(let s=0;s<=L;s+=.1){ const x=pa[0]+dx/L*s, z=pa[1]+dz/L*s; if(!w.insideAt(x,z)){ const t=Math.min(L,s+.35); return {at:s,p:[pa[0]+dx/L*t,pa[1]+dz/L*t],rim:[pa[0]+dx/L*Math.max(0,s-.35),pa[1]+dz/L*Math.max(0,s-.35)]}; } }
    return null; }
  // can someone on the roof at pa see (or shoot) the ground point q? Returns how: over the edge or down a hole
  function view(pa,q,shot){
    if(!w.insideAt(q[0],q[1])){ const e=edgeExit(pa,q); if(e&&e.at<=EDGE&&space.sight(pa,e.rim)&&w.sight(e.p,q,{shot})) return {kind:'edge',p:e.p}; }
    else for(const h of holes){ if(Math.hypot(h.c[0]-pa[0],h.c[1]-pa[1])>h.r+PEEK) continue; if(Math.hypot(q[0]-h.c[0],q[1]-h.c[1])>DOWN) continue;
      if(w.sight(h.c,q,{shot})) return {kind:'hole',p:h.c,h}; }
    return null; }
  // the rules ask this for any pair where someone is on the roof: {from, to, walls, via} or null
  function lineOf(a,b,o={}){ const la=a.lv||0, lb=b.lv||0, pa=[a.x,a.z], pb=[b.x,b.z], shot=o.shot!==false;
    if(la&&lb) return space.sight(pa,pb,{shot})?{from:pa,to:pb,walls:0}:null;
    if(!la&&lb){ const r=lineOf(b,a,o); return r&&{from:r.to,to:r.from,walls:0,via:r.via}; }
    const v=view(pa,pb,shot); return v&&{from:pa,to:pb,walls:0,via:v}; }
  // the target's cover against the shooter, across levels: the parapet or a hole's rim is half cover; shooting down
  // over furniture, full cover counts as half
  function coverOf(b,a){ const la=a.lv||0, lb=b.lv||0;
    if(la&&lb) return space.coverFrom([b.x,b.z],[a.x,a.z]);
    if(lb) return 1;
    const v=view([a.x,a.z],[b.x,b.z],true); if(!v) return 2; return Math.min(1,w.coverFrom([b.x,b.z],v.p)); }
  // a breaching charge on the roof: a 2 × 2 m hole at the nearest cell corner, inside the footprint
  function addHole(p){ const roomOf=G.P.roomOf, corners=[];
    for(const ci of [Math.floor(p[0]-M.u0),Math.ceil(p[0]-M.u0),Math.round(p[0]-M.u0)-1,Math.round(p[0]-M.u0)+1]) for(const cj of [Math.floor(p[1]-M.v0),Math.ceil(p[1]-M.v0),Math.round(p[1]-M.v0)-1,Math.round(p[1]-M.v0)+1]) corners.push([ci,cj]);
    corners.sort((a,b)=>Math.hypot(M.u0+a[0]-p[0],M.v0+a[1]-p[1])-Math.hypot(M.u0+b[0]-p[0],M.v0+b[1]-p[1]));
    for(const [ci,cj] of corners){ if(Math.hypot(M.u0+ci-p[0],M.v0+cj-p[1])>1.3) break; const cells=[]; let room=null, ok=true;
      for(const [di,dj] of [[-1,-1],[0,-1],[-1,0],[0,0]]){ const i=ci+di, j=cj+dj, c=j*M.W+i; if(i<0||j<0||i>=M.W||j>=M.H||!M.mask[c]||holes.some(h=>h.cells.includes(c))){ ok=false; break; }
        if(room===null) room=roomOf[c]; else if(roomOf[c]!==room){ ok=false; break; } cells.push(c); }   // a hole opens into one room, never over a wall
      if(!ok) continue; const h={c:[M.u0+ci,M.v0+cj],r:HOLE_R,cells,room}; holes.push(h); rebuild(); return h; }
    return null; }
  // where a body lands dropping through a hole: the floor under it, or the nearest clear spot
  function landing(h){ for(let r=0;r<=1.2;r+=.2) for(let k=0;k<(r?12:1);k++){ const a=k/12*Math.PI*2, q=[h.c[0]+Math.sin(a)*r,h.c[1]+Math.cos(a)*r]; if(w.clearAt(q[0],q[1])) return q; } return null; }
  const holeNear=(p,r)=>holes.find(h=>Math.hypot(h.c[0]-p[0],h.c[1]-p[1])<=h.r+(r==null?PEEK:r));
  const onRoof=(x,z)=>w.insideAt(x,z)&&!holes.some(h=>h.cells.includes(Math.floor(z-M.v0)*M.W+Math.floor(x-M.u0)));
  const api={H,holes,ladders,view,lineOf,coverOf,addHole,landing,holeNear,onRoof,cellXY,rebuild,EDGE,PEEK,DOWN,space:null};
  rebuild(); return api; }
return {make,EDGE,PEEK,DOWN};
})();
if(typeof module!=='undefined') module.exports=RoofDeck;
