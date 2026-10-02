(function(){
const R=REGION, stage=document.getElementById('rstage'), labelsEl=document.getElementById('rlabels');
if(!window.THREE){ stage.insertAdjacentHTML('beforeend','<p class="fail">The 3D view needs three.js, which could not load. Check your connection and reload.</p>'); return; }
let renderer; try{ renderer=new THREE.WebGLRenderer({antialias:true}); }catch(e){ stage.insertAdjacentHTML('beforeend','<p class="fail">This browser could not start WebGL.</p>'); return; }
renderer.setPixelRatio(Math.min(2,devicePixelRatio||1)); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; stage.prepend(renderer.domElement);
const TAU=Math.PI*2, VE=1.6, SEC=R.sector, D=R.dem, HX=R.half[0], HZ=R.half[1];
const scene=new THREE.Scene(), cam=new THREE.PerspectiveCamera(36,1,10,200000);
scene.fog=new THREE.Fog(0xd9c9a8,30000,90000); renderer.setClearColor(0xd9c9a8);
const hemi=new THREE.HemisphereLight(0xfff3e0,0x6a5a48,.55), sun=new THREE.DirectionalLight(0xfff0d8,1); sun.castShadow=true; sun.shadow.mapSize.set(4096,4096); sun.shadow.bias=-.0006; sun.shadow.normalBias=8;
Object.assign(sun.shadow.camera,{left:-26000,right:26000,top:26000,bottom:-26000,near:100,far:120000}); scene.add(hemi,sun,sun.target);
const KIND={food:'#e0a33a',medicine:'#d9534f',tools:'#5b8fd1',fuel:'#a66bd1',gear:'#3fae7f',water:'#3fb6d9',shelter:'#8f8f8f',goods:'#b9a27a'};
const KLABEL={food:'Food',medicine:'Medicine',tools:'Tools',fuel:'Fuel',gear:'Gear',water:'Water',shelter:'Shelter',goods:'Goods'};
document.getElementById('siteKey').innerHTML=Object.keys(KIND).map(k=>`<li><i style="background:${KIND[k]}"></i>${KLABEL[k]}</li>`).join('');

// ---------- terrain ----------
const hRaw=(x,z)=>{ const fx=(x-D.x0)/D.step, fz=(z-D.z0)/D.step, i=Math.max(0,Math.min(D.nx-2,Math.floor(fx))), j=Math.max(0,Math.min(D.nz-2,Math.floor(fz))), u=Math.min(1,Math.max(0,fx-i)), v=Math.min(1,Math.max(0,fz-j)), h=(a,b)=>D.h[b*D.nx+a];
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; };
const Y=(x,z)=>hRaw(x,z)*VE;
const elevM=(x,z)=>Math.round(hRaw(x,z)+D.base);
const W=(D.nx-1)*D.step, Hh=(D.nz-1)*D.step;
const geo=new THREE.PlaneGeometry(W,Hh,D.nx-1,D.nz-1); geo.rotateX(-Math.PI/2);
{ const p=geo.attributes.position; for(let i=0;i<p.count;i++) p.setY(i,D.h[i]*VE); geo.computeVertexNormals(); }
const TX=2048, TZ=Math.round(2048*Hh/W);
const X=x=>(x-D.x0)/W*TX, Zc=z=>(z-D.z0)/Hh*TZ, px=TX/W;
function groundTex(){
  const c=document.createElement('canvas'); c.width=TX; c.height=TZ; const g=c.getContext('2d');
  // elevation tint: valley sand to ochre ridges
  const img=g.createImageData(D.nx,D.nz); let hmax=0; for(const v of D.h) hmax=Math.max(hmax,v);
  const lo=[214,190,148], mid=[196,160,112], hi=[150,112,80];
  for(let j=0;j<D.nz;j++) for(let i=0;i<D.nx;i++){ const t=D.h[j*D.nx+i]/hmax, a=t<.5?lo:mid, b=t<.5?mid:hi, k=t<.5?t*2:(t-.5)*2, o=(j*D.nx+i)*4;
    for(let q=0;q<3;q++) img.data[o+q]=a[q]+(b[q]-a[q])*k; img.data[o+3]=255; }
  const tc=document.createElement('canvas'); tc.width=D.nx; tc.height=D.nz; tc.getContext('2d').putImageData(img,0,0); g.imageSmoothingEnabled=true; g.drawImage(tc,0,0,TX,TZ);
  const r=(s=>()=>{ s=(Math.imul(s,1664525)+1013904223)>>>0; return s/4294967296; })(7);
  for(let i=0;i<60000;i++){ g.fillStyle=r()<.5?'rgba(110,90,60,.22)':'rgba(120,140,70,.18)'; g.fillRect(r()*TX,r()*TZ,1.4,1.4); }   // desert scrub
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  const line=(pts,w,col,dash)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Zc(z)):g.moveTo(X(x),Zc(z))); g.lineWidth=Math.max(.8,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.setLineDash(dash||[]); g.stroke(); g.setLineDash([]); };
  const AC={residential:'#cdbb98',retail:'#a9a49a',commercial:'#a9a49a',industrial:'#a39a8c',farmland:'#9caf62',farmyard:'#b8a77a'};
  for(const a of R.areas) if(AC[a.kind]) poly(a.pts,AC[a.kind]);
  for(const w of R.water){ const big=w.kind==='river'; line(w.pts,big?60:22,'#b39c78'); line(w.pts,big?40:12,'#e3d2ad'); }
  for(const l of R.lakes) poly(l.pts,'#4aa6c8');
  const RW={motorway:34,trunk:24,primary:20,secondary:16,tertiary:13,motorway_link:10,unclassified:10,residential:8,track:6};
  const order=['track','residential','unclassified','tertiary','secondary','primary','trunk','motorway_link','motorway'];
  for(const k of order) for(const rd of R.roads) if(rd.cls===k){ const w=RW[k]||8;
    if(rd.dirt) line(rd.pts,w,'#a88d68',k==='track'?[w*px*2,w*px*1.4]:null); else { if(w>12) line(rd.pts,w+8,'#e8dcc4'); line(rd.pts,w,k==='motorway'?'#3b3a38':'#5e5a54'); } }
  // hillshade from the north-west
  const sh=document.createElement('canvas'); sh.width=D.nx; sh.height=D.nz; const sg=sh.getContext('2d'), si=sg.createImageData(D.nx,D.nz), L=[-.5,.75,-.45], ll=Math.hypot(...L), flat=L[1]/ll;
  for(let j=0;j<D.nz;j++) for(let i=0;i<D.nx;i++){ const h=(a,b)=>D.h[Math.min(D.nz-1,Math.max(0,b))*D.nx+Math.min(D.nx-1,Math.max(0,a))]*VE, dx=(h(i+1,j)-h(i-1,j))/(2*D.step), dz=(h(i,j+1)-h(i,j-1))/(2*D.step);
    const n=[-dx,1,-dz], nl=Math.hypot(...n), v=((n[0]*L[0]+n[1]*L[1]+n[2]*L[2])/(nl*ll)-flat)*2.4, o=(j*D.nx+i)*4;
    if(v<0){ si.data[o]=70; si.data[o+1]=40; si.data[o+2]=20; si.data[o+3]=Math.min(.55,-v)*255; } else { si.data[o]=255; si.data[o+1]=246; si.data[o+2]=225; si.data[o+3]=Math.min(.35,v)*255; } }
  sg.putImageData(si,0,0); g.drawImage(sh,0,0,TX,TZ);
  const t=new THREE.CanvasTexture(c); t.anisotropy=renderer.capabilities.getMaxAnisotropy(); return t; }
const terrain=new THREE.Mesh(geo,new THREE.MeshStandardMaterial({map:groundTex(), flatShading:true, roughness:.95, metalness:0}));
terrain.position.set(D.x0+W/2,0,D.z0+Hh/2); terrain.receiveShadow=true; scene.add(terrain);
const skirt=new THREE.Mesh(new THREE.PlaneGeometry(400000,400000),new THREE.MeshStandardMaterial({color:0xc4aa82, roughness:1})); skirt.rotation.x=-Math.PI/2; skirt.position.y=-20; scene.add(skirt);

// ---------- knowledge and the sector overlay ----------
const K={UNKNOWN:0,RUMOUR:1,SCOUT:2,CURRENT:3}, KN=['Unknown','Rumoured','Scouted','Current'];
const know=R.sectors.map(row=>row.map(()=>({k:0,seen:0})));
const secAt=(x,z)=>{ const c=Math.floor((x+HX)/SEC), r=Math.floor((z+HZ)/SEC); return c>=0&&r>=0&&c<R.cols&&r<R.rows?[c,r]:null; };
const secCentre=(c,r)=>[-HX+(c+.5)*SEC, -HZ+(r+.5)*SEC];
const OC=document.createElement('canvas'); OC.width=TX; OC.height=TZ; const og=OC.getContext('2d'); const otex=new THREE.CanvasTexture(OC);
const overlay=new THREE.Mesh(geo,new THREE.MeshBasicMaterial({map:otex, transparent:true, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-4, polygonOffsetUnits:-4}));
overlay.position.copy(terrain.position); overlay.renderOrder=2; scene.add(overlay);
const hatch=(()=>{ const c=document.createElement('canvas'); c.width=c.height=16; const g=c.getContext('2d'); g.strokeStyle='rgba(30,26,22,.35)'; g.lineWidth=1.4; g.beginPath(); g.moveTo(0,16); g.lineTo(16,0); g.stroke(); return og.createPattern(c,'repeat'); })();
let hoverSec=null, selSec=null, clockDay=1;
function drawOverlay(){
  og.clearRect(0,0,TX,TZ);
  // outside the region: a soft vignette
  og.fillStyle='rgba(40,34,28,.35)'; og.fillRect(0,0,TX,TZ); og.clearRect(X(-HX),Zc(-HZ),X(HX)-X(-HX),Zc(HZ)-Zc(-HZ));
  for(let r=0;r<R.rows;r++) for(let c=0;c<R.cols;c++){ const kk=know[r][c], x0=X(-HX+c*SEC), z0=Zc(-HZ+r*SEC), w=SEC*px+.6;
    if(kk.k===K.UNKNOWN){ og.fillStyle='rgba(38,34,30,.34)'; og.fillRect(x0,z0,w,w); og.fillStyle=hatch; og.fillRect(x0,z0,w,w); }
    else if(kk.k===K.RUMOUR){ og.fillStyle='rgba(60,52,44,.18)'; og.fillRect(x0,z0,w,w); }
    else if(kk.k===K.SCOUT){ const age=clockDay-kk.seen; if(age>=3){ og.fillStyle='rgba(60,52,44,.16)'; og.fillRect(x0,z0,w,w); } } }
  og.strokeStyle='rgba(40,32,24,.22)'; og.lineWidth=1; og.beginPath();
  for(let c=0;c<=R.cols;c++){ og.moveTo(X(-HX+c*SEC),Zc(-HZ)); og.lineTo(X(-HX+c*SEC),Zc(HZ)); }
  for(let r=0;r<=R.rows;r++){ og.moveTo(X(-HX),Zc(-HZ+r*SEC)); og.lineTo(X(HX),Zc(-HZ+r*SEC)); } og.stroke();
  og.setLineDash([10,6]); og.strokeStyle='#e0a526'; og.lineWidth=3; og.beginPath(); NF.rect.forEach(([x,z],i)=>i?og.lineTo(X(x),Zc(z)):og.moveTo(X(x),Zc(z))); og.closePath(); og.stroke(); og.setLineDash([]);
  const box=(s,col,w)=>{ if(!s) return; og.strokeStyle=col; og.lineWidth=w; og.strokeRect(X(-HX+s[0]*SEC)+w/2,Zc(-HZ+s[1]*SEC)+w/2,SEC*px-w,SEC*px-w); };
  box(home,'#3fae7f',3); box(hoverSec,'rgba(255,250,235,.9)',2); box(selSec,'#e0a526',3.5);
  otex.needsUpdate=true; }

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
function buildBuildings(){
  if(bMesh){ scene.remove(bMesh); scene.remove(bInkMesh); }
  const list=R.buildings.filter(b=>{ const s=secAt(b[0],b[1]); return s && know[s[1]][s[0]].k>=K.RUMOUR; });
  bMesh=new THREE.InstancedMesh(boxG,bMat,Math.max(1,list.length)); bInkMesh=new THREE.InstancedMesh(boxG,bInk,Math.max(1,list.length));
  const m=new THREE.Matrix4(), q=new THREE.Quaternion(), col=new THREE.Color(), TONES=[0xe2cfae,0xd6bf9a,0xcfb48e,0xb5653f,0xbfa182];
  list.forEach((b,i)=>{ const hh=(b[2]*b[3]>600?7:4.5)*VE; m.compose(new THREE.Vector3(b[0],Y(b[0],b[1])-1,b[1]),q,new THREE.Vector3(b[2],hh,b[3])); bMesh.setMatrixAt(i,m); bInkMesh.setMatrixAt(i,m); bMesh.setColorAt(i,col.setHex(TONES[(Math.abs(b[0]*7+b[1]*13))%TONES.length])); });
  bMesh.count=bInkMesh.count=list.length; bMesh.castShadow=true; scene.add(bMesh,bInkMesh); }
const lab=(cls,html)=>{ const e=document.createElement('div'); e.className='lb '+cls; e.innerHTML=html; labelsEl.appendChild(e); return e; };
const labels=[];
for(const p of R.places) if(['town','village','hamlet','city'].includes(p.kind)) labels.push({el:lab('town',p.name),x:p.p[0],z:p.p[1],dy:120,kind:'town'});
for(const p of R.peaks) if(p.name) labels.push({el:lab('peak',`${p.name}<small>${Math.round(p.h*3.281).toLocaleString()} ft</small>`),x:p.p[0],z:p.p[1],dy:60,kind:'peak'});
{ const mw=R.roads.filter(r=>r.cls==='motorway'); if(mw.length){ const r=mw[Math.floor(mw.length/2)], p=r.pts[Math.floor(r.pts.length/2)]; labels.push({el:lab('road','I-17'),x:p[0],z:p[1],dy:40,kind:'road'}); } }
// site pins
const pinG=new THREE.OctahedronGeometry(1,0), pins=new THREE.Group(); scene.add(pins);
const pinInk=inkMat(0x1d1814,.0016);
function buildPins(){ while(pins.children.length) pins.remove(pins.children[0]);
  for(const s of R.sites){ const kk=know[s.sector[1]][s.sector[0]].k; if(kk<K.RUMOUR) continue; const known=kk>=K.SCOUT;
    const m=new THREE.Mesh(pinG,new THREE.MeshStandardMaterial({color:known?KIND[s.loot]:'#7d7468', flatShading:true})); m.scale.set(26,40,26); m.position.set(s.p[0],Y(s.p[0],s.p[1])+70,s.p[1]); m.add(new THREE.Mesh(pinG,pinInk)); m.userData.site=s; pins.add(m); } }

// ---------- travel graph ----------
const G=R.graph, adj=G.nodes.map(()=>[]);
const SPEED={motorway:5,motorway_link:5,trunk:5,primary:5,secondary:5,tertiary:5,unclassified:5,residential:5,track:4}, OFF=2.5;
for(const [a,b,len,cls] of G.edges){ const sp=SPEED[cls]||4, t=len/1000/sp; adj[a].push([b,t,len]); adj[b].push([a,t,len]); }
function nearestNodes(x,z,k=6){ const best=[]; G.nodes.forEach(([nx,nz],i)=>{ if(!adj[i].length) return; const d=Math.hypot(nx-x,nz-z); if(best.length<k||d<best[best.length-1][1]){ best.push([i,d]); best.sort((a,b)=>a[1]-b[1]); if(best.length>k) best.pop(); } }); return best; }
const offTime=(x0,z0,x1,z1)=>{ const d=Math.hypot(x1-x0,z1-z0), climb=Math.max(0,hRaw(x1,z1)-hRaw(x0,z0)); return d/1000/OFF+climb/300; };   // a rule of thumb: +1 h per 300 m climbed
function route(x0,z0,x1,z1){
  const direct=offTime(x0,z0,x1,z1), A=nearestNodes(x0,z0), B=new Map(nearestNodes(x1,z1).map(([i,d])=>[i,d]));
  const dist=new Map(), prev=new Map(), heap=[]; const push=(i,t)=>{ heap.push([t,i]); heap.sort((a,b)=>a[0]-b[0]); };
  for(const [i] of A){ const [nx,nz]=G.nodes[i], t=offTime(x0,z0,nx,nz); if(!dist.has(i)||t<dist.get(i)){ dist.set(i,t); push(i,t); } }
  let best=direct, bestEnd=-1;
  while(heap.length){ const [t,i]=heap.shift(); if(t>dist.get(i)||t>=best) continue;
    if(B.has(i)){ const [nx,nz]=G.nodes[i], tt=t+offTime(nx,nz,x1,z1); if(tt<best){ best=tt; bestEnd=i; } }
    for(const [j,et] of adj[i]){ const nt=t+et; if(!dist.has(j)||nt<dist.get(j)){ dist.set(j,nt); prev.set(j,i); push(j,nt); } } }
  const pts=[[x1,z1]]; if(bestEnd>=0){ let i=bestEnd; while(i!==undefined){ pts.push(G.nodes[i]); i=prev.get(i); } } pts.push([x0,z0]); pts.reverse();
  let km=0; for(let i=1;i<pts.length;i++) km+=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])/1000;
  return {pts, hours:best, km}; }

// ---------- squads ----------
const home=secAt(R.home[0]+700,R.home[1]);   // just east of New River, on the ranch side
const [hx0,hz0]=secCentre(...home);
const squads=[{name:'Ranch party',people:4,c:'#e0a526',x:hx0,z:hz0},{name:'Scouts',people:2,c:'#5b9fc4',x:hx0+120,z:hz0+80}];
const tokG=(()=>{ const g=new THREE.CylinderGeometry(55,70,30,6); g.translate(0,15,0); const p=new THREE.ConeGeometry(45,150,6); p.translate(0,105,0); const pos=[]; for(const gg of [g,p]){ const n=gg.toNonIndexed(); pos.push(...n.attributes.position.array); } const out=new THREE.BufferGeometry(); out.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); out.computeVertexNormals(); return out; })();
let selSquad=0;
for(const s of squads){ s.mesh=new THREE.Mesh(tokG,new THREE.MeshStandardMaterial({color:s.c, flatShading:true})); s.ink=inkMat(0x1d1814,.0022); s.mesh.add(new THREE.Mesh(tokG,s.ink)); s.mesh.castShadow=true; scene.add(s.mesh);
  s.el=lab('sq',s.name); s.el.style.setProperty('--c',s.c); s.path=null; s.line=null; }
function reveal(x,z){ const s=secAt(x,z); if(!s) return; const [c,r]=s, me=R.sectors[r][c];
  let around=0,n=0; for(let dr=-3;dr<=3;dr++) for(let dc=-3;dc<=3;dc++){ const q=R.sectors[r+dr]?.[c+dc]; if(q){ around+=q.lo; n++; } }
  const rad=Math.min(3,1+Math.floor(Math.max(0,me.hi-around/n)/45));   // high ground sees further
  for(let dr=-rad;dr<=rad;dr++) for(let dc=-rad;dc<=rad;dc++){ const kk=know[r+dr]?.[c+dc]; if(!kk) continue; if(Math.hypot(dr,dc)>rad+.4) continue; if(kk.k<K.SCOUT){ kk.k=K.SCOUT; } kk.seen=clockDay; }
  return rad; }
function refreshCurrent(){ for(const row of know) for(const k of row) if(k.k===K.CURRENT) k.k=K.SCOUT;
  const mark=s=>{ const q=secAt(s.x,s.z); if(q) know[q[1]][q[0]].k=K.CURRENT; }; squads.forEach(mark); know[home[1]][home[0]].k=K.CURRENT; }
// starting knowledge: home and its surroundings, rumours of the towns
for(const p of R.places) if(['town','village','hamlet'].includes(p.kind)){ const s=p.sector; for(let dr=-2;dr<=2;dr++) for(let dc=-2;dc<=2;dc++){ const kk=know[s[1]+dr]?.[s[0]+dc]; if(kk) kk.k=Math.max(kk.k,K.RUMOUR); } }
// you know the land around the ranch; further out you have only heard things
{ const [c,r]=home; for(let dr=-7;dr<=7;dr++) for(let dc=-7;dc<=7;dc++){ const kk=know[r+dr]?.[c+dc], d=Math.hypot(dr,dc); if(!kk||d>7.4) continue; if(d<=3.4){ kk.k=K.SCOUT; kk.seen=1; } else kk.k=Math.max(kk.k,K.RUMOUR); } }
reveal(hx0,hz0); refreshCurrent();

// ---------- clock ----------
let minutes=7*60+30, speed=1;  // game minutes; 1× = 10 game minutes per real second
const clockEl=document.getElementById('clock');
const fmtT=m=>{ const d=Math.floor(m/1440)+1, h=Math.floor(m%1440/60), mm=Math.floor(m%60); return `Day ${d} ${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}`; };
function waterFor(startMin,hours,people){ let L=0; for(let t=0;t<hours;t+=.25){ const h=((startMin/60+t)%24); L+=(h>=10&&h<18?1:.5)*.25; } return L*people; }
function lightFor(m){ const h=(m%1440)/60, day=Math.max(0,Math.sin((h-6)/12*Math.PI)), az=(h-6)/12*Math.PI;
  sun.intensity=.3+day*.85; hemi.intensity=.42+day*.3; sun.color.setHSL(.08,.6,.55+day*.35); hemi.color.setHSL(.08+(1-day)*.5,.35,.62+day*.25);
  const night=1-Math.min(1,day*3); renderer.setClearColor(new THREE.Color(0xd9c9a8).lerp(new THREE.Color(0x2a3248),night*.7)); scene.fog.color.copy(renderer.getClearColor(new THREE.Color()));
  sun.position.set(Math.cos(az)*40000,8000+day*50000,-12000+Math.sin(az)*6000); sun.target.position.set(0,0,0); }

// ---------- panel ----------
const secEl=document.getElementById('sector'), sqEl=document.getElementById('squads');
function nearestPlace(x,z){ let best=null,bd=1e12; for(const p of R.places){ const d=Math.hypot(p.p[0]-x,p.p[1]-z); if(d<bd){ bd=d; best=p; } } return best?(bd<1500?best.name:`${(bd/1609).toFixed(1)} mi from ${best.name}`):'open desert'; }
function drawSquads(){ sqEl.innerHTML=squads.map((s,i)=>{ const q=secAt(s.x,s.z); const st=s.path?`moving · ${Math.max(0,(s.arrive-minutes)/60).toFixed(1)} h left`:`at ${q?nearestPlace(s.x,s.z):'?'}`;
  return `<button type="button" class="sqb" data-i="${i}" aria-pressed="${i===selSquad}"><b><span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${s.c};margin-right:7px"></span>${s.name}</b><span>${s.people} people · ${st}</span></button>`; }).join(''); }
sqEl.addEventListener('click',e=>{ const b=e.target.closest('.sqb'); if(!b) return; selSquad=+b.dataset.i; squads.forEach((s,i)=>s.ink.color.setHex(i===selSquad?0xe0a526:0x1d1814)); drawSquads(); if(selSec) drawSector(); });
squads.forEach((s,i)=>s.ink.color.setHex(i===selSquad?0xe0a526:0x1d1814));
let preview=null;
function drawSector(){
  const [c,r]=selSec, s=R.sectors[r][c], kk=know[r][c], [cx,cz]=secCentre(c,r), known=kk.k>=K.SCOUT;
  const sites=s.sites.map(i=>R.sites[i]);
  const sq=squads[selSquad], rt=route(sq.x,sq.z,cx,cz); preview=rt; drawPreview();
  const water=waterFor(minutes,rt.hours,sq.people), TYPE={town:'Town',homes:'Scattered homes',rough:'Rough hills',desert:'Open desert'};
  secEl.innerHTML=`<h2>Sector ${String.fromCharCode(65+c%26)}${c>=26?String.fromCharCode(65+Math.floor(c/26)-1):''}-${r+1}</h2><h3>${(t=>t[0].toUpperCase()+t.slice(1))(nearestPlace(cx,cz))}</h3>
   <dl><div><dt>Knowledge</dt><dd>${KN[kk.k]}${kk.k===K.SCOUT&&clockDay-kk.seen>=3?' (stale)':''}</dd></div>
   <div><dt>Ground</dt><dd>${kk.k>=K.RUMOUR?TYPE[s.type]:'?'}</dd></div>
   <div><dt>Elevation</dt><dd>${Math.round(s.lo*3.281).toLocaleString()}–${Math.round(s.hi*3.281).toLocaleString()} ft</dd></div>
   <div><dt>Buildings</dt><dd>${kk.k>=K.RUMOUR?s.b:'?'}</dd></div>
   <div><dt>Sites</dt><dd>${known?sites.length:kk.k===K.RUMOUR&&sites.length?'some':'?'}</dd></div></dl>
   ${known&&sites.length?`<ul class="sites">${sites.slice(0,40).map(t=>`<li><i style="background:${KIND[t.loot]}"></i>${t.name||t.what.replace(/_/g,' ')}<span style="margin-left:auto;color:var(--muted);font-size:12px">${KLABEL[t.loot]}</span></li>`).join('')}</ul>`:''}
   <button type="button" class="go" id="goBtn" ${sq.path?'disabled':''}>Send ${sq.name} here</button>
   <p class="eta">${rt.km.toFixed(1)} km · ${rt.hours.toFixed(1)} h · ${water.toFixed(1)} L water${(()=>{ const h=(minutes%1440)/60; return h>=10&&h<18?' · midday heat doubles water use':''; })()}</p>`;
  document.getElementById('goBtn').onclick=()=>send(sq,rt); }
// route ribbon on the terrain
const routeMat=new THREE.MeshBasicMaterial({color:0xe0a526, transparent:true, opacity:.9, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-6, polygonOffsetUnits:-6});
function ribbon(pts,w,mat){ const dense=[]; for(let i=0;i<pts.length-1;i++){ const a=pts[i], b=pts[i+1], n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/60)); for(let k=0;k<n;k++) dense.push([a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n]); } dense.push(pts[pts.length-1]);
  const pos=[]; for(let i=0;i<dense.length-1;i++){ const a=dense[i], b=dense[i+1], dx=b[0]-a[0], dz=b[1]-a[1], l=Math.hypot(dx,dz)||1, nx=-dz/l*w, nz=dx/l*w, ya=Y(a[0],a[1])+6, yb=Y(b[0],b[1])+6;
    pos.push(a[0]+nx,ya,a[1]+nz, b[0]+nx,yb,b[1]+nz, b[0]-nx,yb,b[1]-nz, a[0]+nx,ya,a[1]+nz, b[0]-nx,yb,b[1]-nz, a[0]-nx,ya,a[1]-nz); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); const m=new THREE.Mesh(g,mat); m.renderOrder=3; return m; }
let prevMesh=null;
function drawPreview(){ if(prevMesh){ scene.remove(prevMesh); prevMesh.geometry.dispose(); prevMesh=null; } if(preview && !squads[selSquad].path){ prevMesh=ribbon(preview.pts,22,routeMat); scene.add(prevMesh); } }
function send(sq,rt){ sq.path=rt.pts; sq.seg=0; sq.depart=minutes; sq.arrive=minutes+rt.hours*60; sq.total=rt.hours*60;
  // time along the polyline is spread by distance
  const L=[0]; for(let i=1;i<rt.pts.length;i++) L.push(L[i-1]+Math.hypot(rt.pts[i][0]-rt.pts[i-1][0],rt.pts[i][1]-rt.pts[i-1][1])); sq.L=L;
  sq.line=ribbon(rt.pts,14,new THREE.MeshBasicMaterial({color:new THREE.Color(sq.c), transparent:true, opacity:.75, depthWrite:false, polygonOffset:true, polygonOffsetFactor:-6, polygonOffsetUnits:-6})); scene.add(sq.line);
  if(speed===0) setSpeed(1); drawPreview(); drawSquads(); drawSector(); }

// ---------- camera and input ----------
const camS={yaw:-.35,pitch:.62,dist:16000,tx:hx0*.4,tz:hz0*.4}, camT=Object.assign({},camS);
let Wd=1,Ht=1; function resize(){ Wd=stage.clientWidth; Ht=stage.clientHeight; renderer.setSize(Wd,Ht,false); cam.aspect=Wd/Math.max(1,Ht); cam.updateProjectionMatrix(); } new ResizeObserver(resize).observe(stage); resize();
const ray=new THREE.Raycaster(), ndc=new THREE.Vector2(); let drag=null;
const pick=e=>{ const r=renderer.domElement.getBoundingClientRect(); ndc.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1); ray.setFromCamera(ndc,cam); const h=ray.intersectObject(terrain)[0]; return h?h.point:null; };
renderer.domElement.addEventListener('contextmenu',e=>e.preventDefault());
renderer.domElement.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,b:e.button,moved:false,yaw:camT.yaw,pitch:camT.pitch,tx:camT.tx,tz:camT.tz}; renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener('pointermove',e=>{ if(!drag){ const p=pick(e); const s=p&&secAt(p.x,p.z); if(String(s)!==String(hoverSec)){ hoverSec=s; drawOverlay(); } return; }
  const dx=e.clientX-drag.x, dy=e.clientY-drag.y; if(Math.hypot(dx,dy)>4) drag.moved=true; if(!drag.moved) return;
  if(drag.b===2||e.shiftKey){ const k=camT.dist/900, c=Math.cos(camT.yaw), s=Math.sin(camT.yaw); camT.tx=drag.tx-(dx*c+dy*s)*k; camT.tz=drag.tz-(-dx*s+dy*c)*k; }
  else { camT.yaw=drag.yaw-dx*.005; camT.pitch=Math.max(.25,Math.min(1.4,drag.pitch+dy*.004)); } });
renderer.domElement.addEventListener('pointerup',e=>{ const d=drag; drag=null; if(!d||d.moved||d.b!==0) return; const p=pick(e); const s=p&&secAt(p.x,p.z); if(!s) return; selSec=s; drawOverlay(); drawSector(); });
let push=0;
renderer.domElement.addEventListener('wheel',e=>{ e.preventDefault(); const want=camT.dist*Math.exp(e.deltaY*.0012);
  if(want<1500 && camT.dist<=1520){ push+=-e.deltaY; if(push>240){ push=0; dive(camT.tx,camT.tz); } } else push=0;
  camT.dist=Math.max(1500,Math.min(60000,want)); },{passive:false});
renderer.domElement.addEventListener('dblclick',e=>{ const p=pick(e); if(p) dive(p.x,p.z); });
function dive(x,z){ if(!NF.inBlock(x,z)){ NF.tip('Tactical ground is baked only for the gold New River block so far'); camT.tx=(NF.rect[0][0]+NF.rect[2][0])/2; camT.tz=(NF.rect[0][1]+NF.rect[2][1])/2; camT.dist=Math.max(camT.dist,3200); return; }
  const sq=squads[selSquad], here=!sq.path&&NF.inBlock(sq.x,sq.z)?sq:squads.find(o=>!o.path&&NF.inBlock(o.x,o.z));
  NF.enterTactical(x,z,here?{x:here.x,z:here.z,name:here.name,people:here.people,index:squads.indexOf(here)}:null); }
document.getElementById('diveBtn').onclick=()=>{ const sq=squads[selSquad]; dive(NF.inBlock(sq.x,sq.z)?sq.x:camT.tx, NF.inBlock(sq.x,sq.z)?sq.z:camT.tz); };
document.getElementById('homeBtn').onclick=()=>{ camT.tx=hx0; camT.tz=hz0; camT.dist=6000; };
function setSpeed(v){ speed=v; document.querySelectorAll('.hud button[data-s]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.s===v))); }
document.querySelectorAll('.hud button[data-s]').forEach(b=>b.onclick=()=>setSpeed(+b.dataset.s));

// ---------- frame loop ----------
buildBuildings(); buildPins(); drawOverlay(); drawSquads(); lightFor(minutes);
const tmp=new THREE.Vector3(); let last=performance.now(), knowDirty=false, uiAcc=0;
function loop(now){
  requestAnimationFrame(loop); const dt=Math.min(.1,(now-last)/1000); last=now; if(NF.mode!=='region') return;
  const moving=squads.some(s=>s.path);
  if(moving && speed>0){ minutes+=dt*10*speed; clockDay=Math.floor(minutes/1440)+1; lightFor(minutes); }
  for(const s of squads){ if(s.path){ const f=Math.min(1,(minutes-s.depart)/s.total), target=f*s.L[s.L.length-1]; while(s.seg<s.L.length-2 && s.L[s.seg+1]<target) s.seg++;
      const a=s.path[s.seg], b=s.path[s.seg+1], seg=(s.L[s.seg+1]-s.L[s.seg])||1, t=Math.min(1,(target-s.L[s.seg])/seg); s.x=a[0]+(b[0]-a[0])*t; s.z=a[1]+(b[1]-a[1])*t;
      const q=secAt(s.x,s.z); if(q && String(q)!==String(s.lastSec)){ s.lastSec=q; reveal(s.x,s.z); refreshCurrent(); knowDirty=true; }
      if(f>=1){ s.path=null; scene.remove(s.line); s.line.geometry.dispose(); reveal(s.x,s.z); refreshCurrent(); knowDirty=true; drawSquads(); if(selSec) drawSector(); } }
    s.mesh.position.set(s.x,Y(s.x,s.z),s.z); s.mesh.rotation.y+=dt*.6; }
  if(knowDirty){ knowDirty=false; drawOverlay(); buildPins(); buildBuildings(); }
  uiAcc+=dt; if(uiAcc>.5){ uiAcc=0; clockEl.textContent=fmtT(minutes); if(moving) drawSquads(); }
  const k=1-Math.exp(-dt*5); for(const key in camS){ if(key==='yaw'){ const d=Math.atan2(Math.sin(camT.yaw-camS.yaw),Math.cos(camT.yaw-camS.yaw)); camS.yaw+=d*k; } else camS[key]+=(camT[key]-camS[key])*k; }
  const ty=Y(camS.tx,camS.tz); cam.position.set(camS.tx+Math.sin(camS.yaw)*Math.cos(camS.pitch)*camS.dist, ty+Math.sin(camS.pitch)*camS.dist, camS.tz+Math.cos(camS.yaw)*Math.cos(camS.pitch)*camS.dist); cam.lookAt(camS.tx,ty,camS.tz);
  renderer.render(scene,cam);
  const place=(el,x,z,dy)=>{ tmp.set(x,Y(x,z)+dy,z).project(cam); const on=tmp.z<1&&Math.abs(tmp.x)<1.05&&Math.abs(tmp.y)<1.05; el.style.display=on?'':'none'; if(on) el.style.transform=`translate(${(tmp.x+1)/2*Wd}px,${(1-tmp.y)/2*Ht}px) translate(-50%,-100%)`; };
  for(const l of labels){ const show=l.kind!=='peak'||camS.dist<40000; if(!show){ l.el.style.display='none'; continue; } place(l.el,l.x,l.z,l.dy); }
  squads.forEach((s,i)=>{ place(s.el,s.x,s.z,260); const near=squads.slice(0,i).filter(o=>Math.hypot(o.x-s.x,o.z-s.z)<camS.dist*.04).length; if(near) s.el.style.transform+=` translateY(${near*-26}px)`; });
}
requestAnimationFrame(loop);
window.__region={squads,know,route,send,secCentre,setSpeed,camT,
  focus:(x,z)=>{ camT.tx=x; camT.tz=z; camT.dist=2400; camS.tx=x; camS.tz=z; camS.dist=1600; },
  placeSquad:(i,x,z)=>{ const s=squads[i]; s.x=x; s.z=z; reveal(x,z); refreshCurrent(); drawOverlay(); buildPins(); buildBuildings(); drawSquads(); if(selSec) drawSector(); },
  resize,select:(c,r)=>{ selSec=[c,r]; drawOverlay(); drawSector(); }};
})();
