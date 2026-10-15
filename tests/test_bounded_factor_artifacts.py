import hashlib
import json
from pathlib import Path
import subprocess

import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/bounded_factor_history_20261016'


def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))


def test_manifest_frozen_sources_and_sealed_prediction():
    m=read('manifest.json');seal=read('output_sealed.json')
    assert hashlib.sha256((OUT/'inputs.json').read_bytes()).hexdigest()==m['input_sha256']
    assert hashlib.sha256((OUT/'prediction.json').read_bytes()).hexdigest()==seal['prediction_sha256']
    assert m['max_calls']==seal['technical_inference_calls']==1
    assert seal['real_replays']==seal['recovery_truth_files']==0
    for name,expected in m['source_sha256_lf'].items():
        source=subprocess.check_output(['git','show',f"{m['code_commit']}:{name}"],cwd=ROOT)
        assert hashlib.sha256(source.replace(b'\r\n',b'\n')).hexdigest()==expected


def test_nonlocal_64s_example_complete_without_enumeration_or_truncation():
    r=read('prediction.json');m=read('manifest.json')
    assert r['complete'] and r['observed_max_kernel_span_cells']==3
    assert not r['enumeration_used'] and not r['truncation_used']
    assert r['max_states_in_layer']<=m['limits']['max_states_per_layer']
    assert r['declared_state_allowance_bytes']<=m['limits']['max_memory_bytes']
    assert r['context_plan']['target_range_ms']==[10000,56000]
    assert r['logical_phase']['estimated_state']==r['physical_section']['estimated_state']=='UNKNOWN'
    assert r['calibrated_lamp_probability'] is None


def test_posterior_count_and_boundary_marginals_are_consistent():
    r=read('prediction.json');assert set(r['results'])=={'flat','soft'}
    for result in r['results'].values():
        assert sum(result['transition_count_posterior'].values())==pytest.approx(1)
        assert all(sum(row)==pytest.approx(1) for row in result['phase_posterior'])
        expected=sum(int(n)*p for n,p in result['transition_count_posterior'].items())
        assert sum(b['model_conditioned_existence_probability'] for b in result['boundary_existence'])==pytest.approx(expected)
        assert len(result['boundary_existence'])==31
        assert result['diagnostic_segments'][-1][1]==64
