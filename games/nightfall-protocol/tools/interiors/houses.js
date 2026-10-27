// ================================================================= building design: roofs, walls, storeys and footings
// A house's design comes from where it stands (the region), when it went up (the era), its footprint and its lot.
// Shops and offices get a simpler pass: what sits on top of the box. Everything is seeded from the building's
// identity, so a building never changes between visits. Tables here are the content; the sheet explains them.
const wpick=(rng,w)=>{ let t=0; for(const k in w) t+=Math.max(0,w[k]); if(t<=0) return null; let x=rng()*t; for(const k in w){ x-=Math.max(0,w[k]); if(x<=0) return k; } return Object.keys(w).pop(); };
const rrange=(rng,a)=>a[0]+(a[1]-a[0])*rng();

// Roof coverings. pitch: the range it is laid at, in inches of rise per 12 of run. pat: how the courses read
// from above (courses run along the eave, ribs and seams run down the slope, flat is one sheet).
const ROOFMAT={
  shingle:   {n:'Asphalt shingle',          pat:'courses', s:.34, pitch:[3,14], cols:[['#5d5a55','#55524d'],['#6e5a4a','#655243'],['#4a4f55','#43484e'],['#7a6a58','#716150'],['#3f3d3b','#383634']]},
  ctile:     {n:'Concrete S-tile',          pat:'ribs',    s:.3,  pitch:[3,8],  cols:[['#a8553d','#9b4c35'],['#b07a4f','#a46f46'],['#8a7a62','#7f7059'],['#9c6a4a','#906042']]},
  clay:      {n:'Clay barrel tile',         pat:'ribs',    s:.26, pitch:[3,7],  cols:[['#b0623f','#a25838'],['#c4703f','#b66637'],['#a85a3a','#9a5134']]},
  metal:     {n:'Standing-seam metal',      pat:'seams',   s:.46, pitch:[1,16], cols:[['#6f7f86','#68777e'],['#7a3b33','#72362f'],['#3f5a4a','#3a5344'],['#9aa0a3','#92989b'],['#5a5550','#534e4a']]},
  corrugated:{n:'Corrugated metal',         pat:'ribs',    s:.3,  pitch:[1,6],  cols:[['#a7aaa8','#9c9f9d'],['#8a8f8c','#808582'],['#9a7a5a','#8f7053']]},
  shake:     {n:'Cedar shake',              pat:'courses', s:.28, pitch:[5,16], cols:[['#7a6450','#705c49'],['#8a7358','#7f6a51'],['#6a6058','#625851']]},
  slate:     {n:'Slate',                    pat:'courses', s:.26, pitch:[6,20], cols:[['#4b5058','#454a51'],['#5a5560','#534e59'],['#56605e','#4f5957']]},
  foam:      {n:'Spray foam, white coat',   pat:'flat',            pitch:[0,1],  cols:[['#e2ddd2','#dad5ca']]},
  builtup:   {n:'Tar and gravel',           pat:'flat',            pitch:[0,1],  cols:[['#8d877c','#868075'],['#9a9488','#938d81']]},
  membrane:  {n:'Single-ply membrane',      pat:'seams',   s:1.8, pitch:[0,1],  cols:[['#e8e6e0','#dfddd7'],['#c9cccb','#c1c4c3']]},
  rolled:    {n:'Rolled roofing',           pat:'courses', s:.9,  pitch:[1,4],  cols:[['#3e3c39','#383633'],['#5a5348','#534c42']]},
};
// Outside wall finishes and the build-up behind them (the build-up decides how a wall breaks).
const CLAD={
  stucco:     {n:'Stucco',            mat:'frame',  cols:['#d9c7a6','#cfc3ae','#e3c9a8','#e8e2d4','#bfb79c','#d8b48a','#a8b0a0','#e0b48c','#d6bfa0']},
  adobe:      {n:'Adobe',             mat:'adobe',  cols:['#b8855a','#c49870','#a87a52','#c9a27a']},
  block:      {n:'Painted slump block',mat:'block', cols:['#cdbb9c','#d6c8ad','#b9a888','#e0d4bc'], pat:'block'},
  brick:      {n:'Brick',             mat:'brick',  cols:['#9c4a32','#a85a3f','#8a3f2a','#b0704f','#7a4a3a'], pat:'brick'},
  siding:     {n:'Lap siding',        mat:'siding', cols:['#e8e4da','#c9d2d6','#b8c4b0','#d9c49a','#e3cfc2','#8fa3a8','#a24a3c','#f0ece2','#6b7a5a'], pat:'lap'},
  boardbatten:{n:'Board and batten',  mat:'siding', cols:['#8a6a4a','#6b5a48','#c9bfae','#5a6b5a','#9c8a72'], pat:'batten'},
  shingles:   {n:'Cedar shingle siding',mat:'siding',cols:['#9a7f62','#8a7055','#b8a088','#7e8a8c'], pat:'lap'},
  log:        {n:'Log',               mat:'log',    cols:['#8a6a4a','#9c7a52','#7a5a3c'], pat:'log'},
  panel:      {n:'Vinyl panel siding', mat:'metal', cols:['#e8e4da','#d9d4c4','#c9d2d6','#b8b0a0','#d8c8a8'], pat:'lap'},
};
const TRIM=['#e8e4da','#f2efe8','#3a3330','#5a4030','#2f4f6a','#7a2e35','#3f5a4a','#8a6a4a'];

// Footings. y is where the main floor sits above the highest ground under the house.
const FOUND={
  slab:    {n:'Slab on grade', above:.12},
  crawl:   {n:'Crawlspace on a stem wall', above:.6},
  basement:{n:'Full basement', above:.45},
  walkout: {n:'Walk-out lower floor on the downhill side', above:.35},
  piers:   {n:'Posts and beams over the slope', above:.75},
  raised:  {n:'Raised on piers', above:2.2},
  chassis: {n:'Steel chassis on piers, skirted', above:.75},
};

// Regions: which houses get built there, which eras, what footing is normal on a level lot.
const REGIONS={
  sonoran:  {n:'Arizona: Sonoran desert', found:{slab:1}, eras:{postwar:.12,seventies:.33,modern:.38,recent:.17},
    arch:{ranch:3,tract:2.6,pueblo:1.4,territorial:.6,spanish:1.2,mcm:.8,manufactured:2.4,hillside:.6,cabin:.25,aframe:.12}},
  mountain: {n:'Mountain West', found:{basement:.45,crawl:.4,slab:.15}, eras:{postwar:.2,seventies:.35,modern:.3,recent:.15},
    arch:{ranch:2.4,cabin:2,aframe:1,craftsman:1,manufactured:1.2,farmhouse:.6,hillside:1.2,tract:.8,split:1}},
  midwest:  {n:'Midwest', found:{basement:.75,crawl:.15,slab:.1}, eras:{prewar:.25,postwar:.3,seventies:.25,modern:.2},
    arch:{ranch:3,colonial:2,cape:1.2,craftsman:1.5,victorian:.8,split:1.2,manufactured:.8,farmhouse:1.2}},
  northeast:{n:'Northeast', found:{basement:.85,crawl:.1,slab:.05}, eras:{prewar:.4,postwar:.3,seventies:.15,modern:.15},
    arch:{colonial:3,cape:2.5,victorian:1.2,saltbox:.8,ranch:1.2,split:.8,farmhouse:.8}},
  southeast:{n:'Southeast and Gulf', found:{slab:.55,crawl:.35,raised:.1}, eras:{prewar:.15,postwar:.3,seventies:.3,modern:.25},
    arch:{ranch:3,raised:1.4,craftsman:1,colonial:1,manufactured:1.8,farmhouse:1,tract:1}},
  pacificnw:{n:'Pacific Northwest', found:{crawl:.55,basement:.35,slab:.1}, eras:{prewar:.2,postwar:.25,seventies:.3,modern:.25},
    arch:{craftsman:2,ranch:2,split:1.5,hillside:1.6,mcm:1,cabin:.8,aframe:.5,colonial:.6}},
};

// House types. storeys: '1', '1.5' (bedrooms in the roof), '2', 'wing' (a two-storey block beside a one-storey wing).
// roofs: roof forms by weight. pitch in 12ths. over: eave overhang in metres. mats and clad: by region, or 'any'.
// fit(st): can this footprint be one of these. eras: when they were built.
const ARCH={
  ranch:{n:'Ranch', storeys:{'1':1}, roofs:{gable:3,hip:3,dutch:.5}, pitch:[4,6], over:[.45,.75], wallH:2.7, porch:.25, eras:['postwar','seventies','modern'],
    mats:{sonoran:{shingle:1.2,ctile:1},mountain:{shingle:2,metal:1},southeast:{shingle:2,metal:.8},pacificnw:{shingle:2,shake:.4,metal:.5},any:{shingle:3}},
    clad:{sonoran:{stucco:3,block:1.6,brick:.3},mountain:{siding:1.5,boardbatten:1,stucco:1},southeast:{brick:2,siding:1.5},pacificnw:{siding:2,boardbatten:1},any:{siding:2,brick:1.5}},
    fit:st=>st.A>=80&&st.A<=460},
  tract:{n:'Desert tract', storeys:{'1':.5,'2':.3,'wing':.2}, roofs:{hip:3,gable:2}, pitch:[4,5], over:[.3,.45], wallH:2.75, porch:.1, eras:['modern','recent'],
    mats:{any:{ctile:4,shingle:1}}, clad:{any:{stucco:1}}, fit:st=>st.A>=100&&st.A<=460},
  pueblo:{n:'Pueblo Revival', storeys:{'1':.85,'2':.15}, roofs:{parapet:1}, parapet:'pueblo', pitch:[0,0], over:[0,0], wallH:2.7, porch:.15, eras:['postwar','seventies','modern','recent'],
    mats:{any:{foam:2,builtup:1}}, clad:{any:{stucco:1,adobe:.35}}, cladCols:['#b8855a','#c49870','#a87a52','#c9a27a','#d0a878'], fit:st=>st.A>=60},
  territorial:{n:'Territorial', storeys:{'1':.7,'2':.3}, roofs:{parapet:1}, parapet:'territorial', pitch:[0,0], over:[0,0], wallH:2.8, porch:.6, eras:['prewar','postwar','modern','recent'],
    mats:{any:{builtup:1,foam:1}}, clad:{any:{stucco:1,adobe:.4}}, fit:st=>st.A>=70&&st.rect>=.7},
  spanish:{n:'Spanish Colonial', storeys:{'1':.7,'2':.2,'wing':.1}, roofs:{gable:2,hip:1.5}, pitch:[3,4], over:[.15,.3], wallH:2.8, porch:.2, eras:['prewar','modern','recent'],
    mats:{any:{clay:3,ctile:1}}, clad:{any:{stucco:1}}, cladCols:['#efe8dc','#e8dcc4','#f2ead8','#e3d3b8'], fit:st=>st.A>=90&&st.A<=460},
  mcm:{n:'Mid-century modern', storeys:{'1':1}, roofs:{flat:2,butterfly:1,shed:1.5,gable:.8}, pitch:[1,3], over:[.9,1.3], wallH:2.6, porch:0, eras:['postwar','seventies'],
    mats:{any:{builtup:2,metal:1,foam:1}}, clad:{any:{block:1,stucco:1,boardbatten:1}}, fit:st=>st.A>=90&&st.A<=400},
  manufactured:{n:'Manufactured home', storeys:{'1':1}, roofs:{gable:1}, pitch:[1,3], over:[.1,.2], wallH:2.4, porch:.35, found:'chassis', eras:['seventies','modern','recent'],
    mats:{any:{metal:1.2,shingle:1.4,corrugated:.5}}, clad:{any:{panel:2,siding:.5}}, fit:st=>st.rect>=.88&&((st.asp>=2.3&&st.A<=175)||(st.asp>=1.5&&st.asp<=3.2&&st.A<=240&&st.A>=110))},
  hillside:{n:'Hillside contemporary', storeys:{'1':.4,'2':.6}, roofs:{shed:2,gable:1,flat:1}, pitch:[2,4], over:[.6,.9], wallH:2.7, porch:.1, slope:true, eras:['seventies','modern','recent'],
    mats:{any:{metal:2,builtup:1}}, clad:{any:{stucco:1,boardbatten:1,siding:1}}, fit:st=>st.A>=70&&st.A<=400},
  cabin:{n:'Log cabin', storeys:{'1':.6,'1.5':.4}, roofs:{gable:1}, pitch:[7,10], over:[.45,.65], wallH:2.6, porch:.75, eras:['prewar','postwar','seventies','modern'],
    mats:{any:{metal:2,shingle:1}}, clad:{any:{log:2,boardbatten:1}}, fit:st=>st.A>=40&&st.A<=190&&st.rect>=.8},
  aframe:{n:'A-frame', storeys:{'1.5':1}, roofs:{aframe:1}, pitch:[20,21], over:[0,0], wallH:2.5, porch:.4, eras:['postwar','seventies'],
    mats:{any:{shingle:1,metal:1}}, clad:{any:{boardbatten:1,siding:1}}, fit:st=>st.A>=40&&st.A<=150&&st.asp<=2.2&&st.rect>=.88},
  colonial:{n:'Colonial', storeys:{'2':1}, roofs:{gable:3,hip:1.2,gambrel:.6}, pitch:[7,10], over:[.15,.3], wallH:2.7, porch:.3, eras:['prewar','postwar','modern','recent'],
    mats:{northeast:{shingle:3,slate:.5},any:{shingle:3}}, clad:{northeast:{siding:2,brick:1},any:{siding:2,brick:1.5}}, fit:st=>st.A>=70&&st.A<=270&&st.rect>=.72},
  cape:{n:'Cape Cod', storeys:{'1.5':1}, roofs:{gable:1}, pitch:[10,12], over:[.1,.2], wallH:2.6, porch:.15, eras:['prewar','postwar'],
    mats:{any:{shingle:3,shake:.5}}, clad:{any:{siding:2,shingles:1,brick:.4}}, fit:st=>st.A>=55&&st.A<=170&&st.rect>=.8},
  craftsman:{n:'Craftsman bungalow', storeys:{'1':.6,'1.5':.4}, roofs:{gable:3,hip:1}, pitch:[4,6], over:[.6,.9], wallH:2.7, porch:.9, eras:['prewar','postwar'],
    mats:{any:{shingle:3}}, clad:{any:{siding:2,shingles:1,brick:.3}}, fit:st=>st.A>=70&&st.A<=230},
  victorian:{n:'Victorian', storeys:{'2':1}, roofs:{gable:2,hip:1}, pitch:[10,14], over:[.2,.35], wallH:3.0, porch:.8, eras:['prewar'],
    mats:{any:{shingle:2,slate:1}}, clad:{any:{siding:1,shingles:.5}}, cladCols:['#8fa3a8','#a24a3c','#d9c49a','#6b7a5a','#b8a0c0','#e3cfc2'], fit:st=>st.A>=80&&st.A<=300},
  split:{n:'Split-level', storeys:{'wing':1}, roofs:{gable:2,hip:1}, pitch:[4,6], over:[.4,.6], wallH:2.6, porch:.1, eras:['postwar','seventies'],
    mats:{any:{shingle:3}}, clad:{any:{siding:2,brick:1}}, fit:st=>st.A>=110&&st.A<=330},
  farmhouse:{n:'Farmhouse', storeys:{'2':.7,'1.5':.3}, roofs:{gable:3}, pitch:[8,12], over:[.2,.35], wallH:2.7, porch:.85, eras:['prewar','postwar','recent'],
    mats:{any:{metal:2,shingle:2}}, clad:{any:{siding:2,boardbatten:1}}, fit:st=>st.A>=70&&st.A<=260&&st.rect>=.7},
  saltbox:{n:'Saltbox', storeys:{'2':1}, roofs:{saltbox:1}, pitch:[9,12], over:[.1,.2], wallH:2.6, porch:0, eras:['prewar'],
    mats:{any:{shingle:2,shake:1}}, clad:{any:{shingles:1,siding:1}}, fit:st=>st.A>=60&&st.A<=200&&st.rect>=.85},
  raised:{n:'Raised cottage', storeys:{'1':.75,'2':.25}, roofs:{hip:2,gable:1}, pitch:[6,10], over:[.4,.6], wallH:2.9, porch:.9, found:'raised', eras:['prewar','postwar','modern','recent'],
    mats:{any:{metal:2,shingle:1}}, clad:{any:{siding:2,boardbatten:1}}, fit:st=>st.A>=60&&st.A<=260},
};
// Forms that only work over a simple box fall back to a gable or hip when the footprint has wings.
const SIMPLE_ROOF={butterfly:1,shed:1,gambrel:1,saltbox:1,aframe:1,dutch:1};

// The footprint as the design reads it: area, how long and how boxy, how many boxes make it up.
function footprintStats(M){
  const {W,H,mask}=M; let A=0,i0=1e9,i1=-1,j0=1e9,j1=-1; for(let c=0;c<W*H;c++) if(mask[c]){ A++; const i=c%W,j=(c/W)|0; i0=Math.min(i0,i); i1=Math.max(i1,i); j0=Math.min(j0,j); j1=Math.max(j1,j); }
  const w=i1-i0+1, h=j1-j0+1, rects=roofRects(mask,W,H).length;
  return {A,w,h,asp:Math.max(w,h)/Math.max(1,Math.min(w,h)),rect:A/(w*h),rects,i0,i1,j0,j1};
}

// ---------------------------------------------------------------- the lot: real ground from the terrain patch
// heightAt gives metres in the site's frame; the design reads how far the ground falls under the house and which way.
function terrainOf(site){
  const T=site.terrain; if(!T) return null;
  return (x,z)=>{ const fx=(x-T.x0)/T.step, fz=(z-T.z0)/T.step, i=clamp(Math.floor(fx),0,T.nx-2), j=clamp(Math.floor(fz),0,T.nz-2), u=clamp(fx-i,0,1), v=clamp(fz-j,0,1), g=(a,b)=>T.h[b*T.nx+a];
    return (g(i,j)*(1-u)+g(i+1,j)*u)*(1-v)+(g(i,j+1)*(1-u)+g(i+1,j+1)*u)*v; };
}
// ground: 'auto' reads the data, 'flat' levels it, 'hill' tips it 28% falling away from the street
function lotOf(site,M,sense,ground){
  const real=terrainOf(site), {W,H,mask}=M;
  let hAt;
  if(ground==='flat'||!real) hAt=()=>0;
  else if(ground==='hill'){ const f=sense.front; hAt=(u,v)=>-.28*(-(u*f[0]+v*f[1])); } // local frame, rises toward the street
  else hAt=(u,v)=>{ const [x,z]=M.toW(u,v); return real(x,z); };
  let lo=1e9,hi=-1e9,sx=0,sz=0,sh=0,n=0,sxx=0,szz=0,sxh=0,szh=0;
  for(let c=0;c<W*H;c++) if(mask[c]){ const u=M.u0+c%W+.5, v=M.v0+((c/W)|0)+.5, h=hAt(u,v); lo=Math.min(lo,h); hi=Math.max(hi,h); n++; sx+=u; sz+=v; sh+=h; sxx+=u*u; szz+=v*v; sxh+=u*h; szh+=v*h; }
  const mx=sx/n,mz=sz/n,mh=sh/n, gx=(sxh/n-mx*mh)/Math.max(1e-6,sxx/n-mx*mx), gz=(szh/n-mz*mh)/Math.max(1e-6,szz/n-mz*mz), g=Math.hypot(gx,gz);
  return {hAt,lo,hi,drop:hi-lo,grade:g,down:g>1e-4?[-gx/g,-gz/g]:[-sense.front[0],-sense.front[1]],real:!!real&&ground!=='flat'};
}

// ---------------------------------------------------------------- the house design
function designHouse(site,M,sense,seedStr,opt){
  const region=opt.region==='auto'?(site.region||'sonoran'):opt.region, Rg=REGIONS[region];
  const q=rngOf(seedStr+'|design|'+region), st=footprintStats(M), lot=lotOf(site,M,sense,opt.ground||'auto');
  const era0=wpick(q,Rg.eras);
  const w={}; for(const k in Rg.arch){ const a=ARCH[k]; if(a.fit&&!a.fit(st)) continue; let x=Rg.arch[k]; if(!a.eras.includes(era0)) x*=.2; if(a.slope) x*=1+lot.grade*14; if(k==='manufactured') x*=st.rect>.95?2.5:1; w[k]=x; }
  const arch=wpick(q,w)||'ranch', a=ARCH[arch];
  let era=era0; if(!a.eras.includes(era)){ const ew={}; for(const e of a.eras) ew[e]=Rg.eras[e]||.05; era=wpick(q,ew); }
  let storeys=wpick(q,a.storeys);
  if(storeys==='2'&&st.A>360) storeys=q()<.5?'wing':'1';
  let roof=wpick(q,a.roofs); if(SIMPLE_ROOF[roof]&&st.rects>1) roof=q()<.6?'gable':'hip';
  if(roof==='dutch'&&st.rects>2) roof='hip';
  const matKey=wpick(q,a.mats[region]||a.mats.any), mat=ROOFMAT[matKey];
  const lo=Math.max(a.pitch[0],mat.pitch[0]), hi=Math.min(a.pitch[1],mat.pitch[1])||a.pitch[1];
  const pitch=roof==='parapet'||roof==='flat'?0:rrange(q,[lo,Math.max(lo,hi)])/12;
  const cladKey=wpick(q,a.clad[region]||a.clad.any), clad=CLAD[cladKey];
  const cladCol=pick(q,a.cladCols&&cladKey!=='brick'&&cladKey!=='log'?a.cladCols:clad.cols);
  let wallMat=clad.mat; if(cladKey==='stucco'&&region==='sonoran'&&q()<.35) wallMat='block';
  // footing: the type's own, else what the region does on level ground, then the lot's fall decides
  let found=a.found||wpick(q,Rg.found);
  const drop=lot.drop;
  if(found!=='chassis'&&found!=='raised'){
    if(drop>=2.2) found=(found==='basement'||q()<.6)?'walkout':'piers';
    else if(drop>=.6) found=found==='basement'?'basement':(arch==='hillside'||q()<.35)?'piers':'crawl';
  }
  if(lot.grade>.12&&found==='slab') found='piers';
  const over=rrange(q,a.over), porch=q()<a.porch;
  return {arch,label:a.n,era,region,regionName:Rg.n,storeys,roof,parapet:a.parapet||null,matKey,mat,roofCol:pick(q,mat.cols),pitch,over,
    cladKey,clad,cladCol,trim:pick(q,TRIM),wallMat,found,foundName:FOUND[found].n,porch,wallH:a.wallH,lot,st,dormers:storeys==='1.5'&&roof!=='aframe'};
}
// Shops and offices: the box is set by the plan; what tops it is a parapet, a tile fascia or a hipped cap.
function designCommercial(site,typeKey,seedStr,A){
  const q=rngOf(seedStr+'|cdesign'); let roof='parapet', fascia=null, matKey=pick(q,['builtup','membrane','foam']);
  if(/fastfood|cafe|bank|restaurant/.test(typeKey)&&A<700){ const r=q(); if(r<.4){ roof='hip'; matKey=pick(q,['ctile','metal','shingle']); } else if(r<.75){ fascia=pick(q,['ctile','metal']); } }
  else if(/strip|office|clinic|salon|boutique|convenience|pharmacy/.test(typeKey)&&q()<.55) fascia=pick(q,['ctile','ctile','metal']);
  if(typeKey==='canopy') roof='canopy';
  const mat=ROOFMAT[matKey];
  return {roof,fascia,fasciaCol:fascia?pick(q,ROOFMAT[fascia].cols):null,matKey,mat,roofCol:pick(q,mat.cols),pitch:roof==='hip'?4/12:0,over:roof==='hip'?.6:0,parapetH:.6+q()*.6};
}

// ---------------------------------------------------------------- roof geometry
// Cover the roofed area with a few overlapping rectangles, each the largest that still covers new ground. Each
// rectangle gets its own roof at the shared pitch and eave height, and where they overlap the roofs run into each
// other the way cross gables and hipped wings do on a real house.
function roofRects(mask,W,H){
  const left=Uint8Array.from(mask), out=[]; const total=mask.reduce((s,x)=>s+x,0); let covered=0;
  const pre=new Int32Array((W+1)*(H+1));
  for(let guard=0;guard<8&&covered<total*.97;guard++){
    for(let j=0;j<H;j++) for(let i=0;i<W;i++) pre[(j+1)*(W+1)+i+1]=left[j*W+i]+pre[j*(W+1)+i+1]+pre[(j+1)*(W+1)+i]-pre[j*(W+1)+i];
    const cnt=(i0,j0,i1,j1)=>pre[(j1+1)*(W+1)+i1+1]-pre[j0*(W+1)+i1+1]-pre[(j1+1)*(W+1)+i0]+pre[j0*(W+1)+i0];
    const hgt=new Int32Array(W); let best=null;
    for(let j=0;j<H;j++){ for(let i=0;i<W;i++) hgt[i]=mask[j*W+i]?hgt[i]+1:0;
      for(let i=0;i<W;i++){ if(!hgt[i]) continue; let h=hgt[i]; for(let k=i;k<W&&hgt[k];k++){ h=Math.min(h,hgt[k]); const w=k-i+1; if(w<2||h<2) continue;
        const n=cnt(i,j-h+1,k,j); if(n<2) continue; const s=n*1000+w*h; if(!best||s>best.s) best={s,i0:i,j0:j-h+1,i1:k,j1:j,n}; } } }
    if(!best) break;
    out.push(best); for(let j=best.j0;j<=best.j1;j++) for(let i=best.i0;i<=best.i1;i++){ if(left[j*W+i]) covered++; left[j*W+i]=0; }
  }
  return out;
}
// Planes of one rectangle's roof, as polygons in the building's local frame. kind 'roof' wears the covering,
// 'end' is wall infill (gable ends, clerestories) in the cladding colour, 'trim' is fascia.
// r: {x0,x1,z0,z1} in metres, y: eave height (top of the wall), type, p: pitch (rise over run), o: overhang.
function roofPlanes(r,y,type,p,o,opt){
  opt=opt||{};
  const along=(r.x1-r.x0)>=(r.z1-r.z0)||opt.forceX, L=along?r.x1-r.x0:r.z1-r.z0, Wd=along?r.z1-r.z0:r.x1-r.x0, cx=(r.x0+r.x1)/2, cz=(r.z0+r.z1)/2;
  // a: along the ridge from -L/2..L/2, b: across, h: height
  const P=(a,b,h)=>along?[cx+a,h,cz+b]:[cx+b,h,cz+a];
  const out=[], roof=(pts,u)=>out.push({kind:'roof',pts,u}), end=pts=>out.push({kind:'end',pts}), U=along?[1,0,0]:[0,0,1];
  const hl=L/2, hw=Wd/2, B=hw+o, ra=hl+Math.min(o,.45);
  if(type==='gable'||type==='aframe'||type==='saltbox'){
    const off=type==='saltbox'?-hw*.3:0, pf=type==='saltbox'?p:p, Hr=y+(hw+off)*pf, pr=type==='saltbox'?(Hr-y)/(hw-off):p;
    const yL=y-o*pf, yR=y-o*pr;
    roof([P(-ra,-B,yL),P(ra,-B,yL),P(ra,off,Hr),P(-ra,off,Hr)],U); roof([P(ra,B,yR),P(-ra,B,yR),P(-ra,off,Hr),P(ra,off,Hr)],U);
    for(const s of [-1,1]) end([P(s*hl,-hw,y),P(s*hl,hw,y),P(s*hl,off,Hr)]);
    return {planes:out,ridge:Hr};
  }
  if(type==='shed'){ const Hh=y+Wd*p; roof([P(-ra,-B,y-o*p),P(ra,-B,y-o*p),P(ra,B,Hh+o*p),P(-ra,B,Hh+o*p)],U);
    for(const s of [-1,1]) end([P(s*hl,-hw,y),P(s*hl,hw,y),P(s*hl,hw,Hh)]); end([P(-hl,hw,y),P(hl,hw,y),P(hl,hw,Hh),P(-hl,hw,Hh)]);
    return {planes:out,ridge:Hh+o*p};
  }
  if(type==='butterfly'){ const Hh=y+hw*p; for(const s of [-1,1]) roof([P(-ra,0,y),P(ra,0,y),P(ra,s*B,Hh+o*p),P(-ra,s*B,Hh+o*p)].map((v,k)=>v),U);
    for(const s of [-1,1]) end([P(s*hl,-hw,y),P(s*hl,-hw,Hh),P(s*hl,0,y),P(s*hl,hw,Hh),P(s*hl,hw,y)]);
    for(const s of [-1,1]) end([P(-hl,s*hw,y),P(hl,s*hw,y),P(hl,s*hw,Hh),P(-hl,s*hw,Hh)]);
    return {planes:out,ridge:Hh};
  }
  if(type==='gambrel'){ const pl=p*2.2, pu=p*.55, K=hw*.42, Hk=y+(hw-K)*pl, Hr=Hk+K*pu, yL=y-o*pl;
    for(const s of [-1,1]){ roof([P(-ra,s*B,yL),P(ra,s*B,yL),P(ra,s*K,Hk),P(-ra,s*K,Hk)],U); roof([P(-ra,s*K,Hk),P(ra,s*K,Hk),P(ra,0,Hr),P(-ra,0,Hr)],U); }
    for(const s of [-1,1]) end([P(s*hl,-hw,y),P(s*hl,hw,y),P(s*hl,K,Hk),P(s*hl,0,Hr),P(s*hl,-K,Hk)]);
    return {planes:out,ridge:Hr};
  }
  if(type==='mansard'){ const ps=3, k=Math.min(1.1,hw-.4,hl-.4), Hm=y+k*ps, A2=hl+o, B2=hw+o, yl=y-o*ps;
    roof([P(-A2,-B2,yl),P(A2,-B2,yl),P(hl-k,-(hw-k),Hm),P(-(hl-k),-(hw-k),Hm)],U); roof([P(A2,B2,yl),P(-A2,B2,yl),P(-(hl-k),hw-k,Hm),P(hl-k,hw-k,Hm)],U);
    roof([P(-A2,B2,yl),P(-A2,-B2,yl),P(-(hl-k),-(hw-k),Hm),P(-(hl-k),hw-k,Hm)],along?[0,0,1]:[1,0,0]); roof([P(A2,-B2,yl),P(A2,B2,yl),P(hl-k,hw-k,Hm),P(hl-k,-(hw-k),Hm)],along?[0,0,1]:[1,0,0]);
    out.push({kind:'flat',pts:[P(-(hl-k),-(hw-k),Hm),P(hl-k,-(hw-k),Hm),P(hl-k,hw-k,Hm),P(-(hl-k),hw-k,Hm)]});
    return {planes:out,ridge:Hm};
  }
  // hip, and the dutch gable (a hip with a little gable at the top of each end)
  const A2=hl+o, Hl=y-o*p, Hr=Hl+B*p, rl=Math.max(0,A2-B), V=along?[0,0,1]:[1,0,0];
  if(type==='dutch'&&rl>.5){ const hg=Hl+(Hr-Hl)*.55, zc=(Hr-hg)/p, dd=(hg-Hl)/p-o; const da=hl-dd;
    for(const s of [-1,1]) roof([P(-A2,s*B,Hl),P(A2,s*B,Hl),P(da,s*zc,hg),P(da,0,Hr),P(-da,0,Hr),P(-da,s*zc,hg)],U);
    for(const s of [-1,1]){ roof([P(s*A2,-B,Hl),P(s*A2,B,Hl),P(s*da,zc,hg),P(s*da,-zc,hg)],V); end([P(s*da,-zc,hg),P(s*da,zc,hg),P(s*da,0,Hr)]); }
    return {planes:out,ridge:Hr};
  }
  for(const s of [-1,1]) roof([P(-A2,s*B,Hl),P(A2,s*B,Hl),P(rl,0,Hr),P(-rl,0,Hr)],U);
  for(const s of [-1,1]) roof([P(s*A2,-B,Hl),P(s*A2,B,Hl),P(s*rl,0,Hr)],V);
  return {planes:out,ridge:Hr};
}
// Clip a convex polygon to the band lo <= f(p) <= hi (f linear), Sutherland-Hodgman, twice.
function clipBand(pts,f,lo,hi){
  const cut=(P,keep)=>{ const out=[]; for(let k=0;k<P.length;k++){ const a=P[k], b=P[(k+1)%P.length], ka=keep(a), kb=keep(b); if(ka>=0) out.push(a); if((ka>=0)!==(kb>=0)){ const t=ka/(ka-kb); out.push([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t,a[2]+(b[2]-a[2])*t]); } } return out; };
  let P=cut(pts,p=>f(p)-lo); if(P.length<3) return P; return cut(P,p=>hi-f(p));
}
// Draw a roof plane in its covering: courses run along the eave, ribs and seams run down the slope.
function paintPlane(B,pl,mat,cols){
  const pts=pl.pts, U=pl.u||[1,0,0];
  if(mat.pat==='flat'||!mat.s){ B.poly(pts,cols[0],true); return; }
  // the eave direction is U; down-slope is the in-plane direction perpendicular to it
  const e1=[pts[1][0]-pts[0][0],pts[1][1]-pts[0][1],pts[1][2]-pts[0][2]], e2=[pts[2][0]-pts[0][0],pts[2][1]-pts[0][1],pts[2][2]-pts[0][2]];
  const nrm=[e1[1]*e2[2]-e1[2]*e2[1],e1[2]*e2[0]-e1[0]*e2[2],e1[0]*e2[1]-e1[1]*e2[0]];
  const V=[nrm[1]*U[2]-nrm[2]*U[1],nrm[2]*U[0]-nrm[0]*U[2],nrm[0]*U[1]-nrm[1]*U[0]], vl=Math.hypot(...V)||1; for(let k=0;k<3;k++) V[k]/=vl;
  const dir=mat.pat==='courses'?V:U, f=p=>p[0]*dir[0]+p[1]*dir[1]+p[2]*dir[2];
  let lo=1e9,hi=-1e9; for(const p of pts){ const v=f(p); lo=Math.min(lo,v); hi=Math.max(hi,v); }
  for(let k=Math.floor(lo/mat.s);k*mat.s<hi;k++){ const P=clipBand(pts,f,k*mat.s,(k+1)*mat.s); if(P.length>=3) B.poly(P,cols[((k%2)+2)%2],false); }
  B.outline(pts);
}

// ---------------------------------------------------------------- storeys and footings
// The floors of a house, bottom up. y counts storeys from the main floor: -1 is a basement or a walk-out lower
// floor, 1 an upper floor or the rooms in the roof. Each floor has its own cell mask.
function houseFloors(M,design){
  const {W,H,mask}=M, N=W*H, lot=design.lot, FH=design.wallH+.45, cells=[]; for(let c=0;c<N;c++) if(mask[c]) cells.push(c);
  const cu=c=>M.u0+c%W+.5, cv=c=>M.v0+((c/W)|0)+.5;
  let found=design.found; const mainAbs=lot.hi+FOUND[found].above;
  const rel=c=>lot.hAt(cu(c),cv(c))-mainAbs;
  const floors=[{role:'ground',y:0,mask:Uint8Array.from(mask),wallH:design.wallH}];
  const st=design.storeys;
  if(st==='2') floors.push({role:'upper',y:1,mask:Uint8Array.from(mask),wallH:design.wallH});
  else if(st==='wing'){ // the bigger box gets the upper floor; a plain box keeps it over the half away from the garage side
    const rs=roofRects(mask,W,H), up=new Uint8Array(N); if(rs.length){ let r=Object.assign({},rs[0]); const n=(r.i1-r.i0+1)*(r.j1-r.j0+1);
      if(n>cells.length*.8){ if(r.i1-r.i0>=r.j1-r.j0){ const m=Math.round(r.i0+(r.i1-r.i0)*.55); if(design.lot.down[0]>0) r.i1=m; else r.i0=m; } else { const m=Math.round(r.j0+(r.j1-r.j0)*.55); if(design.lot.down[1]>0) r.j1=m; else r.j0=m; } }
      for(let j=r.j0;j<=r.j1;j++) for(let i=r.i0;i<=r.i1;i++) if(mask[j*W+i]) up[j*W+i]=1; }
    if(up.reduce((s,x)=>s+x,0)>=24) floors.push({role:'upper',y:1,mask:up,wallH:design.wallH});
  }
  else if(st==='1.5'){ // rooms in the roof: where the roof clears a 2.2 m wall, measured in from both long eaves
    const p=design.roof==='aframe'?1.75:design.pitch, up=new Uint8Array(N), need=(FH-design.wallH+2.2)/Math.max(.3,p);
    for(const r of roofRects(mask,W,H)){ const alongI=(r.i1-r.i0)>=(r.j1-r.j0);
      for(let j=r.j0;j<=r.j1;j++) for(let i=r.i0;i<=r.i1;i++){ const d=alongI?Math.min(j-r.j0,r.j1-j)+.5:Math.min(i-r.i0,r.i1-i)+.5; if(d>=need&&mask[j*W+i]) up[j*W+i]=1; } }
    if(up.reduce((s,x)=>s+x,0)>=16) floors.push({role:'attic',y:1,mask:up,wallH:2.2});
  }
  // below the main floor
  if(found==='basement') floors.unshift({role:'basement',y:-1,mask:Uint8Array.from(mask),wallH:design.wallH});
  if(found==='walkout'){ // rooms where the ground has fallen far enough to stand a storey under the house
    const lo=new Uint8Array(N); for(const c of cells) if(rel(c)<=-(FH-1.2)) lo[c]=1;
    const seen=new Uint8Array(N); let best=[]; for(const c0 of cells){ if(!lo[c0]||seen[c0]) continue; const comp=[c0]; seen[c0]=1; for(let h=0;h<comp.length;h++){ const c=comp[h]; for(const [di,dj] of DIRS){ const n=c+dj*W+di; if(lo[n]&&!seen[n]){ seen[n]=1; comp.push(n); } } } if(comp.length>best.length) best=comp; }
    if(best.length>=20){ const m=new Uint8Array(N); for(const c of best) m[c]=1; floors.unshift({role:'lower',y:-1,mask:m,wallH:design.wallH}); }
    else found='piers';
  }
  return {floors,found,mainAbs,FH};
}
// The ground round a house, in metres relative to the main floor. A slab sits on a levelled pad, cut and filled;
// raised footings only cut. A walk-out lower floor gets its yard dug down to its own floor on the open side.
function groundOf(M,design,hf,lowerMask){
  const {W,H,mask}=M, lot=design.lot, pad=-FOUND[hf.found].above, fill=/slab|basement/.test(hf.found), FH=hf.FH;
  const R=14, GW=W+2*R, GH=H+2*R, dF=new Float32Array(GW*GH).fill(99), dL=new Float32Array(GW*GH).fill(99);
  const bfs=(D,isSrc)=>{ const q=[]; for(let j=0;j<GH;j++) for(let i=0;i<GW;i++){ const ci=i-R, cj=j-R; if(ci>=0&&cj>=0&&ci<W&&cj<H&&isSrc(cj*W+ci)){ D[j*GW+i]=0; q.push(j*GW+i); } }
    for(let h=0;h<q.length;h++){ const c=q[h], i=c%GW, j=(c/GW)|0; for(const [di,dj] of [[1,0],[-1,0],[0,1],[0,-1],[1,1],[1,-1],[-1,1],[-1,-1]]){ const ni=i+di,nj=j+dj; if(ni<0||nj<0||ni>=GW||nj>=GH) continue; const n=nj*GW+ni, d=D[c]+(di&&dj?1.41:1); if(d<D[n]){ D[n]=d; q.push(n); } } } };
  bfs(dF,c=>mask[c]); if(lowerMask) bfs(dL,c=>lowerMask[c]);
  const at=(D,u,v)=>{ const i=clamp(Math.floor(u-M.u0)+R,0,GW-1), j=clamp(Math.floor(v-M.v0)+R,0,GH-1); return D[j*GW+i]; };
  const sm=t=>t<=0?0:t>=1?1:t*t*(3-2*t);
  return (u,v)=>{
    let h=lot.hAt(u,v)-hf.mainAbs; const f=at(dF,u,v);
    if(fill){ const k=sm((f-2)/4); h=pad*(1-k)+h*k; } else { const k=sm((f-1)/4), cut=Math.min(h,pad); h=cut*(1-k)+h*k; }
    if(lowerMask){ const l=at(dL,u,v), k=sm((l-2.5)/4), cut=Math.min(h,-FH-.05); h=cut*(1-k)+h*k; }
    return h;
  };
}

// ---------------------------------------------------------------- imported homes: rooms from a hand-made layout
// A layout floor lists rooms as outlines in the site's metres. Cells go to the room whose outline holds their
// centre; cells no outline claims go to the nearest room. The floor's own mask is every cell its rooms hold.
// A room's zone: an outline (poly) and/or bounds: x and z ranges, inside or outside a circle [cx, cz, r].
function inZone(rs,x,z){
  if(rs.poly&&!pip(x,z,rs.poly)) return false; const w=rs.where; if(!w) return !!rs.poly;
  if(w.x&&(x<w.x[0]||x>w.x[1])) return false; if(w.z&&(z<w.z[0]||z>w.z[1])) return false;
  if(w.inCircle&&Math.hypot(x-w.inCircle[0],z-w.inCircle[1])>w.inCircle[2]) return false;
  if(w.outCircle&&Math.hypot(x-w.outCircle[0],z-w.outCircle[1])<w.outCircle[2]) return false;
  return true;
}
function planFromLayout(M,FL,roomOf,rooms,unit){
  const {W,H,mask}=M, N=W*H, own=new Int32Array(N).fill(-1);
  FL.rooms.forEach((rs,k)=>{ for(let c=0;c<N;c++){ if(!mask[c]||own[c]>=0) continue; const [x,z]=M.toW(M.u0+c%W+.5,M.v0+((c/W)|0)+.5); if(inZone(rs,x,z)) own[c]=k; } });
  const q=[]; for(let c=0;c<N;c++) if(own[c]>=0) q.push(c);
  for(let h=0;h<q.length;h++){ const c=q[h], i=c%W, j=(c/W)|0; for(const [di,dj] of DIRS){ const n=(j+dj)*W+i+di; if(mask[n]&&own[n]<0&&!(FL.only&&!FL.only[n])){ own[n]=own[c]; q.push(n); } } }
  const made=[];
  FL.rooms.forEach((rs,k)=>{ const cells=[]; for(let c=0;c<N;c++) if(own[c]===k) cells.push(c); if(!cells.length) return;
    const r=Object.assign({kind:rs.kind,area:cells.length,name:rs.name||ROOM[rs.kind].n},rs.extra||{}); r.id=rooms.length; r.cells=cells; r.unit=unit; r.spec=rs; if(rs.kind==='deck') r.outdoor=true; if(rs.cars) r.cars=rs.cars;
    rooms.push(r); for(const c of cells) roomOf[c]=r.id; made.push(r); });
  return made;
}
// A layout floor's mask: the cells any of its room outlines hold (its rooms may then grow only inside it).
function layoutMask(M,FL){
  const {W,H,mask}=M, m=new Uint8Array(W*H);
  for(let c=0;c<W*H;c++){ if(!mask[c]) continue; const [x,z]=M.toW(M.u0+c%W+.5,M.v0+((c/W)|0)+.5); if(FL.rooms.some(r=>inZone(r,x,z))) m[c]=1; }
  if(FL.fill) return mask.slice(); // the main floor fills the footprint
  return m;
}

// ---------------------------------------------------------------- what stands outside the walls
// Roofs, the ground, what holds the house up, porches and steps. All in the building's local frame; y is metres
// above the main floor's slab (the slab top is at FY).
function roofBatch(G){
  const B=new Batch(), BF=new Batch(), d=G.design, M=G.Mfull, {W,H,mask}=M, FH=G.FH, cx=i=>M.u0+i, cz=j=>M.v0+j;
  B.flat=BF; if(!d||d.roof==='canopy') return B;
  // eave height over each cell: the top of the highest floor that holds it (rooms in the roof do not count)
  const eave=new Float32Array(W*H).fill(-1e9);
  for(const F of G.floors){ if(F.role==='attic'||F.role==='basement'||F.role==='lower') continue; const y=F.y*FH+FY+F.wallH; for(let c=0;c<W*H;c++) if(F.M.mask[c]&&y>eave[c]) eave[c]=y; }
  const levels=[...new Set([...eave].filter(v=>v>-1e8).map(v=>+v.toFixed(3)))];
  const mat=d.mat, cols=d.roofCol, trim=d.trim||'#e8e4da';
  for(const y of levels){
    const gm=new Uint8Array(W*H); for(let c=0;c<W*H;c++) if(mask[c]&&Math.abs(eave[c]-y)<1e-3) gm[c]=1;
    if(d.roof==='parapet'||d.roof==='flat'||d.roof==='canopy'||d.roof==='fascia'){ flatRoof(BF,G,gm,y,B); continue; }
    const rects=roofRects(gm,W,H); let coveredFlat=false;
    for(const r of rects){ const rr={x0:cx(r.i0),x1:cx(r.i1+1),z0:cz(r.j0),z1:cz(r.j1+1)};
      let type=d.roof, p=d.pitch, o=d.over, yy=y;
      if(type==='aframe'){ p=1.75; o=Math.max(.3,(y+.15-(FY+.35))/p); yy=y+.15; type='gable'; }
      if(SIMPLE_ROOF[type]&&rects.length>1) type='gable';
      if((rr.x1-rr.x0<2.5||rr.z1-rr.z0<2.5)&&type!=='gable') type='gable';
      const out=roofPlanes(rr,yy,type,p,o);
      for(const pl of out.planes){ if(pl.kind==='roof') paintPlane(B,pl,mat,cols); else if(pl.kind==='flat') B.poly(pl.pts,cols[0],true); else B.poly(pl.pts,G.cladCol,true); }
      // fascia along the long eaves
    }
    // cells no rectangle covered (slivers) get a flat cap so nothing is open to the sky
    const cov=new Uint8Array(W*H); for(const r of rects) for(let j=r.j0;j<=r.j1;j++) for(let i=r.i0;i<=r.i1;i++) cov[j*W+i]=1;
    for(let c=0;c<W*H;c++) if(gm[c]&&!cov[c]){ const i=c%W,j=(c/W)|0; B.box(cx(i)-.05,y,cz(j)-.05,cx(i+1)+.05,y+.25,cz(j+1)+.05,cols[0]); }
  }
  return B;
}
// Flat roofs: a deck on the walls, then a parapet (Pueblo walls step up and down, with vigas and canales; a
// Territorial parapet wears a brick coping) or a plain overhanging slab, or a tile fascia round a hidden flat roof.
function flatRoof(B,G,gm,y,BS){
  const d=G.design, M=G.Mfull, {W,H}=M, cx=i=>M.u0+i, cz=j=>M.v0+j, q=rngOf(G.seedStr+'|parapet'), col=d.roofCol[0];
  const isP=d.roof==='parapet', grow=d.roof==='flat'?Math.max(1,Math.round(d.over||.6)):0;
  // the deck: the roofed cells, grown by the overhang in whole cells; one sheet, inked only round its edge
  let m=gm; for(let g=0;g<grow;g++){ const m2=m.slice(); for(let c=0;c<W*H;c++) if(!m[c]){ const i=c%W,j=(c/W)|0; for(const [di,dj] of DIRS){ const ni=i+di,nj=j+dj; if(ni>=0&&nj>=0&&ni<W&&nj<H&&m[nj*W+ni]){ m2[c]=1; break; } } } m=m2; }
  const W2=W, at=(i,j)=>i>=0&&j>=0&&i<W2&&j<H&&m[j*W2+i];
  const top=y+(isP?.12:.3);
  for(let j=0;j<H;j++){ let i=0; while(i<W){ if(m[j*W+i]){ let k=i; while(k<W&&m[j*W+k]) k++; B.poly([[cx(i),top,cz(j)],[cx(k),top,cz(j)],[cx(k),top,cz(j+1)],[cx(i),top,cz(j+1)]],col,false); i=k; } else i++; } }
  for(let j=0;j<H;j++) for(let i=0;i<W;i++){ if(!m[j*W+i]) continue; for(let dd=0;dd<4;dd++){ if(at(i+DIRS[dd][0],j+DIRS[dd][1])) continue;
    const a=dd===0?[cx(i+1),cz(j)]:dd===2?[cx(i),cz(j+1)]:dd===1?[cx(i+1),cz(j+1)]:[cx(i),cz(j)], b=dd===0?[cx(i+1),cz(j+1)]:dd===2?[cx(i),cz(j)]:dd===1?[cx(i),cz(j+1)]:[cx(i+1),cz(j)];
    B.poly([[a[0],y,a[1]],[b[0],y,b[1]],[b[0],top,b[1]],[a[0],top,a[1]]],isP?col:(d.trim||'#e8e4da'),false); B.outline([[a[0],top,a[1]],[b[0],top,b[1]]]); } }
  const edges=[]; for(let c=0;c<W*H;c++){ if(!gm[c]) continue; const i=c%W,j=(c/W)|0; for(let dd=0;dd<4;dd++){ const n=(j+DIRS[dd][1])*W+i+DIRS[dd][0]; if(!gm[n]) edges.push([i,j,dd]); } }
  const wallCol=G.cladCol||'#cfc3ae';
  if(isP){ const pH=d.parapetH||(d.parapet==='pueblo'?.75:.6);
    for(const [i,j,dd] of edges){ const t=.16, x0=cx(i),z0=cz(j); let h=pH; if(d.parapet==='pueblo'){ const n=G.noise((i+dd*7)*.35,(j-dd*5)*.35); h=pH+(n>.62?.35:n<.3?-.15:0); }
      const bx=(a0,a1,b0,b1,y0,y1,c)=>{ if(dd===0) B.box(x0+1-t+a0,y0,z0+b0,x0+1+a1,y1,z0+1+b1,c); else if(dd===2) B.box(x0-a1,y0,z0+b0,x0+t-a0,y1,z0+1+b1,c); else if(dd===1) B.box(x0+b0,y0,z0+1-t+a0,x0+1+b1,y1,z0+1+a1,c); else B.box(x0+b0,y0,z0-a1,x0+1+b1,y1,z0+t-a0,c); };
      bx(0,.12,0,0,y,y+h,wallCol);
      if(d.parapet==='territorial') bx(-.04,.16,-.02,.02,y+h,y+h+.12,'#9c4a32');
      if(d.parapet==='pueblo'&&(i+j)%2===0&&q()<.5) bx(.12,.55,.42,-.42,y-.45,y-.25,'#7a5a3c'); // a viga end
    }
    if(d.parapet==='pueblo'){ for(let k=0;k<Math.min(3,edges.length);k++){ const [i,j,dd]=edges[Math.floor(q()*edges.length)], x=cx(i)+.5+DIRS[dd][0]*.5, z=cz(j)+.5+DIRS[dd][1]*.5; // canales
      if(dd%2===0) B.box(Math.min(x,x+DIRS[dd][0]*.7),y+.05,z-.12,Math.max(x,x+DIRS[dd][0]*.7),y+.2,z+.12,'#8a6a4a'); else B.box(x-.12,y+.05,Math.min(z,z+DIRS[dd][1]*.7),x+.12,y+.2,Math.max(z,z+DIRS[dd][1]*.7),'#8a6a4a'); } }
  }
  if(d.fascia){ const fc=d.fasciaCol, fm=ROOFMAT[d.fascia];
    for(const [i,j,dd] of edges){ const x0=cx(i),z0=cz(j), o=.7, h=1.0, Dx=DIRS[dd][0], Dz=DIRS[dd][1];
      // the edge line on the wall face, then out and down
      const a=dd===0?[x0+1,z0]:dd===2?[x0,z0+1]:dd===1?[x0+1,z0+1]:[x0,z0], b=dd===0?[x0+1,z0+1]:dd===2?[x0,z0]:dd===1?[x0,z0+1]:[x0+1,z0];
      const pl={pts:[[a[0]+Dx*o,y-.15,a[1]+Dz*o],[b[0]+Dx*o,y-.15,b[1]+Dz*o],[b[0],y+h,b[1]],[a[0],y+h,a[1]]],u:[Math.abs(b[0]-a[0]),0,Math.abs(b[1]-a[1])]};
      paintPlane(BS||B,pl,fm,fc); } }
}
// Under the main floor: what holds it up where the ground falls away. Posts on a 3 m grid and round the edge for
// piers and raised houses, a skirt for a manufactured home, a stem wall for everything else.
function footingBatch(G){
  const B=new Batch(), M=G.Mfull, {W,H,mask}=M, cx=i=>M.u0+i, cz=j=>M.v0+j, gr=G.ground, found=G.found, FH=G.FH;
  if(!gr) return B;
  const lowerF=G.floors.find(F=>F.role==='lower'), low=lowerF?lowerF.M.mask:null;
  const deckCells=new Set(); for(const F of G.floors) if(F.role==='ground') for(const r of F.P.rooms) if(r.outdoor) for(const c of r.cells) deckCells.add(c);
  const open=found==='piers'||found==='raised'||found==='walkout';
  for(let j=0;j<H;j++) for(let i=0;i<W;i++){ const c=j*W+i; if(!mask[c]||(low&&low[c])) continue;
    const deck=deckCells.has(c);
    for(let d=0;d<4;d++){ const n=(j+DIRS[d][1])*W+i+DIRS[d][0]; if(mask[n]&&!(low&&low[n])) continue;
      const mx=cx(i)+.5+DIRS[d][0]*.5, mz=cz(j)+.5+DIRS[d][1]*.5, g=gr(mx,mz); if(g>-.08) continue;
      const t=.1, x0=d===0?cx(i+1)-t:d===2?cx(i):cx(i), x1=d===0?cx(i+1):d===2?cx(i)+t:cx(i+1), z0=d===1?cz(j+1)-t:d===3?cz(j):cz(j), z1=d===1?cz(j+1):d===3?cz(j)+t:cz(j+1);
      if(found==='chassis') B.box(x0,g-.05,z0,x1,-.02,z1,'#cfc8b8');
      else if(open||deck){ B.box(x0,-.42,z0,x1,-.12,z1,deck?'#6b5a48':'#7a6a58'); }
      else B.box(x0,g-.15,z0,x1,-.02,z1,'#9a958c');
    }
    if((open||deck)&&i%3===0&&j%3===0){ const g=gr(cx(i)+.5,cz(j)+.5); if(g<-.3) B.box(cx(i)+.38,g-.1,cz(j)+.38,cx(i)+.62,-.12,cz(j)+.62,deck?'#4a4d50':found==='raised'?'#8a7a62':'#9a958c'); }
  }
  // corner posts along the edge of an open underside
  if(open||deckCells.size) for(let j=0;j<H;j++) for(let i=0;i<W;i++){ const c=j*W+i; if(!mask[c]||(low&&low[c])) continue; let edge=false; for(const [di,dj] of DIRS) if(!mask[c+dj*W+di]) edge=true; if(!edge||(i+j)%2) continue;
    if(!(open||deckCells.has(c))) continue; const g=gr(cx(i)+.5,cz(j)+.5); if(g<-.3) B.box(cx(i)+.4,g-.1,cz(j)+.4,cx(i)+.6,-.12,cz(j)+.6,deckCells.has(c)?'#4a4d50':'#8a7a62'); }
  return B;
}
// Steps from each outside door down to the ground, and a porch on the street side when the house has one.
function stoopBatch(G,F,O){
  const B=new Batch(), M=G.Mfull, gr=G.ground, d=G.design, y0=F.y*G.FH; if(!gr) return B;
  for(const dr of O.extDoors){ const e=dr.edges[0], w=dr.edges.length, mid=edgeMid(M,e,w), D=DIRS[e.dir], o=e.key[0], g=gr(mid[0]+D[0]*1.2,mid[1]+D[1]*1.2)-y0, gap=-g;
    if(gap<.22||dr.kind==='gdoor'||dr.role==='deck') continue; const n=Math.ceil(gap/.18), rise=gap/n, run=.3, half=Math.max(.6,w/2+.1);
    for(let k=0;k<n;k++){ const top=FY-(k+1)*rise, a=.15+k*run, b=a+run+(k===n-1?.1:0);
      const x0=mid[0]+D[0]*a, x1=mid[0]+D[0]*b, z0=mid[1]+D[1]*a, z1=mid[1]+D[1]*b, s=o==='v';
      B.box(Math.min(x0,x1)-(s?0:half),y0+top-rise-.05+ (k===n-1?0:0)-(k===n-1?.3:0)*0,Math.min(z0,z1)-(s?half:0),Math.max(x0,x1)+(s?0:half),y0+top+rise*0,Math.max(z0,z1)+(s?half:0),'#a8a399'); } }
  if(d&&d.porch&&F.role==='ground'&&O.front){ const run=O.front.edges, e=run[0], D=DIRS[e.dir], mid=edgeMid(M,e,run.length), o=e.key[0], L=Math.max(4,Math.min(9,run.length+4)), dep=2.4;
    const along=o==='v'?[0,1]:[1,0], P=(a,b,yy)=>[mid[0]+along[0]*a+D[0]*b,yy,mid[1]+along[1]*a+D[1]*b];
    const ga=gr(mid[0]+D[0]*dep,mid[1]+D[1]*dep)-y0, deckY=FY, eaveY=FY+F.wallH-.15;
    const bx=(a0,a1,b0,b1,yy0,yy1,col)=>{ const p=P(a0,b0,0), q=P(a1,b1,0); B.box(Math.min(p[0],q[0]),y0+yy0,Math.min(p[2],q[2]),Math.max(p[0],q[0]),y0+yy1,Math.max(p[2],q[2]),col); };
    bx(-L/2,L/2,.12,dep,Math.min(ga,0)-.1,deckY,'#8a6a4a');
    for(const a of [-L/2+.15,-L/6,L/6,L/2-.15]){ if(Math.abs(a)<.8&&L<6) continue; bx(a-.1,a+.1,dep-.3,dep-.1,deckY,eaveY,d.trim||'#e8e4da'); }
    const flat=d.roof==='parapet', pr=flat?0:.25, rc=flat?(G.cladCol||'#d9c7a6'):d.roofCol[0];
    B.poly([P(-L/2-.2,.1,y0+eaveY+.15),P(L/2+.2,.1,y0+eaveY+.15),P(L/2+.2,dep+.3,y0+eaveY+.15-(dep+.2)*pr),P(-L/2-.2,dep+.3,y0+eaveY+.15-(dep+.2)*pr)],rc,true);
    bx(-L/2-.2,L/2+.2,dep+.15,dep+.3,eaveY-(dep)*pr-.1,eaveY+.2-(dep)*pr,d.trim||'#e8e4da');
  }
  return B;
}

// The ground as a mesh: 1 m quads 36 m round the house, left open over the footprint, and a wide flat apron
// beyond so the view never runs off the edge. Steeper ground reads a shade darker.
function terrainInto(B,G){
  const M=G.Mfull, {W,H,mask}=M, gr=G.ground, R=36, i0=-R, i1=W+R, j0=-R, j1=H+R, cols=['#b39b74','#ad9570','#b8a07a'];
  const hv=new Float32Array((i1-i0+1)*(j1-j0+1)), NW=i1-i0+1; let sum=0,n=0;
  for(let j=j0;j<=j1;j++) for(let i=i0;i<=i1;i++){ const h=gr(M.u0+i,M.v0+j); hv[(j-j0)*NW+i-i0]=h; if(i===i0||i===i1||j===j0||j===j1){ sum+=h; n++; } }
  const at=(i,j)=>hv[(j-j0)*NW+i-i0];
  for(let j=j0;j<j1;j++) for(let i=i0;i<i1;i++){
    if(i>=0&&j>=0&&i<W&&j<H&&mask[j*W+i]) continue;
    const a=at(i,j),b=at(i+1,j),c=at(i+1,j+1),d=at(i,j+1), sl=Math.max(Math.abs(a-c),Math.abs(b-d)), nz=G.noise(i*.21,j*.21);
    const col=new THREE.Color(cols[nz<.35?1:nz>.7?2:0]).multiplyScalar(1-Math.min(.25,sl*.18)).getStyle();
    const x=M.u0+i, z=M.v0+j; B.quad([x,a,z],[x,d,z+1],[x+1,c,z+1],[x+1,b,z],col);
  }
  const y=sum/n-.08, x0=M.u0+i0, x1=M.u0+i1, z0=M.v0+j0, z1=M.v0+j1;
  for(const [a0,a1,b0,b1] of [[-160,x0,-160,160],[x1,160,-160,160],[x0,x1,-160,z0],[x0,x1,z1,160]]) B.quad([a0,y,b0],[a0,y,b1],[a1,y,b1],[a1,y,b0],'#b09872');
}
// Outside wall cladding read from above: courses of siding, brick, block or log, battens up and down. The
// pattern is carried by tone, in bands of 0.3 m or more, laid on the wall's outer face.
function cladFace(addF,e,o,fixed,along,G,cx,cz){
  const d=G.design, pat=d.clad.pat, WH=G.wallH, T=e.th||.12, sg=(e.dir===0||e.dir===1)?1:-1, bk=e.ext?'e'+e.dir:'int', base=new THREE.Color(d.cladCol);
  const tone=k=>base.clone().multiplyScalar(k).getStyle(), q=rngOf('clad|'+e.key);
  let parts=[[0,WH]]; if(e.type==='window') parts=[[0,e.win.sill],[e.win.head,WH]]; else if(e.type==='door') parts=[[2.1,WH]]; else if(e.type==='gdoor') parts=[[2.3,WH]];
  const box=(y0,y1,col,a0,a1,dep)=>{ for(const [pa,pb] of parts){ const ya=Math.max(y0,pa), yb=Math.min(y1,pb); if(yb-ya<.01) continue; const f0=sg*T, f1=sg*(T+(dep||.015)), A0=along+(a0||0), A1=along+(a1==null?1:a1);
    if(o==='v') addF(bk,0,cx(fixed)+f0,ya,cz(A0),cx(fixed)+f1,yb,cz(A1),col); else addF(bk,0,cx(A0),ya,cz(fixed)+f0,cx(A1),yb,cz(fixed)+f1,col); } };
  if(pat==='lap'){ for(let y=0,k=0;y<WH-.01;y+=.3,k++) box(y,Math.min(WH,y+.3),tone(k%2?.94:1)); }
  else if(pat==='log'){ for(let y=0,k=0;y<WH-.01;y+=.32,k++) box(y,Math.min(WH,y+.32),tone(k%2?.86:1.04),0,1,.04); }
  else if(pat==='batten'){ for(let a=0,k=0;a<.99;a+=.34,k++) box(0,WH,tone(k%2?.9:1),a,Math.min(1,a+.34)); }
  else if(pat==='brick'||pat==='block'){ const h=pat==='brick'?.3:.4; for(let y=0,k=0;y<WH-.01;y+=h,k++){ const off=k%2?.25:0; for(let a=-off;a<1;a+=.5) box(y,Math.min(WH,y+h),tone(q()<.5?.93:1.02),Math.max(0,a),Math.min(1,a+.5)); } }
}

// One paragraph on what the design chose and why, for the panel.
function designNote(G){
  const d=G.design; if(!d) return '';
  const ROOFN={gable:'gable',hip:'hipped',dutch:'Dutch-gable',gambrel:'gambrel',mansard:'mansard',shed:'shed',saltbox:'saltbox',butterfly:'butterfly',parapet:'flat roof behind a parapet',flat:'flat roof with a deep overhang',aframe:'A-frame',canopy:'canopy'};
  if(!G.house){ return 'Roof: '+(d.roof==='hip'?'hipped, '+d.mat.n.toLowerCase():'flat, '+d.mat.n.toLowerCase()+(d.fascia?', behind a '+ROOFMAT[d.fascia].n.toLowerCase()+' fascia':' behind a parapet'))+'.'; }
  const lot=d.lot, fall=lot.drop>.05?'the ground falls '+lot.drop.toFixed(1)+' m across the footprint (about '+Math.round(lot.drop/Math.max(1,Math.max(d.st.w,d.st.h))*100)+'%)':'the lot is level';
  const st={'1':'one storey','1.5':'one and a half storeys (rooms in the roof)','2':'two storeys','wing':'a two-storey block beside a one-storey wing'}[d.storeys]||'';
  const floors=G.floors.map(F=>F.role).join(', ');
  const roof=d.roof==='parapet'||d.roof==='flat'?ROOFN[d.roof]+', '+d.mat.n.toLowerCase():ROOFN[d.roof]+' roof, '+d.mat.n.toLowerCase()+(d.pitch?' at '+Math.round(d.pitch*12)+'/12':'');
  const head=d.imported?'Imported from a listing: '+(d.facts&&d.facts.summary||d.label)+'.':d.label+' ('+d.era.replace('prewar','before 1945').replace('postwar','1945-65').replace('seventies','1965-85').replace('modern','1985-2005').replace('recent','after 2005')+', '+d.regionName+').';
  return head+' '+st[0].toUpperCase()+st.slice(1)+'; floors: '+floors+'. '+roof[0].toUpperCase()+roof.slice(1)+'. Walls: '+(d.clad?d.clad.n.toLowerCase():'')+' ('+WALLMAT[d.wallMat].n.toLowerCase()+'). Footing: '+d.foundName.toLowerCase()+'; '+fall+'.';
}
