import pytest
"""Sealed-artifact checks only: no new inference calls."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/stage2d1_event_time_prototype'


def read(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def test_outputs_and_inputs_seals():
    seal=read(OUT/'outputs_sealed.json');started=read(OUT/'started.json')
    assert seal['inference_calls']==36
    assert seal['cpu_s']<=read(OUT/'manifest.json')['suite_cpu_seconds']
    assert sha(OUT/'inputs.json')==seal['inputs_after_sha256']==started['inputs_sha256']
    for item in seal['predictions']:
        assert sha(ROOT/item['path'])==item['sha256']
    for p,h in started['source_hashes'].items(): assert sha(ROOT/p)==h
    assert sha(ROOT/'app/core/offline_benchmark.py')==started['evaluator_sha256']


def test_truth_absent_from_inputs_and_fixed_priors():
    for case in read(OUT/'inputs.json'):
        assert set(case)=={'case','seed','inference_input'}
        assert set(case['inference_input'])=={'events','mapping','order','windows','horizon','rates'}
    from scripts.event_time_prototype import PRIORS
    assert PRIORS==read(OUT/'manifest.json')['priors']


def test_sealed_adapters_and_no_promotion():
    comparison=read(OUT/'comparison.json')
    assert comparison['historical_gate']=='FAIL_UNCHANGED'
    assert comparison['production_acceptance'] is False
    for row in comparison['rows']:
        name=f"{row['case']}_seed{row['seed']}_{row['prior']}.json"
        assert sha(OUT/'evaluation_adapters'/name)==row['adapter_sha256']
        out=read(OUT/'predictions'/name)
        assert out['physical_state']=='UNKNOWN'
        if out['complete']:
            graph={tuple(e) for e in out['feasible_graph']}
            segs=out['diagnostic_segments']
            assert all((a,i,b,i==len(segs)-1) in graph for i,(a,b,z) in enumerate(segs))
            assert row['event_constraint_violations']==0
            for boundary in out['boundary_sets']:
                assert boundary['times_s']==sorted({u for t,n,u,final in graph if not final and n+1==boundary['ordinal']})
        else:
            assert out['boundary_sets']==[] and out['unknown_fraction']==1


def test_prior_dependence_preserved_without_winner():
    comp=read(OUT/'comparison.json')
    assert all(r['same_feasible_sets'] for r in comp['prior_dependence'])
    for prior in ['uniform','nominal10']:
        assert any(r['point_core_gate']=='FAIL' for r in comp['rows'] if r['prior']==prior)


pytestmark = pytest.mark.local_evidence
