// ---------- the debug copy: see everything, switch the hard parts off ----------
// Loaded only into mockups/combat-interior-debug.html (build.py sets window.COMBAT_DEBUG first). The page's DBG
// switches are read by the fight code; this file draws the panel, the lines of fire and the cursor readout.
(()=>{
const C=window.__combat, S=C.S, D=C.DBG, CR=C.CR; if(!D) return;
const box=document.createElement('div'); box.className='dbg'; box.innerHTML=`<b>Debug</b><span id="dbgState"></span>
  <label><input type="checkbox" data-k="reveal" checked> Show every raider</label>
  <label><input type="checkbox" data-k="cones" checked> Raiders' sight cones</label>
  <label><input type="checkbox" data-k="lines" checked> Lines of fire from the selected</label>
  <label><input type="checkbox" data-k="blind"> Raiders never spot the squad</label>
  <label><input type="checkbox" data-k="passive"> Raiders do nothing</label>
  <label><input type="checkbox" data-k="god"> Squad can't be hurt</label>
  <div class="row"><button type="button" data-a="fight">Start fight</button><button type="button" data-a="fast" aria-pressed="false">Fast ×4</button></div>
  <div class="row"><button type="button" data-a="refill">Refill ammo &amp; kit</button><button type="button" data-a="heal">Heal squad</button></div>
  <p>Alt+click: put the selected soldier there · K: kill the raider under the cursor · Space: Go</p><pre id="dbgCursor"></pre>`;
document.getElementById('stage').appendChild(box);
box.addEventListener('change',e=>{ const k=e.target.dataset.k; if(!k) return; D[k]=e.target.checked; if(k==='reveal'||k==='cones'){ C.updateVision(0); C.drawSight(); C.drawBar(); } });
box.addEventListener('click',e=>{ const b=e.target.closest('button[data-a]'); if(!b) return; const a=b.dataset.a;
  if(a==='fight'&&S.phase==='explore'){ S.prompt=false; S.busy=false; C.startFight('squad','Debug: the fight starts.'); }
  if(a==='fast'){ S.timeScale=S.timeScale>1?1:4; b.setAttribute('aria-pressed',S.timeScale>1); }
  if(a==='refill'){ for(const u of C.squad()){ u.ammo=u.weapon.ammo; const k=CR.ROLES[u.role].kit||{}; u.kit=Object.assign({},u.kit,k,{pipe:Math.max(u.kit.pipe||0,2),charge:Math.max(u.kit.charge||0,2),aid:Math.max(u.kit.aid||0,2)}); u.cooldown=0; } C.log('Debug: ammo and kit refilled.'); C.drawBar(); C.drawHud(); }
  if(a==='heal'){ for(const u of C.squad()){ if(u.dead) continue; u.hp=u.max; u.down=false; u.alive=true; u.stable=false; C.inkAll(); } C.log('Debug: the squad is healed.'); C.drawBar(); C.drawHud(); } });
// K: kill the raider under the cursor
let lastEv=null; const cv=renderer.domElement; cv.addEventListener('pointermove',e=>{ lastEv=e; });
addEventListener('keydown',e=>{ if((e.key==='k'||e.key==='K')&&lastEv&&e.target.tagName!=='INPUT'){ const r=C.pickUnit(lastEv,u=>u.team==='raider'&&u.alive); if(r){ C.harm(r,r.hp+(r.armor||0)+5,null); C.log(`Debug: ${r.name} killed.`); C.drawBar(); } } });
// lines of fire from the selected soldier (from where they will stand) to every raider: green with the odds, red none
const g=new THREE.Group(); scene.add(g); const mats={ok:new THREE.LineBasicMaterial({color:0x3fdc8f}),no:new THREE.LineDashedMaterial({color:0xc23b2e,dashSize:.3,gapSize:.2,transparent:true,opacity:.6})};
let tick=0;
function lines(){ while(g.children.length) g.children.pop().geometry.dispose(); const u=S.sel; if(!D.lines||!u||!u.alive||u.team!=='squad'||!S.w) return;
  const a=C.ghostAt(u), ya=C.yOf(a.x,a.z,u.lv||0)+1.4;
  for(const r of S.units){ if(r.team!=='raider'||!r.alive||r.fled) continue; const lf=CR.lineOfFire(S.w,a,r,{pierce:true}), yb=C.yU(r)+1.2;
    const geo=new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(a.x,ya,a.z),new THREE.Vector3(r.x,yb,r.z)]); const l=new THREE.Line(geo,lf?mats.ok:mats.no); if(!lf) l.computeLineDistances(); g.add(l); } }
function readout(){ const st=document.getElementById('dbgState'); st.textContent=` ${S.phase} · round ${S.round}${S.busy?' · busy':''}`;
  const out=document.getElementById('dbgCursor'); if(!lastEv||!S.w){ out.textContent=''; return; } const p=C.pointUnder(lastEv); if(!p){ out.textContent=''; return; }
  const W=C.wS(), rs=S.units.filter(r=>r.team==='raider'&&r.alive&&!r.fled), lv=S.sel&&S.sel.lv||0;
  const seers=rs.filter(r=>lv?false:CR.sees(S.w,r,p)).map(r=>r.name), cover=rs.map(r=>S.w.coverFrom(p,[r.x,r.z])), probe={x:p[0],z:p[1],lv,team:'squad'};
  out.textContent=`cursor ${p[0].toFixed(1)}, ${p[1].toFixed(1)} · ${lv?'roof':S.w.insideAt(...p)?'inside':'outside'} · ${W.clearAt(...p)?'clear':'blocked'}\n`+
    `raiders who would see you: ${seers.join(', ')||'none'}\ncover here: ${cover.filter(c=>c===2).length} full · ${cover.filter(c=>c===1).length} half · ${cover.filter(c=>c===0).length} flanked\n`+
    `lines from here to raiders: ${rs.filter(r=>CR.lineOfFire(S.w,probe,r)).length} of ${rs.length}`; }
(function loop(){ requestAnimationFrame(loop); if(++tick%12) return; lines(); readout(); })();
})();
