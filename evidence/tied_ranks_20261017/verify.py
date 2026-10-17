"""Read-only D7 artifact verification; no fitting or annotation evaluation."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'benchmarks/tied_ranks_20261017'
BASE='b84e08b1d141e07da8e524080176c64f205233cc'
CODE='a57ae53f7b9e1f336ee0293a1425ac79264ee2a1'


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    old=ast.parse(subprocess.check_output(['git','show',BASE+':app/core/v9/fit.py'],cwd=ROOT).decode())
    new=ast.parse((ROOT/'app/core/v9/fit.py').read_text(encoding='utf-8'))
    old_nodes={n.name:ast.dump(n) for n in old.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    new_nodes={n.name:ast.dump(n) for n in new.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
    assert sorted(n for n in old_nodes if old_nodes[n]!=new_nodes[n])==['_rank_correlation']
    frozen=read(OUT/'freeze.json'); ledger=read(OUT/'predictions_sealed.json')
    comparison=read(OUT/'comparison.json'); started=read(OUT/'corrected_started.json')
    assert frozen['base_sha']==BASE and started['code_sha']==CODE
    assert sha(ROOT/'app/core/v9/fit.py')==started['fit_sha256']
    assert sha(ROOT/'docs/TIED_RANKS_PROTOCOL_20261017.md')==frozen['protocol_sha256']
    assert sha(ROOT/'scripts/score_contract_review.py')==frozen['worker_sha256']
    control=read(OUT/'control_check.json')
    assert not control['reason'] and all(control[k] for k in ('schedule_exact','period_exact','k_exact'))
    assert len(ledger)==len(comparison['rows'])==len(frozen['inputs'])==3
    results=[]
    for source,entry,scored in zip(frozen['inputs'],ledger,comparison['rows']):
        original=ROOT/'benchmarks/stage2c_20261014/predictions'/entry['file']
        baseline=ROOT/'benchmarks/score_contract_20261017/predictions'/entry['file']
        target=OUT/'predictions'/entry['file']
        assert sha(original)==source['sha256'] and sha(baseline)==source['baseline_sha256']
        assert entry['reason'] is None and sha(target)==entry['prediction_sha256']
        a,b=read(baseline),read(target)
        assert a['period_inference']==b['period_inference']
        assert a['event_extraction']['quality_diagnostics']==b['event_extraction']['quality_diagnostics']
        assert source['selected_indices']==b['event_extraction']['quality_diagnostics']['selected_event_indices']
        for key in ('analysis_base_timestamp_ms','recording_start_timestamp_ms','recording_duration_s','event_count'):
            assert a[key]==b[key],key
        for f,g in zip(a['score_contract_trace']['fits'],b['score_contract_trace']['fits']):
            assert f==g, 'D7 must not change per-K fitting'
        for c,d in zip(a['phase_model_selection']['candidates'],b['phase_model_selection']['candidates']):
            assert {k:v for k,v in c.items() if k!='runtime_s'}=={k:v for k,v in d.items() if k!='runtime_s'}
        assert b['score_contract_trace']['annotations_used'] is False
        assert not b.get('reconstruction_history')
        assert b['state_contract']['physical_section']['estimated_state']=='UNKNOWN'
        search=b['phase_model_selection']['search']
        assert search['search_status']=='complete' and search['evaluated_candidate_count']==5
        results.append(dict(file=entry['file'],before_k=a['schedule']['phase_count'],after_k=b['schedule']['phase_count'],
            raw_exact=scored['raw_exact'],baseline_exact=scored['baseline_exact'],period_exact=True,selection_exact=True,
            all_per_k_fits_and_candidate_scores_exact=True,metrics_exact=scored['before']==scored['after'],
            runtime_s=entry['runtime_s'],before_redundancy=a['phase_redundancy'],after_redundancy=b['phase_redundancy']))
    protected=['app/core/v9/decoder.py','app/core/v9/model.py','app/core/v9/events.py','app/core/v9/primitives.py',
        'app/core/v9/vehicle_evidence.py','app/core/v10','app/core/state_contract.py','app/core/temporal_evidence.py',
        'app/core/offline_benchmark.py','scripts/offline_benchmark.py','scripts/score_contract_review.py','config',
        'benchmarks/stage2c_20261014','benchmarks/hsmm_recurrence_20261016',
        'benchmarks/seed_flow_20261017','benchmarks/score_contract_20261017']
    assert not subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT).strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    print(json.dumps(dict(base_sha=BASE,code_sha=CODE,only_changed_function='_rank_correlation',
        structural_gate='PASS',tests_unique_pass=240,strict_xfails=4,main_and_protected_unchanged=True,
        local_2D1='FAIL_DEFAULT_OFF',physical_lamp_accuracy='UNKNOWN',results=results),indent=2))


if __name__=='__main__':
    main()
