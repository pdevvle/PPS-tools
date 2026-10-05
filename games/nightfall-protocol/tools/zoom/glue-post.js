// ---------- handing over between the map and the ground ----------
(function(){
const fade=document.getElementById('fade'), tipEl=document.getElementById('blockTip'), rs=document.getElementById('rstage'), ts=document.getElementById('stage'), rr=document.getElementById('railRegion'), rt=document.getElementById('railTac');
let tipT; NF.tip=t=>{ tipEl.textContent=t; tipEl.classList.add('on'); clearTimeout(tipT); tipT=setTimeout(()=>tipEl.classList.remove('on'),2800); };
const swap=fn=>{ fade.classList.add('on'); setTimeout(()=>{ fn(); requestAnimationFrame(()=>requestAnimationFrame(()=>fade.classList.remove('on'))); },300); };
NF.enterTactical=(x,z,sq)=>{ if(NF.mode!=='region') return; if(!NF.tacEnter){ NF.tip('The tactical data is still loading'); return; }
  const [bx,bz]=NF.regionToBlock(x,z), s=sq?{...sq,...(([qx,qz])=>({x:qx,z:qz}))(NF.regionToBlock(sq.x,sq.z))}:null;
  if(!s) NF.tip('No squad is in this block: you can look around, but send a squad here on the map to walk it');
  swap(()=>{ NF.mode='tactical'; NF.tacT0=performance.now(); rs.hidden=true; rr.hidden=true; ts.hidden=false; rt.hidden=false; NF.tacEnter(s?s.x:bx, s?s.z:bz, s); }); };
NF.exitTactical=()=>{ if(NF.mode!=='tactical') return; if(NF.tacBusy&&NF.tacBusy()){ NF.tip('Finish the fight before leaving the ground'); return; } const st=NF.tacState();
  swap(()=>{ NF.mode='region'; ts.hidden=true; rt.hidden=true; rs.hidden=false; rr.hidden=false; window.__region.resize();
    if(st.squad){ const [x,z]=NF.blockToRegion(st.squad.x,st.squad.z); window.__region.placeSquad(st.squad.index,x,z,st.squad.people); }
    const [rx,rz]=NF.blockToRegion(st.x,st.z); if(st.pose&&window.__region.takePose) window.__region.takePose({...st.pose,x:rx,z:rz}); else window.__region.focus(rx,rz);   // the map starts where the ground's camera left off
    // on the zoom page the campaign runs live while on the ground, so tacSeconds is 0 and only fight turns are owed
    window.__region.back(NF.tacSeconds?NF.tacSeconds():(performance.now()-NF.tacT0)/1000, NF.tacResult?NF.tacResult():undefined);
    if(NF.afterExit){ const f=NF.afterExit; NF.afterExit=null; f(); } }); };   // an order that reaches past the ground goes on as a map order
document.getElementById('upBtn').onclick=()=>NF.exitTactical();
})();
