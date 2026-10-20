import gzip
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/sparse_duration_20261015'


def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))


def test_all_outputs_and_frozen_inputs_sources_match_seals():
    m=read('manifest.json');s=read('outputs_sealed.json')
    assert s['calls']==m['max_calls']==16
    assert not s['truth_file_read_by_worker']
    for name,expected in [('inputs.json',m['inputs_sha256']),('truth.json',m['truth_sha256'])]:
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==expected
    assert hashlib.sha256((ROOT/'docs/SPARSE_DURATION_PROTOCOL_20261015.md').read_bytes()).hexdigest()==m['protocol_sha256']
    for name,expected in m['source_sha256_lf'].items():
        frozen=subprocess.check_output(['git','show',f"{m['code_commit']}:{name}"],cwd=ROOT)
        assert hashlib.sha256(frozen.replace(b'\r\n',b'\n')).hexdigest()==expected
    for e in s['predictions']:assert hashlib.sha256((OUT/e['path']).read_bytes()).hexdigest()==e['sha256']


def test_failures_and_long_hold_budget_refusal_retained():
    c=read('comparison.json')
    assert c['original_2d1_gate']=='FAIL_UNCHANGED'
    assert c['aggregate']['flat']['core_pass']==8
    assert c['aggregate']['soft']['core_pass']==7
    assert all(a['truth']==34 and a['matched']==29 for a in c['aggregate'].values())
    hold=[r for r in c['rows'] if '_hold30_' in r['case']]
    assert len(hold)==2
    assert all(r['status']=='unavailable' and 'PATH_BUDGET' in r['reason'] and r['diagnostic_temporal_coverage']==0 for r in hold)
    assert all(r['truth']==3 and r['matched']==0 and r['predicted']==0 for r in hold)


def test_no_demand_has_no_invented_logical_or_lamp_observation():
    r=json.loads(gzip.decompress((OUT/'K2_no_demand_seed7.json.gz').read_bytes()))
    assert r['prior_only_numerically']
    assert r['logical_phase']['estimated_state']==r['physical_section']['estimated_state']=='UNKNOWN'
    for p in r['results'].values():assert p['posterior_vs_prior_kl_nats']==pytest.approx(0,abs=1e-12)


def test_conditional_intervals_do_not_replace_count_or_point_gate():
    c=read('comparison.json')
    assert 'truth count' in c['conditional_interval_warning']
    failures=[r for r in c['rows'] if r['core_gate']=='FAIL']
    assert failures and any(r['truth_count_posterior_mass']<.15 for r in failures)
    for r in c['rows']:
        assert r['published_logical_unknown_fraction']==r['physical_unknown_fraction']==1
        assert len(r['conditional_intervals'])==r['truth']


pytestmark = pytest.mark.local_evidence
