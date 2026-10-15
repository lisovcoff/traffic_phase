from io import BytesIO
import json
from pathlib import Path
from fastapi import APIRouter,File,Form,HTTPException,UploadFile,Request
from fastapi.responses import HTMLResponse,FileResponse
from app.core.annotation_workbench import prepare_preview,validate_review,MAX_BYTES

router=APIRouter(prefix='/annotation',tags=['manual-review'])
ASSETS=Path(__file__).resolve().parents[1]/'static'/'annotation'


@router.get('',response_class=HTMLResponse)
def page():return (ASSETS/'index.html').read_text(encoding='utf-8')


@router.get('/workbench.js')
def javascript():return FileResponse(ASSETS/'workbench.js',media_type='text/javascript')


@router.post('/preview')
def preview(file:UploadFile=File(...),start_seconds:float=Form(0),duration_seconds:float=Form(180)):
    if not file.filename or not file.filename.lower().endswith('.json'):
        raise HTTPException(422,'На этом шаге откройте один trajectory JSON, не архив')
    if file.size is not None and file.size>MAX_BYTES:raise HTTPException(413,'JSON превышает 256 MiB')
    try:
        file.file.seek(0)
        return prepare_preview(file.file,Path(file.filename).name,start_seconds=start_seconds,duration_seconds=duration_seconds)
    except (ValueError,UnicodeError,OverflowError,TypeError) as exc:
        raise HTTPException(422,str(exc)) from exc


@router.post('/validate')
async def validate(request:Request):
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>4*1024*1024:raise HTTPException(413,'Файл разметки превышает 4 MiB')
        chunks.append(chunk)
    try:return validate_review(json.loads(b''.join(chunks)))
    except (ValueError,TypeError,AttributeError) as exc:raise HTTPException(422,str(exc)) from exc


@router.get('/demo')
def demo():
    # Display/round-trip demo only; no signal truth or discovery.
    origin=1739606400000
    records=[]
    for i,(a,b) in enumerate([('N','S'),('E','W'),('S','E'),('N','S')]):
        ds=[]
        for j in range(100):
            position=j/99
            x,y=(.45,.08+.84*position) if a=='N' else ((.92-.84*position,.55) if a=='E' else (.55+.35*position,.92-.5*position))
            ds.append({'millis':origin+i*4000+j*200,'centroid_x':x,'centroid_y':y})
        records.append({'id':i+1,'zone_in':a,'zone_out':b,'detections':ds})
    return prepare_preview(BytesIO(json.dumps(records).encode()),'SYNTHETIC_DEMO.json')
