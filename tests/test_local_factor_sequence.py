import copy
import math

import numpy as np
import pytest

from app.experimental.joint_track_model import PRIORS,path_loglik
from app.experimental.rounded_observation import rounded_components
from app.experimental.unanchored_sequence import enumerate_sequences,renewal_log_prior
from app.experimental.local_factor_sequence import infer_local_factors,infer_local_context,local_emissions
from test_context_observation import index,censored


def components(h=8,k=2,patterns=((1250,None),(6250,None))):
    m=censored();m.update(horizon_s=h,latent_demand_exposure=[[1]*(h//2)]*k,
        movements=[f'm{i}' for i in range(k)],rates_per_s=[[.2 if i==j else .03 for j in range(k)] for i in range(k)])
    v=index(patterns).query(0,h*1000)
    for row in v['events']:row['event']['movement']='m0'
    return rounded_components(v,m)


def oracle(c,order,prior):
    n=c['n'];h=n*2;paths=enumerate_sequences(h,order)
    scores=[];labels=[]
    for first,b in paths:
        z=np.asarray(order)[(order.index(first)+np.searchsorted(b,np.arange(n)*2,side='right'))%len(order)]
        labels.append(z);scores.append(path_loglik(z,c)+renewal_log_prior(b,h,prior)-math.log(len(order)))
    logZ=float(np.logaddexp.reduce(scores));p=np.exp(np.array(scores)-logZ)
    return paths,np.array(labels),p,logZ,max(scores)


@pytest.mark.parametrize('h,k,order',[(2,2,[0,1]),(8,2,[0,1]),(12,3,[2,0,1])])
def test_messages_and_censored_map_equal_complete_oracle(h,k,order):
    c=components(h,k);r=infer_local_factors(c,order)
    assert r['complete'] and not r['enumeration_used'] and not r['truncation_used']
    for name,prior in PRIORS.items():
        paths,labels,p,logZ,best=oracle(c,order,prior);actual=r['results'][name]
        assert actual['log_normalizer']==pytest.approx(logZ,abs=1e-11)
        assert actual['diagnostic_map_log_joint']==pytest.approx(best,abs=1e-11)
        for count,mass in actual['transition_count_posterior'].items():
            assert mass==pytest.approx(sum(v for (_,b),v in zip(paths,p) if len(b)==int(count)),abs=1e-11)
        expected=[[sum(p[labels[:,j]==z]) for z in range(k)] for j in range(c['n'])]
        np.testing.assert_allclose(actual['phase_posterior'],expected,atol=1e-11)
        for b in actual['boundary_existence']:
            expected=sum(v for (_,bounds),v in zip(paths,p) if b['time_s'] in bounds)
            assert b['model_conditioned_existence_probability']==pytest.approx(expected,abs=1e-11)
        segments=actual['diagnostic_segments'];bounds=[s[0] for s in segments[1:]]
        zs=np.concatenate([np.full((b-a)//2,z) for a,b,z in segments])
        score=path_loglik(zs,c)+renewal_log_prior(bounds,h,prior)-math.log(k)
        assert score==pytest.approx(best,abs=1e-11)


def test_factorization_exact_for_each_small_path():
    c=components();e=local_emissions(c)
    for first,bounds in enumerate_sequences(8,[0,1]):
        z=(first+np.searchsorted(bounds,np.arange(4)*2,side='right'))%2
        assert sum(e[j,label] for j,label in enumerate(z))==pytest.approx(path_loglik(z,c),abs=1e-12)


def test_nonlocal_and_even_tiny_second_support_reject_without_fallback():
    c=components();c['q'][0,1]=1e-100
    r=infer_local_factors(c,[0,1])
    assert r['status']=='unavailable' and r['results']=={}
    assert r['reason']=='NONLOCAL_TRACK_KERNEL_REQUIRES_EXPANDED_STATE'
    assert r['physical_section']['estimated_state']=='UNKNOWN'


def test_long64s_normalization_without_millions_of_paths():
    c=components(h=64,k=3,patterns=());c['exposure']*=0
    r=infer_local_factors(c,[2,0,1])
    assert r['complete'] and not r['enumeration_used']
    assert r['likelihood_constant_over_phase_paths']
    assert r['declared_array_allowance_bytes']<32*1024*1024
    for result in r['results'].values():
        assert result['log_normalizer']==pytest.approx(0,abs=1e-12)
        assert sum(result['transition_count_posterior'].values())==pytest.approx(1)
        assert max(int(c) for c in result['transition_count_posterior'])>4
        expected=sum(int(n)*p for n,p in result['transition_count_posterior'].items())
        existence=sum(b['model_conditioned_existence_probability'] for b in result['boundary_existence'])
        assert existence==pytest.approx(expected)
        np.testing.assert_allclose(result['phase_posterior'],np.full((32,3),1/3),atol=1e-12)
    assert r['logical_phase']['estimated_state']=='UNKNOWN'


def test_structural_zero_emissions_do_not_break_map_censoring():
    c=components();c['rates'][1,0]=0
    r=infer_local_factors(c,[0,1]);assert r['complete']
    for name,prior in PRIORS.items():
        _,_,_,logZ,best=oracle(c,[0,1],prior)
        assert r['results'][name]['log_normalizer']==pytest.approx(logZ)
        assert r['results'][name]['diagnostic_map_log_joint']==pytest.approx(best)


@pytest.mark.parametrize('limits', [{'max_seconds':0},{'max_seconds':1e-12},{'max_memory_bytes':0}])
def test_budget_failure_is_unavailable_no_partial_marginals(limits):
    r=infer_local_factors(components(),[0,1],**limits)
    assert not r['complete'] and r['results']=={}
    assert 'BUDGET' in r['reason'] or r['reason']=='INVALID_OR_EXHAUSTED_RESOURCE_LIMIT'


def test_context_entry_and_input_immutability():
    m=censored();m['cyclic_order']=[0,1];before=copy.deepcopy(m)
    r=infer_local_context(index([(4250,None)]),m,context_origin_ms=0,target_range_ms=[3000,5000])
    assert r['complete'] and r['context_plan']['target_range_ms']==[3000,5000]
    assert m==before and r['logical_phase']['estimated_state']=='UNKNOWN'


def test_no_demand_map_marginalizes_final_duration_not_single_remaining_state():
    c=components(patterns=());c['exposure']*=0
    r=infer_local_factors(c,[0,1])
    for name,prior in PRIORS.items():
        _,_,_,_,best=oracle(c,[0,1],prior)
        assert r['results'][name]['diagnostic_map_log_joint']==pytest.approx(best)
