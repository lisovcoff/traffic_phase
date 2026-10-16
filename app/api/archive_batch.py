"""Local web batch surface. One active batch per application process."""
import errno
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import threading
import uuid
import zipfile

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.concurrency import run_in_threadpool

from app.core.archive_batch import run_archive_batch, render_batch_html, FIT_FRAME_SCRIPT
from app.core.upload_limits import copy_upload, UploadLimitExceeded
from app.core.temporal_evidence import EvidenceUnavailable

router = APIRouter(prefix='/visualization', tags=['archive batch'])
BATCH_ROOT = Path(__file__).resolve().parents[2]/'logs/archive_batches'
_batch_lock = threading.Lock()

PAGE = '''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Traffic Phase — пакетный анализ</title><style>*{box-sizing:border-box}body{font-family:system-ui;background:#10151d;color:#edf2f7;padding:20px;margin:0;overflow-wrap:anywhere}main{max-width:1100px;margin:auto}p{line-height:1.5}input{max-width:100%}button{padding:10px;margin:10px 0}a{color:#9ccaff}iframe{width:100%;height:1000px;border:1px solid #555}</style>
<main><a href="/visualization">Один сеанс и движения машин</a><h1>Анализ JSON или архива по сеансам</h1>
<p>Каждый JSON и сеанс оцениваются отдельно. До 4 попыток, до 90 секунд на источник и 180 секунд на пакет.
Остальные сеансы сохранят статус UNKNOWN с причиной. Загрузка до 512 МиБ; суммарный объём распаковки до 1 ГиБ, без извлечения ZIP на диск.</p>
<p>Выход: K, период, движения и оценка логических фаз. Тип секций и физические лампы UNKNOWN; точная история продлений ещё не принята (2D.1 FAIL).</p>
<form id="batch-form"><input type="file" id="batch-file" accept=".json,.zip" required aria-label="JSON или ZIP"><br><button id="batch-submit">Обработать сеансы</button></form>
<p id="batch-status">Выберите файл.</p><a id="batch-download" hidden>Скачать predictions, отчёты и manifest</a><iframe id="batch-viewer" title="Результаты архива" hidden></iframe></main>
<script>__FIT_FRAME_SCRIPT__
const form=document.querySelector('#batch-form'),file=document.querySelector('#batch-file'),button=document.querySelector('#batch-submit'),status=document.querySelector('#batch-status'),viewer=document.querySelector('#batch-viewer'),download=document.querySelector('#batch-download');
function clear(){viewer.hidden=true;viewer.srcdoc='';download.hidden=true;download.removeAttribute('href');}
file.onchange=()=>{clear();status.textContent='Файл выбран. Запустите обработку.';};
form.onsubmit=async e=>{e.preventDefault();if(!file.files.length)return;clear();button.disabled=true;file.disabled=true;status.textContent='Обработка… Лимит вычислений пакета 180 секунд; загрузка и отчёты учитываются отдельно.';
try{const body=new FormData();body.append('file',file.files[0]);const response=await fetch('/visualization/batch',{method:'POST',body});const page=await response.text();if(!response.ok){let detail;try{detail=JSON.parse(page).detail;}catch{}throw Error(typeof detail==='string'?detail:JSON.stringify(detail||page));}
fitFrame(viewer);viewer.srcdoc=page;viewer.hidden=false;const id=response.headers.get('X-Traffic-Phase-Batch-Id');download.href='/visualization/batch/'+encodeURIComponent(id)+'/download';download.hidden=false;status.textContent='Готово. Проверьте статусы сеансов: частичный результат не означает полного анализа архива.';
}catch(e){status.textContent='Ошибка: '+e.message;}finally{button.disabled=false;file.disabled=false;}};</script></html>'''.replace('__FIT_FRAME_SCRIPT__', FIT_FRAME_SCRIPT)


@router.get('/batch', response_class=HTMLResponse)
def batch_page():
    return PAGE


def _build_batch(source, output):
    manifest = run_archive_batch(source, output)
    page = render_batch_html(manifest, output)
    (output/'index.html').write_text(page, encoding='utf-8')
    # ZIP contains only this run's generated artifacts; never the user's media.
    with zipfile.ZipFile(output/'results.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output.rglob('*')):
            if path.is_file() and path.name != 'results.zip':
                archive.write(path, path.relative_to(output).as_posix())
    return page


@router.post('/batch', response_class=HTMLResponse)
async def batch_analyze(file: UploadFile = File(...)):
    if not file.filename or Path(file.filename).suffix.lower() not in ('.json', '.zip'):
        raise HTTPException(400, 'Only JSON and ZIP inputs are supported')
    if not _batch_lock.acquire(blocking=False):
        raise HTTPException(429, 'BATCH_ALREADY_RUNNING; wait for the current batch')
    try:
        batch_id = uuid.uuid4().hex
        with TemporaryDirectory(prefix='traffic_batch_') as temp:
            source = Path(temp)/Path(file.filename).name
            await file.seek(0)
            with source.open('wb') as sink:
                await run_in_threadpool(copy_upload, file.file, sink)
            page = await run_in_threadpool(_build_batch, source, BATCH_ROOT/batch_id)
        return HTMLResponse(page, headers={'X-Traffic-Phase-Batch-Id': batch_id})
    except UploadLimitExceeded as exc:
        raise HTTPException(413, str(exc)) from exc
    except EvidenceUnavailable as exc:
        raise HTTPException(422, exc.to_dict()) from exc
    except (ValueError, zipfile.BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(507 if exc.errno == errno.ENOSPC else 422, str(exc)) from exc
    finally:
        _batch_lock.release()


@router.get('/batch/{batch_id}/download')
def download_batch(batch_id: str):
    if not re.fullmatch(r'[0-9a-f]{32}', batch_id):
        raise HTTPException(404, 'Unknown batch')
    path = BATCH_ROOT/batch_id/'results.zip'
    if not path.is_file():
        raise HTTPException(404, 'Batch download unavailable')
    return FileResponse(path, filename='traffic_phase_results.zip', media_type='application/zip')
