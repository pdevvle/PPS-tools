// ---------- Motion: procedural movement for FigureKit figures ----------
// One call per figure per frame: Motion.update(fig, state, dt), after the runtime has placed fig.root (position on the
// ground, yaw for heading). Three layers, as in mockups/procedural-motion.html:
//   1. traits fixed per person by seed: stride, arm swing, posture, bounce, how they stand;
//   2. every time an action starts, its joint angles are rolled inside per-joint bounds;
//   3. smooth noise keeps held poses alive; wounds and panic widen and speed it up.
// Legs are solved, not posed: the gait advances by the distance the root really moved, stance feet stay where they
// were put down, and both feet sit on the ground (via state.ground) on slopes and steps.
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
// legs: 'plant' (stand or walk, feet solved to the ground) or 'free' (posed as is: swim, fall)
// arms: 'swing' (natural arm swing while moving), 'hold' (the pose's arms, with a little bob)
const P=o=>Object.assign({bodyY:0,torsoX:0,torsoY:0,headX:.06,shRx:.02,shRz:-.12,elR:-.12,shLx:.02,shLz:.12,elL:-.12,lgR:0,knR:0,lgL:0,knL:0},o);
const READY_ARMS={shRx:-.55,shRz:-.2,elR:-1.35,shLx:-1.05,shLz:.35,elL:-.95};
const AIM_ARMS={shRx:-1.45,shRz:-.1,elR:-.12,shLx:-1.25,shLz:.4,elL:-.55};
const ACTS={
  idle:   {pose:P({}),                                                                                     legs:'plant', arms:'swing', roll:.4},
  walk:   {pose:P({torsoX:.05}),                                                                           legs:'plant', arms:'swing', roll:.4},
  run:    {pose:P({torsoX:.18,headX:-.06}),                                                                legs:'plant', arms:'swing', roll:.4, run:1},
  ready:  {pose:P(Object.assign({bodyY:-.05,torsoX:.14,torsoY:.15,headX:-.05,lgR:-.42,knR:.75,lgL:.12,knL:.3},READY_ARMS)), legs:'plant', arms:'hold', roll:.6},
  'crouch-walk':{pose:P(Object.assign({bodyY:-.26,torsoX:.42,torsoY:.08,headX:-.3,lgR:-.9,knR:1.5,lgL:-.2,knL:1.1},READY_ARMS)), legs:'plant', arms:'hold', roll:.7, crouch:1},
  crouch: {pose:P({bodyY:-.3,torsoX:.38,torsoY:.1,headX:-.25,shRx:-.95,shRz:-.12,elR:-1.25,shLx:-1.1,shLz:.2,elL:-1.1,lgR:-1.2,knR:1.75,lgL:-.35,knL:1.25}), legs:'plant', arms:'hold', roll:1, crouch:1},
  aim:    {pose:P(Object.assign({bodyY:-.04,torsoX:.1,torsoY:.15,headX:0,lgR:-.35,knR:.6,lgL:.15,knL:.3},AIM_ARMS)), legs:'plant', arms:'hold', roll:.35, steady:1},
  shoot:  {pose:P(Object.assign({bodyY:-.04,torsoX:.1,torsoY:.15,headX:0,lgR:-.35,knR:.6,lgL:.15,knL:.3},AIM_ARMS)), legs:'plant', arms:'hold', roll:.35, steady:1},
  reload: {pose:P({bodyY:-.04,torsoX:.16,torsoY:.1,headX:.22,lgR:-.35,knR:.6,lgL:.15,knL:.3,shRx:-.85,shRz:-.15,elR:-1.15,shLx:-1.05,shLz:.3,elL:-.95}), legs:'plant', arms:'hold', roll:.5, cycle:'reload'},
  hunker: {pose:P({bodyY:-.38,lgR:-1.2,knR:1.7,lgL:-.5,knL:1.9,torsoX:.55,headX:.2,shRx:-.8,shRz:-.3,elR:-1.6,shLx:-.9,shLz:.35,elL:-1.5}), legs:'plant', arms:'hold', roll:1, crouch:1},
  hit:    {pose:P({bodyY:-.06,torsoX:-.2,headX:-.15,shRz:-.45,shLz:.45,elR:-.6,elL:-.6,lgR:-.2,knR:.4,lgL:.1,knL:.3}), legs:'plant', arms:'hold', roll:1.2},
  carry:  {pose:P({torsoX:-.06,headX:.1,shRx:-.7,shRz:-.28,elR:-1.15,shLx:-.7,shLz:.28,elL:-1.15}),        legs:'plant', arms:'hold', roll:.5, stride:.8},
  work:   {pose:P({bodyY:-.08,torsoX:.4,headX:.25,lgR:-.4,knR:.5,lgL:.2,knL:.25,shRx:-.7,shRz:-.15,elR:-.5,shLx:-.9,shLz:.15,elL:-.4}), legs:'plant', arms:'hold', roll:.8, cycle:'dig'},
  swim:   {pose:P({torsoX:.35,headX:-.25,shRz:-.5,shLz:.5,elR:-.4,elL:-.4,knR:.3,knL:.3}),                legs:'free',  arms:'hold', roll:.3, cycle:'swim'},
  fall:   {pose:P({bodyY:0,torsoX:-.1,headX:-.2,shRx:.1,shRz:-1.05,elR:-.1,shLx:-.2,shLz:1.15,elL:-.3,lgR:-.25,knR:.35,lgL:.1,knL:.15}), legs:'free', arms:'hold', roll:1.5, fall:1},
};
ACTS.dead=ACTS.fall;
// per-joint bounds for one roll (radians; bodyY in metres), scaled by the action's roll
const BOUND={bodyY:.03,torsoX:4*D,torsoY:7*D,headX:7*D,shRx:8*D,shRz:6*D,elR:10*D,shLx:8*D,shLz:6*D,elL:10*D,lgR:7*D,knR:9*D,lgL:7*D,knL:9*D};
// held weapon: the right arm carries it, so a steady action rolls the arms less (sway comes from the Aim stat, not cosmetics)
const ARMKEYS=new Set(['shRx','shRz','elR','shLx','shLz','elL']);

// ---------- the rig: measured from the figure itself ----------
function rig(fig){ const lg=fig.lg[0], kn=fig.kn[0];
  const hipH=fig.hips.position.y+lg.position.y, a=-kn.position.y, b=hipH-SOLE-a;
  return {hipH, a, b, L:a+b, hipX:Math.abs(lg.position.x)}; }
// ankle relative to the hip joint for a thigh angle and a knee bend: positive angles swing the limb backward (-z)
const fk=(R,th,kn)=>({y:-(R.a*Math.cos(th)+R.b*Math.cos(th+kn)), z:-(R.a*Math.sin(th)+R.b*Math.sin(th+kn))});
// two-bone solve in the leg's plane; the knee always bends forward
function ik(R,dy,dz){ let d=Math.hypot(dy,dz); const lo=Math.abs(R.a-R.b)+1e-4, hi=R.L*.9995; d=clamp(d,lo,hi);
  const psi=Math.atan2(-dz,-dy), al=Math.acos(clamp((R.a*R.a+d*d-R.b*R.b)/(2*R.a*d),-1,1)), kb=Math.acos(clamp((R.a*R.a+R.b*R.b-d*d)/(2*R.a*R.b),-1,1));
  return {th:psi-al, kn:Math.PI-kb}; }

function init(fig){ const seed=seedOf(fig), M={seed, tr:traits(seed), R:rig(fig), rr:rng(Math.imul(seed,31)+7), j:Object.assign({},ACTS.idle.pose),
    ph:rng(seed)()*1, v:0, lx:fig.root.position.x, lz:fig.root.position.z, gaitW:0, runW:0, act:null, actT:0, roll:{}, t:rng(seed+3)()*50,
    wound:0, panic:0, hit:0, hitSide:1, recoil:0, fall:0, fallDir:-1, moving:false};
  fig.motion=M; return M; }
function rollFor(M,def){ const o={}, k=def.roll||0; for(const key of KEYS){ const s=def.steady&&ARMKEYS.has(key)?.3:1; o[key]=(M.rr()*2-1)*BOUND[key]*k*s; } return o; }

// ground height relative to the root under a point given in the root's frame
function groundRel(fig,s,lx,lz){ const yaw=fig.root.rotation.y, c=Math.cos(yaw), si=Math.sin(yaw), p=fig.root.position;
  if(s.ground){ const g=s.ground(p.x+lx*c+lz*si, p.z-lx*si+lz*c); return Number.isFinite(g)?g-p.y:0; }
  return s.slope?s.slope*lz:0; }

// ---------- the update ----------
// state: 'walk' or {act, mood:'calm'|'wounded'|'panicked', ground:(x,z)=>y, slope, compress, look, lookAt:{x,z}}
//   act      one of Motion.ACTS; walking or running is picked from the measured speed, act only says what the body does
//   ground   height of the ground at a world point, so each foot finds its own footing (else slope, else flat)
//   compress how much faster than real time the runtime moves people; gait shape follows the real speed, cadence the shown one
//   look     yaw to turn the upper body toward, relative to the body (or lookAt, a world point)
function update(fig,state,dt){
  const s=typeof state==='string'?{act:state}:(state||{}), M=fig.motion||init(fig), R=M.R, tr=M.tr;
  dt=Math.max(0,Math.min(dt||0,.1)); M.t+=dt;
  const actName=ACTS[s.act]?s.act:'idle', def=ACTS[actName];
  if(actName!==M.act){ const was=ACTS[M.act||'idle'];
    if(def.fall&&!was.fall) M.fallDir=M.rr()<.35?1:-1;
    if(def.legs==='free'&&was.legs==='plant'&&M.out) for(const k of ['bodyY','lgR','knR','lgL','knL']) M.j[k]=M.out[k];   // start from where the legs really were
    M.act=actName; M.actT=0; M.roll=rollFor(M,def); } else M.actT+=dt;
  // ground speed from how far the root really moved (a jump of more than 2 m is a teleport)
  const p=fig.root.position; let dist=Math.hypot(p.x-M.lx,p.z-M.lz); M.lx=p.x; M.lz=p.z; if(dist>2) dist=0;
  const vi=dt>0?dist/dt:0; M.v+=(vi-M.v)*Math.min(1,dt*8);
  const comp=s.compress||1, vr=M.v/comp;
  M.moving=M.moving?vr>.08:vr>.18;
  const mood=s.mood||'calm', quiet=Motion.reduce?.3:1;
  M.wound+=((mood==='wounded'?1:0)-M.wound)*Math.min(1,dt*2); M.panic+=((mood==='panicked'?1:0)-M.panic)*Math.min(1,dt*3);
  const W=M.wound, Pn=M.panic;

  // ---- target pose: action base + roll + traits + mood + the action's own cycle ----
  const T={}; for(const k of KEYS) T[k]=def.pose[k]+(M.roll[k]||0);
  T.torsoX+=tr.slouch; T.headX+=tr.head-tr.slouch*.6; T.shRz-=tr.width; T.shLz+=tr.width;
  if(W>0){ T.torsoX+=.14*W; T.headX+=.12*W; T.bodyY-=.03*W;   // slumped, one arm held to the side
    if(def.arms==='swing'){ const side=tr.favour; if(side) { T.shLx=lerp(T.shLx,-.45,W); T.shLz=lerp(T.shLz,.05,W); T.elL=lerp(T.elL,-1.7,W); } else { T.shRx=lerp(T.shRx,-.45,W); T.shRz=lerp(T.shRz,-.05,W); T.elR=lerp(T.elR,-1.7,W); } } }
  if(Pn>0){ T.torsoX+=.12*Pn; T.headX-=.14*Pn; T.bodyY-=.05*Pn; if(def.arms==='swing'){ T.shRz=lerp(T.shRz,-.04,Pn); T.shLz=lerp(T.shLz,.04,Pn); T.elR-=.7*Pn; T.elL-=.7*Pn; T.shRx-=.3*Pn; T.shLx-=.3*Pn; } }
  if(def.cycle==='reload'){ const c=(M.actT%1.6)/1.6, down=smooth(c/.3)*(1-smooth((c-.6)/.3));   // left hand to the belt and back, gun tipped
    T.shLx=lerp(T.shLx,.15,down); T.shLz=lerp(T.shLz,.22,down); T.elL=lerp(T.elL,-.7,down); T.shRx+=.12*Math.sin(c*TAU); T.headX+=.1*down; }
  if(def.cycle==='dig'){ const c=M.actT/1.5*TAU, sw=Math.sin(c);   // swing down, lift, swing down
    T.torsoX+=.22*sw; T.headX+=.08*sw; T.shRx+=-.45*sw; T.shLx+=-.45*sw; T.elR+=.25*Math.cos(c); T.elL+=.25*Math.cos(c); T.bodyY+=-.04*(sw*.5+.5); }
  if(def.cycle==='swim'){ const t=M.t*2.2; Object.assign(T,{shRx:-1.4+Math.sin(t)*1.3,shLx:-1.4-Math.sin(t)*1.3,lgR:Math.sin(t*2)*.35,lgL:-Math.sin(t*2)*.35}); }
  // look: the spine turns toward it (FigureKit has no neck yaw yet)
  let look=s.look||0; if(s.lookAt){ look=wrap(Math.atan2(s.lookAt.x-p.x,s.lookAt.z-p.z)-fig.root.rotation.y); }
  T.torsoY+=clamp(look,-1.2,1.2)*.55;
  // layer 3: idle noise on top, wider and quicker with wounds and panic, damped while moving
  const amp=quiet*tr.fidget*(1+W*1.4+Pn*1.8)*(M.moving?.45:1)*(def.steady?.5:1), sp=1+W*1.2+Pn*2.2, t=M.t;
  T.headX+=noise(t*.6*sp,1)*6*D*amp; T.torsoX+=noise(t*.45*sp,2)*2.5*D*amp+Math.sin(t*(1.6+Pn*1.8))*.006*(1+Pn);
  T.torsoY+=noise(t*.3*sp,4)*5*D*amp*(1+Pn*1.5); T.shRz+=noise(t*.5*sp,5)*3*D*amp; T.shLz+=noise(t*.5*sp,6)*3*D*amp; T.bodyY+=noise(t*.4,7)*.006*amp;
  const shift=noise(t*.18*sp,8)*amp;   // weight shift, felt in the stance below

  // ---- layer blend: transitions between actions ----
  const rate=def.fall?7:actName==='hit'?16:9, k=1-Math.exp(-dt*rate);
  for(const key of KEYS) M.j[key]+=(T[key]-M.j[key])*k;
  const O=Object.assign({},M.j);

  // ---- legs ----
  const fallE=M.fall=clamp(M.fall+(def.fall?dt/.75:-dt*2),0,1);
  if(def.legs==='plant'&&fallE<1){
    M.gaitW+=((M.moving?1:0)-M.gaitW)*Math.min(1,dt*7);
    const wantRun=(def.run?1:0)||(vr>2.3&&!def.crouch?1:0); M.runW+=(wantRun-M.runW)*Math.min(1,dt*4);
    const rw=M.runW, gw=M.gaitW, cr=def.crouch?1:0;
    // stride length for the real speed; the gait phase moves by the distance actually covered, so feet don't slide
    const strideLen=clamp(R.L*(.8+.5*Math.min(vr,4))*tr.stride*(def.stride||1)*(cr?.75:1)*(1-.22*W)*(1-.12*Pn),R.L*.7,R.L*3.2);
    M.ph=(M.ph+dist/strideLen)%1;
    const beta=.6-.24*rw, lift=(.06+.04*Math.min(1,vr/1.5))*(cr?.8:1)+.16*rw, legs=[];
    for(let i=0;i<2;i++){ const side=i?1:-1, hx=side*R.hipX*(1+tr.toe);
      // standing: the pose's own foot placement, weight shifted by noise
      const th=i?O.lgL:O.lgR, kn=i?O.knL:O.knR, sf=fk(R,th,kn);
      let sz=sf.z+(i===tr.favour?1:-1)*shift*.02, sy=SOLE+groundRel(fig,s,hx,sz);
      // walking: stance foot fixed on the ground while the body passes over it, swing foot lifts and goes ahead
      const injured=W>.01&&i===tr.favour, b=beta-(injured?.1*W:0), ph=(M.ph+(i?.5:0))%1;
      let gz, gl;
      if(ph<b){ const u=ph/b; gz=strideLen*b*(.5-u); gl=.045*smooth((u-.62)/.38)*(1-rw); }   /* heel comes up before toe-off */ else { const u=(ph-b)/(1-b); gz=strideLen*b*(-.5+smooth(u)); gl=lift*Math.sin(Math.PI*u); }
      const gy=SOLE+groundRel(fig,s,hx,gz)+gl;
      legs.push({z:lerp(sz,gz,gw), y:lerp(sy,gy,gw), stance:ph<b, injured, lift:gl*gw}); }
    // pelvis: as high as the action wants, but low enough that every foot reaches the ground
    const reach=R.L*(lerp(.997,.985,gw)-.05*rw)-(W>.01?.01:0);   // nearly straight standing, softer knees walking
    let by=lerp(O.bodyY+Math.min(legs[0].y,legs[1].y)-SOLE, O.bodyY-Math.abs(Math.sin(M.ph*TAU))*.012*tr.bounce*(1+rw), gw);
    for(const l of legs){ const room=reach*reach-l.z*l.z; if(room>0) by=Math.min(by,l.y-R.hipH+Math.sqrt(room)); }
    if(W>.01) for(const l of legs) if(l.injured&&l.stance) by-=.03*W*gw;   // dips onto the bad leg
    O.bodyY=by;
    const sol=legs.map(l=>ik(R,l.y-(R.hipH+by),l.z));
    O.lgR=sol[0].th; O.knR=sol[0].kn; O.lgL=sol[1].th; O.knL=sol[1].kn; M.stance=legs.map(l=>l.stance||gw<.5);
    // arms swing against the legs while moving
    const sw=gw*Math.min(1.3,vr/1.4+.15)*(def.arms==='swing'?1:.15)*(1-.5*W)*(1-.6*Pn), n0=legs[0].z/(R.L*.5), n1=legs[1].z/(R.L*.5);
    O.shRx+=n0*.3*tr.swing*sw*(1+rw*.6); O.shLx+=n1*.3*tr.swing*sw*(1+rw*.6);
    if(def.arms==='swing'){ O.elR-=(.12+.2*tr.swing)*gw+rw*1.0; O.elL-=(.12+.2*tr.swing)*gw+rw*1.0; }
    O.torsoX+=rw*.12*gw+.05*gw*Math.min(1,vr/1.4); O.torsoY+=(n1-n0)*.04*gw*(1+rw);
  } else { M.gaitW=0; M.runW=0; }

  // ---- impulses: hits and recoil ----
  if(M.hit>0){ const h=M.hit*M.hit; O.torsoX-=.45*h; O.headX-=.3*h; O.torsoY+=M.hitSide*.25*h; O.shRz-=.3*h; O.shLz+=.3*h; O.bodyY-=.04*h; M.hit=Math.max(0,M.hit-dt*2.2); }
  if(M.recoil>0){ const r=M.recoil; O.shRx+=.25*r; O.shLx+=.18*r; O.torsoX-=.06*r; O.headX-=.05*r; M.recoil=Math.max(0,M.recoil-dt*5); }

  // ---- falling: the whole body tips over its feet, faster as it goes, with a small bounce at the end ----
  const fe=fallE*fallE;
  fig.body.rotation.x=M.fallDir*(Math.PI/2-.08)*fe*(1+(fallE>.85&&fallE<1?.04*Math.sin((fallE-.85)/.15*Math.PI):0));
  if(fe>0){ O.bodyY=lerp(O.bodyY,.11,fe); }

  M.out=O; FigureKit.applyPose(fig,O);
  return M; }

// one-off impulses from the runtime
function kick(fig,what,k=1){ const M=fig.motion||init(fig);
  if(what==='hit'){ M.hit=Math.min(1.2,Math.max(M.hit,k)); M.hitSide=M.rr()<.5?-1:1; }
  else if(what==='recoil'){ M.recoil=Math.min(1.5,M.recoil+k); } }
function reset(fig){ const M=fig.motion; if(!M) return; M.lx=fig.root.position.x; M.lz=fig.root.position.z; M.v=0; }

const reduce=typeof matchMedia==='function'&&matchMedia('(prefers-reduced-motion: reduce)').matches;
return {update, kick, reset, traits, seedOf, ACTS, KEYS, BOUND, reduce, _rig:rig, _fk:fk, _ik:ik};
})();
