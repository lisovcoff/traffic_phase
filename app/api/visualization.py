from __future__ import annotations

import json
import re
import zipfile
import errno
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.core.v9.signal_renderer import (
    DEFAULT_ACTIVITY_THRESHOLD,
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
)
from scripts.v9_spatial_visualizer import build_spatial_visualization
from app.core.v9.source_scope import ScopeChoiceRequired
from app.core.temporal_evidence import EvidenceUnavailable
from app.core.state_contract import prepare_logical_query
from app.core.upload_limits import copy_upload, UploadLimitExceeded

router = APIRouter(prefix="/visualization", tags=["visualization"])

LOG_ROOT = Path(__file__).resolve().parents[2] / "logs"


def _safe_run_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._") or "input"


def _write_visualization_logs(
    *,
    run_id: str,
    input_name: str,
    result: dict[str, Any],
    physical_plan: dict[str, Any],
    html: str,
    request_params: dict[str, Any],
) -> Path:
    run_dir = LOG_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "request.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "input_name": input_name,
                "parameters": request_params,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (run_dir / "v9_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "physical_signal_plan_v10.json").write_text(
        json.dumps(physical_plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "viewer.html").write_text(html, encoding="utf-8")

    period = float(
        physical_plan.get(
            "cycle_seconds",
            result.get("schedule", {}).get("period_s", 0.0),
        )
        or 0.0
    )
    time_offset_s = float(physical_plan.get("time_offset_s", 0.0) or 0.0)
    duration_s = float(result.get("recording_duration_s", 0.0) or 0.0)

    stages = []
    for index, stage in enumerate(physical_plan.get("stages", []) or []):
        start = float(stage.get("phase_start", 0.0))
        end = float(stage.get("phase_end", 0.0))
        if end <= start:
            continue
        stage_heads = stage.get("heads", {}) or {}
        stages.append(
            {
                "stage_id": int(stage.get("stage_id", index + 1)),
                "name": str(stage.get("name", "")),
                "phase_start": start,
                "phase_end": end,
                "source_phase": stage.get("source_phase"),
                "active_movements": list(stage.get("active_movements", [])),
                "heads": {
                    approach: {
                        "main": str(
                            (stage_heads.get(approach, {}) or {}).get(
                                "main",
                                "RED",
                            )
                        ),
                        "arrows": {
                            str(movement): str(state)
                            for movement, state in (
                                (stage_heads.get(approach, {}) or {}).get(
                                    "arrows",
                                    {},
                                )
                                or {}
                            ).items()
                        },
                    }
                    for approach in ("N", "S", "E", "W")
                },
            }
        )

    query = prepare_logical_query(result)
    anchor = result.get("schedule_base_timestamp_ms")
    display_base = result.get("recording_start_timestamp_ms")
    history_offset = (float(anchor)-float(display_base))/1000 if anchor is not None and display_base is not None else None
    with (run_dir / "signal_timeline_0.1s.jsonl").open(
        "w",
        encoding="utf-8",
    ) as stream:
        step = 0.1
        t = 0.0
        while t <= duration_s + 1e-9:
            cycle = (
                ((t - time_offset_s) % period + period) % period
                if period > 0.0
                else t - time_offset_s
            )
            active = next(
                (
                    item
                    for item in stages
                    if item["phase_start"] <= cycle < item["phase_end"]
                ),
                stages[0] if stages else None,
            )
            row = {
                "video_time_s": round(t, 3),
                "cycle_position_s": round(cycle, 6),
                "phase": active["name"] if active else "UNKNOWN",
                "source_phase": (
                    active.get("source_phase") if active else None
                ),
                "active_movements": (
                    active["active_movements"] if active else []
                ),
                "heads": (
                    active["heads"]
                    if active
                    else {
                        approach: {
                            "main": "RED",
                            "arrows": {},
                        }
                        for approach in ("N", "S", "E", "W")
                    }
                ),
            }
            logical = query.at(t-history_offset if history_offset is not None else -1)
            row.update(phase=logical.estimated_state, logical_phase=logical.to_dict(),
                       active_movements=[], heads={a:{"main":"UNKNOWN","arrows":{}} for a in ("N","S","E","W")},
                       source="common_state_contract", mode="reconstructed",
                       calibrated_lamp_probability=None, cycle_position_s=None,
                       source_phase=logical.observation_support.get("phase_id"),
                       history_time_s=t-history_offset if history_offset is not None else None)
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            t += step

    manifest = {
        "run_id": run_id,
        "input_name": input_name,
        "render_mode": "reconstructed",
        "physical_reconstruction": "UNKNOWN",
        "physical_plan_semantics": "unverified hypothesis; not reconstructed lamp states",
        "trajectory_count": result.get("trajectory_count"),
        "event_count": result.get("event_count"),
        "movement_stream_count": result.get("movement_stream_count"),
        "phase_count": result.get("schedule", {}).get("phase_count"),
        "period_s": period,
        "recording_start_timestamp_ms": result.get(
            "recording_start_timestamp_ms"
        ),
        "analysis_base_timestamp_ms": result.get(
            "analysis_base_timestamp_ms"
        ),
        "time_offset_s": time_offset_s,
        "recording_duration_s": duration_s,
        "physical_enabled": bool(physical_plan.get("enabled")),
        "physical_reason": physical_plan.get("reason"),
        "mapping": physical_plan.get("mapping", {}),
        "stages": stages,
        "files": [
            "request.json",
            "v9_result.json",
            "physical_signal_plan_v10.json",
            "signal_timeline_0.1s.jsonl",
            "viewer.html",
            "manifest.json",
        ],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return run_dir


INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>V10 — визуализация Traffic Phase</title>
<style>
:root{color-scheme:dark;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif}
*{box-sizing:border-box}
body{margin:0;background:#0d1015;color:#edf2f7}
main{max-width:1100px;margin:auto;padding:32px 20px}
.panel{background:#171b22;border:1px solid #303743;border-radius:16px;padding:20px}
h1{margin:0 0 8px;font-size:30px}
p{line-height:1.5}.muted{color:#98a2b3}
.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin-top:20px}
input[type=file]{max-width:100%;padding:10px;border:1px solid #343b46;border-radius:9px;background:#10141a;color:#edf2f7}
#source-choice,#session-choice{margin-top:10px;min-width:0;max-width:100%}
#source-choice label,#session-choice label{display:block;min-width:0;max-width:100%}
#source-choice select,#session-choice select{display:block;box-sizing:border-box;width:100%;max-width:100%;font:inherit;padding:8px;background:#10141a;color:#edf2f7;border:1px solid #343b46;border-radius:9px}
button{font:inherit;border:0;border-radius:9px;padding:10px 16px;cursor:pointer}
button.primary{background:#f0f3f7;color:#111}
button:disabled{opacity:.45;cursor:default}
.status{margin-top:14px;min-height:22px}
#viewer{display:none;width:100%;height:calc(100vh - 180px);min-height:700px;border:1px solid #303743;border-radius:14px;background:#0d1015;margin-top:18px}
.note{margin-top:16px;font-size:13px}
</style>
</head>
<body>
<main>
<section class="panel">
<h1>V10 — Traffic Phase</h1>
<p class="muted">
Анализ JSON/ZIP → оценка фаз и движений → интерактивная схема и временная шкала.
</p>
<form id="form">
<p><a href="/visualization/batch" style="color:#9ccaff">Обработать архив автоматически по отдельным сеансам</a></p>
<div class="toolbar">
<input id="file" name="file" type="file" accept=".json,.zip,application/json,application/zip" required>
<button class="primary" id="submit" type="submit">Запустить анализ</button>
</div>
<div id="source-choice" hidden><label>JSON в архиве <select id="source-member" aria-label="JSON в архиве"></select></label></div>
<div id="session-choice" hidden><label>Сеанс наблюдений <select id="session-id" aria-label="Сеанс наблюдений"></select></label></div>
</form>
<div id="status" class="status muted">Выберите JSON или ZIP-архив.</div>
<div class="note muted">
По умолчанию цветом показана оценка движений текущей фазы.
Переключатель «Отображение» внутри результата открывает вид «Физические лампы»;
неподтверждённые лампы и секции в нём остаются UNKNOWN.
</div>
</section>
<iframe id="viewer" title="V10 visualization"></iframe>
</main>
<script>
const form=document.getElementById("form");
const file=document.getElementById("file");
const submit=document.getElementById("submit");
const status=document.getElementById("status");
const viewer=document.getElementById("viewer");
const sourceSelect=document.getElementById("source-member");
const sessionSelect=document.getElementById("session-id");
let chosenSource="",chosenSession="";
function clearResult(){viewer.style.display="none";viewer.srcdoc="";}
file.addEventListener("change",()=>{
  chosenSource="";chosenSession="";sourceSelect.replaceChildren();sessionSelect.replaceChildren();
  document.getElementById("source-choice").hidden=true;document.getElementById("session-choice").hidden=true;
  clearResult();status.textContent="Выберите источник и запустите анализ.";
});
sourceSelect.addEventListener("change",()=>{
  chosenSource=sourceSelect.value;chosenSession="";sessionSelect.replaceChildren();
  document.getElementById("session-choice").hidden=true;clearResult();
  status.textContent="Источник изменён. Запустите отдельный анализ.";
});
sessionSelect.addEventListener("change",()=>{chosenSession=sessionSelect.value;clearResult();status.textContent="Сеанс изменён. Запустите отдельный анализ.";});
function offerChoice(scope){
  const isSource=scope.choice_kind==="source";
  const select=isSource?sourceSelect:sessionSelect;
  if(scope.source_member)chosenSource=scope.source_member;
  select.replaceChildren(new Option("Выберите…",""));
  const fmt=new Intl.DateTimeFormat("ru-RU",{timeZone:"Asia/Yekaterinburg",dateStyle:"short",timeStyle:"medium"});
  const timeLabel=value=>{const date=new Date(value);return Number.isFinite(date.getTime())?fmt.format(date):String(value)+" ms";};
  for(const row of scope.choices){
    const label=isSource?row.source_member+" ("+row.uncompressed_bytes+" байт)":
      "Сеанс "+row.session_number+": "+timeLabel(row.observation_start_ms)+" — "+
      timeLabel(row.observation_end_ms)+" · "+row.track_count+" треков";
    select.add(new Option(label,isSource?row.source_member:row.session_id));
  }
  document.getElementById(isSource?"source-choice":"session-choice").hidden=false;
  status.textContent=isSource?"В архиве несколько JSON. Выберите один источник для отдельного анализа.":
    "Найдены разрывы наблюдений. Выберите сеанс; разрыв не означает переключение светофора.";
}

form.addEventListener("submit",async function(event){
  event.preventDefault();
  if(!file.files.length)return;
  submit.disabled=true;
  file.disabled=true;sourceSelect.disabled=true;sessionSelect.disabled=true;
  status.textContent="V10 анализирует архив…";
  viewer.style.display="none";
  try{
    const body=new FormData();
    body.append("file",file.files[0]);
    if(chosenSource)body.append("source_member",chosenSource);
    if(chosenSession)body.append("session_id",chosenSession);
    const response=await fetch("/visualization/analyze",{method:"POST",body});
    const html=await response.text();
    if(!response.ok){
      let detail;try{detail=JSON.parse(html).detail;}catch{}
      if(response.status===409 && detail?.choices){offerChoice(detail);return;}
      throw new Error(typeof detail==="string"?detail:(detail?.reason||html||("HTTP "+response.status)));
    }
    viewer.srcdoc=html;
    viewer.style.display="block";
    status.textContent="Готово. Визуализация фаз и движений построена.";
    viewer.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(error){
    status.textContent="Ошибка: "+String(error.message||error);
  }finally{
    submit.disabled=false;
    file.disabled=false;sourceSelect.disabled=false;sessionSelect.disabled=false;
  }
});
</script>
</body>
</html>"""


@router.get("", response_class=HTMLResponse)
def visualization_page() -> str:
    return INDEX_HTML


@router.post("/analyze", response_class=HTMLResponse)
async def visualization_analyze(
    file: UploadFile = File(...),
    dt: float = Form(default=1.0, gt=0.0),
    yellow: float = Form(
        default=DEFAULT_YELLOW_DURATION_SECONDS,
        ge=0.0,
    ),
    red_yellow: float = Form(
        default=DEFAULT_RED_YELLOW_DURATION_SECONDS,
        ge=0.0,
    ),
    activity_threshold: float = Form(
        default=DEFAULT_ACTIVITY_THRESHOLD,
        ge=0.0,
        le=1.0,
    ),
    source_member: str | None = Form(default=None),
    session_id: str | None = Form(default=None),
) -> HTMLResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    lowered = file.filename.lower()
    if not lowered.endswith((".json", ".zip")):
        raise HTTPException(
            status_code=400,
            detail="Only JSON and ZIP inputs are supported",
        )

    dt_value = float(getattr(dt, "default", dt))
    yellow_value = float(getattr(yellow, "default", yellow))
    red_yellow_value = float(getattr(red_yellow, "default", red_yellow))
    activity_threshold_value = float(
        getattr(activity_threshold, "default", activity_threshold)
    )

    try:
        with TemporaryDirectory(prefix="traffic_phase_visualization_") as tmp:
            source_path = Path(tmp) / Path(file.filename).name
            await file.seek(0)
            with source_path.open("wb") as sink:
                copy_upload(file.file, sink)

            built = build_spatial_visualization(
                source_path,
                dt=dt_value,
                yellow_duration_seconds=yellow_value,
                red_yellow_duration_seconds=red_yellow_value,
                activity_threshold=activity_threshold_value,
                **{k: v for k, v in {
                    'source_member': getattr(source_member, 'default', source_member),
                    'session_id': getattr(session_id, 'default', session_id)}.items() if v is not None},
            )
            html = built["html"]
            result = built["result"]
            physical_plan = built["physical_plan"]
            print(
                "[V10 visualization]",
                {
                    "phase_count": result.get("schedule", {}).get("phase_count"),
                    "event_count": result.get("event_count"),
                    "movement_stream_count": result.get("movement_stream_count"),
                    "physical_enabled": bool(physical_plan.get("enabled")),
                    "physical_reason": physical_plan.get("reason"),
                    "analysis_base_timestamp_ms": result.get("analysis_base_timestamp_ms"),
                    "recording_start_timestamp_ms": result.get("recording_start_timestamp_ms"),
                    "rendered_trajectories": built["rendered_trajectory_count"],
                },
            )
            run_id = (
                datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
                + "_"
                + _safe_run_name(Path(file.filename).stem)
            )
            print(
                "[V10 visualization]",
                {
                    "run_id": run_id,
                    "phase_count": result.get("schedule", {}).get("phase_count"),
                    "event_count": result.get("event_count"),
                    "movement_stream_count": result.get("movement_stream_count"),
                    "physical_enabled": physical_plan.get("enabled"),
                    "physical_reason": physical_plan.get("reason"),
                },
            )
            run_dir = _write_visualization_logs(
                run_id=run_id,
                input_name=file.filename,
                result=result,
                physical_plan=physical_plan,
                html=html,
                request_params={
                    "dt": dt_value,
                    "yellow": yellow_value,
                    "red_yellow": red_yellow_value,
                    "activity_threshold": activity_threshold_value,
                },
            )
            return HTMLResponse(
                content=html.replace(
                    "<h1>V9 — пространственная реконструкция перекрёстка</h1>",
                    (
                        "<h1>V9 — пространственная реконструкция перекрёстка</h1>"
                        f"<p class='muted' style='overflow-wrap:anywhere'>Результат: {run_id}</p>"
                    ),
                    1,
                ),
                headers={
                    "X-Traffic-Phase-Run-Id": run_id,
                    "X-Traffic-Phase-Logs": str(run_dir),
                },
            )

    except UploadLimitExceeded as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ScopeChoiceRequired as exc:
        raise HTTPException(status_code=409, detail=exc.to_dict()) from exc
    except EvidenceUnavailable as exc:
        raise HTTPException(status_code=422, detail=exc.to_dict()) from exc
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise HTTPException(status_code=507, detail="Insufficient temporary storage; configure TEMP/TMP on a disk with free space") from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
