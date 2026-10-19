"""Explicit calibrated-model workflow; ordinary automatic discovery stays intact."""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path
import re
from uuid import uuid4

from fastapi import APIRouter,File,Form,HTTPException,UploadFile
from fastapi.responses import HTMLResponse,JSONResponse
from app.api.visualization import INDEX_HTML,_write_visualization_logs
from app.core.learned_visualization import build_learned_visualization,SITES
from app.core.upload_limits import copy_upload,UploadLimitExceeded
from app.core.v9.source_scope import ScopeChoiceRequired

router=APIRouter(prefix='/visualization/learned',tags=['learned visualization'])
LOG_ROOT=Path(__file__).resolve().parents[2]/'logs'


@router.get('',response_class=HTMLResponse)
def learned_page():
    page=INDEX_HTML.replace('/visualization/analyze','/visualization/learned/analyze')
    page=page.replace('V10 — Traffic Phase','Обученная модель — Traffic Phase')
    options=''.join(f'<option value="{key}">{name}</option>' for key,name in SITES.items())
    page=re.sub(r'(<select id="intersection-profile"[^>]*>).*?(</select>)',
        lambda match:match[1]+options+match[2],page,flags=re.S)
    page=page.replace('Схема перекрёстка','Перекрёсток обученной модели')
    page=page.replace('<form id="form">',
        '<p>Этот режим использует заранее обученные профили трёх перекрёстков. '
        'Число фаз задано обучением. Для прогноза нужен только JSON/ZIP с траекториями; '
        'видео и контрольная разметка не требуются.</p><form id="form">')
    page=re.sub(r'<p><a href="/visualization/batch".*?</p>',
        '<p><a href="/visualization" style="color:#9ccaff">Обычный автоматический анализ</a></p>',page,flags=re.S)
    return page


@router.post('/analyze',response_class=HTMLResponse)
async def learned_analyze(file:UploadFile=File(...),intersection_profile:str=Form('lenina_sverdlovsky'),
                          source_member:str|None=Form(None),session_id:str|None=Form(None)):
    if not file.filename or Path(file.filename).suffix.lower() not in {'.json','.zip'}:
        raise HTTPException(400,'JSON or ZIP input required')
    model_id=getattr(intersection_profile,'default',intersection_profile)
    if model_id not in SITES:raise HTTPException(400,'Unknown calibrated model')
    # Keep request inputs and results; do not delete existing user material.
    run_id='learned_'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_')+uuid4().hex[:10]
    request_dir=LOG_ROOT/(run_id+'_input');request_dir.mkdir(parents=True,exist_ok=False)
    path=request_dir/Path(file.filename).name
    try:
        await file.seek(0)
        with path.open('xb') as sink:copy_upload(file.file,sink)
        built=await asyncio.to_thread(build_learned_visualization,path,model_id=model_id,
            source_member=getattr(source_member,'default',source_member),
            session_id=getattr(session_id,'default',session_id))
        _write_visualization_logs(run_id=run_id,input_name=file.filename,result=built['result'],
            physical_plan=built['physical_plan'],html=built['html'],
            request_params={'model_id':model_id,'algorithm':'learned_phase','prediction_marks_received':False})
        return HTMLResponse(built['html'])
    except ScopeChoiceRequired as exc:return JSONResponse(exc.to_dict(),status_code=409)
    except UploadLimitExceeded as exc:raise HTTPException(413,str(exc)) from exc
    except (ValueError,OSError) as exc:raise HTTPException(400,str(exc)) from exc
