// ---------- the combat test range: one hand-laid building that has every case the fight rules handle ----------
// Not procedural. The interiors generator's own helpers make the footprint frame, the room records and the
// colours (they are passed in as `env`, so this file never edits the interiors code); the plan, the openings,
// the furniture and who stands where are written out below, so every test starts from the same place.
//
//   north   ┌ Drywall ┬ Stucco ┬ Block ┬ Vault ┬── Window room ──┐   wall materials: shoot through or breach
//           ├─────────┴────────┴───────┴───────┴─────────────────┤
//           │ Long lane: 32 m end to end (range profiles, overwatch down a corridor)   ← side door (west)
//           ├────────── Cover gallery ───────────┬── Kitchen ─────┤   counters between gallery and kitchen
//           │ full / half / flippable cover,     ├── Stockroom ───┤   ← back door (east); drywall to the gallery
//   south   └──── windows: .6 .9 broken 1.2 boarded 1.8 ─ front double door ┘   yard walls: low and high
//
// Cells are 1 m. Layout coordinates: i = 1..32 west to east, j = 1..22 north to south (the street is south).
const CombatTestMap=(()=>{
const PLAN=[
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW', // j=1
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW',
  'SSSSSSFFFFFFBBBBBBVVVVVVWWWWWWWW', // j=9
  'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC', // j=10
  'CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC',
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK', // j=12
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK',
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK',
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK',
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK',
  'HHHHHHHHHHHHHHHHHHHHKKKKKKKKKKKK', // j=17
  'HHHHHHHHHHHHHHHHHHHHGGGGGGGGGGGG', // j=18
  'HHHHHHHHHHHHHHHHHHHHGGGGGGGGGGGG',
  'HHHHHHHHHHHHHHHHHHHHGGGGGGGGGGGG',
  'HHHHHHHHHHHHHHHHHHHHGGGGGGGGGGGG',
  'HHHHHHHHHHHHHHHHHHHHGGGGGGGGGGGG', // j=22
];
const ROOMS={S:['storage','Drywall room'],F:['storage','Stucco room'],B:['storage','Block room'],V:['vault','Vault'],W:['office','Window room'],
  C:['corridor','Long lane'],H:['sales','Cover gallery'],K:['rkitchen','Kitchen'],G:['stock','Stockroom']};
// the wall each test room shows the lane (and its sides): the build-ups the rules tell apart
const WALL_OF={S:'stud',F:'frame',B:'block',V:'vault'};
const D={E:0,S:1,W:2,N:3};   // the generator's directions: +x, +z, -x, -z
// openings: [i, j, side, what, options]
const OPENINGS=[
  // ways in
  [9,22,'S','front'],[10,22,'S','front'],
  [1,10,'W','side'],
  [32,20,'E','back'],
  // windows: every sill and state the rules know (sill ≤ 1.3 m can be climbed)
  [3,22,'S','window',{sill:.6}],[4,22,'S','window',{sill:.6}],
  [6,22,'S','window',{sill:.9,state:'broken'}],
  [13,22,'S','window',{sill:1.2}],[14,22,'S','window',{sill:1.2}],
  [16,22,'S','window',{sill:.9,state:'boarded'}],
  [19,22,'S','window',{sill:1.8}],
  [1,15,'W','window',{sill:1.0}],[1,16,'W','window',{sill:1.0}],
  [26,1,'N','window',{sill:.9}],[27,1,'N','window',{sill:.9}],[30,1,'N','window',{sill:1.8}],
  [32,3,'E','window',{sill:.6,state:'broken'}],[32,4,'E','window',{sill:.6,state:'broken'}],[32,7,'E','window',{sill:.9,state:'boarded'}],
  [32,14,'E','window',{sill:1.2}],
  // inside: each test room has one closed door at its far end, so the wall itself is the short way
  [1,9,'S','door',{open:false}],[7,9,'S','door',{open:false}],[13,9,'S','door',{open:false}],[19,9,'S','door',{open:false}],[26,9,'S','door',{open:true}],
  // lane to gallery: an open door, a closed door and a 3 m archway; lane to kitchen
  [5,11,'S','door',{open:true}],[16,11,'S','door',{open:false}],[9,11,'S','open'],[10,11,'S','open'],[11,11,'S','open'],
  [28,11,'S','door',{open:true}],
  // kitchen to stockroom
  [24,17,'S','door',{open:false}],
  // gallery to kitchen across counters (half cover, climbable)
  [20,13,'E','counter'],[20,14,'E','counter'],[20,15,'E','counter'],[20,16,'E','counter'],
];
// furniture: [key, i, j, facing]. Facing N: the piece runs east from (i,j) and back (north) from it.
const ITEMS=[
  // cover gallery, squad side (south): half and flippable pieces
  ['crate',3,19,'N'],['barrel',6,19,'N'],['table4',12,20,'N'],['sofa',15,19,'N'],
  // middle row: full and half, most of them flippable
  ['bookcase',2,16,'N'],['vending',7,16,'N'],['desk',12,16,'N'],['drums',18,16,'N'],
  // raider side (north): full shelf, half island, half filing cabinet, the stash safe
  ['rshelf',3,14,'N'],['island',8,14,'N'],['filing',14,14,'N'],['safe',18,13,'N'],
  // kitchen
  ['fridge',31,12,'S'],['island',24,15,'N'],['prep',28,15,'N'],
  // stockroom
  ['gshelf',22,19,'N'],['drums',27,21,'N'],['crate',30,19,'N'],
  // window room and test rooms: something to stand behind at the back
  ['desk',28,5,'N'],['filing',25,4,'N'],
  ['crate',3,2,'N'],['crate',9,2,'N'],['crate',15,2,'N'],['crate',21,2,'N'],
  // the lane: one half-cover crate two thirds of the way down
  ['crate',22,11,'N'],
];
// raiders: [type, i, j, facing, post]. Every enemy type, one behind each wall build-up, one at the end of the lane.
const POSTS=[
  ['boss',4,13,'S','camp'],          // behind the full shelf
  ['brute',9,13,'S','camp'],         // behind the half island: charges with a machete
  ['enforcer',14,13,'S','camp'],     // armour 1, behind the filing cabinet
  ['raider',4,8,'S','camp'],         // behind drywall: shoot through it
  ['raider',10,8,'S','camp'],        // behind stucco: shoot through at a bigger penalty
  ['enforcer',16,8,'S','camp'],      // behind block: rounds stop, a charge breaches
  ['raider',31,10,'W','camp'],       // the far end of the 32 m lane
  ['raider',26,2,'N','sentry'],      // at the north window, looking out
  ['raider',27,13,'W','camp'],       // the kitchen, across the counters
];
const LABELS=[
  [3.5,5,'Drywall: rounds pass, one charge breaches'],[9.5,5,'Stucco: rounds pass (harder)'],[15.5,5,'Block: stops rounds'],[21.5,5,'Reinforced concrete: two charges'],
  [28.5,7,'Windows: 0.9 · 1.8 high · broken · boarded'],[16.5,10.9,'Long lane: 32 m'],[10.5,12.4,'Archway · open door (5) · closed door (16)'],
  [10.5,18,'Cover gallery: full · half · flippable'],[20.6,14.5,'Counters'],[26.5,20,'Stockroom: drywall to the gallery'],
  [10,23.4,'Front door'],[4,23.4,'Sill 0.6'],[6.5,23.4,'Broken'],[14,23.4,'Sill 1.2'],[16.5,23.4,'Boarded'],[19.5,23.4,'Sill 1.8: too high'],[-.4,16,'Sill 1.0'],
];

function build(env){
  const {prepFootprint,streetSense,R,IT,edgeKey,DIRS,styleFor,rngOf,setLevel,noise2,TYPES,WALLMAT}=env;
  const NI=PLAN[0].length, NJ=PLAN.length;
  const site={id:'test/range',block:'test',name:'Test range',what:'combat test range',note:'Combat test range: hand-laid',type:'yes',house:false,loot:'tools',area:'test',levels:1,height:null,
    pts:[[-NI/2,-NJ/2],[NI/2,-NJ/2],[NI/2,NJ/2],[-NI/2,NJ/2]],centre:[0,0],
    roads:[{cls:'residential',name:'Range road',w:8,drive:true,pts:[[-60,NJ/2+9],[60,NJ/2+9]]}],water:[],
    // yard walls [x0,z0,x1,z1,height,thickness]: a low one and a high one between the road and the front
    walls:[[-9,NJ/2+4,-4,NJ/2+4,1.0,.25],[5,NJ/2+5,9,NJ/2+5,2.0,.25]]};
  const M=prepFootprint(site), sense=streetSense(site,M);
  // layout (i,j) is mask cell (i,j): the frame keeps a 1 m border round the footprint
  const cellOf=(i,j)=>j*M.W+i;
  if(M.W!==NI+2||M.H!==NJ+2) throw new Error('test range: footprint frame is '+M.W+'×'+M.H);
  for(let j=1;j<=NJ;j++) for(let i=1;i<=NI;i++) if(!M.mask[cellOf(i,j)]) throw new Error('test range: cell '+i+','+j+' outside the footprint');
  // rooms
  const roomOf=new Int32Array(M.W*M.H).fill(-1), rooms=[], idOf={};
  for(const ch of Object.keys(ROOMS)){ const cells=[]; PLAN.forEach((row,j0)=>[...row].forEach((c,i0)=>{ if(c===ch) cells.push(cellOf(i0+1,j0+1)); }));
    const r=R(ROOMS[ch][0],cells.length,{name:ROOMS[ch][1]}); r.id=rooms.length; r.cells=cells; r.unit=0; r.unitType='hardware'; r.what='test'; idOf[ch]=r.id; rooms.push(r); for(const c of cells) roomOf[c]=r.id; }
  const P={rooms,roomOf};
  // edges, as the generator makes them: outside walls on every side, inside walls where the room changes
  const edges=new Map();
  for(let j=0;j<M.H;j++) for(let i=0;i<M.W;i++){ const c=cellOf(i,j); if(!M.mask[c]) continue;
    for(let d=0;d<4;d++){ const ni=i+DIRS[d][0], nj=j+DIRS[d][1], n=cellOf(ni,nj);
      if(!M.mask[n]){ const e={key:edgeKey(i,j,d),type:'wall',a:roomOf[c],b:-1,dir:d,i,j,ext:true}; edges.set(e.key,e); }
      else if((d===0||d===1)&&roomOf[n]!==roomOf[c]){ const e={key:edgeKey(i,j,d),type:'wall',a:roomOf[c],b:roomOf[n],dir:d,i,j,ext:false}; edges.set(e.key,e); } } }
  const edgeAt=(i,j,side)=>{ const e=edges.get(edgeKey(i,j,D[side])); if(!e) throw new Error('test range: no edge at '+i+','+j+' '+side); return e; };
  const doors=[], windows=[], extDoors=[];
  const ways={};
  for(const [i,j,side,what,o={}] of OPENINGS){ const e=edgeAt(i,j,side);
    if(what==='front'||what==='side'||what==='back'){ e.type='door'; (ways[what]=ways[what]||[]).push(e); }
    else if(what==='window'){ e.type='window'; e.win={sill:o.sill,head:2.2,state:o.state||'intact'}; windows.push(e); }
    else if(what==='door'){ e.type='door'; e.door={open:!!o.open,state:'closed',width:1}; doors.push(e); }
    else e.type=what; }   // 'open', 'counter'
  for(const role of ['front','side','back']){ const es=ways[role]; if(!es) continue;
    for(const e of es) e.door={open:false,state:'closed',width:es.length,role,lead:es[0].key};
    const d={edges:es,role,kind:'door',room:es[0].a,dir:es[0].dir,unit:0}; extDoors.push(d); doors.push(es[0]); }
  const O={edges,doors,extDoors,windows,front:extDoors.find(d=>d.role==='front'),back:extDoors.find(d=>d.role==='back'),
    fronts:extDoors.filter(d=>d.role==='front'),backs:extDoors.filter(d=>d.role==='back'),hub:rooms[idOf.H]};
  // wall build-ups: block outside, stucco on the street front, drywall inside; each test room shows the lane its own
  const TH={stud:.06,frame:.08,block:.1,vault:.15}, letter=id=>Object.keys(idOf).find(k=>idOf[k]===id);
  for(const e of edges.values()){ let m;
    if(e.ext) m=e.dir===D.S&&letter(e.a)==='H'?'frame':'block';
    else { const la=letter(e.a), lb=letter(e.b), test=WALL_OF[la]||WALL_OF[lb];
      if(WALL_OF[la]&&WALL_OF[lb]) m='block';                 // between two test rooms: keep them apart
      else m=test||'stud'; }
    e.mat=m; e.th=e.ext?WALLMAT[m].t:TH[m]; }
  // furniture
  const items=[], occ=new Int32Array(M.W*M.H).fill(-1);
  for(const [key,i,j,side] of ITEMS){ const spec=IT[key], f=D[side], F=DIRS[f], T=DIRS[(f+1)%4], cells=[];
    for(let a=0;a<spec.w;a++) for(let b=0;b<spec.d;b++) cells.push(cellOf(i+a*T[0]-b*F[0],j+a*T[1]-b*F[1]));   // the front faces f; the piece runs back from it
    const room=roomOf[cells[0]];
    for(const c of cells){ if(roomOf[c]!==room) throw new Error('test range: '+key+' at '+i+','+j+' crosses a wall'); if(occ[c]>=0) throw new Error('test range: '+key+' at '+i+','+j+' overlaps '+items[occ[c]].key); }
    const access=cells.map(c=>c+F[0]+F[1]*M.W).filter(c=>roomOf[c]===room&&!cells.includes(c));
    const it={id:items.length,key,spec,room,cells,f,access,i:cells[0]%M.W,j:(cells[0]/M.W)|0,score:0};
    if(spec.slot) it.contents=[];   // what the renderer and the stash expect of anything that stores loot
    if(key==='safe'){ it.stash=true; it.contents=[{name:'Rifle rounds',cat:'ammo',qty:3},{name:'Pipe bomb',cat:'gear',qty:1},{name:'Antibiotics',cat:'meds',qty:2}]; }
    items.push(it); for(const c of cells) occ[c]=it.id; }
  const Fn={items,occ,reserved:new Uint8Array(M.W*M.H),keep:new Uint8Array(M.W*M.H),doorCells:{}};
  const toW=(i,j)=>[M.u0+i+.5,M.v0+j+.5];
  const FACE={S:0,N:Math.PI,E:Math.PI/2,W:-Math.PI/2};
  const posts=POSTS.map(([type,i,j,side,post])=>({type,p:toW(i,j),face:FACE[side],post,boss:type==='boss'}));
  const Dc={people:POSTS.map(([type,i,j])=>({c:cellOf(i,j),side:'raider',boss:type==='boss'}))};
  const units=[{typeKey:'hardware',cells:rooms.flatMap(r=>r.cells),what:'test range',name:'Test range',loot:'tools',cuisine:'diner'}];
  const seedStr='test/range', style=styleFor(seedStr,units,rooms), Lf={units:0,base:0};
  const wallH=3.4;
  const G={site,typeKey:'hardware',seedStr,history:'den',M,sense,A:NI*NJ,floors:[{k:0,units,P,O,Fn,D:Dc,L:Lf,style,fseed:seedStr}],levels:1,cores:[],
    stucco:'#d8c7a3',roofCol:'#6e6a64',L:Lf,ms:0,mess:.25,gone:.3,wallH,FH:wallH+.45,label:'Combat test range',noise:noise2(seedStr+'|noise'),
    test:{posts,labels:LABELS.map(([x,z,text])=>({p:[M.u0+x,M.v0+z],text}))}};
  setLevel(G,0);
  return G;
}
return {build,PLAN,OPENINGS,ITEMS,POSTS};
})();
if(typeof module!=='undefined') module.exports=CombatTestMap;
