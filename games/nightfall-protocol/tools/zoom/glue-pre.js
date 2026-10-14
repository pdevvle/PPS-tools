// ---------- shared frame: the region map and the tactical block use different origins ----------
// BLOCK: the baked corridor in the tactical frame, New River and the block north of it
const NF=(()=>{ const BLOCK={center:[33.918,-112.13855],half:1500,x0:-1500,z0:-4500,x1:1500,z1:1500}, RC=REGION.center, ky=110574;
  const kx=lat=>111320*Math.cos(lat*Math.PI/180);
  const toLL=(x,z,c)=>[c[0]-z/ky, c[1]+x/kx(c[0])], fromLL=(la,lo,c)=>[(lo-c[1])*kx(c[0]), -(la-c[0])*ky];
  const regionToBlock=(x,z)=>fromLL(...toLL(x,z,RC),BLOCK.center), blockToRegion=(x,z)=>fromLL(...toLL(x,z,BLOCK.center),RC);
  const inBlock=(x,z)=>{ const [bx,bz]=regionToBlock(x,z); return bx>BLOCK.x0+20&&bx<BLOCK.x1-20&&bz>BLOCK.z0+20&&bz<BLOCK.z1-20; };
  const rect=[[BLOCK.x0,BLOCK.z0],[BLOCK.x1,BLOCK.z0],[BLOCK.x1,BLOCK.z1],[BLOCK.x0,BLOCK.z1]].map(([a,b])=>blockToRegion(a,b));
  return {BLOCK,regionToBlock,blockToRegion,inBlock,rect,mode:'region'}; })();
