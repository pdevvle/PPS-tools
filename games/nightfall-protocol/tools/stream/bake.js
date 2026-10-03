// Bake a block of real terrain into streamable sector files: node bake.js ../osm/block_newriver.json out/
const fs=require('fs'), zlib=require('zlib'), C=require('./sector-core.js');
const [src,out]=process.argv.slice(2); fs.mkdirSync(out,{recursive:true});
const D=JSON.parse(fs.readFileSync(src,'utf8')), t0=Date.now();
const B=C.bake(D,m=>console.log(((Date.now()-t0)/1000).toFixed(1)+'s',m));
const SEC=D.sector, N=D.n, HALF=D.half, r2=v=>Math.round(v*100)/100, rp=p=>[Math.round(p[0]*10)/10,Math.round(p[1]*10)/10];
const b64=a=>Buffer.from(a.buffer,a.byteOffset,a.byteLength).toString('base64');
// shared index: block facts, bridges (any sector may draw part of a deck), the landscape around
const bridges=B.F.bridges.map(b=>({road:b.road,name:b.name,w:b.w,hw:b.hw,depth:b.depth,len:r2(b.len),long:b.long,e0:r2(b.e0),e1:r2(b.e1),raise:r2(b.raise),ab:r2(b.ab),over:b.over,clear:b.clear,
  d:b.d.map(rp),L:b.L.map(r2),piers:b.piers,mid:rp(b.d[Math.floor(b.d.length/2)])}));
const secOf=(x,z)=>[Math.min(N-1,Math.max(0,Math.floor((x+HALF)/SEC))),Math.min(N-1,Math.max(0,Math.floor((z+HALF)/SEC)))];
const index={name:D.name,center:D.center,sector:SEC,n:N,half:HALF,base:D.terrain.base,navStep:B.nav.NS,navLabels:C.NAVLABEL,bridges,camps:B.camps,context:D.context,sectors:[]};
const sizes=[];
for(let r=0;r<N;r++) for(let c=0;c<N;c++){
  const x0=-HALF+c*SEC, z0=-HALF+r*SEC, x1=x0+SEC, z1=z0+SEC, inS=(x,z)=>x>=x0&&x<x1&&z>=z0&&z<z1, M=24;
  // heights: 153 x 153 samples, one extra on each side so shading has neighbours; the mesh uses the inner 151
  const n=SEC/B.st+3, Hs=new Int16Array(n*n), oi=Math.round((x0-B.st-B.X0)/B.st), oj=Math.round((z0-B.st-B.Z0)/B.st);
  for(let j=0;j<n;j++) for(let i=0;i<n;i++) Hs[j*n+i]=Math.round(B.H[(oj+j)*B.NXg+oi+i]*100);
  // movement grid for this sector
  const NX=B.nav.NX, ns=SEC/B.nav.NS, kind=new Uint8Array(ns*ns), sp=new Uint8Array(ns*ns), ni=c*ns, nj=r*ns;
  for(let j=0;j<ns;j++) for(let i=0;i<ns;i++){ const id=(nj+j)*NX+ni+i; kind[j*ns+i]=B.nav.kind[id]; sp[j*ns+i]=Math.round(B.nav.sp[id]*250); }
  const roads=[]; D.roads.forEach((rd,ri)=>{
    const bi=bridges.findIndex(b=>b.road===ri);
    const base={cls:rd.cls,surface:rd.surface||'',oneway:rd.oneway||'',name:rd.name||'',paved:C.isPaved(rd),drive:C.isDrive(rd),w:C.roadW(rd)};
    if(bi>=0){ const m=bridges[bi].mid; if(inS(m[0],m[1])) roads.push({...base,bridge:bi,pts:rd.pts.map(rp),cutStart:false,cutEnd:false}); return; }
    for(const p of C.clipLine(rd.pts,x0,z0,x1,z1)) roads.push({...base,bridge:-1,pts:p.pts.map(rp),cutStart:p.cutStart,cutEnd:p.cutEnd}); });
  const water=[]; for(const w of D.water) for(const p of C.clipLine(w.pts,x0-M,z0-M,x1+M,z1+M)) water.push({kind:w.kind,name:w.name||'',hw:B.WASH(w).hw,pts:p.pts.map(rp)});
  const near=bb=>bb[2]>x0-M&&bb[0]<x1+M&&bb[3]>z0-M&&bb[1]<z1+M;
  const areas=D.areas.filter(a=>near(C.bbox(a.pts))).map(a=>({kind:a.kind,pts:C.clipRect(a.pts,x0-M,z0-M,x1+M,z1+M).map(rp)})).filter(a=>a.pts.length>=3);
  const beds=B.F.beds.map(b=>C.clipRect(b.raw,x0-M,z0-M,x1+M,z1+M).map(rp)).filter(p=>p.length>=3);
  const lakes=B.F.lakes.filter(l=>near(l.bb)).map(l=>({level:r2(l.level),sheet:C.clipRect(l.raw,x0,z0,x1,z1).map(rp),shore:C.clipLine([...l.raw,l.raw[0]],x0-M,z0-M,x1+M,z1+M).map(p=>p.pts.map(rp)),raw:l.raw.map(rp)}));
  const pools=B.F.pools.filter(p=>inS(...C.centroid(p.pts))).map(p=>({pts:p.pts.map(rp),level:r2(p.level),low:r2(p.low)}));
  const buildings=D.buildings.filter(b=>b.pts.length>=3&&inS(...C.centroid(b.pts))).map(b=>({pts:b.pts.map(rp),type:b.type,levels:b.levels,height:b.height,name:b.name,loot:b.loot,what:b.what,house:B.houses.has(b)||undefined}));
  const walls=B.walls.filter(w=>inS((w[0]+w[2])/2,(w[1]+w[3])/2)).map(w=>w.map(r2));
  const plants=B.plants.filter(p=>inS(p[1],p[3]));
  const culverts=B.F.culverts.filter(q=>inS(q.x,q.z)).map(q=>Object.fromEntries(Object.entries(q).map(([k,v])=>[k,r2(v)])));
  const pois=D.pois.filter(p=>inS(p.p[0],p.p[1]));
  const S={c,r,x0,z0,hn:n,H:b64(Hs),nav:{n:ns,kind:b64(kind),sp:b64(sp)},roads,water,areas,beds,lakes,pools,buildings,walls,plants,culverts,pois};
  const js=JSON.stringify(S), gz=zlib.gzipSync(js,{level:9}).length; fs.writeFileSync(`${out}/s_${c}_${r}.json`,js); sizes.push(gz);   // plain JSON; servers compress it on the way
  index.sectors.push({c,r,bytes:js.length,gz,b:buildings.length,plants:plants.length});
}
fs.writeFileSync(`${out}/index.json`,JSON.stringify(index));
console.log('sectors',sizes.length,'gzipped total',(sizes.reduce((a,b)=>a+b,0)/1e6).toFixed(2),'MB','max',(Math.max(...sizes)/1e3).toFixed(0),'KB','index',(fs.statSync(`${out}/index.json`).size/1e3).toFixed(0),'KB','in',((Date.now()-t0)/1000).toFixed(1),'s');
