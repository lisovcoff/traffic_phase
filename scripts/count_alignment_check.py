"""Single frozen paired-alignment count candidate, no annotation inputs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.isolated_phase_check import ROOT,SOURCE,sha,save

OUT=ROOT/'benchmarks/count_alignment_rewrite_20261018'


def infer(source,target):
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.count_phase import discover_bundle
    from app.core.count_alignment import aligned_event_channels
    old,bundle=cached_bundle(source)
    result=discover_bundle(bundle,input_name=old['input'],observation_builder=aligned_event_channels)
    result['count_phase'].update(input_cache_sha256=sha(source),raw_ingestion_replayed=False)
    save(target,result)


def freeze():
    OUT.mkdir(exist_ok=False)
    save(OUT/'freeze.json',dict(code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        core_sha256=sha(ROOT/'app/core/count_phase.py'),alignment_sha256=sha(ROOT/'app/core/count_alignment.py'),
        worker_sha256=sha(Path(__file__)),max_workers=3,timeout_s=120,max_total_worker_s=360,
        inputs=[dict(name=p.name,sha256=sha(p)) for p in sorted(SOURCE.glob('*.json'))],
        parameter_search=False,annotations_used=False))


def run():
    plan=json.loads((OUT/'freeze.json').read_text(encoding='utf8'))
    assert sha(ROOT/'app/core/count_phase.py')==plan['core_sha256']
    assert sha(ROOT/'app/core/count_alignment.py')==plan['alignment_sha256']
    assert sha(Path(__file__))==plan['worker_sha256']
    ledger=[]
    for entry in plan['inputs']:
        source=SOURCE/entry['name'];assert sha(source)==entry['sha256']
        target=OUT/'predictions'/source.name
        print('Aligned count',source.name,flush=True);started=time.monotonic()
        try:
            process=subprocess.run([sys.executable,'-m','scripts.count_alignment_check','infer',str(source),str(target)],
                cwd=ROOT,timeout=120,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if process.returncode==0 else process.stderr[-2500:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_120S'
        ledger.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',ledger)
    print(json.dumps(ledger,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer']);parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    infer(*args.paths) if args.command=='infer' else globals()[args.command]()
