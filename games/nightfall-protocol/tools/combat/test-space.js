#!/usr/bin/env node
// Sight, cover and movement checks for free-placement fights inside generated buildings.
//   node tools/combat/test-space.js           every check
//   node tools/combat/test-space.js --quick   Roadrunner only
// The interiors are procedural and owned by the interiors topic, so the checks are invariants over whatever the
// generator makes (every wall, window and door), run on every test site and history, plus hand checks on the
// Roadrunner (newriver/2_2/0) that find their places by searching rather than by fixed coordinates.
const assert=require('assert');
const {loadGenerator}=require('./interiors-slice.js');
const SP=require('./space.js'), R=require('./rules.js');
const I=loadGenerator();
let pass=0, fail=0; const fails=[];
function check(name,fn){ try{ fn(); pass++; } catch(e){ fail++; fails.push(name+': '+e.message); } }
const spaceOf=(id,history,seed)=>{ const s=I.SITES.find(x=>x.id===id); return SP.fromGenerated(I.generate(s,'auto',seed||id,history)); };
const edges=w=>w.obs.filter(o=>o.kind==='edge');
// two points straddling a segment's middle, d from it on each side
function straddle(o,d){ const [ax,az,bx,bz]=o.seg, mx=(ax+bx)/2, mz=(az+bz)/2, L=Math.hypot(bx-ax,bz-az), nx=-(bz-az)/L, nz=(bx-ax)/L; return [[mx+nx*d,mz+nz*d],[mx-nx*d,mz-nz*d]]; }
// is p→q blocked by any wall segment (strict crossing)
const crossesWall=(w,p,q)=>w.obs.some(o=>o.kind==='edge'&&o.e.type==='wall'&&SP.segSeg(p[0],p[1],q[0],q[1],...o.seg)>0.001&&SP.segSeg(p[0],p[1],q[0],q[1],...o.seg)<0.999);

const HIST=['untouched','looted','holdout','den'];
const quick=process.argv.includes('--quick');
for(const s of (quick?I.SITES.filter(x=>x.id==='newriver/2_2/0'):I.SITES)) for(const h of HIST){
  const tag=`${s.id} ${h}`; let w;
  check(`${tag}: builds`,()=>{ w=spaceOf(s.id,h); assert.ok(w.obs.length>0); });
  if(!w) continue;
  check(`${tag}: walls stop sight and shots, and a body tight against one has full cover from the far side`,()=>{
    for(const o of edges(w)) if(o.e.type==='wall'){ const [a,b]=straddle(o,.45), [fa,fb]=straddle(o,4);
      assert.ok(!w.sight(a,b),`sight through wall ${o.e.key}`); assert.ok(!w.sight(a,b,{shot:true}),`shot through ${o.e.key}`);
      assert.strictEqual(w.coverFrom(a,fb),2,`wall ${o.e.key} cover`); assert.strictEqual(w.coverFrom(b,fa),2,`wall ${o.e.key} cover (other side)`); } });
  check(`${tag}: windows: glass and broken panes let sight through as half cover or better; boards stop it`,()=>{
    for(const o of edges(w)) if(o.e.type==='window'){ const [a,b]=straddle(o,.45), [fa,fb]=straddle(o,4), boarded=o.e.win.state==='boarded'; if(!w.clearAt(...a,.2)||!w.clearAt(...b,.2)) continue;   // shelving pushed against the glass
      assert.strictEqual(w.sight(a,b),!boarded,`window ${o.e.key} ${o.e.win.state}`); const cv=w.coverFrom(a,fb); assert.ok(boarded?cv===2:cv>=1,`window ${o.e.key} cover ${cv}`); } });
  check(`${tag}: doors: open or broken pass sight, closed and barricaded stop it, and that follows the door`,()=>{
    for(const o of edges(w)) if(/door/.test(o.e.type)){ const [a,b]=straddle(o,.45), st=w.doorState(o.e); if(!w.clearAt(...a,.2)||!w.clearAt(...b,.2)) continue; assert.strictEqual(w.sight(a,b),st==='open'||st==='broken',`door ${o.e.key} ${st}`); }
    const d=edges(w).find(o=>o.e.type==='door'&&w.doorState(o.e)!=='barricaded'); if(!d) return; const [a,b]=straddle(d,.45), before=w.doorSt[d.e.key];
    w.doorSt[d.e.key]='open'; assert.ok(w.sight(a,b)); w.doorSt[d.e.key]='closed'; assert.ok(!w.sight(a,b)); if(before===undefined) delete w.doorSt[d.e.key]; else w.doorSt[d.e.key]=before; });
  check(`${tag}: sight is symmetric`,()=>{ const r=R.rng(tag); for(let k=0;k<300;k++){ const a=[w.X0+r()*(w.X1-w.X0),w.Z0+r()*(w.Z1-w.Z0)], b=[w.X0+r()*(w.X1-w.X0),w.Z0+r()*(w.Z1-w.Z0)]; assert.strictEqual(w.sight(a,b),w.sight(b,a)); } });
  check(`${tag}: routes keep bodies out of walls and furniture, and go in and out only through openings`,()=>{
    const fa=w.frontApproach(); if(!fa) return; const F=w.field(fa.out,300), r=R.rng(tag+'paths'); let n=0;
    for(let k=0;k<4000&&n<25;k++){ const m=Math.floor(r()*F.cost.length); if(!isFinite(F.cost[m])) continue; const p=[w.nodeX(m)+(r()-.5)*.3,w.nodeZ(m)+(r()-.5)*.3]; const P=w.pathTo(F,p); if(!P) continue; n++;
      const pts=P.points; for(let i=1;i<pts.length;i++){ const a=[pts[i-1].x,pts[i-1].z], b=[pts[i].x,pts[i].z];
        assert.ok(w.walk(a,b).ok,`leg ${i} of a route clips something solid`); assert.ok(!crossesWall(w,a,b),`leg ${i} crosses a wall`);
        if(w.insideAt(...a)!==w.insideAt(...b)&&Math.hypot(b[0]-a[0],b[1]-a[1])>.05) assert.ok(pts[i].through||pts[i-1].through||w.walk(a,b).crossed.length,'in or out without an opening'); }
      for(const q of pts) assert.ok(w.clearAt(q.x,q.z,w.R*.9)||q.through,'a waypoint inside something'); }
    assert.ok(n>0,'no routes sampled'); });
  check(`${tag}: same seed, same space`,()=>{ const w2=spaceOf(s.id,h); assert.strictEqual(w2.obs.length,w.obs.length); assert.deepStrictEqual(Array.from(w2.free),Array.from(w.free)); });
}

// ---------- the Roadrunner den by hand ----------
const RR='newriver/2_2/0', w=spaceOf(RR,'den'), fa=w.frontApproach(), ppl=w.posted();
check('Roadrunner: raiders, a boss, a sentry at a window, a front door',()=>{ assert.ok(ppl.length>=3); assert.ok(ppl.some(p=>p.boss)); assert.ok(ppl.some(p=>p.role==='sentry')); assert.ok(fa); });
check('Roadrunner: free placement: range is round, not stepped',()=>{
  // open yard in front: the cost of points 8 m away in eight directions stays within 4% of the straight distance
  const F=w.field(fa.out,40); let tried=0;
  for(let k=0;k<16;k++){ const a=k/16*Math.PI*2, p=[fa.out[0]+Math.sin(a)*8,fa.out[1]+Math.cos(a)*8]; if(!w.clearAt(...p)||w.insideAt(...p)||!w.walk(fa.out,p).ok||w.walk(fa.out,p).crossed.length) continue;
    const c=w.costTo(F,p); if(!c) continue; tried++; let straight=0; for(let k2=0;k2<80;k2++){ const t=(k2+.5)/80; straight+=.1/w.speedAt(fa.out[0]+(p[0]-fa.out[0])*t,fa.out[1]+(p[1]-fa.out[1])*t); } assert.ok(c.cost<=straight*1.06+.2,`cost ${c.cost.toFixed(2)} vs ${straight.toFixed(2)}`); }
  assert.ok(tried>=4,`only ${tried} open directions`); });
check('Roadrunner: any point in reach is a valid place to stand, not just node centres',()=>{
  const F=w.field(fa.out,12), p=[fa.out[0]+.37,fa.out[1]+1.91]; if(w.clearAt(...p)){ const c=w.costTo(F,p); assert.ok(c&&!c.over); const P=w.pathTo(F,p); const end=P.points[P.points.length-1]; assert.ok(Math.hypot(end.x-p[0],end.z-p[1])<1e-9); } });
check('Roadrunner: a click near a wall snaps to just behind it',()=>{
  const wall=edges(w).find(o=>o.e.type==='wall'&&o.ext&&(()=>{ const [a]=straddle(o,1); return w.clearAt(...a)&&!w.insideAt(...a); })()); assert.ok(wall);
  const [a]=straddle(wall,.75), q=w.snap(a), d=SP.ptSeg(q[0],q[1],...wall.seg).d; assert.ok(Math.abs(d-(w.R+.06))<.02,`snapped ${d.toFixed(3)} from the wall`); });
check('Roadrunner: someone right outside a plain wall can neither see nor shoot the person behind it',()=>{
  const wall=edges(w).find(o=>o.e.type==='wall'&&o.ext); const [a,b]=straddle(wall,.5); assert.ok(!R.lineOfFire(w,{x:a[0],z:a[1]},{x:b[0],z:b[1]})); });
check('Roadrunner: the front door decides whether the street sees the dining room',()=>{
  const key=fa.key, before=w.doorState(fa.e); const far=[fa.out[0]+(fa.out[0]-fa.in[0])*6,fa.out[1]+(fa.out[1]-fa.in[1])*6], deep=[fa.in[0]-(fa.out[0]-fa.in[0])*2,fa.in[1]-(fa.out[1]-fa.in[1])*2];
  w.setDoor(key,'open'); assert.ok(w.sight(far,deep),'open door should show the room'); w.setDoor(key,'closed'); assert.ok(!w.sight(far,deep),'closed door should hide it'); w.setDoor(key,before); });
check('Roadrunner: tall furniture blocks sight, low furniture gives cover without blocking it',()=>{
  let tall=0, low=0;
  for(const o of w.obs){ if(o.kind!=='item') continue; const b=o.box, cz=(b.z0+b.z1)/2, a=[b.x0-.6,cz], c=[b.x1+.6,cz]; if(!w.clearAt(...a)||!w.clearAt(...c)) continue;
    if(w.obs.some(x=>x!==o&&(x.box?SP.segBox(a[0],a[1],c[0],c[1],x.box)>=0:SP.segSeg(a[0],a[1],c[0],c[1],...x.seg)>=0))) continue;
    const blocks=o.it.spec.cover==='full'&&o.h>=w.EYE; assert.strictEqual(w.sight(a,c),!blocks,`${o.it.key}`); blocks?tall++:low++;
    const cv={none:0,half:1,full:2}[o.it.spec.cover]; assert.strictEqual(w.coverFrom(a,[c[0]+4,c[1]]),cv,`${o.it.key} cover`); }
  assert.ok(tall+low>0,'no furniture to look across'); });
check('Roadrunner: cover depends on the angle: beside a wall but shot along it is flanked',()=>{
  const wall=edges(w).find(o=>o.e.type==='wall'&&o.ext&&(()=>{ const [a]=straddle(o,1); return w.clearAt(...a)&&!w.insideAt(...a); })());
  const [ax,az,bx,bz]=wall.seg, L=Math.hypot(bx-ax,bz-az), ux=(bx-ax)/L, uz=(bz-az)/L, [p]=straddle(wall,w.R+.06), n=[p[0]-(ax+bx)/2,p[1]-(az+bz)/2];
  const along=[p[0]+ux*10+n[0]*.5,p[1]+uz*10+n[1]*.5]; assert.strictEqual(w.coverFrom(p,along),0); });
check('Roadrunner: the squad gets in only through openings; from the street everyone inside is reachable',()=>{
  const F=w.field(fa.out,400); for(const p of ppl){ const P=w.pathTo(F,p.p); assert.ok(P,`${p.role} unreachable`); assert.ok(P.points.some(q=>q.through),'route without an opening'); } });
check('Roadrunner: a unit in cover leans out to shoot, never through the wall',()=>{
  const wall=edges(w).find(o=>o.e.type==='wall'&&!o.ext); const [a,b]=straddle(wall,w.R+.06); const lf=R.lineOfFire(w,{x:a[0],z:a[1]},{x:b[0],z:b[1]}); if(lf) assert.ok(!crossesWall(w,lf.from,lf.to)); });
check('Roadrunner: a seeded fight replays exactly',()=>{
  const mk=()=>{ const ww=spaceOf(RR,'den'), f=ww.frontApproach(); const units=ww.posted().map((p,i)=>R.makeUnit(p.boss?'boss':'raider',{id:'r'+i,team:'raider',boss:p.boss,x:p.p[0],z:p.p[1],face:p.face}));
    const L=Math.hypot(f.out[0]-f.in[0],f.out[1]-f.in[1]), n=[(f.out[0]-f.in[0])/L,(f.out[1]-f.in[1])/L], t=[-n[1],n[0]]; const roles=['ranger','sharpshooter','breacher','medic'];
    [[4,-1.5],[4,1.5],[6,-1.5],[6,1.5]].forEach(([a,b],i)=>units.push(R.makeUnit(roles[i],{id:'s'+i,team:'squad',x:f.out[0]+n[0]*a+t[0]*b,z:f.out[1]+n[1]*a+t[1]*b})));
    return [ww,units]; };
  const [w1,u1]=mk(), [w2,u2]=mk(); const a=R.simulate(w1,u1,'replay',12), b=R.simulate(w2,u2,'replay',12); assert.deepStrictEqual(a.log,b.log); assert.ok(a.log.length>0); });
check('weapon range profiles: shotguns want it close, rifles want room',()=>{
  const flat={coverFrom:()=>0}, at=(wp,d)=>R.odds(flat,{team:'squad',aim:70,weapon:R.WEAPONS[wp],x:0,z:0},{team:'raider',x:d,z:0}).aim;
  assert.strictEqual(at('shotgun',4),85); assert.strictEqual(at('shotgun',12),70); assert.strictEqual(at('shotgun',20),54);
  assert.strictEqual(at('rifle',4),60); assert.strictEqual(at('rifle',30),70); assert.strictEqual(at('rifle',45),65);
  assert.strictEqual(at('carbine',4),80); assert.strictEqual(at('carbine',30),61);
  const o=R.odds({coverFrom:()=>2},{team:'squad',aim:76,weapon:R.WEAPONS.rifle,x:0,z:0},{team:'raider',x:20,z:0},{steady:true}); assert.strictEqual(o.aim,51); assert.deepStrictEqual(o.why.map(x=>x[0]),['Aim','Full cover','Steady aim']);
  assert.strictEqual(R.odds(flat,{team:'squad',weapon:R.WEAPONS.carbine,x:0,z:0},{team:'raider',x:12,z:0},{reaction:true,doorway:true}).aim,72); });
check('Roadrunner: a pipe bomb destroys the cover it reaches, frees the floor, and walls shelter people behind them',()=>{
  const ww=spaceOf(RR,'den'), it=ww.obs.find(o=>o.kind==='item'&&o.it.spec.cover==='full'&&o.h>=1.5&&ww.clearAt(o.box.x0-.8,(o.box.z0+o.box.z1)/2)); assert.ok(it);
  const cz=(it.box.z0+it.box.z1)/2, c=[it.box.x0-.8,cz], behind=[it.box.x0-.36,cz], far=[it.box.x1+6,cz];
  assert.strictEqual(ww.coverFrom(behind,far),2); const br=ww.blastReach(c,3); assert.ok(br.items.includes(it),'blast should reach the item');
  for(const o of br.items) ww.destroyItem(o); assert.strictEqual(ww.coverFrom(behind,far),0,'cover should be gone'); assert.ok(ww.clearAt((it.box.x0+it.box.x1)/2,cz),'rubble should be walkable');
  const wall=ww.obs.find(o=>o.kind==='edge'&&o.e.type==='wall'&&o.ext); const [a,b]=straddle(wall,.6);
  const units=[{team:'raider',x:a[0],z:a[1],alive:true},{team:'raider',x:b[0],z:b[1],alive:true}]; const hits=R.blastHits(ww,[a[0]+(a[0]-b[0])*.5,a[1]+(a[1]-b[1])*.5],units);
  assert.strictEqual(hits.length,1,'only the one on the blast side'); assert.strictEqual(hits[0].u,units[0]); });
check('wounds: the squad goes down and bleeds, raiders die; morale breaks once the boss is down',()=>{
  const s=R.makeUnit('medic',{team:'squad'}), r=R.makeUnit('raider',{team:'raider'}); assert.strictEqual(R.hurt(s,3),'hit'); assert.strictEqual(R.hurt(s,9),'down'); assert.ok(s.down&&!s.alive&&s.bleed===R.V.bleed);
  assert.strictEqual(R.hurt(r,9),'dead'); assert.ok(r.dead);
  const units=[R.makeUnit('boss',{team:'raider',boss:true,alive:false}),R.makeUnit('raider',{team:'raider'}),R.makeUnit('raider',{team:'raider'})]; units[0].alive=false;
  const broke=R.morale(units,()=>.1); assert.strictEqual(broke.length,2); assert.ok(units[1].fleeing&&units[2].fleeing);
  assert.strictEqual(R.morale([R.makeUnit('boss',{team:'raider',boss:true}),R.makeUnit('raider',{team:'raider'})],()=>.1).length,0); });
check('odds match the foundation table',()=>{
  const flat={coverFrom:p=>p[0]===100?2:p[0]===200?1:0};
  const o=(ax,bx,opt,b)=>R.odds(flat,{team:'squad',x:ax,z:0},Object.assign({team:'raider',x:bx,z:0},b||{}),opt).aim;
  assert.strictEqual(o(0,12),72); assert.strictEqual(o(0,4),82); assert.strictEqual(o(88,100),32); assert.strictEqual(o(188,200),52);
  assert.strictEqual(o(88,100,{},{hunker:true}),12); assert.strictEqual(o(0,12,{reaction:true}),57); assert.strictEqual(o(0,12,{free:true}),82);
  assert.strictEqual(o(0,34),57); assert.strictEqual(o(0,60),32); });

console.log(`${pass} passed, ${fail} failed`); if(fail){ for(const f of fails.slice(0,30)) console.log('  ✗ '+f); process.exit(1); }
