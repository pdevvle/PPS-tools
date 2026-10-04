// Parts are boxes in the item's frame: x along the wall, z out from the wall (front at z = d), y up.
// [x0,y0,z0, sx,sy,sz, colour, o]. o is optional:
//   rx, ry, rz  turn the box about its own centre
//   yaw, tilt, roll, pv:[px,pz], lift  turn a group of boxes about a pivot on the floor (yaw about y, then tilt about x, roll about z)
// Colour 'glass' goes to the see-through batch.
const PAL={
  wood:['#8a6a4a','#6e5038','#a07a52','#b48a5c','#5a4030','#9c6b43','#c19a6b'],
  fab:['#2f8f8a','#b5543a','#c9953f','#7d8f62','#7a2e35','#3f5f86','#d8c7a3','#6b4f7a','#a3473a','#4f7c6e'],
  cab:['#efe9dc','#8a6a4a','#7d8f62','#3f5f86','#a07a52','#d8cdb6','#5f6f73','#b5543a'],
  top:['#cfc6b4','#3b3a38','#d9d2c3','#8c8478','#b9a98c','#e8e4da'],
  paint:['#e9e1d0','#e6d3b3','#d9e0cf','#ecd6c7','#d4e4e2','#f0e7d4','#e3c9a8','#e8d9b0','#d6c6d6'],
  adobe:['#d8a77a','#c98b62','#e3bf8f','#cf9a6e','#b8d4cf','#e0c08e'],
  appl:['#eeeeea','#c9ccce','#2b2c2e','#e6dcc4','#b9bec2'],
  car:['#8c3b2f','#3f5f86','#d8d2c4','#2b2c2e','#7d8f62','#b9a06a','#9aa1a6','#6e1a10','#c9953f','#4f7c6e'],
  product:['#c9693a','#5a8bb0','#d1b04a','#7a2e35','#3f8f5a','#e8e4da','#2f8f8a','#b5543a','#6b4f7a','#e0a526','#3b3a38','#d94f3d'],
  vinyl:['#9e2b25','#2f8f8a','#7a2e35','#c9953f','#3f5f86'],
  rug:[['#b5543a','#e8d9b0','#2b2c2e','#2f8f8a'],['#7a2e35','#d8c7a3','#3f5f86','#c9953f'],['#a3473a','#efe3c8','#4f3a2a','#7d8f62'],['#c9693a','#f0e7d4','#3b3a38','#b8d4cf']],
};
const STEEL='#b8bcbf', STEELD='#7d8285', BLACK='#232324', WHITE='#ece8de', CHROME='#d7dadc', RUST='#7a4a2c', TERRA='#b5653f';
function jit(col,r,a){ const c=new THREE.Color(col); const h={}; c.getHSL(h); c.setHSL((h.h+(r()-.5)*a*.25+1)%1,clamp(h.s+(r()-.5)*a,0,1),clamp(h.l+(r()-.5)*a,0,1)); return '#'+c.getHexString(); }
function noise2(seed){
  const h=hash32(seed);
  const lat=(x,y)=>{ let n=(Math.imul(x,374761393)+Math.imul(y,668265263)+h)|0; n=Math.imul(n^(n>>>13),1274126177); return ((n^(n>>>16))>>>0)/4294967296; };
  return (x,y)=>{ const xi=Math.floor(x),yi=Math.floor(y),xf=x-xi,yf=y-yi,u=xf*xf*(3-2*xf),v=yf*yf*(3-2*yf); const a=lat(xi,yi),b=lat(xi+1,yi),c=lat(xi,yi+1),d=lat(xi+1,yi+1); return a+(b-a)*u+(c-a)*v+(a-b-c+d)*u*v; };
}
const B=(x0,y0,z0,sx,sy,sz,col,o)=>[x0,y0,z0,sx,sy,sz,col,o];
const withO=(parts,o)=>parts.map(p=>{ const q=p.slice(); q[7]=Object.assign({},o,p[7]||{}); return q; });

// ---- shared pieces
function handle(out,x,y,z,vert,col,o){ out.push(vert?B(x-.012,y-.08,z,.024,.16,.03,col,o):B(x-.07,y-.012,z,.14,.024,.03,col,o)); }
// Hinged doors on a front face at z = zf. state: 0 shut, 1 ajar or open, 2 hanging off one hinge, 3 gone
function doors(out,K,x0,x1,y0,y1,zf,n,col,hcol){
  const w=(x1-x0)/n;
  for(let k=0;k<n;k++){
    const a=x0+k*w+.006, b=x0+(k+1)*w-.006, left=n===1?K.r()<.5:k%2===0;
    const st=K.doorState();
    if(st===3){ // torn off: lies on the floor in front
      out.push(B(a,.01,zf+.15+K.r()*.3,b-a,.02,y1-y0-.012,col,{ry:(K.r()-.5)*.8})); continue; }
    const hx=left?a:b, sgn=left?1:-1;
    let o;
    if(st===1) o={yaw:sgn*(.5+K.r()*1.1),pv:[hx,zf]};
    if(st===2) o={yaw:sgn*(.3+K.r()*.5),pv:[hx,zf],roll:sgn*(.12+K.r()*.2)};
    out.push(B(a,y0+.006,zf,b-a,y1-y0-.012,.02,col,o));
    handle(out,left?b-.05:a+.05,(y0+y1)/2,zf+.02,true,hcol,o);
  }
}
// Drawers: rows × cols. Pulled-out drawers stick out; some lie on the floor.
function drawers(out,K,x0,x1,y0,y1,zf,rows,cols,col,hcol){
  const w=(x1-x0)/cols, h=(y1-y0)/rows;
  for(let r=0;r<rows;r++) for(let c=0;c<cols;c++){
    const a=x0+c*w+.006, y=y0+r*h+.006, ww=w-.012, hh=h-.012;
    const st=K.drawerState();
    if(st===2){ const fz=zf+.3+K.r()*.4, fx=a+(K.r()-.5)*.3; out.push(B(fx,.01,fz,ww,Math.min(hh,.16),.4,jit(col,K.r,.06),{ry:(K.r()-.5)*1.4})); out.push(B(fx+.05,.17,fz+.08,.2,.04,.15,pick(K.r,PAL.product),{ry:K.r()*3})); continue; }
    const pull=st===1?.15+K.r()*.25:0;
    out.push(B(a,y,zf+pull,ww,hh,.02,col));
    if(pull){ out.push(B(a+.02,y+.01,zf+pull-.38,.015,hh*.8,.38,'#b49a78')); out.push(B(a+ww-.035,y+.01,zf+pull-.38,.015,hh*.8,.38,'#b49a78')); }
    handle(out,a+ww/2,y+hh/2,zf+pull+.02,false,hcol);
  }
}
function chair(out,K,cx,cz,dir,opt){
  const yaw=Math.atan2(-dir[0],dir[1])+(opt.yawJ||0);
  const down=opt.down;
  const o={yaw,pv:[cx,cz]};
  if(down===1){ o.tilt=-Math.PI/2; o.pv=[cx,cz-.24]; } // on its back
  if(down===2){ o.roll=(K.r()<.5?1:-1)*Math.PI/2; o.pv=[cx,cz]; o.lift=.21; } // on its side
  const s=opt.style||'wood', c=opt.col, seat=opt.seat||c, leg=s==='diner'?CHROME:c;
  const x=cx-.21, z=cz-.21, P=[];
  if(s==='stool'){ P.push(B(cx-.03,0,cz-.03,.06,.72,.06,CHROME)); P.push(B(cx-.18,.72,cz-.18,.36,.06,.36,seat)); P.push(B(cx-.18,.72,cz-.18,.36,.06,.36,seat,{ry:Math.PI/4})); P.push(B(cx-.2,.25,cz-.2,.4,.02,.4,CHROME,{ry:Math.PI/4})); out.push(...withO(P,o)); return; }
  for(const [lx,lz] of [[0,0],[.38,0],[0,.38],[.38,.38]]) P.push(B(x+lx,0,z+lz,.04,.44,.04,leg));
  if(s==='wood') P.push(B(x+.02,.18,z+.02,.38,.02,.02,leg),B(x+.02,.18,z+.38,.38,.02,.02,leg));
  P.push(B(x-.01,.44,z-.01,.44,.05,.44,seat));
  if(s==='wood'){ P.push(B(x,.49,z,.04,.5,.04,c),B(x+.38,.49,z,.04,.5,.04,c)); for(let k=0;k<3;k++) P.push(B(x+.04,.62+k*.13,z+.005,.34,.06,.025,c)); }
  else if(s==='diner'){ P.push(B(x+.03,.49,z,.025,.42,.025,CHROME),B(x+.36,.49,z,.025,.42,.025,CHROME),B(x+.02,.62,z-.015,.38,.28,.06,seat)); }
  else P.push(B(x,.49,z-.02,.42,.52,.08,seat),B(x,.49,z-.04,.42,.52,.02,c));
  out.push(...withO(P,o));
}
function rug(out,K,cx,cz,w,d){
  const cols=pick(K.r,PAL.rug), yaw=(K.r()-.5)*.25, o={yaw,pv:[cx,cz]};
  const P=[B(cx-w/2,.004,cz-d/2,w,.012,d,cols[0])];
  const bands=5; for(let k=0;k<bands;k++){ const zz=cz-d/2+.12+k*(d-.24)/bands; P.push(B(cx-w/2+.12,.016,zz,w-.24,.006,(d-.24)/bands*.45,cols[1+k%3])); }
  P.push(B(cx-.18,.02,cz-.18,.36,.004,.36,cols[2],{ry:Math.PI/4}));
  out.push(...withO(P,o));
}
// Clutter for the floor: cans, papers, broken glass, a box
function litter(out,K,x0,z0,w,d,n){
  for(let k=0;k<n;k++){ const x=x0+K.r()*w, z=z0+K.r()*d, t=K.r();
    if(t<.35) out.push(B(x,.005,z,.21,.004,.28,pick(K.r,['#efe9dc','#e8e1cf','#d9d2c3']),{ry:K.r()*3}));
    else if(t<.6) out.push(B(x,0,z,.07,.12,.07,pick(K.r,PAL.product),{rz:K.r()<.6?Math.PI/2:0,ry:K.r()*3}));
    else if(t<.8) out.push(B(x,0,z,.3,.18+K.r()*.1,.24,'#b49a78',{ry:K.r()*3,rz:K.r()<.3?.5:0}));
    else out.push(B(x,.002,z,.12,.004,.08,'glass',{ry:K.r()*3})); }
}
function products(out,K,x0,x1,y,z0,z1,h){ // a row of goods on a shelf
  let x=x0+.02;
  while(x<x1-.08){ const w=(x1-x0>2?.2:.12)+K.r()*.16; if(x+w>x1) break; if(K.r()>K.gone){ const hh=h*(.45+K.r()*.5); out.push(B(x,y,z0+(z1-z0-.0)*K.r()*.15,w-.01,hh,(z1-z0)*.8,pick(K.r,PAL.product),K.r()<K.mess*.3?{rz:Math.PI/2*(K.r()<.5?1:-1)*.9}:undefined)); } x+=w+.04; }
}
function cabinetBox(out,K,x0,x1,h,z1,col){ // carcass with toe kick
  out.push(B(x0,0,.02,x1-x0,.1,z1-.08,'#3a3330'));
  out.push(B(x0,.1,0,x1-x0,h-.1,z1,col));
}

// ---- the kit
const IT={
  sofa:{w:3,d:1,h:.85,cover:'half',build(K,o){ const f=K.st.fab, P=[];
    P.push(B(.08,0,.1,2.84,.08,.8,BLACK));
    P.push(B(0,.08,.08,.16,.55,.84,K.j(f,.04)),B(2.84,.08,.08,.16,.55,.84,K.j(f,.04)),B(.16,.08,.05,2.68,.3,.85,K.j(f,.04)));
    for(let k=0;k<3;k++){ const ruin=K.r()<K.mess*.4; P.push(B(.17+k*.89,.38,.12,.87,.13,.75,K.j(f,.08),ruin?{rx:.3,ry:(K.r()-.5)*.6}:undefined)); P.push(B(.17+k*.89,.4,.05,.87,.45,.2,K.j(f,.08),{rx:-.12})); }
    for(let k=0;k<2;k++) if(K.r()<.8) P.push(B(.35+K.r()*2,.5,.24,.36,.34,.12,K.j(K.st.fab2,.1),{ry:(K.r()-.5)*.8,rx:-.3}));
    if(K.r()<K.mess*.5) P.push(B(.4+K.r()*2,.01,1.05+K.r()*.3,.85,.12,.7,K.j(f,.08),{ry:(K.r()-.5)*1.2}));
    return P; }},
  armchair:{w:1,d:1,h:.85,cover:'half',build(K){ const f=K.j(K.st.fab2,.06), P=[];
    P.push(B(.05,.06,.08,.14,.55,.82,f),B(.81,.06,.08,.14,.55,.82,f),B(.19,.06,.08,.62,.32,.82,f),B(.19,.38,.12,.62,.12,.72,K.j(f,.06)),B(.19,.4,.05,.62,.45,.18,f,{rx:-.15}));
    for(const x of [.08,.86]) for(const z of [.12,.8]) P.push(B(x,0,z,.05,.06,.05,BLACK));
    if(K.r()<K.mess*.5) return withO(P,{tilt:-Math.PI/2,pv:[.5,.12],yaw:(K.r()-.5)*.8});
    return withO(P,{yaw:(K.r()-.5)*.5,pv:[.5,.5]}); }},
  tvstand:{w:2,d:1,h:.6,cover:'half',slot:'media',build(K){ const P=[]; const w=K.st.wood;
    P.push(B(.2,0,.05,1.6,.55,.45,w)); doors(P,K,.22,1.78,.06,.5,.5,2,K.j(w,.08),STEELD);
    P.push(B(.95,.55,.12,.1,.05,.18,BLACK));
    const tvDown=K.r()<K.mess*.5;
    const tv=[B(.35,.6,.18,1.3,.78,.06,BLACK),B(.4,.65,.24,1.2,.68,.005,tvDown?'#4a4d50':'#202833')];
    P.push(...(tvDown?withO(tv,{tilt:Math.PI/2,pv:[1,.2],yaw:.3}):tv));
    P.push(B(1.5,.55,.15,.25,.07,.2,'#2b2c2e'));
    return P; }},
  coffee:{w:2,d:1,h:.45,cover:'none',build(K){ const P=[]; rug(P,K,1,.5,2.6,1.8); const w=K.st.wood;
    const T=[B(.3,.38,.2,1.4,.05,.6,w),B(.35,0,.25,.05,.38,.05,w),B(1.6,0,.25,.05,.38,.05,w),B(.35,0,.7,.05,.38,.05,w),B(1.6,0,.7,.05,.38,.05,w),B(.38,.12,.24,1.24,.02,.52,K.j(w,.1))];
    T.push(B(.6,.43,.35,.3,.03,.22,pick(K.r,PAL.product),{ry:.3}),B(1.25,.43,.4,.08,.1,.08,WHITE));
    P.push(...(K.r()<K.mess*.45?withO(T,{roll:Math.PI/2,pv:[1,.5],lift:.7}):T)); litter(P,K,0,-.2,2,1.4,Math.round(K.mess*5)); return P; }},
  bookcase:{w:2,d:1,h:1.9,cover:'full',slot:'bookcase',build(K){ const w=K.st.wood, P=[];
    P.push(B(.1,0,.04,.04,1.9,.34,w),B(1.86,0,.04,.04,1.9,.34,w),B(.1,1.86,.04,1.8,.04,.34,w),B(.14,0,.04,1.72,1.88,.02,K.j(w,.1)));
    for(let k=0;k<5;k++){ const y=.02+k*.37; P.push(B(.14,y,.06,1.72,.03,.32,w)); let x=.16; while(x<1.8){ const bw=.03+K.r()*.05; if(K.r()>K.gone){ const bh=.2+K.r()*.1; P.push(B(x,y+.03,.1,bw,bh,.2+K.r()*.06,pick(K.r,PAL.product),K.r()<.12?{rz:.25}:undefined)); } x+=bw+.003; } }
    for(let k=0;k<Math.round(K.mess*7);k++) P.push(B(.1+K.r()*1.6,.003,.45+K.r()*.6,.15,.04,.22,pick(K.r,PAL.product),{ry:K.r()*3}));
    if(K.r()<K.mess*.3) return withO(P,{tilt:Math.PI/2*.92,pv:[1,.38],lift:.02});
    return P; }},
  dtable:{w:2,d:2,h:.75,cover:'half',build(K){ const P=[]; diningSet(P,K,{size:1.4,long:1.0,legs:true,seats:[[0,1],[0,-1],[1,0],[-1,0]],style:'wood',col:K.st.wood,center:true}); return P; }},
  hutch:{w:2,d:1,h:1.85,cover:'full',slot:'hutch',build(K){ const w=K.st.wood, P=[];
    cabinetBox(P,K,.15,1.85,.85,.45,w); drawers(P,K,.17,1.83,.65,.83,.45,1,2,K.j(w,.08),'#c9a24a'); doors(P,K,.17,1.83,.1,.63,.45,2,K.j(w,.08),'#c9a24a');
    P.push(B(.12,.85,.0,1.76,.04,.5,K.j(w,.06)),B(.2,.89,.02,1.6,.94,.3,w),B(.18,1.83,0,1.64,.06,.36,K.j(w,.06)));
    for(let k=0;k<2;k++){ const y=1.1+k*.35; P.push(B(.22,y,.04,1.56,.02,.26,w)); for(let p=0;p<5;p++) if(K.r()>K.gone) P.push(B(.3+p*.3,y+.02,.2,.2,.2,.02,pick(K.r,['#e8e4da','#2f8f8a','#b5543a','#d8c7a3']))); }
    if(K.r()>K.mess*.6) P.push(B(.22,.92,.31,.77,.88,.01,'glass'),B(1.01,.92,.31,.77,.88,.01,'glass')); else P.push(B(.1+K.r()*1.4,.002,.6+K.r()*.4,.25,.004,.2,'glass',{ry:K.r()*3}));
    return P; }},
  counter:{w:1,d:1,h:.92,cover:'half',slot:'cabinet',build(K){ const P=[], c=K.st.cab;
    cabinetBox(P,K,0,1,.88,.6,c); drawers(P,K,.02,.98,.7,.86,.6,1,1,K.j(c,.05),CHROME); doors(P,K,.02,.98,.12,.68,.6,1,K.j(c,.05),CHROME);
    P.push(B(-.01,.88,0,1.02,.04,.64,K.st.top));
    if(K.wallBack){ P.push(B(0,1.45,0,1,.72,.34,c)); doors(P,K,.02,.98,1.46,2.15,.34,K.r()<.5?1:2,K.j(c,.05),CHROME); P.push(B(0,.92,0,1,.5,.01,K.st.splash)); }
    const t=K.r();
    if(t<.16){ P.push(B(.15,.92,.08,.5,.3,.36,K.st.appl),B(.2,.97,.43,.32,.2,.01,BLACK)); } // microwave
    else if(t<.3){ P.push(B(.55,.92,.1,.2,.3,.18,BLACK),B(.58,.92,.25,.12,.12,.1,'glass')); } // coffee maker
    else if(t<.42){ P.push(B(.3,.92,.15,.26,.18,.15,CHROME)); } // toaster
    else if(t<.52){ P.push(B(.2,.92,.35,.3,.08,.3,'#d9d2c3'),B(.25,1.0,.4,.08,.08,.08,'#c9953f'),B(.36,1.0,.42,.08,.07,.08,'#a3473a')); } // fruit bowl, long gone off
    else if(t<.6){ P.push(B(.7,.92,.1,.12,.25,.14,'#3a3330')); }
    if(K.r()<K.mess*.5) litter(P,K,0,.65,1,.6,2);
    return P; }},
  sinkc:{w:1,d:1,h:.92,cover:'half',slot:'sink',build(K){ const P=[], c=K.st.cab;
    cabinetBox(P,K,0,1,.88,.6,c); P.push(B(.02,.72,.6,.96,.14,.02,K.j(c,.05))); doors(P,K,.02,.98,.12,.7,.6,2,K.j(c,.05),CHROME);
    P.push(B(-.01,.88,0,1.02,.04,.64,K.st.top),B(.15,.9,.12,.7,.03,.42,STEELD),B(.2,.86,.16,.6,.05,.34,'#4a4d50'));
    P.push(B(.47,.92,.04,.05,.3,.05,CHROME),B(.47,1.18,.04,.05,.04,.2,CHROME));
    if(K.r()<.6) P.push(B(.25,.88,.25,.22,.06,.22,pick(K.r,['#e8e4da','#7a2e35','#3f5f86'])));
    return P; }},
  dw:{w:1,d:1,h:.92,cover:'half',build(K){ const P=[]; const a=K.st.appl;
    P.push(B(0,0,.02,1,.1,.52,'#3a3330'),B(.02,.1,0,.96,.78,.6,a),B(.04,.74,.6,.92,.12,.02,K.j(a,.04)),B(.2,.66,.62,.6,.03,.04,CHROME),B(-.01,.88,0,1.02,.04,.64,K.st.top));
    if(K.r()<K.mess*.5) P.push(B(.04,.12,.62,.92,.6,.03,a,{tilt:Math.PI/2*.95,pv:[.5,.62,.12]}));
    return P; }},
  stove:{w:1,d:1,h:.95,cover:'half',build(K){ const P=[], a=K.st.appl;
    P.push(B(.04,0,0,.92,.9,.64,a),B(.08,.15,.64,.84,.55,.02,K.j(a,.04)),B(.22,.3,.66,.56,.24,.005,BLACK),B(.15,.62,.66,.7,.03,.04,CHROME),B(.04,.9,0,.92,.02,.64,BLACK));
    for(const [x,z] of [[.25,.18],[.65,.18],[.25,.45],[.65,.45]]) P.push(B(x-.1,.92,z-.1,.2,.02,.2,'#3a3a3a'));
    P.push(B(.04,.92,0,.92,.16,.06,K.j(a,.04))); for(let k=0;k<4;k++) P.push(B(.15+k*.2,.98,.06,.05,.05,.03,BLACK));
    if(K.r()<.5) P.push(B(.15,.94,.1,.26,.12,.26,'#4a4d50'),B(.41,1.0,.2,.18,.02,.03,BLACK));
    if(K.wallBack) P.push(B(.05,1.55,0,.9,.4,.38,K.j(a,.04)),B(.1,1.6,.38,.62,.3,.01,BLACK),B(.78,1.6,.38,.12,.3,.01,'#5a5c5e'));
    if(K.r()<K.mess*.5) P.push(B(.08,.15,.64,.84,.55,.02,a,{tilt:Math.PI/2*.9,pv:[.5,.66,.15]}));
    return P; }},
  fridge:{w:1,d:1,h:1.8,cover:'full',slot:'fridge',build(K){ const P=[], a=K.st.appl;
    P.push(B(.06,0,.02,.88,1.78,.66,a),B(.08,.04,.04,.84,.06,.62,BLACK));
    const fd=K.r()<.5;
    if(fd){ // freezer on top
      P.push(B(.07,1.25,.68,.86,.52,.03,K.j(a,.03)));
      const op=K.doorState(); const o=op?{yaw:-(.4+K.r()*1.2),pv:[.07,.68]}:undefined;
      P.push(B(.07,.12,.68,.86,1.1,.03,K.j(a,.03),o),B(.85,.5,.71,.03,.5,.04,CHROME,o),B(.85,1.3,.71,.03,.3,.04,CHROME));
      if(op){ P.push(B(.1,.3,.1,.8,.02,.58,'#d8dde0'),B(.1,.7,.1,.8,.02,.58,'#d8dde0')); for(let k=0;k<3;k++) if(K.r()>K.gone) P.push(B(.15+k*.22,.32,.2,.12,.16,.12,pick(K.r,PAL.product))); }
    } else { // side by side
      P.push(B(.07,.12,.68,.42,1.65,.03,K.j(a,.03)),B(.51,.12,.68,.42,1.65,.03,K.j(a,.03)),B(.45,.7,.71,.03,.6,.04,CHROME),B(.53,.7,.71,.03,.6,.04,CHROME),B(.15,1.1,.71,.2,.28,.01,'#3a3a3a'));
    }
    for(let k=0;k<3;k++) if(K.r()<.6) P.push(B(.12+K.r()*.6,1.6+K.r()*.1,.69,.08,.1,.005,pick(K.r,PAL.product)));
    if(K.r()<.4) P.push(B(.2,1.8,.15,.3,.2,.3,pick(K.r,PAL.product)));
    return P; }},
  island:{w:2,d:1,h:.92,cover:'half',slot:'cabinet',build(K){ const P=[], c=K.st.cab;
    P.push(B(.12,0,.14,1.76,.1,.72,'#3a3330'),B(.1,.1,.12,1.8,.78,.76,c)); doors(P,K,.12,1.88,.12,.86,.12,3,K.j(c,.05),CHROME);
    P.push(B(.04,.88,.06,1.92,.04,.94,K.st.top));
    for(let k=0;k<2;k++) chair(P,K,.55+k*.9+(K.r()-.5)*.15,1.05+K.r()*.25,[0,-1],{style:'stool',seat:K.st.fab2,yawJ:(K.r()-.5)*.8,down:K.down()?2:0});
    return P; }},
  bed2:{w:2,d:2,h:1.0,cover:'half',build(K){ return bedParts(K,1.6); }},
  bed1:{w:1,d:2,h:.9,cover:'half',build(K){ return bedParts(K,.9); }},
  nightstand:{w:1,d:1,h:.6,cover:'none',slot:'nightstand',build(K){ const P=[], w=K.st.wood;
    P.push(B(.25,0,.05,.5,.56,.42,w),B(.23,.56,.04,.54,.03,.44,K.j(w,.06))); drawers(P,K,.27,.73,.32,.52,.47,1,1,K.j(w,.06),'#c9a24a');
    const L=[B(.32,.59,.12,.12,.04,.12,'#c9953f'),B(.36,.63,.16,.04,.3,.04,'#c9953f'),B(.27,.88,.07,.22,.18,.22,'#efe3c8')];
    P.push(...(K.r()<K.mess*.6?withO(L,{roll:Math.PI/2,pv:[.4,.4],lift:.14}):L));
    if(K.r()<.5) P.push(B(.55,.59,.15,.14,.03,.2,pick(K.r,PAL.product)));
    return P; }},
  dresser:{w:2,d:1,h:.85,cover:'half',slot:'dresser',build(K){ const P=[], w=K.st.wood;
    P.push(B(.2,0,.04,1.6,.82,.48,w),B(.18,.82,.03,1.64,.03,.5,K.j(w,.06))); drawers(P,K,.22,1.78,.06,.8,.52,3,2,K.j(w,.06),'#c9a24a');
    if(K.r()<.6) P.push(B(.5,.85,.1,1,.8,.03,'#a8b8bd',K.r()<K.mess?{rz:.2}:undefined));
    for(let k=0;k<3;k++) if(K.r()<.6) P.push(B(.3+K.r()*1.3,.85,.15+K.r()*.2,.08,.1+K.r()*.1,.08,pick(K.r,PAL.product)));
    return P; }},
  wardrobe:{w:2,d:1,h:2.0,cover:'full',slot:'wardrobe',build(K){ const P=[], w=K.st.wood;
    P.push(B(.08,0,.02,1.84,2.0,.58,w),B(.06,1.98,0,1.88,.05,.62,K.j(w,.06)),B(.12,.05,.6,1.76,.06,.02,K.j(w,.1)));
    doors(P,K,.1,1.9,.12,1.96,.6,2,K.j(w,.06),'#c9a24a');
    for(let k=0;k<5;k++) P.push(B(.25+k*.3,.9,.3,.06,.95,.2+K.r()*.1,pick(K.r,PAL.fab)));
    for(let k=0;k<Math.round(K.mess*4);k++) P.push(B(K.r()*1.6+.1,.003,.65+K.r()*.4,.45,.05,.35,pick(K.r,PAL.fab),{ry:K.r()*3}));
    return P; }},
  toilet:{w:1,d:1,h:.8,cover:'none',build(K){ const P=[];
    P.push(B(.3,.38,.04,.4,.4,.18,WHITE),B(.28,.78,.03,.44,.04,.21,K.j(WHITE,.04)),B(.36,0,.24,.28,.4,.4,WHITE),B(.31,.36,.22,.38,.05,.5,WHITE));
    const lid=K.r()<.5?{tilt:-Math.PI/2*.85,pv:[.5,.24,.41]}:undefined; P.push(B(.31,.41,.24,.38,.02,.48,K.j(WHITE,.06),lid));
    if(K.r()<.6) P.push(B(.78,.6,.02,.06,.12,.12,WHITE));
    return P; }},
  vanity:{w:1,d:1,h:.9,cover:'half',slot:'vanity',build(K){ const P=[], c=K.st.cab;
    cabinetBox(P,K,.06,.94,.84,.55,c); doors(P,K,.08,.92,.12,.8,.55,2,K.j(c,.05),CHROME);
    P.push(B(.04,.84,0,.92,.04,.58,K.st.top),B(.25,.86,.15,.5,.03,.32,WHITE),B(.47,.88,.03,.05,.22,.05,CHROME));
    const broken=K.r()<K.mess*.5;
    P.push(B(.12,1.2,.0,.76,.7,.06,'#a08c72')); P.push(B(.15,1.23,.06,.7,.64,.005,broken?'#6c7a7e':'#bcd0d6'));
    if(broken) for(let k=0;k<3;k++) P.push(B(.2+K.r()*.6,.01,.6+K.r()*.3,.1,.004,.07,'glass',{ry:K.r()*3}));
    for(let k=0;k<2;k++) if(K.r()<.6) P.push(B(.15+K.r()*.6,.88,.08,.05,.12,.05,pick(K.r,PAL.product)));
    return P; }},
  tub:{w:2,d:1,h:.6,cover:'half',build(K){ const P=[];
    P.push(B(.1,0,.08,1.8,.56,.86,WHITE),B(.2,.3,.16,1.6,.27,.7,'#d8d4c9'),B(.15,.56,.1,.06,.12,.06,CHROME),B(.15,.66,.1,.15,.04,.04,CHROME));
    P.push(B(.1,1.95,.92,1.8,.03,.03,CHROME)); if(K.r()<.7) P.push(B(.1,.55,.9,.7+K.r()*.6,1.4,.02,K.j(K.st.fab,.1),K.r()<K.mess?{rz:.08}:undefined));
    return P; }},
  shower:{w:1,d:1,h:2,cover:'none',build(K){ return [B(.05,0,.05,.9,.08,.9,WHITE),B(.05,0,.93,.9,2.0,.02,'glass'),B(.45,1.8,.06,.1,.1,.2,CHROME)]; }},
  washer:{w:1,d:1,h:.9,cover:'half',build(K){ return washerParts(K,true); }},
  dryer:{w:1,d:1,h:.9,cover:'half',build(K){ return washerParts(K,false); }},
  lshelf:{w:1,d:1,h:1.6,cover:'half',slot:'lshelf',build(K){ const P=[]; rack(P,K,.1,.9,1.6,.38,4,STEELD); return P; }},
  car:{w:2,d:5,h:1.45,cover:'full',slot:'car',build(K){ return carParts(K); }},
  workbench:{w:2,d:1,h:1.8,cover:'half',slot:'workbench',build(K){ const P=[], w=K.st.wood;
    P.push(B(.08,.86,.02,1.84,.06,.64,K.j(w,.06))); for(const x of [.12,1.82]) for(const z of [.06,.56]) P.push(B(x,0,z,.06,.86,.06,w));
    P.push(B(.15,.2,.08,1.7,.03,.52,w)); drawers(P,K,1.1,1.85,.58,.84,.64,2,1,K.j(w,.06),STEELD);
    P.push(B(.08,.92,0,1.84,.9,.03,'#b9a07a')); for(let r=0;r<3;r++) for(let c=0;c<9;c++) P.push(B(.15+c*.2,1.0+r*.28,.03,.012,.012,.012,'#5a4a3a'));
    const tools=[[.25,1.2,.04,.14,.3,.03,'#c23b2e'],[.55,1.15,.04,.04,.4,.03,'#7d8285'],[.8,1.3,.04,.25,.08,.03,'#2b2c2e'],[1.2,1.1,.04,.05,.5,.03,'#c9953f'],[1.45,1.25,.04,.3,.25,.02,'#3f5f86']];
    for(const t of tools) if(K.r()>K.gone) P.push(B(...t)); else P.push(B(t[0],.003,.75+K.r()*.3,t[3],t[5],t[4],t[6],{ry:K.r()*3}));
    P.push(B(.2,.92,.2,.2,.12,.15,'#3f5f86'),B(.25,1.04,.24,.1,.06,.06,STEELD));
    if(K.r()<.6) P.push(B(1.3,.92,.15,.4,.2,.2,'#c23b2e'));
    return P; }},
  gshelf:{w:2,d:1,h:1.8,cover:'full',slot:'gshelf',build(K){ const P=[]; rack(P,K,.1,1.9,1.8,.46,4,'#4a5a60');
    if(K.r()<.7) P.push(B(1.5,0,.6,.3,.35,.2,'#c23b2e'),B(1.6,.35,.65,.05,.08,.05,'#c9953f'));
    if(K.r()<K.mess*.35) return withO(P,{tilt:Math.PI/2*.9,pv:[1,.5],lift:.05});
    return P; }},
  heater:{w:1,d:1,h:1.5,cover:'half',build(K){ return [B(.27,.05,.17,.46,1.4,.46,WHITE),B(.27,.05,.17,.46,1.4,.46,WHITE,{ry:Math.PI/4}),B(.42,1.45,.32,.16,.2,.16,STEELD),B(.3,0,.2,.4,.05,.4,'#4a4d50')]; }},
  desk:{w:2,d:1,h:.75,cover:'half',slot:'desk',build(K){ const P=[], w=K.st.wood;
    P.push(B(.1,.72,.05,1.8,.04,.7,w),B(.12,0,.07,.04,.72,.64,w)); P.push(B(1.4,0,.07,.48,.72,.64,K.j(w,.06))); drawers(P,K,1.42,1.86,.05,.7,.71,3,1,K.j(w,.08),CHROME);
    P.push(B(.7,.76,.1,.5,.32,.04,BLACK),B(.72,.79,.14,.46,.27,.005,K.mess>.5?'#3a4044':'#22303a'),B(.92,.76,.2,.06,.04,.1,BLACK),B(.6,.76,.35,.45,.02,.15,'#3a3a3a'));
    litter(P,K,.2,.15,1.4,.5,3);
    chair(P,K,.95+(K.r()-.5)*.3,1.05+K.r()*.25,[0,-1],{style:'office',col:BLACK,seat:K.st.fab,yawJ:(K.r()-.5)*1.4,down:K.down()?2:0});
    return P; }},
  filing:{w:1,d:1,h:1.3,cover:'half',slot:'filing',build(K){ const P=[], c=pick(K.r,['#7d8285','#5f6f73','#9c917f']); P.push(B(.25,0,.04,.5,1.3,.6,c)); drawers(P,K,.27,.73,.04,1.28,.64,4,1,K.j(c,.05),CHROME); litter(P,K,.1,.65,.8,.35,Math.round(K.mess*4)); return P; }},
  safe:{w:1,d:1,h:.9,cover:'half',slot:'safe',build(K){ const P=[]; P.push(B(.2,0,.04,.6,.9,.6,'#3a3d40')); const op=K.open; P.push(B(.24,.06,.64,.52,.78,.04,'#45484b',op?{yaw:1.3,pv:[.24,.64]}:undefined),B(.6,.45,.68,.06,.06,.03,'#c9a24a',op?{yaw:1.3,pv:[.24,.64]}:undefined),B(.4,.42,.68,.12,.12,.02,CHROME,op?{yaw:1.3,pv:[.24,.64]}:undefined)); return P; }},
  pos:{w:3,d:1,h:1.3,cover:'full',slot:'register',build(K){ const P=[], w=K.st.wood;
    P.push(B(.1,0,.1,2.8,1.0,.75,K.j(w,.05)));
    for(let k=0;k<14;k++) P.push(B(.1+k*.2,.05,.85,.18,.9,.02,K.j(w,.1)));
    P.push(B(.04,1.0,.06,2.92,.05,.86,K.st.top),B(.04,.95,.9,2.92,.05,.04,'#5a4030'));
    // the POS terminal faces the staff side (back), the card reader faces the customer
    P.push(B(.45,1.05,.25,.22,.06,.22,BLACK),B(.53,1.11,.33,.06,.18,.06,BLACK),B(.38,1.25,.25,.36,.26,.04,BLACK,{rx:-.35}),B(.4,1.27,.24,.32,.22,.005,K.mess>.6?'#3a4044':'#2b6f8a',{rx:-.35}));
    P.push(B(.85,1.05,.28,.16,.12,.18,'#d8d2c4'),B(.88,1.17,.3,.1,.004,.12,WHITE));
    const drawerOpen=K.open||K.r()<K.mess*.5; P.push(B(.4,.82,.1-(drawerOpen?.3:0),.5,.12,.5,'#2b2c2e'));
    if(drawerOpen) for(let k=0;k<4;k++) P.push(B(.3+K.r()*1.2,.003,-.2-K.r()*.5,.15,.004,.07,'#7d9a6a',{ry:K.r()*3}));
    P.push(B(1.15,1.05,.6,.1,.14,.1,'#3a3330'),B(1.4,1.05,.6,.08,.1,.08,'glass'),B(1.75,1.05,.45,.3,.05,.22,'#efe3c8'),B(2.2,1.05,.35,.2,.08,.2,'#c9953f'),B(2.25,1.13,.4,.1,.04,.1,'#b5543a'));
    P.push(B(2.5,1.05,.5,.08,.06,.08,CHROME)); // bell
    return P; }},
  booth:{w:2,d:2,h:1.2,cover:'half',build(K){ const P=[], v=K.st.vinyl;
    for(const x of [.02,1.5]){ P.push(B(x,0,.05,.48,.42,1.5,'#3a3330'),B(x,.42,.05,.48,.1,1.5,K.j(v,.05))); const bx=x<1?x:x+.33; P.push(B(bx,.42,.05,.15,.72,1.5,K.j(v,.05))); for(let k=0;k<3;k++) P.push(B(x<1?bx+.15:bx-.02,.6+k*.18,.1,.02,.12,1.4,K.j(v,.1))); }
    if(K.r()<K.mess*.6) P.push(B(.1+K.r()*.3,.53,.3+K.r()*.6,.25,.01,.3,'#4a4038',{ry:K.r()*3}));
    const T=[B(.6,.74,.1,.8,.04,1.3,K.st.top),B(.55,.73,.08,.9,.02,1.34,CHROME),B(.95,0,.7,.1,.74,.1,CHROME),B(.75,0,.5,.5,.03,.5,CHROME)];
    T.push(...condiments(K,.75,.78,.25));
    P.push(...(K.r()<K.mess*.25?withO(T,{roll:Math.PI/2*.8,pv:[1,.75],lift:.3}):T));
    return P; }},
  table4:{w:2,d:2,h:.8,cover:'half',build(K){ const P=[]; const round=K.r()<.4; diningSet(P,K,{size:round?1.15:1.0,round,cloth:K.r()<.35,seats:[[0,1],[0,-1],[1,0],[-1,0]],style:K.st.chair,col:K.st.chairCol,seat:K.st.vinyl,pedestal:K.r()<.5,cond:true}); return P; }},
  table2:{w:1,d:1,h:.8,cover:'half',build(K){ const P=[]; const ax=K.r()<.5; diningSet(P,K,{size:.7,seats:ax?[[1,0],[-1,0]]:[[0,1],[0,-1]],style:K.st.chair,col:K.st.chairCol,seat:K.st.vinyl,pedestal:true,cond:true,small:true}); return P; }},
  range:{w:2,d:1,h:2.4,cover:'half',build(K){ const P=[];
    P.push(B(.05,0,0,1.9,.9,.82,STEELD),B(.1,.1,.82,.85,.55,.03,STEEL),B(1.05,.1,.82,.85,.55,.03,STEEL),B(.2,.6,.86,.65,.03,.04,CHROME),B(1.15,.6,.86,.65,.03,.04,CHROME));
    for(let k=0;k<6;k++){ const x=.25+(k%3)*.6, z=.18+Math.floor(k/3)*.38; P.push(B(x-.14,.9,z-.14,.28,.03,.28,BLACK),B(x-.15,.93,z-.01,.3,.015,.02,'#3a3a3a'),B(x-.01,.93,z-.15,.02,.015,.3,'#3a3a3a')); }
    P.push(B(.05,.9,0,1.9,.3,.06,STEEL)); for(let k=0;k<6;k++) P.push(B(.2+k*.3,.72,.84,.05,.05,.04,BLACK));
    if(K.r()<.7) P.push(B(.15+K.r()*1.2,.93,.25,.35,.18,.35,STEELD));
    P.push(B(0,1.95,0,2,.08,1.0,STEEL),B(0,2.03,0,2,.45,.75,STEEL),B(.7,2.48,.1,.6,.6,.4,STEELD),B(.1,1.9,.15,1.8,.05,.7,'#8a8e90'));
    return P; }},
  grill:{w:2,d:1,h:1.1,cover:'half',build(K){ const P=[]; // flat-top griddle on a stand
    P.push(B(.05,0,.05,1.9,.78,.75,STEELD)); doors(P,K,.07,1.93,.08,.74,.8,2,STEEL,CHROME);
    P.push(B(.05,.78,0,1.9,.14,.82,STEEL),B(.08,.92,.05,1.84,.02,.62,'#2b2b2b'),B(.05,.92,0,1.9,.18,.05,STEEL),B(.05,.92,0,.04,.18,.7,STEEL),B(1.91,.92,0,.04,.18,.7,STEEL),B(.1,.82,.82,1.8,.04,.06,'#5a4a2a'));
    for(let k=0;k<4;k++) P.push(B(.25+k*.45,.82,.83,.05,.05,.04,BLACK));
    P.push(B(.4,.94,.3,.12,.01,.25,'#7d8285',{ry:.4}),B(1.2,.94,.2,.3,.03,.2,'#6a4a3a'));
    return P; }},
  charbroil:{w:1,d:1,h:1.0,cover:'half',build(K){ const P=[];
    P.push(B(.05,0,.05,.9,.78,.75,STEELD),B(.05,.78,0,.9,.12,.82,STEEL),B(.1,.82,.05,.8,.06,.62,'#3a2a20'));
    for(let k=0;k<9;k++) P.push(B(.1+k*.09,.9,.05,.035,.02,.62,'#1e1e1e'));
    if(K.r()<.3) P.push(B(.2,.85,.2,.6,.02,.3,'#8a4a20'));
    for(let k=0;k<3;k++) P.push(B(.2+k*.25,.82,.83,.05,.05,.04,BLACK));
    return P; }},
  fryer:{w:1,d:1,h:1.2,cover:'half',build(K){ const P=[];
    P.push(B(.08,0,.05,.84,.9,.72,STEEL),B(.1,.9,.08,.8,.1,.6,STEELD),B(.14,.92,.12,.72,.06,.5,'#5a4a1a'));
    for(const x of [.15,.52]){ const o=K.r()<.5?{tilt:.6,pv:[x+.15,.6,.9]}:undefined; P.push(B(x,.9,.15,.32,.2,.4,'#9a9e9f',o),B(x+.13,1.05,.5,.06,.04,.3,BLACK,o)); }
    P.push(B(.15,.6,.78,.7,.2,.02,STEELD));
    return P; }},
  prep:{w:2,d:1,h:.95,cover:'half',slot:'prep',build(K){ const P=[];
    P.push(B(.05,.88,.1,1.9,.04,.75,STEEL)); for(const x of [.08,1.88]) for(const z of [.13,.78]) P.push(B(x,0,z,.04,.88,.04,STEELD)); P.push(B(.08,.2,.13,1.84,.03,.69,STEELD));
    P.push(B(.3,.92,.3,.45,.02,.3,'#e8e4da'),B(.4,.94,.35,.25,.01,.03,'#4a4d50'));
    for(let k=0;k<3;k++) if(K.r()>K.gone) P.push(B(.9+k*.3,.92,.25+K.r()*.2,.25,.2,.25,'#d8dde0'),B(.9+k*.3,1.12,.25,.25,.02,.25,pick(K.r,['#c23b2e','#3f5f86','#e0a526','#3f8f5a'])));
    for(let k=0;k<3;k++) if(K.r()>K.gone) P.push(B(.2+k*.55,.23,.25,.4,.25,.3,pick(K.r,['#c9b38a','#e8e4da','#b5543a'])));
    if(K.r()<K.mess*.3) return withO(P,{tilt:Math.PI/2,pv:[1,.85]});
    return P; }},
  dsink:{w:2,d:1,h:1.2,cover:'half',build(K){ const P=[];
    P.push(B(.05,0,.05,1.9,.85,.7,STEELD),B(.05,.85,0,1.9,.06,.78,STEEL)); for(let k=0;k<3;k++){ P.push(B(.12+k*.6,.6,.1,.5,.3,.55,'#6a6e70')); P.push(B(.33+k*.6,.91,.04,.05,.28,.05,CHROME),B(.33+k*.6,1.16,.04,.05,.04,.2,CHROME)); }
    P.push(B(.05,.91,0,1.9,.3,.04,STEEL));
    return P; }},
  rshelf:{w:2,d:1,h:1.9,cover:'full',slot:'rshelf',build(K){ const P=[]; rack(P,K,.05,1.95,1.9,.5,5,'#c8ccce',true);
    if(K.r()<K.mess*.3) return withO(P,{tilt:Math.PI/2*.88,pv:[1,.5],lift:.05});
    return P; }},
  reachin:{w:1,d:1,h:2.0,cover:'full',slot:'reachin',build(K){ const P=[];
    P.push(B(.05,0,0,.9,2.0,.78,STEEL),B(.05,0,.78,.9,.16,.02,'#4a4d50'));
    for(let k=0;k<7;k++) P.push(B(.12+k*.11,.03,.8,.06,.1,.005,BLACK));
    const op=K.doorState(); const o=op?{yaw:-(.6+K.r()),pv:[.06,.8]}:undefined;
    P.push(B(.07,.2,.8,.86,1.75,.03,STEEL,o),B(.85,.8,.83,.03,.5,.04,CHROME,o));
    return P; }},
  shelf:{w:1,d:1,h:1.5,cover:'full',slot:'shelf',build(K){ const P=[], L=K.w;
    P.push(B(0,0,.1,L,.12,.8,'#4a4d50'),B(0,0,.48,L,1.5,.04,K.j(K.st.fixture,.05)));
    for(let x=0;x<=L;x+=L) P.push(B(Math.min(x,L-.03),0,.1,.03,1.5,.8,K.j(K.st.fixture,.08)));
    for(let k=0;k<4;k++){ const y=.12+k*.34; P.push(B(0,y,.1,L,.025,.8,K.st.fixture)); products(P,K,0,L,y+.025,.1,.48,.28); products(P,K,0,L,y+.025,.52,.9,.28); }
    for(let k=0;k<Math.round(K.mess*4*L);k++) P.push(B(K.r()*L,.004,.92+K.r()*.4,.08,.08,.12,pick(K.r,PAL.product),{ry:K.r()*3,rz:Math.PI/2}));
    if(K.r()<K.mess*.3) return withO(P,{tilt:Math.PI/2*.88,pv:[L/2,.9],lift:.02}); // fallen on its face
    return P; }},
  wallshelf:{w:2,d:1,h:2.0,cover:'full',slot:'wallshelf',build(K){ const P=[];
    P.push(B(.05,0,.02,1.9,2.0,.04,K.j(K.st.fixture,.05)),B(.05,0,.02,1.9,.15,.5,'#4a4d50'));
    for(let k=0;k<5;k++){ const y=.15+k*.36; P.push(B(.05,y,.06,1.9,.025,.45,K.st.fixture)); products(P,K,.06,1.94,y+.025,.08,.5,.3); }
    for(let k=0;k<Math.round(K.mess*5);k++) P.push(B(.1+K.r()*1.7,.004,.6+K.r()*.5,.08,.08,.12,pick(K.r,PAL.product),{ry:K.r()*3,rz:Math.PI/2}));
    return P; }},
  cooler:{w:1,d:1,h:2.1,cover:'full',slot:'cooler',build(K){ const P=[];
    P.push(B(.02,0,0,.96,2.1,.78,'#3a3d40'),B(.02,1.95,.78,.96,.15,.03,'#c23b2e'));
    for(let k=0;k<5;k++){ const y=.12+k*.36; P.push(B(.06,y,.08,.88,.02,.65,'#8a8e90')); let x=.08; while(x<.9){ if(K.r()>K.gone) P.push(B(x,y+.02,.15+K.r()*.4,.065,.24,.065,pick(K.r,['#c23b2e','#3f8f5a','#2f6fa0','#e0a526','#e8e4da','#7a2e35']))); x+=.08; } }
    const st=K.doorState();
    if(st===3) P.push(B(.2,.01,.9,.8,.03,1.6,'#2b2c2e',{ry:(K.r()-.5)*.6}));
    else { const o=st?{yaw:-(.4+K.r()*1.1),pv:[.04,.8]}:undefined; P.push(B(.04,.08,.8,.92,1.85,.03,'#2b2c2e',o)); if(K.r()>K.mess*.5) P.push(B(.09,.14,.83,.82,1.72,.01,'glass',o)); else P.push(B(.2,.003,1.0,.3,.004,.2,'glass',{ry:K.r()*3})); P.push(B(.84,.8,.84,.03,.4,.04,CHROME,o)); }
    return P; }},
  checkout:{w:3,d:1,h:1.0,cover:'full',slot:'checkout',build(K){ const P=[];
    P.push(B(.1,0,.1,2.8,.95,.8,'#6d5a48'),B(.08,.95,.08,2.84,.05,.84,'#3b3a38'),B(.15,1.0,.2,1.5,.01,.55,BLACK));
    P.push(B(2.0,1.0,.25,.4,.12,.4,'#2b2c2e'),B(2.05,1.12,.28,.3,.22,.04,BLACK,{rx:-.3}));
    const dO=K.open||K.r()<K.mess*.6; P.push(B(2.0,.85,.5+(dO?.3:0),.4,.1,.35,'#2b2c2e'));
    P.push(B(.2,1.0,.75,.6,.5,.1,'#c9693a')); for(let k=0;k<3;k++) products(P,K,.22,.78,1.02+k*.16,.72,.82,.12);
    if(K.r()<.6) P.push(B(1.8,1.6,-.2,.9,.04,.3,'#4a4d50'));
    return P; }},
  pcounter:{w:1,d:1,h:1.05,cover:'full',build(K){ return [B(0,0,.1,1,1.0,.8,'#e1dccf'),B(-.01,1.0,.08,1.02,.05,.84,'#8c8478'),B(.05,.05,.9,.9,.9,.01,'#c9c6bb')]; }},
  crate:{w:1,d:1,h:.62,cover:'half',slot:'crate',build(K){ const P=[], c=K.j('#9c7a4c',.1);
    P.push(B(.15,0,.15,.7,.6,.7,c)); for(let k=0;k<3;k++) P.push(B(.13,.05+k*.2,.13,.74,.06,.74,K.j(c,.1)));
    if(K.open) P.push(B(.15,.6,.15,.7,.04,.7,c,{tilt:-1.2,pv:[.5,.15,.64]})); else P.push(B(.13,.6,.13,.74,.04,.74,K.j(c,.08)));
    return withO(P,{yaw:(K.r()-.5)*.6,pv:[.5,.5]}); }},
  bedroll:{w:1,d:2,h:.15,cover:'none',walk:true,build(K){ const c=pick(K.r,['#5d6b4e','#3f5f86','#7a2e35','#6b5a40']); return withO([B(.2,0,.15,.6,.08,1.7,c),B(.22,.08,.2,.56,.06,1.0,K.j(c,.1)),B(.25,.08,1.55,.5,.12,.25,'#d8d2c4')],{yaw:(K.r()-.5)*.7,pv:[.5,1]}); }},
  barrel:{w:1,d:1,h:1.0,cover:'half',build(K){ return [B(.28,0,.28,.44,.9,.44,RUST),B(.28,0,.28,.44,.9,.44,K.j(RUST,.1),{ry:Math.PI/4}),B(.3,.9,.3,.4,.1,.4,'#e0a526'),B(.33,.95,.33,.34,.12,.34,'#c23b2e',{ry:.4})]; }},
  barricade:{w:1,d:1,h:1.4,cover:'full',build(K){ const P=[B(.05,0,.05,.9,1.25,.5,K.st.wood),B(0,.2,.3,1,.32,.6,'#9c7a4c',{ry:.2})]; for(let k=0;k<3;k++) P.push(B(-.1,.2+k*.4,.0,1.2,.12,.04,'#8a6a4a',{rz:(K.r()-.5)*.4})); return P; }},
  debris:{w:1,d:1,h:.2,cover:'none',walk:true,build(K){ const P=[]; litter(P,K,.05,.05,.9,.9,4+Math.floor(K.r()*4)); if(K.r()<.4) P.push(B(.2,0,.2,.5,.06,.08,K.st.wood,{ry:K.r()*3})); if(K.r()<.3) P.push(B(.1+K.r()*.4,0,.2+K.r()*.4,.35,.25,.3,'#d8cdb6',{ry:K.r()*3,rz:.3})); return P; }},
  cactus:{w:1,d:1,h:1.6,cover:'half',build(K){ const P=[]; P.push(B(.32,0,.32,.36,.3,.36,TERRA),B(.3,.28,.3,.4,.06,.4,K.j(TERRA,.06)));
    const g=K.j('#5f7d3f',.08), t=K.r();
    if(K.mess>.6&&K.r()<.5){ P.push(B(.4,.02,.6,.15,.12,.7,'#7a6a3a',{ry:K.r()*3})); return P; } // dried out, fallen over
    if(t<.45){ const h=.9+K.r()*.6; P.push(B(.43,.3,.43,.14,h,.14,g)); if(K.r()<.8) P.push(B(.29,.55,.45,.14,.1,.1,g),B(.29,.55,.45,.1,.35,.1,g)); if(K.r()<.8) P.push(B(.57,.7,.45,.14,.1,.1,g),B(.61,.7,.45,.1,.3,.1,g)); }
    else if(t<.75){ for(let k=0;k<9;k++) P.push(B(.47,.3,.47,.06,.45,.06,K.j('#7b8f74',.08),{ry:k*.7,rx:.55+K.r()*.3})); }
    else { for(let k=0;k<5;k++) P.push(B(.35+K.r()*.2,.32+k*.12,.48,.22,.24,.05,K.j('#6f8f4a',.08),{ry:K.r()*3,rz:(K.r()-.5)*.6})); }
    return P; }},
};
function bedParts(K,bw){
  const P=[], w=K.st.wood, x0=(K.w-bw)/2, f=K.st.fab;
  P.push(B(x0,0,0,bw,1.05,.06,w),B(x0-.03,0,0,.06,1.15,.08,K.j(w,.06)),B(x0+bw-.03,0,0,.06,1.15,.08,K.j(w,.06)));
  P.push(B(x0,.08,.06,bw,.22,1.9,K.j(w,.06)),B(x0+.02,.3,.07,bw-.04,.2,1.86,'#e8e2d4'));
  const mess=K.r()<K.mess;
  P.push(B(x0-.02,.48,.6,bw+.04,.06,1.34,K.j(f,.06),mess?{ry:(K.r()-.5)*.5,rz:.06}:undefined));
  if(mess) P.push(B(x0+bw*.2+(K.r()-.5)*.6,.01,1.95+K.r()*.4,bw*.8,.08,.6,K.j(f,.06),{ry:(K.r()-.5)*1.2}));
  else P.push(B(x0-.01,.54,1.6,bw+.02,.05,.3,K.j(K.st.fab2,.06)));
  const n=bw>1.2?2:1; for(let k=0;k<n;k++) P.push(B(x0+.08+k*(bw/2),.5,.12,bw/n-.16,.13,.38,WHITE,{ry:(K.r()-.5)*(mess?.9:.15)}));
  if(K.r()<.6){ const R=[]; rug(R,K,K.w/2,1.2,bw+1.0,1.2); P.unshift(...R); }
  return P;
}
function washerParts(K,front){
  const P=[], a=K.st.appl;
  P.push(B(.17,0,.05,.66,.88,.64,a),B(.17,.82,.05,.66,.08,.12,K.j(a,.05)));
  for(let k=0;k<3;k++) P.push(B(.25+k*.15,.85,.17,.06,.04,.04,BLACK));
  const op=K.r()<K.mess*.6, o=op?{yaw:1.3,pv:[.25,.69]}:undefined;
  P.push(B(.27,.25,.69,.46,.46,.03,'#5a5c5e',o),B(.33,.31,.71,.34,.34,.01,'#2b3036',o));
  if(op) P.push(B(.3+K.r()*.3,.003,.9,.35,.06,.3,pick(K.r,PAL.fab),{ry:K.r()*3}));
  return P;
}
function rack(P,K,x0,x1,h,d,n,col,boxes){
  for(const x of [x0,x1-.03]) for(const z of [.04,d]) P.push(B(x,0,z,.03,h,.03,col));
  for(let k=0;k<n;k++){ const y=.08+k*(h-.15)/(n-1); P.push(B(x0,y,.04,x1-x0,.025,d-.0+.0,K.j(col,.04)));
    if(k<n-1){ let x=x0+.04; while(x<x1-.12){ const w=.15+K.r()*.3; if(x+w>x1-.02) break; if(K.r()>K.gone){ const hh=(.15+K.r()*.2); P.push(B(x,y+.025,.08+K.r()*.05,w-.02,hh,d-.12,boxes?pick(K.r,['#c9b38a','#b49a78','#e8e4da','#d1b04a','#c9693a','#5a8bb0']):pick(K.r,PAL.product))); } x+=w; } } }
  for(let k=0;k<Math.round(K.mess*4);k++) P.push(B(x0+K.r()*(x1-x0-.3),.003,d+.1+K.r()*.4,.25,.18,.2,pick(K.r,['#c9b38a','#b49a78','#e8e4da']),{ry:K.r()*3,rz:K.r()<.4?Math.PI/2:0}));
}
function condiments(K,x,y,z){
  const P=[]; if(K.r()<K.gone) return P;
  P.push(B(x,y,z,.05,.16,.05,'#c23b2e'),B(x+.08,y,z,.05,.15,.05,'#e0b526'),B(x+.16,y,z+.02,.03,.07,.03,WHITE),B(x+.21,y,z+.02,.03,.07,.03,'#3a3a3a'),B(x+.27,y,z-.02,.12,.12,.08,CHROME));
  return K.mess>.5&&K.r()<.5?withO(P,{roll:Math.PI/2,pv:[x+.1,z,y]}):P;
}
// A table with chairs. The table shifts and turns with a noise field across the room, so neighbours drift together.
function diningSet(P,K,opt){
  const n1=K.nz(K.ci*.41+.1,K.cj*.41+.3), n2=K.nz(K.ci*.41+5.2,K.cj*.41+1.7), n3=K.nz(K.ci*.6+9,K.cj*.6+2);
  const cx=K.w/2+(n1-.5)*(opt.small?.15:.35), cz=K.d/2+(n2-.5)*(opt.small?.15:.35), yaw=(n3-.5)*.5+(K.r()-.5)*.15;
  const s=opt.size, long=opt.long||0, sx=s+long*.4, sz=s;
  const over=K.down(1.1);
  const T=[];
  const col=opt.center?K.st.wood:K.j(pick(K.r,PAL.top.concat([K.st.wood,K.st.wood])),.05);
  const seatCol=opt.seat?(K.r()<.7?opt.seat:pick(K.r,PAL.fab)):undefined;
  if(opt.round){ T.push(B(cx-s/2,.72,cz-s/2,s,.04,s,col),B(cx-s/2,.72,cz-s/2,s,.04,s,K.j(col,.02),{ry:Math.PI/4})); }
  else T.push(B(cx-sx/2,.72,cz-sz/2,sx,.04,sz,col));
  if(opt.cloth){ const c=pick(K.r,['#efe9dc','#b5543a','#c23b2e','#2f8f8a','#e0c08e']), h=.22, e=.05;
    T.push(B(cx-sx/2-e,.765,cz-sz/2-e,sx+2*e,.01,sz+2*e,c),B(cx-sx/2-e,.765-h,cz-sz/2-e,sx+2*e,h,.01,c),B(cx-sx/2-e,.765-h,cz+sz/2+e-.01,sx+2*e,h,.01,c),B(cx-sx/2-e,.765-h,cz-sz/2-e,.01,h,sz+2*e,c),B(cx+sx/2+e-.01,.765-h,cz-sz/2-e,.01,h,sz+2*e,c));
    T.push(B(cx-.05,0,cz-.05,.1,.72,.1,CHROME)); }
  else if(opt.pedestal) T.push(B(cx-.05,0,cz-.05,.1,.72,.1,CHROME),B(cx-.28,0,cz-.28,.56,.03,.56,CHROME),B(cx-.28,0,cz-.28,.56,.03,.56,CHROME,{ry:Math.PI/4}));
  else for(const [a,b] of [[-1,-1],[1,-1],[-1,1],[1,1]]) T.push(B(cx+a*(sx/2-.08)-.03,0,cz+b*(sz/2-.08)-.03,.06,.72,.06,K.j(col,.08)));
  if(!over){
    if(opt.cond) T.push(...condiments(K,cx-.2,.76,cz-.05));
    if(opt.center){ T.push(B(cx-.15,.76,cz-.15,.3,.08,.3,'#d8d2c4')); for(let k=0;k<4;k++) T.push(B(cx-sx/2+.15+K.r()*(sx-.5),.76,cz-sz/2+.1+K.r()*(sz-.4),.3,.005,.25,K.j(K.st.fab,.1),{ry:(K.r()-.5)*.4})); }
    if(K.r()<.3) T.push(B(cx+(K.r()-.5)*.4,.76,cz+(K.r()-.5)*.4,.07,.1,.07,'glass'));
  }
  // a table on its side
  P.push(...withO(T,over?{yaw,pv:[cx,cz],roll:(K.r()<.5?1:-1)*Math.PI/2,lift:sx/2}:{yaw,pv:[cx,cz]}));
  const cy=Math.cos(yaw), sy=Math.sin(yaw);
  for(const [dx,dz] of opt.seats){
    for(const side of (long&&dz!==0?[-.35,.35]:[0])){
      if(K.r()<.1) continue; // a chair carried off
      const pull=.32+K.nz(K.ci*.8+dx*3,K.cj*.8+dz*3)*.25+K.r()*.15*(1+K.mess);
      const ox=dx*(sx/2+pull)+side*(dz!==0?1:0), oz=dz*(sz/2+pull)+side*(dx!==0?1:0);
      const px=cx+ox*cy-oz*sy, pz=cz+ox*sy+oz*cy;
      const face=[-(dx*cy-dz*sy),-(dx*sy+dz*cy)];
      const down=K.down()?(K.r()<.5?1:2):0;
      const odd=K.r()<.15+K.mess*.15, style=odd?pick(K.r,['wood','diner','office']):opt.style;
      chair(P,K,px,pz,face,{style,col:K.j(odd?pick(K.r,PAL.wood.concat([CHROME])):opt.col,.08),seat:seatCol?K.j(odd?pick(K.r,PAL.fab):seatCol,.06):undefined,yawJ:(K.r()-.5)*(.4+K.mess*.9),down});
    }
  }
}
function carParts(K){
  const P=[], col=K.j(pick(K.r,PAL.car),.08), len=K.it.len===4?4.1:4.6, x0=(2-1.8)/2, w=1.8, z0=(5-len)/2+(K.it.len===4?-.3:0);
  const flat=[K.r()<.35*K.mess+.08,K.r()<.25,K.r()<.25*K.mess,K.r()<.2];
  const rust=K.mess>.4;
  const wheel=(x,z,k)=>{ const y=flat[k]?.26:.32, r=y; P.push(B(x-.11,0,z-r,.22,r*2,r*2,'#1e1e1e'),B(x-.11,0,z-r,.22,r*2,r*2,'#1e1e1e',{rx:Math.PI/4}),B(x-.115,r-.17,z-.17,.23,.34,.34,rim),B(x-.115,r-.17,z-.17,.23,.34,.34,rim,{rx:Math.PI/4}),B(x-.125,r-.06,z-.06,.25,.12,.12,'#4a4d50')); for(let q=0;q<5;q++) P.push(B(x-.13,r-.015,z-.015,.26,.03,.03,'#5a5c5e',{rx:q*Math.PI/5*2})); };
  const rim=K.mess>.5&&K.r()<.4?RUST:pick(K.r,[CHROME,'#9aa1a6','#2b2c2e',CHROME]);
  const zf=z0+len; // the nose faces +z (toward the garage door)
  wheel(x0+.03,z0+.75,0); wheel(x0+w-.03,z0+.75,1); wheel(x0+.03,zf-.85,2); wheel(x0+w-.03,zf-.85,3);
  const lowL=(flat[0]||flat[2])?-.04:0;
  const body=[];
  body.push(B(x0+.14,.22,z0+.05,w-.28,.5,len-.1,col),B(x0+.1,.42,z0+.05,w-.2,.3,len-.1,col)); // lower body, tucked in above the tyres
  for(const zc of [z0+.75,zf-.85]){ for(const [x,s2] of [[x0-.06,1],[x0+w-.1,-1]]){ body.push(B(x,.62,zc-.5,.16,.08,1.0,K.j(col,.04)),B(x,.42,zc-.58,.16,.22,.1,K.j(col,.04)),B(x,.42,zc+.48,.16,.22,.1,K.j(col,.04))); } } // flared wheel arches
  body.push(B(x0-.02,.42,z0+1.35,w+.04,.06,len-2.7,K.j(col,-.05)),B(x0-.03,.3,z0+1.4,w+.06,.08,len-2.8,'#2b2c2e')); // body line and sills
  body.push(B(x0+.04,.66,zf-1.2,w-.08,.1,1.12,K.j(col,.03),{rx:-.06})); // hood
  body.push(B(x0+.04,.66,z0+.1,w-.08,.1,.9,K.j(col,.03))); // trunk lid
  body.push(B(x0+.08,.72,z0+1.0,w-.16,.5,len-2.3,col)); // cabin
  body.push(B(x0+.12,1.22,z0+1.15,w-.24,.05,len-2.6,K.j(col,.05))); // roof
  const glassBroken=K.mess>.5?K.r()<.6:K.r()<.15;
  const g=glassBroken?'#1a1c1e':'#3b5160', tint='#3b5160';
  body.push(B(x0+.12,.78,zf-1.32,w-.24,.42,.04,g,{rx:-.55})); // windscreen
  body.push(B(x0+.12,.78,z0+1.08,w-.24,.4,.04,tint,{rx:.5}));
  if(glassBroken) for(let k=0;k<4;k++) P.push(B(x0+K.r()*w,.002,zf-1.3+K.r()*1.4,.08,.004,.06,'glass',{ry:K.r()*3}));
  for(const x of [x0+.07,x0+w-.08]){ body.push(B(x,.78,z0+1.25,.01,.38,(len-2.6)/2-.05,tint),B(x,.78,z0+1.25+(len-2.6)/2+.05,.01,.38,(len-2.6)/2-.1,glassBroken&&x<1?'#1a1c1e':tint)); body.push(B(x,.72,z0+1.25+(len-2.6)/2,.012,.5,.06,col)); }
  body.push(B(x0-.04,.3,zf-.06,w+.08,.14,.1,CHROME),B(x0-.04,.3,z0-.04,w+.08,.14,.1,CHROME)); // bumpers
  body.push(B(x0+.12,.5,zf-.02,.3,.12,.04,'#f0ead0'),B(x0+w-.42,.5,zf-.02,.3,.12,.04,'#f0ead0'),B(x0+.6,.45,zf-.02,w-1.2,.16,.03,'#2b2c2e')); // lamps and grille
  body.push(B(x0+.1,.52,z0+.0,.32,.12,.04,'#c23b2e'),B(x0+w-.42,.52,z0+.0,.32,.12,.04,'#c23b2e'),B(x0+.7,.48,z0,.4,.1,.02,'#e8d64a')); // tail lamps, plate
  body.push(B(x0-.12,.92,zf-1.4,.1,.08,.12,BLACK),B(x0+w+.02,.92,zf-1.4,.1,.08,.12,BLACK)); // mirrors
  for(const x of [x0+.04,x0+w-.07]) body.push(B(x,.6,z0+1.9,.03,.03,.18,CHROME),B(x,.6,zf-1.9,.03,.03,.18,CHROME)); // door handles
  if(rust) for(let k=0;k<4;k++) body.push(B(K.r()<.5?x0:x0+w-.02,.32+K.r()*.3,z0+.3+K.r()*(len-.8),.03,.08+K.r()*.15,.15+K.r()*.4,RUST));
  P.push(...withO(body,{roll:lowL?.03:(flat[1]||flat[3]?-.03:0),pv:[1,2.5]}));
  if(K.mess>.5&&K.r()<.5) P.push(B(x0+.04,.75,zf-1.2,w-.08,.05,1.1,K.j(col,.03),{tilt:-1.0,pv:[1,zf-1.2,.75]})); // hood propped up
  if(K.open||K.r()<K.mess*.5) P.push(B(x0-.02,.35,z0+1.9,.04,.75,1.0,col,{yaw:-1.0,pv:[x0,z0+1.9]})); // driver door hanging open
  return P;
}
// Pieces hung on a wall: x along the wall, z out from it. Southwest roadhouse and home decor.
const DECOR={
  neon(K){ const c=pick(K.r,['#ff5a3c','#3cd0ff','#ffd23c','#ff4fa0','#7dff7a']); const P=[B(.1,1.7,.12,.8,.45,.03,'#2b2c2e')]; const lit=K.mess<.5&&K.r()<.5;
    for(let k=0;k<4;k++) P.push(B(.18+k*.17,1.8+(k%2)*.1,.15,.12,.04,.03,lit?c:jit(c,K.r,.4)), B(.18+k*.17,1.8,.15,.03,.2,.03,lit?c:jit(c,K.r,.4))); return P; },
  photo(K){ const w=.4+K.r()*.4, h=.3+K.r()*.3, y=1.35+K.r()*.3, x=.5-w/2; const sky=pick(K.r,['#9cc8e0','#e8a87c','#c9a0b8']), land=pick(K.r,['#c9953f','#b5653f','#8f8c5a']);
    const P=[B(x,y,.12,w,h,.03,K.st.wood),B(x+.04,y+h*.45,.15,w-.08,h*.5-.04,.005,sky),B(x+.04,y+.04,.15,w-.08,h*.45-.04,.005,land),B(x+w*.3,y+.04,.155,.05,h*.4,.005,'#4f6a3a')];
    return K.mess>.5&&K.r()<.4?withO(P,{roll:.4,pv:[.5,.12]}):P; },
  flag(K){ // Arizona: rays of red and gold over blue, a copper star
    const P=[B(.05,1.4,.12,.9,.6,.02,'#2a4a8a')]; for(let k=0;k<6;k++) P.push(B(.05+k*.15,1.7,.13,.15,.3,.01,k%2?'#e8b830':'#bf2a2a'));
    P.push(B(.43,1.63,.14,.14,.14,.01,'#c87533',{rz:Math.PI/4})); return P; },
  skull(K){ return [B(.36,1.6,.12,.28,.3,.12,'#efe9dc'),B(.4,1.48,.14,.2,.14,.1,'#e8e1cf'),B(.1,1.82,.16,.3,.05,.05,'#e8e1cf',{rz:.35}),B(.6,1.82,.16,.3,.05,.05,'#e8e1cf',{rz:-.35}),B(.42,1.66,.24,.05,.05,.01,BLACK),B(.53,1.66,.24,.05,.05,.01,BLACK)]; },
  plates(K){ const P=[]; for(let k=0;k<4;k++){ const x=.05+(k%2)*.45, y=1.3+Math.floor(k/2)*.2; P.push(B(x,y,.12,.4,.17,.01,pick(K.r,['#7a2e35','#e8d64a','#9cc8e0','#e8e4da']),{rz:(K.r()-.5)*.2}),B(x+.06,y+.05,.13,.28,.06,.005,BLACK,{rz:(K.r()-.5)*.2})); } return P; },
  wheel(K){ const P=[], r=.42, cx=.5, cy=1.55; for(let k=0;k<8;k++){ const a=k*Math.PI/4; P.push(B(cx+Math.cos(a)*r-.04,cy+Math.sin(a)*r-.17,.12,.08,.34,.05,'#6e5038',{rz:a})); P.push(B(cx-.015,cy-r*.5,.14,.03,r,.03,'#8a6a4a',{rz:a})); } P.push(B(cx-.07,cy-.07,.12,.14,.14,.07,'#5a4030')); return P; },
  clock(K){ return [B(.38,1.75,.12,.24,.24,.04,'#efe9dc'),B(.38,1.75,.12,.24,.24,.04,'#efe9dc',{rz:Math.PI/4}),B(.49,1.82,.165,.02,.1,.005,BLACK),B(.49,1.86,.165,.08,.02,.005,BLACK,{rz:.5})]; },
  menu(K){ const P=[B(.05,1.5,.12,.9,.6,.03,'#2b2c2e')]; for(let k=0;k<6;k++) P.push(B(.12,1.95-k*.07,.15,.3+K.r()*.4,.025,.005,'#efe9dc'),B(.8,1.95-k*.07,.15,.08,.025,.005,'#e0a526')); return P; },
  shelfDecor(K){ const P=[B(.1,1.55,.1,.8,.03,.22,K.st.wood)]; for(let k=0;k<3;k++){ const t=K.r(); P.push(B(.15+k*.25,1.58,.15,.14,.12+K.r()*.15,.12,t<.5?TERRA:pick(K.r,['#2f8f8a','#c9953f','#efe9dc']))); } return P; },
  horseshoe(K){ return [B(.4,1.7,.12,.05,.2,.03,'#6a6a6a'),B(.55,1.7,.12,.05,.2,.03,'#6a6a6a'),B(.4,1.66,.12,.2,.05,.03,'#6a6a6a')]; },
};
const DECOR_BY={
  rdining:['neon','neon','photo','flag','skull','plates','wheel','menu','horseshoe','photo'],
  sales:['neon','menu','photo','flag'], living:['photo','photo','skull','shelfDecor','clock','wheel'], dining:['photo','shelfDecor','clock'],
  kitchen:['clock','shelfDecor'], master:['photo','photo'], bed:['photo','flag'], hall:['photo','photo'], den:['photo','flag','skull','horseshoe'],
  office:['photo','flag','clock'], rkitchen:['clock'], garage:['plates','horseshoe'],
};

// ---- Anthem town centre: fast food, coffee, banks, offices, big stores, auto service, salons, clinics, fuel
Object.assign(IT,{
  ffcounter:{w:3,d:1,h:1.1,cover:'full',slot:'register',build(K){ const P=[], c=K.j(pick(K.r,['#c23b2e','#e0a526','#3f5f86','#5a4030','#d8d2c4']),.05);
    P.push(B(.05,0,.05,2.9,1.0,.8,c),B(.02,1.0,0,2.96,.05,.9,'#3b3a38'),B(.05,.1,.86,2.9,.06,.02,K.j(c,.15)));
    for(const x of [.4,1.6]){ P.push(B(x,1.05,.15,.3,.06,.25,BLACK),B(x+.02,1.1,.2,.26,.2,.03,K.mess>.6?'#3a4044':'#22303a',{rx:-.4})); }
    P.push(B(2.3,1.05,.3,.35,.25,.35,'#c9b38a'),B(2.35,1.3,.32,.25,.02,.3,'#e8e4da'),B(1.1,1.05,.6,.12,.15,.08,CHROME),B(1.3,1.05,.62,.06,.22,.06,'#e8e4da'));
    if(K.mess>.4) litter(P,K,0,1.0,3,.8,4);
    return P; }},
  soda:{w:1,d:1,h:1.9,cover:'half',build(K){ const P=[B(.05,0,.05,.9,.9,.7,'#4a4d50'),B(.08,.9,.05,.84,.9,.55,K.j(pick(K.r,['#c23b2e','#2f6fa0','#3f8f5a']),.05)),B(.1,1.15,.6,.8,.5,.02,'#1e1e1e'),B(.15,.9,.5,.7,.03,.2,'#2b2c2e')];
    for(let k=0;k<6;k++) P.push(B(.13+k*.12,1.05,.45,.06,.12,.08,CHROME),B(.13+k*.12,1.25,.62,.09,.06,.01,pick(K.r,PAL.product)));
    for(let k=0;k<3;k++) if(K.r()>K.gone) P.push(B(.15+k*.25,1.8,.1,.12,.25,.12,'#efe9dc'));
    return P; }},
  trashbin:{w:1,d:1,h:1.2,cover:'half',build(K){ const c=K.j(K.st.wood,.06); const P=[B(.15,0,.15,.7,1.05,.6,c),B(.12,1.05,.12,.76,.06,.66,K.j(c,.05)),B(.25,.7,.76,.5,.2,.01,'#3a3330'),B(.3,.55,.76,.4,.06,.01,'#e0a526')];
    if(K.mess>.4) litter(P,K,-.2,.6,1.4,.8,3);
    return K.down(1.2)?withO(P,{tilt:Math.PI/2,pv:[.5,.75]}):P; }},
  warmer:{w:2,d:1,h:1.6,cover:'half',slot:'warmer',build(K){ const P=[B(.05,0,.05,1.9,.9,.7,STEEL),B(.05,.9,.05,1.9,.04,.7,STEELD),B(.05,1.5,.05,1.9,.08,.6,STEEL),B(.1,.94,.1,.04,.56,.04,STEELD),B(1.86,.94,.1,.04,.56,.04,STEELD),B(.15,1.46,.15,1.7,.04,.4,K.mess>.5?'#5a4a3a':'#ff9a3c')];
    for(let k=0;k<8;k++) if(K.r()>K.gone) P.push(B(.15+k*.22,.95,.2+K.r()*.25,.16,.07,.14,pick(K.r,['#e0b526','#c23b2e','#e8e4da'])));
    return P; }},
  shake:{w:1,d:1,h:1.6,cover:'half',build(K){ return [B(.1,0,.05,.8,1.2,.7,STEEL),B(.15,1.2,.1,.7,.35,.55,'#e8e4da'),B(.3,.85,.75,.15,.12,.08,CHROME),B(.55,.85,.75,.15,.12,.08,CHROME),B(.2,.4,.75,.6,.03,.02,'#2b2c2e')]; }},
  dipcase:{w:2,d:1,h:1.2,cover:'half',slot:'dipcase',build(K){ const P=[B(.05,0,.05,1.9,.85,.8,'#e8e4da'),B(.05,.85,.05,1.9,.04,.8,STEELD),B(.2,.4,.86,1.6,.25,.01,K.j(pick(K.r,['#d94f8a','#3f5f86']),.05))];
    for(let k=0;k<8;k++){ const x=.12+(k%4)*.45, z=.15+Math.floor(k/4)*.35; P.push(B(x,.8,z,.38,.08,.3,K.r()<K.gone?'#4a4d50':pick(K.r,['#f3d7e0','#7a4a2c','#e8e4da','#9fd3a0','#f6e6a8','#c23b2e']))); }
    if(K.r()>K.mess*.6) P.push(B(.05,.89,.75,1.9,.3,.02,'glass',{rx:-.4}));
    return P; }},
  cafecounter:{w:3,d:1,h:1.4,cover:'full',slot:'register',build(K){ const P=[], c=K.j(pick(K.r,['#2f4f3f','#5a4030','#3b3a38','#7a2e35']),.05);
    P.push(B(.05,0,.05,2.9,1.0,.8,c)); for(let k=0;k<12;k++) P.push(B(.08+k*.24,.08,.86,.2,.85,.01,K.j(c,.1)));
    P.push(B(.02,1.0,0,2.96,.05,.9,K.st.top),B(.3,1.05,.08,.9,.5,.45,STEEL),B(.3,1.55,.1,.9,.06,.4,STEELD)); for(let k=0;k<3;k++) P.push(B(.42+k*.28,1.2,.53,.14,.06,.12,BLACK));
    P.push(B(1.35,1.05,.1,.2,.45,.2,BLACK),B(1.38,1.5,.12,.14,.15,.14,'glass'),B(1.65,1.05,.1,.22,.2,.22,STEELD));
    for(let k=0;k<6;k++) if(K.r()>K.gone) P.push(B(1.95+k*.08,1.05,.12,.05,.3,.05,pick(K.r,['#7a2e35','#c9953f','#5a4030','#e8e4da','#3f8f5a'])));
    P.push(B(2.5,1.05,.5,.3,.06,.25,BLACK),B(2.52,1.1,.55,.26,.2,.03,'#22303a',{rx:-.4})); for(let k=0;k<3;k++) P.push(B(2.45,1.05+k*.12,.15,.12,.12,.12,'#efe9dc'));
    return P; }},
  pastry:{w:2,d:1,h:1.3,cover:'full',slot:'pastry',build(K){ const P=[B(.05,0,.1,1.9,.85,.75,K.j(K.st.wood,.05)),B(.05,.85,.1,1.9,.04,.75,'#e8e4da'),B(.1,1.08,.15,1.8,.02,.6,'#d8dde0')];
    const smashed=K.r()<K.mess*.5; if(!smashed) P.push(B(.05,.85,.1,.03,.45,.75,'glass'),B(1.92,.85,.1,.03,.45,.75,'glass'),B(.05,1.3,.1,1.9,.02,.75,'glass'),B(.05,.85,.83,1.9,.45,.02,'glass',{rx:.25})); else for(let k=0;k<4;k++) P.push(B(K.r()*1.8,.002,.95+K.r()*.4,.12,.004,.08,'glass',{ry:K.r()*3}));
    for(let k=0;k<10;k++) if(K.r()>K.gone+.1) P.push(B(.15+(k%5)*.36,.9+Math.floor(k/5)*.2,.25+K.r()*.3,.22,.07,.15,pick(K.r,['#6b5a40','#7a6a4a','#5a4a30'])));
    return P; }},
  checkstand:{w:2,d:1,h:1.1,cover:'half',build(K){ const c=K.j(K.st.wood,.05), P=[B(.85,0,.3,.3,1.0,.4,c),B(.2,1.0,.15,1.6,.05,.7,K.j(c,.05)),B(.3,1.05,.3,.25,.01,.18,'#efe9dc'),B(1.4,1.05,.4,.03,.1,.03,'#2b2c2e'),B(.6,0,.2,.8,.04,.6,c)];
    return K.down(.8)?withO(P,{roll:Math.PI/2,pv:[1,.5],lift:.15}):P; }},
  chairs3:{w:3,d:1,h:.9,cover:'half',build(K){ const P=[], f=K.j(pick(K.r,[K.st.fab,K.st.fab2,'#3b3a38']),.05); P.push(B(.1,0,.2,2.8,.05,.05,CHROME),B(.1,0,.75,2.8,.05,.05,CHROME));
    for(let k=0;k<3;k++){ const x=.15+k*.95; if(k===2&&K.r()<.4){ P.push(B(x,0,.2,.8,.5,.6,K.st.wood),B(x+.2,.5,.3,.25,.03,.2,pick(K.r,PAL.product))); continue; }
      const o=K.down()?{tilt:-Math.PI/2,pv:[x+.4,.15]}:undefined;
      P.push(B(x,.42,.2,.75,.08,.55,f,o),B(x,.5,.12,.75,.45,.1,f,o),B(x+.02,0,.25,.04,.42,.04,CHROME,o),B(x+.69,0,.25,.04,.42,.04,CHROME,o)); }
    litter(P,K,0,.8,3,.6,Math.round(K.mess*3));
    return P; }},
  atm:{w:1,d:1,h:1.75,cover:'full',slot:'atm',build(K){ const P=[B(.15,0,.05,.7,1.6,.6,'#5f6f73'),B(.18,1.1,.65,.64,.4,.04,'#2b2c2e'),B(.25,1.18,.68,.5,.25,.01,K.mess>.5?'#3a4044':'#2b6f8a'),B(.25,.95,.65,.5,.12,.15,'#3a3d40',{rx:.3}),B(.4,.8,.66,.2,.03,.02,BLACK),B(.15,1.6,.05,.7,.15,.6,K.j('#c23b2e',.1))];
    if(K.open||K.mess>.6) P.push(B(.2,.1,.66,.6,.6,.03,'#5f6f73',{yaw:1.2,pv:[.2,.66]}));
    return P; }},
  tellerwin:{w:1,d:1,h:2.2,cover:'full',slot:'register',build(K){ const P=[B(0,0,.1,1,1.05,.8,K.j(K.st.wood,.05)),B(-.01,1.05,.05,1.02,.05,.9,K.st.top),B(0,1.1,.44,.05,1.1,.04,CHROME),B(.95,1.1,.44,.05,1.1,.04,CHROME),B(.35,1.1,.4,.3,.04,.12,CHROME),B(.3,1.1,.12,.35,.25,.04,BLACK)];
    if(K.mess>.5&&K.r()<.6) P.push(B(.1+K.r()*.6,.003,.95+K.r()*.3,.14,.004,.1,'glass',{ry:K.r()*3})); else P.push(B(.05,1.1,.45,.9,1.1,.02,'glass'));
    P.push(B(.35,.85,.1-(K.open?.3:0),.3,.12,.35,'#3a3d40'));
    return P; }},
  depositbox:{w:1,d:1,h:2.3,cover:'full',slot:'deposit',build(K){ const P=[B(0,0,.02,1,2.3,.5,STEELD)];
    for(let r=0;r<7;r++) for(let c=0;c<3;c++){ const op=K.r()<K.mess*.6||(K.open&&K.r()<.5); const x=.04+c*.32, y=.1+r*.31; P.push(B(x,y,.52,.28,.27,.02,'#c9a24a',op?{yaw:1.4,pv:[x,.53]}:undefined)); if(op) P.push(B(x+.02,y+.02,.515,.24,.23,.005,'#1a1a1a')); }
    if(K.mess>.5) for(let k=0;k<3;k++) P.push(B(K.r()*.8,.002,.6+K.r()*.4,.25,.1,.4,STEEL,{ry:K.r()*3}));
    return P; }},
  receptiondesk:{w:3,d:1,h:1.15,cover:'full',slot:'desk',build(K){ const c=K.j(pick(K.r,[K.st.wood,'#d8d2c4','#3b3a38']),.05), P=[];
    P.push(B(.05,0,.55,2.9,1.1,.3,c),B(.02,1.1,.5,2.96,.04,.4,K.st.top),B(.05,0,.05,2.9,.74,.5,K.j(c,.08)),B(.02,.74,0,2.96,.04,.6,K.j(c,.05)));
    P.push(B(.6,.78,.1,.5,.32,.04,BLACK),B(.62,.8,.14,.46,.27,.005,'#22303a'),B(1.3,.78,.15,.35,.04,.15,'#3a3a3a'),B(2.1,1.14,.65,.1,.06,.1,CHROME));
    chair(P,K,.9+(K.r()-.5)*.4,-.35-K.r()*.2,[0,1],{style:'office',col:BLACK,seat:K.st.fab,yawJ:(K.r()-.5)*1.4,down:K.down()?2:0});
    litter(P,K,.2,.1,2.5,.4,2+Math.round(K.mess*3));
    return P; }},
  cubicle:{w:2,d:2,h:1.5,cover:'half',slot:'desk',build(K){ const P=[], pc=K.j(pick(K.r,['#7d8a8c','#9c917f','#5f6f73','#8f8577']),.04), t=K.st.top;
    P.push(B(0,0,0,2,1.45,.05,pc)); const side=B(0,0,0,.05,1.45,2,pc); P.push(...(K.r()<K.mess*.35?withO([side],{roll:Math.PI/2,pv:[.02,1],lift:.03}):[side]));
    P.push(B(.05,.72,.05,1.9,.04,.65,t),B(.05,.72,.7,.65,.04,1.2,t),B(1.85,0,.1,.05,.72,.55,STEELD),B(.1,0,1.8,.55,.72,.05,STEELD));
    P.push(B(.15,.76,.1,.5,.32,.04,BLACK),B(.17,.78,.14,.46,.27,.005,K.mess>.5?'#3a4044':'#22303a'),B(.3,.76,.45,.4,.02,.15,'#3a3a3a'));
    drawers(P,K,1.3,1.8,.05,.7,.7,3,1,STEELD,CHROME);
    for(let k=0;k<3;k++) P.push(B(.5+K.r()*1.2,.76,.2+K.r()*.3,.21,.004+k*.005,.28,'#efe9dc',{ry:(K.r()-.5)*.6}));
    if(K.r()<.6) P.push(B(1.6,.76,.12,.12,.15,.04,pick(K.r,PAL.product))); if(K.r()<.5) P.push(B(.85,.76,.15,.12,.14,.12,TERRA),B(.88,.9,.18,.06,.2,.06,K.mess>.4?'#7a6a3a':'#5f7d3f'));
    chair(P,K,1.0+(K.r()-.5)*.4,1.2+K.r()*.4,[0,-1],{style:'office',col:BLACK,seat:K.j(pick(K.r,[K.st.fab,'#2b2c2e','#3f5f86','#5f6f73','#7a2e35']),.05),yawJ:(K.r()-.5)*1.6,down:K.down()?(K.r()<.5?1:2):0});
    litter(P,K,.3,.9,1.5,1,Math.round(K.mess*4));
    return P; }},
  printer:{w:1,d:1,h:1.2,cover:'half',build(K){ const P=[B(.1,0,.1,.8,.95,.65,'#d8d2c4'),B(.12,.95,.12,.76,.15,.6,'#c9c4b8'),B(.2,.4,.75,.6,.12,.02,'#9c968a'),B(.2,.2,.75,.6,.12,.02,'#9c968a'),B(.6,1.1,.6,.2,.04,.1,BLACK)];
    if(K.mess>.4) litter(P,K,0,.8,1,.6,3); return P; }},
  watercooler:{w:1,d:1,h:1.5,cover:'none',build(K){ const P=[B(.3,0,.25,.4,1.0,.4,'#e8e4da'),B(.38,.85,.63,.06,.06,.06,'#c23b2e'),B(.56,.85,.63,.06,.06,.06,'#2f6fa0')];
    if(K.r()>K.mess*.7) P.push(B(.32,1.0,.27,.36,.45,.36,'glass'),B(.32,1.0,.27,.36,.45,.36,'glass',{ry:Math.PI/4})); else P.push(B(.4,0,.6,.36,.36,.45,'#7fb7c9',{ry:K.r()*3}));
    return P; }},
  conftable:{w:4,d:2,h:.8,cover:'half',build(K){ const P=[], c=K.j(pick(K.r,[K.st.wood,'#3b3a38','#d8d2c4']),.04);
    const T=[B(.3,.72,.45,3.4,.05,1.1,c),B(1.0,0,.85,.25,.72,.3,STEELD),B(2.75,0,.85,.25,.72,.3,STEELD),B(1.9,.77,.95,.2,.05,.1,BLACK)];
    P.push(...withO(T,K.down(.8)?{roll:Math.PI/2,pv:[2,1],lift:.55}:{}));
    for(let k=0;k<4;k++) for(const sg of [-1,1]){ if(K.r()<.1) continue; chair(P,K,.7+k*.86+(K.r()-.5)*.2,1+sg*(.85+K.r()*.2),[0,-sg],{style:'office',col:BLACK,seat:K.j(K.st.fab,.04),yawJ:(K.r()-.5)*(.6+K.mess),down:K.down()?(K.r()<.5?1:2):0}); }
    litter(P,K,.4,.5,3.2,1,Math.round(K.mess*5));
    return P; }},
  vending:{w:1,d:1,h:1.85,cover:'full',slot:'vending',build(K){ const c=K.j(pick(K.r,['#c23b2e','#2f6fa0','#2b2c2e']),.05), P=[B(.05,0,.05,.9,1.85,.75,c)];
    const broken=K.mess>.5&&K.r()<.6; P.push(B(.1,.4,.8,.6,1.3,.01,broken?'#1a1a1a':'glass'),B(.75,.9,.8,.18,.5,.02,'#3a3d40'),B(.15,.12,.8,.55,.18,.02,BLACK));
    for(let r=0;r<5;r++) for(let k=0;k<4;k++) if(K.r()>K.gone) P.push(B(.13+k*.14,.48+r*.24,.4,.1,.14,.35,pick(K.r,PAL.product)));
    if(broken) for(let k=0;k<3;k++) P.push(B(K.r()*.8,.003,.9+K.r()*.4,.12,.03,.08,'glass',{ry:K.r()*3}));
    return K.down(.7)?withO(P,{tilt:Math.PI/2*.92,pv:[.5,.8],lift:.02}):P; }},
  serverrack:{w:1,d:1,h:2.1,cover:'full',build(K){ const P=[B(.1,0,.05,.8,2.1,.8,'#1e1e20')];
    for(let k=0;k<10;k++){ P.push(B(.15,.2+k*.18,.86,.7,.14,.01,'#2b2c2e')); for(let q=0;q<3;q++) if(K.r()<.5) P.push(B(.2+q*.06,.25+k*.18,.87,.03,.03,.005,K.mess>.5?'#3a3a3a':pick(K.r,['#3cd07a','#ffb23c']))); }
    if(K.r()<.6) P.push(B(.2,0,.85,.6,.02,.6,'#2f6fa0',{ry:.3}));
    return P; }},
  dentchair:{w:2,d:2,h:1.9,cover:'half',build(K){ const P=[], up=K.j(pick(K.r,['#2f8f8a','#3f5f86','#e8e4da','#6b4f7a']),.04);
    P.push(B(.7,0,.4,.6,.35,1.2,'#e8e4da'),B(.65,.35,.35,.7,.12,.7,up),B(.65,.45,.15,.7,.08,.55,up,{rx:-.45}),B(.75,.62,-.05,.5,.08,.25,up,{rx:-.2}),B(.65,.33,1.0,.7,.1,.7,up,{rx:.3}));
    P.push(B(1.45,0,.3,.08,1.9,.08,'#d8d2c4'),B(1.0,1.85,.3,.5,.06,.06,'#d8d2c4'),B(.85,1.75,.2,.35,.12,.25,'#e8e4da'),B(1.5,.9,.9,.4,.04,.3,'#d8d2c4'),B(1.6,.94,.95,.08,.02,.18,CHROME));
    chair(P,K,1.6,1.6,[-1,0],{style:'stool',seat:up,yawJ:K.r()*2,down:K.down()?2:0});
    return P; }},
  examtable:{w:2,d:1,h:1.0,cover:'half',build(K){ const P=[];
    if(K.st.what==='veterinary') P.push(B(.15,0,.25,.1,.85,.1,STEELD),B(1.75,0,.25,.1,.85,.1,STEELD),B(.1,.85,.15,1.8,.05,.7,STEEL),B(.3,0,.5,.6,.4,.4,'#7a7f82'));
    else P.push(B(.15,0,.15,1.7,.6,.6,'#e8e4da'),B(.1,.6,.1,1.8,.15,.7,K.j(pick(K.r,['#2f8f8a','#3f5f86','#7a2e35']),.05)),B(.1,.72,.1,.5,.12,.7,K.j('#2f8f8a',.05),{rz:.3}),B(.35,.76,.15,1.5,.004,.6,'#efe9dc'),B(1.9,.2,.2,.08,.3,.5,'#d8d2c4'));
    if(K.r()<K.mess) P.push(B(.4+K.r(),.003,.85+K.r()*.3,.6,.004,.4,'#efe9dc',{ry:K.r()*3}));
    return P; }},
  liftcar:{w:2,d:5,h:2.6,cover:'full',slot:'car',build(K){ const P=[];
    for(const x of [-.25,2.05]) P.push(B(x,0,2.2,.2,3.0,.3,'#c23b2e'),B(x-.05,0,2.1,.3,.05,.5,'#3a3d40'));
    for(const z of [1.2,3.6]) P.push(B(-.05,.85,z,.75,.06,.12,STEELD),B(1.3,.85,z,.75,.06,.12,STEELD));
    if(K.r()<.8) P.push(...withO(carParts(K),{lift:.95,pv:[1,2.5]}));
    P.push(B(.7,0,2.2,.6,.15,.6,'#c9953f'),B(.75,.15,2.25,.5,.02,.5,'#2b2018'));
    return P; }},
  toolchest:{w:1,d:1,h:1.4,cover:'half',slot:'toolchest',build(K){ const c=K.j(pick(K.r,['#c23b2e','#2b2c2e','#2f6fa0']),.05), P=[B(.05,.1,.1,.9,1.0,.6,c),B(.05,1.1,.1,.9,.25,.55,K.j(c,.05))];
    drawers(P,K,.08,.92,.12,1.08,.7,6,1,K.j(c,.08),CHROME); for(const x of [.1,.8]) P.push(B(x,0,.15,.1,.1,.1,BLACK)); P.push(B(.2,1.35,.2,.4,.05,.1,pick(K.r,['#7d8285','#c9953f'])));
    return P; }},
  tires:{w:1,d:1,h:1.2,cover:'half',build(K){ const P=[], n=2+Math.floor(K.r()*4); for(let k=0;k<n;k++){ const y=k*.22, dx=(K.r()-.5)*.08; P.push(B(.15+dx,y,.15,.7,.21,.7,'#1e1e1e'),B(.15+dx,y,.15,.7,.21,.7,'#232323',{ry:Math.PI/4})); }
    if(K.mess>.4) P.push(B(.0,.0,.6,.21,.7,.7,'#1e1e1e',{rz:(K.r()-.5)*.6})); return P; }},
  drums:{w:1,d:1,h:.95,cover:'full',slot:'drums',build(K){ const c=K.j(pick(K.r,['#2f6fa0','#c23b2e','#3f5f86','#e0a526']),.06); const P=[B(.2,0,.2,.6,.9,.6,c),B(.2,0,.2,.6,.9,.6,K.j(c,.04),{ry:Math.PI/4}),B(.2,.3,.2,.6,.03,.6,K.j(c,.15)),B(.2,.6,.2,.6,.03,.6,K.j(c,.15))];
    if(K.mess>.4) P.push(B(.4,.001,.8,.5+K.r()*.4,.004,.4,'#1a1610',{ry:K.r()*3}));
    return K.down(.8)?withO(P,{roll:Math.PI/2,pv:[.5,.5],lift:.3}):P; }},
  station:{w:1,d:1,h:2.0,cover:'half',slot:'station',build(K){ const P=[], broken=K.r()<K.mess*.5;
    P.push(B(.05,1.0,0,.9,1.0,.05,'#3b3a38'),B(.1,1.05,.05,.8,.9,.005,broken?'#6c7a7e':'#bcd0d6'),B(.05,.75,.02,.9,.05,.35,K.st.top));
    for(let k=0;k<4;k++) if(K.r()>K.gone) P.push(B(.12+k*.2,.8,.08,.06,.12+K.r()*.1,.06,pick(K.r,PAL.product)));
    const cc=K.j(pick(K.r,['#2b2c2e','#7a2e35','#3f5f86']),.05), cx=.5, cz=.75;
    const o={yaw:(K.r()-.5)*(.6+K.mess*2),pv:[cx,cz]}; const C=[B(cx-.25,0,cz-.25,.5,.05,.5,CHROME),B(cx-.05,0,cz-.05,.1,.42,.1,CHROME),B(cx-.25,.42,cz-.25,.5,.1,.5,cc),B(cx-.25,.52,cz+.15,.5,.5,.1,cc),B(cx-.3,.5,cz-.25,.06,.2,.45,cc),B(cx+.24,.5,cz-.25,.06,.2,.45,cc)];
    P.push(...withO(C,K.down()?Object.assign(o,{roll:Math.PI/2,lift:.25}):o));
    if(broken) for(let k=0;k<3;k++) P.push(B(.1+K.r()*.7,.003,.4+K.r()*.4,.1,.004,.07,'glass',{ry:K.r()*3}));
    if(K.mess>.3) for(let k=0;k<3;k++) P.push(B(K.r()*.8,.002,.3+K.r()*.6,.15,.004,.1,'#5a4030',{ry:K.r()*3})); // hair on the floor
    return P; }},
  washsink:{w:1,d:1,h:1.0,cover:'half',build(K){ return [B(.15,0,0,.7,.85,.35,'#2b2c2e'),B(.2,.85,.02,.6,.12,.32,'#e8e4da'),B(.45,.97,.05,.05,.12,.05,CHROME),B(.2,0,.4,.6,.42,.5,'#2b2c2e'),B(.2,.42,.4,.6,.1,.5,'#3a3a3a'),B(.2,.52,.35,.6,.45,.12,'#3a3a3a',{rx:.6})]; }},
  showcase:{w:2,d:1,h:1.05,cover:'full',slot:'showcase',build(K){ const P=[B(.05,0,.15,1.9,.75,.7,K.j(pick(K.r,['#2b2c2e','#e8e4da',K.st.wood]),.05)),B(.08,.75,.18,1.84,.02,.64,'#3a2a4a')];
    const smashed=K.r()<K.mess*.7; if(!smashed) P.push(B(.05,.77,.15,1.9,.28,.02,'glass'),B(.05,.77,.83,1.9,.28,.02,'glass'),B(.05,1.04,.15,1.9,.02,.7,'glass')); else for(let k=0;k<5;k++) P.push(B(K.r()*1.8,.002,.9+K.r()*.4,.12,.004,.08,'glass',{ry:K.r()*3}));
    for(let k=0;k<8;k++) if(K.r()>K.gone+(smashed?.3:0)) P.push(B(.15+K.r()*1.6,.77,.25+K.r()*.45,.06,.03,.06,pick(K.r,['#e8d64a','#d7dadc','#bcd0d6','#c23b2e'])));
    return P; }},
  garmentrack:{w:1,d:1,h:2.0,cover:'half',slot:'garments',build(K){ const L=K.w, P=[B(0,1.9,.48,L,.04,.04,CHROME),B(0,0,.46,.04,1.9,.08,CHROME),B(L-.04,0,.46,.04,1.9,.08,CHROME)];
    let x=.05; while(x<L-.05){ if(K.r()>K.gone){ P.push(B(x,.9,.3,.05,.98,.4,pick(K.r,PAL.fab)),B(x,.88,.28,.06,1.0,.44,'glass')); } else if(K.r()<K.mess*.3) P.push(B(x,.003,.9+K.r()*.4,.5,.04,.35,pick(K.r,PAL.fab),{ry:K.r()*3})); x+=.09; }
    return P; }},
  pobox:{w:2,d:1,h:2.0,cover:'full',slot:'pobox',build(K){ const P=[B(0,0,.02,2,2,.35,'#8a6a4a')]; for(let r=0;r<8;r++) for(let c=0;c<8;c++){ const x=.05+c*.24, y=.3+r*.2, op=K.r()<K.mess*.4; P.push(B(x,y,.37,.2,.16,.02,'#c9a24a',op?{yaw:1.3,pv:[x,.38]}:undefined)); }
    if(K.mess>.4) litter(P,K,0,.5,2,.5,4); return P; }},
  hshelf:{w:1,d:1,h:2.2,cover:'full',slot:'shelf',build(K){ const L=K.w, P=[B(0,0,.1,L,.15,.8,'#4a4d50'),B(0,0,.48,L,2.2,.04,'#c9b38a')];
    for(let k=0;k<4;k++){ const y=.15+k*.5; P.push(B(0,y,.1,L,.025,.38,K.st.fixture),B(0,y,.52,L,.025,.38,K.st.fixture)); let x=.05;
      while(x<L-.15){ const w=.12+K.r()*.2; if(K.r()>K.gone){ const t=K.r();
        if(t<.35) P.push(B(x,y+.03,.15,w,.18,.18,pick(K.r,['#e0a526','#c23b2e','#2f6fa0','#3f8f5a'])),B(x,y+.03,.55,w,.18,.18,pick(K.r,['#e0a526','#c23b2e','#2f6fa0'])));
        else if(t<.6) P.push(B(x,y+.03,.18,.18,.2,.18,'#d8d2c4'),B(x,y+.23,.18,.18,.02,.18,pick(K.r,PAL.product)),B(x,y+.03,.6,.18,.2,.18,'#d8d2c4'));
        else P.push(B(x,y+.15,.12,.03,.25,.04,pick(K.r,['#7d8285','#c23b2e','#e0a526'])),B(x,y+.15,.6,.03,.25,.04,'#7d8285')); }
        x+=w+.04; } }
    for(let k=0;k<Math.round(K.mess*3*L);k++) P.push(B(K.r()*L,.003,.95+K.r()*.4,.15,.12,.12,pick(K.r,PAL.product),{ry:K.r()*3}));
    return K.r()<K.mess*.2?withO(P,{tilt:Math.PI/2*.88,pv:[L/2,.9],lift:.02}):P; }},
  tallshelf:{w:2,d:1,h:2.6,cover:'full',slot:'rshelf',build(K){ const P=[]; for(const x of [.03,1.9]) P.push(B(x,0,.05,.07,2.6,.07,'#d9662a'),B(x,0,.85,.07,2.6,.07,'#d9662a'));
    for(let k=0;k<3;k++){ const y=.1+k*.85; P.push(B(.03,y,.05,1.94,.06,.87,'#2f6fa0')); if(K.r()>K.gone) P.push(B(.2,y+.06,.15,.7,.5,.65,pick(K.r,['#c9b38a','#b49a78','#e8e4da'])),B(1.05,y+.06,.15,.7,.4+K.r()*.2,.65,pick(K.r,['#c9b38a','#b49a78','#3f8f5a','#c23b2e']))); }
    if(K.mess>.4) P.push(B(.3,0,.95,.8,.5,.6,'#c9b38a',{ry:K.r()*2,rz:.4}));
    return P; }},
  keycut:{w:2,d:1,h:1.9,cover:'half',build(K){ const P=[B(.05,0,.1,1.9,.95,.75,K.j(K.st.wood,.05)),B(.03,.95,.08,1.94,.04,.79,K.st.top),B(.3,.99,.3,.35,.25,.3,'#5f6f73'),B(1.0,.99,.3,.3,.2,.25,'#5f6f73'),B(.05,.99,.02,1.9,.9,.03,'#c9b38a')];
    for(let r=0;r<4;r++) for(let c=0;c<12;c++) if(K.r()>K.gone) P.push(B(.12+c*.15,1.1+r*.18,.05,.03,.08,.01,'#c9a24a'));
    return P; }},
  paintcounter:{w:2,d:1,h:1.6,cover:'full',slot:'paint',build(K){ const P=[B(.05,0,.1,1.9,.95,.75,'#e8e4da'),B(.03,.95,.08,1.94,.04,.79,K.st.top),B(.2,.99,.15,.5,.6,.5,'#c23b2e'),B(.25,1.2,.6,.4,.05,.05,'#2b2c2e'),B(1.0,.99,.2,.5,.5,.45,'#d8d2c4')];
    for(let k=0;k<6;k++) P.push(B(.8+(k%3)*.35,.99+Math.floor(k/3)*.2,.6,.18,.19,.18,pick(K.r,['#e8e4da','#c9693a','#2f6fa0','#3f8f5a','#e0a526'])));
    for(let k=0;k<Math.round(K.mess*4);k++) P.push(B(K.r()*1.6,.002,.9+K.r()*.5,.4,.004,.3,pick(K.r,['#c9693a','#2f6fa0','#e8e4da','#3f8f5a']),{ry:K.r()*3})); // spilt paint
    return P; }},
  mcase:{w:2,d:1,h:2.1,cover:'full',slot:'cooler',build(K){ const P=[B(.02,0,0,1.96,2.1,.15,'#3a3d40'),B(.02,0,0,1.96,.4,.85,'#e8e4da'),B(.02,1.9,0,1.96,.2,.6,'#e8e4da'),B(.02,1.88,.55,1.96,.04,.05,K.mess>.5?'#9a9e9f':'#e8f4ff')];
    for(let k=0;k<4;k++){ const y=.4+k*.38, d=.75-k*.1; P.push(B(.04,y,.15,1.92,.02,d,'#c8ccce')); let x=.06; while(x<1.9){ const w=.12+K.r()*.2; if(K.r()>K.gone) P.push(B(x,y+.02,.2+K.r()*.1,w-.01,.18+K.r()*.12,d-.15,pick(K.r,PAL.product))); x+=w; } }
    if(K.mess>.5) for(let k=0;k<4;k++) P.push(B(K.r()*1.8,.003,.95+K.r()*.4,.15,.12,.1,pick(K.r,PAL.product),{ry:K.r()*3}));
    return P; }},
  produce:{w:2,d:2,h:1.4,cover:'half',slot:'produce',build(K){ const c=K.j(K.st.wood,.06), P=[B(.2,0,.2,1.6,.6,1.6,c)];
    for(let k=0;k<4;k++){ const x=.22+(k%2)*.8, z=.22+Math.floor(k/2)*.8; P.push(B(x,.6,z,.76,.08,.76,K.j(c,.05),{rx:Math.floor(k/2)?-.2:.2}));
      const rot=K.r()<K.gone+.4, col=rot?pick(K.r,['#6b5a40','#5a4a30','#7a6a3a']):pick(K.r,['#c23b2e','#e0a526','#3f8f5a','#d97a2a','#7a2e35','#a7b85a']);
      for(let q=0;q<5;q++) P.push(B(x+.05+K.r()*.55,.66,z+.05+K.r()*.55,.12,.1,.12,jit(col,K.r,.1))); }
    P.push(B(.95,.6,.95,.1,.7,.1,STEELD),B(.6,1.3,.6,.8,.04,.8,'#3f8f5a'));
    return K.down(.6)?withO(P,{roll:Math.PI/2,pv:[1,1],lift:.8}):P; }},
  carts:{w:2,d:1,h:1.0,cover:'half',build(K){ const P=[]; for(let k=0;k<5;k++){ const x=.1+k*.32, o=k>3&&K.mess>.4?{yaw:(K.r()-.5)*2,pv:[x+.3,.5]}:undefined;
    P.push(B(x,.35,.15,.55,.55,.7,'glass',o),B(x,.35,.15,.55,.02,.7,CHROME,o),B(x,.88,.12,.55,.03,.74,CHROME,o),B(x+.05,0,.2,.04,.35,.04,CHROME,o),B(x+.48,0,.2,.04,.35,.04,CHROME,o),B(x+.05,0,.75,.04,.35,.04,CHROME,o),B(x+.48,0,.75,.04,.35,.04,CHROME,o),B(x+.05,.95,.82,.45,.04,.04,'#c23b2e',o)); }
    return P; }},
  pizzaoven:{w:2,d:1,h:1.8,cover:'full',build(K){ return [B(.05,0,.05,1.9,.25,.85,STEELD),B(.05,.25,.05,1.9,.55,.85,STEEL),B(.05,.85,.05,1.9,.55,.85,STEEL),B(.15,.4,.88,1.7,.18,.03,BLACK),B(.15,1.0,.88,1.7,.18,.03,BLACK),B(.15,.6,.9,1.7,.03,.04,CHROME),B(.15,1.2,.9,1.7,.03,.04,CHROME),B(.7,1.4,.3,.15,.4,.15,STEELD),B(1.5,.3,.9,.06,.06,.6,'#8a6a4a',{rx:.2})]; }},
  wok:{w:2,d:1,h:2.4,cover:'half',build(K){ const P=[B(.05,0,0,1.9,.85,.85,STEELD),B(.05,.85,0,1.9,.04,.85,STEEL)];
    for(let k=0;k<3;k++){ const x=.35+k*.6; P.push(B(x-.22,.89,.2,.44,.1,.44,'#2b2b2b'),B(x-.22,.89,.2,.44,.1,.44,'#2b2b2b',{ry:Math.PI/4}),B(x+.15,.95,.38,.35,.03,.04,'#5a4030')); }
    P.push(B(.05,.89,0,1.9,.4,.05,STEEL),B(0,1.95,0,2,.45,.85,STEEL)); return P; }},
  barcounter:{w:3,d:1,h:1.15,cover:'full',slot:'bar',build(K){ const c=K.j(K.st.wood,.06), P=[B(.05,0,.05,2.9,1.05,.55,c),B(.02,1.05,0,2.96,.06,.75,K.j(c,.08)),B(.05,.1,.6,2.9,.04,.06,CHROME)];
    for(let k=0;k<4;k++) P.push(B(.4+k*.18,1.11,.12,.04,.35,.04,CHROME),B(.36+k*.18,1.4,.1,.12,.08,.08,pick(K.r,['#e0a526','#2b2c2e','#c23b2e','#3f8f5a'])));
    for(let k=0;k<5;k++) if(K.r()>K.gone) P.push(B(1.4+k*.25,1.11,.15+K.r()*.3,.07,.22,.07,pick(K.r,['#3f8f5a','#7a4a2c','glass','#e0a526'])));
    for(let k=0;k<4;k++) chair(P,K,.4+k*.7+(K.r()-.5)*.15,1.05+K.r()*.3,[0,-1],{style:'stool',seat:K.j(K.st.vinyl,.05),yawJ:K.r()*2,down:K.down()?2:0});
    return P; }},
  pump:{w:2,d:3,h:5,cover:'full',slot:'pump',build(K){ const P=[B(.3,0,.1,1.4,.18,2.8,'#d8d2c4'),B(.3,.18,.1,1.4,.02,2.8,'#e0a526')];
    for(const z of [.4,1.9]){ const c=K.j(pick(K.r,['#c23b2e','#e8e4da','#2f6fa0']),.04);
      const D=[B(.55,.2,z,.9,1.6,.5,c),B(.6,1.2,z+.5,.8,.35,.02,'#2b2c2e'),B(.62,1.25,z+.51,.3,.12,.01,K.mess>.4?'#3a4044':'#7fd0a0'),B(.55,1.8,z,.9,.15,.5,'#2b2c2e'),B(.5,.9,z+.1,.05,.6,.05,'#1e1e1e')];
      for(let k=0;k<3;k++) D.push(B(.62+k*.27,.9,z+.5,.12,.2,.08,pick(K.r,['#2b2c2e','#e0a526','#3f8f5a'])));
      if(K.r()<K.mess*.5) D.push(B(.2,.003,z+.7,.05,.03,1.2,'#1e1e1e',{ry:(K.r()-.5)*1.5})); // hose on the ground
      P.push(...(K.down(.5)?withO(D,{tilt:Math.PI/2,pv:[1,z+.5,.2]}):D)); }
    P.push(B(.88,.2,1.38,.24,4.8,.24,'#d8d2c4'),B(.88,.2,1.38,.24,4.8,.24,'#e8e4da',{ry:Math.PI/4}));
    P.push(B(.45,.2,2.65,.3,.7,.3,'#2b2c2e'),B(1.3,.2,.12,.15,.35,.15,'#2f6fa0'));
    for(const z of [.05,2.85]) P.push(B(.25,0,z,.12,.9,.12,'#e0a526'),B(1.65,0,z,.12,.9,.12,'#e0a526'));
    litter(P,K,-.5,-.6,3,4.2,Math.round(K.mess*4));
    return P; }},
});
Object.assign(DECOR,{
  menuboard(K){ const lit=K.mess<.4&&K.r()<.6, P=[B(-.4,1.9,.12,1.8,.7,.05,'#1e1e1e')]; for(let k=0;k<6;k++) P.push(B(-.3+(k%3)*.58,2.25-Math.floor(k/3)*.32,.17,.5,.26,.01,lit?pick(K.r,['#e0a526','#c23b2e','#3f8f5a','#e8e4da']):'#3a3a3a')); return P; },
  chalk(K){ const P=[B(.05,1.3,.12,.9,.8,.03,'#5a4030'),B(.09,1.34,.15,.82,.72,.005,'#2b3a32')]; for(let k=0;k<6;k++) P.push(B(.15,1.95-k*.1,.155,.25+K.r()*.4,.02,.003,pick(K.r,['#efe9dc','#e8c87a','#f3a7b8']))); return P; },
  poster(K){ const w=.5+K.r()*.3, h=.7+K.r()*.2, x=.5-w/2, y=1.25; const P=[B(x,y,.12,w,h,.02,K.mess>.6?'#c9c0a8':pick(K.r,['#e8e4da','#2f6fa0','#c23b2e','#e0a526']))]; P.push(B(x+.05,y+h*.55,.14,w-.1,h*.35,.003,pick(K.r,PAL.fab)),B(x+.05,y+.08,.14,w*.6,.06,.003,'#2b2c2e'));
    return K.mess>.5&&K.r()<.5?withO(P,{roll:.3,pv:[.5,.12]}):P; },
  whiteboard(K){ const P=[B(-.3,1.0,.12,1.6,1.0,.03,'#d8dadc'),B(-.27,1.03,.15,1.54,.94,.005,'#f4f4f2'),B(-.3,.98,.12,1.6,.03,.08,'#9a9e9f')]; for(let k=0;k<5;k++) P.push(B(-.2+K.r()*1.0,1.2+K.r()*.7,.156,.15+K.r()*.4,.015,.002,pick(K.r,['#2f6fa0','#c23b2e','#2b2c2e','#3f8f5a']),{rz:(K.r()-.5)*.4})); return P; },
  screen(K){ return [B(-.3,1.3,.12,1.6,.9,.06,BLACK),B(-.26,1.34,.18,1.52,.82,.005,K.mess>.4?'#3a4044':'#22303a')]; },
  certificate(K){ const P=[]; for(let k=0;k<3;k++) P.push(B(.05+k*.32,1.5+(k%2)*.1,.12,.26,.32,.02,'#5a4030'),B(.07+k*.32,1.52+(k%2)*.1,.14,.22,.28,.003,'#efe9dc')); return P; },
  lantern(K){ const P=[]; for(let k=0;k<3;k++){ const x=.15+k*.3, y=2.2+K.r()*.2, c=pick(K.r,['#c23b2e','#c23b2e','#e0a526']); P.push(B(x+.07,y+.25,.4,.01,.4,.01,'#2b2c2e'),B(x,y,.33,.16,.25,.16,c),B(x,y,.33,.16,.25,.16,c,{ry:Math.PI/4}),B(x+.03,y-.04,.36,.1,.04,.1,'#e0a526')); } return P; },
  papel(K){ const P=[B(0,2.45,.15,1,.01,.01,'#2b2c2e')]; for(let k=0;k<4;k++) P.push(B(.03+k*.25,2.22,.15,.2,.22,.005,pick(K.r,['#d94f8a','#e0a526','#3f8f5a','#2f6fa0','#c23b2e','#9b4fc4']),{rz:(K.r()-.5)*.2})); return P; },
  scroll(K){ return [B(.4,1.1,.12,.3,1.0,.01,'#efe3c8'),B(.38,2.1,.12,.34,.03,.03,'#5a4030'),B(.38,1.08,.12,.34,.03,.03,'#5a4030'),B(.5,1.4,.13,.04,.5,.002,'#2b2c2e')]; },
});
Object.assign(DECOR_BY,{
  ffdining:['menuboard','poster','poster','photo','flag'], cafe:['chalk','photo','shelfDecor','clock','poster'], lobby:['poster','clock','flag','photo'], teller:['poster','clock'],
  reception:['poster','photo','clock'], openoffice:['whiteboard','poster','clock','photo'], conference:['screen','whiteboard'], breakroom:['clock','poster'],
  waiting:['poster','certificate','clock','photo'], exam:['certificate','poster'], salon:['poster','photo','neon'], bay:['plates','poster','neon','horseshoe'],
  rdining:st=>st.cuisine==='asian'?['lantern','lantern','scroll','photo']:st.cuisine==='mexican'?['papel','papel','skull','photo','flag']:st.cuisine==='pizza'?['photo','neon','menu','plates']:st.cuisine==='bar'?['neon','neon','screen','plates','flag','skull','wheel']:['neon','photo','flag','skull','plates','wheel','menu','horseshoe'],
});
