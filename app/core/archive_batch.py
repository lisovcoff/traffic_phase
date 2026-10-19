"""Sequential, process-isolated archive jobs. Never merge sources or sessions.

Budgets bound wall time, input/output bytes and attempted sessions. They are NOT
a hard resident-memory limit. An interrupted source can retain completed jobs.
No annotations, new decoder, hyperparameter selection or physical-state claims.
"""
from dataclasses import asdict, dataclass
import hashlib
import html
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from app.core.v9.source_scope import choose_source, ScopeChoiceRequired

ROOT = Path(__file__).resolve().parents[2]

# Inline so exported HTML works offline. Size from natural body content, not
# document.scrollHeight (which can feed the iframe viewport back into a loop).
FIT_FRAME_SCRIPT = '''function fitFrame(frame){
  if(frame._sizeObserver)frame._sizeObserver.disconnect();
  frame.onload=()=>{
    const doc=frame.contentDocument;
    const resize=()=>{const style=doc.defaultView.getComputedStyle(doc.body);
      const height=Math.ceil(doc.body.getBoundingClientRect().height+parseFloat(style.marginTop)+parseFloat(style.marginBottom)+4);
      if(Math.abs(frame.clientHeight-height)>2)frame.style.height=height+'px';};
    frame._sizeObserver=new ResizeObserver(resize);frame._sizeObserver.observe(doc.body);resize();
  };
}'''


@dataclass(frozen=True)
class BatchConfig:
    dt: float = 1.0
    max_jobs: int = 4
    total_seconds: float = 180.0
    source_seconds: float = 90.0
    max_source_bytes: int = 512 * 1024 * 1024
    max_total_source_bytes: int = 1024 * 1024 * 1024
    max_output_bytes: int = 64 * 1024 * 1024

    def __post_init__(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'invalid positive finite batch budget: {name}')
        for name in ('max_jobs', 'max_source_bytes', 'max_total_source_bytes', 'max_output_bytes'):
            if not isinstance(getattr(self, name), int):
                raise ValueError(f'integer budget required: {name}')
        if self.max_jobs > 512 or self.dt != 1.0:
            raise ValueError('batch supports at most 512 jobs and the unchanged dt=1s configuration')
        if self.max_output_bytes < 1024 * 1024:
            raise ValueError('reserve at least 1 MiB for manifests and unavailable diagnostics')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value, *, max_bytes=1024 * 1024):
    """Bound the serialized file as it is written; replace only our own artifact."""
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    size = 0
    try:
        with temporary.open('wb') as stream:
            for chunk in json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':')).iterencode(value):
                raw = chunk.encode('utf-8')
                size += len(raw)
                if size > max_bytes:
                    raise ValueError('OUTPUT_BYTE_BUDGET_EXCEEDED')
                stream.write(raw)
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _unavailable(row, reason):
    row.update(status='UNAVAILABLE', reason=reason, phase_count=None, estimated_state='UNKNOWN')


def run_source_worker(request):
    """Internal worker: one extraction, unchanged fitting on separate session views."""
    import numpy as np
    from app.core.temporal_evidence import EvidenceUnavailable
    from app.core.v9.events import load_event_streams
    from app.core.v9.model import _discover_bundle
    from app.core.v9.source_scope import input_sessions, choose_session, attach_input_scope
    from app.core.offline_product_report import render_product_html

    np.random.seed(0)
    config = BatchConfig(**request['config'])
    output = Path(request['output'])
    source = request['source_member']
    checkpoint = output/'checkpoint.json'
    started = time.monotonic()
    state = dict(source_member=source, inventory_complete=False, jobs=[])
    write_json(checkpoint, state)
    try:
        recovery = request.get('algorithm_version', 'legacy_v9') == 'trajectory_recovery_v1'
        extractor = {}
        if recovery:
            from app.core.recovery.motion import extract_motion_evidence
            extractor['_event_extractor'] = extract_motion_evidence
        bundle = load_event_streams(Path(request['input']), source_member=source, **extractor)
        sessions = [s.metadata for s in input_sessions(bundle, source)]
        state.update(inventory_complete=True, extraction_seconds=time.monotonic()-started)
        state['jobs'] = [dict(session=s, status='PLANNED') for s in sessions]
        write_json(checkpoint, state)
        used = 0
        for index, row in enumerate(state['jobs']):
            if index >= request['remaining_jobs']:
                _unavailable(row, 'JOB_COUNT_BUDGET')
                continue
            row.update(status='RUNNING', attempted=True)
            write_json(checkpoint, state)
            tick = time.monotonic()
            try:
                scoped, selected, choices = choose_session(bundle, source, row['session']['session_id'])
                if recovery:
                    from app.core.recovery.engine import discover_bundle
                    result = discover_bundle(scoped, input_name=request['input'], dt=config.dt)
                else:
                    result = _discover_bundle(scoped, input_name=request['input'], dt=config.dt,
                        marks_path=None, evidence_policy='permission_per_stream',
                        source_files=[request['input']], experimental_local_history=False)
                attach_input_scope(result, source, selected, choices, source_count=request['source_count'])
                filename = f'session_{index+1:04d}'
                predicted = output/(filename+'.json')
                remaining = request['remaining_output_bytes'] - used
                write_json(predicted, result, max_bytes=min(16*1024*1024, max(0, remaining-65536)))
                used += predicted.stat().st_size
                page = render_product_html(result).encode('utf-8')
                if len(page) > min(8*1024*1024, request['remaining_output_bytes']-used-65536):
                    raise ValueError('OUTPUT_BYTE_BUDGET_EXCEEDED')
                report = output/(filename+'.html')
                report.write_bytes(page)
                used += len(page)
                row.update(status='ESTIMATED', prediction=predicted.name, report=report.name,
                           prediction_sha256=sha256_file(predicted), report_sha256=sha256_file(report),
                           phase_count=result.get('schedule', {}).get('phase_count'),
                           period_s=result.get('schedule', {}).get('period_s'),
                           event_count=result.get('event_count'), trajectory_count=result.get('trajectory_count'),
                           analysis_scope=result['input_scope']['analysis_scope'],
                           physical_state='UNKNOWN', local_deviation_validation='FAIL_2D.1')
            except EvidenceUnavailable as exc:
                _unavailable(row, exc.reason_code)
            except (ValueError, TypeError, KeyError, OSError, MemoryError) as exc:
                _unavailable(row, f'{type(exc).__name__}: {str(exc)[:500]}')
            row['runtime_s'] = round(time.monotonic()-tick, 4)
            write_json(checkpoint, state)
        write_json(checkpoint, state)
    except EvidenceUnavailable as exc:
        state['source_error'] = exc.to_dict()
        write_json(checkpoint, state)
    except (ValueError, TypeError, KeyError, OSError, MemoryError) as exc:
        state['source_error'] = dict(reason=f'{type(exc).__name__}: {str(exc)[:500]}')
        write_json(checkpoint, state)


def _run_worker(request_file, timeout):
    """Same subprocess isolation pattern as offline_benchmark; kill/wait on timeout."""
    env = {**os.environ, 'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1',
           'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    # Worker stdout/stderr are discarded rather than accumulated without a limit.
    started = time.monotonic()
    try:
        completed = subprocess.run([sys.executable, '-m', 'scripts.archive_batch',
                                    '_worker', str(request_file)], cwd=ROOT, env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   timeout=timeout)
        return dict(status='EXITED', returncode=completed.returncode,
                    runtime_s=time.monotonic()-started)
    except subprocess.TimeoutExpired:
        return dict(status='TIMEOUT', runtime_s=time.monotonic()-started)


def run_archive_batch(path, output, *, config=BatchConfig(), _runner=None, algorithm_version='legacy_v9'):
    """Fresh output directory only. Source inventory is metadata-only, not a union."""
    path, output = Path(path).resolve(), Path(output).resolve()
    if algorithm_version not in ('legacy_v9', 'trajectory_recovery_v1'):
        raise ValueError('unknown algorithm_version')
    if not path.is_file() or path.suffix.lower() not in ('.json', '.zip'):
        raise ValueError('batch requires one trajectory JSON or ZIP')
    if path.stat().st_size > config.max_source_bytes:
        raise ValueError('UPLOAD_BYTE_BUDGET_EXCEEDED')
    started = time.monotonic()
    try:
        _, sources = choose_source(path, max_bytes=config.max_source_bytes)
    except ScopeChoiceRequired as exc:
        sources = exc.choices
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(schema='traffic-phase-batch-v1', input_name=path.name,
        input_sha256=sha256_file(path), config=asdict(config), sources=sources,
        code_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        code_dirty=bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip()),
        code_sha256_lf={str(p.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(
            p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
            for p in sorted([*ROOT.glob('app/**/*.py'), ROOT/'scripts/archive_batch.py'])},
        model_config=dict(algorithm_version=algorithm_version, evidence_policy='permission_per_stream', seed=0,
                          phase_search=('supported_bernoulli_or_conditional_mark_bic_then_permission_signature_merge'
                                        if algorithm_version == 'trajectory_recovery_v1' else 'unchanged_2C_default'),
                          experimental_local_history=False),
        semantics='independent source/session estimates; NO global archive K or physical lamp accuracy',
        resource_scope='hard worker wall timeout; byte/job budgets; NO hard RAM limit',
        sources_processed=[], status='RUNNING')
    write_json(output/'manifest.json', manifest)
    attempted = 0
    admitted_bytes = 0
    runner = _runner or _run_worker
    for index, source in enumerate(sources):
        row = dict(source_member=source['source_member'], inventory_complete=False, jobs=[])
        remaining_time = config.total_seconds - (time.monotonic()-started)
        reason = ('JOB_COUNT_BUDGET' if attempted >= config.max_jobs else
                  'TOTAL_TIME_BUDGET' if remaining_time <= 0 else
                  'SOURCE_BYTE_BUDGET' if source['uncompressed_bytes'] > config.max_source_bytes else
                  'TOTAL_SOURCE_BYTE_BUDGET' if admitted_bytes+source['uncompressed_bytes'] > config.max_total_source_bytes else None)
        used = sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        if used >= config.max_output_bytes-1024*1024:
            reason = reason or 'OUTPUT_BYTE_BUDGET'
        if reason:
            row.update(status='UNAVAILABLE', reason=reason)
        else:
            admitted_bytes += source['uncompressed_bytes']
            folder = output/f'source_{index+1:04d}'
            folder.mkdir()
            request = dict(input=str(path), output=str(folder), source_member=source['source_member'],
                           algorithm_version=algorithm_version,
                           source_count=len(sources), remaining_jobs=config.max_jobs-attempted,
                           # Reserve room for the self-contained index (it embeds reports)
                           # and manifests. Download ZIP is a separately bounded copy.
                           remaining_output_bytes=(config.max_output_bytes-used-1024*1024)//2,
                           config=asdict(config))
            write_json(folder/'request.json', request)
            process = runner(folder/'request.json', min(config.source_seconds, remaining_time))
            if (folder/'checkpoint.json').is_file():
                row.update(json.loads((folder/'checkpoint.json').read_text(encoding='utf-8')))
            row['process'] = process
            row['artifact_directory'] = folder.name
            for job in row['jobs']:
                attempted += int(job.get('attempted', False))
                if job['status'] in ('RUNNING', 'PLANNED'):
                    _unavailable(job, 'SOURCE_TIMEOUT' if process['status'] == 'TIMEOUT' else 'WORKER_INTERRUPTED')
            row['status'] = ('ESTIMATED' if row['inventory_complete'] and row['jobs'] and
                             all(j['status'] == 'ESTIMATED' for j in row['jobs']) else 'PARTIAL_OR_UNAVAILABLE')
            if not row['inventory_complete']:
                row['reason'] = ('SOURCE_TIMEOUT_BEFORE_SESSION_INVENTORY' if process['status'] == 'TIMEOUT' else
                                 row.get('source_error', {}).get('reason', 'SESSION_INVENTORY_UNAVAILABLE'))
        manifest['sources_processed'].append(row)
        write_json(output/'manifest.json', manifest)
    manifest.update(status=('COMPLETE_ESTIMATES' if all(s['status'] == 'ESTIMATED' for s in manifest['sources_processed'])
                            else 'PARTIAL_OR_UNAVAILABLE'), attempted_jobs=attempted,
                    runtime_s=round(time.monotonic()-started, 4),
                    session_inventory_complete=all(s['inventory_complete'] for s in manifest['sources_processed']))
    write_json(output/'manifest.json', manifest)
    return manifest


def render_batch_html(manifest, folder):
    """Self-contained index, safe text labels, common-contract per-session reports."""
    cards, reports = [], []
    for source in manifest['sources_processed']:
        label = html.escape(source['source_member'])
        if not source['jobs']:
            cards.append(f'<li><b>{label}</b> — UNKNOWN: {html.escape(source.get("reason", "UNAVAILABLE"))}; число сеансов неизвестно</li>')
        for job in source['jobs']:
            session = job['session']
            text = f'{label} · сеанс {session["session_number"]}'
            if job['status'] == 'ESTIMATED':
                report = Path(folder)/source['artifact_directory']/job['report']
                reports.append(report.read_text(encoding='utf-8'))
                text += (f' · K={job["phase_count"]}, период {job["period_s"]:.3f} с · '
                         f'{job["event_count"]} событий · {html.escape(job["analysis_scope"])} '
                         f'<button type="button" data-report="{len(reports)-1}">Открыть результат</button>')
            else:
                text += ' — UNKNOWN: '+html.escape(job.get('reason', 'UNAVAILABLE'))
            cards.append('<li>'+text+'</li>')
    data = json.dumps(reports, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    page = ('<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Traffic Phase — архив</title><style>*{box-sizing:border-box}body{font-family:system-ui;background:#10151d;color:#edf2f7;margin:0;padding:20px;overflow-wrap:anywhere}'
        'main{max-width:1100px;margin:auto}li{margin:14px 0}button{padding:8px;margin:5px}iframe{width:100%;height:850px;border:1px solid #555}p{line-height:1.5}</style>'
        '<main><h1>Результаты по сеансам</h1><p>Статус: '+html.escape(manifest['status'])+
        '. Архив не объединён в один цикл. Физические лампы и тип секций: UNKNOWN. Продления: 2D.1 FAIL.</p>'
        '<p>Обработано попыток: '+str(manifest['attempted_jobs'])+'. Необработанные источники и timeout не означают отсутствие фаз. '
        'Поддержка траекторий не является покрытием камеры. Длинный сеанс может быть представлен только выбранным окном.</p><ul>'+''.join(cards)+
        '</ul><iframe id="batch-report" title="Результат сеанса" hidden></iframe></main><script>'+FIT_FRAME_SCRIPT+'const reports='+data+
        ';document.querySelectorAll("[data-report]").forEach(b=>b.onclick=()=>{const f=document.querySelector("#batch-report");'
        'fitFrame(f);f.srcdoc=reports[Number(b.dataset.report)];f.hidden=false;});</script></html>')
    used = sum(p.stat().st_size for p in Path(folder).rglob('*') if p.is_file())
    if len(page.encode('utf-8'))+used > manifest['config']['max_output_bytes']:
        raise ValueError('OUTPUT_BYTE_BUDGET_EXCEEDED')
    return page
