"""Read-only verification; never fitting, annotation evaluation or tuning."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'benchmarks/review_closure_20261017'
BASE='c414c5ef486b145cb7605017fbeabee3e68237b0'
CODE='9e987c804c1880b991f5298da27f71224778d8c8'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def nodes(source):
    return {n.name:ast.dump(n) for n in ast.parse(source).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}


def compact(metrics):
    result={}
    for name,m in metrics['histories'].items():
        b=m['boundaries'];a=b['mae_s']
        result[name]=dict(matched=a['matched_boundaries'],truth=a['truth_boundaries'],predicted=a['predicted_boundaries'],
            precision=b['precision']['value'],recall=b['recall']['value'],matched_mae_s=a['value'],
            matched_p95_s=b['p95_s']['value'],nearest_mae_s=b['nearest_truth_boundary_mae_s_diagnostic']['value'],
            coverage=m['coverage']['value'],n=a['n_observations'],range_ms=a['range_ms'],reason=a['reason'])
    return result


def main():
    changes={
        'app/core/v9/fit.py':['_fit_from_initial_labels','_fuse_seed_views','_phase_support_metrics','candidate_metrics','em_fit'],
        'app/core/v9/events.py':['_circular_center','periodic_baseline_from_segments'],
        'app/core/v9/model.py':['_discover_from_stream_views'],
        'app/core/v9/primitives.py':['initial_seed_from_streams'],
    }
    for name,expected in changes.items():
        a=nodes(subprocess.check_output(['git','show',BASE+':'+name],cwd=ROOT).decode())
        b=nodes((ROOT/name).read_text(encoding='utf-8'))
        assert sorted(n for n in a.keys()|b.keys() if a.get(n)!=b.get(n))==expected,name
    # Producer algorithm is byte-for-AST identical apart from provenance field.
    p='app/core/v9/primitives.py'
    a=ast.parse(subprocess.check_output(['git','show',BASE+':'+p],cwd=ROOT).decode())
    b=ast.parse((ROOT/p).read_text(encoding='utf-8'))
    function=next(n for n in b.body if isinstance(n,ast.FunctionDef) and n.name=='initial_seed_from_streams')
    field=function.body[-1].value.elts[1]
    index=next(i for i,k in enumerate(field.keys) if isinstance(k,ast.Constant) and k.value=='group_streams')
    del field.keys[index];del field.values[index]
    assert ast.dump(a)==ast.dump(b)
    frozen=read(OUT/'freeze.json');ledger=read(OUT/'predictions_sealed.json')
    comparison=read(OUT/'comparison.json');started=read(OUT/'corrected_started.json')
    assert frozen['base_sha']==BASE and started['code_sha']==CODE
    assert sha(ROOT/'app/core/v9/fit.py')==started['fit_sha256']
    assert sha(ROOT/'docs/REVIEW_CLOSURE_PROTOCOL_20261017.md')==frozen['protocol_sha256']
    assert sha(ROOT/'scripts/score_contract_review.py')==frozen['worker_sha256']
    control=read(OUT/'control_check.json')
    assert not control['reason'] and all(control[k] for k in ('schedule_exact','period_exact','k_exact'))
    assert len(ledger)==len(comparison['rows'])==len(frozen['inputs'])==3
    results=[]
    for source,entry,scored in zip(frozen['inputs'],ledger,comparison['rows']):
        original=ROOT/'benchmarks/stage2c_20261014/predictions'/entry['file']
        baseline=ROOT/'benchmarks/tied_ranks_20261017/predictions'/entry['file']
        target=OUT/'predictions'/entry['file']
        assert sha(original)==source['sha256'] and sha(baseline)==source['baseline_sha256']
        if entry['reason']:
            results.append(dict(file=entry['file'],status='unavailable',reason=entry['reason']))
            continue
        assert sha(target)==entry['prediction_sha256']
        a,b=read(baseline),read(target)
        assert a['period_inference']==b['period_inference']
        assert a['event_extraction']['quality_diagnostics']==b['event_extraction']['quality_diagnostics']
        assert source['selected_indices']==b['event_extraction']['quality_diagnostics']['selected_event_indices']
        for key in ('analysis_base_timestamp_ms','recording_start_timestamp_ms','recording_duration_s','event_count'):
            assert a[key]==b[key],key
        assert b['score_contract_trace']['annotations_used'] is False
        assert not b.get('reconstruction_history')
        assert b['state_contract']['physical_section']['estimated_state']=='UNKNOWN'
        trace={f['k']:f for f in b['score_contract_trace']['fits']}
        candidates=[]
        for c in b['phase_model_selection']['candidates']:
            f=trace[c['k']]
            assert f['score']==f['pointwise_loglik']==f['data_loglik']==c['objective']
            assert c['phase_support_semantics']=='heuristic_joint_fitted_signature_NOT_external_identifiability'
            candidates.append(dict(k=c['k'],objective=c['objective'],selection_score=c['selection_score'],
                supported=c['supported_phase_count'],unsupported=c['unsupported_phase_count'],
                initialization=f['initialization'],ensemble=c['initialization_diagnostics']['ensemble'],
                selected_source_candidates=f['initialization_candidates']))
        results.append(dict(file=entry['file'],before_k=a['schedule']['phase_count'],after_k=b['schedule']['phase_count'],
            raw_exact=scored['raw_exact'],baseline_exact=scored['baseline_exact'],period_exact=True,selection_exact=True,
            metrics_before=compact(scored['before']),metrics_after=compact(scored['after']),
            period_error_s=scored['after']['period_absolute_error_s'],runtime_s=entry['runtime_s'],
            baseline_diagnostics=b['schedule']['baseline_reconstruction'],
            search=b['phase_model_selection']['search'],candidate_diagnostics=candidates))
    protected=['app/core/v9/decoder.py','app/core/v9/source_scope.py','app/core/v9/vehicle_evidence.py',
        'app/core/v10','app/core/state_contract.py','app/core/temporal_evidence.py','app/core/vehicle_evidence.py',
        'app/core/offline_benchmark.py','scripts/offline_benchmark.py','scripts/score_contract_review.py',
        'app/experimental','config','benchmarks/stage2c_20261014','benchmarks/hsmm_recurrence_20261016',
        'benchmarks/seed_flow_20261017','benchmarks/score_contract_20261017','benchmarks/tied_ranks_20261017']
    assert not subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT).strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    print(json.dumps(dict(base_sha=BASE,code_sha=CODE,production_changes=changes,tests_unique_pass=291,
        review_expected_failures=0,structural_gate='PASS',main_and_protected_unchanged=True,
        combined_experiment='no_individual_fix_causal_attribution',local_2D1='FAIL_DEFAULT_OFF',
        physical_lamp_accuracy='UNKNOWN',results=results),indent=2))


if __name__=='__main__':
    main()
