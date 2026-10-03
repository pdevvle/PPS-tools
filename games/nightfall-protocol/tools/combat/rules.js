// ---------- combat rules: plain functions over plain data ----------
// Works on any "world" that answers the same questions (see interior-world.js): cx, cz, neighbours, sight, coverFrom,
// hasFullCover, step, passable, edge, props, itemAt. Every roll takes a seeded rng, so a fight replays exactly.
// Values are the foundation's combat values (briefs/00-foundation.md); combat owns their tuning.
(function(root,factory){ const m=factory(); if(typeof module==='object'&&module.exports) module.exports=m; else root.CombatRules=m; })(this,function(){
const V={aim:{squad:72,raider:60},halfCover:20,fullCover:40,hunker:20,high:15,farFrom:24,farPer:1.5,farMax:40,near:8,nearBonus:10,reaction:15,free:10,
  crit:10,critFlanked:40,dmg:[3,5],critDmg:2,move:12,sight:16,cone:Math.PI*.36,around:5,spot:30,minutesPerTurn:5};

function hash32(s){ let h=2166136261>>>0; for(let i=0;i<s.length;i++){ h^=s.charCodeAt(i); h=Math.imul(h,16777619); } return h>>>0; }
function rng(seed){ let a=typeof seed==='number'?seed>>>0:hash32(String(seed)); return function(){ a|=0; a=a+0x6D2B79F5|0; let t=Math.imul(a^a>>>15,1|a); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }; }

const dist=(w,a,b)=>Math.hypot(w.cx(a)-w.cx(b),w.cz(a)-w.cz(b));

// Stepping out: a unit tucked behind full cover may lean one cell sideways to see or shoot (XCOM's peek).
// Only into open floor on the same side of every wall.
function peeks(w,c){ const out=[c]; if(!w.hasFullCover(c)) return out;
  for(let d=0;d<4;d++){ const n=w.step(c,d); if(n<0||!w.passable(n)||w.itemAt(n)) continue; if(!w.edgeFree(c,d)) continue; if(w.coverDir(c,d)===2) continue; out.push(n); }
  return out; }
// can a see b, allowing both to lean out of cover; returns the pair of cells that worked
function lineOfFire(w,a,b,opt){ const shot=!opt||opt.shot!==false; const pa=peeks(w,a), pb=peeks(w,b);
  for(const x of pa) for(const y of pb) if(w.sight(x,y,{shot})) return {from:x,to:y};
  return null; }

// Hit chance and crit chance for one shot. `a` and `b` are units: {team, c, hunker, unaware}.
function odds(w,a,b,o={}){ const d=dist(w,a.c,b.c), cv=b.unaware?0:w.coverFrom(b.c,w.cx(a.c),w.cz(a.c));
  let aim=(a.aim!=null?a.aim:V.aim[a.team])-(cv===2?V.fullCover:cv===1?V.halfCover:0)-(b.hunker&&cv?V.hunker:0)
    -(d>V.farFrom?Math.min(V.farMax,(d-V.farFrom)*V.farPer):0)+(d<V.near?V.nearBonus:0)-(o.reaction?V.reaction:0)+(o.free?V.free:0)+(o.mod||0);
  aim=Math.max(5,Math.min(95,Math.round(aim)));
  return {aim,crit:cv===0?V.critFlanked:V.crit,cover:cv,flanked:cv===0,d}; }
function roll(o,r){ const hit=r()*100<o.aim, crit=hit&&r()*100<o.crit, dmg=hit?V.dmg[0]+Math.floor(r()*(V.dmg[1]-V.dmg[0]+1))+(crit?V.critDmg:0):0; return {hit,crit,dmg}; }

// Dijkstra in effective metres; a small binary heap keeps it quick on 1 m cells
function reach(w,u,occupied,budget){ budget=budget||2*V.move; const cost=new Map([[u.c,0]]), prev=new Map(), h=[[0,u.c]];
  const push=x=>{ h.push(x); let i=h.length-1; while(i){ const p=(i-1)>>1; if(h[p][0]<=h[i][0]) break; [h[p],h[i]]=[h[i],h[p]]; i=p; } };
  const pop=()=>{ const top=h[0], last=h.pop(); if(h.length){ h[0]=last; let i=0; for(;;){ const l=2*i+1, r2=l+1; let s=i; if(l<h.length&&h[l][0]<h[s][0]) s=l; if(r2<h.length&&h[r2][0]<h[s][0]) s=r2; if(s===i) break; [h[s],h[i]]=[h[i],h[s]]; i=s; } } return top; };
  while(h.length){ const [g,n]=pop(); if(g>cost.get(n)) continue;
    for(const [m,k] of w.neighbours(n)){ if(occupied&&occupied.has(m)) continue; const c=g+k; if(c>budget+1e-6) continue; if(!cost.has(m)||c<cost.get(m)-1e-9){ cost.set(m,c); prev.set(m,n); push([c,m]); } } }
  return {cost,prev}; }
const pathTo=(r,c)=>{ const out=[]; for(let n=c;n!==undefined;n=r.prev.get(n)) out.push(n); return out.reverse(); };

// an unaware raider's eyes: a cone ahead and a little all round, stopped by walls
function sees(w,r,c){ const d=dist(w,r.c,c); if(d>V.sight) return false; let a=Math.atan2(w.cx(c)-w.cx(r.c),w.cz(c)-w.cz(r.c))-r.face; a=Math.atan2(Math.sin(a),Math.cos(a));
  return (d<V.around||Math.abs(a)<V.cone)&&w.sight(r.c,c); }
function spots(w,s,c){ return dist(w,s.c,c)<=V.spot&&!!lineOfFire(w,s.c,c,{shot:false}); }

// One decision for a unit on the AI side. Returns {type:'shoot',target,odds} | {type:'move',cell,path} | {type:'overwatch'}.
// Shoot when the odds are fair (40%+) and either we're in cover or this is the last action; otherwise move to the cell
// that scores best on cover against every foe, a line of fire, and not drifting away.
function decide(w,u,units,r,opt={}){ const foes=units.filter(f=>f.alive&&f.team!==u.team); if(!foes.length) return {type:'overwatch'};
  let best=null; for(const f of foes){ if(!lineOfFire(w,u.c,f.c)) continue; const o=odds(w,u,f); if(!best||o.aim>best.odds.aim) best={target:f,odds:o}; }
  const myCover=Math.min(...foes.map(f=>w.coverFrom(u.c,w.cx(f.c),w.cz(f.c))));
  if(!opt.scramble&&best&&best.odds.aim>=40&&(myCover>0||u.ap===1)) return {type:'shoot',target:best.target,odds:best.odds};
  const occ=new Set(units.filter(x=>x.alive&&x!==u).map(x=>x.c)), rr=reach(w,u,occ,V.move);
  let pick=null, ps=-1e9;
  for(const [c,g] of rr.cost){ if(c===u.c) continue; let s=0, line=false;
    for(const f of foes){ const cv=w.coverFrom(c,w.cx(f.c),w.cz(f.c)); s+=cv===2?30:cv===1?15:-25; if(!line&&dist(w,c,f.c)<V.spot&&w.sight(c,f.c)) line=true; }
    s+=(line?20:-10)-Math.min(...foes.map(f=>dist(w,c,f.c)))*.25+r()*6; if(s>ps){ ps=s; pick=c; } }
  if(pick===null) return best&&best.odds.aim>=25?{type:'shoot',target:best.target,odds:best.odds}:{type:'overwatch'};
  return {type:'move',cell:pick,path:pathTo(rr,pick)}; }

// A whole fight with no rendering: both sides use decide(). Moves are instant and overwatch fires at the end of a move.
// Used by the tests to show a seeded fight replays exactly; also a quick balance probe.
function simulate(w,units,seed,maxRounds){ const r=rng(seed), log=[]; maxRounds=maxRounds||30; let minutes=0;
  const alive=t=>units.some(u=>u.alive&&u.team===t);
  const fire=(a,b,o)=>{ const res=roll(o,r); if(res.hit){ b.hp-=res.dmg; if(b.hp<=0){ b.hp=0; b.alive=false; b.ow=false; } } log.push(`${a.id}>${b.id} ${o.aim}% ${res.hit?(res.crit?'crit ':'')+res.dmg:'miss'}`); };
  for(let round=1;round<=maxRounds;round++){
    for(const team of ['squad','raider']){
      for(const u of units.filter(x=>x.alive&&x.team===team)){ u.ap=2; u.ow=false; u.hunker=false; u.unaware=false;
        while(u.ap>0&&u.alive&&alive(team==='squad'?'raider':'squad')){ const a=decide(w,u,units,r);
          if(a.type==='shoot'){ fire(u,a.target,a.odds); u.ap=0; }
          else if(a.type==='move'){ u.c=a.cell; u.ap--; log.push(`${u.id}->${a.cell}`);
            for(const o of units) if(o.alive&&o.ow&&o.team!==team&&lineOfFire(w,o.c,u.c)){ o.ow=false; fire(o,u,odds(w,o,u,{reaction:true})); if(!u.alive) break; } }
          else { u.ow=true; u.ap=0; } }
        minutes+=V.minutesPerTurn; }
      if(!alive('squad')||!alive('raider')) return {winner:alive('squad')?'squad':'raider',rounds:round,minutes,log}; } }
  return {winner:null,rounds:maxRounds,minutes,log}; }

return {V,rng,hash32,dist,peeks,lineOfFire,odds,roll,reach,pathTo,sees,spots,decide,simulate};
});
