"""Engineering parity of the production backend against the sealed candidate.

The optional cache contains numerical HSMM fits keyed by observations/settings,
not predictions or truth. Evaluation files are opened only AFTER prediction.
Cold raw-ZIP application integration is checked separately.
"""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

from scripts.corpus_validation import prepare_worker_environment, save, ROOT
prepare_worker_environment()
from scripts.accuracy_recovery import cached_bundle, RUNTIME, OUT, OLD

MODE = 'tracks_motion_clock075_signature_hybrid'


def prediction_path(key):
    for mode in (MODE, MODE+'_retry'):
        path = RUNTIME/'predictions'/mode/(key+'.json.gz')
        if path.exists():
            return path
    raise FileNotFoundError(key)


def worker(key, *, cold=False):
    import numpy as np
    from app.core.recovery import engine
    from app.core.v9.fit import PhaseCountSearch
    target = OUT/'production_parity'/(key+('_cold' if cold else '')+'.json')
    if target.exists():
        return
    begin = time.monotonic()
    hits = []
    original = engine.discover_phase_count

    def numerical_search(*args, **kwargs):
        signature = hashlib.sha256(args[0].tobytes()+repr(args[1:]).encode()+repr(sorted(kwargs.items())).encode()).hexdigest()
        cache = RUNTIME/'fit_cache'/(signature+'.pkl')
        if not cold and cache.exists():
            with cache.open('rb') as stream:
                payload = pickle.load(stream)  # trusted, locally produced fits
            hits.append(signature)
            return PhaseCountSearch(payload[0], payload[1], payload[2], payload[3])
        return original(*args, **kwargs)

    try:
        bundle = cached_bundle(key, motion=True)
        # No monkeypatch of shared V9 globals; this process-local test patches
        # only the pure numerical backend, with identical fit-cache contents.
        with patch.object(engine, 'discover_phase_count', numerical_search):
            result = engine.discover_bundle(bundle)
        # Prediction completed. Only now inspect the sealed expected output.
        with gzip.open(prediction_path(key), 'rt', encoding='utf8') as stream:
            expected = json.load(stream)
        actual = json.loads(json.dumps(result))
        schedule_a, schedule_b = deepcopy(actual['schedule']), deepcopy(expected['schedule'])
        schedule_a.pop('model'); schedule_b.pop('model')
        checks = dict(schedule=schedule_a == schedule_b,
                      physical_plan=actual['physical_signal_plan'] == expected['physical_signal_plan'],
                      clock=actual.get('phase_clock') == expected.get('phase_clock'),
                      period=actual['period_inference'] == expected['period_inference'])
        row = dict(key=key, status='PASS' if all(checks.values()) else 'FAIL', checks=checks,
                   numerical_fit_cache_hits=hits, cold=cold, k=actual['schedule']['phase_count'],
                   period_s=actual['schedule']['period_s'], model=actual['recovery_model'])
        if key.startswith('real_'):
            from app.core.v9.source_scope import input_sessions
            sessions = input_sessions(bundle, bundle[5][0])
            row['source_sessions'] = len(sessions)
            assert len(sessions) == 1, 'source requires separately scoped replay'
        else:
            truth_path = (RUNTIME/'holdout'/key if key.startswith('holdout_') else OLD/'synthetic'/key)/'truth.json.gz'
            with gzip.open(truth_path, 'rt', encoding='utf8') as stream:
                truth = json.load(stream)
            from scripts.realistic_traffic_benchmark import score_prediction
            from scripts.validation_report import without_samples
            row['score'] = without_samples(score_prediction(result, truth))
        if not all(checks.values()):
            mismatch = RUNTIME/'parity_mismatches'/(key+('_cold' if cold else '')+'.json.gz')
            mismatch.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(mismatch, 'xt', encoding='utf8') as stream:
                json.dump(result, stream)
    except Exception as exc:
        row = dict(key=key, status='ERROR', error=str(exc), traceback=traceback.format_exc())
    row['runtime_s'] = time.monotonic()-begin
    save(target, row)
    print(key, row['status'], row.get('checks'), flush=True)


def batch(workers=3):
    from concurrent.futures import ThreadPoolExecutor
    keys = sorted(p.stem for p in (OUT/'pilot'/MODE).glob('*.json'))
    env = {**os.environ, 'OMP_NUM_THREADS':'1', 'OPENBLAS_NUM_THREADS':'1', 'MKL_NUM_THREADS':'1'}

    def run(key):
        result = subprocess.run([sys.executable, '-m', 'scripts.verify_recovery_release', '--key', key],
                                cwd=ROOT, env=env, capture_output=True, text=True)
        print(result.stdout.strip(), result.stderr[-500:], flush=True)
        if result.returncode:
            raise RuntimeError((key, result.returncode))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        list(executor.map(run, keys))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key')
    parser.add_argument('--cold', action='store_true')
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    if args.key:
        worker(args.key, cold=args.cold)
    else:
        batch(args.workers)
