// Standalone isolated Edge QA fallback: bundled browser runtime cannot start.
// No user's browser/profile/session is attached. No extra dependencies.
import fs from 'node:fs/promises';
import path from 'node:path';
const out=path.resolve('evidence/web_archive_qa_20261016');
const tabs=await (await fetch('http://127.0.0.1:9237/json/list')).json();
const socket=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
let counter=0;const pending=new Map(),errors=[];
socket.onmessage=e=>{const x=JSON.parse(e.data);if(x.id){const p=pending.get(x.id);pending.delete(x.id);if(x.error)p.reject(Error(JSON.stringify(x.error)));else p.resolve(x.result)}
 else if(x.method==='Runtime.exceptionThrown')errors.push(x.params.exceptionDetails);};
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++counter;pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))})}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function until(expression,timeout=120000){const start=Date.now();while(Date.now()-start<timeout){const value=await evaluate(expression);if(value)return value;await new Promise(r=>setTimeout(r,250));}throw Error('QA timeout: '+expression)}
async function screenshot(name){const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});await fs.writeFile(path.join(out,name),Buffer.from(r.data,'base64'));}
await send('Page.enable');await send('Runtime.enable');
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1100,deviceScaleFactor:1,mobile:false});
const args=process.argv.slice(2),resume=args.includes('--resume');
const names=args.filter(x=>x!=='--resume');
const previous=resume?JSON.parse(await fs.readFile(path.join(out,'browser_results.json'),'utf8')):{runs:[]};
const runs=previous.runs;
try{
 for(const name of (names.length?names:['synthetic.zip','real_sample.zip','corrupt.zip'])){
  await send('Page.navigate',{url:'http://127.0.0.1:8017/visualization'});
  await until("document.querySelector('#file') && document.readyState==='complete'");
  const doc=await send('DOM.getDocument');const element=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:'#file'});
  await send('DOM.setFileInputFiles',{nodeId:element.nodeId,files:[path.join(out,name)]});
  const start=Date.now();await evaluate("document.querySelector('#submit').click()");
  const status=await until("(()=>{const s=document.querySelector('#status').textContent;return s.startsWith('Готово')||s.startsWith('Ошибка')?s:false})()");
  const row={input:name,status,wall_s:(Date.now()-start)/1000};
  if(name==='corrupt.zip'){
   if(!status.startsWith('Ошибка')||status.includes('Internal Server Error'))throw Error('Corrupt ZIP not handled cleanly: '+status);
  }else{
   if(!status.startsWith('Готово'))throw Error('Upload failed: '+status);
   await until("document.querySelector('#viewer').contentWindow.__V10_DEBUG__");
   row.initial=await evaluate("document.querySelector('#viewer').contentWindow.__V10_DEBUG__");
   row.pageError=await evaluate("document.querySelector('#viewer').contentDocument.querySelector('#error').textContent");
   if(row.pageError)throw Error(row.pageError);
   row.queries=await evaluate(`(()=>{const w=document.querySelector('#viewer').contentWindow;
    const max=Number(w.document.querySelector('#slider').max);
    return [-1,0,10,max/2,max,max+1].map(t=>({t,snapshot:w.signalSnapshot(t)}));})()`);
   if(row.queries.some(q=>Object.values(q.snapshot.heads).some(h=>h.main.state!=='UNKNOWN'||h.arrows.length)))throw Error('Fabricated lamp/hardware');
   await evaluate("(()=>{const w=document.querySelector('#viewer').contentWindow;w.setCurrentTime(10);w.document.querySelector('#play').click()})()");
   await new Promise(r=>setTimeout(r,450));
   await evaluate("document.querySelector('#viewer').contentWindow.document.querySelector('#pause').click()");
   row.afterPlayback=await evaluate("document.querySelector('#viewer').contentWindow.__V10_DEBUG__");
   if(row.afterPlayback.current_time_s<=10)throw Error('Playback did not advance');
   await evaluate("document.querySelector('#viewer').contentWindow.document.querySelector('#reset').click()");
   await screenshot(name+'.png');
  }
  runs.push(row);await fs.writeFile(path.join(out,'browser_results.json'),JSON.stringify({runs,errors},null,2));
  console.log(name,status,row.wall_s);
 }
 if(errors.length)throw Error('Browser exceptions: '+JSON.stringify(errors));
}finally{
 await fs.writeFile(path.join(out,'browser_results.json'),JSON.stringify({runs,errors},null,2));
 await send('Browser.close').catch(()=>{});socket.close();
}
