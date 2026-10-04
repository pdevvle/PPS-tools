// Rules check for settlement.js, no browser: node tools/settlement/test.js
const assert=require('assert');
const S=require('./settlement.js');
let n=0; const t=(name,fn)=>{ fn(); n++; console.log('ok',name); };
const near=(a,b,e=1e-6)=>Math.abs(a-b)<=e;
const DAY=S.DAY, ADULT=-30*365, CHILD=-8*365;
const person=(id,o={})=>Object.assign({id,seed:1,name:id,sex:'f',born:ADULT,body:{water:0,food:0,energy:1},conditions:[],traits:[],skills:{},mood:[],rel:{},partner:null,role:null,at:'base',alive:true},o);
// stands in for People.addMood / People.setRole: logs, and keeps one modifier per key on the record
const moodHook=(now=()=>0)=>{ const log=[]; return {log,addMood:(p,key,value,hours)=>{ log.push({id:p.id,key,value,hours}); p.mood=p.mood.filter(m=>m.key!==key).concat({key,value,until:now()+hours*60}); },setRole:(p,role)=>log.push({id:p.id,role})}; };

t('items stay inside the eight loot categories and every category has a default',()=>{
  for(const it of Object.values(S.ITEMS)){ assert(S.LOOT.includes(it.cat),it.id); assert(it.kg>0&&it.value>0,it.id); }
  for(const c of S.LOOT) assert.equal(S.ITEMS[S.DEFAULT_ITEM[c]].cat,c);
  assert.equal(S.ITEMS.ration.kcal,2000); assert.equal(S.ITEMS.ration.kg,1); });

t('squad loot by category lands as default items; item ids pass through',()=>{
  const st=S.newStores(); S.receive(st,{food:3,water:20,tools:2,goods:1},600); S.receive(st,{antibiotics:2},700);
  assert.equal(S.amount(st,'food'),6000); assert.equal(S.amount(st,'water'),20); assert.equal(S.count(st,'scrap'),2); assert.equal(S.count(st,'antibiotics'),2);
  assert.equal(st.lots.find(l=>l.item==='ration').at,600); });

t('perishables spoil, faster in heat and out of the right storage; tins keep',()=>{
  const mk=()=>{ const st=S.newStores(); S.add(st,'produce',10); S.add(st,'canned',10); S.add(st,'rifle',1); return st; };
  const cold=mk(), hot=mk(), nocellar=mk();
  S.spoil(cold,{dry:500,cool:100},3,0); S.spoil(hot,{dry:500,cool:100},3,1); S.spoil(nocellar,{dry:500,cool:0},3,0);
  const c=st=>st.lots.find(l=>l.item==='produce').cond;
  assert(near(c(cold),.7)); assert(c(hot)<c(cold)); assert(c(nocellar)<c(cold));
  assert(cold.lots.find(l=>l.item==='canned').cond>.99); assert.equal(cold.lots.find(l=>l.item==='rifle').cond,1);
  const lost=S.spoil(cold,{dry:500,cool:100},8,0); assert.equal(lost.produce,10); assert.equal(S.count(cold,'produce'),0); });

t('the most perishable lots take the storage first; the rest overflow',()=>{
  const st=S.newStores(); S.add(st,'tankwater',300); S.add(st,'produce',20); S.add(st,'meal',10);
  const {place,used}=S.placeLots(st,{dry:10,cool:8,tank:100});
  assert.equal(place.get(st.lots[2]),'cool','meals before produce'); assert.equal(place.get(st.lots[1]),'exposed');
  assert.equal(place.get(st.lots[0]),'exposed'); assert.equal(used.cool,5); });

t('full rationing gives what is asked and takes it out of the stores, most perishable first',()=>{
  const st=S.newStores(); S.add(st,'canned',20,0); S.add(st,'meal',2,100); S.add(st,'flour',5); S.add(st,'tankwater',50); S.add(st,'bottled',10);
  const got=S.ration(st,{a:{water:4,food:2000},b:{water:4,food:1000}},{ration:'full'},600);
  assert.equal(got.a.food,2000); assert.equal(got.b.water,4); assert.equal(S.count(st,'meal'),0,'meals eaten first');
  assert(near(S.count(st,'canned'),20-1600/400)); assert.equal(S.count(st,'flour'),5,'flour needs cooking');
  assert.equal(S.count(st,'tankwater'),42); assert.equal(S.count(st,'bottled'),10); assert(near(got.a.cooked,1400/3000,.01)); });

t('rationing levels cut what is handed out; children and the sick are exempt',()=>{
  const people=[person('kid',{born:CHILD}),person('sick',{conditions:[{kind:'fever',severity:.5,since:0}]}),person('guard',{role:'guard'}),person('cook',{role:'cook'})];
  const pr=S.priorities(people,0); assert.deepEqual(pr,{kid:0,sick:0,guard:1,cook:2});
  const st=S.newStores(); S.add(st,'ration',100); S.add(st,'tankwater',100); const dem={}; for(const p of people) dem[p.id]={water:5,food:2000};
  const red=S.ration(st,dem,{ration:'reduced',priority:pr}); assert.equal(red.kid.food,2000); assert.equal(red.cook.food,1500); assert.equal(red.cook.water,4.5);
  const sur=S.ration(st,dem,{ration:'survival',priority:pr}); assert.equal(sur.sick.food,2000); assert.equal(sur.guard.food,1000); assert.equal(sur.guard.water,3.75); });

t('in a shortfall the priority tiers are served first, the rest share what is left',()=>{
  const pr={kid:0,guard:1,a:2,b:2}, dem={kid:{water:5,food:1000},guard:{water:5,food:2000},a:{water:5,food:2000},b:{water:5,food:2000}};
  const st=S.newStores(); S.add(st,'ration',2); S.add(st,'tankwater',12);
  const got=S.ration(st,dem,{ration:'full',priority:pr});
  assert.equal(got.kid.food,1000); assert.equal(got.guard.food,2000); assert.equal(got.a.food,500); assert.equal(got.b.food,500);
  assert.equal(got.kid.water,5); assert.equal(got.guard.water,5); assert.equal(got.a.water,1); assert(S.amount(st,'water')<1e-6); });

t('production: tasks come from amenities and inputs, urgency from supply, and resolve when worked',()=>{
  const st=S.newState({heads:10,amen:{well:1,garden:2,kitchen:1,workshop:1}});
  S.add(st.stores,'tankwater',30); S.add(st.stores,'produce',10); S.add(st.stores,'firewood',20); S.add(st.stores,'scrap',2);
  const tasks=S.offer(st,DAY+600); const kinds=tasks.map(x=>x.recipe);
  assert(kinds.includes('water')&&kinds.includes('garden')&&kinds.includes('cook')); assert(!kinds.includes('tools'),'needs 3 scrap'); assert(!kinds.includes('medicine'),'no infirmary');
  for(const x of tasks) for(const k of ['id','kind','skill','where','hours','urgency']) assert(k in x,k);
  assert.equal(tasks[0].urgency,1); assert.equal(kinds.filter(k=>k==='garden').length,2);
  const w=tasks.find(x=>x.recipe==='water'); assert(S.work(st,w.id,person('a'),DAY+700).ok); assert.equal(S.count(st.stores,'tankwater'),90);
  assert.equal(S.work(st,w.id,person('a'),DAY+800).ok,false,'once per slot a day'); assert(!S.offer(st,DAY+900).some(x=>x.id===w.id));
  const g=tasks.find(x=>x.recipe==='garden'); const r=S.work(st,g.id,person('b',{skills:{grow:4}}),DAY+700); assert(r.ok); assert(near(r.made.produce,8*1.3));
  const c=tasks.find(x=>x.recipe==='cook'); const before=S.count(st.stores,'firewood');
  const cr=S.work(st,c.id,person('c',{skills:{cook:2}}),DAY+720); assert(cr.ok);
  assert.equal(before-S.count(st.stores,'firewood'),3,'burns the cheapest fuel'); assert(near(cr.made.meal,5600*.9/700,.01),'meals from up to 5,600 kcal of produce');
  assert(S.offer(st,2*DAY+600).some(x=>x.recipe==='water'),'new slots the next day'); });

t('the same item is worth more to a holder short of it',()=>{
  const rich={stores:S.newStores(),need:S.needOf(10)}, poor={stores:S.newStores(),need:S.needOf(10)};
  S.add(rich.stores,'tankwater',2000); S.add(poor.stores,'tankwater',300);
  const vr=S.valueOf(rich,'bottled',10), vp=S.valueOf(poor,'bottled',10);
  assert(vp>2*vr,`${vp} vs ${vr}`); assert(vp<=10*S.SCARCITY.max+1e-9);
  assert(S.valueOf(poor,'bottled',100)<10*S.valueOf(poor,'bottled',10),'each more unit is worth less');
  const none={stores:S.newStores(),need:{}}; assert(near(S.valueOf(none,'rifle',1),120*S.SCARCITY.min));
  assert(near(S.scarcity(14,14),1)); });

t('trader stock and schedule are seeded and repeatable',()=>{
  const a=S.makeTrader(42), b=S.makeTrader(42), c=S.makeTrader(43); S.restock(a,0); S.restock(b,0); S.restock(c,0);
  assert.deepEqual(a,b); assert.notDeepEqual(a.stores,c.stores); assert.equal(a.wants.length,2); assert(a.every>=10&&a.every<=20); });

t('a trader visit makes fair deals, writes the ledger and builds reputation',()=>{
  const st=S.newState({heads:12}); S.add(st.stores,'ration',400); S.add(st.stores,'tankwater',300); S.add(st.stores,'scrap',60); S.add(st.stores,'tradegoods',40); S.add(st.stores,'gasoline',100);
  const tr=S.makeTrader(7,{first:3*DAY}); tr.wants=['tools','goods']; for(const c of S.LOOT) tr.need[c]=S.PER_HEAD[c]*6*(tr.wants.includes(c)?2:.25);
  assert.deepEqual(S.traders(st,[tr],2*DAY),[],'not yet');
  const res=S.traders(st,[tr],3*DAY)[0]; assert(res,'visits'); assert(res.accepted.length>0,'trades');
  for(const e of st.ledger){ assert(e.ours.got>=e.ours.gave-1e-6,'fair to us'); assert(e.theirs.got>=e.theirs.gave,'worth it to them'); }
  assert.equal(st.rep[tr.id],S.REP.trade*res.accepted.length+S.REP.visit); assert(tr.next>3*DAY+7*DAY);
  assert(S.margin(60)<S.margin(0)&&S.margin(-60)>S.margin(0)); });

t('the fair-deal rule refuses bad deals and trading below the water floor',()=>{
  const st=S.newState({heads:10}); S.add(st.stores,'tankwater',500); S.add(st.stores,'ration',300);
  assert.equal(S.fair(st,{give:{bottled:1},take:{rifle:0}}).ok,true);
  S.add(st.stores,'rifle',1); assert.equal(S.fair(st,{give:{tradegoods:1},take:{rifle:1}}).ok,false);
  const f=S.fair(st,{give:{rifle:3},take:{tankwater:450}}); assert.equal(f.ok,false); assert.equal(f.why,'water floor'); });

t('support follows the stores, traits and hunger',()=>{
  const p=person('a'), greedy=person('g',{traits:['greedy']}), hungry=person('h',{body:{water:0,food:4000,energy:1}});
  const plenty={foodDays:60,waterDays:30,threat:0}, crisis={foodDays:8,waterDays:20,threat:0};
  assert(S.support(p,'ration','full',plenty)>S.support(p,'ration','survival',plenty));
  assert(S.support(p,'ration','survival',crisis)>S.support(p,'ration','full',crisis));
  assert(S.support(greedy,'ration','survival',crisis)<S.support(p,'ration','survival',crisis));
  assert(S.support(hungry,'ration','survival',crisis)<S.support(p,'ration','survival',crisis));
  const nervous=person('n',{traits:['nervous']}), owl=person('o',{traits:['night-owl']});
  assert(S.support(nervous,'curfew','strict',{threat:.5})>S.support(owl,'curfew','strict',{threat:.5}));
  const fan=person('f',{rel:{L:{opinion:80}}}), foe=person('e',{rel:{L:{opinion:-80}}});
  assert(S.support(fan,'runs','leader',{leader:'L'})>0&&S.support(foe,'runs','leader',{leader:'L'})<0); });

t('roles: one leader at a time, written through the hook',()=>{
  const st=S.newState(), people=[person('a'),person('b')], h=moodHook();
  S.assign(st,people,'a','leader',h); assert.equal(st.leader,'a');
  S.assign(st,people,'b','leader',h); assert.equal(st.leader,'b'); assert(!st.roles.a); assert(h.log.some(x=>x.id==='a'&&x.role===null));
  S.assign(st,people,'a','medic',h); assert.equal(st.roles.a,'medic'); assert.throws(()=>S.assign(st,people,'a','king',h)); });

t('rules give moods through the hook; a hard ration in plenty costs legitimacy and drives people out',()=>{
  const band=()=>{ const ps=[]; for(let i=0;i<10;i++) ps.push(person('p'+i,{traits:i%3?[]:['greedy'],rel:{p0:{opinion:10}}})); ps.push(person('kid',{born:CHILD})); return ps; };
  const people=band(); let now=0;
  const st=S.newState({heads:11,seed:9}); S.add(st.stores,'ration',500); S.add(st.stores,'tankwater',2000);
  S.assign(st,people,'p0','leader'); const h=moodHook(()=>now);
  S.setRule(st,people,'ration','survival',{},h,0);
  assert(h.log.some(x=>x.key==='decision:ration'&&x.value<0)); assert(!h.log.some(x=>x.id==='kid'),'children take no part');
  let gone=[]; const l0=st.legit;
  for(let d=0;d<60;d++){ now=d*DAY; const r=S.civicsDay(st,people,{shortfall:0},h,now); gone=gone.concat(r.departures); }
  assert(st.legit<l0,'legitimacy falls'); assert(gone.length>0,'people leave'); assert(!gone.includes('kid'));
  const m=h.log.find(x=>x.key==='rule:ration'); assert(m.value<=-10&&m.hours===24);
  const st2=S.newState({heads:11,seed:9}); S.add(st2.stores,'ration',500); S.add(st2.stores,'tankwater',2000); const people2=band(); S.assign(st2,people2,'p0','leader');
  let gone2=0; for(let d=0;d<60;d++){ now=d*DAY; gone2+=S.civicsDay(st2,people2,{},moodHook(()=>now),now).departures.length; }
  assert.equal(gone2,0,'full rations in plenty keep everyone'); assert(st2.legit>l0); });

t('run assignment follows the rule',()=>{
  const people=[person('a',{traits:['brave']}),person('b',{traits:['lazy']}),person('c',{role:'scavenger',skills:{shoot:1}}),person('d',{skills:{shoot:4}}),person('L')];
  const st=S.newState(); S.assign(st,people,'L','leader');
  st.rules.runs='volunteers'; const v=S.pickRunners(st,people,2); assert.deepEqual(v,['a','c']);
  st.rules.runs='leader'; assert.deepEqual(S.pickRunners(st,people,2),['d','c']);
  st.rules.runs='rota'; const r1=S.pickRunners(st,people,2), r2=S.pickRunners(st,people,2), r3=S.pickRunners(st,people,2);
  assert.deepEqual(r1,['a','b']); assert.deepEqual(r2,['c','d']); assert.deepEqual(r3,['a','b']); });

t('curfew bars work outside at night; factions group by preference',()=>{
  assert.equal(S.curfewBlocks({curfew:'none'},23*60),false); assert.equal(S.curfewBlocks({curfew:'dusk'},23*60),true);
  assert.equal(S.curfewBlocks({curfew:'dusk'},12*60),false); assert.equal(S.curfewBlocks({curfew:'strict'},DAY+5.5*60),true);
  const st=S.newState(), f=S.factions(st,[person('n',{traits:['nervous']}),person('o',{traits:['night-owl']})],{threat:.5});
  assert(f.curfew.dusk.includes('n')||f.curfew.strict.includes('n')); assert(f.curfew.none.includes('o')); });

t('runs are repeatable from the seed',()=>{
  const run=()=>{ const st=S.newState({heads:8,seed:5}); S.add(st.stores,'ration',100); S.add(st.stores,'tankwater',400); S.add(st.stores,'scrap',30);
    const trs=[S.makeTrader(11),S.makeTrader(12)], out=[]; for(let d=0;d<90;d++){ S.spoil(st.stores,st.capacity,1,.5); out.push(S.traders(st,trs,d*DAY).length); }
    return JSON.stringify([st,out]); };
  assert.equal(run(),run()); });

console.log(`${n} checks passed`);
