"""Chronological calibration/holdout check; predictor never receives test marks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from scripts.isolated_phase_check import ROOT,SOURCE,sha,save

OUT=ROOT/'benchmarks/learned_profile_20261018'


def infer(source,train_file,target):
    from scripts.hsmm_recurrence_check import cached_bundle
    from app.core.v9.primitives import infer_period
    from app.core.learned_phase import fit_profile,predict_profile
    old,bundle=cached_bundle(source)
    training=json.loads(train_file.read_text(encoding='utf8'))
    period,_=infer_period(bundle[1])
    model=fit_profile(bundle.temporal_events,training['marks'],base_ms=bundle[7],period_s=period,
        train_start_ms=training['train_start_ms'],train_end_ms=training['train_end_ms'])
    save(target.parent.parent/'models'/source.name,model)
    prediction=predict_profile(bundle.temporal_events,model,start_ms=training['train_end_ms'],end_ms=training['prediction_end_ms'])
    prediction['input']=old['input']
    save(target,prediction)


def freeze():
    OUT.mkdir(exist_ok=False)
    baseline=json.loads((ROOT/'benchmarks/manual_marks_20261018_baseline/baseline_metrics.json').read_text(encoding='utf8'))
    inputs=[]
    for source in baseline['rows']:
        annotation=Path(source['annotation_path'])
        assert sha(annotation)==source['annotation_sha256']
        payload=json.loads(annotation.read_text(encoding='utf8'))
        marks=sorted(payload['marks'],key=lambda m:m['timestamp_ms'])
        start,end=marks[0]['timestamp_ms'],marks[-1]['timestamp_ms'];cut=(start+end)/2
        name=Path(source['source_name']).stem+'_v9.json'
        train=dict(marks=[m for m in marks if m['timestamp_ms']<=cut],
            train_start_ms=start,train_end_ms=cut,prediction_end_ms=end)
        test={**payload,'marks':[m for m in marks if m['timestamp_ms']>cut]}
        save(OUT/'training'/name,train);save(OUT/'heldout'/name,test)
        inputs.append(dict(file=name,source_sha256=sha(SOURCE/name),training_sha256=sha(OUT/'training'/name),
            heldout_sha256=sha(OUT/'heldout'/name),cut_ms=cut))
    save(OUT/'freeze.json',dict(code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        inputs=inputs,core_sha256=sha(ROOT/'app/core/learned_phase.py'),worker_sha256=sha(Path(__file__)),
        fit_predict_workers=3,timeout_s=120,max_total_s=360,tuning=False,
        evaluation_scope='last half manual window only; K supplied by first-half training labels'))


def run():
    plan=json.loads((OUT/'freeze.json').read_text(encoding='utf8'))
    assert sha(ROOT/'app/core/learned_phase.py')==plan['core_sha256']
    assert sha(Path(__file__))==plan['worker_sha256']
    rows=[]
    for entry in plan['inputs']:
        source=SOURCE/entry['file'];train=OUT/'training'/entry['file'];target=OUT/'predictions'/entry['file']
        assert sha(source)==entry['source_sha256'] and sha(train)==entry['training_sha256']
        print('Train/predict',source.name,flush=True);started=time.monotonic()
        try:
            proc=subprocess.run([sys.executable,'-m','scripts.learned_phase_check','infer',str(source),str(train),str(target)],
                cwd=ROOT,timeout=120,capture_output=True,text=True,
                env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
            reason=None if proc.returncode==0 else proc.stderr[-2500:]
        except subprocess.TimeoutExpired:reason='TIMEOUT_120S'
        rows.append(dict(file=source.name,reason=reason,runtime_s=time.monotonic()-started,
            sha256=sha(target) if target.exists() else None))
    save(OUT/'predictions_sealed.json',rows)
    print(json.dumps(rows,indent=2))


def evaluate():
    from app.core.offline_benchmark import evaluate_prediction,validate_annotation
    from app.core.manual_delay_evaluation import evaluate_reaction_bound
    ledger=json.loads((OUT/'predictions_sealed.json').read_text(encoding='utf8'))
    assert all(r['reason'] is None for r in ledger),ledger
    rows=[]
    for row in ledger:
        path=OUT/'predictions'/row['file'];assert sha(path)==row['sha256']
        raw_annotation=json.loads((OUT/'heldout'/row['file']).read_text(encoding='utf8'))
        # Original ordinal fields refer to the full file. Project the subset
        # to canonical timestamp/kind, without changing a timestamp or label.
        annotation={'start_ms':raw_annotation['start_ms'],'marks':[
            {'timestamp_ms':m['timestamp_ms'],'kind':m['kind']} for m in raw_annotation['marks']]}
        result=dict(file=row['file'],conditional_k=True,scope='chronological heldout half only',variants={})
        for variant,pred_path in [('baseline',SOURCE/row['file']),('learned',path)]:
            pred=json.loads(pred_path.read_text(encoding='utf8'))
            metric=evaluate_prediction(pred,validate_annotation(annotation))
            metric['reaction_0_3s']=evaluate_reaction_bound(pred,annotation)
            result['variants'][variant]=metric
            b=metric['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            print(row['file'],variant,'strict',b['matched_boundaries'],'/',b['truth_boundaries'],
                'predicted',b['predicted_boundaries'],'MAE',b['value'],flush=True)
        rows.append(result)
    save(OUT/'evaluation.json',dict(rows=rows,not_automatic_k_discovery=True,
        not_independent_physical_lamp_accuracy=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['freeze','run','infer','evaluate']);parser.add_argument('paths',nargs='*',type=Path)
    args=parser.parse_args()
    infer(*args.paths) if args.command=='infer' else globals()[args.command]()
