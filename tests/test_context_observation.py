import copy
import math

import numpy as np
import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.joint_track_model import ModelUnavailable,path_loglik,observation_components
from app.experimental.rounded_observation import rounded_components
from app.experimental.phase_observation_bridge import prepare_joint_observation
from app.experimental.context_observation import prepare_context_observation
from test_rounded_observation import supplied


def index(patterns=(),origin=0):
    events=[]
    for i,(r,c) in enumerate(patterns):
        for t,kind,method in ((r,'RELEASE','test_restart'),(c,'CROSSING_PROXY','test_zone')):
            if t is not None:events.append(TemporalEvent(origin+t,kind,'straight',i,method,.5,'MEDIUM',None,
                {'source':'test','track_fingerprint':str(i),'eligible_proxy':True}))
    return build_local_evidence(events,source_namespace='fixed-global-index')


def censored():
    m=supplied();m['query_delivery_mode']='censored_reported_timestamps'
    return m


def test_empty_short_query_uses_rounded_retention_not_undelivered_six_seconds():
    m=censored();m['crossing_detection_probability']=0
    c=rounded_components(index().query(0,2000),m)
    # Centres0..1999ms retain true[0,1999.5ms) after latent/camera intersection.
    assert path_loglik([0]*4,c)==pytest.approx(-(.2+.03)*1.9995)
    assert c['observation_domain']['retained_true_mark_interval_s']==[-.0005,1.9995]
    strict=supplied();strict['crossing_detection_probability']=0
    assert prepare_joint_observation(index().query(0,2000),strict,origin_ms=0)['reason']=='QUERY_DOMAIN_INCOMPLETE'


def test_release_inside_crossing_outside_is_query_censoring_not_nondetection():
    m=censored();m['crossing_detection_probability']=1
    i=index([(6250,8250)])
    c=rounded_components(i.query(0,8000),m)
    assert len(c['tracks'])==1 and c['tracks'][0]['crossing_ms'] is None
    assert c['q'][0,3]==pytest.approx(.001/2)
    assert math.isfinite(path_loglik([0]*4,c))
    assert prepare_joint_observation(i.query(0,8000),supplied(),origin_ms=0)['reason']=='QUERY_DOMAIN_INCOMPLETE'


def test_all_retained_joint_patterns_normalize_with_query_selection():
    m=censored();m.update(horizon_s=4,latent_demand_exposure=[[1]*2]*2,
        timestamp_resolution_ms=1000,timestamp_rounding_origin_ms=500,
        transit_delay_s=[[1,1.]],release_detection_probability=.5,crossing_detection_probability=.25)
    # Retain centres.5/1.5/2.5s only, independent of true camera[0,20).
    patterns=[(r,None) for r in (500,1500,2500)]
    patterns += [(None,c) for c in (1500,2500)]
    patterns += [(r,r+1000) for r in (500,1500)]
    c=rounded_components(index(patterns).query(0,3000),m)
    np.testing.assert_allclose(c['q'].sum(axis=0),c['detected_probability'])
    assert c['detected_probability'].tolist()==pytest.approx([.625,.25])


def test_fractional_query_rounding_clock_and_empty_centre_set():
    m=censored();m['timestamp_rounding_origin_ms']=.25
    c=rounded_components(index().query(0,2),m)
    assert c['observation_domain']['retained_clock_centres_ms']==[.25,1.25]
    assert c['observation_domain']['retained_true_mark_interval_s']==[-.00025,.00175]
    c=rounded_components(index().query(.3,.4),m)
    assert c['observation_domain']['retained_clock_centres_ms']==[]
    assert np.all(c['detected_probability']==0)


def test_context_removes_precontext_vehicle_and_keeps_valid_later_event():
    #250ms release+2s delay needs u=-1.75;2250ms release needs u=.25.
    m=supplied();m.update(release_delay_s=[[2,1.]],crossing_detection_probability=0)
    r=prepare_context_observation(index([(250,None),(2250,None)]),m,
        context_origin_ms=0,target_range_ms=[3000,5000])
    assert r['status']=='ready_for_supplied_context_model_only'
    assert [t['release_ms'] for t in r['components']['tracks']]==[2250]
    p=r['context_plan'];assert p['retained_true_mark_range_ms'][0]>=2000
    assert p['retained_true_mark_range_ms'][1]<=8000
    assert p['context_phase_history_required']
    assert r['logical_phase']['estimated_state']==r['physical_section']['estimated_state']=='UNKNOWN'


def test_absolute_context_and_target_keep_global_track_identity_and_provenance():
    m=supplied();m.update(horizon_s=16,latent_demand_exposure=[[1]*8]*2)
    i=index([(6250,8250)],origin=100000);before=copy.deepcopy(m)
    a=prepare_context_observation(i,m,context_origin_ms=100000,target_range_ms=[104000,112000])
    b=prepare_context_observation(i,m,context_origin_ms=100000,target_range_ms=[106000,110000])
    assert a['status']==b['status']=='ready_for_supplied_context_model_only'
    assert a['evidence_view']['events']==b['evidence_view']['events']
    original=i.query(100000,120000)['events']
    assert a['evidence_view']['events']==original
    assert m==before
    assert a['context_plan']['target_range_ms']!=b['context_plan']['target_range_ms']
    shifted=prepare_context_observation(i,m,context_origin_ms=102000,target_range_ms=[106000,110000])
    assert shifted['status']=='ready_for_supplied_context_model_only'
    assert a['evidence_view']['events']==shifted['evidence_view']['events']


def test_no_camera_or_no_demand_not_a_phase_observation():
    for missing in ('camera','demand'):
        m=supplied()
        if missing=='camera':m['observation_windows_s']=[]
        else:m['latent_demand_exposure']=[[0]*4]*2
        r=prepare_context_observation(index(),m,context_origin_ms=0,target_range_ms=[3000,5000])
        assert r['status']=='ready_for_supplied_context_model_only'
        assert path_loglik([0]*4,r['components'])==path_loglik([1]*4,r['components'])==0
        assert r['logical_phase']['estimated_state']=='UNKNOWN'


@pytest.mark.parametrize('change,reason',[
    ({'release_delay_s':None},'DELAY_MASS'),({'release_delay_s':[[-1,1.]]},'INVALID_DELAY'),
    ({'release_delay_s':[[20,1.]]},'NO_SAFE'),({'timestamp_resolution_ms':None},'ROUNDING_CLOCK'),
    ({'clock_model':'legacy_finite_clock'},'ROUNDED_CLOCK')])
def test_unknown_or_unsafe_context_parameters_abstain(change,reason):
    m=supplied();m.update(change)
    r=prepare_context_observation(index(),m,context_origin_ms=0,target_range_ms=[3000,5000])
    assert r['status']=='unavailable' and reason in r['reason']


def test_target_edges_and_event_budget_never_fallback():
    m=supplied();i=index([(6250,None)])
    r=prepare_context_observation(i,m,context_origin_ms=0,target_range_ms=[0,8000])
    assert r['reason']=='TARGET_OUTSIDE_SAFE_CONTEXT_INTERIOR' and r['components'] is None
    r=prepare_context_observation(i,m,context_origin_ms=0,target_range_ms=[3000,5000],max_events=0)
    assert r['status']=='unavailable' and r['components'] is None and 'limit' in r['reason'].lower()


def test_explicit_unsupported_mode_not_silently_ignored():
    m=censored();m['clock_model']='legacy_finite_clock'
    assert prepare_joint_observation(index().query(0,20000),m,origin_ms=0)['reason']=='UNSUPPORTED_QUERY_DELIVERY_MODE_FOR_CLOCK'
    with pytest.raises(ModelUnavailable,match='UNSUPPORTED_QUERY_DELIVERY_MODE_FOR_CLOCK'):
        observation_components(index().query(0,20000),m)
    m=censored();m['query_delivery_mode']='unknown'
    with pytest.raises(ModelUnavailable,match='UNSUPPORTED_QUERY_DELIVERY_MODE'):
        rounded_components(index().query(0,20000),m)


def test_movement_rename_preserves_context_likelihood():
    m=supplied();a=prepare_context_observation(index([(4250,None)]),m,
        context_origin_ms=0,target_range_ms=[3000,5000])
    m['movements']=['alpha','beta']
    e=TemporalEvent(4250,'RELEASE','alpha',0,'test_restart',.5,'MEDIUM',None,
        {'source':'test','track_fingerprint':'0'})
    renamed=build_local_evidence([e],source_namespace='fixed-global-index')
    b=prepare_context_observation(renamed,m,context_origin_ms=0,target_range_ms=[3000,5000])
    assert b['status']=='ready_for_supplied_context_model_only'
    assert path_loglik([0]*4,a['components'])==path_loglik([0]*4,b['components'])


def test_extreme_finite_clock_is_structured_unavailable_not_crash():
    m=supplied();m.update(timestamp_resolution_ms=1e-308,timestamp_rounding_origin_ms=1e308)
    r=prepare_context_observation(index(),m,context_origin_ms=0,target_range_ms=[3000,5000])
    assert r['reason']=='CONTEXT_DOMAIN_NUMERIC_LIMIT'
