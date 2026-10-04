// Quick sanity run for settlement.js: a year of stores, production, traders, civics and a summer drought, with stub people
// (fixed demand per head, a mood list the hook writes into). node tools/settlement/harness.js [seed]
// The shared harness with real people (tools/people) comes later.
const S=require('./settlement.js');
const DAY=S.DAY, seed=+(process.argv[2]||20261004);
const rng={rng:seed>>>0}, rnd=()=>S.rand(rng);
const TRAITS=['greedy','frugal','cautious','nervous','night-owl','brave','lazy','fair','loyal','tough'];
const people=[]; for(let i=0;i<20;i++){ const kid=i>=17;
  people.push({id:'s'+i,seed:i,name:'s'+i,born:kid?-(6+i-17)*365:-(20+Math.floor(rnd()*40))*365,body:{water:0,food:0,energy:1},conditions:[],
    traits:[TRAITS[Math.floor(rnd()*TRAITS.length)]],skills:{grow:Math.floor(rnd()*4),cook:Math.floor(rnd()*4),craft:Math.floor(rnd()*3),medic:Math.floor(rnd()*3),shoot:Math.floor(rnd()*4)},
    mood:[],rel:{},role:null,at:'base',alive:true}); }
for(const p of people) for(const q of people) if(p!==q) p.rel[q.id]={opinion:Math.round(rnd()*60-20)};
let now=0; const hooks={addMood:(p,key,value,hours)=>{ p.mood=p.mood.filter(m=>m.key!==key&&(m.until==null||m.until>=now)).concat({key,value,until:now+hours*60}); },setRole:(p,role)=>{ p.role=role; }};
const here=()=>people.filter(p=>p.alive&&p.at==='base');

const st=S.newState({seed,heads:20,capacity:{dry:3000,cool:300,tank:3000},amen:{well:3,garden:4,kitchen:2,workshop:1,infirmary:1}});
S.receive(st.stores,{food:300,water:1500,medicine:6,tools:20,fuel:60,gear:6,shelter:10,goods:15},0);
S.add(st.stores,'firewood',200,0); S.add(st.stores,'clothing',6,0); S.add(st.stores,'alcohol',4,0);
const roles=[['s0','leader'],['s1','medic'],['s2','guard'],['s3','guard'],['s4','scavenger'],['s5','scavenger'],['s6','cook'],['s7','builder']];
for(const [id,r] of roles) S.assign(st,people,id,r,hooks);
const traders=[S.makeTrader(seed+1),S.makeTrader(seed+2),S.makeTrader(seed+3)];

const DROUGHT=[150,215];   // the wells fail and the runs come back thin
const heatOn=d=>Math.max(0,Math.sin(Math.PI*(d-60)/240));   // summer peaks around day 180
let shortfall=0, spoiledKcal=0, trades=0, gone=[], month=null; const rows=[];
const fmt=(v,w=6)=>String(v).padStart(w);
console.log(`seed ${seed}: 20 survivors (3 children), 3 wells, 4 garden plots, 3 traders; drought days ${DROUGHT[0]}-${DROUGHT[1]}`);
console.log(' day heads foodD waterD ration  legit unrest  L-value R-value trades spoilt-kcal left');
for(let d=0;d<365;d++){ now=d*DAY+450; const heat=heatOn(d), drought=d>=DROUGHT[0]&&d<DROUGHT[1];
  st.need=S.needOf(here().length);
  // production: every offered task is worked by the best-skilled hand at home
  for(const task of S.offer(st,now)){ if(task.recipe==='water'&&drought&&rnd()<.6) continue; if(!task.urgency&&task.recipe!=='cook') continue;   // nobody bothers with what is plentiful
    const w=here().filter(p=>!S.isChild(p,now)).sort((a,b)=>((b.skills[task.skill]||0)-(a.skills[task.skill]||0))||(a.id<b.id?-1:1))[0]; S.work(st,task.id,w,now); }
  // a scavenging run every 4 days under the run rule
  if(d%4===2){ const runners=S.pickRunners(st,here(),3,now), k=drought?.4:1;
    if(runners.length) S.receive(st.stores,{food:Math.round((20+rnd()*40)*k),water:Math.round(rnd()*120*k),medicine:Math.round(rnd()*2),tools:Math.round(rnd()*6),fuel:Math.round(rnd()*20),gear:Math.round(rnd()*2),shelter:Math.round(rnd()*3),goods:Math.round(rnd()*5)},now); }
  // traders
  for(const v of S.traders(st,traders,now)) trades+=v.accepted.length;
  // the leader sets rationing from the stores
  const fd=S.daysOf(st.stores,st.need,'food'), wd=S.daysOf(st.stores,st.need,'water');
  const want=fd<10||wd<4?'survival':fd<20||wd<7?'reduced':'full';   // a leader who rations only when it bites
  if(want!==st.rules.ration) S.setRule(st,here(),'ration',want,{},hooks,now);
  if(drought&&st.rules.curfew==='none') S.setRule(st,here(),'curfew','dusk',{threat:.5},hooks,now);
  if(!drought&&st.rules.curfew!=='none') S.setRule(st,here(),'curfew','none',{threat:.1},hooks,now);
  // eat and drink: a day's demand at once
  const demands={}; for(const p of here()) demands[p.id]={water:S.isChild(p,now)?3:5+3*heat,food:S.isChild(p,now)?1400:2000};
  const rules={ration:st.rules.ration,priority:S.priorities(here(),now)}, allow=S.allowance(demands,rules), got=S.ration(st.stores,demands,rules,now);
  let ask=0,gave=0; for(const p of here()){ const g=got[p.id], dm=demands[p.id], al=allow[p.id]; ask+=al.food/2000+al.water/5; gave+=g.food/2000+g.water/5;
    // stub body: a deficit builds from what was asked and not had, recovers 400 kcal and 1 L a day, and stops at 4,000 kcal and 6 L
    p.body.food=Math.min(4000,Math.max(0,p.body.food+dm.food-g.food-400)); p.body.water=Math.min(6,Math.max(0,p.body.water+dm.water-g.water-1));
    if(p.body.food>1500) hooks.addMood(p,'hungry',-Math.min(20,p.body.food/300),24); }
  shortfall=ask?Math.max(0,1-gave/ask):0;   // against what the rules allow, not against appetite
  const lost=S.spoil(st.stores,st.capacity,1,heat); for(const [k,n] of Object.entries(lost)) spoiledKcal+=n*S.ITEMS[k].kcal;
  const civ=S.civicsDay(st,here(),{threat:drought?.5:.1,shortfall},hooks,now);
  for(const id of civ.departures){ const p=people.find(q=>q.id===id); p.at='gone'; gone.push(id); }
  if(st.leader==null&&here().length){ const next=here().filter(p=>!S.isChild(p,now)).sort((a,b)=>(st.unrest[a.id]||0)-(st.unrest[b.id]||0))[0]; if(next) S.assign(st,people,next.id,'leader',hooks); }
  if(d%30===29||d===364){ const hold={stores:st.stores,need:st.need}, un=here().filter(p=>!S.isChild(p,now)), avgU=un.reduce((a,p)=>a+(st.unrest[p.id]||0),0)/Math.max(1,un.length);
    console.log(`${fmt(d+1,4)} ${fmt(here().length,5)} ${fmt(fd.toFixed(1))} ${fmt(wd.toFixed(1))} ${st.rules.ration.padStart(8)} ${fmt(st.legit.toFixed(0))} ${fmt(avgU.toFixed(0))} ${fmt(S.valueOf(hold,'bottled',1).toFixed(2),8)} ${fmt(S.valueOf(hold,'ration',1).toFixed(1),7)} ${fmt(trades)} ${fmt(Math.round(spoiledKcal),11)} ${gone.length}`); } }
console.log(`ledger ${st.ledger.length} trades; reputation ${traders.map(t=>`${t.name} ${st.rep[t.id]||0}`).join(', ')}; left: ${gone.join(' ')||'nobody'}`);
