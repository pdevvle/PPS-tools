// ---------- shared frame: the region map and the tactical block use different origins ----------
const NF=(()=>{ const BLOCK={center:[33.918,-112.13855],half:1500}, RC=REGION.center, ky=110574;
  const kx=lat=>111320*Math.cos(lat*Math.PI/180);
  const toLL=(x,z,c)=>[c[0]-z/ky, c[1]+x/kx(c[0])], fromLL=(la,lo,c)=>[(lo-c[1])*kx(c[0]), -(la-c[0])*ky];
  const regionToBlock=(x,z)=>fromLL(...toLL(x,z,RC),BLOCK.center), blockToRegion=(x,z)=>fromLL(...toLL(x,z,BLOCK.center),RC);
  const inBlock=(x,z)=>{ const [bx,bz]=regionToBlock(x,z); return Math.abs(bx)<BLOCK.half-20&&Math.abs(bz)<BLOCK.half-20; };
  const rect=[[-1,-1],[1,-1],[1,1],[-1,1]].map(([a,b])=>blockToRegion(a*BLOCK.half,b*BLOCK.half));
  return {BLOCK,regionToBlock,blockToRegion,inBlock,rect,mode:'region'}; })();
