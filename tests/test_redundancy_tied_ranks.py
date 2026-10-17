"""Fixed structural examples; no phase truth, fitting or threshold selection."""
import itertools

import numpy as np
import pytest

from app.core.v9 import fit
from app.core.v9.decoder import _segments_from_labels
from app.core.v9.primitives import fit_bernoulli_templates, _pointwise_loglik


def independent_average_rank(values):
    # Count-based oracle independent of scipy and sort implementation/order.
    return np.array([sum(w<v for w in values)+(sum(w==v for w in values)+1)/2
                     for v in values],dtype=float)


@pytest.mark.parametrize('a,b',[
    ([1.,1.,0.],[1.,0.,1.]),
    ([0.,1.,1.],[0.,0.,1.]),
    ([2.,4.,6.,8.],[8.,2.,6.,4.]),
    ([0.,1.,1.+1e-13],[1.,0.,2.]),
    ([.01,.01,.9,.9,.5],[.9,.5,.01,.9,.01]),
])
def test_rank_matches_independent_average_rank_oracle(a,b):
    a,b=np.array(a),np.array(b)
    a0,b0=a.copy(),b.copy()
    expected=float(np.corrcoef(independent_average_rank(a),independent_average_rank(b))[0,1])
    assert fit._rank_correlation(a,b)==pytest.approx(expected,abs=1e-12)
    assert np.array_equal(a,a0) and np.array_equal(b,b0)
    if len(np.unique(a))==len(a) and len(np.unique(b))==len(b):
        old=np.corrcoef(np.argsort(np.argsort(a)),np.argsort(np.argsort(b)))[0,1]
        assert fit._rank_correlation(a,b)==pytest.approx(old,abs=1e-12)


@pytest.mark.parametrize('a,b',[( [],[] ),([1.],[2.]),([1.,1.,1.],[0.,1.,2.]),([0.,1.],[1.])])
def test_small_constant_or_incompatible_vectors_keep_zero_convention(a,b):
    assert fit._rank_correlation(np.array(a),np.array(b))==0.


def test_exact_ties_are_invariant_under_all_six_permutations():
    a,b=np.array([1.,1.,0.]),np.array([1.,0.,1.])
    for perm in itertools.permutations(range(3)):
        p=list(perm)
        assert fit._rank_correlation(a[p],b[p])==pytest.approx(-.5,abs=1e-12)


def test_full_redundancy_features_and_decision_under_all_120_column_permutations():
    labels=np.tile(np.repeat(np.arange(3),[40,40,80]),3)
    counts=np.array([[1,1,2,2,0],[1,2,1,2,0],[0,0,0,0,4]])
    x=((np.arange(len(labels))%5)[:,None]<counts[labels]).astype(float)
    def model(z,k):
        p=fit_bernoulli_templates(x,z,k)
        return dict(k=k,labels=z,probs=p,segments=_segments_from_labels(z),
                    pointwise_loglik=_pointwise_loglik(x,p,z))
    f3,f2=model(labels,3),model((labels==2).astype(int),2)
    original=fit.evaluate_phase_redundancy(f3,f2,x,160.)
    expected_pairs={tuple(p['pair']):p for p in original['pairs']}
    for perm in itertools.permutations(range(5)):
        p=list(perm)
        actual=fit.evaluate_phase_redundancy({**f3,'probs':f3['probs'][:,p]},
            {**f2,'probs':f2['probs'][:,p]},x[:,p],160.)
        assert actual['detected']==original['detected']
        assert actual['candidate_pair']==original['candidate_pair']
        assert actual['supported_phase_count']==original['supported_phase_count']==3
        for row in actual['pairs']:
            expected=expected_pairs[tuple(row['pair'])]
            for key in ('rank_correlation','pair_affinity','template_overlap','boundary_exchange_ratio',
                        'boundary_strength_ratio','merge_loss_per_cycle'):
                assert row[key]==pytest.approx(expected[key],abs=1e-12)
