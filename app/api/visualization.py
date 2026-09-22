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
<title>Traffic phase demo</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#0d1015;color:#edf2f7}
main{max-width:1050px;margin:auto;padding:24px}.muted{color:#98a2b3}.hidden{display:none!important}
.panel{background:#171b22;border:1px solid #2c333d;border-radius:14px;padding:16px;margin-top:14px}
.toolbar,.controls,.stats,.modebar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.modebar{margin-top:18px}.mode-btn{background:#242a33;color:#eef}.mode-btn.active{background:#f0f3f7;color:#111}
button,select,input{font:inherit}button{border:0;border-radius:8px;padding:9px 14px;cursor:pointer}
button.primary{background:#f0f3f7;color:#111}button.secondary{background:#2a3039;color:#eef}
button:disabled{opacity:.45;cursor:default}
select{background:#11151b;color:#eef;border:1px solid #343b46;border-radius:8px;padding:8px}
.stat{min-width:135px;flex:1;background:#10141a;border-radius:10px;padding:10px}
.stat span{display:block;color:#8f9aaa;font-size:12px}.stat strong{display:block;margin-top:4px;font-size:18px}
#batchSlider{width:100%}.timelinebar{display:flex;height:34px;border-radius:8px;overflow:hidden;background:#11151b;margin:10px 0}
.segment{min-width:2px;border-right:1px solid #11151b}.segment.ns{background:#314b40}.segment.ew{background:#4b3e31}.segment.unknown{background:#343943}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.intersection{position:relative;aspect-ratio:1/1;max-width:430px;margin:auto;background:#1d222a;border-radius:16px;overflow:hidden;border:1px solid #343b46}
.road-v,.road-h{position:absolute;background:#343b44}.road-v{left:35%;width:30%;height:100%}.road-h{top:35%;height:30%;width:100%}
.center{position:absolute;left:35%;top:35%;width:30%;height:30%;border:1px solid #59616d}
.signal{position:absolute;width:100px;text-align:center;padding:9px;border-radius:10px;background:#0d1015;border:1px solid #454d59;font-weight:700}
.signal.n{top:18px;left:50%;transform:translateX(-50%)}.signal.s{bottom:18px;left:50%;transform:translateX(-50%)}
.signal.w{left:18px;top:50%;transform:translateY(-50%)}.signal.e{right:18px;top:50%;transform:translateY(-50%)}
.state-GREEN{color:#49d17d}.state-YELLOW{color:#f2cc5c}.state-RED{color:#ef6576}.state-RED_YELLOW{color:#f29d5c}.state-UNKNOWN{color:#a7afba}.state-MIXED{color:#8fb7ff}
.axis{display:grid;grid-template-columns:1fr 1fr;gap:10px}.axis-card{background:#10141a;border-radius:10px;padding:12px;text-align:center}
.phase-list{display:flex;gap:8px;flex-wrap:wrap}.phase-chip{background:#242a33;border-radius:999px;padding:7px 10px;font-size:12px}
.notice{line-height:1.45}.error{color:#ef8794}.ok{color:#49d17d}.warmup{color:#f2cc5c}
.progress{height:8px;background:#10141a;border-radius:99px;overflow:hidden;margin-top:10px}.progress>div{height:100%;background:#697586;width:0%}
.small{font-size:13px}
@media(max-width:760px){.grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
<h1>Traffic phase demo</h1>
<p class="muted">Signal phases are inferred indirectly from vehicle trajectories. Ground truth is unavailable.</p>

<div class="modebar">
  <button id="modeBatch" class="mode-btn active">Batch</button>
  <button id="modeRealtime" class="mode-btn">Realtime simulation</button>
</div>

<section id="batchMode">
  <div class="panel toolbar">
    <input id="batchFile" type="file" accept=".json,.zip,application/json,application/zip">
    <button id="batchAnalyze" class="primary" disabled>Analyze archive</button>
    <span id="batchStatus" class="muted">Choose JSON or ZIP.</span>
  </div>

  <div id="batchSessionRow" class="panel hidden">
    <label for="batchSessionSelect">Session:</label>
    <select id="batchSessionSelect"></select>
  </div>

  <div id="batchViewer" class="hidden">
    <div class="panel stats">
      <div class="stat"><span>Cycle length</span><strong id="batchCycle">—</strong></div>
      <div class="stat"><span>Cycle confidence</span><strong id="batchCycleConfidence">—</strong></div>
      <div class="stat"><span>Current phase</span><strong id="batchPhase">UNKNOWN</strong></div>
      <div class="stat"><span>Active movement groups</span><strong id="batchActiveMovements">—</strong></div>
      <div class="stat"><span>Phase confidence</span><strong id="batchPhaseConfidence">—</strong></div>
      <div class="stat"><span>Vehicles / events</span><strong id="batchCounts">—</strong></div>
      <div class="stat"><span>UNKNOWN rate</span><strong id="batchUnknown">—</strong></div>
      <div class="stat"><span>UNKNOWN N/S/E/W</span><strong id="batchUnknownByApproach">—</strong></div>
      <div class="stat"><span>Phase coverage</span><strong id="batchCoverage">—</strong></div>
      <div class="stat"><span>UNKNOWN cause</span><strong id="batchUnknownCause">—</strong></div>
    </div>

    <div class="panel">
      <div class="controls">
        <button id="batchPlay" class="secondary">Play</button>
        <button id="batchPause" class="secondary">Pause</button>
        <span id="batchTimeLabel" class="muted">—</span>
      </div>
      <input id="batchSlider" type="range" min="0" max="0" value="0" step="1">
      <div id="phaseTimeline" class="timelinebar" title="Bounded phase timeline returned by the backend"></div>
    </div>

    <div class="panel">
      <h3>Phase model</h3>
      <div id="batchPhaseList" class="phase-list"></div>
      <div id="batchMovementList" class="phase-list" style="margin-top:10px"></div>
      <div class="muted small" style="margin-top:10px">Movement-specific groups are inferred separately and do not change the main N/S/E/W stage. The selected successful Batch session is the warm-start template available to Realtime simulation.</div>
    </div>
  </div>
</section>

<section id="realtimeMode" class="hidden">
  <div class="panel toolbar">
    <input id="realtimeFile" type="file" accept=".json,.zip,application/json,application/zip">
    <button id="realtimeStart" class="primary" disabled>Start</button>
    <button id="realtimePlay" class="secondary" disabled>Play</button>
    <button id="realtimePause" class="secondary" disabled>Pause</button>
    <button id="realtimeStep" class="secondary" disabled>Step</button>
    <button id="realtimeReset" class="secondary" disabled>Reset</button>
    <label for="realtimeSpeed">Speed</label>
    <select id="realtimeSpeed">
      <option value="1">x1</option>
      <option value="5">x5</option>
      <option value="20" selected>x20</option>
      <option value="1000">MAX</option>
    </select>
  </div>

  <div class="panel notice">
    <strong>Warm-start template:</strong> <span id="templateStatus" class="muted">Run Batch on a reference archive first.</span><br>
    <span class="muted small">Realtime inference is causal: detections become visible only when their own timestamp is reached. The browser does not compute phases.</span>
  </div>

  <div id="realtimeViewer" class="hidden">
    <div class="panel stats">
      <div class="stat"><span>Simulated time</span><strong id="realtimeTime">—</strong></div>
      <div class="stat"><span>Current phase</span><strong id="realtimePhase">UNKNOWN</strong></div>
      <div class="stat"><span>Active movement groups</span><strong id="realtimeMovements">—</strong></div>
      <div class="stat"><span>Confidence</span><strong id="realtimeConfidence">0.00</strong></div>
      <div class="stat"><span>Synchronizer</span><strong id="realtimeSync" class="warmup">WARMUP</strong></div>
      <div class="stat"><span>Adaptive mode</span><strong id="realtimeAdaptive">NORMAL</strong></div>
      <div class="stat"><span>Phase offset</span><strong id="realtimeOffset">—</strong></div>
      <div class="stat"><span>Template compatibility</span><strong id="realtimeCompatibility">CHECKING</strong></div>
      <div class="stat"><span>UNKNOWN post-sync</span><strong id="realtimeUnknownPostSync">—</strong></div>
      <div class="stat"><span>UNKNOWN last 60s</span><strong id="realtimeUnknownRolling">—</strong></div>
      <div class="stat"><span>Deviation / reason</span><strong id="realtimeDeviation">—</strong></div>
    </div>

    <div class="panel">
      <div class="controls">
        <span id="realtimeProgressText" class="muted">0%</span>
        <span id="realtimeSource" class="muted">—</span>
      </div>
      <div class="progress"><div id="realtimeProgressBar"></div></div>
    </div>

    <div class="panel stats">
      <div class="stat"><span>Sync evidence</span><strong id="syncEvidence">0</strong></div>
      <div class="stat"><span>Buffer events</span><strong id="bufferEvents">0</strong></div>
      <div class="stat"><span>Emitted trajectories</span><strong id="emittedTrajectories">0</strong></div>
      <div class="stat"><span>Emitted events</span><strong id="emittedEvents">0</strong></div>
      <div class="stat"><span>Remaining trajectories</span><strong id="remainingTrajectories">0</strong></div>
    </div>
  </div>
</section>

<div id="sharedState" class="grid hidden">
  <div class="panel">
    <h3>NS / EW state</h3>
    <div class="axis">
      <div class="axis-card"><div class="muted">NS</div><strong id="nsState" class="state-UNKNOWN">UNKNOWN</strong></div>
      <div class="axis-card"><div class="muted">EW</div><strong id="ewState" class="state-UNKNOWN">UNKNOWN</strong></div>
    </div>
    <p id="sharedHint" class="muted small">Backend signal state.</p>
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

<script>
const $=id=>document.getElementById(id);
let mode='batch';
let batchAnalysis=null,batchSession=null,batchIndex=0,batchTimer=null;
let realtimeId=null,realtimeSnapshot=null,realtimeTimer=null;

function setMode(next){
  mode=next;
  $('batchMode').classList.toggle('hidden',next!=='batch');
  $('realtimeMode').classList.toggle('hidden',next!=='realtime');
  $('modeBatch').classList.toggle('active',next==='batch');
  $('modeRealtime').classList.toggle('active',next==='realtime');
  stopBatch();
  stopRealtime();
  if(next==='batch'&&batchSession)renderBatchPoint();
  else if(next==='realtime'&&realtimeSnapshot)renderRealtimeSnapshot(realtimeSnapshot);
  else $('sharedState').classList.add('hidden');
}
$('modeBatch').addEventListener('click',()=>setMode('batch'));
$('modeRealtime').addEventListener('click',()=>setMode('realtime'));

$('batchFile').addEventListener('change',()=>{$('batchAnalyze').disabled=!$('batchFile').files.length});
$('batchAnalyze').addEventListener('click',analyzeBatch);
$('batchSessionSelect').addEventListener('change',()=>openBatchSession(Number($('batchSessionSelect').value)));
$('batchSlider').addEventListener('input',()=>{batchIndex=Number($('batchSlider').value);renderBatchPoint()});
$('batchPlay').addEventListener('click',playBatch);
$('batchPause').addEventListener('click',stopBatch);

$('realtimeFile').addEventListener('change',updateRealtimeStart);
$('realtimeStart').addEventListener('click',startRealtime);
$('realtimePlay').addEventListener('click',playRealtime);
$('realtimePause').addEventListener('click',stopRealtime);
$('realtimeStep').addEventListener('click',()=>stepRealtime(1));
$('realtimeReset').addEventListener('click',resetRealtime);
$('realtimeSpeed').addEventListener('change',()=>{if(realtimeSnapshot)renderRealtimeSnapshot(realtimeSnapshot)});

async function analyzeBatch(){
  stopBatch();
  const file=$('batchFile').files[0];
  if(!file)return;
  $('batchStatus').textContent='Analyzing…';
  const form=new FormData();form.append('file',file);
  try{
    const response=await fetch('/api/v1/phase/analyze',{method:'POST',body:form});
    if(!response.ok)throw new Error(await response.text());
    batchAnalysis=await response.json();
    const sessions=batchAnalysis.sessions||[];
    if(!sessions.length)throw new Error('No sessions returned by backend');
    const select=$('batchSessionSelect');select.innerHTML='';
    sessions.forEach((item,i)=>{
      const option=document.createElement('option');
      option.value=String(i);
      option.textContent='Session '+item.session_id+' · '+item.status+' · '+item.duration_s.toFixed(1)+' s';
      select.appendChild(option);
    });
    $('batchSessionRow').classList.toggle('hidden',sessions.length===1);
    $('batchStatus').textContent='Loaded '+batchAnalysis.source.filename+': '+sessions.length+' session(s).';
    openBatchSession(0);
  }catch(error){
    $('batchViewer').classList.add('hidden');
    $('batchSessionRow').classList.add('hidden');
    $('batchStatus').textContent='Error: '+error.message;
  }
}

function openBatchSession(i){
  stopBatch();batchIndex=0;batchSession=batchAnalysis.sessions[i];
  $('batchViewer').classList.remove('hidden');
  $('batchSessionSelect').value=String(i);
  const cycle=batchSession.cycle;
  $('batchCycle').textContent=cycle?cycle.estimated_cycle.toFixed(1)+' s':'—';
  $('batchCycleConfidence').textContent=cycle?cycle.confidence.toFixed(2):'—';
  $('batchCounts').textContent=batchSession.trajectory_count+' / '+batchSession.event_count;
  const unknown=batchSession.unknown_metrics||{};
  $('batchUnknown').textContent=unknown.overall_rate==null?'—':(unknown.overall_rate*100).toFixed(2)+'% '+(unknown.meets_target?'✓ <1%':'');
  const byApproach=unknown.per_approach_rate||{};
  $('batchUnknownByApproach').textContent=['N','S','E','W'].map(a=>a+' '+(byApproach[a]==null?'—':(byApproach[a]*100).toFixed(1)+'%')).join(' · ');
  const model=batchSession.phase_model||{};
  $('batchCoverage').textContent=model.cycle_coverage==null?'—':(Number(model.cycle_coverage)*100).toFixed(1)+'%';
  const reasonRate=unknown.reason_rate||{};
  const gaps=batchSession.uncovered_cycle_intervals||[];
  const reasons=Object.entries(reasonRate).map(([reason,rate])=>reason+' '+(Number(rate)*100).toFixed(1)+'%');
  const gapText=gaps.length?(' · gaps '+gaps.map(g=>Number(g.start_s).toFixed(1)+'–'+Number(g.end_s).toFixed(1)+'s').join(', ')):'';
  $('batchUnknownCause').textContent=(reasons.length?reasons.join(' · '):'none')+gapText;
  const timeline=batchSession.timeline||[];
  $('batchSlider').max=String(Math.max(0,timeline.length-1));
  $('batchSlider').value='0';
  $('batchSlider').disabled=timeline.length===0;
  $('batchPlay').disabled=timeline.length<2;
  $('batchPause').disabled=timeline.length<2;
  buildBatchPhaseModel();
  buildBatchTimeline();
  updateTemplateStatus();
  renderBatchPoint();
}

function buildBatchPhaseModel(){
  const holder=$('batchPhaseList');holder.innerHTML='';
  const movementHolder=$('batchMovementList');movementHolder.innerHTML='';
  const model=batchSession.phase_model||{};
  const phases=model.phases||[];
  if(!phases.length){holder.textContent='No phase model';return}
  phases.forEach(p=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Phase '+p.phase_id+': '+p.active_approaches.join('/')+' · '+p.phase_start+'–'+p.phase_end+'s · conf '+p.confidence.toFixed(2);
    holder.appendChild(chip);
  });
  const movementStages=model.movement_stages||[];
  movementStages.forEach(stage=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Movement '+stage.movement+' · '+stage.phase_start+'–'+stage.phase_end+'s · conf '+stage.confidence.toFixed(2);
    movementHolder.appendChild(chip);
  });
  if(!movementStages.length)movementHolder.textContent='No movement-specific signal groups inferred.';
}

function buildBatchTimeline(){
  const bar=$('phaseTimeline');bar.innerHTML='';
  const timeline=batchSession.timeline||[];
  if(!timeline.length){bar.innerHTML='<div class="segment unknown" style="width:100%"></div>';return}
  timeline.forEach(point=>{
    const seg=document.createElement('div');
    const ns=(point.axis_states&&point.axis_states.NS)||'UNKNOWN';
    const ew=(point.axis_states&&point.axis_states.EW)||'UNKNOWN';
    const states=point.states||{};
    const active=v=>v==='GREEN'||v==='YELLOW'||v==='RED_YELLOW';
    const cls=(active(states.N)||active(states.S))?'ns':((active(states.E)||active(states.W))?'ew':'unknown');
    seg.className='segment '+cls;
    seg.style.width=(100/timeline.length)+'%';
    seg.title=point.offset_s.toFixed(1)+'s · phase '+(point.phase_id==null?'UNKNOWN':point.phase_id)+' · NS '+ns+' · EW '+ew;
    bar.appendChild(seg);
  });
}

function renderBatchPoint(){
  if(mode!=='batch'||!batchSession)return;
  const timeline=batchSession.timeline||[];
  $('sharedState').classList.remove('hidden');
  $('sharedHint').textContent='Batch state at the selected session time.';
  if(!timeline.length){
    $('batchPhase').textContent='UNKNOWN';$('batchActiveMovements').textContent='—';$('batchPhaseConfidence').textContent='0.00';
    $('batchTimeLabel').textContent='No timeline: insufficient inference data';
    renderStates({N:'UNKNOWN',S:'UNKNOWN',E:'UNKNOWN',W:'UNKNOWN'});
    return;
  }
  const point=timeline[Math.min(batchIndex,timeline.length-1)];
  $('batchSlider').value=String(batchIndex);
  $('batchPhase').textContent=point.phase_id==null?'UNKNOWN':('Phase '+point.phase_id+(point.transition?' · transition':''));
  const batchMovements=point.active_movements||[];
  $('batchActiveMovements').textContent=batchMovements.length?batchMovements.map(item=>item.movement).join(', '):'—';
  $('batchPhaseConfidence').textContent=Number(point.confidence||0).toFixed(2);
  $('batchTimeLabel').textContent=point.offset_s.toFixed(1)+' s / '+batchSession.duration_s.toFixed(1)+' s';
  renderStates(point.states||{});
}

function playBatch(){
  stopBatch();
  const timeline=(batchSession&&batchSession.timeline)||[];
  if(timeline.length<2)return;
  if(batchIndex>=timeline.length-1)batchIndex=0;
  batchTimer=setInterval(()=>{
    if(batchIndex>=timeline.length-1){stopBatch();return}
    batchIndex++;renderBatchPoint();
  },350);
}
function stopBatch(){if(batchTimer){clearInterval(batchTimer);batchTimer=null}}

function usableTemplate(){
  return batchSession&&batchSession.status==='ok'&&batchSession.phase_model&&batchSession.phase_model.phases&&batchSession.phase_model.phases.length;
}
function updateTemplateStatus(){
  if(usableTemplate()){
    $('templateStatus').textContent='Batch session '+batchSession.session_id+' · cycle '+batchSession.phase_model.cycle_seconds.toFixed(1)+' s';
    $('templateStatus').className='ok';
  }else{
    $('templateStatus').textContent='Run Batch on a successful reference session first.';
    $('templateStatus').className='muted';
  }
  updateRealtimeStart();
}
function updateRealtimeStart(){
  $('realtimeStart').disabled=!$('realtimeFile').files.length||!usableTemplate();
}

async function startRealtime(){
  stopRealtime();
  if(!usableTemplate())return;
  const file=$('realtimeFile').files[0];
  if(!file)return;
  if(realtimeId)await deleteRealtimeSilently();
  const form=new FormData();
  form.append('file',file);
  form.append('phase_model',JSON.stringify(batchSession.phase_model));
  form.append('speed',$('realtimeSpeed').value);
  try{
    const response=await fetch('/api/v1/realtime/simulations/start',{method:'POST',body:form});
    if(!response.ok)throw new Error(await response.text());
    realtimeSnapshot=await response.json();
    realtimeId=realtimeSnapshot.simulation_id;
    $('realtimeViewer').classList.remove('hidden');
    $('realtimePlay').disabled=false;
    $('realtimePause').disabled=false;
    $('realtimeStep').disabled=false;
    $('realtimeReset').disabled=false;
    renderRealtimeSnapshot(realtimeSnapshot);
  }catch(error){
    $('realtimeViewer').classList.remove('hidden');
    $('realtimeSource').textContent='Error: '+error.message;
  }
}

async function stepRealtime(elapsedSeconds){
  if(!realtimeId)return;
  const speed=$('realtimeSpeed').value;
  const url='/api/v1/realtime/simulations/'+encodeURIComponent(realtimeId)+'/step?elapsed_seconds='+elapsedSeconds+'&speed='+speed;
  const response=await fetch(url,{method:'POST'});
  if(!response.ok){stopRealtime();throw new Error(await response.text())}
  realtimeSnapshot=await response.json();
  renderRealtimeSnapshot(realtimeSnapshot);
  if(realtimeSnapshot.finished)stopRealtime();
}

function playRealtime(){
  stopRealtime();
  if(!realtimeId)return;
  realtimeTimer=setInterval(async()=>{
    try{await stepRealtime(0.5)}catch(error){$('realtimeSource').textContent='Error: '+error.message}
  },500);
}
function stopRealtime(){if(realtimeTimer){clearInterval(realtimeTimer);realtimeTimer=null}}

async function resetRealtime(){
  stopRealtime();
  if(!realtimeId)return;
  const response=await fetch('/api/v1/realtime/simulations/'+encodeURIComponent(realtimeId)+'/reset',{method:'POST'});
  if(!response.ok)return;
  realtimeSnapshot=await response.json();
  renderRealtimeSnapshot(realtimeSnapshot);
}

async function deleteRealtimeSilently(){
  stopRealtime();
  if(!realtimeId)return;
  try{await fetch('/api/v1/realtime/simulations/'+encodeURIComponent(realtimeId),{method:'DELETE'})}catch(_error){}
  realtimeId=null;realtimeSnapshot=null;
}

function renderRealtimeSnapshot(snapshot){
  if(mode!=='realtime')return;
  $('sharedState').classList.remove('hidden');
  const adaptiveMode=snapshot.adaptive_mode||'NORMAL';
  const expectedAxis=snapshot.template_expected_axis||'—';
  const effectiveAxis=snapshot.effective_axis||'—';
  $('sharedHint').textContent=adaptiveMode==='LIVE_OVERRIDE'
    ?'Live override: template '+expectedAxis+', traffic evidence '+effectiveAxis+'.'
    :(adaptiveMode==='RECOVERY'
      ?'Realtime backend is resynchronizing after a temporary template deviation.'
      :'Realtime backend snapshot. WARMUP is shown as UNKNOWN.');
  const date=new Date(snapshot.simulated_timestamp_ms);
  $('realtimeTime').textContent=date.toLocaleString();
  $('realtimePhase').textContent=snapshot.phase_id==null?'UNKNOWN':'Phase '+snapshot.phase_id;
  const realtimeMovements=snapshot.active_movements||[];
  $('realtimeMovements').textContent=realtimeMovements.length?realtimeMovements.map(item=>item.movement).join(', '):'—';
  $('realtimeConfidence').textContent=Number(snapshot.confidence||0).toFixed(2);
  $('realtimeSync').textContent=snapshot.synchronization_status||'WARMUP';
  $('realtimeSync').className=snapshot.synchronization_status==='SYNCHRONIZED'?'ok':'warmup';
  $('realtimeAdaptive').textContent=adaptiveMode+(effectiveAxis!=='—'?' · '+effectiveAxis:'');
  $('realtimeAdaptive').className=adaptiveMode==='NORMAL'?'ok':'warmup';
  $('realtimeOffset').textContent=snapshot.phase_offset_s==null?'—':Number(snapshot.phase_offset_s).toFixed(1)+' s';
  const compatibility=snapshot.template_compatibility||'CHECKING';
  $('realtimeCompatibility').textContent=compatibility+' · match '+(Number(snapshot.synchronization_match_ratio||0)*100).toFixed(0)+'%';
  $('realtimeCompatibility').className=compatibility==='COMPATIBLE'?'ok':(compatibility==='INCOMPATIBLE'?'error':'warmup');
  const unknown=snapshot.unknown_metrics||{};
  $('realtimeUnknownPostSync').textContent=unknown.post_sync_rate==null?'—':(unknown.post_sync_rate*100).toFixed(2)+'% '+(unknown.meets_post_sync_target?'✓ <1%':'');
  $('realtimeUnknownRolling').textContent=unknown.rolling_60s_rate==null?'—':(unknown.rolling_60s_rate*100).toFixed(2)+'%';
  const reasonValues=Object.values(snapshot.unknown_reasons||{});
  const reason=reasonValues.length?[...new Set(reasonValues)].join(', '):(snapshot.warmup_reason||'—');
  const deviation=snapshot.template_deviation_seconds==null?'':(' · extension +'+Number(snapshot.template_deviation_seconds).toFixed(1)+'s');
  $('realtimeDeviation').textContent=reason+deviation;
  const progress=Math.round(Number(snapshot.progress||0)*1000)/10;
  $('realtimeProgressText').textContent=progress.toFixed(1)+'% · '+(snapshot.finished?'finished':'running');
  $('realtimeProgressBar').style.width=progress+'%';
  $('realtimeSource').textContent=snapshot.source.filename+' · '+snapshot.source.trajectory_count+' trajectories';
  const evidence=snapshot.evidence_summary||{};
  $('syncEvidence').textContent=String(evidence.synchronization_evidence_count||0);
  $('bufferEvents').textContent=String(evidence.buffer_event_count||0);
  $('emittedTrajectories').textContent=String(evidence.emitted_trajectory_count||0);
  $('emittedEvents').textContent=String(evidence.emitted_event_count||0);
  $('remainingTrajectories').textContent=String(evidence.remaining_trajectory_count||0);
  renderStates(snapshot.signal_states||{});
}

function renderStates(states){
  const normalized={};
  for(const approach of ['N','S','E','W'])normalized[approach]=states[approach]||'UNKNOWN';
  const ns=normalized.N===normalized.S?normalized.N:'MIXED';
  const ew=normalized.E===normalized.W?normalized.E:'MIXED';
  setState('nsState','',ns);setState('ewState','',ew);
  for(const approach of ['N','S','E','W'])setState('sig'+approach,approach,normalized[approach]);
}

function setState(id,label,state){
  const el=$(id);const value=state||'UNKNOWN';
  el.className=el.className.replace(/state-[A-Z_]+/g,'').trim()+' state-'+value;
  el.textContent=label?(label+' · '+value):value;
}

window.addEventListener('beforeunload',()=>{if(realtimeId)fetch('/api/v1/realtime/simulations/'+encodeURIComponent(realtimeId),{method:'DELETE',keepalive:true}).catch(()=>{})});
updateTemplateStatus();
</script>
</main>
</body>
</html>
"""
