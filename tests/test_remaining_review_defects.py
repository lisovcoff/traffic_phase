"""Preregistered structural counterexamples for D4/D5/D6/D8, no real labels."""
from unittest.mock import patch
import itertools

import numpy as np
import pytest

from app.core.v9 import fit
from app.core.v9.events import periodic_baseline_from_segments
from app.core.state_contract import logical_phase_at
from app.core.v9.signal_renderer import signal_state_at


def view(pairs):
    pairs=sorted(pairs)
    return {'group_onsets_s':[v for v,g in pairs], 'group_streams':[g for v,g in pairs]}


@pytest.mark.parametrize('shift',[0.,10.,37.,80.])
def test_fusion_matches_identity_across_wrap_and_time_origin(shift):
    r=view([((99+shift)%100,['a']),((49+shift)%100,['b'])])
    e=view([((1+shift)%100,['a']),((51+shift)%100,['b'])])
    result,diag=fit._fuse_seed_views(r,e,100.)
    assert diag['status']=='available'
    expected={'a':shift%100,'b':(50+shift)%100}
    assert len(result['group_matching'])==2
    for match in result['group_matching']:
        assert match['onset_s']==pytest.approx(expected[match['shared_streams'][0]])
    assert sum(result['durations_s'])==pytest.approx(100.)


@pytest.mark.parametrize('r,e,reason',[
    ({'group_onsets_s':[0.,40.]},view([(1.,['a']),(41.,['b'])]),'MISSING_GROUP_MEMBERSHIP'),
    (view([(0.,['a']),(40.,['b'])]),view([(1.,['c']),(41.,['d'])]),'NO_SHARED_MOVEMENT_FOR_MATCH'),
    (view([(0.,['a','b']),(40.,['c','d'])]),view([(1.,['a','c']),(41.,['b','d'])]),'AMBIGUOUS_GROUP_ASSIGNMENT'),
    (view([(0.,['a']),(40.,['b'])]),view([(10.,['b']),(50.,['a'])]),'ANTIPODAL_ONSETS'),
    (view([(0.,['a']),(30.,['b']),(60.,['c'])]),view([(1.,['a']),(31.,['c']),(61.,['b'])]),'CYCLIC_ORDER_DISAGREEMENT'),
])
def test_fusion_abstains_on_unknown_identity_order_or_midpoint(r,e,reason):
    frozen=repr((r,e))
    result,diag=fit._fuse_seed_views(r,e,100.)
    assert result is None and diag['reason']==reason
    assert repr((r,e))==frozen


def test_membership_assignment_is_global_and_uses_nonempty_matches():
    # Counts [[2,1],[1,0]] have two equal assignments, even though greedy picks
    # its largest overlap. Do not manufacture identity from onset proximity.
    r=view([(0.,['a','b','c']),(40.,['d'])])
    e=view([(1.,['a','b','d']),(41.,['c'])])
    result,diag=fit._fuse_seed_views(r,e,100.)
    assert result is None
    assert diag['reason'] in {'AMBIGUOUS_GROUP_ASSIGNMENT','NO_SHARED_MOVEMENT_FOR_MATCH'}


def test_exact_quality_tie_keeps_first_candidate_not_privileged_ensemble():
    labels=np.tile(np.repeat([0,1],5),2)
    seeds=[(labels,dict(view([(0.,['a']),(5.,['b'])]),durations_s=[5.,5.])),
           (1-labels,dict(view([(2.,['a']),(7.,['b'])]),durations_s=[5.,5.]))]
    with patch.object(fit,'initial_seed_from_streams',side_effect=seeds), patch.object(fit,'_fit_quality',return_value=1.), patch.object(fit,'_fit_from_initial_labels',side_effect=RuntimeError('seed selection only')):
        result=fit.em_fit(np.zeros((20,2)),10.,2,by_stream_global={},entry_streams={})
    assert result['initialization']['source']=='robust_release_seed'
    assert any(c['source']=='release_entry_seed_ensemble' for c in result['initialization_candidates'])
    assert sum(c['selected'] for c in result['initialization_candidates'])==1


def test_joint_shared_signatures_preserve_all_phases_under_column_renaming():
    probs=np.array([[.9,.9,.01],[.9,.01,.9],[.01,.9,.9]])
    for perm in itertools.permutations(range(3)):
        result=fit._phase_support_metrics({'k':3,'probs':probs[:,list(perm)]})
        assert result['supported_phase_count']==3
        assert set(result['exclusive_stream_support_by_phase'].values())=={0}
        assert all(all(p.values()) for p in result['pairwise_signature_witness_columns'].values())
        assert 'NOT_external' in result['phase_support_semantics']


@pytest.mark.parametrize('probs,expected',[
    ([[.9,.1],[.9,.1],[.1,.9]],1),  # duplicate pair is not identified
    ([[.9,.1],[.90000001,.1]],0),   # unequal floats do not prove support
    ([[.01,.01],[.02,.02]],0),     # no active phase
    ([[.9,.9,.01],[.9,.9,.9]],2),  # conditional joint occupancy difference
])
def test_joint_support_rejects_duplicates_tiny_contrast_and_no_demand(probs,expected):
    result=fit._phase_support_metrics({'k':len(probs),'probs':np.array(probs)})
    assert result['supported_phase_count']==expected


def test_baseline_only_counts_contiguous_changes_and_retains_right_censored_onset():
    rows=[(0.,5.,0),(5.,10.,0),(10.,20.,1),(20.,30.,0)]
    baseline,centers,diag=periodic_baseline_from_segments(rows,20.,30.,return_diagnostics=True)
    assert baseline and centers[0]==pytest.approx(0.,abs=1e-12)
    assert centers[1]==pytest.approx(10.)
    assert diag['onset_counts_by_phase']=={'0':1,'1':1}
    assert diag['status']=='available'


@pytest.mark.parametrize('rows,k',[
    ([(0.,10.,0)],1),
    ([(0.,10.,0),(10.,20.,1)],2),
    ([(0.,10.,0),(15.,20.,1),(20.,30.,0)],2),
    ([(0.,10.,0),(10.,20.,1),(20.,30.,0)],3),
    ([(0.,10.,0),(5.,15.,1)],2),
])
def test_missing_or_invalid_onsets_abstain_without_raw_or_zero_fallback(rows,k):
    baseline,centers,diag=periodic_baseline_from_segments(rows,40.,30.,phase_count=k,return_diagnostics=True)
    assert baseline==[] and diag['status']=='unavailable' and diag['reason']
    result={'schedule':{'phase_names':['A','B','C'][:k],'period_s':40.,'baseline_segments':[],
                       'raw_hsmm_segments':[list(r) for r in rows]}}
    state=logical_phase_at(result,7.,mode='configured')
    assert state.estimated_state=='UNKNOWN'
    assert state.abstention_reason=='NO_TEMPORAL_COVERAGE'
    result['schedule']['stream_activity_by_phase']=[{'stream':'N->S',
        'event_probability_by_phase':{'A':.9,'B':.01}}]
    actual=signal_state_at(result,7.,mode='configured')
    assert actual['phase_name']=='UNKNOWN'
    assert all(row['state']=='UNKNOWN' for row in actual['streams'])


def test_antipodal_onsets_have_no_defined_circular_mean():
    rows=[(0.,10.,0),(10.,20.,1),(20.,30.,0),(30.,40.,1),(40.,50.,0)]
    baseline,centers,diag=periodic_baseline_from_segments(rows,40.,50.,return_diagnostics=True)
    assert not baseline and diag['reason']=='MISSING_OR_AMBIGUOUS_PHASE_ONSETS'


@pytest.mark.parametrize('rows',[[(0.,0.,0)],[(0.,float('nan'),0)],[(0.,10.,'bad')],[7],[(0.,10.,True)]])
def test_invalid_baseline_history_is_structured_unavailable(rows):
    b,c,d=periodic_baseline_from_segments(rows,40.,30.,return_diagnostics=True)
    assert b==[] and d['reason']=='INVALID_PHASE_HISTORY'


def test_refined_snapshot_preserves_seed_matching_provenance():
    labels=np.tile(np.repeat([0,1],10),3)
    info={'durations_s':[10.,10.],'group_matching':[{'release_group_index':0,'entry_group_index':1}],
          'source':'release_entry_seed_ensemble'}
    result,_=fit._fit_from_initial_labels(np.eye(2)[labels],labels,2,20.,None,1.,1,info,None,None)
    assert result['seed_info']==info


def test_real_seed_producer_retains_membership_without_changing_cluster_identity():
    from app.core.v9.primitives import initial_seed_from_streams
    streams={'a':[1.+100*i for i in range(8)],'b':[51.+100*i for i in range(8)]}
    labels,info=initial_seed_from_streams(streams,100.,2,800,1.)
    assert set(tuple(group) for group in info['group_streams'])=={('a',),('b',)}
    assert [len(group) for group in info['group_streams']]==info['group_sizes']
    assert sorted(set(labels))==[0,1]
