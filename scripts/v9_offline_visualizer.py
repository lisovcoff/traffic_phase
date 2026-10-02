from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

from app.core.v9.signal_renderer import (
    DEFAULT_ACTIVITY_THRESHOLD,
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    build_signal_model,
)
from app.core.v9.v9_discovery import discover_path


PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>V9 — офлайн-реконструкция светофора</title>
<style>
:root{
  color-scheme:dark;
  font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
  --bg:#0d1015;--panel:#171b22;--panel2:#10141a;--line:#303743;
  --text:#edf2f7;--muted:#8f9aaa;--green:#49d17d;--yellow:#f2cc5c;
  --red:#ef6576;--orange:#f29d5c;--blue:#8fb7ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text)}
main{max-width:1200px;margin:auto;padding:24px}
h1,h2,h3{margin:0}
p{line-height:1.45}
.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin-top:14px}
.stats{display:grid;grid-template-columns:repeat(6,minmax(120px,1fr));gap:10px}
.stat{background:var(--panel2);border-radius:10px;padding:11px}
.stat span{display:block;color:var(--muted);font-size:11px}
.stat strong{display:block;margin-top:5px;font-size:18px}
.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.controls{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
button,select,input{font:inherit}
button{border:0;border-radius:9px;padding:9px 14px;cursor:pointer;background:#2a3039;color:var(--text)}
button.primary{background:#f0f3f7;color:#111}
input[type=range]{width:100%}
.timeline{position:relative;height:44px;background:var(--panel2);border-radius:9px;overflow:hidden;margin-top:12px}
.segment{position:absolute;top:4px;bottom:4px;border-radius:5px;border:1px solid #4b5563}
.segment.active{outline:2px solid #fff;outline-offset:-2px}
.segment-label{position:absolute;left:6px;top:13px;font-size:10px;pointer-events:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.phase-0{background:#38534a}.phase-1{background:#4d445b}.phase-2{background:#5a4b3b}
.phase-3{background:#3f4f63}.phase-4{background:#5a3f50}.phase-other{background:#4b5563}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:11px;margin-top:5px}
.signal-heading{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.badge{padding:7px 10px;border-radius:9px;background:var(--panel2);border:1px solid var(--line);font-weight:700}
.signal-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:12px;margin-top:16px}
.approach{background:var(--panel2);border:1px solid var(--line);border-radius:13px;padding:13px}
.approach-title{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:9px}
.approach-title strong{font-size:18px}
.movement{display:grid;grid-template-columns:auto 1fr;gap:10px;align-items:center;background:#171b22;border:1px solid #343b46;border-radius:10px;padding:10px;margin-top:8px}
.lamps{display:flex;flex-direction:column;gap:6px}
.lamp{width:22px;height:22px;border-radius:50%;background:#262b32;border:1px solid #697586;opacity:.18}
.lamp.on{opacity:1;box-shadow:0 0 11px currentColor}
.lamp.red.on{color:var(--red);background:var(--red)}
.lamp.yellow.on{color:var(--yellow);background:var(--yellow)}
.lamp.green.on{color:var(--green);background:var(--green)}
.state{font-size:15px;font-weight:800}
.state.GREEN{color:var(--green)}.state.YELLOW{color:var(--yellow)}
.state.RED{color:var(--red)}.state.RED_YELLOW{color:var(--orange)}
.movement-name{font-size:12px;margin-top:3px}.source{font-size:10px;color:var(--muted);margin-top:4px}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:var(--muted)}
.notice{border-left:3px solid var(--blue)}
.notice strong{color:#dbe6f7}
@media(max-width:900px){.stats{grid-template-columns:repeat(3,minmax(120px,1fr))}.signal-grid{grid-template-columns:repeat(2,minmax(180px,1fr))}}
@media(max-width:620px){main{padding:14px}.stats{grid-template-columns:1fr 1fr}.signal-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
  <h1>V9 — офлайн-реконструкция светофора</h1>
  <p class="muted">Архив → V9 discovery → фазовый цикл → модельное состояние секций светофора.</p>

  <section class="panel stats">
    <div class="stat"><span>Траектории</span><strong id="trajectoryCount">—</strong></div>
    <div class="stat"><span>События</span><strong id="eventCount">—</strong></div>
    <div class="stat"><span>Потоки</span><strong id="streamCount">—</strong></div>
    <div class="stat"><span>Фазы</span><strong id="phaseCount">—</strong></div>
    <div class="stat"><span>Период</span><strong id="period">—</strong></div>
    <div class="stat"><span>Длительность</span><strong id="duration">—</strong></div>
  </section>

  <section class="panel">
    <div class="controls">
      <button class="primary" id="play">Воспроизвести</button>
      <button id="pause">Пауза</button>
      <label>Скорость
        <select id="speed">
          <option value="0.5">x0.5</option>
          <option value="1" selected>x1</option>
          <option value="2">x2</option>
          <option value="5">x5</option>
          <option value="20">x20</option>
          <option value="100">x100</option>
        </select>
      </label>
      <strong id="timeLabel">—</strong>
    </div>
    <input id="slider" type="range" min="0" max="0" step="0.1" value="0">
    <div class="timeline" id="timeline"></div>
    <div class="axis"><span id="axisStart">—</span><span id="axisEnd">—</span></div>
  </section>

  <section class="panel">
    <div class="signal-heading">
      <div>
        <h2 id="phaseTitle">Фаза —</h2>
        <p id="phaseMeta" class="muted">Позиция цикла —</p>
      </div>
      <div id="transitionBadge" class="badge">СТАБИЛЬНО</div>
    </div>
    <div id="signalGrid" class="signal-grid"></div>
    <div class="legend">
      <span>● ЗЕЛЁНЫЙ — движение активно в фазе</span>
      <span>● ЖЁЛТЫЙ — модельный переход GREEN → RED</span>
      <span>● КРАСНО-ЖЁЛТЫЙ — модельный переход RED → GREEN</span>
      <span>● КРАСНЫЙ — движение неактивно в фазе</span>
    </div>
  </section>

  <section class="panel notice">
    <strong>Семантика цветов:</strong>
    зелёный и красный выводятся из V9-активности потоков по фазам.
    Жёлтый и красный+жёлтый являются отдельной модельной переходной семантикой
    и не выдаются за прямое наблюдение лампы контроллера.
  </section>
</main>
<script>
const RESULT = __RESULT__;
const MODEL = __MODEL__;
const YELLOW_S = __YELLOW__;
const RED_YELLOW_S = __REDYELLOW__;

const RU = {N:"Север",S:"Юг",E:"Восток",W:"Запад"};
const RU_STATE = {
  GREEN:"ЗЕЛЁНЫЙ",YELLOW:"ЖЁЛТЫЙ",RED:"КРАСНЫЙ",
  RED_YELLOW:"КРАСНЫЙ + ЖЁЛТЫЙ"
};

let current = 0;
let timer = null;

function $(id){return document.getElementById(id)}
function movementLabel(value){
  const [a,b] = String(value).split("->");
  return (RU[a]||a) + " → " + (RU[b]||b);
}
function phaseName(id){
  const names = MODEL.phase_names || [];
  return names[id] || ("PHASE_" + String.fromCharCode(65+id));
}
function findSegment(t){
  const rows = MODEL.segments || [];
  for(let i=0;i<rows.length;i++){
    if(t >= Number(rows[i][0]) && t < Number(rows[i][1])) return {i,start:Number(rows[i][0]),end:Number(rows[i][1]),phase:Number(rows[i][2])};
  }
  if(rows.length){
    const r = rows[rows.length-1];
    return {i:rows.length-1,start:Number(r[0]),end:Number(r[1]),phase:Number(r[2])};
  }
  return null;
}
function adjacentPhase(index, direction){
  const rows = MODEL.segments || [];
  if(!rows.length) return null;
  const target = index + direction;
  const row = rows[(target % rows.length + rows.length) % rows.length];
  return Number(row[2]);
}
function stateAt(t){
  const seg = findSegment(t);
  if(!seg) return null;
  const previousPhase = adjacentPhase(seg.i,-1);
  const nextPhase = adjacentPhase(seg.i,1);
  const distanceFromStart = Math.max(0,t-seg.start);
  const distanceToEnd = Math.max(0,seg.end-t);
  const streams = [];
  for(const movement of Object.keys(MODEL.activity||{})){
    const pmap = MODEL.activity[movement] || {};
    const p = Number(pmap[seg.phase] || 0);
    const currentGreen = p >= Number(MODEL.activity_threshold || 0.05);
    const previousGreen = previousPhase != null && Number(pmap[previousPhase]||0) >= Number(MODEL.activity_threshold || 0.05);
    const nextGreen = nextPhase != null && Number(pmap[nextPhase]||0) >= Number(MODEL.activity_threshold || 0.05);
    let state = currentGreen ? "GREEN" : "RED";
    let source = "INFERRED_MODEL";
    if(currentGreen && !nextGreen && distanceToEnd > 0 && distanceToEnd <= YELLOW_S){
      state = "YELLOW"; source = "MODELLED_TRANSITION";
    }else if(currentGreen && !previousGreen && RED_YELLOW_S > 0 && distanceFromStart >= 0 && distanceFromStart < RED_YELLOW_S){
      state = "RED_YELLOW"; source = "MODELLED_TRANSITION";
    }
    streams.push({movement,approach:movement.split("->")[0],state,probability:p,source});
  }
  return {
    t,
    phase:seg.phase,
    phaseName:phaseName(seg.phase),
    cyclePosition:t % Number(MODEL.period_s),
    transition:streams.some(item=>item.source==="MODELLED_TRANSITION"),
    streams
  };
}
function pct(t){
  const rows = MODEL.segments || [];
  const duration = Number(RESULT.recording_duration_s || 0);
  if(duration<=0) return 0;
  return Math.max(0,Math.min(100,100*t/duration));
}
function buildTimeline(){
  const holder=$("timeline");
  holder.innerHTML="";
  const rows=MODEL.segments||[];
  rows.forEach((row,i)=>{
    const start=Number(row[0]), end=Number(row[1]), phase=Number(row[2]);
    const el=document.createElement("div");
    el.className="segment "+(phase<5?"phase-"+phase:"phase-other");
    el.style.left=pct(start)+"%";
    el.style.width=Math.max(0.15,pct(end)-pct(start))+"%";
    el.title=phaseName(phase)+" · "+start.toFixed(1)+"–"+end.toFixed(1)+" s";
    el.dataset.index=String(i);
    holder.appendChild(el);
  });
}
function render(){
  const snapshot=stateAt(current);
  if(!snapshot) return;
  $("slider").value=String(current);
  $("timeLabel").textContent=current.toFixed(1)+" s";
  $("phaseTitle").textContent="Фаза "+snapshot.phaseName.replace("PHASE_","");
  $("phaseMeta").textContent="Позиция цикла: "+snapshot.cyclePosition.toFixed(3)+" s · абсолютное: "+current.toFixed(1)+" s";
  $("transitionBadge").textContent=snapshot.transition?"МОДЕЛЬНЫЙ ПЕРЕХОД":"СТАБИЛЬНЫЙ РЕЖИМ";
  $("transitionBadge").style.borderColor=snapshot.transition?"#8d6b2f":"#303743";
  const grouped={};
  for(const item of snapshot.streams){
    (grouped[item.approach] ||= []).push(item);
  }
  const approaches=Object.keys(MODEL.approaches||{});
  const holder=$("signalGrid");
  holder.innerHTML="";
  approaches.forEach(approach=>{
    const card=document.createElement("div");
    card.className="approach";
    const title=document.createElement("div");
    title.className="approach-title";
    const strong=document.createElement("strong");
    strong.textContent=RU[approach]||approach;
    const small=document.createElement("span");
    small.className="muted";
    small.textContent=(grouped[approach]||[]).length+" сек.";
    title.append(strong,small);
    card.appendChild(title);
    (grouped[approach]||[]).forEach(item=>{
      const row=document.createElement("div");
      row.className="movement";
      const lamps=document.createElement("div");
      lamps.className="lamps";
      ["RED","YELLOW","GREEN"].forEach(color=>{
        const lamp=document.createElement("span");
        lamp.className="lamp "+color.toLowerCase()+(item.state===color?" on":"");
        lamps.appendChild(lamp);
      });
      const meta=document.createElement("div");
      const state=document.createElement("div");
      state.className="state "+item.state;
      state.textContent=RU_STATE[item.state]||item.state;
      const mv=document.createElement("div");
      mv.className="movement-name";
      mv.textContent=movementLabel(item.movement)+" · P="+Number(item.probability).toFixed(3);
      const source=document.createElement("div");
      source.className="source";
      source.textContent=item.source==="MODELLED_TRANSITION"?"МОДЕЛЬНЫЙ ПЕРЕХОД":"ПО V9-МОДЕЛИ";
      meta.append(state,mv,source);
      row.append(lamps,meta);
      card.appendChild(row);
    });
    holder.appendChild(card);
  });
}
function setCurrent(value){
  const max=Number($("slider").max||0);
  current=Math.max(0,Math.min(max,Number(value)||0));
  render();
}
function play(){
  stop();
  const speed=Number($("speed").value)||1;
  timer=setInterval(()=>{
    const next=current+Math.max(0.1,0.25*speed);
    if(next>=Number($("slider").max||0)){setCurrent(Number($("slider").max||0));stop();return}
    setCurrent(next);
  },250);
}
function stop(){if(timer){clearInterval(timer);timer=null}}
$("slider").addEventListener("input",e=>setCurrent(e.target.value));
$("play").addEventListener("click",play);
$("pause").addEventListener("click",stop);
$("speed").addEventListener("change",()=>{if(timer)play()});

$("trajectoryCount").textContent=String(RESULT.trajectory_count ?? "—");
$("eventCount").textContent=String(RESULT.event_count ?? "—");
$("streamCount").textContent=String(RESULT.movement_stream_count ?? "—");
$("phaseCount").textContent=String(RESULT.schedule?.phase_count ?? "—");
$("period").textContent=Number(RESULT.schedule?.period_s ?? 0).toFixed(3)+" s";
$("duration").textContent=Number(RESULT.recording_duration_s ?? 0).toFixed(1)+" s";
$("slider").max=String(Number(RESULT.recording_duration_s||0));
$("axisStart").textContent="0.0 s";
$("axisEnd").textContent=Number(RESULT.recording_duration_s||0).toFixed(1)+" s";
buildTimeline();
render();
</script>
</body>
</html>
"""


def _safe_json(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        encoded
        .replace("<", "\u003c")
        .replace(">", "\u003e")
        .replace("&", "\u0026")
    )


def render_html(
    result: dict[str, object],
    *,
    yellow_duration_seconds: float,
    red_yellow_duration_seconds: float,
    activity_threshold: float,
) -> str:
    model = build_signal_model(
        result,
        activity_threshold=activity_threshold,
    )
    page = PAGE.replace("__RESULT__", _safe_json(result))
    page = page.replace("__MODEL__", _safe_json(model))
    page = page.replace("__YELLOW__", str(float(yellow_duration_seconds)))
    page = page.replace("__REDYELLOW__", str(float(red_yellow_duration_seconds)))
    return page


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a self-contained HTML visualization from V9 archive analysis."
    )
    parser.add_argument(
        "input",
        type=Path,
        help="JSON file, ZIP archive or directory with JSON trajectory files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("v9_offline_report.html"),
    )
    parser.add_argument("--dt", type=float, default=1.0)
    parser.add_argument(
        "--yellow",
        type=float,
        default=DEFAULT_YELLOW_DURATION_SECONDS,
        help="modelled GREEN->RED transition duration in seconds",
    )
    parser.add_argument(
        "--red-yellow",
        type=float,
        default=DEFAULT_RED_YELLOW_DURATION_SECONDS,
        help="modelled RED->GREEN transition duration in seconds",
    )
    parser.add_argument(
        "--activity-threshold",
        type=float,
        default=DEFAULT_ACTIVITY_THRESHOLD,
        help="minimum V9 activity probability treated as active",
    )
    args = parser.parse_args()

    if args.yellow < 0 or args.red_yellow < 0:
        raise SystemExit("transition durations must be non-negative")
    if not 0 <= args.activity_threshold <= 1:
        raise SystemExit("activity threshold must be in [0, 1]")

    result = discover_path(args.input, dt=args.dt)
    page = render_html(
        result,
        yellow_duration_seconds=args.yellow,
        red_yellow_duration_seconds=args.red_yellow,
        activity_threshold=args.activity_threshold,
    )
    args.output.write_text(
        page,
        encoding="utf-8",
    )
    print("[V9] offline visualization complete")
    print("  input:", args.input)
    print("  output:", args.output)
    print("  phases:", result["phase_model_selection"]["selected_phase_count"])
    print(
        "  period_s:",
        round(float(result["period_inference"]["period_s"]), 3),
    )
    print(
        "  duration_s:",
        round(float(result["recording_duration_s"]), 3),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
