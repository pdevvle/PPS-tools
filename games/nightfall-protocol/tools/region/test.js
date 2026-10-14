// Rules check for campaign.js, no browser: node tools/region/test.js
const assert=require('assert'), fs=require('fs'), path=require('path');
const C=require('./campaign.js');
const R=JSON.parse(fs.readFileSync(path.join(__dirname,'../../data/region/region_i17.json'),'utf8'));
C.init(R);
const mem=()=>{ const m=new Map(); return {getItem:k=>m.has(k)?m.get(k):null,setItem:(k,v)=>m.set(k,String(v)),removeItem:k=>m.delete(k),size:()=>m.size}; };
let n=0; const t=(name,fn)=>{ fn(); n++; console.log('ok',name); };

t('light and heat follow the day',()=>{
  const noon=C.sunAt(12*60), night=C.sunAt(2*60), aft=C.sunAt(16*60);
  assert.equal(night.phase,'night'); assert.equal(night.daylight,0); assert.equal(noon.phase,'day');
  assert(aft.tempC>noon.tempC&&noon.tempC>night.tempC, 'hottest mid-afternoon');
  assert.equal(C.heatOf(29),0); assert.equal(C.heatOf(41),1);
  assert.equal(C.waterRate(true,0),.5); assert.equal(C.waterRate(true,1),1);   // foundation: 0.5 L, doubled in the heat
  assert(C.paceAt(2*60,true,0,false)<C.paceAt(2*60,false,0,false), 'darkness slows off-road travel most');
  assert(C.paceAt(15*60,false,1,false)<C.paceAt(8*60,false,0,false), 'heat slows travel'); });

t('routes keep their legs and forecast by time of day',()=>{
  const [hx,hz]=C.homeXZ, rt=C.route(hx,hz,hx-2000,hz-9000);
  assert(rt.pts.length===rt.segs.length+1); assert(Math.abs(rt.segs.reduce((a,s)=>a+s.h,0)-rt.hours)<1e-6);
  const tr=C.makeTrip(rt), dawn=C.forecast(tr,6*60,4,false), noon=C.forecast(tr,12*60,4,false), rest=C.forecast(tr,11*60,4,true);
  assert(noon.water>dawn.water, 'more water in the heat'); assert(rest.rest>0&&rest.arrive>noon.arrive, 'lying up costs time');
  const p=C.tripPos(tr,tr.total); assert(Math.hypot(p.x-(hx-2000),p.z-(hz-9000))<1); });

t('a new campaign starts with home known and raiders out there',()=>{
  const st=C.newGame(1); const [c,r]=C.home;
  assert.equal(st.know[r][c].k,C.K.CURRENT); assert.equal(st.squads.length,2); assert(st.bands.length>=3);
  assert.equal(st.squads[0].water,4*C.WATER_CAP); });

t('travel spends time and water and reveals ground',()=>{
  const st=C.newGame(2), [hx,hz]=C.homeXZ, before=st.know.flat().filter(k=>k.k>=C.K.SCOUT).length;
  st.bands=[];   // no interruptions
  C.send(1,hx+3000,hz-6000); let guard=0; while(st.squads[1].trip&&guard++<500) C.step(30);
  assert(!st.squads[1].trip,'arrived'); assert(st.squads[1].water<2*C.WATER_CAP,'drank'); assert(st.minutes>450);
  assert(st.know.flat().filter(k=>k.k>=C.K.SCOUT).length>before,'revealed'); });

t('scavenging takes time, fills the pack and empties the site; home takes the haul',()=>{
  const st=C.newGame(3); st.bands=[];
  const si=R.sites.findIndex(s=>s.loot==='food'&&C.sizeOf(s)>=2); const s=R.sites[si], [cx,cz]=C.secCentre(...s.sector);
  const sq=st.squads[0]; sq.x=cx; sq.z=cz; st.know[s.sector[1]][s.sector[0]].k=C.K.SCOUT;
  const full=C.stockOf(si).full; assert(C.canScavenge(0,si)); assert(C.scavenge(0,si));
  const h=C.scavHours(si,4); C.step(h*60-1); assert(sq.task,'still searching'); C.step(2); assert(!sq.task,'done');
  assert(C.packKg(sq)>0); assert(C.leftOf(si)<1&&C.leftOf(si)>0); assert(C.packKg(sq)+sq.water<=C.capKg(sq)+1e-9);
  assert(Object.values(C.stockOf(si).stock).reduce((a,b)=>a+b,0)<full);
  const [hx,hz]=C.homeXZ; C.send(0,hx,hz); let g=0; while(sq.trip&&g++<500) C.step(30);
  assert.equal(C.packKg(sq),0); assert(Object.values(st.base.stock).reduce((a,b)=>a+b,0)>0); assert.equal(sq.water,C.waterCap(sq)); });

t('raiders that come near make an encounter in the agreed shape, and answers resolve it',()=>{
  const st=C.newGame(4), sq=st.squads[1], b=st.bands[0]; const [hx,hz]=C.homeXZ;
  sq.x=hx+4000; sq.z=hz+4000; b.x=sq.x+300; b.z=sq.z; b.trip=null; b.campUntil=1e9; st.minutes=10*60; st.waitUntil=st.minutes+60;
  const out=C.step(1); const e=out.encounter; assert(e,'contact');
  for(const k of ['id','at','where','light','tempC','squad','enemy','firstSight','distance']) assert(k in e,k);
  assert(['unaware','suspicious','alert'].includes(e.enemy.alert)); assert.equal(e.enemy.count,b.size);
  assert(!C.running(),'clock holds during an encounter'); C.step(30); assert.equal(st.minutes,601,'no time passes');
  C.resolve('avoid'); if(st.enc) C.resolve('auto'); assert(!st.enc); });

t('saves and loads the whole campaign',()=>{
  const st=C.newGame(5), store=mem(); st.bands=[]; const [hx,hz]=C.homeXZ;
  C.send(0,hx-3000,hz+2000); C.step(45); C.stockOf(3);
  const snap=JSON.stringify(C.serial()); assert(C.save(store));
  C.newGame(6); assert.notEqual(JSON.stringify(C.serial()),snap);
  assert(C.load(store)); assert.equal(JSON.stringify(C.serial()),snap);
  assert(C.state.squads[0].trip,'trip survives'); C.step(30); assert(C.state.minutes>st.minutes-1);
  store.setItem(C.SAVE_KEY,'{broken'); assert.equal(C.load(store),false); });

t('wait runs the clock to the next dawn or dusk',()=>{
  const st=C.newGame(7); st.bands=[]; st.minutes=12*60; C.waitTurn(); assert(C.running());
  let g=0; while(C.running()&&g++<100) C.step(30); assert.equal(Math.round(st.minutes),19*60+35); });

t('the live tick runs the world but leaves the squad on the ground alone',()=>{
  C.newGame(); const st=C.state, sq=st.squads[0], x=sq.x, z=sq.z, w=sq.water, m=st.minutes; st.squads[1]&&C.send(1,sq.x-3000,sq.z-3000);
  const b=st.bands[0], bx=b.x, bz=b.z; C.tick(240,{except:0});
  assert(Math.abs(st.minutes-m-240)<1e-6, 'the clock ran four hours'); assert.equal(sq.x,x); assert.equal(sq.z,z); assert.equal(sq.water,w);
  assert(st.bands.some(o=>o.x!==bx||o.z!==bz)||st.bands.length!==4, 'raiders roam meanwhile'); });

t('a search on the ground takes stock at once and says how long it took',()=>{
  C.newGame(); const sq=C.state.squads[0];
  const idx=R.sites.findIndex(s=>s.loot==='food'); const before=C.leftOf(idx), res=C.searchNow(0,idx);
  assert(res&&res.hours>0, 'it reports the hours'); assert(C.leftOf(idx)<before, 'the site is picked over'); assert(!sq.task, 'the squad is free again'); });

console.log(`${n} checks passed`);
