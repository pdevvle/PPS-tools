// ---------- Nightfall car kit: abandoned cars built from code, ink-faceted ----------
// CarKit({mat,C}).add(B,rec,ground) adds one car to a batch B (B.tri / B.quad with a material first).
// rec = [x,z,yaw,type,colour,flags,seed] as written by tools/stream/roads-bake.js; ground(x,z) gives the height.
// Flags: 1 burnt out, 2 flat tyres, 4 a wheel gone (corner on a block), 8 bonnet up, 16 glass broken,
// 32 driver's door open, 64 dusty, 128 rusty. Bodies are lofted along their length from side-profile stations.
(function(root){
function CarKit(o){
const {mat,C}=o, TAU=Math.PI*2;
// desert-faded paint: white, silver, champagne, black, oxblood, navy, olive, tan, cream, gunmetal, bronze, rust red
const PAINT=['#d9d6cf','#b3b6b8','#cbbd9f','#2c2d2f','#6f2a26','#2f4766','#4c5a3e','#b0976f','#e2dbc6','#5a5f66','#8a6a3a','#94402c'];
const hex=c=>[1,3,5].map(i=>parseInt(c.slice(i,i+2),16)), toHex=a=>'#'+a.map(v=>Math.round(Math.max(0,Math.min(255,v))).toString(16).padStart(2,'0')).join('');
const mix=(a,b,k)=>{ const A=hex(a), Bc=hex(b); return toHex(A.map((v,i)=>v+(Bc[i]-v)*k)); };
// side profiles: stations [u from the front bumper, top height]; axles, wheel radius, ride height, belt line, where the cabin is
const T={
  sedan:{L:4.8,W:1.84,R:.33,yb:.3,belt:.98,ax:[1.02,3.78],prof:[[0,.7],[.14,.82],[1.22,.95],[1.98,1.43],[3.08,1.43],[3.86,1.01],[4.66,.99],[4.8,.86]],hood:1.22,roof:[1.98,3.08],deck:3.86,bp:2.55,doors:[1.3,2.5,3.6],paintBumper:true},
  hatch:{L:4.15,W:1.76,R:.31,yb:.28,belt:.96,ax:[.86,3.38],prof:[[0,.68],[.13,.8],[.98,.92],[1.72,1.45],[3.3,1.42],[4.02,1.08],[4.15,.92]],hood:.98,roof:[1.72,3.3],deck:4.02,bp:2.35,doors:[1.05,2.3,3.25],paintBumper:true,hatch:true},
  suv:{L:4.85,W:1.94,R:.37,yb:.38,belt:1.12,ax:[1.12,3.92],prof:[[0,.86],[.15,.97],[1.08,1.1],[1.82,1.78],[4.52,1.76],[4.76,1.68],[4.85,1.05]],hood:1.08,roof:[1.82,4.52],deck:4.76,bp:2.75,doors:[1.15,2.7,3.85],paintBumper:true,rearFace:true,rails:true},
  pickup:{L:5.6,W:2.0,R:.38,yb:.42,belt:1.12,ax:[1.15,4.55],prof:[[0,.98],[.15,1.06],[1.3,1.14],[2.02,1.86],[2.92,1.86],[2.98,1.86],[3.02,1.12],[5.5,1.12],[5.6,1.08]],hood:1.3,roof:[2.02,2.92],deck:2.98,bed:[3.02,5.6],bp:2.95,doors:[1.38,2.9],chrome:true},
  van:{L:5.1,W:2.0,R:.36,yb:.38,belt:1.16,ax:[.98,4.2],prof:[[0,.98],[.14,1.06],[.72,1.18],[1.38,2.05],[4.95,2.05],[5.1,1.96]],hood:.72,roof:[1.38,4.95],deck:4.98,bp:2.1,doors:[.8,2.0,3.05,4.0],sideGlass:[1.38,2.05],rearFace:true,chrome:true}};

function add(B,rec,ground){
  const [x,z,yaw,type,ci,fl,seed]=rec, S=T[type]||T.sedan, r=C.rng(seed||1), L=S.L, W=S.W, hw0=W/2;
  const burnt=fl&1, flat=fl&2, missing=fl&4, bonnet=fl&8, broken=fl&16, door=fl&32, dusty=fl&64, rusty=fl&128;
  let paint=PAINT[ci%PAINT.length]; if(rusty) paint=mix(paint,'#7a4a2c',.25); if(dusty) paint=mix(paint,'#cdb48c',.3); if(burnt) paint='#3a3330';
  const BODY=mat(paint), LOWER=mat(burnt?'#2a2421':rusty?'#6e4127':mix(paint,'#1d1b19',.35)), TRIM=mat('#232220'), GLASS=mat(burnt?'#151311':dusty?'#4f5654':'#2b343a'), HOLE=mat('#141312'),
    CHROME=mat(burnt?'#4a3a30':'#b5b7b3'), RUST=mat('#6e4127'), LIGHT=mat('#d8dcd8'), TAIL=mat('#8a1c18'), TYRE=mat('#232120'), RIM=mat(burnt?'#5a3a28':r()<.5?'#a6a9aa':'#3a3b3c'), INSIDE=mat('#2c2723'), LINER=mat('#2e2d2b');
  // pose: the four corners sit on the ground; flats and a missing wheel drop their corner
  const fx=Math.sin(yaw), fz=Math.cos(yaw), rx=-Math.cos(yaw), rz=Math.sin(yaw);
  const XZ=(u,v)=>[x+fx*(L/2-u)+rx*v,z+fz*(L/2-u)+rz*v];
  const drop=[0,0,0,0], lost=missing?Math.floor(r()*4):-1; if(burnt) for(let i=0;i<4;i++) drop[i]=S.R*.38; if(flat) for(let i=0;i<4;i++) if(r()<.6) drop[i]=Math.max(drop[i],.09); if(lost>=0) drop[lost]=Math.max(.05,S.R-.2);
  const cor=[[S.ax[0],-hw0],[S.ax[0],hw0],[S.ax[1],-hw0],[S.ax[1],hw0]].map(([u,v],i)=>ground(...XZ(u,v))-drop[i]);
  const P=(u,v,y)=>{ const [px,pz]=XZ(u,v), a=Math.max(0,Math.min(1,(u-S.ax[0])/(S.ax[1]-S.ax[0]))), b=(v+hw0)/W, g=(cor[0]*(1-b)+cor[1]*b)*(1-a)+(cor[2]*(1-b)+cor[3]*b)*a; return [px,g+y,pz]; };
  const box=(m,u0,u1,v0,v1,y0,y1)=>{ const c=[[u0,v0],[u1,v0],[u1,v1],[u0,v1]]; for(let i=0;i<4;i++){ const [a,b]=c[i], [a2,b2]=c[(i+1)%4]; B.quad(m,P(a,b,y0),P(a2,b2,y0),P(a2,b2,y1),P(a,b,y1)); } B.quad(m,P(u0,v0,y1),P(u1,v0,y1),P(u1,v1,y1),P(u0,v1,y1)); };
  // stations: the profile plus wheel arches and the B pillar
  const topAt=u=>{ const p=S.prof; for(let i=0;i<p.length-1;i++) if(u<=p[i+1][0]) return p[i][1]+(p[i+1][1]-p[i][1])*(u-p[i][0])/((p[i+1][0]-p[i][0])||1); return p[p.length-1][1]; };
  const arch=S.R*2+.05, us=new Set(S.prof.map(p=>p[0])); for(const a of S.ax) for(const d of [-.56,-.44,-.3,.3,.44,.56]) us.add(+(a+d).toFixed(3)); us.add(S.bp-.08); us.add(S.bp+.08); for(const d of S.doors) us.add(d);
  const U=[...us].filter(u=>u>=0&&u<=L).sort((a,b)=>a-b);
  const ybAt=u=>{ for(const a of S.ax){ const d=Math.abs(u-a); if(d<.44) return arch; if(d<.56) return S.yb+(arch-S.yb)*(.56-d)/.12; } return S.yb; };
  const inBed=u=>S.bed&&u>=S.bed[0]-1e-3, cabin=u=>u>=S.roof[0]-1e-3&&u<=S.roof[1]+1e-3;
  const sec=u=>{ const top=topAt(u), belt=Math.min(S.belt,top-.02), taper=u<.5?.9+u*.2:u>L-.4?.9+(L-u)*.25:1, hw=hw0*taper, yb=ybAt(u), cab=top>belt+.2;
    if(inBed(u)){ const fl2=S.yb+.5; return [[hw*.96,yb],[hw,yb+.2],[hw,belt],[hw-.06,belt],[hw-.07,fl2],[0,fl2]]; }
    const rw=cab?hw*.8:hw*.92, crown=cab?.05:.035; return [[hw*.96,yb],[hw,yb+.2],[hw,belt],[rw,top],[rw*.5,top+crown*.8],[0,top+crown]]; };
  const SEC=U.map(sec);
  const windshield=(a,b)=>a>=S.hood-1e-3&&b<=S.roof[0]+1e-3, rearWin=(a,b)=>a>=S.roof[1]-1e-3&&b<=S.deck+1e-3&&!S.bed;
  const sideGlass=(a,b)=>{ if(S.sideGlass&&(a<S.sideGlass[0]-1e-3||b>S.sideGlass[1]+1e-3)) return false; return cabin(a)&&cabin(b)&&!(a>=S.bp-.081&&b<=S.bp+.081); };
  const brokenAt=k=>broken&&C.rng(seed+k*13)()<.45;
  const doorGap=(side,a,b)=>door&&side<0&&a>=S.doors[0]-1e-3&&b<=S.bp-.079;
  for(let i=0;i<U.length-1;i++){ const a=U[i], b=U[i+1], A=SEC[i], Bs=SEC[i+1], bedSeg=inBed(a)&&inBed(b);
    for(const side of [-1,1]){ const p=(s,k,u)=>P(u,s[k][0]*side,s[k][1]);
      for(let k=0;k<5;k++){ let m=k===0?LOWER:BODY;
        if(k===2){ if(sideGlass(a,b)) m=burnt?HOLE:brokenAt(i*2+(side>0)) ?HOLE:GLASS; if(doorGap(side,a,b)) continue; }
        if(k===1&&doorGap(side,a,b)) continue;
        if(k>=3){ if(bedSeg) m=LINER; else if(windshield(a,b)) m=burnt?HOLE:broken&&r()<.3?mat('#5d6569'):GLASS; else if(rearWin(a,b)) m=burnt||brokenAt(99)?HOLE:GLASS; if(bonnet&&b<=S.hood+1e-3) continue; }
        if(burnt&&k>=3&&m===BODY&&r()<.4) m=RUST;
        B.quad(m,p(A,k,a),p(Bs,k,b),p(Bs,k+1,b),p(A,k+1,a)); } }
    B.quad(TRIM,P(a,-A[0][0],A[0][1]),P(b,-Bs[0][0],Bs[0][1]),P(b,Bs[0][0],Bs[0][1]),P(a,A[0][0],A[0][1])); }
  // end caps: front and rear faces, fanned from the middle
  for(const [i,u] of [[0,0],[U.length-1,L]]){ const s=SEC[i], ring=[...s.map(([v,y])=>[v,y]),...s.slice().reverse().map(([v,y])=>[-v,y])], c=P(u,0,(s[0][1]+s[5][1])/2);
    for(let k=0;k<ring.length-1;k++) B.tri(BODY,c,P(u,...ring[k]),P(u,...ring[k+1])); }
  const front=-.012, rear=L+.012, bh=S.belt;
  // bumpers, grille, lamps, plates
  const bumpM=burnt?RUST:S.chrome?CHROME:S.paintBumper?BODY:TRIM;
  box(bumpM,-.06,.12,-hw0*.94,hw0*.94,S.yb+.02,S.yb+.3); box(TRIM,-.07,.1,-hw0*.9,hw0*.9,S.yb-.04,S.yb+.04);
  if(S.bed) box(BODY,L-.07,L,-hw0+.07,hw0-.07,S.yb+.48,S.belt);   // tailgate
  box(bumpM,L-.12,L+.06,-hw0*.94,hw0*.94,S.yb+.02,S.yb+.3);
  box(burnt?HOLE:TRIM,front-.01,.05,-W*.22,W*.22,S.yb+.34,Math.min(bh-.06,S.yb+.62));
  for(const sd of [-1,1]){ box(burnt?HOLE:LIGHT,front-.01,.06,sd*W*.3-.17*sd,sd*W*.3+.17*sd,bh-.3,bh-.14);
    box(burnt?HOLE:TAIL,L-.05,rear+.005,sd*hw0*.86-.16*sd,sd*hw0*.86+.04*sd,bh-.34,bh-.06); }
  box(mat('#d9d6c8'),rear-.02,rear+.02,-.16,.16,S.yb+.34,S.yb+.5);
  // mirrors, door seams and handles
  for(const sd of [-1,1]){ const mu=S.hood+.18, mv=sd*(hw0+.1); box(BODY,mu,mu+.12,mv-.06*sd,mv+.07*sd,bh+.06,bh+.22); box(TRIM,mu-.005,mu+.004,mv-.05*sd,mv+.06*sd,bh+.08,bh+.2);
    for(const d of S.doors){ if(door&&sd<0&&d===S.doors[0]) continue; const s=sec(d); B.quad(TRIM,P(d-.012,sd*(s[1][0]+.006),S.yb+.24),P(d+.012,sd*(s[1][0]+.006),S.yb+.24),P(d+.012,sd*(s[2][0]+.006),bh-.02),P(d-.012,sd*(s[2][0]+.006),bh-.02)); }
    for(let k=0;k<S.doors.length-1;k++){ const hu=S.doors[k+1]-.28; if(door&&sd<0&&k===0) continue; box(TRIM,hu,hu+.16,sd*(hw0+.005),sd*(hw0+.03),bh-.16,bh-.11); } }
  // wheels: tyre, sidewall and rim; burnt ones are bare rims, a missing one leaves the corner on a cinder block
  [[S.ax[0],-1],[S.ax[0],1],[S.ax[1],-1],[S.ax[1],1]].forEach(([u,sd],i)=>{ if(i===lost){ box(mat('#9a968e'),u-.2,u+.2,sd*(hw0-.45),sd*(hw0-.1),-.02,S.yb+.02); return; }
    const R=burnt?S.R*.62:S.R, cy=R-(flat&&drop[i]>0&&!burnt?.06:0), v0=sd*(hw0-.25), v1=sd*(hw0-.02), k=12, ring=(rad,v,t)=>P(u+Math.cos(t)*rad,v,cy+Math.sin(t)*rad);   // a flat sits on its rim
    for(let q=0;q<k;q++){ const t0=q/k*TAU, t1=(q+1)/k*TAU; if(!burnt) B.quad(TYRE,ring(S.R,v0,t0),ring(S.R,v0,t1),ring(S.R,v1,t1),ring(S.R,v1,t0));
      if(!burnt) B.quad(TYRE,ring(S.R,v1,t0),ring(S.R,v1,t1),ring(S.R*.64,v1+sd*.012,t1),ring(S.R*.64,v1+sd*.012,t0));
      B.tri(RIM,P(u,v1+sd*.03,cy),ring(S.R*.62,v1+sd*.015,t0),ring(S.R*.62,v1+sd*.015,t1));
      if(burnt) B.quad(RIM,ring(S.R*.62,v0,t0),ring(S.R*.62,v0,t1),ring(S.R*.62,v1+sd*.015,t1),ring(S.R*.62,v1+sd*.015,t0)); }   // bare rim barrels
    for(let q=0;q<5;q++){ const t=q/5*TAU; box(TRIM,u+Math.cos(t)*S.R*.3-.02,u+Math.cos(t)*S.R*.3+.02,v1+sd*.02,v1+sd*.035,cy+Math.sin(t)*S.R*.3-.02,cy+Math.sin(t)*S.R*.3+.02); } });
  // what the type carries
  if(S.rails) for(const sd of [-1,1]) box(burnt?RUST:TRIM,S.roof[0]+.25,S.roof[1]-.15,sd*hw0*.68,sd*hw0*.74,topAt(2.5)+.05,topAt(2.5)+.1);
  if(S.rearFace){ const top=topAt(L-.01); B.quad(burnt||brokenAt(7)?HOLE:GLASS,P(rear+.002,-hw0*.7,bh+.06),P(rear+.002,hw0*.7,bh+.06),P(rear+.002,hw0*.62,top-.12),P(rear+.002,-hw0*.62,top-.12)); }
  if(S.bed){ B.quad(burnt?HOLE:GLASS,P(S.bed[0]-.075,-hw0*.62,S.belt+.12),P(S.bed[0]-.075,hw0*.62,S.belt+.12),P(S.bed[0]-.075,hw0*.56,1.72),P(S.bed[0]-.075,-hw0*.56,1.72));
    B.quad(TRIM,P(L-.005,-hw0*.95,S.belt-.04),P(L-.005,hw0*.95,S.belt-.04),P(L-.005,hw0*.95,S.belt-.02),P(L-.005,-hw0*.95,S.belt-.02));
    if(r()<.6) for(let q=0;q<1+Math.floor(r()*3);q++){ const u=S.bed[0]+.4+r()*1.6, v=(r()-.5)*1.1, c=[mat('#8a6a48'),mat('#4f5a3a'),mat('#a33a2a')][Math.floor(r()*3)]; box(c,u,u+.4+r()*.3,v,v+.35+r()*.2,S.yb+.5,S.yb+.75+r()*.35); } }
  // bonnet up: the panel propped on its hinge over a dark engine bay
  if(bonnet){ const s0=sec(S.hood), h=topAt(S.hood); box(INSIDE,.3,S.hood-.05,-hw0*.8,hw0*.8,S.yb+.3,topAt(.7)-.1); const ang=1.05, L0=S.hood-.1;
    const hp=(du,v)=>{ const u=S.hood-Math.cos(ang)*du, y=h+Math.sin(ang)*du; return P(u,v,y); }; B.quad(BODY,hp(0,-s0[3][0]),hp(0,s0[3][0]),hp(L0,s0[3][0]*.95),hp(L0,-s0[3][0]*.95)); }
  // driver's door hanging open about its front hinge, the seats behind it
  if(door){ const d0=S.doors[0], d1=S.bp-.08, s=sec(d0), ang=.95, len=d1-d0, hv=-(s[1][0]);
    const dp=(du,y)=>P(d0+Math.cos(ang)*du,hv-Math.sin(ang)*du,y); B.quad(BODY,dp(0,S.yb+.2),dp(len,S.yb+.2),dp(len,S.belt),dp(0,S.belt)); B.quad(burnt?HOLE:GLASS,dp(.08,S.belt),dp(len,S.belt),dp(len*.9,S.belt+.38),dp(.25,S.belt+.38)); }
  if(door||broken||burnt){ box(INSIDE,S.hood+.45,S.roof[1]-.25,-hw0*.78,hw0*.78,S.yb+.25,S.belt+.18); }
}
return {add,TYPES:T};
}
root.CarKit=CarKit;
})(typeof self!=='undefined'?self:this);
