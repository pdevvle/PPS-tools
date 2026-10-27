// Rules check for people.js, no browser: node tools/people/test.js
const assert=require('assert');
const P=require('./people.js');
let n=0; const t=(name,fn)=>{ fn(); n++; console.log('ok',name); };
const R=P.RATES, H=60;
const adult=(seed=1,o={})=>P.create(seed,Object.assign({stage:'adult',traits:[]},o));
const env=(o={})=>Object.assign({minute:6*60,heat:0,activity:'rest',bed:true},o);
// feed exactly what is asked, for k hours
const run=(p,k,e,give=true)=>{ const ev=[]; for(let i=0;i<k;i++){ const en=env(Object.assign({},e,{minute:(e&&e.minute||0)+i*H})); ev.push(...P.step(p,H,en,give?P.demand(p,H,en):null)); } return ev; };

t('create makes a full record in the shared shape, repeatable from the seed',()=>{
  const a=P.create(42,{id:'s1'}), b=P.create(42,{id:'s1'});
  assert.deepStrictEqual(a,b,'same seed, same person');
  for(const k of ['id','seed','name','sex','born','body','conditions','traits','skills','mood','rel','partner','role','at','alive']) assert(k in a,k);
  assert.deepStrictEqual(a.body,{water:0,food:0,energy:1}); assert.equal(a.at,'base'); assert.equal(a.partner,null);
  for(const s of P.SKILLS) assert(a.skills[s]>=0&&a.skills[s]<=5,s);
  assert.notDeepStrictEqual(P.create(43,{id:'s1'}).traits.concat(P.create(43,{id:'s1'}).name),[]);
  for(let i=0;i<50;i++){ const p=P.create(i); for(const tr of p.traits) assert(!p.traits.includes({tough:'frail',optimist:'pessimist'}[tr]),'no opposite traits'); } });

t('age and stage run on the life clock (one life day per 25 game days)',()=>{
  assert.equal(P.LIFE_RATIO,25); assert.equal(P.lifeDayAt(25*1440),1);
  for(const st of ['child','teen','adult','elder']){ const p=P.create(7,{stage:st,minute:450}); assert.equal(P.stageOf(p,450),st); }
  const p=P.create(1,{stage:'teen'}); p.born=-(18*365-10);   // ten life days short of 18
  assert.equal(P.stageOf(p,0),'teen'); assert.equal(P.stageOf(p,9*25*1440),'teen'); assert.equal(P.stageOf(p,11*25*1440),'adult');
  assert(Math.abs(P.ageOf(p,365*25*1440)-P.ageOf(p,0)-1)<1e-9,'a year of life is 365 × 25 game days'); });

t('water: 0.5 L/h awake, doubled in full heat, lower asleep',()=>{
  const p=adult();
  assert.equal(P.waterRate(p,'work',0),.5); assert.equal(P.waterRate(p,'rest',1),1); assert(P.waterRate(p,'sleep',0)<.5);
  P.step(p,H,env({heat:1})); assert(Math.abs(p.body.water-1)<1e-9,'an hour unfed in full heat is a litre short');
  const d=P.demand(p,H,env({heat:0})); assert(d.water>.5&&d.water<=.5+R.DRINK_MAX,'drinks back some of the deficit');
  assert.deepStrictEqual(P.demand(p,H,env({activity:'sleep'})),{water:0,food:0},'nobody eats asleep'); });

t('food drains by activity; children and elders need less',()=>{
  const p=adult(); assert(P.kcalRate(p,'work')>P.kcalRate(p,'rest')&&P.kcalRate(p,'rest')>P.kcalRate(p,'sleep'));
  const day=8*P.kcalRate(p,'sleep')+11*P.kcalRate(p,'rest')+5*P.kcalRate(p,'work'); assert(day>2000&&day<2600,'about one ration and a bit a day');
  assert(P.kcalRate(p,'rest',P.STAGE.child)<P.kcalRate(p,'rest',P.STAGE.elder)); });

t('a fed person stays fed and well; a thirsty one goes through the stages and dies in about a day in the heat',()=>{
  const fed=adult(); run(fed,72,{heat:.5}); assert.equal(P.thirstStage(fed),0); assert.equal(P.hungerStage(fed),0); assert(fed.alive); assert.equal(P.healthOf(fed),1);
  const dry=adult(2), stages=new Set(); let h=0;
  while(dry.alive&&h<200){ P.step(dry,H,env({heat:.5,minute:h*H}),{water:0,food:5000}); stages.add(P.thirstStage(dry)); h++; }
  assert(!dry.alive&&dry.died.cause==='dehydration'); assert.deepStrictEqual([...stages].sort(),[0,1,2,3,4].filter(s=>stages.has(s)));
  assert(stages.has(2)&&stages.has(4)); assert(h>10&&h<30,'dead in '+h+' h'); });

t('no food: malnutrition stages over weeks, then death',()=>{
  const p=adult(3); let h=0; const seen=new Set();
  while(p.alive&&h<24*80){ const e=env({minute:h*H}); P.step(p,H,e,{water:P.demand(p,H,e).water,food:0}); seen.add(P.hungerStage(p)); h++; }
  assert(!p.alive&&p.died.cause==='malnutrition'); assert(seen.has(1)&&seen.has(2)&&seen.has(3),'hungry, malnourished, severe');
  assert(h/24>20&&h/24<60,'dies in '+(h/24).toFixed(1)+' days'); });

t('sleep restores energy; a bed better than the ground, and the ground hurts mood',()=>{
  const a=adult(4), b=adult(4); a.body.energy=b.body.energy=.2;
  run(a,5,{activity:'sleep',bed:true}); run(b,5,{activity:'sleep',bed:false});
  assert(a.body.energy>b.body.energy&&b.body.energy>.2);
  run(a,1,{minute:5*H}); run(b,1,{minute:5*H});
  assert(a.mood.some(m=>m.key==='slept-in-bed')); assert(b.mood.some(m=>m.key==='slept-rough')); assert(P.moodOf(a)>P.moodOf(b));
  const c=adult(5); run(c,16,{activity:'work'}); assert(c.body.energy<.2,'a long day wears you out'); });

t('wounds: small ones heal, big ones bleed until treated, treatment heals faster',()=>{
  const a=adult(6); P.injure(a,.3,0); run(a,200); assert(!P.condOf(a,'wound'),'a light wound heals in days');
  const b=adult(7); const w=P.injure(b,.7,0); run(b,5); assert(w.severity>.7,'a deep wound bleeds');
  P.treat(b,'wound',1); const s=w.severity; run(b,10,{minute:5*H}); assert(w.severity<s,'treated wounds heal');
  const c=adult(8); P.injure(c,.9,0); let k=0; while(c.alive&&k++<100) run(c,1,{minute:k*H}); assert(!c.alive,'an untreated deep wound kills'); });

t('infection and illness progress and respond to treatment',()=>{
  const a=adult(9); const inf=P.addCondition(a,'infection',.3,0);
  a.body.food=20000; for(let h=0;h<48;h++){ const e=env({minute:h*H}); P.step(a,H,e,{water:P.demand(a,H,e).water,food:0}); } assert(a.alive); assert(inf.severity>.3,'untreated infection grows in a weak body');
  P.treat(a,'infection',1); const s=inf.severity; a.body.food=0; a.body.water=0; run(a,24,{minute:48*H}); assert(inf.severity<s);
  const b=adult(10), ill=P.addCondition(b,'illness',.1,0,{peak:48*60}); run(b,40); const top=ill.severity; assert(top>.1);
  run(b,300,{minute:60*H}); assert(!P.condOf(b,'illness'),'illness runs its course'); });

t('heatstroke comes from work in the heat, worse when dry, and passes with rest',()=>{
  let hits=0; for(let s=0;s<40;s++){ const p=adult(100+s); p.body.water=4; for(let h=0;h<6;h++) P.step(p,H,env({activity:'work',heat:1,minute:h*H}),{water:1,food:200}); if(P.condOf(p,'heatstroke')) hits++; }
  let cool=0; for(let s=0;s<40;s++){ const p=adult(100+s); run(p,6,{activity:'work',heat:0}); if(P.condOf(p,'heatstroke')) cool++; }
  assert(hits>5,'hits '+hits); assert.equal(cool,0);
  const p=adult(11), c=P.addCondition(p,'heatstroke',.4,0); run(p,12,{heat:.2}); assert(!P.condOf(p,'heatstroke')); });

t('elders develop chronic conditions slowly on the life clock',()=>{
  let got=0, sev=0; const N=20;   // 100 life days in hourly steps, fed and watered
  for(let s=0;s<N;s++){ const p=P.create(200+s,{stage:'elder',traits:[]}); p.born=-80*365; let c=null;
    for(let h=0;h<100*25*24&&!c;h++){ const e=env({minute:h*H}); P.step(p,H,e,P.demand(p,H,e)); c=P.condOf(p,'chronic'); }
    if(c){ got++; for(let h=0;h<10*25*24;h++){ const e=env({minute:h*H}); P.step(p,H,e,P.demand(p,H,e)); } sev+=c.severity; } }
  assert(got>=2&&got<N,'chronic in '+got+'/'+N+' over 100 life days'); assert(sev/got>.03,'and it grows'); });

t('health is 1 minus the weighted conditions, and death comes at 0 with a cause',()=>{
  const p=adult(12); P.addCondition(p,'wound',.4,0,{treated:1}); P.addCondition(p,'illness',.5,0,{peak:0});
  assert(Math.abs(P.healthOf(p)-(1-.4-.8*.5))<1e-9);
  P.addCondition(p,'infection',.5,0); const ev=P.step(p,H,env(),{water:1,food:200});
  assert(!p.alive&&ev.some(e=>e.kind==='death'&&e.cause)); assert.deepStrictEqual(P.step(p,H,env()),[],'the dead do nothing'); });

t('mood is a sum of modifiers that expire; addMood replaces by key',()=>{
  const p=adult(13); P.addMood(p,'ate-cooked',5,600); P.addMood(p,'ate-cooked',7,600); assert.equal(p.mood.filter(m=>m.key==='ate-cooked').length,1);
  run(p,1,{minute:0}); const m0=P.moodOf(p); assert(m0>=7);
  run(p,1,{minute:700}); assert(!p.mood.some(m=>m.key==='ate-cooked'),'expired'); assert.equal(P.moodOf(p),m0-7);
  P.addMood(p,'council-vote',-3,null); run(p,1,{minute:800}); assert(p.mood.some(m=>m.key==='council-vote'),'while the cause lasts');
  P.removeMood(p,'council-vote'); assert(!p.mood.some(m=>m.key==='council-vote'));
  const opt=adult(14,{traits:['optimist']}), pes=adult(14,{traits:['pessimist']}); run(opt,1); run(pes,1); assert(P.moodOf(opt)>P.moodOf(pes)); });

t('low mood leads to minor and major breaks, and some leave',()=>{
  let minor=0, major=0, left=0;
  for(let s=0;s<60;s++){ const p=adult(300+s); P.addMood(p,'grief',s%2?-35:-70,1e9);
    for(let h=0;h<48;h++) for(const e of P.step(p,H,env({minute:h*H}),P.demand(p,H,env({minute:h*H})))){ if(e.kind==='break') e.level==='minor'?minor++:major++; if(e.kind==='left') left++; } }
  assert(minor>0&&major>0&&left>0,`${minor} ${major} ${left}`);
  const q=adult(400); P.addMood(q,'grief',-70,1e9); let g=0; while(q.at==='base'&&!q.brk&&g++<500) P.step(q,H,env({minute:g*H}),P.demand(q,H,env()));
  if(q.brk) assert.equal(P.score(q,{kind:'build',skill:'build',urgency:1},{minute:g*H}),-Infinity,'no work during a break');
  else assert.equal(q.at,'gone'); });

t('skills grow with practice, more slowly the higher they are, and decay slowly without it',()=>{
  const p=adult(15,{skills:{build:0,cook:4,shoot:3}}); run(p,500,{activity:'work',skill:'build'});
  assert(p.skills.build>.2&&p.skills.build<.4,'build '+p.skills.build); assert(p.skills.shoot<3&&p.skills.shoot>2.97,'shoot '+p.skills.shoot);
  const q=adult(15,{skills:{build:4}}); run(q,500,{activity:'work',skill:'build'}); assert(q.skills.build-4<p.skills.build/4); });

t('job choice prefers skill, urgency, role and priority; tired, hungry and children score lower',()=>{
  const p=adult(16,{skills:{cook:4,build:0}}), cook={kind:'cook',skill:'cook',urgency:.5}, build={kind:'build',skill:'build',urgency:.5,heavy:true,outdoor:true};
  assert(P.score(p,cook)>P.score(p,build));
  assert(P.score(p,build,{priorities:{build:1}})>P.score(p,build,{priorities:{build:0}}));
  const s0=P.score(p,build); P.setRole(p,'builder'); assert(P.score(p,build)>s0); assert.throws(()=>P.setRole(p,'king'));
  assert(P.score(p,build,{heat:1})<P.score(p,build,{heat:0}));
  assert(P.score(p,{kind:'guard',where:{x:5000,z:0}},{from:{x:0,z:0}})<P.score(p,{kind:'guard',where:{x:0,z:0}},{from:{x:0,z:0}}));
  const t1=P.score(p,cook); p.body.energy=.1; assert(P.score(p,cook)<t1); p.body.food=20000; const t2=P.score(p,cook);
  assert(P.score(p,{kind:'eat'})>P.score(p,{kind:'eat'})-1&&P.score(p,{kind:'eat'})>t2,'a starving person wants food more than work');
  const kid=P.create(17,{stage:'child'}); assert.equal(P.score(kid,build),-Infinity); assert(P.score(kid,cook)>-Infinity); });

t('a run is repeatable from the seeds',()=>{
  const go=()=>{ const ps=[1,2,3].map(s=>P.create(s,{id:'s'+s})); for(let h=0;h<500;h++) for(const p of ps){ const e=env({minute:h*H,heat:h%24>11&&h%24<20?.8:0,activity:h%24<6?'sleep':'work',skill:'grow'}); P.step(p,H,e,{water:P.demand(p,H,e).water*.8,food:1500}); } return JSON.stringify(ps); };
  assert.equal(go(),go()); });

console.log(`${n} checks passed`);
