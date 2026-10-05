// ---------- streaming sectors: a 3 x 3 window of baked sectors follows the squad ----------
(async function(){
const C=SectorCore, TAU=Math.PI*2, NK=C.NAVKIND, SWIM=C.SWIM;
const stage=document.getElementById('stage'), labelsEl=document.getElementById('labels'), readout=document.getElementById('readout'), whereEl=document.getElementById('where'), loadingEl=document.getElementById('loading');
const miniEl=document.getElementById('mini'), costEl=document.getElementById('cost'), blockEl=document.getElementById('block');
const fail=t=>{ loadingEl.textContent=t; };
if(!window.THREE){ fail('The 3D view needs three.js, which could not load. Check your connection and reload.'); return; }
let renderer; try{ renderer=new THREE.WebGLRenderer({antialias:true, alpha:true}); }catch(e){ fail('This browser could not start WebGL.'); return; }
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1)); renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; renderer.setClearColor(0x000000,0); stage.prepend(renderer.domElement);
stage.style.background='linear-gradient(180deg,#9fc6e4,#e8dcc2)';
const scene=new THREE.Scene(); scene.fog=new THREE.Fog(0xe2d8c2,380,980);
const cam=new THREE.PerspectiveCamera(38,1,.5,20000);
const hemi=new THREE.HemisphereLight(0xfff6e6,0x8a7a62,.32), sun=new THREE.DirectionalLight(0xfff1da,.78); sun.castShadow=true; sun.shadow.mapSize.set(4096,4096); sun.shadow.bias=-.0004; sun.shadow.normalBias=.04; scene.add(hemi,sun,sun.target);
const RAMP=(()=>{ const t=new THREE.DataTexture(new Uint8Array([88,88,88, 170,170,170, 235,235,235]),3,1,THREE.RGBFormat); t.minFilter=t.magFilter=THREE.NearestFilter; t.generateMipmaps=false; t.needsUpdate=true; return t; })();
const MC=new Map(); const mat=c=>{ let m=MC.get(c); if(!m){ m=new THREE.MeshStandardMaterial({color:c, flatShading:true, roughness:.92, metalness:0, side:THREE.DoubleSide}); MC.set(c,m); } return m; };   // ink faceted props
class Batch{ constructor(){ this.m=new Map(); } tri(m,a,b,c){ let arr=this.m.get(m); if(!arr){ arr=[]; this.m.set(m,arr); } arr.push(...a,...b,...c); }
  quad(m,a,b,c,d){ this.tri(m,a,b,c); this.tri(m,a,c,d); }
  meshes(cast=true){ const out=[]; for(const [m,arr] of this.m){ const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(arr,3)); g.computeVertexNormals(); const me=new THREE.Mesh(g,m); me.castShadow=cast; me.receiveShadow=true; out.push(me); } return out; } }
const mtx=(x,y,z,sx=1,sy=1,sz=1,rx=0,ry=0,rz=0)=>new THREE.Matrix4().compose(new THREE.Vector3(x,y,z),new THREE.Quaternion().setFromEuler(new THREE.Euler(rx,ry,rz)),new THREE.Vector3(sx,sy,sz));
function mergeGeos(list){ const pos=[]; for(const [g0,m] of list){ const g=(g0.index?g0.toNonIndexed():g0.clone()); g.applyMatrix4(m); pos.push(...g.attributes.position.array); } const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.computeVertexNormals(); return g; }
const SHAPES={
  saguaro: mergeGeos([[new THREE.CylinderGeometry(.26,.32,5.2,7),mtx(0,2.6,0)],[new THREE.SphereGeometry(.26,7,4,0,TAU,0,Math.PI/2),mtx(0,5.2,0)],
    [new THREE.CylinderGeometry(.19,.19,1.1,6),mtx(.55,2.2,0,1,1,1,0,0,Math.PI/2)],[new THREE.CylinderGeometry(.19,.2,1.8,6),mtx(1.05,3.05,0)],[new THREE.SphereGeometry(.19,6,3,0,TAU,0,Math.PI/2),mtx(1.05,3.95,0)],
    [new THREE.CylinderGeometry(.17,.17,.9,6),mtx(-.48,2.9,0,1,1,1,0,0,Math.PI/2)],[new THREE.CylinderGeometry(.17,.18,1.3,6),mtx(-.9,3.5,0)],[new THREE.SphereGeometry(.17,6,3,0,TAU,0,Math.PI/2),mtx(-.9,4.15,0)]]),
  trunk: mergeGeos([[new THREE.CylinderGeometry(.08,.14,2.2,5),mtx(0,1.1,0,1,1,1,0,0,.25)],[new THREE.CylinderGeometry(.07,.12,2,5),mtx(.25,1.1,.2,1,1,1,.35,0,-.3)],[new THREE.CylinderGeometry(.06,.1,1.8,5),mtx(-.2,1,-.25,1,1,1,-.4,0,-.1)]]),
  canopy: mergeGeos([[new THREE.IcosahedronGeometry(1,0),mtx(.2,2.4,0,2,.9,1.8)],[new THREE.IcosahedronGeometry(1,0),mtx(-.6,2.2,.4,1.4,.7,1.3)],[new THREE.IcosahedronGeometry(1,0),mtx(.5,2.1,-.7,1.3,.6,1.2)]]),
  shrub: mergeGeos([[new THREE.IcosahedronGeometry(1,0),mtx(0,.45,0,.9,.55,.85)],[new THREE.IcosahedronGeometry(1,0),mtx(.4,.35,.3,.55,.4,.5)]]),
  rock: mergeGeos([[new THREE.DodecahedronGeometry(1,0),mtx(0,.3,0,1,.6,.8)]]),
  reed: mergeGeos([0,1,2,3,4,5].map(i=>[new THREE.ConeGeometry(.05,1.5+i%3*.3,4),mtx(Math.cos(i*2.1)*.22,.8,Math.sin(i*2.1)*.22,1,1,1,Math.sin(i)*.15,0,Math.cos(i)*.15)])),
  saguaroLo: mergeGeos([[new THREE.CylinderGeometry(.24,.32,5.2,5,1,true),mtx(0,2.6,0)],[new THREE.CylinderGeometry(.18,.18,1.9,4,1,true),mtx(1,3,0)],[new THREE.CylinderGeometry(.16,.16,1.4,4,1,true),mtx(-.9,3.4,0)]]),
  pin: new THREE.OctahedronGeometry(1.1,0), stem: new THREE.CylinderGeometry(.08,.08,3,4),
};
const SHARED=new Set(Object.values(SHAPES));
const KIND={food:{c:'#e0a33a',label:'Food'}, medicine:{c:'#d9534f',label:'Medicine'}, tools:{c:'#5b8fd1',label:'Tools'}, fuel:{c:'#a66bd1',label:'Fuel'}, gear:{c:'#3fae7f',label:'Gear'}, shelter:{c:'#8f8f8f',label:'Shelter'}};

// ink: a back-face shell that keeps a constant width on screen, plus crease lines; only the centre sector wears it
const INK=(()=>{ const m=new THREE.MeshBasicMaterial({color:0x231c17, side:THREE.BackSide}); m.onBeforeCompile=sh=>{ sh.vertexShader=sh.vertexShader.replace('#include <project_vertex>',
  `vec4 mvPosition=vec4(transformed,1.0); vec3 nn=normal;
   #ifdef USE_INSTANCING
     mvPosition=instanceMatrix*mvPosition; nn=mat3(instanceMatrix)*nn;
   #endif
   mvPosition=modelViewMatrix*mvPosition; mvPosition.xyz+=normalize(normalMatrix*nn)*0.0011*(-mvPosition.z); gl_Position=projectionMatrix*mvPosition;`); }; m.customProgramCacheKey=()=>'inkStream'; return m; })();
const CREASE=new THREE.LineBasicMaterial({color:0x2d241d, transparent:true, opacity:.55}), creaseOf=new Map();
function inkOn(group){ const list=[]; group.traverse(o=>{ if(o.isMesh && !o.userData.ink && !o.userData.noInk) list.push(o); });
  for(const o of list){ const sh=o.isInstancedMesh?new THREE.InstancedMesh(o.geometry,INK,o.count):new THREE.Mesh(o.geometry,INK); if(o.isInstancedMesh) sh.instanceMatrix=o.instanceMatrix;
    sh.userData.ink=true; sh.matrixAutoUpdate=false; o.add(sh);
    if(!o.isInstancedMesh){ const own=o.userData.crease; let eg=own||creaseOf.get(o.geometry); if(!eg){ eg=new THREE.EdgesGeometry(o.geometry,28); creaseOf.set(o.geometry,eg); } const ln=new THREE.LineSegments(eg,CREASE); if(own) ln.userData.keepGeo=true; ln.userData.ink=true; ln.matrixAutoUpdate=false; o.add(ln); } } }
function inkOff(group){ const kill=[]; group.traverse(o=>{ if(o.userData.ink) kill.push(o); }); for(const o of kill){ o.parent.remove(o); if(o.isLineSegments&&!o.userData.keepGeo){ o.geometry.dispose(); for(const [k,v] of creaseOf) if(v===o.geometry) creaseOf.delete(k); } } }

// ---------- the block ----------
const IDX=await (await fetch('block/index.json')).json();
const SEC=IDX.sector, NB=IDX.n, HALF=IDX.half, NS=IDX.navStep, SN=SEC/NS;
// the baked area is a rectangle of sectors, NBX across and NBZ down, its north-west corner at (BX0,BZ0); GN cells across, GZ down
const NBX=IDX.nx||NB, NBZ=IDX.nz||NB, BX0=IDX.x0??-HALF, BZ0=IDX.z0??-HALF, BX1=BX0+NBX*SEC, BZ1=BZ0+NBZ*SEC, GN=NBX*SN, GZ=NBZ*SN, GNN=GN*GZ;
for(const b of IDX.bridges){ const d=b.d; b.yAt=t=>C.bridgeY(b,t); b.tan=k=>{ const p=d[Math.max(0,k-1)], q=d[Math.min(d.length-1,k+1)], l=Math.hypot(q[0]-p[0],q[1]-p[1])||1; return [(q[0]-p[0])/l,(q[1]-p[1])/l]; }; b.nrm=k=>{ const [tx,tz]=b.tan(k); return [tz,-tx]; };
  b.sec=[Math.floor((b.mid[0]-BX0)/SEC),Math.floor((b.mid[1]-BZ0)/SEC)]; b.bb=C.bbox(d); }
const RK=RoadKit({THREE,C,heightAt:(x,z)=>heightAt(x,z),IDX,renderer,mat,SHAPES,sectorGeo:(g,s)=>sectorGeo(g,s),kindAt:(x,z)=>{ const c=cellOf(x,z); return c<0?255:kindG[c]; }});
const FK=FloraKit({THREE,mat,C,sectorGeo:(g,s)=>sectorGeo(g,s)});   // desert plants, rock and wash beds (tools/stream/flora-kit.js)   // road surfaces, paint, signs and signals
const sectors=new Map(), key=(c,r)=>c+','+r;
const secAt=(x,z)=>{ const c=Math.floor((x-BX0)/SEC), r=Math.floor((z-BZ0)/SEC); return c>=0&&r>=0&&c<NBX&&r<NBZ?[c,r]:null; };
const CX=IDX.context, CCX=CX.cx||0, CCZ=CX.cz||0, ctxH=(x,z)=>{ const fx=(x-CCX+CX.half)/CX.step, fz=(z-CCZ+CX.half)/CX.step, i=Math.max(0,Math.min(CX.n-2,Math.floor(fx))), j=Math.max(0,Math.min(CX.n-2,Math.floor(fz))), u=fx-i, v=fz-j, h=(a,b)=>CX.h[b*CX.n+a]; return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; };
function heightAt(x,z){ const q=secAt(x,z), s=q&&sectors.get(key(...q)); if(!s||!s.Hf) return ctxH(x,z);
  const n=s.hn, fx=(x-s.x0+4)/4, fz=(z-s.z0+4)/4, i=Math.max(0,Math.min(n-2,Math.floor(fx))), j=Math.max(0,Math.min(n-2,Math.floor(fz))), u=fx-i, v=fz-j, H=s.Hf, h=(a,b)=>H[b*n+a];
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; }
const slopeAt=(x,z)=>{ const e=2, gx=(heightAt(x+e,z)-heightAt(x-e,z))/(2*e), gz=(heightAt(x,z+e)-heightAt(x,z-e))/(2*e); return Math.atan(Math.hypot(gx,gz))*180/Math.PI; };
function deckAt(x,z,pad=0){ for(const b of IDX.bridges){ if(x<b.bb[0]-b.hw-pad||x>b.bb[2]+b.hw+pad||z<b.bb[1]-b.hw-pad||z>b.bb[3]+b.hw+pad) continue; const d=b.d;
  for(let k=0;k<d.length-1;k++){ const a=d[k], c=d[k+1], dx=c[0]-a[0], dz=c[1]-a[1], l2=dx*dx+dz*dz||1, t=((x-a[0])*dx+(z-a[1])*dz)/l2; if(t<-.01||t>1.01) continue;
    if(Math.hypot(x-a[0]-dx*t,z-a[1]-dz*t)>b.hw+pad) continue; const s=b.L[k]+t*Math.sqrt(l2); return {b,s,y:b.yAt(Math.max(0,Math.min(1,s/b.len)))}; } } return null; }
// the landscape around the block; inside the block it sits a little low so loaded sectors always cover it
{ const n=CX.n, g=new THREE.PlaneGeometry(CX.half*2,CX.half*2,n-1,n-1); g.rotateX(-Math.PI/2); const p=g.attributes.position;
  for(let i=0;i<p.count;i++){ const x=p.getX(i)+CCX, z=p.getZ(i)+CCZ, inB=x>BX0-60&&x<BX1+60&&z>BZ0-60&&z<BZ1+60; p.setY(i,CX.h[i]-(inB?14:0)); }   // well below the real ground: its 50 m grid would otherwise poke through washes and cuts g.computeVertexNormals();
  const c=document.createElement('canvas'); c.width=c.height=1024; const x2=c.getContext('2d'); x2.fillStyle='#c9ae86'; x2.fillRect(0,0,1024,1024);
  const sh=document.createElement('canvas'); sh.width=sh.height=n; const sg=sh.getContext('2d'), img=sg.createImageData(n,n), L=[-.5,.7,-.5], ll=Math.hypot(...L), flat=L[1]/ll;
  for(let j=0;j<n;j++) for(let i=0;i<n;i++){ const h=(a,b)=>CX.h[Math.min(n-1,Math.max(0,b))*n+Math.min(n-1,Math.max(0,a))], dx=(h(i+1,j)-h(i-1,j))/(2*CX.step), dz=(h(i,j+1)-h(i,j-1))/(2*CX.step), nn=[-dx,1,-dz], nl=Math.hypot(...nn), v=((nn[0]*L[0]+nn[1]*L[1]+nn[2]*L[2])/(nl*ll)-flat)*2.2, o=(j*n+i)*4;
    if(v<0) img.data.set([70,45,25,Math.min(.6,-v)*255],o); else img.data.set([255,248,230,Math.min(.4,v)*255],o); }
  sg.putImageData(img,0,0); x2.drawImage(sh,0,0,1024,1024);
  const me=new THREE.Mesh(g,new THREE.MeshLambertMaterial({map:new THREE.CanvasTexture(c)})); me.position.set(CCX,0,CCZ); me.receiveShadow=true; scene.add(me);
  const skirt=new THREE.Mesh(new THREE.PlaneGeometry(60000,60000),new THREE.MeshLambertMaterial({color:0xc4aa82})); skirt.rotation.x=-Math.PI/2; skirt.position.y=Math.min(...CX.h)-4; scene.add(skirt); }

// ---------- movement: one grid over the whole block, filled in as sectors load ----------
const kindG=new Uint8Array(GNN).fill(255), spG=new Uint8Array(GNN);
const cellOf=(x,z)=>{ const i=Math.floor((x-BX0)/NS), j=Math.floor((z-BZ0)/NS); return i>=0&&j>=0&&i<GN&&j<GZ?j*GN+i:-1; };
const deck=[], link=new Map();
for(const [bi,b] of IDX.bridges.entries()){ const lanes=Math.max(2,Math.round((b.w-1)/2)), base=GNN+deck.length, n=b.d.length;
  for(let k=0;k<n;k++){ const [nx,nz]=b.nrm(k); for(let l=0;l<lanes;l++){ const o=(l/(lanes-1)-.5)*(b.w-1.2); deck.push({x:b.d[k][0]+nx*o,z:b.d[k][1]+nz*o,b:bi,nb:[]}); } }
  for(let k=0;k<n;k++) for(let l=0;l<lanes;l++){ const me=base+k*lanes+l; for(const [dk,dl] of [[1,0],[0,1],[1,1],[1,-1]]){ const k2=k+dk, l2=l+dl; if(k2<n&&l2>=0&&l2<lanes){ const o=base+k2*lanes+l2; deck[me-GNN].nb.push(o); deck[o-GNN].nb.push(me); } } }
  for(const [k,sg] of [[0,-1],[n-1,1]]){ const [tx,tz]=b.tan(k); for(let l=0;l<lanes;l++){ const dn=base+k*lanes+l, p=deck[dn-GNN], c=cellOf(p.x+tx*sg*2.2,p.z+tz*sg*2.2); if(c<0) continue; if(!link.has(c)) link.set(c,[]); link.get(c).push(dn); p.nb.push(c); } } }
const ui={view:'tactical', swim:false, seams:false};
const nodeSpeed=n=>{ if(n>=GNN){ const b=IDX.bridges[deck[n-GNN].b], s=sectors.get(key(...b.sec)); return s&&s.state==='built'?1:0; } const k=kindG[n]; if(k===255) return 0; if(k===NK.water) return ui.swim?SWIM:0; return spG[n]/250; };
const nodePos=n=>{ if(n>=GNN){ const d=deck[n-GNN]; return {x:d.x,z:d.z,l:1}; } return {x:BX0+(n%GN+.5)*NS,z:BZ0+(Math.floor(n/GN)+.5)*NS,l:0}; };
function nearestDeckNode(x,z){ let best=-1,bd=1e9; deck.forEach((d,i)=>{ const dd=Math.hypot(d.x-x,d.z-z); if(dd<bd){ bd=dd; best=i; } }); return best<0?-1:GNN+best; }
function nearestPassable(c){ const ci=c%GN, cj=Math.floor(c/GN); for(let r=1;r<40;r++){ let best=-1,bd=1e9; for(let dj=-r;dj<=r;dj++) for(let di=-r;di<=r;di++){ if(Math.max(Math.abs(di),Math.abs(dj))!==r) continue; const i=ci+di, j=cj+dj; if(i<0||j<0||i>=GN||j>=GZ) continue; const id=j*GN+i; if(nodeSpeed(id)>0){ const dd=di*di+dj*dj; if(dd<bd){ bd=dd; best=id; } } } if(best>=0) return best; } return -1; }
const TOT=GNN+deck.length, gA=new Float32Array(TOT).fill(Infinity), came=new Int32Array(TOT).fill(-1), closed=new Uint8Array(TOT);
function findPath(from,to){
  const touched=[], heap=[], goal=nodePos(to);
  const push=(n,f)=>{ heap.push([f,n]); let i=heap.length-1; while(i>0){ const p=(i-1)>>1; if(heap[p][0]<=heap[i][0]) break; [heap[p],heap[i]]=[heap[i],heap[p]]; i=p; } };
  const pop=()=>{ const top=heap[0], last=heap.pop(); if(heap.length){ heap[0]=last; let i=0; for(;;){ const l=2*i+1, r=l+1; let m=i; if(l<heap.length&&heap[l][0]<heap[m][0]) m=l; if(r<heap.length&&heap[r][0]<heap[m][0]) m=r; if(m===i) break; [heap[m],heap[i]]=[heap[i],heap[m]]; i=m; } } return top; };
  const h=n=>{ const p=nodePos(n); return Math.hypot(p.x-goal.x,p.z-goal.z); };
  gA[from]=0; touched.push(from); push(from,h(from)); let guard=0, found=false;
  while(heap.length && guard++<600000){ const [,n]=pop(); if(closed[n]) continue; closed[n]=1; if(n===to){ found=true; break; }
    const sa=Math.max(nodeSpeed(n),.05), pa=nodePos(n), nbrs=[];
    if(n<GNN){ const i=n%GN, j=Math.floor(n/GN);
      for(let dj=-1;dj<=1;dj++) for(let di=-1;di<=1;di++){ if(!di&&!dj) continue; const i2=i+di, j2=j+dj; if(i2<0||j2<0||i2>=GN||j2>=GZ) continue; if(di&&dj&&(nodeSpeed(j*GN+i2)<=0||nodeSpeed(j2*GN+i)<=0)) continue; nbrs.push(j2*GN+i2); }
      const L=link.get(n); if(L) nbrs.push(...L); }
    else nbrs.push(...deck[n-GNN].nb);
    for(const m of nbrs){ if(closed[m]) continue; const sb=nodeSpeed(m); if(sb<=0) continue; const pb=nodePos(m), c=gA[n]+Math.hypot(pb.x-pa.x,pb.z-pa.z)/((sa+sb)/2);
      if(c<gA[m]){ if(gA[m]===Infinity) touched.push(m); gA[m]=c; came[m]=n; push(m,c+h(m)); } } }
  let out=null, cost=gA[to]; if(found){ out=[]; for(let n=to;n>=0;n=came[n]) out.push(n); out.reverse(); }
  for(const n of touched){ gA[n]=Infinity; came[n]=-1; closed[n]=0; } return out?{nodes:out,cost}:null; }
function smoothPath(nodes){ const pts=nodes.map(nodePos), out=[pts[0]]; let i=0;
  const ok=(a,b)=>{ if(a.l||b.l) return false; const L=Math.hypot(b.x-a.x,b.z-a.z), n=Math.ceil(L/.7), s0=Math.min(nodeSpeed(cellOf(a.x,a.z)),nodeSpeed(cellOf(b.x,b.z)))*.97; for(let q=1;q<n;q++){ const c=cellOf(a.x+(b.x-a.x)*q/n,a.z+(b.z-a.z)*q/n); if(c<0||nodeSpeed(c)<s0) return false; } return true; };
  while(i<pts.length-1){ let j=Math.min(pts.length-1,i+40); while(j>i+1 && !ok(pts[i],pts[j])) j--; out.push(pts[j]); i=j; } return out; }
function waterLevelAt(x,z){ const q=secAt(x,z), s=q&&sectors.get(key(...q)); if(!s||!s.data) return null; for(const l of s.data.lakes) if(C.inPoly(x,z,l.raw)) return l.level; for(const p of s.data.pools) if(C.inPoly(x,z,p.pts)) return p.level-.12; return null; }

// ---------- building one sector, a step at a time ----------
const unb64=(s,T)=>{ const bin=atob(s), u=new Uint8Array(bin.length); for(let i=0;i<bin.length;i++) u[i]=bin.charCodeAt(i); return new T(u.buffer); };
async function fetchSector(c,r){ const res=await fetch(`block/s_${c}_${r}.json`); if(!res.ok) throw new Error('sector '+c+','+r+' '+res.status); return res.json(); }
const STUCCO=['#d9c3a0','#cfb48e','#e2cfae','#c9a882','#d6bf9a','#bfa182'], TILE=['#b5653f','#a8583a','#9c6a4c','#8d5b45','#9b8f80'], SHOP=['#cdb491','#c2a27f','#d9c4a3','#b89a78'];
function shadeCanvas(H,n,step){ const c=document.createElement('canvas'); c.width=c.height=n; const g=c.getContext('2d'), img=g.createImageData(n,n), L=[-.5,.7,-.5], ll=Math.hypot(...L), flat=L[1]/ll;
  for(let j=0;j<n;j++) for(let i=0;i<n;i++){ const h=(a,b)=>H[Math.min(n-1,Math.max(0,b))*n+Math.min(n-1,Math.max(0,a))], dx=(h(i+1,j)-h(i-1,j))/(2*step), dz=(h(i,j+1)-h(i,j-1))/(2*step), nn=[-dx,1,-dz], nl=Math.hypot(...nn), v=((nn[0]*L[0]+nn[1]*L[1]+nn[2]*L[2])/(nl*ll)-flat)*1.6, o=(j*n+i)*4;
    if(v<0) img.data.set([70,45,25,Math.min(.5,-v)*255],o); else img.data.set([255,248,230,Math.min(.35,v)*255],o); }
  g.putImageData(img,0,0); return c; }
function* buildSector(s){
  const D=s.data, x0=s.x0, z0=s.z0, grp=new THREE.Group(); s.group=grp; s.props=new THREE.Group(); s.gen=new THREE.Group(); grp.add(s.props,s.gen); s.labels=[]; s.picks=[];
  // heights and movement
  const Hi=unb64(D.H,Int16Array), n=D.hn; s.hn=n; s.Hf=new Float32Array(n*n); for(let i=0;i<n*n;i++) s.Hf[i]=Hi[i]/100;
  const kind=unb64(D.nav.kind,Uint8Array), sp=unb64(D.nav.sp,Uint8Array), ns=D.nav.n;
  for(let j=0;j<ns;j++){ const gj=(s.r*ns+j)*GN+s.c*ns; kindG.set(kind.subarray(j*ns,(j+1)*ns),gj); spG.set(sp.subarray(j*ns,(j+1)*ns),gj); }
  yield 'grid';
  // ground texture
  const SIZE=1024, cv=document.createElement('canvas'); cv.width=cv.height=SIZE; const g=cv.getContext('2d'), X=x=>(x-x0)/SEC*SIZE, Z=z=>(z-z0)/SEC*SIZE, px=SIZE/SEC, rr=C.rng(1000+s.c*31+s.r*7);
  g.fillStyle='#cdb48c'; g.fillRect(0,0,SIZE,SIZE);
  for(let i=0;i<30;i++){ const x=rr()*SIZE,y=rr()*SIZE,rad=20+rr()*80, gr=g.createRadialGradient(x,y,0,x,y,rad); gr.addColorStop(0,`rgba(${rr()<.5?'150,120,85':'220,200,165'},.35)`); gr.addColorStop(1,'rgba(0,0,0,0)'); g.fillStyle=gr; g.fillRect(x-rad,y-rad,rad*2,rad*2); }
  for(let i=0;i<14000;i++){ g.fillStyle=rr()<.5?'rgba(120,95,70,.25)':'rgba(240,225,200,.25)'; g.fillRect(rr()*SIZE,rr()*SIZE,1.2,1.2); }
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  const line=(pts,w,col)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.lineWidth=Math.max(.6,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.stroke(); };
  const AREA={residential:'#d4c09c',retail:'#9a9894',commercial:'#9a9894',industrial:'#9d978d',parking:'#7d7c79',grass:'#8fa456',park:'#97ab5d',pitch:'#7f9e4a',playground:'#c9a77a',swimming_pool:'#4aa6c8',scree:'#ae9d84',sand:'#dcc7a0',water:'#4aa6c8'};
  for(const k of ['residential','scree','sand','park','grass','pitch','industrial','retail','commercial','parking','playground','swimming_pool','water']) for(const a of D.areas) if(a.kind===k) poly(a.pts,AREA[k]);
  FK.paintGround(g,s,X,Z,px);
  for(const l of D.lakes) for(const p of l.shore){ line(p,6,'#9c8a68'); line(p,2.5,'#7e6d52'); }
  RK.paintGround(g,s,X,Z,px);
  g.imageSmoothingEnabled=true; g.drawImage(shadeCanvas(s.Hf,n,4),X(x0-4)-2*px,Z(z0-4)-2*px,n*4*px,n*4*px);
  const tex=new THREE.CanvasTexture(cv); tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
  yield 'texture';
  // terrain
  const tg=new THREE.PlaneGeometry(SEC,SEC,SEC/4,SEC/4); tg.rotateX(-Math.PI/2); const tp=tg.attributes.position, m1=SEC/4+1;
  for(let i=0;i<tp.count;i++){ const a=i%m1, b=Math.floor(i/m1); tp.setY(i,s.Hf[(b+1)*n+a+1]); } tg.computeVertexNormals();
  s.terrain=new THREE.Mesh(tg,new THREE.MeshToonMaterial({map:tex, gradientMap:RAMP})); s.terrain.position.set(x0+SEC/2,0,z0+SEC/2); s.terrain.receiveShadow=true; s.terrain.userData.noInk=true; s.terrain.userData.ownMat=true; grp.add(s.terrain);
  // sector edges, for the seam toggle
  { const pts=[]; for(const [ax,az,bx,bz] of [[x0,z0,x0+SEC,z0],[x0,z0,x0,z0+SEC]]) for(let t=0;t<SEC;t+=6){ const f=t/SEC, f2=(t+6)/SEC, p=[ax+(bx-ax)*f,az+(bz-az)*f], q=[ax+(bx-ax)*f2,az+(bz-az)*f2]; pts.push(p[0],heightAt(p[0],p[1])+.3,p[1],q[0],heightAt(q[0],q[1])+.3,q[1]); }
    const lg=new THREE.BufferGeometry(); lg.setAttribute('position',new THREE.Float32BufferAttribute(pts,3)); s.seam=new THREE.LineSegments(lg,new THREE.LineBasicMaterial({color:0xe0a526})); s.seam.visible=ui.seams; grp.add(s.seam); }
  yield 'terrain';
  // roads: surfaces, paint, signs, signals and the roadside (tools/stream/road-kit.js)
  yield* RK.build(s,grp);
  // buildings
  { const B=new Batch(), r=C.rng(11+s.c*13+s.r*17), glass=mat('#3b4247'), roofFlat=mat('#d8d2c8'), metal=mat('#9aa3a8');
    for(const b of D.buildings){ const pts=b.pts, A=C.area(pts), [cx,cz]=C.centroid(pts), hs=pts.map(([x,z])=>heightAt(x,z)), lo=Math.min(...hs)-.3, hiG=Math.max(...hs);
      const shop=b.loot||['retail','commercial','supermarket','industrial','school','public'].includes(b.type)||(b.type==='yes'&&!b.house&&A>250), shed=!shop&&!b.house&&A<70;
      const Ht=b.height||(b.levels?b.levels*3.2+(shop?1.2:0):shop?6.5:shed?2.8:3.3), top=hiG+Ht, wallM=mat(shop?SHOP[Math.floor(r()*SHOP.length)]:STUCCO[Math.floor(r()*STUCCO.length)]);
      for(let i=0;i<pts.length;i++){ const [x,z]=pts[i], [x2,z2]=pts[(i+1)%pts.length]; B.quad(wallM,[x,lo,z],[x2,lo,z2],[x2,top,z2],[x,top,z]);
        const L=Math.hypot(x2-x,z2-z); if(shop&&L>6){ const nx=(z2-z)/L*.06, nz=-(x2-x)/L*.06, y0=hiG+.4, y1=Math.min(top-1.4,hiG+3); for(const sg of [1,-1]) B.quad(glass,[x+nx*sg+(x2-x)*.08,y0,z+nz*sg+(z2-z)*.08],[x2+nx*sg-(x2-x)*.08,y0,z2+nz*sg-(z2-z)*.08],[x2+nx*sg-(x2-x)*.08,y1,z2+nz*sg-(z2-z)*.08],[x+nx*sg+(x2-x)*.08,y1,z+nz*sg+(z2-z)*.08]); } }
      let tris; try{ tris=THREE.ShapeUtils.triangulateShape(pts.map(([x,z])=>new THREE.Vector2(x,z)),[]); }catch(e){ tris=[]; }
      if(shop||shed){ const m=shed?metal:roofFlat; for(const [a,b2,c] of tris) B.tri(m,[pts[a][0],top,pts[a][1]],[pts[b2][0],top,pts[b2][1]],[pts[c][0],top,pts[c][1]]); }
      else { const roofM=mat(TILE[Math.floor(r()*TILE.length)]), rad=Math.sqrt(A/Math.PI), k=Math.max(.3,1-2.2/rad), rise=Math.min(1.8,.35*rad+.5);
        const eave=pts.map(([x,z])=>[cx+(x-cx)*1.06,top-.15,cz+(z-cz)*1.06]), inner=pts.map(([x,z])=>[cx+(x-cx)*k,top+rise,cz+(z-cz)*k]);
        for(let i=0;i<pts.length;i++){ const j=(i+1)%pts.length; B.quad(roofM,eave[i],eave[j],inner[j],inner[i]); } for(const [a,b2,c] of tris) B.tri(roofM,inner[a],inner[b2],inner[c]); } }
    // walls
    const block=mat('#c7b596'), fence=mat('#8a7a66');
    for(const w of D.walls){ const a=[w[0],w[1]], b=[w[2],w[3]], h=w[4], t=w[5], m=w[6]?fence:block, L=Math.hypot(b[0]-a[0],b[1]-a[1]); if(L<.2) continue; const nx=-(b[1]-a[1])/L*t/2, nz=(b[0]-a[0])/L*t/2, ya=heightAt(a[0],a[1])-.3, yb=heightAt(b[0],b[1])-.3, ta=ya+h+.3, tb=yb+h+.3;
      for(const sg of [1,-1]) B.quad(m,[a[0]+nx*sg,ya,a[1]+nz*sg],[b[0]+nx*sg,yb,b[1]+nz*sg],[b[0]+nx*sg,tb,b[1]+nz*sg],[a[0]+nx*sg,ta,a[1]+nz*sg]); B.quad(m,[a[0]+nx,ta,a[1]+nz],[b[0]+nx,tb,b[1]+nz],[b[0]-nx,tb,b[1]-nz],[a[0]-nx,ta,a[1]-nz]); }
    B.meshes().forEach(me=>s.props.add(me)); }
  yield 'buildings';
  // bridges whose middle is in this sector, culverts, still water
  { const B=new Batch(), con=mat('#c4bdb0'), conD=mat('#a8a194'), soffit=mat('#8f887d'), steel=mat('#9aa3a8'), post=mat('#6d675f'), joint=mat('#2b2724'), pipe=mat('#2b2622'), rocks=[], r=C.rng(53+s.c+s.r*5);
    const obox=(m,cx,cz,tx,tz,ht,hn,y0,y1)=>{ const nx=tz, nz=-tx, P=(a,b,y)=>[cx+tx*a+nx*b,y,cz+tz*a+nz*b], c=[[-ht,-hn],[ht,-hn],[ht,hn],[-ht,hn]]; for(let i=0;i<4;i++){ const [a,b]=c[i], [a2,b2]=c[(i+1)%4]; B.quad(m,P(a,b,y0),P(a2,b2,y0),P(a2,b2,y1),P(a,b,y1)); } B.quad(m,P(-ht,-hn,y1),P(ht,-hn,y1),P(ht,hn,y1),P(-ht,hn,y1)); };
    const prism=(m,x,z,rad,y0,y1,k=8)=>{ for(let i=0;i<k;i++){ const a=i/k*TAU, b=(i+1)/k*TAU; B.quad(m,[x+Math.cos(a)*rad,y0,z+Math.sin(a)*rad],[x+Math.cos(b)*rad,y0,z+Math.sin(b)*rad],[x+Math.cos(b)*rad,y1,z+Math.sin(b)*rad],[x+Math.cos(a)*rad,y1,z+Math.sin(a)*rad]); } };
    IDX.bridges.forEach((b,bi)=>{ if(b.sec[0]!==s.c||b.sec[1]!==s.r) return; const d=b.d, nn=d.length, hw=b.hw, Y=k=>b.yAt(b.L[k]/b.len), sd=b.depth*.4, P=(k,off,dy)=>{ const [nx,nz]=b.nrm(k); return [d[k][0]+nx*off,Y(k)+dy,d[k][1]+nz*off]; };
      for(let k=0;k<nn-1;k++){
        for(const sg of [-1,1]){ B.quad(con,P(k,sg*b.w/2,.07),P(k+1,sg*b.w/2,.07),P(k+1,sg*hw,.07),P(k,sg*hw,.07)); B.quad(conD,P(k,sg*hw,.95),P(k+1,sg*hw,.95),P(k+1,sg*hw,-sd),P(k,sg*hw,-sd)); }
        B.quad(soffit,P(k,-hw,-sd),P(k+1,-hw,-sd),P(k+1,hw,-sd),P(k,hw,-sd));
        if(b.long) for(const o of [-.72,-.24,.24,.72]){ const c=o*(hw-.6); for(const sg of [-.28,.28]) B.quad(soffit,P(k,c+sg,-sd),P(k+1,c+sg,-sd),P(k+1,c+sg,-b.depth),P(k,c+sg,-b.depth)); B.quad(soffit,P(k,c-.28,-b.depth),P(k+1,c-.28,-b.depth),P(k+1,c+.28,-b.depth),P(k,c+.28,-b.depth)); }
        for(const sg of [-1,1]){ const o2=sg*(hw-.45), o3=sg*(hw-.28); B.quad(con,P(k,o2,.07),P(k+1,o2,.07),P(k+1,o2,.35),P(k,o2,.35)); B.quad(con,P(k,o2,.35),P(k+1,o2,.35),P(k+1,o3,.48),P(k,o3,.48)); B.quad(con,P(k,o3,.48),P(k+1,o3,.48),P(k+1,o3,.95),P(k,o3,.95)); B.quad(con,P(k,o3,.95),P(k+1,o3,.95),P(k+1,sg*hw,.95),P(k,sg*hw,.95)); } }
      const pg=new THREE.BufferGeometry(), pp=[]; for(let k=0;k<nn-1;k++){ const q=[P(k,-hw,.1),P(k+1,-hw,.1),P(k+1,hw,.1),P(k,hw,.1)]; pp.push(...q[0],...q[1],...q[2],...q[0],...q[2],...q[3]); }
      pg.setAttribute('position',new THREE.Float32BufferAttribute(pp,3)); const pick=new THREE.Mesh(pg,new THREE.MeshBasicMaterial({side:THREE.DoubleSide})); pick.visible=false; pick.userData.noInk=true; pick.userData.deck=true; grp.add(pick); s.picks.push(pick);
      const kAt=sv=>{ let k=0; while(k<nn-1&&b.L[k+1]<sv) k++; return k; }, spans=b.long?Math.max(2,Math.round(b.len/24)):1;
      for(let q=0;q<=spans;q++){ const sv=b.ab+(b.len-2*b.ab)*q/spans, k=kAt(sv), [tx,tz]=b.tan(k), x=d[k][0]+tx*(sv-b.L[k]), z=d[k][1]+tz*(sv-b.L[k]), y=b.yAt(sv/b.len);
        obox(joint,x,z,tx,tz,.12,b.w/2,y+.06,y+.075); if(q===0||q===spans){ obox(conD,x,z,tx,tz,.6,hw,y-b.depth-.6,y-sd); continue; } obox(conD,x,z,tx,tz,.7,hw-.2,y-b.depth-1,y-b.depth); }
      for(const [x,z,gy] of b.piers){ const dk=deckAt(x,z); prism(con,x,z,.5,gy-.6,dk?dk.y-b.depth-1:gy+2); }
      for(const s0 of [b.ab,b.len-b.ab]) for(let i=0;i<26;i++){ const sv=s0+(s0<b.len/2?1:-1)*r()*(b.long?8:5), k=kAt(sv), [nx,nz]=b.nrm(k), o=(r()*2-1)*(hw+1.5), x=d[k][0]+nx*o, z=d[k][1]+nz*o, sc=.35+r()*.45; rocks.push(mtx(x,heightAt(x,z)-.1,z,sc*1.3,sc,sc*1.2,r(),r()*TAU,0)); }
      for(const [e,sg] of [[0,-1],[nn-1,1]]){ const [tx,tz]=b.tan(e), [nx,nz]=b.nrm(e); for(const side of [-1,1]){ const off=side*(b.w/2+.7); let prev=null;
        for(let sv=.5;sv<=16;sv+=2){ const x=d[e][0]+tx*sv*sg+nx*off, z=d[e][1]+tz*sv*sg+nz*off, gy=heightAt(x,z); prism(post,x,z,.09,gy-.3,gy+.78,4); if(prev) B.quad(steel,[prev[0],prev[2]+.5,prev[1]],[x,gy+.5,z],[x,gy+.8,z],[prev[0],prev[2]+.8,prev[1]]); prev=[x,z,gy]; } } }
      for(const cp of IDX.camps) if(cp.bridge===bi){ const k=cp.k, [tx,tz]=b.tan(k), [nx,nz]=b.nrm(k), cx=d[k][0]+nx*hw*.35, cz=d[k][1]+nz*hw*.35, gy=heightAt(cx,cz);
        obox(mat('#5a6a4a'),cx+tx*.8,cz+tz*.8,nx,nz,1,.45,gy,gy+.18); obox(mat('#8a6a48'),cx-tx*1.4,cz-tz*1.4,tx,tz,.35,.3,gy,gy+.55); const fx=cx+nx*2.6, fz=cz+nz*2.6, fg=heightAt(fx,fz); for(let i=0;i<9;i++){ const a=i/9*TAU; rocks.push(mtx(fx+Math.cos(a)*.6,fg,fz+Math.sin(a)*.6,.22,.18,.2,0,a,0)); }
        s.extraPois=[{p:[cx,cz],kind:'shelter',what:'undercroft',name:`Under the ${b.name} bridge`,top:gy-.3}]; } });
    for(const c of D.culverts){ const ry=heightAt(c.x,c.z), nx=c.rz, nz=-c.rx; for(const sg of [-1,1]){ const ox=c.x+nx*sg*(c.rhw+1.5), oz=c.z+nz*sg*(c.rhw+1.5), bed=heightAt(ox+nx*sg*2,oz+nz*sg*2), half=c.hw*.85+.6;
      obox(con,ox,oz,c.rx,c.rz,half,.25,bed-.5,ry+.35); for(const w of [-1,1]){ const wx=ox+c.rx*w*half, wz=oz+c.rz*w*half; obox(con,wx+nx*sg*1.1,wz+nz*sg*1.1,nx*sg,nz*sg,1.1,.2,bed-.4,Math.max(bed+.3,ry-.2)); }
      const pr=Math.max(.35,Math.min(.8,(ry-bed)*.33)), np=c.hw>4?2:1; for(let p=0;p<np;p++){ const o=(np===1?0:(p?.9:-.9))*pr*1.4, qx=ox+c.rx*o+nx*sg*.27, qz=oz+c.rz*o+nz*sg*.27, qy=bed+pr+.05; for(let i=0;i<10;i++){ const a=i/10*TAU, a2=(i+1)/10*TAU; B.tri(pipe,[qx,qy,qz],[qx+c.rx*Math.cos(a)*pr,qy+Math.sin(a)*pr,qz+c.rz*Math.cos(a)*pr],[qx+c.rx*Math.cos(a2)*pr,qy+Math.sin(a2)*pr,qz+c.rz*Math.cos(a2)*pr]); } } } }
    const coping=mat('#e2ddd2'), tile=mat('#6fb6c8');
    const sheet=(pts,y,m)=>{ let tris; try{ tris=THREE.ShapeUtils.triangulateShape(pts.map(([x,z])=>new THREE.Vector2(x,z)),[]); }catch(e){ return null; } const pos=[]; for(const t of tris) for(const i of t) pos.push(pts[i][0],y,pts[i][1]); const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.computeVertexNormals(); const me=new THREE.Mesh(g,m); me.receiveShadow=true; me.renderOrder=1; me.userData.noInk=true; return me; };
    for(const l of D.lakes) if(l.sheet.length>=3){ const me=sheet(l.sheet,l.level,LAKE); if(me) grp.add(me); }
    for(const P of D.pools){ const pts=P.pts, [cx,cz]=C.centroid(pts), rad=Math.sqrt(C.area(pts)/Math.PI)||1, outer=pts.map(([x,z])=>[cx+(x-cx)*(1+.45/rad),cz+(z-cz)*(1+.45/rad)]); const me=sheet(pts,P.level-.12,POOL); if(me) grp.add(me);
      for(let i=0;i<pts.length;i++){ const j=(i+1)%pts.length, a=pts[i], b=pts[j], A=outer[i], Bo=outer[j]; B.quad(coping,[a[0],P.level+.1,a[1]],[b[0],P.level+.1,b[1]],[Bo[0],P.level+.1,Bo[1]],[A[0],P.level+.1,A[1]]); B.quad(coping,[A[0],P.low-.3,A[1]],[Bo[0],P.low-.3,Bo[1]],[Bo[0],P.level+.1,Bo[1]],[A[0],P.level+.1,A[1]]); B.quad(tile,[a[0],P.level-.6,a[1]],[b[0],P.level-.6,b[1]],[b[0],P.level+.1,b[1]],[a[0],P.level+.1,a[1]]); } }
    B.meshes().forEach(me=>s.props.add(me)); if(rocks.length){ const rk=new THREE.InstancedMesh(sectorGeo(SHAPES.rock,s),mat('#9c968c'),rocks.length); rocks.forEach((m,i)=>rk.setMatrixAt(i,m)); rk.castShadow=true; s.props.add(rk); } }
  yield 'structures';
  // crease lines for the ink worked out now, one mesh a step, so taking the centre doesn't stall on them
  for(const o of [...s.props.children]) if(o.isMesh&&!o.isInstancedMesh&&!o.userData.noInk&&!o.userData.crease){ o.userData.crease=new THREE.EdgesGeometry(o.geometry,28); yield 'creases'; }
  buildPlants(s,!!centre&&s.c===centre[0]&&s.r===centre[1]);
  yield 'plants';
  // loot pins and labels
  for(const p of [...D.pois,...(s.extraPois||[])]){ const k=KIND[p.kind]; if(!k) continue; const x=p.p[0], z=p.p[1], top=p.top!==undefined?p.top:heightAt(x,z)+6.5;
    const pin=new THREE.Mesh(SHAPES.pin,mat(k.c)); pin.position.set(x,top+3,z); pin.scale.set(1,1.5,1); pin.userData.noInk=true; grp.add(pin); const stem=new THREE.Mesh(SHAPES.stem,mat(k.c)); stem.position.set(x,top+1.5,z); stem.userData.noInk=true; grp.add(stem);
    const el=document.createElement('div'); el.className='lbl'; el.innerHTML=`<i style="background:${k.c}"></i><b>${p.name||String(p.what).replace(/_/g,' ')}</b><span>${k.label}</span>`; labelsEl.appendChild(el); s.labels.push({el,x,z,top,pin}); }
  scene.add(grp);
}
// plants: one instanced mesh per kind. Each sector gets geometry that shares the shape's buffers but carries
// bounds covering the whole sector, so three.js doesn't cull the lot when the shape's own origin is off screen.
// The centre sector shows every plant; the ring keeps trees, cacti and big shrubs, with a lighter saguaro.
function sectorGeo(shape,s){ const g=new THREE.BufferGeometry(); for(const k in shape.attributes) g.setAttribute(k,shape.attributes[k]); g.boundingSphere=new THREE.Sphere(new THREE.Vector3(s.x0+SEC/2,heightAt(s.x0+SEC/2,s.z0+SEC/2),s.z0+SEC/2),SEC*.75); g.userData.proxy=true; return g; }
function buildPlants(s,full){ FK.build(s,full); }
const LAKE=new THREE.MeshStandardMaterial({color:0x3a8fae, roughness:.22, metalness:.1, transparent:true, opacity:.86, side:THREE.DoubleSide, polygonOffset:true, polygonOffsetFactor:-1});
const POOL=new THREE.MeshStandardMaterial({color:0x56c3dc, roughness:.18, metalness:.05, transparent:true, opacity:.9, side:THREE.DoubleSide});
function disposeSector(s){
  if(s.group){ inkOff(s.group); scene.remove(s.group); s.group.traverse(o=>{ if(o.geometry && !SHARED.has(o.geometry) && !FK.SHARED.has(o.geometry)) o.geometry.dispose(); if(o.userData.crease) o.userData.crease.dispose(); if(o.material){ if(o.material.map&&!o.material.userData.keep) o.material.map.dispose(); if(o.userData.ownMat||o.isLineSegments) o.material.dispose(); } if(o.isInstancedMesh) o.dispose&&o.dispose(); }); }
  for(const l of s.labels||[]) l.el.remove();
  if(s.data){ const ns=s.data.nav.n; for(let j=0;j<ns;j++) kindG.fill(255,(s.r*ns+j)*GN+s.c*ns,(s.r*ns+j)*GN+s.c*ns+ns); }
  s.Hf=null; s.data=null; s.state='gone'; }

// ---------- the window: load around the squad, drop what is two away, ink follows the centre ----------
const stats={lastBuild:0,maxStep:0,lastFetch:0,loads:0,drops:0,frame:16,steps:[]};
const jobs=[]; let centre=null;
function want(c,r){ return centre && Math.max(Math.abs(c-centre[0]),Math.abs(r-centre[1]))<=1; }
function ensureWindow(){
  for(let dr=-1;dr<=1;dr++) for(let dc=-1;dc<=1;dc++){ const c=centre[0]+dc, r=centre[1]+dr; if(c<0||r<0||c>=NBX||r>=NBZ) continue; const k=key(c,r); if(sectors.has(k)) continue;
    const s={c,r,x0:BX0+c*SEC,z0:BZ0+r*SEC,state:'fetching',buildMs:0}; sectors.set(k,s); const t0=performance.now();
    fetchSector(c,r).then(d=>{ stats.lastFetch=performance.now()-t0; if(s.state!=='fetching') return; s.data=d; s.state='queued'; jobs.push({s,it:buildSector(s)}); jobs.sort((a,b)=>(a.s.c===centre[0]&&a.s.r===centre[1]?-1:0)-(b.s.c===centre[0]&&b.s.r===centre[1]?-1:0)); })
      .catch(e=>{ console.error(e); s.state='failed'; }); }
  for(const [k,s] of sectors){ if(want(s.c,s.r)) continue; const i=jobs.findIndex(j=>j.s===s); if(i>=0) jobs.splice(i,1); disposeSector(s); sectors.delete(k); stats.drops++; }
}
function setCentre(c,r){ const old=centre&&sectors.get(key(...centre)); centre=[c,r]; const t0=performance.now();
  if(old&&old.state==='built'){ inkOff(old.props); inkOff(old.gen); buildPlants(old,false); }
  const s=sectors.get(key(c,r)); if(s&&s.state==='built'){ buildPlants(s,true); inkOn(s.props); inkOn(s.gen); }
  stats.swap=performance.now()-t0; ensureWindow(); }
function pump(budget){ const t0=performance.now();
  while(jobs.length && performance.now()-t0<budget){ const j=jobs[0]; j.s.state='building'; const ts=performance.now(), res=j.it.next(), dt=performance.now()-ts; j.s.buildMs+=dt; stats.maxStep=Math.max(stats.maxStep,dt); stats.steps.push([res.value||'labels',dt]); if(stats.steps.length>12) stats.steps.shift();
    if(res.done){ jobs.shift(); j.s.state='built'; stats.lastBuild=j.s.buildMs; stats.loads++; if(centre&&j.s.c===centre[0]&&j.s.r===centre[1]){ if(!j.s.full) buildPlants(j.s,true); inkOn(j.s.props); inkOn(j.s.gen); } } } }

// ---------- squad ----------
const squad={x:0,z:0,l:0,heading:0,path:null,trail:[]}; let figs=[], target=new THREE.Vector3(), follow=true;
function spawn(){ const s=sectors.get(key(...centre)); const want0=(s.data.pois.find(p=>/Roadrunner/.test(p.name))||{p:[s.x0+SEC/2,s.z0+SEC/2]}).p;
  let c=cellOf(want0[0]+14,want0[1]+14); if(nodeSpeed(c)<=0) c=nearestPassable(c); const p=nodePos(c);
  figs=[0,1,2,3].map(i=>{ const fem=i%2===1, f=FigureKit.figure(fem,FigureKit.genFace(950+i*7,fem)); f.j=Object.assign({},FigureKit.POSES.stand); f.root.traverse(o=>{ if(o.isMesh) o.castShadow=true; }); f.ink=FigureKit.inkUp(f.root,{persp:true,width:.0016,color:FigureKit.STATES[i===0?'selected':'calm'].c}); scene.add(f.root); f.x=p.x; f.z=p.z+i*.01; f.l=0; return f; });
  Object.assign(squad,{x:p.x,z:p.z,l:0,trail:[{x:p.x,z:p.z,l:0}]}); target.set(p.x,heightAt(p.x,p.z),p.z); }
const inWater=(x,z,l)=>{ if(l) return false; const c=cellOf(x,z); return c>=0&&kindG[c]===NK.water; };
function yOf(x,z,l){ if(l){ const d=deckAt(x,z,.6); if(d) return d.y+.07; } if(!l&&inWater(x,z,0)){ const w=waterLevelAt(x,z); if(w!==null) return w-1.32; } return heightAt(x,z); }

// ---------- camera and input ----------
const VIEWS={tactical:{dist:55,pitch:.85}, street:{dist:9,pitch:.18}, high:{dist:420,pitch:1.0}};
const camS={yaw:.6,pitch:.85,dist:70}, camT={yaw:.6};
let W=1,H=1; function resize(){ W=stage.clientWidth; H=stage.clientHeight; renderer.setSize(W,H,false); cam.aspect=W/Math.max(1,H); cam.updateProjectionMatrix(); } new ResizeObserver(resize).observe(stage); resize();
let drag=null; const ray=new THREE.Raycaster(), ndc=new THREE.Vector2();
renderer.domElement.addEventListener('contextmenu',e=>e.preventDefault());
const pickables=()=>{ const out=[]; for(const s of sectors.values()) if(s.state==='built'){ out.push(s.terrain,...s.picks); } return out; };
const pickAt=e=>{ const r=renderer.domElement.getBoundingClientRect(); ndc.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1); ray.setFromCamera(ndc,cam); const hit=ray.intersectObjects(pickables())[0]; return hit?{p:hit.point,deck:!!hit.object.userData.deck}:null; };
let hover=null; renderer.domElement.addEventListener('pointermove',e=>{ if(!drag) hover=pickAt(e); });
const fmtE=y=>{ const m=Math.round(y+IDX.base); return `${m.toLocaleString()} m · ${Math.round(m*3.281).toLocaleString()} ft`; };
let note='', noteT=-1e9; const say=t=>{ note=t; noteT=performance.now(); };
function where(){ if(squad.l) return 'on the bridge deck'; if(inWater(squad.x,squad.z,0)) return 'swimming'; if(deckAt(squad.x,squad.z)) return 'in the undercroft'; const c=cellOf(squad.x,squad.z); return c>=0&&kindG[c]!==255?IDX.navLabels[kindG[c]].toLowerCase():''; }
function updateReadout(){ let html=`<b>Squad</b> ${fmtE(figs[0]?figs[0].y||0:0)} · ${where()}`;
  if(hover){ const sl=slopeAt(hover.p.x,hover.p.z); html+=`<br><b>Cursor</b> ${fmtE(hover.p.y)} · slope ${Math.round(sl)}°`;
    if(hover.deck) html+=` · bridge deck 5.0 km/h`; else { const c=cellOf(hover.p.x,hover.p.z); if(c>=0&&kindG[c]!==255){ const k=kindG[c]; html+=` · ${IDX.navLabels[k].toLowerCase()} `+(k===NK.water?(ui.swim?`swim ${(SWIM*5).toFixed(1)} km/h`:'needs swim gear'):spG[c]>0?`${(spG[c]/50).toFixed(1)} km/h`:'impassable'); } } }
  if(performance.now()-noteT<2600) html+=`<br><em>${note}</em>`; readout.innerHTML=html; }
function orderMove(h){ let goal;
  if(h.deck) goal=nearestDeckNode(h.p.x,h.p.z);
  else { goal=cellOf(h.p.x,h.p.z); if(goal<0) return; if(nodeSpeed(goal)<=0){ say(kindG[goal]===NK.water?'Water: the squad needs swim gear to cross':kindG[goal]===255?'Not loaded yet':`${IDX.navLabels[kindG[goal]]}: can't go there`); goal=nearestPassable(goal); if(goal<0) return; } }
  let start=squad.l?nearestDeckNode(squad.x,squad.z):cellOf(squad.x,squad.z); if(start<GNN&&nodeSpeed(start)<=0) start=nearestPassable(start);
  const t0=performance.now(), res=findPath(start,goal); stats.path=performance.now()-t0; if(!res){ say('No way through from here'); return; }
  squad.path=smoothPath(res.nodes); squad.wp=1; follow=true; let m=0; for(let i=1;i<squad.path.length;i++) m+=Math.hypot(squad.path[i].x-squad.path[i-1].x,squad.path[i].z-squad.path[i-1].z);
  say(`${Math.round(m)} m, about ${Math.max(1,Math.round(res.cost/1.39/60))} min at walking pace · path found in ${stats.path.toFixed(0)} ms`);
  const end=squad.path[squad.path.length-1]; marker.position.set(end.x,yOf(end.x,end.z,end.l)+.06,end.z); marker.visible=true; markerT=performance.now(); }
renderer.domElement.addEventListener('pointerdown',e=>{ drag={x:e.clientX,y:e.clientY,b:e.button,moved:false,yaw:camT.yaw,pitch:VIEWS[ui.view].pitch,tx:target.x,tz:target.z}; renderer.domElement.setPointerCapture(e.pointerId); });
renderer.domElement.addEventListener('pointermove',e=>{ if(!drag) return; const dx=e.clientX-drag.x, dy=e.clientY-drag.y; if(Math.hypot(dx,dy)>4) drag.moved=true; if(!drag.moved) return;
  if(drag.b===2||e.shiftKey){ follow=false; const sc=VIEWS[ui.view].dist/600, c=Math.cos(camT.yaw), sn=Math.sin(camT.yaw); target.x=drag.tx-(dx*c-dy*sn)*sc*1.6; target.z=drag.tz-(-dx*sn-dy*c)*sc*1.6; target.y=heightAt(target.x,target.z); }
  else { camT.yaw=drag.yaw-dx*.006; VIEWS[ui.view].pitch=Math.max(.08,Math.min(1.35,drag.pitch+dy*.004)); } });
renderer.domElement.addEventListener('pointerup',e=>{ const d=drag; drag=null; if(!d||d.moved||d.b!==0) return; const h=pickAt(e); if(h) orderMove(h); });
renderer.domElement.addEventListener('wheel',e=>{ e.preventDefault(); const v=VIEWS[ui.view]; v.dist=Math.max(ui.view==='street'?4:15,Math.min(800,v.dist*Math.exp(e.deltaY*.001))); },{passive:false});
const marker=new THREE.Mesh(new THREE.RingGeometry(.9,1.2,24),new THREE.MeshBasicMaterial({color:0xffffff,transparent:true,opacity:.8,depthWrite:false})); marker.rotation.x=-Math.PI/2; marker.visible=false; scene.add(marker); let markerT=0;
document.getElementById('segView').addEventListener('click',e=>{ const b=e.target.closest('button[data-v]'); if(!b) return; document.querySelectorAll('#segView button').forEach(x=>x.setAttribute('aria-pressed',String(x===b))); ui.view=b.dataset.v; follow=true; });
document.getElementById('tglSwim').addEventListener('change',e=>{ ui.swim=e.target.checked; });
// places worth a look: the squad is set down there and the camera framed on it
document.getElementById('places')?.addEventListener('click',e=>{ const b=e.target.closest('button[data-p]'); if(!b||!figs.length) return; const [x,z,yaw,pitch,dist]=b.dataset.p.split(',').map(Number);
  window.__stream.teleport(x,z); ui.view='tactical'; document.querySelectorAll('#segView button').forEach(q=>q.setAttribute('aria-pressed',String(q.dataset.v==='tactical'))); camT.yaw=yaw; VIEWS.tactical.pitch=pitch; VIEWS.tactical.dist=dist; say(b.textContent); });
document.getElementById('tglSeams').addEventListener('change',e=>{ ui.seams=e.target.checked; for(const s of sectors.values()) if(s.seam) s.seam.visible=ui.seams; });

// ---------- panels ----------
miniEl.style.gridTemplateColumns=`repeat(${NBX},1fr)`; miniEl.style.aspectRatio=`${NBX}/${NBZ}`;
const cells=[]; for(let r=0;r<NBZ;r++) for(let c=0;c<NBX;c++){ const i=document.createElement('i'); i.title=`Sector ${c+1},${r+1}: go there`; i.addEventListener('click',()=>jumpTo(c,r)); miniEl.appendChild(i); cells.push(i); } const dot=document.createElement('b'); miniEl.appendChild(dot);
const tot=IDX.sectors.reduce((a,s)=>a+s.bytes,0);
blockEl.innerHTML=`<div><dt>Size</dt><dd>${NBX} × ${NBZ} sectors, ${(NBX*SEC/1000).toFixed(1)} by ${(NBZ*SEC/1000).toFixed(1)} km</dd></div><div><dt>Sector files</dt><dd>${(tot/1e6).toFixed(1)} MB of JSON, about ${Math.round(IDX.sectors.reduce((a,s)=>a+s.gz,0)/IDX.sectors.length/1000)} KB each compressed</dd></div>
  <div><dt>Buildings</dt><dd>${IDX.sectors.reduce((a,s)=>a+s.b,0)}</dd></div><div><dt>Plants</dt><dd>${IDX.sectors.reduce((a,s)=>a+s.plants,0).toLocaleString()}</dd></div><div><dt>Bridges</dt><dd>${IDX.bridges.length}</dd></div>`;
function updatePanels(){
  for(let r=0;r<NBZ;r++) for(let c=0;c<NBX;c++){ const s=sectors.get(key(c,r)); cells[r*NBX+c].dataset.s=!s?'':s.state==='built'?(centre[0]===c&&centre[1]===r?'centre':'ring'):s.state==='building'?'building':'queued'; }
  dot.style.left=((squad.x-BX0)/(NBX*SEC)*100)+'%'; dot.style.top=((squad.z-BZ0)/(NBZ*SEC)*100)+'%';
  const inf=renderer.info, built=[...sectors.values()].filter(s=>s.state==='built').length, mem=performance.memory?Math.round(performance.memory.usedJSHeapSize/1e6)+' MB':'n/a';
  costEl.innerHTML=`<div><dt>Loaded</dt><dd>${built} of 9 · ${jobs.length} queued</dd></div><div><dt>Last sector build</dt><dd>${Math.round(stats.lastBuild)} ms</dd></div><div><dt>Longest single step</dt><dd>${Math.round(stats.maxStep)} ms</dd></div>
    <div><dt>Centre swap</dt><dd>${Math.round(stats.swap||0)} ms</dd></div><div><dt>Last fetch</dt><dd>${Math.round(stats.lastFetch)} ms</dd></div><div><dt>Frame</dt><dd>${stats.frame.toFixed(1)} ms</dd></div><div><dt>Draw calls</dt><dd>${inf.render.calls}</dd></div><div><dt>Triangles</dt><dd>${(inf.render.triangles/1e6).toFixed(2)} M</dd></div>
    <div><dt>GPU geometries · textures</dt><dd>${inf.memory.geometries} · ${inf.memory.textures}</dd></div><div><dt>JS heap</dt><dd>${mem}</dd></div><div><dt>Loaded · dropped</dt><dd>${stats.loads} · ${stats.drops}</dd></div>`; }

// ---------- frame loop ----------
const PACE=2.6, GAIT=PACE/1.39;   // the squad moves faster than real walking pace (1.39 m/s); motion shows a walk played faster
// ---------- time: exploring runs in real time; pause, 1× and 4× as on the map ----------
const TM={speed:1, sec:0, base:7.5*60, snap:false};   // game seconds since arriving; base is the clock in game minutes
{ const css=document.createElement('style'); css.textContent=`.tclock{position:absolute;right:10px;top:10px;display:flex;gap:4px;align-items:center;z-index:3;background:rgba(24,24,26,.82);border:1px solid #38393d;border-radius:4px;padding:4px 6px}
  .tclock b{font:500 13px var(--mono,monospace);color:#e2e0dc;margin-right:4px;white-space:nowrap}.tclock button{background:#2d2f33;border:1px solid #38393d;color:#e2e0dc;font:600 12px var(--body,sans-serif);padding:3px 8px;cursor:pointer;border-radius:3px}
  .tclock button[aria-pressed="true"]{border-color:#e0a526;color:#e0a526}.mini i{cursor:pointer}.mini i:hover{outline:1px solid #e0a526;outline-offset:-1px}`; document.head.appendChild(css); }
const clockBox=document.createElement('div'); clockBox.className='tclock'; clockBox.innerHTML='<b id="tclk"></b><button type="button" data-ts="0" aria-pressed="false" title="Pause">❚❚</button><button type="button" data-ts="1" aria-pressed="true">1×</button><button type="button" data-ts="4" aria-pressed="false">4×</button>'; stage.appendChild(clockBox);
const clkEl=clockBox.querySelector('#tclk');
function setSpeed(k){ TM.speed=k; clockBox.querySelectorAll('[data-ts]').forEach(b=>b.setAttribute('aria-pressed',String(+b.dataset.ts===k))); }
clockBox.addEventListener('click',e=>{ const b=e.target.closest('[data-ts]'); if(b) setSpeed(+b.dataset.ts); });
window.addEventListener('keydown',e=>{ if(e.target.closest&&e.target.closest('input,textarea,button,select')) return; if(e.code==='Space'){ e.preventDefault(); setSpeed(TM.speed?0:1); } });
let clkShown='';
function drawClock(){ const m=TM.base+TM.sec/60, d=Math.floor(m/1440)+1, h=Math.floor((m%1440)/60), mm=Math.floor(m%60), ss=Math.floor((m*60)%60), t=`Day ${d} ${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}:${String(ss).padStart(2,'0')}`; if(t!==clkShown){ clkShown=t; clkEl.textContent=t; } }
// jump to a sector from the overview: the squad is set down at its middle, then on the nearest walkable cell once it has loaded
function jumpTo(c,r){ const x=BX0+(c+.5)*SEC, z=BZ0+(r+.5)*SEC;
  if(figs.length){ Object.assign(squad,{x,z,l:0,path:null,trail:[{x,z,l:0}]}); figs.forEach((f,i)=>{ f.x=x; f.z=z+i*.01; f.y=undefined; }); follow=true; TM.snap=true; }
  else { follow=false; }
  target.set(x,heightAt(x,z),z); }
function snapSquad(){ const s=sectors.get(key(...centre)); if(!s||s.state!=='built') return; TM.snap=false; const c=cellOf(squad.x,squad.z); if(c>=0&&nodeSpeed(c)>0) return; const n=nearestPassable(c); if(n<0) return;
  const p=nodePos(n); Object.assign(squad,{x:p.x,z:p.z,trail:[{x:p.x,z:p.z,l:0}]}); figs.forEach((f,i)=>{ f.x=p.x; f.z=p.z+i*.01; f.y=undefined; }); }
let last=performance.now(), boost=1, panelT=0; const tmp=new THREE.Vector3();
const speedHere=(x,z,l)=>{ if(l) return 1; const c=cellOf(x,z); return c<0?.7:Math.max(.15,nodeSpeed(c)||.3); };
function trailAt(back){ const T=squad.trail; let acc=Math.hypot(squad.x-T[T.length-1].x,squad.z-T[T.length-1].z); if(acc>=back) return null;
  for(let i=T.length-1;i>0;i--){ const a=T[i], b=T[i-1], l=Math.hypot(a.x-b.x,a.z-b.z); if(acc+l>=back){ const t=(back-acc)/(l||1); return {x:a.x+(b.x-a.x)*t,z:a.z+(b.z-a.z)*t,l:t<.5?a.l:b.l}; } acc+=l; } return T[0]; }
function loop(now){
  requestAnimationFrame(loop); const raw=now-last; last=now; stats.frame+=(raw-stats.frame)*.05; const rdt=Math.min(.05,raw/1000), dt=rdt*boost*TM.speed; TM.sec+=dt; drawClock();   // the camera keeps real time so it still moves while paused
  pump(8);
  if(!figs.length){ const s=centre&&sectors.get(key(...centre)); if(s&&s.state==='built'&&[...sectors.values()].every(q=>q.state==='built'||q.state==='failed')){ spawn(); loadingEl.hidden=true; } else { renderer.render(scene,cam); return; } }
  let moving=false;
  if(squad.path){ const wp=squad.path[squad.wp], dx=wp.x-squad.x, dz=wp.z-squad.z, d=Math.hypot(dx,dz), m=speedHere(squad.x,squad.z,squad.l), step=PACE*m*dt;
    if(wp.l&&!squad.l&&d<1.5) squad.l=1; if(!wp.l&&squad.l&&d<1.5) squad.l=0;
    if(d<=step){ squad.x=wp.x; squad.z=wp.z; squad.l=wp.l; if(++squad.wp>=squad.path.length) squad.path=null; } else { squad.x+=dx/d*step; squad.z+=dz/d*step; }
    if(d>.01) squad.heading=Math.atan2(dx,dz); moving=true;
    const T=squad.trail, lt=T[T.length-1]; if(Math.hypot(lt.x-squad.x,lt.z-squad.z)>.4){ T.push({x:squad.x,z:squad.z,l:squad.l}); if(T.length>300) T.shift(); } }
  // crossing into another sector moves the window
  const q=secAt(squad.x,squad.z); if(q&&(q[0]!==centre[0]||q[1]!==centre[1])) setCentre(...q);
  if(TM.snap) snapSquad();
  figs.forEach((f,i)=>{
    if(i===0){ f.x=squad.x; f.z=squad.z; f.l=squad.l; if(moving){ let a=squad.heading-f.root.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); f.root.rotation.y+=a*Math.min(1,dt*10); } }
    else { const tp=trailAt(i*1.9); if(tp){ const ddx=tp.x-f.x, ddz=tp.z-f.z, dd=Math.hypot(ddx,ddz); if(dd>.12){ const sp=Math.min(dd,PACE*1.15*speedHere(f.x,f.z,f.l)*dt+Math.max(0,dd-1)*dt*2); f.x+=ddx/dd*sp; f.z+=ddz/dd*sp; let a=Math.atan2(ddx,ddz)-f.root.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); f.root.rotation.y+=a*Math.min(1,dt*8); } f.l=tp.l; } }
    const swim=inWater(f.x,f.z,f.l), y=yOf(f.x,f.z,f.l); f.y=(f.y===undefined?y:f.y+(y-f.y)*Math.min(1,dt*(swim?4:14))); f.root.position.set(f.x,f.y,f.z);
    // gait, idles and swimming come from the shared motion module; feet find the ground or the bridge deck they are on
    Motion.update(f,{act:swim?'swim':'idle',ground:(x,z)=>yOf(x,z,f.l),compress:GAIT},dt); });
  if(marker.visible){ const a=(now-markerT)/900; marker.material.opacity=Math.max(0,.8-a*.6); marker.scale.setScalar(1+a*.4); if(a>1.4) marker.visible=false; }
  // camera
  const sy=figs[0].y||0;
  if(follow){ target.x+=(squad.x-target.x)*Math.min(1,rdt*3); target.z+=(squad.z-target.z)*Math.min(1,rdt*3); target.y+=(sy+(ui.view==='street'?1.4:0)-target.y)*Math.min(1,rdt*4); }
  const V=VIEWS[ui.view], kk=1-Math.exp(-rdt*6); camS.dist+=(V.dist-camS.dist)*kk; camS.pitch+=(V.pitch-camS.pitch)*kk; const ay=camT.yaw-camS.yaw; camS.yaw+=Math.atan2(Math.sin(ay),Math.cos(ay))*kk;
  cam.position.set(target.x+Math.sin(camS.yaw)*Math.cos(camS.pitch)*camS.dist, target.y+Math.sin(camS.pitch)*camS.dist, target.z+Math.cos(camS.yaw)*Math.cos(camS.pitch)*camS.dist);
  const gy=heightAt(cam.position.x,cam.position.z)+1.2; if(cam.position.y<gy) cam.position.y=gy; cam.lookAt(target);
  sun.position.set(target.x+.45*400,target.y+.8*400,target.z+.35*400); sun.target.position.copy(target); const R=ui.view==='high'?420:110;
  Object.assign(sun.shadow.camera,{left:-R,right:R,top:R,bottom:-R,near:10,far:1400}); sun.shadow.camera.updateProjectionMatrix();
  scene.fog.near=ui.view==='high'?700:380; scene.fog.far=ui.view==='high'?1600:980;
  updateReadout(); renderer.render(scene,cam);
  for(const s of sectors.values()) for(const l of s.labels||[]){ l.pin.rotation.y=now/900; tmp.set(l.x,l.top+5.2,l.z); const p=tmp.project(cam), show=p.z<1&&Math.hypot(l.x-target.x,l.z-target.z)<(ui.view==='high'?900:180)&&Math.abs(p.x)<1.05&&Math.abs(p.y)<1.05; l.el.style.display=show?'':'none'; if(show) l.el.style.transform=`translate(${(p.x+1)/2*W}px,${(1-p.y)/2*H}px) translate(-50%,-100%)`; }
  whereEl.textContent=`New River · sector ${centre[0]+1},${centre[1]+1}`;
  if((panelT+=raw)>400){ panelT=0; updatePanels(); }
}
window.__stream={scene,squad,sectors,stats,orderMove:(x,z,deck)=>orderMove({p:new THREE.Vector3(x,heightAt(x,z),z),deck}),boost:k=>{ boost=k; },heightAt,ui,look:(x,z,yaw,pitch,dist)=>{ follow=false; target.set(x,heightAt(x,z),z); camT.yaw=yaw; VIEWS[ui.view].pitch=pitch; VIEWS[ui.view].dist=dist; },follow:()=>{ follow=true; },renderer,teleport:(x,z)=>{ Object.assign(squad,{x,z,l:0,path:null,trail:[{x,z,l:0}]}); figs.forEach((f,i)=>{ f.x=x; f.z=z+i*.01; f.y=undefined; }); target.set(x,heightAt(x,z),z); follow=true; },lowfi:()=>{ renderer.shadowMap.enabled=false; renderer.setPixelRatio(1); resize(); }};
// start where the frame is centred: the New River sector
setCentre(...(secAt(0,0)||[Math.floor(NBX/2),Math.floor(NBZ/2)])); requestAnimationFrame(loop);
})();
