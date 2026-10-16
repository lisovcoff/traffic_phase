"""Single bounded development comparison from frozen lossless event caches.

Inference worker accepts saved prediction only, never annotations. Cached events
are checked against their saved selection before ordinary V9 fitting. The
evaluation command is separate and only runs after every prediction is sealed.
"""
import argparse
from dataclasses import asdict, fields
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'benchmarks/stage2c_20261014'
OUT = ROOT/'benchmarks/hsmm_recurrence_20261016'
BASE = '5b84eab96966f2220d85978056b1568d2f17226a'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def cached_bundle(path):
    from app.core.temporal_evidence import TemporalEvent
    from app.core.v9.events import _pack_temporal_events
    if path.stat().st_size > 16*1024*1024 or 'manual_marks' in path.name:
        raise ValueError('SAVED_PREDICTION_ONLY_BYTE_BUDGET')
    pred = json.loads(path.read_text(encoding='utf-8'))
    if 'evaluation' in pred:
        raise ValueError('ANNOTATION_BEARING_INPUT_FORBIDDEN')
    extraction = pred['event_extraction']
    if extraction.get('manual_marks_used_for_discovery') is not False:
        raise ValueError('UNVERIFIED_LABEL_FREE_CACHE')
    if extraction['evidence_policy'] != 'permission_per_stream':
        raise ValueError('UNCHANGED_PERMISSION_POLICY_REQUIRED')
    events = [TemporalEvent(**{field.name: row[field.name] for field in fields(TemporalEvent)})
              for row in extraction['temporal_events']]
    diag = extraction['quality_diagnostics']
    bundle = _pack_temporal_events(events, pred['archive']['source_files'], pred['trajectory_count'],
        pred['recording_start_timestamp_ms'], diag['track_quality_counts'])
    assert bundle[7] == pred['analysis_base_timestamp_ms']
    assert bundle[9] == pred['event_count']
    assert bundle.diagnostics == diag
    assert [e.to_dict() for e in bundle.temporal_events] == extraction['temporal_events']
    assert {name: len(ts) for name, ts in bundle.permission_streams.items()} == {
        name: sum(extraction['temporal_events'][i]['movement'] == name for i in diag['selected_event_indices'])
        for name in bundle.permission_streams}
    return pred, bundle


def infer(source, output):
    import numpy as np
    from app.core.v9.model import _discover_bundle
    np.random.seed(0)
    pred, bundle = cached_bundle(source)
    tick = time.monotonic()
    result = _discover_bundle(bundle, input_name=pred['input'], dt=1., marks_path=None,
        evidence_policy='permission_per_stream', source_files=pred['archive']['source_files'],
        experimental_local_history=False)
    # Avoid duplicating 26 MB of historical evidence; original immutable event
    # cache remains referenced, and original indices retain their meaning.
    result['event_extraction'].pop('temporal_events')
    result['event_extraction']['temporal_events_ref'] = dict(file=source.relative_to(ROOT).as_posix(), sha256=sha(source))
    result['development_replay'] = dict(input_cache_sha256=sha(source), raw_trajectory_ingestion=False,
        annotations_used=False, dt=1., seed=0, cached_fit_runtime_s=time.monotonic()-tick)
    save(output, result)


def worker(source, target):
    env = {**os.environ, 'PYTHONHASHSEED': '0', 'OMP_NUM_THREADS': '1',
           'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1'}
    started = time.monotonic()
    try:
        done = subprocess.run([sys.executable, '-m', 'scripts.hsmm_recurrence_check', 'infer',
                               str(source), str(target)], cwd=ROOT, env=env, capture_output=True,
                              text=True, timeout=90.)
        reason = None if done.returncode == 0 else done.stderr[-3000:]
    except subprocess.TimeoutExpired:
        reason = 'WORKER_TIMEOUT_90S'
    return dict(file=source.name, runtime_s=time.monotonic()-started, reason=reason,
                prediction_sha256=sha(target) if target.exists() else None)


def freeze():
    from app.core.v9.fit import PhaseSearchConfig
    OUT.mkdir(exist_ok=False)
    files = sorted((SOURCE/'predictions').glob('*_v9.json'))
    assert len(files) == 3
    inputs = []
    for path in files:
        pred, bundle = cached_bundle(path)
        inputs.append(dict(file=path.name, sha256=sha(path), events=len(bundle.temporal_events),
                           selected=len(bundle.diagnostics['selected_event_indices']),
                           cached_input_exact=True, recording_duration_s=pred['recording_duration_s']))
    save(OUT/'freeze.json', dict(base_sha=BASE, inputs=inputs, dt=1., seed=0,
        phase_search=asdict(PhaseSearchConfig()), worker_timeout_s=90., total_worker_budget_s=360.,
        max_control_runs=1, max_corrected_runs=3, boundary_tolerance_s=2., split='development',
        source_contract='exact cached events+selection+anchors; no raw JSON/ZIP ingestion',
        experimental_local_history=False, no_post_result_tuning=True))
    print('Frozen cached input/selection equality for all three inputs; no fitting or annotation access')


def control():
    save(OUT/'control_started.json', dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()))
    frozen = json.loads((OUT/'freeze.json').read_text())
    entry = next(r for r in frozen['inputs'] if r['file'].startswith('19_'))
    source = SOURCE/'predictions'/entry['file']
    assert sha(source) == entry['sha256']
    target = OUT/'control.json'
    row = worker(source, target)
    if row['reason']:
        save(OUT/'control_check.json', row)
        raise RuntimeError('CONTROL_FAILED; no corrected replay permitted')
    before = json.loads(source.read_text(encoding='utf-8'))
    after = json.loads(target.read_text(encoding='utf-8'))
    row['schedule_exact'] = before['schedule'] == after['schedule']
    row['period_exact'] = before['period_inference'] == after['period_inference']
    row['selected_k_exact'] = before['phase_model_selection']['selected_phase_count'] == after['phase_model_selection']['selected_phase_count']
    save(OUT/'control_check.json', row)
    assert row['schedule_exact'] and row['period_exact'] and row['selected_k_exact'], 'UNEXPLAINED_CONTROL_MISMATCH; stop'
    print('Control reproduced saved schedule, period and K exactly; no annotation access')


def run():
    control = json.loads((OUT/'control_check.json').read_text())
    assert control['schedule_exact'] and control['period_exact'] and control['selected_k_exact']
    save(OUT/'corrected_started.json', dict(code_sha=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()))
    frozen = json.loads((OUT/'freeze.json').read_text())
    rows = []
    for entry in frozen['inputs']:
        source = SOURCE/'predictions'/entry['file']
        assert sha(source) == entry['sha256']
        print('Corrected cached discovery:', source.name, flush=True)
        row = worker(source, OUT/'predictions'/source.name)
        rows.append(row)
    save(OUT/'predictions_sealed.json', rows)
    print('All corrected outputs sealed; annotations still unopened')


def evaluate():
    from app.core.offline_benchmark import evaluate_prediction, validate_annotation
    ledger = json.loads((OUT/'predictions_sealed.json').read_text())
    baseline = json.loads((SOURCE/'baseline_metrics.json').read_text(encoding='utf-8'))
    old = {r['source_name']: r for r in baseline['rows']}
    comparison = []
    for entry in ledger:
        name = entry['file'].replace('_v9.json', '.json')
        previous = old[name]
        row = dict(source=name, runtime_scope='cached full discovery; excludes original trajectory ingestion',
                   worker=entry, before=previous['metrics'])
        if entry['reason']:
            row.update(status='unavailable', reason=entry['reason'])
        else:
            target = OUT/'predictions'/entry['file']
            assert sha(target) == entry['prediction_sha256']
            candidates = list((ROOT.parent/'data').glob('*/'+name+'_manual_marks.json'))
            marks = next(p for p in candidates if sha(p) == previous['annotation_sha256'])
            annotation = validate_annotation(json.loads(marks.read_text(encoding='utf-8')))
            assert annotation['valid']
            prediction = json.loads(target.read_text(encoding='utf-8'))
            original = json.loads((SOURCE/'predictions'/entry['file']).read_text(encoding='utf-8'))
            row.update(status='evaluated', after=evaluate_prediction(prediction, annotation, tolerance_s=2.),
                       phase_count_before=original['schedule']['phase_count'],
                       phase_count_after=prediction['schedule']['phase_count'],
                       period_before=original['period_inference'],
                       period_after=prediction['period_inference'],
                       decoder=prediction['schedule']['decoder'])
            assert sha(target) == entry['prediction_sha256']
        comparison.append(row)
    save(OUT/'comparison.json', dict(rows=comparison, split='development_NOT_holdout',
        observation_model_unchanged=True, physical_lamp_accuracy='UNKNOWN', overall_2D1_gate='FAIL',
        no_post_result_tuning=True, tolerance_s=2.))
    print('Single evaluation completed; no post-result tuning permitted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['freeze', 'control', 'infer', 'run', 'evaluate'])
    parser.add_argument('paths', nargs='*', type=Path)
    args = parser.parse_args()
    if args.command == 'infer':
        infer(*args.paths)
    else:
        globals()[args.command]()


if __name__ == '__main__':
    main()
