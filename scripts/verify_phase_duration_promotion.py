"""Verify production fit matches the sealed duration-only candidate, no opt-ins."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.isolated_phase_check import ROOT,SOURCE,sha,save

OUT=ROOT/'benchmarks/duration_promotion_20261018'


def infer(source,target):
    import numpy as np
    np.random.seed(0)
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.v9.model import _discover_bundle
    old,bundle=cached_bundle(source)
    result=_discover_bundle(bundle,input_name=old['input'],dt=1.,marks_path=None,
        evidence_policy='permission_per_stream',source_files=old['archive']['source_files'],
        experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref']={'file':source.relative_to(ROOT).as_posix(),'sha256':sha(source)}
    result['promotion_verification']={'opt_ins':False,'annotations_used':False}
    save(target,result)


def run():
    OUT.mkdir(exist_ok=False)
    save(OUT/'freeze.json',dict(code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        fit_sha256=sha(ROOT/'app/core/v9/fit.py'),worker_sha256=sha(Path(__file__)),
        inputs=[dict(name=p.name,sha256=sha(p)) for p in sorted(SOURCE.glob('*.json'))],
        max_workers=3,timeout_s=90,dt=1,seed=0,no_tuning=True,purpose='production integration equality'))
    ledger=[]
    for source in sorted(SOURCE.glob('*.json')):
        target=OUT/'predictions'/source.name
        started=time.monotonic()
        try:
            process=subprocess.run([sys.executable,'-m','scripts.verify_phase_duration_promotion','infer',str(source),str(target)],
                cwd=ROOT,capture_output=True,text=True,timeout=90,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if process.returncode==0 else process.stderr[-2500:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_90S'
        ledger.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',ledger)
    comparisons=[]
    for item in ledger:
        if item['reason']:continue
        production=json.loads((OUT/'predictions'/item['file']).read_text(encoding='utf8'))
        candidate=json.loads((ROOT/'benchmarks/isolated_equal_durations_20261018/predictions'/item['file']).read_text(encoding='utf8'))
        comparisons.append(dict(file=item['file'],schedule_exact=production['schedule']==candidate['schedule'],
            period_exact=production['period_inference']==candidate['period_inference']))
    save(OUT/'integration_equality.json',comparisons)
    print(json.dumps(comparisons,indent=2))
    assert len(comparisons)==3 and all(r['schedule_exact'] and r['period_exact'] for r in comparisons)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','infer']);parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    run() if args.command=='run' else infer(*args.paths)
