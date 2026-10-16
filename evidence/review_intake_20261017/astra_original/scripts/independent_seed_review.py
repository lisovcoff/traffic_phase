"""One bounded cached comparison; annotation-derived targets read only in score.

No replacement annotation or new evaluator. Full original annotations are absent.
"""
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/independent_review_20261017'
HIST = ROOT / 'benchmarks/hsmm_recurrence_20261016'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def infer(source, target):
    import numpy as np
    from app.core.v9 import fit
    from app.core.v9.model import _discover_bundle
    from scripts.hsmm_recurrence_check import cached_bundle
    np.random.seed(0)
    pred, bundle = cached_bundle(source)
    original_em, original_refine = fit.em_fit, fit._fit_from_initial_labels
    traces, refinements = [], []

    def traced_refine(*args, **kwargs):
        result, history = original_refine(*args, **kwargs)
        refinements.append(dict(k=args[2], source=args[7].get('source'),
            parent=args[7].get('split_parent_phase'), score=result['score'],
            pointwise_loglik=result['pointwise_loglik'], coherence=result['coherence']))
        return result, history

    def traced_em(*args, **kwargs):
        result = original_em(*args, **kwargs)
        traces.append({key: result[key] for key in ('k', 'initialization',
            'initialization_candidates', 'score', 'pointwise_loglik', 'model_quality', 'decoder_info')})
        return result

    fit.em_fit, fit._fit_from_initial_labels = traced_em, traced_refine
    tick = time.monotonic()
    result = _discover_bundle(bundle, input_name=pred['input'], dt=1., marks_path=None,
        evidence_policy='permission_per_stream', source_files=pred['archive']['source_files'],
        experimental_local_history=False)
    result['event_extraction'].pop('temporal_events')
    result['review_trace'] = dict(fits=traces, refinements=refinements,
        cached_runtime_s=time.monotonic()-tick, cache_sha256=sha(source), annotations_used=False)
    save(target, result)


def worker(source, target):
    tick = time.monotonic()
    env = {**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1',
           'MKL_NUM_THREADS':'1', 'PYTHONHASHSEED':'0'}
    try:
        result = subprocess.run([sys.executable, '-m', 'scripts.independent_seed_review',
            'infer', str(source), str(target)], cwd=ROOT, env=env, capture_output=True,
            text=True, timeout=90)
        reason = result.stderr[-3000:] if result.returncode else None
    except subprocess.TimeoutExpired:
        reason = 'WORKER_TIMEOUT_90S'
    return dict(file=source.name, runtime_s=time.monotonic()-tick, reason=reason,
                sha256=sha(target) if target.exists() else None)


def control():
    frozen = json.loads((OUT/'freeze.json').read_text())
    assert sha(ROOT/'app/core/v9/fit.py') == frozen['hashes']['app/core/v9/fit.py']
    save(OUT/'control_started.json', dict(fit_sha256=sha(ROOT/'app/core/v9/fit.py')))
    entry = next(e for e in frozen['inputs'] if Path(e['path']).name.startswith('19_'))
    source = ROOT/entry['path']
    assert sha(source) == entry['sha256']
    target = OUT/'control.json'
    row = worker(source, target)
    if row['reason'] is None:
        old = json.loads((HIST/'predictions'/source.name).read_text())
        new = json.loads(target.read_text())
        row.update(schedule_exact=old['schedule'] == new['schedule'],
            period_exact=old['period_inference'] == new['period_inference'],
            k_exact=old['schedule']['phase_count'] == new['schedule']['phase_count'])
    save(OUT/'control_check.json', row)
    print(json.dumps(row), flush=True)
    assert not row['reason'] and all(row[k] for k in ('schedule_exact','period_exact','k_exact')), 'STOP_CONTROL_MISMATCH'


def run():
    check = json.loads((OUT/'control_check.json').read_text())
    assert not check['reason'] and all(check[k] for k in ('schedule_exact','period_exact','k_exact'))
    frozen = json.loads((OUT/'freeze.json').read_text())
    for path, digest in frozen['hashes'].items():
        if path != 'app/core/v9/fit.py':
            assert sha(ROOT/path) == digest, path
    save(OUT/'corrected_started.json', dict(fit_sha256=sha(ROOT/'app/core/v9/fit.py'),
                                           runner_sha256=sha(Path(__file__))))
    rows = []
    for entry in frozen['inputs']:
        source = ROOT/entry['path']
        assert sha(source) == entry['sha256']
        print('One corrected worker:', source.name, flush=True)
        row = worker(source, OUT/'predictions'/source.name)
        rows.append(row)
        print(json.dumps(row), flush=True)
    save(OUT/'predictions_sealed.json', rows)


def boundary_metrics(prediction, field, truth, interval):
    from app.core.offline_benchmark import segments_absolute, match_boundaries, percentile
    rows, error = segments_absolute(prediction, field)
    assert error is None, error
    start, end = interval
    predicted = [b[0] for a,b in zip(rows,rows[1:])
                 if abs(a[1]-b[0]) <= .001 and a[2] != b[2] and start < b[0] < end]
    matches = match_boundaries(truth, predicted, 2.)
    errors = [abs(m['signed_error_s']) for m in matches]
    coverage = sum(max(0,min(end,b)-max(start,a)) for a,b,_ in rows)/(end-start)
    return dict(matched=len(matches), truth=len(truth), predicted=len(predicted),
        precision=len(matches)/len(predicted) if predicted else None,
        recall=len(matches)/len(truth) if truth else None,
        matched_mae_s=statistics.mean(errors) if errors else None,
        matched_p95_s=percentile(errors,.95) if errors else None,
        nearest_mae_s=statistics.mean(min(abs(t-p)/1000 for p in predicted) for t in truth) if predicted and truth else None,
        coverage=coverage, logical_unknown_fraction=1-coverage, physical_state='UNKNOWN',
        matches=matches)


def historical_flat(history):
    b = history['boundaries']; c=b['mae_s']
    return dict(matched=c['matched_boundaries'], truth=c['truth_boundaries'], predicted=c['predicted_boundaries'],
        precision=b['precision']['value'], recall=b['recall']['value'],
        matched_mae_s=c['value'], matched_p95_s=b['p95_s']['value'],
        nearest_mae_s=b['nearest_truth_boundary_mae_s_diagnostic']['value'],
        coverage=history['coverage']['value'], logical_unknown_fraction=1-history['coverage']['value'],
        physical_state='UNKNOWN', matches=b['matches'])


def score():
    sealed=json.loads((OUT/'predictions_sealed.json').read_text())
    frozen=json.loads((OUT/'freeze.json').read_text())
    assert sha(HIST/'comparison.json') == frozen['hashes']['benchmarks/hsmm_recurrence_20261016/comparison.json']
    history=json.loads((HIST/'comparison.json').read_text())
    rows=[]
    # Validate every historical target/metric before new output scoring.
    targets={}
    for row in history['rows']:
        name=row['source'].replace('.json','_v9.json')
        pred=json.loads((HIST/'predictions'/name).read_text())
        target_sets=[]
        for field,h in row['after']['histories'].items():
            b=h['boundaries']
            truth=sorted([m['truth_ms'] for m in b['matches']]+b['missed_truth_ms'])
            interval=h['coverage']['range_ms']
            target_sets.append((truth,interval))
            actual=boundary_metrics(pred,field,truth,interval)
            expected=historical_flat(h)
            assert actual==expected, (name,field,'HISTORICAL_PARITY_FAILED')
            targets[name,field]=(truth,interval,actual)
        assert all(t==target_sets[0] for t in target_sets)
    save(OUT/'historical_boundary_parity.json', dict(all_six_histories_exact=True,
         original_annotations_available=False, tolerance_s=2., source_sha256=sha(HIST/'comparison.json')))
    old_by_name={r['source'].replace('.json','_v9.json'):r for r in history['rows']}
    for item in sealed:
        row=dict(file=item['file'],worker=item,original_annotations_available=False,
                 evaluation_scope='saved_interior_boundaries_only_NOT_full_annotations')
        if item['reason']:
            row['status']='unavailable'
        else:
            path=OUT/'predictions'/item['file'];assert sha(path)==item['sha256']
            pred=json.loads(path.read_text())
            old=old_by_name[item['file']]
            row.update(status='evaluated', k_before=old['phase_count_after'],k_after=pred['schedule']['phase_count'],
                expert_distinct_labels=old['after']['phase_count_match']['annotation_distinct_labels'],
                period_s=pred['period_inference']['period_s'],
                selected_initialization=next(t['initialization'] for t in pred['review_trace']['fits'] if t['k']==pred['schedule']['phase_count']),
                search_status=pred['phase_model_selection']['search']['search_status'],histories={})
            for field in ('raw_hsmm_segments','baseline_segments'):
                truth,interval,before=targets[item['file'],field]
                row['histories'][field]=dict(before=before,after=boundary_metrics(pred,field,truth,interval))
            historical=json.loads((HIST/'predictions'/item['file']).read_text())
            row['schedule_exact']=pred['schedule']==historical['schedule']
        rows.append(row)
    save(OUT/'comparison.json',dict(rows=rows,development_not_holdout=True,tolerance_s=2.,
        original_marks_missing=True,physical_lamp_probability=None,local_2d1='FAIL_DEFAULT_OFF'))
    for row in rows:
        print(json.dumps({k:v for k,v in row.items() if k!='histories'},ensure_ascii=False))
        for field,values in row.get('histories',{}).items():
            print(field,json.dumps({k:v for k,v in values['after'].items() if k!='matches'}))


if __name__=='__main__':
    command=sys.argv[1]
    if command=='infer': infer(Path(sys.argv[2]),Path(sys.argv[3]))
    elif command in ('control','run','score'): globals()[command]()
    else: raise ValueError(command)
