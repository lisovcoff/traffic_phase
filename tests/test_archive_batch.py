import asyncio
from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
import time
import zipfile
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.core import archive_batch as batch
from app.core.upload_limits import copy_upload, UploadLimitExceeded, UploadLimitMiddleware
from app.api import archive_batch as api
from app.main import app
from tests.test_v9_source_scope import track, write_json, zip_bytes
from tests.test_web_archive_contract import model as fixture_prediction


def request(tmp_path, *, remaining_jobs=4, budget=1024*1024):
    source = write_json(tmp_path/'input.json', [track(), track(2, start=86401000, origin='E', target='_W')])
    output = tmp_path/'worker'
    output.mkdir()
    return dict(input=str(source), output=str(output), source_member=source.name, source_count=1,
                remaining_jobs=remaining_jobs, remaining_output_bytes=budget, config=asdict(batch.BatchConfig()))


def install_dummy_fitter(monkeypatch):
    calls = []
    from app.core.v9 import model

    def fit(bundle, **kwargs):
        assert kwargs['marks_path'] is None
        assert kwargs['experimental_local_history'] is False
        assert kwargs['evidence_policy'] == 'permission_per_stream'
        events = bundle.temporal_events
        assert max(e.timestamp_ms for e in events)-min(e.timestamp_ms for e in events) < 86400000
        calls.append((bundle, kwargs))
        value = fixture_prediction()
        value.update(event_count=bundle[9], trajectory_count=bundle[8])
        return value
    monkeypatch.setattr(model, '_discover_bundle', fit)
    return calls


def test_worker_extracts_once_and_never_merges_sessions(monkeypatch, tmp_path):
    calls = install_dummy_fitter(monkeypatch)
    from app.core.v9 import events
    original = events.load_event_streams
    extractions = []

    def extraction(*a, **kw):
        extractions.append(kw)
        return original(*a, **kw)
    monkeypatch.setattr(events, 'load_event_streams', extraction)
    req = request(tmp_path)
    batch.run_source_worker(req)
    state = json.loads((Path(req['output'])/'checkpoint.json').read_text())
    assert len(extractions) == 1 and len(calls) == 2
    assert state['inventory_complete']
    assert [r['status'] for r in state['jobs']] == ['ESTIMATED']*2
    for row in state['jobs']:
        prediction = Path(req['output'])/row['prediction']
        value = json.loads(prediction.read_text())
        assert value['input_scope']['selected_session'] == row['session']
        assert row['prediction_sha256'] == batch.sha256_file(prediction)
        assert row['physical_state'] == 'UNKNOWN'


def test_worker_job_limit_reports_all_known_unattempted_sessions(monkeypatch, tmp_path):
    calls = install_dummy_fitter(monkeypatch)
    req = request(tmp_path, remaining_jobs=1)
    batch.run_source_worker(req)
    state = json.loads((Path(req['output'])/'checkpoint.json').read_text())
    assert len(calls) == 1
    assert state['jobs'][1]['reason'] == 'JOB_COUNT_BUDGET'
    assert state['jobs'][1]['phase_count'] is None
    assert not state['jobs'][1].get('attempted')


def test_all_sources_keep_namespace_and_per_session_artifacts(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    source = tmp_path/'two.zip'
    source.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track(), track(2, start=86401000)])]))
    calls = []

    def runner(path, timeout):
        req = json.loads(path.read_text())
        calls.append((req, timeout))
        batch.run_source_worker(req)
        return dict(status='EXITED', returncode=0)
    out = tmp_path/'out'
    result = batch.run_archive_batch(source, out, _runner=runner)
    assert result['status'] == 'COMPLETE_ESTIMATES'
    assert result['attempted_jobs'] == 3
    assert [r['source_member'] for r in result['sources_processed']] == ['a.json', 'b.json']
    assert [len(r['jobs']) for r in result['sources_processed']] == [1, 2]
    assert all(0 < timeout <= 90 for _, timeout in calls)
    assert result['input_sha256'] == batch.sha256_file(source)
    page = batch.render_batch_html(result, out)
    assert page.count('data-report=') == 3
    assert 'GREEN' not in page  # fixture has no independently observed lamp state


def test_source_timeout_retains_completed_and_marks_remaining_unknown(tmp_path):
    source = write_json(tmp_path/'input.json', [track()])

    def runner(path, timeout):
        req = json.loads(path.read_text())
        state = dict(inventory_complete=True, jobs=[dict(status='ESTIMATED', attempted=True),
            dict(status='RUNNING', attempted=True), dict(status='PLANNED')])
        batch.write_json(Path(req['output'])/'checkpoint.json', state)
        return dict(status='TIMEOUT')
    result = batch.run_archive_batch(source, tmp_path/'out', _runner=runner)
    rows = result['sources_processed'][0]['jobs']
    assert rows[0]['status'] == 'ESTIMATED'
    assert all(r['reason'] == 'SOURCE_TIMEOUT' and r['phase_count'] is None for r in rows[1:])
    assert result['attempted_jobs'] == 2 and result['status'] == 'PARTIAL_OR_UNAVAILABLE'


def test_timeout_before_inventory_does_not_fabricate_session_count(tmp_path):
    source = write_json(tmp_path/'input.json', [track()])
    result = batch.run_archive_batch(source, tmp_path/'out', _runner=lambda *a: dict(status='TIMEOUT'))
    assert not result['session_inventory_complete']
    row = result['sources_processed'][0]
    assert row['jobs'] == [] and row['reason'] == 'SOURCE_TIMEOUT_BEFORE_SESSION_INVENTORY'


def test_total_decompression_budget_stops_before_opening_next_source(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    source = tmp_path/'two.zip'
    source.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track()])]))
    _, choices = batch.choose_source(source, 'a.json')

    def runner(path, timeout):
        batch.run_source_worker(json.loads(path.read_text()))
        return dict(status='EXITED', returncode=0)
    config = batch.BatchConfig(max_total_source_bytes=choices[0]['uncompressed_bytes'])
    result = batch.run_archive_batch(source, tmp_path/'out', config=config, _runner=runner)
    assert result['sources_processed'][1]['reason'] == 'TOTAL_SOURCE_BYTE_BUDGET'


def test_global_job_count_is_shared_between_sources(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    source = tmp_path/'two.zip'
    source.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track()])]))
    calls = []

    def runner(path, timeout):
        calls.append(path)
        batch.run_source_worker(json.loads(path.read_text()))
        return dict(status='EXITED', returncode=0)
    result = batch.run_archive_batch(source, tmp_path/'out', config=batch.BatchConfig(max_jobs=1), _runner=runner)
    assert len(calls) == 1 and result['attempted_jobs'] == 1
    assert result['sources_processed'][1]['reason'] == 'JOB_COUNT_BUDGET'


def test_total_time_budget_stops_before_next_source(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    source = tmp_path/'two.zip'
    source.write_bytes(zip_bytes([('a.json', [track()]), ('b.json', [track()])]))
    clock = [0.0]
    monkeypatch.setattr(batch, 'time', SimpleNamespace(monotonic=lambda: clock[0]))

    def runner(path, timeout):
        assert timeout == 1.0
        batch.run_source_worker(json.loads(path.read_text()))
        clock[0] = 2.0
        return dict(status='EXITED', returncode=0)
    result = batch.run_archive_batch(source, tmp_path/'out', config=batch.BatchConfig(total_seconds=1), _runner=runner)
    assert result['sources_processed'][1]['reason'] == 'TOTAL_TIME_BUDGET'
    assert result['attempted_jobs'] == 1 and result['status'] == 'PARTIAL_OR_UNAVAILABLE'


def test_worker_crash_does_not_invent_session_or_k(tmp_path):
    source = write_json(tmp_path/'input.json', [track()])
    result = batch.run_archive_batch(source, tmp_path/'out', _runner=lambda *a: dict(status='EXITED', returncode=17))
    row = result['sources_processed'][0]
    assert row['jobs'] == [] and row['process']['returncode'] == 17
    assert row['reason'] == 'SESSION_INVENTORY_UNAVAILABLE'


def test_output_overflow_never_publishes_partial_prediction(tmp_path):
    target = tmp_path/'prediction.json'
    with pytest.raises(ValueError, match='OUTPUT_BYTE_BUDGET'):
        batch.write_json(target, {'x': 'a'*1000}, max_bytes=50)
    assert not target.exists() and not target.with_suffix('.json.tmp').exists()


@pytest.mark.parametrize('config', [dict(max_jobs=0), dict(total_seconds=float('nan')),
                                  dict(source_seconds=float('inf')), dict(max_jobs=True),
                                  dict(max_jobs=1.5), dict(dt=2), dict(max_jobs=513)])
def test_invalid_budgets_rejected(config):
    with pytest.raises(ValueError):
        batch.BatchConfig(**config)


def test_preexisting_output_not_overwritten(tmp_path):
    source = write_json(tmp_path/'input.json', [track()])
    out = tmp_path/'out'
    out.mkdir()
    with pytest.raises(FileExistsError):
        batch.run_archive_batch(source, out, _runner=lambda *a: pytest.fail('no worker'))


def test_real_process_empty_input_abstains_without_fitting(tmp_path):
    source = write_json(tmp_path/'input.json', [])
    result = batch.run_archive_batch(source, tmp_path/'out', config=batch.BatchConfig(source_seconds=20, total_seconds=25))
    row = result['sources_processed'][0]
    assert row['process']['returncode'] == 0
    assert row['source_error']['reason_code'] == 'NO_USABLE_DEMAND_EVIDENCE'
    assert not row['inventory_complete'] and not row['jobs']


def test_actual_subprocess_timeout_is_killed_and_waited(monkeypatch, tmp_path):
    original = subprocess.run

    def sleep_process(command, **kwargs):
        return original([sys.executable, '-c', 'import time;time.sleep(30)'], **kwargs)
    monkeypatch.setattr(batch.subprocess, 'run', sleep_process)
    started = time.monotonic()
    result = batch._run_worker(tmp_path/'unused.json', .1)
    assert result['status'] == 'TIMEOUT' and time.monotonic()-started < 5


@pytest.mark.parametrize('size,accepted', [(0, True), (16, True), (17, False)])
def test_copy_byte_limit_exact_boundary(size, accepted):
    sink = BytesIO()
    if accepted:
        assert copy_upload(BytesIO(b'x'*size), sink, max_bytes=16) == size
    else:
        with pytest.raises(UploadLimitExceeded):
            copy_upload(BytesIO(b'x'*size), sink, max_bytes=16)
    assert len(sink.getvalue()) <= 16


@pytest.mark.parametrize('declared', [None, b'1', b'100'])
def test_asgi_limit_checks_actual_bytes_before_endpoint(declared):
    messages, entered = [], []
    chunks = iter([dict(type='http.request', body=b'x'*8, more_body=True),
                   dict(type='http.request', body=b'y'*8, more_body=False)])

    async def receive():
        return next(chunks)

    async def inner(scope, receive, send):
        entered.append(True)
        await receive()
        await receive()
        pytest.fail('oversized request reached endpoint')

    async def send(message):
        messages.append(message)
    scope = dict(type='http', method='POST', path='/visualization/batch',
                 headers=[] if declared is None else [(b'content-length', declared)])
    asyncio.run(UploadLimitMiddleware(inner, max_bytes=10)(scope, receive, send))
    assert messages[0]['status'] == 413
    assert bool(entered) == (declared != b'100')


def test_chunked_multipart_overflow_closes_spooled_file_before_handler(monkeypatch):
    from fastapi import FastAPI, File
    import starlette.formparsers as formparsers
    files, messages = [], []
    original = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        value = original(*args, **kwargs)
        files.append(value)
        return value
    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', spool)
    local = FastAPI()

    @local.post('/visualization/batch')
    async def handler(file: UploadFile = File(...)):
        pytest.fail('request exceeded byte budget before handler')
    body = (b'--test\r\nContent-Disposition: form-data; name="file"; filename="x.json"\r\n'
            b'Content-Type: application/json\r\n\r\n'+b'x'*300+b'\r\n--test--\r\n')
    chunks = iter(body[i:i+32] for i in range(0, len(body), 32))

    async def receive():
        chunk = next(chunks)
        return dict(type='http.request', body=chunk, more_body=True)

    async def send(message):
        messages.append(message)
    scope = dict(type='http', asgi={'version': '3.0'}, method='POST', path='/visualization/batch',
                 raw_path=b'/visualization/batch', query_string=b'', root_path='', scheme='http',
                 server=('test', 80), client=('test', 1), http_version='1.1',
                 headers=[(b'content-type', b'multipart/form-data; boundary=test')])
    asyncio.run(UploadLimitMiddleware(local, max_bytes=180)(scope, receive, send))
    assert messages[0]['status'] == 413
    assert files and all(file.closed for file in files)


def test_batch_api_busy_bad_zip_and_input_contract(monkeypatch, tmp_path):
    monkeypatch.setattr(api, 'BATCH_ROOT', tmp_path/'results')
    with TestClient(app) as client:
        api._batch_lock.acquire()
        try:
            response = client.post('/visualization/batch', files={'file': ('input.json', b'[]')})
            assert response.status_code == 429
        finally:
            api._batch_lock.release()
        assert client.post('/visualization/batch', files={'file': ('bad.zip', b'bad')}).status_code == 422
        assert client.post('/visualization/batch', files={'file': ('marks.txt', b'[]')}).status_code == 400
        assert client.get('/visualization/batch/not-an-id/download').status_code == 404


def test_multipart_batch_download_is_limited_to_run_artifacts(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    monkeypatch.setattr(api, 'BATCH_ROOT', tmp_path/'results')
    original = batch.run_archive_batch

    def run(path, out, **kwargs):
        assert kwargs['algorithm_version'] == 'trajectory_recovery_v1'
        def runner(request_path, timeout):
            batch.run_source_worker(json.loads(request_path.read_text()))
            return dict(status='EXITED', returncode=0)
        return original(path, out, _runner=runner)
    monkeypatch.setattr(api, 'run_archive_batch', run)
    with TestClient(app) as client:
        response = client.post('/visualization/batch', files={'file': ('input.json', json.dumps([track()]))})
        assert response.status_code == 200 and 'UNKNOWN' in response.text
        ident = response.headers['X-Traffic-Phase-Batch-Id']
        archive = client.get(f'/visualization/batch/{ident}/download')
        assert archive.status_code == 200
        with zipfile.ZipFile(BytesIO(archive.content)) as zipped:
            assert zipped.testzip() is None
            assert 'manifest.json' in zipped.namelist() and 'index.html' in zipped.namelist()
            assert all(not n.startswith(('/', '../')) for n in zipped.namelist())
            assert 'input.json' not in zipped.namelist()


def test_batch_html_source_labels_cannot_execute_script(monkeypatch, tmp_path):
    install_dummy_fitter(monkeypatch)
    source = tmp_path/'input.zip'
    source.write_bytes(zip_bytes([('<img onerror=alert(1)>.json', [track()])]))

    def runner(path, timeout):
        batch.run_source_worker(json.loads(path.read_text()))
        return dict(status='EXITED', returncode=0)
    out = tmp_path/'out'
    result = batch.run_archive_batch(source, out, _runner=runner)
    page = batch.render_batch_html(result, out)
    assert '<img onerror' not in page and '&lt;img onerror' in page
