from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/visualization", tags=["visualization"])


@router.get("", response_class=HTMLResponse)
def visualization_page() -> str:
    return r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic phase archive playback</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#0d1015;color:#edf2f7}
main{max-width:1000px;margin:auto;padding:24px}.muted{color:#98a2b3}.hidden{display:none!important}
.panel{background:#171b22;border:1px solid #2c333d;border-radius:14px;padding:16px;margin-top:14px}
.toolbar,.controls,.stats{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button,select,input{font:inherit}button{border:0;border-radius:8px;padding:9px 14px;cursor:pointer}
button.primary{background:#f0f3f7;color:#111}button.secondary{background:#2a3039;color:#eef}
button:disabled{opacity:.45;cursor:default}select{background:#11151b;color:#eef;border:1px solid #343b46;border-radius:8px;padding:8px}
.stat{min-width:135px;flex:1;background:#10141a;border-radius:10px;padding:10px}.stat span{display:block;color:#8f9aaa;font-size:12px}.stat strong{display:block;margin-top:4px;font-size:18px}
#slider{width:100%}.timelinebar{display:flex;height:34px;border-radius:8px;overflow:hidden;background:#11151b;margin:10px 0}
.segment{min-width:2px;border-right:1px solid #11151b}.segment.ns{background:#314b40}.segment.ew{background:#4b3e31}.segment.unknown{background:#343943}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.intersection{position:relative;aspect-ratio:1/1;max-width:430px;margin:auto;background:#1d222a;border-radius:16px;overflow:hidden;border:1px solid #343b46}
.road-v,.road-h{position:absolute;background:#343b44}.road-v{left:35%;width:30%;height:100%}.road-h{top:35%;height:30%;width:100%}
.center{position:absolute;left:35%;top:35%;width:30%;height:30%;border:1px solid #59616d}
.signal{position:absolute;width:94px;text-align:center;padding:9px;border-radius:10px;background:#0d1015;border:1px solid #454d59;font-weight:700}
.signal.n{top:18px;left:50%;transform:translateX(-50%)}.signal.s{bottom:18px;left:50%;transform:translateX(-50%)}
.signal.w{left:18px;top:50%;transform:translateY(-50%)}.signal.e{right:18px;top:50%;transform:translateY(-50%)}
.state-GREEN{color:#49d17d}.state-YELLOW{color:#f2cc5c}.state-RED{color:#ef6576}.state-RED_YELLOW{color:#f29d5c}.state-UNKNOWN{color:#a7afba}
.axis{display:grid;grid-template-columns:1fr 1fr;gap:10px}.axis-card{background:#10141a;border-radius:10px;padding:12px;text-align:center}
.phase-list{display:flex;gap:8px;flex-wrap:wrap}.phase-chip{background:#242a33;border-radius:999px;padding:7px 10px;font-size:12px}
.notice{line-height:1.45}.error{color:#ef8794}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
<h1>Traffic phase archive playback</h1>
<p class="muted">Signal phases are inferred indirectly from vehicle trajectories. Ground truth is unavailable.</p>

<div class="panel toolbar">
  <input id="file" type="file" accept=".json,.zip,application/json,application/zip">
  <button id="analyze" class="primary" disabled>Analyze archive</button>
  <span id="status" class="muted">Choose JSON or ZIP.</span>
</div>

<div id="sessionRow" class="panel hidden">
  <label for="sessionSelect">Session:</label>
  <select id="sessionSelect"></select>
</div>

<div id="viewer" class="hidden">
  <div class="panel stats">
    <div class="stat"><span>Cycle length</span><strong id="cycle">—</strong></div>
    <div class="stat"><span>Cycle confidence</span><strong id="cycleConfidence">—</strong></div>
    <div class="stat"><span>Current phase</span><strong id="phase">UNKNOWN</strong></div>
    <div class="stat"><span>Phase confidence</span><strong id="phaseConfidence">—</strong></div>
    <div class="stat"><span>Vehicles / events</span><strong id="counts">—</strong></div>
  </div>

  <div class="panel">
    <div class="controls">
      <button id="play" class="secondary">Play</button>
      <button id="pause" class="secondary">Pause</button>
      <span id="timeLabel" class="muted">—</span>
    </div>
    <input id="slider" type="range" min="0" max="0" value="0" step="1">
    <div id="phaseTimeline" class="timelinebar" title="Bounded phase timeline returned by the backend"></div>
  </div>

  <div class="grid">
    <div class="panel">
      <h3>NS / EW state</h3>
      <div class="axis">
        <div class="axis-card"><div class="muted">NS</div><strong id="nsState" class="state-UNKNOWN">UNKNOWN</strong></div>
        <div class="axis-card"><div class="muted">EW</div><strong id="ewState" class="state-UNKNOWN">UNKNOWN</strong></div>
      </div>
      <h3>Phase model</h3>
      <div id="phaseList" class="phase-list"></div>
    </div>

    <div class="panel">
      <h3>Simple intersection view</h3>
      <div class="intersection">
        <div class="road-v"></div><div class="road-h"></div><div class="center"></div>
        <div id="sigN" class="signal n state-UNKNOWN">N · UNKNOWN</div>
        <div id="sigS" class="signal s state-UNKNOWN">S · UNKNOWN</div>
        <div id="sigW" class="signal w state-UNKNOWN">W · UNKNOWN</div>
        <div id="sigE" class="signal e state-UNKNOWN">E · UNKNOWN</div>
      </div>
    </div>
  </div>

  <div class="panel notice">
    <strong>Session status:</strong> <span id="sessionStatus">—</span><br>
    <span id="sessionError" class="error"></span>
    <div class="muted" style="margin-top:7px">The browser displays backend inference only. It does not infer signal phases from the uploaded archive itself.</div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
let analysis=null,session=null,index=0,timer=null;

$('file').addEventListener('change',()=>{$('analyze').disabled=!$('file').files.length});
$('analyze').addEventListener('click',analyze);
$('sessionSelect').addEventListener('change',()=>openSession(Number($('sessionSelect').value)));
$('slider').addEventListener('input',()=>{index=Number($('slider').value);renderPoint()});
$('play').addEventListener('click',play);
$('pause').addEventListener('click',pause);

async function analyze(){
  pause();
  const file=$('file').files[0];
  if(!file)return;
  $('status').textContent='Analyzing…';
  const form=new FormData();form.append('file',file);
  try{
    const response=await fetch('/api/v1/phase/analyze',{method:'POST',body:form});
    if(!response.ok)throw new Error(await response.text());
    analysis=await response.json();
    const sessions=analysis.sessions||[];
    if(!sessions.length)throw new Error('No sessions returned by backend');
    const select=$('sessionSelect');select.innerHTML='';
    sessions.forEach((item,i)=>{
      const option=document.createElement('option');
      option.value=String(i);
      option.textContent='Session '+item.session_id+' · '+item.status+' · '+item.duration_s.toFixed(1)+' s';
      select.appendChild(option);
    });
    $('sessionRow').classList.toggle('hidden',sessions.length===1);
    $('status').textContent='Loaded '+analysis.source.filename+': '+sessions.length+' session(s).';
    openSession(0);
  }catch(error){
    $('viewer').classList.add('hidden');
    $('sessionRow').classList.add('hidden');
    $('status').textContent='Error: '+error.message;
  }
}

function openSession(i){
  pause();index=0;session=analysis.sessions[i];
  $('viewer').classList.remove('hidden');
  $('sessionSelect').value=String(i);
  const cycle=session.cycle;
  $('cycle').textContent=cycle?cycle.estimated_cycle.toFixed(1)+' s':'—';
  $('cycleConfidence').textContent=cycle?cycle.confidence.toFixed(2):'—';
  $('counts').textContent=session.trajectory_count+' / '+session.event_count;
  $('sessionStatus').textContent=session.status;
  $('sessionError').textContent=session.error_reason||'';
  const timeline=session.timeline||[];
  $('slider').max=String(Math.max(0,timeline.length-1));
  $('slider').value='0';
  $('slider').disabled=timeline.length===0;
  $('play').disabled=timeline.length<2;
  $('pause').disabled=timeline.length<2;
  buildPhaseModel();
  buildTimeline();
  renderPoint();
}

function buildPhaseModel(){
  const holder=$('phaseList');holder.innerHTML='';
  const phases=(session.phase_model&&session.phase_model.phases)||[];
  if(!phases.length){holder.textContent='No phase model';return}
  phases.forEach(p=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Phase '+p.phase_id+': '+p.active_approaches.join('/')+' · '+p.phase_start+'–'+p.phase_end+'s · conf '+p.confidence.toFixed(2);
    holder.appendChild(chip);
  });
}

function buildTimeline(){
  const bar=$('phaseTimeline');bar.innerHTML='';
  const timeline=session.timeline||[];
  if(!timeline.length){bar.innerHTML='<div class="segment unknown" style="width:100%"></div>';return}
  timeline.forEach(point=>{
    const seg=document.createElement('div');
    const ns=(point.axis_states&&point.axis_states.NS)||'UNKNOWN';
    const ew=(point.axis_states&&point.axis_states.EW)||'UNKNOWN';
    const cls=(ns==='GREEN'||ns==='YELLOW'||ns==='RED_YELLOW')?'ns':((ew==='GREEN'||ew==='YELLOW'||ew==='RED_YELLOW')?'ew':'unknown');
    seg.className='segment '+cls;
    seg.style.width=(100/timeline.length)+'%';
    seg.title=point.offset_s.toFixed(1)+'s · phase '+(point.phase_id==null?'UNKNOWN':point.phase_id)+' · NS '+ns+' · EW '+ew;
    bar.appendChild(seg);
  });
}

function setState(id,label,state){
  const el=$(id);const value=state||'UNKNOWN';
  el.className=el.className.replace(/state-[A-Z_]+/g,'').trim()+' state-'+value;
  el.textContent=label?(label+' · '+value):value;
}

function renderPoint(){
  const timeline=session.timeline||[];
  if(!timeline.length){
    $('phase').textContent='UNKNOWN';$('phaseConfidence').textContent='0.00';
    $('timeLabel').textContent='No timeline: insufficient inference data';
    setState('nsState','', 'UNKNOWN');setState('ewState','', 'UNKNOWN');
    for(const a of ['N','S','E','W'])setState('sig'+a,a,'UNKNOWN');
    return;
  }
  const point=timeline[Math.min(index,timeline.length-1)];
  $('slider').value=String(index);
  $('phase').textContent=point.phase_id==null?'UNKNOWN':('Phase '+point.phase_id+(point.transition?' · transition':''));
  $('phaseConfidence').textContent=point.confidence.toFixed(2);
  $('timeLabel').textContent=point.offset_s.toFixed(1)+' s / '+session.duration_s.toFixed(1)+' s';
  setState('nsState','',point.axis_states&&point.axis_states.NS);
  setState('ewState','',point.axis_states&&point.axis_states.EW);
  for(const a of ['N','S','E','W'])setState('sig'+a,a,point.states&&point.states[a]);
}

function play(){
  pause();
  const timeline=(session&&session.timeline)||[];
  if(timeline.length<2)return;
  if(index>=timeline.length-1)index=0;
  timer=setInterval(()=>{
    if(index>=timeline.length-1){pause();return}
    index++;renderPoint();
  },350);
}
function pause(){if(timer){clearInterval(timer);timer=null}}
</script>
</main>
</body>
</html>
"""
