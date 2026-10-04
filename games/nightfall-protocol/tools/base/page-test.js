// Browser check for the base prototype: loads, places things with the mouse and through the rules, runs a day and a night,
// founds the base at the other base point and in open ground.
//   ./build.sh   then   THREE=<path to three r128 three.min.js> node page-test.js [shots-dir]
// Software rendering is slow; this checks behaviour, not frame rate.
const {chromium}=require(process.env.PW||'playwright'), assert=require('assert'), path=require('path');
const PAGE='file://'+path.resolve(__dirname,'../../mockups/base.html'), THREE=process.env.THREE||require.resolve('three/build/three.min.js'), SHOTS=process.argv[2];
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROME||'/opt/pw-browsers/chromium/chrome-linux/chrome',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}).catch(()=>chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}));
  const page=await browser.newPage({viewport:{width:1360,height:960}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{ if(m.type()==='error'&&!/Failed to load resource/.test(m.text())) errors.push(m.text()); });   // fonts may not load offline
  await page.route('**/three.min.js',r=>r.fulfill({path:THREE,contentType:'application/javascript'}));
  await page.goto(PAGE); await page.waitForFunction(()=>window.__ranch&&window.__ranch.frames()>2,null,{timeout:180000});
  const shot=async n=>{ if(SHOTS) await page.screenshot({path:path.join(SHOTS,n+'.png')}); };
  const screenOf=(x,z)=>page.evaluate(([x,z])=>window.__ranch.screen(x,z),[x,z]);
  const look=(x,z,dist=90,pitch=.9)=>page.evaluate(([x,z,dist,pitch])=>{ const r=window.__ranch; Object.assign(r.view,{tx:x,tz:z,dist,pitch}); r.placeCam(); },[x,z,dist,pitch]);
  await shot('1-dawn');
  // a tank with the mouse, then a dragged wall line
  await page.evaluate(()=>{ window.__ranch.ui.speed=0; }); await look(730,35);
  await page.click('[data-tool="tank"]'); const p1=await screenOf(731,31); await page.mouse.move(p1.x,p1.y); await page.mouse.move(p1.x+1,p1.y); await page.mouse.click(p1.x+1,p1.y);
  await page.click('[data-tool="wall"]'); const a=await screenOf(752,0), b=await screenOf(752,22);
  await page.mouse.move(a.x,a.y); await page.mouse.down(); await page.mouse.move((a.x+b.x)/2,(a.y+b.y)/2); await page.mouse.move(b.x,b.y); await page.mouse.up(); await page.keyboard.press('Escape');
  const placed=await page.evaluate(()=>{ const st=window.__ranch.st; return {tank:st.things.filter(t=>t.type==='tank').length, walls:st.things.filter(t=>t.type==='wall').length}; });
  assert.equal(placed.tank,1,'a tank placed with the mouse'); assert(placed.walls>=10,'a wall line dragged with the mouse: '+placed.walls);
  // beds, a ramada, a bunkhouse, a gate and a watch post through the rules; run the morning
  await page.evaluate(()=>{ const {R}=window.__ranch; R.place('bed',R.cellOf(722,44),0); R.place('bed',R.cellOf(724,44),0); R.place('ramada',R.cellOf(716,50),0); R.place('bunkhouse',R.cellOf(740,64),0); R.place('watch',R.cellOf(700,70),0); R.place('gate',R.cellOf(752,26),0); window.__ranch.st.stock.shelter+=30; window.__ranch.ui.speed=.25; });
  const m1=await page.evaluate(()=>{ const {R,st}=window.__ranch; R.advance(90); return {building:st.people.filter(p=>p.task&&p.task.kind==='build').length, clock:R.fmt(st.minutes)}; });
  assert(m1.building>=3,'people build: '+JSON.stringify(m1));
  await page.waitForTimeout(1500); await shot('2-building');
  await page.evaluate(()=>{ window.__ranch.ui.speed=.05; }); await look(736,24,30,.55); await page.waitForTimeout(2500); await shot('2b-close');
  await page.evaluate(()=>{ window.__ranch.ui.speed=.25; }); await look(730,40,110,.85);
  // four days on: everything finished, the grid view shows it
  const m2=await page.evaluate(()=>{ const {R,st}=window.__ranch; R.advance(4*1440-90); document.getElementById('grid').click(); return {done:st.things.filter(t=>t.state==='done').map(t=>t.type), cap:R.waterCap()}; });
  for(const k of ['tank','bed','ramada','bunkhouse','watch','gate']) assert(m2.done.includes(k),k+' finished: '+JSON.stringify(m2)); assert.equal(m2.cap,1400);
  await page.waitForTimeout(1500); await shot('3-grid');
  await page.evaluate(()=>{ const {R}=window.__ranch; document.getElementById('grid').click(); R.advance(6*60); });   // noon
  await page.waitForTimeout(1500); await shot('3b-noon');
  // night: two on watch, two on the cots, the rest in the bunkhouse
  const m3=await page.evaluate(async()=>{ const {R,st,figs}=window.__ranch; R.advance(11*60); await new Promise(r=>setTimeout(r,900));
    return {guards:st.people.filter(p=>p.task&&p.task.kind==='guard').length, asleep:st.people.filter(p=>p.rec.asleep).length, lumps:figs.filter(f=>f.lump.visible).length, bunk:st.people.filter(p=>p.task&&p.task.spot&&p.task.spot.thing&&p.task.spot.thing.type==='bunkhouse').length, clock:R.fmt(st.minutes)}; });
  await page.waitForTimeout(800); await shot('4-night');
  assert.equal(m3.guards,2,'two on watch: '+JSON.stringify(m3)); assert.equal(m3.asleep,4,'four asleep'); assert.equal(m3.lumps,2,'two on the cots'); assert.equal(m3.bunk,2,'two in the bunkhouse');
  // found the base at the region home point with its button, then in open ground with the tool
  await page.click('#presets button:nth-of-type(3)');
  const m4=await page.evaluate(()=>{ const {st}=window.__ranch; return {area:st.area, things:st.things.length, claimed:Object.keys(st.claimed).length, people:st.people.length}; });
  assert(m4.area[0]===166&&m4.area[1]===162&&m4.claimed>=3&&m4.people===6,'founded at the region home point: '+JSON.stringify(m4));
  await page.waitForTimeout(1500); await shot('5-home-point');
  await page.click('[data-tool="found"]'); await look(400,190,260,1.1); const p5=await screenOf(400,190); await page.mouse.move(p5.x,p5.y); await page.mouse.move(p5.x+1,p5.y); await page.mouse.click(p5.x+1,p5.y);
  const m5=await page.evaluate(()=>{ const {R,st}=window.__ranch; R.place('wall',R.cellOf(400,180),0); R.advance(120); const a=st.area; return {area:a, claimed:Object.keys(st.claimed).length, clock:R.fmt(st.minutes), onBase:st.people.every(p=>p.x>a[0]&&p.x<a[2]&&p.z>a[1]&&p.z<a[3])}; });
  assert(Math.abs((m5.area[0]+m5.area[2])/2-400)<4&&m5.claimed===0&&m5.onBase,'founded in open ground with the tool: '+JSON.stringify(m5));
  await page.waitForTimeout(1200); await shot('6-open-ground');
  const pnl=await page.evaluate(()=>({people:document.querySelectorAll('.person').length, water:document.getElementById('wl').textContent, log:document.querySelectorAll('#log li').length}));
  assert.equal(pnl.people,6); assert(/ L$/.test(pnl.water));
  if(errors.length) console.log('ERRORS',[...new Set(errors)].slice(0,5));
  assert.deepEqual(errors,[],'no page errors');
  console.log('ok',JSON.stringify({placed,m1,m3,m4,m5}));
  await browser.close();
})().catch(e=>{ console.error(e); process.exit(1); });
