"""One frozen controlled-channel development candidate. Workers never read marks."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.hsmm_recurrence_check import cached_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'benchmarks/manual_marks_20261018_baseline/predictions'
OUT = ROOT/'benchmarks/manual_marks_20261018_channels'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
        stream.write('\n')


def infer(source, target):
    import numpy as np
    np.random.seed(0)
    from app.core.v9.model import _discover_from_stream_views
    pred,bundle = cached_bundle(source)
    allowed={'N->S','S->N','E->W','W->E'}
    if source.name.startswith('17_'):
        allowed.update({'N->E','E->N'})
    by_stream,entries,releases,methods,release_methods,files,start,anchor,tracks,count=bundle
    permissions={m:ts for m,ts in bundle.permission_streams.items() if m in allowed}
    result=_discover_from_stream_views(by_stream,entries,methods,release_methods,
        release_streams=releases,permission_streams=permissions,
        input_name=pred['input'],dt=1.,marks_path=None,
        recording_start_ms=start,analysis_base_ms=anchor,trajectory_count=tracks,
        event_count=count,source_files=files,temporal_events=bundle.temporal_events,
        evidence_diagnostics=deepcopy(bundle.diagnostics),experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref']={'file':str(source.relative_to(ROOT)),'sha256':sha(source)}
    result['controlled_channel_candidate']=dict(allowed_movements=sorted(allowed),
        excluded_permission_movements=sorted(set(bundle.permission_streams)-allowed),
        permission_events_used=sum(len(v) for v in permissions.values()),
        demand_entries_unchanged=True,period_model_unchanged=True,automatic_k_range=[2,6],
        annotation_input=False,scope='Sverdlovsky confirmed channels; other two sites through-only diagnostic assumption')
    save(target,result)


def freeze():
    OUT.mkdir(exist_ok=False)
    sources=sorted(SOURCE.glob('*_v9.json'))
    assert len(sources)==3
    save(OUT/'freeze.json',dict(code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        sources=[dict(name=p.name,sha256=sha(p)) for p in sources],
        worker_sha256=sha(Path(__file__)), max_workers=3,timeout_per_worker_s=90,
        max_total_worker_s=270,dt=1,seed=0,no_parameter_search=True,
        hypothesis='uncontrolled turns can split discharge evidence and bias operating boundaries',
        annotation_delay_claim_s=3,phase_count_not_supplied=True))


def run():
    frozen=json.loads((OUT/'freeze.json').read_text())
    assert sha(Path(__file__))==frozen['worker_sha256']
    rows=[]
    for source in frozen['sources']:
        path=SOURCE/source['name'];assert sha(path)==source['sha256']
        target=OUT/'predictions'/source['name']
        started=time.monotonic()
        print('Candidate:',path.name,flush=True)
        try:
            process=subprocess.run([sys.executable,'-m','scripts.manual_marks_channel_check','infer',str(path),str(target)],
                cwd=ROOT,capture_output=True,text=True,timeout=90,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if process.returncode==0 else process.stderr[-3000:]
        except subprocess.TimeoutExpired:
            reason='TIMEOUT_90S'
        rows.append(dict(file=path.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',rows)
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer'])
    parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    infer(*args.paths) if args.command=='infer' else globals()[args.command]()
