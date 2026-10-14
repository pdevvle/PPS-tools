// Headless people harness: node tools/people/harness.js [seed] [hours] [--supply ok|short|hungry|thin|none] [--water L/day] [--food rations/day]
//   [--med kits/day] [--beds n] [--people n] [--out series.json] [--quiet]
// Simulates a group at the base for [hours] of real play at 1× (25 game days per hour, one life day per hour) in 60-minute steps,
// with a stub supply (a pool with a daily income, tools/sim/README.md) and a simple day: sleep 22–06, work while it's cool, rest in the heat.
const fs=require('fs'), path=require('path');
const P=require('./people.js'), C=require('../region/campaign.js');

const argv=process.argv.slice(2), pos=[], opt={};
for(let i=0;i<argv.length;i++){ const a=argv[i]; if(a.startsWith('--')){ const k=a.slice(2); if(k==='quiet') opt.quiet=true; else opt[k]=argv[++i]; } else pos.push(a); }
const SEED=+(pos[0]||1), HOURS=+(pos[1]||100), N=+(opt.people||20), BEDS=opt.beds!=null?+opt.beds:N;
const PRESET={ok:[1,1],short:[.5,.5],hungry:[1,0],thin:[1,.6],none:[0,0]}[opt.supply||'ok']; if(!PRESET) throw new Error('--supply ok|short|hungry|thin|none');
const SUPPLY=Math.min(...PRESET);
const WATER_DAY=opt.water!=null?+opt.water:14*N*PRESET[0];           // L per day into the pool (adult ≈ 13 L/day in early summer)
const FOOD_DAY=(opt.food!=null?+opt.food:1.25*N*PRESET[1])*2000;     // rations per day → kcal (1 ration = 2,000 kcal)
const MED_DAY=opt.med!=null?+opt.med:.3;                          // med kits per day
const STEP=60, DAYS=HOURS*P.LIFE_RATIO, START=7*60+30;            // a campaign starts at 07:30 on day 0

// harness randomness (accidents, news), separate from the survivors' own
const H={rng:(SEED*2654435761)>>>0}, rand=()=>P.rnd(H);
const people=[]; for(let i=0;i<N;i++) people.push(P.create(SEED*1000+i,{id:'s'+(i+1),minute:START}));
people.forEach((p,i)=>{ if(i===0) P.setRole(p,'medic'); else if(i<3) P.setRole(p,'cook'); else if(i<6) P.setRole(p,'builder'); });
const pool={water:WATER_DAY*3||14*N*3*(SUPPLY||.25),food:FOOD_DAY*3||2500*N*3*(SUPPLY||.25),med:4};   // a few days in hand
const TASKS=[{id:'cook',kind:'cook',skill:'cook',urgency:.5},{id:'grow',kind:'grow',skill:'grow',urgency:.4,outdoor:true},
  {id:'build',kind:'build',skill:'build',urgency:.4,heavy:true,outdoor:true},{id:'craft',kind:'craft',skill:'craft',urgency:.3},
  {id:'guard',kind:'guard',skill:'shoot',urgency:.4,outdoor:true},{id:'nurse',kind:'nurse',skill:'medic',urgency:.2},{id:'haul',kind:'haul',urgency:.3,heavy:true}];
const heatAt=m=>C.heatOf(C.sunAt(m).tempC);
const activityAt=(m,heat)=>{ const hr=Math.floor((m%1440)/60); return hr>=22||hr<6?'sleep':heat<.3?'work':'rest'; };

const series=[], events=[], t0=Date.now();
let acc=null; const resetAcc=()=>{ acc={n:0,water:0,food:0,energy:0,mood:0,health:0}; }; resetAcc();
const job={};
for(let m=START;m<START+DAYS*1440;m+=STEP){
  const heat=heatAt(m), act=activityAt(m,heat), here=people.filter(p=>p.alive&&p.at==='base');
  // beds go to whoever is most tired
  const inBed=new Set(here.slice().sort((a,b)=>a.body.energy-b.body.energy).slice(0,BEDS).map(p=>p.id));
  const envs={}, dem={}; let wW=0,wF=0;
  for(const p of here){ let a=act; if(a==='work'&&(P.stageOf(p,m)==='child'||(p.brk&&p.brk.until>m))) a='rest';
    if(a==='work'&&(!job[p.id]||m%1440<STEP||job[p.id].until<=m)){   // choose a job at the start of each work spell
      let best=null,bs=-Infinity; for(const t of TASKS){ const s=P.score(p,t,{minute:m,heat}); if(s>bs){ bs=s; best=t; } }
      job[p.id]=best?{task:best,until:m+5*60}:null; if(!best) a='rest'; }
    envs[p.id]={minute:m,heat,activity:a,bed:inBed.has(p.id),skill:a==='work'&&job[p.id]?job[p.id].task.skill:null};
    const d=P.demand(p,STEP,envs[p.id]); dem[p.id]=d; wW+=d.water; wF+=d.food; }
  const fw=wW>0?Math.min(1,pool.water/wW):1, ff=wF>0?Math.min(1,pool.food/wF):1;
  for(const p of here){ const d=dem[p.id], got={water:d.water*fw,food:d.food*ff}; pool.water-=got.water; pool.food-=got.food;
    const env=envs[p.id];
    if(env.activity==='work'&&env.skill!=null&&rand()<.0004){ const c=P.injure(p,.1+.6*rand(),m); if(c.severity>.3&&pool.med>=1){ pool.med--; c.treated=.6; }   // first aid for the bad ones
      events.push({kind:'injury',id:p.id,minute:m,severity:+c.severity.toFixed(2)}); }
    for(const e of P.step(p,STEP,env,got)) events.push(e);
    acc.n++; acc.water+=p.body.water; acc.food+=p.body.food; acc.energy+=p.body.energy; acc.mood+=P.moodOf(p); acc.health+=p.health; }
  if(((m+STEP-6*60)%1440+1440)%1440<STEP){   // morning: income arrives, the medic does the rounds, news comes in
    pool.water+=WATER_DAY; pool.food+=FOOD_DAY; pool.med+=MED_DAY;
    const alive=people.filter(p=>p.alive&&p.at==='base'), medic=Math.max(0,...alive.map(p=>p.role==='medic'?p.skills.medic:0));
    for(const p of alive) for(const c of p.conditions) if(!c.treated&&c.severity>.15&&P.COND[c.kind]&&c.kind!=='dehydration'&&c.kind!=='malnutrition'&&pool.med>=1){ pool.med--; c.treated=.5+medic/10; }
    if(alive.length&&rand()<.15){ const p=alive[Math.floor(rand()*alive.length)], good=rand()<.5; P.addMood(p,good?'good-find':'grim-news',good?8:-12,m+STEP+3*1440); }
    const day=Math.floor((m+STEP-START)/1440)-1, k=acc.n||1;
    series.push({day,alive:people.filter(p=>p.alive).length,here:alive.length,water:+(acc.water/k).toFixed(2),food:Math.round(acc.food/k),
      energy:+(acc.energy/k).toFixed(3),mood:+(acc.mood/k).toFixed(1),health:+(acc.health/k).toFixed(3),pool:{water:Math.round(pool.water),food:+(pool.food/2000).toFixed(1),med:+pool.med.toFixed(1)}});
    resetAcc(); }
}
const ms=Date.now()-t0;

// ---------- summary ----------
const count=k=>events.filter(e=>e.kind===k).length, deaths=events.filter(e=>e.kind==='death'), left=events.filter(e=>e.kind==='left');
const byCause={}; for(const d of deaths) byCause[d.cause]=(byCause[d.cause]||0)+1;
const onsets={}; for(const e of events) if(e.kind==='onset') onsets[e.cond]=(onsets[e.cond]||0)+1;
const at=d=>series[Math.min(series.length-1,d)]||{};
const fmt=s=>s?`alive ${s.alive} here ${s.here}  water −${s.water} L  food −${s.food} kcal  energy ${s.energy}  mood ${s.mood}  health ${s.health}`:'';
const out={meta:{seed:SEED,hours:HOURS,days:DAYS,people:N,beds:BEDS,supply:opt.supply||'ok',waterPerDay:WATER_DAY,foodPerDay:FOOD_DAY/2000,medPerDay:MED_DAY,stepMinutes:STEP,ms,rates:P.RATES},
  series,events,deathsByCause:byCause,onsets,
  people:people.map(p=>({id:p.id,name:p.name,sex:p.sex,stage:P.stageOf(p,START),age:+P.ageOf(p,START).toFixed(1),traits:p.traits,role:p.role,alive:p.alive,at:p.at,died:p.died||null,left:p.left||null,
    skills:Object.fromEntries(Object.entries(p.skills).map(([k,v])=>[k,+v.toFixed(2)]))}))};
if(opt.out){ fs.mkdirSync(path.dirname(path.resolve(opt.out)),{recursive:true}); fs.writeFileSync(opt.out,JSON.stringify(out)); }
if(!opt.quiet){
  console.log(`people harness: seed ${SEED}, ${N} people, ${HOURS} h of play = ${DAYS} game days (${HOURS} life days), supply ${opt.supply||'ok'} (water ${WATER_DAY} L/day, food ${FOOD_DAY/2000} rations/day, med ${MED_DAY}/day), beds ${BEDS}; ${ms} ms`);
  for(const d of [0,1,2,3,5,7,14,30,100,500,1000,DAYS-1]) if(d<series.length) console.log(`  day ${String(d).padStart(4)}: ${fmt(at(d))}`);
  console.log(`  deaths ${deaths.length} ${JSON.stringify(byCause)}  left ${left.length}  breaks ${count('break')}  injuries ${count('injury')}  onsets ${JSON.stringify(onsets)}`);
  if(deaths.length) console.log(`  first death day ${((deaths[0].minute-START)/1440).toFixed(1)}`);
  const ages=people.filter(p=>p.alive).map(p=>Object.values(p.skills).reduce((a,b)=>Math.max(a,b),0)); if(ages.length) console.log(`  best skill per survivor (mean) ${(ages.reduce((a,b)=>a+b,0)/ages.length).toFixed(2)}`);
  if(opt.out) console.log(`  series → ${opt.out}`); }
module.exports=out;
