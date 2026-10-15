import copy
import math

import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.joint_track_model import ModelUnavailable,observation_components,path_loglik
from app.experimental.rounded_observation import rounded_components
from app.experimental.phase_observation_bridge import prepare_joint_observation
from scripts.check_query_observation_domain import inputs,probe
from test_rounded_observation import supplied


def empty(end,start=0):
    return build_local_evidence([],source_namespace='test').query(start,end)


def test_review_pair_and_empty_query_rejected_before_likelihood():
    r=probe()
    assert r['truncated_pair']['reason']=='QUERY_DOMAIN_INCOMPLETE'
    assert r['complete_pair']['status']=='ready_for_declared_model_only'
    assert r['empty_short_query']['reason']=='QUERY_DOMAIN_INCOMPLETE'
    assert r['empty_short_query']['log_likelihood'] is None


@pytest.mark.parametrize('backend',['legacy_finite_clock','continuous_latent_rounded_marks'])
def test_both_component_entry_points_guard_missing_marks(backend):
    m=supplied();m['clock_model']=backend
    fn=rounded_components if backend=='continuous_latent_rounded_marks' else observation_components
    with pytest.raises(ModelUnavailable,match='QUERY_DOMAIN_INCOMPLETE'):fn(empty(2000),m)


def test_rounded_right_edge_requires_last_reported_clock_center():
    m=supplied();m.update(crossing_detection_probability=0,observation_windows_s=[[0,8]])
    assert prepare_joint_observation(empty(8000),m,origin_ms=0)['reason']=='QUERY_DOMAIN_INCOMPLETE'
    r=prepare_joint_observation(empty(8001),m,origin_ms=0)
    assert r['status']=='ready_for_declared_model_only'
    assert r['components']['observation_domain']['required_channel_ranges_ms'][0]['last_reported_ms']==8000


def test_rounded_selection_not_true_time_intersection():
    m=supplied();m.update(crossing_detection_probability=0,
        observation_windows_s=[[.00025,.00125]],timestamp_rounding_origin_ms=0)
    # true times start.25ms; centres0ms and1ms both have positive support.
    r=prepare_joint_observation(empty(2,start=1),m,origin_ms=0)
    assert r['reason']=='QUERY_DOMAIN_INCOMPLETE'
    assert r['observation_domain']['required_channel_ranges_ms'][0]['first_reported_ms']==0
    assert prepare_joint_observation(empty(2),m,origin_ms=0)['status']=='ready_for_declared_model_only'


def test_absolute_query_domain_translated_with_events_and_inputs_not_mutated():
    m=supplied();v=empty(120000,start=100000);before=copy.deepcopy((v,m))
    r=prepare_joint_observation(v,m,origin_ms=100000)
    assert r['status']=='ready_for_declared_model_only'
    assert r['components']['observation_domain']['query_range_ms']==[0,20000]
    assert (v,m)==before


def test_delayed_crossing_support_and_camera_censoring_are_distinct():
    _,m=inputs()
    m['clock_model']='continuous_latent_rounded_marks';m.update(timestamp_resolution_ms=1,
        timestamp_rounding_origin_ms=0,timestamp_resolution_source='test clock')
    assert prepare_joint_observation(empty(8001),m,origin_ms=0)['reason']=='QUERY_DOMAIN_INCOMPLETE'
    assert prepare_joint_observation(empty(10001),m,origin_ms=0)['status']=='ready_for_declared_model_only'
    m['observation_windows_s']=[[0,8]]
    assert prepare_joint_observation(empty(8001),m,origin_ms=0)['status']=='ready_for_declared_model_only'


def test_irrelevant_camera_tail_and_disabled_channels_need_no_extra_query():
    m=supplied();m.update(observation_windows_s=[[0,1000]],crossing_detection_probability=0)
    r=prepare_joint_observation(empty(8001),m,origin_ms=0)
    assert r['status']=='ready_for_declared_model_only'
    assert r['components']['observation_domain']['upstream_event_delivery'].startswith('ASSUMED')


def test_missing_invalid_range_or_inconsistent_event_rejected():
    m=supplied();v=empty(20000)
    for bad in (None,[float('nan'),20000],[0,0]):
        v['range_ms']=bad
        assert prepare_joint_observation(v,m,origin_ms=0)['reason']=='QUERY_TIMESTAMP_DOMAIN_REQUIRED'
    index,_=inputs();v=index.query(0,20000);v['events'][0]['event']['timestamp_ms']=30000
    assert prepare_joint_observation(v,m,origin_ms=0)['reason']=='EVENT_OUTSIDE_QUERY_DOMAIN'


def test_left_population_censoring_remains_explicit_not_fixed_by_wider_query():
    m=supplied();m.update(release_method='test',release_delay_s=[[2,1.]],crossing_detection_probability=0)
    e=TemporalEvent(250,'RELEASE','straight',1,'test',.5,'MEDIUM',None,{'source':'test','track_fingerprint':'one'})
    v=build_local_evidence([e],source_namespace='test').query(0,20000)
    r=prepare_joint_observation(v,m,origin_ms=0)
    assert r['reason']=='TRACK_PATTERN_UNSUPPORTED_BY_DELAY_DETECTION_MODEL'


@pytest.mark.parametrize('rounded',[False,True])
def test_complete_contexts_preserve_closed_form_joint_likelihood(rounded):
    index,m=inputs()
    if rounded:
        m.update(clock_model='continuous_latent_rounded_marks',timestamp_resolution_ms=1,
            timestamp_rounding_origin_ms=0,timestamp_resolution_source='test clock')
    a=prepare_joint_observation(index.query(0,20000),m,origin_ms=0)['components']
    b=prepare_joint_observation(index.query(0,40000),m,origin_ms=0)['components']
    expected=-8*(.2+.03)+math.log(.2*(.001 if rounded else 2))
    assert path_loglik([0]*4,a)==pytest.approx(expected)
    assert path_loglik([0]*4,b)==pytest.approx(expected)
