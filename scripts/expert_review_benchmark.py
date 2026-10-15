"""One sealed development baseline on the three new review sessions, no tuning."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from scripts.offline_benchmark import ROOT, DEFAULT_CONFIG, sha256_file, write_json, code_manifest, canonical_bytes
from app.core.expert_interval_evaluation import adapt_review, evaluate_review


GROUPS = {
    '17_2025_2_12_7.json': {'Начало группы 1': ['E->W','W->E'],
        'Начало группы 2': ['N->E','E->N','N->S'], 'Начало группы 3': ['N->S','S->N']},
    '19_2025_2_25_8.json': {'Начало группы 1': ['W->E','E->W'], 'Начало группы 2': ['N->S','S->N']},
    '6_2025_2_14_6.json': {'Начало группы 1': ['E->W','W->E'], 'Начало группы 2': ['N->S','S->N']},
}


def worker_command(source, prediction):
    # Only an explicit trajectory file enters the existing worker, never a directory,
    # review file, group definitions, label-derived offset or truth time window.
    if source.name not in GROUPS:
        raise ValueError('unregistered trajectory input')
    return [sys.executable, '-m', 'scripts.offline_benchmark', 'infer',
            str(source.resolve()), str(prediction.resolve()), '--dt', '1.0']


def prepare(data, output):
    if output.exists():
        raise ValueError('fresh output directory required')
    output.mkdir(parents=True)
    entries = []
    for name, groups in GROUPS.items():
        source = data/name
        review_path = data/(source.stem+'_review.json')
        review = json.loads(review_path.read_text(encoding='utf-8-sig'))
        source_hash = sha256_file(source)
        if source_hash != review['source']['sha256']:
            raise ValueError('source hash mismatch')
        adapter_path = output/'adapters'/(source.stem+'.json')
        write_json(adapter_path, adapt_review(review,groups))
        entries.append({'source': str(source.resolve()), 'source_sha256': source_hash,
            'review': str(review_path.resolve()), 'review_sha256': sha256_file(review_path),
            'adapter': str(adapter_path.relative_to(output)), 'adapter_sha256': sha256_file(adapter_path)})
    code = code_manifest()
    code['file_hashes']['scripts/expert_review_benchmark.py'] = sha256_file(Path(__file__))
    code['code_digest'] = hashlib.sha256(canonical_bytes(code['file_hashes'])).hexdigest()
    manifest = {'schema': 'expert-review-baseline-v1', 'code': code, 'sessions': entries,
        'config': {**DEFAULT_CONFIG, 'max_runs': 3, 'retries': 0, 'total_worker_budget_s': 270,
                   'experimental_local_history': False, 'evidence_policy': 'permission_per_stream',
                   'phase_search': {'kmin': 2, 'kmax': 6, 'max_candidates': 5, 'max_seconds': 60.0,
                                    'selection': 'unchanged production defaults'},
                   'threads': 1, 'overlap_point_convention': 'floor midpoint; bracket retained; no offset fitting',
                   'window_edges': 'censored, excluded from switch and recurrence counts'},
        'acceptance': {'adapter_tests_must_pass': True,
            'no_improvement_claim_from_baseline_only': True,
            'publish_all_timeouts_and_regressions': True,
            'point_metrics': 'unchanged history evaluator +/-2s; matched/truth/predicted, precision/recall, MAE/p95/nearest',
            'coverage': 'temporal coverage separately; physical lamp accuracy unavailable',
            'no_tuning_after_results': True},
        'source_of_groups': 'operator descriptions, not predictions; no mapping fed into inference',
        'scope': 'three NEW development dates, not the historical 34-boundary cohort'}
    write_json(output/'manifest.json',manifest)
    (output/'manifest.sha256').write_text(sha256_file(output/'manifest.json')+'\n',encoding='ascii')


def run(output):
    manifest_path = output/'manifest.json'
    seal = (output/'manifest.sha256').read_text().strip()
    if sha256_file(manifest_path) != seal:
        raise ValueError('manifest changed')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    # Atomic marker prevents accidental reruns/retries, including after interruption.
    with (output/'run_started.json').open('x',encoding='utf-8') as f:
        json.dump({'manifest_sha256': seal, 'code_at_run': code_manifest()},f,indent=2)
    for relative, expected in manifest['code']['file_hashes'].items():
        if sha256_file(ROOT/relative) != expected:
            raise ValueError('production/evaluator code changed after manifest')
    records = []
    env = {**os.environ, 'PYTHONHASHSEED':'0', 'OMP_NUM_THREADS':'1',
           'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}
    for entry in manifest['sessions']:
        source = Path(entry['source'])
        if sha256_file(source) != entry['source_sha256']:
            raise ValueError('trajectory changed')
        prediction = output/'predictions'/(source.stem+'_v9.json')
        row = {'source':source.name, 'prediction':str(prediction.relative_to(output))}
        started = time.monotonic()
        print('Inference only:',source.name,flush=True)
        try:
            p = subprocess.run(worker_command(source,prediction),cwd=ROOT,env=env,
                               capture_output=True,timeout=90)
            row['status'] = 'ok' if p.returncode == 0 and prediction.exists() else 'failed'
            row['exit_code'] = p.returncode
            row['stdout'] = p.stdout.decode('utf-8',errors='replace')[-4000:]
            row['stderr'] = p.stderr.decode('utf-8',errors='replace')[-4000:]
        except subprocess.TimeoutExpired:
            row.update(status='timeout',reason='fixed_90s_worker_budget_exhausted_no_retry')
        row['runtime_s'] = time.monotonic()-started
        if row['status'] == 'ok':
            row['prediction_sha256'] = sha256_file(prediction)
        records.append(row)
        print(row['status'],round(row['runtime_s'],3),flush=True)
        write_json(output/'inference_log.json',records)
    # Seal all prediction bytes before any evaluation is called.
    write_json(output/'predictions_seal.json',{'manifest_sha256':seal,'predictions':records})
    results = []
    for entry,row in zip(manifest['sessions'],records):
        adapter_path = output/entry['adapter']
        if sha256_file(adapter_path) != entry['adapter_sha256']:
            raise ValueError('adapter changed')
        if sha256_file(Path(entry['review'])) != entry['review_sha256']:
            raise ValueError('original review changed')
        if row['status'] != 'ok':
            results.append({**row,'metrics':{'status':'unavailable','reason':row['status']}})
            continue
        prediction_path = output/row['prediction']
        prediction = json.loads(prediction_path.read_text(encoding='utf-8'))
        adapter = json.loads(adapter_path.read_text(encoding='utf-8'))
        metrics = evaluate_review(prediction,adapter)
        if sha256_file(prediction_path) != row['prediction_sha256']:
            raise ValueError('prediction changed during evaluation')
        results.append({**row, 'metrics':metrics})
    write_json(output/'comparison.json',{'manifest_sha256':seal,
        'prediction_seal_sha256':sha256_file(output/'predictions_seal.json'), 'rows':results,
        'historical_34_boundary_cohort': 'unchanged; different dates, no before/after claim',
        'physical_lamp_accuracy': None})
    print('Predictions sealed; evaluation complete.',flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--data',type=Path)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.command == 'prepare':
        if a.data is None: p.error('--data required for prepare')
        prepare(a.data,a.out)
    else: run(a.out)


if __name__ == '__main__': main()
