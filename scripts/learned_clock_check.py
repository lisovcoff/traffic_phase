"""Verify numerical clock fix using frozen trained models, without retraining."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.isolated_phase_check import ROOT,SOURCE,sha,save

TRAIN=ROOT/'benchmarks/learned_profile_20261018'
OUT=ROOT/'benchmarks/learned_clock_fixed_20261018'


def infer(source,model_path,window_path,target):
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.learned_phase import predict_profile
    old,bundle=cached_bundle(source)
    model=json.loads(model_path.read_text(encoding='utf8'))
    window=json.loads(window_path.read_text(encoding='utf8'))
    value=predict_profile(bundle.temporal_events,model,start_ms=window['train_end_ms'],end_ms=window['prediction_end_ms'])
    value['input']=old['input'];value['learned_phase']['trained_model_sha256']=sha(model_path)
    save(target,value)


def run():
    OUT.mkdir(exist_ok=False)
    inputs=[dict(file=p.name,model_sha256=sha(p),source_sha256=sha(SOURCE/p.name),
        window_sha256=sha(TRAIN/'training'/p.name)) for p in sorted((TRAIN/'models').glob('*.json'))]
    save(OUT/'freeze.json',dict(inputs=inputs,core_sha256=sha(ROOT/'app/core/learned_phase.py'),
        worker_sha256=sha(Path(__file__)),timeout_s=120,max_workers=3,retraining=False,parameter_tuning=False))
    ledger=[]
    for item in inputs:
        name=item['file'];source=SOURCE/name;target=OUT/'predictions'/name
        assert sha(source)==item['source_sha256'] and sha(TRAIN/'models'/name)==item['model_sha256']
        started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.learned_clock_check','infer',str(source),
                str(TRAIN/'models'/name),str(TRAIN/'training'/name),str(target)],cwd=ROOT,
                timeout=120,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_120S'
        ledger.append(dict(file=name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',ledger)
    print(json.dumps(ledger,indent=2))


def evaluate():
    from app.core.offline_benchmark import evaluate_prediction,validate_annotation
    from app.core.manual_delay_evaluation import evaluate_reaction_bound
    ledger=json.loads((OUT/'predictions_sealed.json').read_text(encoding='utf8'))
    assert len(ledger)==3 and all(r['reason'] is None for r in ledger)
    rows=[]
    for entry in ledger:
        name=entry['file'];path=OUT/'predictions'/name;assert sha(path)==entry['sha256']
        raw=json.loads((TRAIN/'heldout'/name).read_text(encoding='utf8'))
        ann={'start_ms':raw['start_ms'],'marks':[dict(timestamp_ms=m['timestamp_ms'],kind=m['kind']) for m in raw['marks']]}
        row=dict(file=name,conditional_k=True,variants={})
        for variant,p in [('baseline',SOURCE/name),('initial_learned',TRAIN/'predictions'/name),('corrected_learned',path)]:
            pred=json.loads(p.read_text(encoding='utf8'))
            metric=evaluate_prediction(pred,validate_annotation(ann))
            metric['reaction_0_3s']=evaluate_reaction_bound(pred,ann)
            row['variants'][variant]=metric
            b=metric['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            print(name,variant,b['matched_boundaries'],'/',b['truth_boundaries'],
                'pred',b['predicted_boundaries'],'MAE',b['value'],flush=True)
        rows.append(row)
    save(OUT/'evaluation.json',dict(rows=rows,scope='chronological heldout half only',
        not_automatic_discovery=True,not_independent_lamp_accuracy=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','infer','evaluate']);parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    infer(*args.paths) if args.command=='infer' else globals()[args.command]()
