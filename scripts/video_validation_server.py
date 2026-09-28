from __future__ import annotations

import argparse
import json
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Видео ↔ реконструкция светофора</title>
<style>
:root{
  color-scheme:dark;
  --bg:#0d1117;--panel:#151b24;--border:#2a3442;--muted:#9aa6b5;
  --text:#eef3f8;--green:#39d77d;--yellow:#f2c94c;--red:#ef6676;--unknown:#aab3be;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1500px;margin:0 auto;padding:18px}
h1,h2,h3{margin:0}
h1{font-size:24px}.muted{color:var(--muted)}
.small{font-size:12px}
.toolbar,.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px}
.toolbar{padding:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:14px 0}
button{border:1px solid var(--border);border-radius:9px;background:#111721;color:var(--text);padding:9px 12px;cursor:pointer}
button:hover{border-color:#4a586d}button.primary{background:#243246}
input[type="datetime-local"]{background:#111721;color:var(--text);border:1px solid var(--border);border-radius:8px;padding:8px}
.layout{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(360px,.9fr);gap:14px}
.panel{padding:14px}
video{width:100%;display:block;border-radius:9px;background:#000;max-height:70vh}
.video-meta{display:flex;gap:16px;flex-wrap:wrap;margin-top:9px}
.controls{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px}
.big-time{font-size:20px;font-weight:700}
.signal-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}
.signal-card{border:1px solid var(--border);background:#10151d;border-radius:10px;padding:12px;text-align:center}
.signal-card h3{font-size:16px;margin-bottom:7px}
.lamps{display:flex;justify-content:center;gap:7px;margin:7px 0}
.lamp{width:18px;height:18px;border-radius:50%;opacity:.18;box-shadow:inset 0 0 0 1px #000}
.lamp.on.red{background:var(--red);opacity:1}.lamp.on.yellow{background:var(--yellow);opacity:1}.lamp.on.green{background:var(--green);opacity:1}
.state{font-weight:800;font-size:16px}.state-RED{color:var(--red)}.state-YELLOW{color:var(--yellow)}.state-GREEN{color:var(--green)}.state-RED_YELLOW{color:#f1a15d}.state-UNKNOWN{color:var(--unknown)}
.card-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:12px}
.metric{border:1px solid var(--border);background:#10151d;border-radius:10px;padding:11px}
.metric span{display:block;color:var(--muted);font-size:11px}.metric strong{display:block;font-size:17px;margin-top:4px}
.timeline-wrap{margin-top:14px}.timeline{position:relative;height:44px;border:1px solid var(--border);border-radius:9px;overflow:hidden;background:#0f141b;cursor:pointer}
.seg{position:absolute;top:0;bottom:0}.seg.phase1{background:rgba(80,120,180,.35)}.seg.phase2{background:rgba(60,160,120,.35)}.seg.phase3{background:rgba(170,120,70,.35)}.seg.unknown{background:rgba(160,165,175,.28)}
.cursor{position:absolute;top:-2px;bottom:-2px;width:3px;background:#fff;box-shadow:0 0 8px rgba(255,255,255,.7)}
.legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:7px;font-size:11px;color:var(--muted)}
.phase-badge{display:inline-block;padding:5px 8px;border:1px solid var(--border);border-radius:8px;background:#10151d}
.warning{border-color:#695a33;background:#19160e}.error{border-color:#713d47;background:#1a1013}
.movement-list{margin-top:8px;display:grid;gap:6px}.movement{padding:8px;border:1px solid var(--border);border-radius:8px;background:#10151d}
.statusline{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}
details{margin-top:10px}.json-box{white-space:pre-wrap;word-break:break-word;color:#aeb8c6;font:11px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
@media(max-width:980px){.layout{grid-template-columns:1fr}.signal-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:560px){.signal-grid,.card-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<main>
  <div class="statusline">
    <div>
      <h1>Видео ↔ реконструкция светофора</h1>
      <div class="muted">Синхронизация по абсолютному времени. Модель строится из готового Batch JSON.</div>
    </div>
    <div id="status" class="phase-badge">Загрузка…</div>
  </div>

  <div class="toolbar">
    <span class="muted">Начало видео:</span>
    <input id="videoStart" type="datetime-local" step="1">
    <button id="minus1">−1 с</button>
    <button id="plus1">+1 с</button>
    <button id="minus5">−5 с</button>
    <button id="plus5">+5 с</button>
    <button id="syncNow" class="primary">Синхронизировать</button>
  </div>

  <div class="layout">
    <section>
      <div class="panel">
        <video id="video" controls preload="metadata"></video>
        <div class="video-meta">
          <div><span class="muted small">Видео</span><div id="videoClock" class="big-time">—</div></div>
          <div><span class="muted small">Позиция</span><div id="videoPosition">0.0 с</div></div>
          <div><span class="muted small">Архив</span><div id="archiveClock">—</div></div>
        </div>
        <div class="controls">
          <button id="playVideo" class="primary">Воспроизвести</button>
          <button id="pauseVideo">Пауза</button>
          <button id="stepBack">Кадр −1 с</button>
          <button id="stepForward">Кадр +1 с</button>
        </div>
      </div>
      <div class="panel timeline-wrap">
        <h3>Временная шкала модели</h3>
        <div id="timeline" class="timeline"></div>
        <div class="legend">
          <span>Цветные участки — определённая фаза</span>
          <span>Серые участки — UNKNOWN / нет покрытия модели</span>
          <span>Белая линия — текущее положение видео</span>
        </div>
      </div>
    </section>

    <section>
      <div class="panel">
        <div class="statusline">
          <div><h2>Состояние светофора</h2><div id="modelNote" class="muted small">—</div></div>
          <div id="phaseBadge" class="phase-badge">Фаза —</div>
        </div>
        <div class="signal-grid" id="signals"></div>
        <div class="card-grid">
          <div class="metric"><span>Позиция в цикле</span><strong id="cyclePos">—</strong></div>
          <div class="metric"><span>Длина цикла</span><strong id="cycleLen">—</strong></div>
          <div class="metric"><span>Уверенность</span><strong id="confidence">—</strong></div>
          <div class="metric"><span>Состояние модели</span><strong id="modelStatus">—</strong></div>
          <div class="metric"><span>Причина UNKNOWN</span><strong id="unknownReason">—</strong></div>
          <div class="metric"><span>Точка</span><strong id="pointInfo">—</strong></div>
        </div>
      </div>

      <div class="panel">
        <h3>Движения в текущей точке</h3>
        <div id="movements" class="movement-list"></div>
      </div>

      <div id="warning" class="panel warning" style="display:none">
        <strong>Внимание:</strong>
        <span id="warningText"></span>
      </div>

      <details class="panel">
        <summary>Технические данные текущей точки</summary>
        <div id="jsonBox" class="json-box">—</div>
      </details>
    </section>
  </div>
</main>

<script>
const $ = (id) => document.getElementById(id);
const APPROACHES = {N:'Север', S:'Юг', E:'Восток', W:'Запад'};
const STATES = {GREEN:'ЗЕЛЁНЫЙ', YELLOW:'ЖЁЛТЫЙ', RED:'КРАСНЫЙ', RED_YELLOW:'КРАСНЫЙ + ЖЁЛТЫЙ', UNKNOWN:'НЕ ОПРЕДЕЛЕНО'};

let config = null;
let points = [];
let session = null;
let currentIndex = 0;
let cycleSeconds = 0;

function fmtDate(ms){
  if(ms == null || !Number.isFinite(Number(ms))) return '—';
  return new Date(Number(ms)).toLocaleString('ru-RU');
}
function parseLocalInput(value){
  const [date,time] = value.split('T');
  if(!date || !time) return NaN;
  const [y,m,d] = date.split('-').map(Number);
  const [hh,mm,ss='0'] = time.split(':').map(Number);
  return new Date(y,m-1,d,hh,mm,ss).getTime();
}
function setLocalInput(ms){
  const d = new Date(ms);
  const pad = (v)=>String(v).padStart(2,'0');
  $('videoStart').value =
    d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate())+
    'T'+pad(d.getHours())+':'+pad(d.getMinutes())+':'+pad(d.getSeconds());
}
function videoArchiveMs(){
  return config.videoStartMs + ($('video').currentTime || 0) * 1000;
}
function pointAbsMs(point){
  const raw = Number(point.timestamp_ms);
  const offset = Number(point.offset_s);
  if(Number.isFinite(offset)) return session.start_timestamp_ms + offset * 1000;
  if(Number.isFinite(raw) && raw > 100000000000) return raw;
  return session.start_timestamp_ms + (Number.isFinite(raw) ? raw : 0);
}
function nearestIndex(targetMs){
  if(!points.length) return 0;
  let lo=0,hi=points.length-1;
  while(lo<hi){
    const mid=(lo+hi)>>1;
    if(pointAbsMs(points[mid]) < targetMs) lo=mid+1; else hi=mid;
  }
  if(lo===0)return 0;
  const a=Math.abs(pointAbsMs(points[lo])-targetMs);
  const b=Math.abs(pointAbsMs(points[lo-1])-targetMs);
  return a<b?lo:lo-1;
}
function cyclePosition(point){
  if(point && point.cycle_position_s!=null) return Number(point.cycle_position_s);
  const origin = Number(session.phase_model?.origin_timestamp_ms||session.start_timestamp_ms);
  const abs = pointAbsMs(point);
  return cycleSeconds ? (((abs-origin)/1000)%cycleSeconds+cycleSeconds)%cycleSeconds : 0;
}
function signalCard(approach,state){
  const card=document.createElement('div'); card.className='signal-card';
  const h=document.createElement('h3'); h.textContent=APPROACHES[approach]||approach;
  const lamps=document.createElement('div'); lamps.className='lamps';
  for(const color of ['RED','YELLOW','GREEN']){
    const l=document.createElement('span');
    l.className='lamp '+color.toLowerCase()+(state===color?' on':'');
    lamps.appendChild(l);
  }
  const text=document.createElement('div');
  text.className='state state-'+state;
  text.textContent=STATES[state]||state;
  card.append(h,lamps,text);
  return card;
}
function renderSignals(states){
  $('signals').innerHTML='';
  for(const a of ['N','S','E','W']) $('signals').appendChild(signalCard(a,states?.[a]||'UNKNOWN'));
}
function renderTimeline(){
  const holder=$('timeline'); holder.innerHTML='';
  if(!points.length)return;
  const start=pointAbsMs(points[0]), end=pointAbsMs(points[points.length-1]);
  const span=Math.max(1,end-start);
  for(const p of points){
    const t=pointAbsMs(p), x=((t-start)/span)*100;
    const prevIndex=points.indexOf(p)-1;
    const prev=prevIndex>=0?points[prevIndex]:p;
    const width=Math.max(.15, ((t-pointAbsMs(prev))/span)*100);
    const div=document.createElement('div');
    const phase=p.phase_id==null?'unknown':'phase'+p.phase_id;
    div.className='seg '+phase;
    div.style.left=x+'%'; div.style.width=width+'%';
    div.title=fmtDate(t)+' · '+(p.phase_id==null?'UNKNOWN':'Фаза '+p.phase_id);
    div.addEventListener('click',()=>seekToArchive(t));
    holder.appendChild(div);
  }
  const cursor=document.createElement('div'); cursor.id='cursor'; cursor.className='cursor'; holder.appendChild(cursor);
}
function seekToArchive(absMs){
  $('video').currentTime=Math.max(0,(absMs-config.videoStartMs)/1000);
  updateFromVideo();
}
function renderPoint(){
  if(!session || !points.length)return;
  const p=points[currentIndex];
  const abs=pointAbsMs(p);
  const pos=cyclePosition(p);
  const states=p.states||{};
  renderSignals(states);
  $('phaseBadge').textContent=p.phase_id==null?'Фаза не определена':'Фаза '+p.phase_id;
  $('cyclePos').textContent=pos.toFixed(1)+' с';
  $('cycleLen').textContent=cycleSeconds.toFixed(1)+' с';
  $('confidence').textContent=Number(p.confidence||0).toFixed(2);
  $('modelStatus').textContent=p.unknown_reason?'НЕ ОПРЕДЕЛЕНО':'ОПРЕДЕЛЕНО';
  $('unknownReason').textContent=p.unknown_reason||'—';
  $('pointInfo').textContent=(currentIndex+1)+' / '+points.length;
  $('modelNote').textContent=(p.signal_source==='INFERRED_MODEL'?'По восстановленной модели фазы':'Модельный снимок');
  const movements=(p.movement_states||[]).map(m=>{
    const el=document.createElement('div'); el.className='movement';
    el.textContent=(m.movement||'—')+' · '+(m.state||'UNKNOWN')+' · confidence '+Number(m.confidence||0).toFixed(2);
    return el;
  });
  $('movements').innerHTML='';
  if(!movements.length){
    $('movements').innerHTML='<div class="muted small">Для этой точки отдельные движения не выделены.</div>';
  } else movements.forEach(x=>$('movements').appendChild(x));
  $('jsonBox').textContent=JSON.stringify(p,null,2);
  $('archiveClock').textContent=fmtDate(abs);
  const cursor=$('cursor');
  if(cursor){
    const start=pointAbsMs(points[0]), end=pointAbsMs(points[points.length-1]);
    const left=Math.max(0,Math.min(100,((abs-start)/Math.max(1,end-start))*100));
    cursor.style.left=left+'%';
  }
  if(p.unknown_reason){
    $('warning').style.display='block';
    $('warningText').textContent='В этой точке модель не подтверждает фазу: '+p.unknown_reason+'. Это не следует трактовать как факт о реальном светофоре.';
  } else $('warning').style.display='none';
}
function updateFromVideo(){
  const ms=videoArchiveMs();
  $('videoClock').textContent=fmtDate(ms);
  $('videoPosition').textContent=Number($('video').currentTime||0).toFixed(1)+' с';
  if(!session)return;
  currentIndex=nearestIndex(ms);
  renderPoint();
}
async function init(){
  const [cfgRes,analysisRes]=await Promise.all([fetch('/config'),fetch('/analysis')]);
  if(!cfgRes.ok||!analysisRes.ok) throw new Error('Не удалось загрузить конфигурацию или JSON');
  config=await cfgRes.json();
  const analysis=await analysisRes.json();
  session=(analysis.sessions||[])[0];
  if(!session) throw new Error('В analysis JSON нет session');
  points=session.effective_timeline||[];
  cycleSeconds=Number(session.effective_phase_model?.cycle_seconds||session.phase_model?.cycle_seconds||0);
  $('video').src='/video';
  setLocalInput(config.videoStartMs);
  $('status').textContent=(session.status||'ok').toUpperCase()+' · цикл '+cycleSeconds.toFixed(1)+' с';
  $('video').addEventListener('loadedmetadata', updateFromVideo);
  $('video').addEventListener('timeupdate', updateFromVideo);
  $('video').addEventListener('seeking', updateFromVideo);
  $('playVideo').onclick=()=>$('video').play();
  $('pauseVideo').onclick=()=>$('video').pause();
  $('minus1').onclick=()=>seekVideo(-1);
  $('plus1').onclick=()=>seekVideo(1);
  $('minus5').onclick=()=>seekVideo(-5);
  $('plus5').onclick=()=>seekVideo(5);
  $('stepBack').onclick=()=>seekVideo(-1);
  $('stepForward').onclick=()=>seekVideo(1);
  $('syncNow').onclick=()=>{const v=parseLocalInput($('videoStart').value); if(Number.isFinite(v))config.videoStartMs=v; updateFromVideo();};
  $('videoStart').addEventListener('change',()=>{const v=parseLocalInput($('videoStart').value); if(Number.isFinite(v)){config.videoStartMs=v; updateFromVideo();}});
  document.addEventListener('keydown',(e)=>{
    if(e.target.matches('input,textarea,select'))return;
    if(e.key==='ArrowLeft')seekVideo(-1);
    if(e.key==='ArrowRight')seekVideo(1);
    if(e.code==='Space'){e.preventDefault(); $('video').paused?$('video').play():$('video').pause();}
  });
  renderTimeline();
  updateFromVideo();
}
function seekVideo(delta){ $('video').currentTime=Math.max(0,Math.min(($('video').duration||Infinity),($('video').currentTime||0)+delta)); updateFromVideo(); }
init().catch(err=>{$('status').textContent='ОШИБКА';$('status').className='phase-badge error';$('jsonBox').textContent=String(err);});
</script>
</body>
</html>
"""


def _parse_iso_ms(value: str) -> int:
    value = value.strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError("video_start must include an explicit timezone offset")
    return int(dt.timestamp() * 1000)


def _load_analysis(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    sessions = data.get("sessions")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("analysis JSON must contain a non-empty 'sessions' list")
    if not isinstance(sessions[0].get("effective_timeline"), list):
        raise ValueError("analysis session must contain 'effective_timeline'")
    return data


class Handler(BaseHTTPRequestHandler):
    server_version = "TrafficPhaseVideoValidator/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        app = self.server.app_state  # type: ignore[attr-defined]

        if path == "/":
            return self._send_bytes(
                HTML.encode("utf-8"),
                "text/html; charset=utf-8",
            )
        if path == "/config":
            return self._send_json(
                {
                    "videoStartMs": app["video_start_ms"],
                    "videoStart": app["video_start"],
                }
            )
        if path == "/analysis":
            return self._send_file(
                app["analysis_path"],
                "application/json",
            )
        if path == "/video":
            return self._send_file(
                app["video_path"],
                "video/mp4",
                allow_range=True,
            )

        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def _send_json(self, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(raw, "application/json; charset=utf-8")

    def _send_file(
        self,
        path: Path,
        content_type: str,
        *,
        allow_range: bool = False,
    ) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, f"File not found: {path}")
            return

        size = path.stat().st_size
        if allow_range:
            range_header = self.headers.get("Range")
            if range_header and range_header.startswith("bytes="):
                start_text, _, end_text = range_header[6:].partition("-")
                start = int(start_text)
                end = int(end_text) if end_text else size - 1
                start = max(0, min(start, size - 1))
                end = max(start, min(end, size - 1))
                length = end - start + 1
                self.send_response(HTTPStatus.PARTIAL_CONTENT)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Accept-Ranges", "bytes")
                self.end_headers()
                with path.open("rb") as f:
                    f.seek(start)
                    self.wfile.write(f.read(length))
                return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(size))
        if allow_range:
            self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        with path.open("rb") as f:
            while chunk := f.read(1024 * 1024):
                self.wfile.write(chunk)

    def _send_bytes(self, raw: bytes, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize a local traffic video with Batch reconstruction JSON."
    )
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--analysis", required=True, type=Path)
    parser.add_argument(
        "--video-start",
        required=True,
        help="ISO-8601 timestamp with timezone, e.g. 2025-02-27T09:59:56+05:00",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()

    video = args.video.resolve()
    analysis = args.analysis.resolve()

    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    if not analysis.exists():
        raise SystemExit(f"Analysis not found: {analysis}")

    analysis_data = _load_analysis(analysis)
    video_start_ms = _parse_iso_ms(args.video_start)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.app_state = {  # type: ignore[attr-defined]
        "video_path": video,
        "analysis_path": analysis,
        "video_start_ms": video_start_ms,
        "video_start": args.video_start,
        "analysis": analysis_data,
    }
    print(f"Open http://{args.host}:{args.port}")
    print(f"Video: {video}")
    print(f"Video start: {args.video_start}")
    print(f"Analysis: {analysis}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
