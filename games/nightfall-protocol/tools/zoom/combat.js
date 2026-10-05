// ---------- combat layer (demonstration): one raider camp under the New River bridge ----------
// Exploring is real time. Whoever sees the other first decides how the fight opens: the squad gets a first strike
// (a free shot each before the raiders react), or the raiders get to scramble into cover. Then it is turn based on
// the same 2 m movement grid: two actions a soldier, terrain speed sets how far an action goes, cover comes from what
// is really there (walls, buildings and bridge piers are full cover; saguaros, palo verdes and boulders half).
const CB=(()=>{
  const stageEl=document.getElementById('stage');
  const css=document.createElement('style'); css.textContent=`
  .cb-banner{position:absolute;left:50%;top:44px;transform:translateX(-50%);background:rgba(24,24,26,.9);border:1px solid #c23b2e;color:#f1eee8;padding:8px 12px;border-radius:5px;font:14px var(--body);text-align:center;max-width:min(520px,90%);z-index:3}
  .cb-banner b{display:block;font:600 16px var(--body);margin-bottom:3px}.cb-banner.ours{border-color:#e0a526}
  .cb-banner button,.cb-bar button{background:#2d2f33;border:1px solid #38393d;color:#e2e0dc;font:600 13px var(--body);padding:5px 10px;margin:6px 3px 0;cursor:pointer;border-radius:3px}
  .cb-banner button.pri,.cb-bar button.pri{background:#e0a526;color:#211b10;border-color:#e0a526}
  .cb-bar{position:absolute;left:50%;bottom:40px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:4px;z-index:3;max-width:96%}
  .cb-units{display:flex;gap:5px;flex-wrap:wrap;justify-content:center}
  .cb-unit{background:rgba(24,24,26,.88);border:1px solid #38393d;color:#e2e0dc;font:12px var(--mono);padding:4px 7px;border-radius:4px;cursor:pointer;min-width:84px;text-align:left}
  .cb-unit[aria-pressed="true"]{border-color:#e0a526}.cb-unit.dead{opacity:.4;cursor:default}
  .cb-unit i{display:block;height:4px;background:#3a3b3f;margin-top:3px}.cb-unit i s{display:block;height:100%;background:#3fae7f}
  .cb-acts{display:flex;flex-wrap:wrap;justify-content:center;background:rgba(24,24,26,.85);border-radius:5px;padding:0 6px 6px}
  .cb-pop{position:absolute;left:0;top:0;font:700 15px var(--mono);color:#fff;text-shadow:0 1px 3px #000;pointer-events:none;transform:translate(-50%,-100%);z-index:2}
  .cb-pop.miss{color:#d9d4c8}.cb-pop.crit{color:#ffcf5a}`;
  document.head.appendChild(css);
  const banner=document.createElement('div'); banner.className='cb-banner'; banner.hidden=true; stageEl.appendChild(banner);
  const bar=document.createElement('div'); bar.className='cb-bar'; bar.hidden=true; bar.innerHTML='<div class="cb-units"></div><div class="cb-acts"></div>'; stageEl.appendChild(bar);
  const unitsEl=bar.firstChild, actsEl=bar.lastChild;
  const C={active:false, turn:'squad', units:[], sel:null, mode:'move', busy:false, round:1, prompt:false, slow:1, camGoal:null};
  const NAMES=['Rosa','Dev','Malik','June','Tomas','Ana'], RAIDERS=['Raider','Raider','Raider boss'];
  const INKS={selected:0xe0a526,calm:0x1d1814,overwatch:0x2f9fc4,concealed:0x5b6fa8,wounded:0xc23b2e,raider:0x6e1a10,dead:0x77726a};
  let pod=null;   // the camp: built once its sector is loaded
  // ---------- geometry of the fight ----------
  const BLOCKING=new Set([NK.building,NK.wall,NK.pier,NK.steep,NK.car]);   // wrecked cars are full cover
  const plantCover=new Map();   // cell -> 1 for saguaros, palo verdes and boulders
  C.onBuilt=s=>{ for(const p of s.data.plants){ if(p[0]===0||p[0]===1||(p[0]===3&&p[4]>.8)){ const c=cellOf(p[1],p[3]); if(c>=0) plantCover.set(c,1); } } };
  C.onDropped=s=>{ for(const p of s.data.plants){ const c=cellOf(p[1],p[3]); plantCover.delete(c); } };
  const cx=c=>BX0+(c%GN+.5)*NS, cz=c=>BZ0+(Math.floor(c/GN)+.5)*NS;
  const coverVal=c=>c<0||kindG[c]===255?0:BLOCKING.has(kindG[c])?2:plantCover.get(c)||0;
  function coverFrom(c,sx,sz){ const x=cx(c), z=cz(c), dx=sx-x, dz=sz-z, i=c%GN, j=Math.floor(c/GN), out=[];
    const di=Math.abs(dx)>1.2?Math.sign(dx):0, dj=Math.abs(dz)>1.2?Math.sign(dz):0;
    if(di) out.push(j*GN+i+di); if(dj) out.push((j+dj)*GN+i); if(di&&dj) out.push((j+dj)*GN+i+di);
    let v=0; for(const n of out) v=Math.max(v,coverVal(n)); return v; }
  function los(ax,az,bx,bz){ const ya=heightAt(ax,az)+1.5, yb=heightAt(bx,bz)+1.5, L=Math.hypot(bx-ax,bz-az), n=Math.ceil(L/.8);
    for(let q=1;q<n;q++){ const t=q/n, x=ax+(bx-ax)*t, z=az+(bz-az)*t, c=cellOf(x,z); if(c<0||kindG[c]===255) return false; if(kindG[c]===NK.building||kindG[c]===NK.wall||kindG[c]===NK.pier) return false; if(heightAt(x,z)>ya+(yb-ya)*t-.2) return false; } return true; }
  const occupied=except=>new Set(C.units.filter(u=>u.alive&&u!==except).map(u=>u.cell));
  // how far one unit can go: two actions of 12 "effective metres" each, so brush and slopes shorten the reach
  function reach(u){ const occ=occupied(u), cost=new Map([[u.cell,0]]), prev=new Map(), open=[[0,u.cell]];
    while(open.length){ open.sort((a,b)=>a[0]-b[0]); const [g,n]=open.shift(); if(g>cost.get(n)) continue; const i=n%GN, j=Math.floor(n/GN), sa=Math.max(nodeSpeed(n),.1);
      for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ if(!di&&!dj) continue; const m=(j+dj)*GN+i+di; if(occ.has(m)) continue; const sb=nodeSpeed(m); if(sb<=0) continue; if(di&&dj&&(nodeSpeed(j*GN+i+di)<=0||nodeSpeed((j+dj)*GN+i)<=0)) continue;
        const c=g+Math.hypot(di,dj)*NS/((sa+sb)/2); if(c>24.01) continue; if(!cost.has(m)||c<cost.get(m)){ cost.set(m,c); prev.set(m,n); open.push([c,m]); } } }
    return {cost,prev}; }
  const pathTo=(r,c)=>{ const out=[]; for(let n=c;n!==undefined;n=r.prev.get(n)) out.push(n); return out.reverse(); };
  // ---------- odds ----------
  function odds(a,b,{reaction=false,free=false}={}){ const d=Math.hypot(b.x-a.x,b.z-a.z), cv=b.unaware?0:coverFrom(b.cell,a.x,a.z), hunk=b.hunker&&cv?20:0, high=heightAt(a.x,a.z)-heightAt(b.x,b.z)>2?15:0;
    let aim=(a.team==='squad'?72:60)-(cv===2?40:cv===1?20:0)-hunk+high-(d>24?Math.min(40,(d-24)*1.5):0)+(d<8?10:0)-(reaction?15:0)+(free?10:0);
    aim=Math.max(5,Math.min(95,Math.round(aim))); return {aim,crit:cv===0?40:10,cover:cv,flanked:cv===0,d}; }
  // ---------- figures and their states ----------
  function makeRaider(i,x,z){ const fem=i===1, f=FigureKit.figure(fem,FigureKit.genFace(4000+i*13,fem)); f.j=Object.assign({},FigureKit.POSES.stand); f.root.traverse(o=>{ if(o.isMesh) o.castShadow=true; });
    f.ink=FigureKit.inkUp(f.root,{persp:true,width:.0016,color:INKS.raider}); armed(f,i===2?'pistol':'rifle'); scene.add(f.root);
    const c=cellOf(x,z); return {team:'raider',fig:f,name:RAIDERS[i]||'Raider',hp:i===2?6:4,max:i===2?6:4,ap:0,alive:true,x,z,cell:c,face:Math.random()*TAU,unaware:true,look:Math.random()*TAU,lookT:0}; }
  // weapons and the hands on them come from the motion module: bolt-action rifles, a pistol for the raider boss
  function armed(f,kind='rifle'){ if(f.gun) return; f.gun=Motion.arm(f,kind,{ink:{persp:true,width:.0016}}); }
  function ink(u){ if(!u.fig.ink) return; const k=!u.alive?'dead':u.team==='raider'?'raider':u.ow?'overwatch':u.hp<=u.max/2?'wounded':C.sel===u?'selected':'calm'; u.fig.ink.color.setHex(INKS[k]); }
  C.concealedInk=()=>{ figs.forEach((f,i)=>{ if(f.ink) f.ink.color.setHex(i===0?INKS.selected:INKS.concealed); armed(f); }); };
  // ---------- the camp ----------
  function placePod(){ if(pod||!IDX.camps.length) return; const cp=IDX.camps.find(q=>/New River/.test(IDX.bridges[q.bridge].name))||IDX.camps[0], b=IDX.bridges[cp.bridge]; if(!b) return; const s=sectors.get(key(...b.sec)); if(!s||s.state!=='built') return;
    const k=cp.k, [nx,nz]=b.nrm(k), x0=b.d[k][0]+nx*b.hw*.35+nx*2.6, z0=b.d[k][1]+nz*b.hw*.35+nz*2.6;   // round the fire ring
    pod={x:x0,z:z0,units:[]}; C.pod=pod; [[1.6,.3],[-1.2,1.4],[.2,-1.8]].forEach(([ox,oz],i)=>{ let c=cellOf(x0+ox,z0+oz); if(nodeSpeed(c)<=0) c=nearestPassable(c); const r=makeRaider(i,cx(c),cz(c)); r.cell=c; pod.units.push(r); }); }
  // a fan on the ground for each raider's eyes while they don't know you are there
  const coneG=new THREE.CircleGeometry(16,18,-Math.PI*.36,Math.PI*.72); coneG.rotateX(-Math.PI/2); coneG.rotateY(Math.PI/2);
  const coneM=new THREE.MeshBasicMaterial({color:0xc23b2e,transparent:true,opacity:.18,depthWrite:false,side:THREE.DoubleSide});
  function sees(r,x,z){ const d=Math.hypot(x-r.x,z-r.z); if(d>16) return false; let a=Math.atan2(x-r.x,z-r.z)-r.face; a=Math.atan2(Math.sin(a),Math.cos(a)); return (d<5||Math.abs(a)<Math.PI*.36)&&los(r.x,r.z,x,z); }
  // ---------- popups and tracers ----------
  const pops=[], tracers=[];
  function pop(x,y,z,text,cls){ const el=document.createElement('div'); el.className='cb-pop '+(cls||''); el.textContent=text; stageEl.appendChild(el); pops.push({el,x,y,z,t:0}); }
  function tracer(a,b,hit){ const g=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a.x,heightAt(a.x,a.z)+1.35,a.z),new THREE.Vector3(b.x+(hit?0:(Math.random()-.5)*2.5),heightAt(b.x,b.z)+(hit?1.2:1.8),b.z+(hit?0:(Math.random()-.5)*2.5))]);
    const l=new THREE.Line(g,new THREE.LineBasicMaterial({color:0xffe3a0,transparent:true})); scene.add(l); tracers.push({l,t:0}); }
  // ---------- timing: actions are promises resolved by the frame loop ----------
  const waits=[]; const wait=ms=>new Promise(r=>waits.push({t:ms,r}));
  function moveUnit(u,cells){ return new Promise(res=>{ u.route=cells.map(c=>({x:cx(c),z:cz(c),c})); u.rk=1; u.done=res; }); }
  async function shoot(a,b,opt={}){ const o=odds(a,b,opt); a.face=Math.atan2(b.x-a.x,b.z-a.z); a.aiming=true; await wait(380);
    const hit=Math.random()*100<o.aim, crit=hit&&Math.random()*100<o.crit, dmg=hit?(3+Math.floor(Math.random()*3)+(crit?2:0)):0;
    tracer(a,b,hit); if(hit) Motion.kick(b.fig,'hit',1,{from:{x:a.x,z:a.z}}); Motion.kick(a.fig,'recoil');
    pop(b.x,heightAt(b.x,b.z)+2.3,b.z,hit?(crit?`CRIT −${dmg}`:`−${dmg}`):'Miss',hit?(crit?'crit':''):'miss');
    if(hit){ b.hp-=dmg; if(b.hp<=0){ b.hp=0; b.alive=false; b.ow=false; } } b.unaware=false; ink(b);
    await wait(450); a.aiming=false; drawBar(); return hit; }
  // overwatch: a reaction shot at -15 when an enemy moves into sight
  async function overwatchCheck(mover){ for(const w of C.units){ if(!w.alive||!w.ow||w.team===mover.team||!mover.alive) continue; if(Math.hypot(w.x-mover.x,w.z-mover.z)>28||!los(w.x,w.z,mover.x,mover.z)) continue;
      w.ow=false; ink(w); say(`${w.name} takes an overwatch shot`); mover.paused=true; await shoot(w,mover,{reaction:true}); mover.paused=false; } }
  // ---------- starting and ending ----------
  C.start=async(first)=>{ C.active=true; C.prompt=false; banner.hidden=true; C.slow=1; squad.path=null; follow=false;
    C.units=figs.map((f,i)=>{ let c=cellOf(f.x,f.z); if(nodeSpeed(c)<=0) c=nearestPassable(c); return {team:'squad',fig:f,name:NAMES[i%NAMES.length],hp:6,max:6,ap:2,alive:true,x:cx(c),z:cz(c),cell:c,face:f.root.rotation.y,free:first==='squad'}; });
    for(const r of pod.units){ r.unaware=first==='squad'; C.units.push(r); }
    const occ=new Set(); for(const u of C.units){ if(occ.has(u.cell)){ u.cell=nearestFree(u.cell,occ); u.x=cx(u.cell); u.z=cz(u.cell); } occ.add(u.cell); }
    C.round=1; C.free=first==='squad'; C.units.forEach(ink);
    if(first==='squad'){ flash('First strike','The raiders haven\'t seen you. Every soldier gets one free shot (+10 aim, no cover for them) before they react.',true); }
    else { flash('Spotted','The raiders saw you first and scramble for cover.',false); C.turn='raider'; await wait(900); for(const r of C.units.filter(u=>u.team==='raider'&&u.alive)){ r.ap=1; await raiderAct(r,true); } }
    beginSquadTurn(); };
  function nearestFree(c,occ){ const i0=c%GN, j0=Math.floor(c/GN); for(let r=1;r<8;r++) for(let dj=-r;dj<=r;dj++) for(let di=-r;di<=r;di++){ const m=(j0+dj)*GN+i0+di; if(!occ.has(m)&&nodeSpeed(m)>0) return m; } return c; }
  function flash(title,text,ours){ banner.className='cb-banner'+(ours?' ours':''); banner.innerHTML=`<b>${title}</b>${text}`; banner.hidden=false; clearTimeout(flash.t); flash.t=setTimeout(()=>{ if(!C.prompt) banner.hidden=true; },3600); }
  function beginSquadTurn(){ C.turn='squad'; for(const u of C.units) if(u.team==='squad'&&u.alive){ u.ap=2; u.hunker=false; } select(C.units.find(u=>u.team==='squad'&&u.alive)); if(!C.free) flash(`Turn ${C.round}`,'Your squad',true); }
  function end(won){ C.active=false; bar.hidden=true; clearOverlay(); C.units.forEach(u=>{ u.ow=false; u.hunker=false; });
    const alive=C.units.filter(u=>u.team==='squad'&&u.alive);
    if(won){ flash('Area clear','The camp under the bridge is yours. The squad goes back to moving freely.',true);
      // the fallen stay where they fell; the living carry on as the squad
      const keep=figs.filter(f=>alive.some(u=>u.fig===f)); figs.length=0; figs.push(...keep); const L=alive[0]; Object.assign(squad,{x:L.x,z:L.z,l:0,path:null,trail:[{x:L.x,z:L.z,l:0}]}); figs.forEach((f,i)=>{ f.x=alive[i].x; f.z=alive[i].z; if(f.ink) f.ink.color.setHex(i===0?INKS.selected:INKS.calm); }); follow=true; squadInfo&&(squadInfo.people=figs.length); }
    else { flash('Squad lost','Nobody walks away from the bridge. Zoom out to the map.',false); figs.length=0; squadInfo&&(squadInfo.people=0); } }
  const check=()=>{ const s=C.units.some(u=>u.team==='squad'&&u.alive), r=C.units.some(u=>u.team==='raider'&&u.alive); if(!r){ end(true); return true; } if(!s){ end(false); return true; } return false; };
  // ---------- the player's turn ----------
  let R=null, ovl=null; const ovlG=new THREE.PlaneGeometry(1.7,1.7); ovlG.rotateX(-Math.PI/2);
  function clearOverlay(){ if(ovl){ scene.remove(ovl); ovl.dispose&&ovl.dispose(); ovl=null; } }
  function drawOverlay(){ clearOverlay(); const u=C.sel; if(!u||C.turn!=='squad'||!u.ap) { R=null; return; } R=reach(u); const lim=u.ap>=2?24:12, cells=[...R.cost].filter(([c,g])=>g<=lim&&c!==u.cell);
    ovl=new THREE.InstancedMesh(ovlG,new THREE.MeshBasicMaterial({transparent:true,opacity:.42,depthWrite:false}),Math.max(1,cells.length)); const col=new THREE.Color();
    cells.forEach(([c,g],i)=>{ ovl.setMatrixAt(i,mtx(cx(c),heightAt(cx(c),cz(c))+.12,cz(c))); ovl.setColorAt(i,col.setHex(g<=12?0x3f8fd1:0xe0a526)); }); ovl.count=cells.length; ovl.frustumCulled=false; ovl.renderOrder=4; scene.add(ovl); }
  function select(u){ if(!u) return; C.sel=u; C.mode='move'; C.units.forEach(ink); C.camGoal={x:u.x,z:u.z}; drawOverlay(); drawBar(); }
  function drawBar(){ if(!C.active){ bar.hidden=true; return; } bar.hidden=false;
    unitsEl.innerHTML=C.units.filter(u=>u.team==='squad').map((u,i)=>`<button type="button" class="cb-unit${u.alive?'':' dead'}" data-i="${C.units.indexOf(u)}" aria-pressed="${C.sel===u}">${u.name} · ${u.alive?'●'.repeat(u.ap)+'○'.repeat(2-u.ap):'down'}${u.ow?' · OW':''}${u.hunker?' · HUNK':''}<i><s style="width:${u.hp/u.max*100}%;background:${u.hp<=u.max/2?'#c23b2e':'#3fae7f'}"></s></i></button>`).join('')+
      C.units.filter(u=>u.team==='raider').map(u=>`<span class="cb-unit${u.alive?'':' dead'}" style="border-color:#6e1a10">${u.name}${u.alive?'':' · down'}<i><s style="width:${u.hp/u.max*100}%;background:#c23b2e"></s></i></span>`).join('');
    const u=C.sel, mine=C.turn==='squad'&&!C.busy&&u&&u.alive&&u.ap>0;
    if(C.mode==='shoot'&&mine){ const ts=C.units.filter(t=>t.team==='raider'&&t.alive&&los(u.x,u.z,t.x,t.z)&&Math.hypot(t.x-u.x,t.z-u.z)<45);
      actsEl.innerHTML=(ts.length?ts.map(t=>{ const o=odds(u,t,{free:u.free}); return `<button type="button" class="pri" data-t="${C.units.indexOf(t)}">${t.name}: ${o.aim}%${o.flanked?' · flanked':o.cover===2?' · full cover':' · half cover'}</button>`; }).join(''):'<span style="color:#98968f;font:12px var(--mono);padding:8px">No raider in sight from here</span>')+'<button type="button" data-a="back">Back</button>'; }
    else actsEl.innerHTML=C.turn!=='squad'?'<span style="color:#e2b0a8;font:600 13px var(--body);padding:8px">Raiders\' turn…</span>':
      `<button type="button" data-a="shoot" ${mine?'':'disabled'} class="pri">${u&&u.free?'Free shot':'Shoot'} [1]</button><button type="button" data-a="ow" ${mine?'':'disabled'}>Overwatch [2]</button><button type="button" data-a="hunker" ${mine?'':'disabled'}>Hunker [3]</button><button type="button" data-a="end" ${C.busy?'disabled':''}>End turn [⌫]</button>`; }
  bar.addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b||b.disabled) return;
    if(b.dataset.i!==undefined){ const u=C.units[+b.dataset.i]; if(u.alive&&C.turn==='squad'&&!C.busy) select(u); return; }
    if(b.dataset.t!==undefined){ fire(C.units[+b.dataset.t]); return; } act(b.dataset.a); });
  async function fire(t){ const u=C.sel; C.busy=true; clearOverlay(); C.camGoal={x:(u.x+t.x)/2,z:(u.z+t.z)/2}; const free=u.free; await shoot(u,t,{free}); if(free){ u.free=false; } else u.ap=0; C.busy=false; C.mode='move'; if(check()) return; afterAction(u); }
  function act(a){ const u=C.sel; if(!u) return;
    if(a==='shoot'){ C.mode='shoot'; drawBar(); return; } if(a==='back'){ C.mode='move'; drawBar(); return; }
    if(a==='ow'){ u.ow=true; u.ap=0; ink(u); say(`${u.name} is on overwatch`); afterAction(u); return; }
    if(a==='hunker'){ u.hunker=true; u.ap=0; say(`${u.name} hunkers down: cover counts double`); afterAction(u); return; }
    if(a==='end'){ for(const v of C.units) if(v.team==='squad') { v.ap=0; v.free=false; } enemyTurn(); } }
  function afterAction(u){ C.free=C.units.some(v=>v.free&&v.alive); if(u.ap>0||u.free){ select(u); return; } const next=C.units.find(v=>v.team==='squad'&&v.alive&&(v.ap>0||v.free)); if(next) select(next); else enemyTurn(); }
  C.click=async h=>{ if(C.prompt||!C.active||C.turn!=='squad'||C.busy||!C.sel||!R) return; const c=cellOf(h.p.x,h.p.z), g=R.cost.get(c); const u=C.sel;
    if(g===undefined||c===u.cell||g>(u.ap>=2?24:12)){ say('Out of reach this turn'); return; }
    C.busy=true; clearOverlay(); u.ap-=g<=12?1:2; u.free=u.free&&u.ap>0; u.ow=false; u.hunker=false; await moveUnit(u,pathTo(R,c)); C.busy=false; if(check()) return; afterAction(u); };
  C.hover=h=>{ if(!C.active||C.turn!=='squad'||!h||!R) return ''; const c=cellOf(h.p.x,h.p.z); if(!R.cost.has(c)) return ''; const foes=C.units.filter(t=>t.team==='raider'&&t.alive);
    const cv=foes.map(t=>coverFrom(c,t.x,t.z)); return `Cover here: ${cv.filter(v=>v===2).length} full · ${cv.filter(v=>v===1).length} half · flanked by ${cv.filter(v=>v===0).length} · ${R.cost.get(c)<=12?'1 action':'dash, 2 actions'}`; };
  addEventListener('keydown',e=>{ if(!C.active||C.turn!=='squad'||C.busy) return; if(e.key==='1') act('shoot'); else if(e.key==='2') act('ow'); else if(e.key==='3') act('hunker'); else if(e.key==='Backspace'){ e.preventDefault(); act('end'); }
    else if(e.key==='Tab'){ e.preventDefault(); const sq=C.units.filter(u=>u.team==='squad'&&u.alive); select(sq[(sq.indexOf(C.sel)+1)%sq.length]); } else if(e.key==='Escape'){ C.mode='move'; drawBar(); } });
  // ---------- the raiders' turn ----------
  async function enemyTurn(){ C.turn='raider'; C.busy=true; clearOverlay(); C.free=false; drawBar(); flash(`Turn ${C.round}`,'Raiders',false); await wait(700);
    for(const r of C.units.filter(u=>u.team==='raider'&&u.alive)){ r.ap=2; r.unaware=false; r.hunker=false; await raiderAct(r,false); if(check()){ C.busy=false; return; } }
    C.round++; C.busy=false; beginSquadTurn(); }
  // move somewhere with cover against the squad and a shot if possible; shoot when the odds are fair, else overwatch
  async function raiderAct(r,scramble){ const foes=()=>C.units.filter(u=>u.team==='squad'&&u.alive);
    const best=()=>{ let b=null; for(const f of foes()){ if(!los(r.x,r.z,f.x,f.z)) continue; const o=odds(r,f); if(!b||o.aim>b.o.aim) b={f,o}; } return b; };
    C.camGoal={x:r.x,z:r.z};
    while(r.ap>0&&r.alive&&foes().length){ const shot=best(), myCover=Math.min(...foes().map(f=>coverFrom(r.cell,f.x,f.z)));
      if(!scramble&&shot&&shot.o.aim>=40&&(myCover>0||r.ap===1)){ C.camGoal={x:(r.x+shot.f.x)/2,z:(r.z+shot.f.z)/2}; await shoot(r,shot.f); r.ap=0; break; }
      const rr=reach(r); let pick=null, ps=-1e9;
      for(const [c,g] of rr.cost){ if(g>12||c===r.cell) continue; const x=cx(c), z=cz(c); let s=0, sight=false;
        for(const f of foes()){ const cv=coverFrom(c,f.x,f.z); s+=cv===2?30:cv===1?15:-25; if(!sight&&Math.hypot(f.x-x,f.z-z)<30&&los(x,z,f.x,f.z)) sight=true; }
        s+=(sight?20:-10)-Math.min(...foes().map(f=>Math.hypot(f.x-x,f.z-z)))*.25+Math.random()*6; if(s>ps){ ps=s; pick=c; } }
      if(pick===null) break; r.ap--; await moveUnit(r,pathTo(rr,pick)); if(scramble) break; }
    if(r.alive&&r.ap>0){ r.ow=true; r.ap=0; say(`${r.name} watches the open ground`); } }
  // ---------- per frame: exploration detection, animation of everyone in a fight ----------
  let detT=0;
  C.frame=(dt,now)=>{ placePod(); if(!pod) return;
    const sdt=dt*C.slow;
    // pops and tracers
    for(const p of pops){ p.t+=dt; tmp.set(p.x,p.y+p.t*1.2,p.z).project(cam); p.el.style.left=((tmp.x+1)/2*W)+'px'; p.el.style.top=((1-tmp.y)/2*H)+'px'; p.el.style.opacity=String(Math.max(0,1-p.t/1.6)); }
    for(let i=pops.length-1;i>=0;i--) if(pops[i].t>1.6){ pops[i].el.remove(); pops.splice(i,1); }
    for(const t of tracers){ t.t+=dt; t.l.material.opacity=Math.max(0,1-t.t/.35); } for(let i=tracers.length-1;i>=0;i--) if(tracers[i].t>.35){ scene.remove(tracers[i].l); tracers[i].l.geometry.dispose(); tracers.splice(i,1); }
    for(let i=waits.length-1;i>=0;i--){ waits[i].t-=dt*1000; if(waits[i].t<=0){ waits[i].r(); waits.splice(i,1); } }
    // the raiders while nobody is fighting: look around the fire, and watch
    if(!C.active){ for(const r of pod.units){ if(!r.alive) continue; r.lookT-=sdt; if(r.lookT<=0){ r.look=Math.random()*TAU; r.lookT=3+Math.random()*4; } let a=r.look-r.face; a=Math.atan2(Math.sin(a),Math.cos(a)); r.face+=a*Math.min(1,sdt*1.2);
        if(!r.cone){ r.cone=new THREE.Mesh(coneG,coneM); r.cone.renderOrder=3; scene.add(r.cone); } r.cone.visible=figs.length>0&&Math.hypot(squad.x-r.x,squad.z-r.z)<80; r.cone.position.set(r.x,heightAt(r.x,r.z)+.2,r.z); r.cone.rotation.y=r.face; }
      if(figs.length&&!C.prompt&&(detT+=dt)>.2){ detT=0;
        if(pod.units.some(r=>r.alive&&figs.some(f=>sees(r,f.x,f.z)))){ C.start('raider'); }
        else if(!pod.declined&&pod.units.some(r=>r.alive&&figs.some(f=>Math.hypot(f.x-r.x,f.z-r.z)<30&&los(f.x,f.z,r.x,r.z)))){ C.prompt=true; C.slow=.15; squad.path=null;
          banner.className='cb-banner ours'; banner.innerHTML='<b>Contact</b>Three raiders round a fire under the bridge. They haven\'t seen you.<br><button type="button" class="pri" data-c="go">Engage: first strike</button><button type="button" data-c="no">Hold back</button>'; banner.hidden=false; } } }
    else for(const r of pod.units) if(r.cone) r.cone.visible=false;
    // everyone in the fight
    // in a fight everyone; otherwise the camp, and any of the squad who fell (so they finish falling)
    const list=C.active?C.units:[...pod.units,...C.units.filter(u=>u.team==='squad'&&!u.alive)];
    for(const u of list){ const f=u.fig;
      if(u.route&&!u.paused){ const p=u.route[u.rk], dx=p.x-u.x, dz=p.z-u.z, d=Math.hypot(dx,dz), st=4*dt;
        if(d<=st){ u.x=p.x; u.z=p.z; u.cell=p.c; u.rk++; if(u.rk>=u.route.length){ u.route=null; const res=u.done; u.done=null; res&&res(); } else overwatchCheck(u); } else { u.x+=dx/d*st; u.z+=dz/d*st; u.face=Math.atan2(dx,dz); }
        if(!u.alive){ u.route=null; const res=u.done; u.done=null; res&&res(); } }
      if(u.team==='squad'){ f.x=u.x; f.z=u.z; }
      let a=u.face-f.root.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); f.root.rotation.y+=a*Math.min(1,dt*9);
      const y=heightAt(u.x,u.z); f.y=f.y===undefined?y:f.y+(y-f.y)*Math.min(1,dt*12); f.root.position.set(u.x,f.y,u.z);
      // tactical moves are 4 m/s, shown as a run; wounds show in the gait and the idle as well as the ink
      const act=!u.alive?'dead':u.hunker?'hunker':(u.aiming||u.ow)?'aim':C.active?'ready':'idle';
      Motion.update(f,{act,mood:u.alive&&u.hp<=u.max/2?'wounded':'calm',ground:heightAt,compress:1.4},dt); }
    if(C.active&&C.camGoal){ target.x+=(C.camGoal.x-target.x)*Math.min(1,dt*2.5); target.z+=(C.camGoal.z-target.z)*Math.min(1,dt*2.5); target.y+=(heightAt(target.x,target.z)-target.y)*Math.min(1,dt*3); if(C.sel&&!C.busy&&C.turn==='squad') C.camGoal={x:C.sel.x,z:C.sel.z}; }
  };
  banner.addEventListener('click',e=>{ const b=e.target.closest('button[data-c]'); if(!b) return; if(b.dataset.c==='go') C.start('squad'); else { pod.declined=true; C.prompt=false; C.slow=1; banner.hidden=true; say('Holding back. Keep out of their sight lines.'); } });
  C.los=los; C.sees=sees; return C; })();
