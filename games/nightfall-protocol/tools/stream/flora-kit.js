// ---------- Nightfall flora kit: the plants and rock of the Arizona Upland Sonoran Desert, and the ground they stand on ----------
// FloraKit(ctx) returns {build(s), buildSteps(s), frame(sectors,x,z,dist), paintGround(g,s,X,Z,px)}. Plant records come from the bake ([type,x,y,z,sx,sy,sz,rx,ry],
// types in SectorCore.PLANTS). buildSteps fills s.gen with instanced meshes, a step at a time; frame() shows each tile's
// detail by its distance from the camera. paintGround paints wash beds, the braided river bed and exposed rock on steep ground.
(function(root){
function FloraKit(o){
const {THREE,mat,C,sectorGeo}=o, TAU=Math.PI*2, K=C.PT;
const mtx=(x,y,z,sx=1,sy=1,sz=1,rx=0,ry=0,rz=0)=>new THREE.Matrix4().compose(new THREE.Vector3(x,y,z),new THREE.Quaternion().setFromEuler(new THREE.Euler(rx,ry,rz)),new THREE.Vector3(sx,sy,sz));
function merge(list){ const pos=[]; for(const [g0,m] of list){ const g=g0.index?g0.toNonIndexed():g0.clone(); g.applyMatrix4(m); pos.push(...g.attributes.position.array); } const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.computeVertexNormals(); return g; }
const ico=(r=1)=>new THREE.IcosahedronGeometry(r,0), dod=(r=1)=>new THREE.DodecahedronGeometry(r,0), cyl=(a,b,h,k=6)=>new THREE.CylinderGeometry(a,b,h,k), cone=(r,h,k=4)=>new THREE.ConeGeometry(r,h,k);
const rr=C.rng(91), R=()=>rr();
// a stick from point a to point b
const stick=(a,b,ra,rb,k=5)=>{ const dx=b[0]-a[0], dy=b[1]-a[1], dz=b[2]-a[2], L=Math.hypot(dx,dy,dz)||1, g=cyl(rb,ra,L,k); g.translate(0,L/2,0);
  const q=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0,1,0),new THREE.Vector3(dx/L,dy/L,dz/L)); return [g,new THREE.Matrix4().compose(new THREE.Vector3(...a),q,new THREE.Vector3(1,1,1))]; };
const fan=(n,len,lean,r,k=4,y0=0,spread=1)=>Array.from({length:n},(_,i)=>{ const a=i/n*TAU+R()*.5, l=len*(.75+R()*.4), le=lean*(.6+R()*.8)*spread; return stick([Math.cos(a)*.05,y0,Math.sin(a)*.05],[Math.cos(a)*l*le,y0+l*Math.sqrt(Math.max(.05,1-le*le)),Math.sin(a)*l*le],r,r*.35,k); });
const blobs=(n,cy,spread,r,sq=.7)=>Array.from({length:n},(_,i)=>{ const a=i/n*TAU+R(), d=spread*(.3+R()*.7); return [ico(1),mtx(Math.cos(a)*d,cy+(R()-.5)*r,Math.sin(a)*d,r*(.8+R()*.4),r*sq*(.8+R()*.4),r*(.8+R()*.4))]; });
// one entry per plant type: the parts, each a geometry and a colour; lo: a lighter stand-in for the ring sectors
const SPEC=[];
SPEC[K.SAG]={parts:[[merge([[cyl(.26,.32,5.2,7),mtx(0,2.6,0)],[new THREE.SphereGeometry(.26,7,4,0,TAU,0,Math.PI/2),mtx(0,5.2,0)],[cyl(.19,.19,1.1,6),mtx(.55,2.2,0,1,1,1,0,0,Math.PI/2)],[cyl(.19,.2,1.8,6),mtx(1.05,3.05,0)],[new THREE.SphereGeometry(.19,6,3,0,TAU,0,Math.PI/2),mtx(1.05,3.95,0)],[cyl(.17,.17,.9,6),mtx(-.48,2.9,0,1,1,1,0,0,Math.PI/2)],[cyl(.17,.18,1.3,6),mtx(-.9,3.5,0)],[new THREE.SphereGeometry(.17,6,3,0,TAU,0,Math.PI/2),mtx(-.9,4.15,0)]]),'#5f7d3f']],
  lo:[[merge([[cyl(.24,.32,5.2,5,1,true),mtx(0,2.6,0)],[cyl(.18,.18,1.9,4,1,true),mtx(1,3,0)],[cyl(.16,.16,1.4,4,1,true),mtx(-.9,3.4,0)]]),'#5f7d3f']]};
SPEC[K.PV]={parts:[[merge([[cyl(.08,.14,2.2,5),mtx(0,1.1,0,1,1,1,0,0,.25)],[cyl(.07,.12,2,5),mtx(.25,1.1,.2,1,1,1,.35,0,-.3)],[cyl(.06,.1,1.8,5),mtx(-.2,1,-.25,1,1,1,-.4,0,-.1)]]),'#8a9a52'],
  [merge([[ico(),mtx(.2,2.4,0,2,.9,1.8)],[ico(),mtx(-.6,2.2,.4,1.4,.7,1.3)],[ico(),mtx(.5,2.1,-.7,1.3,.6,1.2)]]),'#a7b85a']]};
SPEC[K.WOLF]={parts:[[merge([[ico(),mtx(0,.45,0,.9,.55,.85)],[ico(),mtx(.4,.35,.3,.55,.4,.5)]]),'#6e7f45']]};
SPEC[K.RCK]={parts:[[merge([[dod(),mtx(0,.3,0,1,.6,.8)]]),'#a8937a']]};
SPEC[K.REED]={parts:[[merge([0,1,2,3,4,5].map(i=>[cone(.05,1.5+i%3*.3),mtx(Math.cos(i*2.1)*.22,.8,Math.sin(i*2.1)*.22,1,1,1,Math.sin(i)*.15,0,Math.cos(i)*.15)])),'#7f9248']]};
// creosote: an open vase of thin dark stems with small clumps of resinous olive leaves at their tips
SPEC[K.CRE]={parts:[[merge(fan(6,1.4,.45,.03,3)),'#6a5a40'],[merge(Array.from({length:6},(_,i)=>{ const a=i/6*TAU+R()*.4, l=1.1+R()*.5, le=.45*(.6+R()*.8); return [ico(1),mtx(Math.cos(a)*l*le,l*.92,Math.sin(a)*l*le,.28,.2,.28)]; })),'#55602f']]};
// white bursage: a low pale grey mound
SPEC[K.BUR]={parts:[[merge([[ico(),mtx(0,.18,0,.45,.3,.45)],[ico(),mtx(.18,.14,.1,.28,.2,.28)]]),'#a3a487']]};
// brittlebush: a silver-grey dome
SPEC[K.BRT]={parts:[[merge([[ico(),mtx(0,.38,0,.6,.42,.6)],...blobs(4,.45,.35,.28,.8)]),'#b0b398']]};
// ocotillo: a fan of tall, nearly leafless wands
SPEC[K.OCO]={parts:[[merge(fan(11,3.6,.35,.045,4)),'#6c6646']]};
// teddy bear cholla: a dark trunk under a glowing golden head of stubby joints
SPEC[K.TBC]={parts:[[merge([[cyl(.1,.13,.9,5),mtx(0,.45,0)]]),'#4a4030'],[merge([...blobs(9,1.15,.3,.17,1.3),[ico(),mtx(0,1.25,0,.2,.28,.2)]]),'#dccb8a']]};
// buckhorn cholla: jointed purple-green branches
SPEC[K.BHC]={parts:[[merge([stick([0,0,0],[0,.8,0],.07,.07),...Array.from({length:6},(_,i)=>{ const a=i/6*TAU+R(), h=.4+R()*.4, l=.5+R()*.4; return stick([0,h,0],[Math.cos(a)*l*.6,h+l,Math.sin(a)*l*.6],.06,.05); }),...Array.from({length:6},(_,i)=>{ const a=i/6*TAU+R(), h=.9+R()*.4, l=.35+R()*.3; return stick([Math.cos(a)*.3,h,Math.sin(a)*.3],[Math.cos(a)*(.3+l*.7),h+l,Math.sin(a)*(.3+l*.7)],.05,.04); })]),'#7c7550']]};
// prickly pear: flat blue-green pads stacked at angles, a few purple fruits
const pad=(x,y,z,ry,rz,s)=>[new THREE.CylinderGeometry(.24,.24,.05,8),mtx(x,y,z,s,s*1.25,s,Math.PI/2,ry,rz)];
SPEC[K.PP]={parts:[[merge([pad(0,.25,0,0,0,1),pad(.18,.42,.05,.6,.3,.9),pad(-.2,.4,-.05,-.4,-.35,.85),pad(.05,.62,.12,1.2,.1,.8),pad(.32,.62,-.1,.2,.6,.7),pad(-.3,.62,.15,-1,-.5,.75),pad(.1,.25,.25,1.6,.2,.9)]),'#7a9350'],[merge([[ico(),mtx(.05,.83,.12,.05,.06,.05)],[ico(),mtx(.33,.82,-.1,.05,.06,.05)],[ico(),mtx(-.3,.81,.15,.05,.06,.05)]]),'#7a2f3a']]};
// fishhook barrel: a squat ribbed column with a yellow crown
SPEC[K.BAR]={parts:[[merge([[cyl(.28,.33,.75,12),mtx(0,.37,0)],[new THREE.SphereGeometry(.28,12,3,0,TAU,0,Math.PI/2),mtx(0,.74,0,1,.4,1)]]),'#6a7b3f'],[merge([[ico(),mtx(0,.86,0,.16,.06,.16)]]),'#c99a3a']]};
// velvet mesquite: dark, twisting multiple trunks under a wide, low, dark green crown
SPEC[K.MES]={parts:[[merge([stick([0,0,0],[.6,2.2,.2],.18,.1,6),stick([0,0,0],[-.7,2,.3],.16,.09,6),stick([0,0,0],[.1,2.4,-.6],.15,.08,6),stick([.6,2.2,.2],[1.6,2.8,.5],.08,.05),stick([-.7,2,.3],[-1.7,2.6,.2],.08,.05)]),'#4e3d2c'],
  [merge([[ico(),mtx(.3,3,0,2.6,.85,2.3)],[ico(),mtx(-1.3,2.7,.4,1.7,.7,1.6)],[ico(),mtx(1.4,2.75,.3,1.6,.65,1.5)],[ico(),mtx(0,2.6,-1.3,1.5,.6,1.4)]]),'#5b6a33']]};
// blue palo verde: bright green bark, a big airy blue-green crown (the wash tree)
SPEC[K.BPV]={parts:[[merge([stick([0,0,0],[.4,2.5,.1],.17,.1,6),stick([0,0,0],[-.5,2.3,.4],.15,.09,6),stick([.4,2.5,.1],[1.3,3.4,.3],.09,.06),stick([-.5,2.3,.4],[-1.3,3.1,.6],.08,.05)]),'#9cb25a'],
  [merge([[ico(),mtx(.2,3.4,0,2.6,1.1,2.4)],[ico(),mtx(-1.2,3,.5,1.7,.9,1.6)],[ico(),mtx(1.3,3.1,-.4,1.6,.85,1.5)]]),'#a9bd6c']]};
// ironwood: grey trunks under a dense, rounded, grey-green crown
SPEC[K.IRW]={parts:[[merge([stick([0,0,0],[.3,2,.2],.2,.12,6),stick([0,0,0],[-.4,1.9,-.2],.17,.1,6)]),'#6b675f'],[merge([[ico(),mtx(0,2.8,0,2.2,1.4,2.1)],[ico(),mtx(.8,2.4,.6,1.4,1,1.3)],[ico(),mtx(-.9,2.5,-.4,1.3,.9,1.3)]]),'#7a8763']]};
// desert broom: an upright bright-green broom of stiff twigs
SPEC[K.BRM]={parts:[[merge(fan(14,1.5,.22,.05,4)),'#7f993f']]};
// jojoba: a dense, rounded, leathery grey-olive shrub
SPEC[K.JOJ]={parts:[[merge([[ico(),mtx(0,.6,0,.85,.65,.85)],...blobs(4,.65,.5,.42,.8)]),'#7a8758']]};
// agave: a rosette of thick, pointed, blue-grey leaves
SPEC[K.AGV]={parts:[[merge(Array.from({length:13},(_,i)=>{ const a=i/13*TAU, up=i%2?.55:.95, g=cone(.11,.95,4); g.translate(0,.475,0); return [g,new THREE.Matrix4().compose(new THREE.Vector3(0,.05,0),new THREE.Quaternion().setFromEuler(new THREE.Euler(0,-a,up,'YXZ')),new THREE.Vector3(1,1,1))]; })),'#8c9b80']]};
// bunch grass: a tuft of straw-coloured blades
SPEC[K.GRS]={parts:[[merge(Array.from({length:11},(_,i)=>{ const a=i/11*TAU+R()*.5, l=.45+R()*.25, le=.2+R()*.35, g=new THREE.ConeGeometry(.03,l,3,1,true); g.translate(0,l/2,0); return [g,mtx(Math.cos(a)*.05,0,Math.sin(a)*.05,1,1,1,Math.sin(a)*le,0,-Math.cos(a)*le)]; })),'#c3ad6c']]};
// catclaw acacia: a tangled, thorny, grey-green thicket
SPEC[K.CAT]={parts:[[merge(fan(10,1.6,.6,.035,4)),'#6e6650'],[merge(blobs(6,1.1,.7,.45,.6)),'#7d8358']]};
// granite tors: big, rounded-angular blocks, desert varnish on their tops
SPEC[K.TOR]={parts:[[merge([[dod(),mtx(0,.6,0,1,.85,.9,.2,0,.1)],[ico(),mtx(.4,.9,.2,.55,.45,.5)]]),'#a28d74'],[merge([[dod(),mtx(0,1.08,0,.82,.32,.75,.2,0,.1)]]),'#6f5f50']]};
// a rock face: a broad slab lying in a cliff
SPEC[K.SLAB]={parts:[[merge([[dod(),mtx(0,0,0,1.1,.5,1),],[dod(),mtx(.5,.1,.3,.6,.4,.7)]]),'#8a7a68']]};
SPEC[K.COB]={parts:[[merge([[dod(),mtx(0,.3,0,1,.6,.8)]]),'#9b8f80']]};
// flood wood: a bleached branch left by the last flood
SPEC[K.DRF]={parts:[[merge([stick([-1.1,.08,0],[1.1,.1,.1],.09,.06),stick([.2,.1,.05],[.8,.15,.5],.05,.03),stick([-.5,.1,0],[-.9,.12,-.4],.04,.03)]),'#bdb19b']]};
// a dead tree: grey trunk and bare branches
SPEC[K.SNAG]={parts:[[merge([stick([0,0,0],[.2,2.6,.1],.15,.08,6),stick([.1,1.4,0],[1,2.6,.3],.06,.03),stick([.15,1.9,.05],[-.8,3,-.2],.05,.03),stick([.2,2.6,.1],[.6,3.4,-.2],.04,.02)]),'#8e857a']]};
// light stand-ins for what is drawn farther out: a few big facets in the same colours
const LO=(list,col)=>[merge(list),col], trunk=(h,r=.15)=>[cyl(r*.7,r,h,4),mtx(0,h/2,0)];
SPEC[K.CRE].lo=[LO([[ico(),mtx(0,.95,0,.75,.55,.75)],[ico(),mtx(.35,.7,.2,.45,.4,.45)]],'#55602f')];
SPEC[K.BHC].lo=[LO([trunk(.8,.08),[ico(),mtx(0,1.15,0,.55,.45,.55)]],'#7c7550')];
SPEC[K.PV].lo=[LO([trunk(2,.12)],'#8a9a52'),LO([[ico(),mtx(.1,2.3,0,1.9,.8,1.8)]],'#a7b85a')];
SPEC[K.CAT].lo=[LO([[ico(),mtx(0,.9,0,.95,.7,.95)]],'#7d8358')];
SPEC[K.JOJ].lo=[LO([[ico(),mtx(0,.6,0,.9,.7,.9)]],'#7a8758')];
SPEC[K.MES].lo=[LO([trunk(2.2,.18)],'#4e3d2c'),LO([[ico(),mtx(0,2.8,0,2.8,.9,2.6)]],'#5b6a33')];
SPEC[K.BPV].lo=[LO([trunk(2.4,.16)],'#9cb25a'),LO([[ico(),mtx(0,3.2,0,2.8,1.1,2.6)]],'#a9bd6c')];
SPEC[K.IRW].lo=[LO([trunk(2,.18)],'#6b675f'),LO([[ico(),mtx(0,2.7,0,2.3,1.4,2.2)]],'#7a8763')];
SPEC[K.TBC].lo=[LO([trunk(.9,.12)],'#4a4030'),LO([[ico(),mtx(0,1.2,0,.4,.45,.4)]],'#dccb8a')];
SPEC[K.OCO].lo=[LO(fan(5,3.6,.35,.05,3),'#6c6646')];
const SHARED=new Set(); for(const sp of SPEC) for(const p of [...sp.parts,...(sp.lo||[])]) SHARED.add(p[0]);

// Plants are drawn by distance from the camera, not by sector. Each sector draws the plants the ring keeps (trees, cacti,
// big shrubs) as light stand-ins, one instanced mesh per kind. Within reach of the camera, 150 m tiles with tight bounds
// draw every plant in full, and the stand-ins under those tiles are hidden (their matrices zeroed), so nothing is drawn
// twice. Small plants beyond the near tiles are not drawn. frame() keeps this up to date as the camera moves, so crossing
// into another sector rebuilds nothing; the tight bounds also let the sun's shadow camera skip tiles out of its reach.
const TILE=150, ZERO=new Float32Array(16);
function proxy(shape,cx,cy,cz,r){ const g=new THREE.BufferGeometry(); for(const k in shape.attributes) g.setAttribute(k,shape.attributes[k]); g.boundingSphere=new THREE.Sphere(new THREE.Vector3(cx,cy,cz),r); g.userData.proxy=true; return g; }
function shell(me){ if(!o.ink) return null; const sh=new THREE.InstancedMesh(me.geometry,o.ink,me.count); sh.instanceMatrix=me.instanceMatrix; sh.userData.ink=true; sh.matrixAutoUpdate=false; me.add(sh); return sh; }
function* buildSteps(s){
  for(const c of [...s.gen.children]){ s.gen.remove(c); c.traverse(q=>{ if(q.isInstancedMesh&&!q.userData.ink) q.geometry.dispose(); }); }
  const SEC=o.SEC||600, NT=Math.max(1,Math.round(SEC/TILE)), TS=SEC/NT, e=new THREE.Euler(0,0,0,'YXZ'), q=new THREE.Quaternion(), v=new THREE.Vector3(), sc=new THREE.Vector3(), m=new THREE.Matrix4();
  const tiles=Array.from({length:NT*NT},(_,i)=>({x0:s.x0+(i%NT)*TS,z0:s.z0+Math.floor(i/NT)*TS,all:SPEC.map(()=>[]),keep:SPEC.map(()=>[]),y:0,n:0}));
  for(const p of s.data.plants){ const t=C.PLANTS[p[0]]; if(!t||!SPEC[p[0]]) continue;
    const T=tiles[Math.min(NT-1,Math.max(0,Math.floor((p[3]-s.z0)/TS)))*NT+Math.min(NT-1,Math.max(0,Math.floor((p[1]-s.x0)/TS)))];
    T.all[p[0]].push(p); if(t.ring===1||(t.ring&&p[4]>t.ring)) T.keep[p[0]].push(p); T.y+=p[2]; T.n++; }
  // tilt first, then turn: a rock face leans into its slope facing down it
  const fill=(list,parts,geoOf,into)=>{ const out=[]; for(const [geo,col] of parts){ const me=new THREE.InstancedMesh(geoOf(geo),mat(col),list.length);
      list.forEach((p,i)=>{ e.set(p[7],p[8],0,'YXZ'); q.setFromEuler(e); me.setMatrixAt(i,m.compose(v.set(p[1],p[2],p[3]),q,sc.set(p[4],p[5],p[6]))); }); me.castShadow=true; me.receiveShadow=true; into.add(me); out.push(me); } return out; };
  // the far layer: kept plants as stand-ins, in tile order so a tile's run of instances can be hidden in one go
  const far=new THREE.Group(), runs=[]; s.gen.add(far);
  SPEC.forEach((sp,t)=>{ const list=[], at=[]; tiles.forEach(T=>{ at.push(list.length); list.push(...T.keep[t]); }); at.push(list.length); if(!list.length) return;
    for(const me of fill(list,sp.lo||sp.parts,g=>sectorGeo(g,s),far)){ me.userData.full=Float32Array.from(me.instanceMatrix.array); runs.push({me,at}); } });
  yield 'plants';
  const near=[]; s.flora={far,runs,near,on:new Array(NT*NT).fill(false)};
  for(let i=0;i<tiles.length;i++){ const T=tiles[i], G=new THREE.Group(), ink=[]; G.visible=false; near.push({box:[T.x0,T.z0,T.x0+TS,T.z0+TS],G,ink}); s.gen.add(G); if(!T.n) continue;
    const cx=T.x0+TS/2, cz=T.z0+TS/2, geoOf=g=>proxy(g,cx,T.y/T.n,cz,TS*.72+14);
    T.all.forEach((list,t)=>{ if(list.length) for(const me of fill(list,SPEC[t].parts,geoOf,G)) ink.push(shell(me)); });
    if(i%4===3) yield 'plants'; } }
function build(s){ for(const _ of buildSteps(s)); }
// distance from the camera's target to each tile: full plants (and their ink, closer still) near, stand-ins beyond
function frame(sectors,tx,tz,dist){ const RN=Math.min(400,130+dist*.4), RI=Math.min(260,90+dist*.3);
  for(const s of sectors){ const F=s.flora; if(!F) continue; let dirty=false;
    F.near.forEach((N,i)=>{ const b=N.box, d=Math.hypot(Math.max(b[0]-tx,0,tx-b[2]),Math.max(b[1]-tz,0,tz-b[3])), on=d<RN, ink=d<RI;
      for(const sh of N.ink) if(sh&&sh.visible!==ink) sh.visible=ink;
      if(on===F.on[i]) return; F.on[i]=on; N.G.visible=on; dirty=true;
      for(const {me,at} of F.runs){ const a=me.instanceMatrix.array, full=me.userData.full; if(on) for(let k=at[i];k<at[i+1];k++) a.set(ZERO,k*16); else a.set(full.subarray(at[i]*16,at[i+1]*16),at[i]*16); } });
    if(dirty) for(const {me} of F.runs) me.instanceMatrix.needsUpdate=true; } }

// ---------- the ground: rock exposed on steep slopes, wash beds, the braided river bed ----------
function paintGround(g,s,X,Z,px){ const D=s.data, n=s.hn, H=s.Hf, rnd=C.rng(400+s.c*17+s.r*29);
  const line=(pts,w,col,dash)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.lineWidth=Math.max(.6,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; if(dash) g.setLineDash(dash.map(d=>d*px)); g.stroke(); g.setLineDash([]); };
  const poly=(pts,fill)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.closePath(); g.fillStyle=fill; g.fill(); };
  // exposed rock: anything steeper than about 20 degrees shows its rock, darker and cracked on cliffs, lighter on rounded ridges
  { const c=document.createElement('canvas'); c.width=c.height=n; const cg=c.getContext('2d'), img=cg.createImageData(n,n), h=(a,b)=>H[Math.min(n-1,Math.max(0,b))*n+Math.min(n-1,Math.max(0,a))];
    for(let j=0;j<n;j++) for(let i=0;i<n;i++){ const dx=(h(i+1,j)-h(i-1,j))/8, dz=(h(i,j+1)-h(i,j-1))/8, sl=Math.atan(Math.hypot(dx,dz))*180/Math.PI, cv=h(i,j)-(h(i+2,j)+h(i-2,j)+h(i,j+2)+h(i,j-2))/4;
      const a=Math.max(0,Math.min(1,(sl-19)/11)), ridge=Math.max(0,Math.min(1,cv/1.2))*(sl>8?1:0), A=Math.max(a,ridge*.7); if(A<=0) continue;
      const wx=s.x0+(i-1)*4, wz=s.z0+(j-1)*4, nz=C.vnoise(wx,wz,9,5), o=(j*n+i)*4, dark=sl>30?.75:1;
      img.data[o]=(150+nz*30)*dark+ridge*12; img.data[o+1]=(128+nz*26)*dark+ridge*10; img.data[o+2]=(106+nz*22)*dark+ridge*8; img.data[o+3]=A*235; }
    cg.putImageData(img,0,0);
    // wash banks are sand and gravel, not rock: clear the rock from every wash and the river bed (and a little beyond)
    const cx=x=>(x-s.x0)/4+1, cz=z=>(z-s.z0)/4+1; cg.globalCompositeOperation='destination-out'; cg.lineCap='round'; cg.lineJoin='round';
    for(const w of D.water){ cg.beginPath(); w.pts.forEach(([x,z],i)=>i?cg.lineTo(cx(x),cz(z)):cg.moveTo(cx(x),cz(z))); cg.lineWidth=(w.hw*2+8)/4; cg.stroke(); }
    for(const b of D.beds){ cg.beginPath(); b.forEach(([x,z],i)=>i?cg.lineTo(cx(x),cz(z)):cg.moveTo(cx(x),cz(z))); cg.closePath(); cg.fill(); cg.lineWidth=3; cg.stroke(); }
    cg.globalCompositeOperation='source-over'; g.imageSmoothingEnabled=true; g.drawImage(c,X(s.x0-4)-2*px,Z(s.z0-4)-2*px,n*4*px,n*4*px);
    // joints and ledges run across the slope on the steepest ground
    g.strokeStyle='rgba(70,56,44,.55)'; g.lineCap='round';
    for(let j=1;j<n-1;j+=1) for(let i=1;i<n-1;i+=1){ const dx=(h(i+1,j)-h(i-1,j))/8, dz=(h(i,j+1)-h(i,j-1))/8, gl=Math.hypot(dx,dz), sl=Math.atan(gl)*180/Math.PI; if(sl<27||rnd()>.55) continue;
      const wx=s.x0+(i-1)*4+rnd()*4, wz=s.z0+(j-1)*4+rnd()*4, tx=-dz/gl, tz=dx/gl, L=1.5+rnd()*3; g.lineWidth=Math.max(.6,(.15+rnd()*.25)*px); g.beginPath(); g.moveTo(X(wx-tx*L),Z(wz-tz*L)); g.lineTo(X(wx+tx*L),Z(wz+tz*L)); g.stroke(); } }
  // the river's sandy bed: pale sand, wind ripples and gravel; damp, darker low-flow braids; the flood's strand line at its edge
  for(const b of D.beds){ poly(b,'#dcc8a1'); g.save(); g.beginPath(); b.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.closePath(); g.clip();
    const bb=C.bbox(b); for(let k=0;k<Math.min(5000,(bb[2]-bb[0])*(bb[3]-bb[1])/6);k++){ const x=bb[0]+rnd()*(bb[2]-bb[0]), z=bb[1]+rnd()*(bb[3]-bb[1]); g.fillStyle=['rgba(150,128,96,.45)','rgba(240,228,205,.5)','rgba(120,105,90,.4)'][Math.floor(rnd()*3)]; g.fillRect(X(x),Z(z),1.2+rnd()*1.6,1.2+rnd()*1.4); }
    for(let k=0;k<180;k++){ const x=bb[0]+rnd()*(bb[2]-bb[0]), z=bb[1]+rnd()*(bb[3]-bb[1]), l=3+rnd()*6; g.strokeStyle='rgba(170,148,112,.35)'; g.lineWidth=Math.max(.6,.18*px); g.beginPath(); g.moveTo(X(x),Z(z)); g.quadraticCurveTo(X(x+l/2),Z(z+(rnd()-.5)*1.2),X(x+l),Z(z+(rnd()-.5)*.8)); g.stroke(); }
    g.restore(); line([...b,b[0]],2.2,'rgba(140,118,88,.6)',[2.5,1.5]); }
  for(const w of D.water){ if(w.kind==='braid'){ line(w.pts,w.hw*2+1.2,'rgba(190,165,125,.8)'); line(w.pts,w.hw*1.3,'#bca37a'); line(w.pts,w.hw*.45,'#ad946c'); continue; }
    if(w.kind==='river'&&D.beds.length) continue;
    // a wash: dark cut-bank band, pale sandy bed, coarser gravel down the thalweg, a speckle of cobbles
    line(w.pts,w.hw*2+4,'#b39a74'); line(w.pts,w.hw*2-1,'#dcc9a2'); line(w.pts,Math.max(.8,w.hw*.55),'#c8b088');
    const d=C.densify(w.pts,3); for(const [x,z] of d) for(let k=0;k<3;k++){ const o=(rnd()-.5)*w.hw*1.6; g.fillStyle=rnd()<.5?'rgba(120,106,90,.55)':'rgba(236,224,200,.6)'; g.fillRect(X(x+o),Z(z+(rnd()-.5)*3),1.4,1.4); } } }
return {build,buildSteps,frame,paintGround,SHARED};
}
root.FloraKit=FloraKit;
})(typeof self!=='undefined'?self:this);
