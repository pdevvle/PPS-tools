// Browser check for the ranch prototype: loads, places things with the mouse and through the rules, runs a day and a night.
//   ./build.sh   then   THREE=<path to three r128 three.min.js> node page-test.js [shots-dir]
// Software rendering is slow; this checks behaviour, not frame rate.
const {chromium}=require(process.env.PW||'playwright'), assert=require('assert'), path=require('path');
const PAGE='file://'+path.resolve(__dirname,'../../mockups/base.html'), THREE=process.env.THREE||require.resolve('three/build/three.min.js'), SHOTS=process.argv[2];
(async()=>{
  const browser=await chromium.launch({executablePath:process.env.CHROME||'/opt/pw-browsers/chromium/chrome-linux/chrome',args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}).catch(()=>chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']}));
  const page=await browser.newPage({viewport:{width:1360,height:960}}), errors=[];
  page.on('pageerror',e=>errors.push(e.message)); page.on('console',m=>{ if(m.type()==='error'&&!/Failed to load resource/.test(m.text())) errors.push(m.text()); });   // fonts may not load offline
  await page.route('**/three.min.js',r=>r.fulfill({path:THREE,contentType:'application/javascript'}));
  await page.goto(PAGE); await page.waitForFunction(()=>window.__ranch&&window.__ranch.frames()>2,null,{timeout:120000});
  const shot=async n=>{ if(SHOTS) await page.screenshot({path:path.join(SHOTS,n+'.png')}); };
  await shot('1-dawn');
  // place a tank with the mouse: pick the tool, then click the ground at a world point
  const screenOf=(x,z)=>page.evaluate(([x,z])=>window.__ranch.screen(x,z),[x,z]);
  await page.evaluate(()=>{ const r=window.__ranch; r.ui.speed=0; r.view.tx=730; r.view.tz=35; r.view.dist=90; r.view.pitch=.9; r.placeCam(); });
  await page.click('[data-tool="tank"]');
  const p1=await screenOf(731,31); await page.mouse.move(p1.x,p1.y); await page.mouse.move(p1.x+1,p1.y); await page.mouse.click(p1.x+1,p1.y);
  // a dragged wall line
  await page.click('[data-tool="wall"]');
  const a=await screenOf(752,0), b=await screenOf(752,22); await page.mouse.move(a.x,a.y); await page.mouse.down(); await page.mouse.move((a.x+b.x)/2,(a.y+b.y)/2); await page.mouse.move(b.x,b.y); await page.mouse.up();
  await page.keyboard.press('Escape');
  const placed=await page.evaluate(()=>{ const st=window.__ranch.st; return {tank:st.things.filter(t=>t.type==='tank').length, walls:st.things.filter(t=>t.type==='wall').length}; });
  assert.equal(placed.tank,1,'a tank placed with the mouse'); assert(placed.walls>=10,'a wall line dragged with the mouse: '+placed.walls);
  // two beds and a ramada through the rules, then run the morning
  await page.evaluate(()=>{ const {R}=window.__ranch; R.place('bed',R.cellOf(722,40),0); R.place('bed',R.cellOf(724,40),0); R.place('ramada',R.cellOf(716,46),0); window.__ranch.ui.speed=.25; });
  await page.waitForFunction(()=>window.__ranch.frames()>30,null,{timeout:120000});
  const m1=await page.evaluate(()=>{ const {R,st}=window.__ranch; R.advance(90); return {walking:st.people.filter(p=>p.act==='walk'||p.act==='carry').length, building:st.people.filter(p=>p.task&&p.task.kind==='build').length, water:st.stock.water}; });
  assert(m1.building>=3,'people build: '+JSON.stringify(m1));
  await page.waitForTimeout(1500); await shot('2-building');
  await page.evaluate(()=>{ const r=window.__ranch; r.ui.speed=.05; r.view.tx=738; r.view.tz=22; r.view.dist=34; r.view.pitch=.55; r.placeCam(); }); await page.waitForTimeout(2500); await shot('2b-close');
  await page.evaluate(()=>{ const r=window.__ranch; r.ui.speed=.25; r.view.tx=730; r.view.tz=35; r.view.dist=90; r.view.pitch=.9; r.placeCam(); });
  // to the evening of day 2: things finished, the grid shows them
  const m2=await page.evaluate(()=>{ const {R,st}=window.__ranch; R.advance(13*60); document.getElementById('grid').click(); return {done:st.things.filter(t=>t.state==='done').map(t=>t.type), cap:R.waterCap(), clock:document.getElementById('clock').textContent}; });
  assert(m2.done.includes('tank')&&m2.done.filter(t=>t==='bed').length===2&&m2.done.includes('ramada'),'finished: '+JSON.stringify(m2)); assert.equal(m2.cap,1400);
  await page.waitForTimeout(1500); await shot('3-grid');
  await page.evaluate(()=>{ const {R}=window.__ranch; document.getElementById('grid').click(); R.advance(18*60); });   // day 2 noon
  await page.waitForTimeout(1500); await shot('3b-noon');
  // night: sleepers on the beds, the rest inside
  const m3=await page.evaluate(async()=>{ const {R,st,figs}=window.__ranch; R.advance(11*60); await new Promise(r=>setTimeout(r,800)); return {asleep:st.people.filter(p=>p.asleep).length, visible:figs.filter(f=>f.root.visible).length, lumps:figs.filter(f=>f.lump.visible).length, clock:document.getElementById('clock').textContent}; });
  await page.waitForTimeout(1200); await shot('4-night');
  assert.equal(m3.asleep,6,'everyone asleep at night: '+JSON.stringify(m3)); assert.equal(m3.lumps,2,'two sleep on the beds');
  // panels follow the state
  const pnl=await page.evaluate(()=>({people:document.querySelectorAll('.person').length, water:document.getElementById('wl').textContent, log:document.querySelectorAll('#log li').length}));
  assert.equal(pnl.people,6); assert(/ L$/.test(pnl.water)); assert(pnl.log>3);
  if(errors.length) console.log('ERRORS',[...new Set(errors)].slice(0,5));
  assert.deepEqual(errors,[],'no page errors');
  console.log('ok',JSON.stringify({placed,m1,m2,m3,pnl}));
  await browser.close();
})().catch(e=>{ console.error(e); process.exit(1); });
