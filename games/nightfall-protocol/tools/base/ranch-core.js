// ---------- the ranch: building's rules (the logistic layer) ----------
// Placing things on the 2 m movement grid, the tasks they offer, survivors walking to them, water draining.
// No rendering, so the same file runs in the page and in Node (tools/base/test.js). Plain data in, plain data out.
// Needs and job choice belong to people.md and stores to settlement.md: the numbers marked WORKING are stand-ins.
const Ranch=(()=>{
const VERSION=1;
// movement kinds, the same values as SectorCore.NAVKIND
const NK={open:0,asphalt:1,dirt:2,path:3,lot:4,yard:5,wash:6,brush:7,hill:8,water:9,building:10,wall:11,steep:12,low:13,pier:14};
const BLOCKS=new Set([NK.building,NK.wall,NK.water,NK.steep,NK.low,NK.pier]);
const COVER={none:0,half:1,full:2};
const WALK=5000/60;   // metres per game minute at speed 1 (5 km/h on asphalt)

// ---------- WORKING values (people.md and settlement.md own these) ----------
// water: the foundation's 0.5 L per person per hour, doubled from 10:00 to 18:00
const waterRate=min=>{ const h=hourOf(min); return h>=10&&h<18?1:.5; };
const THIRSTY=4, DEHYDRATED=8, DRINK_AT=2;   // litres behind
const START_STOCK={water:400,food:30,medicine:4,tools:6,fuel:10,gear:6,shelter:20,goods:5};   // units as Campaign.UNIT
const BARRELS=400, TANK=1000, SEEP_DAY=25, PUMP_DAY=60, PUMP_HOUR=15, CARRY_WATER=20;
const NAMES=['Rosa','Eli','Marisol','Dale','Nita','Tomas','June','Abel','Ines','Walt','Lupe','Cass'];

// ---------- the first ten things (tools/base/DESIGN.md) ----------
// size in cells (w across x, d along z, before rotation), cost in stock units, hours of work at average skill,
// what the finished thing writes into the grid, the tasks it offers
const CATALOG={
  wall:     {label:'Wall',         w:1,d:1, cost:{shelter:1},         hours:1,   kind:NK.wall,     cover:COVER.full, drag:true},
  gate:     {label:'Gate',         w:1,d:1, cost:{shelter:1,tools:1}, hours:1.5, kind:NK.wall,     cover:COVER.full, gate:true},
  barricade:{label:'Barricade',    w:1,d:1, cost:{shelter:1},         hours:.5,  kind:NK.wall,     cover:COVER.half, drag:true},
  bed:      {label:'Bed',          w:1,d:2, cost:{shelter:1},         hours:1,   speed:.6,          offers:['sleep']},
  ramada:   {label:'Shade ramada', w:2,d:2, cost:{shelter:2},         hours:2,   offers:['rest_shade']},
  tank:     {label:'Water tank',   w:2,d:2, cost:{shelter:4,tools:2}, hours:6,   kind:NK.building, cover:COVER.full, water:TANK, offers:['drink','fill']},
  seep:     {label:'Wash seep',    w:1,d:1, cost:{},                  hours:6,   on:NK.wash,        offers:['collect_water']},
  pump:     {label:'Hand pump',    w:1,d:1, cost:{tools:4},           hours:4,   cover:COVER.half,  repair:true, offers:['pump']},
  garden:   {label:'Garden bed',   w:3,d:3, cost:{shelter:1,water:5}, hours:2,   speed:.8,          offers:['tend']},
  kitchen:  {label:'Kitchen',      w:2,d:2, cost:{shelter:2,tools:1}, hours:3,   kind:NK.building, cover:COVER.full, offers:['cook']},
  watch:    {label:'Watch post',   w:2,d:2, cost:{shelter:3,tools:1}, hours:6,   kind:NK.building, cover:COVER.half, offers:['watch']},
};
const TEAR={hours:4, gives:{shelter:6}};   // tearing down a claimed outbuilding

// ---------- helpers ----------
const mod=m=>((m%1440)+1440)%1440;
const hourOf=min=>mod(min)/60;
const fmt=m=>{ const d=Math.floor(m/1440)+1, h=Math.floor(mod(m)/60), mm=Math.floor(mod(m)%60); return `Day ${d} ${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}`; };
function unb64(s){ if(typeof Buffer!=='undefined') return new Uint8Array(Buffer.from(s,'base64')); const b=atob(s), a=new Uint8Array(b.length); for(let i=0;i<b.length;i++) a[i]=b.charCodeAt(i); return a; }
function rng(seed){ let x=seed>>>0||1; return ()=>{ x=(Math.imul(x,1664525)+1013904223)>>>0; return x/4294967296; }; }
const inPoly=(x,z,pts)=>{ let c=false; for(let i=0,j=pts.length-1;i<pts.length;j=i++){ const [xi,zi]=pts[i],[xj,zj]=pts[j]; if(((zi>z)!==(zj>z)) && x<(xj-xi)*(z-zi)/(zj-zi)+xi) c=!c; } return c; };
const centroid=pts=>[pts.reduce((s,p)=>s+p[0],0)/pts.length, pts.reduce((s,p)=>s+p[1],0)/pts.length];

// ---------- the site: heights and the grid ----------
function siteOf(raw){ const S=Object.assign({},raw), Hi=new Int16Array(unb64(raw.H).buffer.slice(0)), n=raw.hn;
  S.Hf=new Float32Array(n*n); for(let i=0;i<n*n;i++) S.Hf[i]=Hi[i]/100;
  S.N=raw.nav.n; S.NS=raw.nav.step; S.kind0=unb64(raw.nav.kind); S.sp0=unb64(raw.nav.sp); return S; }
function heightAt(S,x,z){ const n=S.hn, fx=(x-S.x0+4)/4, fz=(z-S.z0+4)/4, i=Math.max(0,Math.min(n-2,Math.floor(fx))), j=Math.max(0,Math.min(n-2,Math.floor(fz))), u=fx-i, v=fz-j, H=S.Hf, h=(a,b)=>H[b*n+a];
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; }
let st=null;   // the state the helpers below work on (set by use())
const S=()=>st.site;
const cellOf=(x,z)=>{ const s=S(), i=Math.floor((x-s.x0)/s.NS), j=Math.floor((z-s.z0)/s.NS); return i>=0&&j>=0&&i<s.N&&j<s.N?j*s.N+i:-1; };
const cellXZ=c=>{ const s=S(); return [s.x0+(c%s.N+.5)*s.NS, s.z0+(Math.floor(c/s.N)+.5)*s.NS]; };
const cellIJ=c=>[c%S().N, Math.floor(c/S().N)];
const idOf=(i,j)=>{ const N=S().N; return i>=0&&j>=0&&i<N&&j<N?j*N+i:-1; };
const passable=c=>c>=0 && st.grid.sp[c]>0 && (st.grid.gate[c]===1 || !BLOCKS.has(st.grid.kind[c]));
const speedOf=c=>passable(c)?(st.grid.gate[c]?.8:st.grid.sp[c]/250):0;
function inArea(c){ const [x,z]=cellXZ(c), a=S().area; return x>a[0]&&x<a[2]&&z>a[1]&&z<a[3]; }
function nearestPassable(c,pred=passable){ const N=S().N, [ci,cj]=cellIJ(c); if(pred(c)) return c;
  for(let r=1;r<30;r++){ let best=-1,bd=1e9; for(let dj=-r;dj<=r;dj++) for(let di=-r;di<=r;di++){ if(Math.max(Math.abs(di),Math.abs(dj))!==r) continue; const id=idOf(ci+di,cj+dj); if(id>=0&&pred(id)){ const d=di*di+dj*dj; if(d<bd){ bd=d; best=id; } } } if(best>=0) return best; } return -1; }

// ---------- paths: A* over the 2 m grid, cost is time at terrain speed (as the streaming page) ----------
function findPath(from,to){ if(from<0||to<0||!passable(to)) return null; if(from===to) return {cells:[from],cost:0};
  const N=S().N, g=new Float32Array(N*N).fill(Infinity), came=new Int32Array(N*N).fill(-1), closed=new Uint8Array(N*N), heap=[], [tx,tz]=cellXZ(to);
  const push=(f,n)=>{ heap.push([f,n]); let i=heap.length-1; while(i>0){ const p=(i-1)>>1; if(heap[p][0]<=heap[i][0]) break; [heap[p],heap[i]]=[heap[i],heap[p]]; i=p; } };
  const pop=()=>{ const top=heap[0], last=heap.pop(); if(heap.length){ heap[0]=last; let i=0; for(;;){ const l=2*i+1, r=l+1; let m=i; if(l<heap.length&&heap[l][0]<heap[m][0]) m=l; if(r<heap.length&&heap[r][0]<heap[m][0]) m=r; if(m===i) break; [heap[m],heap[i]]=[heap[i],heap[m]]; i=m; } } return top; };
  const h=n=>{ const [x,z]=cellXZ(n); return Math.hypot(x-tx,z-tz); };
  g[from]=0; push(h(from),from);
  while(heap.length){ const [,n]=pop(); if(closed[n]) continue; closed[n]=1; if(n===to) break; const i=n%N, j=(n-i)/N, sa=Math.max(speedOf(n),.05);
    for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ if(!di&&!dj) continue; const m=idOf(i+di,j+dj); if(m<0||closed[m]||!passable(m)) continue;
      if(di&&dj&&(!passable(idOf(i+di,j))||!passable(idOf(i,j+dj)))) continue;   // no squeezing between two blocked corners
      const c=g[n]+S().NS*(di&&dj?Math.SQRT2:1)/((sa+speedOf(m))/2); if(c<g[m]){ g[m]=c; came[m]=n; push(c+h(m),m); } } }
  if(!closed[to]) return null; const cells=[]; for(let n=to;n>=0;n=came[n]) cells.push(n); cells.reverse(); return {cells,cost:g[to]}; }
// straighten a cell path where the straight line keeps to cells at least as fast
function smooth(cells){ const pts=cells.map(cellXZ), out=[pts[0]]; let i=0;
  const ok=(a,b)=>{ const L=Math.hypot(b[0]-a[0],b[1]-a[1]), n=Math.ceil(L/.6), s0=Math.min(speedOf(cellOf(...a)),speedOf(cellOf(...b)))*.97; for(let q=1;q<n;q++){ const c=cellOf(a[0]+(b[0]-a[0])*q/n,a[1]+(b[1]-a[1])*q/n); if(c<0||speedOf(c)<s0||speedOf(c)<=0) return false; } return true; };
  while(i<pts.length-1){ let j=Math.min(pts.length-1,i+30); while(j>i+1&&!ok(pts[i],pts[j])) j--; out.push(pts[j]); i=j; } return out; }

// ---------- a new ranch ----------
function create(raw,{seed=20261004,people=6,minutes=5*60}={}){
  const site=siteOf(raw), N=site.N;
  st={v:VERSION, seed, rng:seed>>>0, minutes, site, seq:1, things:[], people:[], stock:Object.assign({},START_STOCK), heatWork:false, log:[],
    grid:{kind:Uint8Array.from(site.kind0), sp:Uint8Array.from(site.sp0), cover:new Uint8Array(N*N), gate:new Uint8Array(N*N), occ:new Int32Array(N*N)}, places:{}};
  const G=st.grid; for(let c=0;c<N*N;c++) if(G.kind[c]===NK.building||G.kind[c]===NK.wall) G.cover[c]=COVER.full;
  // claimed buildings: each gets its cells and a door (the passable cell nearest its middle, on the yard side)
  st.claimed={}; const mid=[(site.area[0]+site.area[2])/2,(site.area[1]+site.area[3])/2];
  for(const b of site.buildings){ if(!b.claim) continue; const [cx,cz]=centroid(b.pts), cells=[]; for(let c=0;c<N*N;c++){ const [x,z]=cellXZ(c); if(G.kind[c]===NK.building&&inPoly(x,z,b.pts)) cells.push(c); }
    const dx=mid[0]-cx, dz=mid[1]-cz, dl=Math.hypot(dx,dz)||1, door=nearestPassable(cellOf(cx+dx/dl*3,cz+dz/dl*3));
    st.claimed[b.claim]={claim:b.claim, pts:b.pts, cells, door, torn:false, order:null}; }
  st.places={home:st.claimed.house.door, store:st.claimed.barn.door, work:st.claimed.shed.door};
  // the old well beside the barn: its electric pump is dead, a hand pump is a repair (lore.md)
  { const c=nearestPassable(cellOf(702,36),q=>passable(q)&&!st.grid.occ[q]); addThing('pump',c,0,'broken'); }
  const r=rand, home=cellXZ(st.places.home);
  for(let k=0;k<people;k++){ const fem=k%2===1; st.people.push({id:'p'+(k+1), name:NAMES[k%NAMES.length], seed:900+k*37, fem, x:home[0]+(r()-.5)*4, z:home[1]+(r()-.5)*4,
    behind:r()*1.2 /*litres of water behind*/, skill:{building:2+Math.floor(r()*7)}, task:null, inside:false, asleep:false, act:'idle', drank:0}); }
  note('The ranch at dawn. Six people, 400 L of water in the house barrels.');
  return st; }
function use(s){ st=s; return st; }
const rand=()=>{ st.rng=(Math.imul(st.rng,1664525)+1013904223)>>>0; return st.rng/4294967296; };
function note(msg){ st.log.unshift({t:st.minutes,msg}); if(st.log.length>60) st.log.length=60; }

// ---------- placing things ----------
// footprint cells for a type at a corner cell; rot 1 swaps width and depth
function footprint(type,c,rot=0){ const T=CATALOG[type], [i0,j0]=cellIJ(c), w=rot%2?T.d:T.w, d=rot%2?T.w:T.d, out=[]; for(let j=0;j<d;j++) for(let i=0;i<w;i++){ const id=idOf(i0+i,j0+j); if(id<0) return null; out.push(id); } return out; }
function canPlace(type,c,rot=0){ const T=CATALOG[type]; if(!T||T.repair) return {ok:false,why:T&&T.repair?'Repair the old well instead':'Unknown thing'};
  const cells=footprint(type,c,rot); if(!cells) return {ok:false,why:'Off the site'};
  for(const q of cells){ if(!inArea(q)) return {ok:false,why:'Outside the buildable area'}; if(st.grid.occ[q]) return {ok:false,why:'Something is already there'};
    const k=st.grid.kind[q]; if(T.on!==undefined?k!==T.on:!passable(q)) return {ok:false,why:T.on===NK.wash?'A seep has to be dug in the sand wash':'The ground is blocked'}; }
  return {ok:true,cells}; }
function addThing(type,c,rot,state='site'){ const T=CATALOG[type], cells=footprint(type,c,rot), id='t'+st.seq++;
  const t={id, type, cell:c, rot, cells, state, progress:0, delivered:Object.keys(T.cost).length===0, pool:0, pumped:0, day:-1, tended:-1, by:null};
  for(const q of cells) st.grid.occ[q]=st.seq-1; st.things.push(t); return t; }
function place(type,c,rot=0){ const ok=canPlace(type,c,rot); if(!ok.ok) return null; const t=addThing(type,c,rot); return t; }
// a straight line of walls or barricades in one of eight directions, as dragged
function lineCells(a,b){ const [ai,aj]=cellIJ(a), [bi,bj]=cellIJ(b), di=bi-ai, dj=bj-aj, n=Math.max(Math.abs(di),Math.abs(dj)), out=[];
  const ang=Math.round(Math.atan2(dj,di)/(Math.PI/4)), si=Math.round(Math.cos(ang*Math.PI/4)), sj=Math.round(Math.sin(ang*Math.PI/4));
  for(let k=0;k<=n;k++){ const id=idOf(ai+si*k,aj+sj*k); if(id>=0) out.push(id); } return out; }
function placeLine(type,a,b){ const out=[]; for(const c of lineCells(a,b)) if(canPlace(type,c).ok) out.push(place(type,c)); return out; }
function cancel(id){ const t=st.things.find(q=>q.id===id); if(!t||t.state==='done'||t.state==='broken') return false;
  if(t.delivered) for(const [k,n] of Object.entries(CATALOG[t.type].cost)) st.stock[k]=(st.stock[k]||0)+n;   // the materials go back to the store
  for(const q of t.cells) st.grid.occ[q]=0; st.things=st.things.filter(q=>q!==t); for(const p of st.people) if(p.task&&p.task.thing===t) p.task=null; return true; }
function orderRepair(){ const t=st.things.find(q=>q.type==='pump'&&q.state==='broken'); if(!t) return null; t.state='site'; t.delivered=false; note('Ordered: repair the old well with a hand pump.'); return t; }
function orderTear(claim){ const b=st.claimed[claim]; if(!b||b.torn||b.order||!/outbuilding/.test(claim)) return false; b.order={progress:0,by:null}; note('Ordered: tear down an outbuilding for materials.'); return true; }

// what a finished thing does to the grid: this is the interface combat and pathing read (kind, speed, cover)
function finish(t){ const T=CATALOG[t.type], G=st.grid; t.state='done';
  for(const q of t.cells){ if(T.kind!==undefined){ G.kind[q]=T.kind; } if(T.speed) G.sp[q]=Math.round(G.sp[q]*T.speed); if(T.cover!==undefined) G.cover[q]=T.cover; if(T.gate) G.gate[q]=1; }
  if(T.kind!==undefined) for(const p of st.people){ const c=cellOf(p.x,p.z); if(t.cells.includes(c)){ const q=nearestPassable(c); [p.x,p.z]=cellXZ(q); } }   // step off a cell that just became solid
  note(`${T.label} finished.`); }
function tearDown(b){ const G=st.grid; for(const q of b.cells){ G.kind[q]=NK.open; G.sp[q]=180; G.cover[q]=0; } b.torn=true; b.order=null;
  for(const [k,n] of Object.entries(TEAR.gives)) st.stock[k]=(st.stock[k]||0)+n; note(`An outbuilding came down: +${TEAR.gives.shelter} materials.`); }

// ---------- water ----------
const waterCap=()=>BARRELS+st.things.filter(t=>t.type==='tank'&&t.state==='done').length*TANK;
const waterPoints=()=>[st.places.home,...st.things.filter(t=>t.type==='tank'&&t.state==='done').map(accessOf)];
const dailyUse=()=>{ let s=0; for(let m=0;m<1440;m+=10) s+=waterRate(m)/6; return s*st.people.length; };

// ---------- tasks: what things offer, chosen by a stand-in for people.md's utility score ----------
// where to stand to work on a thing: on it if it is passable furniture, else the passable cell next to it nearest home
function accessOf(t){ const T=CATALOG[t.type]; if(T.kind===undefined){ const c=t.cells.find(passable); if(c!==undefined) return c; }
  const [hx,hz]=cellXZ(st.places.home); let best=-1,bd=1e9; for(const q of t.cells){ const [i,j]=cellIJ(q); for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ const m=idOf(i+di,j+dj); if(m<0||t.cells.includes(m)||!passable(m)) continue; const [x,z]=cellXZ(m), d=Math.hypot(x-hx,z-hz); if(d<bd){ bd=d; best=m; } } } return best; }
const dayOf=m=>Math.floor(m/1440);
const night=m=>{ const h=hourOf(m); return h>=22||h<5; };
const heat=m=>{ const h=hourOf(m); return h>=10&&h<18; };
function costOK(t){ if(t.delivered) return true; for(const [k,n] of Object.entries(CATALOG[t.type].cost)) if((st.stock[k]||0)<n) return false; return true; }
function busyOn(thing){ return st.people.some(p=>p.task&&p.task.thing===thing); }
function distTo(p,c){ const [x,z]=cellXZ(c); return Math.hypot(x-p.x,z-p.z); }

function choose(p){ const m=st.minutes, opts=[], add=(score,make)=>opts.push([score,make]);
  const exposed=s=>heat(m)&&!st.heatWork?s*.05:s;   // outdoor work waits for the cool hours unless ordered
  if(p.behind>=DRINK_AT&&st.stock.water>.5) add(60+p.behind*10,()=>{ const wp=nearestOf(p,waterPoints()); return {kind:'drink',steps:[{go:wp},{do:'drink',min:3}]}; });
  if(night(m)){
    const post=st.things.find(t=>t.type==='watch'&&t.state==='done'&&!busyOn(t));
    if(post&&(p.watched||0)<=Math.min(...st.people.map(q=>q.watched||0))) add(58,()=>(p.watched=(p.watched||0)+1,{kind:'watch',thing:post,steps:[{go:accessOf(post)},{do:'watch',until:'dawn',act:'idle'}]}));
    const bed=st.things.find(t=>t.type==='bed'&&t.state==='done'&&!busyOn(t)&&(!t.owner||t.owner===p.id));
    add(55,()=>bed?(bed.owner=p.id,{kind:'sleep',thing:bed,steps:[{go:accessOf(bed)},{do:'sleep',until:'dawn',bed:true}]}):{kind:'sleep',steps:[{go:st.places.home},{do:'sleep',until:'dawn',inside:true}]}); }
  else {
    for(const t of st.things){ if(t.state!=='site'||busyOn(t)||!costOK(t)||t.blockedUntil>m) continue; const d=distTo(p,t.cells[0]);
      add(exposed(40-d/20+(p.skill.building||0)*.3),()=>({kind:t.type==='pump'?'repair':'build',thing:t,steps:[...(t.delivered?[]:[{go:st.places.store},{do:'take',min:2}]),{go:accessOf(t),carry:!t.delivered},{do:'work',act:'work'}]})); }
    for(const b of Object.values(st.claimed)) if(b.order&&!st.people.some(q=>q.task&&q.task.claimed===b)){ const d=distTo(p,b.door); add(exposed(36-d/20),()=>({kind:'tear',claimed:b,steps:[{go:nearestPassable(b.cells[0])},{do:'tear',act:'work'}]})); }
    const cap=waterCap()-st.stock.water;
    for(const t of st.things){ if(t.state!=='done'||busyOn(t)) continue;
      if(t.type==='seep'&&t.pool>=5&&cap>=5) add(exposed(32),()=>({kind:'collect_water',thing:t,steps:[{go:accessOf(t)},{do:'collect',min:20,act:'work'},{go:nearestOf(t,waterPoints()),carry:true},{do:'deliver',min:3}]}));
      if(t.type==='pump'&&t.pumped<PUMP_DAY&&cap>=5) add(exposed(30),()=>({kind:'pump',thing:t,steps:[{go:accessOf(t)},{do:'pump',min:60,act:'work'}]}));
      if(t.type==='garden'&&t.tended<dayOf(m)&&st.stock.water>=3) add(exposed(34),()=>({kind:'tend',thing:t,steps:[{go:accessOf(t)},{do:'tend',min:40,act:'work'}]})); }
    if(heat(m)){ const shade=[st.places.home,...st.things.filter(t=>t.type==='ramada'&&t.state==='done').map(accessOf)], s=nearestOf(p,shade);
      add(10,()=>({kind:'rest_shade',steps:[{go:s},{do:'rest',min:45,inside:s===st.places.home}]})); } }
  add(1,()=>{ const [hx,hz]=cellXZ(st.places.home), a=rand()*Math.PI*2, r=4+rand()*10, c0=nearestPassable(cellOf(hx+Math.cos(a)*r,hz+Math.sin(a)*r)), c=c0>=0?c0:st.places.home; return {kind:'idle',steps:[{go:c},{do:'idle',min:15+rand()*25}]}; });
  opts.sort((a,b)=>b[0]-a[0]); const task=opts[0][1](); task.step=-1; task.score=opts[0][0]; return task; }
function nearestOf(p,cells){ let best=cells[0],bd=1e9; const x=p.x!==undefined?p.x:cellXZ(p.cells[0])[0], z=p.z!==undefined?p.z:cellXZ(p.cells[0])[1]; for(const c of cells){ const [cx,cz]=cellXZ(c), d=Math.hypot(cx-x,cz-z); if(d<bd){ bd=d; best=c; } } return best; }

// ---------- one person over dt game minutes ----------
function startStep(p){ const T=p.task; T.step++; const s=T.steps[T.step]; if(!s){ p.task=null; return; }
  p.inside=false; p.asleep=false; s.left=s.min||0;
  if(s.go!==undefined){ const from=nearestPassable(cellOf(p.x,p.z)), path=findPath(from,s.go);
    if(!path){ if(T.thing) T.thing.blockedUntil=st.minutes+60; note(`${p.name} can't reach the ${T.thing?CATALOG[T.thing.type].label.toLowerCase():'spot'}.`); p.task=null; return; }
    s.pts=smooth(path.cells); s.k=1; } }
function stepPerson(p,dt){ const m=st.minutes;
  p.behind+=waterRate(m)*dt/60;   // WORKING: people.md owns the rate
  const urgent=p.behind>=THIRSTY&&st.stock.water>.5&&(!p.task||p.task.kind!=='drink');
  if(urgent&&p.task&&p.task.kind!=='sleep') leave(p);
  if(!p.task){ p.task=choose(p); startStep(p); if(!p.task) return; }
  let left=dt;
  while(left>1e-6&&p.task){ const T=p.task, s=T.steps[T.step];
    if(s.go!==undefined){ const tgt=s.pts[s.k]; if(!tgt){ startStep(p); continue; }
      const sp=WALK*Math.max(.15,speedOf(cellOf(p.x,p.z))||.3)*(p.behind>=DEHYDRATED?.6:p.behind>=THIRSTY?.8:1), dx=tgt[0]-p.x, dz=tgt[1]-p.z, d=Math.hypot(dx,dz), can=sp*left;
      p.act=s.carry?'carry':'walk'; if(d>1e-6) p.heading=Math.atan2(dx,dz);
      if(can>=d){ p.x=tgt[0]; p.z=tgt[1]; left-=d/sp; s.k++; if(s.k>=s.pts.length) startStep(p); } else { p.x+=dx/d*can; p.z+=dz/d*can; left=0; }
      continue; }
    p.act=s.act||'idle'; p.inside=!!s.inside;
    switch(s.do){
      case 'drink': { const take=Math.min(p.behind,st.stock.water); st.stock.water-=take; p.behind-=take; p.drank+=take; s.left-=left; left=0; if(s.left<=0) startStep(p); break; }
      case 'take': { const t=T.thing; if(!t.delivered){ if(!costOK(t)){ p.task=null; break; } for(const [k,n] of Object.entries(CATALOG[t.type].cost)) st.stock[k]-=n; t.delivered=true; } startStep(p); break; }
      case 'work': { const t=T.thing, rate=.6+.08*(p.skill.building||0), need=CATALOG[t.type].hours*60, use=Math.min(left,(need-t.progress)/rate);
        t.progress+=use*rate; left-=use; if(t.progress>=need-1e-6){ finish(t); startStep(p); } else if(stop(p)) leave(p); break; }
      case 'tear': { const b=T.claimed, rate=.6+.08*(p.skill.building||0); const need=TEAR.hours*60, use=Math.min(left,(need-b.order.progress)/rate); b.order.progress+=use*rate; left-=use;
        if(b.order.progress>=need-1e-6){ tearDown(b); startStep(p); } else if(stop(p)) leave(p); break; }
      case 'collect': { const t=T.thing; s.left-=left; left=0; if(s.left<=0){ p.load=Math.min(t.pool,CARRY_WATER); t.pool-=p.load; startStep(p); } break; }
      case 'deliver': { const put=Math.min(p.load||0,waterCap()-st.stock.water); st.stock.water+=put; p.load=0; s.left-=left; left=0; if(s.left<=0) startStep(p); break; }
      case 'pump': { const t=T.thing, use=Math.min(left,s.left), got=Math.min(PUMP_HOUR*use/60,PUMP_DAY-t.pumped,waterCap()-st.stock.water); t.pumped+=got; st.stock.water+=got; s.left-=use; left-=use;
        if(s.left<=0||t.pumped>=PUMP_DAY||st.stock.water>=waterCap()) startStep(p); else if(stop(p)) leave(p); break; }
      case 'tend': { const t=T.thing; s.left-=left; left=0; if(s.left<=0){ const w=Math.min(3,st.stock.water); st.stock.water-=w; t.tended=dayOf(st.minutes); startStep(p); } break; }
      case 'sleep': case 'watch': { p.asleep=s.do==='sleep'; if(!night(st.minutes)){ if(p.asleep) p.slept=(p.slept||0)+1; startStep(p); } left=0; break; }
      case 'rest': case 'idle': default: { s.left-=left; left=0; if(s.left<=0||(s.do==='rest'&&!heat(st.minutes))) startStep(p); if(p.task&&s.do==='idle'&&stop(p)) leave(p); break; } } } }
// stop work when a need is pressing or the day turns (night, the heat for outdoor work)
function stop(p){ const T=p.task; if(!T) return false; if(p.behind>=THIRSTY&&st.stock.water>.5) return true; if(night(st.minutes)&&T.kind!=='watch') return true;
  if(heat(st.minutes)&&!st.heatWork&&OUTDOOR.has(T.kind)) return true; return T.kind==='idle'&&p.behind>=DRINK_AT; }
const OUTDOOR=new Set(['build','repair','tear','collect_water','pump','tend']);
function leave(p){ p.task=null; p.load=0; p.inside=false; p.asleep=false; }

// ---------- the clock ----------
// settle any stretch of world time in short steps (the foundation's continuous rates)
function advance(dt){ const STEP=.5; while(dt>1e-9){ const d=Math.min(STEP,dt); dt-=d;
  const before=st.minutes; st.minutes+=d;
  if(dayOf(before)!==dayOf(st.minutes)) for(const t of st.things) t.pumped=0;
  for(const t of st.things) if(t.type==='seep'&&t.state==='done') t.pool=Math.min(SEEP_DAY,t.pool+SEEP_DAY*d/1440);
  for(const p of st.people) stepPerson(p,d);
  if(st.stock.water<=0&&!st.dry){ st.dry=true; note('The water has run out.'); } else if(st.stock.water>0) st.dry=false; } return st; }

return {VERSION, NK, COVER, CATALOG, TEAR, START_STOCK, BARRELS, TANK, THIRSTY, DEHYDRATED, WALK,
  create, use, advance, place, placeLine, lineCells, canPlace, footprint, cancel, orderRepair, orderTear,
  cellOf, cellXZ, cellIJ, idOf, passable, speedOf, findPath, nearestPassable, accessOf, waterCap, waterRate, dailyUse, heightAt:(x,z)=>heightAt(st.site,x,z),
  hourOf, fmt, night, heat, get state(){ return st; } };
})();
if(typeof module!=='undefined') module.exports=Ranch;
