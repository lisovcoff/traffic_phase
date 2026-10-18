"""Bounded candidate: repack exact events with per-track selection; no labels."""
import argparse
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'benchmarks/manual_marks_20261018_baseline/predictions'
OUT=ROOT/'benchmarks/per_track_permission_20261018'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def infer(source,target):
    import numpy as np
    np.random.seed(0)
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.v9.events import _pack_temporal_events
    from app.core.v9.model import _discover_bundle
    from app.core.v9 import vehicle_evidence
    old,before=cached_bundle(source)  # Verify the original selection first.
    vehicle_evidence.select_permission_events=vehicle_evidence.select_permission_events_per_track
    bundle=_pack_temporal_events(before.temporal_events,before[5],before[8],before[6],
        before.diagnostics['track_quality_counts'])
    assert list(bundle.temporal_events)==list(before.temporal_events)
    assert bundle[0]==before[0] and bundle[1]==before[1]
    assert bundle[6:]==before[6:]
    result=_discover_bundle(bundle,input_name=old['input'],dt=1.,marks_path=None,
        evidence_policy='permission_per_stream',source_files=old['archive']['source_files'],
        experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref']={'file':source.relative_to(ROOT).as_posix(),'sha256':sha(source)}
    result['per_track_candidate']={'old_selected':before.diagnostics['selected_event_count'],
        'new_selected':bundle.diagnostics['selected_event_count'],
        'events_demand_anchors_unchanged':True,'labels_used':False,'dt':1.,'seed':0}
    save(target,result)


def freeze():
    OUT.mkdir(exist_ok=False)
    save(OUT/'freeze.json',dict(code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        worker_sha256=sha(Path(__file__)),selector_sha256=sha(ROOT/'app/core/v9/vehicle_evidence.py'),
        inputs=[dict(name=p.name,sha256=sha(p)) for p in sorted(SOURCE.glob('*.json'))],
        candidate='per_track_selection_only',dt=1,seed=0,timeout_s=90,max_workers=3,
        max_total_worker_s=270,parameter_search=False,labels_in_inference=False))


def run():
    plan=json.loads((OUT/'freeze.json').read_text(encoding='utf8'))
    assert sha(Path(__file__))==plan['worker_sha256']
    assert sha(ROOT/'app/core/v9/vehicle_evidence.py')==plan['selector_sha256']
    ledger=[]
    for entry in plan['inputs']:
        source=SOURCE/entry['name'];assert sha(source)==entry['sha256']
        target=OUT/'predictions'/source.name
        print('Infer',source.name,flush=True)
        started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.per_track_permission_check','infer',str(source),str(target)],
                cwd=ROOT,timeout=90,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
        except subprocess.TimeoutExpired:
            reason='TIMEOUT_90S'
        ledger.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',ledger)
    print(json.dumps(ledger,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer'])
    parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    infer(*args.paths) if args.command=='infer' else globals()[args.command]()
