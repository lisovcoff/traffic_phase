// Smoke test in our dedicated Chrome profile; exported UI_TEST marks are not calibration.
import fs from 'node:fs';
import path from 'node:path';
const root=process.cwd(),port=9229,base='http://127.0.0.1:8011/annotation';
const out=path.join(root,'evidence/video_calibration_pilot_20261015');
const manifest=JSON.parse(fs.readFileSync(path.join(out,'trajectory_sample/sample_manifest.json'),'utf8'));
const sample=path.join(out,'trajectory_sample/calibration_tracks.json');
const video='C:\\Users\\sheld\\Downloads\\len_sverdl 2025-02-27T10_00_00_2025-02-27T12_00_00.mp4';
const downloads=path.join(root,'.annotation_runtime/calibration_media/downloads',String(Date.now()));fs.mkdirSync(downloads,{recursive:true});
const target=await(await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(base)}`,{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
let serial=0;const pending=new Map(),errors=[];
ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);};
function call(method,params={}){return new Promise((resolve,reject)=>{const id=++serial,timer=setTimeout(()=>reject(Error('timeout '+method)),20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await sleep(100);}throw Error('UI wait failed: '+expression);}
async function file(selector,name){const d=await call('DOM.getDocument'),n=await call('DOM.querySelector',{nodeId:d.root.nodeId,selector});await call('DOM.setFileInputFiles',{nodeId:n.nodeId,files:[name]});}
const assert=(value,message)=>{if(!value)throw Error(message);};
const checks=[];
try{
 await call('Runtime.enable');await call('Page.enable');await call('Network.enable');await call('Network.setCacheDisabled',{cacheDisabled:true});await call('Page.reload',{ignoreCache:true});await call('Page.bringToFront');
 await call('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
 await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
 await wait("document.getElementById('videoNow')!==null");
 await evaluate(`localStorage.removeItem('traffic-phase-review:${manifest.sample.sha256}')`);
 await file('#trajectoryFile',sample);
 await evaluate(`document.getElementById('windowStart').value=${manifest.recommended_preview_start_s};document.getElementById('windowDuration').value=180;document.getElementById('reviewer').value='UI_TEST_ONLY';document.getElementById('open').click();`);
 await wait("document.getElementById('sourceInfo').textContent.includes('calibration_tracks.json')");
 checks.push('Continuous sample loaded with fractional window start; no inference');
 await evaluate("document.getElementById('videoFile').closest('details').open=true");
 await file('#videoFile',video);await wait("document.getElementById('video').readyState>=2");
 await evaluate("document.getElementById('video').currentTime=275.067");
 await wait("Math.abs(document.getElementById('video').currentTime-275.067)<.001 && document.getElementById('video').readyState>=2");
 await evaluate("document.getElementById('videoNow').click()");
 assert(await evaluate("document.getElementById('videoAnchor').value==='275.067'"),'copy video cursor');
 checks.push('Local 3GB video opened without upload; exact requested media cursor copied');
 await evaluate("document.getElementById('videoForward').click()");
 await wait("Math.abs(document.getElementById('video').currentTime-275.167)<.002");
 await evaluate("document.getElementById('videoBack').click()");
 await wait("Math.abs(document.getElementById('video').currentTime-275.067)<.002 && document.getElementById('video').readyState>=2");
 checks.push('Video +/-0.1s seeks');
 async function roi(x,y){await evaluate(`(()=>{document.getElementById('chooseVideoRoi').click();const v=document.getElementById('video'),r=v.getBoundingClientRect(),scale=Math.min(r.width/v.videoWidth,r.height/v.videoHeight),ox=(r.width-v.videoWidth*scale)/2,oy=(r.height-v.videoHeight*scale)/2;v.dispatchEvent(new MouseEvent('click',{bubbles:true,clientX:r.left+ox+v.videoWidth*scale*${x},clientY:r.top+oy+v.videoHeight*scale*${y}}));})()`);}
 await roi(.756,.61);await wait("!document.getElementById('videoZoom').hidden");
 const bad=await evaluate("document.body.textContent.includes('?????')");assert(!bad,'Cyrillic UI labels corrupted');
 checks.push('Intrinsic-pixel ROI magnifier rendered; Cyrillic controls intact');
 await evaluate("document.getElementById('videoZoom').scrollIntoView({block:'center'})");
 const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
 fs.writeFileSync(path.join(out,'calibration_ui.png'),Buffer.from(screenshot.data,'base64'));
 await evaluate("document.getElementById('track').selectedIndex=1;document.getElementById('track').dispatchEvent(new Event('change'));document.getElementById('sourceKind').value='video_review';document.getElementById('label').value='UI_TEST_ANCHOR_1';document.getElementById('note').value='UI TEST ONLY, NOT CALIBRATION';document.getElementById('alignVideo').click();document.getElementById('add').click();");
 await wait("document.getElementById('count').textContent==='1'");
 await roi(.5,.5);
 await evaluate("document.getElementById('label').value='UI_TEST_ANCHOR_2';document.getElementById('add').click();");
 await wait("document.getElementById('count').textContent==='2'");
 await evaluate("document.getElementById('export').click()");
 const exported=path.join(downloads,'calibration_tracks_review.json');for(let i=0;i<100&&!fs.existsSync(exported);i++)await sleep(100);
 const review=JSON.parse(fs.readFileSync(exported,'utf8'));
 const [a,b]=review.annotations.map(m=>m.evidence_source.synchronization.video_binding);
 assert(a.video_seconds===275.067&&b.video_seconds===275.067,'media binding time');
 assert(a.video_roi_px.x!==b.video_roi_px.x,'ROI snapshots must not mutate prior marks');
 assert(review.independent_truth_certified===false&&review.annotations.every(m=>m.independently_verified===false),'no fake verification');
 assert(review.source.sha256===manifest.sample.sha256,'sample identity');
 checks.push('Export keeps media cursor, distinct immutable ROI snapshots and unverified source provenance');
 assert(errors.length===0,'Browser exceptions: '+errors.join(';'));
 fs.writeFileSync(path.join(out,'ui_checks.json'),JSON.stringify({checks,console_exceptions:errors,
  test_marks_role:'UI_TEST_ONLY, not calibration or signal truth',raw_video_uploaded:false},null,2)+'\n');
 console.log(JSON.stringify(checks,null,2));
}finally{await call('Page.close').catch(()=>{});ws.close();}
