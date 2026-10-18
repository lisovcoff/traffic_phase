"""Two separately frozen phase hypotheses; trajectories/events only in workers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'benchmarks/manual_marks_20261018_baseline/predictions'
VARIANTS=('equal_durations','likelihood_only')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf8',newline='\n') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)


def folder(variant):
    return ROOT/'benchmarks'/('isolated_'+variant+'_20261018')


def infer(variant,source,target):
    import numpy as np
    np.random.seed(0)
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.v9 import fit
    from app.core.v9.model import _discover_bundle
    old,bundle=cached_bundle(source)
    if variant=='equal_durations':
        original=fit.decode_cyclic_hsmm
        def decode(x,probs,period,k,**kwargs):
            if k==2:
                kwargs.update(duration_min_factor=.25,duration_max_factor=1.75)
            return original(x,probs,period,k,**kwargs)
        fit.decode_cyclic_hsmm=decode
    elif variant=='likelihood_only':
        original=fit._fit_quality
        def quality(value,shape,evidence_weight=.05):
            return original(value,shape,evidence_weight=0.)
        fit._fit_quality=quality
    else:
        raise ValueError(variant)
    result=_discover_bundle(bundle,input_name=old['input'],dt=1.,marks_path=None,
        evidence_policy='permission_per_stream',source_files=old['archive']['source_files'],
        experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref']={'file':source.relative_to(ROOT).as_posix(),'sha256':sha(source)}
    result['isolated_candidate']={'variant':variant,'unchanged_selection':True,'labels_used':False,
        'dt':1.,'seed':0,'unchanged_period_model':True,'experimental_local_history':False}
    save(target,result)


def freeze():
    files=sorted(SOURCE.glob('*.json'))
    for variant in VARIANTS:
        out=folder(variant);out.mkdir(exist_ok=False)
        save(out/'freeze.json',dict(variant=variant,
            code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            worker_sha256=sha(Path(__file__)),fit_sha256=sha(ROOT/'app/core/v9/fit.py'),
            inputs=[dict(name=p.name,sha256=sha(p)) for p in files],dt=1,seed=0,
            timeout_s=90,max_workers=3,max_total_worker_s=270,labels_in_inference=False,
            parameter_search=False))


def run(variant):
    out=folder(variant);plan=json.loads((out/'freeze.json').read_text(encoding='utf8'))
    assert sha(Path(__file__))==plan['worker_sha256']
    assert sha(ROOT/'app/core/v9/fit.py')==plan['fit_sha256']
    ledger=[]
    for entry in plan['inputs']:
        source=SOURCE/entry['name'];assert sha(source)==entry['sha256']
        target=out/'predictions'/source.name
        print(variant,source.name,flush=True)
        started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.isolated_phase_check','infer',
                variant,str(source),str(target)],cwd=ROOT,timeout=90,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
        except subprocess.TimeoutExpired:
            reason='TIMEOUT_90S'
        ledger.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(out/'predictions_sealed.json',ledger)
    print(json.dumps(ledger,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer'])
    parser.add_argument('values',nargs='*')
    args=parser.parse_args()
    if args.command=='freeze':freeze()
    elif args.command=='run':run(*args.values)
    else:infer(args.values[0],Path(args.values[1]),Path(args.values[2]))
