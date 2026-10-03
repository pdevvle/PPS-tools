#!/usr/bin/env node
// Sight, cover and movement checks for fights inside generated buildings.
//   node tools/combat/test-interior.js           run every check
//   node tools/combat/test-interior.js --map     also print the Roadrunner den with the sentry's sight
// The interiors are procedural and owned by the interiors topic, so the checks are invariants over whatever the
// generator makes (every wall, every window, every door), run on every test site and history, plus a few hand checks
// on the Roadrunner (newriver/2_2/0) that find their cells by searching rather than by fixed coordinates.
const assert=require('assert');
const {loadGenerator}=require('./interiors-slice.js');
const IW=require('./interior-world.js'), R=require('./rules.js');
const I=loadGenerator();
let pass=0, fail=0; const fails=[];
function check(name,fn){ try{ fn(); pass++; } catch(e){ fail++; fails.push(name+': '+e.message); } }
const worldOf=(id,history,seed)=>{ const s=I.SITES.find(x=>x.id===id); const G=I.generate(s,'auto',seed||id,history); return IW.fromGenerated(G); };
// every edge as the pair of cells it separates
function* edgesOf(w){ for(let c=0;c<w.N;c++) for(const d of [0,1]){ const n=w.step(c,d); if(n<0) continue; const e=w.edge(c,d); if(e) yield {c,n,d,e}; } }

// ---------- the adapter agrees with the generator ----------
check('edge keys match the generator',()=>{ for(let i=-3;i<5;i++) for(let j=-3;j<5;j++) for(let d=0;d<4;d++) assert.strictEqual(IW.edgeKey(i,j,d),I.edgeKey(i,j,d)); });

// ---------- invariants on every site and history ----------
const HIST=['untouched','looted','holdout','den'];
for(const s of I.SITES) for(const h of HIST){
  const tag=`${s.id} ${h}`; let w;
  check(`${tag}: builds`,()=>{ w=worldOf(s.id,h); assert.ok(w.N>0); });
  if(!w) continue;
  check(`${tag}: walls stop sight and shots and give full cover`,()=>{
    for(const {c,n,d,e} of edgesOf(w)) if(e.type==='wall'){ assert.ok(!w.sight(c,n),`sight through wall ${e.key}`); assert.ok(!w.sight(c,n,{shot:true}),`shot through wall ${e.key}`); assert.strictEqual(w.coverDir(c,d),2,`wall ${e.key} not full cover`); } });
  check(`${tag}: windows: glass and broken let sight through as half cover, boards stop it`,()=>{
    for(const {c,n,d,e} of edgesOf(w)) if(e.type==='window'){ const boarded=e.win.state==='boarded';
      assert.strictEqual(w.sight(c,n),!boarded,`window ${e.key} ${e.win.state}`); assert.strictEqual(w.coverDir(c,d),boarded?2:1,`window ${e.key} cover`); } });
  check(`${tag}: doors: open or broken pass sight, closed and barricaded stop it`,()=>{
    for(const {c,n,e} of edgesOf(w)) if(e.type==='door'||e.type==='gdoor'){ const st=w.doorState(e); assert.strictEqual(w.sight(c,n),st==='open'||st==='broken',`door ${e.key} ${st}`); } });
  check(`${tag}: nobody walks through a wall; inside and outside meet only at openings`,()=>{
    for(let c=0;c<w.N;c++) for(const [n] of w.neighbours(c)){ const e=w.edgeBetween(c,n);
      if(e) assert.notStrictEqual(e.type,'wall',`step ${c}->${n} through wall ${e.key}`);
      const diag=(c%w.W)!==(n%w.W)&&((c/w.W)|0)!==((n/w.W)|0);
      if(diag){ const di=(n%w.W)>(c%w.W)?0:2, dj=n>c?1:3, a=w.step(c,di), b=w.step(c,dj);
        for(const [x,d] of [[c,di],[c,dj],[a,dj],[b,di]]){ const ee=w.edge(x,d); assert.ok(!ee||ee.type==='none'||ee.type==='open',`diagonal ${c}->${n} clips ${ee&&ee.type}`); } }
      else if(w.isInside(c)!==w.isInside(n)){ assert.ok(e,`step ${c}->${n} crosses the outline without an edge`); assert.ok(/door|window|none|open/.test(e.type),`outline crossed at ${e.type}`); } } });
  check(`${tag}: sight is symmetric`,()=>{ const r=R.rng(tag); for(let k=0;k<400;k++){ const a=Math.floor(r()*w.N), b=Math.floor(r()*w.N); if(!w.passable(a)||!w.passable(b)) continue; assert.strictEqual(w.sight(a,b),w.sight(b,a),`${a}<->${b}`); } });
  check(`${tag}: same seed, same world`,()=>{ const w2=worldOf(s.id,h); assert.deepStrictEqual(Array.from(w2.speed),Array.from(w.speed)); assert.deepStrictEqual([...w2.G.O.edges.keys()],[...w.G.O.edges.keys()]); });
}

// ---------- the Roadrunner den by hand ----------
const RR='newriver/2_2/0';
const w=worldOf(RR,'den');
const inside=c=>w.isInside(c);
check('Roadrunner: den has raiders, a boss, a front door and windows',()=>{
  assert.ok(w.people.length>=3,'raiders'); assert.ok(w.people.some(p=>p.boss),'boss'); assert.ok(w.frontApproach(),'front door'); assert.ok(w.entries().some(e=>e.kind==='window'),'windows'); });
check('Roadrunner: someone outside a plain wall can neither see nor shoot the person behind it',()=>{
  const ent=[...edgesOf(w)].find(x=>x.e.type==='wall'&&x.e.ext); assert.ok(ent); const out=inside(ent.c)?ent.n:ent.c, inn=inside(ent.c)?ent.c:ent.n;
  // stand 4 m out, straight back from the wall
  const d=w.step(inn,0)===out?0:w.step(inn,1)===out?1:w.step(inn,2)===out?2:3; let far=out; for(let k=0;k<3;k++) far=w.step(far,d);
  assert.ok(!w.sight(far,inn),'sight through outer wall'); assert.strictEqual(w.coverFrom(inn,w.cx(far),w.cz(far)),2); });
check('Roadrunner: opening the front door opens a line of sight into the dining room, closing it shuts it',()=>{
  const fa=w.frontApproach(), key=fa.door.edges[0].key, before=w.doorState(fa.door.edges[0]);
  let far=fa.outCell; for(let k=0;k<5;k++) far=w.step(far,fa.dir);
  let deep=fa.inCell; const back=(fa.dir+2)%4; for(let k=0;k<3&&w.passable(w.step(deep,back))&&w.edgeFree(deep,back);k++) deep=w.step(deep,back);
  w.setDoor(key,'open'); assert.ok(w.sight(far,deep),'open door should show the room');
  w.setDoor(key,'closed'); assert.ok(!w.sight(far,deep),'closed door should hide the room');
  w.setDoor(key,before); });
check('Roadrunner: tall furniture blocks sight, low furniture does not',()=>{
  let tall=0, low=0;
  for(let c=0;c<w.N;c++){ if(!inside(c)) continue; const it=w.itemAt(c); if(!it) continue;
    for(const d of [0,1]){ const a=w.step(c,d+2), b=w.step(c,d); if(!w.passable(a)||!w.passable(b)||w.itemAt(a)||w.itemAt(b)) continue; if(w.edge(a,d)||w.edge(c,d)) continue;
      const blocks=it.spec.cover==='full'&&it.spec.h>=IW.EYE; assert.strictEqual(w.sight(a,b),!blocks,`${it.key} h${it.spec.h}`); blocks?tall++:low++; } }
  assert.ok(tall+low>0,'found furniture to look across'); });
check('Roadrunner: cover shows up beside furniture and walls, and the open floor is flanked',()=>{
  let half=0, full=0, open=0;
  for(let c=0;c<w.N;c++){ if(!inside(c)||!w.passable(c)) continue; for(let d=0;d<4;d++){ const v=w.coverDir(c,d); const n=w.step(c,d), it=w.itemAt(n), e=w.edge(c,d);
      if(!e&&it) assert.strictEqual(v,{none:0,half:1,full:2}[it.spec.cover]);
      if(v===1) half++; else if(v===2) full++; else open++; } }
  assert.ok(half&&full&&open,`half ${half} full ${full} open ${open}`);
  const mid=[...Array(w.N).keys()].find(c=>inside(c)&&w.passable(c)&&[0,1,2,3].every(d=>w.coverDir(c,d)===0));
  assert.ok(mid!==undefined,'an open cell'); const o=R.odds(w,{team:'squad',c:w.step(w.step(w.step(mid,0),0),0)},{team:'raider',c:mid}); assert.ok(o.flanked&&o.crit===40); });
check('Roadrunner: a unit behind full cover leans out to shoot, but never through the wall',()=>{
  let tried=0; for(const {c,n,e} of edgesOf(w)){ if(e.type!=='wall'||e.ext) continue; tried++; const lf=R.lineOfFire(w,c,n); if(lf){ assert.ok(lf.from!==c||lf.to!==n,'shot straight through a wall'); } if(tried>60) break; } });
check('Roadrunner: the squad gets in only through openings; from the street the boss is reachable',()=>{
  const fa=w.frontApproach(), boss=w.people.find(p=>p.boss), r=R.reach(w,{c:fa.outCell},null,500);
  const p=R.pathTo(r,boss.c); assert.ok(r.cost.has(boss.c),'boss unreachable');
  for(let k=1;k<p.length;k++) if(inside(p[k-1])!==inside(p[k])) assert.ok(/door|window/.test(w.edgeBetween(p[k-1],p[k]).type)); });
check('Roadrunner: a seeded fight replays exactly',()=>{
  const mk=()=>{ const ww=worldOf(RR,'den'), fa=ww.frontApproach(); const units=ww.people.map((p,i)=>({id:'r'+i,team:'raider',c:p.c,hp:p.boss?6:4,alive:true,face:0}));
    const occ=new Set(units.map(u=>u.c)); let c=fa.outCell; const sq=[]; for(let k=0;sq.length<4&&k<200;k++){ if(ww.passable(c)&&!occ.has(c)){ sq.push(c); occ.add(c); } c=k%2?ww.step(c,(fa.dir+1)%4):ww.step(c,fa.dir); if(c<0) c=fa.outCell; }
    sq.forEach((c,i)=>units.push({id:'s'+i,team:'squad',c,hp:6,alive:true})); return [ww,units]; };
  const [w1,u1]=mk(), [w2,u2]=mk(); const a=R.simulate(w1,u1,'replay'), b=R.simulate(w2,u2,'replay');
  assert.deepStrictEqual(a.log,b.log); assert.ok(a.log.length>0); });
check('odds match the foundation table',()=>{
  const flat={cx:c=>c,cz:()=>0,coverFrom:(c)=>c===100?2:c===200?1:0};
  const o=(ac,bc,opt,b)=>R.odds(flat,{team:'squad',c:ac},Object.assign({team:'raider',c:bc},b||{}),opt).aim;
  assert.strictEqual(o(0,12),72); assert.strictEqual(o(0,4),82); assert.strictEqual(o(90,100),32); assert.strictEqual(o(190,200),52);
  assert.strictEqual(o(90,100,{},{hunker:true}),12); assert.strictEqual(o(0,12,{reaction:true}),57); assert.strictEqual(o(0,12,{free:true}),82);
  assert.strictEqual(o(0,34),57); assert.strictEqual(o(0,60),32); });

// ---------- report ----------
if(process.argv.includes('--map')){
  // two characters a metre: cells on odd places, the edges between them on even ones
  const ppl=w.posted(), sentry=ppl.find(p=>p.role==='sentry')||ppl[0], seen=new Set();
  for(let c=0;c<w.N;c++) if(w.passable(c)&&R.sees(w,sentry,c)) seen.add(c);
  const at=new Map(ppl.map(p=>[p.c,p.role==='sentry'?'S':p.boss?'B':'R']));
  let i0=1e9,i1=-1,j0=1e9,j1=-1; for(let c=0;c<w.N;c++) if(w.isInside(c)){ i0=Math.min(i0,c%w.W); i1=Math.max(i1,c%w.W); j0=Math.min(j0,(c/w.W)|0); j1=Math.max(j1,(c/w.W)|0); }
  i0-=3; j0-=3; i1+=3; j1+=3; const out=[];
  const ech=(e,v)=>!e?' ':e.type==='wall'?(v?'|':'-'):e.type==='window'?(e.win.state==='boarded'?'#':e.win.state==='broken'?'%':'~'):/door/.test(e.type)?({open:'/',broken:'_',closed:'D',barricaded:'X'}[w.doorState(e)]||'D'):e.type==='counter'?'=':' ';
  for(let j=j0;j<=j1;j++){ let top='', mid='';
    for(let i=i0;i<=i1;i++){ const c=j*w.W+i, it=w.itemAt(c);
      let ch=at.get(c)||(it?(w.blocksSight(c)?'#':'o'):!w.passable(c)?'x':w.isInside(c)?'.':' ');
      if(seen.has(c)&&(ch==='.'||ch===' ')) ch=w.isInside(c)?':':'`';
      top+=' '+ech(w.edge(c,3),false); mid+=ech(w.edge(c,2),true)+ch; }
    out.push(top.replace(/\s+$/,''),mid.replace(/\s+$/,'')); }
  console.log(out.join('\n'));
  console.log('S sentry (facing out of its window), R raider, B boss · # tall furniture, o low furniture, x yard wall');
  console.log('| - wall · ~ window, % broken, # boarded · D closed door, / open, _ broken, X barricaded · : ` cells the sentry sees (inside, outside)');
}
console.log(`${pass} passed, ${fail} failed`); if(fail){ for(const f of fails.slice(0,30)) console.log('  ✗ '+f); process.exit(1); }
