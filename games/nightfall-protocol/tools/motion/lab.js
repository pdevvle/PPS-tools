// ---------- Motion Lab: four people on a loop over a ramp, a landing and stairs, all driven by Motion.update ----------
(function(){
const stage=document.getElementById('stage');
if(!window.THREE){ stage.insertAdjacentHTML('beforeend','<p class="fail">The 3D view needs three.js, which could not load.</p>'); return; }
const TAU=Math.PI*2;
// ---- the ground: profile along x, the same everywhere along z ----
const RISE=.45, STEP=.075, TREAD=.3;
function ground(x){ if(x<-3) return 0; if(x<0) return (x+3)/3*RISE; if(x<1.5) return RISE; const k=Math.floor((x-1.5)/TREAD)+1; return Math.max(0,RISE-STEP*k); }
const groundAt=(x,z)=>ground(x);
// ---- the loop: two straights across the profile joined by half circles ----
const HALF=5.5, RAD=1.1, LOOP=4*HALF+TAU*RAD;
function along(s){ s=((s%LOOP)+LOOP)%LOOP; const A=2*HALF, C=Math.PI*RAD;
  if(s<A) return {x:-HALF+s,z:-RAD,h:Math.PI/2};
  if((s-=A)<C){ const a=s/RAD; return {x:HALF+Math.sin(a)*RAD,z:-Math.cos(a)*RAD,h:Math.PI/2-a}; }
  if((s-=C)<A) return {x:HALF-s,z:RAD,h:-Math.PI/2};
  s-=A; const a=s/RAD; return {x:-HALF-Math.sin(a)*RAD,z:Math.cos(a)*RAD,h:-Math.PI/2-a}; }
// ---- scene ----
const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true}); renderer.setPixelRatio(Math.min(2,devicePixelRatio||1)); renderer.setClearColor(0,0);
renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; stage.prepend(renderer.domElement);
const scene=new THREE.Scene(), cam=new THREE.PerspectiveCamera(30,1,.1,100);
scene.add(new THREE.HemisphereLight(0xfffaf0,0x8a8070,.35));
const sun=new THREE.DirectionalLight(0xfff3dc,.9); sun.position.set(5,9,4); sun.castShadow=true; sun.shadow.mapSize.set(2048,2048);
Object.assign(sun.shadow.camera,{left:-9,right:9,top:6,bottom:-6,near:1,far:30}); sun.shadow.bias=-.0006; sun.shadow.normalBias=.02; scene.add(sun);
const floor=new THREE.Mesh(new THREE.PlaneGeometry(60,40),new THREE.ShadowMaterial({opacity:.14})); floor.rotation.x=-Math.PI/2; floor.receiveShadow=true; scene.add(floor);
{ const pts=[[-8,0],[-3,0],[0,RISE],[1.5,RISE]]; for(let k=1;k<=6;k++){ const x=1.5+(k-1)*TREAD; pts.push([x,RISE-STEP*(k-1)],[x,RISE-STEP*k]); pts.push([1.5+k*TREAD,RISE-STEP*k]); } pts.push([8,0],[8,-.05],[-8,-.05]);
  const sh=new THREE.Shape(); sh.moveTo(...pts[0]); for(const p of pts.slice(1)) sh.lineTo(...p);
  const g=new THREE.ExtrudeGeometry(sh,{depth:3.6,bevelEnabled:false}); g.translate(0,0,-1.8);
  const m=new THREE.Mesh(g,new THREE.MeshToonMaterial({color:0xcdb48c})); m.receiveShadow=true; scene.add(m);
  scene.add(new THREE.LineSegments(new THREE.EdgesGeometry(g,20),new THREE.LineBasicMaterial({color:0x6d5f49}))); }
// ---- people ----
const NAMES=['Rosa','Dev','Malik','June'], INK={calm:0x1d1814,wounded:0xc23b2e,panicked:0x9b4fc4};
const gunG=new THREE.BoxGeometry(.055,.62,.08); gunG.translate(0,-.3,.02); const gunM=new THREE.MeshToonMaterial({color:0x2b2a28});
const crateG=new THREE.BoxGeometry(.42,.3,.32), crateM=new THREE.MeshToonMaterial({color:0x8a6a40});
const people=NAMES.map((name,i)=>{ const fem=i%2===1, seed=950+i*7, f=FigureKit.figure(fem,FigureKit.genFace(seed,fem)); f.seed=seed;
  f.root.traverse(o=>{ if(o.isMesh) o.castShadow=true; });
  const gun=new THREE.Mesh(gunG,gunM); gun.position.set(0,-.24,0); gun.castShadow=true; f.el[0].add(gun);
  const crate=new THREE.Mesh(crateG,crateM); crate.position.set(0,.16,.3); crate.castShadow=true; f.torso.add(crate);
  f.ink=FigureKit.inkUp(f.root,{persp:true,width:.0016,color:INK.calm}); scene.add(f.root);
  const s=i*LOOP/4, p=along(s); f.root.position.set(p.x,ground(p.x),p.z); f.root.rotation.y=p.h;
  return {name,f,gun,crate,s,y:ground(p.x)}; });
// ---- controls ----
const ui={speed:1.4, act:'idle', mood:'calm', fallen:false};
const speedEl=document.getElementById('speed'), speedOut=document.getElementById('speedOut');
function setSpeed(v){ ui.speed=+v; speedEl.value=v; speedOut.textContent=ui.speed.toFixed(2)+' m/s'; document.querySelectorAll('#presets button').forEach(b=>b.setAttribute('aria-pressed',String(Math.abs(+b.dataset.v-ui.speed)<.01))); }
speedEl.addEventListener('input',()=>setSpeed(speedEl.value));
document.getElementById('presets').addEventListener('click',e=>{ const b=e.target.closest('button'); if(b) setSpeed(b.dataset.v); });
const seg=(id,key,attr)=>document.getElementById(id).addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b) return; ui[key]=b.dataset[attr];
  document.querySelectorAll('#'+id+' button').forEach(x=>x.setAttribute('aria-pressed',String(x===b))); if(key==='mood') people.forEach(p=>p.f.ink.color.setHex(INK[ui.mood])); });
seg('act','act','a'); seg('mood','mood','m');
const later=[]; const after=(ms,fn)=>later.push({t:ms/1000,fn});
document.getElementById('hit').addEventListener('click',()=>people.forEach((p,i)=>after(i*140,()=>Motion.kick(p.f,'hit'))));
document.getElementById('fire').addEventListener('click',()=>people.forEach((p,i)=>after(i*90,()=>Motion.kick(p.f,'recoil'))));
const fallBtn=document.getElementById('fall');
fallBtn.addEventListener('click',()=>{ ui.fallen=!ui.fallen; fallBtn.textContent=ui.fallen?'Get up':'Fall'; });
// orbit by dragging
const view={yaw:.55,pitch:.36,dist:12.5}; let drag=null;
stage.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,yaw:view.yaw,pitch:view.pitch}; stage.setPointerCapture(e.pointerId); });
stage.addEventListener('pointermove',e=>{ if(!drag) return; view.yaw=drag.yaw-(e.clientX-drag.x)*.006; view.pitch=Math.max(.08,Math.min(1.2,drag.pitch+(e.clientY-drag.y)*.004)); });
stage.addEventListener('pointerup',()=>{ drag=null; }); stage.addEventListener('pointercancel',()=>{ drag=null; });
let W=1,H=1; new ResizeObserver(()=>{ W=stage.clientWidth; H=stage.clientHeight; renderer.setSize(W,H,false); cam.aspect=W/Math.max(1,H); cam.updateProjectionMatrix(); }).observe(stage);
// ---- the cards: each person's traits from their seed ----
document.getElementById('people').innerHTML=people.map(p=>{ const t=Motion.traits(p.f.seed); return `<div><b>${p.name}</b>seed ${p.f.seed}<br>stride ×${t.stride.toFixed(2)} · swing ${t.swing.toFixed(2)}<br>bounce ${t.bounce.toFixed(2)} · fidget ${t.fidget.toFixed(2)}<br>rests on the ${t.favour?'left':'right'} leg</div>`; }).join('');
// ---- readout: the first person's gait, and how far her planted feet slid ----
const readout=document.getElementById('readout'), v=new THREE.Vector3(); let slip=0, lastFeet=[null,null], cad=0, lastPh=null, roT=0;
function measure(p,dt){ const M=p.f.motion; if(!M||!M.R) return; p.f.root.updateMatrixWorld(true);
  for(let i=0;i<2;i++){ v.set(0,-M.R.b,0); p.f.kn[i].localToWorld(v); const st=M.stance&&M.stance[i]&&M.gaitW>.98;
    if(st&&lastFeet[i]&&dt>0) slip=Math.max(slip,Math.hypot(v.x-lastFeet[i].x,v.z-lastFeet[i].z)/dt); lastFeet[i]=st?v.clone():null; }
  if(lastPh!==null&&dt>0){ const d=((M.ph-lastPh)%1+1)%1; cad+=(d/dt*120-cad)*Math.min(1,dt*3); } lastPh=M.ph; }
function drawReadout(){ const M=people[0].f.motion; if(!M) return; const gait=M.gaitW<.5?'standing':M.runW>.5?'running':'walking';
  readout.innerHTML=`<b>${people[0].name}</b> · ${gait} · ${Motion.ACTS[M.act]===Motion.ACTS.fall?'down':M.act}<br>speed ${M.v.toFixed(2)} m/s · cadence ${M.gaitW<.5?'–':Math.round(cad)+' steps/min'}<br>`+
    `planted-foot slip <span class="ok">${(slip*1000).toFixed(1)} mm/s</span><br>hips ${(M.out.bodyY*100).toFixed(1)} cm · knees ${Math.round(M.out.knR*57.3)}° / ${Math.round(M.out.knL*57.3)}°`; slip=0; }
// ---- frame loop ----
let last=performance.now();
function loop(now){ requestAnimationFrame(loop); const dt=Math.min(.05,(now-last)/1000); last=now;
  for(let i=later.length-1;i>=0;i--){ if((later[i].t-=dt)<=0){ later[i].fn(); later.splice(i,1); } }
  const moving=!ui.fallen&&!['hunker','work'].includes(ui.act), sp=moving?ui.speed:0;
  for(const p of people){ p.s+=sp*dt; const q=along(p.s), f=p.f; f.root.position.x=q.x; f.root.position.z=q.z;
    p.y+=(ground(q.x)-p.y)*Math.min(1,dt*14); f.root.position.y=p.y;
    let a=q.h-f.root.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); f.root.rotation.y+=a*Math.min(1,dt*10);
    const act=ui.fallen?'fall':ui.act==='idle'&&sp>2.3?'run':ui.act;
    Motion.update(f,{act,mood:ui.mood,ground:groundAt},dt);
    p.gun.visible=!['carry','work'].includes(ui.act); p.crate.visible=ui.act==='carry'; }
  measure(people[0],dt); if((roT+=dt)>.4){ roT=0; drawReadout(); }
  const tg=new THREE.Vector3(0,.7,0); cam.position.set(Math.sin(view.yaw)*Math.cos(view.pitch)*view.dist,tg.y+Math.sin(view.pitch)*view.dist,Math.cos(view.yaw)*Math.cos(view.pitch)*view.dist); cam.lookAt(tg);
  renderer.render(scene,cam); }
requestAnimationFrame(loop);
window.__lab={people,ui,setSpeed};
})();
