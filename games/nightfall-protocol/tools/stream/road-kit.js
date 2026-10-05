// ---------- Nightfall road kit: road surfaces, paint, signs and signals for the streamed sectors ----------
// RoadKit(ctx) returns {paintGround(g,s,X,Z,px), *build(s,grp)}. It reads what tools/stream/roads-bake.js added to the
// sector files (lanes, surfaces, rk: junctions, signs, signals, bars, crosswalks, arrows, medians, gates, cattle guards)
// and falls back to plain roads for sector files without it. Coordinates: block metres, x east, z south, y up.
(function(root){
function RoadKit(o){
const {THREE,C,heightAt,IDX,renderer,mat,SHAPES,sectorGeo}=o, TAU=Math.PI*2;
const aniso=renderer.capabilities.getMaxAnisotropy(), CK=root.CarKit?root.CarKit({mat,C}):null;

// ---------- textures, drawn once ----------
function canvasTex(w,h,draw,seed){ const c=document.createElement('canvas'); c.width=w; c.height=h; const g=c.getContext('2d'), r=C.rng(seed);
  // anything drawn through W() is repeated across the edges so the texture tiles
  const W=fn=>{ for(const dx of [-w,0,w]) for(const dy of [-h,0,h]){ g.save(); g.translate(dx,dy); fn(); g.restore(); } };
  draw(g,r,W,w,h); const t=new THREE.CanvasTexture(c); t.wrapS=t.wrapT=THREE.RepeatWrapping; t.anisotropy=aniso; return t; }
function speckle(g,r,w,h,n,cols,sz=1.4){ for(let i=0;i<n;i++){ g.fillStyle=cols[Math.floor(r()*cols.length)]; const s=sz*(.5+r()); g.fillRect(r()*w,r()*h,s,s); } }
function crack(g,r,x,y,dx,dy,len,wid,col){ g.strokeStyle=col; g.lineWidth=wid; g.lineCap='round'; g.beginPath(); g.moveTo(x,y); let px=x,py=y; const n=Math.max(3,Math.round(len/6));
  for(let i=1;i<=n;i++){ px+=dx*len/n+(r()-.5)*len/n*.8*Math.abs(dy||1); py+=dy*len/n+(r()-.5)*len/n*.8*Math.abs(dx||1); g.lineTo(px,py); } g.stroke(); }
// one travel lane, 3.6 m across and 14.4 m along (256 x 1024): wheel paths, the oil drip line, cracks, sealant, patches
const laneTex=(base,dark,light,seed)=>canvasTex(256,1024,(g,r,W,w,h)=>{ g.fillStyle=base; g.fillRect(0,0,w,h);
  for(const [u,a] of [[.26,.16],[.74,.16]]){ const gr=g.createLinearGradient((u-.1)*w,0,(u+.1)*w,0); gr.addColorStop(0,'rgba(0,0,0,0)'); gr.addColorStop(.5,`rgba(20,18,16,${a})`); gr.addColorStop(1,'rgba(0,0,0,0)'); g.fillStyle=gr; g.fillRect(0,0,w,h); }
  for(let i=0;i<70;i++){ const y=r()*h, l=8+r()*40; W(()=>{ g.fillStyle=`rgba(15,12,10,${.1+r()*.15})`; g.beginPath(); g.ellipse(w*.5+(r()-.5)*18,y,6+r()*8,l,0,0,TAU); g.fill(); }); }
  speckle(g,r,w,h,9000,[dark,light,'rgba(255,255,255,.18)','rgba(0,0,0,.22)'],1.3);
  for(let i=0;i<3;i++){ const y=r()*h, x=r()*w*.6, pw=40+r()*120, ph=60+r()*200; W(()=>{ g.fillStyle=r()<.5?'rgba(25,24,22,.28)':'rgba(255,250,240,.07)'; g.fillRect(x,y,pw,ph); g.strokeStyle='rgba(10,10,10,.35)'; g.lineWidth=1.5; g.strokeRect(x,y,pw,ph); }); }
  W(()=>{ crack(g,r,3,0,0,1,h,1.2,'rgba(20,18,15,.55)'); });
  for(let i=0;i<5;i++){ const y=r()*h, tar=r()<.55; W(()=>{ crack(g,r,0,y,1,(r()-.5)*.2,w,tar?5:1.3,tar?'rgba(12,12,12,.7)':'rgba(20,18,15,.5)'); }); }
  for(let i=0;i<4;i++){ const x=r()*w, y=r()*h; W(()=>{ for(let k=0;k<6;k++) crack(g,r,x,y,Math.cos(k),Math.sin(k),18+r()*30,1,'rgba(20,18,15,.4)'); }); }
},seed);
// plain asphalt for shoulders and junction boxes, 8 m tile; sand blown in at the edges
const plainTex=(base,dark,light,seed)=>canvasTex(512,512,(g,r,W,w,h)=>{ g.fillStyle=base; g.fillRect(0,0,w,h);
  for(let i=0;i<18;i++){ const x=r()*w,y=r()*h,rad=30+r()*90; W(()=>{ const gr=g.createRadialGradient(x,y,0,x,y,rad); gr.addColorStop(0,r()<.5?'rgba(205,180,140,.16)':'rgba(10,10,10,.12)'); gr.addColorStop(1,'rgba(0,0,0,0)'); g.fillStyle=gr; g.fillRect(x-rad,y-rad,rad*2,rad*2); }); }
  speckle(g,r,w,h,16000,[dark,light,'rgba(255,255,255,.15)','rgba(0,0,0,.2)'],1.3);
  for(let i=0;i<7;i++){ const x=r()*w,y=r()*h,a=r()*TAU; W(()=>crack(g,r,x,y,Math.cos(a),Math.sin(a),60+r()*160,1.2,'rgba(20,18,15,.45)')); }
},seed);
// concrete panels 3.6 x 4.5 m with tined grooves and joints (7.2 x 9 m tile)
const concreteTex=canvasTex(512,640,(g,r,W,w,h)=>{ g.fillStyle='#b9b3a8'; g.fillRect(0,0,w,h);
  for(let p=0;p<4;p++){ g.fillStyle=`rgba(${r()<.5?'90,85,75':'255,250,240'},${.04+r()*.06})`; g.fillRect((p%2)*w/2,Math.floor(p/2)*h/2,w/2,h/2); }
  g.strokeStyle='rgba(60,55,50,.12)'; g.lineWidth=1; for(let y=0;y<h;y+=4){ g.beginPath(); g.moveTo(0,y+r()); g.lineTo(w,y+r()); g.stroke(); }
  speckle(g,r,w,h,6000,['rgba(80,75,65,.25)','rgba(255,255,255,.25)'],1.2);
  g.fillStyle='#4d4943'; g.fillRect(0,0,w,3); g.fillRect(0,h/2-1,w,3); g.fillRect(0,0,3,h); g.fillRect(w/2-1,0,3,h);
  for(let i=0;i<5;i++){ const x=r()*w,y=r()*h,a=r()*TAU; W(()=>crack(g,r,x,y,Math.cos(a),Math.sin(a),30+r()*90,1,'rgba(40,36,30,.5)')); }
  for(let i=0;i<6;i++){ const x=r()*w,y=r()*h,rad=10+r()*40; W(()=>{ g.fillStyle='rgba(40,35,30,.1)'; g.beginPath(); g.arc(x,y,rad,0,TAU); g.fill(); }); }
},31);
// gravel: angular stones in desert tones with a shadow each (4 m tile)
const gravelTex=canvasTex(512,512,(g,r,W,w,h)=>{ g.fillStyle='#ab9a7f'; g.fillRect(0,0,w,h); speckle(g,r,w,h,9000,['#8d7c63','#c4b393','#9d8e78'],1.5);
  const cols=['#cbbca2','#9a8f80','#b49b78','#8c7a66','#d6c9b0','#a3876a','#7f7569','#c2a582'];
  for(let i=0;i<2600;i++){ const x=r()*w,y=r()*h,s=2+r()*5.5,c=cols[Math.floor(r()*cols.length)],k=5+Math.floor(r()*3),a0=r()*TAU;
    W(()=>{ g.beginPath(); for(let q=0;q<k;q++){ const a=a0+q/k*TAU, rr=s*(.6+r()*.5); q?g.lineTo(x+1.2+Math.cos(a)*rr,y+1.6+Math.sin(a)*rr):g.moveTo(x+1.2+Math.cos(a)*rr,y+1.6+Math.sin(a)*rr); } g.fillStyle='rgba(50,40,30,.35)'; g.fill();
      g.beginPath(); for(let q=0;q<k;q++){ const a=a0+q/k*TAU, rr=s*(.6+r()*.5); q?g.lineTo(x+Math.cos(a)*rr,y+Math.sin(a)*rr):g.moveTo(x+Math.cos(a)*rr,y+Math.sin(a)*rr); } g.fillStyle=c; g.fill(); }); }
},47);
// a graded dirt road: two packed wheel ruts, a loose crown with pebbles and dry grass, washboard ripples (full width x 16 m)
const trackTex=canvasTex(256,1024,(g,r,W,w,h)=>{ g.fillStyle='#c4a982'; g.fillRect(0,0,w,h);
  for(const u of [.27,.73]){ const gr=g.createLinearGradient((u-.13)*w,0,(u+.13)*w,0); gr.addColorStop(0,'rgba(120,90,55,0)'); gr.addColorStop(.5,'rgba(120,90,55,.38)'); gr.addColorStop(1,'rgba(120,90,55,0)'); g.fillStyle=gr; g.fillRect(0,0,w,h); }
  for(let y=0;y<h;y+=9){ g.fillStyle=`rgba(90,65,40,${.05+r()*.05})`; g.fillRect(0,y,w,3); }
  speckle(g,r,w,h,7000,['rgba(110,85,55,.35)','rgba(235,220,190,.35)'],1.4);
  const stones=['#a99a84','#8f8170','#cdbfa5','#9b7e60'];
  for(let i=0;i<900;i++){ const y=r()*h, side=r(), u=side<.4?.5+(r()-.5)*.22:side<.7?r()*.12:1-r()*.12, s=1.5+r()*3.5; g.fillStyle=stones[Math.floor(r()*4)]; W(()=>{ g.beginPath(); g.ellipse(u*w,y,s,s*.8,r()*3,0,TAU); g.fill(); }); }
  for(let i=0;i<160;i++){ const y=r()*h, u=r()<.6?.5+(r()-.5)*.16:(r()<.5?r()*.08:1-r()*.08); W(()=>{ g.strokeStyle=r()<.5?'rgba(150,140,80,.7)':'rgba(170,150,95,.7)'; g.lineWidth=1.2; for(let k=0;k<6;k++){ g.beginPath(); g.moveTo(u*w,y); g.lineTo(u*w+(r()-.5)*10,y-4-r()*8); g.stroke(); } }); }
},59);
// loose sand: ripples and a few pebbles (6 m tile)
const sandTex=canvasTex(512,512,(g,r,W,w,h)=>{ g.fillStyle='#dac49c'; g.fillRect(0,0,w,h); speckle(g,r,w,h,8000,['rgba(170,140,100,.3)','rgba(250,240,220,.4)'],1.3);
  for(let i=0;i<120;i++){ const x=r()*w,y=r()*h,l=30+r()*70; W(()=>{ g.strokeStyle='rgba(160,130,90,.3)'; g.lineWidth=1.5; g.beginPath(); g.moveTo(x,y); g.quadraticCurveTo(x+l/2,y+(r()-.5)*10,x+l,y+(r()-.5)*6); g.stroke(); }); }
},61);
const M=(t,c='#ffffff',extra={})=>{ const m=new THREE.MeshStandardMaterial({map:t,color:c,roughness:.95,metalness:0,flatShading:true,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2,...extra}); m.userData.keep=true; return m; };
const TEX={
  laneDark:laneTex('#4f4e4b','rgba(20,20,20,.5)','rgba(150,145,135,.45)',3), laneLight:laneTex('#7d786f','rgba(50,45,40,.45)','rgba(200,190,170,.45)',5),
  plainDark:plainTex('#5c5a56','rgba(20,20,20,.5)','rgba(150,145,135,.4)',7), plainLight:plainTex('#88827a','rgba(50,45,40,.45)','rgba(205,195,175,.45)',9) };
const MAT={laneDark:M(TEX.laneDark), laneLight:M(TEX.laneLight), plainDark:M(TEX.plainDark), plainLight:M(TEX.plainLight), concrete:M(concreteTex), gravel:M(gravelTex), track:M(trackTex), sand:M(sandTex),
  jDark:M(TEX.plainDark,'#ffffff',{polygonOffsetFactor:-4,polygonOffsetUnits:-4}), jLight:M(TEX.plainLight,'#ffffff',{polygonOffsetFactor:-4,polygonOffsetUnits:-4}), jGravel:M(gravelTex,'#ffffff',{polygonOffsetFactor:-4,polygonOffsetUnits:-4}) };
const PAINT=k=>{ const m=new THREE.MeshStandardMaterial({color:k,roughness:.7,metalness:0,side:THREE.DoubleSide,polygonOffset:true,polygonOffsetFactor:-6,polygonOffsetUnits:-6}); m.userData.keep=true; return m; };
const WHITE=PAINT('#e6e3da'), YELLOW=PAINT('#dcaa35'), GROOVE=PAINT('#3b3a37');

// ---------- the sign atlas: one canvas, cells packed in shelves; street names are added as sectors need them ----------
const AT=1024, atC=document.createElement('canvas'); atC.width=atC.height=AT; const ag=atC.getContext('2d'); const atlas=new THREE.CanvasTexture(atC); atlas.anisotropy=aniso; atlas.flipY=false;
const cells=new Map(); let shelfY=0, shelfH=0, shelfX=0, dirty=false;
const FONT='"IBM Plex Sans Condensed","Arial Narrow",Arial,sans-serif';
function cell(key,w,h,draw){ let c=cells.get(key); if(c) return c;
  if(shelfX+w>AT){ shelfY+=shelfH+2; shelfX=0; shelfH=0; } if(shelfY+h>AT) return cells.get('blank');
  const x=shelfX, y=shelfY; shelfX+=w+2; shelfH=Math.max(shelfH,h); ag.save(); ag.beginPath(); ag.rect(x,y,w,h); ag.clip(); ag.translate(x,y); draw(ag,w,h); ag.restore();
  c={u0:x/AT,v0:y/AT,u1:(x+w)/AT,v1:(y+h)/AT}; cells.set(key,c); dirty=true; return c; }
const rr=(g,x,y,w,h,r)=>{ g.beginPath(); g.moveTo(x+r,y); g.arcTo(x+w,y,x+w,y+h,r); g.arcTo(x+w,y+h,x,y+h,r); g.arcTo(x,y+h,x,y,r); g.arcTo(x,y,x+w,y,r); g.closePath(); };
const fitText=(g,t,x,y,maxW,size,weight='600')=>{ let s=size; do{ g.font=`${weight} ${s}px ${FONT}`; s-=1; } while(g.measureText(t).width>maxW&&s>8); g.fillText(t,x,y); };
// a little road grime on every face
const grime=(g,w,h,seed)=>{ const r=C.rng(seed); for(let i=0;i<w*h/90;i++){ g.fillStyle=`rgba(${r()<.5?'90,70,40':'255,255,255'},${r()*.08})`; g.fillRect(r()*w,r()*h,2,2); } };
cell('blank',8,8,(g,w,h)=>{ g.fillStyle='#8e9396'; g.fillRect(0,0,w,h); });
const stopCell=()=>cell('stop',128,128,(g,w,h)=>{ const oct=(rad,col)=>{ g.beginPath(); for(let i=0;i<8;i++){ const a=(i+.5)/8*TAU; g.lineTo(w/2+Math.cos(a)*rad,h/2+Math.sin(a)*rad); } g.closePath(); g.fillStyle=col; g.fill(); };
  oct(64,'#ffffff'); oct(58,'#b8232b'); g.fillStyle='#fff'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,'STOP',w/2,h/2+2,100,40,'700'); grime(g,w,h,3); });
const yieldCell=()=>cell('yield',128,112,(g,w,h)=>{ const tri=(i,col)=>{ g.beginPath(); g.moveTo(i,i*.6); g.lineTo(w-i,i*.6); g.lineTo(w/2,h-i*1.1); g.closePath(); g.fillStyle=col; g.fill(); }; tri(0,'#b8232b'); tri(18,'#fff'); g.fillStyle='#b8232b'; g.textAlign='center'; fitText(g,'YIELD',w/2,44,60,17,'700'); });
const speedCell=t=>cell('speed'+t,96,120,(g,w,h)=>{ g.fillStyle='#f2f0ea'; g.fillRect(0,0,w,h); g.strokeStyle='#1d1d1d'; g.lineWidth=3; rr(g,4,4,w-8,h-8,6); g.stroke(); g.fillStyle='#1d1d1d'; g.textAlign='center'; g.textBaseline='alphabetic';
  fitText(g,'SPEED',w/2,30,80,18,'700'); fitText(g,'LIMIT',w/2,50,80,18,'700'); fitText(g,t,w/2,104,84,52,'700'); grime(g,w,h,7); });
const dneCell=()=>cell('dne',112,112,(g,w,h)=>{ g.fillStyle='#f2f0ea'; g.fillRect(0,0,w,h); g.fillStyle='#b8232b'; g.beginPath(); g.arc(w/2,h/2,48,0,TAU); g.fill(); g.fillStyle='#fff'; g.fillRect(16,h/2-8,w-32,16);
  g.textAlign='center'; g.textBaseline='middle'; fitText(g,'DO NOT',w/2,h/2-24,70,15,'700'); fitText(g,'ENTER',w/2,h/2+24,70,15,'700'); });
const plaqueCell=t=>cell('plq'+t,96,32,(g,w,h)=>{ g.fillStyle='#b8232b'; g.fillRect(0,0,w,h); g.strokeStyle='#fff'; g.lineWidth=2; g.strokeRect(3,3,w-6,h-6); g.fillStyle='#fff'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,t,w/2,h/2+1,84,18,'700'); });
const bladeCell=t=>cell('blade'+t,256,40,(g,w,h)=>{ g.fillStyle='#1f6a45'; g.fillRect(0,0,w,h); g.strokeStyle='#f2f0ea'; g.lineWidth=2; rr(g,3,3,w-6,h-6,4); g.stroke(); g.fillStyle='#f2f0ea'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,t,w/2,h/2+1,236,26,'600'); grime(g,w,h,t.length); });
const greenCell=(key,w,h,lines,tab,foot)=>cell(key,w,h,(g)=>{ g.fillStyle='#1f6a45'; const top=tab?34:0; g.fillRect(0,top,w,h-top); if(tab){ const tw=150; g.fillRect(w-tw,0,tw,top+6); g.strokeStyle='#f2f0ea'; g.lineWidth=2; rr(g,w-tw+4,4,tw-8,top,4); g.stroke(); g.fillStyle='#f2f0ea'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,tab,w-tw/2,top/2+4,tw-16,22,'600'); }
  g.strokeStyle='#f2f0ea'; g.lineWidth=3; rr(g,5,top+5,w-10,h-top-10,8); g.stroke(); g.fillStyle='#f2f0ea'; g.textAlign='center'; g.textBaseline='middle';
  const n=lines.length+(foot?1:0), lh=(h-top-20)/Math.max(1,n); lines.forEach((t,i)=>fitText(g,t,w/2,top+10+lh*(i+.5),w-30,Math.min(44,lh*.8),'600')); if(foot) fitText(g,foot,w/2,top+10+lh*(n-.5),w-30,Math.min(30,lh*.6),'600'); grime(g,w,h,key.length); });
const shieldPath=(g,x,y,w,h)=>{ g.beginPath(); g.moveTo(x,y+h*.08); g.quadraticCurveTo(x+w*.25,y,x+w*.5,y+h*.06); g.quadraticCurveTo(x+w*.75,y,x+w,y+h*.08); g.lineTo(x+w,y+h*.45); g.quadraticCurveTo(x+w*.95,y+h*.85,x+w*.5,y+h); g.quadraticCurveTo(x+w*.05,y+h*.85,x,y+h*.45); g.closePath(); };
const shieldCell=t=>cell('shield'+t,112,112,(g,w,h)=>{ g.fillStyle='#f2f0ea'; shieldPath(g,2,2,w-4,h-4); g.fill(); g.fillStyle='#1d4f9a'; shieldPath(g,8,8,w-16,h-16); g.fill(); g.fillStyle='#b8232b'; g.save(); shieldPath(g,8,8,w-16,h-16); g.clip(); g.fillRect(0,0,w,32); g.restore();
  g.fillStyle='#fff'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,'INTERSTATE',w/2,22,70,10,'700'); fitText(g,t,w/2,66,80,48,'700'); });
const cardCell=t=>cell('card'+t,112,40,(g,w,h)=>{ g.fillStyle='#f2f0ea'; g.fillRect(0,0,w,h); g.strokeStyle='#1d1d1d'; g.lineWidth=2; g.strokeRect(3,3,w-6,h-6); g.fillStyle='#1d1d1d'; g.textAlign='center'; g.textBaseline='middle'; fitText(g,t,w/2,h/2+1,w-14,26,'700'); });
const backCell=()=>cell('backplate',64,128,(g,w,h)=>{ g.fillStyle='#e0b52a'; g.fillRect(0,0,w,h); g.fillStyle='#1e1e1e'; g.fillRect(6,6,w-12,h-12); });
const FACE=new THREE.MeshStandardMaterial({map:atlas,roughness:.55,metalness:.05,flatShading:true}); FACE.userData.keep=true;

// ---------- a batch that carries texture coordinates ----------
class UB{ constructor(){ this.m=new Map(); }
  get(m){ let a=this.m.get(m); if(!a){ a={p:[],u:[]}; this.m.set(m,a); } return a; }
  tri(m,a,b,c,ua,ub,uc){ const A=this.get(m); A.p.push(...a,...b,...c); A.u.push(...(ua||[0,0]),...(ub||[0,0]),...(uc||[0,0])); }
  quad(m,a,b,c,d,ua,ub,uc,ud){ this.tri(m,a,b,c,ua,ub,uc); this.tri(m,a,c,d,ua,uc,ud); }
  meshes(cast){ const out=[]; for(const [m,A] of this.m){ if(!A.p.length) continue; const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(A.p,3)); g.setAttribute('uv',new THREE.Float32BufferAttribute(A.u,2)); g.computeVertexNormals();
    const me=new THREE.Mesh(g,m); me.castShadow=cast; me.receiveShadow=true; out.push(me); } return out; } }
// local frame of a roadside object: x to the viewer's right, y up, z out of the face
const frame=(x,y,z,yaw)=>{ const c=Math.cos(yaw), s=Math.sin(yaw); return (lx,ly,lz)=>[x+lx*c+lz*s,y+ly,z-lx*s+lz*c]; };
function box(B,m,F,cx,cy,cz,hx,hy,hz){ const P=(a,b,c)=>F(cx+a*hx,cy+b*hy,cz+c*hz);
  const f=[[[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]],[[1,-1,-1],[-1,-1,-1],[-1,1,-1],[1,1,-1]],[[-1,-1,-1],[-1,-1,1],[-1,1,1],[-1,1,-1]],[[1,-1,1],[1,-1,-1],[1,1,-1],[1,1,1]],[[-1,1,1],[1,1,1],[1,1,-1],[-1,1,-1]],[[-1,-1,-1],[1,-1,-1],[1,-1,1],[-1,-1,1]]];
  for(const q of f) B.quad(m,P(...q[0]),P(...q[1]),P(...q[2]),P(...q[3])); }
function tube(B,m,a,b,r,k=6){ const dx=b[0]-a[0], dy=b[1]-a[1], dz=b[2]-a[2], L=Math.hypot(dx,dy,dz)||1, d=[dx/L,dy/L,dz/L], up=Math.abs(d[1])>.9?[1,0,0]:[0,1,0];
  const u=[d[1]*up[2]-d[2]*up[1],d[2]*up[0]-d[0]*up[2],d[0]*up[1]-d[1]*up[0]], ul=Math.hypot(...u); u[0]/=ul; u[1]/=ul; u[2]/=ul; const v=[d[1]*u[2]-d[2]*u[1],d[2]*u[0]-d[0]*u[2],d[0]*u[1]-d[1]*u[0]];
  const ring=(p,i)=>{ const t=i/k*TAU, c=Math.cos(t)*r, s=Math.sin(t)*r; return [p[0]+u[0]*c+v[0]*s,p[1]+u[1]*c+v[1]*s,p[2]+u[2]*c+v[2]*s]; };
  for(let i=0;i<k;i++) B.quad(m,ring(a,i),ring(a,i+1),ring(b,i+1),ring(b,i)); }
// a flat plate in the face plane (z = dz), its outline given in local x,y; face from the atlas cell, metal back
function plate(B,F,pts,c,dz=.03,back=true){ const xs=pts.map(p=>p[0]), ys=pts.map(p=>p[1]), x0=Math.min(...xs), x1=Math.max(...xs), y0=Math.min(...ys), y1=Math.max(...ys);
  const uv=p=>[c.u0+(p[0]-x0)/(x1-x0)*(c.u1-c.u0), c.v0+(y1-p[1])/(y1-y0)*(c.v1-c.v0)];
  for(let i=1;i<pts.length-1;i++){ B.tri(FACE,F(...pts[0],dz),F(...pts[i],dz),F(...pts[i+1],dz),uv(pts[0]),uv(pts[i]),uv(pts[i+1])); if(back) B.tri(METAL,F(...pts[0],dz-.02),F(...pts[i+1],dz-.02),F(...pts[i],dz-.02)); } }
const rect=(w,h,y0)=>[[-w/2,y0],[w/2,y0],[w/2,y0+h],[-w/2,y0+h]];
const octo=(r,y)=>Array.from({length:8},(_,i)=>{ const a=(i+.5)/8*TAU; return [Math.cos(a)*r,y-Math.sin(a)*r]; }).reverse();
const METAL=mat('#8e9396'), POST=mat('#7f8589'), GALV=mat('#a9aeb0'), HEAD=mat('#242424'), RED=mat('#4a1612'), AMBER=mat('#4d3a10'), GREEN=mat('#123d2a'), WOOD=mat('#6b5a45'), PIPE=mat('#8b8f8c'), DARK=mat('#2b2724'), BERM=mat('#b99d74'), CONC=mat('#c4bdb0'), REFL=mat('#e8e4d8'), REFLA=mat('#d9a12a');
const WOODP=mat('#6a5844'), POLE69=mat('#7a7166'), INSUL=mat('#c9c2b2'), CAN=mat('#8d9193'), LAMP=mat('#8f9496'), LENS=mat('#d9d4bf'), BRONZE=mat('#3b3530'), TRANS=mat('#7f8a80');
const MESH=(()=>{ const m=new THREE.MeshStandardMaterial({color:0x6d6f6c,transparent:true,opacity:.35,side:THREE.DoubleSide,depthWrite:false}); m.userData.keep=true; return m; })();
const lens=(B,F,lx,ly,lz,r,m)=>{ for(let i=0;i<8;i++){ const a=i/8*TAU, b=(i+1)/8*TAU; B.tri(m,F(lx,ly,lz),F(lx+Math.cos(a)*r,ly+Math.sin(a)*r,lz),F(lx+Math.cos(b)*r,ly+Math.sin(b)*r,lz)); } };

// ---------- ground paint under the roads: dusty margins, and rock exposed where the road was cut into a hill ----------
function paintGround(g,s,X,Z,px){ const D=s.data, rr0=C.rng(77+s.c*5+s.r*11); s.cutRocks=[];
  const line=(pts,w,col)=>{ g.beginPath(); pts.forEach(([x,z],i)=>i?g.lineTo(X(x),Z(z)):g.moveTo(X(x),Z(z))); g.lineWidth=Math.max(.6,w*px); g.strokeStyle=col; g.lineCap='round'; g.lineJoin='round'; g.stroke(); };
  for(const rd of [...D.roads].sort((a,b)=>a.w-b.w)){ const surf=C.roadSurf(rd); line(rd.pts,rd.w+(rd.drive?2.4:.8),surf==='asphalt'||surf==='concrete'?'#b8b1a3':surf==='gravel'?'#b4a283':'#bfa47f'); }
  for(const rd of D.roads){ if(!rd.drive||rd.cls==='service'||rd.bridge>=0) continue; const pts=C.densify(rd.pts,3), hw=rd.w/2;
    for(let i=0;i<pts.length-1;i++){ const [x,z]=pts[i], [x2,z2]=pts[i+1], dx=x2-x, dz=z2-z, l=Math.hypot(dx,dz)||1, nx=-dz/l, nz=dx/l, y=heightAt(x,z);
      // bridge approaches are built-up fill, not cuts
      if(IDX.bridges.some(b=>x>b.bb[0]-45&&x<b.bb[2]+45&&z>b.bb[1]-45&&z<b.bb[3]+45)) continue;
      for(const sg of [-1,1]){ const rise=heightAt(x+nx*sg*(hw+6),z+nz*sg*(hw+6))-y; if(rise<1.8) continue; const ext=Math.min(18,rise*2.4), o0=hw+1, o1=hw+1+ext;
        const q=[[x+nx*sg*o0,z+nz*sg*o0],[x2+nx*sg*o0,z2+nz*sg*o0],[x2+nx*sg*o1,z2+nz*sg*o1],[x+nx*sg*o1,z+nz*sg*o1]];
        g.beginPath(); q.forEach(([a,b],k)=>k?g.lineTo(X(a),Z(b)):g.moveTo(X(a),Z(b))); g.closePath(); g.fillStyle=`rgba(${142+rr0()*16|0},${122+rr0()*14|0},${104+rr0()*12|0},.85)`; g.fill();
        // strata run along the cut
        for(let k=1;k<4;k++){ const o=o0+ext*k/4+(rr0()-.5); g.beginPath(); g.moveTo(X(x+nx*sg*o),Z(z+nz*sg*o)); g.lineTo(X(x2+nx*sg*o),Z(z2+nz*sg*o)); g.lineWidth=Math.max(.6,.35*px); g.strokeStyle='rgba(95,78,62,.55)'; g.stroke(); }
        if(rr0()<.5){ const o=hw+1.2+rr0()*1.6, t=rr0(), rx=x+dx*t+nx*sg*o, rz=z+dz*t+nz*sg*o; s.cutRocks.push([rx,heightAt(rx,rz),rz,.3+rr0()*.6]); } } } } }

// ---------- building the roads of a sector ----------
const SURFM={concrete:'concrete',gravel:'gravel',dirt:'track',sand:'sand'};
function* build(s,grp){ const D=s.data, rk=D.rk||{}, J=rk.junctions||[], rnd=C.rng(5+s.c*7+s.r*13);
  // height on the sector's terrain mesh itself (its triangles, not the smooth interpolation), so nothing pokes through the road
  const n0=s.hn, Hf=s.Hf, HM=(x,z)=>{ const fx=(x-s.x0)/4, fz=(z-s.z0)/4; if(!Hf||fx<0||fz<0||fx>150||fz>150) return heightAt(x,z);
    const i=Math.min(149,Math.floor(fx)), j=Math.min(149,Math.floor(fz)), u=fx-i, v=fz-j, h=(a,b)=>Hf[(b+1)*n0+a+1];
    return u+v<=1?h(i,j)+u*(h(i+1,j)-h(i,j))+v*(h(i,j+1)-h(i,j)):h(i+1,j+1)+(1-u)*(h(i,j+1)-h(i+1,j+1))+(1-v)*(h(i+1,j)-h(i+1,j+1)); };
  const nearJ=(x,z,pad=0)=>{ for(const j of J) if(Math.hypot(x-j[0],z-j[1])<j[3]+pad) return true; return false; };
  const RB=new UB(), PB=new UB(), berms=[], rocks=[];
  D.roads.forEach((rd,ri)=>{ const sec=C.roadSection(rd), surf=C.roadSurf(rd), paved=surf==='asphalt'||surf==='concrete', br=rd.bridge>=0?IDX.bridges[rd.bridge]:null;
    const dark=paved&&(rd.cls==='motorway'||/_link$/.test(rd.cls)||rd.cls==='secondary'||rd.cls==='trunk'||rd.cls==='primary');
    const pts=C.densify(rd.pts,3), n=pts.length, Ls=[0]; for(let i=1;i<n;i++) Ls.push(Ls[i-1]+Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])); const tot=Ls[n-1]||1, vo=rnd()*50;
    const lift=(paved?.06:.04)+(ri%12)*.0012;
    const nrm=i=>{ const p=pts[Math.max(0,i-1)], q=pts[Math.min(n-1,i+1)], dx=q[0]-p[0], dz=q[1]-p[1], l=Math.hypot(dx,dz)||1; return [-dz/l,dx/l]; };
    const N=pts.map((_,i)=>nrm(i));
    const P=(i,off,dy=0)=>{ const x=pts[i][0]+N[i][0]*off, z=pts[i][1]+N[i][1]*off; return [x,(br?br.yAt(Ls[i]/tot)+.07:HM(x,z)+lift)+dy,z]; };
    // strip between two offsets, uv from a function of (offset, arc length)
    // split into columns no wider than 2 m so the ground's crown or curve across the road can't show through
    const strip=(m,o0,o1,uv,dy=0)=>{ const k=Math.max(1,Math.ceil(Math.abs(o1-o0)/2)); for(let c=0;c<k;c++){ const a=o0+(o1-o0)*c/k, b=o0+(o1-o0)*(c+1)/k;
      for(let i=0;i<n-1;i++) RB.quad(m,P(i,a,dy),P(i+1,a,dy),P(i+1,b,dy),P(i,b,dy),uv(a,Ls[i]),uv(a,Ls[i+1]),uv(b,Ls[i+1]),uv(b,Ls[i])); } };
    const W2=rd.w/2, pv=sec.pave/2;
    if(paved){ const lanesM=surf==='concrete'?MAT.concrete:dark?MAT.laneDark:MAT.laneLight, plainM=surf==='concrete'?MAT.concrete:dark?MAT.plainDark:MAT.plainLight;
      const cu=surf==='concrete'?(o,l)=>[o/7.2,(l+vo)/9]:null;
      // the travelled way: columns at every painted line so the paint sits exactly on the surface
      let xL=-pv, xR=pv; if(sec.x0!==undefined){ xL=sec.x0; xR=sec.x1; } else if(sec.sh){ xL=-(pv-sec.sh); xR=pv-sec.sh; }
      const cols=[...new Set([xL,...sec.lines.map(l=>l.o).filter(o=>o>xL&&o<xR),...(sec.mid!==undefined||sec.x0===undefined?[0]:[]),xR].map(v=>Math.round(v*1000)/1000))].sort((a,b)=>a-b);
      const lw=sec.x0!==undefined?3.7:3.6, c0=sec.x0!==undefined?sec.x0:0;
      const lu=cu||((o,l)=>[Math.abs(o-c0)/lw,(l+vo)/14.4]);
      for(let k=0;k<cols.length-1;k++) strip(lanesM,cols[k],cols[k+1],lu);
      if(xL>-pv+.05) strip(plainM,-pv,xL,cu||((o,l)=>[o/8,(l+vo)/8])); if(xR<pv-.05) strip(plainM,xR,pv,cu||((o,l)=>[o/8,(l+vo)/8]));
      if(!br&&W2>pv+.25) for(const sg of [-1,1]) strip(MAT.gravel,sg*pv,sg*(W2+.5),(o,l)=>[o/4,(l+vo)/4],-.015);
      // paint
      const near=i=>{ for(const j of J) if(j[3]>0&&Math.hypot(pts[i][0]-j[0],pts[i][1]-j[1])<j[3]+60) return true; return false; };
      for(const L of sec.lines){ const m=L.c==='y'?YELLOW:WHITE, hw=L.w/2;
        for(let i=0;i<n-1;i++){ const mx=(pts[i][0]+pts[i+1][0])/2, mz=(pts[i][1]+pts[i+1][1])/2; if(nearJ(mx,mz)) continue;
          if(L.c==='y'&&(L.near!==undefined||(rd.cls==='tertiary'&&L.dash))){ const nr=near(i); if(L.near&&!nr) continue; if(!L.near&&L.dash&&nr&&rd.cls==='tertiary') continue; }
          let a=Ls[i], b=Ls[i+1];
          const seg=(s0,s1)=>{ const t0=(s0-Ls[i])/((b-a)||1), t1=(s1-Ls[i])/((b-a)||1), lerp=(p,q,t)=>p.map((v,k)=>v+(q[k]-v)*t);
            PB.quad(m,lerp(P(i,L.o-hw,.012),P(i+1,L.o-hw,.012),t0),lerp(P(i,L.o-hw,.012),P(i+1,L.o-hw,.012),t1),lerp(P(i,L.o+hw,.012),P(i+1,L.o+hw,.012),t1),lerp(P(i,L.o+hw,.012),P(i+1,L.o+hw,.012),t0)); };
          if(!L.dash){ seg(a,b); continue; }
          const per=L.dash[0]+L.dash[1]; let k=Math.floor(a/per)*per; for(;k<b;k+=per){ const s0=Math.max(a,k), s1=Math.min(b,k+L.dash[0]); if(s1>s0&&C.rng(Math.floor(k/per)*7+ri)()>.06) seg(s0,s1); } } }
      // rumble strips on the freeway shoulders
      if(sec.rumble) for(const [o,wd] of [[xL-.55,.35],[xR+.6,.4]]) for(let sv=.3;sv<tot;sv+=.6){ let i=0; while(i<n-2&&Ls[i+1]<sv) i++; const t=(sv-Ls[i])/((Ls[i+1]-Ls[i])||1); if(t<0||t>1) continue;
        const A=P(i,o-wd,.008), B2=P(i+1,o-wd,.008), Cc=P(i+1,o+wd,.008), Dd=P(i,o+wd,.008), l=(p,q,u)=>p.map((v,k)=>v+(q[k]-v)*u), dt=.09/((Ls[i+1]-Ls[i])||1);
        if(nearJ(...[l(A,B2,t)[0],l(A,B2,t)[2]])) continue; PB.quad(GROOVE,l(A,B2,t-dt),l(A,B2,t+dt),l(Dd,Cc,t+dt),l(Dd,Cc,t-dt)); }
      // delineators along the freeway and its ramps
      if(rd.cls==='motorway'||/_link$/.test(rd.cls)){ const step=rd.cls==='motorway'?40:15; for(let sv=(Ls.length?vo%step:0);sv<tot;sv+=step){ let i=0; while(i<n-2&&Ls[i+1]<sv) i++; const p=P(i,W2+.3,-lift), q=pts[i], nn=N[i];
        if(br||nearJ(q[0],q[1],4)) continue; (s.delin||(s.delin=[])).push([p[0],p[1],p[2],Math.atan2(nn[0],nn[1])]); } } }
    else { // dirt, gravel and sand: one textured strip, edges a little lower, grader berms on graded roads
      const m=MAT[SURFM[surf]||'track'], u=surf==='dirt'&&rd.cls!=='path'&&rd.cls!=='footway'?(o,l)=>[(o+W2)/(2*W2),(l+vo)/16]:(o,l)=>[o/(surf==='gravel'?4:6),(l+vo)/(surf==='gravel'?4:6)];
      strip(m,-W2,W2,u); if(rd.drive&&!br){ for(const sg of [-1,1]) strip(m,sg*W2,sg*(W2+.6),u,-.05); }
      if(rd.drive&&!br&&(rd.cls==='track'||rd.cls==='unclassified'||rd.cls==='residential')) for(let i=1;i<n-1;i++){ if(nearJ(pts[i][0],pts[i][1],2)) continue;
        // no berm on a tight bend: the grader can't throw one there
        const h0=Math.atan2(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1]), h1=Math.atan2(pts[i+1][0]-pts[i][0],pts[i+1][1]-pts[i][1]); if(Math.abs(Math.atan2(Math.sin(h1-h0),Math.cos(h1-h0)))>.15) continue;
        for(const sg of [-1,1]){ const o=sg*(W2+.75); berms.push([P(i,o-.55*sg,-.06),P(i+1,o-.55*sg,-.06),P(i+1,o,.16-.04),P(i,o,.16-.04),P(i+1,o+.6*sg,-.08),P(i,o+.6*sg,-.08)]);
          if(rnd()<.55){ const t=rnd(), p=P(i,o+(rnd()-.5)*.8,-.05), q=P(i+1,o,-.05); rocks.push([p[0]+(q[0]-p[0])*t,p[1],p[2]+(q[2]-p[2])*t,.1+rnd()*.22]); } } } } });
  // junction boxes: the crossing paved over in one piece so lane textures don't cross each other
  for(const j of J){ const hp=j[4]; if(!j[2]||!hp||hp.length<6) continue; const dark=D.roads.some(rd=>rd.cls!=='residential'&&rd.cls!=='service'&&rd.cls!=='track'&&C.roadSurf(rd)==='asphalt'&&rd.pts.some(p=>Math.hypot(p[0]-j[0],p[1]-j[1])<20)), m=dark?MAT.jDark:MAT.jLight;
    const Y=(x,z)=>HM(x,z)+.085, uv=p=>[p[0]/8,p[2]/8], k=hp.length/2, c=[0,0]; for(let i=0;i<k;i++){ c[0]+=hp[2*i]/k; c[1]+=hp[2*i+1]/k; } const cc=[c[0],Y(c[0],c[1]),c[1]];
    // a fan from the middle, each edge split so the box follows the ground
    for(let i=0;i<k;i++){ const a=[hp[2*i],0,hp[2*i+1]], b=[hp[(2*i+2)%hp.length],0,hp[(2*i+3)%hp.length]], n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[2]-a[2])/4));
      for(let q=0;q<n;q++){ const p0=[a[0]+(b[0]-a[0])*q/n,0,a[2]+(b[2]-a[2])*q/n], p1=[a[0]+(b[0]-a[0])*(q+1)/n,0,a[2]+(b[2]-a[2])*(q+1)/n]; p0[1]=Y(p0[0],p0[2]); p1[1]=Y(p1[0],p1[2]);
        const m0=[(cc[0]+p0[0])/2,0,(cc[2]+p0[2])/2], m1=[(cc[0]+p1[0])/2,0,(cc[2]+p1[2])/2]; m0[1]=Y(m0[0],m0[2]); m1[1]=Y(m1[0],m1[2]);
        RB.quad(m,m0,m1,p1,p0,uv(m0),uv(m1),uv(p1),uv(p0)); RB.tri(m,cc,m1,m0,uv(cc),uv(m1),uv(m0)); } } }
  for(const me of RB.meshes(false)){ me.userData.noInk=true; grp.add(me); }
  yield 'roads';
  // stop bars, crosswalks and lane arrows
  const flat=(x,z)=>HM(x,z)+.1;
  for(const [x1,z1,x2,z2] of rk.bars||[]){ const dx=x2-x1, dz=z2-z1, l=Math.hypot(dx,dz)||1, ax=-dz/l*.23, az=dx/l*.23; PB.quad(WHITE,[x1-ax,flat(x1-ax,z1-az),z1-az],[x2-ax,flat(x2-ax,z2-az),z2-az],[x2+ax,flat(x2+ax,z2+az),z2+az],[x1+ax,flat(x1+ax,z1+az),z1+az]); }
  for(const [x,z,yaw,len,wd] of rk.walks||[]){ const F=frame(x,0,z,yaw); for(let o=-len/2+.4;o<len/2-.3;o+=1.2){ const q=[F(o-.3,0,-wd/2),F(o+.3,0,-wd/2),F(o+.3,0,wd/2),F(o-.3,0,wd/2)]; for(const p of q) p[1]=flat(p[0],p[2]); PB.quad(WHITE,...q); } }
  const ARROW={through:[[-.15,0],[.15,0],[.15,2.6],[.45,2.6],[0,3.8],[-.45,2.6],[-.15,2.6]], left:[[-.15,0],[.15,0],[.15,2.4],[-.6,2.4],[-.6,2.75],[-1.4,2.2],[-.6,1.65],[-.6,2],[-.15,2]], slight_left:[[-.15,0],[.15,0],[.15,1.8],[-.35,2.9],[-.05,3],[-.75,3.8],[-.95,2.75],[-.65,2.85],[-.15,1.7]]};
  ARROW.right=ARROW.left.map(([a,b])=>[-a,b]).reverse(); ARROW.slight_right=ARROW.slight_left.map(([a,b])=>[-a,b]).reverse();
  for(const [x,z,yaw,t] of rk.arrows||[]){ const sh=ARROW[t]||ARROW.through, F=frame(x,0,z,yaw), W3=sh.map(([a,b])=>{ const p=F(a,0,b-1.9); p[1]=flat(p[0],p[2]); return p; });
    // arrows are simple fans from the shaft's base; their outlines are star-shaped from there
    const c=F(0,0,1.0-1.9); c[1]=flat(c[0],c[2]); for(let i=0;i<W3.length;i++) PB.tri(WHITE,c,W3[i],W3[(i+1)%W3.length]); }
  for(const me of PB.meshes(false)){ me.userData.noInk=true; grp.add(me); }
  yield 'paint';
  // ---------- signs, signals and the rest of the roadside ----------
  const B=new UB();
  const post=(F,h,w=.04)=>box(B,POST,F,0,h/2-.3,0,w,h/2+.3,w);
  for(const sg of rk.signs||[]){ const y0=heightAt(sg.x,sg.z), F=frame(sg.x,y0,sg.z,sg.y);
    if(sg.k==='stop'||sg.k==='yield'){ post(F,3.2); if(sg.k==='stop') plate(B,F,octo(.38,2.15),stopCell()); else plate(B,F,[[-.45,2.45],[0,1.67],[.45,2.45]],yieldCell());
      if(sg.all) plate(B,F,rect(.46,.15,1.6),plaqueCell('ALL WAY'));
      sg.n.forEach((nm,i)=>{ if(!nm) return; const Fb=frame(sg.x,y0,sg.z,sg.y+(i?0:Math.PI/2)), c=bladeCell(nm), yb=2.82+i*.2; plate(B,Fb,rect(.92,.15,yb),c,.012,false); plate(B,frame(sg.x,y0,sg.z,sg.y+(i?Math.PI:-Math.PI/2)),rect(.92,.15,yb),c,.012,false); box(B,METAL,Fb,0,yb+.075,0,.46,.075,.008); }); }
    else if(sg.k==='speed'){ post(F,2.6); plate(B,F,rect(.6,.75,1.75),speedCell(sg.t)); }
    else if(sg.k==='dne'){ post(F,2.4); plate(B,F,rect(.75,.75,1.5),dneCell()); }
    else if(sg.k==='gore'){ for(const x of [-.5,.5]) box(B,POST,F,x,1.2,0,.05,1.5,.05); plate(B,F,rect(1.5,1.15,1.6),greenCell('gore'+sg.t,160,120,['EXIT',sg.t||''],'','')); }
    else if(sg.k==='guide'){ for(const x of [-1.7,1.7]) box(B,POST,F,x,2.4,-.08,.11,2.7,.11); const c=greenCell('guide'+sg.t+sg.r+sg.d,384,224,[sg.t],sg.r?'EXIT '+sg.r:'',sg.d||''); plate(B,F,rect(4.6,2.7,2.6),c); }
    else if(sg.k==='shield'){ post(F,3); plate(B,F,rect(.62,.22,2.55),cardCell(sg.d)); plate(B,F,rect(.62,.62,1.88),shieldCell(sg.t)); }
    else if(sg.k==='trail'){ for(const x of [-.45,.45]) box(B,POST,F,x,1.3,0,.05,1.6,.05); plate(B,F,rect(1.3,.3,2.62),greenCell('trailn'+sg.n,192,44,[sg.n],'','')); plate(B,F,rect(.6,.22,2.32),cardCell(sg.d||'')); plate(B,F,rect(.6,.6,1.68),shieldCell(sg.t)); } }
  // mast-arm signals: pole on the far right corner, arm over the incoming lanes, heads facing the traffic (dark: there is no power)
  // the face points at the incoming traffic, so the arm reaches over the road along local -x
  for(const sg of rk.signals||[]){ const y0=heightAt(sg.x,sg.z), F=frame(sg.x,y0,sg.z,sg.y);
    tube(B,GALV,F(0,-.3,0),F(0,7.2,0),.17,8); box(B,CONC,F,0,.1,0,.42,.35,.42);
    const L=sg.L; tube(B,GALV,F(0,6.1,0),F(-L,5.9,0),.1,6); tube(B,GALV,F(0,6.9,0),F(-L*.45,6.0,0),.04,4);
    for(const h of sg.h){ const hx=-h; box(B,HEAD,F,hx,5.25,.05,.17,.5,.13); plate(B,F,[[hx-.31,4.65],[hx+.31,4.65],[hx+.31,5.85],[hx-.31,5.85]],backCell(),-.1);
      lens(B,F,hx,5.6,.19,.12,RED); lens(B,F,hx,5.25,.19,.12,AMBER); lens(B,F,hx,4.9,.19,.12,GREEN); box(B,GALV,F,hx,5.85,0,.03,.12,.03); }
    if(sg.n&&L>3.4) plate(B,F,rect(1.6,.3,6.15).map(([a,b])=>[a-Math.min(L*.5,2.2),b]),bladeCell(sg.n),.12);
    box(B,METAL,F,.1,1.1,.2,.06,.09,.04);
    tube(B,GALV,F(0,7.2,0),F(0,9.4,0),.09,6); tube(B,GALV,F(0,9.3,0),F(-2.6,9.7,0),.05,5); box(B,LAMP,F,-2.75,9.62,0,.36,.07,.17); }
  // ---------- power: poles, crossarms and insulators; wires sag between them; service drops to the houses ----------
  const W=[], wire=(a,b,sag)=>{ const n=8; let p=a; for(let q=1;q<=n;q++){ const t=q/n, c=[a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t-4*sag*t*(1-t),a[2]+(b[2]-a[2])*t]; W.push(...p,...c); p=c; } };
  // where the conductors hang on each kind of pole: [across the line, height]
  const ATT=[[[-1.6,17.2],[1.6,17.2],[-1.6,15.2],[1.6,15.2],[-1.6,13.2],[1.6,13.2],[0,20.1]],[[1.5,17.2],[-1.5,15.6],[1.5,14],[0,19.1]],[[-1,10.42],[1,10.42],[0,11.2],[.22,8.6]]];
  const att=(x,z,yaw,t,k,flip)=>{ const [o,h]=ATT[t][k], F=frame(x,heightAt(x,z),z,yaw); return F(o*flip,h,0); };
  for(const p of rk.poles||[]){ const F=frame(p.x,heightAt(p.x,p.z),p.z,p.y);
    if(p.t===2){ tube(B,WOODP,F(0,-.5,0),F(0,11.05,0),.14,7); box(B,WOODP,F,0,10.25,0,1.25,.05,.06);
      for(const [o,h] of ATT[2]) box(B,INSUL,F,o,h-.16,0,.05,.12,.05);
      if(p.tf){ tube(B,CAN,F(0,7.1,.4),F(0,8.05,.4),.28,8); box(B,CAN,F,0,7.6,.2,.06,.2,.15); }
      if(p.l!==undefined){ const L2=frame(p.x,heightAt(p.x,p.z),p.z,p.l); tube(B,GALV,L2(0,8.8,0),L2(0,9.3,2.2),.045,5); box(B,LAMP,L2,0,9.26,2.45,.17,.07,.36); } }
    else { const H=p.t===0?20.2:19.2; tube(B,POLE69,F(0,-.6,0),F(0,H,0),.32,8); tube(B,POLE69,F(0,H-.2,0),F(0,H+.3,0),.05,4);
      for(const [o,h] of ATT[p.t].slice(0,-1)) tube(B,INSUL,F(0,h,0),F(o,h,0),.07,6); }
    if(p.g!==undefined){ const top=p.t===2?F(0,9.6,0):F(0,16,0), gx=p.x+Math.sin(p.g)*6, gz=p.z+Math.cos(p.g)*6; W.push(...top,gx,heightAt(gx,gz),gz); } }
  for(const [x1,z1,y1,x2,z2,y2,t] of rk.spans||[]){ const flip=Math.cos(y1)*Math.cos(y2)+Math.sin(y1)*Math.sin(y2)<0?-1:1, span=Math.hypot(x2-x1,z2-z1);
    for(let k=0;k<ATT[t].length;k++) wire(att(x1,z1,y1,t,k,1),att(x2,z2,y2,t,k,flip),span*(t===2?.022:.03)); }
  for(const [px,pz,py,hx,hz] of rk.drops||[]){ const a=frame(px,heightAt(px,pz),pz,py)(.2,8.6,0); wire(a,[hx,heightAt(hx,hz)+3.1,hz],.35); }
  if(W.length){ const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(W,3)); const ln=new THREE.LineSegments(g,new THREE.LineBasicMaterial({color:0x26221e})); s.props.add(ln); }
  // ---------- street lights (dark) and the substation ----------
  for(const l of rk.lights||[]){ if(l.k==='sub'){ const ring=l.pts, [cx,cz]=C.centroid(ring);
      for(let k=0;k<ring.length;k++){ const a=ring[k], b=ring[(k+1)%ring.length], n=Math.max(1,Math.round(Math.hypot(b[0]-a[0],b[1]-a[1])/3)); let prev=null;
        for(let q=0;q<=n;q++){ const x=a[0]+(b[0]-a[0])*q/n, z=a[1]+(b[1]-a[1])*q/n, y=heightAt(x,z); tube(B,GALV,[x,y-.2,z],[x,y+2.4,z],.035,4); if(prev){ B.quad(MESH,[prev[0],prev[1],prev[2]],[x,y,z],[x,y+2.3,z],[prev[0],prev[1]+2.3,prev[2]]); tube(B,GALV,[prev[0],prev[1]+2.35,prev[2]],[x,y+2.35,z],.02,4); } prev=[x,y,z]; } }
      const ang=Math.atan2(ring[1][0]-ring[0][0],ring[1][1]-ring[0][1]);
      for(const [du,dv] of [[-3.5,0],[3.5,0]]){ const F=frame(cx,heightAt(cx,cz),cz,ang); box(B,TRANS,F,du,1.1,dv,1.3,1.1,1.0); for(let q=-2;q<=2;q++) box(B,TRANS,F,du+q*.5,1.0,dv+1.15,.06,.8,.15);
        for(const o of [-.6,0,.6]) tube(B,INSUL,F(du+o,2.2,dv),F(du+o,3.1,dv),.1,6); }
      const F=frame(cx,heightAt(cx,cz),cz,ang); for(const du of [-6,6]) for(const dv of [-2.5,2.5]) tube(B,GALV,F(du,-.2,dv),F(du,7,dv),.12,6); for(const du of [-6,6]) tube(B,GALV,F(du,7,-2.5),F(du,7,2.5),.1,6); tube(B,GALV,F(-6,6.5,0),F(6,6.5,0),.08,6);
      continue; }
    const y0=heightAt(l.x,l.z), F=frame(l.x,y0,l.z,l.y);
    if(l.k==='davit'){ tube(B,GALV,F(0,-.4,0),F(0,12,0),.13,8); tube(B,GALV,F(0,11.8,0),F(0,12.5,1.2),.07,6); tube(B,GALV,F(0,12.5,1.2),F(0,12.6,3),.06,6); box(B,LAMP,F,0,12.55,3.25,.2,.08,.42); box(B,CONC,F,0,.15,0,.35,.35,.35); }
    else { box(B,BRONZE,F,0,3.8,0,.08,4.3,.08); box(B,BRONZE,F,0,8.1,.35,.3,.07,.25); box(B,LENS,F,0,8.02,.35,.26,.02,.21); box(B,CONC,F,0,.25,0,.3,.45,.3); } }
  // ---------- abandoned cars ----------
  if(CK) for(const c of rk.cars||[]) CK.add(B,c,(x,z)=>HM(x,z)+.03);
  // cable median barrier: posts every 3 m, three cables
  const CB=new UB();
  for(const md of rk.medians||[]){ const pts=C.densify(md.pts,3); let prev=null; for(const [x,z] of pts){ const y=heightAt(x,z); box(CB,GALV,(a,b,c)=>[x+a,y+b,z+c],0,.35,0,.035,.45,.035);
      if(prev) for(const hgt of [.45,.6,.75]){ CB.quad(DARK,[prev[0],prev[1]+hgt,prev[2]],[x,y+hgt,z],[x,y+hgt+.03,z],[prev[0],prev[1]+hgt+.03,prev[2]]); } prev=[x,y,z]; } }
  // delineators
  for(const [x,y,z,yaw] of s.delin||[]){ const F=frame(x,y,z,yaw); box(CB,REFL,F,0,.6,0,.05,.6,.03); box(CB,REFLA,F,0,1.05,.035,.04,.08,.01); }
  s.delin=null;
  // ranch gates swung open off the drive, and cattle guards across it
  for(const [x,z,yaw,w,open] of rk.gates||[]){ const F=frame(x,heightAt(x,z),z,yaw), hw=w/2+.35;   // local x runs across the drive for(const sg2 of [-1,1]) box(B,WOOD,F,sg2*hw,.7,0,.09,1,.09);
    const hp=F(-hw,0,0), ang=open?1.75:.8, Fg=frame(hp[0],heightAt(hp[0],hp[2]),hp[2],yaw+ang), gl=Math.min(4.8,w+.4);   // swung on its hinge post
    for(const hy of [.25,.6,.95,1.25]) tube(B,PIPE,Fg(0,hy,0),Fg(gl,hy,0),.03,4); for(const gx of [0,gl/2,gl]) tube(B,PIPE,Fg(gx,.2,0),Fg(gx,1.3,0),.03,4); tube(B,PIPE,Fg(0,.25,0),Fg(gl,1.25,0),.025,4); }
  for(const [x,z,yaw,w] of rk.grids||[]){ const y=heightAt(x,z)+.07, F=frame(x,y,z,yaw), hw=w/2+.3; B.quad(DARK,F(-hw,-.04,-1.3),F(hw,-.04,-1.3),F(hw,-.04,1.3),F(-hw,-.04,1.3));
    for(let o=-1.25;o<=1.25;o+=.16) tube(B,PIPE,F(-hw,0,o),F(hw,0,o),.045,5); for(const sg2 of [-1,1]) box(B,CONC,F,sg2*(hw+.15),0,0,.15,.12,1.4); }
  // grader berms along dirt roads
  for(const q of berms){ const [a,b,c,d,e,f]=q; B.quad(BERM,a,b,c,d); B.quad(BERM,d,c,e,f); }
  if(dirty){ atlas.needsUpdate=true; dirty=false; }
  for(const me of B.meshes(true)) s.props.add(me); for(const me of CB.meshes(true)){ me.userData.noInk=true; s.props.add(me); }
  const all=[...rocks,...(s.cutRocks||[])]; if(all.length){ const rk2=new THREE.InstancedMesh(sectorGeo(SHAPES.rock,s),mat('#a39079'),all.length); const r3=C.rng(9+s.c+s.r*3);
    all.forEach(([x,y,z,sc],i)=>rk2.setMatrixAt(i,new THREE.Matrix4().compose(new THREE.Vector3(x,y-.05,z),new THREE.Quaternion().setFromEuler(new THREE.Euler(r3(),r3()*TAU,0)),new THREE.Vector3(sc*1.2,sc*.8,sc))));
    rk2.castShadow=true; s.props.add(rk2); }
  s.cutRocks=null;
  yield 'roadside';
}
return {paintGround,build,atlas};
}
root.RoadKit=RoadKit;
})(typeof self!=='undefined'?self:this);
