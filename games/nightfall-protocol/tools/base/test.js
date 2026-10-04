// Checks the ranch rules in Node: node tools/base/test.js
const fs=require('fs'), path=require('path'), R=require('./ranch-core.js');
const SITE=JSON.parse(fs.readFileSync(path.join(__dirname,'../../data/base/ranch_site.json'),'utf8'));
let fails=0; const ok=(c,msg)=>{ console.log((c?'  ok   ':'  FAIL ')+msg); if(!c) fails++; };
const fresh=(o)=>R.create(SITE,o);
const run=(h)=>R.advance(h*60);
const at=(x,z)=>R.cellOf(x,z);

console.log('site and claims');
{ const st=fresh(), G=st.grid;
  ok(['house','barn','shed','outbuilding_w','outbuilding_e'].every(k=>st.claimed[k]&&st.claimed[k].cells.length>5),'five claimed buildings with their cells');
  ok(Object.values(st.places).every(c=>R.passable(c)),'house, barn and shed doors are passable');
  ok(G.cover[st.claimed.house.cells[0]]===R.COVER.full,'baked buildings are full cover');
  ok(st.things.length===1&&st.things[0].type==='pump'&&st.things[0].state==='broken','the old well waits for a repair');
  ok(R.canPlace('seep',at(700,60)).ok===false,'a seep cannot go on dry ground'); }

console.log('grid writes');
{ fresh(); const st=R.state, G=st.grid;
  const a=at(740,-20), b=at(740,40), line=R.placeLine('wall',a,b);
  ok(line.length===31,`a dragged wall line is 31 cells (${line.length})`);
  ok(line.every(t=>R.passable(t.cell)),'unfinished walls are still passable');
}
{ fresh(); const st=R.state, G=st.grid, c=at(760,60);
  const t=R.place('tank',c,0); ok(!!t&&t.cells.length===4,'a tank takes 2 x 2 cells');
  ok(!R.place('bed',c,0),'cannot place over a planned thing');
  ok(R.canPlace('wall',at(713,14)).ok===false,'cannot build inside the house');
  ok(R.canPlace('wall',at(600,0)).ok===false,'cannot build outside the buildable area'); }

console.log('a wall blocks paths and a gate lets people through');
{ fresh(); const st=R.state, G=st.grid;
  const a=at(745,-28), b=at(745,108), from=at(735,40), to=at(770,40);
  const before=R.findPath(from,to); ok(!!before,'open ground: a path across');
  const ws=R.placeLine('wall',a,b); for(const t of ws){ t.delivered=true; }
  // finish every wall directly through the rules' own finishing by giving each full progress and one work tick
  for(const t of ws){ t.progress=R.CATALOG.wall.hours*60; }
  for(const t of ws){ t.state='done'; for(const q of t.cells){ G.kind[q]=R.NK.wall; G.cover[q]=R.COVER.full; } }
  const blocked=R.findPath(from,to);
  ok(!blocked||R.findPath(from,to).cost>before.cost*3,'a wall across the site cuts the way (or forces a long way round the end)');
  ok(G.kind[ws[10].cell]===R.NK.wall&&G.cover[ws[10].cell]===R.COVER.full,'walls write kind wall and full cover');
  const gc=ws[34]?ws[34].cell:ws[Math.floor(ws.length/2)].cell; G.gate[gc]=1;
  const through=R.findPath(from,to); ok(!!through&&through.cells.includes(gc),'a gate cell opens the way for the ranch people'); }

console.log('people walk to jobs and build');
{ fresh({minutes:5*60}); const st=R.state;
  const tank=R.place('tank',at(730,30),0), bed1=R.place('bed',at(722,40),0), bed2=R.place('bed',at(724,40),0);
  const w=R.placeLine('wall',at(752,0),at(752,20));
  ok(!!tank&&!!bed1&&!!bed2&&w.length===11,'ordered a tank, two beds and eleven walls');
  const shelter0=st.stock.shelter, tools0=st.stock.tools;
  const pos0=st.people.map(p=>[p.x,p.z]);
  run(1); const moved=st.people.filter((p,i)=>Math.hypot(p.x-pos0[i][0],p.z-pos0[i][1])>3).length;
  ok(moved>=4,`within an hour ${moved} people have walked off to work`);
  ok(st.people.some(p=>p.task&&['build'].includes(p.task.kind)),'some are building');
  run(4.5);   // to 10:30: the heat
  ok(st.people.every(p=>!p.task||!['build','repair','tear'].includes(p.task.kind)),'at 10:30 nobody builds outdoors in the heat');
  ok(st.people.filter(p=>p.task&&p.task.kind==='rest_shade').length>=3,'most rest in shade in the heat');
  run(24+12);
  ok(tank.state==='done'&&bed1.state==='done'&&bed2.state==='done'&&w.every(t=>t.state==='done'),'by day 2 evening the tank, beds and walls are finished');
  ok(st.stock.shelter===shelter0-4-2-11&&st.stock.tools===tools0-2,`materials were used: shelter ${shelter0}→${st.stock.shelter}, parts ${tools0}→${st.stock.tools}`);
  ok(R.waterCap()===R.BARRELS+R.TANK,`water capacity is now ${R.waterCap()} L`);
  ok(R.state.grid.kind[tank.cells[0]]===R.NK.building,'the finished tank is a building on the grid'); }

console.log('night: beds and the house');
{ fresh({minutes:5*60}); const st=R.state; const beds=[0,1].map(k=>R.place('bed',at(722+k*2,40),0)); run(20);   // to 01:00 day 2
  const asleep=st.people.filter(p=>p.asleep); ok(asleep.length===6,`at 01:00 everyone is asleep (${asleep.length})`);
  ok(asleep.filter(p=>p.task.thing&&p.task.thing.type==='bed').length===2,'two sleep on the new beds');
  ok(asleep.filter(p=>p.inside).length===4,'the rest sleep inside the house');
  run(4.5); ok(st.people.every(p=>!p.asleep),'at 05:30 everyone is up'); }

console.log('water drains per person per hour');
{ fresh({minutes:0}); const st=R.state; const w0=st.stock.water, b0=st.people.reduce((s,p)=>s+p.behind,0);
  run(24); const used=(w0-st.stock.water)+(st.people.reduce((s,p)=>s+p.behind,0)-b0), want=R.dailyUse();
  ok(Math.abs(used-want)<.01,`a day uses ${used.toFixed(1)} L for six people (${(want/6).toFixed(1)} L each: 0.5 L/h, doubled 10:00–18:00)`);
  ok(st.people.every(p=>p.behind<R.THIRSTY),'with water in the barrels nobody goes thirsty');
  run(24*4); ok(st.stock.water<=0&&st.dry,'four more days with no new water and the barrels are dry');
  ok(st.people.every(p=>p.behind>R.THIRSTY),'and everyone is falling behind'); }

console.log('water sources');
{ fresh({minutes:5*60}); const st=R.state; st.stock.water=100;
  const seep=R.place('seep',at(769,95),0); ok(!!seep,'a seep dug in the wash');
  const pump=R.orderRepair(); ok(!!pump,'the well repair ordered');
  run(48); ok(seep.state==='done'&&pump.state==='done','both done within two days');
  const w=st.stock.water; run(24); ok(st.stock.water>w-R.dailyUse()+40,`the pump and seep add water: ${w.toFixed(0)} → ${st.stock.water.toFixed(0)} L over a day`); }

console.log('tearing down an outbuilding');
{ fresh({minutes:5*60}); const st=R.state, b=st.claimed.outbuilding_w, s0=st.stock.shelter; R.orderTear('outbuilding_w'); run(30);
  ok(b.torn&&st.stock.shelter===s0+R.TEAR.gives.shelter,'torn down for materials');
  ok(b.cells.every(c=>R.passable(c)&&st.grid.cover[c]===0),'its cells are open ground again'); }

console.log('determinism and speed');
{ const go=()=>{ fresh({minutes:5*60,seed:7}); R.place('tank',at(730,30),0); R.placeLine('wall',at(752,0),at(752,20)); run(30); return JSON.stringify(R.state.people.map(p=>[p.x.toFixed(3),p.z.toFixed(3),p.behind.toFixed(4)])); };
  ok(go()===go(),'the same seed and orders give the same ranch');
  fresh({minutes:5*60}); R.place('tank',at(730,30),0); const t0=Date.now(); run(24*10); const ms=Date.now()-t0;
  ok(ms<4000,`ten days settle in ${ms} ms`); }

console.log(fails?`${fails} failed`:'all passed'); process.exit(fails?1:0);
