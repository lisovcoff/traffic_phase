"""Read-only verification/summary of the single frozen comparison. No fitting."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT/'benchmarks/hsmm_recurrence_20261016'
BASE = '5b84eab96966f2220d85978056b1568d2f17226a'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    frozen = json.loads((RUN/'freeze.json').read_text(encoding='utf-8'))
    ledger = json.loads((RUN/'predictions_sealed.json').read_text(encoding='utf-8'))
    comparison = json.loads((RUN/'comparison.json').read_text(encoding='utf-8'))
    rows, candidates = [], []
    for before_entry, entry, scored in zip(frozen['inputs'], ledger, comparison['rows']):
        source = ROOT/'benchmarks/stage2c_20261014/predictions'/entry['file']
        target = RUN/'predictions'/entry['file']
        assert sha(source) == before_entry['sha256']
        assert sha(target) == entry['prediction_sha256'] and not entry['reason']
        old = json.loads(source.read_text(encoding='utf-8'))
        new = json.loads(target.read_text(encoding='utf-8'))
        assert old['schedule'] == new['schedule']
        assert old['period_inference'] == new['period_inference']
        assert old['phase_evidence'] == new['phase_evidence']
        assert old['event_extraction']['quality_diagnostics'] == new['event_extraction']['quality_diagnostics']
        assert scored['before'] == scored['after']
        assert not new.get('reconstruction_history')
        assert new['state_contract']['physical_section']['estimated_state'] == 'UNKNOWN'
        old_candidates = {c['k']: c for c in old['phase_model_selection']['candidates']}
        changed = []
        for candidate in new['phase_model_selection']['candidates']:
            previous = old_candidates[candidate['k']]
            if candidate['objective'] != previous['objective']:
                changed.append(dict(k=candidate['k'], before=previous['objective'], after=candidate['objective']))
        candidates.append(dict(file=entry['file'], changed_objectives=changed))
        for field in ('raw_hsmm_segments', 'baseline_segments'):
            metric = scored['after']['histories'][field]
            b = metric['boundaries']; m = b['mae_s']
            rows.append(dict(file=scored['source'], field=field, K=new['schedule']['phase_count'],
                period_error_s=scored['after']['period_absolute_error_s']['value'],
                matched=m['matched_boundaries'], truth=m['truth_boundaries'], predicted=m['predicted_boundaries'],
                precision=b['precision']['value'], recall=b['recall']['value'], matched_mae_s=m['value'],
                matched_p95_s=b['p95_s']['value'], nearest_mae_s=b['nearest_truth_boundary_mae_s_diagnostic']['value'],
                temporal_coverage=metric['coverage']['value'], range_ms=m['range_ms'],
                matched_observations=m['n_observations'], reason=m['reason'], runtime_s=entry['runtime_s']))
    protected = ['app/core/v9/fit.py', 'app/core/v9/model.py', 'app/core/v9/events.py',
                 'app/core/v9/primitives.py', 'app/core/v9/vehicle_evidence.py', 'app/core/v10',
                 'app/core/state_contract.py', 'app/core/temporal_evidence.py', 'app/core/offline_benchmark.py',
                 'scripts/offline_benchmark.py', 'config', 'benchmarks/stage2c_20261014']
    assert not subprocess.check_output(['git', 'diff', '--name-only', BASE, '--', *protected], cwd=ROOT).strip()
    main_sha = subprocess.check_output(['git', 'rev-parse', 'main'], cwd=ROOT, text=True).strip()
    assert main_sha == 'a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    result = dict(input_selection_schedule_period_exact=True, no_real_accuracy_improvement=True,
        corrected_candidate_objectives=candidates, metrics=rows, protected_files_unchanged=True,
        main_unchanged=main_sha, worker_timeouts=0, control_runs=1, corrected_discoveries=3,
        raw_json_reads=0, tuning_runs=0, physical_lamps='UNKNOWN', stage_2D1='FAIL')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
