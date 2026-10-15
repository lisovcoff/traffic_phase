import copy
import math

import numpy as np
import pytest

from app.experimental.joint_track_model import PRIORS,path_loglik
from app.experimental.unanchored_sequence import enumerate_sequences,renewal_log_prior
from app.experimental.rounded_observation import rounded_components
from app.experimental.local_factor_sequence import infer_local_factors
from app.experimental.bounded_factor_sequence import VehicleFactors,infer_bounded_factors,infer_bounded_context
from test_local_factor_sequence import components,oracle
from test_context_observation import index
from test_rounded_observation import supplied


@pytest.mark.parametrize('h,k,order,span',[(2,2,[0,1],1),(8,2,[0,1],2),(12,3,[2,0,1],3),(12,2,[1,0],4)])
def test_full_posterior_and_map_match_exhaustive_oracle(h,k,order,span):
    c=components(h,k)
    if span>1:
        original=c['q'][0].sum();c['q'][0]*=0
        c['q'][0,0]=original*.4;c['q'][0,span-1]=original*.6
    r=infer_bounded_factors(c,order,max_kernel_span_cells=max(3,span))
    assert r['complete'],r.get('reason')
    assert not r['enumeration_used'] and not r['truncation_used']
    assert r['observed_max_kernel_span_cells']==span
    for name,prior in PRIORS.items():
        paths,labels,p,logZ,best=oracle(c,order,prior);a=r['results'][name]
        assert a['log_normalizer']==pytest.approx(logZ,abs=1e-11)
        assert a['diagnostic_map_log_joint']==pytest.approx(best,abs=1e-11)
        assert sum(a['transition_count_posterior'].values())==pytest.approx(1)
        for count,mass in a['transition_count_posterior'].items():
            assert mass==pytest.approx(sum(v for (_,b),v in zip(paths,p) if len(b)==int(count)),abs=1e-11)
        expected=[[sum(p[labels[:,j]==z]) for z in range(k)] for j in range(c['n'])]
        np.testing.assert_allclose(a['phase_posterior'],expected,atol=1e-11)
        for b in a['boundary_existence']:
            assert b['model_conditioned_existence_probability']==pytest.approx(
                sum(v for (_,bounds),v in zip(paths,p) if b['time_s'] in bounds),abs=1e-11)
        segments=a['diagnostic_segments'];bounds=[s[0] for s in segments[1:]]
        z=np.concatenate([np.full((b-a)//2,label) for a,b,label in segments])
        assert path_loglik(z,c)+renewal_log_prior(bounds,h,prior)-math.log(k)==pytest.approx(best,abs=1e-11)


def test_closure_factorization_matches_joint_likelihood_for_all_short_paths():
    c=components();c['q'][0,2]=c['q'][0,0]/3
    f=VehicleFactors(c,3)
    for first,b in enumerate_sequences(8,[0,1]):
        z=(first+np.searchsorted(b,np.arange(4)*2,side='right'))%2
        assert sum(f.value(j,tuple(z[max(0,j-2):j+1])) for j in range(4))==pytest.approx(path_loglik(z,c),abs=1e-12)


def test_same_current_phase_and_run_age_cannot_merge_distinct_factor_history():
    c=components();mass=c['q'][0].sum();c['q'][0]*=0
    c['q'][0,0]=mass*.4;c['q'][0,3]=mass*.6
    factors=VehicleFactors(c,4)
    # Both valid prefixes end phase0/run_age1; earlier phase0 differs.
    assert factors.value(3,(1,1,1,0))!=factors.value(3,(0,1,1,0))


@pytest.mark.parametrize('lag,span',[(2,2),(4,3),(6,4)])
def test_real_joint_pattern_components_with_delay_mixture(lag,span):
    m=supplied();m.update(horizon_s=12,latent_demand_exposure=[[1]*6]*2,
        release_delay_s=[[0,.5],[lag,.5]])
    release=lag*1000+2250
    c=rounded_components(index([(release,release+2000)]).query(0,24000),m)
    r=infer_bounded_factors(c,[0,1],max_kernel_span_cells=max(3,span))
    assert r['complete'] and r['observed_max_kernel_span_cells']==span
    for name,prior in PRIORS.items():
        _,_,_,logZ,best=oracle(c,[0,1],prior)
        assert r['results'][name]['log_normalizer']==pytest.approx(logZ)
        assert r['results'][name]['diagnostic_map_log_joint']==pytest.approx(best)


def test_local_case_equals_existing_local_dp_both_priors():
    c=components(h=12);a=infer_local_factors(c,[0,1]);b=infer_bounded_factors(c,[0,1])
    assert a['complete'] and b['complete']
    for name in PRIORS:
        for field in ('log_normalizer','diagnostic_map_log_joint'):
            assert a['results'][name][field]==pytest.approx(b['results'][name][field])
        np.testing.assert_allclose(a['results'][name]['phase_posterior'],b['results'][name]['phase_posterior'],atol=1e-12)


def test_no_threshold_on_tiny_mass_and_span_counts_holes():
    c=components(h=12);c['q'][0,4]=1e-100
    r=infer_bounded_factors(c,[0,1])
    assert r['reason']=='KERNEL_HISTORY_LIMIT_EXCEEDED' and r['results']=={}
    c['q'][0,4]=0;c['q'][0,2]=1e-100
    r=infer_bounded_factors(c,[0,1]);assert r['complete'] and r['observed_max_kernel_span_cells']==3


def test_structural_zeros_and_censored_initial_final_durations():
    c=components(h=12);c['q'][0,1]=c['q'][0,0];c['rates'][1,0]=0
    r=infer_bounded_factors(c,[0,1]);assert r['complete']
    for name,prior in PRIORS.items():
        _,_,_,logZ,best=oracle(c,[0,1],prior)
        assert r['results'][name]['log_normalizer']==pytest.approx(logZ)
        assert r['results'][name]['diagnostic_map_log_joint']==pytest.approx(best)


@pytest.mark.parametrize('limits,reason',[
    ({'max_states_per_layer':1},'LAYER_STATE_BUDGET'),({'max_total_states':1},'TOTAL_STATE_BUDGET'),
    ({'max_states_per_layer':3},'LAYER_STATE_BUDGET'),({'max_total_states':4},'TOTAL_STATE_BUDGET'),
    ({'max_memory_bytes':0},'MEMORY_BUDGET'),({'max_seconds':1e-12},'TIME_BUDGET'),
    ({'max_seconds':0},'RESOURCE_LIMIT'),({'max_kernel_span_cells':6},'RESOURCE_LIMIT')])
def test_budget_failure_returns_no_partial_posterior(limits,reason):
    r=infer_bounded_factors(components(),[0,1],**limits)
    assert not r['complete'] and r['status']=='unavailable' and r['results']=={}
    assert reason in r['reason'] and r['physical_section']['estimated_state']=='UNKNOWN'


def test_long_no_demand_prior_only_normalization_without_enumeration():
    c=components(h=64,k=3,patterns=());c['exposure']*=0
    r=infer_bounded_factors(c,[2,0,1]);assert r['complete'] and not r['enumeration_used']
    assert r['likelihood_constant_over_phase_paths']
    for result in r['results'].values():
        assert result['log_normalizer']==pytest.approx(0,abs=1e-11)
        np.testing.assert_allclose(result['phase_posterior'],np.full((32,3),1/3),atol=1e-11)
        expected=sum(int(n)*p for n,p in result['transition_count_posterior'].items())
        assert sum(b['model_conditioned_existence_probability'] for b in result['boundary_existence'])==pytest.approx(expected)


def test_input_immutability_movement_rename_and_context_failure_contract():
    c=components();c['q'][0,1]=c['q'][0,0]/2;before=copy.deepcopy(c)
    a=infer_bounded_factors(c,[0,1]);np.testing.assert_array_equal(c['q'],before['q'])
    c['movements']=['alpha','beta']
    for t in c['tracks']:t['movement']='alpha'
    b=infer_bounded_factors(c,[0,1]);assert a['results']==b['results']
    m=supplied();m['cyclic_order']=[0,1]
    r=infer_bounded_context(index(),m,context_origin_ms=0,target_range_ms=[0,8000])
    assert r['status']=='unavailable' and not r['complete'] and r['results']=={}


def test_context_entry_supports_nonlocal_kernel_without_changing_global_track():
    m=supplied();m.update(horizon_s=16,latent_demand_exposure=[[1]*8]*2,
        cyclic_order=[0,1],release_delay_s=[[0,.5],[2,.5]])
    r=infer_bounded_context(index([(6250,8250)]),m,context_origin_ms=0,target_range_ms=[6000,10000])
    assert r['complete'] and r['observed_max_kernel_span_cells']==2
    assert r['context_plan']['source_namespace']=='fixed-global-index'
    assert r['logical_phase']['estimated_state']==r['physical_section']['estimated_state']=='UNKNOWN'
