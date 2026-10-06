const FigureKit=(()=>{
const TAU=Math.PI*2; const ui={shade:'toon'};
const SKINS=['#f3dfb0','#efd3a8','#e6c39a','#d8ab80','#c18e64','#a87550','#8a5a3c','#6a4330'];
const HAIRS=['#1f1813','#2e2119','#4a3020','#6a4a2e','#8a6a40','#b08a52','#7a3c22','#5c5650'];
const EYES=['#4a3524','#2f2a26','#4c6a7a','#566640','#6a4a2a','#3a4a58'];
// every face is generated from a seed: proportions, features, colouring and haircut
function rng(seed){ let x=seed>>>0; x^=x>>>16; x=Math.imul(x,0x7feb352d); x^=x>>>15; x=Math.imul(x,0x846ca68b); x^=x>>>16; x=x>>>0||1; return ()=>{ x=(Math.imul(x,1664525)+1013904223)>>>0; return x/4294967296; }; }
// Heritage profiles: broad population tendencies that nudge the individual draw. Ranges overlap heavily, individual
// variation stays larger than the nudge, and about a third of people blend two profiles.
const HERITAGE={
  westAfrican:   {label:'West African',    skin:[5,7], eyes:[0,1],       hair:[0,1],   d:{noseW:.26,noseL:-.06,noseT:-.12,noseS:.04,lipU:.0016,lipL:.0018,eyeOpen:.05,eyeS:.04}},
  eastAsian:     {label:'East Asian',      skin:[0,3], eyes:[0,1],       hair:[0,1],   d:{noseW:.02,noseL:-.08,noseT:-.24,noseS:-.06,eyeOpen:-.3,fold:.9,tilt:.07,socket:-.004,brow:-.003,cheek:.002,w:.03,eyeS:-.05}},
  southAsian:    {label:'South Asian',     skin:[3,6], eyes:[0,1,4],     hair:[0,1,2], d:{noseL:.03,noseW:.06,eyeOpen:.06,eyeS:.05,lipL:.0006}},
  european:      {label:'European',        skin:[0,2], eyes:[0,1,2,3,4,5], hair:[1,2,3,4,5,6,7], d:{noseL:.05,noseT:.1,noseW:-.08,socket:.002,brow:.001}},
  middleEastern: {label:'Middle Eastern',  skin:[2,4], eyes:[0,1,4,3],   hair:[0,1,2], d:{noseL:.07,noseT:.14,noseS:.05,hump:.35,brow:.001,browT:.12}},
  indigenous:    {label:'Indigenous American', skin:[3,5], eyes:[0,1],   hair:[0,1],   d:{noseT:.06,noseL:.02,cheek:.003,eyeOpen:-.12,fold:.4,w:.03}},
};
const HKEYS=Object.keys(HERITAGE);
function genFace(seed,fem){
  const r=rng(seed*2654435761), R=(a,b)=>a+(b-a)*r(), pick=a=>a[Math.floor(r()*a.length)], k=fem?.6:1;
  // heritage: one profile, sometimes blended with a second
  const h1=pick(HKEYS), mixed=r()<.33; let h2=pick(HKEYS); if(h2===h1) h2=HKEYS[(HKEYS.indexOf(h1)+1)%HKEYS.length];
  const wt=mixed?R(.25,.5):0, H1=HERITAGE[h1], H2=HERITAGE[h2], D=k2=>(H1.d[k2]||0)*(1-wt)+(H2.d[k2]||0)*wt;
  const P={fem, heritage:mixed?`${H1.label} / ${H2.label}`:H1.label,
    w:R(.88,1.12)+D('w'), d:R(.94,1.07), len:R(.92,1.08), jaw:R(.8,1.2)*(fem?.93:1), chinFwd:R(-.01,.01), chin:R(.002,.011)*k,
    brow:Math.max(.0005,R(.002,.011)*k+D('brow')), cheek:R(.002,.011)+D('cheek'), cheekY:R(.09,.106), eyeY:R(.11,.126), eyeA:R(16,22.5), socket:Math.max(.003,R(.006,.014)+D('socket')),
    noseL:R(.84,1.14)+D('noseL'), noseW:R(.78,1.3)+D('noseW'), noseT:R(.75,1.3)+D('noseT'), noseS:R(.86,1.14)+D('noseS'), hump:r()<.2+D('hump'),
    lipU:R(.002,.0045)+(fem?.0015:0)+D('lipU'), lipL:R(.0028,.005)+(fem?.0015:0)+D('lipL'),
    mouthW:R(.9,1.15), browT:R(.8,1.25)*(fem?.8:1)+D('browT'), browArch:R(-.004,.006)+(fem?.003:0),
    eyeS:R(.82,1.2)+D('eyeS'), eyeOpen:Math.max(.5,R(.85,1.15)+D('eyeOpen')), fold:Math.min(1,Math.max(0,R(-.15,.15)+D('fold'))), tilt:R(-.03,.05)+D('tilt'),
    forehead:R(-.008,.006), ear:R(.85,1.15)};
  // colouring from the blended profile: skin index range, then eye and brow colour from the main profile
  const lo=H1.skin[0]*(1-wt)+H2.skin[0]*wt, hi=H1.skin[1]*(1-wt)+H2.skin[1]*wt, tone=Math.max(0,Math.min(SKINS.length-1,Math.round(R(lo-.4,hi+.4))));
  P.skin=SKINS[tone]; P.eye=EYES[pick(r()<wt?H2.eyes:H1.eyes)]; P.hair=HAIRS[pick(r()<wt?H2.hair:H1.hair)];
  const hs=r(); P.style=fem?(hs<.45?'bob':hs<.8?'bun':'crop'):(hs<.45?'crop':hs<.8?'buzz':'quiff');
  // body: a second random stream from the same seed
  const b=rng(seed*97+13), B=(a,c)=>a+(c-a)*b();
  P.body={head:B(.93,1.07), neck:B(.8,1.3), shoulders:fem?B(.88,1.06):B(.9,1.15), torso:B(.94,1.06), waist:B(.88,1.15), hips:fem?B(1,1.12):B(.92,1.06),
    chest:fem?0:B(0,1), breast:fem?B(0,1):0, glutes:B(0,1), legs:B(.92,1.08), knee:B(.94,1.06), arms:B(.95,1.05), girth:B(.85,1.2), muscle:fem?B(0,.75):B(.15,1)};
  for(const key in P.body) P.body[key]=Math.round(P.body[key]*1000)/1000;
  for(const key in P) if(typeof P[key]==='number') P[key]=Math.round(P[key]*10000)/10000;
  return P; }
// ---------- geometry: low-sided lofts (stacked cross-sections; front of any texture is its horizontal centre) ----------
const GC={}; const geo=(k,fn)=>GC[k]||(GC[k]=fn());
function loft(k,rings,seg){ return geo(k,()=>{
  rings=rings.slice().sort((a,b)=>a[0]-b[0]);
  const pos=[],uv=[],idx=[], y0=rings[0][0], y1=rings[rings.length-1][0], pw=(v,n)=>Math.sign(v)*Math.pow(Math.abs(v),2/n);
  rings.forEach(([y,w,d,cz=0,n=2])=>{ for(let i=0;i<=seg;i++){ const a=i/seg*TAU+Math.PI; pos.push(w*pw(Math.sin(a),n),y,cz+d*pw(Math.cos(a),n)); uv.push(i/seg,(y-y0)/(y1-y0)); } });
  for(let j=0;j<rings.length-1;j++) for(let i=0;i<seg;i++){ const a=j*(seg+1)+i,b=a+seg+1; idx.push(a,a+1,b,a+1,b+1,b); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2)); g.setIndex(idx); g.computeVertexNormals();
  return g; }); }
const smooth=t=>t<0?0:t>1?1:t*t*(3-2*t), gauss=(x,m,s)=>Math.exp(-((x-m)**2)/(2*s*s));
// a loft with soft lobes pushed out of its surface: used for the bust, pecs and glutes so they stay round, not pointed
function loftLobes(k,rings,seg,extraY,lobes){ return geo(k,()=>{
  rings=rings.slice().sort((a,b)=>a[0]-b[0]);
  const at=y=>{ for(let i=0;i<rings.length-1;i++){ const A=rings[i],B=rings[i+1]; if(y<=B[0]){ const t=(y-A[0])/(B[0]-A[0]); return A.map((v,j)=>j===0?y:(v??(j===3?0:2))+(((B[j]??(j===3?0:2)))-(v??(j===3?0:2)))*t); } } return rings[rings.length-1]; };
  const ys=[...new Set([...rings.map(r=>r[0]),...extraY])].sort((a,b)=>a-b), R=ys.map(at);
  const pos=[],uv=[],idx=[], y0=ys[0], y1=ys[ys.length-1], pw=(v,n)=>Math.sign(v)*Math.pow(Math.abs(v),2/n);
  R.forEach(([y,w,d,cz=0,n=2])=>{ for(let i=0;i<=seg;i++){ const a=i/seg*TAU+Math.PI, sx=Math.sin(a), cz2=Math.cos(a), x=w*pw(sx,n), z=cz+d*pw(cz2,n), ang=Math.atan2(sx,cz2);
    let push=0; for(const L of lobes){ const da=Math.atan2(Math.sin(ang-L.a),Math.cos(ang-L.a)), r2=(da/L.sa)**2+((y-L.y)/L.sy)**2; if(r2<1) push+=L.amp*Math.pow(1-r2,1.6); }
    const l=Math.hypot(x,z-cz)||1; pos.push(x+x/l*push,y,z+(z-cz)/l*push); uv.push(i/seg,(y-y0)/(y1-y0)); } });
  for(let j=0;j<R.length-1;j++) for(let i=0;i<seg;i++){ const a=j*(seg+1)+i,b=a+seg+1; idx.push(a,a+1,b,a+1,b+1,b); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2)); g.setIndex(idx); g.computeVertexNormals();
  return g; }); }
function bodyShape(fem,Bd){ const F=shape(fem), k='b'+fem+JSON.stringify(Bd);
  const torsoRings=F.torsoRings.map(([y,w,d,cz=0,n=2])=>{
    const hipF=Bd.hips*Bd.girth, waistF=Bd.waist*Bd.girth, shF=Bd.shoulders;
    const wf=hipF+(waistF-hipF)*smooth((y-.04)/.12), wf2=wf+(shF-wf)*smooth((y-.24)/.14);
    return [y*Bd.torso, w*wf2, d*Bd.girth, cz, n]; });
  const pelvisRings=F.pelvisRings.map(([y,w,d,cz=0,n=2])=>[y, w*Bd.hips*Bd.girth, d*Bd.girth, cz, n]);
  const T=Bd.torso, side=s=>s*.5;
  // lobes: a = angle from the front (radians), y = centre height, sa/sy = spread, amp = how far out (metres)
  const chestLobes=fem
    ? [-1,1].map(s=>({a:side(s)*1.0,y:.285*T,sa:.62,sy:.055,amp:.006+Bd.breast*.03}))
    : [-1,1].map(s=>({a:side(s)*1.05,y:.325*T,sa:.75,sy:.05,amp:Bd.chest*.014}));
  const gluteLobes=[-1,1].map(s=>({a:Math.PI+side(s)*.95,y:fem?-.065:-.075,sa:.7,sy:.06,amp:.004+Bd.glutes*.022}));
  const tY=[.1,.13,.16,.19,.2,.23,.25,.27,.29,.31,.33,.35,.43,.45].map(y=>y*T), pY=[-.14,-.11,-.09,-.07,-.05,-.03,-.01,.02];
  const m=Math.round(Bd.muscle*20)/20, mk=fem+'_'+m, base=(.35+m)*1.4;   // a little shape even at low tone
  torsoLobesExtra(chestLobes,T,m);
  const limb=(name,lobes,extra)=>loftLobes('M'+name+mk,F.rings[name],8,extra,lobes.map(L=>Object.assign({},L,{amp:L.amp*base})));
  return Object.assign({},F,{torso:loftLobes('T'+k,torsoRings,12,tY,chestLobes), pelvis:loftLobes('P'+k,pelvisRings,12,pY,gluteLobes),
    upperArm:limb('upperArm',[{a:0,y:-.14,sa:1.0,sy:.09,amp:.008},{a:Math.PI,y:-.1,sa:1.1,sy:.1,amp:.007},{a:Math.PI/2,y:-.03,sa:1.3,sy:.05,amp:.004},{a:-Math.PI/2,y:-.03,sa:1.3,sy:.05,amp:.004}],[-.24,-.2,-.16,-.12,-.06,-.04]),
    forearm:limb('forearm',[{a:.35,y:-.06,sa:1.1,sy:.07,amp:.006},{a:Math.PI,y:-.07,sa:1.2,sy:.08,amp:.004}],[-.02,-.08,-.16]),
    thigh:limb('thigh',[{a:0,y:-.2,sa:1.0,sy:.14,amp:.011},{a:0,y:-.35,sa:.7,sy:.05,amp:.005},{a:Math.PI,y:-.18,sa:1.0,sy:.13,amp:.009}],[-.05,-.08,-.18,-.22,-.31,-.34]),
    shin:limb('shin',[{a:Math.PI,y:-.11,sa:.95,sy:.08,amp:.011},{a:.45,y:-.08,sa:.5,sy:.07,amp:.003}],[-.03,-.09,-.17,-.26])}); }
// traps on the upper back and a hint of abs, scaled by muscle tone
function torsoLobesExtra(list,T,m){ list.push({a:Math.PI,y:.44*T,sa:.9,sy:.045,amp:.002+m*.008},{a:0,y:.16*T,sa:.45,sy:.08,amp:m*.004},{a:Math.PI,y:.3*T,sa:.8,sy:.08,amp:m*.004}); }
function shape(fem){ const f=fem?.88:1, h=fem?1.08:1, k='f'+fem; const TR=[[-.01,.124*h,.086],[.06,.118*(fem?.92:1),.084],[.14,.128*(fem?.95:1),.09,.004],[.22,.148*f,.1,.012],[.28,.162*f,fem?.104:.108,fem?.014:.02],[.335,.172*f,fem?.1:.1,.012],[.37,.184*f,.094,.008],[.395,.19*f,.086,.002],[.418,.172*f,.075,-.004],[.442,.13*f,.065,-.006],[.462,.088*f,.058,-.008],[.48,.06,.052,-.008]], PR=[[-.18,.03,.034,.004],[-.16,.08*h,.07,.004],[-.12,.13*h,.088],[-.06,.14*h,.095,-.006],[0,.135*h,.09],[.04,.126*h,.087]]; const RG={}, L=(n,kk,r,sg)=>{ RG[n]=r; return loft(kk,r,sg); }; return { rings:RG, torsoRings:TR, pelvisRings:PR,
  torso:loft('t'+k,[[-.01,.124*h,.086],[.06,.118*(fem?.92:1),.084],[.14,.128*(fem?.95:1),.09,.004],[.22,.148*f,.1,.012],[.28,.162*f,fem?.104:.108,fem?.014:.02],[.335,.172*f,fem?.1:.1,.012],[.37,.184*f,.094,.008],[.395,.19*f,.086,.002],[.418,.172*f,.075,-.004],[.442,.13*f,.065,-.006],[.462,.088*f,.058,-.008],[.48,.06,.052,-.008]],7),
  pelvis:loft('p'+k,[[-.18,.03,.034,.004],[-.16,.08*h,.07,.004],[-.12,.13*h,.088],[-.06,.14*h,.095,-.006],[0,.135*h,.09],[.04,.126*h,.087]],7),
  neck:loft('n'+k,[[0,.078*f,.066,-.006,2.5],[.05,.067*f,.061,-.006,2.5],[.1,.062*f,.059,-.006,2.5],[.15,.058*f,.057,-.008,2.5],[.2,.054*f,.055,-.012,2.5],[.215,.03,.03,-.012]],6),
  upperArm:L('upperArm','u'+k,[[-.3,.03,.03],[-.28,.038*f,.04],[-.18,.043*f,.047,.003],[-.08,.046*f,.05],[-.02,.048*f,.05],[.012,.042*f,.046],[.026,.026,.032],[.032,.004,.006]],5),
  forearm:L('forearm','f'+k,[[.03,.02,.02],[.015,.04*f,.04],[-.04,.046*f,.045],[-.12,.038*f,.036],[-.22,.028*f,.024],[-.245,.026*f,.022],[-.255,.012,.012]],5),
  hand:loft('h'+k,[[-.19,.006,.015],[-.16,.011,.028],[-.09,.014,.04*f],[-.03,.016,.042*f],[.005,.014,.03],[.015,.008,.015]],4),
  thigh:L('thigh','g'+k,[[.06,.03,.03],[.04,.064*h,.066],[0,.076*h,.08,.004],[-.12,.074*h,.078,.008],[-.26,.066,.07,.006],[-.37,.052,.055,.004],[-.42,.046,.048],[-.44,.025,.025]],6),
  shin:L('shin','s'+k,[[.035,.026,.026],[.01,.047,.05],[-.06,.05*f,.056,-.008],[-.14,.048*f,.055,-.012],[-.22,.038,.042,-.006],[-.33,.028,.028],[-.38,.025,.025],[-.4,.016,.016]],5),
  foot:loft('o'+k,[[-.11,.012,.016],[-.09,.03,.026,0,2.4],[-.01,.036*f,.03,0,2.6],[.07,.04*f,.024,0,2.6],[.11,.034*f,.016,0,2.4],[.13,.012,.008]],4),
  head:loft('d'+k,[
    [0,.034*f,.022,.062,3],       // underside of the chin: broad and flat
    [.016,.046*f,.032,.06,3],     // chin
    [.042,.064*f,.066,.038,2.8],  // angle of the jaw
    [.07,.07*f,.083,.024,2.8],    // mouth
    [.095,.072*f,.09,.016,2.8],   // under the nose
    [.12,.074*f,.092,.012,2.8],   // cheekbones
    [.145,.074*f,.087,.01,2.8],   // eye line, set back under the brow
    [.162,.077*f,.096,.008,2.8],  // brow ridge
    [.2,.076*f,.095,.004,2.8],    // tall, flat forehead
    [.226,.068*f,.088,-.002,2.6],
    [.244,.048*f,.064,-.006,2.4],
    [.254,.018,.024,-.008],[.256,.002,.002,-.008]].map(r=>fem?[r[0]*.97,r[1]*(r[0]<.1?.93:1),...r.slice(2)]:r),7),
}; }
function hairBlock(k,edge,rings){ return geo(k,()=>{
  // the bottom edge height depends on the angle round the head: fringe at the front, in front of the ears, then down to the nape
  const seg=8, pos=[], idx=[], pw=(v,n)=>Math.sign(v)*Math.pow(Math.abs(v),2/n);
  const all=[[null,...rings[0].slice(1)],...rings];
  all.forEach(([y,w,d,cz=0,n=2],j)=>{ for(let i=0;i<=seg;i++){ const a=i/seg*TAU+Math.PI, c=Math.cos(a);
    const yy = j===0 ? (c>.6?edge[0]: c>-.1?edge[1]: c>-.8?edge[2]:edge[3]) : y; pos.push(w*pw(Math.sin(a),n),yy,cz+d*pw(c,n)); } });
  for(let j=0;j<all.length-1;j++) for(let i=0;i<seg;i++){ const a=j*(seg+1)+i,b=a+seg+1; idx.push(a,a+1,b,a+1,b+1,b); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.setIndex(idx); g.computeVertexNormals(); return g; }); }
const capG=hairBlock('hairM',[.192,.142,.1,.07],[[.198,.081,.106,.006,2.5],[.214,.078,.103,.004,2.5],[.227,.066,.09,0,2.3],[.236,.044,.064,-.006,2.2],[.242,.012,.018,-.01],[.2435,.002,.002,-.01]]);
const buzzG=hairBlock('hairB',[.188,.14,.1,.065],[[.194,.0775,.102,.005,2.5],[.212,.0755,.099,.003,2.5],[.226,.063,.087,-.001,2.3],[.235,.041,.061,-.006,2.2],[.24,.012,.018,-.01],[.241,.002,.002,-.01]]);
const bobG=hairBlock('hairF',[.19,.05,.04,.03],[[.196,.082,.106,.004,2.5],[.214,.079,.103,.002,2.5],[.227,.067,.09,-.002,2.3],[.236,.045,.065,-.006,2.2],[.242,.012,.018,-.01],[.2435,.002,.002,-.01]]);
// a bare foot: narrow round heel, high ankle and instep, a raised arch on the inner side, the ball as the widest part,
// and toes that slope back from the big toe to the little toe. Origin at the ankle, toe toward +z; side -1 = right foot, +1 = left.
function footG(fem,side){ return geo('foot'+fem+side,()=>{
  const f=fem?.9:1, sole=-.062;
  // [z, half-width, height, arch lift on the inner bottom edge, how far the outer toe edge pulls back]
  const S=[[-.052,.018,.028,0,0],[-.044,.025,.048,0,0],[-.025,.028,.064,0,0],[.005,.03,.068,.004,0],[.04,.034,.05,.009,0],[.075,.04,.034,.006,0],[.1,.043,.025,0,0],[.122,.041,.019,0,.008],[.142,.035,.014,0,.016],[.153,.022,.009,0,.022]];
  const ring=([z,hw,top,arch,pull])=>{ const inner=-side, pts=[[-hw,0],[hw,0],[hw*1.03,top*.45],[hw*.7,top],[-hw*.7,top],[-hw*1.03,top*.45]];
    return pts.map(([x,y])=>{ const isInner=Math.sign(x)===inner, yy=(y===0&&isInner)?arch:y, zz=z-(Math.sign(x)===-inner?pull:0); return [x*f,sole+yy,zz*f]; }); };
  const R=S.map(ring), n=6, pos=[], tri=(a,b,c)=>pos.push(...a,...b,...c);
  for(let j=0;j<R.length-1;j++) for(let i=0;i<n;i++){ const a=R[j][i], b=R[j][(i+1)%n], c=R[j+1][(i+1)%n], d=R[j+1][i]; tri(a,b,c); tri(a,c,d); }
  for(const [rr,flip] of [[R[0],true],[R[R.length-1],false]]) for(let i=1;i<n-1;i++) flip?tri(rr[0],rr[i+1],rr[i]):tri(rr[0],rr[i],rr[i+1]);
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.computeVertexNormals(); return g; }); }
const jointG=geo('joint',()=>new THREE.SphereGeometry(1,5,3));   // a chunky faceted block at each joint
const earG=geo('ear',()=>new THREE.SphereGeometry(1,6,4));
function sculptHead(F){ return geo('sculpt'+JSON.stringify(F),()=>{
  const prof=[[0,.02,.015,.066],[.008,.034,.03,.062],[.025,.05,.06,.045],[.045,.062,.08,.03],[.065,.068,.09,.02],[.09,.072,.096,.012],[.115,.074,.098,.008],[.135,.076,.1,.006],[.16,.077,.101,.003],[.185,.075,.1,0],[.205,.068,.094,-.004],[.222,.055,.08,-.008],[.233,.035,.055,-.01],[.238,.01,.015,-.012],[.2395,.001,.001,-.012]];
  const at=y=>{ for(let i=0;i<prof.length-1;i++){ const a=prof[i],b=prof[i+1]; if(y<=b[0]){ const t=(y-a[0])/(b[0]-a[0]); return [a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t,a[3]+(b[3]-a[3])*t]; } } return prof[prof.length-1].slice(1); };
  const ys=[0,.008,.016,.025,.033,.04,.046,.052,.058,.065,.072,.08,.088,.096,.104,.112,.12,.128,.136,.145,.155,.165,.175,.187,.2,.212,.222,.23,.235,.2385,.2395];
  const seg=24, n=2.3, G=(x,m,sg)=>Math.exp(-((x-m)*(x-m))/(2*sg*sg)), sm=t=>t<0?0:t>1?1:t*t*(3-2*t);
  const disp=(adeg,y)=>{ const A=Math.abs(adeg); return 0
    -F.socket*G(A,F.eyeA,8)*G(y,F.eyeY,.011)              // eye sockets
    +F.brow*G(A,F.eyeA-5,16)*G(y,F.eyeY+.019,.007)        // brow ridge
    +.004*G(A,0,8)*G(y,.104,.022)                         // bridge of the nose
    +F.cheek*G(A,38,12)*G(y,F.cheekY,.012)                // cheekbones
    -.005*G(A,48,12)*G(y,.062,.013)                       // cheek hollows
    +.006*G(A,0,22*F.mouthW)*G(y,.054,.016)               // the mouth's forward curve over the teeth
    +F.lipU*G(A,0,11*F.mouthW)*G(y,.058,.004)             // upper lip
    -.003*G(A,0,12*F.mouthW)*G(y,.051,.0035)              // line of the mouth
    +F.lipL*G(A,0,11*F.mouthW)*G(y,.045,.004)             // lower lip
    -.003*G(A,0,12)*G(y,.034,.004)                        // fold under the lower lip
    +F.chin*G(A,0,15)*G(y,.016,.009)                      // chin
    -.004*G(A,68,12)*G(y,.155,.02)                        // temples
    +.004*(F.jaw-.8)*G(A,74,10)*G(y,.032,.012); };        // angle of the jaw
  const pos=[],uv=[],idx=[], pw=v=>Math.sign(v)*Math.pow(Math.abs(v),2/n);
  ys.forEach(y=>{ let [w,d,cz]=at(y);
    w*=F.w*(1+(F.jaw-1)*sm(1-y/.085)); d*=F.d;                                  // overall width and depth; jaw width fades out above the mouth
    cz+=F.chinFwd*sm(1-y/.04)+F.forehead*sm((y-.16)/.08);                       // chin projection and forehead slope
    for(let i=0;i<=seg;i++){ const a=i/seg*TAU+Math.PI, x=w*pw(Math.sin(a)), z=d*pw(Math.cos(a)), l=Math.hypot(x,z)||1, dd=disp((i/seg-.5)*360,y);
      pos.push(x+x/l*dd, y, cz+z+z/l*dd); uv.push(i/seg, y/.2395); } });
  for(let j=0;j<ys.length-1;j++) for(let i=0;i<seg;i++){ const a=j*(seg+1)+i,b=a+seg+1; idx.push(a,a+1,b,a+1,b+1,b); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(pos,3)); g.setAttribute('uv',new THREE.Float32BufferAttribute(uv,2)); g.setIndex(idx); g.computeVertexNormals(); return g; }); }
const noseFor=F=>geo('nose'+[F.noseL,F.noseW,F.noseT,F.hump,F.eyeY].join(),()=>{
  // bridge, tip and nostril wings as separate planes; local z is measured from the face surface
  const root=F.eyeY+.012, Y=y=>root-(root-y)*F.noseL, Xw=x=>x*F.noseW, Zt=z=>z*F.noseT;
  const R=[0,Y(.13),-.004], Mb=[0,Y(.105),Zt(.011)+(F.hump?.004:0)], T=[0,Y(.084),Zt(.024)], U=[0,Y(.077),Zt(.018)], B=[0,Y(.073),.004];
  const TL=[Xw(-.009),Y(.124),-.006], TR=[Xw(.009),Y(.124),-.006], ML=[Xw(-.011),Y(.1),.003], MR=[Xw(.011),Y(.1),.003], AL=[Xw(-.016),Y(.078),-.002], AR=[Xw(.016),Y(.078),-.002];
  const tris=[[TL,R,Mb],[R,TR,Mb],[TL,Mb,ML],[ML,Mb,T],[ML,T,AL],[AL,T,U],[AL,U,B],[TR,MR,Mb],[MR,T,Mb],[MR,AR,T],[AR,U,T],[AR,B,U]];
  const A=new THREE.Vector3(),Bv=new THREE.Vector3(),C=new THREE.Vector3(), inside=new THREE.Vector3(0,.1,-.03), out=[];
  for(const t of tris){ A.fromArray(t[0]); Bv.fromArray(t[1]); C.fromArray(t[2]);
    const nn=Bv.clone().sub(A).cross(C.clone().sub(A)), c=A.clone().add(Bv).add(C).multiplyScalar(1/3);
    out.push(...(nn.dot(c.sub(inside))<0?[t[0],t[2],t[1]]:t)); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(out.flat(),3)); g.computeVertexNormals(); return g; });
const noseOld=geo('nose2',()=>{
  const tl=[-.008,.15,-.004], tr=[.008,.15,-.004], tip=[0,.092,.034], bl=[-.018,.086,.002], br=[.018,.086,.002], bm=[0,.084,.014];
  const tris=[[tl,tip,bl],[tr,br,tip],[tl,tr,tip],[bl,tip,bm],[bm,tip,br]];
  const A=new THREE.Vector3(),B=new THREE.Vector3(),C=new THREE.Vector3(), inside=new THREE.Vector3(0,.12,-.03), out=[];
  for(const t of tris){ A.fromArray(t[0]); B.fromArray(t[1]); C.fromArray(t[2]);
    const n=B.clone().sub(A).cross(C.clone().sub(A)), c=A.clone().add(B).add(C).multiplyScalar(1/3);
    out.push(...(n.dot(c.sub(inside))<0 ? [t[0],t[2],t[1]] : t)); }
  const g=new THREE.BufferGeometry(); g.setAttribute('position',new THREE.Float32BufferAttribute(out.flat(),3)); g.computeVertexNormals(); return g; });

// ---------- materials: solid colours; only the face and underwear bands use tiny textures ----------
const mats=[];
const RAMP=(()=>{ const t=new THREE.DataTexture(new Uint8Array([40,40,40, 140,140,140, 255,255,255]),3,1,THREE.RGBFormat); t.minFilter=t.magFilter=THREE.NearestFilter; t.generateMipmaps=false; t.needsUpdate=true; return t; })();
const ramp=v=>{ const d=new Uint8Array(v.length*3); v.forEach((x,i)=>d.set([x,x,x],i*3)); const t=new THREE.DataTexture(d,v.length,1,THREE.RGBFormat); t.minFilter=t.magFilter=THREE.NearestFilter; t.generateMipmaps=false; t.needsUpdate=true; return t; };
const RAMPS={toon:RAMP, ink:RAMP, two:ramp([70,255]), painted:ramp([70,125,185,255])};
const M=o=>{ const m = RAMPS[ui.shade] ? new THREE.MeshToonMaterial(Object.assign({gradientMap:RAMPS[ui.shade], flatShading:true},o))
                                        : new THREE.MeshStandardMaterial(Object.assign({roughness:.85, metalness:0, flatShading:ui.shade==='flat'||ui.shade==='inkfacet'},o)); mats.push(m); return m; };
function tex(w,h,paint){ const c=document.createElement('canvas'); c.width=w; c.height=h; paint(c.getContext('2d'),w,h); const t=new THREE.CanvasTexture(c); t.magFilter=THREE.LinearFilter; return t; }
const UNDER='#5b504d', BAND='#3c3433';
function faceTex(F){ return tex(512,256,(g,w,h)=>{
  const skin=F.skin, fem=F.fem; g.fillStyle=skin; g.fillRect(0,0,w,h);
  const cx=w/2, Y=m=>(1-m/.2395)*h, X=f=>cx+f*w, eu=F.eyeA/360, by=F.eyeY+.019;
  const sk=new THREE.Color(skin), mix=(c,t,a)=>{ const o=sk.clone().lerp(new THREE.Color(c),t); return `rgba(${o.r*255|0},${o.g*255|0},${o.b*255|0},${a})`; };
  for(const s of [-1,1]){
    const t=.004*F.browT;
    g.fillStyle=mix(F.hair,.78,.92); g.beginPath();
    g.moveTo(X(s*(eu-.03)),Y(by-.002)); g.quadraticCurveTo(X(s*eu),Y(by+F.browArch+t*.6),X(s*(eu+.034)),Y(by-.003));
    g.lineTo(X(s*(eu+.032)),Y(by-.005)); g.quadraticCurveTo(X(s*eu),Y(by+F.browArch-t),X(s*(eu-.03)),Y(by-.002-t*1.4)); g.closePath(); g.fill();
    const ex=X(s*eu), ey=Y(F.eyeY), ew=w*.02*F.eyeS, eh=h*.012*F.eyeS*F.eyeOpen;
    g.save(); g.translate(ex,ey); g.rotate(-s*F.tilt); g.translate(-ex,-ey);   // canthal tilt: outer corners up
    g.fillStyle=mix('#000',.35,.35*(1-F.fold*.6)); g.beginPath(); g.ellipse(ex,ey-eh*1.2,ew*1.05,eh*.9,0,0,TAU); g.fill();
    g.fillStyle='#ece6dc'; g.beginPath(); g.moveTo(ex-ew,ey); g.quadraticCurveTo(ex,ey-eh*1.3,ex+ew,ey); g.quadraticCurveTo(ex,ey+eh*1.1,ex-ew,ey); g.fill();
    g.fillStyle=F.eye; g.beginPath(); g.arc(ex+s,ey,eh*.85,0,TAU); g.fill();
    g.fillStyle='#161210'; g.beginPath(); g.arc(ex+s,ey,eh*.38,0,TAU); g.fill();
    g.strokeStyle='rgba(40,26,18,.95)'; g.lineWidth=fem?2.2:1.8; g.beginPath(); g.moveTo(ex-ew,ey); g.quadraticCurveTo(ex,ey-eh*1.35,ex+ew,ey+.5); g.stroke();
    // lid crease above the eye; a fuller lid fold hides it and narrows the visible eye
    if(F.fold<.6){ g.strokeStyle=mix('#2a1a12',.5,.5*(1-F.fold/.6)); g.lineWidth=1; g.beginPath(); g.moveTo(ex-ew*.8,ey-eh*1.25); g.quadraticCurveTo(ex,ey-eh*2.2,ex+ew*.9,ey-eh*1.1); g.stroke(); }
    g.restore();
  }
  const mw=F.mouthW;
  g.fillStyle=mix(fem?'#b04a44':'#a0574a',fem?.38:.25,1);
  g.beginPath(); g.ellipse(cx,Y(.058),w*.026*mw,h*.006+F.lipU*h*1.6,0,0,TAU); g.fill();
  g.beginPath(); g.ellipse(cx,Y(.046),w*.024*mw,h*.006+F.lipL*h*1.6,0,0,TAU); g.fill();
  g.strokeStyle=mix('#3a1810',.6,.9); g.lineWidth=1.6; g.beginPath(); g.moveTo(cx-w*.027*mw,Y(.0515)); g.quadraticCurveTo(cx,Y(.0505),cx+w*.027*mw,Y(.0515)); g.stroke();
}); }
function bandTex(skin,stops){ return tex(4,64,(g,w,h)=>{ g.fillStyle=skin; g.fillRect(0,0,w,h); for(const [a,b,c] of stops){ g.fillStyle=c; g.fillRect(0,(1-b)*h,w,(b-a)*h); } }); }

// ---------- figure ----------
function Gp(p,x=0,y=0,z=0){ const g=new THREE.Group(); g.position.set(x,y,z); p.add(g); return g; }
function P(g,m,p,x=0,y=0,z=0,sx=1,sy=1,sz=1,rx=0,ry=0,rz=0){ const me=new THREE.Mesh(g,m); me.position.set(x,y,z); me.scale.set(sx,sy,sz); me.rotation.set(rx,ry,rz); me.castShadow=true; me.receiveShadow=true; p.add(me); return me; }
function figure(fem,FP){
  const Bd=FP.body, F=bodyShape(fem,Bd), sx=(fem?.175:.192)*Bd.shoulders, skin=FP.skin, hair=FP.hair, gi=Bd.girth;
  const ts=Bd.legs*(2-Bd.knee), ss=Bd.legs*Bd.knee, tl=Bd.torso;   // thigh and shin scale: knee height splits the leg
  const skinM=M({color:skin}), underM=M({color:UNDER});
  const root=new THREE.Group(), body=Gp(root), hips=Gp(body,0,.08+.42*ts+.39*ss+.062,0);
  P(F.pelvis,underM,hips);
  const torso=Gp(hips,0,.05,0);
  P(F.torso,fem?M({map:bandTex(skin,[[.5,.72,UNDER],[.5,.53,BAND]])}):skinM,torso);
  P(F.neck,skinM,torso,0,.43*tl,-.004,(1+gi)/2,Bd.neck,(1+gi)/2);
  const head=Gp(torso,0,.43*tl+.12*Bd.neck,.008), face=Gp(head,0,-.01,0); head.scale.setScalar(Bd.head);
  face.scale.set(fem?.95:1,(fem?.97:1)*FP.len,fem?.97:1);
  P(sculptHead(FP),M({map:faceTex(FP)}),face);
  P(noseFor(FP),skinM,face,0,(FP.eyeY+.012)*(1-FP.noseS),.112*FP.d,(fem?.85:1)*FP.noseS,(fem?.94:1)*FP.noseS,(fem?.85:1)*FP.noseS);   // scaled about the bridge
  for(const s of [-1,1]) P(earG,skinM,face,s*.075*FP.w,FP.eyeY-.012,-.016,.008*FP.ear,.03*FP.ear,.018*FP.ear,-.12,s*.2,0);
  // no hair on the base figure: hair length and style will be a procedural layer, like clothing
  const sh=[],el=[],lg=[],kn=[];
  for(const s of [-1,1]){
    const shoulder=Gp(torso,s*sx,.385*tl,-.006); P(F.upperArm,skinM,shoulder,0,0,0,gi,Bd.arms,gi);
    const elbow=Gp(shoulder,0,-.3*Bd.arms,0); P(F.forearm,skinM,elbow,0,0,0,gi,Bd.arms,gi); P(jointG,skinM,elbow,0,0,0,.042,.04,.042);   // elbow
    const hand=Gp(elbow,0,-.25*Bd.arms,0); P(F.hand,skinM,hand,0,0,.004); P(jointG,skinM,hand,0,.004,0,.024,.02,.026);   // wrist
    P(loft('thumb',[[-.05,.008,.008],[-.025,.011,.011],[0,.012,.012],[.006,.004,.004]],6),skinM,hand,s*-.006,-.03,.036,1,1,1,-.25,0,s*.3);
    sh.push(shoulder); el.push(elbow);
  }
  const thighM=M({map:bandTex(skin,[[fem?.92:.5,1,UNDER]])});
  for(const s of [-1,1]){
    const leg=Gp(hips,s*(fem?.082:.078)*Bd.hips,-.08,0); P(F.thigh,thighM,leg,0,0,0,gi,ts,gi);
    const knee=Gp(leg,0,-.42*ts,0); P(F.shin,skinM,knee,0,0,0,gi,ss,gi); P(jointG,skinM,knee,0,.005,.006,.05,.052,.054);   // knee
    P(footG(fem,s),skinM,knee,0,-.39*ss,0); P(jointG,skinM,knee,0,-.39*ss+.004,-.004,.024,.026,.028);   // foot, ankle
    lg.push(leg); kn.push(knee); }
  return {root, body, hips, torso, head, sh, el, lg, kn, j:null, t0:Math.random()*10, fem, FP};
}
// ---------- ink: outline shells and creases ----------
// The outline is a back-facing shell pushed out along the normal in view space. With persp, the push grows with distance
// so the stroke keeps the same width on screen (used in the 3D sectors); without it the width is fixed in metres.
function makeInk(color,width,persp){ const m=new THREE.MeshBasicMaterial({color, side:THREE.BackSide});
  m.onBeforeCompile=sh=>{ sh.vertexShader=sh.vertexShader.replace('#include <project_vertex>',
    `vec4 mvPosition=vec4(transformed,1.0); vec3 nn=normal;
     #ifdef USE_INSTANCING
       mvPosition=instanceMatrix*mvPosition; nn=mat3(instanceMatrix)*nn;
     #endif
     mvPosition=modelViewMatrix*mvPosition; mvPosition.xyz+=normalize(normalMatrix*nn)*${width.toFixed(5)}*${persp?'(-mvPosition.z)':'1.0'};
     gl_Position=projectionMatrix*mvPosition;`); };
  m.customProgramCacheKey=()=>'ink'+width+persp; return m; }
const creaseCache=new Map();
function inkUp(root,{color=0x1d1814,width=.0072,persp=false,creases=false,creaseColor=0x2a211b}={}){
  const mat=makeInk(color,width,persp), cm=creases?new THREE.LineBasicMaterial({color:creaseColor, transparent:true, opacity:.55}):null, list=[];
  root.traverse(o=>{ if(o.isMesh && !o.userData.ink && !o.userData.noInk) list.push(o); });
  for(const o of list){ const sh=o.isInstancedMesh? new THREE.InstancedMesh(o.geometry,mat,o.count) : new THREE.Mesh(o.geometry,mat);
    if(o.isInstancedMesh){ sh.instanceMatrix=o.instanceMatrix; }
    sh.userData.ink=true; sh.castShadow=false; sh.receiveShadow=false; sh.matrixAutoUpdate=false; o.add(sh);
    if(cm && !o.isInstancedMesh){ let eg=creaseCache.get(o.geometry); if(!eg){ eg=new THREE.EdgesGeometry(o.geometry,28); creaseCache.set(o.geometry,eg); } const ln=new THREE.LineSegments(eg,cm); ln.userData.ink=true; ln.matrixAutoUpdate=false; o.add(ln); } }
  return mat; }
// stroke colour carries the character's state
const STATES={calm:{c:0x1d1814,label:'Calm'}, selected:{c:0xe0a526,label:'Selected'}, overwatch:{c:0x2f9fc4,label:'Overwatch'}, concealed:{c:0x5b6fa8,label:'Concealed'}, wounded:{c:0xc23b2e,label:'Wounded'}, panicked:{c:0x9b4fc4,label:'Panicked'}};
const POSES={
  t:{bodyY:0,torsoX:0,torsoY:0,headX:.08,shRx:0,shRz:-1.5,elR:0,shLx:0,shLz:1.5,elL:0,lgR:0,knR:0,lgL:0,knL:0},
  ready:{bodyY:-.05,torsoX:.14,torsoY:.15,headX:-.05,shRx:-.55,shRz:-.2,elR:-1.35,shLx:-1.05,shLz:.35,elL:-.95,lgR:-.42,knR:.75,lgL:.12,knL:.3},
  stand:{bodyY:0,torsoX:0,torsoY:0,headX:.06,shRx:.02,shRz:-.12,elR:-.12,shLx:.02,shLz:.12,elL:-.12,lgR:0,knR:0,lgL:0,knL:0},
};
function applyPose(r,j){ r.body.position.y=j.bodyY; r.torso.rotation.set(j.torsoX,j.torsoY,0); r.head.rotation.x=j.headX;
  r.sh[0].rotation.set(j.shRx,0,j.shRz); r.el[0].rotation.x=j.elR; r.sh[1].rotation.set(j.shLx,0,j.shLz); r.el[1].rotation.x=j.elL;
  r.lg[0].rotation.x=j.lgR; r.kn[0].rotation.x=j.knR; r.lg[1].rotation.x=j.lgL; r.kn[1].rotation.x=j.knL; }

return {figure, genFace, POSES, applyPose, mats, inkUp, STATES};
})();
