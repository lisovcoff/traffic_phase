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
<title>Traffic signal playback</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#0d0f13;color:#eef2f7}main{max-width:1240px;margin:0 auto;padding:24px}
h1{margin:0;font-size:30px}.subtitle{color:#9da6b3;margin:6px 0 18px}.panel{background:#171a20;border:1px solid #2a2f38;border-radius:14px;padding:16px;margin-top:14px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.btn{border:0;border-radius:9px;padding:10px 15px;font:inherit;cursor:pointer}.btn.primary{background:#e9eef6;color:#111}.btn.secondary{background:#2c323b;color:#eef}.btn:disabled{opacity:.45;cursor:default}
input[type=file]{max-width:300px}.timeline{width:100%;margin:16px 0 5px}.time-row{display:flex;justify-content:space-between;color:#9da6b3;font-size:13px}
.stats{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.stat{background:#101218;border-radius:10px;padding:11px}.stat span{display:block;color:#99a2af;font-size:12px}.stat strong{display:block;margin-top:4px;font-size:17px}
.phase-title{display:flex;justify-content:space-between;gap:10px;align-items:center}.badge{padding:6px 9px;border-radius:999px;background:#252b34;color:#dbe2ec;font-size:12px}.cycle-map{display:flex;height:64px;overflow:hidden;border-radius:10px;margin-top:12px;border:1px solid #303641}.phase-segment{display:flex;flex-direction:column;justify-content:center;padding:6px 9px;min-width:58px;border-right:1px solid #12151a;background:#252a32}.phase-segment.active{background:#263b32}.phase-segment b{font-size:13px}.phase-segment small{color:#aeb6c1;margin-top:2px}
.signals{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:14px}.signal-card{background:#171a20;border:1px solid #2a2f38;border-radius:14px;padding:16px;position:relative}.approach{font-size:18px;font-weight:700}.signal-head{width:76px;margin:14px auto 10px;padding:9px 10px;background:#0e1014;border-radius:18px;border:1px solid #303640}.lamp{width:46px;height:46px;border-radius:50%;margin:6px auto;background:#20242b;box-shadow:inset 0 0 0 3px #333944}.lamp.on.red{background:#ed5367;box-shadow:0 0 18px rgba(237,83,103,.45)}.lamp.on.yellow{background:#f4ce4e;box-shadow:0 0 18px rgba(244,206,78,.4)}.lamp.on.green{background:#2fd078;box-shadow:0 0 18px rgba(47,208,120,.4)}.state-label{text-align:center;font-size:21px;font-weight:800}.support{text-align:center;color:#9da6b3;font-size:12px;margin-top:5px}.unknown-note{text-align:center;color:#aeb6c1;font-size:12px;margin-top:6px}
.bottom{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:14px}.evidence table{width:100%;border-collapse:collapse}.evidence th,.evidence td{text-align:left;padding:8px;border-bottom:1px solid #2a2f38;font-size:13px}.evidence th{color:#9da6b3;font-weight:500}.validation{line-height:1.5;color:#c8ced8}.validation strong{color:#fff}.validation .warn{color:#f2cb67}
pre{margin:0;background:#0f1116;padding:12px;border-radius:10px;overflow:auto;max-height:340px;font:12px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}.hidden{display:none}
@media(max-width:900px){.stats{grid-template-columns:repeat(3,1fr)}.signals{grid-template-columns:repeat(2,1fr)}.bottom{grid-template-columns:1fr}}@media(max-width:620px){.stats{grid-template-columns:repeat(2,1fr)}.signals{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
<h1>Traffic signal playback</h1>
<div class="subtitle">Reconstructed state of the intersection from vehicle trajectories. The colors are inferred, not measured.</div>
<div id="status" class="panel" style="color:#aeb6c1">Choose a trajectory JSON and load it.</div>
<div class="panel toolbar"><input id="file" type="file" accept=".json,application/json"><button id="load" class="btn primary" disabled>Load JSON</button><button id="play" class="btn secondary" disabled>Play</button><button id="pause" class="btn secondary" disabled>Pause</button></div>
<div id="app" class="hidden">
  <div class="panel">
    <input id="timeline" class="timeline" type="range" min="0" max="0" step="1" value="0">
    <div class="time-row"><span id="leftTime">0.000 s</span><span id="rightTime">0.000 s</span></div>
  </div>
  <div class="panel stats">
    <div class="stat"><span>Simulated time</span><strong id="simTime">—</strong></div>
    <div class="stat"><span>Real millis</span><strong id="timestamp">—</strong></div>
    <div class="stat"><span>Current phase</span><strong id="phase">—</strong></div>
    <div class="stat"><span>Phase confidence</span><strong id="confidence">—</strong></div>
    <div class="stat"><span>Estimated cycle</span><strong id="cycle">—</strong></div>
    <div class="stat"><span>Vehicles used</span><strong id="cars">—</strong></div>
  </div>
  <div class="panel">
    <div class="phase-title"><div><strong>Cycle map</strong><div style="color:#9da6b3;font-size:13px;margin-top:3px">Colored segment = inferred active phase. Yellow is the transition interval.</div></div><div id="groundTruth" class="badge">Ground truth: unavailable</div></div>
    <div id="cycleMap" class="cycle-map"></div>
  </div>
  <div class="signals" id="signals"></div>
  <div class="bottom">
    <div class="panel evidence"><strong>Recent traffic evidence</strong><div style="color:#9da6b3;font-size:12px;margin:4px 0 8px">Supporting data in the last 12 s. It does not override a reliable phase model.</div><table><thead><tr><th>Side</th><th>Inferred</th><th>Evidence weight</th><th>Confidence</th></tr></thead><tbody id="evidenceBody"></tbody></table></div>
    <div class="panel validation"><strong>How to judge the result</strong><p><strong>1.</strong> At a phase change, the active pair should switch to the other group.</p><p><strong>2.</strong> During GREEN, release activity on the active approaches should recur at similar cycle positions.</p><p><strong>3.</strong> During RED, waiting traffic should accumulate on the inactive approaches.</p><p class="warn"><strong>Important:</strong> no labeled traffic-light timestamps are present in the supplied data, so this UI cannot prove that the inferred color is the real controller state. It exposes the evidence needed for manual sanity checks.</p></div>
  </div>
  <div class="panel"><strong>Diagnostic snapshot</strong><pre id="diagnostic">—</pre></div>
</div>
<script>
const $=id=>document.getElementById(id);let payload=null,index=0,timer=null,playing=false;
$('file').addEventListener('change',()=>{$('load').disabled=!$('file').files.length});
$('load').addEventListener('click',async()=>{const file=$('file').files[0];if(!file)return;$('status').textContent='Reconstructing cycle and phases…';try{const form=new FormData();form.append('file',file);const r=await fetch('/visualization/playback',{method:'POST',body:form});if(!r.ok)throw new Error(await r.text());payload=await r.json();index=0;playing=false;$('timeline').max=String(Math.max(0,payload.timeline.length-1));$('timeline').value='0';$('play').disabled=false;$('pause').disabled=false;$('app').classList.remove('hidden');$('status').textContent=`Loaded ${payload.source.filename}. Playback uses observed millis timestamps.`;$('cycle').textContent=payload.cycle.estimated_seconds.toFixed(2)+' s';$('cars').textContent=payload.source.cars_used;buildCycleMap();render();}catch(e){$('status').textContent='Error: '+e.message}});
$('timeline').addEventListener('input',()=>{index=Number($('timeline').value);render()});$('play').addEventListener('click',play);$('pause').addEventListener('click',pause);
function play(){if(!payload||playing||payload.timeline.length<2)return;if(index>=payload.timeline.length-1)index=0;playing=true;const tick=()=>{if(!playing)return;const a=payload.timeline[index],b=payload.timeline[index+1];const delay=Math.max(1,b.timestamp_ms-a.timestamp_ms);timer=setTimeout(()=>{index++;$('timeline').value=String(index);render();tick()},delay)};tick()}
function pause(){playing=false;if(timer)clearTimeout(timer);timer=null}
function buildCycleMap(){const map=$('cycleMap');map.innerHTML='';const cycle=payload.cycle.estimated_seconds||1;for(const p of payload.phase_model.phases){const width=Math.max(5,((p.phase_end-p.phase_start+cycle)%cycle)/cycle*100);const d=document.createElement('div');d.className='phase-segment';d.style.width=width+'%';d.innerHTML=`<b>Phase ${p.phase_id}</b><small>${p.phase_start.toFixed(0)}–${p.phase_end.toFixed(0)} s · ${(p.active_approaches||[]).join('/')||'—'}</small>`;map.appendChild(d)}}
function lamp(cls,on){return `<div class="lamp ${cls}${on?' on':''}"></div>`}
function render(){const item=payload.timeline[index];$('simTime').textContent=item.timestamp_s.toFixed(3)+' s';$('timestamp').textContent=String(item.timestamp_ms);$('phase').textContent=item.phase_id==null?'UNKNOWN':`Phase ${item.phase_id}${item.transition?' · TRANSITION':''}`;$('confidence').textContent=item.phase_confidence.toFixed(2);$('leftTime').textContent=item.timestamp_s.toFixed(3)+' s';$('rightTime').textContent=payload.source.duration_s.toFixed(3)+' s';const phase=payload.phase_model.phases.find(p=>p.phase_id===item.phase_id);$('signals').innerHTML='';$('evidenceBody').innerHTML='';for(const a of ['N','S','E','W']){const s=item.approaches[a];const card=document.createElement('section');card.className='signal-card';card.innerHTML=`<div class="approach">${a}</div><div class="signal-head">${lamp('red',s.state==='RED')}${lamp('yellow',s.state==='YELLOW')}${lamp('green',s.state==='GREEN')}</div><div class="state-label">${s.state}</div><div class="support">model confidence ${s.confidence.toFixed(2)} · evidence ${s.evidence_weight.toFixed(2)}</div><div class="unknown-note">${s.state==='UNKNOWN'?'No reliable phase at this moment':'State is inferred from the current phase model'}</div>`;$('signals').appendChild(card);const tr=document.createElement('tr');tr.innerHTML=`<td>${a}</td><td>${s.state}</td><td>${s.evidence_weight.toFixed(2)}</td><td>${s.confidence.toFixed(2)}</td>`;$('evidenceBody').appendChild(tr)};$('diagnostic').textContent=JSON.stringify({timestamp_ms:item.timestamp_ms,timestamp_s:item.timestamp_s,cycle_phase_s:item.cycle_phase_s,phase_id:item.phase_id,phase_confidence:item.phase_confidence,transition:item.transition,active_approaches:phase?phase.active_approaches:[],states:Object.fromEntries(['N','S','E','W'].map(a=>[a,item.approaches[a].state]))},null,2)}
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
