'use strict';
const $=id=>document.getElementById(id);
let data=null, marks=[], timeMs=0, playing=false, lastFrame=0, selected='', cars=[], videoUrl=null, videoBinding=null;
const canvas=$('scene'),ctx=canvas.getContext('2d'),bg=document.createElement('canvas');
const palette=['#5cd8bd','#7db8ff','#ffc178','#cc9cff','#fb9cae','#8cd87c'];
let movementColors=new Map(),view=null,videoRoi=null,selectVideoRoi=false;
const stateFields=['reviewer','sessionRole','intersection','knowledge'];

function status(id,text,error=false){$(id).textContent=text;$(id).className=error?'error small':'status small';}
function key(){return data?'traffic-phase-review:'+data.source.sha256:null;}
function metadata(){return Object.fromEntries(stateFields.map(id=>[id,$(id).value]));}
function persist(){if(!data)return;try{localStorage.setItem(key(),JSON.stringify({marks,metadata:metadata(),videoBinding}));status('saveStatus','Черновик сохранён в браузере. Скачайте JSON для передачи.');}catch(e){status('saveStatus','Не удалось сохранить черновик: скачайте JSON.',true);}}
function restore(){try{const saved=JSON.parse(localStorage.getItem(key())||'null');if(saved){marks=saved.marks||[];for(const [id,value]of Object.entries(saved.metadata||{}))if(stateFields.includes(id))$(id).value=value;videoBinding=saved.videoBinding||null;status('saveStatus','Восстановлен черновик для этого SHA256.');}}catch(e){status('saveStatus','Черновик не прочитан; можно импортировать JSON.',true);}}
async function responseJson(response){let body;try{body=await response.json();}catch{throw Error('Сервер вернул некорректный ответ');}if(!response.ok)throw Error(typeof body.detail==='string'?body.detail:JSON.stringify(body.detail));return body;}

async function openSource(demo=false){
  playing=false;$('play').textContent='▶ Пуск';$('open').disabled=$('demo').disabled=true;
  try{
    let response;
    if(demo)response=await fetch('/annotation/demo');
    else{const file=$('trajectoryFile').files[0];if(!file)throw Error('Выберите trajectory JSON');if(file.size>256*1024*1024)throw Error('Лимит файла — 256 MiB');const form=new FormData();form.append('file',file);form.append('start_seconds',$('windowStart').value);form.append('duration_seconds',$('windowDuration').value);status('loadStatus','Чтение и подготовка окна траекторий…');response=await fetch('/annotation/preview',{method:'POST',body:form});}
    const next=await responseJson(response);
    data=next;marks=[];selected='';timeMs=0;videoBinding=null;
    for(const id of stateFields)if(id!=='reviewer')$(id).value=id==='sessionRole'?'development':'';
    restore();movementColors=new Map([...new Set(data.tracks.map(t=>t.movement))].sort().map((m,i)=>[m,palette[i%palette.length]]));
    $('track').replaceChildren(new Option('Не выбрана',''));
    for(const t of data.tracks)$('track').add(new Option(`${t.source_track_id||t.key} · ${t.movement}`,t.key));
    for(const id of ['timeline','play','back','forward','start','end','add','export','import'])$(id).disabled=false;
    $('timeline').min=data.preview_window_ms[0];$('timeline').max=data.preview_window_ms[1];$('position').min=data.preview_window_ms[0]/1000;$('position').max=data.preview_window_ms[1]/1000;
    $('startSec').value=$('endSec').value=data.preview_window_ms[0]/1000;
    $('sourceInfo').textContent=`${data.source.name} · ${data.stats.display_tracks} машин · ${data.stats.display_points} точек · SHA256 ${data.source.sha256}\nПропущенные/дублированные записи: ${JSON.stringify(data.stats)}`;
    status('loadStatus',demo?'Открыта синтетическая демонстрация. Это не calibration-данные.':'Запись готова. Сигналы алгоритмом не вычислялись.');
    resize();setTime(data.preview_window_ms[0]);renderMarks();
  }catch(e){status('loadStatus',e.message,true);}finally{$('open').disabled=$('demo').disabled=false;}
}

function project(x,y){return [view.ox+(x-view.minx)*view.scale,view.oy+($('flipY').checked?view.maxy-y:y-view.miny)*view.scale];}
function resize(){
  const box=canvas.getBoundingClientRect();canvas.width=Math.max(200,Math.round(box.width));canvas.height=Math.round(box.height);
  bg.width=canvas.width;bg.height=canvas.height;
  if(!data){ctx.fillStyle='#adbdcb';ctx.font='16px system-ui';ctx.fillText('Откройте JSON или нажмите «Демо»',25,45);return;}
  let [minx,miny,maxx,maxy]=data.bounds;let dx=maxx-minx,dy=maxy-miny;
  if(!dx){minx-=.5;maxx+=.5;dx=1;}if(!dy){miny-=.5;maxy+=.5;dy=1;}
  const scale=Math.min((canvas.width-70)/dx,(canvas.height-70)/dy);
  view={minx,miny,maxx,maxy,scale,ox:(canvas.width-dx*scale)/2,oy:(canvas.height-dy*scale)/2};
  const b=bg.getContext('2d');b.clearRect(0,0,bg.width,bg.height);
  b.strokeStyle='#223446';b.lineWidth=1;for(let x=0;x<bg.width;x+=40){b.beginPath();b.moveTo(x,0);b.lineTo(x,bg.height);b.stroke();}for(let y=0;y<bg.height;y+=40){b.beginPath();b.moveTo(0,y);b.lineTo(bg.width,y);b.stroke();}
  for(const t of data.tracks){b.strokeStyle=movementColors.get(t.movement);b.globalAlpha=.13;b.lineWidth=1.5;b.beginPath();const step=Math.max(1,Math.ceil(t.points.length/150));for(let i=0;i<t.points.length;i+=step){const p=project(t.points[i][1],t.points[i][2]);i?b.lineTo(...p):b.moveTo(...p);}b.stroke();}
  b.globalAlpha=1;draw();
}
function locate(points,t){let l=0,r=points.length;while(l<r){const m=(l+r)>>1;if(points[m][0]<=t)l=m+1;else r=m;}return l-1;}
function at(track,t){const ps=track.points;const i=locate(ps,t);if(i<0)return null;const a=ps[i];if(a[0]===t)return [a[1],a[2],i,false];if(i+1>=ps.length)return null;const b=ps[i+1],gap=b[0]-a[0];if(gap>Math.max(0,Number($('gap').value))*1000)return null;const f=(t-a[0])/gap;return [a[1]+f*(b[1]-a[1]),a[2]+f*(b[2]-a[2]),i,true];}
function draw(){
  if(!data||!view)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(bg,0,0);cars=[];
  const chosen=data.tracks.find(t=>t.key===selected);
  if(chosen){ctx.strokeStyle='#ffffff';ctx.lineWidth=2;ctx.beginPath();chosen.points.forEach((p,i)=>{const q=project(p[1],p[2]);i?ctx.lineTo(...q):ctx.moveTo(...q);});ctx.stroke();}
  for(const track of data.tracks){const p=at(track,timeMs);if(!p)continue;const [x,y]=project(p[0],p[1]);cars.push({x,y,track});ctx.fillStyle=movementColors.get(track.movement);ctx.strokeStyle=track.key===selected?'#fff':'#102333';ctx.lineWidth=track.key===selected?3:1;ctx.beginPath();ctx.arc(x,y,track.key===selected?8:6,0,2*Math.PI);ctx.fill();ctx.stroke();if(track.key===selected){ctx.fillStyle='#fff';ctx.font='12px system-ui';ctx.fillText(track.source_track_id||track.key,x+12,y-10);}}
  $('sceneInfo').textContent=`Видно машин: ${cars.length} · ${[...movementColors.keys()].join(' · ')}`;
  const current=new Date(data.source.timestamp_origin_ms+timeMs);$('clock').textContent=current.toLocaleString('ru-RU',{timeZone:'Asia/Yekaterinburg',hour12:false})+'.'+String(current.getUTCMilliseconds()).padStart(3,'0')+' UTC+5';
  if(chosen){const i=locate(chosen.points,timeMs),before=chosen.points[i],after=chosen.points[i+1];$('selectedInfo').textContent=`ID ${chosen.source_track_id} · ${chosen.movement}\nFingerprint ${chosen.fingerprint}\nТочка до: ${before?(before[0]/1000).toFixed(3)+' с; raw speed '+(before[3]??'UNKNOWN'):'нет'}\nТочка после: ${after?(after[0]/1000).toFixed(3)+' с':'нет'} · units speed: UNKNOWN\n${before&&after?'Sampling gap '+(after[0]-before[0])+' мс':''}`;}else $('selectedInfo').textContent='';
}
function setTime(t){if(!data||!Number.isFinite(t))return;timeMs=Math.max(data.preview_window_ms[0],Math.min(data.preview_window_ms[1],Math.round(t)));$('timeline').value=timeMs;$('position').value=(timeMs/1000).toFixed(3);draw();}
function frame(now){if(playing&&data){setTime(timeMs+(now-lastFrame)*Number($('rate').value));if(timeMs>=data.preview_window_ms[1]){playing=false;$('play').textContent='▶ Пуск';}}lastFrame=now;requestAnimationFrame(frame);}
function source(){const external=['video_review','controller_log_review'].includes($('sourceKind').value);return {kind:$('sourceKind').value,reference:$('sourceReference').value.trim(),synchronization:{status:$('syncStatus').value,uncertainty_ms:$('syncUncertainty').value===''?null:Number($('syncUncertainty').value),verification_note:$('syncNote').value.trim(),video_binding:videoBinding},independent_source_claimed:external};}
function payload(){return {schema:data.producer,created_at:new Date().toISOString(),reviewer:$('reviewer').value.trim(),session_role:$('sessionRole').value,source:data.source,display:{preview_window_ms:data.preview_window_ms,coordinates:'raw image coordinates; units UNKNOWN',interpolation_max_gap_ms:Number($('gap').value)*1000,flip_y:$('flipY').checked,timezone:'Asia/Yekaterinburg'},intersection_knowledge:{name:$('intersection').value,description:$('knowledge').value,source:'operator_report_not_independently_verified'},annotations:marks.slice().sort((a,b)=>a.interval_start_ms-b.interval_start_ms),independent_truth_certified:false,inference_used:false};}
async function check(p){return responseJson(await fetch('/annotation/validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)}));}
async function addMark(){
 if(!data)return;
 try{
  const track=data.tracks.find(t=>t.key===selected),src=source();
  if($('kind').value==='vehicle_event'&&!track)throw Error('Выберите машину кликом или в списке');
  if(!$('reviewer').value.trim())throw Error('Укажите имя разметчика в блоке сохранения');
  const a=Number($('startSec').value),b=Number($('endSec').value);
  if($('startSec').value===''||$('endSec').value==='')throw Error('Укажите обе границы интервала');
  const mark={id:crypto.randomUUID(),kind:$('kind').value,label:$('label').value.trim(),interval_start_ms:data.source.timestamp_origin_ms+Math.round(a*1000),interval_end_ms:data.source.timestamp_origin_ms+Math.round(b*1000),review_window_ms:data.preview_window_ms,source_track_id:track?.source_track_id??null,track_key:track?.key??null,track_fingerprint:track?.fingerprint??null,movement:track?.movement??null,evidence_source:src,visibility:$('visibility').value,vehicle_timing_uncertainty_ms:$('uncertainty').value===''?null:Number($('uncertainty').value),signal_relation_uncertainty:'UNKNOWN',geometry_source:$('geometry').value.trim()||'UNKNOWN',notes:$('note').value.trim(),independently_verified:false,interpretation:src.independent_source_claimed?'independent_source_review_claim':'trajectory_based_hypothesis'};
  if(marks.some(m=>m.kind===mark.kind&&m.label===mark.label&&m.track_key===mark.track_key&&m.interval_start_ms===mark.interval_start_ms&&m.interval_end_ms===mark.interval_end_ms))throw Error('Такая метка уже есть');
  const p=payload();p.annotations.push(mark);await check(p);marks.push(mark);persist();renderMarks();status('markStatus','Метка добавлена.');
 }catch(e){status('markStatus',e.message,true);}
}
function renderMarks(){const root=$('marks');root.replaceChildren();$('count').textContent=marks.length;if(!marks.length){root.textContent='Пока нет меток.';return;}for(const mark of marks.slice().sort((a,b)=>a.interval_start_ms-b.interval_start_ms)){const row=document.createElement('div');row.className='mark';const body=document.createElement('div');body.className='body';const title=document.createElement('strong');title.textContent=mark.label;const text=document.createElement('div');text.className='small muted';text.textContent=`${((mark.interval_start_ms-data.source.timestamp_origin_ms)/1000).toFixed(3)}–${((mark.interval_end_ms-data.source.timestamp_origin_ms)/1000).toFixed(3)} с · ${mark.movement||'группа'} · ${mark.interpretation==='trajectory_based_hypothesis'?'гипотеза по траекториям':'внешний источник, review'}`;body.append(title,text);const go=document.createElement('button');go.textContent='К метке';go.onclick=()=>{playing=false;$('play').textContent='▶ Пуск';selected=mark.track_key||'';$('track').value=selected;const t=mark.interval_start_ms-data.source.timestamp_origin_ms;if(t<data.preview_window_ms[0]||t>data.preview_window_ms[1]){$('windowStart').value=Math.max(0,Math.floor(t/1000)-10);status('loadStatus','????? ??? ???????? ????. ?????? ???? ????????????; ??????? ???????? JSON?.');}else setTime(t);};const del=document.createElement('button');del.textContent='Удалить';del.onclick=()=>{marks=marks.filter(m=>m.id!==mark.id);persist();renderMarks();};row.append(body,go,del);root.append(row);}}
async function exportReview(){try{const p=payload();await check(p);const blob=new Blob([JSON.stringify(p,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=data.source.name.replace(/\.json$/i,'')+'_review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);status('saveStatus','JSON скачан. Передайте этот файл вместе с именем исходной записи.');}catch(e){status('saveStatus',e.message,true);}}
async function importReview(){try{const f=$('importFile').files[0];if(!f)throw Error('Выберите файл разметки');if(f.size>4*1024*1024)throw Error('Разметка превышает 4 MiB');const p=JSON.parse(await f.text());if(p.source?.sha256!==data.source.sha256)throw Error('SHA256 не совпадает: разметка относится к другому JSON');if(p.source.timestamp_origin_ms!==data.source.timestamp_origin_ms||p.source.end_timestamp_ms!==data.source.end_timestamp_ms)throw Error('Временная база не совпадает');await check(p);const keys=new Map(data.tracks.map(t=>[t.key,t]));for(const m of p.annotations)if(m.track_key&&keys.has(m.track_key)&&keys.get(m.track_key).fingerprint!==m.track_fingerprint)throw Error('Метка ссылается на неизвестный трек');marks=p.annotations;$('reviewer').value=p.reviewer;$('sessionRole').value=p.session_role;$('intersection').value=p.intersection_knowledge?.name||'';$('knowledge').value=p.intersection_knowledge?.description||'';persist();renderMarks();status('saveStatus','Разметка открыта.');}catch(e){status('saveStatus',e.message,true);}}

$('open').onclick=()=>openSource();$('demo').onclick=()=>openSource(true);
$('play').onclick=()=>{playing=!playing;$('play').textContent=playing?'❚❚ Пауза':'▶ Пуск';};
$('back').onclick=()=>setTime(timeMs-100);$('forward').onclick=()=>setTime(timeMs+100);
$('timeline').oninput=()=>setTime(Number($('timeline').value));$('position').onchange=()=>setTime(Number($('position').value)*1000);
$('start').onclick=()=>{$('startSec').value=(timeMs/1000).toFixed(3);if(Number($('endSec').value)<timeMs/1000)$('endSec').value=$('startSec').value;};
$('end').onclick=()=>{$('endSec').value=(timeMs/1000).toFixed(3);};
$('track').onchange=()=>{selected=$('track').value;draw();};$('flipY').onchange=resize;$('gap').onchange=draw;
canvas.onclick=e=>{const rect=canvas.getBoundingClientRect(),x=(e.clientX-rect.left)*canvas.width/rect.width,y=(e.clientY-rect.top)*canvas.height/rect.height;let best=null,d=20;for(const car of cars){const dist=Math.hypot(x-car.x,y-car.y);if(dist<d){best=car;d=dist;}}if(best){selected=best.track.key;$('track').value=selected;draw();}};
$('add').onclick=addMark;$('export').onclick=exportReview;$('import').onclick=importReview;
for(const button of document.querySelectorAll('[data-preset-kind]'))button.onclick=()=>{if(!data)return;playing=false;$('play').textContent='▶ Пуск';$('kind').value=button.dataset.presetKind;$('label').value=button.dataset.presetLabel;$('startSec').value=$('endSec').value=(timeMs/1000).toFixed(3);status('markStatus','Метка подготовлена; можно расширить интервал неопределённости.');};
for(const id of stateFields)$(id).addEventListener('change',persist);
function refreshVideo(){const v=$('video');$('videoPosition').textContent=Number.isFinite(v.duration)?`${v.currentTime.toFixed(3)} / ${v.duration.toFixed(3)} с`:'Видео не открыто';if(videoRoi&&v.readyState>=2){const c=$('videoZoom');c.hidden=false;const context=c.getContext('2d');context.imageSmoothingEnabled=false;context.drawImage(v,videoRoi.x,videoRoi.y,videoRoi.width,videoRoi.height,0,0,c.width,c.height);}}
$('videoFile').onchange=()=>{const file=$('videoFile').files[0];if(!file)return;if(videoUrl)URL.revokeObjectURL(videoUrl);const previous=videoBinding?.file;const same=previous&&previous.name===file.name&&previous.size===file.size&&previous.last_modified===file.lastModified;if(!same)videoBinding=null;videoRoi=same?videoBinding.video_roi_px||null:null;$('videoZoom').hidden=!videoRoi;videoUrl=URL.createObjectURL(file);$('video').src=videoUrl;$('sourceReference').value=file.name;$('videoInfo').textContent=same?'Восстановлена ручная привязка к тому же файлу; синхронизация не проверена.':'Видео открыто локально; синхронизация не проверена.';};
for(const name of ['loadedmetadata','seeked','timeupdate','loadeddata'])$('video').addEventListener(name,refreshVideo);
$('videoNow').onclick=()=>{if($('video').readyState<1)return;$('videoAnchor').value=$('video').currentTime.toFixed(3);};
$('videoBack').onclick=()=>{const v=$('video');if(v.readyState>=1){v.pause();v.currentTime=Math.max(0,v.currentTime-.1);}};
$('videoForward').onclick=()=>{const v=$('video');if(v.readyState>=1){v.pause();v.currentTime=Math.min(v.duration,v.currentTime+.1);}};
$('chooseVideoRoi').onclick=()=>{if($('video').readyState<2)return;selectVideoRoi=true;$('video').style.cursor='crosshair';$('videoRoiInfo').textContent='Нажмите на интересующую секцию в изображении видео. Привязка к movement не устанавливается.';};
$('video').addEventListener('click',e=>{if(!selectVideoRoi)return;e.preventDefault();e.stopPropagation();selectVideoRoi=false;const v=$('video');v.pause();v.style.cursor='';const r=v.getBoundingClientRect(),scale=Math.min(r.width/v.videoWidth,r.height/v.videoHeight),ox=(r.width-v.videoWidth*scale)/2,oy=(r.height-v.videoHeight*scale)/2;const x=(e.clientX-r.left-ox)/scale,y=(e.clientY-r.top-oy)/scale;if(x<0||y<0||x>v.videoWidth||y>v.videoHeight)return;const width=Math.min(180,v.videoWidth),height=Math.min(120,v.videoHeight);videoRoi={x:Math.max(0,Math.min(v.videoWidth-width,x-width/2)),y:Math.max(0,Math.min(v.videoHeight-height,y-height/2)),width,height,coordinate_space:'intrinsic video pixels; display ROI only, not verified geometry'};$('videoRoiInfo').textContent=`Область ${videoRoi.x.toFixed(1)}, ${videoRoi.y.toFixed(1)} · ${width}×${height} пикселей. Mapping и цвет не назначены.`;if(videoBinding){videoBinding={...videoBinding,video_roi_px:{...videoRoi}};persist();}refreshVideo();},true);
$('alignVideo').onclick=()=>{if(!data||!$('videoFile').files[0])return;const seconds=Number($('videoAnchor').value);if(!Number.isFinite(seconds)||seconds<0)return;const file=$('videoFile').files[0];videoBinding={trajectory_timestamp_ms:data.source.timestamp_origin_ms+timeMs,video_seconds:seconds,file:{name:file.name,size:file.size,last_modified:file.lastModified},status:'manual_alignment_not_verified',video_roi_px:videoRoi?{...videoRoi}:null};$('videoInfo').textContent=`JSON ${timeMs/1000} с ↔ видео ${seconds} с. Это ручное соответствие, не проверка часов.`;persist();};
$('seekVideo').onclick=()=>{if(!data||!videoBinding)return;const t=videoBinding.video_seconds+(data.source.timestamp_origin_ms+timeMs-videoBinding.trajectory_timestamp_ms)/1000;if(t<0||t>$('video').duration){$('videoInfo').textContent='Этот момент вне видео.';return;}$('video').currentTime=t;};
document.addEventListener('keydown',e=>{if(['INPUT','TEXTAREA','SELECT','BUTTON','VIDEO'].includes(document.activeElement.tagName)||!data)return;if(e.code==='Space'){e.preventDefault();$('play').click();}if(e.code==='ArrowLeft'){e.preventDefault();setTime(timeMs-100);}if(e.code==='ArrowRight'){e.preventDefault();setTime(timeMs+100);}});
window.addEventListener('resize',resize);resize();requestAnimationFrame(frame);
