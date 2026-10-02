from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

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
                shutil.copyfileobj(
                    file.file,
                    sink,
                    length=1024 * 1024,
                )

            tracks, _source_files = load_source(source_path)
            result = discover_records(
                tracks,
                input_name=str(source_path),
                dt=dt_value,
            )
            projection = build_spatial_projection(tracks)
            analysis_base_ms = float(result["analysis_base_timestamp_ms"])
            recording_start_ms = result.get("recording_start_timestamp_ms")
            display_base_ms = (
                float(recording_start_ms)
                if recording_start_ms is not None
                else analysis_base_ms
            )
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

            physical_plan = result.get("physical_signal_plan")
            print(
                "[V10 visualization]",
                {
                    "phase_count": result.get("schedule", {}).get("phase_count"),
                    "physical_enabled": (
                        physical_plan.get("enabled")
                        if isinstance(physical_plan, dict)
                        else False
                    ),
                    "physical_reason": (
                        physical_plan.get("reason", "")
                        if isinstance(physical_plan, dict)
                        else "missing"
                    ),
                    "analysis_base_timestamp_ms": analysis_base_ms,
                    "recording_start_timestamp_ms": display_base_ms,
                    "time_offset_s": time_offset_s,
                },
            )

            physical_plan = result.get("physical_signal_plan") or {
                "enabled": False,
                "reason": "physical_signal_plan missing from V9 result",
            }
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
                    "analysis_base_timestamp_ms": analysis_base_ms,
                    "recording_start_timestamp_ms": display_base_ms,
                    "time_offset_s": time_offset_s,
                },
            )

            html = render_html(
                result,
                projection,
                compact,
                yellow_duration_seconds=yellow_value,
                red_yellow_duration_seconds=red_yellow_value,
                activity_threshold=activity_threshold_value,
                physical_plan=physical_plan,
                time_offset_s=time_offset_s,
                display_duration_s=display_duration_s,
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
                        f"<p class='muted'>Run: {run_id} · logs: {run_dir}</p>"
                    ),
                    1,
                ),
                headers={
                    "X-Traffic-Phase-Run-Id": run_id,
                    "X-Traffic-Phase-Logs": str(run_dir),
                },
            )

    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
