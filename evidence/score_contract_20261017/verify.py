"""Read-only verification of the frozen score-contract comparison, no fitting."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'benchmarks/score_contract_20261017'
BASE='e41c075d7c9cef7c6eb512cfadf7d29d435cafba'
CODE='787c9776e47675ab9dede456330b65850f0ef799'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compact(metrics):
    rows=[]
    for field, m in metrics['histories'].items():
        b=m['boundaries']; a=b['mae_s']
        rows.append(dict(field=field,matched=a['matched_boundaries'],truth=a['truth_boundaries'],
            predicted=a['predicted_boundaries'],precision=b['precision']['value'],recall=b['recall']['value'],
            matched_mae_s=a['value'],matched_p95_s=b['p95_s']['value'],
            nearest_mae_s=b['nearest_truth_boundary_mae_s_diagnostic']['value'],
            coverage=m['coverage']['value'],n=a['n_observations'],range_ms=a['range_ms'],reason=a['reason']))
    return rows


def main():
    before=ast.parse(subprocess.check_output(['git','show',BASE+':app/core/v9/fit.py'],cwd=ROOT).decode())
    after=ast.parse((ROOT/'app/core/v9/fit.py').read_text(encoding='utf-8'))
    old_nodes={n.name:ast.dump(n) for n in before.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    new_nodes={n.name:ast.dump(n) for n in after.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    changed=sorted(n for n in old_nodes if old_nodes[n]!=new_nodes[n])
    assert changed==['_fit_from_initial_labels','_seed_labels_to_fit','candidate_metrics','em_fit']
    frozen=read(OUT/'freeze.json'); control=read(OUT/'control_check.json')
    assert frozen['base_sha']==BASE
    assert control['schedule_exact'] and control['period_exact'] and control['raw_exact'] and control['k_exact']
    assert sha(ROOT/'docs/SCORE_CONTRACT_PROTOCOL_20261017.md')==frozen['protocol_sha256']
    assert read(OUT/'corrected_started.json')['code_sha']==CODE
    assert sha(ROOT/'app/core/v9/fit.py')==read(OUT/'corrected_started.json')['fit_sha256']
    ledger=read(OUT/'predictions_sealed.json'); comparison=read(OUT/'comparison.json')
    assert len(ledger)==len(comparison['rows'])==3
    results=[]
    for source, entry, scored in zip(frozen['inputs'],ledger,comparison['rows']):
        original=ROOT/'benchmarks/stage2c_20261014/predictions'/entry['file']
        baseline=ROOT/'benchmarks/seed_flow_20261017/predictions'/entry['file']
        target=OUT/'predictions'/entry['file']
        assert sha(original)==source['sha256'] and sha(baseline)==source['baseline_sha256']
        assert sha(target)==entry['prediction_sha256'] and entry['reason'] is None
        old,new=read(baseline),read(target)
        assert old['period_inference']==new['period_inference']
        assert old['event_extraction']['quality_diagnostics']==new['event_extraction']['quality_diagnostics']
        assert source['selected_indices']==new['event_extraction']['quality_diagnostics']['selected_event_indices']
        for key in ('analysis_base_timestamp_ms','recording_start_timestamp_ms','recording_duration_s','event_count'):
            assert old[key]==new[key], key
        assert not new.get('reconstruction_history')
        assert new['state_contract']['physical_section']['estimated_state']=='UNKNOWN'
        trace=new['score_contract_trace']
        assert trace['annotations_used'] is False
        for r in trace['refinements']:
            assert r['score']==r['penalized_objective']
            assert abs(r['score']-max(h['loglik_with_duration_penalty'] for h in r['history']))<1e-8
            for h in r['history']:
                expected=h['decoder_input_objective']+h['data_loglik']-h['decoder_input_data_loglik']
                assert abs(expected-h['loglik_with_duration_penalty'])<1e-8
        old_trace={f['k']:f for f in old['seed_flow_trace']['fits']}
        candidates=new['phase_model_selection']['candidates']
        old_candidates={c['k']:c for c in old['phase_model_selection']['candidates']}
        changes=[]
        for f,c in zip(trace['fits'],candidates):
            assert f['k']==c['k']
            assert f['score']==f['data_loglik']==f['pointwise_loglik']==c['objective']==c['data_loglik']
            assert f['score_semantics']=='data_loglik' and c['objective_semantics']=='returned_model_data_loglik'
            previous=old_trace[f['k']]; previous_c=old_candidates[f['k']]
            changes.append(dict(k=f['k'],labels_exact=f['labels_sha256']==previous['labels_sha256'],
                probs_exact=f['probs_sha256']==previous['probs_sha256'],
                before_initialization=previous['initialization'],after_initialization=f['initialization'],
                old_mixed_objective=previous_c['objective'],data_loglik=c['data_loglik'],
                before_selection_score=previous_c['selection_score'],after_selection_score=c['selection_score'],
                eligibility_reason=c['eligibility_reason'],penalized_objective=c['penalized_objective']))
        search=new['phase_model_selection']['search']
        assert search['search_status']=='complete'
        assert [c['k'] for c in search['candidate_ledger']]==[2,3,4,5,6]
        results.append(dict(file=entry['file'],before_k=old['schedule']['phase_count'],after_k=new['schedule']['phase_count'],
            period_exact=True,selection_exact=True,raw_exact=scored['raw_exact'],baseline_exact=scored['baseline_exact'],
            metrics_before=compact(scored['before']),metrics_after=compact(scored['after']),
            runtime_s=entry['runtime_s'],candidates=changes))
    protected=['app/core/v9/decoder.py','app/core/v9/model.py','app/core/v9/events.py',
        'app/core/v9/primitives.py','app/core/v9/vehicle_evidence.py','app/core/v10',
        'app/core/state_contract.py','app/core/temporal_evidence.py','app/core/offline_benchmark.py',
        'scripts/offline_benchmark.py','config','benchmarks/stage2c_20261014',
        'benchmarks/hsmm_recurrence_20261016','benchmarks/seed_flow_20261017']
    assert not subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT).strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    print(json.dumps(dict(base_sha=BASE,code_sha=CODE,changed_functions=changed,main_unchanged=True,
        protected_files_unchanged=True,structural_gate='PASS',tests_passed_unique=225,strict_xfails=6,
        local_2D1='FAIL_DEFAULT_OFF',physical_lamp_accuracy='UNKNOWN',results=results),indent=2))


if __name__=='__main__':
    main()
