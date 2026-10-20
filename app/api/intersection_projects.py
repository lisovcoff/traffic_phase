"""Persistent offline intersection jobs. No model/profile supplied by the user."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from app.core.intersection_project import (MAX_ARCHIVE_BYTES, read_json, write_json,
    load_prediction,read_model)
from app.core.upload_limits import copy_upload, UploadLimitExceeded

ROOT=Path(__file__).resolve().parents[2]
PROJECT_ROOT=ROOT/'logs/intersection_projects'
router=APIRouter(prefix='/api/v1/intersections',tags=['intersection projects'])
_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='intersection-worker')
_view_lock=threading.Lock()


def _folder(identifier):
    if not re.fullmatch(r'[a-f0-9]{32}',identifier):
        raise HTTPException(404,'Unknown intersection model')
    folder=PROJECT_ROOT/identifier
    if not folder.is_dir():raise HTTPException(404,'Unknown intersection model')
    return folder


def _run_worker(source, folder):
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    try:
        with (folder/'worker.log').open('ab') as stream:
            process=subprocess.run([sys.executable,'-m','scripts.intersection_project',str(source),'--output',str(folder)],
                cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=3*3600)
        status=read_json(folder/'status.json')
        if process.returncode and status['status'] not in ('FAILED','PARTIAL'):
            status.update(status='FAILED',reason='Analysis worker exited unexpectedly');write_json(folder/'status.json',status)
    except Exception as error:
        status=read_json(folder/'status.json')
        status.update(status='FAILED',reason=type(error).__name__+': '+str(error)[:500])
        write_json(folder/'status.json',status)


@router.post('',status_code=202)
async def create_project(file:UploadFile=File(...)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.json','.zip'):raise HTTPException(400,'Choose a JSON or ZIP of one intersection')
    identifier=uuid.uuid4().hex;folder=PROJECT_ROOT/identifier;folder.mkdir(parents=True)
    source=folder/('input'+suffix)
    write_json(folder/'status.json',dict(status='UPLOADING',stage='upload',model_id=identifier,
        input_name=Path(file.filename).name,sources_done=0,sources_total=0,sessions_done=0))
    try:
        await file.seek(0)
        with source.open('wb') as sink:
            await run_in_threadpool(copy_upload,file.file,sink,max_bytes=MAX_ARCHIVE_BYTES)
        write_json(folder/'status.json',dict(status='QUEUED',stage='queued',model_id=identifier,
            input_name=Path(file.filename).name,sources_done=0,sources_total=0,sessions_done=0))
        _executor.submit(_run_worker,source,folder)
        return dict(model_id=identifier,status='QUEUED',status_url=f'/api/v1/intersections/{identifier}')
    except (UploadLimitExceeded,OSError) as error:
        write_json(folder/'status.json',dict(status='FAILED',reason=str(error)))
        raise HTTPException(413 if isinstance(error,UploadLimitExceeded) else 507,str(error)) from error


@router.get('/{identifier}')
def project_status(identifier:str):
    return read_json(_folder(identifier)/'status.json')


@router.get('/{identifier}/model')
def project_model(identifier:str):
    folder=_folder(identifier)
    if not (folder/'model.json').is_file():raise HTTPException(409,'Model is not ready')
    try:value=read_model(folder)
    except ValueError as error:raise HTTPException(422,str(error)) from error
    value.pop('input_path_private',None)
    return JSONResponse(value,headers={'Content-Disposition':'attachment; filename="intersection_model.json"'})


def _build_view(folder, session_id):
    from scripts.v9_spatial_visualizer import build_spatial_visualization
    model,session,prediction=load_prediction(folder,session_id)
    from app.core.observed_topology import project_observed_topology
    prediction=project_observed_topology(prediction,model['approaches'],repair_missing_phases=(
        'selective' if model.get('projection_version')=='observed-topology-v3' else model.get('projection_version')=='observed-topology-v2'))
    prediction.get('event_extraction',{}).pop('temporal_events',None)
    # Explicitly no filename-selected known hardware in the autonomous product.
    page=build_spatial_visualization(Path(model['input_path_private']),precomputed_result=prediction,
        precomputed_projection=model['geometries'][session['source_member']]['projection'],
        intersection_profile='none')['html']
    return page.replace('V9 — пространственная реконструкция перекрёстка','Перекрёсток и сигналы').replace('Показан только выбранный сеанс; остальные источники и интервалы не анализировались.',
        'Показана выбранная запись. Остальные результаты доступны в списке записей модели.').replace(
        '<h3 style="margin-top:14px">Фазы модели</h3>','<h3 style="margin-top:14px">Состояния и переходы</h3>')


def _cached_view(folder,session_id):
    with _view_lock:
        model=read_model(folder)
        if not any(s['session_id']==session_id for s in model['sessions']):raise KeyError('unknown session')
        cached=folder/'viewers'/(session_id+'.v6.html')
        if not cached.is_file():
            page=_build_view(folder,session_id)
            cached.parent.mkdir(exist_ok=True)
            temporary=cached.with_name(session_id+'.'+uuid.uuid4().hex+'.writing')
            temporary.write_text(page,encoding='utf8')
            try:temporary.replace(cached)
            except PermissionError:
                # A concurrent Windows reader/renderer may hold the cache.
                # The complete generated page is still valid to return.
                return page
        return cached.read_text(encoding='utf8')


@router.get('/{identifier}/sessions/{session_id}/viewer',response_class=HTMLResponse)
async def project_viewer(identifier:str,session_id:str):
    folder=_folder(identifier)
    if not re.fullmatch(r'[a-f0-9]{24}',session_id):raise HTTPException(404,'Unknown session')
    if not (folder/'model.json').is_file():raise HTTPException(409,'Model is not ready')
    try:
        return HTMLResponse(await run_in_threadpool(_cached_view,folder,session_id))
    except KeyError as error:raise HTTPException(404,'Unknown session') from error
    except (ValueError,OSError) as error:raise HTTPException(422,str(error)) from error
