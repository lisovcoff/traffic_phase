from dataclasses import asdict
import numpy as np
import pytest
from app.core.v9 import fit
from app.core.v9.primitives import fit_bernoulli_templates, _pointwise_loglik
from app.core.v9.decoder import _segments_from_labels


def protected_four(names=("N->S","S->N","E->W","W->E")):
    labels=np.tile(np.repeat(np.arange(4),20),6)
    x=np.eye(4,dtype=np.float32)[labels]
    streams={name:np.flatnonzero(x[:,i]).tolist() for i,name in enumerate(names)}
    return x,streams


def fake_fit(x,period,k,**kwargs):
    labels=np.arange(len(x))%k
    probs=np.eye(k,x.shape[1])*.9+.01
    return {"k":k,"score":-100.,"probs":np.eye(k,x.shape[1])*.9+.01,
            "pointwise_loglik":_pointwise_loglik(x,probs,labels),
            "labels":labels,"segments":[(0.,float(len(x)),0)]}


def test_informative_k4_and_bijective_renaming_recover_without_topology():
    outputs=[]
    for names in (("N->S","S->N","E->W","W->E"),("zeta","alpha","r3","r4")):
        x,streams=protected_four(names)
        search=fit.discover_phase_count(x,streams,80.,kmin=2,kmax=4,max_candidates=3,max_seconds=30.)
        outputs.append(search[0])
        assert 4 in search[2]
        assert search.diagnostics['search_status']=='complete'
        assert all(not c['topology_cap_applied'] for c in search[1])
    assert outputs==[4,4]


def test_explicit_k5_to_8_considered_without_high_k_fitting(monkeypatch):
    called=[]
    def cheap(x,period,k,**kwargs):
        called.append(k);return fake_fit(x,period,k,**kwargs)
    monkeypatch.setattr(fit,'em_fit',cheap)
    search=fit.discover_phase_count(np.ones((16,4)),dict.fromkeys(['N->S','S->N','E->W','W->E'],[1,2]),80.,
                                    kmin=5,kmax=8,max_candidates=4)
    assert called==[5,6,7,8]
    assert [r['k'] for r in search.diagnostics['candidate_ledger']]==called
    assert all(r['status']=='evaluated' for r in search.diagnostics['candidate_ledger'])


def test_candidate_budget_retains_skipped_alternatives(monkeypatch):
    monkeypatch.setattr(fit,'em_fit',fake_fit)
    search=fit.discover_phase_count(np.ones((16,4)),{'a':[1,2]},80.,max_candidates=1)
    assert len(search[1])==1
    assert search.diagnostics['ambiguity']=='PARTIAL_SEARCH'
    assert search.diagnostics['search_status']=='partial_or_unavailable'
    assert [r['reason'] for r in search.diagnostics['candidate_ledger'][1:]]==['CANDIDATE_BUDGET_EXHAUSTED']*4
    assert search.diagnostics['score_margin'] is None


def test_zero_time_budget_never_starts_fit(monkeypatch):
    monkeypatch.setattr(fit,'em_fit',lambda *a,**k:pytest.fail('outside budget'))
    search=fit.discover_phase_count(np.ones((16,4)),{'a':[1]},80.,max_seconds=0)
    assert search[0] is None
    assert all(r['reason']=='TIME_BUDGET_EXHAUSTED' for r in search.diagnostics['candidate_ledger'])


def test_timeout_is_partial_search_not_optimality(monkeypatch):
    def timed(*a,**kw):raise TimeoutError('independent worker timeout')
    monkeypatch.setattr(fit,'em_fit',timed)
    search=fit.discover_phase_count(np.ones((16,4)),{'a':[1]},80.)
    assert search[0] is None
    assert all(r['status']=='timeout' for r in search.diagnostics['candidate_ledger'])
    assert search.diagnostics['search_status']=='partial_or_unavailable'


def test_no_demand_abstains_and_sparse_support_is_not_confidence(monkeypatch):
    monkeypatch.setattr(fit,'em_fit',fake_fit)
    empty=fit.discover_phase_count(np.zeros((16,4)),{},80.)
    assert empty[0] is None and not empty[1]
    sparse=fit.discover_phase_count(np.zeros((16,4)),{'a':[1]},80.,kmax=2)
    assert sparse.diagnostics['evidence_status']=='UNSUPPORTED_PHASES_OR_NO_EVENTS'
    assert sparse.diagnostics['ambiguity']=='UNSUPPORTED_PHASES'
    assert 'NOT_confidence' in sparse.diagnostics['score_margin_semantics']


def test_supported_subphase_and_shared_movement_are_not_redundant():
    labels=np.tile(np.repeat(np.arange(3),20),4)
    x=np.column_stack([np.eye(3)[labels],np.ones(len(labels))*.7]).astype(np.float32)
    probs=fit_bernoulli_templates(x,labels,3)
    merged=np.where(labels==2,1,0)
    def view(z,k):
        p=fit_bernoulli_templates(x,z,k)
        return {'k':k,'probs':p,'labels':z,'segments':_segments_from_labels(z,1.),
                'pointwise_loglik':_pointwise_loglik(x,p,z),'score':_pointwise_loglik(x,p,z)}
    assert probs.shape==(3,4)
    result=fit.evaluate_phase_redundancy(view(labels,3),view(merged,2),x,60.,
        {str(i):np.flatnonzero(x[:,i]).tolist() for i in range(4)},dt=1.)
    assert result['supported_phase_count']==3
    assert result['detected'] is False


def test_default_range_and_public_config_are_preserved():
    assert asdict(fit.PhaseSearchConfig())=={'kmin':2,'kmax':6,'max_candidates':5,'max_seconds':60.}
