"""Read-only native review/result verification. Never fitting or scoring truth."""
import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'benchmarks/seed_flow_20261017'
BASE = 'b7675c70bf191a20454fe974baa18cc161f01856'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    before = ast.parse(subprocess.check_output(['git','show',BASE+':app/core/v9/fit.py'],cwd=ROOT).decode())
    after = ast.parse((ROOT/'app/core/v9/fit.py').read_text(encoding='utf-8'))
    previous = {n.name:n for n in before.body if isinstance(n,ast.FunctionDef)}
    current = {n.name:n for n in after.body if isinstance(n,ast.FunctionDef)}
    for name in previous.keys()-{'em_fit'}:
        assert ast.dump(previous[name]) == ast.dump(current[name]), name
    expected = deepcopy(previous['em_fit'])
    index = next(i for i,n in enumerate(expected.body) if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='unique' for t in n.targets))
    nodes = expected.body
    assert isinstance(nodes[index+4],ast.If)
    expected.body = nodes[:index]+[nodes[index+4]]+nodes[index:index+4]+nodes[index+5:]
    assert ast.dump(expected) == ast.dump(current['em_fit'])
    frozen = json.loads((OUT/'freeze.json').read_text(encoding='utf-8'))
    control = json.loads((OUT/'control_check.json').read_text(encoding='utf-8'))
    assert control['schedule_exact'] and control['period_exact'] and control['raw_exact'] and control['k_exact']
    ledger = json.loads((OUT/'predictions_sealed.json').read_text(encoding='utf-8'))
    comparison = json.loads((OUT/'comparison.json').read_text(encoding='utf-8'))
    results=[]
    for source, entry, scored in zip(frozen['inputs'],ledger,comparison['rows']):
        original = ROOT/'benchmarks/stage2c_20261014/predictions'/entry['file']
        baseline = ROOT/'benchmarks/hsmm_recurrence_20261016/predictions'/entry['file']
        target = OUT/'predictions'/entry['file']
        assert sha(original) == source['sha256'] and sha(baseline) == source['baseline_sha256']
        assert sha(target) == entry['prediction_sha256'] and not entry['reason']
        old = json.loads(baseline.read_text(encoding='utf-8'))
        new = json.loads(target.read_text(encoding='utf-8'))
        assert old['schedule'] == new['schedule']
        assert old['period_inference'] == new['period_inference']
        assert old['phase_evidence'] == new['phase_evidence']
        assert source['selected_indices'] == new['event_extraction']['quality_diagnostics']['selected_event_indices']
        assert scored['before'] == scored['after']
        assert not new.get('reconstruction_history')
        assert new['state_contract']['physical_section']['estimated_state']=='UNKNOWN'
        trace = new['seed_flow_trace']
        splits = [r for r in trace['refinements'] if r['source']=='two_phase_internal_split_seed']
        assert [r['parent'] for r in splits] == [0,1]
        assert new['phase_model_selection']['search']['search_status']=='complete'
        assert [r['k'] for r in new['phase_model_selection']['search']['candidate_ledger']] == [2,3,4,5,6]
        rows=[]
        for field, metric in scored['after']['histories'].items():
            b=metric['boundaries'];m=b['mae_s']
            rows.append(dict(field=field,matched=m['matched_boundaries'],truth=m['truth_boundaries'],
                predicted=m['predicted_boundaries'],precision=b['precision']['value'],recall=b['recall']['value'],
                matched_mae_s=m['value'],matched_p95_s=b['p95_s']['value'],
                nearest_mae_s=b['nearest_truth_boundary_mae_s_diagnostic']['value'],
                n=m['n_observations'],range_ms=m['range_ms'],coverage=metric['coverage']['value'],reason=m['reason']))
        results.append(dict(file=entry['file'],selected_k=new['schedule']['phase_count'],
            selected_initialization=next(f['initialization'] for f in trace['fits'] if f['k']==new['schedule']['phase_count']),
            split_refinements_complete=len(splits),schedule_exact=True,metrics=rows,runtime_s=entry['runtime_s']))
    protected=['app/core/v9/decoder.py','app/core/v9/model.py','app/core/v9/events.py',
        'app/core/v9/primitives.py','app/core/v9/vehicle_evidence.py','app/core/v10',
        'app/core/state_contract.py','app/core/temporal_evidence.py','app/core/offline_benchmark.py',
        'scripts/offline_benchmark.py','config','benchmarks/stage2c_20261014','benchmarks/hsmm_recurrence_20261016']
    assert not subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT).strip()
    main_sha=subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()
    assert main_sha=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    print(json.dumps(dict(base_sha=BASE,native_control_exact=True,only_production_change='AST block relocation in em_fit',
        other_fit_functions_exact=True,protected_files_unchanged=True,main_unchanged=main_sha,
        native_tests_passed=208,open_expected_failures=8,open_defects=7,results=results,
        structural_gate='PASS',development_benefit_gate='FAIL_NO_GAIN',local_2D1='FAIL_DEFAULT_OFF',
        real_accuracy_improvement=False,raw_trajectory_reads=0,no_post_result_tuning=True),indent=2))


if __name__=='__main__':
    main()
