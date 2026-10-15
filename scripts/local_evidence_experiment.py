"""Bounded sidecar-only experiment. No annotations, trajectory extraction or fitting."""
import argparse
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from app.core.temporal_evidence import TemporalEvent, EvidenceUnavailable
from app.experimental.local_evidence import build_local_evidence
from scripts.offline_benchmark import ROOT, sha256_file, write_json, git

MAX_BYTES=32*1024*1024
LIMITS={'max_events':20000,'max_seconds':30.0,'worker_timeout_s':30,'files':3,
        'max_prediction_bytes':MAX_BYTES,'window_s':180,'retries':0,'phase_fitting_runs':0}


def read_prediction(path, expected_sha):
    if path.stat().st_size>MAX_BYTES:
        raise EvidenceUnavailable('prediction byte limit exceeded',reason_code='PREDICTION_BYTE_LIMIT')
    raw=path.read_bytes()
    if len(raw)>MAX_BYTES: raise EvidenceUnavailable('prediction byte limit exceeded',reason_code='PREDICTION_BYTE_LIMIT')
    if hashlib.sha256(raw).hexdigest()!=expected_sha: raise ValueError('sealed prediction changed')
    return json.loads(raw)


def inspect_sidecar(prediction, *, source_namespace):
    start=prediction.get('recording_start_timestamp_ms')
    if not isinstance(start,(int,float)) or isinstance(start,bool): raise ValueError('missing recording start')
    raw=prediction['event_extraction']['temporal_events']
    if not isinstance(raw,list): raise ValueError('missing temporal events')
    if len(raw)>LIMITS['max_events']:
        raise EvidenceUnavailable('event input limit exceeded',reason_code='EVIDENCE_EVENT_LIMIT')
    names=[f.name for f in fields(TemporalEvent)]
    events=[]
    for item in raw:
        e=TemporalEvent(**{name:item[name] for name in names})
        if e.to_dict()!=item: raise ValueError('unsupported saved evidence contract; lossless roundtrip required')
        events.append(e)
    index=build_local_evidence(events,source_namespace=source_namespace,
                               max_events=LIMITS['max_events'],max_seconds=LIMITS['max_seconds'])
    view=index.query(start,start+180000)
    old_indices=prediction['event_extraction']['quality_diagnostics']['selected_event_indices']
    if any(isinstance(i,bool) or not isinstance(i,int) or not 0<=i<len(raw) for i in old_indices):
        raise ValueError('invalid saved selected_event_indices')
    old=[i for i in old_indices if start<=raw[i]['timestamp_ms']<start+180000]
    old_set=set(old)
    local=view['events']
    recovered=[e for e in local if e['eligible_vehicle_evidence'] and not old_set.intersection(e['source_indices'])]
    new_eligible_indices={i for e in local if e['eligible_vehicle_evidence'] for i in e['source_indices']}
    assert old_set<=new_eligible_indices, 'previously eligible local evidence lost'
    movements=sorted({e['event']['movement'] for e in local})
    comparison=[]
    for m in movements:
        old_m=[i for i in old if raw[i]['movement']==m]
        new_m=[e for e in local if e['event']['movement']==m and e['eligible_vehicle_evidence']]
        recovered_m=[e for e in recovered if e['event']['movement']==m]
        comparison.append({'movement':m,'old_selected_events':len(old_m),
            'new_eligible_events':len(new_m),
            'new_known_vehicle_groups':len({e['vehicle_group_id'] for e in new_m if e['vehicle_group_id'] is not None}),
            'recovered_event_count':len(recovered_m),
            'recovered_event_types':sorted({e['event']['event_type'] for e in recovered_m})})
    return {'schema':'local-evidence-experiment-v1', 'view':view,
        'input_event_count':index.input_event_count,'deduplicated_event_count':len(index.rows),
        'exact_duplicate_events':index.duplicate_events,
        'old_selected_local_count':len(old),'old_selected_indices':old,
        'new_eligible_local_count':view['counts']['eligible_vehicle_events'],
        'recovered_event_ids':[e['event_id'] for e in recovered],
        'recovered_event_count':len(recovered),'by_movement':comparison,
        'old_selection_preserved':True,'physical_state':'UNKNOWN','new_phase_prediction':None,
        'interpretation':'information retention, not phase or physical lamp accuracy'}


def prepare(baseline,output):
    if output.exists(): raise ValueError('fresh output directory required')
    # Provenance metadata only: no review/adapters/metrics files are opened.
    seal_path=baseline/'predictions_seal.json'
    seal=json.loads(seal_path.read_text(encoding='utf-8'))
    previous=json.loads((baseline/'manifest.json').read_text(encoding='utf-8'))
    sessions={Path(s['source']).name:s['source_sha256'] for s in previous['sessions']}
    inputs=[]
    for row in seal['predictions']:
        if row['status']!='ok': raise ValueError('sealed prediction unavailable')
        path=baseline/row['prediction']
        if sha256_file(path)!=row['prediction_sha256']: raise ValueError('prediction changed')
        inputs.append({'path':str(path.resolve()),'prediction_sha256':row['prediction_sha256'],
                       'source_namespace':sessions[row['source']],'source':row['source']})
    if len(inputs)!=3: raise ValueError('exactly three sealed sources required')
    files=sorted([*ROOT.glob('app/core/**/*.py'),*ROOT.glob('app/experimental/*.py'),
        Path(__file__),ROOT/'tests/test_local_evidence_channels.py',ROOT/'docs/LOCAL_EVIDENCE_CHANNELS_20261015.md'])
    manifest={'base_sha':'b96f81f04d533cf0f721041460db727eb662539d',
        'prepared_head':git('rev-parse','HEAD'),'inputs':inputs,'limits':LIMITS,
        'source_predictions_seal_sha256':sha256_file(seal_path),
        'file_hashes':{str(p.relative_to(ROOT)):sha256_file(p) for p in files},
        'evaluation':'event retention only; no labels/fitting/boundary scoring',
        'exposure':'UNKNOWN; no independent observation windows supplied',
        'source_namespace':'original trajectory SHA256 from prior provenance manifest',
        'window':'first 180s from recording_start_timestamp_ms; fixed protocol, not label crop'}
    output.mkdir(parents=True)
    write_json(output/'manifest.json',manifest)
    (output/'manifest.sha256').write_text(sha256_file(output/'manifest.json')+'\n',encoding='ascii')


def run(output):
    expected=(output/'manifest.sha256').read_text().strip()
    if sha256_file(output/'manifest.json')!=expected: raise ValueError('manifest seal changed')
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if manifest['limits']!=LIMITS: raise ValueError('limits changed')
    for relative,digest in manifest['file_hashes'].items():
        if sha256_file(ROOT/relative)!=digest: raise ValueError('frozen code changed: '+relative)
    with (output/'started.json').open('x',encoding='utf-8') as f:
        json.dump({'manifest_sha256':expected,'code_commit':git('rev-parse','HEAD')},f)
    rows=[]
    for entry in manifest['inputs']:
        started=time.monotonic()
        out=output/'views'/(Path(entry['source']).stem+'.json')
        cmd=[sys.executable,'-m','scripts.local_evidence_experiment','worker','--prediction',entry['path'],
             '--sha256',entry['prediction_sha256'],'--namespace',entry['source_namespace'],'--out',str(out)]
        print('Sidecar only:',entry['source'],flush=True)
        row={'source':entry['source'],'prediction_sha256':entry['prediction_sha256']}
        try:
            p=subprocess.run(cmd,cwd=ROOT,capture_output=True,timeout=LIMITS['worker_timeout_s'],
                env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            row.update(status='ok' if p.returncode==0 else 'unavailable',exit_code=p.returncode,
                       stderr=p.stderr.decode('utf-8',errors='replace')[-2000:])
            if p.returncode==0:
                artifact=json.loads(out.read_text(encoding='utf-8'))
                row.update(view_file=str(out.relative_to(output)),view_sha256=sha256_file(out),
                    summary={k:artifact[k] for k in ('old_selected_local_count','new_eligible_local_count',
                        'recovered_event_count','exact_duplicate_events','old_selection_preserved','by_movement')},
                    counts=artifact['view']['counts'],observation_support=artifact['view']['observation_support'])
        except subprocess.TimeoutExpired:
            row.update(status='unavailable',reason='WORKER_TIMEOUT_NO_RETRY')
        row['runtime_s']=time.monotonic()-started
        assert sha256_file(Path(entry['path']))==entry['prediction_sha256']
        rows.append(row)
        write_json(output/'comparison.json',{'manifest_sha256':expected,'rows':rows,
            'phase_metrics':'unchanged; not re-evaluated','phase_fitting_runs':0})
        print(row['status'],row.get('summary',{}).get('recovered_event_count'),round(row['runtime_s'],3),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','run','worker'])
    p.add_argument('--baseline',type=Path)
    p.add_argument('--out',required=True,type=Path)
    p.add_argument('--prediction',type=Path)
    p.add_argument('--sha256')
    p.add_argument('--namespace')
    a=p.parse_args()
    if a.command=='prepare': prepare(a.baseline,a.out)
    elif a.command=='run': run(a.out)
    else:
        prediction=read_prediction(a.prediction,a.sha256)
        artifact=inspect_sidecar(prediction,source_namespace=a.namespace)
        write_json(a.out,artifact)


if __name__=='__main__': main()
