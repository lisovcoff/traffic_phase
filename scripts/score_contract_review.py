"""One native coherent-score comparison. Inference takes no annotations."""
import argparse
from dataclasses import asdict
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.hsmm_recurrence_check import cached_bundle, sha, save

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'benchmarks/score_contract_20261017'
SOURCE = ROOT/'benchmarks/stage2c_20261014/predictions'
BASELINE = ROOT/'benchmarks/seed_flow_20261017/predictions'
BASE = 'e41c075d7c9cef7c6eb512cfadf7d29d435cafba'


def numerically_equal(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(numerically_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(numerically_equal(x, y) for x, y in zip(a, b))
    if type(a) is float and type(b) is float:
        return math.isfinite(a) and math.isfinite(b) and abs(a-b) <= 1e-12
    return type(a) is type(b) and a == b


def infer(source, output):
    import hashlib
    import numpy as np
    from app.core.v9 import fit
    from app.core.v9.model import _discover_bundle
    np.random.seed(0)
    pred, bundle = cached_bundle(source)
    fits, refinements = [], []
    original_fit, original_refine = fit.em_fit, fit._fit_from_initial_labels

    def identity(result):
        return dict(labels_sha256=hashlib.sha256(result['labels'].tobytes()).hexdigest(),
                    probs_sha256=hashlib.sha256(result['probs'].tobytes()).hexdigest())

    def trace_refine(*args, **kwargs):
        result, history = original_refine(*args, **kwargs)
        refinements.append(dict(k=args[2], source=args[7].get('source'),
            parent=args[7].get('split_parent_phase'), score=result['score'],
            pointwise_loglik=result['pointwise_loglik'], penalized_objective=result.get('penalized_objective'),
            decoder_input_objective=result.get('decoder_input_objective'), history=history, **identity(result)))
        return result, history

    def trace_fit(*args, **kwargs):
        result = original_fit(*args, **kwargs)
        fits.append({**{key: result[key] for key in ('k', 'initialization', 'initialization_candidates',
            'score', 'pointwise_loglik', 'model_quality')},
            **{key:result.get(key) for key in ('data_loglik','score_semantics','penalized_objective','decoder_input_objective')}, **identity(result)})
        return result

    fit.em_fit, fit._fit_from_initial_labels = trace_fit, trace_refine
    started = time.monotonic()
    try:
        result = _discover_bundle(bundle, input_name=pred['input'], dt=1., marks_path=None,
            evidence_policy='permission_per_stream', source_files=pred['archive']['source_files'],
            experimental_local_history=False)
    finally:
        fit.em_fit, fit._fit_from_initial_labels = original_fit, original_refine
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref'] = dict(file=source.relative_to(ROOT).as_posix(), sha256=sha(source))
    result['score_contract_trace'] = dict(fits=fits, refinements=refinements,
        annotations_used=False, cached_runtime_s=time.monotonic()-started)
    save(output, result)


def worker(source, target):
    started = time.monotonic()
    env = {**os.environ, 'PYTHONHASHSEED':'0', 'OMP_NUM_THREADS':'1',
           'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
    try:
        done = subprocess.run([sys.executable, '-m', 'scripts.score_contract_review', 'infer',
            str(source), str(target)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=90)
        reason = None if done.returncode == 0 else done.stderr[-3000:]
    except subprocess.TimeoutExpired:
        reason = 'WORKER_TIMEOUT_90S'
    return dict(file=source.name, runtime_s=time.monotonic()-started, reason=reason,
                prediction_sha256=sha(target) if target.exists() else None)


def freeze():
    from app.core.v9.fit import PhaseSearchConfig
    OUT.mkdir(exist_ok=False)
    inputs = []
    for source in sorted(SOURCE.glob('*_v9.json')):
        _, bundle = cached_bundle(source)
        inputs.append(dict(file=source.name, sha256=sha(source), baseline_sha256=sha(BASELINE/source.name),
            temporal_events=len(bundle.temporal_events), selected_indices=bundle.diagnostics['selected_event_indices']))
    assert len(inputs) == 3
    save(OUT/'freeze.json', dict(base_sha=BASE, inputs=inputs, seed=0, dt=1.,
        search_config=asdict(PhaseSearchConfig()), max_control_runs=1, max_corrected_runs=3,
        worker_timeout_s=90, total_worker_allowance_s=360, boundary_tolerance_s=2.,
        control_float_atol=1e-12, control_float_rtol=0, control_raw_segments_and_K='EXACT',
        package_versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','scikit-learn','fastapi')},
        protocol_sha256=sha(ROOT/'docs/SCORE_CONTRACT_PROTOCOL_20261017.md'),
        local_2D1='FAIL_DEFAULT_OFF', source='lossless_event_cache_NOT_original_ingestion'))


def control():
    save(OUT/'control_started.json', dict(fit_sha256=sha(ROOT/'app/core/v9/fit.py')))
    entry = next(e for e in json.loads((OUT/'freeze.json').read_text())['inputs'] if e['file'].startswith('19_'))
    assert sha(SOURCE/entry['file']) == entry['sha256']
    row = worker(SOURCE/entry['file'], OUT/'control.json')
    if row['reason'] is None:
        old = json.loads((BASELINE/entry['file']).read_text(encoding='utf-8'))
        new = json.loads((OUT/'control.json').read_text(encoding='utf-8'))
        row.update(raw_exact=old['schedule']['raw_hsmm_segments'] == new['schedule']['raw_hsmm_segments'],
            k_exact=old['schedule']['phase_count'] == new['schedule']['phase_count'],
            schedule_exact=old['schedule'] == new['schedule'], period_exact=old['period_inference'] == new['period_inference'],
            schedule_numerical_parity=numerically_equal(old['schedule'], new['schedule']),
            period_numerical_parity=numerically_equal(old['period_inference'], new['period_inference']))
    save(OUT/'control_check.json', row)
    assert not row['reason'] and all(row[k] for k in ('raw_exact','k_exact','schedule_numerical_parity','period_numerical_parity')), 'STOP_UNEXPLAINED_NATIVE_CONTROL_MISMATCH'
    print(json.dumps(row))


def run():
    check = json.loads((OUT/'control_check.json').read_text())
    assert not check['reason'] and all(check[k] for k in ('raw_exact','k_exact','schedule_numerical_parity','period_numerical_parity'))
    frozen = json.loads((OUT/'freeze.json').read_text())
    assert not subprocess.check_output(['git','diff','HEAD','--','app/core','scripts/score_contract_review.py'],cwd=ROOT).strip(), 'COMMIT_CODE_BEFORE_RUN'
    assert sha(ROOT/'docs/SCORE_CONTRACT_PROTOCOL_20261017.md') == frozen['protocol_sha256']
    save(OUT/'corrected_started.json', dict(code_sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                                         fit_sha256=sha(ROOT/'app/core/v9/fit.py')))
    rows = []
    for entry in frozen['inputs']:
        assert sha(SOURCE/entry['file']) == entry['sha256']
        assert sha(BASELINE/entry['file']) == entry['baseline_sha256']
        print('One corrected cached worker:', entry['file'], flush=True)
        rows.append(worker(SOURCE/entry['file'], OUT/'predictions'/entry['file']))
    save(OUT/'predictions_sealed.json', rows)
    print('All prediction hashes sealed before annotation access')


def evaluate():
    from app.core.offline_benchmark import evaluate_prediction, validate_annotation
    ledger = json.loads((OUT/'predictions_sealed.json').read_text())
    previous_run = json.loads((BASELINE.parent/'comparison.json').read_text(encoding='utf-8'))
    previous_metrics = {r['source']:r['after'] for r in previous_run['rows']}
    original_metrics = json.loads((SOURCE.parent/'baseline_metrics.json').read_text(encoding='utf-8'))
    annotations = {r['source_name']:r['annotation_sha256'] for r in original_metrics['rows']}
    comparison = []
    for entry in ledger:
        name = entry['file'].replace('_v9.json','.json')
        old = json.loads((BASELINE/entry['file']).read_text(encoding='utf-8'))
        row = dict(source=name, worker=entry, before=previous_metrics[name],
                   runtime_scope='cached discovery; not original trajectory ingestion',
                   phase_count_before=old['schedule']['phase_count'])
        if entry['reason']:
            row.update(status='unavailable', reason=entry['reason'])
        else:
            target = OUT/'predictions'/entry['file']
            assert sha(target) == entry['prediction_sha256']
            marks = next(p for p in (ROOT.parent/'data').glob('*/'+name+'_manual_marks.json')
                         if sha(p) == annotations[name])
            annotation = validate_annotation(json.loads(marks.read_text(encoding='utf-8')))
            assert annotation['valid']
            prediction = json.loads(target.read_text(encoding='utf-8'))
            row.update(status='evaluated', annotation_sha256=sha(marks),
                after=evaluate_prediction(prediction,annotation,tolerance_s=2.),
                phase_count_after=prediction['schedule']['phase_count'],
                period_exact=old['period_inference']==prediction['period_inference'],
                raw_exact=old['schedule']['raw_hsmm_segments']==prediction['schedule']['raw_hsmm_segments'],
                baseline_exact=old['schedule']['baseline_segments']==prediction['schedule']['baseline_segments'])
            assert sha(target) == entry['prediction_sha256']
        comparison.append(row)
    save(OUT/'comparison.json',dict(rows=comparison,split='development_NOT_holdout',
        tolerance_s=2., observation_model_unchanged=True, physical_lamp_accuracy='UNKNOWN',
        overall_2D1_gate='FAIL',no_post_result_tuning=True))
    print('Single unchanged evaluator pass completed; no post-result tuning')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('freeze','control','infer','run','evaluate'))
    parser.add_argument('paths', nargs='*', type=Path)
    args = parser.parse_args()
    if args.command == 'infer':
        infer(*args.paths)
    else:
        globals()[args.command]()


if __name__ == '__main__':
    main()
