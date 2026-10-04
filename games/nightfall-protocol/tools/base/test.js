// Checks the base rules in Node: node tools/base/test.js
const fs=require('fs'), path=require('path'), R=require('./ranch-core.js'), P=R.People;
const SITE=JSON.parse(fs.readFileSync(path.join(__dirname,'../../data/base/ranch_site.json'),'utf8'));
let fails=0; const ok=(c,msg)=>{ console.log((c?'  ok   ':'  FAIL ')+msg); if(!c) fails++; };
const RANCH=SITE.presets.find(p=>p.key==='ranch').centre, HOME=SITE.presets.find(p=>p.key==='home').centre;
const fresh=(o={})=>R.create(SITE,Object.assign({centre:RANCH},o));
const run=h=>R.advance(h*60);
const at=(x,z)=>R.cellOf(x,z);
const finishAll=list=>{ for(const t of list){ t.delivered=true; t.progress=R.CATALOG[t.type].hours*60; } };

console.log('founding a base anywhere');
for(const pr of SITE.presets){ const st=fresh({centre:pr.centre});
  ok(Object.keys(st.claimed).includes('house')&&Object.values(st.places).every(c=>R.passable(c)),`${pr.label}: a house is claimed and its doors are passable`);
  ok(st.area[2]-st.area[0]===140&&st.area[3]-st.area[1]===140,`${pr.label}: the base is 140 m square`); }
{ ok(R.canFound(SITE,500,150)&&!R.canFound(SITE,140,0),'a base can be founded anywhere its square fits on the cut ground');
  const st=fresh({centre:[520,60]}); ok(st.people.length===6&&R.passable(st.places.home),'a base in open ground: people start by the middle');
  ok(R.canPlace('wall',at(520,60)).ok,'and building works there'); }
{ const st=fresh(); ok(st.things.length===1&&st.things[0].type==='pump'&&st.things[0].state==='broken','a base with a house has an old well waiting for a hand pump');
  ok(st.people.every(p=>p.rec.id&&p.rec.body&&p.rec.skills&&'build' in p.rec.skills),'survivors are People records'); }

console.log('the catalogue: building.md numbers, four inferred');
{ const C=R.CATALOG; ok(Object.keys(C).length===14,'fourteen buildables');
  ok(C.wall.hours===3&&C.wall.cost.shelter===2&&C.gate.w===2&&C.bunkhouse.w*C.bunkhouse.d===12&&C.tank.cost.goods===4&&C.watch.hours===12,'wall, gate, bunkhouse, tank and watch post as building.md');
  ok(['barricade','ramada','seep','pump'].every(k=>C[k].inferred),'barricade, ramada, seep and pump are marked inferred'); }

console.log('placing and grid writes');
{ fresh(); const st=R.state, G=st.grid;
  const line=R.placeLine('wall',at(740,-20),at(740,40)); ok(line.length===31,`a dragged wall line is 31 cells (${line.length})`);
  ok(line.every(t=>R.passable(t.cell)),'unfinished walls are still passable');
  ok(!R.place('bed',line[3].cell,0),'cannot place over a planned thing');
  ok(R.canPlace('wall',st.claimed.house.cells[0]).ok===false,'cannot build inside the house');
  ok(R.canPlace('wall',at(st.area[0]-6,st.area[1]+20)).ok===false,'cannot build outside the base');
  ok(R.canPlace('seep',at(700,60)).ok===false,'a seep only goes in a sand wash'); }
{ fresh(); const st=R.state, G=st.grid, from=at(735,40), to=at(770,40), before=R.findPath(from,to);
  const ws=R.placeLine('wall',at(752,-28),at(752,108)); finishAll(ws); run(.5);
  ok(ws.every(t=>t.state==='done'),'walls with their work done are finished on the next step');
  ok(G.kind[ws[10].cell]===R.NK.wall&&G.cover[ws[10].cell]===R.COVER.full,'a wall writes kind wall and full cover');
  const after=R.findPath(from,to); ok(!after||after.cost>before.cost*3,'a wall across the base cuts the way');
  const b=R.placeLine('barricade',at(730,60),at(736,60)); finishAll(b); run(.5); ok(G.cover[b[0].cell]===R.COVER.half&&G.kind[b[0].cell]===R.NK.wall,'a barricade is wall with half cover');
  const k=R.place('kitchen',at(715,70),0); finishAll([k]); run(.5); ok(G.cover[k.cells[0]]===R.COVER.half&&R.passable(k.cells[0]),'a kitchen keeps its ground kind with half cover (building.md)'); }
{ fresh({minute:12*60}); const st=R.state, G=st.grid; const ws=R.placeLine('wall',at(752,-28),at(752,108)); const mid=ws[30]; R.cancel(mid.id); R.cancel(ws[31].id);
  const gate=R.place('gate',mid.cell,0); finishAll([...ws,gate]); run(.5);
  ok(gate.state==='done'&&!gate.shut&&G.kind[gate.cells[0]]!==R.NK.wall,'by day the gate stands open');
  ok(!!R.findPath(at(735,40),at(770,40)),'and people get through');
  run(10.5); ok(gate.shut&&G.kind[gate.cells[0]]===R.NK.wall&&G.cover[gate.cells[0]]===R.COVER.full,'at night it shuts: wall, full cover');
  ok(!!R.findPath(at(735,40),at(770,40)),'and still lets the base\'s own people through'); }

console.log('people take the work and build');
{ fresh({minute:6*60}); const st=R.state;
  const tank=R.place('tank',at(730,30),0), beds=[0,1].map(k=>R.place('bed',at(722+k*2,44),0)), w=R.placeLine('wall',at(752,0),at(752,10));
  ok(!!tank&&beds.every(Boolean)&&w.length===6,'ordered a tank, two beds and six walls');
  const sh0=st.stock.shelter, g0=st.stock.goods, pos0=st.people.map(p=>[p.x,p.z]);
  run(1); ok(st.people.filter((p,i)=>Math.hypot(p.x-pos0[i][0],p.z-pos0[i][1])>3).length>=4,'within an hour most have walked off to work');
  ok(st.people.filter(p=>p.task&&p.task.kind==='build').length>=3,'several are building (People.score picked the build tasks)');
  run(4.5); const mid=st.people.filter(p=>p.task&&p.task.kind==='rest').length; ok(mid>=2,`in the heat at 10:30 ${mid} rest in the house`);
  run(48); ok(tank.state==='done'&&beds.every(b=>b.state==='done')&&w.every(t=>t.state==='done'),'within two days the tank, beds and walls are finished');
  ok(st.stock.shelter===sh0-2-2-12&&st.stock.goods===g0-4,`materials were used: shelter ${sh0}→${st.stock.shelter}, goods ${g0}→${st.stock.goods}`);
  ok(R.waterCap()===R.BARRELS+1000,'water capacity is now 1,400 L'); }
{ // skill: Build 1 takes the catalogue's hours, each level above 15% less, and outdoor work in the heat half speed
  fresh({minute:6*60}); const st=R.state, p=st.people[0]; p.rec.skills.build=3; const t=R.place('wall',at(760,20),0); t.delivered=true;
  for(const q of st.people) if(q!==p){ q.rec.skills.build=0; } st.people.forEach(q=>{ q.task=null; });
  const task={id:'x',kind:'build',steps:[{do:'build',act:'work'}],step:0,thing:t,skill:'build'}; p.task=task; p.x=R.cellXZ(R.accessOf(t))[0]; p.z=R.cellXZ(R.accessOf(t))[1];
  st.people.splice(1); R.advance(60); ok(Math.abs(t.progress-60/Math.pow(.85,2))<1,`Build 3 works ${(t.progress/60).toFixed(2)} hours of the wall in an hour (1/0.85² = 1.38)`); }

console.log('night: beds, the bunkhouse, the house, the watch');
{ fresh({minute:6*60}); const st=R.state; const beds=[0,1].map(k=>R.place('bed',at(722+k*2,44),0)), post=R.place('watch',at(760,60),0); finishAll([...beds,post]); run(.5);
  run(17); const asleep=st.people.filter(p=>p.rec.asleep), guards=st.people.filter(p=>p.task&&p.task.kind==='guard');
  ok(guards.length===2,`two keep watch on the post (${guards.length})`);
  ok(asleep.length===4,`the other four sleep (${asleep.length})`);
  ok(st.people.filter(p=>p.task&&p.task.kind==='sleep'&&p.task.spot.bed).length===2,'two on the beds, the rest on the house floor');
  run(7); ok(st.people.every(p=>!p.rec.asleep&&!(p.task&&p.task.kind==='guard')),'at 06:30 everyone is up');
  run(16.5); ok(st.people.filter(p=>p.task&&p.task.kind==='guard').every(p=>p.watched===1),'the watch rotates to people who haven\'t stood it'); }
{ fresh({minute:6*60}); const st=R.state; const b=R.place('bunkhouse',at(735,50),0); finishAll([b]); run(.5); ok(st.grid.kind[b.cells[0]]===R.NK.building,'a bunkhouse is a building on the grid');
  run(18); ok(st.people.filter(p=>p.task&&p.task.kind==='sleep'&&p.task.spot.thing===b).length===4,'four sleep in its beds'); }

console.log('water and food through People');
{ fresh({minute:6*60}); const st=R.state, w0=st.stock.water; run(24);
  const used=w0-st.stock.water, body=st.people.reduce((s,p)=>s+p.rec.body.water,0), cans=st.people.reduce((s,p)=>s+R.CANTEEN-p.canteen,0);
  ok(used>40&&used<110,`a day draws ${used.toFixed(0)} L from the barrels for six people (People's rates in early-summer heat)`);
  ok(st.people.every(p=>P.thirstStage(p.rec)===0),'with water at home nobody is thirsty');
  ok(st.stock.food<30&&st.stock.food>22,`food comes from the stores: ${(30-st.stock.food).toFixed(1)} rations a day`);
  run(24*8); ok(st.dry&&st.people.every(p=>P.thirstStage(p.rec)>=1),'eight more days without new water: the barrels are dry and everyone is thirsty'); }
{ fresh({minute:6*60}); const st=R.state; st.stock.water=200;
  const seep=R.place('seep',at(769,95),0); ok(!!seep,'a seep dug in the wash'); R.orderRepair(); const pump=st.things.find(t=>t.type==='pump');
  run(48); ok(seep.state==='done'&&pump.state==='done','both done within two days');
  ok(R.inflow()===85,'they bring in 85 L a day');
  const tank=R.place('tank',at(730,30),0), c=R.place('catcher',at(720,70),0); finishAll([tank,c]); run(.5); const w=st.stock.water; ok(R.rainfall(10)===240&&st.stock.water===w+240,'10 mm of rain on a catcher fills the tank with 240 L'); }

console.log('tearing down an outbuilding');
{ fresh({minute:6*60}); const st=R.state, key=Object.keys(st.claimed).find(k=>st.claimed[k].role==='outbuilding'), b=st.claimed[key], s0=st.stock.shelter;
  ok(R.orderTear(key),'ordered'); run(30); ok(b.torn&&st.stock.shelter===s0+R.TEAR.gives.shelter,'taken apart for materials');
  ok(b.cells.every(c=>R.passable(c)&&st.grid.cover[c]===0),'its cells are open ground again'); }

console.log('determinism and speed');
{ const go=()=>{ fresh({minute:6*60,seed:7,centre:HOME}); R.place('tank',at(HOME[0]+20,HOME[1]+20),0); R.placeLine('wall',at(HOME[0]-30,HOME[1]),at(HOME[0]-30,HOME[1]+20)); run(30); return JSON.stringify(R.state.people.map(p=>[p.x.toFixed(3),p.z.toFixed(3),p.rec.body.water.toFixed(4)])); };
  ok(go()===go(),'the same seed and orders give the same base');
  fresh({minute:6*60}); R.place('tank',at(730,30),0); const t0=Date.now(); run(24*10); const ms=Date.now()-t0; ok(ms<6000,`ten days settle in ${ms} ms`); }

console.log(fails?`${fails} failed`:'all passed'); process.exit(fails?1:0);
