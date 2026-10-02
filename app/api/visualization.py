from __future__ import annotations

import shutil
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.core.v9.events import load_source
from app.core.v9.signal_renderer import (
    DEFAULT_ACTIVITY_THRESHOLD,
    DEFAULT_RED_YELLOW_DURATION_SECONDS,
    DEFAULT_YELLOW_DURATION_SECONDS,
)
from app.core.v9.spatial import build_spatial_projection, compact_trajectories
from app.core.v9.v9_discovery import discover_records
from scripts.v9_spatial_visualizer import render_html

router = APIRouter(prefix="/visualization", tags=["visualization"])

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
Единый офлайн-анализ: JSON/ZIP → V9 discovery → V10 физическая семантика →
пространственная реконструкция машин и светофоров.
</p>
<form id="form">
<div class="toolbar">
<input id="file" name="file" type="file" accept=".json,.zip,application/json,application/zip" required>
<button class="primary" id="submit" type="submit">Запустить анализ</button>
</div>
</form>
<div id="status" class="status muted">Выберите JSON или ZIP-архив.</div>
<div class="note muted">
Результат строится сервером и открывается внутри страницы. Состояния зелёный/красный
восстанавливаются по транспортным потокам и физическому плану; жёлтый и
красный+жёлтый — модельные переходы. Прямых данных контроллера нет.
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

form.addEventListener("submit",async function(event){
  event.preventDefault();
  if(!file.files.length)return;
  submit.disabled=true;
  status.textContent="V10 анализирует архив…";
  viewer.style.display="none";
  try{
    const body=new FormData();
    body.append("file",file.files[0]);
    const response=await fetch("/visualization/analyze",{method:"POST",body});
    const html=await response.text();
    if(!response.ok)throw new Error(html || ("HTTP "+response.status));
    viewer.srcdoc=html;
    viewer.style.display="block";
    status.textContent="Готово. V10 визуализация построена.";
    viewer.scrollIntoView({behavior:"smooth",block:"start"});
  }catch(error){
    status.textContent="Ошибка: "+String(error.message||error);
  }finally{
    submit.disabled=false;
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
) -> HTMLResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    lowered = file.filename.lower()
    if not lowered.endswith((".json", ".zip")):
        raise HTTPException(
            status_code=400,
            detail="Only JSON and ZIP inputs are supported",
        )

    try:
        with TemporaryDirectory(prefix="traffic_phase_visualization_") as tmp:
            source_path = Path(tmp) / Path(file.filename).name
            await file.seek(0)
            with source_path.open("wb") as sink:
                shutil.copyfileobj(
                    file.file,
                    sink,
                    length=1024 * 1024,
                )

            tracks, _source_files = load_source(source_path)
            result = discover_records(
                tracks,
                input_name=str(source_path),
                dt=dt,
            )
            projection = build_spatial_projection(tracks)
            compact = compact_trajectories(
                tracks,
                analysis_base_timestamp_ms=float(
                    result["analysis_base_timestamp_ms"]
                ),
                projection=projection,
            )

            html = render_html(
                result,
                projection,
                compact,
                yellow_duration_seconds=yellow,
                red_yellow_duration_seconds=red_yellow,
                activity_threshold=activity_threshold,
                physical_plan=result.get("physical_signal_plan"),
            )
            return HTMLResponse(content=html)

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
