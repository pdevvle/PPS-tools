// ---------- Motion Lab: a loop over a ramp and stairs, and an obstacle course, all driven by Motion ----------
(function(){
const stage=document.getElementById('stage');
if(!window.THREE){ stage.insertAdjacentHTML('beforeend','<p class="fail">The 3D view needs three.js, which could not load.</p>'); return; }
const TAU=Math.PI*2, CZ=11;   // the course sits beside the loop, centred 11 m along z
// ---- ground: the loop's ramp, landing and stairs; the course's wall, tower and block ----
const RISE=.45, STEP=.075, TREAD=.3;
const WALL={x0:-3,x1:-2.75,z0:CZ-2,z1:CZ-.4,h:1.0}, TOWER={x0:1,x1:3,z0:CZ-2.2,z1:CZ-.2,h:2.1}, BLOCK={x0:0,x1:2,z0:CZ+.4,z1:CZ+2,h:1.4};
const inside=(b,x,z)=>x>=b.x0&&x<=b.x1&&z>=b.z0&&z<=b.z1;
function loopGround(x){ if(x<-3) return 0; if(x<0) return (x+3)/3*RISE; if(x<1.5) return RISE; const k=Math.floor((x-1.5)/TREAD)+1; return Math.max(0,RISE-STEP*k); }
function ground(x,z){ if(z<CZ-4) return Math.abs(z)<1.8?loopGround(x):0; for(const b of [WALL,TOWER,BLOCK]) if(inside(b,x,z)) return b.h; return 0; }
// ---- the loop: two straights across the profile joined by half circles ----
const HALF=5.5, RAD=1.1, LOOP=4*HALF+TAU*RAD;
function along(s){ s=((s%LOOP)+LOOP)%LOOP; const A=2*HALF, C=Math.PI*RAD;
  if(s<A) return {x:-HALF+s,z:-RAD,h:Math.PI/2};
  if((s-=A)<C){ const a=s/RAD; return {x:HALF+Math.sin(a)*RAD,z:-Math.cos(a)*RAD,h:Math.PI/2-a}; }
  if((s-=C)<A) return {x:HALF-s,z:RAD,h:-Math.PI/2};
  s-=A; const a=s/RAD; return {x:-HALF-Math.sin(a)*RAD,z:Math.cos(a)*RAD,h:-Math.PI/2-a}; }
function nearestS(x,z){ let best=0, bd=1e9; for(let i=0;i<400;i++){ const s=i/400*LOOP, q=along(s), d=(q.x-x)**2+(q.z-z)**2; if(d<bd){ bd=d; best=s; } } return best; }
// ---- scene ----
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true}); renderer.setPixelRatio(Math.min(2,devicePixelRatio||1)); renderer.setClearColor(0,0);
renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; stage.prepend(renderer.domElement);
const scene=new THREE.Scene(), cam=new THREE.PerspectiveCamera(30,1,.1,120);
scene.add(new THREE.HemisphereLight(0xfffaf0,0x8a8070,.35));
const sun=new THREE.DirectionalLight(0xfff3dc,.9); sun.castShadow=true; sun.shadow.mapSize.set(2048,2048);
Object.assign(sun.shadow.camera,{left:-9,right:9,top:7,bottom:-7,near:1,far:40}); sun.shadow.bias=-.0006; sun.shadow.normalBias=.02; scene.add(sun); scene.add(sun.target);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(80,60),new THREE.ShadowMaterial({opacity:.14})); floor.rotation.x=-Math.PI/2; floor.receiveShadow=true; floor.position.z=6; scene.add(floor);
const sand=new THREE.MeshToonMaterial({color:0xcdb48c}), stucco=new THREE.MeshToonMaterial({color:0xd8c7a8}), edgeM=new THREE.LineBasicMaterial({color:0x6d5f49}), steel=new THREE.MeshToonMaterial({color:0x5a5650});
const addMesh=(g,m)=>{ const o=new THREE.Mesh(g,m); o.receiveShadow=true; o.castShadow=true; scene.add(o); scene.add(new THREE.LineSegments(new THREE.EdgesGeometry(g,20),edgeM)); return o; };
{ const pts=[[-8,0],[-3,0],[0,RISE],[1.5,RISE]]; for(let k=1;k<=6;k++){ const x=1.5+(k-1)*TREAD; pts.push([x,RISE-STEP*(k-1)],[x,RISE-STEP*k]); pts.push([1.5+k*TREAD,RISE-STEP*k]); } pts.push([8,0],[8,-.05],[-8,-.05]);
  const sh=new THREE.Shape(); sh.moveTo(...pts[0]); for(const p of pts.slice(1)) sh.lineTo(...p);
  const g=new THREE.ExtrudeGeometry(sh,{depth:3.6,bevelEnabled:false}); g.translate(0,0,-1.8); addMesh(g,sand); }
for(const b of [WALL,TOWER,BLOCK]){ const g=new THREE.BoxGeometry(b.x1-b.x0,b.h,b.z1-b.z0); g.translate((b.x0+b.x1)/2,b.h/2,(b.z0+b.z1)/2); addMesh(g,stucco); }
{ const g=new THREE.BoxGeometry(16,.04,7); g.translate(0,-.02,CZ); addMesh(g,sand); }
// ladders: rails and rungs every 0.3 m against a face (x = the face, z = the ladder's centre, up to height h)
function ladder(x,z,h,side){ const gr=new THREE.Group(); for(const dz of [-.2,.2]){ const r=new THREE.Mesh(new THREE.BoxGeometry(.04,h+.9,.04),steel); r.position.set(x+side*.03,(h+.9)/2,z+dz); gr.add(r); }
  for(let y=.3;y<=h+.01;y+=.3){ const r=new THREE.Mesh(new THREE.CylinderGeometry(.015,.015,.4,6),steel); r.rotation.x=Math.PI/2; r.position.set(x+side*.03,y,z); gr.add(r); }
  gr.traverse(o=>{ if(o.isMesh) o.castShadow=true; }); scene.add(gr); }
ladder(TOWER.x0,CZ-1.2,TOWER.h,-1); ladder(BLOCK.x0,CZ+1.2,BLOCK.h,-1);
// ---- people ----
const INK={calm:0x1d1814,wounded:0xc23b2e,panicked:0x9b4fc4};
const crateG=new THREE.BoxGeometry(.42,.3,.32), crateM=new THREE.MeshToonMaterial({color:0x8a6a40});
function person(name,seed,fem){ const f=FigureKit.figure(fem,FigureKit.genFace(seed,fem)); f.seed=seed; f.root.traverse(o=>{ if(o.isMesh) o.castShadow=true; });
  const crate=new THREE.Mesh(crateG,crateM); crate.position.set(0,.16,.3); crate.castShadow=true; crate.visible=false; f.torso.add(crate);
  f.ink=FigureKit.inkUp(f.root,{persp:true,width:.0016,color:INK.calm}); scene.add(f.root); return {name,f,crate}; }
const loopers=['Rosa','Dev','Malik','June'].map((n,i)=>{ const P=person(n,950+i*7,i%2===1); P.s=i*LOOP/4; const q=along(P.s); P.f.root.position.set(q.x,ground(q.x,q.z),q.z); P.f.root.rotation.y=q.h; P.y=P.f.root.position.y; return P; });
const runners=[['Ana',1012,true],['Tomas',1019,false]].map(([n,s,fem],i)=>{ const P=person(n,s,fem); P.step=0; P.t=0; P.wait=i*9; P.f.root.position.set(-6,0,CZ-1.2); P.f.root.rotation.y=Math.PI/2; return P; });
// ---- the course: walk, turn, and the four traversals; the runners loop it ----
const H=Math.PI/2, ZA=CZ-1.2, ZB=CZ+1.2;
const COURSE=[
  {walk:[-3.4,ZA]}, {trav:{type:'vault',x:WALL.x0,z:ZA,yaw:H,height:WALL.h,depth:WALL.x1-WALL.x0}, say:'vaults the wall'},
  {walk:[TOWER.x0-.38,ZA]}, {trav:{type:'ladder',x:TOWER.x0,z:ZA,yaw:H,height:TOWER.h}, say:'climbs the ladder'},
  {walk:[TOWER.x1-.35,ZA]}, {trav:{type:'drop',x:TOWER.x1,z:ZA,yaw:H,height:TOWER.h,y:0}, say:'drops off the tower'},
  {walk:[6,ZA]}, {turn:0, say:'turns on the spot'}, {walk:[6,ZB]}, {turn:-H},
  {walk:[BLOCK.x1+.4,ZB]}, {trav:{type:'climb',x:BLOCK.x1,z:ZB,yaw:-H,height:BLOCK.h}, say:'climbs the ledge'},
  {walk:[BLOCK.x0+.5,ZB]}, {turn:H, say:'turns to the ladder'}, {trav:{type:'descend',x:BLOCK.x0,z:ZB,yaw:H,height:BLOCK.h}, say:'climbs down'},
  {turn:-H}, {walk:[-6,ZB]}, {turn:Math.PI}, {walk:[-6,ZA]}, {turn:H}];
function runCourse(P,dt,state){ const f=P.f, r=f.root; if(P.wait>0){ P.wait-=dt; P.doing='waits'; return; }
  const st=COURSE[P.step]; let done=false;
  if(st.walk){ const [x,z]=st.walk, dx=x-r.position.x, dz=z-r.position.z, d=Math.hypot(dx,dz), sp=Math.min(d,1.35*dt*ui.courseSpeed);
    if(d>.02){ r.position.x+=dx/d*sp; r.position.z+=dz/d*sp; } else done=true; r.position.y=ground(r.position.x,r.position.z); P.doing=P.doing||'walks'; }
  else if(st.turn!==undefined){ const a=((st.turn-r.rotation.y+Math.PI)%TAU+TAU)%TAU-Math.PI, m=Math.min(Math.abs(a),1.6*dt*ui.courseSpeed); r.rotation.y+=Math.sign(a)*m; if(Math.abs(a)<.01) done=Motion.busy(f)?false:true; }
  else if(st.trav){ if(!P.started){ P.started=true; Motion.traverse(f,Object.assign({},st.trav),state); } else if(!Motion.busy(f)){ done=true; P.started=false; } }
  if(st.say) P.doing=st.say; else if(st.walk) P.doing='walks';
  if(done){ P.step=(P.step+1)%COURSE.length; } }
// ---- controls ----
const ui={view:'loop', speed:1.4, act:'idle', mood:'calm', weapon:'mixed', fallen:false, courseSpeed:1};
const speedEl=document.getElementById('speed'), speedOut=document.getElementById('speedOut');
function setSpeed(v){ ui.speed=+v; speedEl.value=v; speedOut.textContent=ui.speed.toFixed(2)+' m/s'; document.querySelectorAll('#presets button').forEach(b=>b.setAttribute('aria-pressed',String(Math.abs(+b.dataset.v-ui.speed)<.01))); }
speedEl.addEventListener('input',()=>setSpeed(speedEl.value));
document.getElementById('presets').addEventListener('click',e=>{ const b=e.target.closest('button'); if(b) setSpeed(b.dataset.v); });
const seg=(id,key,attr,after)=>document.getElementById(id).addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b) return; ui[key]=b.dataset[attr];
  document.querySelectorAll('#'+id+' button').forEach(x=>x.setAttribute('aria-pressed',String(x===b))); after&&after(); });
seg('act','act','a'); seg('mood','mood','m',()=>[...loopers,...runners].forEach(p=>p.f.ink.color.setHex(INK[ui.mood])));
seg('weapon','weapon','w',arming); seg('view','view','v',()=>{ document.getElementById('loopCtl').disabled=ui.view!=='loop'; view.follow=null; cards.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed','false')); view.goal=ui.view==='loop'?LOOPV:COURSEV; });
function arming(){ const pick=i=>ui.weapon==='mixed'?(i%2?'pistol':'rifle'):ui.weapon==='none'?null:ui.weapon;
  loopers.forEach((p,i)=>Motion.arm(p.f,pick(i),{ink:{persp:true,width:.0016}})); runners.forEach((p,i)=>Motion.arm(p.f,pick(i),{ink:{persp:true,width:.0016}})); }
const later=[]; const after=(ms,fn)=>later.push({t:ms/1000,fn});
document.getElementById('hit').addEventListener('click',()=>loopers.forEach((p,i)=>after(i*140,()=>{ const r=p.f.root, a=r.rotation.y+(Math.random()-.5)*1.2; Motion.kick(p.f,'hit',1,{from:{x:r.position.x+Math.sin(a)*12,z:r.position.z+Math.cos(a)*12}}); })));
document.getElementById('fire').addEventListener('click',()=>loopers.forEach((p,i)=>after(i*110,()=>Motion.kick(p.f,'recoil'))));
const fallBtn=document.getElementById('fall');
fallBtn.addEventListener('click',()=>{ ui.fallen=!ui.fallen; fallBtn.textContent=ui.fallen?'Get up':'Fall';
  if(ui.fallen) loopers.forEach((p,i)=>{ const r=p.f.root, a=r.rotation.y+(i%2?.4:-.4); p.f.motion&&Motion.kick(p.f,'hit',1.1,{from:{x:r.position.x+Math.sin(a)*10,z:r.position.z+Math.cos(a)*10}}); p.down=true; });
  else loopers.forEach(p=>{ p.down=false; p.back=true; }); });
// orbit by dragging
const LOOPV={x:0,y:.7,z:0,dist:12.5}, COURSEV={x:0,y:1.1,z:CZ,dist:17};
const view={yaw:.55,pitch:.36,dist:12.5,x:0,y:.7,z:0,goal:LOOPV}; let drag=null;
stage.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,yaw:view.yaw,pitch:view.pitch}; stage.setPointerCapture(e.pointerId); });
stage.addEventListener('pointermove',e=>{ if(!drag) return; view.yaw=drag.yaw-(e.clientX-drag.x)*.006; view.pitch=Math.max(.08,Math.min(1.2,drag.pitch+(e.clientY-drag.y)*.004)); });
stage.addEventListener('pointerup',()=>{ drag=null; }); stage.addEventListener('pointercancel',()=>{ drag=null; });
stage.addEventListener('wheel',e=>{ e.preventDefault(); view.goal.dist=Math.max(5,Math.min(30,view.goal.dist*Math.exp(e.deltaY*.001))); },{passive:false});
let W=1,Hh=1; new ResizeObserver(()=>{ W=stage.clientWidth; Hh=stage.clientHeight; renderer.setSize(W,Hh,false); cam.aspect=W/Math.max(1,Hh); cam.updateProjectionMatrix(); }).observe(stage);
// ---- the cards ----
const everyone=[...loopers,...runners], cards=document.getElementById('people');
cards.innerHTML=everyone.map((p,i)=>{ const t=Motion.traits(p.f.seed); return `<button type="button" data-i="${i}" aria-pressed="false"><b>${p.name}</b>seed ${p.f.seed}<br>stride ×${t.stride.toFixed(2)} · swing ${t.swing.toFixed(2)}<br>bounce ${t.bounce.toFixed(2)} · fidget ${t.fidget.toFixed(2)}</button>`; }).join('');
// a card follows that person with the camera; again to let go
cards.addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b) return; const p=everyone[+b.dataset.i]; view.follow=view.follow===p?null:p;
  cards.querySelectorAll('button').forEach(x=>x.setAttribute('aria-pressed',String(!!view.follow&&x===b)));
  view.goal=view.follow?{x:view.x,y:view.y,z:view.z,dist:5.5}:ui.view==='loop'?LOOPV:COURSEV; });
// ---- readout: slip of planted feet, steps, the hold ----
const readout=document.getElementById('readout'), v=new THREE.Vector3(); let slip=0, last=[null,null], steps=0, lastSt=[true,true], roT=0;
function measure(p,dt){ const M=p.f.motion; if(!M||!M.R||M.clip||M.rag) { last=[null,null]; return; } p.f.root.updateMatrixWorld(true);
  // the point on the ground: the heel while landing, the ball of the foot while rolling off, else the ankle
  for(let i=0;i<2;i++){ const an=p.f.an[i], hl=an.localToWorld(new THREE.Vector3(0,-.062,-.05)), bl=an.localToWorld(new THREE.Vector3(0,-.062,.12)), st=M.stance&&M.stance[i];
    const w=bl.y<hl.y-.0005?1:hl.y<bl.y-.0005?0:2; if(w===2){ v.set(0,-M.R.b,0); p.f.kn[i].localToWorld(v); } else v.copy(w?bl:hl);
    if(st&&last[i]&&last[i].w===w&&dt>0) slip=Math.max(slip,Math.hypot(v.x-last[i].p.x,v.z-last[i].p.z)/dt); if(st&&!lastSt[i]) steps++; lastSt[i]=!!st; last[i]=st?{p:v.clone(),w}:null; } }
function drawReadout(){ const P=ui.view==='loop'?loopers[0]:runners[0], M=P.f.motion; if(!M) return;
  const what=M.rag?(M.rag.sleep?'down':'falling'):M.clip?(ui.view==='loop'?'getting up':P.doing):M.gaitW<.5?'standing':M.runW>.5?'running':'walking';
  readout.innerHTML=`<b>${P.name}</b> · ${what}${M.w?` · ${M.w.spec.kind}`:''}<br>`+(ui.view==='course'?`${runners.map(r=>`${r.name} ${r.doing||''}`).join(' · ')}<br>`:`speed ${M.v.toFixed(2)} m/s · steps ${steps}<br>`)+
    `planted-foot slip <span class="ok">${(slip*1000).toFixed(1)} mm/s</span>`; slip=0; }
// ---- frame loop ----
let lastT=performance.now();
function loop(now){ requestAnimationFrame(loop); const dt=Math.min(.05,(now-lastT)/1000); lastT=now;
  for(let i=later.length-1;i>=0;i--){ if((later[i].t-=dt)<=0){ later[i].fn(); later.splice(i,1); } }
  const still=['hunker','work'].includes(ui.act), sp=still?0:ui.speed, state=act=>({act,mood:ui.mood,ground});
  for(const p of loopers){ const f=p.f, r=f.root;
    if(p.down){ Motion.update(f,state('fall'),dt); p.crate.visible=false; continue; }
    if(Motion.busy(f)){ Motion.update(f,state('idle'),dt); continue; }
    if(p.back){ p.s=nearestS(r.position.x,r.position.z); p.back=false; p.rejoin=true; }
    const q=along(p.s);
    if(p.rejoin){ const dx=q.x-r.position.x, dz=q.z-r.position.z, d=Math.hypot(dx,dz); if(d<.03){ p.rejoin=false; } else { const m=Math.min(d,1.2*dt); r.position.x+=dx/d*m; r.position.z+=dz/d*m; let a=Math.atan2(dx,dz)-r.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); r.rotation.y+=a*Math.min(1,dt*6); } }
    else { p.s+=sp*dt; r.position.x=q.x; r.position.z=q.z; let a=q.h-r.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); r.rotation.y+=a*Math.min(1,dt*10); }
    p.y+=(ground(r.position.x,r.position.z)-p.y)*Math.min(1,dt*14); r.position.y=p.y;
    const act=ui.act==='idle'&&sp>2.3?'run':ui.act; Motion.update(f,state(act),dt); p.crate.visible=ui.act==='carry'; }
  for(const p of runners){ runCourse(p,dt,state('idle')); Motion.update(p.f,state('idle'),dt); }
  measure(ui.view==='loop'?loopers[0]:runners[0],dt); if((roT+=dt)>.4){ roT=0; drawReadout(); }
  if(view.follow){ const q=view.follow.f.root.position; view.goal.x=q.x; view.goal.y=q.y+.9; view.goal.z=q.z; }
  const g=view.goal, k=Math.min(1,dt*3); view.x+=(g.x-view.x)*k; view.y+=(g.y-view.y)*k; view.z+=(g.z-view.z)*k; view.dist+=(g.dist-view.dist)*k;
  cam.position.set(view.x+Math.sin(view.yaw)*Math.cos(view.pitch)*view.dist,view.y+Math.sin(view.pitch)*view.dist,view.z+Math.cos(view.yaw)*Math.cos(view.pitch)*view.dist); cam.lookAt(view.x,view.y,view.z);
  sun.position.set(view.x+5,9,view.z+4); sun.target.position.set(view.x,0,view.z);
  renderer.render(scene,cam); }
arming(); requestAnimationFrame(loop);
window.__lab={loopers,runners,ui,setSpeed,view,COURSE};
})();
