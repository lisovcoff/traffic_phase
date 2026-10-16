// Isolated headless Edge fallback after Browser runtime reported no browsers.
// One ordinary V9 synthetic fit only; never retry/tune to obtain a desired K.
import fs from 'node:fs/promises';
import path from 'node:path';
const out=path.resolve('evidence/archive_session_isolation_20261016');
const saved=process.argv.includes('--saved'),prefix=saved?'layout_':'';
const tabs=await (await fetch('http://127.0.0.1:9239/json/list')).json();
const socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
let counter=0;const pending=new Map(),errors=[],responses=[];
socket.onmessage=e=>{const r=JSON.parse(e.data);if(r.id){const p=pending.get(r.id);pending.delete(r.id);if(r.error)p.reject(Error(JSON.stringify(r.error)));else p.resolve(r.result);}
else if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails);
else if(r.method==='Network.responseReceived'&&r.params.response.url.endsWith('/visualization/analyze'))responses.push({status:r.params.response.status,headers:r.params.response.headers});};
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function until(expression,timeout=180000){const start=Date.now();while(Date.now()-start<timeout){const value=await evaluate(expression);if(value)return value;await new Promise(r=>setTimeout(r,200));}throw Error('QA timeout: '+expression);}
async function screenshot(name){const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await fs.writeFile(path.join(out,prefix+name),Buffer.from(r.data,'base64'));}
const report={responses,errors,ordinary_discovery_submissions:0,saved_prediction_replays:0};
try{
 await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:'http://127.0.0.1:8019/visualization'});
 await until("document.querySelector('#file')&&document.readyState==='complete'");
 const doc=await send('DOM.getDocument'),input=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#file'});
 await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.join(out,'two_sources.zip')]});
 await evaluate("document.querySelector('#submit').click()");
 await until("!document.querySelector('#source-choice').hidden&&!document.querySelector('#submit').disabled");
 report.source_choices=await evaluate("Array.from(document.querySelector('#source-member').options,o=>({value:o.value,text:o.textContent}))");
 if(report.source_choices.length!==3)throw Error('Expected placeholder and two sources');
 await screenshot('source_choices.png');
 await evaluate("(()=>{const s=document.querySelector('#source-member');s.value='b.json';s.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#submit').click()})()");
 await until("!document.querySelector('#session-choice').hidden&&!document.querySelector('#submit').disabled");
 report.session_choices=await evaluate("Array.from(document.querySelector('#session-id').options,o=>({value:o.value,text:o.textContent}))");
 if(report.session_choices.length!==3)throw Error('Expected placeholder and two sessions');
 await screenshot('session_choices.png');
 if(saved)report.saved_prediction_replays++;else report.ordinary_discovery_submissions++;
 const started=Date.now();
 await evaluate("(()=>{const s=document.querySelector('#session-id');s.selectedIndex=2;s.dispatchEvent(new Event('change',{bubbles:true}));document.querySelector('#submit').click()})()");
 const status=await until("(()=>{const s=document.querySelector('#status').textContent;return s.startsWith('Готово')||s.startsWith('Ошибка')?s:false})()");
 if(!status.startsWith('Готово'))throw Error(status);
 await until("document.querySelector('#viewer').contentWindow.__V10_DEBUG__");
 report.upload_to_ready_s=(Date.now()-started)/1000;
 report.prediction=await evaluate("document.querySelector('#viewer').contentWindow.eval('RESULT')");
 if(report.prediction.input_scope.source_member!=='b.json'||report.prediction.input_scope.selected_session.session_number!==2)throw Error('Wrong selected scope');
 if(report.prediction.trajectory_count!==40)throw Error('Unselected tracks entered model');
 await fs.writeFile(path.join(out,prefix+'selected_prediction.json'),JSON.stringify(report.prediction,null,2));
 report.scope_banner=await evaluate("document.querySelector('#viewer').contentDocument.querySelector('#input-scope').textContent");
 report.frame_error=await evaluate("document.querySelector('#viewer').contentDocument.querySelector('#error').textContent");
 if(report.frame_error)throw Error(report.frame_error);
 report.queries=await evaluate("(()=>{const w=document.querySelector('#viewer').contentWindow,max=Number(w.document.querySelector('#slider').max);return [-1,0,10,max/2,max,max+1].map(t=>({t,snapshot:w.signalSnapshot(t)}))})()");
 if(report.queries.some(q=>Object.values(q.snapshot.heads).some(h=>h.main.state!=='UNKNOWN'||h.arrows.length)))throw Error('Unverified lamps published');
 await fs.writeFile(path.join(out,prefix+'selected_report.html'),await evaluate("document.querySelector('#viewer').contentDocument.documentElement.outerHTML"));
 await screenshot('selected_desktop.png');
 report.desktop_overflow=await evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 await screenshot('selected_mobile.png');
 report.mobile_overflow=await evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth");
 report.mobile_inner_overflow=await evaluate("(()=>{const d=document.querySelector('#viewer').contentDocument;return d.documentElement.scrollWidth>d.documentElement.clientWidth})()");
 report.mobile_widths=await evaluate("({client:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})");
 if(report.desktop_overflow||report.mobile_overflow||report.mobile_inner_overflow)throw Error('Horizontal overflow');
 await evaluate("(()=>{const s=document.querySelector('#session-id');s.selectedIndex=1;s.dispatchEvent(new Event('change',{bubbles:true}))})()");
 report.stale_result_hidden=await evaluate("document.querySelector('#viewer').style.display==='none'&&document.querySelector('#viewer').srcdoc===''");
 if(!report.stale_result_hidden)throw Error('Old session result remains visible');
 if(JSON.stringify(responses.map(r=>r.status))!=='[409,409,200]')throw Error('Unexpected HTTP sequence');
 if(errors.length)throw Error('Browser exceptions');
 delete report.prediction; report.status='PASS';
 console.log(JSON.stringify({status:report.status,responses:responses.map(r=>r.status),runtime_s:report.upload_to_ready_s,queries:report.queries.length}));
}catch(error){report.status='FAIL';report.failure=String(error.stack||error);throw error;}
finally{
 delete report.prediction;
 await fs.writeFile(path.join(out,prefix+'browser_results.json'),JSON.stringify(report,null,2));
 await send('Browser.close').catch(()=>{});socket.close();
}
