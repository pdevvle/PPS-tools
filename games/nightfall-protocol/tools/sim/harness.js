// Shared settlement harness: real survivors (tools/people) living off real stores (tools/settlement), in 60-minute steps.
// node tools/sim/harness.js [seed] [hours] [--people n] [--wells n] [--gardens n] [--drought from-to] [--out series.json] [--quiet]
// Hourly: people ask (People.demand), the stores serve by the ration rule and priority (Settlement.ration), people live (People.step).
// Each morning at 06:00: production tasks go to the best-scoring hands (People.score → Settlement.work), the medic does the rounds,
// a run every 4 days brings loot home, traders call, the leader sets rationing, food spoils, civics settle and some may leave.
const fs=require('fs'), path=require('path');
const P=require('../people/people.js'), S=require('../settlement/settlement.js'), C=require('../region/campaign.js');

const argv=process.argv.slice(2), pos=[], opt={};
for(let i=0;i<argv.length;i++){ const a=argv[i]; if(a.startsWith('--')){ const k=a.slice(2); if(k==='quiet') opt.quiet=true; else opt[k]=argv[++i]; } else pos.push(a); }
const SEED=+(pos[0]||1), HOURS=+(pos[1]||20), N=+(opt.people||20), WELLS=+(opt.wells||6), GARDENS=+(opt.gardens||4);
const DROUGHT=opt.drought?opt.drought.split('-').map(Number):null;
const STEP=60, DAYS=Math.round(HOURS*P.LIFE_RATIO), START=7*60+30, DAY=1440;

const H={rng:(SEED*2654435761)>>>0}, rand=()=>P.rnd(H);
const people=[]; for(let i=0;i<N;i++) people.push(P.create(SEED*1000+i,{id:'s'+(i+1),minute:START}));
let now=START;
// settlement hooks take hours; People.addMood takes the world minute it ends
const hooks={addMood:(p,key,value,hours)=>P.addMood(p,key,value,hours==null?null:now+hours*60),setRole:(p,role)=>P.setRole(p,role)};
const here=()=>people.filter(p=>p.alive&&p.at==='base');
const adults=()=>here().filter(p=>!S.isChild(p,now));

const st=S.newState({seed:SEED,heads:N,capacity:{dry:3000,cool:300,tank:4000},amen:{well:WELLS,garden:GARDENS,kitchen:2,workshop:1,infirmary:1}});
S.receive(st.stores,{food:Math.round(N*1.25*7),water:N*14*3,medicine:6,tools:20,fuel:60,gear:6,shelter:10,goods:15},now);
S.add(st.stores,'firewood',200,now); S.add(st.stores,'clothing',6,now); S.add(st.stores,'alcohol',4,now);
{ const a=adults(), roles=['leader','medic','guard','guard','scavenger','scavenger','cook','builder'];
  roles.forEach((r,i)=>{ if(a[i]) S.assign(st,people,a[i].id,r,hooks); }); }
const traders=[S.makeTrader(SEED+1),S.makeTrader(SEED+2),S.makeTrader(SEED+3)];

const heatAt=m=>C.heatOf(C.sunAt(m).tempC);
const activityAt=(m,heat)=>{ const hr=Math.floor((m%DAY)/60); return hr>=22||hr<6?'sleep':heat<.3?'work':'rest'; };
const inDrought=d=>!!DROUGHT&&d>=DROUGHT[0]&&d<DROUGHT[1];

const series=[], events=[], t0=Date.now();
let day=0, job={}, acc={n:0,mood:0,health:0,water:0,food:0}, ask=0, gave=0, trades=0, prio={};
for(let m=START;m<START+DAYS*DAY;m+=STEP){ now=m;
  const heat=heatAt(m), act=activityAt(m,heat), home=here();
  if(((m-6*60)%DAY+DAY)%DAY<STEP){   // ---------- the morning ----------
    day=Math.floor((m-START)/DAY); st.need=S.needOf(home.length); prio=S.priorities(home,m); job={};
    // production: each offered task goes to the free adult who scores it best
    const free=new Set(adults().filter(p=>!(p.brk&&p.brk.until>m)).map(p=>p.id));
    for(const task of S.offer(st,m)){ if(task.recipe==='water'&&inDrought(day)&&rand()<.7) continue;   // the wells run low
      let best=null,bs=-Infinity; for(const p of home) if(free.has(p.id)){ const s=P.score(p,task,{minute:m,heat}); if(s>bs){ bs=s; best=p; } }
      if(!best) break; free.delete(best.id); S.work(st,task.id,best,m); job[best.id]=task.skill; }
    // the medic's round: dressings or kits on anything that needs them
    const medic=home.find(p=>p.role==='medic'), q=.5+(medic?medic.skills.medic:0)/10;
    for(const p of home) for(const c of p.conditions) if(!c.treated&&c.severity>.15&&P.COND[c.kind]&&c.kind!=='dehydration'&&c.kind!=='malnutrition'){
      const used=S.take(st.stores,'bandage',1).length?1:S.take(st.stores,'medkit',1).length?1:0; if(!used) break; P.treat(p,c.kind,q); }
    // a run every 4 days; thinner in a drought
    if(day%4===2){ const runners=S.pickRunners(st,home,3,m), k=inDrought(day)?.4:1;
      if(runners.length) S.receive(st.stores,{food:Math.round((20+rand()*40)*k),water:Math.round(rand()*120*k),medicine:Math.round(rand()*2),tools:Math.round(rand()*6),
        fuel:Math.round(rand()*20),gear:Math.round(rand()*2),shelter:Math.round(rand()*3),goods:Math.round(rand()*5)},m); }
    for(const v of S.traders(st,traders,m)) trades+=v.accepted.length;
    // the leader rations when it bites, and calls a curfew in a drought
    const fd=S.daysOf(st.stores,st.need,'food'), wd=S.daysOf(st.stores,st.need,'water');
    const want=fd<10||wd<4?'survival':fd<20||wd<7?'reduced':'full';
    if(want!==st.rules.ration) S.setRule(st,home,'ration',want,{},hooks,m);
    const curfew=inDrought(day)?'dusk':'none'; if(curfew!==st.rules.curfew) S.setRule(st,home,'curfew',curfew,{threat:inDrought(day)?.5:.1},hooks,m);
    S.spoil(st.stores,st.capacity,1,heatAt(m+8*60));
    const shortfall=ask?Math.max(0,1-gave/ask):0; ask=gave=0;
    const civ=S.civicsDay(st,home,{threat:inDrought(day)?.5:.1,shortfall},hooks,m);
    for(const id of civ.departures){ const p=people.find(q=>q.id===id); p.at='gone'; p.left=m; events.push({kind:'left',id,minute:m,cause:'civics'}); }
    if(st.leader==null&&adults().length){ const next=adults().sort((a,b)=>(st.unrest[a.id]||0)-(st.unrest[b.id]||0))[0]; S.assign(st,people,next.id,'leader',hooks); }
    if(day>0){ const k=acc.n||1; series.push({day:day-1,alive:people.filter(p=>p.alive).length,here:home.length,ration:st.rules.ration,
      foodDays:+fd.toFixed(1),waterDays:+wd.toFixed(1),shortfall:+shortfall.toFixed(3),legit:Math.round(st.legit),
      mood:+(acc.mood/k).toFixed(1),health:+(acc.health/k).toFixed(3),thirst:+(acc.water/k).toFixed(2),hunger:Math.round(acc.food/k)}); }
    acc={n:0,mood:0,health:0,water:0,food:0}; }
  // ---------- the hour ----------
  const envs={}, dem={};
  for(const p of here()){ let a=act; if(a==='work'&&(S.isChild(p,m)||(p.brk&&p.brk.until>m))) a='rest';
    envs[p.id]={minute:m,heat,activity:a,bed:true,skill:a==='work'?job[p.id]||null:null}; dem[p.id]=P.demand(p,STEP,envs[p.id]); }
  const rules={ration:st.rules.ration,priority:prio}, allow=S.allowance(dem,rules), got=S.ration(st.stores,dem,rules,m);
  for(const p of here()){ const g=got[p.id]||{water:0,food:0}, al=allow[p.id];
    if(al){ ask+=al.food/2000+al.water/5; gave+=g.food/2000+g.water/5; }
    if(g.cooked>.5) P.addMood(p,'ate-cooked',3,m+12*60);
    if(envs[p.id].activity==='work'&&envs[p.id].skill&&rand()<.0004) events.push({kind:'injury',id:p.id,minute:m,severity:+P.injure(p,.1+.6*rand(),m).severity.toFixed(2)});
    for(const e of P.step(p,STEP,envs[p.id],{water:g.water,food:g.food})) events.push(e);
    if(p.alive){ acc.n++; acc.mood+=P.moodOf(p); acc.health+=p.health; acc.water+=p.body.water; acc.food+=p.body.food; } } }
const ms=Date.now()-t0;

// ---------- summary ----------
const deaths=events.filter(e=>e.kind==='death'), left=events.filter(e=>e.kind==='left'), byCause={};
for(const d of deaths) byCause[d.cause]=(byCause[d.cause]||0)+1;
const out={meta:{seed:SEED,hours:HOURS,days:DAYS,people:N,wells:WELLS,gardens:GARDENS,drought:DROUGHT,ms},series,events,deathsByCause:byCause,
  ledger:st.ledger.length,reputation:Object.fromEntries(traders.map(t=>[t.name,st.rep[t.id]||0]))};
if(opt.out){ fs.mkdirSync(path.dirname(path.resolve(opt.out)),{recursive:true}); fs.writeFileSync(opt.out,JSON.stringify(out)); }
if(!opt.quiet){
  console.log(`sim harness: seed ${SEED}, ${N} people, ${HOURS} h of play = ${DAYS} game days, ${WELLS} wells, ${GARDENS} gardens${DROUGHT?`, drought days ${DROUGHT[0]}-${DROUGHT[1]}`:''}; ${ms} ms`);
  console.log('  day here ration   foodD waterD short legit  mood health');
  const pad=(v,w)=>String(v).padStart(w);
  for(const s of series) if(s.day%50===0||s.day===series.length-1||(DROUGHT&&(s.day===DROUGHT[0]+10||s.day===DROUGHT[1])))
    console.log(`${pad(s.day,5)} ${pad(s.here,4)} ${s.ration.padEnd(8)} ${pad(s.foodDays,6)} ${pad(s.waterDays,6)} ${pad(s.shortfall,5)} ${pad(s.legit,5)} ${pad(s.mood,5)} ${pad(s.health,6)}`);
  console.log(`  deaths ${deaths.length} ${JSON.stringify(byCause)}  left ${left.length}  trades ${trades}  breaks ${events.filter(e=>e.kind==='break').length}`);
  if(opt.out) console.log(`  series → ${opt.out}`); }
module.exports=out;
