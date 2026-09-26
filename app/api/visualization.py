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
.player-toolbar{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap}
.player-jumps{display:flex;gap:8px;flex-wrap:wrap}
.player-readout{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:12px 0}
.player-readout>div,.detail-card{background:#10141a;border-radius:10px;padding:10px}
.player-readout span,.detail-card span{display:block;color:#8f9aaa;font-size:11px}
.player-readout strong,.detail-card strong{display:block;margin-top:4px}
.timeline-axis{display:flex;justify-content:space-between;color:#7f8a99;font-size:10px;margin-top:4px}
.timeline-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;color:#98a2b3;font-size:11px}
.timeline-legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px;background:#536170}
.timeline-legend .legend-movement{background:#6b6578}.timeline-legend .legend-unknown{background:#343943}.timeline-legend .legend-transition{background:#8b7450}.timeline-legend .legend-extension{background:#596d87}.timeline-legend .legend-anomaly{background:#875d66}
.timeline-lanes{display:grid;grid-template-columns:82px 1fr;gap:6px 10px;margin-top:12px}
.timeline-lane-label{color:#8f9aaa;font-size:11px;align-self:center}
.timeline-lane{min-height:26px;position:relative;border-radius:6px;background:#10141a;overflow:hidden}
.timeline-segment{position:absolute;top:3px;bottom:3px;border-radius:4px;min-width:2px;background:#596777;cursor:pointer}
.timeline-segment.phase{background:#495d55}.timeline-segment.movement{background:#665c72}
.timeline-segment.unknown{background:#343943;border:1px dashed #8f98a5}.timeline-segment.transition{background:#8b7450}
.timeline-segment.extension{background:#596d87;border:1px dashed #b4c1d0}.timeline-segment.anomaly{background:#875d66}
.timeline-segment.active{outline:2px solid #eef2f7;outline-offset:-2px}
.player-detail .detail-heading{display:flex;justify-content:space-between;align-items:center;gap:10px}
.player-detail h4{margin:0 0 8px}.detail-grid{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:10px;margin:12px 0}
.detail-columns{display:grid;grid-template-columns:1fr 1fr;gap:14px}.detail-list{display:grid;gap:6px}
.detail-item{background:#10141a;border-radius:8px;padding:8px;font-size:12px}
.batch-player button:disabled{opacity:.35}
@media(max-width:900px){.player-readout,.detail-grid{grid-template-columns:1fr 1fr}.detail-columns{grid-template-columns:1fr}}
@media(max-width:640px){.player-readout,.detail-grid{grid-template-columns:1fr}.timeline-lanes{grid-template-columns:1fr}.timeline-lane-label{margin-top:6px}}
.segment{min-width:2px;border-right:1px solid #11151b}.segment.ns{background:#314b40}.segment.ew{background:#4b3e31}.segment.unknown{background:#343943}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.signal-renderer{--signal-gap:12px;display:grid;gap:var(--signal-gap);grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}
.signal-approach{background:#10141a;border:1px solid #343b46;border-radius:14px;padding:12px}
.signal-approach-title{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:10px}
.signal-head{background:#171b22;border:1px solid #3a424e;border-radius:11px;padding:10px;margin-top:8px}
.signal-head.additional{border-style:dashed}
.signal-head-title{display:flex;justify-content:space-between;gap:8px;align-items:center;font-size:13px;font-weight:700}
.signal-section{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:center;margin-top:8px;padding:9px;border-radius:9px;border:1px solid #303743}
.signal-section.source-modelled{border-style:dashed;background:#1b1a17}
.signal-section.source-observed{border-style:solid}
.signal-lamps{display:flex;gap:4px;align-items:center}
.signal-lamp{width:16px;height:16px;border-radius:50%;border:1px solid #697586;background:#252a31;opacity:.18}
.signal-lamp.on{opacity:1;box-shadow:0 0 10px currentColor}
.signal-lamp.red.on{color:#ef6576;background:#ef6576}.signal-lamp.yellow.on{color:#f2cc5c;background:#f2cc5c}.signal-lamp.green.on{color:#49d17d;background:#49d17d}
.signal-lamp.arrow{width:24px;height:24px;border-radius:5px;font-size:15px;display:grid;place-items:center;background:transparent;opacity:.9}
.signal-meta{min-width:0}.signal-state{font-weight:800;font-size:14px}.signal-state.unknown{padding:2px 6px;border:1px solid #ef6576;border-radius:5px;letter-spacing:.06em}
.signal-movement{font-size:12px;color:#98a2b3;overflow-wrap:anywhere}.signal-source{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:#aeb7c5;margin-top:4px}
.signal-confidence{font-size:10px;color:#7f8a99;margin-top:2px}
.signal-legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:#98a2b3}
.signal-legend .observed::before{content:'●';margin-right:4px}.signal-legend .modelled::before{content:'◌';margin-right:4px}
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

    <div class="panel stats">
      <div class="stat"><span>Processed members</span><strong id="batchProcessedMembers">0 / 0</strong></div>
      <div class="stat"><span>Trajectories</span><strong id="batchProcessedTrajectories">0</strong></div>
      <div class="stat"><span>Events</span><strong id="batchProcessedEvents">0</strong></div>
      <div class="stat"><span>Current session</span><strong id="batchCurrentSession">—</strong></div>
      <div class="stat"><span>Elapsed</span><strong id="batchElapsed">0.0 s</strong></div>
    </div>

  <div id="batchSessionRow" class="panel hidden">
    <label for="batchSessionSelect">Analysis segment:</label>
    <select id="batchSessionSelect"></select>
  </div>

  <div id="batchViewer" class="hidden">
    <div class="panel stats">
      <div class="stat"><span>Cycle length</span><strong id="batchCycle">—</strong></div>
      <div class="stat"><span>Determination confidence</span><strong id="batchCycleConfidence">—</strong></div>
      <div class="stat"><span>Current phase</span><strong id="batchPhase">UNKNOWN</strong></div>
      <div class="stat"><span>Active movement groups</span><strong id="batchActiveMovements">—</strong></div>
      <div class="stat"><span>Phase confidence</span><strong id="batchPhaseConfidence">—</strong></div>
      <div class="stat"><span>Vehicles / events</span><strong id="batchCounts">—</strong></div>
      <div class="stat"><span>Determination</span><strong id="batchQuality">—</strong></div>
      <div class="stat"><span>Determined coverage</span><strong id="batchCoverage">—</strong></div>
      <div class="stat"><span>Unable to determine</span><strong id="batchUnknown">—</strong></div>
      <div class="stat"><span>Unable N/S/E/W</span><strong id="batchUnknownByApproach">—</strong></div>
      <div class="stat"><span>Model source</span><strong id="batchUnresolved">—</strong></div>
      <div class="stat"><span>Realtime template</span><strong id="batchTemplateUsability">—</strong></div>
    </div>

    <details class="panel">
      <summary><strong>Diagnostics</strong> · local reconstruction, pooling and research-only hypotheses</summary>
      <div class="stats" style="margin-top:12px">
        <div class="stat"><span>Local model quality</span><strong id="batchLocalQuality">—</strong></div>
        <div class="stat"><span>Local coverage</span><strong id="batchLocalCoverage">—</strong></div>
        <div class="stat"><span>Regime family</span><strong id="batchRegimeFamily">—</strong></div>
        <div class="stat"><span>Pooled raw reconstruction</span><strong id="batchPooled">—</strong></div>
        <div class="stat"><span>Boundary suggestion</span><strong id="batchRecovery">—</strong></div>
        <div class="stat"><span>Gap diagnostics</span><strong id="batchGapSemantics">—</strong></div>
        <div class="stat"><span>Local unable cause</span><strong id="batchUnknownCause">—</strong></div>
      </div>
    </details>

    <div class="panel batch-player">
      <div class="player-toolbar">
        <div class="controls">
          <button id="batchPlay" class="primary">Play</button>
          <button id="batchPause" class="secondary">Pause</button>
          <label for="batchSpeed">Speed</label>
          <select id="batchSpeed">
            <option value="0.5">x0.5</option>
            <option value="1" selected>x1</option>
            <option value="2">x2</option>
            <option value="4">x4</option>
            <option value="10">x10</option>
            <option value="50">MAX</option>
          </select>
          <strong id="batchTimeLabel">—</strong>
        </div>
        <div class="player-jumps">
          <button id="batchPrevPhase" class="secondary">Previous phase</button>
          <button id="batchNextPhase" class="secondary">Next phase</button>
          <button id="batchNextUnknown" class="secondary">Next UNKNOWN</button>
          <button id="batchNextExtension" class="secondary">Next extension</button>
          <button id="batchNextAnomaly" class="secondary">Next anomaly</button>
        </div>
      </div>
      <div class="player-readout">
        <div><span>Exact timestamp</span><strong id="batchExactTimestamp">—</strong></div>
        <div><span>Cycle position</span><strong id="batchCyclePosition">—</strong></div>
        <div><span>Phase boundaries</span><strong id="batchBoundaryReadout">—</strong></div>
        <div><span>Timeline status</span><strong id="batchTimelineStatus">—</strong></div>
      </div>
      <input id="batchSlider" type="range" min="0" max="0" value="0" step="1" aria-label="Batch reconstruction timeline">
      <div id="phaseTimeline" class="timelinebar player-track phase-track" title="Backend reconstruction timeline"></div>
      <div class="timeline-axis" id="batchTimelineAxis"></div>
      <div class="timeline-legend">
        <span><i class="legend-phase"></i> phase</span>
        <span><i class="legend-movement"></i> movement</span>
        <span><i class="legend-unknown"></i> UNKNOWN</span>
        <span><i class="legend-transition"></i> transition</span>
        <span><i class="legend-extension"></i> extension</span>
        <span><i class="legend-anomaly"></i> anomaly</span>
      </div>
      <div class="timeline-lanes">
        <div class="timeline-lane-label">Movements</div>
        <div id="movementTimeline" class="timeline-lane"></div>
        <div class="timeline-lane-label">States</div>
        <div id="stateTimeline" class="timeline-lane"></div>
      </div>
    </div>
    <div class="panel player-detail">
      <div class="detail-heading">
        <div><h3>Selected reconstruction point</h3><span id="batchPointLabel" class="muted small">—</span></div>
        <span id="batchPlayerAdaptive" class="badge">—</span>
      </div>
      <div class="detail-grid">
        <div class="detail-card"><span>Signal state</span><strong id="batchSignalState">—</strong></div>
        <div class="detail-card"><span>Phase</span><strong id="batchPlayerPhase">UNKNOWN</strong></div>
        <div class="detail-card"><span>Confidence</span><strong id="batchPlayerConfidence">0.00</strong></div>
        <div class="detail-card"><span>Unknown reason</span><strong id="batchUnknownReason">—</strong></div>
      </div>
      <div class="detail-columns">
        <div><h4>Movement states</h4><div id="batchMovementStates" class="detail-list"></div></div>
        <div><h4>Evidence</h4><div id="batchEvidence" class="detail-list"></div></div>
      </div>
    </div>

    <div class="panel">
      <h3>Effective phase model</h3>
      <div id="batchPhaseList" class="phase-list"></div>
      <div class="muted small" style="margin-top:10px">Only evidence-backed intervals are authoritative. This is the best supported model for the selected regime; uncovered intervals remain impossible to determine.</div>
      <details style="margin-top:12px">
        <summary>Movement / gap research diagnostics</summary>
        <div id="batchMovementList" class="phase-list" style="margin-top:10px"></div>
        <div class="muted small" style="margin-top:10px">These diagnostics explain rejected or ambiguous hypotheses and never fill the authoritative main-phase gaps.</div>
      </details>
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
      <div class="stat"><span>Unable post-sync</span><strong id="realtimeUnknownPostSync">—</strong></div>
      <div class="stat"><span>Unable last 60s</span><strong id="realtimeUnknownRolling">—</strong></div>
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

<div id="sharedState" class="panel hidden">
  <h3>Configured signal heads</h3>
  <p id="sharedHint" class="muted small">Signal state renderer.</p>
  <div id="signalRenderer" class="signal-renderer"></div>
  <div class="signal-legend">
    <span class="observed">Observed evidence</span>
    <span class="modelled">Modelled transition / model state</span>
    <span>Dashed sections are modelled, not direct lamp observations.</span>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
let mode='batch';
let batchAnalysis=null,batchSession=null,batchIndex=0,batchTimer=null,batchSpeed=1;
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
$('batchSpeed').addEventListener('change',()=>{batchSpeed=Number($('batchSpeed').value)||1});
$('batchPrevPhase').addEventListener('click',()=>jumpBatch('previous_phase'));
$('batchNextPhase').addEventListener('click',()=>jumpBatch('next_phase'));
$('batchNextUnknown').addEventListener('click',()=>jumpBatch('next_unknown'));
$('batchNextExtension').addEventListener('click',()=>jumpBatch('next_extension'));
$('batchNextAnomaly').addEventListener('click',()=>jumpBatch('next_anomaly'));

$('realtimeFile').addEventListener('change',updateRealtimeStart);
$('realtimeStart').addEventListener('click',startRealtime);
$('realtimePlay').addEventListener('click',playRealtime);
$('realtimePause').addEventListener('click',stopRealtime);
$('realtimeStep').addEventListener('click',()=>stepRealtime(1));
$('realtimeReset').addEventListener('click',resetRealtime);
$('realtimeSpeed').addEventListener('change',()=>{if(realtimeSnapshot)renderRealtimeSnapshot(realtimeSnapshot)});

function renderBatchProgress(){
  const progress=(batchAnalysis&&batchAnalysis.progress)||{};
  $('batchProcessedMembers').textContent=(progress.processed_members||0)+' / '+(progress.total_members||0);
  $('batchProcessedTrajectories').textContent=String(progress.trajectories||0);
  $('batchProcessedEvents').textContent=String(progress.events||0);
  $('batchCurrentSession').textContent=progress.current_session==null?'—':String(progress.current_session);
  $('batchElapsed').textContent=Number(progress.elapsed_seconds||0).toFixed(1)+' s';
}

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
    renderBatchProgress();
    const sessions=batchAnalysis.sessions||[];
    if(!sessions.length)throw new Error('No sessions returned by backend');
    const select=$('batchSessionSelect');select.innerHTML='';
    sessions.forEach((item,i)=>{
      const option=document.createElement('option');
      option.value=String(i);
      const determination=item.determination||{};
      const template=item.realtime_template_usability||{};
      option.textContent='Segment '+item.session_id+' · physical '+item.physical_session_index+' · regime '+item.regime_index+'/'+item.regime_count+' · '+(determination.status||'UNABLE_TO_DETERMINE')+' · RT '+(template.status||'NOT_USABLE')+' · '+item.duration_s.toFixed(1)+' s';
      select.appendChild(option);
    });
    $('batchSessionRow').classList.toggle('hidden',sessions.length===1);
    $('batchStatus').textContent='Loaded '+batchAnalysis.source.filename+': '+sessions.length+' analysis segment(s), '+(batchAnalysis.source.regime_family_count||0)+' regime family/families.';
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

  const determination=batchSession.determination||{};
  const effectiveModel=batchSession.effective_phase_model||{};
  const localModel=batchSession.phase_model||{};
  const localCycle=batchSession.cycle;
  const template=batchSession.realtime_template_usability||{};

  const cycleSeconds=effectiveModel.cycle_seconds==null
    ?(localCycle?localCycle.estimated_cycle:null)
    :Number(effectiveModel.cycle_seconds);
  $('batchCycle').textContent=cycleSeconds==null?'—':Number(cycleSeconds).toFixed(1)+' s';
  $('batchCycleConfidence').textContent=determination.confidence==null?'—':Number(determination.confidence).toFixed(2);
  $('batchCounts').textContent=batchSession.trajectory_count+' / '+batchSession.event_count;

  const unable=determination.unable_to_determine_fraction;
  const determined=determination.determined_fraction;
  $('batchUnknown').textContent=unable==null?'—':(Number(unable)*100).toFixed(2)+'%';
  $('batchCoverage').textContent=determined==null?'—':(Number(determined)*100).toFixed(1)+'%';

  const effectiveUnknown=batchSession.effective_unknown_metrics||{};
  const byApproach=effectiveUnknown.per_approach_rate||{};
  $('batchUnknownByApproach').textContent=['N','S','E','W'].map(a=>a+' '+(byApproach[a]==null?'—':(Number(byApproach[a])*100).toFixed(1)+'%')).join(' · ');

  const status=determination.status||'UNABLE_TO_DETERMINE';
  $('batchQuality').textContent=status;
  $('batchQuality').className=status==='AVAILABLE'?'ok':(status==='UNABLE_TO_DETERMINE'?'error':'warmup');
  $('batchUnresolved').textContent=determination.source||'—';

  $('batchTemplateUsability').textContent=(template.status||'NOT_USABLE')+' · '+(template.source||'—')+(template.usable?'':' · batch-only');
  $('batchTemplateUsability').className=template.usable?'ok':'warmup';

  const localQuality=batchSession.model_quality||'UNKNOWN';
  const localReasons=batchSession.quality_reasons||[];
  $('batchLocalQuality').textContent=localQuality+(localReasons.length?(' · '+localReasons.join(', ')):'');
  $('batchLocalQuality').className=localQuality==='GOOD'?'ok':(localQuality==='INSUFFICIENT'?'error':'warmup');
  $('batchLocalCoverage').textContent=localModel.cycle_coverage==null?'—':(Number(localModel.cycle_coverage)*100).toFixed(1)+'%';

  const suggested=Number(localModel.boundary_suggested_fraction||0);
  const recoveryItems=localModel.boundary_recoveries||[];
  $('batchRecovery').textContent=(suggested*100).toFixed(1)+'% suggested · not applied'+(recoveryItems.length?(' · '+recoveryItems.map(item=>item.axis+' '+Number(item.phase_start).toFixed(1)+'–'+Number(item.phase_end).toFixed(1)+'s').join(', ')):'');

  const localUnknown=batchSession.unknown_metrics||{};
  const reasonRate=localUnknown.reason_rate||{};
  const localGaps=batchSession.uncovered_cycle_intervals||[];
  const reasons=Object.entries(reasonRate).map(([reason,rate])=>reason+' '+(Number(rate)*100).toFixed(1)+'%');
  const gapText=localGaps.length?(' · gaps '+localGaps.map(g=>Number(g.start_s).toFixed(1)+'–'+Number(g.end_s).toFixed(1)+'s').join(', ')):'';
  $('batchUnknownCause').textContent=(reasons.length?reasons.join(' · '):'none')+gapText;

  const gapMetrics=batchSession.gap_metrics||{};
  $('batchGapSemantics').textContent='clearance '+(Number(gapMetrics.clearance_candidate_rate||0)*100).toFixed(1)+'% · transition ambiguous '+(Number(gapMetrics.transition_ambiguous_rate||0)*100).toFixed(1)+'% · unresolved stage '+(Number(gapMetrics.unresolved_stage_rate||0)*100).toFixed(1)+'% · unobserved '+(Number(gapMetrics.unobserved_rate||0)*100).toFixed(1)+'%';

  const family=currentRegimeFamily();
  $('batchRegimeFamily').textContent=family?(family.family_id+' · '+family.member_count+' member(s) · '+family.model_quality+' · vote '+(Number(family.consensus_coverage||0)*100).toFixed(1)+'%'):'—';
  $('batchPooled').textContent=family?(family.pooling_status+' · '+(family.pooled_event_count||0)+' events · '+(family.pooled_cycle_count||0)+' cycles · coverage '+(family.pooled_coverage==null?'—':(Number(family.pooled_coverage)*100).toFixed(1)+'%')+' · quality '+(family.pooled_model_quality||'—')+' · movement candidates '+(family.pooled_movement_candidate_count||0)+' / stages '+(family.pooled_movement_stage_count||0)):'—';

  const timeline=(batchSession.player&&batchSession.player.timeline)||batchSession.timeline||[];
  batchSpeed=Number($('batchSpeed').value)||1;
  $('batchSlider').max=String(Math.max(0,timeline.length-1));
  $('batchSlider').value='0';
  $('batchSlider').disabled=timeline.length===0;
  $('batchPlay').disabled=timeline.length<2;
  $('batchPause').disabled=timeline.length<2;
  const nav=(batchSession.player&&batchSession.player.navigation)||{};
  $('batchPrevPhase').disabled=!Array.isArray(nav.phase_starts)||nav.phase_starts.length===0;
  $('batchNextPhase').disabled=!Array.isArray(nav.phase_starts)||nav.phase_starts.length===0;
  $('batchNextUnknown').disabled=!Array.isArray(nav.unknown)||nav.unknown.length===0;
  $('batchNextExtension').disabled=!Array.isArray(nav.extensions)||nav.extensions.length===0;
  $('batchNextAnomaly').disabled=!Array.isArray(nav.anomalies)||nav.anomalies.length===0;
  buildBatchPhaseModel();
  buildBatchTimeline();
  updateTemplateStatus();
  renderBatchPoint();
}
function buildBatchPhaseModel(){
  const holder=$('batchPhaseList');holder.innerHTML='';
  const movementHolder=$('batchMovementList');movementHolder.innerHTML='';
  const model=batchSession.effective_phase_model||{};
  const localModel=batchSession.phase_model||{};
  const phases=model.phases||[];
  if(!phases.length){holder.textContent='Unable to determine a supported phase model';movementHolder.textContent='No diagnostics available.';return}
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
  const movementDecisions=localModel.movement_stage_decisions||[];
  movementDecisions.forEach(item=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    const residual=item.residual_start==null?'no residual':('residual '+Number(item.residual_start).toFixed(1)+'–'+Number(item.residual_end).toFixed(1)+'s · rep '+Number(item.residual_repeatability||0).toFixed(2)+' · stab '+Number(item.residual_stability||0).toFixed(2)+' · conflict '+(Number(item.conflicting_event_ratio||0)*100).toFixed(0)+'%');
    chip.textContent='Decision '+item.movement+' · '+(item.promoted?'PROMOTE':'REJECT')+' · '+residual+' · '+item.reason;
    movementHolder.appendChild(chip);
  });
  const gapProbes=(batchSession.gap_semantics||[]).flatMap(gap=>(gap.movement_evidence||[]).map(item=>({gap,item})));
  gapProbes.forEach(({gap,item})=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Gap '+Number(gap.start_s).toFixed(1)+'–'+Number(gap.end_s).toFixed(1)+'s · '+gap.kind+' · '+item.movement+' candidate · conf '+Number(item.confidence||0).toFixed(2);
    movementHolder.appendChild(chip);
  });
  const family=currentRegimeFamily();
  const pooled=family&&family.pooled_phase_model?family.pooled_phase_model:null;
  const pooledStages=pooled?(pooled.movement_stages||[]):[];
  const pooledCandidates=pooled?(pooled.distinct_movement_candidates||[]):[];
  const pooledDecisions=pooled?(pooled.movement_stage_decisions||[]):[];
  pooledStages.forEach(stage=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Pooled movement '+stage.movement+' · '+stage.phase_start+'–'+stage.phase_end+'s · conf '+Number(stage.confidence||0).toFixed(2);
    movementHolder.appendChild(chip);
  });
  pooledCandidates.forEach(item=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    chip.textContent='Pooled candidate '+item.movement+' · '+item.phase_start+'–'+item.phase_end+'s · score '+Number(item.score||0).toFixed(2);
    movementHolder.appendChild(chip);
  });
  pooledDecisions.forEach(item=>{
    const chip=document.createElement('span');chip.className='phase-chip';
    const residual=item.residual_start==null?'no residual':('residual '+Number(item.residual_start).toFixed(1)+'–'+Number(item.residual_end).toFixed(1)+'s · rep '+Number(item.residual_repeatability||0).toFixed(2)+' · stab '+Number(item.residual_stability||0).toFixed(2)+' · conflict '+(Number(item.conflicting_event_ratio||0)*100).toFixed(0)+'%');
    chip.textContent='Pooled decision '+item.movement+' · '+(item.promoted?'PROMOTE':'REJECT')+' · '+residual+' · '+item.reason;
    movementHolder.appendChild(chip);
  });
  if(!movementStages.length&&!movementDecisions.length&&!gapProbes.length&&!pooledStages.length&&!pooledCandidates.length&&!pooledDecisions.length)movementHolder.textContent='No movement-specific signal groups inferred.';
}

function playerTimeline(){
  return (batchSession&&batchSession.player&&batchSession.player.timeline)
    || (batchSession&&batchSession.timeline)
    || [];
}
function batchPlayerEndTimestamp(index){
  const timeline=playerTimeline();
  if(!timeline.length)return null;
  const next=timeline[index+1];
  if(next&&Number.isFinite(Number(next.timestamp_ms)))return Number(next.timestamp_ms);
  return batchSession&&batchSession.end_timestamp_ms!=null?Number(batchSession.end_timestamp_ms):Number(timeline[index].timestamp_ms);
}
function percentForTimestamp(timestamp){
  if(!batchSession)return 0;
  const start=Number(batchSession.start_timestamp_ms);
  const end=Number(batchSession.end_timestamp_ms);
  if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start)return 0;
  return Math.max(0,Math.min(100,((Number(timestamp)-start)/(end-start))*100));
}
function addTimelineSegment(holder,{start_ms,end_ms,kind,label,index}){
  const start=Number(start_ms),end=Number(end_ms);
  const left=percentForTimestamp(start);
  const width=Math.max(0.35,percentForTimestamp(Math.max(start,end))-left);
  const seg=document.createElement('button');
  seg.type='button';seg.dataset.index=String(index);
  seg.className='timeline-segment '+kind+(index===batchIndex?' active':'');
  seg.style.left=left+'%';seg.style.width=width+'%';
  seg.title=label||'';seg.setAttribute('aria-label',label||kind);
  seg.addEventListener('click',()=>selectBatchIndex(index));
  holder.appendChild(seg);
}
function buildBatchTimeline(){
  const bar=$('phaseTimeline'),movement=$('movementTimeline'),states=$('stateTimeline');
  bar.innerHTML='';movement.innerHTML='';states.innerHTML='';
  const timeline=playerTimeline();
  if(!timeline.length){
    bar.innerHTML='<div class="segment unknown" style="width:100%"></div>';
    $('batchTimelineAxis').innerHTML='';
    return;
  }
  timeline.forEach((point,index)=>{
    const start=Number(point.timestamp_ms),end=batchPlayerEndTimestamp(index)||start;
    const phase=point.phase_id==null?'UNKNOWN':('Phase '+point.phase_id);
    addTimelineSegment(bar,{start_ms:start,end_ms:end,kind:point.phase_id==null?'unknown':'phase',
      label:new Date(start).toISOString()+' · '+phase+' · cycle '+Number(point.cycle_position_s||0).toFixed(1)+'s',index});
    const stateLabel=Object.entries(point.states||{}).map(([approach,state])=>approach+':'+state).join(' · ');
    addTimelineSegment(states,{start_ms:start,end_ms:end,kind:point.transition?'transition':(point.unknown_reason?'unknown':'phase'),
      label:stateLabel||'UNKNOWN',index});
  });
  const player=batchSession.player||{};
  (player.movement_intervals||[]).forEach(interval=>{
    const start=Number(interval.start_timestamp_ms),end=Number(interval.end_timestamp_ms);
    const label='Movement '+interval.movement+' · '+Number(interval.cycle_start_s||0).toFixed(1)+'–'+Number(interval.cycle_end_s||0).toFixed(1)+'s';
    addTimelineSegment(movement,{start_ms:start,end_ms:end,kind:'movement',label,index:nearestBatchIndex(start)});
  });
  (player.unknown_intervals||[]).forEach(interval=>addTimelineSegment(bar,{
    start_ms:Number(interval.start_timestamp_ms),end_ms:Number(interval.end_timestamp_ms),kind:'unknown',
    label:'UNKNOWN · '+(interval.reason||'unknown'),index:nearestBatchIndex(Number(interval.start_timestamp_ms))}));
  (player.transition_intervals||[]).forEach(interval=>addTimelineSegment(bar,{
    start_ms:Number(interval.start_timestamp_ms),end_ms:Number(interval.end_timestamp_ms),kind:'transition',
    label:'Transition interval',index:nearestBatchIndex(Number(interval.start_timestamp_ms))}));
  (player.phase_extension_intervals||[]).forEach(interval=>addTimelineSegment(bar,{
    start_ms:Number(interval.start_timestamp_ms),end_ms:Number(interval.end_timestamp_ms),kind:'extension',
    label:'Phase extension',index:nearestBatchIndex(Number(interval.start_timestamp_ms))}));
  (player.anomaly_intervals||[]).forEach(interval=>{
    addTimelineSegment(bar,{
      start_ms:Number(interval.start_timestamp_ms),end_ms:Number(interval.end_timestamp_ms),kind:'anomaly',
      label:'Anomaly · '+(interval.kind||'unknown'),index:nearestBatchIndex(Number(interval.start_timestamp_ms))
    });
  });
  const axis=$('batchTimelineAxis');
  axis.innerHTML='<span>'+new Date(Number(timeline[0].timestamp_ms)).toLocaleTimeString()+'</span><span>'+new Date(Number(timeline[timeline.length-1].timestamp_ms)).toLocaleTimeString()+'</span>';
}
function syncBatchTimelineActive(){
  document.querySelectorAll('#phaseTimeline .timeline-segment,#movementTimeline .timeline-segment,#stateTimeline .timeline-segment').forEach(seg=>{
    seg.classList.toggle('active',Number(seg.dataset.index)===batchIndex);
  });
}
function nearestBatchIndex(timestamp){
  const timeline=playerTimeline();
  if(!timeline.length)return 0;
  let best=0,bestDistance=Infinity;
  timeline.forEach((point,index)=>{
    const distance=Math.abs(Number(point.timestamp_ms)-Number(timestamp));
    if(distance<bestDistance){best=index;bestDistance=distance}
  });
  return best;
}
function selectBatchIndex(index){
  const timeline=playerTimeline();
  if(!timeline.length)return;
  batchIndex=Math.max(0,Math.min(timeline.length-1,Number(index)));
  renderBatchPoint();
  syncBatchTimelineActive();
}
function renderBatchDetailList(holder,items,emptyText){
  holder.innerHTML='';
  if(!items.length){
    const empty=document.createElement('div');empty.className='muted small';empty.textContent=emptyText;holder.appendChild(empty);return;
  }
  items.forEach(item=>{const row=document.createElement('div');row.className='detail-item';row.textContent=item;holder.appendChild(row)});
}
function renderBatchPoint(){
  if(mode!=='batch'||!batchSession)return;
  const timeline=playerTimeline();
  $('sharedState').classList.remove('hidden');
  $('sharedHint').textContent='Backend reconstruction snapshot. Browser playback selects and renders returned points; it does not infer phases.';
  if(!timeline.length){
    $('batchPhase').textContent='UNKNOWN';$('batchActiveMovements').textContent='—';$('batchPhaseConfidence').textContent='0.00';
    $('batchTimeLabel').textContent='No timeline: insufficient reconstruction data';
    $('batchExactTimestamp').textContent='—';$('batchCyclePosition').textContent='—';$('batchBoundaryReadout').textContent='—';$('batchTimelineStatus').textContent='No backend timeline';
    $('batchSignalState').textContent='UNKNOWN';$('batchPlayerPhase').textContent='UNKNOWN';$('batchPlayerConfidence').textContent='0.00';$('batchUnknownReason').textContent='insufficient_reconstruction_data';
    $('batchPlayerAdaptive').textContent=(batchSession.player&&batchSession.player.adaptive_mode)||'BATCH_RECONSTRUCTION';
    renderSignalRenderer(batchSession.signal_renderer||null);return;
  }
  const point=timeline[Math.min(batchIndex,timeline.length-1)];
  const player=batchSession.player||{};
  const exactDate=new Date(Number(point.timestamp_ms));
  const states=point.states||{};
  const stateText=Object.entries(states).map(([approach,state])=>approach+' '+state).join(' · ')||'UNKNOWN';
  const phase=point.phase_id==null?'UNKNOWN':('Phase '+point.phase_id);
  const movements=point.movement_states||point.active_movements||[];
  const movementLabels=movements.map(item=>item.movement+' · '+(item.state||'UNKNOWN')+' · conf '+Number(item.confidence||0).toFixed(2));
  const evidence=point.evidence||{};
  const evidenceLabels=[
    'phase support '+Number(evidence.phase_supporting_event_count||0),
    'phase contradictory '+Number(evidence.phase_contradictory_event_count||0),
    'movement support '+Number(evidence.movement_supporting_event_count||0)
  ];
  const boundaries=player.phase_boundaries||[];
  const cyclePosition=Number(point.cycle_position_s||0);
  let boundaryReadout='—';
  if(boundaries.length){
    const exact=boundaries.find(item=>Math.abs(Number(item.cycle_position_s||0)-cyclePosition)<0.6);
    const nearest=[...boundaries].sort((a,b)=>Math.abs(Number(a.cycle_position_s||0)-cyclePosition)-Math.abs(Number(b.cycle_position_s||0)-cyclePosition))[0];
    if(exact)boundaryReadout='P'+exact.phase_id+' boundary @ '+Number(exact.cycle_position_s||0).toFixed(1)+'s';
    else if(nearest)boundaryReadout='nearest P'+nearest.phase_id+' @ '+Number(nearest.cycle_position_s||0).toFixed(1)+'s';
  }
  $('batchSlider').value=String(batchIndex);
  $('batchTimeLabel').textContent=exactDate.toLocaleString()+' · '+Number(point.offset_s||0).toFixed(1)+' s';
  $('batchExactTimestamp').textContent=exactDate.toISOString()+' · '+exactDate.toLocaleTimeString();
  $('batchPointLabel').textContent='Point '+(batchIndex+1)+' / '+timeline.length+' · '+Number(point.timestamp_ms);
  $('batchCyclePosition').textContent=cyclePosition.toFixed(3)+' s';
  $('batchBoundaryReadout').textContent=boundaryReadout;
  $('batchTimelineStatus').textContent=(point.transition?'TRANSITION · ':'')+(point.unknown_reason?'UNKNOWN · '+point.unknown_reason:'determined');
  $('batchPhase').textContent=phase+(point.transition?' · transition':'');
  $('batchActiveMovements').textContent=movements.length?movements.map(item=>item.movement).join(', '):'—';
  $('batchPhaseConfidence').textContent=Number(point.confidence||0).toFixed(2);
  $('batchSignalState').textContent=stateText;
  $('batchPlayerPhase').textContent=phase;
  $('batchPlayerConfidence').textContent=Number(point.confidence||0).toFixed(2);
  $('batchUnknownReason').textContent=point.unknown_reason||'—';
  $('batchPlayerAdaptive').textContent=player.adaptive_mode||point.adaptive_mode||'BATCH_RECONSTRUCTION';
  renderBatchDetailList($('batchMovementStates'),movementLabels,'No movement state active at this timestamp.');
  renderBatchDetailList($('batchEvidence'),evidenceLabels.concat([
    'signal source '+(point.signal_source||'backend reconstruction'),
    'snapshot timestamp '+Number(point.timestamp_ms)
  ]),'No evidence metadata returned by backend.');
  renderSignalRenderer(point.signal_renderer||batchSession.signal_renderer||null);
  syncBatchTimelineActive();
}
function playBatch(){
  stopBatch();
  const timeline=playerTimeline();
  if(timeline.length<2)return;
  if(batchIndex>=timeline.length-1)batchIndex=0;
  const advance=()=>{
    if(batchIndex>=timeline.length-1){stopBatch();return}
    const current=timeline[batchIndex],next=timeline[batchIndex+1];
    const delay=Math.max(25,Math.min(5000,(Number(next.timestamp_ms)-Number(current.timestamp_ms))/Math.max(0.1,batchSpeed)));
    batchTimer=setTimeout(()=>{batchIndex++;renderBatchPoint();if(batchTimer)advance()},delay);
  };
  advance();
}
function stopBatch(){if(batchTimer){clearTimeout(batchTimer);batchTimer=null}}
function jumpBatch(kind){
  const nav=(batchSession&&batchSession.player&&batchSession.player.navigation)||{};
  const key=kind==='previous_phase'||kind==='next_phase'?'phase_starts':kind==='next_unknown'?'unknown':kind==='next_extension'?'extensions':'anomalies';
  const points=Array.isArray(nav[key])?nav[key]:[];
  if(!points.length)return;
  let target;
  if(kind==='previous_phase'){target=[...points].reverse().find(index=>index<batchIndex);if(target==null)target=points[points.length-1]}
  else {target=points.find(index=>index>batchIndex);if(target==null)target=points[0]}
  selectBatchIndex(target);
}
function currentRegimeFamily(){
  if(!batchAnalysis||!batchSession||!batchSession.regime_family_id)return null;
  return (batchAnalysis.regime_families||[]).find(item=>item.family_id===batchSession.regime_family_id)||null;
}
function effectiveTemplate(){
  if(!batchSession||batchSession.status!=='ok')return null;
  const template=batchSession.realtime_template_usability||{};
  const model=batchSession.realtime_phase_model;
  if(!template.usable||!model||!model.phases||!model.phases.length)return null;
  return {model,source:template.source||'realtime template',status:template.status||'USABLE'};
}
function usableTemplate(){
  return Boolean(effectiveTemplate());
}
function updateTemplateStatus(){
  const template=effectiveTemplate();
  if(template){
    $('templateStatus').textContent=template.status+' · '+template.source+' · coverage '+(Number(template.model.cycle_coverage||0)*100).toFixed(1)+'% · cycle '+Number(template.model.cycle_seconds).toFixed(1)+' s';
    $('templateStatus').className=template.status==='USABLE'?'ok':'warmup';
  }else{
    $('templateStatus').textContent=batchSession?'Impossible to determine a usable recurring phase model from the available traffic evidence.':'Run Batch on a reference archive first.';
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
  const template=effectiveTemplate();
  if(!template)return;
  form.append('phase_model',JSON.stringify(template.model));
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
      :'Realtime backend snapshot. UNKNOWN means the phase cannot be determined from the available evidence. Signal colors are modeled from the inferred phase, not observed lamps.');
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
  $('realtimeUnknownPostSync').textContent=unknown.post_sync_rate==null?'—':(unknown.post_sync_rate*100).toFixed(2)+'%';
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
  renderSignalRenderer(snapshot.signal_renderer||null);
}

function renderSignalRenderer(data){
  const holder=$('signalRenderer');
  holder.innerHTML='';
  if(!data||!Array.isArray(data.heads)){
    const empty=document.createElement('div');
    empty.className='muted small';
    empty.textContent='No configured signal renderer data.';
    holder.appendChild(empty);
    return;
  }
  holder.dataset.approachCount=String((data.approaches||[]).length);
  (data.approaches||[]).forEach(approach=>{
    const card=document.createElement('div');
    card.className='signal-approach';
    const title=document.createElement('div');
    title.className='signal-approach-title';
    const name=document.createElement('strong');
    name.textContent=approach;
    const heads=data.heads.filter(head=>head.approach===approach);
    const count=document.createElement('span');
    count.className='muted small';
    count.textContent=heads.length+' head'+(heads.length===1?'':'s');
    title.append(name,count);card.appendChild(title);
    heads.forEach(head=>{
      const headEl=document.createElement('div');
      headEl.className='signal-head '+(head.kind==='additional'?'additional':'');
      const headTitle=document.createElement('div');
      headTitle.className='signal-head-title';
      headTitle.textContent=head.id+(head.kind==='additional'?' · additional':' · main');
      headEl.appendChild(headTitle);
      (head.sections||[]).forEach(section=>{
        const row=document.createElement('div');
        row.className='signal-section '+(section.source==='MODELLED_TRANSITION'||section.source==='INFERRED_MODEL'?'source-modelled':'source-observed');
        const lamps=document.createElement('div');
        lamps.className='signal-lamps';
        ['RED','YELLOW','GREEN'].forEach(color=>{
          const lamp=document.createElement('span');
          lamp.className='signal-lamp '+color.toLowerCase()+(section.state===color?' on':'');
          lamps.appendChild(lamp);
        });
        (section.arrows||[]).forEach(arrow=>{
          const arrowEl=document.createElement('span');
          arrowEl.className='signal-lamp arrow';
          arrowEl.textContent=arrow==='left'?'←':arrow==='right'?'→':arrow==='straight'?'↑':arrow==='uturn'?'↶':'•';
          arrowEl.style.opacity=section.state==='UNKNOWN'?'0.35':'1';
          lamps.appendChild(arrowEl);
        });
        const meta=document.createElement('div');meta.className='signal-meta';
        const state=document.createElement('div');
        state.className='signal-state '+(section.state==='UNKNOWN'?'unknown':'');
        state.textContent=section.state;
        const movement=document.createElement('div');movement.className='signal-movement';
        movement.textContent=section.movement;
        const source=document.createElement('div');source.className='signal-source';
        source.textContent=section.source;
        const conf=document.createElement('div');conf.className='signal-confidence';
        conf.textContent='confidence '+Number(section.confidence||0).toFixed(2);
        meta.append(state,movement,source,conf);row.append(lamps,meta);headEl.appendChild(row);
      });
      card.appendChild(headEl);
    });
    holder.appendChild(card);
  });
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
