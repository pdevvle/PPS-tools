// ---------- combat rules: plain functions over plain data ----------
// Units stand at points ({x, z}); the world is a free space (see space.js) that answers sight, cover, leans, field,
// costTo, pathTo and coverSpots. Every roll takes a seeded rng, so a fight replays exactly.
// Values are the foundation's combat values (briefs/00-foundation.md); combat owns their tuning.
(function(root,factory){ const m=factory(); if(typeof module==='object'&&module.exports) module.exports=m; else root.CombatRules=m; })(this,function(){
const V={aim:{squad:72,raider:60},halfCover:20,fullCover:40,hunker:20,farFrom:24,farPer:1.5,farMax:40,near:8,nearBonus:10,reaction:15,free:10,
  crit:10,critFlanked:40,dmg:[3,5],critDmg:2,move:12,sight:16,cone:Math.PI*.36,around:5,spot:30,overwatch:28,minutesPerTurn:5};

function hash32(s){ let h=2166136261>>>0; for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619); } return h>>>0; }
function rng(seed){ let a=typeof seed==='number'?seed>>>0:hash32(String(seed)); return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }

const P=u=>[u.x,u.z];
const dist=(a,b)=>Math.hypot(a.x-b.x,a.z-b.z);

// can a see b, with both allowed to lean out of cover; returns the two points that worked
function lineOfFire(w,a,b,opt){ const shot=!opt||opt.shot!==false, pa=P(a), pb=P(b);
  const as=[pa,...w.leans(pa,pb)], bs=[pb,...w.leans(pb,pa)];
  for(const x of as) for(const y of bs) if(w.sight(x,y,{shot})) return {from:x,to:y};
  return null; }

// Hit and crit chance for one shot. Units: {team, x, z, hunker, unaware, aim}.
function odds(w,a,b,o={}){ const d=dist(a,b), cv=b.unaware?0:w.coverFrom(P(b),P(a));
  let aim=(a.aim!=null?a.aim:V.aim[a.team])-(cv===2?V.fullCover:cv===1?V.halfCover:0)-(b.hunker&&cv?V.hunker:0)
    -(d>V.farFrom?Math.min(V.farMax,(d-V.farFrom)*V.farPer):0)+(d<V.near?V.nearBonus:0)-(o.reaction?V.reaction:0)+(o.free?V.free:0)+(o.mod||0);
  aim=Math.max(5,Math.min(95,Math.round(aim)));
  return {aim,crit:cv===0?V.critFlanked:V.crit,cover:cv,flanked:cv===0,d}; }
function roll(o,r){ const hit=r()*100<o.aim, crit=hit&&r()*100<o.crit, dmg=hit?V.dmg[0]+Math.floor(r()*(V.dmg[1]-V.dmg[0]+1))+(crit?V.critDmg:0):0; return {hit,crit,dmg}; }

// an unaware raider's eyes: a cone ahead and a little all round, stopped by walls
function sees(w,r,p){ const dx=p[0]-r.x, dz=p[1]-r.z, d=Math.hypot(dx,dz); if(d>V.sight) return false; let a=Math.atan2(dx,dz)-r.face; a=Math.atan2(Math.sin(a),Math.cos(a));
  return (d<V.around||Math.abs(a)<V.cone)&&w.sight(P(r),p); }

const others=(units,u)=>units.filter(x=>x.alive&&x!==u).map(P);

// One decision for a unit on the AI side: {type:'shoot',target,odds} | {type:'move',to,path} | {type:'overwatch'}.
// Shoot when the odds are fair (40%+) and we're in cover or this is the last action; otherwise move to the reachable
// spot that scores best on cover against every foe, a line of fire, and not drifting away. Candidates are the cover
// spots along walls and furniture plus a coarse sample of open floor.
function decide(w,u,units,r,opt={}){ const foes=units.filter(f=>f.alive&&f.team!==u.team); if(!foes.length) return {type:'overwatch'};
  let best=null; for(const f of foes){ if(!lineOfFire(w,u,f)) continue; const o=odds(w,u,f); if(!best||o.aim>best.odds.aim) best={target:f,odds:o}; }
  const myCover=Math.min(...foes.map(f=>w.coverFrom(P(u),P(f))));
  if(!opt.scramble&&best&&best.odds.aim>=40&&(myCover>0||u.ap===1)) return {type:'shoot',target:best.target,odds:best.odds};
  const F=w.field(P(u),V.move,others(units,u)), cands=[];
  for(const s of w.coverSpots) if(Math.hypot(s[0]-u.x,s[1]-u.z)<=V.move+1) cands.push(s);
  for(let n=0;n<F.cost.length;n+=7) if(F.cost[n]<=V.move) cands.push([w.nodeX(n),w.nodeZ(n)]);
  let pick=null, ps=-1e9;
  for(const c of cands){ if(Math.hypot(c[0]-u.x,c[1]-u.z)<.5) continue; let s=0, line=false;
    for(const f of foes){ const cv=w.coverFrom(c,P(f)); s+=cv===2?30:cv===1?15:-25; }
    for(const f of foes){ if(Math.hypot(f.x-c[0],f.z-c[1])<V.spot&&w.sight(c,P(f))){ line=true; break; } }
    s+=(line?20:-10)-Math.min(...foes.map(f=>Math.hypot(f.x-c[0],f.z-c[1])))*.25+r()*6;
    if(s<=ps) continue; const ct=w.costTo(F,c); if(!ct||ct.over) continue; ps=s; pick=c; }
  if(!pick) return best&&best.odds.aim>=25?{type:'shoot',target:best.target,odds:best.odds}:{type:'overwatch'};
  return {type:'move',to:pick,path:w.pathTo(F,pick)}; }

// A whole fight with no rendering: both sides use decide(). Moves are instant; overwatch fires at the end of a move.
// The tests use it to show a seeded fight replays exactly.
function simulate(w,units,seed,maxRounds){ const r=rng(seed), log=[]; maxRounds=maxRounds||30; let minutes=0;
  const alive=t=>units.some(u=>u.alive&&u.team===t);
  const fire=(a,b,o)=>{ const res=roll(o,r); if(res.hit){ b.hp-=res.dmg; if(b.hp<=0){ b.hp=0; b.alive=false; b.ow=false; } } log.push(`${a.id}>${b.id} ${o.aim}% ${res.hit?(res.crit?'crit ':'')+res.dmg:'miss'}`); };
  for(let round=1;round<=maxRounds;round++){
    for(const team of ['squad','raider']){
      for(const u of units.filter(x=>x.alive&&x.team===team)){ u.ap=2; u.ow=false; u.hunker=false; u.unaware=false;
        while(u.ap>0&&u.alive&&alive(team==='squad'?'raider':'squad')){ const a=decide(w,u,units,r);
          if(a.type==='shoot'){ fire(u,a.target,a.odds); u.ap=0; }
          else if(a.type==='move'){ u.x=a.to[0]; u.z=a.to[1]; u.ap--; log.push(`${u.id}->${u.x.toFixed(2)},${u.z.toFixed(2)}`);
            for(const o of units) if(o.alive&&o.ow&&o.team!==team&&dist(o,u)<=V.overwatch&&lineOfFire(w,o,u)){ o.ow=false; fire(o,u,odds(w,o,u,{reaction:true})); if(!u.alive) break; } }
          else { u.ow=true; u.ap=0; } }
        minutes+=V.minutesPerTurn; }
      if(!alive('squad')||!alive('raider')) return {winner:alive('squad')?'squad':'raider',rounds:round,minutes,log}; } }
  return {winner:null,rounds:maxRounds,minutes,log}; }

return {V,rng,hash32,dist,lineOfFire,odds,roll,sees,decide,simulate};
});
