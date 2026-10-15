import copy
import inspect
import math

import numpy as np
import pytest

from app.experimental.joint_track_model import PRIORS, ModelUnavailable
from app.experimental.unanchored_sequence import enumerate_sequences, renewal_log_prior, infer_unanchored
from test_phase_observation_bridge import query
from test_rounded_observation import supplied


def model(h=8):
    m=supplied();m.update(horizon_s=h,cyclic_order=[0,1],latent_demand_exposure=[[1]*(h//2)]*2)
    return m


@pytest.mark.parametrize('h',[2,4,8,12])
def test_equilibrium_prior_paths_normalize_with_censoring(h):
    paths=enumerate_sequences(h,[0,1])
    for prior in PRIORS.values():
        assert sum(math.exp(renewal_log_prior(b,h,prior))/2 for _,b in paths)==pytest.approx(1)
    assert all(0<t<h for _,b in paths for t in b)
    assert any(not b for _,b in paths)


def test_initial_residual_can_be_shorter_than_complete_phase():
    p=enumerate_sequences(12,[0,1])
    assert (1,(2,6,10)) in p
    assert (1,(2,4)) not in p  # second complete phase cannot last2s
    assert (0,(4,8)) in p
    assert all(first in (0,1) for first,_ in p)


def test_no_demand_posterior_equals_prior_and_states_unknown():
    m=model();m['latent_demand_exposure']=[[0]*4]*2
    r=infer_unanchored(query(empty=True),m,origin_ms=100000)
    assert r['complete'] and r['prior_only_numerically']
    for name,prior in PRIORS.items():
        assert r['results'][name]['posterior_vs_prior_kl_nats']==pytest.approx(0,abs=1e-12)
        assert sum(r['results'][name]['transition_count_posterior'].values())==pytest.approx(1)
        for row in r['alternatives']:
            assert row['posterior'][name]==pytest.approx(math.exp(renewal_log_prior(row['boundaries_s'],8,prior))/2)
    assert r['logical_phase']['estimated_state']==r['physical_section']['estimated_state']=='UNKNOWN'
    assert r['results']['flat']['transition_count_posterior']!=r['results']['soft']['transition_count_posterior']


def test_all_camera_missing_not_silently_full_exposure():
    m=model();m['observation_windows_s']=[]
    r=infer_unanchored(query(empty=True),m,origin_ms=100000)
    assert r['complete'] and r['prior_only_numerically']
    assert r['published_logical_unknown_fraction']==1


def test_unknown_initial_phase_and_conditional_boundary_mass():
    m=model();r=infer_unanchored(query(),m,origin_ms=100000)
    assert r['complete']
    for p in r['results'].values():
        assert set(p['initial_phase_posterior'])=={'0','1'}
        assert sum(p['initial_phase_posterior'].values())==pytest.approx(1)
        assert '0' in p['transition_count_posterior'] and '1' in p['transition_count_posterior']
        for count,ordinals in p['boundary_posteriors_conditioned_on_count'].items():
            assert len(ordinals)==int(count)
            for mass in ordinals.values():assert sum(mass.values())==pytest.approx(1)


def test_nontrivial_cyclic_order_not_assumed_numeric_order():
    m=model();m.update(cyclic_order=[2,0,1],movements=['a','b','c'],
        rates_per_s=[[.2,.03,.03],[.03,.2,.03],[.03,.03,.2]],
        latent_demand_exposure=[[1]*4]*3)
    r=infer_unanchored(query(empty=True),m,origin_ms=100000)
    assert r['complete']
    for result in r['results'].values():
        zs=[s[2] for s in result['diagnostic_segments']]
        assert all(m['cyclic_order'][(m['cyclic_order'].index(a)+1)%3]==b for a,b in zip(zs,zs[1:]))


@pytest.mark.parametrize('limits,reason',[
    ({'max_paths':1},'PATH_BUDGET'),({'max_seconds':0},'RESOURCE_LIMIT'),
    ({'max_seconds':1e-12},'TIME_BUDGET'),({'max_memory_bytes':1},'MEMORY_BUDGET')])
def test_exhaustion_never_returns_partial_posterior(limits,reason):
    r=infer_unanchored(query(),model(),origin_ms=100000,**limits)
    assert not r['complete'] and r['status']=='unavailable'
    assert reason in r['reason'] and r['results']=={} and 'alternatives' not in r


def test_long_horizon_hidden_cycles_retained_or_honest_budget_failure():
    with pytest.raises(ModelUnavailable,match='PATH_BUDGET'):
        enumerate_sequences(80,[0,1],max_paths=5)


def test_no_fixed_anchor_count_inputs_and_invalid_order():
    for key in ('initial_phase','initial_phase_start_s','observed_segment_count'):
        m=model();m[key]=0
        assert 'NOT_ACCEPTED' in infer_unanchored(query(),m,origin_ms=100000)['reason']
    m=model();m['cyclic_order']=[0,0]
    assert 'ORDER_REQUIRED' in infer_unanchored(query(),m,origin_ms=100000)['reason']


def test_rename_input_immutability_and_result_prior_snapshot():
    v=query();m=model();before=copy.deepcopy((v,m))
    r=infer_unanchored(v,m,origin_ms=100000)
    assert (v,m)==before
    m['movements']=['x','y'];v['events'][0]['event']['movement']='x'
    rr=infer_unanchored(v,m,origin_ms=100000)
    assert r['results']==rr['results']
    prior_copy=copy.deepcopy(PRIORS)
    r['results']['flat']['prior']['max_s']=999
    assert PRIORS==prior_copy


def test_missing_scientific_inputs_stay_unavailable_and_no_truth_access():
    m=model();del m['latent_demand_exposure']
    r=infer_unanchored(query(),m,origin_ms=100000)
    assert r['reason']=='OBSERVATION_MODEL_INPUTS_UNKNOWN'
    source=inspect.getsource(infer_unanchored)
    assert 'open(' not in source and 'truth' not in inspect.signature(infer_unanchored).parameters


def test_witness_worker_does_not_read_truth_or_evaluate_during_inference():
    from scripts.check_unanchored_sequence import run
    source=inspect.getsource(run)
    assert 'truth.json' not in source and 'match_boundaries' not in source
