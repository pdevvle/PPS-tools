// ---------- campaign: the strategic layer's rules (clock, light and heat, travel, water, scavenging, raiders, saving) ----------
// No rendering, so the same file runs in the pages and in Node (tools/region/test.js). The page draws what this holds.
const Campaign=(()=>{
const VERSION=1, SAVE_KEY='nightfall.campaign.v1';
const K={UNKNOWN:0,RUMOUR:1,SCOUT:2,CURRENT:3}, STALE=3*1440;   // scouted knowledge goes stale after 3 days
const LOOT=['food','medicine','tools','fuel','gear','water','shelter','goods'];
// what one unit of each loot category is and what it weighs; base.stock holds these units for the base (building.md)
const UNIT={food:{name:'rations',kg:1},medicine:{name:'med kits',kg:.5},tools:{name:'parts',kg:2},fuel:{name:'L fuel',kg:.8},gear:{name:'gear',kg:2},water:{name:'L water',kg:1},shelter:{name:'materials',kg:5},goods:{name:'trade goods',kg:1}};
const CARRY=25, WATER_CAP=6;   // kg a person carries, water included; litres of water a person carries at most
const SPEED={motorway:5,motorway_link:5,trunk:5,primary:5,secondary:5,tertiary:5,unclassified:5,residential:5,track:4}, OFF=2.5;
const STEP=5;   // game minutes per simulation step at most

// ---------- light and heat: early summer in the Sonoran desert ----------
const SUNRISE=5*60+20, SUNSET=19*60+35, T_LO=24, T_HI=40, T_MIN_AT=5.5, T_MAX_AT=16, LAPSE=.0065, T_REF=600, REST_HEAT=.5;
const mod=m=>((m%1440)+1440)%1440;
function sunAt(min){ const m=mod(min), h=m/60;
  const daylight=m<SUNRISE-30||m>SUNSET+30?0:m<SUNRISE+30?(m-SUNRISE+30)/60:m>SUNSET-30?(SUNSET+30-m)/60:1;
  const phase=daylight===0?'night':daylight<1?(m<720?'dawn':'dusk'):'day';
  let t;   // coolest just before sunrise, hottest mid-afternoon
  if(h>=T_MIN_AT&&h<T_MAX_AT) t=T_LO+(T_HI-T_LO)*(1-Math.cos(Math.PI*(h-T_MIN_AT)/(T_MAX_AT-T_MIN_AT)))/2;
  else { const s=(h>=T_MAX_AT?h-T_MAX_AT:h+24-T_MAX_AT)/(24-T_MAX_AT+T_MIN_AT); t=T_HI-(T_HI-T_LO)*(1-Math.cos(Math.PI*s))/2; }
  const arc=(m-SUNRISE)/(SUNSET-SUNRISE);   // 0 at sunrise, 1 at sunset
  return {daylight, phase, tempC:t, elev:Math.max(0,Math.sin(Math.PI*arc)), arc}; }
const heatOf=tC=>Math.max(0,Math.min(1,(tC-30)/10));   // 0 at 30 °C or cooler, 1 at 40 °C
// litres per person per hour: 0.5 on the move, up to double in full heat; resting in shade 0.2, up to 0.4
const waterRate=(moving,heat)=>(moving?.5:.2)*(1+heat);
// how fast travel goes against the base speeds: darkness slows off-road travel most, heat slows everything, thirst more so
function paceAt(min,off,heat,thirsty){ const dark=1-sunAt(min).daylight; return (off?1-.4*dark:1-.15*dark)*(1-.25*heat)*(thirsty?.6:1); }

// ---------- the region: terrain, sectors, the travel graph ----------
let R,D,G,adj,HX,HZ,SEC,homeSec,homeXZ,st=null;
const hRaw=(x,z)=>{ const fx=(x-D.x0)/D.step, fz=(z-D.z0)/D.step, i=Math.max(0,Math.min(D.nx-2,Math.floor(fx))), j=Math.max(0,Math.min(D.nz-2,Math.floor(fz))), u=Math.min(1,Math.max(0,fx-i)), v=Math.min(1,Math.max(0,fz-j)), h=(a,b)=>D.h[b*D.nx+a];
  return (h(i,j)*(1-u)+h(i+1,j)*u)*(1-v)+(h(i,j+1)*(1-u)+h(i+1,j+1)*u)*v; };
const elevAt=(x,z)=>hRaw(x,z)+D.base;
const tempAt=(min,x,z)=>sunAt(min).tempC-LAPSE*(elevAt(x,z)-T_REF);   // high ground runs cooler
const secAt=(x,z)=>{ const c=Math.floor((x+HX)/SEC), r=Math.floor((z+HZ)/SEC); return c>=0&&r>=0&&c<R.cols&&r<R.rows?[c,r]:null; };
const secCentre=(c,r)=>[-HX+(c+.5)*SEC, -HZ+(r+.5)*SEC];
const sameSec=(a,b)=>!!a&&!!b&&a[0]===b[0]&&a[1]===b[1];
function init(region){ R=region; D=R.dem; G=R.graph; HX=R.half[0]; HZ=R.half[1]; SEC=R.sector;
  adj=G.nodes.map(()=>[]);
  for(const [a,b,len,cls] of G.edges){ const t=len/1000/(SPEED[cls]||4), ha=hRaw(...G.nodes[a]), hb=hRaw(...G.nodes[b]);   // +1 h per 300 m climbed
    adj[a].push([b,t+Math.max(0,hb-ha)/300]); adj[b].push([a,t+Math.max(0,ha-hb)/300]); }
  homeSec=secAt(R.home[0]+700,R.home[1]);   // just east of New River, on the ranch side
  homeXZ=secCentre(...homeSec); }
function nearestNodes(x,z,k=6){ const best=[]; for(let i=0;i<G.nodes.length;i++){ if(!adj[i].length) continue; const d=Math.hypot(G.nodes[i][0]-x,G.nodes[i][1]-z);
  if(best.length<k||d<best[best.length-1][1]){ best.push([i,d]); best.sort((a,b)=>a[1]-b[1]); if(best.length>k) best.pop(); } } return best; }
const offTime=(x0,z0,x1,z1)=>Math.hypot(x1-x0,z1-z0)/1000/OFF+Math.max(0,hRaw(x1,z1)-hRaw(x0,z0))/300;
function heap(){ const a=[]; return {get size(){ return a.length; },
  push(t,i){ a.push([t,i]); let k=a.length-1; while(k){ const p=(k-1)>>1; if(a[p][0]<=a[k][0]) break; [a[p],a[k]]=[a[k],a[p]]; k=p; } },
  pop(){ const top=a[0], last=a.pop(); if(a.length){ a[0]=last; let k=0; for(;;){ const l=2*k+1, r=l+1; let m=k; if(l<a.length&&a[l][0]<a[m][0]) m=l; if(r<a.length&&a[r][0]<a[m][0]) m=r; if(m===k) break; [a[m],a[k]]=[a[k],a[m]]; k=m; } } return top; } }; }
// fastest way on the road graph (Dijkstra), walking off-road to and from it; each leg keeps its base hours and whether it is off-road
function route(x0,z0,x1,z1){
  const direct=offTime(x0,z0,x1,z1), B=new Set(nearestNodes(x1,z1).map(([i])=>i)), dist=new Map(), prev=new Map(), h=heap();
  for(const [i] of nearestNodes(x0,z0)){ const t=offTime(x0,z0,...G.nodes[i]); if(!dist.has(i)||t<dist.get(i)){ dist.set(i,t); prev.set(i,-1); h.push(t,i); } }
  let best=direct, bestEnd=-1;
  while(h.size){ const [t,i]=h.pop(); if(t>dist.get(i)||t>=best) continue;
    if(B.has(i)){ const tt=t+offTime(...G.nodes[i],x1,z1); if(tt<best){ best=tt; bestEnd=i; } }
    for(const [j,et] of adj[i]){ const nt=t+et; if(!dist.has(j)||nt<dist.get(j)){ dist.set(j,nt); prev.set(j,i); h.push(nt,j); } } }
  const pts=[[x0,z0]], segs=[];
  if(bestEnd>=0){ const chain=[]; for(let i=bestEnd;i!==-1;i=prev.get(i)) chain.push(i); chain.reverse();
    let tp=0; chain.forEach((i,k)=>{ const t=dist.get(i); pts.push(G.nodes[i].slice()); segs.push({h:t-tp,off:k===0}); tp=t; });
    pts.push([x1,z1]); segs.push({h:best-tp,off:true}); }
  else { pts.push([x1,z1]); segs.push({h:direct,off:true}); }
  let km=0; for(let i=1;i<pts.length;i++) km+=Math.hypot(pts[i][0]-pts[i-1][0],pts[i][1]-pts[i-1][1])/1000;
  return {pts,segs,hours:best,km}; }
// a trip: progress is measured in base hours, and spent faster or slower as light and heat change
function makeTrip(rt){ const cum=[0]; for(const s of rt.segs) cum.push(cum[cum.length-1]+s.h); return {pts:rt.pts,segs:rt.segs,cum,total:cum[cum.length-1],done:0}; }
function segOf(tr,done){ let k=0; while(k<tr.segs.length-1&&tr.cum[k+1]<=done) k++; return k; }
function tripPos(tr,done=tr.done){ const k=segOf(tr,done), a=tr.pts[k], b=tr.pts[k+1], f=tr.segs[k].h>1e-9?Math.min(1,Math.max(0,(done-tr.cum[k])/tr.segs[k].h)):1;
  return {x:a[0]+(b[0]-a[0])*f, z:a[1]+(b[1]-a[1])*f, seg:k}; }
// what a trip will cost from now: arrival time, water and hours spent lying up in the heat (a forecast; raiders aside)
function forecast(tr,startMin,people,restHeat){ let t=startMin, done=tr.done, water=0, rest=0;
  while(done<tr.total-1e-9&&t-startMin<14*1440){ const p=tripPos(tr,done), heat=heatOf(tempAt(t,p.x,p.z));
    if(restHeat&&heat>=REST_HEAT){ water+=waterRate(false,heat)*people*STEP/60; rest+=STEP; t+=STEP; continue; }
    const pace=paceAt(t,tr.segs[p.seg].off,heat,false), need=(tr.total-done)/pace*60, dt=Math.min(STEP,need);
    water+=waterRate(true,heat)*people*dt/60; done+=dt/60*pace; t+=dt; }
  return {arrive:t, hours:(t-startMin)/60, water, rest:rest/60}; }

// ---------- randomness that survives a reload ----------
function rand(){ let s=st.rng=(st.rng+0x6D2B79F5)>>>0; s=Math.imul(s^s>>>15,s|1); s^=s+Math.imul(s^s>>>7,s|61); return ((s^s>>>14)>>>0)/4294967296; }
const hash=n=>{ let s=(n*2654435761)>>>0; s=Math.imul(s^s>>>15,s|1); s^=s+Math.imul(s^s>>>7,s|61); return ((s^s>>>14)>>>0)/4294967296; };

// ---------- knowledge ----------
function lookout(x,z){ const s=secAt(x,z); if(!s) return 1; const [c,r]=s, me=R.sectors[r][c]; let around=0,n=0;
  for(let dr=-3;dr<=3;dr++) for(let dc=-3;dc<=3;dc++){ const q=R.sectors[r+dr]?.[c+dc]; if(q){ around+=q.lo; n++; } }
  return Math.min(3,1+Math.floor(Math.max(0,me.hi-around/n)/45)); }   // high ground sees further
function reveal(x,z){ const s=secAt(x,z); if(!s) return 0; const [c,r]=s, rad=Math.max(1,lookout(x,z)-(sunAt(st.minutes).daylight<.5?1:0));   // one less at night
  for(let dr=-rad;dr<=rad;dr++) for(let dc=-rad;dc<=rad;dc++){ const kk=st.know[r+dr]?.[c+dc]; if(!kk||Math.hypot(dr,dc)>rad+.4) continue; if(kk.k<K.SCOUT) kk.k=K.SCOUT; kk.seen=st.minutes; }
  return rad; }
function refreshCurrent(){ for(const row of st.know) for(const k of row) if(k.k===K.CURRENT) k.k=K.SCOUT;
  for(const s of st.squads){ const q=secAt(s.x,s.z); if(q){ st.know[q[1]][q[0]].k=K.CURRENT; st.know[q[1]][q[0]].seen=st.minutes; } }
  st.know[homeSec[1]][homeSec[0]].k=K.CURRENT; st.know[homeSec[1]][homeSec[0]].seen=st.minutes; }
const stale=kk=>kk.k===K.SCOUT&&st.minutes-kk.seen>=STALE;

// ---------- a new campaign ----------
function newGame(seed=20261003){
  st={v:VERSION, minutes:7*60+30, rng:seed>>>0, seq:1, know:R.sectors.map(row=>row.map(()=>({k:0,seen:0}))), squads:[], sites:{}, bands:[], base:{stock:{}}, log:[], enc:null, waitUntil:0};
  for(const p of R.places) if(['town','village','hamlet'].includes(p.kind)){ const s=p.sector; for(let dr=-2;dr<=2;dr++) for(let dc=-2;dc<=2;dc++){ const kk=st.know[s[1]+dr]?.[s[0]+dc]; if(kk) kk.k=Math.max(kk.k,K.RUMOUR); } }
  { const [c,r]=homeSec; for(let dr=-7;dr<=7;dr++) for(let dc=-7;dc<=7;dc++){ const kk=st.know[r+dr]?.[c+dc], d=Math.hypot(dr,dc); if(!kk||d>7.4) continue; if(d<=3.4){ kk.k=K.SCOUT; kk.seen=st.minutes; } else kk.k=Math.max(kk.k,K.RUMOUR); } }
  const [hx,hz]=homeXZ, sq=(name,people,c,x,z)=>({name,people,c,x,z,water:people*WATER_CAP,pack:{},restHeat:false,trip:null,task:null,thirsty:false});
  st.squads.push(sq('Ranch party',4,'#e0a526',hx,hz), sq('Scouts',2,'#5b9fc4',hx+120,hz+80));
  spawnBands(4); reveal(hx,hz); refreshCurrent();
  note('The ranch is quiet. Two squads are ready.');
  return st; }
// raider bands: lairs well away from the ranch, near a road, spread apart
function spawnBands(n){ const nodes=[]; for(let i=0;i<G.nodes.length;i++) if(adj[i].length){ const [x,z]=G.nodes[i]; if(Math.hypot(x-homeXZ[0],z-homeXZ[1])>6000) nodes.push(i); }
  const lairs=[]; for(let tries=0;lairs.length<n&&tries<400;tries++){ const [x,z]=G.nodes[nodes[Math.floor(rand()*nodes.length)]]; if(lairs.every(([a,b])=>Math.hypot(a-x,b-z)>4500)) lairs.push([x,z]); }
  for(const [x,z] of lairs){ const size=3+Math.floor(rand()*4); st.bands.push({id:'b'+st.seq++, size, boss:size>=5, x, z, lair:[x,z], trip:null, campUntil:st.minutes+rand()*300, seen:null, cool:{}}); } }
function note(msg){ st.log.unshift({t:st.minutes,msg}); if(st.log.length>40) st.log.length=40; }
const fmtT=m=>{ const d=Math.floor(m/1440)+1, h=Math.floor(mod(m)/60), mm=Math.floor(m%60); return `Day ${d} ${String(h).padStart(2,'0')}:${String(mm).padStart(2,'0')}`; };
const nearestPlace=(x,z)=>{ let best=null,bd=1e12; for(const p of R.places){ const d=Math.hypot(p.p[0]-x,p.p[1]-z); if(d<bd){ bd=d; best=p; } } return best?(bd<1500?best.name:`${(bd/1609).toFixed(1)} mi from ${best.name}`):'open desert'; };

// ---------- squads: carrying, water, orders ----------
const packKg=sq=>Object.entries(sq.pack).reduce((a,[k,n])=>a+n*UNIT[k].kg,0);
const capKg=sq=>sq.people*CARRY, waterCap=sq=>sq.people*WATER_CAP;
const atHome=sq=>sameSec(secAt(sq.x,sq.z),homeSec);
const busy=sq=>!!(sq.trip||sq.task);
function send(i,x,z){ const sq=st.squads[i]; if(!sq||sq.task||st.enc) return null; const rt=route(sq.x,sq.z,x,z); sq.trip=makeTrip(rt); note(`${sq.name} set out for ${nearestPlace(x,z)}.`); return sq.trip; }
function stop(i){ const sq=st.squads[i]; if(sq?.trip){ sq.trip=null; note(`${sq.name} stopped.`); } }
function unload(sq){ const got=Object.entries(sq.pack).filter(([,n])=>n>0); if(got.length){ for(const [k,n] of got) st.base.stock[k]=(st.base.stock[k]||0)+n; note(`${sq.name} brought home ${got.map(([k,n])=>`${n} ${UNIT[k].name}`).join(', ')}.`); sq.pack={}; }
  if(sq.water<waterCap(sq)) sq.water=waterCap(sq); sq.thirsty=false; }

// ---------- sites: what is there, how long it takes, what comes back ----------
const SIZE={supermarket:3,school:3,fire_station:3,storage_rental:3,community_centre:3,place_of_worship:2,car_repair:2,waste_disposal:1,waste_transfer_station:2,storage_tank:2,water_tower:2,fuel:2,convenience:2,restaurant:2,variety_store:2,pharmacy:2,veterinary:2,clothes:1,shoes:1,fast_food:1,shelter:1,toilets:1,parking:1};
const sizeOf=s=>SIZE[s.what]||1, HOURS=[0,1,2,3];
function stockOf(i){ let s=st.sites[i]; if(s) return s; const site=R.sites[i], size=sizeOf(site), base=[0,8,16,30][size], r=k=>hash(i*31+k), stock={};
  stock[site.loot]=Math.round(base*(.6+r(1)*.8)*(site.loot==='water'?6:1));   // tanks and wells hold litres
  for(let k=0;k<2;k++){ const other=LOOT[Math.floor(r(2+k)*LOOT.length)]; if(other!==site.loot) stock[other]=(stock[other]||0)+Math.round(base*(.15+r(4+k)*.25)); }
  return st.sites[i]={stock, visits:0, last:0, full:Object.values(stock).reduce((a,b)=>a+b,0)}; }
// others pick places over as the days go by
function weather(s){ const days=(st.minutes-(s.last||450))/1440; if(days<=0) return; const f=Math.pow(.985,days); for(const k in s.stock) s.stock[k]=Math.round(s.stock[k]*f); }
const leftOf=i=>{ const s=st.sites[i]; if(!s) return 1; const n=Object.values(s.stock).reduce((a,b)=>a+b,0); return s.full?n/s.full:0; };
const scavHours=(i,people,min=st.minutes)=>HOURS[sizeOf(R.sites[i])]*Math.sqrt(4/Math.max(1,people))*(sunAt(min).daylight<.5?1.3:1);   // dark rooms take longer
function canScavenge(i,si){ const sq=st.squads[i], site=R.sites[si]; if(!sq||!site||busy(sq)||st.enc) return false; const q=secAt(sq.x,sq.z); return sameSec(q,site.sector)&&st.know[q[1]][q[0]].k>=K.SCOUT; }
function scavenge(i,si){ if(!canScavenge(i,si)) return false; const sq=st.squads[i], h=scavHours(si,sq.people); sq.task={kind:'scavenge',site:si,start:st.minutes,until:st.minutes+h*60};
  note(`${sq.name} started searching ${siteName(R.sites[si])} (${h.toFixed(1)} h).`); return true; }
const siteName=s=>s.name||String(s.what).replace(/_/g,' ');
const ORDER=['medicine','water','food','tools','fuel','gear','goods','shelter'];   // what a squad takes first when it can't carry everything
function finishScavenge(sq){ const si=sq.task.site, s=stockOf(si); weather(s); const took={};
  for(const k of ORDER){ const have=s.stock[k]||0; if(!have) continue; const want=Math.ceil(have*.6); let got=0;
    if(k==='water'){ const fill=Math.max(0,Math.min(want,waterCap(sq)-sq.water)); sq.water+=fill; got+=fill; if(fill) sq.thirsty=false; }   // drink up and fill the bottles first
    const room=capKg(sq)-sq.water-packKg(sq), n=Math.max(0,Math.min(Math.floor(want-got),Math.floor(room/UNIT[k].kg)));
    if(n) sq.pack[k]=(sq.pack[k]||0)+n; got+=n;
    s.stock[k]=Math.max(0,have-Math.ceil(got-1e-9)); if(got>=.5) took[k]=Math.round(got); }
  s.visits++; s.last=st.minutes; sq.task=null;
  const got=Object.entries(took).filter(([,n])=>n>0);
  note(got.length?`${sq.name} searched ${siteName(R.sites[si])}: ${got.map(([k,n])=>`${n} ${UNIT[k].name}`).join(', ')}.`:`${sq.name} searched ${siteName(R.sites[si])} and found nothing worth carrying.`);
  return took; }

// ---------- raiders ----------
const RAIDER_HEAT=.6;   // bands lie up in the worst of the heat
function stepBand(b,dt){ const heat=heatOf(tempAt(st.minutes,b.x,b.z));
  if(b.trip){ if(heat>=RAIDER_HEAT) return; const tr=b.trip, p=tripPos(tr); tr.done=Math.min(tr.total,tr.done+dt/60*(tr.segs[p.seg].off?1:.9)*(1-.2*heat));   // they know the ground, dark or not
    const q=tripPos(tr); b.x=q.x; b.z=q.z; if(tr.done>=tr.total-1e-9){ b.trip=null; b.campUntil=st.minutes+(2+rand()*4)*60; } return; }
  if(st.minutes<b.campUntil||heat>=RAIDER_HEAT) return;
  for(let tries=0;tries<8;tries++){ const a=rand()*Math.PI*2, d=1500+rand()*3500, x=b.lair[0]+Math.cos(a)*d, z=b.lair[1]+Math.sin(a)*d;   // roam around the lair
    if(!secAt(x,z)) continue; b.trip=makeTrip(route(b.x,b.z,x,z)); return; }
  b.campUntil=st.minutes+60; }
// who sees whom: squads spot further by day and from high ground; raiders spot a moving squad more easily than one holed up
const squadSight=(sq,min)=>900*(.45+.55*sunAt(min).daylight)*(1+.2*(lookout(sq.x,sq.z)-1));
const bandSight=(sq,min)=>650*(.5+.5*sunAt(min).daylight)*(sq.trip?1:.6);
const HOME_SIGHT=1500;
function spot(){ let enc=null;
  for(const b of st.bands){ let seen=Math.hypot(b.x-homeXZ[0],b.z-homeXZ[1])<HOME_SIGHT*(.5+.5*sunAt(st.minutes).daylight);
    st.squads.forEach((sq,i)=>{ const d=Math.hypot(b.x-sq.x,b.z-sq.z), sR=squadSight(sq,st.minutes), bR=bandSight(sq,st.minutes); if(d<sR) seen=true;
      if(enc||atHome(sq)||(b.cool[i]||0)>st.minutes||(d>=sR&&d>=bR)) return;
      enc=encounter(b,i,d<sR&&d<bR?'both':d<sR?'squad':'enemy',d); });
    if(seen) b.seen={x:b.x,z:b.z,t:st.minutes}; }
  return enc; }
const ALERT={squad:'unaware',both:'suspicious',enemy:'alert'};
// the encounter the tactical layer plays out (data shape agreed in briefs/strategy-map.md)
function encounter(b,i,first,d){ const sq=st.squads[i], s=sunAt(st.minutes), x=(sq.x+b.x)/2, z=(sq.z+b.z)/2, q=secAt(x,z);
  return {id:'e'+st.seq++, at:st.minutes, where:{x,z,sector:q,ground:q?R.sectors[q[1]][q[0]].type:'desert',place:nearestPlace(x,z)}, light:s.phase, tempC:Math.round(tempAt(st.minutes,x,z)),
    squad:{index:i,name:sq.name,people:sq.people,pos:[sq.x,sq.z]}, enemy:{kind:'raiders',band:b.id,count:b.size,boss:b.boss,alert:ALERT[first],pos:[b.x,b.z]}, firstSight:first, distance:Math.round(d), forced:false}; }
const bandOf=id=>st.bands.find(b=>b.id===id);
function backOff(sq,b,m){ const dx=sq.x-b.x, dz=sq.z-b.z, l=Math.hypot(dx,dz)||1; let x=sq.x+dx/l*m, z=sq.z+dz/l*m; if(!secAt(x,z)){ x=sq.x; z=sq.z; } sq.trip=makeTrip(route(sq.x,sq.z,x,z)); }
// the player's answer to an encounter: avoid, hide, engage (on baked ground) or fight it out (placeholder until combat reports results)
function resolve(choice,result){ const e=st.enc; if(!e) return null; const sq=st.squads[e.squad.index], b=bandOf(e.enemy.band); let out='';
  const forced=why=>{ st.enc={...e, id:'e'+st.seq++, forced:true, enemy:{...e.enemy,alert:'alert'}, firstSight:'enemy'}; note(why); return st.enc; };
  if(!b||!sq){ st.enc=null; return null; }
  if(choice==='avoid'){ if(e.forced) return e;
    if(e.enemy.alert==='alert'&&b.size>sq.people&&rand()<.4) return forced(`The raiders ran ${sq.name} down.`);
    backOff(sq,b,1500); b.cool[e.squad.index]=st.minutes+180; out=`${sq.name} pulled back from the raiders.`; }
  else if(choice==='hide'){ if(e.forced) return e;
    if(e.enemy.alert==='alert'||(e.enemy.alert==='suspicious'&&rand()<.35)) return forced(`The raiders found ${sq.name}.`);
    sq.task={kind:'hide',until:st.minutes+60,start:st.minutes,resume:sq.trip}; sq.trip=null; b.cool[e.squad.index]=st.minutes+180; out=`${sq.name} lay low and the raiders passed.`; }
  else if(choice==='fought'){   // back from the tactical ground; combat may say how it went
    const won=result?result.won!==false:true; if(result&&result.people!==undefined) sq.people=Math.max(0,result.people);
    if(won){ st.bands=st.bands.filter(o=>o!==b); out=`${sq.name} beat the raiders near ${e.where.place}.`; } else { backOff(sq,b,1500); b.cool[e.squad.index]=st.minutes+240; out=`${sq.name} was driven off.`; } }
  else if(choice==='auto'){   // placeholder: rough odds from head count, aim and who saw whom first
    const s=sq.people*72*(e.firstSight==='squad'?1.3:1), r=b.size*60*(e.enemy.alert==='alert'?1.15:1)*(b.boss?1.1:1), won=rand()<s/(s+r);
    st.minutes+=60; sq.task=null;
    if(won){ st.bands=st.bands.filter(o=>o!==b); out=`${sq.name} fought off ${b.size} raiders near ${e.where.place}.`; }
    else { sq.people=Math.max(1,sq.people-1); sq.trip=null; backOff(sq,b,2000); b.cool[e.squad.index]=st.minutes+240; out=`${sq.name} lost a fight with the raiders and fell back; one of them didn't make it.`; } }
  else return e;
  sq.water=Math.min(sq.water,waterCap(sq)); st.enc=null; refreshCurrent(); note(out); return null; }

// ---------- the clock ----------
function stepSquad(sq,i,dt){ const ev={}; if(sq.water>waterCap(sq)) sq.water=waterCap(sq);   // fewer people carry less
  if(atHome(sq)&&!sq.trip) unload(sq);
  const heat=heatOf(tempAt(st.minutes,sq.x,sq.z)); let moving=false;
  if(sq.task){ if(st.minutes>=sq.task.until){ if(sq.task.kind==='scavenge'){ ev.found=finishScavenge(sq); } else { sq.trip=sq.task.resume||null; sq.task=null; } } }
  else if(sq.trip){ const tr=sq.trip, p=tripPos(tr);
    if(!(sq.restHeat&&heat>=REST_HEAT)){ moving=true; tr.done=Math.min(tr.total,tr.done+dt/60*paceAt(st.minutes,tr.segs[p.seg].off,heat,sq.thirsty)); }
    const q=tripPos(tr), was=secAt(sq.x,sq.z); sq.x=q.x; sq.z=q.z;
    if(!sameSec(was,secAt(sq.x,sq.z))){ reveal(sq.x,sq.z); ev.revealed=true; }
    if(tr.done>=tr.total-1e-9){ sq.trip=null; reveal(sq.x,sq.z); ev.revealed=true; ev.arrived=true; note(`${sq.name} reached ${nearestPlace(sq.x,sq.z)}.`); if(atHome(sq)) unload(sq); } }
  if(!atHome(sq)){ sq.water=Math.max(0,sq.water-waterRate(moving,heat)*sq.people*dt/60);
    if(sq.water<=0&&!sq.thirsty){ sq.thirsty=true; note(`${sq.name} is out of water and slowing down.`); } }
  return ev; }
const running=()=>!st.enc&&(st.squads.some(busy)||st.waitUntil>st.minutes);
// advance the campaign by game minutes while anything is going on; stops early at an encounter or when all is still. Returns what the page needs to redraw.
function step(minutes){ const out={revealed:false,arrived:false,found:false,encounter:null,elapsed:0};
  let left=minutes;
  while(left>1e-9&&running()){ const waitOnly=!st.squads.some(busy), dt=Math.min(STEP,left,waitOnly?st.waitUntil-st.minutes:STEP); left-=dt; out.elapsed+=dt; st.minutes+=dt;
    st.squads.forEach((sq,i)=>{ const ev=stepSquad(sq,i,dt); if(ev.revealed) out.revealed=true; if(ev.arrived) out.arrived=true; if(ev.found) out.found=true; });
    for(const b of st.bands) stepBand(b,dt);
    const enc=spot(); if(enc){ st.enc=enc; out.encounter=enc;
      note(`${enc.squad.name}: ${enc.enemy.count} raiders near ${enc.where.place} (${enc.firstSight==='squad'?'not seen us yet':enc.firstSight==='both'?'both sides saw each other':'they saw us first'}).`); }
    if(st.waitUntil&&st.minutes>=st.waitUntil) st.waitUntil=0; }
  refreshCurrent();
  return out; }
// wait (idle squads) until the next dawn or dusk
function waitTurn(){ const m=mod(st.minutes), marks=[SUNRISE,SUNSET,SUNRISE+1440]; const next=marks.find(t=>t>m+1); st.waitUntil=st.minutes+(next-m); return st.waitUntil; }
const waitLabel=()=>{ const m=mod(st.minutes); return m>SUNRISE+1&&m<SUNSET-1?'Wait for dusk':'Wait for dawn'; };

// ---------- saving: one JSON blob in the viewer's browser ----------
function serial(){ const o=JSON.parse(JSON.stringify(st)); o.know={k:st.know.map(row=>row.map(k=>k.k).join('')), seen:st.know.map(row=>row.map(k=>Math.round(k.seen)))}; return o; }
function save(store){ if(!st||!store) return false; try{ store.setItem(SAVE_KEY,JSON.stringify(serial())); return true; }catch(e){ return false; } }
function load(store){ if(!store) return false; try{ const raw=store.getItem(SAVE_KEY); if(!raw) return false; const o=JSON.parse(raw);
    if(o.v!==VERSION||!o.know||o.know.k.length!==R.rows||o.know.k[0].length!==R.cols) return false;
    o.know=o.know.k.map((row,r)=>[...row].map((ch,c)=>({k:+ch,seen:o.know.seen[r][c]}))); st=o; refreshCurrent(); return true; }catch(e){ return false; } }
function forget(store){ try{ store&&store.removeItem(SAVE_KEY); }catch(e){} }

return {VERSION,SAVE_KEY,K,LOOT,UNIT,CARRY,WATER_CAP,REST_HEAT,STALE,init,newGame,get state(){ return st; },get home(){ return homeSec; },get homeXZ(){ return homeXZ; },
  sunAt,heatOf,waterRate,paceAt,tempAt,elevAt,hRaw,secAt,secCentre,route,makeTrip,tripPos,forecast,lookout,reveal,refreshCurrent,stale,fmtT,nearestPlace,
  packKg,capKg,waterCap,atHome,busy,send,stop,stockOf,leftOf,scavHours,canScavenge,scavenge,siteName,sizeOf,resolve,step,running,waitTurn,waitLabel,
  squadSight,bandSight,serial,save,load,forget,note};
})();
if(typeof module!=='undefined') module.exports=Campaign;
