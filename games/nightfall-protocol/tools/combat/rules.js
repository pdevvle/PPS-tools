// ---------- combat rules: plain functions over plain data ----------
// Units stand at points ({x, z}); the world is a free space (see space.js) that answers sight, cover, leans, field,
// costTo, pathTo, coverSpots and blast. Every roll takes a seeded rng, so a fight replays exactly.
// Base values are the foundation's combat values (briefs/00-foundation.md); combat owns their tuning.
(function(root,factory){ const m=factory(); if(typeof module==='object'&&module.exports) module.exports=m; else root.CombatRules=m; })(this,function(){
const V={aim:{squad:72,raider:60},halfCover:20,fullCover:40,hunker:20,reaction:15,free:10,steady:15,
  crit:10,critFlanked:40,move:12,sight:16,cone:Math.PI*.36,around:5,spot:30,overwatch:28,minutesPerTurn:5,
  throwRange:12,blastRadius:3,throughWall:20,blastDmg:3,bleed:3,aidHeal:3,runGunCooldown:3,doorway:1.3};

// Range profiles: how aim changes with distance. Short weapons want to be close, long ones want room.
const PROFILES={
  short:{label:'short',mod:d=>d<6?15:d>12?-Math.min(40,(d-12)*2):0},
  mid:{label:'mid',mod:d=>d<8?10:d>24?-Math.min(40,(d-24)*1.5):0},
  long:{label:'long',mod:d=>d<8?-10:d>40?-Math.min(40,d-40):0},
  melee:{label:'melee',mod:()=>0},
};
const WEAPONS={
  shotgun:{name:'Pump shotgun',profile:'short',dmg:[4,6],crit:15,critDmg:2,ammo:4},
  rifle:{name:'Hunting rifle',profile:'long',dmg:[4,6],crit:10,critDmg:3,ammo:3},
  carbine:{name:'Carbine',profile:'mid',dmg:[3,5],crit:5,critDmg:2,ammo:4},
  pistol:{name:'Pistol',profile:'mid',dmg:[2,4],crit:5,critDmg:1,ammo:8},
  raiderRifle:{name:'Rifle',profile:'mid',dmg:[3,5],crit:0,critDmg:2,ammo:4},
  bossShotgun:{name:'Sawn-off',profile:'short',dmg:[4,6],crit:10,critDmg:2,ammo:2},
  machete:{name:'Machete',profile:'melee',dmg:[4,7],crit:20,critDmg:3,ammo:Infinity,melee:true},
  sidearm:{name:'Revolver',profile:'mid',dmg:[2,3],crit:0,critDmg:1,ammo:Infinity},
};
// The squad's roles, adapted from the original game's four classes to survivors
const ROLES={
  ranger:{label:'Ranger',weapon:'shotgun',hp:6,aim:70,kit:{},skill:'Run and gun: one extra action, every 3 rounds'},
  sharpshooter:{label:'Sharpshooter',weapon:'rifle',hp:5,aim:76,kit:{},skill:'Steady aim: +15 when the shot is the first action of the turn'},
  breacher:{label:'Breacher',weapon:'carbine',hp:7,aim:68,kit:{pipe:2,charge:1},skill:'Pipe bombs; a charge blows barricades and boards at a breach'},
  medic:{label:'Medic',weapon:'pistol',hp:6,aim:70,kit:{aid:2},skill:'First aid: heals 3, or stabilises someone bleeding out'},
  raider:{label:'Raider',weapon:'raiderRifle',hp:4,aim:60,kit:{}},
  // the original game's enemy types, as raiders: the Lancer's charge, the Warden's armour, the Officer's defence
  brute:{label:'Brute',weapon:'machete',hp:5,aim:72,def:10,move:15,kit:{},melee:true},
  enforcer:{label:'Enforcer',weapon:'bossShotgun',hp:8,aim:58,armor:1,move:10,kit:{}},
  boss:{label:'Raider boss',weapon:'bossShotgun',hp:6,aim:64,def:5,kit:{}},
};
// Secondary weapons: the Ranger carries a machete (Slash), the Sharpshooter a revolver (no reload).
const SECONDARY={ranger:'machete',sharpshooter:'sidearm'};
// Ranks: experience from kills and wins; each promotion adds 1 HP and 3 aim (the original game's ladder)
const RANKS=['Rookie','Private','Corporal','Sergeant','Lieutenant','Captain','Major'], XP_REQ=[0,1,3,6,10,15,21];
const rankOf=xp=>{ let r=0; for(let k=0;k<XP_REQ.length;k++) if(xp>=XP_REQ[k]) r=k; return r; };
function makeUnit(role,o){ o=o||{}; const R=ROLES[role], W=WEAPONS[R.weapon], rank=o.rank||0, hp=R.hp+rank;
  const u=Object.assign({role,hp,max:hp,aim:R.aim+rank*3,def:R.def||0,armor:R.armor||0,move:R.move||V.move,weapon:W,ammo:W.ammo,kit:Object.assign({},R.kit),alive:true,ap:2,cooldown:0},o);
  if(SECONDARY[role]) u.second=WEAPONS[SECONDARY[role]]; return u; }

function hash32(s){ let h=2166136261>>>0; for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619); } return h>>>0; }
function rng(seed){ let a=typeof seed==='number'?seed>>>0:hash32(String(seed)); return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }

const P=u=>[u.x,u.z];
const dist=(a,b)=>Math.hypot(a.x-b.x,a.z-b.z);

// can a see b, with both allowed to lean out of cover; returns the two points that worked
function lineOfFire(w,a,b,opt){ const shot=!opt||opt.shot!==false, pa=P(a), pb=P(b);
  const as=[pa,...w.leans(pa,pb)], bs=[pb,...w.leans(pb,pa)];
  for(const x of as) for(const y of bs) if(w.sight(x,y,{shot})) return {from:x,to:y,walls:0};
  // a round can punch through drywall, stucco and doors at someone the squad knows is there (opt.pierce)
  if(opt&&opt.pierce&&w.shotThrough){ const t=w.shotThrough(pa,pb); if(t&&t.walls) return {from:pa,to:pb,walls:t.walls}; }
  return null; }

// Hit and crit chance for one shot, with the reasons, so the page can show where the number comes from.
// opt: reaction (overwatch), doorway (a watched doorway: no reaction penalty), free (first strike), steady, mod.
function odds(w,a,b,o={}){ const W=o.weapon||a.weapon||WEAPONS.carbine, melee=!!W.melee, d=dist(a,b), cv=b.unaware||melee?0:w.coverFrom(P(b),P(a)), why=[];
  const base=a.aim!=null?a.aim:V.aim[a.team]; why.push(['Aim',base]);
  if(melee){ why.push(['Melee',10]); if(b.def) why.push(['Defence',-b.def]); let aim=0; for(const [,v] of why) aim+=v; aim=Math.max(5,Math.min(95,aim));
    return {aim,crit:Math.min(100,(cv===0?V.critFlanked:V.crit)+(W.crit||0)),cover:0,flanked:true,d,why,melee:true}; }
  if(cv===2) why.push(['Full cover',-V.fullCover]); else if(cv===1) why.push(['Half cover',-V.halfCover]);
  if(b.hunker&&cv) why.push(['Hunkered',-V.hunker]);
  const rm=Math.round(PROFILES[W.profile].mod(d)); if(rm) why.push([`${d.toFixed(0)} m, ${PROFILES[W.profile].label} range`,rm]);
  if(o.reaction&&!o.doorway) why.push(['Overwatch',-V.reaction]);
  if(o.free) why.push(['First strike',V.free]);
  if(o.steady) why.push(['Steady aim',V.steady]);
  if(o.mod) why.push([o.modLabel||'Entry',o.mod]);
  if(o.walls) why.push([o.walls>1?`Through ${o.walls} walls`:'Through a wall',-V.throughWall*o.walls]);
  if(b.def) why.push(['Defence',-b.def]);
  let aim=0; for(const [,v] of why) aim+=v; aim=Math.max(5,Math.min(95,Math.round(aim)));
  return {aim,crit:Math.min(100,(cv===0?V.critFlanked:V.crit)+(W.crit||0)),cover:cv,flanked:cv===0,d,why}; }
// armour soaks up to its value from each hit (explosives shred it instead)
function roll(o,r,W,target){ W=W||WEAPONS.carbine; const hit=r()*100<o.aim, crit=hit&&r()*100<o.crit; let dmg=hit?W.dmg[0]+Math.floor(r()*(W.dmg[1]-W.dmg[0]+1))+(crit?W.critDmg:0):0;
  const armor=hit&&target?Math.min(target.armor||0,dmg):0; dmg-=armor; return {hit,crit,dmg,armor}; }
// melee range: close enough to strike (bodies 0.3 m, a blade's reach)
const MELEE=1.4;

// Damage taken: raiders die at 0. Squad members go down and bleed out after V.bleed of their own turns unless stabilised.
function hurt(u,dmg){ u.hp=Math.max(0,u.hp-dmg); if(u.hp>0) return 'hit'; u.alive=false; u.ow=false; u.hunker=false;
  if(u.team==='squad'){ u.down=true; u.bleed=V.bleed; return 'down'; } u.dead=true; return 'dead'; }

// An explosion: everyone within the radius whom the blast can reach (walls stop it) takes damage, cover ignored.
function blastHits(w,c,units,r){ r=r||V.blastRadius; const out=[];
  for(const u of units){ if(!u.alive&&!u.down) continue; const d=Math.hypot(u.x-c[0],u.z-c[1]); if(d>r) continue; if(!w.sight(c,P(u),{shot:true})) continue; out.push({u,dmg:V.blastDmg+(d<1?1:0),shred:(u.armor||0)>0}); }
  return out; }

// an unaware raider's eyes: a cone ahead and a little all round, stopped by walls
function sees(w,r,p){ const dx=p[0]-r.x, dz=p[1]-r.z, d=Math.hypot(dx,dz); if(d>V.sight) return false; let a=Math.atan2(dx,dz)-r.face; a=Math.atan2(Math.sin(a),Math.cos(a));
  return (d<V.around||Math.abs(a)<V.cone)&&w.sight(P(r),p); }

const others=(units,u)=>units.filter(x=>x.alive&&x!==u).map(P);
// is p close to the middle of a doorway or window (where a watcher has it pre-aimed)
function atDoorway(w,p){ for(const e of w.entries().concat(w.innerDoors?w.innerDoors():[])){ const o=e.o||e; const m=[(o.seg[0]+o.seg[2])/2,(o.seg[1]+o.seg[3])/2]; if(Math.hypot(m[0]-p[0],m[1]-p[1])<V.doorway) return true; } return false; }

// Raider morale: once the boss is down or half the pod is gone, each raider may break and run.
function morale(units,r){ const raiders=units.filter(u=>u.team==='raider'), standing=raiders.filter(u=>u.alive);
  const bossDown=raiders.some(u=>u.boss&&!u.alive), half=standing.length*2<=raiders.length;
  if(!(bossDown||half)) return [];
  const out=[]; for(const u of standing) if(!u.fleeing&&!u.boss&&r()<.5){ u.fleeing=true; out.push(u); } return out; }

// One decision for a unit on the AI side:
// {type:'shoot',target,odds} | {type:'move',to,path} | {type:'reload'} | {type:'overwatch'} | {type:'escape'}.
// Fleeing units head for the exit furthest from the squad and escape once outside and out of sight.
// Otherwise: reload when empty; shoot when the odds are fair (40%+) and we're in cover or this is the last action;
// else move to the spot in reach that scores best on cover against every foe and a line of fire. Wounded raiders
// prefer distance; the boss with a sawn-off prefers to close in.
function decide(w,u,units,r,opt={}){ const foes=units.filter(f=>f.alive&&f.team!==u.team); if(!foes.length) return {type:'overwatch'};
  const F=w.field(P(u),u.move||V.move,others(units,u));
  if(u.fleeing){ const out=!w.insideAt(u.x,u.z), seen=foes.some(f=>w.sight(P(f),P(u)));
    if(out&&!seen) return {type:'escape'};
    const exits=w.entries().filter(e=>w.props(e.o).cross); let best=null, bs=-1e9;
    for(const e of exits){ const s=Math.min(...foes.map(f=>Math.hypot(f.x-e.out[0],f.z-e.out[1])))-Math.hypot(e.out[0]-u.x,e.out[1]-u.z)*.5; if(s>bs){ bs=s; best=e; } }
    if(best){ const far=w.field(P(u),400,others(units,u)), route=w.pathTo(far,[best.out[0]+(best.out[0]-best.in[0])*4,best.out[1]+(best.out[1]-best.in[1])*4])||w.pathTo(far,best.out);
      if(route){ let pick=null; for(const q of route.points){ const c=w.costTo(F,[q.x,q.z]); if(c&&!c.over) pick=[q.x,q.z]; } if(pick&&Math.hypot(pick[0]-u.x,pick[1]-u.z)>.3) return {type:'move',to:pick,path:w.pathTo(F,pick),flee:true}; } } }
  if(u.weapon&&u.weapon.melee){   // a blade: reach someone and strike; otherwise close in from cover to cover
    let best=null; for(const f of foes){ const spot=meleeSpot(w,F,u,f,units); if(!spot) continue; const s=-spot.cost+(f.hp<=3?6:0)-(f.hunker?3:0); if(!best||s>best.s) best={s,f,spot}; }
    if(best) return {type:'melee',target:best.f,to:best.spot.p,path:best.spot.path,odds:odds(w,u,best.f)}; }
  if(u.weapon&&u.ammo<=0) return {type:'reload'};
  let best=null; for(const f of foes){ if(!lineOfFire(w,u,f)) continue; const o=odds(w,u,f); if(!best||o.aim>best.odds.aim) best={target:f,odds:o}; }
  const myCover=Math.min(...foes.map(f=>w.coverFrom(P(u),P(f))));
  if(!opt.scramble&&best&&best.odds.aim>=40&&(myCover>0||u.ap===1)) return {type:'shoot',target:best.target,odds:best.odds};
  const cands=[];
  const mv=u.move||V.move; for(const s of w.coverSpots) if(Math.hypot(s[0]-u.x,s[1]-u.z)<=mv+1) cands.push(s);
  for(let n=0;n<F.cost.length;n+=7) if(F.cost[n]<=mv) cands.push([w.nodeX(n),w.nodeZ(n)]);
  const wounded=u.hp<=u.max/2&&!(u.weapon&&u.weapon.melee), closer=u.weapon&&(u.weapon.profile==='short'||u.weapon.melee);
  let pick=null, ps=-1e9;
  for(const c of cands){ if(Math.hypot(c[0]-u.x,c[1]-u.z)<.5) continue; let s=0, line=false;
    for(const f of foes){ const cv=w.coverFrom(c,P(f)); s+=cv===2?30:cv===1?15:-25; }
    for(const f of foes){ if(Math.hypot(f.x-c[0],f.z-c[1])<V.spot&&w.sight(c,P(f))){ line=true; break; } }
    const near=Math.min(...foes.map(f=>Math.hypot(f.x-c[0],f.z-c[1])));
    s+=(line?20:-10)+(wounded?near*.6:closer?-near*.8:-near*.25)+r()*6;
    if(s<=ps) continue; const ct=w.costTo(F,c); if(!ct||ct.over) continue; ps=s; pick=c; }
  if(!pick) return best&&best.odds.aim>=25?{type:'shoot',target:best.target,odds:best.odds}:{type:'overwatch'};
  return {type:'move',to:pick,path:w.pathTo(F,pick)}; }

// where a melee attacker could stand to strike f this action: the cheapest reachable point beside them
function meleeSpot(w,F,u,f,units){ if(dist(u,f)<=MELEE&&w.sight(P(u),P(f),{shot:true})) return {p:P(u),cost:0,path:null};
  const occ=units.filter(x=>(x.alive||x.down)&&x!==u&&x!==f); let best=null;
  for(let k=0;k<12;k++){ const a=k/12*Math.PI*2, p=[f.x+Math.sin(a)*.9,f.z+Math.cos(a)*.9]; if(occ.some(x=>Math.hypot(x.x-p[0],x.z-p[1])<.65)) continue;
    const c=w.costTo(F,p); if(!c||c.over) continue; if(!w.sight(p,P(f),{shot:true})) continue; if(!best||c.cost<best.cost) best={p,cost:c.cost}; }
  if(best) best.path=w.pathTo(F,best.p); return best&&best.path?best:null; }
// Both of a unit's actions decided at once, for a side that plays all its units together: decide the first from
// where it stands, then the second from where the first move leaves it. Returns up to two decisions.
function planAI(w,u,units,r,opt={}){ const out=[], x0=u.x, z0=u.z, ap0=u.ap; u.ap=opt.scramble?1:2;
  for(let k=0;k<(opt.scramble?1:2)&&u.ap>0;k++){ const a=decide(w,u,units,r,opt); out.push(a);
    if(a.type==='move'){ u.x=a.to[0]; u.z=a.to[1]; u.ap--; if(a.flee) continue; continue; }
    break; }
  u.x=x0; u.z=z0; u.ap=ap0; return out; }
// A whole fight with no rendering: both sides use decide(). Moves are instant; overwatch fires at the end of a move.
// The tests use it to show a seeded fight replays exactly.
function simulate(w,units,seed,maxRounds){ const r=rng(seed), log=[]; maxRounds=maxRounds||30; let minutes=0;
  const standing=t=>units.some(u=>u.alive&&u.team===t);
  const fire=(a,b,o,W)=>{ W=W||a.weapon; if(W&&!W.melee) a.ammo--; const res=roll(o,r,W,b); if(res.hit&&res.dmg) hurt(b,res.dmg); log.push(`${a.id}>${b.id} ${o.aim}% ${res.hit?(res.crit?'crit ':'')+res.dmg:'miss'}`); };
  for(let round=1;round<=maxRounds;round++){
    for(const team of ['squad','raider']){
      for(const u of units.filter(x=>x.team===team)){
        if(u.down&&!u.stable&&!u.dead){ if(--u.bleed<=0){ u.dead=true; log.push(`${u.id} bled out`); } continue; }
        if(!u.alive) continue; u.ap=2; u.ow=false; u.hunker=false; u.unaware=false;
        while(u.ap>0&&u.alive&&standing(team==='squad'?'raider':'squad')){ const a=decide(w,u,units,r);
          if(a.type==='shoot'){ fire(u,a.target,a.odds); u.ap=0; }
          else if(a.type==='melee'){ if(a.path){ u.x=a.to[0]; u.z=a.to[1]; } fire(u,a.target,a.odds); u.ap=0; }
          else if(a.type==='reload'){ u.ammo=u.weapon.ammo; u.ap--; log.push(`${u.id} reloads`); }
          else if(a.type==='escape'){ u.alive=false; u.fled=true; log.push(`${u.id} fled`); }
          else if(a.type==='move'){ u.x=a.to[0]; u.z=a.to[1]; u.ap--; log.push(`${u.id}->${u.x.toFixed(2)},${u.z.toFixed(2)}`);
            for(const o of units) if(o.alive&&o.ow&&o.team!==team&&dist(o,u)<=V.overwatch&&lineOfFire(w,o,u)){ o.ow=false; fire(o,u,odds(w,o,u,{reaction:true,doorway:atDoorway(w,P(u))})); if(!u.alive) break; } }
          else { u.ow=true; u.ap=0; } }
        minutes+=V.minutesPerTurn; }
      if(team==='squad') for(const x of morale(units,r)) log.push(`${x.id} breaks`);
      if(!standing('squad')||!standing('raider')) return {winner:standing('squad')?'squad':'raider',rounds:round,minutes,log}; } }
  return {winner:null,rounds:maxRounds,minutes,log}; }

return {V,planAI,PROFILES,WEAPONS,ROLES,SECONDARY,RANKS,XP_REQ,rankOf,MELEE,meleeSpot,makeUnit,rng,hash32,dist,lineOfFire,odds,roll,hurt,blastHits,sees,atDoorway,morale,decide,simulate};
});
