"""Rebuild an offline project from byte-verified, sealed event/fit caches.

Every raw ZIP member is read completely and SHA/CRC checked. This is an explicit
validation accelerator; normal HTTP uploads continue to parse raw trajectories.
Neither cached lamp labels nor cached predictions are supplied to the solver.
"""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter,defaultdict
import argparse
from dataclasses import replace
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import uuid
import zipfile

from scripts.corpus_validation import ROOT,prepare_worker_environment,save,HashReader
prepare_worker_environment()


def main(run_name='verified_v2'):
    from app.core import intersection_project as project
    from app.core.temporal_evidence import TemporalEvent
    from app.core.v9.events import _iter_json_records,_pack_temporal_events
    from app.core.v9.fit import PhaseCountSearch
    from app.core.recovery import engine
    out=ROOT/'evidence/cross_day_sverdlovsky_20261019'
    job=project.read_json(out/'job.json');source=Path(job['input'])
    if Path(run_name).name!=run_name:raise ValueError('run name must be one directory name')
    out=out/run_name;out.mkdir(exist_ok=False)
    sealed=project.read_json(ROOT/'evidence/accuracy_recovery_20261019/release_manifest.json')
    artifacts={r['path']:r for r in sealed['local_reproduction_files']+sealed['evidence_files']}
    corpus_manifest=project.read_json(ROOT/'evidence/all_archives_synthetic_20261019/manifest.json')
    artifacts.update({'evidence/all_archives_synthetic_20261019/'+r['path']:r for r in corpus_manifest['files']})
    code={r['path']:r for r in sealed['source_files']}
    guarded=[*sorted((ROOT/'app/core/recovery').glob('*.py'))]+[
        ROOT/p for p in ('app/core/v9/events.py','app/core/v9/model.py','app/core/v9/fit.py',
                         'app/core/v9/primitives.py','app/core/v9/vehicle_evidence.py','app/core/temporal_evidence.py')]
    for path in guarded:
        key=path.relative_to(ROOT).as_posix()
        assert hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()==code[key]['sha256_lf'],key
    def verified(path):
        key=path.relative_to(ROOT).as_posix();expected=artifacts[key]
        assert path.stat().st_size==expected['bytes'] and project.digest(path)==expected['sha256'],key
        return path
    inv=project.read_json(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')
    jobs={r['member']:r for r in inv['jobs'] if Path(r['path'])==source}
    identifier=uuid.uuid4().hex;folder=ROOT/'logs/intersection_projects'/identifier
    project.write_json(folder/'status.json',dict(status='QUEUED',input_name=source.name))
    save(out/'accelerated_job.json',dict(model_id=identifier,cold_model_id=job['model_id'],
        semantics='fresh raw SHA/CRC verification; sealed motion events; current production solver; verified numerical fit cache'))
    cold={}
    for path in (ROOT/'logs/intersection_projects'/job['model_id']/'sessions').glob('*.gz'):
        try:
            with gzip.open(path,'rt',encoding='utf8') as f:r=json.load(f)
            cold[r['input_scope']['source_member']]=r
        except (EOFError,OSError,ValueError):pass
    assert len(cold)>=3,'need at least three fresh cold predictions for parity guard'
    checks=[];parity=[];fit_hits=[]
    def loader(path,selected):
        member=selected['source_member'];j=jobs[member]
        receipt=project.read_json(verified(ROOT/'evidence/all_archives_synthetic_20261019/ingest'/(j['id']+'.json')))
        assert receipt['crc_checked'] and receipt['job']['crc32']==selected['crc32']
        assert receipt['bytes_read']==selected['uncompressed_bytes']
        stats=receipt['statistics'];samples=defaultdict(list)
        with zipfile.ZipFile(path) as archive,archive.open(member) as raw:
            reader=HashReader(raw);records=_iter_json_records(reader)
            for track in records:
                origin=project._compass(track.get('zone_in'));ds=track.get('detections')
                if origin and isinstance(ds,list) and ds and len(samples[origin])<48:
                    indices=sorted(set([0,len(ds)-1]+list(range(0,len(ds),max(1,len(ds)//16)))))
                    points=[{k:ds[i].get(k) for k in ('millis','centroid_x','centroid_y','zone')}
                            for i in indices if isinstance(ds[i],dict)]
                    samples[origin].append(dict(zone_in=track.get('zone_in'),zone_out=track.get('zone_out'),detections=points))
                if all(len(samples[a])>=48 for a in 'NSEW'):break
            records.close()
            for _ in iter(lambda:reader.read(4*1024**2),b''):pass
            assert reader.bytes==receipt['bytes_read'] and reader.hash.hexdigest()==receipt['sha256'],member
        cache=verified(ROOT/'.web_runtime/accuracy_recovery_20261019/motion_event_cache'/('real_'+j['id']+'.json.gz'))
        with gzip.open(cache,'rt',encoding='utf8') as f:cached=json.load(f)
        events=[replace(TemporalEvent(**e),provenance={**e['provenance'],'source':member}) for e in cached['events']]
        bundle=_pack_temporal_events(events,[member],cached['trajectories'],cached['recording_start'],cached.get('stats',{}))
        checks.append(dict(member=member,raw_sha256=receipt['sha256'],raw_bytes=reader.bytes,crc_checked=True,
            events=len(events),event_cache_sha256=project.digest(cache),statistics={k:v for k,v in stats.items() if k not in ('samples',)},
            samples_per_approach={a:len(s) for a,s in samples.items()}))
        return bundle,dict(record_counts=dict(trajectory_records=stats['tracks'],detections=stats['detections']),samples=samples)
    original=engine.discover_phase_count
    def numerical_search(*args,**kwargs):
        signature=hashlib.sha256(args[0].tobytes()+repr(args[1:]).encode()+repr(sorted(kwargs.items())).encode()).hexdigest()
        cache=ROOT/'.web_runtime/accuracy_recovery_20261019/fit_cache'/(signature+'.pkl')
        if cache.exists() and cache.relative_to(ROOT).as_posix() in artifacts:
            with verified(cache).open('rb') as stream:payload=pickle.load(stream)
            fit_hits.append(signature);return PhaseCountSearch(payload[0],payload[1],payload[2],payload[3])
        return original(*args,**kwargs)
    def predict(bundle,**kwargs):
        result=engine.discover_bundle(bundle,**kwargs);member=bundle[5][0]
        if member in cold:
            expected=cold[member]
            checks_equal={k:result[k]==expected[k] for k in ('schedule','phase_clock','physical_signal_plan','period_inference')}
            parity.append(dict(member=member,checks=checks_equal))
            assert all(checks_equal.values()),parity[-1]
        return result
    engine.discover_phase_count=numerical_search
    last=[None]
    def progress(state):
        done=state['sources_done']
        if done!=last[0]:
            last[0]=done;print('OFFLINE',done,'/',state['sources_total'],'sessions',state['sessions_done'],'seconds',state['elapsed_s'],flush=True)
    try:model=project.run_project(source,folder,predictor=predict,_source_loader=loader,on_progress=progress)
    finally:engine.discover_phase_count=original
    assert len(model['sessions'])==len(jobs)==len(checks) and model['completeness']=='COMPLETE'
    save(out/'source_audit.json',dict(status='PASS',members=checks,guarded_code=[p.relative_to(ROOT).as_posix() for p in guarded],
        cold_parity=parity,numerical_cache_hits=fit_hits))
    save(out/'accelerated_complete.json',dict(status='PASS',model_id=identifier,fingerprint=model['fingerprint'],
        sources=len(checks),sessions=len(model['sessions']),regimes=len(model['regimes']),K=Counter(r['phase_count'] for r in model['regimes'])))
    print('COMPLETE',identifier,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-name',default='verified_v2')
    main(parser.parse_args().run_name)
