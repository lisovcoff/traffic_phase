// Bounded local-file sampling in our own headless Chrome profile, no user sessions.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import http from 'node:http';
const args=Object.fromEntries(process.argv.slice(2).reduce((rows,x,i,a)=>i%2===0?[...rows,[x,a[i+1]]]:rows,[]));
const video=path.resolve(args['--video']),out=path.resolve(args['--out']),port=Number(args['--port']||9229);
const sampleTimes=args['--times']?args['--times'].split(',').map(Number):[0,30,60,180,1800,3600,5400,7190];
const frameLimit=Number(args['--max-frames']||16);
if(!Number.isInteger(frameLimit)||frameLimit<1||frameLimit>128)throw Error('Explicit frame limit must be 1..128');
if(!sampleTimes.length||sampleTimes.length>frameLimit||sampleTimes.some(t=>!Number.isFinite(t)||t<0))throw Error('Finite nonnegative frame times within declared limit required');
const roi=args['--roi']?args['--roi'].split(',').map(Number):null;
if(roi&&(roi.length!==4||roi.some(x=>!Number.isInteger(x))||roi[0]<0||roi[1]<0||roi[2]<=0||roi[3]<=0))throw Error('ROI requires integer x,y,width,height');
if(fs.existsSync(out))throw Error('Fresh output directory required');
if(!fs.statSync(video).isFile())throw Error('Video file required');
fs.mkdirSync(out,{recursive:true});
const page=path.join(out,'frame_inspector.html');
fs.writeFileSync(page,'<!doctype html><meta charset="utf-8"><title>Local calibration frame inspection</title><video id="v" muted preload="metadata"></video><canvas id="c"></canvas>');
let mediaBytes=0;
const size=fs.statSync(video).size;
const server=http.createServer((req,res)=>{
 if(req.url==='/'){res.writeHead(200,{'Content-Type':'text/html'});res.end(fs.readFileSync(page));return;}
 if(req.url!=='/video'){res.writeHead(404);res.end();return;}
 const match=/^bytes=(\d+)-(\d*)$/.exec(req.headers.range||'');
 if(req.headers.range&&!match){res.writeHead(416,{'Content-Range':`bytes */${size}`});res.end();return;}
 const start=match?Number(match[1]):0,end=match&&match[2]?Math.min(Number(match[2]),size-1):size-1;
 if(start>end||start>=size){res.writeHead(416,{'Content-Range':`bytes */${size}`});res.end();return;}
 res.writeHead(match?206:200,{'Content-Type':'video/mp4','Accept-Ranges':'bytes','Content-Length':end-start+1,...(match?{'Content-Range':`bytes ${start}-${end}/${size}`}:{})});
 if(req.method==='HEAD'){res.end();return;}
 const stream=fs.createReadStream(video,{start,end,highWaterMark:65536});
 stream.on('data',b=>{mediaBytes+=b.length;if(mediaBytes>128*1024*1024){stream.destroy();res.destroy(Error('128MiB media read budget exceeded'));}});
 stream.on('error',()=>res.destroy());res.on('close',()=>stream.destroy());stream.pipe(res);
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
const localUrl=`http://127.0.0.1:${server.address().port}/`;
const target=await(await fetch(`http://127.0.0.1:${port}/json/new?${encodeURIComponent(localUrl)}`,{method:'PUT'})).json();
const ws=new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
let serial=0;const pending=new Map();
ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);clearTimeout(p.timer);m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}};
function call(method,params={}){return new Promise((resolve,reject)=>{const id=++serial;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},20000);pending.set(id,{resolve,reject,timer});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
const start=Date.now();const frames=[];
try{
 await call('Runtime.enable');await call('Page.enable');await call('Page.bringToFront');
 await call('Emulation.setDeviceMetricsOverride',{width:1400,height:1000,deviceScaleFactor:1,mobile:false});
 const metadata=await evaluate(`new Promise((resolve,reject)=>{const v=document.getElementById('v');v.onerror=()=>reject(Error('Video error '+v.error?.code));v.onloadedmetadata=()=>resolve({duration_s:v.duration,width:v.videoWidth,height:v.videoHeight,can_play_h264:v.canPlayType('video/mp4; codecs="avc1.640033"')});v.src='/video';})`);
 fs.writeFileSync(path.join(out,'probe.json'),JSON.stringify(metadata,null,2));console.log('Media metadata:',metadata);
 if(roi&&(roi[0]+roi[2]>metadata.width||roi[1]+roi[3]>metadata.height))throw Error('ROI outside video');
 for(const requested of sampleTimes){
  if(requested>=metadata.duration_s)throw Error('Frame time exceeds media duration');
  if(Date.now()-start>90000)throw Error('90s sampling budget exceeded');
  const draw=roi?`c.width=${roi[2]};c.height=${roi[3]};c.getContext('2d').drawImage(v,${roi.join(',')},0,0,c.width,c.height)`:`c.width=v.videoWidth;c.height=v.videoHeight;c.getContext('2d').drawImage(v,0,0)`;
  const sample=await evaluate(`new Promise((resolve,reject)=>{const v=document.getElementById('v'),c=document.getElementById('c');const timer=setTimeout(()=>reject(Error('Frame timeout')),10000);v.pause();v.onseeked=()=>{v.onseeked=null;v.requestVideoFrameCallback((now,m)=>{try{v.pause();${draw};window.__calibrationFrame=c.toDataURL(${roi?"'image/png'":"'image/jpeg',.95"});clearTimeout(timer);resolve({actual_media_time_s:m.mediaTime,width:m.width,height:m.height,data_length:window.__calibrationFrame.length});}catch(e){clearTimeout(timer);reject(e);}});v.play().catch(reject);};v.currentTime=${requested===0?0.000001:requested};})`);
  let data='';for(let offset=0;offset<sample.data_length;offset+=262144)data+=await evaluate(`window.__calibrationFrame.slice(${offset},${offset+262144})`);
  const name=`frame_${String(requested).padStart(5,'0')}.${roi?'png':'jpg'}`,bytes=Buffer.from(data.split(',')[1],'base64');
  fs.writeFileSync(path.join(out,name),bytes);
  frames.push({requested_elapsed_s:requested,actual_media_time_s:sample.actual_media_time_s,file:name,
    sha256:crypto.createHash('sha256').update(bytes).digest('hex'),width:sample.width,height:sample.height,roi_intrinsic_px:roi});
 }
 const stat=fs.statSync(video),size=1024*1024,parts=[];const fd=fs.openSync(video,'r');
 try{for(const offset of [0,Math.floor(stat.size/2),stat.size-size]){const b=Buffer.alloc(size);const n=fs.readSync(fd,b,0,size,offset);parts.push({offset,bytes:n,sha256:crypto.createHash('sha256').update(b.subarray(0,n)).digest('hex')});}}finally{fs.closeSync(fd);}
 const report={source:{path:video,bytes:stat.size,mtime_utc:stat.mtime.toISOString(),full_sha256:null,
   sampled_chunks:parts,sampled_identity_sha256:crypto.createHash('sha256').update(JSON.stringify({bytes:stat.size,parts})).digest('hex'),
   fingerprint_scope:'three 1MiB chunks only; not a whole-file SHA256'},metadata,frames,
   runtime_s:(Date.now()-start)/1000,media_bytes_served:mediaBytes,clock_synchronization:'UNVERIFIED',inference_runs:0,
   frame_limit:frameLimit,roi_intrinsic_px:roi,
   codec_surface:roi?'installed Chrome; source-pixel ROI in PNG; decoded video, not original encoded bytes':'installed Chrome, separate headless profile; requestVideoFrameCallback mediaTime; JPEG quality .95 preview, not original encoded frame bytes'};
 fs.writeFileSync(path.join(out,'frames.json'),JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({metadata,frames,runtime_s:report.runtime_s},null,2));
}finally{await call('Page.close').catch(()=>{});ws.close();server.closeAllConnections();server.close();}
