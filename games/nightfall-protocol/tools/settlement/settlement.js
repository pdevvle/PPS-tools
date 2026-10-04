// ---------- settlement: stores, production, barter, traders and civics (briefs/settlement.md, tools/sim/README.md) ----------
// Plain functions over plain data, no rendering, no Math.random or Date: runs in the pages and in Node (tools/settlement/test.js).
// World time is game minutes (campaign.js state.minutes). Food is kcal, water litres. Survivor records belong to people:
// this file reads them and writes back only through hooks ({addMood(p,key,value,hours), setRole(p,role)}).
const Settlement=(()=>{
const VERSION=1, DAY=1440, LIFE_RATIO=25;
const LOOT=['food','medicine','tools','fuel','gear','water','shelter','goods'];

// ---------- items: [id, category, name, unit, kg, kcal, litres, base value, shelf life in days (null = keeps), storage, tags] ----------
// Value points: 1 point is about a litre of clean bottled water. Shelf life is at 25 °C in the right storage.
const ITEM_ROWS=[
  ['ration','food','mixed rations','ration',1,2000,0,10,365,'dry',''],          // campaign.js UNIT.food: 1 ration = 2,000 kcal = 1 kg
  ['canned','food','canned food','can',.4,400,0,2.5,1100,'dry',''],
  ['jerky','food','jerky','pack',.25,750,0,4,180,'dry',''],
  ['flour','food','flour','kg',1,3600,0,9,240,'dry','cookable needscook'],      // not eaten until cooked
  ['produce','food','fresh produce','kg',1,400,0,2,10,'cool','cookable fresh'],
  ['meal','food','cooked meal','portion',.5,700,0,4,2,'cool','cooked'],
  ['bottled','water','bottled water','L',1,0,1,1,null,'dry',''],
  ['tankwater','water','tank water','L',1,0,1,.5,60,'tank',''],                 // campaign.js water from tanks and wells
  ['bandage','medicine','bandages','roll',.1,0,0,3,null,'dry',''],
  ['antibiotics','medicine','antibiotics','course',.05,0,0,25,700,'cool',''],
  ['painkillers','medicine','painkillers','strip',.05,0,0,6,900,'dry',''],
  ['medkit','medicine','med kit','kit',.5,0,0,15,1000,'dry',''],
  ['scrap','tools','scrap parts','part',2,0,0,2,null,'dry',''],
  ['handtools','tools','hand tools','set',3,0,0,15,null,'dry',''],
  ['nails','tools','nails','kg',1,0,0,4,null,'dry',''],
  ['gasoline','fuel','gasoline','L',.8,0,0,3,365,'dry',''],                     // goes stale in about a year
  ['propane','fuel','propane','kg',1.6,0,0,4,null,'dry',''],
  ['firewood','fuel','firewood','kg',1,0,0,.5,null,'dry',''],
  ['ammo','gear','ammunition','box of 20',.5,0,0,15,null,'dry',''],
  ['rifle','gear','rifle','rifle',4,0,0,120,null,'dry',''],
  ['batteries','gear','batteries','pack',.2,0,0,5,1800,'dry',''],
  ['clothing','gear','clothing','set',1,0,0,6,null,'dry',''],
  ['fieldgear','gear','field gear','kit',2,0,0,10,null,'dry',''],
  ['lumber','shelter','lumber','bundle',5,0,0,4,null,'dry',''],
  ['tarp','shelter','tarp','tarp',1.5,0,0,6,null,'dry',''],
  ['tradegoods','goods','trade goods','lot',1,0,0,5,null,'dry',''],
  ['alcohol','goods','spirits','bottle',1,0,0,8,null,'dry',''],
];
const ITEMS={}; for(const [id,cat,name,unit,kg,kcal,L,value,shelf,store,tags] of ITEM_ROWS) ITEMS[id]={id,cat,name,unit,kg,kcal,L,value,shelf,store,tags:tags?tags.split(' '):[]};
// what one unit of a campaign.js loot category (base.stock, squad packs) becomes in the stores
const DEFAULT_ITEM={food:'ration',medicine:'medkit',tools:'scrap',fuel:'gasoline',gear:'fieldgear',water:'tankwater',shelter:'lumber',goods:'tradegoods'};

// ---------- seeded randomness kept in the data it belongs to ----------
function rand(o){ let s=o.rng=(o.rng+0x6D2B79F5)>>>0; s=Math.imul(s^s>>>15,s|1); s^=s+Math.imul(s^s>>>7,s|61); return ((s^s>>>14)>>>0)/4294967296; }
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)), EPS=1e-9, r2=v=>Math.round(v*100)/100;

// ---------- stores: lots of one item with the minute they came in and their condition (1 fresh, 0 spoiled or worn out) ----------
const newStores=()=>({lots:[]});
function add(stores,item,n,minute=0,cond=1){ if(!ITEMS[item]) throw new Error('unknown item '+item); if(n<=EPS) return stores;
  const same=stores.lots.find(l=>l.item===item&&l.at===minute&&Math.abs(l.cond-cond)<1e-6); if(same) same.n+=n; else stores.lots.push({item,n,at:minute,cond}); return stores; }
// a squad's haul or base.stock: {category:count} in campaign.js UNIT units, or {itemId:n}
function receive(stores,pack,minute=0,cond=1){ for(const [k,n] of Object.entries(pack||{})) if(n>0) add(stores,ITEMS[k]?k:DEFAULT_ITEM[k],n,minute,cond); return stores; }
const tidy=stores=>{ stores.lots=stores.lots.filter(l=>l.n>EPS&&l.cond>EPS); return stores; };
const count=(stores,item)=>stores.lots.reduce((a,l)=>a+(l.item===item?l.n:0),0);
const match=(sel,it)=>sel.startsWith('cat:')?it.cat===sel.slice(4):sel.startsWith('tag:')?it.tags.includes(sel.slice(4)):it.id===sel;
const daysLeft=l=>{ const it=ITEMS[l.item]; return it.shelf==null?1e9:l.cond*it.shelf; };
// order to use things in: most perishable first, then oldest; 'cheap' takes the least valuable first (fuel for the stove)
const ordered=(stores,sel,how='perishable')=>stores.lots.filter(l=>match(sel,ITEMS[l.item])).sort(how==='cheap'?
  (a,b)=>ITEMS[a.item].value*a.cond-ITEMS[b.item].value*b.cond||a.at-b.at : (a,b)=>daysLeft(a)-daysLeft(b)||a.at-b.at);
// take n units (or n of a measure: 'kcal', 'L', 'n') of whatever matches; returns the pieces taken
function take(stores,sel,n,measure='n',how='perishable'){ const out=[]; let left=n;
  for(const l of ordered(stores,sel,how)){ if(left<=EPS) break; const per=measure==='n'?1:ITEMS[l.item][measure]; if(!per) continue;
    const u=Math.min(l.n,left/per); l.n-=u; left-=u*per; out.push({item:l.item,n:u,at:l.at,cond:l.cond}); }
  tidy(stores); out.short=Math.max(0,left); return out; }
const sumOf=(pieces,measure)=>pieces.reduce((a,p)=>a+p.n*(measure==='n'?1:ITEMS[p.item][measure]),0);
// what the stores hold of a category: food in kcal, water in litres, the rest in default-item units by value
const REF={}; for(const c of LOOT) REF[c]=ITEMS[DEFAULT_ITEM[c]].value;
function amount(stores,cat){ let a=0; for(const l of stores.lots){ const it=ITEMS[l.item]; if(it.cat!==cat) continue;
  a+=cat==='food'?l.n*it.kcal:cat==='water'?l.n*it.L:l.n*l.cond*it.value/REF[cat]; } return a; }
const edibleKcal=stores=>stores.lots.reduce((a,l)=>{ const it=ITEMS[l.item]; return a+(it.kcal&&!it.tags.includes('needscook')?l.n*it.kcal:0); },0);
const kgOf=stores=>stores.lots.reduce((a,l)=>a+l.n*ITEMS[l.item].kg,0);

// ---------- storage and spoilage (daily cadence) ----------
// capacity from buildings (building.md): {dry:kg, cool:kg (cellar, spring house), tank:L}. Most perishable lots get storage first.
// cool items out of the cool store keep 2.5× worse; tank water in open containers 4×; anything that spoils and does not fit
// anywhere is exposed, 1.5× on top. Heat (0..1, campaign.heatOf) adds up to 2× for perishables (shelf life 30 days or less) and
// up to 1.3× for the rest.
const SPOIL={warmCool:2.5, noTank:4, exposed:1.5, heatFresh:1, heatSlow:.3, fresh:30};
function placeLots(stores,capacity={}){ const cap={dry:capacity.dry||0,cool:capacity.cool||0,tank:capacity.tank||0}, used={dry:0,cool:0,tank:0}, place=new Map();
  const order=stores.lots.slice().sort((a,b)=>daysLeft(a)-daysLeft(b)||a.at-b.at);
  const fit=(where,q)=>{ if(used[where]+q<=cap[where]+EPS){ used[where]+=q; return true; } return false; };
  for(const l of order){ const it=ITEMS[l.item], q=l.n*(it.store==='tank'?1:it.kg);
    place.set(l,it.store==='tank'?(fit('tank',q)?'tank':fit('dry',q)?'open':'exposed')
      :it.store==='cool'?(fit('cool',q)?'cool':fit('dry',q)?'dry':'exposed'):(fit('dry',q)?'dry':'exposed')); }
  return {place,used,cap}; }
function spoilRate(l,where,heat=0){ const it=ITEMS[l.item]; if(it.shelf==null) return 0;
  let f=1+heat*(it.shelf<=SPOIL.fresh?SPOIL.heatFresh:SPOIL.heatSlow);
  if(it.store==='cool'&&where!=='cool') f*=SPOIL.warmCool;
  if(it.store==='tank'&&where!=='tank') f*=SPOIL.noTank;
  if(where==='exposed') f*=SPOIL.exposed;
  return f/it.shelf; }   // condition lost per day
function spoil(stores,capacity,days=1,heat=0){ const {place}=placeLots(stores,capacity), lost={};
  for(const l of stores.lots){ const d=spoilRate(l,place.get(l),heat)*days; if(!d) continue; l.cond-=d;
    if(l.cond<=EPS) lost[l.item]=(lost[l.item]||0)+l.n; }
  tidy(stores); return lost; }

// ---------- rationing (tools/sim/README.md) ----------
// levels cut what is handed out against what is asked; water is cut less because the desert kills fast
const LEVELS={full:{food:1,water:1}, reduced:{food:.75,water:.9}, survival:{food:.5,water:.75}};
const LEVEL_NAMES=Object.keys(LEVELS);
const lifeDay=minute=>minute/(DAY*LIFE_RATIO);
const ageYears=(p,minute)=>(lifeDay(minute)-(p.born||0))/365;
const isChild=(p,minute)=>ageYears(p,minute)<13;
// sick or wounded: pregnant, or any condition but the need ones (dehydration, malnutrition) at severity 0.3 or more
const isSick=p=>(p.conditions||[]).some(c=>c.kind==='pregnant'||(c.kind!=='dehydration'&&c.kind!=='malnutrition'&&(c.severity||0)>=.3));
// priority tiers (lower is served first): 0 children; 1 the sick, wounded and pregnant; 2 working roles (guard, scavenger,
// builder, medic); 3 everyone else. Tiers 0 and 1 are never cut by the rationing level. rules.priority may hold any numbers.
const TIER={child:0,sick:1,role:2,rest:3}, EXEMPT_TIER=1, WORK_ROLES=['guard','scavenger','builder','medic'];
function priorities(people,minute=0){ const pr={};
  for(const p of people){ if(p.alive===false) continue; pr[p.id]=isChild(p,minute)?TIER.child:isSick(p)?TIER.sick:WORK_ROLES.includes(p.role)?TIER.role:TIER.rest; }
  return pr; }
const tierIn=(pr,id)=>pr[id]==null?TIER.rest:pr[id];
// what the rules allow each person before the stores are counted (the yardstick for a real shortfall)
function allowance(demands,rules={}){ const lv=LEVELS[rules.ration]||LEVELS.full, pr=rules.priority||{}, out={};
  for(const [id,d] of Object.entries(demands)){ const ex=tierIn(pr,id)<=EXEMPT_TIER; out[id]={water:(d.water||0)*(ex?1:lv.water),food:(d.food||0)*(ex?1:lv.food)}; } return out; }
// how a tier that cannot be served in full shares what is left: 'ordered' serves people in full one after another
// (rules.order, a list of ids, then by id), 'equal' cuts everyone in proportion. Water defaults to ordered: an equal cut
// in a water shortage dehydrates everyone at once (people.md), so some are kept whole instead. Food defaults to equal.
const SHARE={water:'ordered',food:'equal'};
// demands {[id]:{water:L, food:kcal}}; rules {ration:'full'|'reduced'|'survival', priority:{[id]:tier}, share:{water,food}, order:[ids]}
// returns {[id]:{water, food, cooked}} where cooked is the share of the food that came as cooked meals
function ration(stores,demands,rules={},minute=0){ const pr=rules.priority||{}, out={}, ids=Object.keys(demands), allow=allowance(demands,rules);
  const order=rules.order||[], rank=id=>{ const i=order.indexOf(id); return i<0?1e9:i; };
  for(const id of ids) out[id]={water:0,food:0,cooked:0};
  for(const res of ['water','food']){
    const mode=(rules.share||{})[res]||SHARE[res], tiers=[...new Set(ids.map(id=>tierIn(pr,id)))].sort((a,b)=>a-b);
    let avail=res==='water'?amount(stores,'water'):edibleKcal(stores), total=0;
    for(const tier of tiers){ const who=ids.filter(id=>tierIn(pr,id)===tier), want=who.reduce((a,id)=>a+Math.max(0,allow[id][res]),0); if(!want) continue;
      if(mode==='ordered'&&want>avail) for(const id of who.slice().sort((a,b)=>rank(a)-rank(b)||(a<b?-1:1))){ const g=Math.min(Math.max(0,allow[id][res]),avail); out[id][res]=g; total+=g; avail-=g; }
      else { const share=Math.min(1,avail/want); for(const id of who){ const g=Math.max(0,allow[id][res])*share; out[id][res]=g; total+=g; } avail-=want*share; } }
    if(res==='water') take(stores,'cat:water',total,'L');
    else { const got=[]; let left=total;   // edible food only, most perishable first (meals, produce, then the cans)
      for(const l of stores.lots.filter(l=>ITEMS[l.item].kcal&&!ITEMS[l.item].tags.includes('needscook')).sort((a,b)=>daysLeft(a)-daysLeft(b)||a.at-b.at)){
        if(left<=EPS) break; const k=ITEMS[l.item].kcal, u=Math.min(l.n,left/k); l.n-=u; left-=u*k; got.push({item:l.item,n:u}); }
      tidy(stores); const all=sumOf(got,'kcal'), cooked=got.filter(g=>ITEMS[g.item].tags.includes('cooked')).reduce((a,g)=>a+g.n*ITEMS[g.item].kcal,0);
      for(const id of ids) out[id].cooked=all?cooked/all:0; } }
  for(const id of ids){ out[id].water=r2(out[id].water); out[id].food=Math.round(out[id].food); out[id].cooked=r2(out[id].cooked); }
  return out; }

// ---------- needs of a holder for valuation and urgency: daily use per category ----------
// food kcal, water L (people.md: about 2,250 kcal and 13 L a day for an adult in early summer), the rest in default-item units (med kits, scrap parts, L gasoline, field gear, lumber, trade goods)
const PER_HEAD={food:2250,water:13,medicine:.02,tools:.03,fuel:.5,gear:.02,shelter:.03,goods:.02};
const TARGET={food:30,water:14,medicine:60,tools:60,fuel:60,gear:60,shelter:60,goods:60};   // days of supply that feel comfortable
const needOf=(heads,mult={})=>{ const n={}; for(const c of LOOT) n[c]=PER_HEAD[c]*heads*(mult[c]==null?1:mult[c]); return n; };
const daysOf=(stores,need,cat)=>need[cat]>0?amount(stores,cat)/need[cat]:Infinity;

// ---------- production chains: recipes run at an amenity, offered as tasks, resolved when worked ----------
// in: {selector:n}, selectors are item ids, 'cat:<category>' or 'tag:<tag>'; {kcal:x} asks for food energy instead of units,
// {L:x} for litres; min = the least the recipe runs on (it takes up to the full amount).
// Yields at skill 2 are the listed ones; skill s gives ×clamp(0.7+0.15s, 0.5, 1.5); cooking keeps min(1, 0.9 × that) of the kcal. Each amenity unit runs a recipe once a day.
const RECIPES={
  water:   {kind:'haul',  skill:null,   hours:3, needs:'well',      in:{},                                  out:{tankwater:150}, cat:'water', label:'draw and carry water'},
  garden:  {kind:'grow',  skill:'grow', hours:4, needs:'garden',    in:{'cat:water':{L:25}},                out:{produce:8},    cat:'food',  label:'tend a garden plot'},
  tools:   {kind:'craft', skill:'craft',hours:4, needs:'workshop',  in:{scrap:3},                           out:{handtools:1},  cat:'tools', label:'make tools from scrap'},
  cook:    {kind:'cook',  skill:'cook', hours:2, needs:'kitchen',   in:{'tag:cookable':{kcal:5600,min:1400},'cat:fuel':{n:3,how:'cheap'}}, out:{meal:'kcal'}, cat:'food', label:'cook meals'},
  medicine:{kind:'nurse', skill:'medic',hours:3, needs:'infirmary', in:{clothing:1,alcohol:1},              out:{bandage:6},    cat:'medicine', label:'make dressings'},
};
const skillMult=s=>s==null?1:clamp(.7+.15*s,.5,1.5);
const inSpec=v=>typeof v==='number'?{n:v}:v;
function canRun(stores,key){ const r=RECIPES[key];
  for(const [sel,v] of Object.entries(r.in)){ const s=inSpec(v), m=s.kcal?'kcal':s.L?'L':'n', want=s.min||s.kcal||s.L||s.n;
    if(ordered(stores,sel).reduce((a,l)=>a+l.n*(m==='n'?1:ITEMS[l.item][m]),0)<want-EPS) return false; } return true; }
// tasks for today's open slots: {id, kind, skill, where, hours, urgency, recipe}; urgency rises as the output runs short
function offer(S,minute){ const day=Math.floor(minute/DAY), out=[];
  const dry=daysOf(S.stores,S.need,'water')<TARGET.water/2;   // under 7 days of water, nothing that uses water is offered: people drink first
  for(const [key,r] of Object.entries(RECIPES)){ const slots=(S.amen||{})[r.needs]||0; if(!slots||!canRun(S.stores,key)) continue;
    if(dry&&Object.keys(r.in).includes('cat:water')) continue;
    const d=key==='cook'?count(S.stores,'meal')*ITEMS.meal.kcal/Math.max(1,S.need.food)/2:daysOf(S.stores,S.need,r.cat)/TARGET[r.cat];
    const urgency=r2(clamp(1-d,0,1));
    for(let k=0;k<slots;k++){ const id=`${key}:${day}:${k}`; if(!S.done[id]) out.push({id,kind:r.kind,skill:r.skill,where:null,hours:r.hours,urgency,recipe:key}); } }
  return out.sort((a,b)=>b.urgency-a.urgency); }
// ---------- care: a medic treats someone; the integration turns the result into People.treat(patient, kind, quality) ----------
// supplies tried in order for each condition kind (people.md kinds), with the quality each adds; hours per treatment.
// quality = 0.25 + 0.1 × medic skill + the supply's bonus + 0.1 at an infirmary, at most 1. Without supplies, care alone.
const CARE={
  wound:     {hours:1,  use:[['bandage',1,.3],['medkit',1,.4]]},
  infection: {hours:.5, use:[['antibiotics',1,.5],['medkit',1,.2]]},
  illness:   {hours:.5, use:[['painkillers',1,.2],['medkit',1,.2]]},
  heatstroke:{hours:1,  use:[['cat:water',{L:3},.3]]},
  chronic:   {hours:.5, use:[['painkillers',1,.2]]},
};
const CARE_BELOW=.5;   // a condition treated below this quality is offered again (once a day per patient and kind)
// treatment tasks for the people at base: {id, kind:'nurse', skill:'medic', where, hours, urgency, patient, condition}
function offerCare(S,people,minute){ const day=Math.floor(minute/DAY), out=[];
  for(const p of people){ if(p.alive===false||(p.at&&p.at!=='base')) continue;
    for(const c of p.conditions||[]){ const care=CARE[c.kind]; if(!care||(c.treated||0)>=CARE_BELOW) continue;
      const id=`treat:${day}:${p.id}:${c.kind}`; if(S.done[id]||out.some(t=>t.id===id)) continue;
      out.push({id,kind:'nurse',skill:'medic',where:null,hours:care.hours,urgency:r2(clamp(c.severity*1.5,.1,1)),patient:p.id,condition:c.kind}); } }
  return out.sort((a,b)=>b.urgency-a.urgency); }
function care(S,taskId,medic,minute){ const [,,patient,kind]=taskId.split(':'), cr=CARE[kind]; if(!cr) return {ok:false,why:'no such care'};
  let bonus=0; const used=[];
  for(const [sel,v,b] of cr.use){ const sp=inSpec(v), m=sp.L?'L':'n', want=sp.L||sp.n;
    if(ordered(S.stores,sel).reduce((a,l)=>a+l.n*(m==='n'?1:ITEMS[l.item][m]),0)>=want-EPS){ used.push(...take(S.stores,sel,want,m)); bonus=b; break; } }
  const quality=r2(clamp(.25+.1*(medic?(medic.skills||{}).medic||0:0)+bonus+((S.amen||{}).infirmary?.1:0),0,1));
  S.done[taskId]=minute; return {ok:true,treat:{patient,kind,quality,by:medic?medic.id:null},used:used.map(u=>({item:u.item,n:r2(u.n)})),made:{}}; }
// the task was worked: take the inputs, add the outputs (or, for care, say who was treated and how well).
// worker = survivor record (for skills) or null.
function work(S,taskId,worker,minute){ const [key,day]=taskId.split(':'), r=RECIPES[key];
  if(key==='treat'){ if(S.done[taskId]) return {ok:false,why:'already done'}; const res=care(S,taskId,worker,minute); for(const k in S.done) if(minute-S.done[k]>2*DAY) delete S.done[k]; return res; }
  if(!r) return {ok:false,why:'no such recipe'}; if(S.done[taskId]) return {ok:false,why:'already done'};
  if(!canRun(S.stores,key)) return {ok:false,why:'missing inputs'};
  const used=[], made={}; let kcal=0;
  for(const [sel,v] of Object.entries(r.in)){ const s=inSpec(v), m=s.kcal?'kcal':s.L?'L':'n', got=take(S.stores,sel,s.kcal||s.L||s.n,m,s.how);
    used.push(...got); if(m==='kcal') kcal+=sumOf(got,'kcal'); }
  const mult=skillMult(r.skill&&worker?(worker.skills||{})[r.skill]||0:null);
  for(const [item,q] of Object.entries(r.out)){ const n=q==='kcal'?kcal*Math.min(1,.9*mult)/ITEMS[item].kcal:q*mult;
    add(S.stores,item,n,minute); made[item]=r2(n); }
  S.done[taskId]=minute; for(const k in S.done) if(minute-S.done[k]>2*DAY) delete S.done[k];
  return {ok:true,used:used.map(u=>({item:u.item,n:r2(u.n)})),made}; }

// ---------- barter: value from scarcity ----------
// value of n units to a holder {stores, need} = base × condition × scarcity, scarcity = √(target days / days on hand), 0.35 to 3,
// taken at the middle of the change (receiving lowers it, giving raises it). A holder with no use for a category values it at 0.35.
// holder.floor raises that minimum: traders keep floor 1, so they never let goods go below base value however little they need them.
const SCARCITY={min:.35,max:3};
const scarcity=(days,target)=>clamp(Math.sqrt(target/Math.max(days,.25)),SCARCITY.min,SCARCITY.max);
const perUnit=(it,cond)=>it.cat==='food'?it.kcal:it.cat==='water'?it.L:cond*it.value/REF[it.cat];
function avgCond(stores,item){ let n=0,c=0; for(const l of stores.lots) if(l.item===item){ n+=l.n; c+=l.n*l.cond; } return n?c/n:1; }
function valueOf(holder,item,n,dir=1,cond){ const it=ITEMS[item]; if(cond==null) cond=dir<0?avgCond(holder.stores,item):1;
  const need=holder.need[it.cat]||0, lo=holder.floor||SCARCITY.min; if(!need) return n*it.value*cond*lo;
  const d0=amount(holder.stores,it.cat)/need, d1=Math.max(0,d0+dir*n*perUnit(it,cond)/need);
  return n*it.value*cond*Math.max(lo,scarcity((d0+d1)/2,TARGET[it.cat])); }
const bundleValue=(holder,bundle,dir)=>Object.entries(bundle).reduce((a,[k,n])=>a+valueOf(holder,k,n,dir),0);
// move a bundle {item:n} between stores, keeping condition and acquisition time
function move(from,to,bundle,minute){ for(const [item,n] of Object.entries(bundle)) for(const p of take(from,item,n)) add(to,item,p.n,minute,p.cond); }

// ---------- traders ----------
const TRADER_NAMES=['the Verde caravan','Hollis the tinker','the Agua Fria brothers','Rosa Contreras','the Bumble Bee mule train','Old Teague'];
// a travelling trader: an aggregate holder with seeded stock, two wanted categories and a visiting schedule
function makeTrader(seed,o={}){ const tr={id:o.id||'tr'+(seed>>>0).toString(36),seed:seed>>>0,rng:seed>>>0,visits:0,floor:1,stores:newStores()};
  tr.name=o.name||TRADER_NAMES[Math.floor(rand(tr)*TRADER_NAMES.length)];
  const cats=LOOT.slice(); tr.wants=[]; for(let k=0;k<2;k++) tr.wants.push(cats.splice(Math.floor(rand(tr)*cats.length),1)[0]);
  const mult={}; for(const c of LOOT) mult[c]=tr.wants.includes(c)?2:.25; tr.need=needOf(o.heads||6,mult);
  tr.every=o.every||Math.round(10+rand(tr)*10); tr.next=o.first!=null?o.first:Math.round((2+rand(tr)*tr.every)*DAY);
  return tr; }
// fresh stock for each visit: five lines of goods outside the trader's wants, each worth 40 to 120 points, plus food and water for the road
function restock(tr,minute){ tr.stores=newStores(); const ids=Object.keys(ITEMS).filter(id=>!tr.wants.includes(ITEMS[id].cat)&&id!=='meal');
  for(let k=0;k<5;k++){ const id=ids[Math.floor(rand(tr)*ids.length)], it=ITEMS[id], worth=40+rand(tr)*80;
    add(tr.stores,id,Math.max(1,Math.round(worth/it.value)),minute,it.shelf?.8+.2*rand(tr):1); }
  add(tr.stores,'jerky',20,minute); add(tr.stores,'bottled',30,minute); }
// how much a trader asks over fair value, from reputation (−100..100): 1.2 at 0, 1.0 at +50 and above, up to 1.4 below
const margin=rep=>clamp(1.2-(rep||0)/250,1,1.4);
const FLOOR={food:7,water:7};   // the settlement never trades its food or water below this many days
const isWhole=it=>!['L','kg'].includes(it.unit);
// deals the trader puts on the table: goods it has that we value more than it does, against goods we have that it values more
function proposals(tr,S,maxDeals=3){ const ours={stores:S.stores,need:S.need}, theirs={stores:tr.stores,need:tr.need,floor:tr.floor}, rep=S.rep[tr.id]||0;
  const distinct=st=>[...new Set(st.lots.map(l=>l.item))];
  const offers=distinct(tr.stores).map(i=>[i,valueOf(ours,i,1,1,avgCond(tr.stores,i))/valueOf(theirs,i,1,-1)]).filter(x=>x[1]>1.1).sort((a,b)=>b[1]-a[1]);
  const asks=distinct(S.stores).filter(i=>ITEMS[i].tags.indexOf('cooked')<0).map(i=>[i,valueOf(theirs,i,1,1,avgCond(S.stores,i))/valueOf(ours,i,1,-1)]).filter(x=>x[1]>1.1).sort((a,b)=>b[1]-a[1]);
  const deals=[];
  for(let k=0;k<Math.min(maxDeals,offers.length)&&asks.length;k++){ const gi=offers[k][0], ai=asks[k%asks.length][0], G=ITEMS[gi], A=ITEMS[ai];
    let ng=Math.min(count(tr.stores,gi),Math.max(1,Math.round(60/G.value))); if(isWhole(G)) ng=Math.floor(ng); if(ng<=0) continue;
    const have=count(S.stores,ai), price=valueOf(theirs,gi,ng,-1)*margin(rep);
    let lo=0, hi=have; for(let i=0;i<40;i++){ const mid=(lo+hi)/2; if(valueOf(theirs,ai,mid,1,avgCond(S.stores,ai))<price) lo=mid; else hi=mid; }
    let na=isWhole(A)?Math.ceil(hi-EPS):Math.ceil(hi*10-EPS)/10; if(na>have+EPS||valueOf(theirs,ai,na,1,avgCond(S.stores,ai))<price-EPS) continue;
    deals.push({give:{[gi]:ng},take:{[ai]:na}}); }   // give = from the trader to us, take = from us to the trader
  return deals; }
// the settlement's fair-deal rule: what comes in is worth at least what goes out, to us, and food and water stay above the floor
function fair(S,deal){ const ours={stores:S.stores,need:S.need};
  const got=bundleValue(ours,deal.give,1), gave=bundleValue(ours,deal.take,-1);
  for(const c of Object.keys(FLOOR)){ let after=amount(S.stores,c);
    for(const [i,n] of Object.entries(deal.take)) if(ITEMS[i].cat===c) after-=n*perUnit(ITEMS[i],1);
    for(const [i,n] of Object.entries(deal.give)) if(ITEMS[i].cat===c) after+=n*perUnit(ITEMS[i],1);
    if(S.need[c]&&after/S.need[c]<FLOOR[c]&&after<amount(S.stores,c)) return {ok:false,got,gave,why:c+' floor'}; }
  return {ok:got>=gave-EPS,got,gave,why:got>=gave-EPS?'':'not worth it'}; }
// a visit: restock, put deals on the table, accept the fair ones, write the ledger, move reputation, schedule the next visit
const REP={trade:3,visit:1,refuse:-1};
function visit(S,tr,minute){ restock(tr,minute); tr.visits++; const res={trader:tr.id,name:tr.name,minute,accepted:[],declined:[]};
  for(const deal of proposals(tr,S)){ const f=fair(S,deal);
    if(!f.ok){ res.declined.push({...deal,why:f.why}); continue; }
    const theirs={stores:tr.stores,need:tr.need,floor:tr.floor}, tv={gave:bundleValue(theirs,deal.give,-1),got:bundleValue(theirs,deal.take,1)};
    move(tr.stores,S.stores,deal.give,minute); move(S.stores,tr.stores,deal.take,minute);
    S.ledger.push({minute,with:tr.id,got:deal.give,gave:deal.take,ours:{got:r2(f.got),gave:r2(f.gave)},theirs:{got:r2(tv.got),gave:r2(tv.gave)}});
    res.accepted.push(deal); S.rep[tr.id]=clamp((S.rep[tr.id]||0)+REP.trade,-100,100); }
  S.rep[tr.id]=clamp((S.rep[tr.id]||0)+(res.accepted.length?REP.visit:REP.refuse),-100,100);
  tr.next=minute+Math.round((tr.every+(rand(tr)*4-2))*DAY); return res; }
// the trader loop: call daily (or each step); every trader whose time has come visits
function traders(S,list,minute){ return list.filter(tr=>tr.next<=minute).map(tr=>visit(S,tr,minute)); }

// ---------- civics: roles, three rules, support, legitimacy, unrest ----------
const ROLES=['leader','medic','guard','scavenger','cook','builder'];
const RULES={ration:['full','reduced','survival'], curfew:['none','dusk','strict'], runs:['volunteers','rota','leader']};
// everyone's mood from a rule in force (refreshed daily for 24 h), plus 4 × their support for it
const RULE_MOOD={ration:[0,-4,-10], curfew:[0,-1,-4], runs:[1,0,-2]}, SUPPORT_MOOD=4;
// trait leanings (people.md owns the trait list; unknown traits do nothing). ration/curfew shift the level a person wants
// (positive = stricter), runs add to the support for each option.
const TRAIT_BIAS={
  greedy:{ration:-.8}, glutton:{ration:-.8}, frugal:{ration:.5}, selfless:{ration:.5},
  cautious:{curfew:.6}, nervous:{curfew:.8}, 'night-owl':{curfew:-.8}, 'free-spirit':{curfew:-.8,runs:{leader:-.4}},
  brave:{runs:{volunteers:.4}}, lazy:{runs:{volunteers:.3,rota:-.4}}, fair:{runs:{rota:.4}}, kind:{runs:{rota:.2}},
  loyal:{runs:{leader:.4}}, ambitious:{runs:{leader:.2}} };
// adults (16+) who are still here: alive, not walked out (people marks at:'gone') and not on the settlement's leavers list
const isAdult=(p,minute,S)=>p.alive!==false&&p.at!=='gone'&&!(S&&S.left.some(l=>l.id===p.id))&&ageYears(p,minute)>=16;
const moodSum=(p,minute)=>(p.mood||[]).reduce((a,m)=>a+(m.until==null||m.until>=minute?m.value:0),0);
// support (−1..1) of survivor p for an option of a rule, from stores, threat, hunger, role, traits and opinion of the leader.
// ctx: {foodDays, waterDays, threat 0..1, leader id}
function support(p,rule,option,ctx){ const idx=RULES[rule].indexOf(option), tr=p.traits||[];
  const bias=k=>tr.reduce((a,t)=>a+((TRAIT_BIAS[t]||{})[k]||0),0);
  if(rule==='ration'){   // the level the stores call for: full above 30 days of food and 14 of water, survival under 10 and 4
    const ideal=Math.max(clamp((30-ctx.foodDays)/10,0,2),clamp((14-ctx.waterDays)/5,0,2));
    const hunger=clamp(((p.body||{}).food||0)/3000,0,1)+clamp(((p.body||{}).water||0)/3,0,1)*.5;   // a hungry person wants more now
    return r2(clamp(1-.9*Math.abs(idx-(ideal+bias('ration')-hunger)),-1,1)); }
  if(rule==='curfew'){ const ideal=2*(ctx.threat||0)+bias('curfew')+(p.role==='guard'?.3:0)+(p.role==='scavenger'?-.3:0);
    return r2(clamp(1-.8*Math.abs(idx-ideal),-1,1)); }
  const base={volunteers:.3,rota:.2,leader:-.2}[option];
  const op=ctx.leader&&p.id!==ctx.leader?((p.rel||{})[ctx.leader]||{}).opinion||0:p.id===ctx.leader?60:0;
  const t=tr.reduce((a,k)=>a+(((TRAIT_BIAS[k]||{}).runs||{})[option]||0),0);
  const role=p.role==='scavenger'&&option==='volunteers'?.3:0, lead=option==='leader'?op/100*.8:0;
  return r2(clamp(base+t+role+lead,-1,1)); }
function newState(o={}){ return {v:VERSION, rng:(o.seed||1)>>>0, stores:newStores(), capacity:o.capacity||{dry:2000,cool:200,tank:2000}, amen:o.amen||{},
  need:o.need||needOf(o.heads||12), rules:{ration:'full',curfew:'none',runs:'volunteers'}, roles:{}, leader:null, legit:50, unrest:{},
  ledger:[], rep:{}, done:{}, rota:0, left:[]}; }
// role assignment; one leader at a time. hooks.setRole(p,role) writes it to the survivor (People.setRole).
function assign(S,people,id,role,hooks={}){ if(role!=null&&!ROLES.includes(role)) throw new Error('unknown role '+role);
  const p=people.find(q=>q.id===id); if(!p) return false;
  if(role==='leader'&&S.leader&&S.leader!==id){ const old=people.find(q=>q.id===S.leader); delete S.roles[S.leader]; if(old&&hooks.setRole) hooks.setRole(old,null); S.legit=Math.min(S.legit,40); }
  if(S.leader===id&&role!=='leader') S.leader=null;
  if(role==='leader') S.leader=id;
  if(role) S.roles[id]=role; else delete S.roles[id];
  if(hooks.setRole) hooks.setRole(p,role); return true; }
function context(S,ctx={}){ return {foodDays:ctx.foodDays!=null?ctx.foodDays:daysOf(S.stores,S.need,'food'), waterDays:ctx.waterDays!=null?ctx.waterDays:daysOf(S.stores,S.need,'water'),
  threat:ctx.threat||0, shortfall:ctx.shortfall||0, leader:S.leader}; }
// change a rule: the old rule's mood is removed (hooks.removeMood) and the new one set; supporters of the new option get +3
// for 3 days, opponents −3, and legitimacy moves by 5 × the average support
function setRule(S,people,rule,option,ctx={},hooks={},minute=0){ if(!RULES[rule]||!RULES[rule].includes(option)) throw new Error('bad rule '+rule+'='+option);
  S.rules[rule]=option; const c=context(S,ctx), idx=RULES[rule].indexOf(option); let sum=0,n=0;
  for(const p of people){ if(!isAdult(p,minute,S)) continue; const s=support(p,rule,option,c); sum+=s; n++;
    if(hooks.removeMood) hooks.removeMood(p,'rule:'+rule);   // the old rule's mood goes at once, the new one starts now
    if(hooks.addMood){ hooks.addMood(p,'rule:'+rule,r2(RULE_MOOD[rule][idx]+SUPPORT_MOOD*s),24); if(Math.abs(s)>=.2) hooks.addMood(p,'decision:'+rule,s>0?3:-3,72); } }
  const avg=n?sum/n:0; S.legit=clamp(S.legit+5*avg,0,100); return avg; }
// daily civics: rule moods, support, legitimacy, unrest and who leaves. ctx: {threat, shortfall (0..1 of demand unmet yesterday)}
// legitimacy moves 15% a day towards 50 + 30 × average stance + 20 × average opinion of the leader / 100 − 30 × shortfall
// (25 with no leader). Unrest per adult rises with opposition, a bad mood and shortfall, falls with legitimacy; over 60
// a survivor leaves with a daily chance of (unrest − 60) / 400 (10% a day at 100).
const UNREST={opp:10,mood:.25,short:12,calm:6,decay:1.5,leaveAt:60,leaveSpan:400};
// a survivor's overall stance: rationing weighs half, curfew and runs a quarter each, opposition counts double
const RULE_WEIGHT={ration:.5,curfew:.25,runs:.25};
function civicsDay(S,people,ctx={},hooks={},minute=0){ const c=context(S,ctx), adults=people.filter(p=>isAdult(p,minute,S)), sup={}, departures=[];
  let all=0,n=0,op=0,on=0;
  for(const p of adults){ const s={}; let ps=0;
    for(const rule of Object.keys(RULES)){ const v=support(p,rule,S.rules[rule],c); s[rule]=v; ps+=v;
      if(hooks.addMood) hooks.addMood(p,'rule:'+rule,r2(RULE_MOOD[rule][RULES[rule].indexOf(S.rules[rule])]+SUPPORT_MOOD*v),24); }
    sup[p.id]=s; ps=Object.keys(RULES).reduce((a,k)=>a+RULE_WEIGHT[k]*(s[k]<0?2*s[k]:s[k]),0); all+=ps; n++;
    if(S.leader&&p.id!==S.leader){ op+=((p.rel||{})[S.leader]||{}).opinion||0; on++; }
    const u=(S.unrest[p.id]||0)+UNREST.opp*Math.max(0,-ps)+UNREST.mood*Math.max(0,-moodSum(p,minute))+UNREST.short*c.shortfall-UNREST.calm*S.legit/100-UNREST.decay;
    S.unrest[p.id]=r2(clamp(u,0,100)); }
  const avg=n?all/n:0, target=S.leader?50+30*avg+20*(on?op/on:0)/100-30*c.shortfall:25;
  S.legit=r2(clamp(S.legit+(target-S.legit)*.15,0,100));
  for(const p of adults){ const u=S.unrest[p.id]; if(u>UNREST.leaveAt&&rand(S)<(u-UNREST.leaveAt)/UNREST.leaveSpan){ departures.push(p.id); S.left.push({id:p.id,minute,unrest:u}); delete S.unrest[p.id]; clearMoods(p,hooks); if(S.roles[p.id]) assign(S,people,p.id,null,hooks); } }
  return {support:sup,avgSupport:r2(avg),legit:S.legit,departures}; }
// exile: the community sends someone away (a decision; mood hooks for the rest are the caller's)
// settlement moods all expire within 3 days, none use until:null; this removes them at once (departure, exile)
function clearMoods(p,hooks={}){ if(!hooks.removeMood||!p) return; for(const r of Object.keys(RULES)){ hooks.removeMood(p,'rule:'+r); hooks.removeMood(p,'decision:'+r); } }
function exile(S,people,id,hooks={},minute=0){ if(S.roles[id]) assign(S,people,id,null,hooks); clearMoods(people.find(q=>q.id===id),hooks); S.left.push({id,minute,exiled:true}); delete S.unrest[id]; return id; }
// who goes on a run under the run rule: volunteers (the most willing), a rota (in turn), or the leader's picks (best shots, scavengers first)
function pickRunners(S,people,n,minute=0){ const pool=people.filter(p=>isAdult(p,minute,S)&&p.at!=='away'&&(p.at==null||p.at==='base')&&!isSick(p)&&p.id!==S.leader);
  if(S.rules.runs==='rota'){ const ids=pool.map(p=>p.id).sort(), out=[]; for(let k=0;k<Math.min(n,ids.length);k++) out.push(ids[(S.rota+k)%ids.length]); S.rota=(S.rota+out.length)%Math.max(1,ids.length); return out; }
  const score=S.rules.runs==='leader'?p=>((p.skills||{}).shoot||0)+(p.role==='scavenger'?2:0)
    :p=>((p.traits||[]).includes('brave')?2:0)-((p.traits||[]).includes('lazy')?2:0)+(p.role==='scavenger'?1.5:0)+((p.body||{}).energy==null?1:p.body.energy)-(S.unrest[p.id]||0)/50;
  return pool.map(p=>[p.id,score(p)]).filter(x=>S.rules.runs==='leader'||x[1]>0).sort((a,b)=>b[1]-a[1]||(a[0]<b[0]?-1:1)).slice(0,n).map(x=>x[0]); }
// factions (stub): who would pick which option of each rule
function factions(S,people,ctx={},minute=0){ const c=context(S,ctx), out={};
  for(const rule of Object.keys(RULES)){ out[rule]={}; for(const o of RULES[rule]) out[rule][o]=[];
    for(const p of people){ if(!isAdult(p,minute,S)) continue; let best=null,bv=-2; for(const o of RULES[rule]){ const v=support(p,rule,o,c); if(v>bv){ bv=v; best=o; } } out[rule][best].push(p.id); } }
  return out; }
// curfew effects for other systems: share of night exposure kept, and whether outside work is barred at a time of day
const CURFEW={none:{exposure:1,from:null,to:null},dusk:{exposure:.6,from:20*60,to:5*60},strict:{exposure:.3,from:19*60,to:6*60}};
function curfewBlocks(rules,minute){ const c=CURFEW[rules.curfew||'none']; if(c.from==null) return false; const m=((minute%DAY)+DAY)%DAY; return m>=c.from||m<c.to; }

return {VERSION,DAY,LIFE_RATIO,LOOT,ITEMS,DEFAULT_ITEM,newStores,add,receive,take,count,amount,edibleKcal,kgOf,placeLots,spoilRate,spoil,SPOIL,
  LEVELS,LEVEL_NAMES,TIER,SHARE,priorities,allowance,ration,ageYears,isChild,isSick,PER_HEAD,TARGET,needOf,daysOf,RECIPES,skillMult,canRun,offer,work,CARE,offerCare,
  SCARCITY,scarcity,valueOf,bundleValue,move,makeTrader,restock,margin,proposals,fair,visit,traders,REP,FLOOR,
  ROLES,RULES,RULE_MOOD,TRAIT_BIAS,support,newState,assign,setRule,civicsDay,clearMoods,exile,pickRunners,factions,CURFEW,curfewBlocks,rand};
})();
if(typeof module!=='undefined') module.exports=Settlement;
