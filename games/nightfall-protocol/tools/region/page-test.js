// Browser check for the region map and the zoom page: loads, plays a little, saves, reloads and resumes.
//   (cd ../../mockups && python3 -m http.server 8642) &   then   THREE=<path to three r128 three.min.js> node page-test.js
// Software rendering is slow; this checks behaviour, not frame rate.
const {chromium}=require('playwright'), assert=require('assert');
const BASE=process.env.BASE||'http://localhost:8642', THREE=process.env.THREE||require.resolve('three/build/three.min.js');
(async()=>{
  const browser=await chromium.launch({executablePath:'/opt/pw-browsers/chromium/chrome-linux/chrome', args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}).catch(()=>chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}));
  for(const page_ of ['region-map.html','streaming/zoom.html']){
    const ctx=await browser.newContext({viewport:{width:1280,height:900}}), page=await ctx.newPage(), errors=[];
    page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{ if(m.type()==='error') errors.push(m.text()); });
    await page.route('**/three.min.js',r=>r.fulfill({path:THREE,contentType:'application/javascript'}));
    await page.goto(`${BASE}/${page_}`); await page.waitForFunction(()=>window.__region,null,{timeout:120000});
    const r1=await page.evaluate(()=>{ const R=window.__region, C=R.campaign, st=C.state, [hx,hz]=C.homeXZ;
      st.bands=[]; R.send(1,hx+2500,hz-4000); R.setSpeed(0); const t0=st.minutes; R.advance(90); R.save();
      return {t0, t1:st.minutes, moving:!!st.squads[1].trip, water:st.squads[1].water, clock:document.getElementById('clock').textContent, sky:document.getElementById('sky').textContent, cards:document.querySelectorAll('.sqcard').length}; });
    assert(r1.t1>=r1.t0+89,'time passed'); assert(r1.water<12,'water used'); assert.equal(r1.cards,2); assert(/°C/.test(r1.sky));
    // pick a site in a scouted sector near home and search it
    const r2=await page.evaluate(()=>{ const R=window.__region, C=R.campaign, st=C.state, sq=st.squads[0];
      const si=REGION.sites.findIndex(s=>st.know[s.sector[1]][s.sector[0]].k>=C.K.SCOUT); if(si<0) return {skip:true};
      const s=REGION.sites[si], [cx,cz]=C.secCentre(...s.sector); R.placeSquad(0,cx,cz); R.select(...s.sector);
      const btn=document.querySelector(`[data-scav="${si}"]`); if(!btn) return {noBtn:true}; btn.click(); const busy=!!sq.task; R.advance(C.scavHours(si,sq.people)*60+5);
      return {busy, pack:C.packKg(sq)+(st.sites[si]?1:0), whole:Object.values(sq.pack).every(Number.isInteger), log:st.log[0].msg}; });
    assert(r2.skip||(!r2.noBtn&&r2.busy&&r2.pack>0&&r2.whole),'scavenged: '+JSON.stringify(r2));
    // an encounter shows the dialog and holds the clock
    const r3=await page.evaluate(()=>{ const R=window.__region, C=R.campaign, st=C.state, sq=st.squads[1];
      st.bands=[{id:'bt',size:4,boss:false,x:sq.x+250,z:sq.z,lair:[sq.x,sq.z],trip:null,campUntil:1e9,seen:null,cool:{}}];
      R.advance(10); const shown=!document.querySelector('.enc').hidden, held=!C.running(), acts=[...document.querySelectorAll('.enc [data-a]')].map(b=>b.dataset.a);
      return {shown,held,acts,enc:st.enc}; });
    assert(r3.shown&&r3.held&&r3.acts.includes('auto'),'encounter: '+JSON.stringify(r3));
    for(const k of ['where','squad','enemy','firstSight','light']) assert(r3.enc[k]!==undefined,k);
    await page.click('.enc [data-a="auto"]');
    const before=await page.evaluate(()=>{ window.__region.setSpeed(0); window.__region.save(); return JSON.stringify(window.__region.campaign.serial()); });
    await page.reload(); await page.waitForFunction(()=>window.__region,null,{timeout:120000});
    const after=await page.evaluate(()=>{ const o=window.__region.campaign.serial(); o.log=o.log.slice(1); return JSON.stringify(o); });
    const b=JSON.parse(before), a=JSON.parse(after);
    if(JSON.stringify(a.know)!==JSON.stringify(b.know)) console.log('know cells', b.know.k.flatMap((row,r)=>[...row].map((ch,c)=>[r,c,ch,a.know.k[r][c],b.know.seen[r][c],a.know.seen[r][c]])).filter(x=>x[2]!==x[3]||x[4]!==x[5]).slice(0,10));
    const diff=Object.keys(b).filter(k=>JSON.stringify(a[k])!==JSON.stringify(b[k]));
    assert.deepEqual(diff,[],'resumed the same campaign: '+diff.map(k=>k+' '+JSON.stringify(b[k]).slice(0,300)+' -> '+JSON.stringify(a[k]).slice(0,300)).join(' | '));
    await page.screenshot({path:process.env.SHOT?`${process.env.SHOT}/${page_.replace(/\W/g,'_')}.png`:undefined});
    assert.deepEqual(errors.filter(e=>!/favicon|block\/|Failed to load resource/.test(e)),[]);
    console.log('ok',page_); await ctx.close(); }
  await browser.close(); console.log('page checks passed');
})().catch(e=>{ console.error(e); process.exit(1); });
