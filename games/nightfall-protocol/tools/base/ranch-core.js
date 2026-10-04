// ---------- the base: building's rules (the logistic layer) ----------
// A base is a 140 m square founded anywhere on baked ground. Things are placed on the 2 m movement grid and write their
// kind and cover into it as the bake does; they offer tasks in the shared shape (tools/sim/README.md); survivors are
// People records (tools/people) who choose tasks with People.score and walk the real ground to them.
// No rendering, so the same file runs in the page and in Node (tools/base/test.js). Plain data in, plain data out.
// Stores belong to settlement.md: the stock here is a stand-in until the base is wired to Settlement.
const Ranch=(()=>{
const P=typeof People!=='undefined'?People:require('../people/people.js');
const VERSION=2;
// movement kinds, the same values as SectorCore.NAVKIND
const NK={open:0,asphalt:1,dirt:2,path:3,lot:4,yard:5,wash:6,brush:7,hill:8,water:9,building:10,wall:11,steep:12,low:13,pier:14};
const BLOCKS=new Set([NK.building,NK.wall,NK.water,NK.steep,NK.low,NK.pier]);
const COVER={none:0,half:1,full:2};
const WALK=5000/60;   // metres per game minute at terrain speed 1 (5 km/h on asphalt, foundation)
const BASE=140;       // the buildable square, metres

// ---------- the day (building.md): outdoor work 06–10 and 18–22, indoor work and rest in the heat (outdoor at half speed), sleep 22–06 ----------
const mod=m=>((m%1440)+1440)%1440;
const hourOf=min=>mod(min)/60;
const night=m=>{ const h=hourOf(m); return h>=22||h<6; };
const midday=m=>{ const h=hourOf(m); return h>=10&&h<18; };
// heat 0..1 from the campaign's early-summer curve (campaign.js sunAt/heatOf): 24 °C before sunrise to 40 °C at 16:00
function heatAt(min){ const h=hourOf(min); let t; if(h>=5.5&&h<16) t=24+16*(1-Math.cos(Math.PI*(h-5.5)/10.5))/2; else { const s=(h>=16?h-16:h+8)/13.5; t=40-16*(1-Math.cos(Math.PI*s))/2; } return Math.max(0,Math.min(1,(t-30)/10)); }

// ---------- the first buildables: building.md's ten with its numbers, plus four from the ranch design with stats inferred from them ----------
// size in cells (w across x, d along z, before rotation), cost in stock units, hours of work at Build 1 (−15% per level above),
// what the finished thing writes into the grid, and what it gives.
const CATALOG={
  wall:     {label:'Wall',         w:1,d:1, cost:{shelter:2},         hours:3,  kind:NK.wall,     cover:COVER.full, drag:true},
  gate:     {label:'Gate',         w:2,d:1, cost:{shelter:3,goods:1}, hours:6,  gate:true,         cover:COVER.full},   // `wall` while shut (at night), open by day
  barricade:{label:'Barricade',    w:1,d:1, cost:{shelter:1},         hours:1.5,kind:NK.wall,     cover:COVER.half, drag:true, inferred:true},
  bed:      {label:'Bed',          w:1,d:1, cost:{shelter:1},         hours:2,  speed:.6,          beds:1},
  bunkhouse:{label:'Bunkhouse',    w:4,d:3, cost:{shelter:12,goods:2},hours:24, kind:NK.building, cover:COVER.full, beds:4, shade:4},
  ramada:   {label:'Shade ramada', w:2,d:2, cost:{shelter:3},         hours:4,  shade:4,           inferred:true},
  tank:     {label:'Water tank',   w:2,d:2, cost:{goods:4,shelter:2}, hours:8,  kind:NK.building, cover:COVER.full, water:1000},
  catcher:  {label:'Rain catcher', w:3,d:2, cost:{shelter:3,goods:1}, hours:6,  catchL:24},       // litres per mm of rain, into the tanks
  seep:     {label:'Wash seep',    w:1,d:1, cost:{},                  hours:8,  on:NK.wash,        seepL:25, inferred:true},
  pump:     {label:'Hand pump',    w:1,d:1, cost:{goods:3},           hours:6,  cover:COVER.half,  repair:true, pumpL:60, pumpH:15, inferred:true},
  garden:   {label:'Garden bed',   w:2,d:3, cost:{shelter:1},         hours:4,  speed:.8,          tendL:3},
  kitchen:  {label:'Kitchen',      w:2,d:2, cost:{shelter:2,goods:1}, hours:6,  cover:COVER.half,  site:'cook'},
  workbench:{label:'Workbench',    w:1,d:2, cost:{shelter:2,goods:2}, hours:6,  cover:COVER.half,  site:'craft'},
  watch:    {label:'Watch post',   w:2,d:2, cost:{shelter:6},         hours:12, kind:NK.building, cover:COVER.full, guards:2, spot:60, raise:3},
};
const TEAR={hours:6, gives:{shelter:6}};   // taking apart a small outbuilding on the base
const SKILL_STEP=.85;                       // each Build level above 1 takes 15% off the time
// stand-ins until settlement.md supplies the stores (proposed starting stock, strategy units)
const START_STOCK={water:400,food:30,medicine:4,tools:6,fuel:10,gear:6,shelter:40,goods:12};
const BARRELS=400, CANTEEN=2, KCAL_RATION=2000;

// ---------- helpers ----------
const fmt=m=>{ const d=Math.floor(m/1440)+1, h=Math.floor(mod(m)/60), mm=Math.floor(mod(m)%60); return `Day ${d} ${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}`; };
function unb64(s){ if(typeof Buffer!=='undefined') return new Uint8Array(Buffer.from(s,'base64')); const b=atob(s), a=new Uint8Array(b.length); for(let i=0;i<b.length;i++) a[i]=b.charCodeAt(i); return a; }
const inPoly=(x,z,pts)=>{ let c=false; for(let i=0,j=pts.length-1;i<pts.length;j=i++){ const [xi,zi]=pts[i],[xj,zj]=pts[j]; if(((zi>z)!==(zj>z)) && x<(xj-xi)*(z-zi)/(zj-zi)+xi) c=!c; } return c; };
const centroid=pts=>[pts.reduce((s,p)=>s+p[0],0)/pts.length, pts.reduce((s,p)=>s+p[1],0)/pts.length];
const polyArea=pts=>{ let s=0; for(let i=0,j=pts.length-1;i<pts.length;j=i++) s+=(pts[j][0]+pts[i][0])*(pts[j][1]-pts[i][1]); return Math.abs(s/2); };

// ---------- the ground: a cut of the baked block (cut_site.py) ----------
const siteCache=new WeakMap();
function siteOf(raw){ if(siteCache.has(raw)) return siteCache.get(raw);
  const S=Object.assign({},raw), Hi=new Int16Array(unb64(raw.H).buffer.slice(0)); S.Hf=new Float32Array(Hi.length); for(let i=0;i<Hi.length;i++) S.Hf[i]=Hi[i]/100;
  S.NX=raw.nav.nx; S.NZ=raw.nav.nz; S.NS=raw.nav.step; S.kind0=unb64(raw.nav.kind); S.sp0=unb64(raw.nav.sp); siteCache.set(raw,S); return S; }
function heightAt(S,x,z){ const fx=(x-S.x0+4)/4, fz=(z-S.z0+4)/4, i=Math.max(0,Math.min(S.hnx-2,Math.floor(fx))), j=Math.max(0,Math.min(S.hnz-2,Math.floor(fz))), u=Math.min(1,Math.max(0,fx-i)), v=Math.min(1,Math.max(0,fz-j)), h=(a,b)=>S.Hf[b*S.hnx+a];
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; }
let st=null;   // the state the functions below work on (create() and use() set it)
const S=()=>st.site;
const cellOf=(x,z)=>{ const s=S(), i=Math.floor((x-s.x0)/s.NS), j=Math.floor((z-s.z0)/s.NS); return i>=0&&j>=0&&i<s.NX&&j<s.NZ?j*s.NX+i:-1; };
const cellXZ=c=>{ const s=S(); return [s.x0+(c%s.NX+.5)*s.NS, s.z0+(Math.floor(c/s.NX)+.5)*s.NS]; };
const cellIJ=c=>[c%S().NX, Math.floor(c/S().NX)];
const idOf=(i,j)=>{ const s=S(); return i>=0&&j>=0&&i<s.NX&&j<s.NZ?j*s.NX+i:-1; };
const passable=c=>c>=0 && st.grid.sp[c]>0 && (st.grid.gate[c]===1 || !BLOCKS.has(st.grid.kind[c]));
const speedOf=c=>passable(c)?Math.max(.3,st.grid.sp[c]/250):0;
function inArea(c){ const [x,z]=cellXZ(c), a=st.area; return x>a[0]&&x<a[2]&&z>a[1]&&z<a[3]; }
function nearestPassable(c,pred=passable){ if(c<0) return -1; if(pred(c)) return c; const [ci,cj]=cellIJ(c);
  for(let r=1;r<40;r++){ let best=-1,bd=1e9; for(let dj=-r;dj<=r;dj++) for(let di=-r;di<=r;di++){ if(Math.max(Math.abs(di),Math.abs(dj))!==r) continue; const id=idOf(ci+di,cj+dj); if(id>=0&&pred(id)){ const d=di*di+dj*dj; if(d<bd){ bd=d; best=id; } } } if(best>=0) return best; } return -1; }

// ---------- paths: A* over the 2 m grid, cost is time at terrain speed (as the streaming page) ----------
let G_=null;
function findPath(from,to){ if(from<0||to<0||!passable(to)) return null; if(from===to) return {cells:[from],cost:0};
  const s=S(), N=s.NX*s.NZ; if(!G_||G_.g.length!==N) G_={g:new Float32Array(N),came:new Int32Array(N),closed:new Uint8Array(N),touched:[]};
  const {g,came,closed}=G_, touched=[], heap=[], [tx,tz]=cellXZ(to);
  const push=(f,n)=>{ heap.push([f,n]); let i=heap.length-1; while(i>0){ const p=(i-1)>>1; if(heap[p][0]<=heap[i][0]) break; [heap[p],heap[i]]=[heap[i],heap[p]]; i=p; } };
  const pop=()=>{ const top=heap[0], last=heap.pop(); if(heap.length){ heap[0]=last; let i=0; for(;;){ const l=2*i+1, r=l+1; let m=i; if(l<heap.length&&heap[l][0]<heap[m][0]) m=l; if(r<heap.length&&heap[r][0]<heap[m][0]) m=r; if(m===i) break; [heap[m],heap[i]]=[heap[i],heap[m]]; i=m; } } return top; };
  const h=n=>{ const [x,z]=cellXZ(n); return Math.hypot(x-tx,z-tz); };
  // the arrays persist between searches: only the cells the last search touched are reset
  if(!G_.init){ g.fill(Infinity); came.fill(-1); G_.init=true; } for(const n of G_.touched){ g[n]=Infinity; came[n]=-1; closed[n]=0; } G_.touched=touched;
  g[from]=0; touched.push(from); push(h(from),from); let found=false;
  while(heap.length){ const [,n]=pop(); if(closed[n]) continue; closed[n]=1; if(n===to){ found=true; break; } const i=n%s.NX, j=(n-i)/s.NX, sa=speedOf(n)||.3;
    for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ if(!di&&!dj) continue; const m=idOf(i+di,j+dj); if(m<0||closed[m]||!passable(m)) continue;
      if(di&&dj&&(!passable(idOf(i+di,j))||!passable(idOf(i,j+dj)))) continue;   // no squeezing between two blocked corners
      const c=g[n]+s.NS*(di&&dj?Math.SQRT2:1)/((sa+speedOf(m))/2); if(c<g[m]){ if(g[m]===Infinity) touched.push(m); g[m]=c; came[m]=n; push(c+h(m),m); } } }
  if(!found) return null; const cells=[]; for(let n=to;n>=0;n=came[n]){ cells.push(n); if(n===from) break; } cells.reverse(); return {cells,cost:g[to]}; }
// straighten a cell path where the straight line keeps to cells at least as fast
function smooth(cells){ const pts=cells.map(cellXZ), out=[pts[0]]; let i=0;
  const ok=(a,b)=>{ const L=Math.hypot(b[0]-a[0],b[1]-a[1]), n=Math.ceil(L/.6), s0=Math.min(speedOf(cellOf(...a)),speedOf(cellOf(...b)))*.97; for(let q=1;q<n;q++){ const c=cellOf(a[0]+(b[0]-a[0])*q/n,a[1]+(b[1]-a[1])*q/n); if(c<0||speedOf(c)<s0||speedOf(c)<=0) return false; } return true; };
  while(i<pts.length-1){ let j=Math.min(pts.length-1,i+30); while(j>i+1&&!ok(pts[i],pts[j])) j--; out.push(pts[j]); i=j; } return out; }

// ---------- founding a base ----------
// any centre whose 140 m square lies on the cut ground; snapped to the 2 m grid
function areaAt(raw,x,z){ const s=siteOf(raw), h=BASE/2, cx=Math.round(x/2)*2, cz=Math.round(z/2)*2; return [cx-h,cz-h,cx+h,cz+h]; }
function canFound(raw,x,z){ const s=siteOf(raw), a=areaAt(raw,x,z); return a[0]>=s.x0+4&&a[1]>=s.z0+4&&a[2]<=s.x0+s.w-4&&a[3]<=s.z0+s.d-4; }
function create(raw,{seed=20261004,people=6,minute=6*60,centre=null}={}){
  const site=siteOf(raw), N=site.NX*site.NZ, c0=centre||raw.presets[0].centre;
  if(!canFound(raw,...c0)) throw new Error('a base must lie on the cut ground');
  st={v:VERSION, seed, minutes:minute, site, area:areaAt(raw,...c0), seq:1, things:[], people:[], stock:Object.assign({},START_STOCK), log:[], rain:0,
    grid:{kind:Uint8Array.from(site.kind0), sp:Uint8Array.from(site.sp0), cover:new Uint8Array(N), gate:new Uint8Array(N), occ:new Int32Array(N)}};
  G_=null; const G=st.grid; for(let c=0;c<N;c++) if(G.kind[c]===NK.building||G.kind[c]===NK.wall) G.cover[c]=COVER.full;
  // buildings standing on the base are claimed: the biggest house is home (shelter, the water barrels), the next the store, the next the workshop;
  // the rest can be taken apart for materials. Each gets a door: the passable cell nearest its middle on the side facing the base's centre.
  const a=st.area, mid=[(a[0]+a[2])/2,(a[1]+a[3])/2], found=[];
  for(const b of site.buildings){ const [cx,cz]=centroid(b.pts); if(cx<=a[0]||cx>=a[2]||cz<=a[1]||cz>=a[3]) continue; const cells=[], bb=[Math.min(...b.pts.map(p=>p[0])),Math.min(...b.pts.map(p=>p[1])),Math.max(...b.pts.map(p=>p[0])),Math.max(...b.pts.map(p=>p[1]))];
    for(let z=bb[1];z<=bb[3]+2;z+=2) for(let x=bb[0];x<=bb[2]+2;x+=2){ const c=cellOf(x,z); if(c<0) continue; const [qx,qz]=cellXZ(c); if(G.kind[c]===NK.building&&inPoly(qx,qz,b.pts)&&!cells.includes(c)) cells.push(c); }
    if(!cells.length) continue; const dx=mid[0]-cx, dz=mid[1]-cz, dl=Math.hypot(dx,dz)||1, r=Math.sqrt(polyArea(b.pts))/2+1.5;
    found.push({pts:b.pts, house:b.house, area:polyArea(b.pts), cells, door:nearestPassable(cellOf(cx+dx/dl*r,cz+dz/dl*r)), torn:false, order:null}); }
  found.sort((p,q)=>(q.house-p.house)||(q.area-p.area));
  st.claimed={}; const roles=['house','store','workshop']; found.forEach((b,i)=>{ b.role=roles[i]||'outbuilding'; b.key=b.role+(i>=3?'-'+(i-2):''); if(b.role==='outbuilding'&&b.area>260) b.role='spare'; st.claimed[b.key]=b; });
  const home=st.claimed.house?st.claimed.house.door:nearestPassable(cellOf(...mid));
  st.places={home, store:st.claimed.store?st.claimed.store.door:home, work:st.claimed.workshop?st.claimed.workshop.door:home};
  // a base with a house has an old well beside the store: its electric pump died with the grid; a hand pump is a repair (lore.md)
  if(st.claimed.house){ const [sx,sz]=cellXZ(st.places.store), c=nearestPassable(cellOf(sx+4,sz+4),q=>passable(q)&&!G.occ[q]&&inArea(q)&&G.kind[q]!==NK.wash); if(c>=0) addThing('pump',c,0,'broken'); }
  const [hx,hz]=cellXZ(home);
  for(let k=0;k<people;k++){ const rec=P.create(seed+k*7919,{id:'s'+(k+1),minute,stage:'adult'}), j=k/people*Math.PI*2;
    st.people.push({id:rec.id, rec, name:rec.name.split(' ')[0], x:hx+Math.cos(j)*1.5, z:hz+Math.sin(j)*1.5, canteen:CANTEEN, task:null, inside:false, act:'idle', heading:0, watched:0}); }
  note(`A base founded: ${people} people, ${st.stock.water} L of water in barrels${st.claimed.house?' in the house':''}.`);
  return st; }
function use(s){ st=s; G_=null; return st; }
function note(msg){ st.log.unshift({t:st.minutes,msg}); if(st.log.length>60) st.log.length=60; }

// ---------- placing things ----------
function footprint(type,c,rot=0){ const T=CATALOG[type], [i0,j0]=cellIJ(c), w=rot%2?T.d:T.w, d=rot%2?T.w:T.d, out=[]; for(let j=0;j<d;j++) for(let i=0;i<w;i++){ const id=idOf(i0+i,j0+j); if(id<0) return null; out.push(id); } return out; }
function canPlace(type,c,rot=0){ const T=CATALOG[type]; if(!T) return {ok:false,why:'Unknown thing'}; if(T.repair) return {ok:false,why:'A hand pump goes on an old well: use Repair well'};
  const cells=footprint(type,c,rot); if(!cells) return {ok:false,why:'Off the ground'};
  for(const q of cells){ if(!inArea(q)) return {ok:false,why:'Outside the base'}; if(st.grid.occ[q]) return {ok:false,why:'Something is already there'};
    const k=st.grid.kind[q]; if(T.on!==undefined?k!==T.on:!passable(q)) return {ok:false,why:T.on===NK.wash?'A seep has to be dug in a sand wash':'The ground is blocked'};
    if(T.on===undefined&&k===NK.wash&&(T.kind!==undefined||T.beds)) return {ok:false,why:'Not in the wash: it floods'}; }
  return {ok:true,cells}; }
function addThing(type,c,rot,state='site'){ const T=CATALOG[type], cells=footprint(type,c,rot), id='t'+st.seq++;
  const t={id, type, cell:c, rot, cells, state, progress:0, delivered:Object.keys(T.cost).length===0, pool:0, pumped:0, tended:-1, shut:false};
  for(const q of cells) st.grid.occ[q]=st.seq-1; st.things.push(t); return t; }
function place(type,c,rot=0){ return canPlace(type,c,rot).ok?addThing(type,c,rot):null; }
// a straight line in one of eight directions, as dragged
function lineCells(a,b){ const [ai,aj]=cellIJ(a), [bi,bj]=cellIJ(b), di=bi-ai, dj=bj-aj, n=Math.max(Math.abs(di),Math.abs(dj)), out=[];
  const ang=Math.round(Math.atan2(dj,di)/(Math.PI/4)), si=Math.round(Math.cos(ang*Math.PI/4)), sj=Math.round(Math.sin(ang*Math.PI/4));
  for(let k=0;k<=n;k++){ const id=idOf(ai+si*k,aj+sj*k); if(id>=0) out.push(id); } return out; }
function placeLine(type,a,b){ const out=[]; for(const c of lineCells(a,b)) if(canPlace(type,c).ok) out.push(place(type,c)); return out; }
function cancel(id){ const t=st.things.find(q=>q.id===id); if(!t||t.state!=='site') return false; if(t.type==='pump'){ t.state='broken'; t.progress=0; return true; }
  if(t.delivered) for(const [k,n] of Object.entries(CATALOG[t.type].cost)) st.stock[k]=(st.stock[k]||0)+n;   // materials go back to the store
  for(const q of t.cells) st.grid.occ[q]=0; st.things=st.things.filter(q=>q!==t); for(const p of st.people) if(p.task&&p.task.thing===t) leave(p); return true; }
function orderRepair(){ const t=st.things.find(q=>q.type==='pump'&&q.state==='broken'); if(!t) return null; t.state='site'; t.delivered=false; note('Ordered: a hand pump on the old well.'); return t; }
function orderTear(key){ const b=st.claimed[key]; if(!b||b.torn||b.order||b.role!=='outbuilding') return false; b.order={progress:0}; note('Ordered: take an outbuilding apart for materials.'); return true; }

// what a finished thing does to the grid: the interface combat and pathing read (kind, speed, cover; a gate flag lets the base's own people through)
function writeCells(t){ const T=CATALOG[t.type], G=st.grid;
  for(const q of t.cells){ if(T.gate){ G.gate[q]=1; G.kind[q]=t.shut?NK.wall:st.site.kind0[q]; G.cover[q]=t.shut?COVER.full:COVER.none; continue; }
    if(T.kind!==undefined) G.kind[q]=T.kind; if(T.speed) G.sp[q]=Math.round(st.site.sp0[q]*T.speed); if(T.cover!==undefined) G.cover[q]=T.cover; } }
function finish(t){ if(t.state==='done') return; const T=CATALOG[t.type]; t.state='done'; t.shut=!!T.gate&&night(st.minutes); writeCells(t);
  if(T.kind!==undefined) for(const p of st.people){ const c=cellOf(p.x,p.z); if(t.cells.includes(c)){ [p.x,p.z]=cellXZ(nearestPassable(c)); } }   // step off a cell that just became solid
  note(`${T.label} finished.`); }
function tearDown(b){ const G=st.grid; for(const q of b.cells){ G.kind[q]=NK.open; G.sp[q]=180; G.cover[q]=0; } b.torn=true; b.order=null;
  for(const [k,n] of Object.entries(TEAR.gives)) st.stock[k]=(st.stock[k]||0)+n; note(`An outbuilding came apart: +${TEAR.gives.shelter} materials.`); }

// ---------- water ----------
const done=type=>st.things.filter(t=>t.type===type&&t.state==='done');
const waterCap=()=>BARRELS+done('tank').length*CATALOG.tank.water;
const waterPoints=()=>[st.places.home,...done('tank').map(accessOf)];
const inflow=()=>done('seep').length*CATALOG.seep.seepL+done('pump').length*CATALOG.pump.pumpL;
// rain into the catchers, as far as the tanks hold it (no rain in early summer yet: the monsoon is a weather model to come)
function rainfall(mm){ const L=done('catcher').length*CATALOG.catcher.catchL*mm, put=Math.min(L,Math.max(0,waterCap()-st.stock.water)); st.stock.water+=put; return put; }

// ---------- tasks in the shared shape, chosen with People.score ----------
// where to stand: on a passable thing, else the free cell beside it nearest home
function accessOf(t){ const T=CATALOG[t.type]; if(T.kind===undefined&&!T.gate){ const c=t.cells.find(passable); if(c!==undefined) return c; }
  const [hx,hz]=cellXZ(st.places.home); let best=-1,bd=1e9; for(const q of t.cells){ const [i,j]=cellIJ(q); for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ const m=idOf(i+di,j+dj); if(m<0||t.cells.includes(m)||!passable(m)) continue; const [x,z]=cellXZ(m), d=Math.hypot(x-hx,z-hz); if(d<bd){ bd=d; best=m; } } } return best>=0?best:nearestPassable(t.cells[0]); }
const dayOf=m=>Math.floor(m/1440);
const costOK=t=>t.delivered||Object.entries(CATALOG[t.type].cost).every(([k,n])=>(st.stock[k]||0)>=n);
const busyOn=(thing,max=1)=>st.people.filter(p=>p.task&&p.task.thing===thing).length>=max;
const where=c=>{ const [x,z]=cellXZ(c); return {x,z}; };
function sleepSpots(){ const out=[]; for(const t of done('bed')) out.push({thing:t,cell:accessOf(t),bed:true,inside:false,slots:1});
  for(const t of done('bunkhouse')) out.push({thing:t,cell:accessOf(t),bed:true,inside:true,slots:4});
  out.push({thing:null,cell:st.places.home,bed:false,inside:!!st.claimed.house,slots:99}); return out; }   // the house floor (or the ground) until interiors furnish it
function shadeSpots(){ const out=[]; if(st.claimed.house) out.push({cell:st.places.home,inside:true}); for(const t of [...done('bunkhouse'),...done('ramada')]) out.push({cell:accessOf(t),inside:t.type==='bunkhouse',thing:t}); return out; }
// every task the base offers this person now: {id, kind, skill, where, hours, urgency, outdoor, heavy} plus how to carry it out
function offers(p){ const m=st.minutes, out=[], add=(task,steps)=>out.push({task,steps});
  if(p.canteen<.5&&st.stock.water>.5){ const wp=nearest(p,waterPoints()); add({id:'drink',kind:'drink',where:where(wp),hours:.05,urgency:1},[{go:wp},{do:'refill',min:4}]); }
  if(night(m)){
    // the watch goes to whoever has stood it least (building.md: two on watch at night)
    const least=Math.min(...st.people.filter(q=>q.rec.alive&&q.rec.at!=='gone').map(q=>q.watched));
    for(const t of done('watch')) if(!busyOn(t,CATALOG.watch.guards)&&p.watched<=least&&!(p.task&&p.task.kind==='sleep')) add({id:'guard-'+t.id,kind:'guard',skill:'shoot',where:where(accessOf(t)),hours:8,urgency:1,outdoor:true,thing:t},[{go:accessOf(t)},{do:'guard',act:'idle'}]);
    for(const s of sleepSpots()){ const n=st.people.filter(q=>q.task&&q.task.spot&&q.task.spot.cell===s.cell&&q.task.spot.thing===s.thing).length; if(n>=s.slots) continue;
      add({id:'sleep-'+s.cell,kind:'sleep',where:where(s.cell),hours:8,urgency:1,bed:s.bed,spot:s},[{go:s.cell},{do:'sleep',bed:s.bed,inside:s.inside}]); } }
  else {
    for(const t of st.things){ if(t.state!=='site'||busyOn(t,t.type==='bunkhouse'?3:t.type==='watch'?2:1)||!costOK(t)||t.blockedUntil>m) continue;
      add({id:'build-'+t.id,kind:'build',skill:'build',where:where(t.cells[0]),hours:CATALOG[t.type].hours,urgency:t.type==='pump'||t.type==='tank'?.8:.6,outdoor:true,heavy:true,thing:t},
        [...(t.delivered?[]:[{go:st.places.store},{do:'take',min:4}]),{go:accessOf(t),carry:!t.delivered},{do:'build',act:'work'}]); }
    for(const b of Object.values(st.claimed)) if(b.order&&!st.people.some(q=>q.task&&q.task.claimed===b)){ const c=nearestPassable(b.cells[0]);
      add({id:'tear-'+b.key,kind:'build',skill:'build',where:where(c),hours:TEAR.hours,urgency:.5,outdoor:true,heavy:true,claimed:b},[{go:c},{do:'tear',act:'work'}]); }
    const room=waterCap()-st.stock.water;
    for(const t of done('seep')) if(t.pool>=5&&room>=5&&!busyOn(t)) add({id:'haul-'+t.id,kind:'haul',where:where(accessOf(t)),hours:1,urgency:.5,outdoor:true,heavy:true,thing:t},[{go:accessOf(t)},{do:'collect',min:20,act:'work'},{go:nearest(t,waterPoints()),carry:true},{do:'deliver',min:3}]);
    for(const t of done('pump')) if(t.pumped<CATALOG.pump.pumpL-1&&room>=5&&!busyOn(t)) add({id:'pump-'+t.id,kind:'haul',where:where(accessOf(t)),hours:1,urgency:.55,outdoor:true,heavy:true,thing:t},[{go:accessOf(t)},{do:'pump',min:60,act:'work'}]);
    for(const t of done('garden')) if(t.tended<dayOf(m)&&st.stock.water>=CATALOG.garden.tendL&&!busyOn(t)) add({id:'grow-'+t.id,kind:'grow',skill:'grow',where:where(accessOf(t)),hours:.75,urgency:.5,outdoor:true,thing:t},[{go:accessOf(t)},{do:'tend',min:45,act:'work'}]); }
  const sh=shadeSpots(); if(sh.length){ const s=nearest(p,sh.map(q=>q.cell)), spot=sh.find(q=>q.cell===s); add({id:'rest',kind:'rest',where:where(s),hours:1,urgency:0},[{go:s},{do:'rest',min:60,inside:spot.inside}]); }
  return out; }
function nearest(p,cells){ let best=cells[0],bd=1e9; const [x,z]=p.x!==undefined?[p.x,p.z]:cellXZ(p.cells[0]); for(const c of cells){ const [cx,cz]=cellXZ(c), d=Math.hypot(cx-x,cz-z); if(d<bd){ bd=d; best=c; } } return best; }
// People.score picks; building adds the day shape (sleep pulls at night) and an idle wander as the floor
function choose(p){ const m=st.minutes, ctx={minute:m,heat:heatAt(m),from:{x:p.x,z:p.z}}; let best=null, bs=-Infinity;
  for(const o of offers(p)){ let s=P.score(p.rec,o.task,ctx); if(o.task.kind==='sleep') s+=1+(o.task.bed?.2:0); if(o.task.kind==='drink') s=Math.max(s,2.2); if(o.task.kind==='guard') s=Math.max(s,3.5); if(s>bs){ bs=s; best=o; } }
  if(!best||bs<.2){ const [hx,hz]=cellXZ(st.places.home), a=((p.rec.rng>>>8)%360)/57.3+m*.01, r=4+(m*7+p.id.length*13)%10, c0=nearestPassable(cellOf(hx+Math.cos(a)*r,hz+Math.sin(a)*r));
    best={task:{id:'idle',kind:'idle'},steps:[{go:c0>=0?c0:st.places.home},{do:'idle',min:20}]}; }
  const T=Object.assign({},best.task,{steps:best.steps,step:-1,thing:best.task.thing,claimed:best.task.claimed,spot:best.task.spot}); if(T.kind==='guard') p.watched++; return T; }

// ---------- one person over dt game minutes ----------
function startStep(p){ const T=p.task; T.step++; const s=T.steps[T.step]; if(!s){ p.task=null; return; }
  p.inside=false; s.left=s.min||0;
  if(s.go!==undefined){ const from=nearestPassable(cellOf(p.x,p.z)), path=findPath(from,s.go);
    if(!path){ if(T.thing) T.thing.blockedUntil=st.minutes+120; note(`${p.name} can't reach the ${T.thing?CATALOG[T.thing.type].label.toLowerCase():'spot'}.`); p.task=null; return; }
    s.pts=smooth(path.cells); s.k=1; } }
// time is the catalogue's hours at Build 1, −15% per level above (so faster below level 1 is slower); outdoor work in the heat goes at half speed
function workRate(p,skill){ const lvl=(p.rec.skills&&p.rec.skills[skill])||0; return Math.pow(SKILL_STEP,-(lvl-1))*(midday(st.minutes)?.5:1); }
function activityOf(p){ const s=p.task&&p.task.steps[p.task.step]; if(!s) return 'rest'; if(s.do==='sleep') return 'sleep'; if(s.go!==undefined||s.act==='work'||s.do==='guard') return 'work'; return 'rest'; }
function stepPerson(p,dt){ const m=st.minutes, rec=p.rec; if(!rec.alive||rec.at==='gone') return;
  // the body: People settles it; water comes from the canteen, food from the stores (settlement will ration both)
  const act=activityOf(p), shaded=p.inside||!!(p.task&&p.task.kind==='rest'), env={minute:m,heat:heatAt(m)*(shaded?.4:1),activity:act,bed:!!(p.task&&p.task.steps[p.task.step]&&p.task.steps[p.task.step].bed),skill:p.task&&p.task.skill};
  const dem=P.demand(rec,dt,env), got={water:Math.min(p.canteen,dem.water),food:Math.min(st.stock.food*KCAL_RATION,dem.food)}; p.canteen-=got.water; st.stock.food-=got.food/KCAL_RATION;
  for(const e of P.step(rec,dt,env,got)){ if(e.kind==='death'){ note(`${p.name} died (${e.cause}).`); leave(p); p.act='dead'; return; } if(e.kind==='left'){ note(`${p.name} walked out.`); leave(p); return; } if(e.kind==='break') note(`${p.name} has had enough (${e.break||'a break'}).`); }
  if(p.task&&stop(p)) leave(p);
  if(!p.task){ p.task=choose(p); startStep(p); if(!p.task) return; }
  let left=dt;
  while(left>1e-6&&p.task){ const T=p.task, s=T.steps[T.step];
    if(s.go!==undefined){ const tgt=s.pts[s.k]; if(!tgt){ startStep(p); continue; }
      const thirst=P.thirstStage(rec), sp=WALK*(speedOf(cellOf(p.x,p.z))||.5)*(thirst>=2?.6:thirst>=1?.85:1)*Math.max(.4,P.capacity(rec,m)), dx=tgt[0]-p.x, dz=tgt[1]-p.z, d=Math.hypot(dx,dz), can=sp*left;
      p.act=s.carry?'carry':'walk'; if(d>1e-6) p.heading=Math.atan2(dx,dz);
      if(can>=d){ p.x=tgt[0]; p.z=tgt[1]; left-=d/sp; s.k++; if(s.k>=s.pts.length) startStep(p); } else { p.x+=dx/d*can; p.z+=dz/d*can; left=0; }
      continue; }
    p.act=s.act||'idle'; p.inside=!!s.inside;
    switch(s.do){
      case 'refill': { const take=Math.min(CANTEEN-p.canteen,st.stock.water); st.stock.water-=take; p.canteen+=take; s.left-=left; left=0; if(s.left<=0) startStep(p); break; }
      case 'take': { const t=T.thing; if(!t.delivered){ if(!costOK(t)){ leave(p); break; } for(const [k,n] of Object.entries(CATALOG[t.type].cost)) st.stock[k]-=n; t.delivered=true; } startStep(p); break; }
      case 'build': { const t=T.thing; if(t.state!=='site'){ startStep(p); break; } const rate=workRate(p,'build'), need=CATALOG[t.type].hours*60, use=Math.min(left,(need-t.progress)/rate);
        t.progress+=use*rate; left-=use; if(t.progress>=need-1e-6){ finish(t); startStep(p); } break; }
      case 'tear': { const b=T.claimed, rate=workRate(p,'build'), need=TEAR.hours*60, use=Math.min(left,(need-b.order.progress)/rate); b.order.progress+=use*rate; left-=use;
        if(b.order.progress>=need-1e-6){ tearDown(b); startStep(p); } break; }
      case 'collect': { const t=T.thing; s.left-=left; left=0; if(s.left<=0){ p.load=Math.min(t.pool,20); t.pool-=p.load; startStep(p); } break; }
      case 'deliver': { const put=Math.min(p.load||0,waterCap()-st.stock.water); st.stock.water+=put; p.load=0; s.left-=left; left=0; if(s.left<=0) startStep(p); break; }
      case 'pump': { const t=T.thing, use=Math.min(left,s.left), got=Math.min(CATALOG.pump.pumpH*use/60,CATALOG.pump.pumpL-t.pumped,waterCap()-st.stock.water); t.pumped+=got; st.stock.water+=got; s.left-=use; left-=use;
        if(s.left<=0||t.pumped>=CATALOG.pump.pumpL-1e-6||st.stock.water>=waterCap()) startStep(p); break; }
      case 'tend': { const t=T.thing; s.left-=left; left=0; if(s.left<=0){ st.stock.water-=Math.min(CATALOG.garden.tendL,st.stock.water); t.tended=dayOf(st.minutes); startStep(p); } break; }
      case 'sleep': case 'guard': { if(!night(st.minutes)) startStep(p); left=0; break; }
      default: { s.left-=left; left=0; if(s.left<=0) startStep(p); } } } }
// leave work when the canteen runs dry, at nightfall, or when a person can't go on
function stop(p){ const T=p.task, m=st.minutes; if(['drink','sleep','guard'].includes(T.kind)) return false;
  if(p.canteen<.05&&st.stock.water>.5) return true; if(night(m)) return true; if(T.kind==='rest'&&!midday(m)&&T.step>=1) return false;
  return P.thirstStage(p.rec)>=2&&st.stock.water>.5; }
function leave(p){ p.task=null; p.load=0; p.inside=false; }

// ---------- the clock: settle any stretch of world time in short steps (the foundation's continuous rates) ----------
function advance(dt){ const STEP=.5; while(dt>1e-9){ const d=Math.min(STEP,dt); dt-=d;
  const before=st.minutes; st.minutes+=d;
  if(dayOf(before)!==dayOf(st.minutes)) for(const t of st.things) t.pumped=0;
  if(night(before)!==night(st.minutes)) for(const t of done('gate')){ t.shut=night(st.minutes); writeCells(t); }   // gates shut at night
  for(const t of st.things) if(t.state==='site'&&t.delivered&&t.progress>=CATALOG[t.type].hours*60-1e-6) finish(t);   // work already done (or set by a test or a save)
  for(const t of done('seep')) t.pool=Math.min(CATALOG.seep.seepL,t.pool+CATALOG.seep.seepL*d/1440);
  for(const p of st.people) stepPerson(p,d);
  if(st.stock.water<=0&&!st.dry){ st.dry=true; note('The water has run out.'); } else if(st.stock.water>0) st.dry=false; } return st; }
// what a person loses in a day at the base, for the panel (People's rates over this day's heat)
function dailyUse(){ let s=0; for(let m=0;m<1440;m+=10){ const sleep=night(m), h=heatAt(m)*(midday(m)?.4:1); s+=(sleep?P.RATES.WATER_SLEEP:P.RATES.WATER_AWAKE)*(1+P.RATES.WATER_HEAT*h)/6; } return s*st.people.filter(p=>p.rec.alive&&p.rec.at!=='gone').length; }

return {VERSION, NK, COVER, CATALOG, TEAR, START_STOCK, BARRELS, CANTEEN, BASE, People:P,
  create, use, advance, canFound, areaAt, place, placeLine, lineCells, canPlace, footprint, cancel, orderRepair, orderTear, rainfall, offers,
  cellOf, cellXZ, cellIJ, idOf, passable, speedOf, findPath, nearestPassable, accessOf, waterCap, inflow, dailyUse, heightAt:(x,z)=>heightAt(st.site,x,z), siteOf,
  hourOf, heatAt, fmt, night, midday, get state(){ return st; } };
})();
if(typeof module!=='undefined') module.exports=Ranch;
