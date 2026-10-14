// ---------- people: survivors' bodies, needs, health, mood, skills and job choice (briefs/people.md, tools/sim/README.md) ----------
// Plain functions over plain survivor records, no rendering, no Math.random or Date: the same file runs in the pages and in Node
// (tools/people/test.js, tools/people/harness.js). step() updates the record in place; randomness comes from p.rng, seeded from p.seed.
const People=(()=>{
const VERSION=1;
// ---------- clocks: needs on the world clock (game minutes), age on the life clock (life days) ----------
const LIFE_RATIO=25, DAY=1440, LIFE_DAY=DAY*LIFE_RATIO, YEAR=365;   // one life day per 25 game days (foundation)
const lifeDayAt=minute=>minute/LIFE_DAY;

// ---------- rates (all tunable; per game hour unless said otherwise) ----------
// water, L/h (world clock): awake 0.5, up to double in full heat as campaign.waterRate; asleep much lower
const WATER_AWAKE=.5, WATER_SLEEP=.15, WATER_HEAT=1;
const DRINK_MAX=1.2;                                   // L/h a person drinks back on top of what they lose
const THIRST=[1.5,3,5,7.5], WATER_LETHAL=10;           // deficit L: thirsty, dehydrated, severe, critical; dehydration alone kills at 10 L
// food, kcal/h (world clock), adult; ~2,250 kcal on a day of 8 h sleep, 11 h rest, 5 h work
const KCAL={sleep:60,rest:85,work:170,travel:200};
const EAT_MAX=700;                                     // kcal/h a person eats back on top of what they burn (awake only)
const HUNGER=[1200,8000,30000,60000], FOOD_LETHAL=100000;   // deficit kcal: hungry, malnourished, severe, starving; ~45 days to die
// energy 0..1: drains awake, comes back asleep; ground sleep barely balances an ordinary day
const ENERGY={rest:.045,work:.065,travel:.075}, SLEEP_BED=.14, SLEEP_GROUND=.11;
// life stages on the life clock (years) and what they change
const STAGES=[['child',0],['teen',13],['adult',18],['elder',60]];
const STAGE={child:{water:.6,food:.6,work:.4,learn:1.5,reserve:.4},teen:{water:.9,food:.95,work:.8,learn:1.3,reserve:.8},
  adult:{water:1,food:1,work:1,learn:1,reserve:1},elder:{water:.9,food:.8,work:.7,learn:.7,reserve:.8}};
// conditions: weight against health (health = 1 − Σ weight × severity, death at 0) and how much each hurts
const COND={wound:{w:1,pain:1},infection:{w:1,pain:.5},illness:{w:.8,pain:.4},heatstroke:{w:1,pain:.6},
  dehydration:{w:1,pain:.2},malnutrition:{w:1,pain:.2},chronic:{w:.7,pain:.5}};
const WOUND_BLEED=.6, BLEED=.01, WOUND_HEAL=.003, WOUND_HEAL_TREATED=.008;   // wounds at 0.6+ worsen until treated; smaller ones heal
const INFECT=.003, INFECT_TREATED=.2;                  // infection onset per hour × wound severity (× 0.2 when treated)
const INFECTION_GROW=.001, INFECTION_GROW_WEAK=.004, INFECTION_CLEAR=.01;   // untreated (fed / not), treated
const ILLNESS=.0001, ILLNESS_ROUGH=3, ILLNESS_GROW=.006, ILLNESS_FALL=.008, ILLNESS_COURSE=[48,120];   // onset/h; course in hours to the peak
const HEATSTROKE=.01, HEATSTROKE_HEAT=.6, HEATSTROKE_GROW=.08, HEATSTROKE_FALL=.05;   // onset/h × heat × (1 + L short) when active above heat 0.6
const CHRONIC_ONSET=.002, CHRONIC_GROW=.004, CHRONIC_TREATED=.0015;   // per LIFE day: onset × (age − 60) / 10, growth
// mood: points, sum of modifiers; breaks below the thresholds
const MOOD_MINOR=-25, MOOD_MAJOR=-50, BREAK_RATE=.03, BREAK_HOURS={minor:8,major:24}, LEAVE_CHANCE=.4, CATHARSIS=10;
const MOOD_THIRST=[-5,-12,-25,-40], MOOD_HUNGER=[-4,-10,-20,-30], MOOD_TIRED=[-6,-15], MOOD_PAIN=40, MOOD_PAIN_MAX=40;
const MOOD_WELL=6, MOOD_BED=3, MOOD_ROUGH=-5, MOOD_SLEEP_HOURS=18, MOOD_HEAT_WORK=-4;
// skills 0..5: practice raises them (gain per work hour / (1 + level)), disuse wears them down slowly
const SKILLS=['build','grow','cook','medic','craft','shoot'], SKILL_MAX=5, SKILL_GAIN=.0006, SKILL_DECAY=.000005;
// traits from the seed; pairs are exclusive
const TRAITS=['tough','frail','optimist','pessimist','hardy','glutton','ascetic','quick','slow','industrious','lazy','nervous','steady'];
const OPPOSITE={tough:'frail',frail:'tough',optimist:'pessimist',pessimist:'optimist',quick:'slow',slow:'quick',industrious:'lazy',lazy:'industrious',nervous:'steady',steady:'nervous',glutton:'ascetic',ascetic:'glutton'};
const ROLES=['leader','medic','guard','scavenger','cook','builder'];
const ROLE_KINDS={leader:['trade','lead'],medic:['nurse','medic'],guard:['guard'],scavenger:['scavenge','haul'],cook:['cook'],builder:['build','craft']};
// job choice weights
const W={urgency:1,skill:.6,priority:.8,role:.3,dist:.15,fatigue:.6,need:.8,heat:.5,trait:.15,self:2};
const SELF={drink:1,eat:1,sleep:1,rest:1,treat:1};
const LIGHT={cook:1,grow:1,haul:1,nurse:1,craft:1,rest:1};   // what children can do

// ---------- seeded random ----------
const hash=n=>{ let s=(n|0)+0x9E3779B9; s=Math.imul(s^s>>>16,0x85EBCA6B); s=Math.imul(s^s>>>13,0xC2B2AE35); return (s^s>>>16)>>>0; };
function rnd(p){ let s=p.rng=(p.rng+0x6D2B79F5)>>>0; s=Math.imul(s^s>>>15,s|1); s^=s+Math.imul(s^s>>>7,s|61); return ((s^s>>>14)>>>0)/4294967296; }
const clamp=(v,a=0,b=1)=>v<a?a:v>b?b:v;
const chance=(p,ratePerH,h)=>ratePerH>0&&rnd(p)<1-Math.exp(-ratePerH*h);

// ---------- names ----------
const FIRST={f:['Ana','Rosa','Maria','Lena','Joy','Carmen','Dana','Ivy','Nora','Luz','Tess','Mae','Elena','Rita','June','Sofia','Wren','Alma','Gloria','Kim'],
  m:['Luis','Ray','Tomas','Jesse','Hank','Cruz','Eli','Dale','Marco','Owen','Abel','Wade','Rafael','Cole','Ignacio','Sam','Earl','Diego','Troy','Joel']};
const LAST=['Ruiz','Begay','Holt','Vega','Tso','Pruitt','Ochoa','Kerr','Salas','Yazzie','Moreno','Dunn','Archuleta','Lowe','Ibarra','Carver','Nez','Quintero','Haskell','Reyes','Sandoval','Pike','Tsosie','Marsh'];

// ---------- creation ----------
let nextId=1;
const STAGE_MIX=[['adult',.7],['teen',.1],['elder',.12],['child',.08]];
const AGE_RANGE={child:[3,12],teen:[13,17],adult:[18,59],elder:[60,82]};
// create(seed, {id, minute, stage, sex, name, traits, skills}) -> survivor record (tools/sim/README.md)
function create(seed,opts={}){
  const p={id:opts.id||'s'+(nextId++),seed:seed>>>0,name:'',sex:'f',born:0,body:{water:0,food:0,energy:1},conditions:[],traits:[],
    skills:{},mood:[],rel:{},partner:null,role:null,at:'base',alive:true,rng:hash(seed)};
  const r=()=>rnd(p), pick=a=>a[Math.floor(r()*a.length)];
  p.sex=opts.sex||(r()<.5?'f':'m');
  let stage=opts.stage; if(!stage){ let x=r(); stage='adult'; for(const [s,f] of STAGE_MIX){ if(x<f){ stage=s; break; } x-=f; } }
  const [a0,a1]=AGE_RANGE[stage], years=a0+r()*(a1+1-a0);
  p.born=lifeDayAt(opts.minute||0)-years*YEAR;
  p.name=opts.name||`${pick(FIRST[p.sex])} ${pick(LAST)}`;
  if(opts.traits) p.traits=opts.traits.slice();
  else { const n=r()<.35?1:r()<.85?2:3; let g=0; while(p.traits.length<n&&g++<30){ const t=pick(TRAITS); if(!p.traits.includes(t)&&!p.traits.includes(OPPOSITE[t])) p.traits.push(t); } }
  const top=stage==='child'?1:stage==='teen'?2:stage==='elder'?4:3, spec=pick(SKILLS);
  for(const s of SKILLS) p.skills[s]=Math.round(r()*top*(stage==='child'?.6:.7)*10)/10;
  if(stage!=='child') p.skills[spec]=Math.min(SKILL_MAX,p.skills[spec]+1+Math.round(r()*2));
  if(opts.skills) Object.assign(p.skills,opts.skills);
  return p; }

// ---------- age on the life clock ----------
const ageOf=(p,minute)=>(lifeDayAt(minute)-p.born)/YEAR;   // years
function stageOf(p,minute){ const a=ageOf(p,minute); let s='child'; for(const [k,y] of STAGES) if(a>=y) s=k; return s; }
const has=(p,t)=>p.traits.indexOf(t)>=0;

// ---------- needs ----------
function waterRate(p,act,heat,st=STAGE.adult){ return (act==='sleep'?WATER_SLEEP:WATER_AWAKE)*(1+WATER_HEAT*heat)*st.water*(has(p,'hardy')?.85:1); }   // L/h
function kcalRate(p,act,st=STAGE.adult){ return (KCAL[act]||KCAL.rest)*st.food*(has(p,'glutton')?1.15:1); }   // kcal/h
const stage4=(v,th)=>v>=th[3]?4:v>=th[2]?3:v>=th[1]?2:v>=th[0]?1:0;
const thirstStage=p=>stage4(p.body.water,THIRST);   // 0 fine … 4 critical
const hungerStage=p=>stage4(p.body.food,HUNGER);
// what this person wants over dt minutes: what they lose plus some of the deficit back. Nothing while asleep.
function demand(p,dt,env={}){ if(!p.alive||env.activity==='sleep') return {water:0,food:0};
  const h=dt/60, st=STAGE[stageOf(p,env.minute||0)], act=env.activity||'rest', lw=waterRate(p,act,env.heat||0,st)*h, lf=kcalRate(p,act,st)*h;
  return {water:Math.min(p.body.water,DRINK_MAX*h)+lw, food:Math.min(p.body.food,EAT_MAX*h)+lf}; }

// ---------- conditions ----------
function condOf(p,kind){ for(const c of p.conditions) if(c.kind===kind) return c; return null; }
function addCondition(p,kind,severity,minute,extra){ const c=Object.assign({kind,severity:clamp(severity),since:minute||0,treated:0},extra||{}); p.conditions.push(c); return c; }
// a wound (combat, accident): severity 0..1
const injure=(p,severity,minute)=>addCondition(p,'wound',severity,minute);
// treat the worst untreated condition of a kind (or any kind) with quality 0..1 (a med kit and a medic's skill). Returns it or null.
function treat(p,kind,quality=1){ let best=null; for(const c of p.conditions) if((!kind||c.kind===kind)&&c.treated<quality&&c.kind!=='dehydration'&&c.kind!=='malnutrition'&&(!best||c.severity>best.severity)) best=c;
  if(best) best.treated=clamp(quality); return best; }
function healthOf(p){ let s=0; for(const c of p.conditions) s+=(COND[c.kind]?COND[c.kind].w:1)*c.severity; return clamp(1-s); }
function painOf(p){ let s=0; for(const c of p.conditions) s+=(COND[c.kind]?COND[c.kind].pain:0)*c.severity; return s*(has(p,'tough')?.7:1); }
function needCond(p,kind,sev,minute){ let c=condOf(p,kind); if(sev>0){ if(!c) c=addCondition(p,kind,sev,minute); else c.severity=clamp(sev); } else if(c) p.conditions.splice(p.conditions.indexOf(c),1); }

function stepConditions(p,h,env,st,ev){
  const b=p.body, m=env.minute||0, act=env.activity||'rest', heat=env.heat||0;
  const weak=b.food>HUNGER[1]||b.water>THIRST[1], tough=has(p,'tough')?.7:has(p,'frail')?1.4:1;
  needCond(p,'dehydration',(b.water-THIRST[0])/(WATER_LETHAL*st.reserve-THIRST[0]),m);
  needCond(p,'malnutrition',(b.food-HUNGER[0])/(FOOD_LETHAL*st.reserve-HUNGER[0]),m);
  let wounds=0;
  for(let i=p.conditions.length-1;i>=0;i--){ const c=p.conditions[i], tr=c.treated;
    switch(c.kind){
      case 'wound': wounds+=c.severity*(tr?INFECT_TREATED:1);
        if(c.severity>=WOUND_BLEED&&!tr) c.severity+=BLEED*h*tough;
        else c.severity-=(tr?WOUND_HEAL_TREATED:WOUND_HEAL)*h*(weak?.5:1)/tough; break;
      case 'infection': c.severity+=(tr?-INFECTION_CLEAR*tr:(weak?INFECTION_GROW_WEAK:INFECTION_GROW)*tough)*h; break;
      case 'illness': { const rising=m<c.peak&&!(tr&&c.severity>.3);
        c.severity+=(rising?ILLNESS_GROW*(tr?.5:1)*tough*(weak?1.5:1):-ILLNESS_FALL*(tr?1.5:1)*(weak?.5:1))*h; break; }
      case 'heatstroke': { const hot=heat>=HEATSTROKE_HEAT&&(act==='work'||act==='travel');
        c.severity+=(hot?HEATSTROKE_GROW*heat:-HEATSTROKE_FALL*(tr?2:1)*(b.water>THIRST[1]?.4:1))*h; break; }
      case 'chronic': c.severity+=(tr?CHRONIC_TREATED:CHRONIC_GROW)*h/24/LIFE_RATIO*tough; break;   // per life day
    }
    if(c.severity<=0&&c.kind!=='dehydration'&&c.kind!=='malnutrition') p.conditions.splice(i,1); else if(c.severity>1) c.severity=1; }
  // onsets
  if(wounds>0&&!condOf(p,'infection')&&chance(p,INFECT*wounds*tough,h)){ addCondition(p,'infection',.1,m); ev.push({kind:'onset',id:p.id,cond:'infection',minute:m}); }
  if(!condOf(p,'illness')){ const rate=ILLNESS*tough*(p.slept==='ground'?ILLNESS_ROUGH:1)*(1+2*(condOf(p,'malnutrition')?.severity||0))*(weak?2:1);
    if(chance(p,rate,h)){ const [a,z]=ILLNESS_COURSE; addCondition(p,'illness',.1,m,{peak:m+(a+rnd(p)*(z-a))*60}); ev.push({kind:'onset',id:p.id,cond:'illness',minute:m}); } }
  if(heat>=HEATSTROKE_HEAT&&(act==='work'||act==='travel')&&!condOf(p,'heatstroke')&&chance(p,HEATSTROKE*heat*(1+b.water)*(has(p,'hardy')?.5:1),h)){
    addCondition(p,'heatstroke',.2,m); ev.push({kind:'onset',id:p.id,cond:'heatstroke',minute:m}); }
  const age=ageOf(p,m);
  if(age>60&&!condOf(p,'chronic')&&chance(p,CHRONIC_ONSET*(age-60)/10,h/24/LIFE_RATIO)){ addCondition(p,'chronic',.05,m); ev.push({kind:'onset',id:p.id,cond:'chronic',minute:m}); }
}

// ---------- mood ----------
const NEED_MOODS={thirst:1,hunger:1,tired:1,pain:1,'well-kept':1,'heat-work':1};
// add or replace a modifier; until = world minute it ends, null = while the cause lasts (the caller removes it)
function addMood(p,key,value,until=null){ removeMood(p,key); p.mood.push({key,value,until}); return p; }
function removeMood(p,key){ for(let i=p.mood.length-1;i>=0;i--) if(p.mood[i].key===key) p.mood.splice(i,1); return p; }
const moodBase=p=>(has(p,'optimist')?8:0)-(has(p,'pessimist')?8:0);
function moodOf(p){ let s=moodBase(p); for(const x of p.mood) s+=x.value; return s; }
const thresholds=p=>{ const d=has(p,'nervous')?8:has(p,'steady')?-8:0; return {minor:MOOD_MINOR+d,major:MOOD_MAJOR+d}; };
function needMoods(p,env){ const b=p.body, m=env.minute||0, keep=[];
  for(const x of p.mood) if(!NEED_MOODS[x.key]&&(x.until==null||x.until>m)) keep.push(x);
  p.mood=keep; const sc=has(p,'ascetic')?.5:has(p,'glutton')?1.3:1;
  const ts=thirstStage(p), hs=hungerStage(p), pain=painOf(p);
  if(ts) keep.push({key:'thirst',value:MOOD_THIRST[ts-1]*(has(p,'ascetic')?.5:1),until:null});
  if(hs) keep.push({key:'hunger',value:Math.round(MOOD_HUNGER[hs-1]*sc),until:null});
  if(b.energy<.3&&env.activity!=='sleep') keep.push({key:'tired',value:b.energy<.1?MOOD_TIRED[1]:MOOD_TIRED[0],until:null});
  if(pain>.02) keep.push({key:'pain',value:-Math.min(MOOD_PAIN_MAX,Math.round(MOOD_PAIN*pain)),until:null});
  if(!ts&&!hs&&b.energy>.4&&pain<.1) keep.push({key:'well-kept',value:MOOD_WELL,until:null});
  if(env.activity==='work'&&(env.heat||0)>.5) keep.push({key:'heat-work',value:MOOD_HEAT_WORK,until:null}); }
function stepBreaks(p,h,env,ev){ const m=(env.minute||0), mood=moodOf(p), th=thresholds(p);
  if(p.brk&&p.brk.until<=m) p.brk=null;
  if(p.brk||mood>=th.minor) return;
  const major=mood<th.major, lim=major?th.major:th.minor;
  if(!chance(p,BREAK_RATE*(1+(lim-mood)/10),h)) return;
  const kind=major?'major':'minor';
  if(major&&rnd(p)<LEAVE_CHANCE){ p.at='gone'; p.left={minute:m,mood:Math.round(mood)}; ev.push({kind:'left',id:p.id,minute:m,mood:Math.round(mood)}); return; }
  p.brk={kind,until:m+BREAK_HOURS[kind]*60}; addMood(p,'catharsis',CATHARSIS,p.brk.until+DAY);
  ev.push({kind:'break',id:p.id,level:kind,minute:m,mood:Math.round(mood)}); }

// ---------- skills ----------
function stepSkills(p,h,env,st){ const prac=env.activity==='work'?env.skill:null, learn=(has(p,'quick')?1.5:has(p,'slow')?.7:1)*st.learn;
  for(const s of SKILLS){ const v=p.skills[s]||0;
    if(s===prac) p.skills[s]=Math.min(SKILL_MAX,v+SKILL_GAIN*learn*h/(1+v));
    else if(v>0) p.skills[s]=v-SKILL_DECAY*v*h; } }

// ---------- the step ----------
// step(p, dt, env, got): settle dt game minutes (≤ 60 for accuracy). env = {minute, heat 0..1, activity:'rest'|'work'|'sleep'|'travel', bed, skill?}
// got = {water:L, food:kcal} handed out this step. Returns events: onset, break, left, death.
function step(p,dt,env={},got){ const ev=[]; if(!p.alive||p.at==='gone') return ev;
  const h=dt/60, act=env.activity||'rest', heat=env.heat||0, st=STAGE[stageOf(p,env.minute||0)], b=p.body;
  b.water+=waterRate(p,act,heat,st)*h-(got&&got.water||0); if(b.water<0) b.water=0;
  b.food+=kcalRate(p,act,st)*h-(got&&got.food||0); if(b.food<0) b.food=0;
  if(act==='sleep'){ b.energy=Math.min(1,b.energy+(env.bed?SLEEP_BED:SLEEP_GROUND)*h*(1-.5*painOf(p))); p.slept=env.bed?'bed':'ground'; p.asleep=true; }
  else { b.energy=Math.max(0,b.energy-(ENERGY[act]||ENERGY.rest)*h);
    if(p.asleep){ p.asleep=false; const end=(env.minute||0)+MOOD_SLEEP_HOURS*60;
      if(p.slept==='bed'){ removeMood(p,'slept-rough'); addMood(p,'slept-in-bed',MOOD_BED,end); } else { removeMood(p,'slept-in-bed'); addMood(p,'slept-rough',MOOD_ROUGH,end); } } }
  stepConditions(p,h,env,st,ev);
  stepSkills(p,h,env,st);
  needMoods(p,env);
  const hp=healthOf(p); p.health=hp;
  if(hp<=0){ let worst=null,ws=-1; for(const c of p.conditions){ const v=(COND[c.kind]?COND[c.kind].w:1)*c.severity; if(v>ws){ ws=v; worst=c.kind; } }
    p.alive=false; p.died={minute:(env.minute||0)+dt,cause:worst}; ev.push({kind:'death',id:p.id,minute:p.died.minute,cause:worst}); return ev; }
  stepBreaks(p,h,env,ev);
  return ev; }

// ---------- roles and job choice ----------
function setRole(p,role){ if(role!==null&&!ROLES.includes(role)) throw new Error('unknown role '+role); p.role=role; return p; }
// how much a person would work at full stretch now: stage, health, energy
function capacity(p,minute){ return STAGE[stageOf(p,minute)].work*healthOf(p)*(.4+.6*p.body.energy); }
// utility of a task for this person. task = {id, kind, skill, where:{x,z}|null, hours, urgency, heavy?, outdoor?}
// ctx = {minute, heat, from:{x,z}, priorities:{kind:0..1}}. -Infinity = can't or won't.
function score(p,task,ctx={}){ const m=ctx.minute||0, b=p.body;
  if(!p.alive||p.at==='gone') return -Infinity;
  if(SELF[task.kind]){ const need=task.kind==='drink'?b.water/THIRST[1]:task.kind==='eat'?b.food/HUNGER[1]:task.kind==='sleep'?1-b.energy:
      task.kind==='treat'?1-healthOf(p):.2+.8*(1-b.energy)*.5;
    return W.self*Math.min(1.5,need); }
  if(p.brk&&p.brk.until>m) return -Infinity;
  const stage=stageOf(p,m); if(stage==='child'&&!LIGHT[task.kind]) return -Infinity;
  const skill=task.skill?(p.skills[task.skill]||0)/SKILL_MAX:0, pr=ctx.priorities&&ctx.priorities[task.kind]!=null?ctx.priorities[task.kind]:.5;
  const role=p.role&&ROLE_KINDS[p.role]&&ROLE_KINDS[p.role].includes(task.kind)?W.role:0;
  const dist=task.where&&ctx.from?Math.hypot(task.where.x-ctx.from.x,task.where.z-ctx.from.z)/1000*W.dist:0;
  const need=Math.max(clamp(b.water/THIRST[2]),clamp(b.food/HUNGER[2]));
  const heat=task.outdoor?(ctx.heat||0)*W.heat*(has(p,'hardy')?.5:1):0;
  const tr=(has(p,'industrious')?W.trait:0)-(has(p,'lazy')?W.trait:0);
  return W.urgency*(task.urgency||0)+W.skill*skill+W.priority*pr+role+tr-dist-heat-W.fatigue*(1-b.energy)-W.need*need-(1-capacity(p,m))*(task.heavy?1:.4); }

// the stage of each need as a word, for pages and the harness
const THIRST_WORDS=['fine','thirsty','dehydrated','severe','critical'], HUNGER_WORDS=['fine','hungry','malnourished','severe','starving'];
function needs(p){ return {water:THIRST_WORDS[thirstStage(p)],food:HUNGER_WORDS[hungerStage(p)],energy:p.body.energy,health:healthOf(p),mood:moodOf(p)}; }

const RATES={WATER_AWAKE,WATER_SLEEP,WATER_HEAT,DRINK_MAX,THIRST,WATER_LETHAL,KCAL,EAT_MAX,HUNGER,FOOD_LETHAL,ENERGY,SLEEP_BED,SLEEP_GROUND,
  WOUND_BLEED,BLEED,WOUND_HEAL,WOUND_HEAL_TREATED,INFECT,INFECTION_GROW,INFECTION_GROW_WEAK,INFECTION_CLEAR,ILLNESS,ILLNESS_ROUGH,HEATSTROKE,HEATSTROKE_HEAT,
  CHRONIC_ONSET,CHRONIC_GROW,MOOD_MINOR,MOOD_MAJOR,BREAK_RATE,LEAVE_CHANCE,SKILL_GAIN,SKILL_DECAY};
return {VERSION,LIFE_RATIO,LIFE_DAY,YEAR,STAGES,STAGE,COND,SKILLS,TRAITS,ROLES,RATES,
  create,demand,step,addMood,removeMood,setRole,score,capacity,ageOf,stageOf,lifeDayAt,
  waterRate,kcalRate,thirstStage,hungerStage,healthOf,painOf,moodOf,thresholds,needs,addCondition,injure,treat,condOf,rnd};
})();
if(typeof module!=='undefined') module.exports=People;
