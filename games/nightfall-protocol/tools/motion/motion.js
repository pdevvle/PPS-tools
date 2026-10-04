// ---------- Motion: procedural movement for FigureKit figures ----------
// One call per figure per frame: Motion.update(fig, state, dt), after the runtime has placed fig.root (position on the
// ground, yaw for heading). Layers, as in mockups/procedural-motion.html:
//   1. traits fixed per person by seed: stride, arm swing, posture, bounce, how they stand;
//   2. every time an action starts, its joint angles are rolled inside per-joint bounds;
//   3. smooth noise keeps held poses alive; wounds and panic widen and speed it up.
// On top of the pose:
//   - feet are anchored in the world while they bear weight and step when they must (walking, turning, changing stance);
//     hips, knees and ankles are solved to put each foot flat on its own ground;
//   - a held weapon (Motion.arm: a bolt-action rifle or a pistol) is placed by its hold, and the hands are solved to it;
//   - a fall is a ragdoll; standing up again is a get-up from the back or the front;
//   - vaults, ledge climbs, ladders and drops are clips that move the root themselves (Motion.traverse).
const Motion=(()=>{
const TAU=Math.PI*2, D=Math.PI/180;
const KEYS=['bodyY','torsoX','torsoY','headX','shRx','shRz','elR','shLx','shLz','elL','lgR','knR','lgL','knL'];
const SOLE=.062;   // ankle above the sole (FigureKit's foot)
// seeds next to each other (950, 957, ...) must give unrelated people, so the seed is mixed before the stream starts
function rng(seed){ let x=seed>>>0; x^=x>>>16; x=Math.imul(x,0x7feb352d); x^=x>>>15; x=Math.imul(x,0x846ca68b); x^=x>>>16; x=(x>>>0)||1; return ()=>{ x=(Math.imul(x,1664525)+1013904223)>>>0; return x/4294967296; }; }
// smooth 1D value noise in -1..1
const hash=i=>{ let x=Math.imul(i^0x5bd1e995,0x27d4eb2d); x^=x>>>15; x=Math.imul(x,0x85ebca6b); x^=x>>>13; return ((x>>>0)/4294967296)*2-1; };
const noise=(t,ch)=>{ const i=Math.floor(t), f=t-i, u=f*f*(3-2*f); return hash(i*131+ch*7919)*(1-u)+hash((i+1)*131+ch*7919)*u; };
const clamp=(v,a,b)=>v<a?a:v>b?b:v, smooth=t=>t<=0?0:t>=1?1:t*t*(3-2*t), lerp=(a,b,t)=>a+(b-a)*t;
const wrap=a=>Math.atan2(Math.sin(a),Math.cos(a));
const V=(x=0,y=0,z=0)=>new THREE.Vector3(x,y,z), Q=()=>new THREE.Quaternion();
const _v=V(), _v2=V(), _q=Q(), _q2=Q(), _m=new THREE.Matrix4(), _e=new THREE.Euler();
const UP=new THREE.Vector3(0,1,0), qYaw=(y,q=Q())=>q.setFromAxisAngle(UP,y);

// ---------- layer 1: traits from the seed ----------
function traits(seed){ const r=rng(Math.imul(seed|0,7)+1);
  return {stride:.88+r()*.24,      // longer or shorter steps than average for the speed (so cadence differs too)
    swing:.6+r()*.8,               // arm swing
    slouch:(r()-.4)*.16,           // forward lean of the spine; the head compensates
    bounce:.6+r()*.8,              // vertical bob
    width:(r()-.5)*.08,            // arms held out or in
    toe:(r()-.5)*.08,              // stance width
    fidget:.7+r()*.6,              // how much they move standing still
    favour:r()<.5?0:1,             // the leg they rest on, and the one a wound favours
    head:(r()-.5)*.12};            // head carriage
}
// FigureKit figures carry their face values; the same person always hashes to the same seed
function seedOf(fig){ if(fig.seed!=null) return fig.seed>>>0; let h=2166136261; const FP=fig.FP||{};
  for(const k of Object.keys(FP).sort()){ const v=FP[k]; if(typeof v==='number'){ h^=Math.round(v*1e4); h=Math.imul(h,16777619); } }
  return h>>>0; }

// ---------- actions: a base pose, which legs and arms layers drive it, and how far a roll may move it ----------
// legs: 'plant' (stand or walk, feet solved to the ground) or 'free' (posed as is: swim)
// arms: 'swing' (natural arm swing while moving), 'hold' (the pose's arms, with a little bob)
// hold: which weapon hold the action uses, per weapon kind
const P=o=>Object.assign({bodyY:0,torsoX:0,torsoY:0,headX:.06,shRx:.02,shRz:-.12,elR:-.12,shLx:.02,shLz:.12,elL:-.12,lgR:0,knR:0,lgL:0,knL:0},o);
const READY_ARMS={shRx:-.55,shRz:-.2,elR:-1.35,shLx:-1.05,shLz:.35,elL:-.95};
const AIM_ARMS={shRx:-1.45,shRz:-.1,elR:-.12,shLx:-1.25,shLz:.4,elL:-.55};
const STANCE={bodyY:-.04,lgR:-.35,knR:.6,lgL:.15,knL:.3};
const ACTS={
  idle:   {pose:P({}),                                                     legs:'plant', arms:'swing', roll:.4, hold:{rifle:'low',pistol:'hand'}},
  walk:   {pose:P({torsoX:.05}),                                           legs:'plant', arms:'swing', roll:.4, hold:{rifle:'low',pistol:'hand'}},
  run:    {pose:P({torsoX:.18,headX:-.06}),                                legs:'plant', arms:'swing', roll:.4, run:1, hold:{rifle:'port',pistol:'hand'}},
  ready:  {pose:P(Object.assign({bodyY:-.05,torsoX:.14,torsoY:.15,headX:-.05,lgR:-.42,knR:.75,lgL:.12,knL:.3},READY_ARMS)), legs:'plant', arms:'hold', roll:.6, hold:{rifle:'ready',pistol:'ready'}},
  'crouch-walk':{pose:P(Object.assign({bodyY:-.26,torsoX:.42,torsoY:.08,headX:-.3,lgR:-.9,knR:1.5,lgL:-.2,knL:1.1},READY_ARMS)), legs:'plant', arms:'hold', roll:.7, crouch:1, hold:{rifle:'ready',pistol:'ready'}},
  crouch: {pose:P({bodyY:-.3,torsoX:.38,torsoY:.1,headX:-.25,shRx:-.95,shRz:-.12,elR:-1.25,shLx:-1.1,shLz:.2,elL:-1.1,lgR:-1.2,knR:1.75,lgL:-.35,knL:1.25}), legs:'plant', arms:'hold', roll:1, crouch:1, hold:{rifle:'ready',pistol:'ready'}},
  aim:    {pose:P(Object.assign({torsoX:.1,torsoY:.15,headX:0},STANCE,AIM_ARMS)), legs:'plant', arms:'hold', roll:.35, steady:1, hold:{rifle:'aim',pistol:'aim'}},
  shoot:  {pose:P(Object.assign({torsoX:.1,torsoY:.15,headX:0},STANCE,AIM_ARMS)), legs:'plant', arms:'hold', roll:.35, steady:1, hold:{rifle:'aim',pistol:'aim'}},
  reload: {pose:P(Object.assign({torsoX:.16,torsoY:.1,headX:.22,shRx:-.85,shRz:-.15,elR:-1.15,shLx:-1.05,shLz:.3,elL:-.95},STANCE)), legs:'plant', arms:'hold', roll:.5, cycle:'reload', hold:{rifle:'reload',pistol:'reload'}},
  hunker: {pose:P({bodyY:-.38,lgR:-1.2,knR:1.7,lgL:-.5,knL:1.9,torsoX:.55,headX:.2,shRx:-.8,shRz:-.3,elR:-1.6,shLx:-.9,shLz:.35,elL:-1.5}), legs:'plant', arms:'hold', roll:1, crouch:1, hold:{rifle:'hug',pistol:'hug'}},
  hit:    {pose:P({bodyY:-.06,torsoX:-.2,headX:-.15,shRz:-.45,shLz:.45,elR:-.6,elL:-.6,lgR:-.2,knR:.4,lgL:.1,knL:.3}), legs:'plant', arms:'hold', roll:1.2, hold:{rifle:'low',pistol:'hand'}},
  carry:  {pose:P({torsoX:-.06,headX:.1,shRx:-.7,shRz:-.28,elR:-1.15,shLx:-.7,shLz:.28,elL:-1.15}), legs:'plant', arms:'hold', roll:.5, stride:.8, hold:{rifle:'sling',pistol:'holster'}},
  work:   {pose:P({bodyY:-.08,torsoX:.4,headX:.25,lgR:-.4,knR:.5,lgL:.2,knL:.25,shRx:-.7,shRz:-.15,elR:-.5,shLx:-.9,shLz:.15,elL:-.4}), legs:'plant', arms:'hold', roll:.8, cycle:'dig', hold:{rifle:'sling',pistol:'holster'}},
  swim:   {pose:P({torsoX:.35,headX:-.25,shRz:-.5,shLz:.5,elR:-.4,elL:-.4,knR:.3,knL:.3}), legs:'free', arms:'hold', roll:.3, cycle:'swim', hold:{rifle:'sling',pistol:'holster'}},
  fall:   {pose:P({}), legs:'rag', arms:'rag', roll:0, fall:1},
};
ACTS.dead=Object.assign({},ACTS.fall,{dead:1});
// per-joint bounds for one roll (radians; bodyY in metres), scaled by the action's roll
const BOUND={bodyY:.03,torsoX:4*D,torsoY:7*D,headX:7*D,shRx:8*D,shRz:6*D,elR:10*D,shLx:8*D,shLz:6*D,elL:10*D,lgR:7*D,knR:9*D,lgL:7*D,knL:9*D};
// held weapon: a steady action rolls the arms less (sway comes from the Aim stat, not cosmetics)
const ARMKEYS=new Set(['shRx','shRz','elR','shLx','shLz','elL']);

// ---------- the rig: measured from the figure, plus the joints FigureKit doesn't have yet ----------
// Ankles: the foot meshes hang straight off the knee in FigureKit, so an ankle group is slipped in between.
function rig(fig){ const lg=fig.lg[0], kn=fig.kn[0];
  const hipH=fig.hips.position.y+lg.position.y, a=-kn.position.y, b=hipH-SOLE-a;
  fig.hand=fig.hand||fig.el.map(e=>e.children.find(c=>c.isGroup));
  if(!fig.an) fig.an=fig.kn.map(k=>{ const g=new THREE.Group(); g.position.set(0,-b,0);
    for(const c of [...k.children]) if(c.isMesh&&c.position.y<-.2){ k.remove(c); c.position.y+=b; g.add(c); }
    k.add(g); return g; });
  if(!fig.fingers) buildHands(fig);
  const ua=-fig.el[0].position.y, fa=-fig.hand[0].position.y;
  return {hipH, a, b, L:a+b, hipX:Math.abs(lg.position.x), hipsY:fig.hips.position.y, ua, fa, arm:ua+fa,
    sh:fig.sh.map(s=>s.position.clone()), lgP:fig.lg.map(l=>l.position.clone())}; }
// Hands: FigureKit's hand is one mitten mesh and a thumb. It is swapped for a palm, four fingers of three joints each
// and a thumb of two, all sized from the mitten, skinned with its material and inked with its outline.
// fig.fingers[hand][finger][joint] (index to little, base to tip), fig.thumbs[hand][joint]. Curling is rotation about z
// toward the palm, which faces the body when the arm hangs (+x on the right hand, -x on the left).
const FING=[{z:.026,len:.074,r:.0084},{z:.009,len:.082,r:.0088},{z:-.008,len:.077,r:.0084},{z:-.024,len:.062,r:.0074}], PHAL=[.46,.3,.24];
const HG={}, hg=(k,f)=>HG[k]||(HG[k]=f());
function buildHands(fig){ fig.fingers=[]; fig.thumbs=[];
  fig.hand.forEach((h,i)=>{ const side=i?1:-1, meshes=h.children.filter(c=>c.isMesh), mitten=meshes[0], thumb=meshes[2]||null;
    if(!mitten){ fig.fingers.push([]); fig.thumbs.push([]); return; }
    mitten.geometry.computeBoundingBox(); const bb=mitten.geometry.boundingBox, k=(bb.max.z-bb.min.z)/.084, skin=mitten.material; fig.handK=k;
    const ink=mitten.children.find(c=>c.userData&&c.userData.ink&&c.isMesh), inkM=ink&&ink.material;
    const add=(parent,geo,x,y,z,sx=1,sy=1,sz=1)=>{ const m=new THREE.Mesh(geo,skin); m.position.set(x,y,z); m.scale.set(sx,sy,sz); m.castShadow=true; parent.add(m);
      if(inkM){ const o=new THREE.Mesh(geo,inkM); o.userData.ink=true; o.castShadow=false; m.add(o); } return m; };
    h.remove(mitten); if(thumb) h.remove(thumb);
    // palm: a slab, a touch narrower at the heel, knuckles at its end
    const palmG=hg('palm',()=>{ const g=new THREE.BoxGeometry(.023,.086,.066,1,2,1), p=g.attributes.position; for(let n=0;n<p.count;n++){ const y=p.getY(n); if(y>.02){ p.setZ(n,p.getZ(n)*.8); p.setX(n,p.getX(n)*.85); } } g.translate(0,-.043,.001); g.computeVertexNormals(); return g; });
    add(h,palmG,0,0,0,k,k,k);
    const ball=hg('knuckle',()=>new THREE.SphereGeometry(1,5,3));
    const fingers=FING.map(F=>{ const chain=[]; let parent=h, y=-.088*k, z=F.z*k, r=F.r*k;
      PHAL.forEach((pf,j)=>{ const len=F.len*pf*k, g=new THREE.Group(); g.position.set(0,y,j?0:z); parent.add(g);
        const geo=hg('ph'+len.toFixed(4)+r.toFixed(4),()=>{ const c=new THREE.CylinderGeometry(r*.86,r,len,5); c.translate(0,-len/2,0); return c; });
        g.userData.seg={len,r}; add(g,geo,0,0,0); add(g,ball,0,0,0,r*1.05,r*1.05,r*1.05); chain.push(g); parent=g; y=-len; r*=.88; });
      return chain; });
    const thumbs=[]; { let parent=h; const r0=.0098*k, base=new THREE.Group(); base.position.set(side*.006*k,-.022*k,.036*k); h.add(base);
      [.04,.032].forEach((len,j)=>{ len*=k; const g=j?new THREE.Group():base; if(j){ g.position.set(0,-.04*k,0); thumbs[0].add(g); }
        const rr=r0*(j?.85:1), geo=hg('th'+len.toFixed(4)+rr.toFixed(4),()=>{ const c=new THREE.CylinderGeometry(rr*.85,rr,len,5); c.translate(0,-len/2,0); return c; });
        g.userData.seg={len,r:rr}; add(g,geo,0,0,0); add(g,ball,0,0,0,rr*1.1,rr*1.1,rr*1.1); thumbs.push(g); }); }
    fig.fingers.push(fingers); fig.thumbs.push(thumbs); setHand(fig,i,{curl:.3}); }); }
// curl 0 (flat) to 1 (wrapped round a grip); index alone for a trigger finger; thumb 0 (alongside) to 1 (across the palm)
function setHand(fig,i,{curl=.3,index,thumb,spread=.15}){ const side=i?1:-1, c=side*-1, F=fig.fingers&&fig.fingers[i]; if(!F||!F.length) return;
  F.forEach((chain,j)=>{ const cu=j===0&&index!==undefined?index:curl, w=[1.25,1.45,1.0];
    chain.forEach((g,k)=>g.rotation.set(k?0:(1.5-j)*spread*.12,0,c*cu*w[k])); });
  const T=fig.thumbs[i], th=thumb===undefined?curl:thumb; if(T&&T.length){ T[0].rotation.set(-.55+th*.25,side*-(.25+th*.55),c*(.35+th*.55)); T[1].rotation.set(0,0,c*(.2+th*.9)); } }

// two-bone limb: a ball joint at the root (shoulder or hip: x, y and z rotation) and a hinge (elbow or knee, about x).
// t: target of the end joint in the root joint's parent frame, relative to the root joint. bend -1: elbow (forearm
// comes forward), +1: knee (shin goes back). pole: the direction the middle joint should point (elbow out and down,
// knee forward). Returns Euler XYZ angles for the root joint and the hinge angle.
const _bl=new THREE.Matrix4(), _bt=new THREE.Matrix4(), _eu=new THREE.Euler();
function limb(a,b,t,bend,pole){ const tl=t.length()||1e-6, d=clamp(tl,Math.abs(a-b)+1e-3,(a+b)*.9995);
  const e=bend*Math.acos(clamp((d*d-a*a-b*b)/(2*a*b),-1,1));
  // the limb in its own frame: end joint at v, middle joint at E
  const v=V(0,-a-b*Math.cos(e),-b*Math.sin(e)), al=v.clone().normalize(), E=V(0,-a,0), nl=E.clone().addScaledVector(al,-E.dot(al));
  if(nl.lengthSq()<1e-10) nl.set(0,0,-bend); nl.normalize();
  const at=t.clone().normalize(), nt=(pole||V(0,0,bend>0?1:-1)).clone(); nt.addScaledVector(at,-nt.dot(at));
  if(nt.lengthSq()<1e-8){ nt.set(0,0,1).addScaledVector(at,-at.z); if(nt.lengthSq()<1e-8) nt.set(1,0,0); } nt.normalize();
  _bl.makeBasis(al,nl,V().crossVectors(al,nl)); _bt.makeBasis(at,nt,V().crossVectors(at,nt));
  _eu.setFromRotationMatrix(_bt.multiply(_bl.transpose()),'XYZ');
  return {rx:_eu.x, ry:_eu.y, rz:_eu.z, e}; }
// where elbows and knees point: elbows down, out and a little back; knees forward and slightly out
const ARM_POLE=[V(-.55,-1,-.3),V(.55,-1,-.3)], KNEE_POLE=[V(-.12,.05,1),V(.12,.05,1)];
// ankle relative to the hip joint for a thigh angle and a knee bend (the leg's own plane)
const fk=(R,th,kn)=>({y:-(R.a*Math.cos(th)+R.b*Math.cos(th+kn)), z:-(R.a*Math.sin(th)+R.b*Math.sin(th+kn))});

function init(fig){ const seed=seedOf(fig), R=rig(fig), M={grip:[null,null], seed, tr:traits(seed), R, rr:rng(Math.imul(seed,31)+7), j:Object.assign({},ACTS.idle.pose),
    ph:rng(seed)()*1, v:0, lx:fig.root.position.x, lz:fig.root.position.z, gaitW:0, runW:0, act:null, actT:0, roll:{}, t:rng(seed+3)()*50,
    wound:0, panic:0, hit:0, hitSide:1, hitDir:null, recoil:0, moving:false, still:0, feet:null, handW:[0,0], wc:null, clip:null, rag:null, dirty:false};
  fig.motion=M; return M; }
function rollFor(M,def){ const o={}, k=def.roll||0; for(const key of KEYS){ const s=def.steady&&ARMKEYS.has(key)?.3:1; o[key]=(M.rr()*2-1)*BOUND[key]*k*s; } return o; }

// ground under a world point (state.ground, else state.slope along the heading, else the root's own height)
function groundW(fig,s,x,z){ const p=fig.root.position;
  if(s.ground){ const g=s.ground(x,z); if(Number.isFinite(g)) return g; }
  if(s.slope){ const y=fig.root.rotation.y; return p.y+s.slope*((x-p.x)*Math.sin(y)+(z-p.z)*Math.cos(y)); }
  return p.y; }
const toWorld=(fig,x,y,z)=>{ const r=fig.root, c=Math.cos(r.rotation.y), s=Math.sin(r.rotation.y); return V(r.position.x+x*c+z*s, r.position.y+y, r.position.z-x*s+z*c); };
const toLocal=(fig,w)=>{ const r=fig.root, c=Math.cos(r.rotation.y), s=Math.sin(r.rotation.y), dx=w.x-r.position.x, dz=w.z-r.position.z; return V(dx*c-dz*s, w.y-r.position.y, dx*s+dz*c); };

// ======================================================================================================
// Weapons: quick inked models, the holds that place them, and the hand targets they give
// ======================================================================================================
const WMAT={};
const wm=(c)=>WMAT[c]||(WMAT[c]=new THREE.MeshToonMaterial({color:c}));
function part(g,geo,col,x,y,z,rx=0,ry=0,rz=0){ const m=new THREE.Mesh(geo,wm(col)); m.position.set(x,y,z); m.rotation.set(rx,ry,rz); m.castShadow=true; g.add(m); return m; }
const box=(w,h,d)=>new THREE.BoxGeometry(w,h,d), cyl=(r,l,s=6)=>{ const g=new THREE.CylinderGeometry(r,r,l,s); g.rotateX(Math.PI/2); return g; };
const WOOD='#7a5236', STEEL='#34373a', DARK='#232426', BRASS='#b08a3e';
// Weapon frame: origin at the trigger grip, +z down the barrel, +y up; the figure's right is -x.
const WEAPONS={
  // a Mauser-pattern bolt-action rifle, 1.1 m
  rifle:{kind:'rifle', len:1.1, butt:V(0,.005,-.4), muzzle:V(0,.045,.7), flip:.1, back:.035, cycle:'bolt', reload:3.0,
    grip:[{p:V(0,-.02,-.035),axis:V(.05,-.85,.5),palm:V(1,0,0),index:.5}, {p:V(0,-.005,.24),axis:V(-.85,0,.5),palm:V(0,1,0)}],
    build(){ const g=new THREE.Group();
      part(g,box(.042,.12,.26),WOOD,0,-.025,-.27,-.1); part(g,box(.036,.055,.13),WOOD,0,-.012,-.07,-.25); part(g,box(.046,.05,.52),WOOD,0,.012,.24);
      part(g,box(.032,.036,.22),STEEL,0,.044,.04); part(g,cyl(.0105,.5),STEEL,0,.046,.45); part(g,box(.006,.016,.012),STEEL,0,.062,.69);
      part(g,box(.008,.03,.05),STEEL,0,-.022,.005); part(g,box(.01,.012,.03),STEEL,0,.052,-.005);
      const bolt=new THREE.Group(); bolt.position.set(0,.05,-.015); g.add(bolt); part(bolt,cyl(.0085,.11),STEEL,0,0,-.01);
      part(bolt,box(.048,.008,.008),STEEL,-.024,0,.02); part(bolt,new THREE.SphereGeometry(.011,6,4),STEEL,-.05,-.004,.02);
      const clip=new THREE.Group(); part(clip,box(.012,.05,.06),BRASS,0,0,0); clip.visible=false;
      return {g,bolt,mag:clip}; }},
  // a service pistol, 0.21 m
  pistol:{kind:'pistol', len:.21, muzzle:V(0,.035,.15), flip:.32, back:.025, cycle:'slide', reload:1.9,
    grip:[{p:V(0,-.035,-.015),axis:V(0,-.3,.95),palm:V(1,0,0),index:.45}, {p:V(.03,-.045,-.01),axis:V(-.1,-.45,.89),palm:V(-1,0,0)}],
    build(){ const g=new THREE.Group();
      part(g,box(.028,.105,.052),DARK,0,-.035,-.018,-.22); part(g,box(.026,.012,.13),DARK,0,.006,.05); part(g,box(.008,.022,.04),DARK,0,-.008,.035);
      const slide=new THREE.Group(); g.add(slide); part(slide,box(.03,.034,.2),STEEL,0,.034,.045); part(slide,box(.005,.008,.01),STEEL,0,.054,.13); part(slide,cyl(.006,.012),DARK,0,.034,.15);
      const mag=new THREE.Group(); part(mag,box(.022,.09,.032),DARK,0,0,0); mag.visible=false;
      return {g,bolt:slide,mag}; }},
};
// arm a figure: build the weapon (parented to the root; its hold places it every frame)
function arm(fig,kind,opt={}){ const M=fig.motion||init(fig);
  if(M.w){ fig.root.remove(M.w.g); if(M.w.mag.parent) M.w.mag.parent.remove(M.w.mag); M.w=null; }
  if(!kind||!WEAPONS[kind]) return null;
  const W=WEAPONS[kind], b=W.build(); b.spec=W; fig.root.add(b.g);
  if(opt.ink!==false&&FigureKit.inkUp) FigureKit.inkUp(b.g,Object.assign({color:0x1d1814},opt.ink||{}));
  fig.root.add(b.mag); b.pos=null; b.q=Q(); M.w=b; return b; }

// a hold: where the weapon sits (root frame) and whether each hand is on it
function holdTarget(fig,M,name,s,out){ const W=M.w.spec, R=M.R, torso=fig.torso;
  const fromTorso=(x,y,z)=>toLocal(fig,torso.localToWorld(V(x,y,z)));
  const torsoQ=()=>{ torso.getWorldQuaternion(_q); qYaw(-fig.root.rotation.y,_q2); return _q2.multiply(_q).clone(); };
  const look=clamp(M.look||0,-.9,.9), pitch=s.aimPitch||0, sx=Math.abs(R.sh[0].x);
  const aimQ=(p,y=0,r=0)=>Q().setFromEuler(_e.set(p,look+y,r,'YXZ'));
  const butt=(q,dy=0)=>{ const pk=fromTorso(-sx*.62,R.sh[0].y-.03+dy,.06); return pk.sub(W.butt.clone().applyQuaternion(q)); };
  const chest=()=>{ const a=fig.sh[0].getWorldPosition(V()), b=fig.sh[1].getWorldPosition(V()); return toLocal(fig,a.add(b).multiplyScalar(.5)); };
  let p, q, hands=[1,1];
  if(W.kind==='rifle') switch(name){
    case 'aim': q=aimQ(-pitch); p=butt(q); break;
    case 'ready': q=aimQ(.55-pitch*.5,.05); p=butt(q,-.02); break;
    case 'reload': q=aimQ(.4,.15,-.45); p=butt(q,-.06); p.z+=.06; break;
    case 'hug': q=torsoQ().multiply(Q().setFromUnitVectors(V(0,0,1),V(.35,.88,.3).normalize())); p=fromTorso(-.06,.16,.2); break;
    case 'port': q=torsoQ().multiply(Q().setFromUnitVectors(V(0,0,1),V(.55,.68,.48).normalize())); p=fromTorso(-.1,.15,.21); break;
    case 'sling': q=torsoQ().multiply(Q().setFromUnitVectors(V(0,0,1),V(-.42,.88,-.2).normalize())).multiply(Q().setFromAxisAngle(V(0,0,1),Math.PI/2)); p=fromTorso(-.02,.22,-.15); hands=[0,0]; break;
    default: q=torsoQ().multiply(Q().setFromEuler(_e.set(.95,.35,.15))); p=fromTorso(-.11,.05,.21); }   // low: muzzle down and across
  else switch(name){
    case 'aim': { q=aimQ(-pitch); const c=chest(); p=c.add(V(-.03,-.04,R.arm*.86).applyQuaternion(aimQ(0))); break; }
    case 'ready': { q=aimQ(.55); const c=chest(); p=c.add(V(-.02,-.2,.3).applyQuaternion(aimQ(0))); break; }
    case 'hug': { q=aimQ(-1.0); const c=chest(); p=c.add(V(-.03,-.16,.2).applyQuaternion(aimQ(0))); break; }
    case 'reload': { q=aimQ(-.5,0,.4); const c=chest(); p=c.add(V(-.02,-.14,.3).applyQuaternion(aimQ(0))); break; }
    case 'holster': q=torsoQ().multiply(Q().setFromEuler(_e.set(Math.PI/2,0,0))); p=toLocal(fig,fig.hips.localToWorld(V(-.19,-.06,.02))); hands=[0,0]; break;
    default: { // in the right hand: the weapon follows the hand, the arm keeps its swing
      const h=fig.hand[0]; h.updateWorldMatrix(true,false); h.getWorldQuaternion(_q); qYaw(-fig.root.rotation.y,_q2); q=_q2.multiply(_q).clone().multiply(Q().setFromEuler(_e.set(1.25,0,0)));   // grip across the palm like a hammer handle, muzzle down and a little forward
      p=toLocal(fig,h.localToWorld(V(0,-.075,.005))); hands=[0,0]; M.inHand=1; } }
  out.p=p; out.q=q; out.hands=hands; return out; }

// weapon-cycle timelines: each a list of [time, target] for one hand; targets are {w:Vector3} (weapon frame),
// {t:Vector3} (torso frame) or null (the hand's own grip)
const seg=(list,t)=>{ for(let i=0;i<list.length-1;i++){ const [t0,a]=list[i], [t1,b]=list[i+1]; if(t<=t1) return [a,b,smooth((t-t0)/(t1-t0||1))]; } const l=list[list.length-1]; return [l[1],l[1],1]; };
const HB0=V(-.05,.05,.005), HB1=V(-.052,.075,.005), HB2=V(-.052,.075,-.085);   // rifle bolt handle: closed, lifted, drawn back
const TL={
  bolt:{dur:.85, R:[[0,null],[.12,{w:HB0}],[.22,{w:HB1}],[.42,{w:HB2}],[.6,{w:HB1}],[.68,{w:HB0}],[.85,null]]},
  rifleReload:{dur:3.0, R:[[0,null],[.12,{w:HB0}],[.22,{w:HB1}],[.42,{w:HB2}],[1.95,{w:HB2}],[2.15,{w:HB1}],[2.25,{w:HB0}],[2.5,null],[3,null]],
    L:[[0,null],[.5,null],[.95,{t:V(.13,.02,.16)}],[1.15,{t:V(.13,.02,.16)}],[1.45,{w:V(.012,.12,-.03)}],[1.6,{w:V(.012,.085,-.03)}],[1.68,{w:V(.012,.1,-.03)}],[1.78,{w:V(.012,.08,-.03)}],[2.05,null],[3,null]], mag:[.95,1.75]},
  pistolReload:{dur:1.9, L:[[0,null],[.2,{w:V(.01,-.12,-.03)}],[.5,{t:V(.15,-.06,.13)}],[.65,{t:V(.15,-.06,.13)}],[.95,{w:V(.01,-.17,-.035)}],[1.05,{w:V(.01,-.12,-.03)}],[1.22,{w:V(.03,.06,-.04)}],[1.36,{w:V(.03,.06,-.09)}],[1.5,{w:V(.03,.06,-.04)}],[1.9,null]], mag:[.6,1.05], rack:[1.22,1.36,1.5]},
};
function cycleState(M){ const c=M.wc; if(!c) return null; const tl=TL[c.type]; return {tl, t:c.t}; }

// ======================================================================================================
// The update
// ======================================================================================================
// state: 'walk' or {act, mood, ground, slope, compress, look, lookAt, aimPitch}
//   act      one of Motion.ACTS; walking or running is picked from the measured speed, act only says what the body does
//   mood     calm | wounded | panicked
//   ground   height of the ground at a world point, so each foot finds its own footing (else slope, else flat)
//   compress how much faster than real time the runtime moves people; gait shape follows the real speed, cadence the shown one
//   look     yaw relative to the body to turn toward and aim at (or lookAt, a world point)
function update(fig,state,dt){
  const s=typeof state==='string'?{act:state}:(state||{}), M=fig.motion||init(fig);
  dt=Math.max(0,Math.min(dt||0,.1)); M.t+=dt;
  const actName=ACTS[s.act]?s.act:'idle', def=ACTS[actName];
  if(actName!==M.act){ M.prevAct=M.act; M.act=actName; M.actT=0; M.roll=rollFor(M,def);
    if(def.fall&&!M.rag&&!M.clip) startRag(fig,M,s);
    if(actName==='reload'&&M.w) M.wc={type:M.w.spec.kind==='rifle'?'rifleReload':'pistolReload',t:0}; } else M.actT+=dt;
  const p=fig.root.position; let dist=Math.hypot(p.x-M.lx,p.z-M.lz); if(dist>2){ dist=0; M.feet=null; }
  if(M.clip){ clipStep(fig,M,s,dt); M.lx=p.x; M.lz=p.z; M.v=0; return M; }
  if(M.rag){ ragStep(fig,M,s,dt); if(!def.fall&&M.rag&&(M.rag.sleep||M.rag.t>1.2)) startRise(fig,M,s); M.lx=p.x; M.lz=p.z; return M; }
  M.lx=p.x; M.lz=p.z;
  const vi=dt>0?dist/dt:0; M.v+=(vi-M.v)*Math.min(1,dt*8);
  const comp=s.compress||1, vr=M.v/comp;
  M.moving=M.moving?vr>.08:vr>.18;
  pose(fig,M,s,def,actName,dt,dist,vr);
  return M; }

// ---------- the normal pose: layers, legs, weapon, hands ----------
function pose(fig,M,s,def,actName,dt,dist,vr){
  const R=M.R, tr=M.tr, p=fig.root.position;
  const mood=s.mood||'calm', quiet=Motion.reduce?.3:1;
  M.wound+=((mood==='wounded'?1:0)-M.wound)*Math.min(1,dt*2); M.panic+=((mood==='panicked'?1:0)-M.panic)*Math.min(1,dt*3);
  const W=M.wound, Pn=M.panic;
  if(M.dirty) clean(fig,M);
  // ---- target pose: action base + roll + traits + mood + the action's own cycle ----
  const T={}; for(const k of KEYS) T[k]=def.pose[k]+(M.roll[k]||0);
  T.torsoX+=tr.slouch; T.headX+=tr.head-tr.slouch*.6; T.shRz-=tr.width; T.shLz+=tr.width;
  if(W>0){ T.torsoX+=.14*W; T.headX+=.12*W; T.bodyY-=.03*W;   // slumped, one arm held to the side
    if(def.arms==='swing'&&!M.w){ if(tr.favour){ T.shLx=lerp(T.shLx,-.45,W); T.shLz=lerp(T.shLz,.05,W); T.elL=lerp(T.elL,-1.7,W); } else { T.shRx=lerp(T.shRx,-.45,W); T.shRz=lerp(T.shRz,-.05,W); T.elR=lerp(T.elR,-1.7,W); } } }
  if(Pn>0){ T.torsoX+=.12*Pn; T.headX-=.14*Pn; T.bodyY-=.05*Pn; if(def.arms==='swing'){ T.shRz=lerp(T.shRz,-.04,Pn); T.shLz=lerp(T.shLz,.04,Pn); T.elR-=.7*Pn; T.elL-=.7*Pn; T.shRx-=.3*Pn; T.shLx-=.3*Pn; } }
  if(def.cycle==='reload'&&!M.w){ const c=(M.actT%1.6)/1.6, down=smooth(c/.3)*(1-smooth((c-.6)/.3));
    T.shLx=lerp(T.shLx,.15,down); T.shLz=lerp(T.shLz,.22,down); T.elL=lerp(T.elL,-.7,down); T.shRx+=.12*Math.sin(c*TAU); T.headX+=.1*down; }
  if(def.cycle==='dig'){ const c=M.actT/1.5*TAU, sw=Math.sin(c);
    T.torsoX+=.22*sw; T.headX+=.08*sw; T.shRx+=-.45*sw; T.shLx+=-.45*sw; T.elR+=.25*Math.cos(c); T.elL+=.25*Math.cos(c); T.bodyY+=-.04*(sw*.5+.5); }
  if(def.cycle==='swim'){ const t=M.t*2.2; Object.assign(T,{shRx:-1.4+Math.sin(t)*1.3,shLx:-1.4-Math.sin(t)*1.3,lgR:Math.sin(t*2)*.35,lgL:-Math.sin(t*2)*.35}); }
  if(M.w&&M.w.spec.kind==='rifle'&&(actName==='aim'||actName==='shoot')) T.headX+=.12;   // cheek on the stock
  // a rifle is shot bladed: the body turns right so the left shoulder leads and the support hand reaches the fore-end;
  // the neck turns the head back to the target
  const blade=M.w&&M.w.spec.kind==='rifle'&&['aim','shoot','ready','reload'].includes(actName)?-.8:0; M.blade=(M.blade||0)+(blade-(M.blade||0))*Math.min(1,dt*8); T.torsoY+=M.blade;
  // look: spine takes part of it, the neck the rest (neck yaw is set on the head directly)
  let look=s.look||0; if(s.lookAt) look=wrap(Math.atan2(s.lookAt.x-p.x,s.lookAt.z-p.z)-fig.root.rotation.y);
  M.look=look; T.torsoY+=clamp(look,-1.2,1.2)*.5;
  // layer 3: idle noise on top, wider and quicker with wounds and panic, damped while moving
  const amp=quiet*tr.fidget*(1+W*1.4+Pn*1.8)*(M.moving?.45:1)*(def.steady?.5:1), sp=1+W*1.2+Pn*2.2, t=M.t;
  T.headX+=noise(t*.6*sp,1)*6*D*amp; T.torsoX+=noise(t*.45*sp,2)*2.5*D*amp+Math.sin(t*(1.6+Pn*1.8))*.006*(1+Pn);
  T.torsoY+=noise(t*.3*sp,4)*5*D*amp*(1+Pn*1.5); T.shRz+=noise(t*.5*sp,5)*3*D*amp; T.shLz+=noise(t*.5*sp,6)*3*D*amp; T.bodyY+=noise(t*.4,7)*.006*amp;
  const shift=noise(t*.18*sp,8)*amp;
  // ---- transitions between actions ----
  const k=1-Math.exp(-dt*(actName==='hit'?16:9));
  for(const key of KEYS) M.j[key]+=(T[key]-M.j[key])*k;
  const O=Object.assign({},M.j);

  // ---- legs: decide where each foot goes (world targets) and how high the pelvis rides ----
  let feet=null;
  if(def.legs==='plant') feet=legs(fig,M,s,def,O,dt,dist,vr,W,Pn,shift); else { M.gaitW=0; M.runW=0; M.feet=null; }
  // arms swing against the legs while moving (an armed hand on the weapon ignores it)
  if(feet){ const gw=M.gaitW, rw=M.runW, sw=gw*Math.min(1.3,vr/1.4+.15)*(def.arms==='swing'?1:.15)*(1-.5*W)*(1-.6*Pn), n0=feet.n[0], n1=feet.n[1];
    O.shRx+=n0*.3*tr.swing*sw*(1+rw*.6); O.shLx+=n1*.3*tr.swing*sw*(1+rw*.6);
    if(def.arms==='swing'){ O.elR-=(.12+.2*tr.swing)*gw+rw*1.0; O.elL-=(.12+.2*tr.swing)*gw+rw*1.0; }
    O.torsoX+=rw*.12*gw+.05*gw*Math.min(1,vr/1.4); O.torsoY+=(n1-n0)*.04*gw*(1+rw); }
  // ---- impulses ----
  if(M.hit>0){ const h=M.hit*M.hit; O.torsoX-=.45*h; O.headX-=.3*h; O.torsoY+=M.hitSide*.25*h; O.shRz-=.3*h; O.shLz+=.3*h; O.bodyY-=.04*h; M.hit=Math.max(0,M.hit-dt*2.2); }
  if(M.recoil>0){ const r=M.recoil; O.torsoX-=.05*r; O.headX-=.04*r; if(!M.w){ O.shRx+=.25*r; O.shLx+=.18*r; } }
  M.out=O; FigureKit.applyPose(fig,O);
  fig.head.rotation.y=clamp(M.look-clamp(M.look,-1.2,1.2)*.5,-.8,.8)*.9-(M.blade||0)*.85;
  fig.root.updateMatrixWorld(true);
  // ---- solve legs and ankles to their targets ----
  if(feet) for(let i=0;i<2;i++) solveLeg(fig,M,i,feet.w[i],feet.pitch[i]);
  else for(let i=0;i<2;i++){ fig.lg[i].rotation.y=0; fig.lg[i].rotation.z=0; fig.an[i].rotation.x=0; }
  // ---- weapon and hands ----
  weapon(fig,M,s,def,actName,dt);
  fingers(fig,M,def,actName,dt);
  M.recoil=Math.max(0,M.recoil-dt*5);
}

// legs: anchored feet. A foot that bears weight stays at its world anchor; walking swaps feet by the gait phase; standing
// still, a foot steps when it is too far from where the stance wants it or the body has turned away from it.
function legs(fig,M,s,def,O,dt,dist,vr,W,Pn,shift){
  const R=M.R, tr=M.tr, root=fig.root, yaw=root.rotation.y;
  M.gaitW+=((M.moving?1:0)-M.gaitW)*Math.min(1,dt*7);
  const wantRun=(def.run?1:0)||(vr>2.3&&!def.crouch?1:0); M.runW+=(wantRun-M.runW)*Math.min(1,dt*4);
  const rw=M.runW, gw=M.gaitW, cr=def.crouch?1:0;
  const strideLen=clamp(R.L*(.78+.48*Math.min(vr,4))*tr.stride*(def.stride||1)*(cr?.75:1)*(1-.22*W)*(1-.12*Pn),R.L*.7,R.L*3.2);
  if(M.moving) M.ph=(M.ph+dist/strideLen)%1;
  const beta=.58-.22*rw, lift=(.06+.04*Math.min(1,vr/1.5))*(cr?.8:1)+.16*rw;
  // nominal stance: where the action's pose puts each foot (root frame)
  const nom=[0,1].map(i=>{ const f=fk(R,i?O.lgL:O.lgR,i?O.knL:O.knR); return V((i?1:-1)*R.hipX*(1+tr.toe),0,f.z+(i===tr.favour?1:-1)*shift*.02); });
  if(!M.feet){ M.feet=[0,1].map(i=>{ const w=footWorld(fig,M,i)||toWorld(fig,nom[i].x,0,nom[i].z); w.y=groundW(fig,s,w.x,w.z)+SOLE; return {st:'stance',a:w,yaw,from:null,t:0,dur:.3,gait:false}; }); }
  if(M.moving) M.still=0; else M.still+=dt;
  const out={w:[],pitch:[],n:[0,0]}, loc=[];
  const groundL=(l)=>{ const w=toWorld(fig,l.x,0,l.z); return groundW(fig,s,w.x,w.z)-root.position.y; };
  for(let i=0;i<2;i++){ const F=M.feet[i], injured=W>.01&&i===tr.favour, b=beta-(injured?.1*W:0), ph=(M.ph+(i?.5:0))%1;
    const land=V(nom[i].x,0,lerp(nom[i].z,strideLen*b*.42,gw)), s1=.28*gw*(1-rw);   // land a little under the body; the toe roll covers the longer push-off behind
    let heel=0, roll=0, strike=0, swingU=-1;
    if(M.moving){
      // hand-offs keep the ankle where it is: lift off from the rolled-up ankle, and on landing put the anchor (the
      // flat-foot ankle) where the heel-strike pose says it is
      const s0=.28*gw*(1-rw);
      if(F.st==='stance'&&ph>=b){ F.st='swing'; F.from=F.cur?toWorld(fig,F.cur.x,F.cur.y,F.cur.z):F.a.clone(); F.roll0=F.roll||0; F.gait=true; }
      if(F.st==='swing'&&F.gait&&ph<b){ F.st='stance'; F.a=toWorld(fig,F.cur.x,0,F.cur.z-(.05*(Math.cos(s0)-1)-SOLE*Math.sin(s0))); F.a.y=groundW(fig,s,F.a.x,F.a.z)+SOLE; F.yaw=yaw; }
      // the back foot rolls up onto its toes before push-off (pivoting on the toe, so the ankle rises and comes
      // forward a little); the front foot lands on its heel with the toes up and rolls flat
      if(F.st==='stance'&&ph<b){ const u=ph/b; roll=.66*smooth((u-.5)/.5)*(1-.6*rw)*gw; strike=.28*(1-smooth(u/.16))*gw*(1-rw); heel=.13*Math.sin(roll); F.roll=roll; }
    } else if(F.st==='swing'&&F.gait){ F.gait=false; F.t=0; F.dur=.22; F.from=toWorld(fig,F.cur.x,F.cur.y,F.cur.z); }
    if(F.st==='swing'){ const u=F.gait?clamp((ph-b)/(1-b),0,1):clamp((F.t+=dt)/F.dur,0,1); swingU=u;
      const fl=toLocal(fig,F.from), e=smooth(u), c=V(lerp(fl.x,land.x,e),0,lerp(fl.z,land.z,e));
      c.y=lerp(F.from.y-root.position.y,groundL(land)+SOLE+(F.gait?SOLE*(Math.cos(s1)-1)+.05*Math.sin(s1):0),e)+(F.gait?lift:.07)*Math.sin(Math.PI*u); F.cur=c;
      if(!F.gait&&u>=1){ F.st='stance'; F.a=toWorld(fig,c.x,0,c.z); F.a.y=groundW(fig,s,F.a.x,F.a.z)+SOLE; F.yaw=yaw; } }
    // the ankle swings round the contact point: the ball of the foot (0.12 ahead, on the sole) while rolling off,
    // the heel (0.05 behind) while landing; so that point stays where it is on the ground
    // (on a slope the foot's flat pitch is the ground's, so the pivot turns from there)
    if(F.st==='stance'){ const l=toLocal(fig,F.a), g=clamp(Math.atan2(groundL(V(l.x,0,l.z-.07))-groundL(V(l.x,0,l.z+.12)),.19),-.4,.4);
      const R2=(z,y,p)=>[z*Math.cos(p)+y*Math.sin(p),-z*Math.sin(p)+y*Math.cos(p)], piv=(z,y,p)=>{ const a=R2(z,y,g), b2=R2(z,y,g+p); return [a[0]-b2[0],a[1]-b2[1]]; };
      const rb=piv(.12,-SOLE,roll), hs=piv(-.05,-SOLE,-strike); l.y=F.a.y-root.position.y+rb[1]+hs[1]; l.z+=rb[0]+hs[0]; F.cur=l; }
    loc.push(F.cur); out.n[i]=F.cur.z/(R.L*.5); F.u=swingU;
    // foot pitch: flat on its ground, heel up before toe-off, toes up through the swing
    const h1=groundL(V(F.cur.x,0,F.cur.z-.07)), h2=groundL(V(F.cur.x,0,F.cur.z+.12));
    let pitch=F.st==='stance'?clamp(Math.atan2(h1-h2,.19),-.4,.4)+roll-strike:(F.gait?(F.roll0||0)*(1-smooth(swingU/.35))-.28*gw*(1-rw)*smooth((swingU-.55)/.45):0)-.18*Math.sin(Math.PI*clamp(swingU,0,1));
    out.pitch.push(pitch); }
  // standing still: step a foot that is out of place or turned away (one at a time)
  if(!M.moving&&M.feet.every(F=>F.st==='stance')){ let worst=-1, wv=0;
    for(let i=0;i<2;i++){ const F=M.feet[i], e=Math.hypot(loc[i].x-nom[i].x,loc[i].z-nom[i].z), dy=Math.abs(wrap(yaw-F.yaw)), v=Math.max(e/.15,dy/.5,M.still>.35?e/.05:0);
      if(v>1&&v>wv){ wv=v; worst=i; } }
    if(worst>=0&&(M.lastStep===undefined||M.t-M.lastStep>.12)){ const F=M.feet[worst]; F.st='swing'; F.gait=false; F.t=0; F.dur=.26; F.from=F.a.clone(); M.lastStep=M.t; } }
  // pelvis: as high as the action wants, low enough that every foot reaches
  const reach=R.L*(lerp(.997,.993,gw)-.05*rw)-(W>.01?.01:0);
  const minG=Math.min(groundL(V(nom[0].x,0,nom[0].z)),groundL(V(nom[1].x,0,nom[1].z)));
  let by=O.bodyY+minG*(1-gw)+(rw*(.012*tr.bounce*Math.cos(M.ph*TAU*2)-.045))*gw;   // walking: as high as the stance legs allow; a run keeps a little lift
  // only feet bearing weight hold the pelvis down; a swinging foot bends its knee to fit, and only counts as it lands
  for(let i=0;i<2;i++){ const l=loc[i], dx=l.x-(i?1:-1)*R.hipX, room=reach*reach-dx*dx-l.z*l.z, lim=room>0?l.y-R.hipH+Math.sqrt(room):l.y-R.hipH+.05;
    const F=M.feet[i], w=F.st==='stance'?1:smooth((F.u-(.75-.4*rw))/.25); by=Math.min(by,lerp(by,lim,w)); }
  if(W>.01) for(let i=0;i<2;i++) if(i===tr.favour&&M.feet[i].st==='stance') by-=.03*W*gw;
  O.bodyY=by; M.stance=M.feet.map(F=>F.st==='stance');
  out.w=loc.map(l=>toWorld(fig,l.x,l.y,l.z));
  return out; }
function footWorld(fig,M,i){ if(!fig.kn[i].parent) return null; fig.root.updateMatrixWorld(true); const w=fig.kn[i].localToWorld(V(0,-M.R.b,0)); return w; }
// hip (two axes) and knee to put the ankle at a world point; the ankle turns the foot to the wanted pitch
function solveLeg(fig,M,i,w,pitch){ const R=M.R, hips=fig.hips;
  const t=hips.worldToLocal(w.clone()).sub(R.lgP[i]), r=limb(R.a,R.b,t,1,KNEE_POLE[i]);
  fig.lg[i].rotation.set(r.rx,r.ry,r.rz); fig.kn[i].rotation.x=r.e;
  fig.kn[i].updateMatrixWorld(true); setFootPitch(fig,i,pitch); }
function setFootPitch(fig,i,pitch){ const y=fig.root.rotation.y, f=V(Math.sin(y)*Math.cos(pitch),-Math.sin(pitch),Math.cos(y)*Math.cos(pitch));
  fig.kn[i].getWorldQuaternion(_q); f.applyQuaternion(_q.invert()); fig.an[i].rotation.x=clamp(Math.atan2(-f.y,f.z),-.75,.95); }
// shoulder (two axes) and elbow to put the wrist at a world point; the wrist turns the hand along a world direction
function solveArm(fig,M,i,w,axis,weight,palm){ const R=M.R, torso=fig.torso;
  const t=torso.worldToLocal(w.clone()).sub(R.sh[i]), r=limb(R.ua,R.fa,t,-1,ARM_POLE[i]), sh=fig.sh[i], el=fig.el[i];
  sh.rotation.set(lerp(sh.rotation.x,r.rx,weight),lerp(sh.rotation.y,r.ry,weight),lerp(sh.rotation.z,r.rz,weight)); el.rotation.x=lerp(el.rotation.x,r.e,weight);
  const h=fig.hand[i]; if(axis){ el.updateMatrixWorld(true); el.getWorldQuaternion(_q); const inv=_q.clone().invert(), a=axis.clone().applyQuaternion(inv).normalize();
    if(palm){ // hand +y back toward the wrist, the palm side (+x right hand, -x left) toward the grip
      const y=a.clone().multiplyScalar(-1), x=palm.clone().applyQuaternion(inv).multiplyScalar(i?-1:1); x.addScaledVector(y,-x.dot(y)).normalize();
      _m.makeBasis(x,y,V().crossVectors(x,y)); _q2.setFromRotationMatrix(_m); }
    else _q2.setFromUnitVectors(V(0,-1,0),a);
    h.quaternion.slerp(_q2,weight); } else h.quaternion.slerp(_q2.identity(),Math.min(1,weight));
  sh.updateMatrixWorld(true); }

// ---------- weapon: smooth it toward its hold, run its cycles, put the hands on it ----------
// fingers: wrapped round a grip (index on the trigger), pinching a bolt or a clip, holding a load or a tool, fists in
// panic, a loose curl otherwise with a little life in it
function fingers(fig,M,def,actName,dt){ const want=[0,1].map(i=>{ const g=M.grip&&M.grip[i];
    if(g==='grip'){ const spec=M.w.spec.grip[i]; return {curl:1,index:spec.index,thumb:.85,spread:.05}; }
    if(g==='pinch') return {curl:.75,index:.35,thumb:.7,spread:.05};
    if(M.inHand&&i===0) return {curl:1,index:.45,thumb:.85,spread:.05};
    if(actName==='carry') return {curl:.75,thumb:.3,spread:.1};
    if(actName==='work') return {curl:1,thumb:.9,spread:.02};
    if(M.panic>.5) return {curl:1.05,thumb:1,spread:0};
    return {curl:.28+.1*noise(M.t*.3,20+i)+.15*M.wound,thumb:.3,spread:.18}; });
  smoothHands(fig,M,want,dt);
  M.contact=[null,null];
  if(Motion.grasp!==false) for(let i=0;i<2;i++){ if(!(M.w&&(M.grip[i]==='grip'||(M.inHand&&i===0)))){ if(M.gc) M.gc[i]=null; continue; }
    // reuse the last solve while the hand sits the same way on the weapon (within 1.5 mm and about 1.5°) and asks for
    // the same curl; otherwise solve again
    const h=fig.hand[i]; h.updateMatrixWorld(true); const rel=_m.copy(h.matrixWorld).invert().multiply(M.w.g.matrixWorld), e=rel.elements, cu=M.hc[i];
    const key=[e[12],e[13],e[14],e[0],e[1],e[2],e[8],e[9],e[10],cu.curl,cu.index,cu.thumb];
    M.gc=M.gc||[null,null]; const C=M.gc[i];
    if(C&&C.key.every((v,n)=>Math.abs(v-key[n])<(n<3?.0015:.025))){ C.apply(); M.contact[i]=C.out; continue; }
    const out=graspContact(fig,M,i), chains=[...fig.fingers[i],fig.thumbs[i]], rot=chains.map(ch=>ch.map(g=>[g.rotation.y,g.rotation.z]));
    M.gc[i]={key,out,apply(){ chains.forEach((ch,a)=>ch.forEach((g,b)=>{ g.rotation.y=rot[a][b][0]; g.rotation.z=rot[a][b][1]; })); }}; M.contact[i]=out; } }
// ---------- grasping: fingers close on the weapon until they touch it ----------
// The weapon's own parts are the colliders: each mesh's box in its own frame (so a new model brings its own). A finger
// closes joint by joint from the knuckle out: with the joints beyond it straight, a joint turns until its segments
// first touch a part (found by stepping, then bisecting), and stays there; then the next joint closes. A joint that
// meets nothing stops at the curl the hold asked for. The thumb closes the same way.
const _p=V(), _c=V();
function proxies(w){ if(!w.prox){ w.prox=[]; w.g.traverse(o=>{ if(o.isMesh&&!o.userData.ink){ o.geometry.computeBoundingBox(); const bb=o.geometry.boundingBox;
      w.prox.push({o, c:bb.getCenter(V()), h:bb.getSize(V()).multiplyScalar(.5), inv:new THREE.Matrix4(), wc:V(), rad:bb.getSize(V()).length()*.5}); } }); }
  for(const P of w.prox){ P.inv.copy(P.o.matrixWorld).invert(); P.wc.copy(P.c).applyMatrix4(P.o.matrixWorld); } return w.prox; }
// the point where a line from p0 against dir (toward the hand) leaves the parts: the surface the palm rests on
function surfaceAlong(list,p0,dir){ const at=t=>partDist(list,_c.copy(p0).addScaledVector(dir,-t)), st=.004;
  let lo, hi;   // lo: inside or at the part, hi: outside
  if(at(0)<0){ lo=0; hi=st; while(at(hi)<0&&hi<.12){ lo=hi; hi+=st; } }
  else { hi=0; lo=-st; while(at(lo)>=0&&lo>-.08){ hi=lo; lo-=st; } if(at(lo)>=0) return p0.clone(); }
  for(let n=0;n<6;n++){ const m=(lo+hi)/2; if(at(m)<0) lo=m; else hi=m; }
  return p0.clone().addScaledVector(dir,-hi); }
// signed distance from a world point to the nearest part (negative inside)
function partDist(list,pw){ let best=1e9; for(const P of list){ _p.copy(pw).applyMatrix4(P.inv).sub(P.c);
    const qx=Math.abs(_p.x)-P.h.x, qy=Math.abs(_p.y)-P.h.y, qz=Math.abs(_p.z)-P.h.z;
    const d=Math.hypot(Math.max(qx,0),Math.max(qy,0),Math.max(qz,0))+Math.min(Math.max(qx,qy,qz),0); if(d<best) best=d; } return best; }
// how deep segments k.. of a chain sink into the parts (0 when clear)
function chainHit(chain,k,list){ let worst=0; for(let j=k;j<chain.length;j++){ const g=chain[j], S=g.userData.seg;
    for(const t of [.3,.65,1]){ _c.set(0,-S.len*t,0); g.localToWorld(_c); const pen=S.r*.92-partDist(list,_c); if(pen>worst) worst=pen; } } return worst; }
function graspContact(fig,M,i){ const hand=fig.hand[i], c=i?-1:1, out={touch:0,chains:0,pen:0,gap:0};
  hand.updateMatrixWorld(true); const hp=hand.getWorldPosition(V());
  const list=proxies(M.w).filter(P=>P.wc.distanceTo(hp)<P.rad+.16); if(!list.length) return out;
  for(const chain of [...fig.fingers[i],fig.thumbs[i]]){ if(!chain||!chain.length) continue; out.chains++;
    const want=chain.map(g=>Math.abs(g.rotation.z)); let touched=false;
    // the thumb root can also swing round (about its own y) to clear the grip: take the first swing that frees it
    if(chain===fig.thumbs[i]){ const T0=chain[0], y0=T0.rotation.y, side=i?1:-1; chain[1].rotation.z=0;
      for(const dy of [0,.35,.7,1.05,-.35]){ T0.rotation.y=y0+side*-dy; let free=false;
        for(let n=0;n<=8&&!free;n++){ T0.rotation.z=c*(-.9+(want[0]+1.0)*n/8); T0.updateMatrixWorld(true); if(chainHit(chain,0,list)<=0) free=true; }
        if(free) break; }
      T0.rotation.z=c*want[0]; }
    for(let k=0;k<chain.length;k++){ const g=chain[k], lim=want[k]*1.35+.12, set=a=>{ g.rotation.z=c*a; g.updateMatrixWorld(true); };
      for(let j=k+1;j<chain.length;j++) chain[j].rotation.z=0;
      // scan from open (a little back for fingers, well back for the thumb) to past the asked curl: the first free
      // angle starts the search, the first touch after it ends it; with nothing free, keep the least sunk angle
      const open=chain===fig.thumbs[i]?-.9:-.25, N=12; let lo=null, hi=-1, best=want[k], bp=1e9;
      for(let n=0;n<=N;n++){ const a=open+(lim-open)*n/N; set(a); const pen=chainHit(chain,k,list);
        if(pen<=0){ if(lo===null||hi<0) lo=a; } else { if(pen<bp){ bp=pen; best=a; } if(lo!==null){ hi=a; break; } } }
      if(lo===null){ set(best); continue; }
      if(hi<0){ set(Math.max(lo,Math.min(want[k],lim))); continue; }
      for(let n=0;n<5;n++){ const m=(lo+hi)/2; set(m); if(chainHit(chain,k,list)>0) hi=m; else lo=m; }
      set(lo); touched=true; }
    if(touched) out.touch++;
    const tip=chain[chain.length-1], S=tip.userData.seg; _c.set(0,-S.len,0); tip.localToWorld(_c); const d=partDist(list,_c)-S.r;
    out.pen=Math.max(out.pen,chainHit(chain,0,list)); if(touched) out.gap=Math.max(out.gap,Math.max(0,d)); }
  return out; }
function smoothHands(fig,M,want,dt){ if(!M.hc) M.hc=want.map(w=>Object.assign({index:w.curl},w)); const k=Math.min(1,dt*14);
  for(let i=0;i<2;i++){ const h=M.hc[i], w=want[i], wi=w.index===undefined?w.curl:w.index; h.curl+=(w.curl-h.curl)*k; h.index+=(wi-h.index)*k; h.thumb+=(w.thumb-h.thumb)*k; h.spread+=(w.spread-h.spread)*k; setHand(fig,i,h); } }
function weapon(fig,M,s,def,actName,dt){ const w=M.w; M.grip=[null,null];
  if(!w){ for(let i=0;i<2;i++) fig.hand[i].quaternion.slerp(_q.identity(),Math.min(1,dt*8)); return; }
  const spec=w.spec; M.inHand=0;
  let hold=(def.hold||{})[spec.kind]||'low'; if(spec.kind==='rifle'&&hold==='low'&&M.runW>.5) hold='port';
  if(M.wc&&M.wc.type!=='bolt'&&actName!=='reload') M.wc=null;
  if(actName==='reload'&&!M.wc) M.wc={type:spec.kind==='rifle'?'rifleReload':'pistolReload',t:-.6};   // held reload: go again after a pause
  const H=holdTarget(fig,M,hold,s,{});
  // recoil: back and muzzle up, then settle
  if(M.recoil>0){ const r=M.recoil*M.recoil; H.p.add(V(0,0,-spec.back*r).applyQuaternion(H.q)); H.q.multiply(Q().setFromEuler(_e.set(-spec.flip*r,0,0))); }
  const k=1-Math.exp(-dt*(M.inHand?30:12));
  if(!w.pos){ w.pos=H.p.clone(); w.q.copy(H.q); } else { w.pos.lerp(H.p,k); w.q.slerp(H.q,k); }
  if(M.inHand){ w.pos.copy(H.p); w.q.copy(H.q); }
  w.g.position.copy(w.pos); w.g.quaternion.copy(w.q); w.g.updateMatrixWorld(true);
  // carried in the hand: slide the weapon along the palm's normal until its grip rests on the palm
  if(M.inHand&&fig.fingers){ const h=fig.hand[0], palm=V(1,0,0).applyQuaternion(h.getWorldQuaternion(Q())), pc=h.localToWorld(V(0,-.05,0)), g0=w.g.localToWorld(spec.grip[0].p.clone());
    const sfc=surfaceAlong(proxies(w),g0,palm), want=pc.clone().addScaledVector(palm,.0118*(fig.handK||1)), d=palm.dot(want.sub(sfc));
    const shift=toLocal(fig,w.g.getWorldPosition(V()).addScaledVector(palm,d)); w.pos.copy(shift); w.g.position.copy(shift); w.g.updateMatrixWorld(true); }
  // cycles: bolt after a rifle shot, the reloads; the hands follow their timelines, the moving parts follow the hands
  let tgt=[null,null], magOn=false;
  if(M.wc){ const tl=TL[M.wc.type]; M.wc.t+=dt; const tt=M.wc.t;
    for(const [i,key] of [[0,'R'],[1,'L']]) if(tl[key]){ const [a,b,e]=seg(tl[key],tt); tgt[i]=[a,b,e]; }
    if(tl.mag&&tt>tl.mag[0]&&tt<tl.mag[1]) magOn=true;
    if(tt>=tl.dur) M.wc=null; }
  // the bolt or slide
  if(spec.cycle==='bolt'){ let up=0, back=0; if(tgt[0]){ const [a,b,e]=tgt[0], pa=a&&a.w, pb=b&&b.w, at=(P,Pp)=>P===HB1?[1,0]:P===HB2?[1,1]:[0,0];
      const A=pa?at(pa):[0,0], B=pb?at(pb):[0,0]; up=lerp(A[0],B[0],e); back=lerp(A[1],B[1],e); }
    w.bolt.rotation.z=-up*1.25; w.bolt.position.z=-.015-back*.09; }
  else { let back=M.recoil>0?.03*M.recoil:0; if(M.wc&&TL[M.wc.type].rack){ const r=TL[M.wc.type].rack, tt=M.wc.t; if(tt>r[0]&&tt<r[2]) back=.045*(tt<r[1]?smooth((tt-r[0])/(r[1]-r[0])):1-smooth((tt-r[1])/(r[2]-r[1]))); } w.bolt.position.z=-back; }
  // hands
  const resolve=tg=>tg.t?fig.torso.localToWorld(tg.t.clone()):w.g.localToWorld(tg.w.clone());
  for(let i=0;i<2;i++){ const want=H.hands[i]; M.handW[i]+=(want-M.handW[i])*Math.min(1,dt*10);
    const g=spec.grip[i], wq=w.g.getWorldQuaternion(Q()), axisW=g.axis.clone().applyQuaternion(wq), palmW=g.palm&&g.palm.clone().applyQuaternion(wq);
    let gp=w.g.localToWorld(g.p.clone());
    if(tgt[i]){ const [a,b,e]=tgt[i]; const pa=a?resolve(a):gp.clone(), pb=b?resolve(b):gp.clone(); gp=pa.lerp(pb,e); }
    // seat the palm on the grip's surface: from the grip point, find where the part ends on the palm's side
    if(palmW&&!(tgt[i]&&(tgt[i][0]||tgt[i][1]))){ gp=surfaceAlong(proxies(w),gp,palmW).addScaledVector(palmW,-.0118*(fig.handK||1)); }
    const wrist=gp.clone().sub(axisW.clone().multiplyScalar(palmW?.055:.075));
    const hw=tgt[i]?Math.max(M.handW[i],1):M.handW[i];
    const busyHand=tgt[i]&&(tgt[i][0]||tgt[i][1]);
    if(hw>.01) solveArm(fig,M,i,wrist,axisW,clamp(hw,0,1),busyHand?null:palmW); else fig.hand[i].quaternion.slerp(_q.identity(),Math.min(1,dt*8));
    M.grip[i]=busyHand?'pinch':hw>.5?'grip':null;
    if(i===1&&magOn){ w.mag.visible=true; w.mag.position.copy(toLocal(fig,fig.hand[1].localToWorld(V(0,-.09,.02)))); w.mag.quaternion.copy(w.q); } }
  if(!magOn) w.mag.visible=false; }

// ======================================================================================================
// Ragdoll: particles on the joints, held together by distances, dropped under gravity; the skeleton follows
// ======================================================================================================
// particles: pelvis, chest, head, hips R/L, shoulders, elbows, wrists, knees, ankles, toes, and the weapon's grip and muzzle
function startRag(fig,M,s){ fig.root.updateMatrixWorld(true);
  const w=o=>o.getWorldPosition(V()), lw=(o,x,y,z)=>o.localToWorld(V(x,y,z)), R=M.R;
  const pts=[w(fig.hips), lw(fig.torso,0,.3,0), lw(fig.head,0,.12,.01), w(fig.lg[0]), w(fig.lg[1]), w(fig.sh[0]), w(fig.sh[1]), w(fig.el[0]), w(fig.el[1]), w(fig.hand[0]), w(fig.hand[1]),
    w(fig.kn[0]), w(fig.kn[1]), w(fig.an[0]), w(fig.an[1]), lw(fig.an[0],0,-.05,.12), lw(fig.an[1],0,-.05,.12)];
  if(M.w){ pts.push(M.w.g.localToWorld(V(0,0,0)), M.w.g.localToWorld(M.w.spec.muzzle.clone())); }
  const rad=[.11,.12,.1,.08,.08,.07,.07,.05,.05,.04,.04,.06,.06,.05,.05,.03,.03,.03,.03];
  const cons=[]; const C=(a,b,k=1)=>cons.push([a,b,pts[a].distanceTo(pts[b]),k]);
  const trunk=[0,1,3,4,5,6]; for(let i=0;i<trunk.length;i++) for(let j=i+1;j<trunk.length;j++) C(trunk[i],trunk[j]);
  C(2,1); C(2,5,.6); C(2,6,.6); C(2,0,.3); C(5,7); C(7,9); C(6,8); C(8,10); C(3,11); C(11,13); C(13,15); C(11,15); C(4,12); C(12,14); C(14,16); C(12,16);
  if(M.w) C(17,18);
  // velocity: the body's own motion, a shove from the hit (upper body most), knees buckling
  const yaw=fig.root.rotation.y, fwd=V(Math.sin(yaw),0,Math.cos(yaw)), vel=fwd.clone().multiplyScalar(M.v);
  const push=M.hitDir?M.hitDir.clone():fwd.clone().multiplyScalar(-1).applyAxisAngle(V(0,1,0),(M.rr()-.5)*.8);
  const amt=(M.hit>.05?2.6:.9)+M.rr()*.6, up={1:1,2:1.2,5:1,6:1,7:.8,8:.8,9:.6,10:.6,0:.45};
  const prev=pts.map((q,i)=>{ const v=vel.clone().add(push.clone().multiplyScalar(amt*(up[i]||0))); if(i===11||i===12) v.add(fwd.clone().multiplyScalar(.9)); return q.clone().sub(v.multiplyScalar(1/120)); });
  M.rag={pts,prev,rad,cons,t:0,quiet:0,sleep:false,acc:0}; M.feet=null; M.dirty=true; M.wc=null; }
function ragStep(fig,M,s,dt){ const G=M.rag;
  if(!G.sleep){ G.acc+=dt; const h=1/120; let n=0;
    while(G.acc>=h&&n<12){ G.acc-=h; n++; G.t+=h; let maxV=0;
      for(let i=0;i<G.pts.length;i++){ const p=G.pts[i], q=G.prev[i], vx=(p.x-q.x)*.996, vy=(p.y-q.y)*.996, vz=(p.z-q.z)*.996; q.copy(p); p.x+=vx; p.y+=vy-9.8*h*h; p.z+=vz; maxV=Math.max(maxV,Math.hypot(vx,vy,vz)/h); }
      for(let it=0;it<8;it++){ for(const [a,b,L,k] of G.cons){ const A=G.pts[a], B=G.pts[b], dx=B.x-A.x, dy=B.y-A.y, dz=B.z-A.z, d=Math.hypot(dx,dy,dz)||1e-6, f=(d-L)/d*.5*k;
          A.x+=dx*f; A.y+=dy*f; A.z+=dz*f; B.x-=dx*f; B.y-=dy*f; B.z-=dz*f; }
        for(let i=0;i<G.pts.length;i++){ const p=G.pts[i], g=groundW(fig,s,p.x,p.z)+G.rad[i]; if(p.y<g){ p.y=g; const q=G.prev[i]; q.x=lerp(q.x,p.x,.35); q.z=lerp(q.z,p.z,.35); } } }
      G.quiet=maxV<.06?G.quiet+h:0; if(G.quiet>.4||G.t>4) G.sleep=true; } }
  ragPose(fig,M); }
// map the particles back onto the skeleton: the trunk sets the body, the limbs are solved to their particles
function ragPose(fig,M){ const G=M.rag, P=G.pts, R=M.R, root=fig.root;
  const X=P[4].clone().sub(P[3]).normalize(), Y0=P[1].clone().sub(P[0]).normalize(), Z=V().crossVectors(X,Y0).normalize(), Y=V().crossVectors(Z,X);
  _m.makeBasis(X,Y,Z); const qW=Q().setFromRotationMatrix(_m); root.getWorldQuaternion(_q); const qB=_q.clone().invert().multiply(qW);
  fig.body.quaternion.copy(qB); fig.hips.rotation.set(0,0,0); fig.torso.rotation.set(0,0,0);
  const hipsL=root.worldToLocal(P[0].clone()); fig.body.position.copy(hipsL.sub(V(0,R.hipsY,0).applyQuaternion(qB)));
  root.updateMatrixWorld(true);
  const hl=fig.torso.worldToLocal(P[2].clone()); fig.head.rotation.set(clamp(Math.atan2(hl.z-.008,hl.y-.4)*.8,-.6,.6),0,0);
  for(let i=0;i<2;i++){ solveArm(fig,M,i,P[9+i],null,1); fig.hand[i].quaternion.identity();
    const t=fig.hips.worldToLocal(P[13+i].clone()).sub(R.lgP[i]), r=limb(R.a,R.b,t,1,KNEE_POLE[i]); fig.lg[i].rotation.set(r.rx,r.ry,r.rz); fig.kn[i].rotation.x=r.e;
    fig.kn[i].updateMatrixWorld(true); const f=fig.kn[i].worldToLocal(P[15+i].clone()).sub(V(0,-R.b,0)); fig.an[i].rotation.x=clamp(Math.atan2(-f.y,f.z),-.8,1); }
  if(M.w&&P[17]){ const a=P[17], b=P[18], d=b.clone().sub(a).normalize(); const wq=Q().setFromUnitVectors(V(0,0,1),d); root.getWorldQuaternion(_q); M.w.q.copy(_q.clone().invert().multiply(wq)); M.w.pos=root.worldToLocal(a.clone()); M.w.g.position.copy(M.w.pos); M.w.g.quaternion.copy(M.w.q); M.w.mag.visible=false; }
  smoothHands(fig,M,[{curl:.45,thumb:.3,spread:.25},{curl:.45,thumb:.3,spread:.25}],1/60);
  M.out=null; }

// ======================================================================================================
// Clips: get-ups and traversal. A clip is a pose over time in its own frame (origin + yaw): root, hips, body
// rotation, spine, head, and world targets for both ankles and both wrists. It starts from a snapshot of the
// current pose, so nothing pops, and moves the root itself.
// ======================================================================================================
function snapshot(fig,M){ fig.root.updateMatrixWorld(true); const w=o=>o.getWorldPosition(V());
  const bq=fig.body.getWorldQuaternion(Q()), hq=fig.hips.getWorldQuaternion(Q());
  return {hips:w(fig.hips), q:hq, tX:fig.torso.rotation.x, tY:fig.torso.rotation.y, hX:fig.head.rotation.x,
    feet:[0,1].map(i=>fig.kn[i].localToWorld(V(0,-M.R.b,0))), hands:[0,1].map(i=>w(fig.hand[i]))}; }
// keys use the clip frame: +z forward along the clip's yaw, +x to the figure's left, y up from the origin
function frameW(C,v){ return v.clone().applyQuaternion(C.yq).add(C.o); }
function keyed(keys){ // Catmull-Rom through the keys for vectors, smooth blends for scalars, slerp for rotations
  return t=>{ let i=0; while(i<keys.length-2&&t>keys[i+1].t) i++; const A=keys[i], B=keys[i+1], u=clamp((t-A.t)/(B.t-A.t||1),0,1), e=smooth(u);
    const P0=keys[Math.max(0,i-1)], P3=keys[Math.min(keys.length-1,i+2)];
    const cr=(f)=>{ const p0=f(P0), p1=f(A), p2=f(B), p3=f(P3), u2=u*u, u3=u2*u; return V().addScaledVector(p0,-.5*u3+u2-.5*u).addScaledVector(p1,1.5*u3-2.5*u2+1).addScaledVector(p2,-1.5*u3+2*u2+.5*u).addScaledVector(p3,.5*u3-.5*u2); };
    const ln=(f)=>f(A).clone().lerp(f(B),e);
    return {root:ln(k=>k.root), hips:cr(k=>k.hips), q:(A.q||Q()).clone().slerp(B.q||Q(),e), tX:lerp(A.tX||0,B.tX||0,e), tY:lerp(A.tY||0,B.tY||0,e), hX:lerp(A.hX||0,B.hX||0,e),
      feet:[0,1].map(j=>ln(k=>k.feet[j])), hands:[0,1].map(j=>ln(k=>k.hands[j])), fp:[0,1].map(j=>lerp((A.fp||[0,0])[j],(B.fp||[0,0])[j],e)), yaw:lerp(A.yaw||0,B.yaw||0,e)}; }; }
const pitchQ=(p,r=0)=>Q().setFromEuler(_e.set(p,0,r));
function startClip(fig,M,C,fn,dur,blend=.3){ C.yq=qYaw(C.yaw); C.fn=fn; C.dur=dur; C.t=0; C.blend=blend; C.snap=snapshot(fig,M); M.clip=C; M.feet=null; M.dirty=true; M.wc=null; return dur; }
function clipStep(fig,M,s,dt){ const C=M.clip, R=M.R, root=fig.root; C.t=Math.min(C.dur,C.t+dt);
  const k=C.fn(C.t), b=C.blend>0?smooth(C.t/C.blend):1, S=C.snap;
  // world values from the clip frame
  const rootW=frameW(C,k.root), hipsW=frameW(C,k.hips).lerp(S.hips,1-b), qW=C.yq.clone().multiply(k.q); qW.copy(S.q.clone().slerp(qW,b));
  const feetW=k.feet.map((f,i)=>frameW(C,f).lerp(S.feet[i],1-b)), handsW=k.hands.map((h,i)=>frameW(C,h).lerp(S.hands[i],1-b));
  root.position.copy(rootW); root.rotation.set(0,C.yaw+(k.yaw||0),0); root.updateMatrixWorld(true);
  root.getWorldQuaternion(_q); const qB=_q.clone().invert().multiply(qW);
  fig.body.quaternion.copy(qB); fig.body.position.copy(root.worldToLocal(hipsW.clone()).sub(V(0,R.hipsY,0).applyQuaternion(qB)));
  fig.hips.rotation.set(0,0,0); fig.torso.rotation.set(lerp(S.tX,k.tX,b),lerp(S.tY,k.tY,b),0); fig.head.rotation.set(lerp(S.hX,k.hX,b),0,0);
  root.updateMatrixWorld(true);
  for(let i=0;i<2;i++){ const t=fig.hips.worldToLocal(feetW[i].clone()).sub(R.lgP[i]), r=limb(R.a,R.b,t,1,KNEE_POLE[i]); fig.lg[i].rotation.set(r.rx,r.ry,r.rz); fig.kn[i].rotation.x=r.e; fig.kn[i].updateMatrixWorld(true); setFootPitch(fig,i,k.fp[i]); }
  for(let i=0;i<2;i++){ solveArm(fig,M,i,handsW[i],null,1); fig.hand[i].quaternion.identity(); }
  const hand=C.hand||{curl:.9,thumb:.8,spread:.05}; smoothHands(fig,M,[hand,hand],dt);
  // weapon: slung while climbing, picked back up after a get-up
  if(M.w){ const H=holdTarget(fig,M,M.w.spec.kind==='rifle'?'sling':'holster',s,{}), kk=1-Math.exp(-dt*6); if(!M.w.pos) M.w.pos=H.p.clone(); M.w.pos.lerp(H.p,kk); M.w.q.slerp(H.q,kk); M.w.g.position.copy(M.w.pos); M.w.g.quaternion.copy(M.w.q); M.handW=[0,0]; }
  if(C.t>=C.dur){ M.clip=null; const end=frameW(C,C.endRoot||k.root); root.position.copy(end); root.rotation.set(0,C.yaw+(C.endYaw||0),0);
    M.lx=end.x; M.lz=end.z; M.feet=null; M.j=Object.assign({},ACTS.idle.pose); M.act=null; if(C.done) C.done(); }
  M.out=null; }
function clean(fig,M){ fig.body.quaternion.identity(); fig.body.position.set(0,fig.body.position.y,0); fig.hips.rotation.set(0,0,0); M.dirty=false; }

// ---------- get-ups ----------
// from the back: sit up, tuck the feet in, push off the ground with a hand, stand. From the front: push up onto hands
// and knees, bring one foot forward, stand. The clip frame sits where the figure will stand.
function startRise(fig,M,s){ const G=M.rag, P=G.pts, R=M.R; M.rag=null;
  const X=P[4].clone().sub(P[3]).normalize(), Y=P[1].clone().sub(P[0]).normalize(), Z=V().crossVectors(X,Y).normalize();
  const onBack=Z.y>0, head=P[1].clone().sub(P[0]); head.y=0; const hd=head.normalize();
  // standing up facing away from the head (back) or toward it (front)
  const face=onBack?hd.clone().multiplyScalar(-1):hd.clone(), yaw=Math.atan2(face.x,face.z);
  const feetMid=P[13].clone().add(P[14]).multiplyScalar(.5), pel=P[0].clone();
  const spot=onBack?pel.clone().lerp(feetMid,.75):pel.clone().add(hd.clone().multiplyScalar(.25));
  spot.y=groundW(fig,s,spot.x,spot.z);
  const C={o:spot, yaw}, H0=R.hipH, hx=R.hipX, g=(x,z)=>groundW(fig,s,spot.x+x*Math.cos(yaw)+z*Math.sin(yaw),spot.z-x*Math.sin(yaw)+z*Math.cos(yaw))-spot.y;
  const F=(x,z,lift=0)=>V(x,g(x,z)+SOLE+lift,z);
  let keys;
  if(onBack) keys=[
    {t:.0, root:V(), hips:V(0,.14,-.75), q:pitchQ(-1.45), tX:0, hX:-.1, feet:[F(-hx,.05),F(hx,.05)], hands:[V(-.3,.06,-.9),V(.3,.06,-.9)]},
    {t:.55, root:V(), hips:V(0,.13,-.62), q:pitchQ(-.15), tX:.55, hX:.15, feet:[F(-hx,.02),F(hx,.12)], hands:[V(-.28,.06,-.75),V(.25,.35,-.25)]},
    {t:1.0, root:V(), hips:V(0,.3,-.35), q:pitchQ(0), tX:.85, hX:.1, feet:[F(-hx-.02,-.05),F(hx,.1)], hands:[V(-.25,.06,-.55),V(.2,.42,.05)]},
    {t:1.45, root:V(), hips:V(0,.55,-.12), q:pitchQ(0), tX:.65, hX:-.05, feet:[F(-hx,-.05),F(hx,.08)], hands:[V(-.22,.45,-.1),V(.22,.5,.12)]},
    {t:1.9, root:V(), hips:V(0,H0-.02,0), q:pitchQ(0), tX:.05, hX:.06, feet:[F(-hx,0),F(hx,0)], hands:[V(-.2,H0-.12,0),V(.2,H0-.12,0)]}];
  else keys=[
    {t:.0, root:V(), hips:V(0,.16,-.5), q:pitchQ(1.45), tX:0, hX:-.2, feet:[F(-hx,-1.25),F(hx,-1.25)], hands:[V(-.3,.06,.15),V(.3,.06,.15)]},
    {t:.5, root:V(), hips:V(0,.45,-.55), q:pitchQ(.15), tX:1.25, hX:-.6, feet:[F(-hx,-.95,.0),F(hx,-.95,.0)], hands:[V(-.22,.06,.15),V(.22,.06,.15)]},
    {t:1.0, root:V(), hips:V(0,.5,-.35), q:pitchQ(.1), tX:.6, hX:-.2, feet:[F(-hx,.2),F(hx,-.75,.08)], hands:[V(-.18,.45,.25),V(.22,.25,.0)]},
    {t:1.5, root:V(), hips:V(0,H0-.2,-.1), q:pitchQ(0), tX:.35, hX:0, feet:[F(-hx,.15),F(hx,-.15)], hands:[V(-.2,.55,.2),V(.2,.55,.05)]},
    {t:1.9, root:V(), hips:V(0,H0-.02,0), q:pitchQ(0), tX:.05, hX:.06, feet:[F(-hx,0),F(hx,0)], hands:[V(-.2,H0-.12,0),V(.2,H0-.12,0)]}];
  C.hand={curl:.12,thumb:.15,spread:.3};
  return startClip(fig,M,C,keyed(keys),1.9,.45); }

// ---------- traversal ----------
// spec: {type, x, z, yaw, height, depth?, ground?}
//   vault  a low wall (up to ~1.2 m): (x,z) is the base of its near face, yaw the way over, depth its thickness
//   climb  a ledge (1–2.2 m): (x,z) the base of its face, height the top; ends standing on top
//   ladder up a ladder to a top: (x,z) the foot of the ladder, height the top; ends standing on top past the edge
//   descend down a ladder from a top: (x,z) the foot of the ladder, yaw facing the ladder from below (as for 'ladder')
//   drop   step off an edge: (x,z) the edge on the ground below, height of the top above it
// The figure should already stand near the start (about 0.4 m before the face or edge, facing yaw). Returns the duration.
function traverse(fig,spec,state){ const M=fig.motion||init(fig); if(M.clip||M.rag) return 0; const s=state||{};
  const R=M.R, H0=R.hipH, hx=R.hipX, yaw=spec.yaw, h=spec.height||1;
  // the ground the move starts from: just before the face (the face itself is the top of the obstacle)
  const gy=Number.isFinite(spec.y)?spec.y:groundW(fig,s,spec.x-Math.sin(yaw)*.3,spec.z-Math.cos(yaw)*.3);
  const C={o:V(spec.x,gy,spec.z), yaw, done:spec.done}, rp=toFrame(C,fig.root.position);
  const F=(x,y,z)=>V(x,y+SOLE,z), stand=(z,y=0)=>({hips:V(0,y+H0-.02,z), feet:[F(-hx,y,z),F(hx,y,z)]});
  let keys, dur;
  if(spec.type==='vault'){ const d=spec.depth||.25;
    keys=[{t:0, root:rp, ...stand(rp.z), q:pitchQ(0), tX:.1, hands:[V(-.25,H0-.15,rp.z+.1),V(.25,H0-.15,rp.z+.1)]},
      {t:.28, root:V(0,0,-.2), hips:V(0,H0-.12,-.32), q:pitchQ(.15), tX:.55, hX:-.3, feet:[F(-hx,0,-.25),F(hx,0,-.45)], hands:[V(-.12,h,.06),V(.3,h,.04)], fp:[0,.3]},
      {t:.52, root:V(0,0,d*.5), hips:V(.12,h+.38,d*.4), q:pitchQ(.2,-.35), tX:.45, hX:-.25, feet:[F(.42,h+.05,d*.2),F(.45,h+.02,d*.55)], hands:[V(-.1,h,d*.4),V(.35,h+.25,d+.2)], fp:[-.2,-.2]},
      {t:.78, root:V(0,0,d+.5), hips:V(0,H0-.32,d+.55), q:pitchQ(.25), tX:.4, hX:-.15, feet:[F(-hx,0,d+.62),F(hx,0,d+.45)], hands:[V(-.3,H0-.2,d+.8),V(.3,H0-.15,d+.7)]},
      {t:1.05, root:V(0,0,d+.85), ...stand(d+.85), q:pitchQ(0), tX:.08, hands:[V(-.2,H0-.12,d+.85),V(.2,H0-.12,d+.85)]}]; dur=1.05; }
  else if(spec.type==='climb'){
    keys=[{t:0, root:rp, ...stand(rp.z), q:pitchQ(0), hands:[V(-.2,H0-.12,rp.z),V(.2,H0-.12,rp.z)]},
      {t:.35, root:V(0,0,-.35), hips:V(0,H0-.15,-.38), q:pitchQ(-.05), tX:-.1, hX:-.35, feet:[F(-hx,0,-.36),F(hx,0,-.3)], hands:[V(-.22,h,.03),V(.22,h,.03)], fp:[.2,.2]},
      {t:.8, root:V(0,h*.4,-.25), hips:V(0,h-.72,-.26), q:pitchQ(.1), tX:.15, hX:-.2, feet:[F(-hx,h-1.05,-.14),F(hx,h-.8,-.13)], hands:[V(-.22,h,.04),V(.22,h,.04)], fp:[.4,.4]},
      {t:1.2, root:V(0,h,-.1), hips:V(0,h+.18,-.08), q:pitchQ(.6), tX:.6, hX:-.3, feet:[F(-hx,h-.6,-.13),F(hx,h,.1)], hands:[V(-.22,h,.12),V(.22,h,.12)], fp:[.4,0]},
      {t:1.6, root:V(0,h,.3), hips:V(0,h+.55,.25), q:pitchQ(.1), tX:.7, hX:-.1, feet:[F(-hx,h,.35),F(hx,h,.25)], hands:[V(-.25,h+.45,.5),V(.25,h+.4,.45)]},
      {t:2.0, root:V(0,h,.45), ...stand(.45,h), q:pitchQ(0), tX:.06, hands:[V(-.2,h+H0-.12,.45),V(.2,h+H0-.12,.45)]}]; dur=2.0; }
  else if(spec.type==='drop'){ const fall=Math.sqrt(2*Math.max(.2,h-.3)/9.8);
    keys=[{t:0, root:rp, ...stand(rp.z,h), q:pitchQ(0), hands:[V(-.2,h+H0-.12,rp.z),V(.2,h+H0-.12,rp.z)]},
      {t:.3, root:V(0,h,-.1), hips:V(0,h+H0-.1,-.12), q:pitchQ(.05), tX:.15, feet:[F(-hx,h,-.12),F(hx,h-.05,.18)], hands:[V(-.3,h+H0,0),V(.3,h+H0,0)], fp:[.3,-.1]},
      {t:.3+fall, root:V(0,0,.5), hips:V(0,H0-.4,.5), q:pitchQ(.15), tX:.45, hX:-.1, feet:[F(-hx,0,.58),F(hx,0,.48)], hands:[V(-.3,H0-.3,.75),V(.3,H0-.3,.75)]},
      {t:.55+fall, root:V(0,0,.55), hips:V(0,H0-.5,.52), q:pitchQ(.2), tX:.55, hX:-.05, feet:[F(-hx,0,.58),F(hx,0,.48)], hands:[V(-.3,H0-.45,.85),V(.3,H0-.45,.8)]},
      {t:1.05+fall, root:V(0,0,.6), ...stand(.6), q:pitchQ(0), tX:.06, hands:[V(-.2,H0-.12,.6),V(.2,H0-.12,.6)]}];
    C.o.y=gy; dur=1.05+fall; }
  else if(spec.type==='ladder'||spec.type==='descend'){ const fn=ladderFn(R,h); dur=fn.dur;
    const f=spec.type==='ladder'?fn:(t=>fn(fn.dur-t));   // down is the climb played backward: facing the ladder, the drop behind
    return startClip(fig,M,C,f,dur,.35); }
  if(!keys) return 0;
  return startClip(fig,M,C,keyed(keys),dur,.2); }
function toFrame(C,w){ const d=w.clone().sub(C.o); return d.applyQuaternion(qYaw(-C.yaw)); }
// a ladder at z=0 rising to a top at height h, rungs every 0.3 m: hands on the rails, feet on the rungs, each limb
// holding while its diagonal partner moves (right hand with left foot); then over the top onto the floor behind it
function ladderFn(R,h){ const H0=R.hipH, hx=R.hipX, RUNG=.3, v=.55, z0=-.38, climbTop=h+.15-(H0-.12), tc=Math.max(.1,climbTop)/v, tIn=.4, tTop=1.4, dur=tIn+tc+tTop;
  const step=(p,off,base)=>{ const q=(p-off)/(2*RUNG), f=q-Math.floor(q); return base+2*RUNG*(Math.floor(q)+smooth((f-.5)/.5)); };
  const snap=y=>Math.max(RUNG,Math.round(y/RUNG)*RUNG);
  const hipsEnd=H0-.12+climbTop, top=keyed([
    {t:0, root:V(0,hipsEnd-H0,z0), hips:V(0,hipsEnd,z0+.02), q:pitchQ(-.05), tX:.12, hX:-.15}, {t:.5, root:V(0,h,-.1), hips:V(0,h+.28,-.16), q:pitchQ(.5), tX:.5, hX:-.25}, {t:.95, root:V(0,h,.3), hips:V(0,h+.5,.25), q:pitchQ(.1), tX:.65},
    {t:tTop, root:V(0,h,.5), hips:V(0,h+H0-.02,.5), q:pitchQ(0), tX:.06}].map(k=>Object.assign({feet:[V(),V()],hands:[V(),V()],q:Q(),hips:V()},k)));
  const fn=t=>{ const tt=Math.max(0,t-tIn), p=Math.min(climbTop,tt*v), hipsY=H0-.12+p;
    const handY=[step(p,0,snap(H0+.6)),step(p,RUNG,snap(H0+.6)+RUNG)], footY=[step(p,RUNG,RUNG),step(p,0,2*RUNG)];
    const base={root:V(0,hipsY-H0,z0), hips:V(0,hipsY,z0+.02), q:pitchQ(-.05), tX:.12, tY:0, hX:-.15, yaw:0,
      hands:[V(-.2,Math.min(h,handY[0]),-.05),V(.2,Math.min(h,handY[1]),-.05)], feet:[V(-hx,footY[0]+.07,-.15),V(hx,footY[1]+.07,-.15)], fp:[.1,.1]};
    if(t<tIn){ const e=smooth(t/tIn); base.hips.z=lerp(z0+.05,z0+.02,e); }
    if(t<=tIn+tc) return base;
    // over the top: hands on the edge, a knee up, stand on the floor behind it
    const u=t-tIn-tc, K=top(u), e=smooth(u/tTop), e1=smooth(u/.6), e2=smooth((u-.4)/.6);
    K.hands=[V(-.22,h+.0,lerp(-.05,.1,e1)).lerp(V(-.2,h+H0-.12,.5),smooth((u-.9)/.5)),V(.22,h+.0,lerp(-.05,.1,e1)).lerp(V(.2,h+H0-.12,.5),smooth((u-.9)/.5))];
    K.feet=[base.feet[0].clone().lerp(V(-hx,h+SOLE,.12),e1).lerp(V(-hx,h+SOLE,.5),e2), base.feet[1].clone().lerp(V(hx,h+SOLE+.05,-.05),e1).lerp(V(hx,h+SOLE,.5),smooth((u-.6)/.5))];
    K.root=base.root.clone().lerp(V(0,h,.5),e); K.hips=base.hips.clone().lerp(K.hips,smooth(u/.5)); K.fp=[0,0]; K.yaw=0; return K; };
  fn.dur=dur; return fn; }

// ---------- one-off impulses from the runtime ----------
// kick(fig,'hit',k,{from:{x,z}}) flinches away from the shooter; kick(fig,'recoil') fires: kicks the weapon back,
// and a bolt-action rifle then works its bolt
function kick(fig,what,k=1,opt={}){ const M=fig.motion||init(fig);
  if(what==='hit'){ M.hit=Math.min(1.2,Math.max(M.hit,k)); M.hitSide=M.rr()<.5?-1:1;
    if(opt.from){ const p=fig.root.position; M.hitDir=V(p.x-opt.from.x,0,p.z-opt.from.z).normalize(); const loc=toLocal(fig,V(opt.from.x,0,opt.from.z)); M.hitSide=loc.x>0?-1:1; } else M.hitDir=null; }
  else if(what==='recoil'){ M.recoil=Math.min(1.5,M.recoil+k); if(M.w&&M.w.spec.cycle==='bolt'&&!M.wc) M.wc={type:'bolt',t:-.18}; } }
function reset(fig){ const M=fig.motion; if(!M) return; M.lx=fig.root.position.x; M.lz=fig.root.position.z; M.v=0; M.feet=null; }
const busy=fig=>!!(fig.motion&&(fig.motion.clip||fig.motion.rag));

const reduce=typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
return {grasp:true, _grasp:{proxies,partDist,chainHit}, update, kick, reset, arm, traverse, busy, setHand, traits, seedOf, ACTS, KEYS, BOUND, WEAPONS, reduce, _limb:limb, _fk:fk};
})();
