// Standalone local Chrome/CDP smoke test. Dedicated test profile, no user profile.
import fs from 'node:fs';
import path from 'node:path';
const root=process.cwd(),out=path.join(root,'evidence/annotation_step1_20261015');
const downloads=path.join(root,'.annotation_runtime/downloads',String(Date.now()));fs.mkdirSync(downloads,{recursive:true});
const tab=await (await fetch('http://127.0.0.1:9225/json/new?http://127.0.0.1:8011/annotation',{method:'PUT'})).json();
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
let serial=0;const pending=new Map(),errors=[];
ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails.text);};
function call(method,params={}){return new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function wait(expression){for(let i=0;i<100;i++){if(await evaluate(expression))return;await sleep(100);}throw Error('UI wait failed: '+expression);}
async function file(selector,filename){const d=await call('DOM.getDocument');const n=await call('DOM.querySelector',{nodeId:d.root.nodeId,selector});await call('DOM.setFileInputFiles',{nodeId:n.nodeId,files:[filename]});}
function assert(ok,message){if(!ok)throw Error(message);}
const checks=[];
try{
 await call('Runtime.enable');await call('Page.enable');await call('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
 await call('Browser.setDownloadBehavior',{behavior:'allow',downloadPath:downloads});
 await wait("document.querySelector('#demo') !== null");
 await evaluate("localStorage.clear()"); // This dedicated test browser has no user data.
 await evaluate("document.getElementById('demo').click()");await wait("document.getElementById('loadStatus').textContent.includes('синтетическая')");
 checks.push('Demo loaded and trajectories rendered');
 await evaluate(`document.getElementById('reviewer').value='UI_TEST';document.getElementById('reviewer').dispatchEvent(new Event('change'));document.getElementById('track').selectedIndex=1;document.getElementById('track').dispatchEvent(new Event('change'));document.getElementById('position').value='8';document.getElementById('position').dispatchEvent(new Event('change'));document.getElementById('startSec').value='2';document.getElementById('endSec').value='3';document.getElementById('uncertainty').value='200';document.getElementById('add').click();`);
 await wait("document.getElementById('count').textContent==='1'");checks.push('Vehicle selection, seek, interval annotation persisted');
 const screenshot=await call('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(out,'workbench.png'),Buffer.from(screenshot.data,'base64'));
 await evaluate("document.getElementById('export').click()");
 const exported=path.join(downloads,'SYNTHETIC_DEMO_review.json');for(let i=0;i<100&&!fs.existsSync(exported);i++)await sleep(100);
 const p=JSON.parse(fs.readFileSync(exported,'utf8'));assert(p.annotations.length===1,'download mark count');assert(p.annotations[0].interpretation==='trajectory_based_hypothesis','no fake independent truth');assert(p.annotations[0].interval_end_ms-p.annotations[0].interval_start_ms===1000,'interval milliseconds');checks.push('Browser download JSON verified');
 await file('#importFile',exported);await evaluate("document.getElementById('import').click()");await wait("document.getElementById('saveStatus').textContent==='Разметка открыта.'");checks.push('Export/import round trip');
 const wrong=path.join(downloads,'wrong_hash.json');p.source.sha256='f'.repeat(64);fs.writeFileSync(wrong,JSON.stringify(p));await file('#importFile',wrong);await evaluate("document.getElementById('import').click()");await wait("document.getElementById('saveStatus').textContent.includes('SHA256 не совпадает')");checks.push('Mismatched source hash rejected');
 await evaluate("document.getElementById('kind').value='signal_observation';document.getElementById('label').value='GREEN';document.getElementById('add').click()");await wait("document.getElementById('markStatus').textContent.includes('Цвет лампы')");checks.push('Trajectory-only lamp observation blocked');
 await call('Page.reload');await wait("document.querySelector('#demo') !== null");await evaluate("document.getElementById('demo').click()");await wait("document.getElementById('count').textContent==='1'");checks.push('Draft recovered after reload');
 const sample=path.join(root,'.annotation_runtime/real_20_tracks.json');
 if(fs.existsSync(sample)){await file('#trajectoryFile',sample);await evaluate("document.getElementById('open').click()");await wait("document.getElementById('sourceInfo').textContent.includes('real_20_tracks.json')");checks.push('Real 20-track source fragment uploaded, no inference');const s=await call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'real_fragment.png'),Buffer.from(s.data,'base64'));}
 assert(errors.length===0,'browser JS errors: '+errors.join(';'));
 const result={checks,console_exceptions:errors,uses_dedicated_profile:true,new_phase_fitting:false};fs.writeFileSync(path.join(out,'ui_checks.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}finally{ws.close();}
