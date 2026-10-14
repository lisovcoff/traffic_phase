import copy
import math
import numpy as np
from scripts.event_time_prototype import infer, observations, interval_loglik, PRIORS, duration_mass


def args(events=(),windows=((0,12),)):
    return dict(events=list(events),mapping={'a':0,'b':1},order=[0,1],
                windows=windows,horizon=12,rates=[.5,.25],prior=PRIORS['uniform'])


def test_poisson_counts_exposure_and_structural_zeros():
    ev=[{'timestamp_ms':1250,'movement':'a'},{'timestamp_ms':1500,'movement':'a'}]
    c,e=observations(**{k:v for k,v in args(ev).items() if k!='prior'})
    assert c[1,0]==2
    assert interval_loglik(c,e,[.5,.25],0,4,0)==2*math.log(.5)-2
    assert interval_loglik(c,e,[.5,.25],0,4,1)==-math.inf
    e[:]=0
    assert interval_loglik(c,e,[.5,.25],0,4,0)==2*math.log(.5)


def test_gap_exposure_not_inferred_from_silence():
    a=args(windows=((0,3),(9,12)))
    c,e=observations(**{k:v for k,v in a.items() if k!='prior'})
    assert e.sum()==6
    assert interval_loglik(c,e,[.5,.25],0,12,0)==-3
    out=infer(**a)
    assert out['observed_seconds']==6
    assert out['unknown_fraction']>=.5


def test_empty_events_keep_hidden_cycles_unknown():
    out=infer(**args())
    assert out['complete'] and len(out['possible_transition_counts'])>2
    assert out['unknown_fraction']==1
    assert out['physical_state']=='UNKNOWN'
    assert out['possible_transition_counts'][0]==0
    assert any(not b['exists_in_all_paths'] for b in out['boundary_sets'])


def test_constraints_paths_and_input_immutability():
    a=args([{'timestamp_ms':1250,'movement':'a'},{'timestamp_ms':8250,'movement':'b'}])
    original=copy.deepcopy(a); out=infer(**a)
    assert a==original
    assert out['complete']
    for t,n,u,final in out['feasible_graph']:
        for e in a['events']:
            if t<=e['timestamp_ms']/1000<u:
                assert a['mapping'][e['movement']]==n%2


def test_priors_same_feasibility_different_assumptions():
    a=args(); uniform=infer(**a); a['prior']=PRIORS['nominal10']; peaked=infer(**a)
    assert uniform['boundary_sets']==peaked['boundary_sets']
    assert uniform['feasible_graph']==peaked['feasible_graph']
    assert abs(sum(duration_mass(PRIORS['nominal10']).values())-1)<1e-12


def test_budget_no_partial_full_set_claim():
    for limit in ({'max_edges':1},{'max_seconds':0},{'max_horizon':5},{'max_memory_bytes':1}):
        out=infer(**args(),**limit)
        assert not out['complete'] and out['status']=='unavailable'
        assert out['boundary_sets']==[]


def test_rounding_boundary_explicitly_unavailable():
    out=infer(**args([{'timestamp_ms':2000,'movement':'a'}]))
    assert out['reason']=='ROUNDING_CELL_STRADDLES_GRID_BOUNDARY'


def test_complete_graph_against_tiny_independent_enumeration():
    a=args([{'timestamp_ms':1250,'movement':'a'},{'timestamp_ms':6250,'movement':'b'}])
    a.update(horizon=8,windows=[[0,8]])
    out=infer(**a)
    paths=[]
    def enumerate_paths(start,n,path):
        for end in range(start+1,9):
            final=end==8
            if not final and end-start<2:
                continue
            if any(start<=e['timestamp_ms']/1000<end and a['mapping'][e['movement']]!=n%2 for e in a['events']):
                continue
            edge=(start,n,end,final)
            if final: paths.append(path+[edge])
            else: enumerate_paths(end,n+1,path+[edge])
    enumerate_paths(0,0,[])
    assert {tuple(e) for e in out['feasible_graph']}=={e for path in paths for e in path}
    assert out['possible_transition_counts']==sorted({len(path)-1 for path in paths})


def test_right_censoring_survival_not_duration_mass():
    a=args();a.update(horizon=1,windows=[[0,1]])
    out=infer(**a)
    assert out['diagnostic_segments']==[[0,1,0]]
    assert out['diagnostic_score']==-.5  # P(duration >=1)=1, no termination observation


def test_missing_window_event_rejected():
    import pytest
    with pytest.raises(ValueError,match='outside supplied'):
        infer(**args([{'timestamp_ms':5250,'movement':'a'}],windows=((0,3),(9,12))))
