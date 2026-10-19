"""Reproducible all-member validation; video and annotations are never inputs.

Run with the project interpreter: python -m scripts.corpus_validation --help.
Runtime caches live outside versioned evidence. Every input is independently
partitioned with production session semantics before running either solver.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import asdict
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SITES = {'17': 'lenina_sverdlovsky', '6': 'lenina_entuziastov', '19': 'chicherina_40let'}


def prepare_worker_environment():
    """Avoid a failing WMI architecture query in disposable Windows workers.

    Python's own fallback uses these same OS-provided architecture variables.
    Only command-line validation workers use this; application code is untouched.
    Numerical algorithms, source data, search bounds and seeds stay unchanged.
    """
    if sys.platform=='win32':
        import platform
        arch=os.environ.get('PROCESSOR_ARCHITEW6432') or os.environ.get('PROCESSOR_ARCHITECTURE')
        if arch:platform._get_machine_win32=lambda:arch


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Immutable receipts: reruns require a new output path or explicit resume.
    with path.open('x', encoding='utf8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, default=str)


def inventory(data):
    jobs, exclusions = [], []
    for path in sorted(Path(data).iterdir()):
        if path.suffix.lower() == '.zip':
            with zipfile.ZipFile(path) as archive:
                members = [i for i in archive.infolist() if not i.is_dir() and i.filename.lower().endswith('.json')]
                raw = [i for i in members if re.fullmatch(r'(?:.*/)?(?:17|19|6)_\d{4}_\d+_\d+_\d+\.json', i.filename)]
                if not raw:
                    exclusions.append(dict(path=str(path), reason='code_or_validation_fixtures_NOT_raw_traffic', json_count=len(members)))
                    continue
                for member in raw:
                    jobs.append(dict(path=str(path.resolve()), member=member.filename, bytes=member.file_size,
                                     crc32=f'{member.CRC:08x}', archive_bytes=path.stat().st_size))
        elif path.suffix.lower() == '.json' and re.fullmatch(r'(17|19|6)_\d{4}_\d+_\d+_\d+\.json', path.name):
            jobs.append(dict(path=str(path.resolve()), member=None, bytes=path.stat().st_size))
    for i, job in enumerate(jobs):
        job['id'] = f'{i:04d}'
        job['source_name'] = job['member'] or Path(job['path']).name
        job['site'] = SITES.get(Path(job['source_name']).name.split('_')[0])
    return dict(schema='all-raw-traffic-inventory-v1', jobs=jobs, exclusions=exclusions,
                raw_member_count=len(jobs), uncompressed_bytes=sum(j['bytes'] for j in jobs))


class HashReader:
    def __init__(self, stream):
        self.stream, self.hash, self.bytes = stream, hashlib.sha256(), 0

    def read(self, size=-1):
        chunk = self.stream.read(size)
        self.hash.update(chunk)
        self.bytes += len(chunk)
        return chunk


class CorpusStats:
    """Bounded, deterministic samples; not a copy of 46 GB of detections."""
    def __init__(self, seed=0, capacity=4096):
        self.rng, self.capacity = random.Random(seed), capacity
        self.samples, self.counts = defaultdict(list), Counter()
        self.movements, self.classes = Counter(), Counter()
        self.tracks = self.detections = 0
        self.start = self.end = None

    def add(self, key, value):
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return
        self.counts[key] += 1
        sample = self.samples[key]
        if len(sample) < self.capacity:
            sample.append(value)
        else:
            index = self.rng.randrange(self.counts[key])
            if index < self.capacity:
                sample[index] = value

    def observe(self, records):
        for track in records:
            self.tracks += 1
            ds = track.get('detections') or []
            self.detections += len(ds)
            self.movements[f"{track.get('zone_in')}->{track.get('zone_out')}"] += 1
            self.classes[str(track.get('category_name', 'unknown'))] += 1
            valid = [d for d in ds if isinstance(d, dict) and isinstance(d.get('millis'), (int, float))]
            if valid:
                a, b = min(d['millis'] for d in valid), max(d['millis'] for d in valid)
                self.start = a if self.start is None else min(self.start, a)
                self.end = b if self.end is None else max(self.end, b)
                self.add('track_duration_s', (b-a)/1000)
                self.add('detections_per_track', len(valid))
                # Uniformly sample at most eight steps from each track, then a
                # reservoir across tracks: label this sampling scope explicitly.
                if len(valid) > 1:
                    for i in self.rng.sample(range(1, len(valid)), min(8, len(valid)-1)):
                        delta = (valid[i]['millis']-valid[i-1]['millis'])/1000
                        self.add('detection_step_s', delta)
                        self.add('raw_speed', valid[i].get('speed'))
                self.add('wait_metadata_s', max(float(track.get('wait_s') or 0), float(track.get('stay_duration_millis') or 0)/1000))
            yield track

    def result(self):
        import numpy as np
        return dict(tracks=self.tracks, detections=self.detections, movements=dict(self.movements),
                    vehicle_classes=dict(self.classes), start_ms=self.start, end_ms=self.end,
                    samples=dict(self.samples), sample_counts=dict(self.counts),
                    quantiles={k: dict(zip(('p05','p25','p50','p75','p95'), map(float, np.quantile(v,[.05,.25,.5,.75,.95]))))
                               for k,v in self.samples.items() if v},
                    sample_scope='deterministic bounded per-member reservoirs; at most 8 adjacent steps per track; NOT detection-weighted exact quantiles')


@contextmanager
def source_stream(job):
    if job.get('member'):
        with zipfile.ZipFile(job['path']) as archive:
            with archive.open(job['member']) as stream:
                yield HashReader(stream)
    else:
        with Path(job['path']).open('rb') as stream:
            yield HashReader(stream)


def sample_environment(inventory_path,out,records=256):
    """A declared bounded sample from every archive; never a full-read claim."""
    import itertools
    from app.core.v9.events import _iter_json_records
    inv=json.loads(Path(inventory_path).read_text(encoding='utf8'));archives={}
    for job in inv['jobs']:
        if job.get('member'):archives.setdefault(job['path'],[]).append(job)
    for jobs in archives.values():
        job=sorted(jobs,key=lambda j:j['bytes'])[len(jobs)//2]
        stats=CorpusStats(seed=int(job['id']))
        with source_stream(job) as reader:
            for _ in stats.observe(itertools.islice(_iter_json_records(reader),records)):pass
            prefix,size=reader.hash.hexdigest(),reader.bytes
        save(Path(out)/f"{job['id']}.json",dict(job=job,statistics=stats.result(),prefix_sha256=prefix,bytes_read=size,
             sample_scope=f'first {records} trajectories of median-size member in each archive; partial read, CRC NOT checked, NOT a full-file SHA or traffic-weighted sample'))


def predict_modes(bundle, *, site=None, automatic=True, learned_window_s=3600):
    """Only events and a frozen training profile enter inference; no truth args."""
    from app.core.v9.model import _discover_bundle
    from app.core.v9.source_scope import input_sessions, choose_session, attach_input_scope
    from app.core.v9.primitives import infer_period
    from app.core.learned_phase import predict_profile
    sessions = input_sessions(bundle, 'records')
    output = []
    for session in sessions:
        scoped, selected, choices = choose_session(bundle, 'records', session.metadata['session_id'])
        row = dict(session=selected)
        begin = time.monotonic()
        if automatic:
            try:
                automatic_result = _discover_bundle(scoped, input_name='trajectory-only validation', dt=1.,
                    marks_path=None, evidence_policy='permission_per_stream', experimental_local_history=False)
                attach_input_scope(automatic_result, 'records', selected, choices)
                row['automatic'] = dict(status='ok', result=automatic_result)
            except Exception as exc:
                row['automatic'] = dict(status='abstained' if hasattr(exc, 'reason_code') else 'failed',
                    error=type(exc).__name__+': '+str(exc), reason_code=getattr(exc,'reason_code',None))
            row['automatic']['runtime_s'] = time.monotonic()-begin
        if site:
            begin = time.monotonic()
            try:
                model_path = ROOT/'config/learned_profiles'/f'{site}.json'
                model = json.loads(model_path.read_text(encoding='utf8'))
                period, info = infer_period(scoped[1])
                chunks = []
                start, end = selected['observation_start_ms'], selected['observation_end_ms']
                while start < end:
                    stop = min(end, start+learned_window_s*1000)
                    try:
                        result = predict_profile(scoped.temporal_events, model, start_ms=start, end_ms=stop, period_s=period)
                        chunks.append(dict(status='ok', result=result))
                    except Exception as exc:
                        chunks.append(dict(status='failed', start_ms=start, end_ms=stop, error=str(exc)))
                    start = stop
                row['learned'] = dict(status='ok' if all(c['status']=='ok' for c in chunks) else 'partial',
                    period_s=period, period_info=info, chunks=chunks, site=site,
                    model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                    count_source='operator_training_labels_NOT_automatic',
                    chunk_semantics=f'independent <={learned_window_s}s windows; no cross-window continuity claim',
                    prediction_window_limit_s=learned_window_s)
            except Exception as exc:
                row['learned'] = dict(status='failed', error=type(exc).__name__+': '+str(exc))
            row['learned']['runtime_s'] = time.monotonic()-begin
        output.append(row)
    return output


def compact_predictions(rows):
    compact = []
    for row in rows:
        item = dict(session=row['session'])
        for mode in ('automatic','learned'):
            if mode not in row:
                continue
            value = {k:v for k,v in row[mode].items() if k not in ('result','chunks')}
            if 'result' in row[mode]:
                result = row[mode]['result']
                value.update(phase_count=result['schedule']['phase_count'], period_s=result['schedule']['period_s'],
                    input_scope=result.get('input_scope'), model_selection=result.get('phase_model_selection'),
                    event_count=result.get('event_count'))
            if 'chunks' in row[mode]:
                value['chunks'] = [dict(status=c['status'], start_ms=c.get('result',{}).get('analysis_base_timestamp_ms',c.get('start_ms')),
                    duration_s=c.get('result',{}).get('recording_duration_s'),
                    phase_count=c.get('result',{}).get('schedule',{}).get('phase_count'), error=c.get('error')) for c in row[mode]['chunks']]
            item[mode] = value
        compact.append(item)
    return compact


def worker(inventory_path, job_id, evidence, runtime):
    prepare_worker_environment()
    from app.core.v9.events import _iter_json_records, load_event_streams
    job = next(j for j in json.loads(Path(inventory_path).read_text(encoding='utf8'))['jobs'] if j['id']==job_id)
    begin = time.monotonic()
    stats = CorpusStats(seed=int(job_id))
    receipt = dict(job=job, runtime_input='raw trajectory JSON only', namespace_alias='records')
    try:
        with source_stream(job) as reader:
            bundle = load_event_streams(Path('records'), _records=stats.observe(_iter_json_records(reader)))
            receipt.update(sha256=reader.hash.hexdigest(), bytes_read=reader.bytes, crc_checked=bool(job.get('member')))
        receipt['ingest_s'] = time.monotonic()-begin
        receipt['statistics'] = stats.result()
        receipt['evidence_diagnostics'] = bundle.diagnostics
        cache = Path(runtime)/f'{job_id}_events.json.gz'
        with gzip.open(cache, 'xt', encoding='utf8') as stream:
            json.dump(dict(events=[asdict(e) for e in bundle.temporal_events], files=bundle[5],
                trajectories=bundle[8], recording_start=bundle[6], stats={}), stream, separators=(',',':'))
        # Ingest checkpoint remains usable even if a solver times out later.
        save(Path(evidence)/'ingest'/f'{job_id}.json', receipt)
        predictions = predict_modes(bundle, site=job.get('site'))
        with gzip.open(Path(runtime)/f'{job_id}_predictions.json.gz', 'xt', encoding='utf8') as stream:
            json.dump(predictions, stream, default=str)
        receipt['predictions'] = compact_predictions(predictions)
        receipt['status'] = 'processed'
    except Exception as exc:
        receipt.update(status='failed', error=type(exc).__name__+': '+str(exc), traceback=traceback.format_exc())
        receipt.setdefault('statistics',stats.result())
    receipt['runtime_s'] = time.monotonic()-begin
    save(Path(evidence)/'results'/f'{job_id}.json', receipt)


def replay_learned_one(job, evidence, runtime):
    prepare_worker_environment()
    from app.core.temporal_evidence import TemporalEvent
    from app.core.v9.events import _pack_temporal_events
    evidence,runtime=Path(evidence),Path(runtime)
    output=evidence/'learned_replay'/f"{job['id']}.json"
    if output.exists():return job['id'],'existing'
    begin=time.monotonic()
    try:
        with gzip.open(runtime/f"{job['id']}_events.json.gz",'rt',encoding='utf8') as stream:cache=json.load(stream)
        bundle=_pack_temporal_events([TemporalEvent(**e) for e in cache['events']],cache['files'],
                                    cache['trajectories'],cache['recording_start'],cache['stats'])
        predictions=predict_modes(bundle,site=job['site'],automatic=False,learned_window_s=10800)
        with gzip.open(runtime/f"{job['id']}_production_learned.json.gz",'xt',encoding='utf8') as stream:json.dump(predictions,stream)
        receipt=dict(job=job,status='processed',predictions=compact_predictions(predictions),
                     scope='production predictor window bound 10800s; frozen profile; no video/labels passed')
    except Exception as exc:
        receipt=dict(job=job,status='failed',error=type(exc).__name__+': '+str(exc))
    receipt['runtime_s']=time.monotonic()-begin
    save(output,receipt)
    return job['id'],receipt['status']


def replay_learned(evidence,runtime,workers=4):
    from concurrent.futures import ProcessPoolExecutor,as_completed
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
    inv=json.loads((Path(evidence)/'inventory.json').read_text(encoding='utf8'))
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures=[executor.submit(replay_learned_one,job,str(evidence),str(runtime)) for job in inv['jobs']]
        for future in as_completed(futures):print(*future.result(),flush=True)


def run(data, evidence, runtime, *, concurrency=2, timeout_s=600, resume=False):
    evidence, runtime = Path(evidence), Path(runtime)
    runtime.mkdir(parents=True, exist_ok=True)
    inv_path = evidence/'inventory.json'
    if not inv_path.exists():
        inv = inventory(data)
        save(inv_path, inv)
    elif resume:
        inv = json.loads(inv_path.read_text(encoding='utf8'))
    else:
        raise ValueError('inventory exists; use --resume or a new output directory')
    pending = [j for j in inv['jobs'] if not (evidence/'results'/f"{j['id']}.json").exists()]
    active = []
    env = {**os.environ, 'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    print(f"Inventory {len(inv['jobs'])} sources, {inv['uncompressed_bytes']:,} uncompressed bytes; pending {len(pending)}", flush=True)
    while pending or active:
        while pending and len(active)<concurrency:
            job = pending.pop(0)
            log = (runtime/f"{job['id']}.log").open('ab')
            process = subprocess.Popen([sys.executable,'-m','scripts.corpus_validation','worker',
                '--inventory',str(inv_path.resolve()),'--job',job['id'],'--evidence',str(evidence.resolve()),'--runtime',str(runtime.resolve())],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            active.append((job,process,time.monotonic(),log))
        for entry in active[:]:
            job,process,begin,log = entry
            expired = time.monotonic()-begin>timeout_s
            code = process.poll()
            if code is None and not expired:
                continue
            if code is None:
                process.kill()
                process.wait()
            log.close()
            target = evidence/'results'/f"{job['id']}.json"
            if not target.exists():
                save(target,dict(job=job,status='timeout' if expired else 'worker_failed',exit_code=process.returncode,
                    runtime_s=time.monotonic()-begin,ingest_checkpoint_exists=(evidence/'ingest'/f"{job['id']}.json").exists()))
            result = json.loads(target.read_text(encoding='utf8'))
            print(f"{job['id']} {result['status']} {time.monotonic()-begin:.1f}s {job['source_name']}",flush=True)
            active.remove(entry)
        if active:
            time.sleep(.25)
    print('All inventoried sources have terminal receipts.',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    scan=sub.add_parser('run')
    scan.add_argument('--data',type=Path,required=True)
    scan.add_argument('--evidence',type=Path,required=True)
    scan.add_argument('--runtime',type=Path,required=True)
    scan.add_argument('--concurrency',type=int,default=2)
    scan.add_argument('--timeout-s',type=float,default=600)
    scan.add_argument('--resume',action='store_true')
    one=sub.add_parser('worker')
    one.add_argument('--inventory',type=Path,required=True)
    one.add_argument('--job',required=True)
    one.add_argument('--evidence',type=Path,required=True)
    one.add_argument('--runtime',type=Path,required=True)
    replay=sub.add_parser('replay-learned')
    replay.add_argument('--evidence',type=Path,required=True)
    replay.add_argument('--runtime',type=Path,required=True)
    replay.add_argument('--workers',type=int,default=4)
    sample=sub.add_parser('sample-environment')
    sample.add_argument('--inventory',type=Path,required=True)
    sample.add_argument('--out',type=Path,required=True)
    sample.add_argument('--records',type=int,default=256)
    args=vars(parser.parse_args());command=args.pop('command')
    if command=='run':run(**args)
    elif command=='worker':worker(args.pop('inventory'),args.pop('job'),**args)
    elif command=='replay-learned':replay_learned(**args)
    else:sample_environment(args.pop('inventory'),**args)


if __name__=='__main__':
    main()
