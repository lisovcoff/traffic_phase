// Read-only browser review of saved outputs. No uploads or inference.
import fs from 'node:fs/promises';import path from 'node:path';
const folder=path.resolve('evidence/web_archive_qa_20261016');
const cases=JSON.parse(await fs.readFile(path.join(folder,'browser_expectations.json'),'utf8'));
const tabs=await(await fetch('http://127.0.0.1:9237/json/list')).json();
const ws=new WebSocket(tabs.find(t=>t.type==='page').webSocketDebuggerUrl);
await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j});
let id=0;const pending=new Map(),errors=[];
ws.onmessage=e=>{const x=JSON.parse(e.data);if(x.id){const p=pending.get(x.id);pending.delete(x.id);x.error?p.j(Error(JSON.stringify(x.error))):p.r(x.result)}else if(x.method==='Runtime.exceptionThrown')errors.push(x.params.exceptionDetails)};
const send=(method,params={})=>new Promise((r,j)=>{const n=++id;pending.set(n,{r,j});ws.send(JSON.stringify({id:n,method,params}))});
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function ready(expression){for(let i=0;i<80;i++){if(await evaluate(expression))return;await new Promise(r=>setTimeout(r,100))}throw Error('page readiness timeout')}
await send('Page.enable');await send('Runtime.enable');
const results=[];
try{
 for(const test of cases){
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1200,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:test.url});await ready('window.__V10_DEBUG__');
  const answers=await evaluate(`(${JSON.stringify(test.points)}).map(p=>({t:p.t,snapshot:signalSnapshot(p.t)}))`);
  for(let i=0;i<answers.length;i++){
   if(answers[i].snapshot.phaseName!==test.points[i].expected)throw Error('Python/browser phase mismatch '+test.name+' '+test.points[i].t);
   if(Object.values(answers[i].snapshot.heads).some(h=>h.main.state!=='UNKNOWN'||h.arrows.length))throw Error('Fabricated hardware');
  }
  await evaluate("setCurrentTime(Math.min(120,Number(document.querySelector('#slider').max)))");
  const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  await fs.writeFile(path.join(folder,test.name+'_desktop.png'),Buffer.from(shot.data,'base64'));
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate('resizeCanvas();render()');
  const dimensions=await evaluate('({width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth,error:document.querySelector("#error").textContent})');
  if(dimensions.error||dimensions.scroll>dimensions.width+2)throw Error('Mobile overflow/error: '+JSON.stringify(dimensions));
  const mobile=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  await fs.writeFile(path.join(folder,test.name+'_mobile.png'),Buffer.from(mobile.data,'base64'));
  results.push({name:test.name,checked_queries:answers.length,all_queries_match_common_contract:true,dimensions,
   displayed:await evaluate('window.__V10_DEBUG__')});
  console.log(test.name,answers.length,'queries match; desktop/mobile rendered');
 }
 await send('Page.navigate',{url:'http://127.0.0.1:8017/qa/offline_product_html_20261016/6_2025_2_14_20_v9.html'});
 await ready('document.querySelector("#phaseTitle")?.textContent.includes("Логическая фаза")');
 const offline=await evaluate('(()=>{setCurrent(100000);return {phase:document.querySelector("#phaseTitle").textContent,lamp:document.querySelector("#lampState").textContent}})()');
 if(!offline.phase.includes('UNKNOWN')||offline.lamp!=='UNKNOWN')throw Error('Offline out-of-range failed');
 results.push({name:'previous_offline_report',out_of_range:offline});
 if(errors.length)throw Error('Browser exceptions');
}finally{
 await fs.writeFile(path.join(folder,'saved_browser_results.json'),JSON.stringify({results,errors},null,2));
 await send('Browser.close').catch(()=>{});ws.close();
}
