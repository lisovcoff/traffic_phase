import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/unanchored_sequence_20261015'


def load(name):return json.loads((OUT/name).read_text(encoding='utf-8'))


def test_sealed_output_inputs_and_frozen_code():
    seal=load('outputs_sealed.json');manifest=load('manifest.json')
    assert seal['calls']==manifest['max_calls']==5
    assert not seal['truth_file_read_by_worker']
    for name,expected in [('predictions.json',seal['predictions_sha256']),
        ('inputs.json',manifest['inputs_sha256']),('truth.json',manifest['truth_sha256'])]:
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==expected
    assert hashlib.sha256((ROOT/'docs/UNANCHORED_SEQUENCE_PROTOCOL_20261015.md').read_bytes()).hexdigest()==manifest['protocol_sha256']
    for name,expected in manifest['source_sha256_lf'].items():
        frozen=subprocess.check_output(['git','show',f"{manifest['code_commit']}:{name}"],cwd=ROOT)
        assert hashlib.sha256(frozen.replace(b'\r\n',b'\n')).hexdigest()==expected


def test_exact_witness_criterion_both_priors_and_prior_only_unknown():
    rows=load('comparison.json')['rows'];preds=load('predictions.json')
    witnesses=[r for r in rows if r['case'].startswith('informative')]
    assert len(witnesses)==4 and all(r['exact_witness_pass'] for r in witnesses)
    for name in ('zero_demand','camera_missing'):
        output=preds[name]
        assert output['prior_only_numerically']
        assert output['logical_phase']['estimated_state']==output['physical_section']['estimated_state']=='UNKNOWN'
        for result in output['results'].values():
            assert result['posterior_vs_prior_kl_nats']==pytest.approx(0,abs=1e-12)
            assert len(result['transition_count_posterior'])>1


def test_all_alternatives_and_count_conditionals_normalized():
    for output in load('predictions.json').values():
        assert output['complete'] and len(output['alternatives'])==output['path_count']
        for name,result in output['results'].items():
            assert sum(row['posterior'][name] for row in output['alternatives'])==pytest.approx(1)
            assert sum(result['transition_count_posterior'].values())==pytest.approx(1)
            for ordinals in result['boundary_posteriors_conditioned_on_count'].values():
                for mass in ordinals.values():assert sum(mass.values())==pytest.approx(1)
