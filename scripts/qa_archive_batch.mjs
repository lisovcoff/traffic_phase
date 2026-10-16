// Local technical QA only. One batch of three pre-existing fixed synthetic
// sessions, unchanged V9 defaults; not an accuracy/recovery experiment.
import fs from 'node:fs/promises';
import path from 'node:path';
const out=path.resolve('evidence/bounded_archive_batch_20261016');
const saved=process.argv.includes('--saved'),prefix=saved?'layout_':'';
const tabs=await(await fetch('http://127.0.0.1:9241/json/list')).json();
const socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});
let counter=0;const pending=new Map(),errors=[],responses=[];
socket.onmessage=e=>{const r=JSON.parse(e.data);if(r.id){const p=pending.get(r.id);pending.delete(r.id);if(r.error)p.reject(Error(JSON.stringify(r.error)));else p.resolve(r.result);}
else if(r.method==='Runtime.exceptionThrown')errors.push(r.params.exceptionDetails);
else if(r.method==='Network.responseReceived'&&r.params.response.url.endsWith('/visualization/batch'))responses.push({status:r.params.response.status,headers:r.params.response.headers});};
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}));});
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function until(expression,timeout=210000){const start=Date.now();while(Date.now()-start<timeout){const r=await evaluate(expression);if(r)return r;await new Promise(r=>setTimeout(r,200));}throw Error('QA timeout: '+expression);}
async function screenshot(name){const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await fs.writeFile(path.join(out,prefix+name),Buffer.from(r.data,'base64'));}
const report={errors,responses,technical_only:true,real_replays:0,hyperparameter_search:false,saved_prediction_replay:saved,ordinary_batch_submissions:saved?0:1};
try{
 await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
 await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
 await send('Page.navigate',{url:'http://127.0.0.1:8021/visualization/batch'});
 await until("document.querySelector('#batch-file')&&document.readyState==='complete'");
 const doc=await send('DOM.getDocument'),input=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#batch-file'});
 await send('DOM.setFileInputFiles',{nodeId:input.nodeId,files:[path.resolve('evidence/archive_session_isolation_20261016/two_sources.zip')]});
 const started=Date.now();
 await evaluate("document.querySelector('#batch-submit').click()");
 const status=await until("(()=>{const s=document.querySelector('#batch-status').textContent;return s.startsWith('Готово')||s.startsWith('Ошибка')?s:false})()");
 if(!status.startsWith('Готово'))throw Error(status);
 report.upload_to_ready_s=(Date.now()-started)/1000;
 await until("document.querySelector('#batch-viewer').contentDocument.querySelectorAll('[data-report]').length===3");
 report.summary=await evaluate("document.querySelector('#batch-viewer').contentDocument.body.innerText");
 report.session_reports=[];
 for(let i=0;i<3;i++){
  await evaluate(`document.querySelector('#batch-viewer').contentDocument.querySelectorAll('[data-report]')[${i}].click()`);
  await until("document.querySelector('#batch-viewer').contentDocument.querySelector('#batch-report').contentDocument.querySelector('#phaseCount')?.textContent==='2'");
  report.session_reports.push(await evaluate("(()=>{const w=document.querySelector('#batch-viewer').contentDocument.querySelector('#batch-report').contentWindow;return {K:w.document.querySelector('#phaseCount').textContent,scope:w.document.querySelector('#inputScope').textContent,period:w.document.querySelector('#period').textContent,lamp:w.document.querySelector('#lampState').textContent,queries:[-1,0,10,80,Number(w.document.querySelector('#slider').max)].map(t=>({t,state:w.stateAt(t)})),physical:w.eval('PRODUCT.physical_section')}})()"));
 }
 if(report.session_reports.some(r=>r.lamp!=='UNKNOWN'||r.K!=='2'||r.physical.calibrated_lamp_probability!==null))throw Error('Wrong query/physical semantics');
 await fs.writeFile(path.join(out,prefix+'aggregate.html'),await evaluate("document.querySelector('#batch-viewer').contentDocument.documentElement.outerHTML"));
 await screenshot('desktop.png');
 report.desktop_overflow=await evaluate("document.documentElement.scrollWidth>document.documentElement.clientWidth");
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
 report.mobile_widths=await evaluate("(()=>{const a=document.documentElement,b=document.querySelector('#batch-viewer').contentDocument.documentElement,c=document.querySelector('#batch-viewer').contentDocument.querySelector('#batch-report').contentDocument.documentElement;return [a,b,c].map(d=>({client:d.clientWidth,scroll:d.scrollWidth}))})()");
 if(saved){
  await until("(()=>{const f=document.querySelector('#batch-viewer'),g=f.contentDocument.querySelector('#batch-report');return f.clientHeight>f.contentDocument.body.getBoundingClientRect().height&&g.clientHeight>g.contentDocument.body.getBoundingClientRect().height})()");
  await evaluate("document.querySelector('#batch-viewer').contentDocument.querySelector('#batch-report').scrollIntoView({block:'start'})");
  await new Promise(r=>setTimeout(r,300));
 }
 await screenshot('mobile.png');
 if(report.desktop_overflow||report.mobile_widths.some(r=>r.scroll>r.client))throw Error('Horizontal overflow');
 const download=await evaluate("(async()=>{const href=document.querySelector('#batch-download').href,r=await fetch(href),bytes=new Uint8Array(await r.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=20000)binary+=String.fromCharCode(...bytes.subarray(i,i+20000));return {href,status:r.status,base64:btoa(binary)}})()");
 if(download.status!==200)throw Error('Download unavailable');
 await fs.writeFile(path.join(out,prefix+'download.zip'),Buffer.from(download.base64,'base64'));
 report.download={href:download.href,status:download.status,bytes:Buffer.from(download.base64,'base64').length};
 await evaluate("document.querySelector('#batch-file').dispatchEvent(new Event('change',{bubbles:true}))");
 report.stale_result_hidden=await evaluate("document.querySelector('#batch-viewer').hidden&&document.querySelector('#batch-viewer').srcdoc===''&&document.querySelector('#batch-download').hidden");
 if(!report.stale_result_hidden||errors.length)throw Error('Stale result or browser errors');
 report.status='PASS';console.log(JSON.stringify({status:report.status,runtime_s:report.upload_to_ready_s,reports:report.session_reports.length,download_bytes:report.download.bytes}));
}catch(error){report.status='FAIL';report.failure=String(error.stack||error);throw error;}
finally{await fs.writeFile(path.join(out,prefix+'browser_results.json'),JSON.stringify(report,null,2));await send('Browser.close').catch(()=>{});socket.close();}
