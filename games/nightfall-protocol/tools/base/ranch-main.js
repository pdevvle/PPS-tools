// ---------- the base page: real ground, a base founded anywhere on it, things placed on the 2 m grid, survivors at work ----------
// Draws what ranch-core.js holds and takes orders. RANCH_SITE (the cut of the baked block) is inlined by build.sh.
(function(){
const R=Ranch, TAU=Math.PI*2;
const $=id=>document.getElementById(id);
const stage=$('stage'), labelsEl=$('labels'), tipEl=$('tip'), loadingEl=$('loading');
if(!window.THREE){ loadingEl.textContent='The 3D view needs three.js, which could not load. Check your connection and reload.'; return; }
let renderer; try{ renderer=new THREE.WebGLRenderer({antialias:true,alpha:true}); }catch(e){ loadingEl.textContent='This browser could not start WebGL.'; return; }
renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1)); renderer.localClippingEnabled=true;   // sites rise from the ground with a clipping plane
 renderer.shadowMap.enabled=true; renderer.shadowMap.type=THREE.PCFSoftShadowMap; renderer.setClearColor(0,0); stage.prepend(renderer.domElement);
const scene=new THREE.Scene(); scene.fog=new THREE.Fog(0xe2d8c2,420,1100);
const cam=new THREE.PerspectiveCamera(38,1,.5,4000);
const hemi=new THREE.HemisphereLight(0xfff6e6,0x8a7a62,.34), sun=new THREE.DirectionalLight(0xfff1da,.8); sun.castShadow=true; sun.shadow.mapSize.set(2048,2048);
{ const c=sun.shadow.camera; c.left=c.bottom=-110; c.right=c.top=110; c.near=1; c.far=600; } sun.shadow.bias=-.0005; sun.shadow.normalBias=.04; scene.add(hemi,sun,sun.target);

// ---------- the ranch ----------
let st=R.create(RANCH_SITE,{centre:RANCH_SITE.presets[0].centre});
const S=st.site, H=(x,z)=>R.heightAt(x,z);
const X0=S.x0, Z0=S.z0, WX=S.w, WZ=S.d, CX=X0+WX/2, CZ=Z0+WZ/2;

// ---------- materials and shapes (ink faceted, as the streaming page) ----------
const RAMP=(()=>{ const t=new THREE.DataTexture(new Uint8Array([88,88,88, 170,170,170, 235,235,235]),3,1,THREE.RGBFormat); t.minFilter=t.magFilter=THREE.NearestFilter; t.generateMipmaps=false; t.needsUpdate=true; return t; })();
const MC=new Map(); const mat=c=>{ let m=MC.get(c); if(!m){ m=new THREE.MeshStandardMaterial({color:c,flatShading:true,roughness:.92,metalness:0,side:THREE.DoubleSide}); MC.set(c,m); } return m; };
class Batch{ constructor(){ this.m=new Map(); } tri(m,a,b,c){ let arr=this.m.get(m); if(!arr){ arr=[]; this.m.set(m,arr); } arr.push(...a,...b,...c); } quad(m,a,b,c,d){ this.tri(m,a,b,c); this.tri(m,a,c,d); }
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
};
const INK=(()=>{ const m=new THREE.MeshBasicMaterial({color:0x231c17,side:THREE.BackSide}); m.onBeforeCompile=sh=>{ sh.vertexShader=sh.vertexShader.replace('#include <project_vertex>',
  `vec4 mvPosition=vec4(transformed,1.0); vec3 nn=normal;
   #ifdef USE_INSTANCING
     mvPosition=instanceMatrix*mvPosition; nn=mat3(instanceMatrix)*nn;
   #endif
   mvPosition=modelViewMatrix*mvPosition; mvPosition.xyz+=normalize(normalMatrix*nn)*0.0011*(-mvPosition.z); gl_Position=projectionMatrix*mvPosition;`); }; m.customProgramCacheKey=()=>'inkRanch'; return m; })();
const CREASE=new THREE.LineBasicMaterial({color:0x2d241d,transparent:true,opacity:.55});
function inkOn(group){ const list=[]; group.traverse(o=>{ if(o.isMesh&&!o.userData.ink&&!o.userData.noInk) list.push(o); });
  for(const o of list){ const sh=o.isInstancedMesh?new THREE.InstancedMesh(o.geometry,INK,o.count):new THREE.Mesh(o.geometry,INK); if(o.isInstancedMesh) sh.instanceMatrix=o.instanceMatrix; sh.userData.ink=true; sh.matrixAutoUpdate=false; o.add(sh);
    if(!o.isInstancedMesh){ const ln=new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry,28),CREASE); ln.userData.ink=true; ln.matrixAutoUpdate=false; o.add(ln); } } }
function dispose(o){ o.traverse(q=>{ if(q.geometry&&!q.geometry.userData.shared) q.geometry.dispose(); }); if(o.parent) o.parent.remove(o); }

// ---------- the ground: heights, a texture painted from the real features, and its shading ----------
const terrain=(()=>{
  const TW=4096, TH=Math.round(TW*WZ/WX), cv=document.createElement('canvas'); cv.width=TW; cv.height=TH; const TS=TW, g=cv.getContext('2d'), X=x=>(x-X0)/WX*TW, Z=z=>(z-Z0)/WZ*TH, px=TW/WX, rr=(()=>{ let s=4242; return ()=>{ s=(Math.imul(s,1664525)+1013904223)>>>0; return s/4294967296; }; })();
  g.fillStyle='#cdb48c'; g.fillRect(0,0,TW,TH);
  for(let i=0;i<120;i++){ const x=rr()*TW,y=rr()*TH,rad=40+rr()*160,gr=g.createRadialGradient(x,y,0,x,y,rad); gr.addColorStop(0,`rgba(${rr()<.5?'150,120,85':'220,200,165'},.3)`); gr.addColorStop(1,'rgba(0,0,0,0)'); g.fillStyle=gr; g.fillRect(x-rad,y-rad,rad*2,rad*2); }
  for(let i=0;i<200000;i++){ g.fillStyle=rr()<.5?'rgba(120,95,70,.22)':'rgba(240,225,200,.22)'; g.fillRect(rr()*TW,rr()*TH,1.5,1.5); }
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  const line=(pts,w,col)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.lineWidth=Math.max(.6,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.stroke(); };
  const AREA={residential:'#d4c09c',scree:'#ae9d84',sand:'#dcc7a0'};
  for(const a of S.areas) if(AREA[a.kind]) poly(a.pts,AREA[a.kind]);
  for(const b of S.beds) poly(b,'#dac7a0');
  for(const w of S.water){ line(w.pts,w.hw*2+4,'#b9a07a'); line(w.pts,w.hw*2-1,'#dcc9a2'); line(w.pts,w.hw*.6,'#cbb48c'); }
  // brush cells from the movement grid: darker scrub under the shrubs
  const N=S.NX*S.NZ; for(let c=0;c<N;c++) if(S.kind0[c]===R.NK.brush){ const [x,z]=R.cellXZ(c); g.fillStyle='rgba(120,110,70,.16)'; g.fillRect(X(x-1),Z(z-1),2*px,2*px); }
  for(const rd of [...S.roads].sort((a,b)=>a.w-b.w)) line(rd.pts,rd.w+(rd.drive?2.4:.8),rd.paved?'#b8b1a3':'#b79f7b');
  // hill shading from the heights
  { const nx=S.hnx, nz=S.hnz, sh=document.createElement('canvas'); sh.width=nx; sh.height=nz; const sg=sh.getContext('2d'), img=sg.createImageData(nx,nz), L=[-.5,.7,-.5], ll=Math.hypot(...L), flat=L[1]/ll;
    for(let j=0;j<nz;j++) for(let i=0;i<nx;i++){ const h=(a,b)=>S.Hf[Math.min(nz-1,Math.max(0,b))*nx+Math.min(nx-1,Math.max(0,a))], dx=(h(i+1,j)-h(i-1,j))/8, dz=(h(i,j+1)-h(i,j-1))/8, nn=[-dx,1,-dz], nl=Math.hypot(...nn), v=((nn[0]*L[0]+nn[1]*L[1]+nn[2]*L[2])/(nl*ll)-flat)*2.4, o=(j*nx+i)*4;
      if(v<0) img.data.set([70,45,25,Math.min(.6,-v)*255],o); else img.data.set([255,248,230,Math.min(.4,v)*255],o); }
    sg.putImageData(img,0,0); g.imageSmoothingEnabled=true; g.drawImage(sh,X(X0-4)-2*px,Z(Z0-4)-2*px,nx*4*px,nz*4*px); }
  const tex=new THREE.CanvasTexture(cv); tex.anisotropy=renderer.capabilities.getMaxAnisotropy();
  const tg=new THREE.PlaneGeometry(WX,WZ,WX/2,WZ/2); tg.rotateX(-Math.PI/2); const p=tg.attributes.position;
  for(let i=0;i<p.count;i++) p.setY(i,H(p.getX(i)+CX,p.getZ(i)+CZ)); tg.computeVertexNormals();
  const me=new THREE.Mesh(tg,new THREE.MeshToonMaterial({map:tex,gradientMap:RAMP})); me.position.set(CX,0,CZ); me.receiveShadow=true; me.userData.noInk=true; scene.add(me);
  // a skirt so the edge of the cut never shows a void
  const lo=Math.min(...S.Hf)-1, sk=new THREE.Mesh(new THREE.PlaneGeometry(6000,6000),new THREE.MeshLambertMaterial({color:0xc6ab83})); sk.rotation.x=-Math.PI/2; sk.position.set(CX,lo,CZ); scene.add(sk);
  return {mesh:me,geo:tg}; })();

// ---------- roads, baked walls, buildings, plants ----------
const STUCCO=['#e4d6bd','#dccbb0','#e8dcc6','#d6c3a3','#eadfcb'], TILE=['#b5643f','#a8563a','#c07a4f','#9c5a3c'];
{ const B=new Batch(), asphalt=mat('#4c4b49'), dirt=mat('#bfa47f'), walk=mat('#cfc8ba'), paint=mat('#e1b53c');
  const dens=(pts,step)=>{ const out=[]; for(let i=0;i<pts.length-1;i++){ const a=pts[i], b=pts[i+1], n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/step)); for(let k=0;k<n;k++) out.push([a[0]+(b[0]-a[0])*k/n,a[1]+(b[1]-a[1])*k/n]); } out.push(pts[pts.length-1]); return out; };
  const inCut=(x,z)=>x>=X0-1&&x<=X0+WX+1&&z>=Z0-1&&z<=Z0+WZ+1;
  S.roads.forEach((rd,ri)=>{ const w=rd.w/2, m=!rd.drive?walk:rd.paved?asphalt:dirt, lift=.06+ri*.0004, pts=dens(rd.pts,4).filter(([x,z])=>inCut(x,z)); if(pts.length<2) return;
    const side=(i,off)=>{ const p=pts[i], q=pts[Math.min(pts.length-1,i+1)], o=pts[Math.max(0,i-1)], dx=q[0]-o[0], dz=q[1]-o[1], l=Math.hypot(dx,dz)||1, x=p[0]+dz/l*off, z=p[1]-dx/l*off; return [x,H(x,z)+lift,z]; };
    for(let i=0;i<pts.length-1;i++){ if(Math.hypot(pts[i+1][0]-pts[i][0],pts[i+1][1]-pts[i][1])>8) continue; B.quad(m,side(i,-w),side(i+1,-w),side(i+1,w),side(i,w)); if(m===asphalt&&rd.cls==='secondary') B.quad(paint,side(i,-.12),side(i+1,-.12),side(i+1,.12),side(i,.12)); } });
  for(const me of B.meshes(false)){ me.material=me.material.clone(); me.material.polygonOffset=true; me.material.polygonOffsetFactor=-2; me.material.polygonOffsetUnits=-2; me.userData.noInk=true; scene.add(me); } }
const bldMesh=new Map();   // site building → its group, so a building taken apart can go and come back when a base is founded again
let bldGroup=null;
function buildBuildings(){ if(bldGroup) dispose(bldGroup); bldGroup=new THREE.Group(); bldMesh.clear();
  const rr=(()=>{ let s=77; return ()=>{ s=(Math.imul(s,1664525)+1013904223)>>>0; return s/4294967296; }; })(), metal=mat('#9aa3a8'), props=bldGroup;
  const area=pts=>{ let s=0; for(let i=0,j=pts.length-1;i<pts.length;j=i++) s+=(pts[j][0]+pts[i][0])*(pts[j][1]-pts[i][1]); return Math.abs(s/2); };
  for(const b of S.buildings){ const B=new Batch(), pts=b.pts, Ar=area(pts), cx=pts.reduce((s,p)=>s+p[0],0)/pts.length, cz=pts.reduce((s,p)=>s+p[1],0)/pts.length, hs=pts.map(([x,z])=>H(x,z)), lo=Math.min(...hs)-.3, hiG=Math.max(...hs);
    const barn=!b.house&&Ar>=200, shed=!b.house&&Ar<120, Ht=barn?4.6:shed?2.8:3.3, top=hiG+Ht, wallM=mat(barn?'#9a8a74':shed?'#a9a39a':STUCCO[Math.floor(rr()*STUCCO.length)]);
    for(let i=0;i<pts.length;i++){ const [x,z]=pts[i], [x2,z2]=pts[(i+1)%pts.length]; B.quad(wallM,[x,lo,z],[x2,lo,z2],[x2,top,z2],[x,top,z]); }
    let tris; try{ tris=THREE.ShapeUtils.triangulateShape(pts.map(([x,z])=>new THREE.Vector2(x,z)),[]); }catch(e){ tris=[]; }
    if(shed||barn){ const m=shed?metal:mat('#8f8b84'); for(const [a,b2,c] of tris) B.tri(m,[pts[a][0],top,pts[a][1]],[pts[b2][0],top,pts[b2][1]],[pts[c][0],top,pts[c][1]]); }
    else { const roofM=mat(TILE[Math.floor(rr()*TILE.length)]), rad=Math.sqrt(Ar/Math.PI), k=Math.max(.3,1-2.2/rad), rise=Math.min(1.8,.35*rad+.5);
      const eave=pts.map(([x,z])=>[cx+(x-cx)*1.06,top-.15,cz+(z-cz)*1.06]), inner=pts.map(([x,z])=>[cx+(x-cx)*k,top+rise,cz+(z-cz)*k]);
      for(let i=0;i<pts.length;i++){ const j=(i+1)%pts.length; B.quad(roofM,eave[i],eave[j],inner[j],inner[i]); } for(const [a,b2,c] of tris) B.tri(roofM,inner[a],inner[b2],inner[c]); }
    const grp=new THREE.Group(); B.meshes().forEach(me=>grp.add(me)); grp.userData.top=top+1; props.add(grp); bldMesh.set(b.pts,grp); }
  inkOn(props); scene.add(props); }
buildBuildings();
{ const props=new THREE.Group(), B=new Batch(), block=mat('#c7b596'), fence=mat('#8a7a66');
  for(const w of S.walls){ const a=[w[0],w[1]], b=[w[2],w[3]], h=w[4], t=w[5], m=w[6]?fence:block, L=Math.hypot(b[0]-a[0],b[1]-a[1]); if(L<.2) continue; const nx=-(b[1]-a[1])/L*t/2, nz=(b[0]-a[0])/L*t/2, ya=H(...a)-.3, yb=H(...b)-.3, ta=ya+h+.3, tb=yb+h+.3;
    for(const sg of [1,-1]) B.quad(m,[a[0]+nx*sg,ya,a[1]+nz*sg],[b[0]+nx*sg,yb,b[1]+nz*sg],[b[0]+nx*sg,tb,b[1]+nz*sg],[a[0]+nx*sg,ta,a[1]+nz*sg]); B.quad(m,[a[0]+nx,ta,a[1]+nz],[b[0]+nx,tb,b[1]+nz],[b[0]-nx,tb,b[1]-nz],[a[0]-nx,ta,a[1]-nz]); }
  B.meshes().forEach(me=>props.add(me));
  const L=[[],[],[],[],[]]; for(const p of S.plants) L[p[0]].push(mtx(p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8],0));
  const inst=(shape,m,list)=>{ if(!list.length) return; const me=new THREE.InstancedMesh(shape,m,list.length); list.forEach((mm,i)=>me.setMatrixAt(i,mm)); me.castShadow=true; me.receiveShadow=true; me.frustumCulled=false; props.add(me); };
  inst(SHAPES.saguaro,mat('#5f7d3f'),L[0]); inst(SHAPES.trunk,mat('#8a9a52'),L[1]); inst(SHAPES.canopy,mat('#a7b85a'),L[1]); inst(SHAPES.shrub,mat('#6e7f45'),L[2]); inst(SHAPES.rock,mat('#a8937a'),L[3]); inst(SHAPES.reed,mat('#7f9248'),L[4]);
  // plants on cells that get built over are hidden (a bed in a bush looks wrong)
  props.userData.plants=L; inkOn(props); scene.add(props); }

// ---------- overlays: the buildable area and the movement grid ----------
let areaLine=null;
function drawArea(){ const A=st.area, vis=areaLine?areaLine.visible:true; if(areaLine) dispose(areaLine); const pts=[]; const edge=(ax,az,bx,bz)=>{ for(let t=0;t<1;t+=.02){ const x=ax+(bx-ax)*t, z=az+(bz-az)*t, x2=ax+(bx-ax)*(t+.02), z2=az+(bz-az)*(t+.02); pts.push(x,H(x,z)+.25,z,x2,H(x2,z2)+.25,z2); } };
  edge(A[0],A[1],A[2],A[1]); edge(A[2],A[1],A[2],A[3]); edge(A[2],A[3],A[0],A[3]); edge(A[0],A[3],A[0],A[1]);
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pts,3)); areaLine=new THREE.LineSegments(g,new THREE.LineDashedMaterial({color:0xe0a526,dashSize:2,gapSize:1.4})); areaLine.computeLineDistances(); areaLine.visible=vis; scene.add(areaLine); }
drawArea();
const gridCv=document.createElement('canvas'); gridCv.width=S.NX; gridCv.height=S.NZ;
const gridTex=new THREE.CanvasTexture(gridCv); gridTex.magFilter=THREE.NearestFilter; gridTex.minFilter=THREE.NearestFilter;
const gridMesh=new THREE.Mesh(terrain.geo,new THREE.MeshBasicMaterial({map:gridTex,transparent:true,opacity:.62,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-4,polygonOffsetUnits:-4}));
gridMesh.position.copy(terrain.mesh.position); gridMesh.visible=false; gridMesh.renderOrder=2; scene.add(gridMesh);
const KCOL={0:[217,201,163],1:[85,85,85],2:[168,145,106],3:[194,167,122],4:[119,119,119],5:[185,196,138],6:[232,217,168],7:[138,154,90],8:[156,132,102],9:[74,139,194],10:[192,57,43],11:[34,34,34],12:[92,74,58],13:[255,0,255],14:[0,0,0]};
function paintGrid(){ const g=gridCv.getContext('2d'), img=g.createImageData(S.NX,S.NZ), G=st.grid;
  for(let c=0;c<S.NX*S.NZ;c++){ const k=G.kind[c], col=G.gate[c]?[176,120,60]:KCOL[k]||[255,0,255], o=c*4, cv=G.cover[c]; img.data.set(col,o); img.data[o+3]=k===0&&!cv?40:k===7?120:200;
    if(cv===1&&k!==10&&k!==11){ img.data.set([47,159,196],o); img.data[o+3]=230; } }
  g.putImageData(img,0,0); gridTex.needsUpdate=true; }

// ---------- things ----------
const ghostOK=new THREE.MeshBasicMaterial({color:0x3fae7f,transparent:true,opacity:.55,depthWrite:false}), ghostBad=new THREE.MeshBasicMaterial({color:0xc23b2e,transparent:true,opacity:.55,depthWrite:false});
const siteMat=new THREE.MeshStandardMaterial({color:0xe0a526,transparent:true,opacity:.35,depthWrite:false,flatShading:true});
const box=(g,m,x,y,z,sx,sy,sz,ry=0)=>{ const me=new THREE.Mesh(new THREE.BoxGeometry(sx,sy,sz),m); me.position.set(x,y,z); me.rotation.y=ry; me.castShadow=true; me.receiveShadow=true; g.add(me); return me; };
const cyl=(g,m,x,y,z,r0,r1,h,n=10)=>{ const me=new THREE.Mesh(new THREE.CylinderGeometry(r0,r1,h,n),m); me.position.set(x,y,z); me.castShadow=true; me.receiveShadow=true; g.add(me); return me; };
// a model in local metres: x across, z along, y up from the ground at the footprint's centre
function model(type,t){ const g=new THREE.Group(), T=R.CATALOG[type], w=T.w*2, d=T.d*2;
  switch(type){
    case 'tank': { const m=mat('#3f4a3c'); cyl(g,m,0,1.25,0,1.75,1.8,2.5,14); cyl(g,mat('#333c31'),0,2.58,0,.9,1.75,.3,14); for(const y of [.6,1.25,1.9]) cyl(g,mat('#4a5646'),0,y,0,1.82,1.82,.08,14); box(g,mat('#6a5a44'),1.95,.2,0,.5,.4,.5); break; }
    case 'bed': { const fr=mat('#6e5a40'), cv=mat('#8b8f68'); for(const [x,z] of [[-.34,-.88],[.34,-.88],[-.34,.88],[.34,.88]]) box(g,fr,x,.22,z,.06,.44,.06); box(g,cv,0,.45,0,.72,.06,1.86); box(g,mat('#d8cfb8'),0,.52,-.7,.46,.08,.3); break; }   // a cot on one 2 m cell
    case 'bunkhouse': { const wl=mat('#b39a76'), rf=mat('#8f8b84'), dr=mat('#5c4532'); box(g,wl,0,1.3,0,7.8,2.6,5.8); const r1=box(g,rf,0,2.95,-1.5,8.2,.12,3.2); r1.rotation.x=.18; const r2=box(g,rf,0,2.95,1.5,8.2,.12,3.2); r2.rotation.x=-.18;
      box(g,dr,0,1,2.92,1,2,.06); for(const x of [-2.6,2.6]) box(g,mat('#3b4247'),x,1.6,2.92,1.1,.7,.06); break; }
    case 'catcher': { const p=mat('#6e5a40'), sh=mat('#a9b0b4'); for(const [x,z] of [[-2.8,-1.8],[2.8,-1.8],[-2.8,1.8],[2.8,1.8]]) box(g,p,x,1.1+(z<0?.4:0),z,.14,2.2+(z<0?.8:0),.14); const r=box(g,sh,0,2.55,0,6,.06,4); r.rotation.x=-.2;
      box(g,sh,0,1.9,2.1,6,.14,.2); box(g,mat('#3f4a3c'),2.6,.6,2.4,.5,1.2,.5); break; }
    case 'workbench': { const tb=mat('#7a6648'); box(g,tb,0,.9,0,1,.1,3.4); for(const [x,z] of [[-.4,-1.5],[.4,-1.5],[-.4,1.5],[.4,1.5]]) box(g,tb,x,.45,z,.08,.9,.08); box(g,tb,0,.3,0,.9,.06,3.2); box(g,mat('#5d6a6e'),.1,1.05,-.8,.3,.2,.5); box(g,mat('#3b4046'),-.2,1.0,.9,.12,.12,.6); break; }
    case 'ramada': { const p=mat('#6e5a40'), sl=mat('#9c8a68'); for(const [x,z] of [[-1.8,-1.8],[1.8,-1.8],[-1.8,1.8],[1.8,1.8]]) box(g,p,x,1.3,z,.16,2.6,.16); box(g,p,0,2.62,-1.8,3.9,.14,.14); box(g,p,0,2.62,1.8,3.9,.14,.14); for(let i=-1.8;i<=1.81;i+=.3) box(g,sl,i,2.74,0,.14,.06,4.1); break; }
    case 'seep': { const st0=mat('#8f8476'); for(let i=0;i<9;i++){ const a=i/9*TAU; box(g,st0,Math.cos(a)*.75,.12,Math.sin(a)*.75,.32,.24,.28,a); } const w=cyl(g,new THREE.MeshStandardMaterial({color:0x4a8bab,roughness:.25}),0,-.05,0,.55,.55,.06,12); w.userData.noInk=true; w.userData.water=true; break; }
    case 'pump': { box(g,mat('#b9b2a5'),0,.08,0,1.6,.16,1.6); if(t&&t.state==='broken'){ box(g,mat('#7a5a3a'),0,.5,0,.6,.7,.5); box(g,mat('#5c4532'),0,.95,0,.4,.2,.35); } else { const ir=mat('#3b4046'); cyl(g,ir,0,.75,0,.11,.13,1.3,8); cyl(g,ir,0,1.42,0,.16,.16,.22,8); box(g,ir,.35,1.4,0,.8,.06,.06).rotation.z=-.35; box(g,ir,-.18,1.1,0,.35,.06,.06); box(g,mat('#6e5a40'),-.6,.3,.35,.5,.5,.5); } break; }
    case 'garden': { const fr=mat('#7a6648'); for(const s of [-1,1]){ box(g,fr,s*1.9,.18,0,.16,.36,6); box(g,fr,0,.18,s*2.9,4,.36,.16); } box(g,mat('#6b5440'),0,.2,0,3.7,.3,5.7); const gr=mat('#6f8a3f'); for(let r=-1.3;r<=1.31;r+=.86) for(let q=-2.4;q<=2.41;q+=.8) box(g,gr,r,.48,q,.34,.3+((Math.round(r*7+q*3))%3+3)%3*.08,.34); break; }
    case 'kitchen': { const s=mat('#8f8476'); for(let i=0;i<8;i++){ const a=i/8*TAU; box(g,s,-1+Math.cos(a)*.55,.13,Math.sin(a)*.55,.28,.26,.24,a); } box(g,mat('#2b2622'),-1,.05,0,.6,.04,.6); const tb=mat('#7a6648'); box(g,tb,1,.9,0,1,.08,1.8); for(const [x,z] of [[.6,-.8],[1.4,-.8],[.6,.8],[1.4,.8]]) box(g,tb,x,.45,z,.08,.9,.08); box(g,mat('#5d6a6e'),1,1.02,-.4,.35,.16,.35); break; }
    case 'watch': { const p=mat('#6e5a40'), pl=mat('#8a7658'); for(const [x,z] of [[-1.6,-1.6],[1.6,-1.6],[-1.6,1.6],[1.6,1.6]]) box(g,p,x,1.7,z,.2,3.4,.2); box(g,pl,0,3.05,0,3.8,.14,3.8);
      for(const s of [-1,1]){ box(g,pl,s*1.85,3.6,0,.1,1,3.8); box(g,pl,0,3.6,s*1.85,3.8,1,.1); } box(g,p,0,4.6,0,4,.1,4); for(const [x,z] of [[-1.8,-1.8],[1.8,-1.8],[-1.8,1.8],[1.8,1.8]]) box(g,p,x,4.1,z,.1,1,.1);
      for(let y=.3;y<3;y+=.35) box(g,p,0,y,2.05,.7,.06,.06); box(g,p,-.35,1.5,2.05,.06,3,.06); box(g,p,.35,1.5,2.05,.06,3,.06); break; }
    case 'gate': { const p=mat('#6e5a40'), pl=mat('#9c7e58'); for(const x of [-2,2]) box(g,p,x,1.1,0,.24,2.2,.24); const shut=t&&t.shut;   // two leaves across 4 m; open by day, swung back
      for(const sg of [-1,1]){ const leaf=new THREE.Group(); for(let y=.25;y<1.8;y+=.38) box(leaf,pl,sg*-1,y,0,1.9,.28,.1); leaf.position.set(sg*2,0,0); leaf.rotation.y=shut?0:sg*1.35; g.add(leaf); } break; }
    case 'barricade': { const sb=mat('#b29d74'); for(let y=0;y<3;y++) for(let i=-1;i<=1;i++) box(g,sb,i*.62+(y%2)*.3-.15,.15+y*.28,0,.58,.26,.5); break; }
    case 'wall': { box(g,mat('#8d7f6a'),0,.95,0,.3,1.9,.3); break; } }
  return g; }
const wallTypes=new Set(['wall','gate','barricade']);
// walls join their neighbours: each finished wall cell draws a half-span toward every finished wall cell next to it
function wallSpans(t,g){ if(t.type==='gate') return; const [i,j]=R.cellIJ(t.cell), m=t.type==='barricade'?mat('#b29d74'):mat('#8d7f6a'), h=t.type==='barricade'?.85:1.8;
  for(const [di,dj] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[-1,-1],[1,-1],[-1,1]]){ const c=R.idOf(i+di,j+dj), o=c>=0&&st.grid.occ[c]&&st.things.find(q=>q.cells.includes(c)&&q.state==='done'&&wallTypes.has(q.type)); if(!o) continue;
    if(di&&dj&&(R.idOf(i+di,j)>=0&&wallAt(R.idOf(i+di,j))||R.idOf(i,j+dj)>=0&&wallAt(R.idOf(i,j+dj)))) continue;   // a diagonal is drawn only where no straight run turns the corner
    const L=Math.hypot(di,dj), me=box(g,o.type==='gate'||t.type==='gate'?mat('#6e5a40'):m,di,h/2,dj,.24,h,L*2+.05,0); me.rotation.y=Math.atan2(di,dj); me.position.set(di*.5,h/2,dj*.5); me.scale.z=.5; } }
const wallAt=c=>st.things.some(q=>q.cells.includes(c)&&q.state==='done'&&wallTypes.has(q.type));
const thingView=new Map();
function centreOf(t,rot=t.rot){ const xs=t.cells.map(c=>R.cellXZ(c)), x=xs.reduce((s,p)=>s+p[0],0)/xs.length, z=xs.reduce((s,p)=>s+p[1],0)/xs.length; return [x,z]; }
// ---------- construction, as it happens ----------
// A site goes through stages by its share of the work: marked out (stakes and string) → materials on site (a pile by the
// footprint) → groundwork (a pad) → framing (scaffold, the thing rising from the ground) → walls → roof or finishing → done.
// The rising part is the finished model cut by a clipping plane; the rest of it shows as a faint blueprint.
const ROOFED=new Set(['bunkhouse','ramada','catcher','watch','tank']);
function stageOf(t){ if(t.state==='broken') return 'Broken'; if(t.state==='done') return 'Done'; const f=t.progress/(R.CATALOG[t.type].hours*60);
  if(!t.delivered) return 'Marked out'; if(t.type==='seep') return f>0?'Digging':'Marked out'; if(t.type==='pump') return f>0?'Repairing':'Parts on site';
  if(f<=0) return 'Materials on site'; if(f<.2) return 'Groundwork'; if(f<.5) return 'Framing'; if(f<.8) return wallTypes.has(t.type)?'Building up':'Walls'; return ROOFED.has(t.type)?'Roof':'Finishing'; }
const blueMat=new THREE.MeshBasicMaterial({color:0xe0a526,transparent:true,opacity:.09,depthWrite:false});
const FRAMED=new Set(['bunkhouse']);   // a timber frame goes up before the walls
const stringMat=new THREE.LineBasicMaterial({color:0xe0a526}), padMat=mat('#b9ab92'), plankM=mat('#b08a5a'), crateM=mat('#6a5a44'), toolM=mat('#5d6a6e'), scafM=mat('#a07a4c');
function sizeOf(t){ const T=R.CATALOG[t.type]; return [T.w*2,T.d*2]; }
function buildView(t){ const v=thingView.get(t.id); if(v){ dispose(v.g); for(const m of v.mats||[]) m.dispose(); }
  const g=new THREE.Group(), [x,z]=centreOf(t), y=Math.min(...t.cells.map(c=>H(...R.cellXZ(c)))), view={g,state:t.state,shut:t.shut,mats:[]};
  if(t.state==='site'||t.state==='broken'&&false){ const [w,d]=sizeOf(t), hw=w/2-.05, hd=d/2-.05;
    // marked out: a stake at each corner and string between them, the cleared ground under them
    for(const [sx,sz] of [[-1,-1],[1,-1],[1,1],[-1,1]]) box(g,mat('#e0a526'),sx*hw,.35,sz*hd,.07,.7,.07);
    { const lg=new THREE.BufferGeometry(), q=[]; for(const [a1,b1,a2,b2] of [[-hw,-hd,hw,-hd],[hw,-hd,hw,hd],[hw,hd,-hw,hd],[-hw,hd,-hw,-hd]]) q.push(a1,.45,b1,a2,.45,b2); lg.setAttribute('position',new THREE.Float32BufferAttribute(q,3)); g.add(new THREE.LineSegments(lg,stringMat)); }
    const ground=new THREE.Mesh(new THREE.PlaneGeometry(w,d),new THREE.MeshBasicMaterial({color:0x8a6f50,transparent:true,opacity:0,depthWrite:false})); ground.rotation.x=-Math.PI/2; ground.position.y=.06; g.add(ground); view.ground=ground; view.mats.push(ground.material);
    // groundwork: a pad under anything with walls
    const T=R.CATALOG[t.type]; if(T.kind!==undefined&&!wallTypes.has(t.type)){ const pad=box(g,padMat,0,.06,0,w-.3,.12,d-.3); pad.scale.y=.01; view.pad=pad; }
    // the pile: one piece per unit of cost, laid beside the footprint, used up as the work goes on
    const pile=new THREE.Group(), units=[]; for(const [k,n] of Object.entries(T.cost)) for(let i=0;i<Math.min(n,12);i++) units.push(k);
    units.forEach((k,i)=>{ const row=i%4, lay=Math.floor(i/4), mm=k==='shelter'?plankM:k==='goods'?crateM:toolM; const me=k==='shelter'?box(pile,mm,0,.1+lay*.18,(row-1.5)*.32,1.8,.14,.28):box(pile,mm,(row-1.5)*.5,.22+lay*.42,0,.42,.4,.42); me.userData.n=i; });
    pile.position.set(hw+1.1,0,0); pile.visible=false; g.add(pile); view.pile=pile; view.units=units.length;
    // the finished model, cut at the working height; above it the blueprint
    const real=model(t.type,t), blue=model(t.type,t), plane=new THREE.Plane(new THREE.Vector3(0,-1,0),y);
    real.traverse(o=>{ if(o.isMesh){ o.material=o.material.clone(); o.material.clippingPlanes=[plane]; o.material.clipShadows=true; view.mats.push(o.material); } });
    blue.traverse(o=>{ if(o.isMesh){ o.material=blueMat; o.castShadow=false; o.userData.noInk=true; } });
    g.add(real,blue); const bb=new THREE.Box3().setFromObject(real); view.top=Math.max(.4,bb.max.y); view.plane=plane; view.real=real;
    // a timber frame: studs every metre or so round the walls and a top plate, standing up during framing
    if(FRAMED.has(t.type)){ const fr=new THREE.Group(), fx=bb.max.x-.05, fz=bb.max.z-.05, fh=2.6; const stud=(x,z)=>{ const me=box(fr,plankM,x,fh/2,z,.1,fh,.1); me.userData.stud=true; };
      for(let x=-fx;x<=fx+.01;x+=fx/4){ stud(x,-fz); stud(x,fz); } for(let z=-fz+fz/3;z<fz-.01;z+=fz/3){ stud(-fx,z); stud(fx,z); }
      const plate=new THREE.Group(); box(plate,plankM,0,fh,-fz,fx*2+.1,.12,.12); box(plate,plankM,0,fh,fz,fx*2+.1,.12,.12); box(plate,plankM,-fx,fh,0,.12,.12,fz*2); box(plate,plankM,fx,fh,0,.12,.12,fz*2); fr.add(plate);
      fr.visible=false; g.add(fr); view.frame=fr; view.plate=plate; }
    // scaffold round anything tall, while it goes up
    if(view.top>2.2){ const sc=new THREE.Group(), H2=view.top+.6, ex=Math.max(hw,bb.max.x)+.35, ez=Math.max(hd,bb.max.z)+.35; for(const [sx,sz] of [[-1,-1],[1,-1],[1,1],[-1,1]]) box(sc,scafM,sx*ex,H2/2,sz*ez,.1,H2,.1);
      for(let hy=1.2;hy<H2;hy+=1.4){ box(sc,scafM,0,hy,-ez,ex*2,.08,.08); box(sc,scafM,0,hy,ez,ex*2,.08,.08); box(sc,scafM,-ex,hy,0,.08,.08,ez*2); box(sc,scafM,ex,hy,0,.08,.08,ez*2); }
      sc.visible=false; g.add(sc); view.scaffold=sc; }
    inkOn(pile); }
  else { const m=model(t.type,t); g.add(m); if(t.state==='done'&&wallTypes.has(t.type)) wallSpans(t,m); inkOn(g); }
  g.position.set(x,y,z); g.rotation.y=t.rot%2?Math.PI/2:0; scene.add(g); view.y=y; thingView.set(t.id,view); return view; }
// every frame: the stage of each site drives what shows
const puffs=[];
function updateSites(dt){ for(const t of st.things){ const v=thingView.get(t.id); if(!v) continue;
    if(v.pop>0){ v.pop=Math.max(0,v.pop-dt); const k=v.pop/.6; v.g.scale.set(1+.1*k*Math.sin(k*9),1+.18*k*Math.sin(k*9),1+.1*k*Math.sin(k*9)); }
    if(t.state!=='site'||!v.plane) continue;
    const f=Math.min(1,t.progress/(R.CATALOG[t.type].hours*60)), rise=Math.max(0,Math.min(1,(f-.2)/.8));
    v.ground.material.opacity=t.delivered?.35:.12;
    if(v.pad) v.pad.scale.y=Math.max(.01,Math.min(1,f/.2));
    v.pile.visible=t.delivered; const left=Math.ceil(v.units*(1-f)); v.pile.children.forEach(c=>{ if(c.userData.n!==undefined) c.visible=c.userData.n<left; });
    const up=v.frame?Math.max(0,Math.min(1,(f-.45)/.55)):rise;   // framed things raise their walls only once the frame stands
    v.plane.constant=v.y+(f<.2&&v.pad?0:Math.max(.02,up*(v.top+.05)));   // world height the model is cut at (the plane faces down)
    if(v.frame){ const k=Math.max(0,Math.min(1,(f-.2)/.25)); v.frame.visible=f>=.2; v.frame.children.forEach(c=>{ if(c.userData.stud){ c.scale.y=Math.max(.02,k); c.position.y=1.3*Math.max(.02,k); } }); v.plate.visible=k>=1; }
    if(v.scaffold) v.scaffold.visible=f>=.15&&f<.97; } }
function finishPuff(t){ const [x,z]=centreOf(t), [w,d]=sizeOf(t), ring=new THREE.Mesh(new THREE.RingGeometry(.6,1,28),new THREE.MeshBasicMaterial({color:0xe8dcc2,transparent:true,opacity:.8,depthWrite:false,side:THREE.DoubleSide}));
  ring.rotation.x=-Math.PI/2; ring.position.set(x,H(x,z)+.15,z); ring.userData.r=Math.max(w,d)*.6; scene.add(ring); puffs.push({ring,t:0}); }
function updatePuffs(dt){ for(let i=puffs.length-1;i>=0;i--){ const q=puffs[i]; q.t+=dt; const k=q.t/.9, r=q.ring.userData.r*(1+1.6*k); q.ring.scale.set(r,r,r); q.ring.material.opacity=.8*(1-k); if(k>=1){ dispose(q.ring); q.ring.material.dispose(); puffs.splice(i,1); } } }
let viewKey='';
function syncThings(){ const key=st.things.map(t=>t.id+t.state+(t.shut?'s':'')).join()+'|'+Object.values(st.claimed).map(b=>b.torn?1:0).join(); if(key===viewKey) return; viewKey=key;
  const live=new Set(st.things.map(t=>t.id)); for(const [id,v] of thingView) if(!live.has(id)){ dispose(v.g); thingView.delete(id); }
  for(const t of st.things){ const v=thingView.get(t.id), was=v&&v.state; if(!v||v.state!==t.state||v.shut!==t.shut||(wallTypes.has(t.type)&&t.state==='done')){ const nv=buildView(t); if(was==='site'&&t.state==='done'){ nv.pop=.6; finishPuff(t); } } }
  for(const b of Object.values(st.claimed)) if(b.torn&&bldMesh.has(b.pts)){ dispose(bldMesh.get(b.pts)); bldMesh.delete(b.pts); }
  paintGrid(); }
function clearThings(){ for(const v of thingView.values()){ dispose(v.g); for(const m of v.mats||[]) m.dispose(); } thingView.clear(); viewKey=''; }

// ---------- people ----------
let figs=[];
function makeFigs(){ for(const f of figs){ dispose(f.root); dispose(f.lump); f.tag.remove(); }
  figs=st.people.map((p,i)=>{ const fem=p.rec.sex==='f', f=FigureKit.figure(fem,FigureKit.genFace(p.rec.seed,fem)); f.seed=p.rec.seed; f.j=Object.assign({},FigureKit.POSES.stand);
  f.root.traverse(o=>{ if(o.isMesh) o.castShadow=true; }); f.ink=FigureKit.inkUp(f.root,{persp:true,width:.0016,color:FigureKit.STATES.calm.c}); f.inkState='calm'; scene.add(f.root);
  f.root.position.set(p.x,H(p.x,p.z),p.z); f.yaw=0;
  const tag=document.createElement('div'); tag.className='tag'; tag.textContent=p.name; labelsEl.appendChild(tag); f.tag=tag;
  const lump=new THREE.Group(); box(lump,mat('#7a8a9a'),0,.62,.1,.62,.22,1.6); box(lump,mat('#d8b890'),0,.64,-.82,.22,.2,.24); lump.visible=false; inkOn(lump); scene.add(lump); f.lump=lump;
  // what a person carries in both arms: a bundle of planks for a build, jerrycans of water from the seep
  const planks=new THREE.Group(); for(let k=0;k<3;k++) box(planks,plankM,0,k*.07,0,.5,.06,1.6); planks.position.set(0,1.02,.34); planks.rotation.x=-.1;
  const cans=new THREE.Group(); for(const sx of [-.16,.16]) box(cans,mat('#3f5a6e'),sx,0,0,.26,.36,.14); cans.position.set(0,1.0,.3);
  for(const q of [planks,cans]){ q.visible=false; inkOn(q); f.root.add(q); } f.planks=planks; f.cans=cans; return f; }); }
makeFigs();
function setInk(f,state){ if(f.inkState===state) return; f.inkState=state; if(f.ink) f.ink.color.setHex(FigureKit.STATES[state].c); }
const TASKTEXT={drink:'Filling a canteen',build:'Building',sleep:'Asleep',guard:'On watch',rest:'Resting in shade',idle:'Idle',haul:'Hauling water',grow:'Tending the garden'};
function taskText(p){ if(!p.rec.alive) return 'Dead'; if(p.rec.at==='gone') return 'Gone'; const T=p.task; if(!T) return 'Idle'; const s=T.steps[T.step]||{}; let txt=TASKTEXT[T.kind]||T.kind;
  if(T.kind==='build'&&T.thing) txt=(s.do==='take'||(s.go===st.places.store&&!s.carry)?'Fetching materials: ':s.do==='build'?'Building ':'Off to build ')+R.CATALOG[T.thing.type].label.toLowerCase();
  if(T.kind==='build'&&T.claimed) txt='Taking an outbuilding apart';
  if(T.kind==='sleep') txt=s.go!==undefined?'Going to bed':p.inside?(T.spot&&T.spot.thing?'Asleep in the bunkhouse':'Asleep in the house'):T.spot&&T.spot.bed?'Asleep on a cot':'Asleep on the ground';
  if(T.kind==='haul'&&T.thing&&T.thing.type==='pump') txt='Pumping water';
  if(T.kind==='rest'&&s.do==='rest') txt=p.inside?'Resting indoors':'Resting in shade'; return txt; }
let selected=null;   // {kind:'person',i} or {kind:'thing',id} or {kind:'claimed',k}

// ---------- camera: orbit, pan, zoom ----------
const view={tx:(st.area[0]+st.area[2])/2,tz:(st.area[1]+st.area[3])/2,yaw:-.55,pitch:.78,dist:170};
function placeCam(){ view.tx=Math.max(X0+10,Math.min(X0+WX-10,view.tx)); view.tz=Math.max(Z0+10,Math.min(Z0+WZ-10,view.tz)); view.dist=Math.max(14,Math.min(520,view.dist)); view.pitch=Math.max(.25,Math.min(1.45,view.pitch));
  const ty=H(view.tx,view.tz), cp=Math.cos(view.pitch); cam.position.set(view.tx+Math.sin(view.yaw)*cp*view.dist,ty+Math.sin(view.pitch)*view.dist,view.tz+Math.cos(view.yaw)*cp*view.dist); cam.lookAt(view.tx,ty,view.tz); }
function resize(){ const w=stage.clientWidth, h=stage.clientHeight; renderer.setSize(w,h,false); cam.aspect=w/h; cam.updateProjectionMatrix(); }
new ResizeObserver(resize).observe(stage); resize(); placeCam();

// ---------- tools and picking ----------
let tool=null, rot=0, drag=null, ghost=null, ghostKey='';
const ray=new THREE.Raycaster(), ndc=new THREE.Vector2();
function groundAt(ev){ const r=renderer.domElement.getBoundingClientRect(); ndc.set((ev.clientX-r.left)/r.width*2-1,-(ev.clientY-r.top)/r.height*2+1); ray.setFromCamera(ndc,cam); const hit=ray.intersectObject(terrain.mesh)[0]; return hit?hit.point:null; }
function tip(text,bad){ if(!text){ tipEl.hidden=true; return; } tipEl.hidden=false; tipEl.textContent=text; tipEl.classList.toggle('bad',!!bad); }
const costText=T=>Object.entries(T.cost).map(([k,n])=>`${n} ${({shelter:'materials',tools:'parts',water:'L water'})[k]||k}`).join(', ')||'no materials';
// the build card: what a thing costs against the stores, how long it takes, its footprint, what it does to the grid and what it gives
const cardEl=$('card'), UNIT1={shelter:'materials',goods:'goods',tools:'parts',water:'L water'};
function givesOf(T){ return [T.beds?`${T.beds} bed${T.beds>1?'s':''}`:'',T.shade?'shade':'',T.water?`stores ${T.water.toLocaleString()} L`:'',T.catchL?`${T.catchL} L per mm of rain into the tanks`:'',T.seepL?`${T.seepL} L a day`:'',T.pumpL?`${T.pumpL} L a day of pumping`:'',T.tendL?`a garden plot (${T.tendL} L a day)`:'',T.site?`a ${T.site} site for settlement`:'',T.guards?`${T.guards} on watch at night, spots at ${T.spot} m`:'',T.drag?'blocks the way':''].filter(Boolean).join(' · '); }
const gridOf=T=>`${T.gate?'wall when shut':T.kind===R.NK.wall?'wall':T.kind===R.NK.building?'building':'passable'+(T.speed?` (walking ×${T.speed})`:'')}${T.cover?` · ${T.cover===2?'full':'half'} cover`:''}`;
function showCard(type,status,bad,count=1){ if(!type){ cardEl.hidden=true; return; } const T=R.CATALOG[type], live=st.people.filter(p=>p.rec.alive&&p.rec.at!=='gone'), best=live.reduce((a,p)=>(p.rec.skills.build||0)>(a?a.rec.skills.build||0:-1)?p:a,null);
  const chips=Object.entries(T.cost).map(([k,n])=>{ const need=n*count, have=Math.floor(st.stock[k]||0); return `<span class="chip${have<need?' short':''}">${need} ${UNIT1[k]||k}<small>${have} in store</small></span>`; }).join('')||'<span class="chip">no materials</span>';
  const pace=best?R.workRate(best,'build')/(R.midday(st.minutes)?.5:1):1;
  cardEl.innerHTML=`<b>${T.label}${count>1?` × ${count}`:''}</b>${T.inferred?'<em>stats inferred</em>':''}<div class="chips">${chips}</div>
    <dl><dt>Work</dt><dd>${T.hours*count} h at Build 1${best?` · about ${(T.hours*count/pace).toFixed(1)} h for ${best.name} (Build ${(best.rec.skills.build||0).toFixed(1)})`:''}</dd>
    <dt>Size</dt><dd>${T.w} × ${T.d} cells (${T.w*2} × ${T.d*2} m)${T.w!==T.d?' · R rotates':''}${T.drag?' · drag for a line':''}</dd>
    <dt>Grid</dt><dd>${gridOf(T)}</dd>${givesOf(T)?`<dt>Gives</dt><dd>${givesOf(T)}</dd>`:''}</dl>
    <div class="status${bad?' bad':''}">${status}</div>`; cardEl.hidden=false; }
function setTool(t){ tool=t; drag=null; clearGhost(); document.querySelectorAll('[data-tool]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.tool===t)));
  if(R.CATALOG[t]){ tip(''); showCard(t,'Move over the base to lay it out.'); } else showCard(null);
  stage.style.cursor=t?'crosshair':'grab'; if(!R.CATALOG[t]) tip(t==='tear'?'Click a small outbuilding on the base to take it apart for materials.':t==='cancel'?'Click a planned thing to cancel it.':t==='found'?'Click anywhere on the ground to found the base there (a 140 m square). The old base is left behind.':''); }
function clearGhost(){ if(ghost){ dispose(ghost); ghost=null; } ghostKey=''; }
function showGhost(type,cells,okAll){ const key=type+cells.join(',')+okAll+rot; if(key===ghostKey) return; clearGhost(); ghostKey=key; ghost=new THREE.Group();
  const T=R.CATALOG[type], groups=T.drag?cells.map(c=>[c]):[cells];
  for(const cs of groups){ const xs=cs.map(c=>R.cellXZ(c)), x=xs.reduce((s,p)=>s+p[0],0)/xs.length, z=xs.reduce((s,p)=>s+p[1],0)/xs.length, m=model(type,null), ok=okAll&&cs.every(c=>R.canPlace(type,T.drag?c:cells[0],rot).ok||true);
    m.traverse(o=>{ if(o.isMesh){ o.material=okAll?ghostOK:ghostBad; o.castShadow=false; } }); m.position.set(x,Math.min(...cs.map(c=>H(...R.cellXZ(c))))+.02,z); m.rotation.y=rot%2?Math.PI/2:0; ghost.add(m);
    for(const c of cs){ const [cx,cz]=R.cellXZ(c), q=new THREE.Mesh(new THREE.PlaneGeometry(1.9,1.9),okAll?ghostOK:ghostBad); q.rotation.x=-Math.PI/2; q.position.set(cx,H(cx,cz)+.08,cz); ghost.add(q); } }
  scene.add(ghost); }
// the corner cell for a footprint centred under the pointer
function cornerAt(type,p){ const T=R.CATALOG[type], w=rot%2?T.d:T.w, d=rot%2?T.w:T.d; return R.cellOf(p.x-(w-1),p.z-(d-1)); }
function hover(ev){ const p=groundAt(ev); if(p) hoverAt(p); }
function hoverAt(p){ const T=R.CATALOG[tool];
  if(tool==='found'){ const ok=R.canFound(RANCH_SITE,p.x,p.z), a=R.areaAt(RANCH_SITE,p.x,p.z), key='found'+a.join()+ok; if(key!==ghostKey){ clearGhost(); ghostKey=key; ghost=new THREE.Group(); const pts=[];
      for(const [ax,az,bx,bz] of [[a[0],a[1],a[2],a[1]],[a[2],a[1],a[2],a[3]],[a[2],a[3],a[0],a[3]],[a[0],a[3],a[0],a[1]]]) for(let t=0;t<1;t+=.025){ const x=ax+(bx-ax)*t, z=az+(bz-az)*t, x2=ax+(bx-ax)*(t+.025), z2=az+(bz-az)*(t+.025); pts.push(x,H(x,z)+.4,z,x2,H(x2,z2)+.4,z2); }
      const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pts,3)); ghost.add(new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:ok?0x3fae7f:0xc23b2e}))); scene.add(ghost); }
    tip(ok?'Found the base here: a 140 m square.':'The base has to fit on the cut ground.',!ok); return; }
  if(T){ if(T.drag&&drag){ const cells=R.lineCells(drag.a,R.cellOf(p.x,p.z)), good=cells.filter(c=>R.canPlace(tool,c).ok); showGhost(tool,good.length?good:cells,good.length>0); showCard(tool,good.length?`Release to lay out ${good.length}${good.length<cells.length?` (${cells.length-good.length} blocked)`:''}.`:'Nothing can go along this line.',!good.length,Math.max(1,good.length)); return; }
    const c=cornerAt(tool,p), chk=R.canPlace(tool,c,rot), cells=R.footprint(tool,c,rot)||[]; showGhost(tool,cells,chk.ok); showCard(tool,chk.ok?(T.drag?'Click to lay out one, or drag for a line.':'Click to lay it out.'):chk.why,!chk.ok); } }
function click(ev){ const p=groundAt(ev); if(p) clickAt(p,ev); }
function clickAt(p,ev){ const c=R.cellOf(p.x,p.z), T=R.CATALOG[tool];
  if(T&&!T.drag){ const t=R.place(tool,cornerAt(tool,p),rot); if(t){ ui.dirty=true; R.state.log.unshift({t:st.minutes,msg:`Laid out: ${T.label.toLowerCase()}.`}); } return t; }
  if(T&&T.drag){ const t=R.place(tool,c,0); if(t){ ui.dirty=true; R.state.log.unshift({t:st.minutes,msg:`Laid out: ${T.label.toLowerCase()}.`}); } return t; }
  if(tool==='found'){ if(R.canFound(RANCH_SITE,p.x,p.z)){ found([p.x,p.z]); setTool(null); } return; }
  if(tool==='tear'){ for(const [k,b] of Object.entries(st.claimed)) if(b.role==='outbuilding'&&!b.torn&&b.cells.some(q=>{ const [x,z]=R.cellXZ(q); return Math.hypot(x-p.x,z-p.z)<3; })){ R.orderTear(k); setTool(null); ui.dirty=true; return; } tip('Only a small outbuilding on the base can be taken apart.',true); return; }
  if(tool==='cancel'){ const t=st.things.find(q=>q.state==='site'&&q.cells.includes(c)); if(t){ R.cancel(t.id); ui.dirty=true; } return; }
  if(!ev) return;
  // no tool: pick a person by screen distance, else a thing, else a claimed building
  const r=renderer.domElement.getBoundingClientRect(); let best=-1,bd=26; figs.forEach((f,i)=>{ if(!f.root.visible) return; const v=f.root.position.clone(); v.y+=1; v.project(cam); const sx=(v.x+1)/2*r.width, sy=(1-v.y)/2*r.height, d=Math.hypot(sx-(ev.clientX-r.left),sy-(ev.clientY-r.top)); if(d<bd){ bd=d; best=i; } });
  if(best>=0){ selected={kind:'person',i:best}; ui.dirty=true; return; }
  const t=st.things.find(q=>q.cells.includes(c)); if(t){ selected={kind:'thing',id:t.id}; ui.dirty=true; return; }
  for(const [k,b] of Object.entries(st.claimed)) if(!b.torn&&b.cells.includes(c)){ selected={kind:'claimed',k}; ui.dirty=true; return; }
  selected=null; ui.dirty=true; }
// pointers: with no tool, drag turns the view; right or two-finger drag pans; wheel and pinch zoom. With a line tool, drag draws.
const ptrs=new Map(); let gesture=null;
renderer.domElement.addEventListener('contextmenu',e=>e.preventDefault());
renderer.domElement.addEventListener('pointerdown',e=>{ if(demo) stopDemo(); renderer.domElement.setPointerCapture(e.pointerId); ptrs.set(e.pointerId,{x:e.clientX,y:e.clientY,x0:e.clientX,y0:e.clientY,b:e.button});
  if(ptrs.size===2){ gesture={pinch:true}; drag=null; return; }
  const T=R.CATALOG[tool]; if(T&&T.drag&&e.button===0){ const p=groundAt(e); if(p) drag={a:R.cellOf(p.x,p.z)}; } });
renderer.domElement.addEventListener('pointermove',e=>{ const q=ptrs.get(e.pointerId);
  if(!q){ if(tool) hover(e); return; }
  const dx=e.clientX-q.x, dy=e.clientY-q.y; q.x=e.clientX; q.y=e.clientY;
  if(ptrs.size===2){ const [a,b]=[...ptrs.values()], d=Math.hypot(a.x-b.x,a.y-b.y); if(gesture.d) view.dist*=gesture.d/d; gesture.d=d; panBy(dx/2,dy/2); placeCam(); return; }
  if(drag){ hover(e); return; }
  if(q.b===2||e.shiftKey) panBy(dx,dy); else if(!tool||Math.hypot(e.clientX-q.x0,e.clientY-q.y0)>6){ view.yaw-=dx*.006; view.pitch+=dy*.005; } placeCam(); if(tool) hover(e); });
function panBy(dx,dy){ const k=view.dist/600, s=Math.sin(view.yaw), c=Math.cos(view.yaw); view.tx+=(-dx*c-dy*s)*k; view.tz+=(dx*s-dy*c)*k; }
renderer.domElement.addEventListener('pointerup',e=>{ const q=ptrs.get(e.pointerId); ptrs.delete(e.pointerId); if(ptrs.size===0) gesture=null; if(!q) return;
  if(drag&&e.button===0){ const p=groundAt(e); if(p){ const placed=R.placeLine(tool,drag.a,R.cellOf(p.x,p.z)); if(placed.length) R.state.log.unshift({t:st.minutes,msg:`Laid out: ${placed.length} × ${R.CATALOG[tool].label.toLowerCase()}.`}); ui.dirty=true; } drag=null; clearGhost(); hover(e); return; }
  if(q.b===0&&Math.hypot(e.clientX-q.x0,e.clientY-q.y0)<6) click(e); });
renderer.domElement.addEventListener('pointerleave',()=>{ if(!drag) clearGhost(); });
renderer.domElement.addEventListener('wheel',e=>{ e.preventDefault(); view.dist*=Math.exp(e.deltaY*.0012); placeCam(); },{passive:false});
addEventListener('keydown',e=>{ if(e.target.tagName==='INPUT') return; if(e.key==='Escape') setTool(null); if(e.key==='r'||e.key==='R'){ rot=(rot+1)%2; ghostKey=''; }
  const k={ArrowLeft:[-30,0],ArrowRight:[30,0],ArrowUp:[0,-30],ArrowDown:[0,30],a:[-30,0],d:[30,0],w:[0,-30],s:[0,30]}[e.key]; if(k){ panBy(...k); placeCam(); e.preventDefault(); } });

// ---------- panels ----------
const ui={speed:.25, dirty:true};
const GROUPS=[['Defence',['wall','gate','barricade','watch']],['Shelter',['bed','bunkhouse','ramada']],['Water',['tank','catcher','seep']],['Work',['garden','kitchen','workbench']]];
{ const bar=$('build'); for(const [name,keys] of GROUPS){ const g=document.createElement('div'); g.className='grp'; g.innerHTML=`<span class="lbl">${name}</span>`; bar.appendChild(g);
    for(const k of keys){ const T=R.CATALOG[k], b=document.createElement('button'); b.type='button'; b.dataset.tool=k; b.textContent=T.label; b.title=`${costText(T)} · ${T.hours} h at Build 1${T.inferred?' · stats inferred':''}`; g.appendChild(b); } }
  $('demo').addEventListener('click',()=>startDemo());
  const pre=$('presets'); for(const pr of RANCH_SITE.presets){ const b=document.createElement('button'); b.type='button'; b.textContent=pr.label; b.title=pr.note; b.addEventListener('click',()=>found(pr.centre)); pre.appendChild(b); }
  document.querySelectorAll('[data-tool]').forEach(b=>b.addEventListener('click',()=>setTool(tool===b.dataset.tool?null:b.dataset.tool)));
  $('repair').addEventListener('click',()=>{ if(!R.orderRepair()) R.state.log.unshift({t:st.minutes,msg:'There is no broken well on this base.'}); ui.dirty=true; });
  $('speed').querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>{ stopDemo(); ui.speed=+b.dataset.s; $('speed').querySelectorAll('button').forEach(q=>q.setAttribute('aria-pressed',String(q===b))); }));
  $('grid').addEventListener('change',e=>{ gridMesh.visible=e.target.checked; });
  $('area').addEventListener('change',e=>{ areaLine.visible=e.target.checked; }); }
const peopleEl=$('people'); let rows=[];
function makeRows(){ peopleEl.innerHTML=''; rows=st.people.map((p,i)=>{ const b=document.createElement('button'); b.type='button'; b.className='person'; b.innerHTML=`<span class="nm"></span><span class="what"></span><span class="meter"><i></i></span>`;
  b.addEventListener('click',()=>{ selected={kind:'person',i}; view.tx=st.people[i].x; view.tz=st.people[i].z; placeCam(); ui.dirty=true; }); peopleEl.appendChild(b); return b; }); }
makeRows();
// found a base somewhere else: the ground stays, everything on it starts over
function found(centre,at){ const speed=ui.speed, minute=at!==undefined?at:st.minutes; st=R.create(RANCH_SITE,{centre,minute});   // the clock carries on
  clearThings(); buildBuildings(); drawArea(); makeFigs(); makeRows(); selected=null;
  view.tx=(st.area[0]+st.area[2])/2; view.tz=(st.area[1]+st.area[3])/2; placeCam(); paintGrid(); ui.speed=speed; ui.dirty=true; }
// the construction queue: every open site with its stage, progress and who is on it; ▲ moves it to the front, × cancels.
// Lines of walls or barricades are one row per kind.
const queueEl=$('queue');
queueEl.addEventListener('click',e=>{ const b=e.target.closest('button'); if(!b) return; const ids=b.dataset.ids.split(',');
  if(b.dataset.a==='up'){ const on=!st.things.find(t=>t.id===ids[0]).priority; for(const id of ids) R.setPriority(id,on); }
  else if(b.dataset.a==='x'){ for(const id of ids) R.cancel(id); }
  else { const t=st.things.find(q=>q.id===ids[0]); if(t){ selected={kind:'thing',id:t.id}; [view.tx,view.tz]=centreOf(t); placeCam(); } } ui.dirty=true; });
function queue(){ const open=st.things.filter(t=>t.state==='site'), rowsQ=[], lines={};
  for(const t of open){ if(R.CATALOG[t.type].drag){ (lines[t.type]=lines[t.type]||[]).push(t); continue; } rowsQ.push([t]); }
  for(const ts of Object.values(lines)) rowsQ.push(ts);
  rowsQ.sort((a,b)=>(b[0].priority-a[0].priority));
  if(!rowsQ.length){ queueEl.innerHTML='<li class="empty">Nothing ordered. Pick a thing in the build bar and lay it out on the base.</li>'; return; }
  queueEl.innerHTML=rowsQ.map(ts=>{ const t=ts[0], T=R.CATALOG[t.type], info=ts.map(q=>R.siteInfo(q)), f=info.reduce((a,i)=>a+i.fraction,0)/ts.length, who=info.reduce((a,i)=>a+i.working,0), coming=info.reduce((a,i)=>a+i.coming,0)-who;
    const left=ts.length===1&&info[0].hoursLeft!=null?` · ~${info[0].hoursLeft.toFixed(1)} h left`:'', name=ts.length>1?`${T.label} × ${ts.length}`:T.label, stage=ts.length>1?`${ts.filter(q=>q.progress>0).length} begun`:stageOf(t), ids=ts.map(q=>q.id).join(',');
    return `<li${t.priority?' class="hot"':''}><button type="button" class="qn" data-ids="${ids}">${name}<small>${stage}${who?` · ${who} at work`:coming?` · ${coming} on the way`:''}${left}</small></button>
      <span class="meter"><i style="width:${(f*100).toFixed(0)}%"></i></span><button type="button" class="qb" data-a="up" data-ids="${ids}" aria-pressed="${!!t.priority}" title="Build this first">▲</button><button type="button" class="qb" data-a="x" data-ids="${ids}" title="Cancel and return the materials">×</button></li>`; }).join(''); }
const UNITNAME={water:'L water',food:'rations',medicine:'med kits',tools:'parts',fuel:'L fuel',gear:'gear',shelter:'materials',goods:'goods'};
const ROLE={house:['House','Shelter: rest and sleep indoors (on the floor until interiors furnish it). The water barrels, 400 L.'],store:['Store','Materials are fetched from its door.'],workshop:['Workshop','A production site for settlement (crafting).'],outbuilding:['Outbuilding','Can be taken apart for 6 materials.'],spare:['Spare building','Too big to take apart by hand; room for settlement to use.']};
const P=R.People, TH=P.RATES.THIRST;
let lastLog=null;
function panels(){ const cap=R.waterCap(), w=st.stock.water, use=R.dailyUse(), inn=R.inflow(), alive=st.people.filter(p=>p.rec.alive&&p.rec.at!=='gone').length;
  $('clock').textContent=R.fmt(st.minutes); const h=R.hourOf(st.minutes); $('phase').textContent=`${R.night(st.minutes)?'night':R.midday(st.minutes)?'heat of the day':h<10?'morning':'evening'} · heat ${R.heatAt(st.minutes).toFixed(2)}`;
  $('wl').textContent=`${Math.round(w)} L`; $('wcap').textContent=`of ${cap} L`; $('wbar').style.width=`${Math.max(0,Math.min(100,w/cap*100))}%`;
  $('wdays').textContent=`about ${use.toFixed(0)} L a day for ${alive} people${inn?`, ${inn} L a day coming in`:''} · ${w>0?(use>inn?(w/(use-inn)).toFixed(1)+' days left':'holding'):'dry'}`;
  $('stock').innerHTML=Object.entries(st.stock).filter(([k])=>k!=='water').map(([k,n])=>`<dt>${UNITNAME[k]||k}</dt><dd>${k==='food'?n.toFixed(1):Math.round(n)}</dd>`).join('');
  st.people.forEach((p,i)=>{ const r=rows[i], b=p.rec.body, pct=Math.min(100,b.water/TH[1]*100), stg=P.thirstStage(p.rec); r.children[0].textContent=p.name; r.children[1].textContent=taskText(p);
    const bar=r.children[2].firstChild; bar.style.width=pct+'%'; bar.className=stg>=2?'d':stg>=1?'t':''; r.setAttribute('aria-pressed',String(!!selected&&selected.kind==='person'&&selected.i===i)); r.title=`${b.water.toFixed(1)} L short · canteen ${p.canteen.toFixed(1)} L`; });
  let sel='Click a person, a thing or a building.';
  if(selected&&selected.kind==='person'){ const p=st.people[selected.i], n=P.needs(p.rec); sel=`<b>${p.rec.name}</b><br>${taskText(p)}<br>Water ${n.water} (${p.rec.body.water.toFixed(1)} L short) · canteen ${p.canteen.toFixed(1)} L<br>Food ${n.food} · energy ${(n.energy*100).toFixed(0)}% · mood ${n.mood.toFixed(0)}<br>Build ${(p.rec.skills.build||0).toFixed(1)} · traits ${p.rec.traits.join(', ')||'none'}`; }
  if(selected&&selected.kind==='thing'){ const t=st.things.find(q=>q.id===selected.id); if(!t) selected=null; else { const T=R.CATALOG[t.type], need=T.hours*60;
    const gives=[T.beds?`${T.beds} bed${T.beds>1?'s':''}`:'',T.shade?'shade':'',T.water?`stores ${T.water} L`:'',T.catchL?`${T.catchL} L per mm of rain into the tanks`:'',T.seepL?`${T.seepL} L a day`:'',T.pumpL?`${T.pumpL} L a day of pumping`:'',T.tendL?`a garden plot (${T.tendL} L a day)`:'',T.site?`a ${T.site} site for settlement`:'',T.guards?`${T.guards} on watch at night, spots at ${T.spot} m`:''].filter(Boolean).join(' · ');
    sel=`<b>${T.label}</b>${T.inferred?' <span>(stats inferred)</span>':''}<br>${t.state==='broken'?'Broken: the electric pump died with the grid. A hand pump needs 3 goods.':t.state==='site'?`Planned · ${Math.round(t.progress/need*100)}% built · ${t.delivered?'materials on site':'materials in the store'}`:'Finished'}${gives?`<br>${gives}`:''}<br>Grid: ${T.gate?(t.shut?'wall (shut for the night)':'open'):T.kind===R.NK.wall?'wall':T.kind===R.NK.building?'building':'passable'}${T.cover?`, ${T.cover===2?'full':'half'} cover${T.gate?' when shut':''}`:''}${T.gate?'; the base\'s own people pass':''}${t.type==='seep'&&t.state==='done'?`<br>${t.pool.toFixed(0)} L waiting`:''}${t.type==='pump'&&t.state==='done'?`<br>${t.pumped.toFixed(0)} of ${T.pumpL} L pumped today`:''}`; } }
  if(selected&&selected.kind==='claimed'){ const b=st.claimed[selected.k], [nm,txt]=ROLE[b.role]; sel=`<b>${nm}</b><br>${b.order?'Being taken apart.':txt}`; }
  $('sel').innerHTML=sel;
  queue();
  if(st.log[0]!==lastLog){ lastLog=st.log[0]; $('log').innerHTML=st.log.slice(0,30).map(l=>`<li><span>${R.fmt(l.t).replace('Day ','D')}</span>${l.msg}</li>`).join(''); } }

// ---------- light through the day ----------
const SKY=[[0,'#1d2433','#3a3a44'],[5,'#2a3248','#5a4a48'],[6,'#e8b98a','#e8d0b0'],[8,'#9fc6e4','#e8dcc2'],[17,'#a7c8e0','#ead9bc'],[19.3,'#e09a6a','#d8b890'],[20.3,'#2e3550','#4a4048'],[24,'#1d2433','#3a3a44']];
const lerpC=(a,b,t)=>{ const A=new THREE.Color(a), B=new THREE.Color(b); return '#'+A.lerp(B,t).getHexString(); };
function light(){ const h=R.hourOf(st.minutes); let k=0; while(k<SKY.length-2&&SKY[k+1][0]<=h) k++; const [h0,a0,b0]=SKY[k], [h1,a1,b1]=SKY[k+1], t=(h-h0)/(h1-h0||1);
  stage.style.background=`linear-gradient(180deg,${lerpC(a0,a1,t)},${lerpC(b0,b1,t)})`;
  const arc=(h-5.33)/(19.58-5.33), up=Math.max(0,Math.sin(Math.PI*Math.min(1,Math.max(0,arc)))), day=arc>0&&arc<1;
  // night stays readable: a cool sky light and a low moon stand in for the sun
  sun.intensity=day?.45+.4*Math.min(1,up*1.6):.32; sun.color.set(day?(up<.3?0xffd2a0:0xfff1da):0x9fb4e0); hemi.intensity=day?.34+.08*up:.36; hemi.color.set(day?0xfff6e6:0x8fa0c8); hemi.groundColor.set(day?0x8a7a62:0x3a3a48);
  const bx=(st.area[0]+st.area[2])/2, bz=(st.area[1]+st.area[3])/2, az=Math.PI*(day?arc:.35); sun.position.set(bx+Math.cos(az)*160,H(bx,bz)+30+up*180,bz+60); sun.target.position.set(bx,H(bx,bz),bz);   // east at dawn, west at dusk; shadows follow the base   // east at dawn, west at dusk
  scene.fog.color.set(day?0xe2d8c2:0x2a2e3a); }

// ---------- site labels: stage, progress and who is on it, above every open site (one per wall line: the one being worked) ----------
const siteTagEls=new Map();
function siteTags(r){ const live=new Set();
  for(const t of st.things){ if(t.state!=='site') continue; const T=R.CATALOG[t.type], info=R.siteInfo(t); if(T.drag&&!info.coming) continue; live.add(t.id);
    let el=siteTagEls.get(t.id); if(!el){ el=document.createElement('div'); el.className='tag site'; el.innerHTML='<b></b><span></span><i><u></u></i>'; labelsEl.appendChild(el); siteTagEls.set(t.id,el); }
    const v=thingView.get(t.id), [x,z]=centreOf(t), y=(v?v.y:H(x,z))+(v?v.top:2)+1.2, q=new THREE.Vector3(x,y,z).project(cam);
    if(q.z>1){ el.style.display='none'; continue; } el.style.display=''; el.style.left=((q.x+1)/2*r.width)+'px'; el.style.top=((1-q.y)/2*r.height)+'px';
    el.children[0].textContent=T.label; el.children[1].textContent=`${stageOf(t)}${info.working?` · ${info.working} at work`:info.coming?' · on the way':''}`; el.children[2].firstChild.style.width=(info.fraction*100).toFixed(0)+'%'; el.classList.toggle('hot',!!t.priority); }
  for(const [id,el] of siteTagEls) if(!live.has(id)){ el.remove(); siteTagEls.delete(id); } }

// ---------- watch a build: the whole process on the ranch, played with the real rules ----------
// Founds the ranch afresh at dawn, chooses the bunkhouse, moves its layout over blocked and open ground, lays it out, then follows
// the site while people haul the materials and build it through every stage. Captions name each step. Any speed button stops it.
let demo=null; const capEl=$('caption');
const STEPS={choose:'1 · Choose. The build card shows the cost against the stores, the work at Build 1 and for your best builder, the footprint, what it does to the grid and what it gives.',
  layout:'2 · Lay out. The plan follows the pointer. It turns red, and the card says why, over blocked ground. Click to stake it out.',
  'Marked out':'3 · Staked out. Stakes and string mark the footprint, and it joins the construction queue. A builder fetches the materials from the store.',
  'Materials on site':'4 · Materials on site. The pile by the stakes is used up as the work goes on.',
  Groundwork:'5 · Groundwork. Builders level the ground and lay a pad.',
  Framing:'6 · Framing. Scaffold goes up and the frame rises out of the ground. The faint plan above shows what is still to come.',
  Walls:'7 · Walls. Up to three can build a bunkhouse at once. Each Build level is 15% faster, and outdoor work in the heat goes at half speed.',
  Roof:'8 · Roof.',
  Done:'Done. The bunkhouse writes building and full cover into the movement grid, so paths go round it and it gives cover in a fight. Its four beds and shade are ready tonight.'};
function caption(t){ if(!t){ capEl.hidden=true; return; } capEl.hidden=false; capEl.textContent=t; }
function startDemo(){ stopDemo(); setTool(null); const day=Math.floor(st.minutes/1440); found(RANCH_SITE.presets[0].centre,(R.hourOf(st.minutes)<6?day:day+1)*1440+6*60);
  st.stock.shelter+=10; st.stock.goods+=4; st.log.unshift({t:st.minutes,msg:'Watch a build: the ranch founded afresh at dawn.'});
  demo={t:0,phase:'choose',site:null,from:[713,20],to:[735,58]}; ui.speed=0; $('speed').querySelectorAll('button').forEach(q=>q.setAttribute('aria-pressed','false'));
  Object.assign(view,{tx:726,tz:40,dist:58,pitch:.72,yaw:-.7}); placeCam(); caption(STEPS.choose); $('demo').setAttribute('aria-pressed','true'); }
function stopDemo(){ if(!demo) return; demo=null; caption(''); $('demo').setAttribute('aria-pressed','false'); if(gridMesh.visible&&!$('grid').checked) gridMesh.visible=false; }
function stepDemo(dt){ const d=demo; d.t+=dt;
  if(d.phase==='choose'){ if(d.t>1.2&&tool!=='bunkhouse') setTool('bunkhouse'); if(d.t>4){ d.phase='layout'; d.t=0; caption(STEPS.layout); } return; }
  if(d.phase==='layout'){ const k=Math.min(1,d.t/3.2), e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2, x=d.from[0]+(d.to[0]-d.from[0])*e, z=d.from[1]+(d.to[1]-d.from[1])*e;   // eased over the house, then out into the open
    hoverAt({x,z}); if(d.t>4.4){ d.site=clickAt({x:d.to[0],z:d.to[1]}); setTool(null); if(!d.site){ stopDemo(); return; } d.phase='build'; d.t=0; ui.speed=1; } return; }
  const t=d.site, info=R.siteInfo(t), stg=stageOf(t);
  if(d.phase==='build'){ if(stg!==d.stage){ d.stage=stg; caption(STEPS[stg]||STEPS.Done); }
    // time runs at 60× while the materials are carried, 360× while people build, and fast when nobody is on it (the midday heat, the walk)
    ui.speed=!t.delivered?1:info.working?6:30; const [x,z]=centreOf(t);
    if(t.delivered){ view.tx+=(x-view.tx)*Math.min(1,dt*1.5); view.tz+=(z-view.tz)*Math.min(1,dt*1.5); view.dist+=(32-view.dist)*Math.min(1,dt); view.yaw+=dt*.12; placeCam(); }
    if(t.state==='done'){ d.phase='done'; d.t=0; caption(STEPS.Done); ui.speed=.25; gridMesh.visible=true; } return; }
  if(d.phase==='done'){ view.yaw+=dt*.08; placeCam(); if(d.t>7){ stopDemo(); $('speed').querySelector('[data-s="0.25"]').setAttribute('aria-pressed','true'); } } }

// ---------- the frame ----------
let last=performance.now(), tick=0, panelT=0;
function frame(now){ const dt=Math.min(.1,(now-last)/1000); last=now; tick++;
  if(ui.speed>0) R.advance(ui.speed*dt);
  syncThings(); updateSites(dt); updatePuffs(dt); if(demo) stepDemo(dt);
  const comp=Math.max(1,ui.speed*60), r=renderer.domElement.getBoundingClientRect();
  st.people.forEach((p,i)=>{ const f=figs[i], s0=p.task&&p.task.steps[p.task.step], sleeping=!!(s0&&s0.do==='sleep'), hidden=p.inside||p.rec.at==='gone', onBed=sleeping&&!p.inside;
    f.root.visible=!hidden&&!onBed; f.tag.style.display=f.root.visible?'':'none';
    f.lump.visible=!!onBed; if(onBed){ const t=p.task.spot&&p.task.spot.thing, [x,z]=t?centreOf(t):[p.x,p.z]; f.lump.position.set(x,H(x,z)-(t?0:.4),z); f.lump.rotation.y=t&&t.rot%2?Math.PI/2:0; }
    if(!f.root.visible) return;
    const y=H(p.x,p.z); f.root.position.set(p.x,y,p.z);
    if(p.heading!==undefined){ let a=p.heading-f.root.rotation.y; a=Math.atan2(Math.sin(a),Math.cos(a)); f.root.rotation.y+=a*Math.min(1,dt*10); }
    const act=!p.rec.alive?'dead':p.act==='work'?'work':p.act==='carry'?'carry':'idle', stg=P.thirstStage(p.rec);
    setInk(f,selected&&selected.kind==='person'&&selected.i===i?'selected':p.rec.brk&&p.rec.brk.until>st.minutes?'panicked':stg>=2||P.healthOf(p.rec)<.6?'wounded':p.task&&p.task.kind==='guard'?'overwatch':'calm');
    Motion.update(f,{act,ground:(x,z)=>H(x,z),compress:comp},dt);
    f.planks.visible=p.act==='carry'&&!!p.task&&p.task.kind==='build'; f.cans.visible=p.act==='carry'&&!!p.task&&p.task.kind==='haul';
    const v=new THREE.Vector3(p.x,y+2.1,p.z).project(cam); if(v.z>1){ f.tag.style.display='none'; } else { f.tag.style.left=((v.x+1)/2*r.width)+'px'; f.tag.style.top=((1-v.y)/2*r.height)+'px'; }
    f.tag.classList.toggle('sel',!!selected&&selected.kind==='person'&&selected.i===i); f.tag.classList.toggle('thirst',stg>=1); });
  siteTags(r);
  light();
  panelT+=dt; if(panelT>.25||ui.dirty){ panelT=0; ui.dirty=false; panels(); }
  renderer.render(scene,cam); requestAnimationFrame(frame); }
loadingEl.remove(); light(); paintGrid(); panels(); requestAnimationFrame(frame);
window.__ranch={R, get st(){ return st; }, startDemo, get demo(){ return demo; }, stageOf, get figs(){ return figs; }, found, view, placeCam, setTool, ui, get tool(){ return tool; }, frames:()=>tick, cellAt:(x,z)=>R.cellOf(x,z),
  screen:(x,z)=>{ cam.updateMatrixWorld(); const v=new THREE.Vector3(x,H(x,z),z).project(cam), r=renderer.domElement.getBoundingClientRect(); return {x:r.left+(v.x+1)/2*r.width, y:r.top+(1-v.y)/2*r.height}; }};
})();
