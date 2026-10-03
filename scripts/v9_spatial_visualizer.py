from __future__ import annotations

import argparse
import base64
import gzip
import json
from pathlib import Path
from typing import Any

from app.core.v10.semantic_mapping import (
    build_phase_specs_from_signal_plan_dict,
    map_v9_to_physical,
    normalized_segments,
)
from app.core.v9.events import load_source
from app.core.v9.signal_renderer import (
    DEFAULT_ACTIVITY_THRESHOLD,
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
    build_signal_model,
)
from app.core.v9.spatial import build_spatial_projection, compact_trajectories
from app.core.v9.v9_discovery import discover_path


PAGE = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>V9 — пространственная реконструкция перекрёстка</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;
--bg:#0d1015;--panel:#171b22;--panel2:#10141a;--line:#303743;--text:#edf2f7;
--muted:#8f9aaa;--green:#49d17d;--yellow:#f2cc5c;--red:#ef6576;--orange:#f29d5c;--blue:#63a4ff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text)}
main{max-width:1250px;margin:auto;padding:18px}
h1,h2,h3{margin:0}p{line-height:1.4}.muted{color:var(--muted)}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;margin-top:12px}
.toolbar,.controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.stats{display:grid;grid-template-columns:repeat(7,minmax(110px,1fr));gap:8px}
.stat{background:var(--panel2);border-radius:10px;padding:10px}
.stat span{display:block;color:var(--muted);font-size:10px}
.stat strong{display:block;margin-top:4px;font-size:17px}
button,select,input{font:inherit}
button{border:0;border-radius:8px;padding:8px 12px;cursor:pointer;background:#2a3039;color:var(--text)}
button.primary{background:#f0f3f7;color:#111}
button:disabled{opacity:.45;cursor:default}
input[type=range]{width:100%}
.layout{display:grid;grid-template-columns:minmax(560px,1fr) 320px;gap:12px}
.canvas-wrap{position:relative;background:#0b0e13;border-radius:12px;overflow:hidden}
#scene{display:block;width:100%;aspect-ratio:1/1}
.scene-badge{position:absolute;left:12px;top:12px;background:rgba(13,16,21,.82);border:1px solid #39414d;border-radius:9px;padding:7px 9px;font-size:12px}
.scene-badge.warning{border-color:#8d6b2f}
.side h3{font-size:15px;margin-bottom:8px}
.phase-card{display:flex;justify-content:space-between;gap:8px;padding:9px;background:var(--panel2);border-radius:9px;margin-top:7px}
.phase-card strong{font-size:13px}.phase-card span{color:var(--muted);font-size:11px}
.legend{display:grid;gap:7px;color:var(--muted);font-size:11px}
.legend-row{display:flex;align-items:center;gap:8px}
.dot{width:12px;height:12px;border-radius:50%}
.dot.green{background:var(--green)}.dot.yellow{background:var(--yellow)}.dot.red{background:var(--red)}.dot.car{background:var(--blue)}
.notice{border-left:3px solid var(--blue);font-size:12px}
.timeline{height:36px;background:var(--panel2);border-radius:8px;position:relative;overflow:hidden}
.timeline-segment{position:absolute;top:4px;bottom:4px;border-radius:4px;border:1px solid #566170;cursor:pointer}
.phase-0{background:#38534a}.phase-1{background:#4d445b}.phase-2{background:#5a4b3b}
.phase-3{background:#3f4f63}.phase-4{background:#5a3f50}.phase-other{background:#4b5563}
.axis{display:flex;justify-content:space-between;color:var(--muted);font-size:10px;margin-top:4px}
@media(max-width:950px){.layout{grid-template-columns:1fr}.stats{grid-template-columns:repeat(4,minmax(110px,1fr))}}
@media(max-width:600px){main{padding:10px}.stats{grid-template-columns:repeat(2,minmax(110px,1fr))}.panel{padding:11px}}
</style>
</head>
<body>
<main>
<h1>V9 — пространственная реконструкция перекрёстка</h1>
<p class="muted">N — сверху · S — снизу · E — справа · W — слева. Транспорт отображается только по detections исходного JSON.</p>

<section class="panel toolbar">
<button class="primary" id="play">▶ Воспроизвести</button>
<button id="pause">⏸ Пауза</button>
<button id="reset">↺ В начало</button>
<label>Скорость
<select id="speed">
<option value="0.5">x0.5</option><option value="1" selected>x1</option>
<option value="2">x2</option><option value="5">x5</option>
<option value="20">x20</option><option value="100">x100</option>
</select></label>
<strong id="timeLabel">—</strong>
</section>

<section class="panel">
<input id="slider" type="range" min="0" max="1" step="0.1" value="0">
<div class="axis"><span id="axisStart">—</span><span id="axisEnd">—</span></div>
</section>

<section class="stats">
<div class="stat"><span>Фаза</span><strong id="phase">—</strong></div>
<div class="stat"><span>Позиция цикла</span><strong id="cycle">—</strong></div>
<div class="stat"><span>Машины в кадре</span><strong id="vehicles">—</strong></div>
<div class="stat"><span>Период</span><strong id="period">—</strong></div>
<div class="stat"><span>Траектории</span><strong id="trajectoryCount">—</strong></div>
<div class="stat"><span>События</span><strong id="eventCount">—</strong></div>
<div class="stat"><span>Отклонение</span><strong id="anomaly">—</strong></div>
</section>

<section class="layout">
<div class="canvas-wrap panel">
<canvas id="scene"></canvas>
<div id="sceneBadge" class="scene-badge">Загрузка данных…</div>
</div>

<aside class="panel side">
<h3>Состояние светофоров</h3>
<div id="signalList"></div>

<div class="panel notice">
<strong>Семантика:</strong> <span id="semanticText">зелёный/красный — реконструкция V9 по активности потоков.
Жёлтый и красный+жёлтый — модельные переходы, а не прямое чтение контроллера.</span>
</div>

<h3 style="margin-top:14px">Фазы цикла</h3>
<div id="phaseList"></div>

<h3 style="margin-top:14px">Легенда</h3>
<div class="legend">
<div class="legend-row"><span class="dot green"></span> Зелёный</div>
<div class="legend-row"><span class="dot yellow"></span> Жёлтый</div>
<div class="legend-row"><span class="dot red"></span> Красный</div>
<div class="legend-row"><span class="dot car"></span> Точка транспорта из JSON</div>
</div>
<p id="error"></p>
<details style="margin-top:14px"><summary style="cursor:pointer">Диагностика V10</summary><pre id="v10Debug" class="muted" style="margin-top:8px;font:11px ui-monospace,monospace;white-space:pre-wrap"></pre></details>
</aside>
</section>

<section class="panel">
<div class="timeline" id="phaseTimeline"></div>
<div class="axis"><span>Начало анализа V9</span><span id="timelineEnd">—</span></div>
</section>
</main>

<script>
const RESULT = __RESULT__;
const SIGNAL_MODEL = __SIGNAL_MODEL__;
const PROJECTION = __PROJECTION__;
const PACKED_DATA = "__PACKED_DATA__";
const ANALYSIS_BASE_MS = Number(RESULT.analysis_base_timestamp_ms || 0);
const RECORDING_START_MS = Number(RESULT.recording_start_timestamp_ms || ANALYSIS_BASE_MS || 0);
const PHYSICAL = __PHYSICAL__;
const TIME_OFFSET_S = Number(PHYSICAL.time_offset_s || 0);
const DISPLAY_BASE_MS = Number(
  PHYSICAL.display_base_timestamp_ms || RECORDING_START_MS || ANALYSIS_BASE_MS || 0
);
const RECORDING_DURATION = Number(
  PHYSICAL.display_duration_s || RESULT.recording_duration_s || 0
);
const ACTIVITY_THRESHOLD = Number(SIGNAL_MODEL.activity_threshold || 0.05);
const YELLOW_S = __YELLOW__;
const RED_YELLOW_S = __REDYELLOW__;
const PHYSICAL_TOPOLOGY = __PHYSICAL_TOPOLOGY__;

let TRACKS = [];
let currentTime = 0;
let timer = null;
let tGlobal = 0;
let canvasScale = 1;

const APPROACHES = ["N","S","E","W"];
const APPROACH_LABELS = {N:"Север",S:"Юг",E:"Восток",W:"Запад"};
// Physical signal topology is inferred from recurring movement-phase evidence.
// A head always controls its incoming approach; only supported dedicated turn
// movements are rendered as additional physical sections.
const HEAD_SECTIONS = PHYSICAL.enabled ? PHYSICAL.topology : PHYSICAL_TOPOLOGY;
const ACTIVE_APPROACHES = PHYSICAL.enabled
  ? APPROACHES
  : (
      PROJECTION && PROJECTION.anchors &&
      Object.keys(PROJECTION.anchors).length
    )
    ? APPROACHES.filter(function(approach){
        return Object.prototype.hasOwnProperty.call(PROJECTION.anchors, approach);
      })
    : APPROACHES;
const LIGHT_POS = {
  N:{x:0.565,y:0.305}, S:{x:0.435,y:0.695},
  E:{x:0.695,y:0.565}, W:{x:0.305,y:0.435}
};

function $(id){return document.getElementById(id)}

async function unpackData(){
  const binary=Uint8Array.from(atob(PACKED_DATA),function(c){return c.charCodeAt(0)});
  if(typeof DecompressionStream==="undefined"){
    throw new Error("Браузер не поддерживает DecompressionStream. Используйте современный Chrome или Edge.");
  }
  const stream=new Blob([binary]).stream().pipeThrough(new DecompressionStream("gzip"));
  const bytes=new Uint8Array(await new Response(stream).arrayBuffer());
  return JSON.parse(new TextDecoder("utf-8").decode(bytes));
}

function phaseAt(t){
  const rows=PHYSICAL.enabled
    ? (PHYSICAL.stages || [])
    : (RESULT.schedule && RESULT.schedule.baseline_segments || []);
  if(!rows.length)return null;

  const period=Number(SIGNAL_MODEL.period_s || PHYSICAL.cycle_seconds || 0);
  const cycleTime=PHYSICAL.enabled
    ? Number(t) - TIME_OFFSET_S
    : Number(t);
  const localTime=PHYSICAL.enabled && period>0
    ? ((cycleTime%period)+period)%period
    : Number(t);

  for(let i=0;i<rows.length;i++){
    const start=PHYSICAL.enabled
      ? Number(rows[i].phase_start)
      : Number(rows[i][0]);
    const end=PHYSICAL.enabled
      ? Number(rows[i].phase_end)
      : Number(rows[i][1]);
    if(localTime>=start && localTime<end){
      return {
        index:i,
        start:start,
        end:end,
        phase:PHYSICAL.enabled
          ? String(rows[i].name)
          : Number(rows[i][2]),
        heads:PHYSICAL.enabled ? (rows[i].heads || {}) : null
      };
    }
  }

  if(PHYSICAL.enabled){
    const row=rows[0];
    return {
      index:0,
      start:Number(row.phase_start),
      end:Number(row.phase_end),
      phase:String(row.name),
      heads:row.heads || {}
    };
  }

  const row=rows[rows.length-1];
  return {
    index:rows.length-1,
    start:Number(row[0]),
    end:Number(row[1]),
    phase:Number(row[2]),
    heads:null
  };
}

function adjacentPhase(index,direction){
  const rows=PHYSICAL.enabled
    ? (PHYSICAL.stages || [])
    : (RESULT.schedule && RESULT.schedule.baseline_segments || []);
  if(!rows.length)return null;
  const j=((index+direction)%rows.length+rows.length)%rows.length;
  return PHYSICAL.enabled ? rows[j] : Number(rows[j][2]);
}

function probability(movement,phase){
  const map=(SIGNAL_MODEL.activity||{})[movement]||{};
  return Number(map[String(phase)] == null ? (map[phase] || 0) : map[String(phase)]);
}

function physicalSectionState(section,previousSection,nextSection,distanceFromStart,distanceToEnd){
  const currentState=section==="GREEN" ? "GREEN" : "RED";
  let state=currentState;
  const previousGreen=previousSection==="GREEN";
  const nextGreen=nextSection==="GREEN";
  if(currentState==="GREEN" && !nextGreen && distanceToEnd>0 && distanceToEnd<=YELLOW_S){
    state="YELLOW";
  }else if(currentState==="GREEN" && !previousGreen && distanceFromStart>=0 && distanceFromStart<RED_YELLOW_S){
    state="RED_YELLOW";
  }
  return state;
}

function physicalHeadInfo(approach,seg){
  const current=(seg.heads||{})[approach] || {main:"RED",arrows:{}};
  const previous=adjacentPhase(seg.index,-1);
  const next=adjacentPhase(seg.index,1);
  const previousHead=previous && previous.heads
    ? (previous.heads[approach] || {main:"RED",arrows:{}})
    : {main:"RED",arrows:{}};
  const nextHead=next && next.heads
    ? (next.heads[approach] || {main:"RED",arrows:{}})
    : {main:"RED",arrows:{}};

  const distanceFromStart=Math.max(0,tGlobal-seg.start);
  const distanceToEnd=Math.max(0,seg.end-tGlobal);

  const main=physicalSectionState(
    String(current.main || "RED"),
    String(previousHead.main || "RED"),
    String(nextHead.main || "RED"),
    distanceFromStart,
    distanceToEnd
  );

  const currentArrows=current.arrows || {};
  const previousArrows=previousHead.arrows || {};
  const nextArrows=nextHead.arrows || {};
  const arrows=Object.keys(currentArrows).sort().map(function(movement){
    const state=physicalSectionState(
      String(currentArrows[movement] || "RED"),
      String(previousArrows[movement] || "RED"),
      String(nextArrows[movement] || "RED"),
      distanceFromStart,
      distanceToEnd
    );
    return {
      movement:movement,
      state:state,
      probability:state==="RED" ? 0 : 1,
      peak:1,
      dominant_ratio:state==="RED" ? 0 : 1,
      transition:state==="YELLOW" || state==="RED_YELLOW",
      source:"V10_PHYSICAL_PLAN"
    };
  });

  return {
    main:{
      movement:HEAD_SECTIONS[approach].main,
      state:main,
      probability:main==="RED" ? 0 : 1,
      peak:1,
      dominant_ratio:main==="RED" ? 0 : 1,
      transition:main==="YELLOW" || main==="RED_YELLOW",
      source:"V10_PHYSICAL_PLAN"
    },
    arrows:arrows
  };
}

function movementState(movement,seg){
  const distanceFromStart=Math.max(0,tGlobal-seg.start);
  const distanceToEnd=Math.max(0,seg.end-tGlobal);

  if(PHYSICAL.enabled){
    // Kept only for compatibility with callers outside the V10 snapshot path.
    const currentPhase=(PHYSICAL.phases||[]).find(function(item){return item.name===String(seg.phase)}) || null;
    return {
      movement:movement,
      state:currentPhase && currentPhase.green_movements.includes(movement) ? "GREEN" : "RED",
      probability:currentPhase && currentPhase.green_movements.includes(movement) ? 1 : 0,
      peak:1,
      dominant_ratio:currentPhase && currentPhase.green_movements.includes(movement) ? 1 : 0,
      transition:false,
      source:"V10_PHYSICAL_PLAN"
    };
  }

  const current=probability(movement,seg.phase);
  const phaseValues=(SIGNAL_MODEL.activity||{})[movement]||{};
  const values=Object.values(phaseValues).map(Number).filter(Number.isFinite);
  const peak=values.length ? Math.max(...values) : 0;
  const dominantRatio=peak>0 ? current/peak : 0;
  const currentGreen=current>=ACTIVITY_THRESHOLD && dominantRatio>=0.70;
  const previousPhase=adjacentPhase(seg.index,-1);
  const nextPhase=adjacentPhase(seg.index,1);
  const previous=probability(movement,previousPhase);
  const next=probability(movement,nextPhase);
  const previousDominant=previous>=ACTIVITY_THRESHOLD &&
    (peak>0 ? previous/peak>=0.70 : false);
  const nextDominant=next>=ACTIVITY_THRESHOLD &&
    (peak>0 ? next/peak>=0.70 : false);
  let state=currentGreen ? "GREEN" : "RED";
  if(currentGreen && !nextDominant && distanceToEnd>0 && distanceToEnd<=YELLOW_S){
    state="YELLOW";
  }else if(currentGreen && !previousDominant && distanceFromStart>=0 && distanceFromStart<RED_YELLOW_S){
    state="RED_YELLOW";
  }
  return {
    movement:movement,
    state:state,
    probability:current,
    peak:peak,
    dominant_ratio:dominantRatio,
    transition:state==="YELLOW"||state==="RED_YELLOW",
    source:"INFERRED_MODEL"
  };
}

function headInfo(approach,seg){
  if(PHYSICAL.enabled){
    return physicalHeadInfo(approach,seg);
  }
  const sections=HEAD_SECTIONS[approach];
  const main=movementState(sections.main,seg);
  const arrows=sections.arrows.map(function(movement){return movementState(movement,seg)});
  return {main:main,arrows:arrows};
}

function signalSnapshot(t){
  const period=Number(SIGNAL_MODEL.period_s || PHYSICAL.cycle_seconds || 0);
  const cycleTime=PHYSICAL.enabled
    ? Number(t) - TIME_OFFSET_S
    : Number(t);
  tGlobal=PHYSICAL.enabled && period>0
    ? ((cycleTime%period)+period)%period
    : Number(t);
  const seg=phaseAt(t);
  if(!seg)return {phase:null,phaseName:"UNKNOWN",cyclePosition:t,approaches:{}};
  const heads={};
  for(const approach of ACTIVE_APPROACHES)heads[approach]=headInfo(approach,seg);
  return {
    phase:seg.phase,
    phaseName:PHYSICAL.enabled
      ? String(seg.phase)
      : ((SIGNAL_MODEL.phase_names||[])[seg.phase] || ("PHASE_"+String.fromCharCode(65+seg.phase))),
    cyclePosition:PHYSICAL.enabled && period>0
      ? ((cycleTime%period)+period)%period
      : ((t%Number(SIGNAL_MODEL.period_s))+Number(SIGNAL_MODEL.period_s))%Number(SIGNAL_MODEL.period_s),
    heads:heads
  };
}

function binarySearchDetections(detections,t){
  if(!detections.length || t<Number(detections[0][0]) || t>Number(detections[detections.length-1][0]))return -1;
  let lo=0,hi=detections.length-1;
  while(lo<=hi){
    const mid=(lo+hi)>>1;
    if(Number(detections[mid][0])<=t)lo=mid+1;
    else hi=mid-1;
  }
  return Math.max(0,Math.min(detections.length-2,lo-1));
}

function vehicleAt(track,t){
  const detections=track[3];
  const index=binarySearchDetections(detections,t);
  if(index<0)return null;
  const a=detections[index];
  const b=detections[Math.min(index+1,detections.length-1)];
  const ta=Number(a[0]),tb=Number(b[0]);
  const factor=tb>ta ? Math.max(0,Math.min(1,(t-ta)/(tb-ta))) : 0;
  return {
    x:Number(a[1])+(Number(b[1])-Number(a[1]))*factor,
    y:Number(a[2])+(Number(b[2])-Number(a[2]))*factor,
    angle:Math.atan2(Number(b[2])-Number(a[2]),Number(b[1])-Number(a[1]))
  };
}

function activeVehicles(t){
  const result=[];
  for(const track of TRACKS){
    const pos=vehicleAt(track,t);
    if(!pos)continue;
    if(pos.x<-0.08 || pos.x>1.08 || pos.y<-0.08 || pos.y>1.08)continue;
    result.push({track:track,pos:pos});
  }
  return result;
}

function drawRoad(ctx,w,h){
  ctx.clearRect(0,0,w,h);
  ctx.fillStyle="#222831";ctx.fillRect(0,0,w,h);

  const roadL=0.32*w,roadR=0.68*w,roadT=0.32*h,roadB=0.68*h;
  ctx.fillStyle="#3a4049";
  ctx.fillRect(roadL,0,roadR-roadL,h);
  ctx.fillRect(0,roadT,w,roadB-roadT);
  ctx.fillStyle="#262c34";
  ctx.fillRect(roadL,roadT,roadR-roadL,roadB-roadT);

  ctx.strokeStyle="#e0b83f";
  ctx.lineWidth=Math.max(1,1.5*canvasScale);
  ctx.setLineDash([12*canvasScale,10*canvasScale]);
  ctx.beginPath();
  ctx.moveTo(w*.5,0);ctx.lineTo(w*.5,roadT);
  ctx.moveTo(w*.5,roadB);ctx.lineTo(w*.5,h);
  ctx.moveTo(0,h*.5);ctx.lineTo(roadL,h*.5);
  ctx.moveTo(roadR,h*.5);ctx.lineTo(w,h*.5);
  ctx.stroke();ctx.setLineDash([]);

  ctx.strokeStyle="#f3f5f7";ctx.lineWidth=Math.max(2,2.4*canvasScale);
  ctx.beginPath();
  ctx.moveTo(roadL,roadT);ctx.lineTo(w*.44,roadT);
  ctx.moveTo(w*.56,roadT);ctx.lineTo(roadR,roadT);
  ctx.moveTo(roadL,roadB);ctx.lineTo(w*.44,roadB);
  ctx.moveTo(w*.56,roadB);ctx.lineTo(roadR,roadB);
  ctx.moveTo(roadL,h*.44);ctx.lineTo(roadL,h*.56);
  ctx.moveTo(roadR,h*.44);ctx.lineTo(roadR,h*.56);
  ctx.stroke();

  ctx.fillStyle="#c9cfd8";
  ctx.font="700 "+(14*canvasScale)+"px Inter,system-ui";
  ctx.textAlign="center";ctx.textBaseline="middle";
  ctx.fillText("N",w*.5,18*canvasScale);
  ctx.fillText("S",w*.5,h-18*canvasScale);
  ctx.fillText("W",18*canvasScale,h*.5);
  ctx.fillText("E",w-18*canvasScale,h*.5);
}

function lampColor(state,which){
  if(state==="GREEN")return which==="GREEN"?"#49d17d":"#252a31";
  if(state==="YELLOW")return which==="YELLOW"?"#f2cc5c":"#252a31";
  if(state==="RED")return which==="RED"?"#ef6576":"#252a31";
  if(state==="RED_YELLOW"){
    return which==="RED" ? "#ef6576" : which==="YELLOW" ? "#f2cc5c" : "#252a31";
  }
  return "#252a31";
}

function drawArrowSection(ctx,x,y,state,arrow,w,h){
  const px=x*w,py=y*h;
  const bodyW=34*canvasScale,bodyH=26*canvasScale;
  const left=px-bodyW/2,top=py-bodyH/2;
  ctx.fillStyle="#171b22";ctx.strokeStyle="#47505d";ctx.lineWidth=1.2*canvasScale;
  ctx.beginPath();ctx.roundRect(left,top,bodyW,bodyH,5*canvasScale);ctx.fill();ctx.stroke();

  const arrowGlyph=arrow.endsWith("N")?"↑":arrow.endsWith("S")?"↓":arrow.endsWith("E")?"→":"←";
  ctx.fillStyle=state==="GREEN"?"#49d17d":state==="YELLOW"?"#f2cc5c":"#252a31";
  ctx.font="800 "+(17*canvasScale)+"px Inter,system-ui";
  ctx.textAlign="center";ctx.textBaseline="middle";
  ctx.fillText(arrowGlyph,px,py+1*canvasScale);
}

function drawLight(ctx,x,y,head,approach,w,h){
  const px=x*w,py=y*h;
  const bodyW=34*canvasScale,bodyH=96*canvasScale;
  const left=px-bodyW/2,top=py-bodyH/2;

  ctx.fillStyle="#171b22";ctx.strokeStyle="#47505d";ctx.lineWidth=1.5*canvasScale;
  ctx.beginPath();ctx.roundRect(left,top,bodyW,bodyH,7*canvasScale);ctx.fill();ctx.stroke();

  const lamps=[
    {y:top+20*canvasScale,c:"RED"},
    {y:top+48*canvasScale,c:"YELLOW"},
    {y:top+76*canvasScale,c:"GREEN"}
  ];
  for(const item of lamps){
    ctx.beginPath();ctx.arc(px,item.y,9*canvasScale,0,Math.PI*2);
    ctx.fillStyle=lampColor(head.main.state,item.c);ctx.fill();ctx.strokeStyle="#697586";ctx.stroke();
  }

  ctx.fillStyle="#edf2f7";ctx.font="700 "+(11*canvasScale)+"px Inter,system-ui";
  ctx.textAlign="center";ctx.textBaseline="bottom";ctx.fillText(approach,px,top-5*canvasScale);

  head.arrows.forEach(function(section,index){
    // Keep additional sections adjacent to the main head in normalized canvas coordinates.
    const offsetX=(index+1)*30/w;
    const offsetY=27/h;
    drawArrowSection(ctx,x+offsetX,y+offsetY,section.state,section.movement,w,h);
  });
}

function drawVehicle(ctx,vehicle,w,h){
  const pos=vehicle.pos;
  const x=pos.x*w,y=pos.y*h,r=4.5*canvasScale;
  ctx.save();ctx.translate(x,y);ctx.rotate(pos.angle);
  ctx.fillStyle="#63a4ff";ctx.beginPath();ctx.arc(0,0,r,0,Math.PI*2);ctx.fill();
  ctx.strokeStyle="#dce8ff";ctx.lineWidth=Math.max(1,1.2*canvasScale);
  ctx.beginPath();ctx.moveTo(r,0);ctx.lineTo(r+4*canvasScale,0);ctx.stroke();
  ctx.restore();
}

function anomalyAt(t){
  const deviations=RESULT.anomaly_detection && RESULT.anomaly_detection.temporary_phase_deviations || [];
  for(const item of deviations){
    if(t>=Number(item.start_s)&&t<Number(item.end_s))return item;
  }
  return null;
}

function renderSignalList(snapshot){
  const holder=$("signalList");holder.innerHTML="";
  for(const approach of ACTIVE_APPROACHES){
    const head=snapshot.heads[approach] || {main:{state:"UNKNOWN",probability:0},arrows:[]};
    const row=document.createElement("div");row.className="phase-card";
    const left=document.createElement("strong");left.textContent=APPROACH_LABELS[approach];
    const right=document.createElement("span");
    const arrowText=head.arrows.map(function(item){
      return "доп. "+item.movement+" "+item.state;
    }).join(" · ");
    right.textContent="основной "+head.main.state+(PHYSICAL.enabled?"":" · P="+Number(head.main.probability||0).toFixed(3))+(arrowText?" · "+arrowText:"");
    right.style.color=head.main.state==="GREEN"?"var(--green)":head.main.state==="YELLOW"?"var(--yellow)":head.main.state==="RED_YELLOW"?"var(--orange)":"var(--red)";
    row.append(left,right);holder.appendChild(row);
  }
}

function renderPhases(){
  const holder=$("phaseList");holder.innerHTML="";
  const rows=PHYSICAL.enabled
    ? (PHYSICAL.stages || [])
    : (RESULT.schedule && RESULT.schedule.baseline_segments || []);
  const seen={};
  for(const row of rows){
    const phase=PHYSICAL.enabled ? String(row.name) : Number(row[2]);
    const key=String(phase);
    if(seen[key])continue;
    seen[key]=true;
    const card=document.createElement("div");card.className="phase-card";
    const name=document.createElement("strong");
    name.textContent=PHYSICAL.enabled
      ? String(phase)
      : ((SIGNAL_MODEL.phase_names||[])[phase] || ("PHASE_"+String.fromCharCode(65+phase)));
    const duration=document.createElement("span");
    const startTime=PHYSICAL.enabled ? Number(row.phase_start) : Number(row[0]);
    const endTime=PHYSICAL.enabled ? Number(row.phase_end) : Number(row[1]);
    duration.textContent=(endTime-startTime).toFixed(1)+" s";
    card.append(name,duration);holder.appendChild(card);
  }
}

function renderPhaseTimeline(){
  const holder=$("phaseTimeline");holder.innerHTML="";
  const rows=PHYSICAL.enabled
    ? (PHYSICAL.stages || [])
    : (RESULT.schedule && RESULT.schedule.baseline_segments || []);
  for(const row of rows){
    const phase=PHYSICAL.enabled ? String(row.name) : Number(row[2]);
    const element=document.createElement("button");element.type="button";
    element.className="timeline-segment "+(PHYSICAL.enabled ? "phase-other" : (phase<5?"phase-"+phase:"phase-other"));
    const start=PHYSICAL.enabled ? Number(row.phase_start) : Number(row[0]);
    const end=PHYSICAL.enabled ? Number(row.phase_end) : Number(row[1]);
    const timelineDuration=PHYSICAL.enabled
      ? Number(PHYSICAL.cycle_seconds || SIGNAL_MODEL.period_s || RECORDING_DURATION)
      : RECORDING_DURATION;
    element.style.left=(100*start/timelineDuration)+"%";
    element.style.width=Math.max(0.08,100*(end-start)/timelineDuration)+"%";
    const label=PHYSICAL.enabled
      ? String(phase)
      : ((SIGNAL_MODEL.phase_names||[])[phase]||phase);
    element.title="Фаза "+label+" · "+start.toFixed(1)+"–"+end.toFixed(1)+" s";
    element.addEventListener("click",function(){setCurrentTime(start)});
    holder.appendChild(element);
  }
}

function resizeCanvas(){
  const canvas=$("scene"),rect=canvas.getBoundingClientRect();
  canvasScale=window.devicePixelRatio||1;
  canvas.width=Math.max(1,Math.round(rect.width*canvasScale));
  canvas.height=Math.max(1,Math.round(rect.height*canvasScale));
  render();
}
window.addEventListener("resize",resizeCanvas);

function render(){
  tGlobal=currentTime;
  const snapshot=signalSnapshot(currentTime);
  const vehicles=activeVehicles(currentTime);

  const debugHeads={};
  for(const approach of APPROACHES){
    const head=snapshot.heads[approach] || {main:{state:"UNKNOWN"},arrows:[]};
    debugHeads[approach]={
      main:String(head.main && head.main.state || "UNKNOWN"),
      arrows:(head.arrows||[]).map(function(item){
        return String(item.movement)+"="+String(item.state);
      })
    };
  }
  const stage=(PHYSICAL.stages||[]).find(function(row){
    const start=Number(row.phase_start),end=Number(row.phase_end);
    return snapshot.cyclePosition>=start && snapshot.cyclePosition<end;
  }) || null;
  const debugState={
    renderer:"V10_spatial_visualizer",
    physical_enabled:Boolean(PHYSICAL.enabled),
    physical_reason:String(PHYSICAL.reason || ""),
    current_time_s:Number(currentTime.toFixed(3)),
    cycle_position_s:Number((snapshot.cyclePosition||0).toFixed(3)),
    phase:String(snapshot.phaseName||"UNKNOWN"),
    active_movements:stage ? (stage.active_movements||[]) : [],
    heads:debugHeads,
    active_vehicle_count:vehicles.length,
    timebase:{
      recording_start_ms:RECORDING_START_MS,
      analysis_base_ms:ANALYSIS_BASE_MS,
      offset_s:TIME_OFFSET_S,
      display_base_ms:DISPLAY_BASE_MS
    }
  };
  window.__V10_DEBUG__=debugState;
  const debugNode=$("v10Debug");
  if(debugNode)debugNode.textContent=JSON.stringify(debugState,null,2);
  if(Boolean(PHYSICAL.enabled)){
    console.info("[V10_RENDER]",debugState);
  }else{
    console.warn("[V10_RENDER_DISABLED]",debugState);
  }
  const canvas=$("scene"),ctx=canvas.getContext("2d");
  drawRoad(ctx,canvas.width,canvas.height);
  for(const vehicle of vehicles)drawVehicle(ctx,vehicle,canvas.width,canvas.height);
  for(const approach of ACTIVE_APPROACHES){
    const head=snapshot.heads[approach] || {main:{state:"UNKNOWN"},arrows:[]};
    drawLight(ctx,LIGHT_POS[approach].x,LIGHT_POS[approach].y,head,approach,canvas.width,canvas.height);
  }

  const anomaly=anomalyAt(currentTime);
  $("phase").textContent=snapshot.phaseName==="UNKNOWN"?"UNKNOWN":snapshot.phaseName.replace(/^PHASE_/,"");
  $("cycle").textContent=Number(snapshot.cyclePosition||0).toFixed(2)+" s";
  $("vehicles").textContent=String(vehicles.length);
  $("timeLabel").textContent=new Date(DISPLAY_BASE_MS+currentTime*1000).toLocaleString()+" · T+"+currentTime.toFixed(1)+" s";
  $("anomaly").textContent=anomaly?"⚠ "+anomaly.type+" · "+Number(anomaly.delta_s).toFixed(1)+" s":"Нет";
  $("sceneBadge").textContent=(PHYSICAL.enabled
    ? "V10 · физический план · "
    : "V10 OFF · "+String(PHYSICAL.reason || "physical plan unavailable")+" · ")
    +"N ↑ · S ↓ · W ← · E → · "+vehicles.length+" машин";
  $("sceneBadge").className="scene-badge"+(anomaly?" warning":"");
  $("semanticText").textContent=PHYSICAL.enabled
    ? "зелёный/красный — по V10 physical phase mapping и заданному плану сигналов. Жёлтый и красный+жёлтый — модельные переходы."
    : "V10 physical plan ОТКЛЮЧЁН: "+String(PHYSICAL.reason || "причина не передана")+". Сейчас отображается fallback V9, а не физические головы.";
  renderSignalList(snapshot);
  $("slider").value=String(currentTime);
}

function setCurrentTime(value){
  currentTime=Math.max(0,Math.min(RECORDING_DURATION,Number(value)||0));
  render();
}

function play(){
  stop();
  let previous=performance.now();
  function frame(now){
    const delta=Math.min(.25,(now-previous)/1000);previous=now;
    const speed=Number($("speed").value)||1;
    setCurrentTime(currentTime+delta*speed);
    if(currentTime>=RECORDING_DURATION){stop();return}
    timer=requestAnimationFrame(frame);
  }
  timer=requestAnimationFrame(frame);
}

function stop(){
  if(timer){cancelAnimationFrame(timer);timer=null}
}

$("play").addEventListener("click",play);
$("pause").addEventListener("click",stop);
$("reset").addEventListener("click",function(){stop();setCurrentTime(0)});
$("slider").addEventListener("input",function(e){setCurrentTime(e.target.value)});
$("speed").addEventListener("change",function(){if(timer)play()});

async function init(){
  try{
    TRACKS=await unpackData();
    $("trajectoryCount").textContent=String(RESULT.trajectory_count||0);
    $("eventCount").textContent=String(RESULT.event_count||0);
    $("period").textContent=Number(RESULT.schedule && RESULT.schedule.period_s || 0).toFixed(3)+" s";
    $("slider").max=String(RECORDING_DURATION);
    $("axisStart").textContent="T+0.0 s · "+new Date(DISPLAY_BASE_MS).toLocaleTimeString();
    $("axisEnd").textContent="T+"+RECORDING_DURATION.toFixed(1)+" s · "+new Date(DISPLAY_BASE_MS+RECORDING_DURATION*1000).toLocaleTimeString();
    $("timelineEnd").textContent=new Date(DISPLAY_BASE_MS+RECORDING_DURATION*1000).toLocaleTimeString();
    renderPhases();renderPhaseTimeline();resizeCanvas();render();
  }catch(error){
    $("error").textContent=String(error.message||error);
    $("sceneBadge").textContent="Ошибка загрузки данных";
  }
}
init();
</script>
</body>
</html>
"""


def _safe_json(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


def _pack_data(trajectories: list[list[Any]]) -> str:
    raw=json.dumps(trajectories,ensure_ascii=False,separators=(",",":")).encode("utf-8")
    return base64.b64encode(gzip.compress(raw,compresslevel=6)).decode("ascii")


def _phase_activity(result: dict[str, Any]) -> dict[str, dict[int, float]]:
    activity: dict[str, dict[int, float]] = {}
    rows = result.get("schedule", {}).get("stream_activity_by_phase", [])
    phase_names = result.get("schedule", {}).get("phase_names", [])
    for row in rows:
        movement = str(row.get("stream", ""))
        values = row.get("event_probability_by_phase", {})
        if not movement or not isinstance(values, dict):
            continue
        phase_map: dict[int, float] = {}
        for key, value in values.items():
            try:
                phase = phase_names.index(key) if key in phase_names else int(key)
                phase_map[int(phase)] = float(value)
            except (ValueError, TypeError):
                continue
        if phase_map:
            activity[movement] = phase_map
    return activity


def infer_physical_signal_topology(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Infer which approaches need physical additional arrow sections.

    Straight movements are always the main signal. A turn becomes a physical
    additional section only when there is repeated material evidence for a
    reciprocal turn pair sharing the same dominant phase. This prevents weak
    residual streams such as W->S from becoming fabricated hardware.
    """
    approaches = ("N", "S", "E", "W")
    topology = {
        approach: {
            "main": f"{approach}->{ {'N':'S','S':'N','E':'W','W':'E'}[approach] }",
            "arrows": [],
        }
        for approach in approaches
    }
    activity = _phase_activity(result)
    candidates: dict[str, tuple[float, int]] = {}
    for movement, phase_values in activity.items():
        if "->" not in movement:
            continue
        source, target = movement.split("->", 1)
        if source not in approaches or target not in approaches or source == target:
            continue
        # Straight-through movement is already the main signal of this
        # approach. It must never be represented as an additional arrow
        # section, even when its reciprocal movement has strong evidence.
        main_target = {"N": "S", "S": "N", "E": "W", "W": "E"}[source]
        if target == main_target:
            continue
        peak_phase, peak_value = max(phase_values.items(), key=lambda item: item[1])
        # 0.08 rejects the Lenina W->S residual (0.0759), while retaining
        # N->E (0.1093) and E->N (0.0948).
        if peak_value >= 0.08:
            candidates[movement] = (float(peak_value), int(peak_phase))

    for movement, (peak_value, peak_phase) in candidates.items():
        source, target = movement.split("->", 1)
        reverse = f"{target}->{source}"
        if reverse not in candidates:
            continue
        if candidates[reverse][1] != peak_phase:
            continue
        topology[source]["arrows"].append(movement)

    for approach in approaches:
        topology[approach]["arrows"].sort()
    return topology


def _head_states_from_movements(movements: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, Any]]:
    """Normalize one V10 stage into explicit physical head states."""
    green = {str(item).strip() for item in movements if str(item).strip()}
    opposite = {"N": "S", "S": "N", "E": "W", "W": "E"}
    result: dict[str, dict[str, Any]] = {}
    for approach in ("N", "S", "E", "W"):
        main = f"{approach}->{opposite[approach]}"
        arrows = sorted(
            movement
            for movement in green
            if movement.startswith(f"{approach}->")
            and movement != main
        )
        result[approach] = {
            "main": "GREEN" if main in green else "RED",
            "arrows": {
                movement: "GREEN"
                for movement in arrows
            },
        }
    return result


def _physical_visual_model(
    result: dict[str, Any],
    physical_plan: dict[str, Any] | None,
) -> dict[str, Any]:
    if physical_plan is None:
        physical_plan = result.get("physical_signal_plan")
    if not isinstance(physical_plan, dict) or not physical_plan.get("enabled"):
        return {
            "enabled": False,
            "phases": [],
            "segments": [],
            "topology": {},
            "reason": (
                str(physical_plan.get("reason", "physical plan unavailable"))
                if isinstance(physical_plan, dict)
                else "physical plan unavailable"
            ),
        }

    specs = build_phase_specs_from_signal_plan_dict(physical_plan)
    if physical_plan.get("auto_inferred") and isinstance(physical_plan.get("mapping"), dict):
        mapping = physical_plan["mapping"]
        mapping_payload = {
            "mapping": mapping,
            "confidence": physical_plan.get("confidence", 0.0),
            "scores": {},
        }
    else:
        resolved = map_v9_to_physical(result, specs)
        mapping = resolved.mapping
        mapping_payload = resolved.to_dict()
    # V10 stages are already in cycle-local coordinates and carry the
    # authoritative head states. Do not rebuild them from V9 baseline rows at
    # render time; that duplicated mapping was the source of state divergence.
    stages: list[dict[str, Any]] = []
    raw_stages = physical_plan.get("stages", ())
    if isinstance(raw_stages, (list, tuple)):
        for raw in raw_stages:
            if not isinstance(raw, dict):
                continue
            try:
                start = float(raw.get("phase_start", 0.0))
                end = float(raw.get("phase_end", 0.0))
            except (TypeError, ValueError):
                continue
            if end <= start:
                continue
            active_movements = [
                str(item).strip()
                for item in raw.get("active_movements", ())
                if str(item).strip()
            ]
            heads = raw.get("heads")
            if not isinstance(heads, dict):
                heads = _head_states_from_movements(active_movements)
            stages.append({
                "stage_id": int(raw.get("stage_id", len(stages) + 1)),
                "name": str(raw.get("name", "")),
                "phase_start": start,
                "phase_end": end,
                "active_movements": active_movements,
                "additional_movements": [
                    str(item).strip()
                    for item in raw.get("additional_movements", ())
                    if str(item).strip()
                ],
                "source_phase": raw.get("source_phase"),
                "heads": heads,
            })

    if stages:
        segments = [
            [stage["phase_start"], stage["phase_end"], stage["name"]]
            for stage in stages
        ]
    else:
        segments = normalized_segments(result, mapping)
        by_name_spec = {spec.name: spec for spec in specs}
        for index, (start, end, name) in enumerate(segments, start=1):
            spec = by_name_spec.get(str(name))
            active_movements = sorted(spec.green_movements) if spec else []
            additional_movements = sorted(spec.additional_movements) if spec else []
            stages.append({
                "stage_id": index,
                "name": str(name),
                "phase_start": float(start),
                "phase_end": float(end),
                "active_movements": active_movements,
                "additional_movements": additional_movements,
                "source_phase": None,
                "heads": _head_states_from_movements(active_movements),
            })

    topology = {
        approach: {
            "main": f"{approach}->{ {'N':'S','S':'N','E':'W','W':'E'}[approach] }",
            "arrows": [],
        }
        for approach in ("N", "S", "E", "W")
    }
    for spec in specs:
        # The visual topology must not depend solely on the optional
        # additional_movements field. Some V10 plans can carry a turn in
        # green_movements while the derived additional list is incomplete.
        # Any non-straight green movement is therefore rendered as a physical
        # arrow section on its incoming approach.
        for movement in spec.green_movements:
            if "->" not in movement:
                continue
            approach, target = movement.split("->", 1)
            main_target = {"N": "S", "S": "N", "E": "W", "W": "E"}.get(approach)
            if (
                approach in topology
                and target in {"N", "S", "E", "W"}
                and target != main_target
            ):
                topology[approach]["arrows"].append(movement)
    for approach in topology:
        topology[approach]["arrows"] = sorted(set(topology[approach]["arrows"]))

    phases = [
        {
            "name": spec.name,
            "green_movements": sorted(spec.green_movements),
            "additional_movements": sorted(spec.additional_movements),
            "duration_s": spec.duration_s,
        }
        for spec in specs
    ]
    analysis_base_ms = float(
        result.get("analysis_base_timestamp_ms", 0.0) or 0.0
    )
    recording_start_value = result.get("recording_start_timestamp_ms")
    recording_start_ms = (
        float(recording_start_value)
        if recording_start_value is not None
        else analysis_base_ms
    )
    time_offset_s = (analysis_base_ms - recording_start_ms) / 1000.0
    display_duration_s = float(
        result.get("recording_duration_s", 0.0) or 0.0
    )

    return {
        "enabled": True,
        "mapping": mapping_payload,
        "segments": segments,
        "stages": stages,
        "phases": phases,
        "topology": topology,
        "time_offset_s": round(time_offset_s, 6),
        "display_base_timestamp_ms": recording_start_ms,
        "display_duration_s": round(display_duration_s, 6),
    }


def render_html(result,projection,trajectories,*,yellow_duration_seconds=3.0,
                red_yellow_duration_seconds=2.0,activity_threshold=0.05,
                physical_plan=None,time_offset_s=None,display_duration_s=None):
    signal_model=build_signal_model(result,activity_threshold=activity_threshold)
    physical=_physical_visual_model(result,physical_plan)
    if time_offset_s is not None:
        physical["time_offset_s"] = float(time_offset_s)
    if display_duration_s is not None:
        physical["display_duration_s"] = float(display_duration_s)
    page=PAGE.replace("__RESULT__",_safe_json(result))
    page=page.replace("__SIGNAL_MODEL__",_safe_json(signal_model))
    page=page.replace("__PROJECTION__",_safe_json(projection))
    page=page.replace("__PACKED_DATA__",_pack_data(trajectories))
    page=page.replace("__YELLOW__",str(float(yellow_duration_seconds)))
    page=page.replace("__REDYELLOW__",str(float(red_yellow_duration_seconds)))
    page=page.replace("__PHYSICAL_TOPOLOGY__",_safe_json(infer_physical_signal_topology(result)))
    page=page.replace("__PHYSICAL__",_safe_json(physical))
    return page


def build_spatial_visualization(
    input_path: Path,
    *,
    dt: float = 1.0,
    yellow_duration_seconds: float = DEFAULT_YELLOW_DURATION_SECONDS,
    red_yellow_duration_seconds: float = DEFAULT_RED_YELLOW_DURATION_SECONDS,
    activity_threshold: float = DEFAULT_ACTIVITY_THRESHOLD,
    physical_plan_path: Path | None = None,
) -> dict[str, Any]:
    """Build the canonical spatial HTML used by both CLI and Uvicorn."""
    input_path = Path(input_path)
    if dt <= 0:
        raise ValueError("dt must be positive")
    if yellow_duration_seconds < 0 or red_yellow_duration_seconds < 0:
        raise ValueError("transition durations must be non-negative")
    if not 0 <= activity_threshold <= 1:
        raise ValueError("activity_threshold must be in [0,1]")

    tracks, _source_files = load_source(input_path)
    # Use the canonical path-based discovery for JSON and ZIP inputs.
    # It streams large archives and applies the same large-recording regime
    # selection as the standalone V9 discovery command.
    result = discover_path(
        input_path,
        dt=float(dt),
    )
    physical_plan = (
        json.loads(physical_plan_path.read_text(encoding="utf-8"))
        if physical_plan_path is not None
        else result.get("physical_signal_plan")
    )
    projection = build_spatial_projection(tracks)
    display_base_ms = (
        float(result["recording_start_timestamp_ms"])
        if result.get("recording_start_timestamp_ms") is not None
        else float(result["analysis_base_timestamp_ms"])
    )
    analysis_base_ms = float(result["analysis_base_timestamp_ms"])
    time_offset_s = (analysis_base_ms - display_base_ms) / 1000.0
    display_duration_s = float(result["recording_duration_s"]) + max(
        0.0,
        time_offset_s,
    )
    compact = compact_trajectories(
        tracks,
        analysis_base_timestamp_ms=analysis_base_ms,
        display_base_timestamp_ms=display_base_ms,
        projection=projection,
    )
    physical_plan = result.get("physical_signal_plan") or {
        "enabled": False,
        "reason": "physical_signal_plan missing from V9 result",
    }
    html = render_html(
        result,
        projection,
        compact,
        yellow_duration_seconds=float(yellow_duration_seconds),
        red_yellow_duration_seconds=float(red_yellow_duration_seconds),
        activity_threshold=float(activity_threshold),
        physical_plan=physical_plan,
        time_offset_s=time_offset_s,
        display_duration_s=display_duration_s,
    )
    return {
        "html": html,
        "result": result,
        "physical_plan": physical_plan,
        "projection": projection,
        "rendered_trajectory_count": len(compact),
        "trajectory_count": len(tracks),
    }

def main()->int:
    parser=argparse.ArgumentParser(description="Create V9 spatial offline visualization.")
    parser.add_argument("input",type=Path)
    parser.add_argument("--output",type=Path,default=Path("v9_spatial.html"))
    parser.add_argument("--dt",type=float,default=1.0)
    parser.add_argument("--yellow",type=float,default=DEFAULT_YELLOW_DURATION_SECONDS)
    parser.add_argument("--red-yellow",type=float,default=DEFAULT_RED_YELLOW_DURATION_SECONDS)
    parser.add_argument("--activity-threshold",type=float,default=DEFAULT_ACTIVITY_THRESHOLD)
    parser.add_argument(
        "--physical-plan",
        type=Path,
        default=None,
        help="JSON physical signal plan/catalog consumed by V10 semantics",
    )
    args=parser.parse_args()

    if args.dt<=0:raise SystemExit("--dt must be positive")
    if args.yellow<0 or args.red_yellow<0:raise SystemExit("transition durations must be non-negative")
    if not 0<=args.activity_threshold<=1:raise SystemExit("--activity-threshold must be in [0,1]")

    built=build_spatial_visualization(
        args.input,
        dt=args.dt,
        yellow_duration_seconds=args.yellow,
        red_yellow_duration_seconds=args.red_yellow,
        activity_threshold=args.activity_threshold,
        physical_plan_path=args.physical_plan,
    )
    html=built["html"]
    result=built["result"]
    projection=built["projection"]
    args.output.write_text(html,encoding="utf-8")
    print("[V9] spatial offline visualization complete")
    print("  input:",args.input)
    print("  output:",args.output)
    print("  phases:",result["phase_model_selection"]["selected_phase_count"])
    print("  period_s:",round(float(result["period_inference"]["period_s"]),3))
    print("  trajectories:",result["trajectory_count"])
    print("  rendered_trajectories:",built["rendered_trajectory_count"])
    print("  html_size_mb:",round(len(html.encode("utf-8"))/1024/1024,2))
    print("  projection:",projection["method"])
    return 0


if __name__=="__main__":
    raise SystemExit(main())