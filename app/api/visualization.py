from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.core.playback import build_playback_payload

router = APIRouter(prefix="/visualization", tags=["visualization"])


@router.get("", response_class=HTMLResponse)
def visualization_page() -> str:
    return r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Traffic intersection playback</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}*{box-sizing:border-box}body{margin:0;background:#0d0f13;color:#eef2f7}main{max-width:1240px;margin:0 auto;padding:24px}h1{margin:0;font-size:30px}.subtitle{color:#9da6b3;margin:6px 0 18px}.panel{background:#171a20;border:1px solid #2a2f38;border-radius:14px;padding:16px;margin-top:14px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.btn{border:0;border-radius:9px;padding:10px 15px;font:inherit;cursor:pointer}.btn.primary{background:#e9eef6;color:#111}.btn.secondary{background:#2c323b;color:#eef}.btn:disabled{opacity:.45;cursor:default}input[type=file]{max-width:300px}.timeline{width:100%;margin:16px 0 5px}.time-row{display:flex;justify-content:space-between;color:#9da6b3;font-size:13px}.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.stat{background:#101218;border-radius:10px;padding:11px}.stat span{display:block;color:#99a2af;font-size:12px}.stat strong{display:block;margin-top:4px;font-size:17px}.phase-title{display:flex;justify-content:space-between;gap:10px;align-items:center}.badge{padding:6px 9px;border-radius:999px;background:#252b34;color:#dbe2ec;font-size:12px}.cycle-map{display:flex;height:64px;overflow:hidden;border-radius:10px;margin-top:12px;border:1px solid #303641}.phase-segment{display:flex;flex-direction:column;justify-content:center;padding:6px 9px;min-width:58px;border-right:1px solid #12151a;background:#252a32}.phase-segment b{font-size:13px}.phase-segment small{color:#aeb6c1;margin-top:2px}
.intersection-panel{padding:18px}.intersection-title{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.intersection-title strong{font-size:20px}.intersection-title small{display:block;color:#9da6b3;margin-top:4px}.intersection-wrap{display:flex;justify-content:center;margin-top:14px}.intersection{position:relative;width:min(760px,86vw);aspect-ratio:1/1;overflow:hidden;border-radius:18px;border:1px solid #343a44;background:#12151a;box-shadow:0 20px 50px rgba(0,0,0,.28)}.road{position:absolute;background:#30353d}.road.vertical{left:32%;top:0;width:36%;height:100%}.road.horizontal{left:0;top:32%;width:100%;height:36%}.lane-divider{position:absolute;background:repeating-linear-gradient(to bottom,#d9dde3 0 24px,transparent 24px 42px)}.lane-divider.v{left:49.6%;top:0;width:2px;height:100%;opacity:.65}.lane-divider.h{top:49.6%;left:0;height:2px;width:100%;opacity:.65;background:repeating-linear-gradient(to right,#d9dde3 0 24px,transparent 24px 42px)}.center-box{position:absolute;left:32%;top:32%;width:36%;height:36%;border:2px solid rgba(235,240,247,.24);background:rgba(18,21,26,.1)}.crosswalk{position:absolute;opacity:.72;background:repeating-linear-gradient(90deg,#eef2f7 0 7px,transparent 7px 14px)}.crosswalk.top,.crosswalk.bottom{left:34%;width:32%;height:15px}.crosswalk.top{top:28%}.crosswalk.bottom{bottom:28%}.crosswalk.left,.crosswalk.right{top:34%;height:32%;width:15px;background:repeating-linear-gradient(0deg,#eef2f7 0 7px,transparent 7px 14px)}.crosswalk.left{left:28%}.crosswalk.right{right:28%}.stop-line{position:absolute;background:#eef2f7}.stop-line.top,.stop-line.bottom{left:32%;width:36%;height:4px}.stop-line.top{top:29.5%}.stop-line.bottom{bottom:29.5%}.stop-line.left,.stop-line.right{top:32%;width:4px;height:36%}.stop-line.left{left:29.5%}.stop-line.right{right:29.5%}.arrow{position:absolute;color:#f2f4f7;font-size:28px;font-weight:700;opacity:.75;line-height:1}.arrow.n{left:39%;top:18%}.arrow.s{right:39%;bottom:18%}.arrow.w{left:18%;bottom:39%}.arrow.e{right:18%;top:39%}.approach-label{position:absolute;color:#aeb6c1;font-weight:800;font-size:12px;letter-spacing:.12em;text-transform:uppercase}.approach-label.n{top:7px;left:50%;transform:translateX(-50%)}.approach-label.s{bottom:7px;left:50%;transform:translateX(-50%)}.approach-label.w{left:7px;top:50%;transform:translateY(-50%)}.approach-label.e{right:7px;top:50%;transform:translateY(-50%)}.mini-signal{position:absolute;width:58px;padding:7px 6px;border-radius:14px;background:#0b0d10;border:1px solid #454b55;box-shadow:0 8px 22px rgba(0,0,0,.32);z-index:8}.mini-signal.n{top:22px;left:50%;transform:translateX(-50%)}.mini-signal.s{bottom:22px;left:50%;transform:translateX(-50%)}.mini-signal.w{left:22px;top:50%;transform:translateY(-50%)}.mini-signal.e{right:22px;top:50%;transform:translateY(-50%)}.mini-signal .lamp{width:34px;height:34px;border-radius:50%;margin:4px auto;background:#20242b;box-shadow:inset 0 0 0 2px #333944}.mini-signal .lamp.on.red{background:#ed5367;box-shadow:0 0 14px rgba(237,83,103,.55)}.mini-signal .lamp.on.yellow{background:#f4ce4e;box-shadow:0 0 14px rgba(244,206,78,.5)}.mini-signal .lamp.on.green{background:#2fd078;box-shadow:0 0 14px rgba(47,208,120,.5)}.mini-signal .signal-state{text-align:center;font-size:10px;color:#dbe2ec;font-weight:800;margin-top:3px}.cars-layer{position:absolute;inset:0;z-index:5;pointer-events:none}.car{position:absolute;border-radius:6px;background:#b9c1cd;border:2px solid #edf1f6;box-shadow:0 3px 8px rgba(0,0,0,.45);opacity:.92}.car.v{width:16px;height:30px}.car.h{width:30px;height:16px}.car.n{left:calc(50% - 68px)}.car.s{left:calc(50% + 52px)}.car.w{top:calc(50% + 52px)}.car.e{top:calc(50% - 68px)}.car.moving.n{animation:move-n 3.8s linear infinite}.car.moving.s{animation:move-s 3.8s linear infinite}.car.moving.w{animation:move-w 3.8s linear infinite}.car.moving.e{animation:move-e 3.8s linear infinite}.car.moving.yellow{animation-duration:5s}.car.queued.n{top:calc(29% - var(--q));}.car.queued.s{bottom:calc(29% - var(--q));}.car.queued.w{left:calc(29% - var(--q));}.car.queued.e{right:calc(29% - var(--q));}.car.fade{opacity:.32}.car-label{position:absolute;z-index:9;padding:4px 7px;border-radius:999px;background:rgba(10,12,15,.76);border:1px solid #3e444d;color:#dbe2ec;font-size:11px}.car-label.n{top:12%;left:calc(50% - 95px)}.car-label.s{bottom:12%;left:calc(50% + 78px)}.car-label.w{left:12%;bottom:calc(50% - 92px)}.car-label.e{right:12%;top:calc(50% - 92px)}.intersection-legend{display:flex;justify-content:center;gap:14px;flex-wrap:wrap;margin-top:12px;color:#aeb6c1;font-size:12px}.legend-item{display:flex;align-items:center;gap:6px}.legend-dot{width:10px;height:10px;border-radius:50%;display:inline-block}.legend-dot.green{background:#2fd078}.legend-dot.yellow{background:#f4ce4e}.legend-dot.red{background:#ed5367}.legend-dot.redyellow{background:linear-gradient(90deg,#ed5367 0 50%,#f4ce4e 50%)}.intersection-note{text-align:center;color:#848d9a;font-size:11px;margin-top:8px}
.bottom{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:14px}.evidence table{width:100%;border-collapse:collapse}.evidence th,.evidence td{text-align:left;padding:8px;border-bottom:1px solid #2a2f38;font-size:13px}.evidence th{color:#9da6b3;font-weight:500}.validation{line-height:1.5;color:#c8ced8}.validation strong{color:#fff}.validation .warn{color:#f2cb67}pre{margin:0;background:#0f1116;padding:12px;border-radius:10px;overflow:auto;max-height:340px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.hidden{display:none}.review-actions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0}.review-note{color:#9da6b3;font-size:12px;margin-top:5px}
@keyframes move-n{from{top:-8%;}to{top:108%}}@keyframes move-s{from{top:108%;}to{top:-8%}}@keyframes move-w{from{left:-8%;}to{left:108%}}@keyframes move-e{from{left:108%;}to{left:-8%}}
@media(max-width:900px){.stats{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){main{padding:14px}.stats{grid-template-columns:repeat(2,1fr)}.mini-signal{transform:scale(.88)}.mini-signal.n,.mini-signal.s{margin-left:0}.mini-signal.w,.mini-signal.e{margin-top:0}}
</style>
</head>
<body>
<main>
<h1>Traffic intersection playback</h1>
<div class="subtitle">Top-down reconstruction of the intersection. Signal colors are inferred from vehicle trajectories, not measured directly.</div>
<div id="status" class="panel" style="color:#aeb6c1">Choose a trajectory JSON and load it.</div>
<div class="panel toolbar"><input id="file" type="file" accept=".json,application/json"><button id="load" class="btn primary" disabled>Load JSON</button><button id="play" class="btn secondary" disabled>Play</button><button id="pause" class="btn secondary" disabled>Pause</button></div>
<div id="app" class="hidden">
  <div class="panel"><input id="timeline" class="timeline" type="range" min="0" max="0" step="1" value="0"><div class="time-row"><span id="leftTime">0.000 s</span><span id="rightTime">0.000 s</span></div></div>
  <div class="panel stats">
    <div class="stat"><span>Simulated time</span><strong id="simTime">—</strong></div>
    <div class="stat"><span>Real millis</span><strong id="timestamp">—</strong></div>
    <div class="stat"><span>Current phase</span><strong id="phase">—</strong></div>
    <div class="stat"><span>Phase confidence</span><strong id="confidence">—</strong></div>
    <div class="stat"><span>Estimated cycle</span><strong id="cycle">—</strong></div>
    <div class="stat"><span>Vehicles used</span><strong id="cars">—</strong></div>
  </div>
  <div class="panel"><div class="phase-title"><div><strong>Cycle map</strong><div style="color:#9da6b3;font-size:13px;margin-top:3px">The model alternates two opposing traffic groups.</div></div><div class="badge">Ground truth: unavailable</div></div><div id="cycleMap" class="cycle-map"></div></div>
  <div class="panel intersection-panel">
    <div class="intersection-title"><div><strong>Intersection view</strong><small>Right-hand traffic. Mini signal heads are placed at the four approaches; cars are illustrative and seeded from recent traffic evidence.</small></div><div class="badge" id="intersectionStatus">—</div></div>
    <div class="intersection-wrap">
      <div class="intersection" id="intersection">
        <div class="road vertical"></div><div class="road horizontal"></div><div class="lane-divider v"></div><div class="lane-divider h"></div><div class="center-box"></div>
        <div class="crosswalk top"></div><div class="crosswalk bottom"></div><div class="crosswalk left"></div><div class="crosswalk right"></div>
        <div class="stop-line top"></div><div class="stop-line bottom"></div><div class="stop-line left"></div><div class="stop-line right"></div>
        <div class="arrow n">↓</div><div class="arrow s">↑</div><div class="arrow w">→</div><div class="arrow e">←</div>
        <div class="approach-label n">N</div><div class="approach-label s">S</div><div class="approach-label w">W</div><div class="approach-label e">E</div>
        <div class="mini-signal n" id="signal-N"></div><div class="mini-signal s" id="signal-S"></div><div class="mini-signal w" id="signal-W"></div><div class="mini-signal e" id="signal-E"></div>
        <div class="car-label n">N approach</div><div class="car-label s">S approach</div><div class="car-label w">W approach</div><div class="car-label e">E approach</div>
        <div class="cars-layer" id="carsLayer"></div>
      </div>
    </div>
    <div class="intersection-legend"><span class="legend-item"><span class="legend-dot green"></span>GREEN — cars move</span><span class="legend-item"><span class="legend-dot yellow"></span>YELLOW — transition out</span><span class="legend-item"><span class="legend-dot red"></span>RED — cars queue</span><span class="legend-item"><span class="legend-dot redyellow"></span>RED+YELLOW — transition in</span></div>
    <div class="intersection-note">The car animation is a visual explanation of the inferred phase, not a replay of individual vehicle trajectories.</div>
  </div>
  <div class="bottom">
    <div class="panel evidence"><strong>Recent traffic evidence</strong><div style="color:#9da6b3;font-size:12px;margin:4px 0 8px">Evidence is diagnostic; it does not override the phase model.</div><table><thead><tr><th>Side</th><th>Inferred</th><th>Evidence</th><th>Confidence</th></tr></thead><tbody id="evidenceBody"></tbody></table></div>
    <div class="panel validation"><strong>How to read the reconstruction</strong><p><strong>1.</strong> GREEN/YELLOW/RED+YELLOW follow the inferred signal phase.</p><p><strong>2.</strong> Moving trajectories provide positive evidence for the active group.</p><p><strong>3.</strong> Brief conflicting movement near a phase boundary can come from the 12 s diagnostic window.</p><p class="warn"><strong>Important:</strong> the source JSON has no measured traffic-light state, so the reconstruction is a consistency model, not direct controller telemetry.</p></div>
  </div>
  <div class="panel"><strong>Review log for manual checking</strong><div class="review-note">Copy or download this log and send it here for analysis.</div><div class="review-actions"><button id="copyLog" class="btn secondary" disabled>Copy review log</button><button id="downloadLog" class="btn secondary" disabled>Download review.log</button></div><pre id="reviewLog">—</pre></div>
  <div class="panel"><strong>Diagnostic snapshot</strong><pre id="diagnostic">—</pre></div>
</div>
<script>
const $=id=>document.getElementById(id);let payload=null,index=0,timer=null,playing=false;
$('file').addEventListener('change',()=>{$('load').disabled=!$('file').files.length});
$('load').addEventListener('click',async()=>{const file=$('file').files[0];if(!file)return;$('status').textContent='Reconstructing intersection…';try{const form=new FormData();form.append('file',file);const r=await fetch('/visualization/playback',{method:'POST',body:form});if(!r.ok)throw new Error(await r.text());payload=await r.json();index=0;playing=false;$('timeline').max=String(Math.max(0,payload.timeline.length-1));$('timeline').value='0';$('play').disabled=false;$('pause').disabled=false;$('copyLog').disabled=false;$('downloadLog').disabled=false;$('app').classList.remove('hidden');$('status').textContent=`Loaded ${payload.source.filename}. Timeline is sampled every 0.5 s from the raw millis origin.`;$('cycle').textContent=payload.cycle.estimated_seconds.toFixed(2)+' s';$('cars').textContent=payload.source.cars_used;buildCycleMap();render();$('reviewLog').textContent=payload.review_log}catch(e){$('status').textContent='Error: '+e.message}});
$('timeline').addEventListener('input',()=>{index=Number($('timeline').value);render()});$('play').addEventListener('click',play);$('pause').addEventListener('click',pause);
$('copyLog').addEventListener('click',async()=>{if(!payload)return;await navigator.clipboard.writeText(payload.review_log);$('status').textContent='Review log copied. Send it here for analysis.'});
$('downloadLog').addEventListener('click',()=>{if(!payload)return;const blob=new Blob([payload.review_log],{type:'text/plain;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='review.log';a.click();URL.revokeObjectURL(a.href)});
function play(){if(!payload||playing||payload.timeline.length<2)return;if(index>=payload.timeline.length-1)index=0;playing=true;const tick=()=>{if(!playing)return;const a=payload.timeline[index],b=payload.timeline[index+1];const delay=Math.max(1,b.timestamp_ms-a.timestamp_ms);timer=setTimeout(()=>{index++;$('timeline').value=String(index);render();tick()},delay)};tick()}
function pause(){playing=false;if(timer)clearTimeout(timer);timer=null}
function buildCycleMap(){const map=$('cycleMap');map.innerHTML='';const cycle=payload.cycle.estimated_seconds;for(const p of payload.phase_model.phases){const width=Math.max(5,((p.phase_end-p.phase_start+cycle)%cycle)/cycle*100);const d=document.createElement('div');d.className='phase-segment';d.style.width=width+'%';d.innerHTML=`<b>Phase ${p.phase_id}</b><small>${p.phase_start.toFixed(0)}–${p.phase_end.toFixed(0)} s · ${(p.active_approaches||[]).join('/')||'—'}</small>`;map.appendChild(d)}}
function lamp(cls,on){return `<div class="lamp ${cls}${on?' on':''}"></div>`}
function signalHtml(state){return `${lamp('red',state==='RED'||state==='RED_YELLOW')}${lamp('yellow',state==='YELLOW'||state==='RED_YELLOW')}${lamp('green',state==='GREEN')}<div class="signal-state">${state}</div>`}
function carCount(evidence){if(!evidence||evidence<=0)return 0;return Math.max(1,Math.min(5,Math.round(evidence)))}
function renderCars(item){const layer=$('carsLayer');layer.innerHTML='';for(const a of ['N','S','E','W']){const state=item.approaches[a].state;const count=carCount(item.approaches[a].evidence_weight);for(let i=0;i<count;i++){const car=document.createElement('div');const queue=i*34+12;const moving=state==='GREEN'||state==='YELLOW';const sideClass=a.toLowerCase();const vertical=a==='N'||a==='S';car.className=`car ${vertical?'v':'h'} ${sideClass} ${moving?'moving':'queued'} ${state==='YELLOW'?'yellow':''}${state==='UNKNOWN'?' fade':''}`;car.style.setProperty('--q',queue+'px');if(moving){const phase=(i/count)*-3.8;car.style.animationDelay=phase+'s'}layer.appendChild(car)}}}
function render(){const item=payload.timeline[index];$('simTime').textContent=item.timestamp_s.toFixed(3)+' s';$('timestamp').textContent=String(item.timestamp_ms);$('phase').textContent=item.phase_id==null?'UNKNOWN':`Phase ${item.phase_id}${item.transition?' · TRANSITION':''}`;$('confidence').textContent=item.phase_confidence.toFixed(2);$('leftTime').textContent=item.timestamp_s.toFixed(3)+' s';$('rightTime').textContent=payload.source.duration_s.toFixed(3)+' s';const phase=payload.phase_model.phases.find(p=>p.phase_id===item.phase_id);$('intersectionStatus').textContent=phase?`Active: ${phase.active_approaches.join(' / ')}`:'No modeled phase';for(const a of ['N','S','E','W']){$('signal-'+a).innerHTML=signalHtml(item.approaches[a].state)}renderCars(item);$('evidenceBody').innerHTML='';for(const a of ['N','S','E','W']){const s=item.approaches[a];const tr=document.createElement('tr');tr.innerHTML=`<td>${a}</td><td>${s.state}</td><td>${s.evidence_weight.toFixed(2)}</td><td>${s.confidence.toFixed(2)}</td>`;$('evidenceBody').appendChild(tr)}$('diagnostic').textContent=JSON.stringify({timestamp_ms:item.timestamp_ms,timestamp_s:item.timestamp_s,cycle_phase_s:item.cycle_phase_s,phase_id:item.phase_id,phase_confidence:item.phase_confidence,transition:item.transition,active_approaches:phase?phase.active_approaches:[],states:Object.fromEntries(['N','S','E','W'].map(a=>[a,item.approaches[a].state])),ground_truth:payload.ground_truth,model:payload.model},null,2)}
</script>
</body>
</html>
"""


@router.post("/playback")
async def visualization_playback(file: UploadFile = File(...)) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".json"):
        raise HTTPException(status_code=400, detail="Only JSON trajectory files are supported")

    payload = await file.read()
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            tmp.write(payload)
            temp_path = Path(tmp.name)
        return build_playback_payload(temp_path)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
