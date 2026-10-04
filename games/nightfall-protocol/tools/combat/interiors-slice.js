// Pulls the procedural interiors generator (and, for the browser, its renderer) out of tools/interiors without
// editing it: the interiors topic owns those files. Slices by marker comments; fails loudly if a marker moves.
const fs=require('fs'), path=require('path');
const DIR=path.join(__dirname,'..','interiors');
const GEN_START='<script>\n', REND='// ================================================================= rendering', REND_END='function resize(';
const PHYS='// ================================================================= physics', PHYS_END='// ================================================================= plan canvas';
function read(){
  const src=fs.readFileSync(path.join(DIR,'interiors.src.html'),'utf8');
  const kit=fs.readFileSync(path.join(DIR,'kit.js'),'utf8');
  const sites=fs.readFileSync(path.join(DIR,'sites.json'),'utf8');
  const s0=src.indexOf('<script>\n',src.indexOf('three.min.js')), r0=src.indexOf(REND), r1=src.indexOf(REND_END,r0);
  const p0=src.indexOf(PHYS), p1=src.indexOf(PHYS_END,p0);
  if(s0<0||r0<0||r1<0||p0<0||p1<0) throw new Error('interiors.src.html markers moved: update tools/combat/interiors-slice.js');
  const fill=t=>t.replace('/*SITES*/[]',sites).replace('/*KIT*/',kit);
  // physics: grenades scattering props and overturned furniture (the renderer's build() calls its applyMoves)
  return { gen:fill(src.slice(s0+GEN_START.length,r0)), render:src.slice(r0,r1), phys:src.slice(p0,p1) };
}
// Node: run the generator in a sandbox and hand back what combat needs
function loadGenerator(){
  const vm=require('vm'), {gen}=read();
  // the generator only touches THREE.Color for colour jitter; a tiny stand-in keeps it headless
  class Color{ constructor(c){ this.r=this.g=this.b=.5; } getHSL(h){ h.h=0;h.s=0;h.l=.5; return h; } setHSL(){ return this; } getHexString(){ return '808080'; } multiplyScalar(){ return this; } getStyle(){ return '#808080'; } }
  const ctx={THREE:{Color},performance:{now:()=>Date.now()},console,Math,Map,Set,Int32Array,Uint8Array,Float32Array,Array,Object,JSON};
  vm.createContext(ctx);
  return vm.runInContext(gen+';({SITES,TYPES,ROOM,IT,DIRS,edgeKey,generate,rngOf})',ctx);
}
module.exports={read,loadGenerator};
