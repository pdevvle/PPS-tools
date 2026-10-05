(function(){
// The region map: draws the campaign (tools/region/campaign.js) and takes the player's orders. Runs on its own page
// (mockups/region-map.html) and as the map half of the zoom page, where glue-pre.js has defined NF.
const ZOOM=typeof NF!=='undefined';
const R=REGION, stage=document.getElementById(ZOOM?'rstage':'stage'), labelsEl=document.getElementById(ZOOM?'rlabels':'labels');
if(!window.THREE){ stage.insertAdjacentHTML('beforeend','<p class="fail">The 3D view needs three.js, which could not load. Check your connection and reload.</p>'); return; }
let renderer; try{ renderer=new THREE.WebGLRenderer({antialias:true}); }catch(e){ stage.insertAdjacentHTML('beforeend','<p class="fail">This browser could not start WebGL.</p>'); return; }
renderer.setPixelRatio(Math.min(2,devicePixelRatio||1)); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; stage.prepend(renderer.domElement);
const C=Campaign, S=()=>C.state; C.init(R);
const store=(()=>{ try{ const s=window.localStorage, k='__nf_probe'; s.setItem(k,'1'); s.removeItem(k); return s; }catch(e){ return null; } })();
const resumed=C.load(store); if(!resumed) C.newGame();
const TAU=Math.PI*2, VE=1.6, SEC=R.sector, D=R.dem, HX=R.half[0], HZ=R.half[1], K=C.K, KN=['Unknown','Rumoured','Scouted','Current'];
const TAC_RATE=1, TURN_MIN=5;   // tactical exploration runs in real time; each character's turn in a fight is 5 game minutes (foundation)
const scene=new THREE.Scene(), cam=new THREE.PerspectiveCamera(36,1,10,1200000);
scene.fog=new THREE.Fog(0xd9c9a8,30000,90000); renderer.setClearColor(0xd9c9a8);
const hemi=new THREE.HemisphereLight(0xfff3e0,0x6a5a48,.55), sun=new THREE.DirectionalLight(0xfff0d8,1); sun.castShadow=true; sun.shadow.mapSize.set(4096,4096); sun.shadow.bias=-.0006; sun.shadow.normalBias=8;
Object.assign(sun.shadow.camera,{left:-26000,right:26000,top:26000,bottom:-26000,near:100,far:120000}); scene.add(hemi,sun,sun.target);
const KIND={food:'#e0a33a',medicine:'#d9534f',tools:'#5b8fd1',fuel:'#a66bd1',gear:'#3fae7f',water:'#3fb6d9',shelter:'#8f8f8f',goods:'#b9a27a'};
const KLABEL={food:'Food',medicine:'Medicine',tools:'Tools',fuel:'Fuel',gear:'Gear',water:'Water',shelter:'Shelter',goods:'Goods'};
document.getElementById('siteKey').innerHTML=Object.keys(KIND).map(k=>`<li><i style="background:${KIND[k]}"></i>${KLABEL[k]}</li>`).join('')+'<li><i style="background:#6e1a10"></i>Raiders, where you have seen them</li>';
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// ---------- the campaign's own interface: weather in the HUD, base stock, log, encounters ----------
document.head.insertAdjacentHTML('beforeend',`<style>
.hud .sky{font:12px var(--mono);color:#d8d4cc;margin:0 4px 0 -2px;white-space:nowrap}
.hud .sky.hot{color:#f0a05a}
.sqcard{display:flex;flex-direction:column;gap:6px;background:var(--bg);border:1px solid var(--line)}
.sqcard.on{border-color:var(--accent)}
.sqcard .sqb{border:0;background:none;width:100%}
.sqcard .sqb .warn{color:#f0a05a}
.sqctl{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:0 9px 8px;font-size:13px;color:var(--muted)}
.sqctl label{display:flex;gap:6px;align-items:center;cursor:pointer}
.sqctl button,.sites button,.newc{background:#2d2f33;border:1px solid var(--line);color:var(--text);font:600 12px var(--mono);padding:3px 8px;cursor:pointer}
.sites button{margin-left:6px;flex:none}
.sites button:disabled{opacity:.4;cursor:default}
.sites .left{margin-left:auto;color:var(--muted);font-size:12px;white-space:nowrap}
.danger{color:#e46a55;font-size:13px;margin:8px 0 0}
.stock{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:1fr 1fr;gap:2px 10px;font-size:13px;font-variant-numeric:tabular-nums}
.stock li{display:flex;gap:6px;align-items:center}.stock i{width:8px;height:8px;border-radius:50%;flex:none}
.log{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:4px;font-size:13px;max-height:170px;overflow:auto}
.log time{font:11px var(--mono);color:var(--muted);display:block}
.newc{margin-top:6px}
.lb.town.city{font-size:18px;letter-spacing:.08em}
.lb.band{font:600 11px var(--body);color:#fff;background:rgba(110,26,16,.9);padding:1px 6px;border-radius:3px;text-shadow:none}
.lb.band.old{background:rgba(110,26,16,.55)}
.enc{position:absolute;left:50%;top:54px;transform:translateX(-50%);width:min(440px,calc(100% - 24px));background:rgba(24,24,26,.94);border:1px solid #c23b2e;border-radius:6px;padding:12px 14px;color:#f1eee8;z-index:4}
.enc h3{font:600 17px var(--body);margin:0 0 4px}.enc p{margin:0 0 8px;font-size:14px;color:#d8d4cc}
.enc .acts{display:flex;flex-wrap:wrap;gap:6px}
.enc button{background:#2d2f33;border:1px solid var(--line);color:var(--text);font:600 13px var(--body);padding:6px 10px;cursor:pointer;border-radius:3px}
.enc button.pri{background:var(--accent);border-color:var(--accent);color:#211b10}
</style>`);
const hud=stage.querySelector('.hud'), clockEl=document.getElementById('clock');
clockEl.insertAdjacentHTML('afterend','<span class="sky" id="sky"></span>');
hud.insertAdjacentHTML('beforeend','<button type="button" id="waitBtn"></button>');
document.getElementById('homeBtn').insertAdjacentHTML('afterend','<button type="button" id="realmBtn" title="See the whole realm">Realm</button>');
const skyEl=document.getElementById('sky'), waitBtn=document.getElementById('waitBtn');
const sqEl=document.getElementById('squads'), secEl=document.getElementById('sector'), rail=sqEl.closest('section').parentElement;
rail.insertAdjacentHTML('beforeend',`<section style="margin-top:14px"><h2>At the ranch</h2><ul class="stock" id="stock"></ul></section>
  <section style="margin-top:14px"><h2>Log</h2><ol class="log" id="log"></ol><button type="button" class="newc" id="newBtn">New campaign</button></section>`);
const stockEl=document.getElementById('stock'), logEl=document.getElementById('log'), newBtn=document.getElementById('newBtn');
const encEl=document.createElement('div'); encEl.className='enc'; encEl.hidden=true; encEl.setAttribute('role','alertdialog'); stage.appendChild(encEl);

// ---------- terrain: the realm at 400 m, and the corridor's 100 m terrain laid over it ----------
const hRaw=C.hRaw, Y=(x,z)=>hRaw(x,z)*VE;
const DF=R.demFine||null, MAXT=Math.min(4096,renderer.capabilities.maxTextureSize);
const AC={residential:'#cdbb98',retail:'#a9a49a',commercial:'#a9a49a',industrial:'#a39a8c',farmland:'#9caf62',farmyard:'#b8a77a'};
const RW={motorway:34,trunk:24,primary:20,secondary:16,tertiary:13,motorway_link:10,trunk_link:10,primary_link:10,secondary_link:9,tertiary_link:9,unclassified:10,residential:8,track:6};
const ORDER=['track','residential','unclassified','tertiary_link','tertiary','secondary_link','secondary','primary_link','primary','trunk_link','trunk','motorway_link','motorway'];
const bboxOf=pts=>{ let a=1e9,b=1e9,c=-1e9,d=-1e9; for(const [x,z] of pts){ if(x<a)a=x; if(z<b)b=z; if(x>c)c=x; if(z>d)d=z; } return [a,b,c,d]; };
// one level of terrain: its mesh, its ground texture and its knowledge overlay
function layer(Dm,size,{fine,sink}){
  const W=(Dm.nx-1)*Dm.step, Hh=(Dm.nz-1)*Dm.step, TX=W>=Hh?size:Math.round(size*W/Hh), TZ=W>=Hh?Math.round(size*Hh/W):size;
  const X=x=>(x-Dm.x0)/W*TX, Zc=z=>(z-Dm.z0)/Hh*TZ, px=TX/W, ext=[Dm.x0,Dm.z0,Dm.x0+W,Dm.z0+Hh];
  const geo=new THREE.PlaneGeometry(W,Hh,Dm.nx-1,Dm.nz-1); geo.rotateX(-Math.PI/2);
  { const p=geo.attributes.position; for(let i=0;i<p.count;i++){ const x=Dm.x0+(i%Dm.nx)*Dm.step, z=Dm.z0+Math.floor(i/Dm.nx)*Dm.step;
      p.setY(i,Dm.h[i]*VE-(sink&&x>sink[0]&&z>sink[1]&&x<sink[2]&&z<sink[3]?60*VE:0)); }   // under the corridor, the realm sinks out of the way
    geo.computeVertexNormals(); }
  const over=b=>b[2]>=ext[0]&&b[0]<=ext[2]&&b[3]>=ext[1]&&b[1]<=ext[3];
  const c=document.createElement('canvas'); c.width=TX; c.height=TZ; const g=c.getContext('2d');
  // elevation tint: valley sand to ochre ridges
  const img=g.createImageData(Dm.nx,Dm.nz); let hmax=0; for(const v of Dm.h) hmax=Math.max(hmax,v);
  const lo=[214,190,148], mid=[196,160,112], hi=[150,112,80];
  for(let j=0;j<Dm.nz;j++) for(let i=0;i<Dm.nx;i++){ const t=Dm.h[j*Dm.nx+i]/hmax, a=t<.5?lo:mid, b=t<.5?mid:hi, k=t<.5?t*2:(t-.5)*2, o=(j*Dm.nx+i)*4;
    for(let q=0;q<3;q++) img.data[o+q]=a[q]+(b[q]-a[q])*k; img.data[o+3]=255; }
  const tc=document.createElement('canvas'); tc.width=Dm.nx; tc.height=Dm.nz; tc.getContext('2d').putImageData(img,0,0); g.imageSmoothingEnabled=true; g.drawImage(tc,0,0,TX,TZ);
  const r=(s=>()=>{ s=(Math.imul(s,1664525)+1013904223)>>>0; return s/4294967296; })(7);
  for(let i=0;i<60000;i++){ g.fillStyle=r()<.5?'rgba(110,90,60,.22)':'rgba(120,140,70,.18)'; g.fillRect(r()*TX,r()*TZ,1.4,1.4); }   // desert scrub
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  const line=(pts,w,col,dash)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.lineWidth=Math.max(fine?.8:.6,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.setLineDash(dash||[]); g.stroke(); g.setLineDash([]); };
  for(const a of R.areas) if(AC[a.kind]&&over(a.bb||(a.bb=bboxOf(a.pts)))) poly(a.pts,AC[a.kind]);
  for(const w of R.water) if(over(w.bb||(w.bb=bboxOf(w.pts)))){ const big=w.kind==='river'; line(w.pts,big?60:22,'#b39c78'); line(w.pts,big?40:12,'#e3d2ad'); }
  for(const l of R.lakes) if(over(l.bb||(l.bb=bboxOf(l.pts)))) poly(l.pts,'#4aa6c8');
  // the corridor draws its own road list; the realm draws the travel graph's edges (the same roads, major ones only)
  const src=fine||!DF?R.roads:R.graph.edges.filter(e=>RW[e[3]]&&e[3]!=='residential'&&e[3]!=='track').map(e=>({cls:e[3],dirt:!!e[5],pts:[R.graph.nodes[e[0]],...e[4],R.graph.nodes[e[1]]]}));
  const byCls=new Map(); for(const rd of src){ if(!over(rd.bb||(rd.bb=bboxOf(rd.pts)))) continue; if(!byCls.has(rd.cls)) byCls.set(rd.cls,[]); byCls.get(rd.cls).push(rd); }
  for(const k of ORDER) for(const rd of byCls.get(k)||[]){ const w=RW[k]||8;
    if(rd.dirt) line(rd.pts,w,'#a88d68',k==='track'?[w*px*2,w*px*1.4]:null); else { if(w>12&&fine) line(rd.pts,w+8,'#e8dcc4'); line(rd.pts,w,k==='motorway'?'#3b3a38':'#5e5a54'); } }
  // hillshade from the north-west
  const sh=document.createElement('canvas'); sh.width=Dm.nx; sh.height=Dm.nz; const sg=sh.getContext('2d'), si=sg.createImageData(Dm.nx,Dm.nz), L=[-.5,.75,-.45], ll=Math.hypot(...L), flat=L[1]/ll;
  for(let j=0;j<Dm.nz;j++) for(let i=0;i<Dm.nx;i++){ const h=(a,b)=>Dm.h[Math.min(Dm.nz-1,Math.max(0,b))*Dm.nx+Math.min(Dm.nx-1,Math.max(0,a))]*VE, dx=(h(i+1,j)-h(i-1,j))/(2*Dm.step), dz=(h(i,j+1)-h(i,j-1))/(2*Dm.step);
    const n=[-dx,1,-dz], nl=Math.hypot(...n), v=((n[0]*L[0]+n[1]*L[1]+n[2]*L[2])/(nl*ll)-flat)*2.4, o=(j*Dm.nx+i)*4;
    if(v<0){ si.data[o]=70; si.data[o+1]=40; si.data[o+2]=20; si.data[o+3]=Math.min(.55,-v)*255; } else { si.data[o]=255; si.data[o+1]=246; si.data[o+2]=225; si.data[o+3]=Math.min(.35,v)*255; } }
  sg.putImageData(si,0,0); g.drawImage(sh,0,0,TX,TZ);
  const tex=new THREE.CanvasTexture(c); tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
  const mesh=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({map:tex, flatShading:true, roughness:.95, metalness:0}));
  mesh.position.set(Dm.x0+W/2,0,Dm.z0+Hh/2); mesh.receiveShadow=true; scene.add(mesh);
  const OCv=document.createElement('canvas'); OCv.width=TX; OCv.height=TZ; const og=OCv.getContext('2d'), otex=new THREE.CanvasTexture(OCv);
  const overlay=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({map:otex, transparent:true, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-4, polygonOffsetUnits:-4}));
  overlay.position.copy(mesh.position); overlay.renderOrder=2; scene.add(overlay);
  return {mesh,X,Zc,px,TX,TZ,og,otex,fine}; }
const sinkBox=DF?[DF.x0+DF.step,DF.z0+DF.step,DF.x0+(DF.nx-2)*DF.step,DF.z0+(DF.nz-2)*DF.step]:null;
const layers=[layer(D,DF?MAXT:2048,{fine:!DF,sink:sinkBox})]; if(DF) layers.push(layer(DF,2048,{fine:true}));
const terrains=layers.map(l=>l.mesh);
const skirt=new THREE.Mesh(new THREE.PlaneGeometry(2000000,2000000),new THREE.MeshStandardMaterial({color:0xc4aa82, roughness:1})); skirt.rotation.x=-Math.PI/2; skirt.position.y=-20; scene.add(skirt);

// ---------- knowledge and the sector overlay ----------
// knowledge is painted one pixel per sector, then stretched onto each layer; outlines (home, hover, selection) are ribbons
const secAt=C.secAt, secCentre=C.secCentre, home=C.home, [hx0,hz0]=C.homeXZ;
const KC=document.createElement('canvas'); KC.width=R.cols; KC.height=R.rows; const kg=KC.getContext('2d');
const UC=document.createElement('canvas'); UC.width=R.cols; UC.height=R.rows; const ug=UC.getContext('2d');
const hatchTile=n=>{ const c=document.createElement('canvas'); c.width=c.height=n; const g=c.getContext('2d'); g.strokeStyle='rgba(30,26,22,.35)'; g.lineWidth=Math.max(1,n/11); g.beginPath(); g.moveTo(0,n); g.lineTo(n,0); g.stroke(); return c; };   // n px: one stroke every 200 m on every layer
let hoverSec=null, selSec=null;
function drawOverlay(){ const know=S().know, ki=kg.createImageData(R.cols,R.rows), ui=ug.createImageData(R.cols,R.rows);
  for(let r=0;r<R.rows;r++) for(let c=0;c<R.cols;c++){ const kk=know[r][c], o=(r*R.cols+c)*4, set=(d,rgb,a)=>{ d.data[o]=rgb[0]; d.data[o+1]=rgb[1]; d.data[o+2]=rgb[2]; d.data[o+3]=a*255; };
    if(kk.k===K.UNKNOWN){ set(ki,[38,34,30],.34); set(ui,[0,0,0],1); } else if(kk.k===K.RUMOUR) set(ki,[60,52,44],.18); else if(C.stale(kk)) set(ki,[60,52,44],.16); }
  kg.putImageData(ki,0,0); ug.putImageData(ui,0,0);
  for(const L of layers){ const {og,X,Zc,TX,TZ}=L, x0=X(-HX), z0=Zc(-HZ), w=X(HX)-x0, h=Zc(HZ)-z0;
    og.clearRect(0,0,TX,TZ); og.imageSmoothingEnabled=false;
    og.fillStyle='rgba(40,34,28,.35)'; og.fillRect(0,0,TX,TZ); og.clearRect(x0,z0,w,h);   // outside the realm: a soft vignette
    og.drawImage(KC,x0,z0,w,h);
    const t=document.createElement('canvas'); t.width=TX; t.height=TZ; const tg=t.getContext('2d');   // the hatch, only over unknown sectors
    tg.fillStyle=tg.createPattern(hatchTile(Math.max(4,Math.round(200*L.px))),'repeat'); tg.fillRect(0,0,TX,TZ); tg.globalCompositeOperation='destination-in'; tg.imageSmoothingEnabled=false; tg.drawImage(UC,x0,z0,w,h); og.drawImage(t,0,0);
    if(L.fine){ og.strokeStyle='rgba(40,32,24,.22)'; og.lineWidth=1; og.beginPath();
      for(let c=0;c<=R.cols;c++){ const x=X(-HX+c*SEC); if(x<0||x>TX) continue; og.moveTo(x,Math.max(0,z0)); og.lineTo(x,Math.min(TZ,z0+h)); }
      for(let r=0;r<=R.rows;r++){ const z=Zc(-HZ+r*SEC); if(z<0||z>TZ) continue; og.moveTo(Math.max(0,x0),z); og.lineTo(Math.min(TX,x0+w),z); } og.stroke(); }
    if(ZOOM&&L===layers[layers.length-1]){ og.setLineDash([10,6]); og.strokeStyle='#e0a526'; og.lineWidth=3; og.beginPath(); NF.rect.forEach(([x,z],i)=>i?og.lineTo(X(x),Zc(z)):og.moveTo(X(x),Zc(z))); og.closePath(); og.stroke(); og.setLineDash([]); }
    L.otex.needsUpdate=true; }
  drawMarks(); }
const marks={}, markMat={home:new THREE.MeshBasicMaterial({color:0x3fae7f,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-8,polygonOffsetUnits:-8}),hover:new THREE.MeshBasicMaterial({color:0xfffaeb,transparent:true,opacity:.9,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-8,polygonOffsetUnits:-8}),sel:new THREE.MeshBasicMaterial({color:0xe0a526,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-8,polygonOffsetUnits:-8})};
function drawMarks(){ const w=Math.max(6,(typeof camS!=='undefined'?camS.dist:16000)/1400);
  for(const [k,s] of [['home',home],['hover',hoverSec],['sel',selSec]]){ const key=s?s+'|'+Math.round(w):'';
    if(marks[k]&&marks[k].key===key) continue; if(marks[k]){ scene.remove(marks[k].mesh); marks[k].mesh.geometry.dispose(); marks[k]=null; } if(!s) continue;
    const x0=-HX+s[0]*SEC+w, z0=-HZ+s[1]*SEC+w, x1=x0+SEC-2*w, z1=z0+SEC-2*w, m=ribbon([[x0,z0],[x1,z0],[x1,z1],[x0,z1],[x0,z0]],w*(k==='sel'?1.4:1),markMat[k]); m.renderOrder=4; scene.add(m); marks[k]={key,mesh:m}; } }

// ---------- buildings, sites, labels ----------
const inkMat=(color,width)=>{ const m=new THREE.MeshBasicMaterial({color, side:THREE.BackSide});
  m.onBeforeCompile=sh=>{ sh.vertexShader=sh.vertexShader.replace('#include <project_vertex>',`vec4 mvPosition=vec4(transformed,1.0); vec3 nn=normal;
    #ifdef USE_INSTANCING
      mvPosition=instanceMatrix*mvPosition; nn=mat3(instanceMatrix)*nn;
    #endif
    mvPosition=modelViewMatrix*mvPosition; mvPosition.xyz+=normalize(normalMatrix*nn)*${width.toFixed(5)}*(-mvPosition.z); gl_Position=projectionMatrix*mvPosition;`); };
  return m; };
const boxG=new THREE.BoxGeometry(1,1,1); boxG.translate(0,.5,0);
const bMat=new THREE.MeshStandardMaterial({color:0xe2cfae, flatShading:true, roughness:.9}), bInk=inkMat(0x2a211b,.0012);
let bMesh=null, bInkMesh=null;
function buildBuildings(){ const know=S().know;
  if(bMesh){ scene.remove(bMesh); scene.remove(bInkMesh); bMesh.dispose(); bInkMesh.dispose(); }
  const list=R.buildings.filter(b=>{ const s=secAt(b[0],b[1]); return s && know[s[1]][s[0]].k>=K.RUMOUR; });
  bMesh=new THREE.InstancedMesh(boxG,bMat,Math.max(1,list.length)); bInkMesh=new THREE.InstancedMesh(boxG,bInk,Math.max(1,list.length));
  const m=new THREE.Matrix4(), q=new THREE.Quaternion(), col=new THREE.Color(), TONES=[0xe2cfae,0xd6bf9a,0xcfb48e,0xb5653f,0xbfa182];
  list.forEach((b,i)=>{ const hh=(b[2]*b[3]>600?7:4.5)*VE; m.compose(new THREE.Vector3(b[0],Y(b[0],b[1])-1,b[1]),q,new THREE.Vector3(b[2],hh,b[3])); bMesh.setMatrixAt(i,m); bInkMesh.setMatrixAt(i,m); bMesh.setColorAt(i,col.setHex(TONES[(Math.abs(b[0]*7+b[1]*13))%TONES.length])); });
  bMesh.count=bInkMesh.count=list.length; bMesh.castShadow=true; scene.add(bMesh,bInkMesh); }
const lab=(cls,html)=>{ const e=document.createElement('div'); e.className='lb '+cls; e.innerHTML=html; labelsEl.appendChild(e); return e; };
const labels=[];
const SHOW={city:1e9,town:140000,village:60000,hamlet:24000,suburb:24000};   // the furthest camera distance a place's label shows at
for(const p of R.places) if(SHOW[p.kind]) labels.push({el:lab('town'+(p.kind==='city'?' city':''),esc(p.name)),x:p.p[0],z:p.p[1],dy:120,kind:p.kind,far:SHOW[p.kind]});
for(const p of R.peaks) if(p.name) labels.push({el:lab('peak',`${p.name}<small>${Math.round(p.h*3.281).toLocaleString()} ft</small>`),x:p.p[0],z:p.p[1],dy:60,kind:'peak'});
{ const mw=R.roads.filter(r=>r.cls==='motorway'); if(mw.length){ const r=mw[Math.floor(mw.length/2)], p=r.pts[Math.floor(r.pts.length/2)]; labels.push({el:lab('road','I-17'),x:p[0],z:p[1],dy:40,kind:'road'}); } }
// site pins: grey while only rumoured, the loot colour once scouted, dimmer as a place is picked over
const pinG=new THREE.OctahedronGeometry(1,0), pinMat=new THREE.MeshStandardMaterial({color:0xffffff, flatShading:true}), pinInk=inkMat(0x1d1814,.0016);
let pinMesh=null, pinInkMesh=null;
function buildPins(){ const know=S().know, list=[];   // one instanced mesh for every pin: there can be thousands across the realm
  R.sites.forEach((s,i)=>{ const kk=know[s.sector[1]][s.sector[0]].k; if(kk>=K.RUMOUR) list.push([s,i,kk>=K.SCOUT]); });
  if(pinMesh){ scene.remove(pinMesh,pinInkMesh); pinMesh.dispose(); pinInkMesh.dispose(); }
  pinMesh=new THREE.InstancedMesh(pinG,pinMat,Math.max(1,list.length)); pinInkMesh=new THREE.InstancedMesh(pinG,pinInk,Math.max(1,list.length));
  const m=new THREE.Matrix4(), q=new THREE.Quaternion(), sc=new THREE.Vector3(26,40,26), v=new THREE.Vector3(), col=new THREE.Color();
  list.forEach(([s,i,known],n)=>{ m.compose(v.set(s.p[0],Y(s.p[0],s.p[1])+70,s.p[1]),q,sc); pinMesh.setMatrixAt(n,m); pinInkMesh.setMatrixAt(n,m);
    pinMesh.setColorAt(n,col.set(!known?'#7d7468':C.leftOf(i)<.05?'#4a4640':KIND[s.loot])); });   // grey while rumoured, dark once searched out
  pinMesh.count=pinInkMesh.count=list.length; scene.add(pinMesh,pinInkMesh); }

// ---------- squads and raiders on the map ----------
const tokG=(()=>{ const g=new THREE.CylinderGeometry(55,70,30,6); g.translate(0,15,0); const p=new THREE.ConeGeometry(45,150,6); p.translate(0,105,0); const pos=[]; for(const gg of [g,p]){ const n=gg.toNonIndexed(); pos.push(...n.attributes.position.array); } const out=new THREE.BufferGeometry(); out.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); out.computeVertexNormals(); return out; })();
const bandG=(()=>{ const g=new THREE.ConeGeometry(60,120,4); g.translate(0,60,0); return g; })();
let selSquad=0; const views=[];
const routeMat=new THREE.MeshBasicMaterial({color:0xe0a526, transparent:true, opacity:.9, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-6, polygonOffsetUnits:-6});
function ribbon(pts,w,mat){ const dense=[]; for(let i=0;i<pts.length-1;i++){ const a=pts[i], b=pts[i+1], n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/60)); for(let k=0;k<n;k++) dense.push([a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n]); } dense.push(pts[pts.length-1]);
  const pos=[]; for(let i=0;i<dense.length-1;i++){ const a=dense[i], b=dense[i+1], dx=b[0]-a[0], dz=b[1]-a[1], l=Math.hypot(dx,dz)||1, nx=-dz/l*w, nz=dx/l*w, ya=Y(a[0],a[1])+6, yb=Y(b[0],b[1])+6;
    pos.push(a[0]+nx,ya,a[1]+nz, b[0]+nx,yb,b[1]+nz, b[0]-nx,yb,b[1]-nz, a[0]+nx,ya,a[1]+nz, b[0]-nx,yb,b[1]-nz, a[0]-nx,ya,a[1]-nz); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); const m=new THREE.Mesh(g,mat); m.renderOrder=3; return m; }
function syncViews(){   // one token, label and route ribbon per squad in the campaign
  S().squads.forEach((s,i)=>{ let v=views[i]; if(!v){ v=views[i]={mesh:new THREE.Mesh(tokG,new THREE.MeshStandardMaterial({color:s.c, flatShading:true})), ink:inkMat(0x1d1814,.0022), el:lab('sq','')}; v.mesh.add(new THREE.Mesh(tokG,v.ink)); v.mesh.castShadow=true; scene.add(v.mesh); }
    v.el.textContent=s.name; v.el.style.setProperty('--c',s.c); v.mesh.material.color.set(s.c); v.ink.color.setHex(i===selSquad?0xe0a526:0x1d1814);
    if(v.trip!==s.trip){ if(v.line){ scene.remove(v.line); v.line.geometry.dispose(); v.line.material.dispose(); v.line=null; } v.trip=s.trip;
      if(s.trip){ v.line=ribbon(s.trip.pts,14,new THREE.MeshBasicMaterial({color:new THREE.Color(s.c), transparent:true, opacity:.75, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-6, polygonOffsetUnits:-6})); scene.add(v.line); } } }); }
const bandViews=new Map(), bandMat=new THREE.MeshStandardMaterial({color:0x6e1a10, flatShading:true}), bandGhost=new THREE.MeshStandardMaterial({color:0x6e1a10, flatShading:true, transparent:true, opacity:.4}), bandInk=inkMat(0x1d1814,.002);
const SEEN_FOR=12*60;   // a last sighting stays on the map this long
function syncBands(){ const st=S(), live=new Set();
  for(const b of st.bands){ live.add(b.id); let v=bandViews.get(b.id); if(!v){ v={mesh:new THREE.Mesh(bandG,bandMat), el:lab('band','')}; v.mesh.add(new THREE.Mesh(bandG,bandInk)); scene.add(v.mesh); bandViews.set(b.id,v); }
    const now=b.seen&&b.seen.t>=st.minutes-.01, show=b.seen&&st.minutes-b.seen.t<SEEN_FOR;
    v.mesh.visible=!!show; v.el.style.display=show?'':'none'; v.show=!!show;
    if(show){ v.mesh.material=now?bandMat:bandGhost; v.x=now?b.x:b.seen.x; v.z=now?b.z:b.seen.z; v.el.className='lb band'+(now?'':' old'); v.el.textContent=now?`Raiders · ${b.size}`:`Raiders · seen ${Math.max(1,Math.round((st.minutes-b.seen.t)/60))} h ago`; } }
  for(const [id,v] of bandViews) if(!live.has(id)){ scene.remove(v.mesh); v.el.remove(); bandViews.delete(id); } }

// ---------- light ----------
function lightFor(m){ const s=C.sunAt(m), day=s.elev, az=s.arc*Math.PI;
  sun.intensity=.3+day*.85; hemi.intensity=.42+day*.3; sun.color.setHSL(.08,.6,.55+day*.35); hemi.color.setHSL(.08+(1-s.daylight)*.5,.35,.62+day*.25);
  const night=1-Math.min(1,s.daylight*1.5); renderer.setClearColor(new THREE.Color(0xd9c9a8).lerp(new THREE.Color(0x2a3248),night*.7)); scene.fog.color.copy(renderer.getClearColor(new THREE.Color()));
  sunDir.set(Math.cos(az)*40000,8000+day*50000,-12000+Math.sin(az)*6000); }
const sunDir=new THREE.Vector3(0,50000,0); let shadowExt=26000;
function followView(tx,ty,tz,dist){   // the fog, the sun and its shadow box follow the view, so the whole realm can be seen
  scene.fog.near=dist*2; scene.fog.far=dist*7; sun.target.position.set(tx,ty,tz); sun.position.copy(sun.target.position).add(sunDir);
  const ext=Math.min(60000,Math.max(4000,dist*1.6)); if(Math.abs(ext-shadowExt)/shadowExt>.15){ shadowExt=ext; Object.assign(sun.shadow.camera,{left:-ext,right:ext,top:ext,bottom:-ext}); sun.shadow.camera.updateProjectionMatrix(); } }
const PHASE={night:'Night',dawn:'Dawn',day:'Day',dusk:'Dusk'};
function drawSky(){ const st=S(), sq=st.squads[selSquad]||{x:hx0,z:hz0}, s=C.sunAt(st.minutes), t=C.tempAt(st.minutes,sq.x,sq.z), heat=C.heatOf(t);
  clockEl.textContent=C.fmtT(st.minutes); skyEl.textContent=`${PHASE[s.phase]} · ${Math.round(t)} °C${heat>=C.REST_HEAT?' · heat':''}`; skyEl.classList.toggle('hot',heat>=C.REST_HEAT);
  waitBtn.textContent=st.waitUntil>st.minutes?'Waiting…':C.waitLabel(); waitBtn.setAttribute('aria-pressed',String(st.waitUntil>st.minutes)); }

// ---------- panels ----------
const fmtH=h=>h<1?`${Math.max(1,Math.round(h*60))} min`:`${h.toFixed(1)} h`;
function status(s){ const st=S();
  if(s.task?.kind==='scavenge') return `searching ${esc(C.siteName(R.sites[s.task.site]))} · ${fmtH((s.task.until-st.minutes)/60)} left`;
  if(s.task?.kind==='hide') return `lying low · ${fmtH((s.task.until-st.minutes)/60)}`;
  if(s.trip){ const heat=C.heatOf(C.tempAt(st.minutes,s.x,s.z)); if(s.restHeat&&heat>=C.REST_HEAT) return 'lying up in the heat';
    const f=C.forecast(s.trip,st.minutes,s.people,s.restHeat); return `moving · arrives ${C.fmtT(f.arrive).slice(-5)} (${fmtH(f.hours)})`; }
  return C.atHome(s)?'at the ranch':`at ${esc(C.nearestPlace(s.x,s.z))}`; }
function drawSquads(){ const st=S();
  sqEl.innerHTML=st.squads.map((s,i)=>{ const on=i===selSquad, kg=C.packKg(s), wc=C.waterCap(s), low=s.water<wc*.25;
    return `<div class="sqcard${on?' on':''}"><button type="button" class="sqb" data-i="${i}" aria-pressed="${on}"><b><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${s.c};margin-right:7px"></span>${esc(s.name)}</b>
      <span>${s.people} people · ${status(s)}</span>
      <span${low?' class="warn"':''}>water ${s.water.toFixed(1)} / ${wc} L${s.thirsty?' · thirsty':''} · pack ${kg.toFixed(0)} / ${(C.capKg(s)-s.water).toFixed(0)} kg</span></button>
      ${on?`<div class="sqctl"><label><input type="checkbox" data-rest="${i}"${s.restHeat?' checked':''}> Lie up in the heat</label>${s.trip?`<button type="button" data-stop="${i}">Stop</button>`:''}</div>`:''}</div>`; }).join(''); }
sqEl.addEventListener('click',e=>{ const st=e.target.closest('[data-stop]'); if(st){ C.stop(+st.dataset.stop); changed(); return; }
  const b=e.target.closest('.sqb'); if(!b) return; selSquad=+b.dataset.i; syncViews(); drawSquads(); drawSky(); if(selSec) drawSector(); });
sqEl.addEventListener('change',e=>{ const r=e.target.closest('[data-rest]'); if(!r) return; S().squads[+r.dataset.rest].restHeat=r.checked; changed(); });
function drawStock(){ const st=S(), have=C.LOOT.filter(k=>st.base.stock[k]>0);
  stockEl.innerHTML=have.length?have.map(k=>`<li><i style="background:${KIND[k]}"></i>${st.base.stock[k]} ${C.UNIT[k].name}</li>`).join(''):'<li style="grid-column:1/-1;color:var(--muted)">Nothing brought home yet.</li>'; }
function drawLog(){ logEl.innerHTML=S().log.slice(0,12).map(l=>`<li><time>${C.fmtT(l.t)}</time>${esc(l.msg)}</li>`).join(''); }
let preview=null, routeMemo={};   // routes across the realm take a moment; the panel redraws often
const colName=c=>{ let s=''; c++; while(c>0){ const m=(c-1)%26; s=String.fromCharCode(65+m)+s; c=Math.floor((c-1)/26); } return s; };   // A..Z, AA..
function drawSector(){ const st=S();
  const [c,r]=selSec, s=R.sectors[r][c], kk=st.know[r][c], [cx,cz]=secCentre(c,r), known=kk.k>=K.SCOUT;
  const sq=st.squads[selSquad], key=[sq.x,sq.z,cx,cz].map(Math.round).join(), rt=routeMemo.key===key?routeMemo.rt:(routeMemo={key,rt:C.route(sq.x,sq.z,cx,cz)}).rt, tr=C.makeTrip(rt); preview=rt; drawPreview();
  const f=C.forecast(tr,st.minutes,sq.people,sq.restHeat), TYPE={town:'Town',homes:'Scattered homes',rough:'Rough hills',desert:'Open desert'};
  const siteRows=s.sites.map(i=>{ const t=R.sites[i], left=C.leftOf(i), can=C.canScavenge(selSquad,i);
    const state=st.sites[i]?(left<.05?'searched out':`${Math.round(left*100)}% left`):'untouched';
    return `<li><i style="background:${KIND[t.loot]}"></i>${esc(C.siteName(t))}<span class="left">${KLABEL[t.loot]} · ${state}</span>${can?`<button type="button" data-scav="${i}" title="Search with ${esc(sq.name)}">Search ${fmtH(C.scavHours(i,sq.people))}</button>`:''}</li>`; });
  const seen=st.bands.filter(b=>b.seen&&st.minutes-b.seen.t<C.STALE&&String(secAt(b.seen.x,b.seen.z))===String(selSec));
  const short=f.water>sq.water+.05, inSec=String(secAt(sq.x,sq.z))===String(selSec);
  secEl.innerHTML=`<h2>Sector ${colName(c)}-${r+1}</h2><h3>${esc((t=>t[0].toUpperCase()+t.slice(1))(C.nearestPlace(cx,cz)))}</h3>
   <dl><div><dt>Knowledge</dt><dd>${KN[kk.k]}${C.stale(kk)?' (stale)':''}</dd></div>
   <div><dt>Ground</dt><dd>${kk.k>=K.RUMOUR?TYPE[s.type]:'?'}</dd></div>
   <div><dt>Elevation</dt><dd>${Math.round(s.lo*3.281).toLocaleString()}–${Math.round(s.hi*3.281).toLocaleString()} ft</dd></div>
   <div><dt>Buildings</dt><dd>${kk.k<K.RUMOUR?'?':s.fine===false?'about '+s.b:s.b}</dd></div>
   <div><dt>Sites</dt><dd>${known?s.sites.length:kk.k===K.RUMOUR&&s.sites.length?'some':'?'}</dd></div></dl>
   ${seen.length?`<p class="danger">Raiders seen here ${C.fmtT(Math.max(...seen.map(b=>b.seen.t)))}</p>`:''}
   ${known&&s.sites.length?`<ul class="sites">${siteRows.slice(0,40).join('')}</ul>`:''}
   ${inSec?'':`<button type="button" class="go" id="goBtn" ${sq.task||st.enc?'disabled':''}>${sq.trip?'Send '+esc(sq.name)+' here instead':'Send '+esc(sq.name)+' here'}</button>
   <p class="eta">${rt.km.toFixed(1)} km · ${fmtH(f.hours)}${f.rest>0?` (${fmtH(f.rest)} lying up)`:''} · arrives ${C.fmtT(f.arrive)} · ${f.water.toFixed(1)} L water${short?` <span style="color:#f0a05a">· carrying ${sq.water.toFixed(1)} L</span>`:''}</p>`}`;
  const go=document.getElementById('goBtn'); if(go) go.onclick=()=>{ C.send(selSquad,cx,cz); if(speed===0) setSpeed(1); changed(); }; }
secEl.addEventListener('click',e=>{ const b=e.target.closest('[data-scav]'); if(!b) return; if(C.scavenge(selSquad,+b.dataset.scav)){ if(speed===0) setSpeed(1); changed(); } });
let prevMesh=null;
function drawPreview(){ if(prevMesh){ scene.remove(prevMesh); prevMesh.geometry.dispose(); prevMesh=null; } const sq=S().squads[selSquad];
  if(preview && !sq.task && String(secAt(sq.x,sq.z))!==String(selSec)){ prevMesh=ribbon(preview.pts,22,routeMat); scene.add(prevMesh); } }

// ---------- encounters ----------
const LIGHT={day:'In daylight',dawn:'At dawn',dusk:'At dusk',night:'In the dark'};
const canDive=e=>ZOOM&&NF.inBlock(e.where.x,e.where.z);
function drawEncounter(){ const e=S().enc; encEl.hidden=!e; if(!e) return;
  const first=e.firstSight==='squad'?'They have not seen you yet.':e.firstSight==='both'?'Both sides saw each other at once.':'They saw you first.';
  encEl.innerHTML=`<h3>Raiders near ${esc(e.where.place)}</h3>
    <p>${esc(e.squad.name)} (${e.squad.people}) against ${e.enemy.count} raiders${e.enemy.boss?' with a boss':''}, ${e.distance} m off. ${first} ${LIGHT[e.light]}, ${e.tempC} °C.${e.forced?' There is no slipping away now.':''}</p>
    <div class="acts">${canDive(e)?'<button type="button" class="pri" data-a="dive">Go tactical</button>':''}<button type="button"${canDive(e)?'':' class="pri"'} data-a="auto" title="A rough outcome from head count and who saw whom first, until the tactical ground covers the whole corridor">Fight it out (quick)</button>
    ${e.forced?'':'<button type="button" data-a="avoid">Pull back</button><button type="button" data-a="hide">Lie low</button>'}</div>`; }
encEl.addEventListener('click',ev=>{ const b=ev.target.closest('[data-a]'); if(!b) return; const e=S().enc; if(!e) return;
  if(b.dataset.a==='dive'){ const sq=S().squads[e.squad.index]; sq.trip=null; sq.task=null; selSquad=e.squad.index; NF.encounter=e; pendingFight=e.id; save(true); NF.mapPose={yaw:camS.yaw,pitch:camS.pitch,dist:camS.dist};
    NF.enterTactical(sq.x,sq.z,{x:sq.x,z:sq.z,name:sq.name,people:sq.people,index:e.squad.index,encounter:e}); return; }
  C.resolve(b.dataset.a); changed(); });
let pendingFight=null;

// ---------- orders, saving ----------
let dirty=false, saveT=0;
function save(now){ if(now||dirty){ C.save(store); dirty=false; saveT=0; } }
function changed(){ dirty=true; syncViews(); syncBands(); drawSquads(); drawStock(); drawLog(); drawSky(); drawEncounter(); if(selSec) drawSector(); else drawPreview(); }
let knowDirty=false;
function apply(out){ if(!out||!out.elapsed&&!out.encounter) return; dirty=true; if(out.revealed) knowDirty=true; if(out.found) buildPins();
  if(out.encounter){ setSpeed(0); camT.tx=out.encounter.where.x; camT.tz=out.encounter.where.z; camT.dist=Math.min(camT.dist,7000); }
  syncViews(); syncBands(); drawEncounter(); if(out.arrived||out.found||out.encounter){ drawStock(); drawLog(); drawSquads(); if(selSec) drawSector(); } }
waitBtn.onclick=()=>{ const st=S(); if(st.waitUntil>st.minutes) st.waitUntil=0; else { C.waitTurn(); if(speed===0) setSpeed(1); } changed(); };
let armed=0; newBtn.onclick=()=>{ if(Date.now()-armed>3000){ armed=Date.now(); newBtn.textContent='Click again to start over'; setTimeout(()=>{ if(Date.now()-armed>=3000) newBtn.textContent='New campaign'; },3100); return; }
  armed=0; newBtn.textContent='New campaign'; C.forget(store); C.newGame(); selSec=null; secEl.innerHTML='<p class="empty">Click a sector on the map.</p>'; preview=null;
  knowDirty=true; lightFor(S().minutes); changed(); save(true); };
addEventListener('pagehide',()=>save(true)); document.addEventListener('visibilitychange',()=>{ if(document.hidden) save(true); });

// ---------- camera and input ----------
const camS={yaw:-.35,pitch:.62,dist:16000,tx:hx0*.4,tz:hz0*.4}, camT=Object.assign({},camS);
let Wd=1,Ht=1; function resize(){ Wd=stage.clientWidth; Ht=stage.clientHeight; renderer.setSize(Wd,Ht,false); cam.aspect=Wd/Math.max(1,Ht); cam.updateProjectionMatrix(); } new ResizeObserver(resize).observe(stage); resize();
const ray=new THREE.Raycaster(), ndc=new THREE.Vector2(); let drag=null;
const pick=e=>{ const r=renderer.domElement.getBoundingClientRect(); ndc.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1); ray.setFromCamera(ndc,cam); const h=ray.intersectObjects(terrains)[0]; return h?h.point:null; };
renderer.domElement.addEventListener('contextmenu',e=>e.preventDefault());
renderer.domElement.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,b:e.button,moved:false,yaw:camT.yaw,pitch:camT.pitch,tx:camT.tx,tz:camT.tz}; renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener('pointermove',e=>{ if(!drag){ const p=pick(e); const s=p&&secAt(p.x,p.z); if(String(s)!==String(hoverSec)){ hoverSec=s; drawMarks(); } return; }
  const dx=e.clientX-drag.x, dy=e.clientY-drag.y; if(Math.hypot(dx,dy)>4) drag.moved=true; if(!drag.moved) return;
  if(drag.b===2||e.shiftKey){ const k=camT.dist/900, c=Math.cos(camT.yaw), s=Math.sin(camT.yaw); camT.tx=drag.tx-(dx*c+dy*s)*k; camT.tz=drag.tz-(-dx*s+dy*c)*k; }
  else { camT.yaw=drag.yaw-dx*.005; camT.pitch=Math.max(.25,Math.min(1.4,drag.pitch+dy*.004)); } });
renderer.domElement.addEventListener('pointerup',e=>{ const d=drag; drag=null; if(!d||d.moved||d.b!==0) return; const p=pick(e); const s=p&&secAt(p.x,p.z); if(!s) return; selSec=s; drawMarks(); drawSector(); });
let push=0;
renderer.domElement.addEventListener('wheel',e=>{ e.preventDefault(); const want=camT.dist*Math.exp(e.deltaY*.0012);
  if(ZOOM&&want<1500 && camT.dist<=1520){ push+=-e.deltaY; if(push>240){ push=0; dive(camT.tx,camT.tz); } } else push=0;
  camT.dist=Math.max(1500,Math.min(260000,want)); },{passive:false});
function dive(x,z){ if(!NF.inBlock(x,z)){ NF.tip('Tactical ground is baked only inside the gold outline (New River and north of it) so far'); camT.tx=(NF.rect[0][0]+NF.rect[2][0])/2; camT.tz=(NF.rect[0][1]+NF.rect[2][1])/2; camT.dist=Math.max(camT.dist,3200); return; }
  if(S().enc){ NF.tip('Answer the encounter first'); return; }
  const sqs=S().squads, sq=sqs[selSquad], free=o=>!C.busy(o)&&NF.inBlock(o.x,o.z), here=free(sq)?sq:sqs.find(free);
  NF.encounter=null; NF.mapPose={yaw:camS.yaw,pitch:camS.pitch,dist:camS.dist}; NF.enterTactical(x,z,here?{x:here.x,z:here.z,name:here.name,people:here.people,index:sqs.indexOf(here)}:null); }
if(ZOOM){ renderer.domElement.addEventListener('dblclick',e=>{ const p=pick(e); if(p) dive(p.x,p.z); });
  document.getElementById('diveBtn').onclick=()=>{ const sq=S().squads[selSquad]; dive(NF.inBlock(sq.x,sq.z)?sq.x:camT.tx, NF.inBlock(sq.x,sq.z)?sq.z:camT.tz); }; }
document.getElementById('homeBtn').onclick=()=>{ camT.tx=hx0; camT.tz=hz0; camT.dist=6000; };
document.getElementById('realmBtn').onclick=()=>{ camT.tx=0; camT.tz=0; camT.dist=Math.max(HX,HZ)*2.6; camT.pitch=Math.max(camT.pitch,.75); };
let speed=1;   // 1× = 10 game minutes per real second
function setSpeed(v){ speed=v; document.querySelectorAll('.hud button[data-s]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.s===v))); }
document.querySelectorAll('.hud button[data-s]').forEach(b=>b.onclick=()=>setSpeed(+b.dataset.s));
if(resumed) setSpeed(0);   // a resumed campaign waits for the player

// ---------- frame loop ----------
syncViews(); syncBands(); buildBuildings(); buildPins(); drawOverlay(); drawSquads(); drawStock(); drawLog(); drawSky(); drawEncounter(); lightFor(S().minutes);
if(resumed){ C.note('Campaign resumed.'); drawLog(); }
const tmp=new THREE.Vector3(); let last=performance.now(), uiAcc=0, marksAt=16000;
function loop(now){
  requestAnimationFrame(loop); const dt=Math.min(.1,(now-last)/1000); last=now; if(ZOOM&&NF.mode!=='region') return;
  const st=S(), run=C.running()&&speed>0;
  if(run){ apply(C.step(dt*10*speed)); lightFor(st.minutes); }
  if(knowDirty){ knowDirty=false; drawOverlay(); buildPins(); buildBuildings(); }
  st.squads.forEach((s,i)=>{ const v=views[i]; v.mesh.position.set(s.x,Y(s.x,s.z),s.z); v.mesh.rotation.y+=dt*.6; });
  for(const [id,v] of bandViews) if(v.show) v.mesh.position.set(v.x,Y(v.x,v.z),v.z);
  uiAcc+=dt; if(uiAcc>.5){ uiAcc=0; drawSky(); if(run){ drawSquads(); syncBands(); } }
  saveT+=dt; if(saveT>2) save();
  const k=1-Math.exp(-dt*5); for(const key in camS){ if(key==='yaw'){ const d=Math.atan2(Math.sin(camT.yaw-camS.yaw),Math.cos(camT.yaw-camS.yaw)); camS.yaw+=d*k; } else camS[key]+=(camT[key]-camS[key])*k; }
  const ty=Y(camS.tx,camS.tz); cam.position.set(camS.tx+Math.sin(camS.yaw)*Math.cos(camS.pitch)*camS.dist, ty+Math.sin(camS.pitch)*camS.dist, camS.tz+Math.cos(camS.yaw)*Math.cos(camS.pitch)*camS.dist); cam.lookAt(camS.tx,ty,camS.tz); followView(camS.tx,ty,camS.tz,camS.dist);
  if(Math.abs(camS.dist-marksAt)/marksAt>.25){ marksAt=camS.dist; drawMarks(); }
  renderer.render(scene,cam);
  const place=(el,x,z,dy)=>{ tmp.set(x,Y(x,z)+dy,z).project(cam); const on=tmp.z<1&&Math.abs(tmp.x)<1.05&&Math.abs(tmp.y)<1.05; el.style.display=on?'':'none'; if(on) el.style.transform=`translate(${(tmp.x+1)/2*Wd}px,${(1-tmp.y)/2*Ht}px) translate(-50%,-100%)`; };
  for(const l of labels){ const show=l.kind==='peak'?camS.dist<40000&&Math.hypot(l.x-camS.tx,l.z-camS.tz)<camS.dist*2.5:l.far?camS.dist<l.far:true; if(!show){ l.el.style.display='none'; continue; } place(l.el,l.x,l.z,l.dy); }
  st.squads.forEach((s,i)=>{ const v=views[i]; place(v.el,s.x,s.z,260); const near=st.squads.slice(0,i).filter(o=>Math.hypot(o.x-s.x,o.z-s.z)<camS.dist*.04).length; if(near) v.el.style.transform+=` translateY(${near*-26}px)`; });
  for(const v of bandViews.values()) if(v.show) place(v.el,v.x,v.z,150);
}
requestAnimationFrame(loop);
// back from the tactical ground: the clock catches up (real time exploring, 5 minutes per fight turn that combat reports) and an encounter fought there is settled
function back(realSeconds,result){ const st=S();
  if(pendingFight&&st.enc&&st.enc.id===pendingFight) C.resolve('fought',result); pendingFight=null; NF.encounter=null;
  advanceBy(Math.max(0,realSeconds)*TAC_RATE/60+(result&&result.turns>0?result.turns*TURN_MIN:0)); knowDirty=true; changed(); save(true); }
// let a stretch of game time pass now, whether or not a squad is busy (other squads keep travelling)
function advanceBy(m){ const st=S(), keep=st.waitUntil; if(!(m>0)) return null; st.waitUntil=Math.max(keep,st.minutes+m); const out=C.step(m); st.waitUntil=keep>st.minutes?keep:0; apply(out); lightFor(st.minutes); drawSky(); return out; }
// ---------- for the tactical ground: the map's own painters, a live clock and the camera ----------
// S2: the realm's ground (elevation tint, scrub, land use, water, roads, hillshade) over any extent in region metres
let HMAX=0; for(const v of D.h) HMAX=Math.max(HMAX,v);
function groundTexture(ext,size=2048){ const [x0,z0,x1,z1]=ext, W=x1-x0, Hh=z1-z0, TX=W>=Hh?size:Math.round(size*W/Hh), TZ=W>=Hh?Math.round(size*Hh/W):size;
  const X=x=>(x-x0)/W*TX, Zc=z=>(z-z0)/Hh*TZ, px=TX/W, c=document.createElement('canvas'); c.width=TX; c.height=TZ; const g=c.getContext('2d');
  const n=Math.min(512,Math.max(64,Math.round(Math.max(W,Hh)/60))), nx=W>=Hh?n:Math.max(8,Math.round(n*W/Hh)), nz=W>=Hh?Math.max(8,Math.round(n*Hh/W)):n, sx=W/(nx-1), sz=Hh/(nz-1);
  const hs=new Float32Array(nx*nz); for(let j=0;j<nz;j++) for(let i=0;i<nx;i++) hs[j*nx+i]=hRaw(x0+i*sx,z0+j*sz);
  const img=g.createImageData(nx,nz), lo=[214,190,148], mid=[196,160,112], hi=[150,112,80], L=[-.5,.75,-.45], ll=Math.hypot(...L), flat=L[1]/ll;
  for(let j=0;j<nz;j++) for(let i=0;i<nx;i++){ const t=Math.max(0,Math.min(1,hs[j*nx+i]/HMAX)), a=t<.5?lo:mid, b=t<.5?mid:hi, k=t<.5?t*2:(t-.5)*2, o=(j*nx+i)*4;
    const h=(p,q)=>hs[Math.min(nz-1,Math.max(0,q))*nx+Math.min(nx-1,Math.max(0,p))]*VE, dx=(h(i+1,j)-h(i-1,j))/(2*sx), dz=(h(i,j+1)-h(i,j-1))/(2*sz), nn=[-dx,1,-dz], nl=Math.hypot(...nn), v=((nn[0]*L[0]+nn[1]*L[1]+nn[2]*L[2])/(nl*ll)-flat)*2.4;
    for(let q=0;q<3;q++){ let cch=a[q]+(b[q]-a[q])*k; cch=v<0?cch*(1-Math.min(.55,-v)*.6):cch+(255-cch)*Math.min(.35,v)*.5; img.data[o+q]=cch; } img.data[o+3]=255; }
  const tc=document.createElement('canvas'); tc.width=nx; tc.height=nz; tc.getContext('2d').putImageData(img,0,0); g.imageSmoothingEnabled=true; g.drawImage(tc,0,0,TX,TZ);
  const r=(q=>()=>{ q=(Math.imul(q,1664525)+1013904223)>>>0; return q/4294967296; })(Math.round(x0*7+z0*3)>>>0);
  for(let i=0;i<TX*TZ/70;i++){ g.fillStyle=r()<.5?'rgba(110,90,60,.22)':'rgba(120,140,70,.18)'; g.fillRect(r()*TX,r()*TZ,1.4,1.4); }
  const over=b=>b[2]>=x0&&b[0]<=x1&&b[3]>=z0&&b[1]<=z1;
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  const line=(pts,w,col,dash)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.lineWidth=Math.max(.7,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.setLineDash(dash||[]); g.stroke(); g.setLineDash([]); };
  for(const a of R.areas) if(AC[a.kind]&&over(a.bb||(a.bb=bboxOf(a.pts)))) poly(a.pts,AC[a.kind]);
  for(const w of R.water) if(over(w.bb||(w.bb=bboxOf(w.pts)))){ const big=w.kind==='river'; line(w.pts,big?60:22,'#b39c78'); line(w.pts,big?40:12,'#e3d2ad'); }
  for(const l of R.lakes) if(over(l.bb||(l.bb=bboxOf(l.pts)))) poly(l.pts,'#4aa6c8');
  const edges=groundTexture.edges||(groundTexture.edges=R.graph.edges.filter(e=>RW[e[3]]&&e[3]!=='residential'&&e[3]!=='track').map(e=>({cls:e[3],dirt:!!e[5],pts:[R.graph.nodes[e[0]],...e[4],R.graph.nodes[e[1]]]})));
  const byCls=new Map(); for(const rd of [...edges,...(DF?R.roads:[])]){ if(!over(rd.bb||(rd.bb=bboxOf(rd.pts)))) continue; if(!byCls.has(rd.cls)) byCls.set(rd.cls,[]); byCls.get(rd.cls).push(rd); }
  for(const k of ORDER) for(const rd of byCls.get(k)||[]){ const w=RW[k]||8; if(rd.dirt) line(rd.pts,w,'#a88d68',k==='track'?[w*px*2,w*px*1.4]:null); else line(rd.pts,w,k==='motorway'?'#3b3a38':'#5e5a54'); }
  return c; }
// S1: the sector grid, knowledge, home, the selected sector and squad routes on any 2D canvas; toCanvas maps region metres to pixels
function paintKnowledge(ctx,toCanvas,ext){ const st=S(), [x0,z0,x1,z1]=ext||[-HX,-HZ,HX,HZ];
  const c0=Math.max(0,Math.floor((x0+HX)/SEC)), c1=Math.min(R.cols-1,Math.floor((x1+HX)/SEC)), r0=Math.max(0,Math.floor((z0+HZ)/SEC)), r1=Math.min(R.rows-1,Math.floor((z1+HZ)/SEC));
  const quad=(c,r,inset=0)=>{ const a=-HX+c*SEC+inset, b=-HZ+r*SEC+inset, e=SEC-2*inset; return [[a,b],[a+e,b],[a+e,b+e],[a,b+e]].map(([x,z])=>toCanvas(x,z)); };
  const path=q=>{ ctx.beginPath(); q.forEach(([px,py],i)=>i?ctx.lineTo(px,py):ctx.moveTo(px,py)); ctx.closePath(); };
  for(let r=r0;r<=r1;r++) for(let c=c0;c<=c1;c++){ const kk=st.know[r][c], q=quad(c,r);
    if(kk.k===K.UNKNOWN){ path(q); ctx.fillStyle='rgba(38,34,30,.34)'; ctx.fill(); ctx.save(); path(q); ctx.clip(); ctx.strokeStyle='rgba(30,26,22,.35)'; ctx.lineWidth=Math.max(1,Math.hypot(q[1][0]-q[0][0],q[1][1]-q[0][1])/110);
      const n=6; for(let k=-n;k<=n;k++){ const a=[q[0][0]+(q[1][0]-q[0][0])*k/n,q[0][1]+(q[1][1]-q[0][1])*k/n]; ctx.beginPath(); ctx.moveTo(a[0]+(q[3][0]-q[0][0]),a[1]+(q[3][1]-q[0][1])); ctx.lineTo(a[0]+(q[1][0]-q[0][0]),a[1]+(q[1][1]-q[0][1])); ctx.stroke(); } ctx.restore(); }
    else if(kk.k===K.RUMOUR){ path(q); ctx.fillStyle='rgba(60,52,44,.18)'; ctx.fill(); }
    else if(C.stale(kk)){ path(q); ctx.fillStyle='rgba(60,52,44,.16)'; ctx.fill(); }
    path(q); ctx.strokeStyle='rgba(40,32,24,.35)'; ctx.lineWidth=1; ctx.stroke(); }
  const outline=(s,col,w)=>{ if(!s) return; const q=quad(s[0],s[1],8); path(q); ctx.strokeStyle=col; ctx.lineWidth=w; ctx.stroke(); };
  outline(home,'#3fae7f',3); outline(selSec,'#e0a526',3);
  st.squads.forEach(sq=>{ if(!sq.trip) return; ctx.beginPath(); sq.trip.pts.forEach(([x,z],i)=>{ const [px,py]=toCanvas(x,z); i?ctx.lineTo(px,py):ctx.moveTo(px,py); }); ctx.strokeStyle=sq.c; ctx.globalAlpha=.85; ctx.lineWidth=3; ctx.setLineDash([8,5]); ctx.stroke(); ctx.setLineDash([]); ctx.globalAlpha=1; }); }
// S3: the live clock while a squad is on the ground; the map redraws when it is shown again
function liveTick(minutes,opts){ const out=C.tick(minutes,opts); dirty=true; if(out.revealed||out.found) knowDirty=true; if(out.encounter){ camT.tx=out.encounter.where.x; camT.tz=out.encounter.where.z; } lightFor(S().minutes); return out; }
// S4: take the ground's camera where it left off, slightly higher, then ease out
function takePose(p){ camS.tx=camT.tx=p.x; camS.tz=camT.tz=p.z; camS.yaw=camT.yaw=p.yaw; camS.pitch=camT.pitch=Math.max(.25,Math.min(1.4,p.pitch)); camS.dist=1500; camT.dist=Math.max(2400,p.dist*3); }
window.__region={get squads(){ return S().squads; }, get know(){ return S().know; }, campaign:C, setSpeed, camT, secCentre, back,
  route:(x0,z0,x1,z1)=>C.route(x0,z0,x1,z1), send:(i,x,z)=>{ const t=C.send(i,x,z); changed(); return t; },
  focus:(x,z)=>{ camT.tx=x; camT.tz=z; camT.dist=2400; camS.tx=x; camS.tz=z; camS.dist=1600; },
  placeSquad:(i,x,z,people)=>{ const s=S().squads[i]; s.x=x; s.z=z; s.trip=null; if(people!==undefined){ s.people=people; s.water=Math.min(s.water,C.waterCap(s)); } C.reveal(x,z); C.refreshCurrent(); drawOverlay(); buildPins(); buildBuildings(); changed(); },
  advance:advanceBy,
  save:()=>save(true), resize, groundTexture, paintKnowledge, tick:liveTick, takePose, changed:()=>{ knowDirty=true; changed(); }, get pose(){ return {...camS}; }, select:(c,r)=>{ selSec=[c,r]; drawMarks(); drawSector(); }};
})();
