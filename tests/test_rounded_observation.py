import copy
import math

import numpy as np
import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.joint_track_model import ModelUnavailable, path_loglik
from app.experimental.phase_observation_bridge import prepare_joint_observation
from app.experimental.rounded_observation import rounded_components
from test_phase_observation_bridge import model, query


def supplied():
    m=model()
    m.update(clock_model='continuous_latent_rounded_marks',
        timestamp_resolution_ms=1, timestamp_rounding_origin_ms=0,
        timestamp_resolution_source='test rounding specification')
    return m


def test_arbitrary_millisecond_and_closed_form_count_likelihood():
    v=query();v['events'][0]['event']['timestamp_ms']=100137
    m=supplied();m['crossing_detection_probability']=0
    result=prepare_joint_observation(v,m,origin_ms=100000)
    assert result['status']=='ready_for_declared_model_only'
    c=result['components']
    assert c['q'][0,0]==pytest.approx(.001/2)
    assert path_loglik([0]*4,c)==pytest.approx(-8*(.2+.03)+math.log(.2*.001))
    assert result['physical_section']['estimated_state']=='UNKNOWN'


def test_all_rounded_joint_patterns_normalize_to_detected_exposure():
    m=supplied();m.update(horizon_s=4, latent_demand_exposure=[[1]*2]*2,
        timestamp_resolution_ms=1000, timestamp_rounding_origin_ms=500, release_detection_probability=.5,
        crossing_detection_probability=.25, transit_delay_s=[[1,1.]])
    events=[]
    patterns=[]
    for r in (500,1500,2500,3500): patterns.extend(((r,None),(None,r+1000),(r,r+1000)))
    for i,(r,c) in enumerate(patterns):
        for ts,kind,method in ((r,'RELEASE','test_restart'),(c,'CROSSING_PROXY','test_zone')):
            if ts is not None:
                events.append(TemporalEvent(ts,kind,'straight',i,method,.5,'MEDIUM',None,
                    {'source':'test','track_fingerprint':str(i),'eligible_proxy':True}))
    v=build_local_evidence(events,source_namespace='test').query(0,8000)
    comp=rounded_components(v,m)
    np.testing.assert_allclose(comp['q'].sum(axis=0),comp['detected_probability'])
    np.testing.assert_allclose(comp['detected_probability'],.625)


def test_pair_uses_one_latent_vehicle_and_same_redundant_information():
    m=supplied();m['transit_delay_s']=[[2,1.]]
    a=prepare_joint_observation(query(),m,origin_ms=100000)['components']
    b=prepare_joint_observation(query(pair=True),m,origin_ms=100000)['components']
    assert len(b['tracks'])==1
    assert path_loglik([0,1,0,1],a)==pytest.approx(path_loglik([0,1,0,1],b))


def test_fractional_delay_and_partial_window_exposure_exact():
    m=supplied();m.update(release_delay_s=[[.125,1.]],
        observation_windows_s=[[.375,1.375]],crossing_detection_probability=0)
    v=query(empty=True,offset=0)
    c=rounded_components(v,m)
    assert c['detected_probability'][0]==pytest.approx(.5)
    assert sum(c['detected_probability'][1:])==0
    assert path_loglik([0]*4,c)==pytest.approx(-(.2+.03)*1)


def test_rounding_cell_crossing_window_edge_is_integrated_not_discarded():
    m=supplied();m.update(observation_windows_s=[[.25025,1]],crossing_detection_probability=0)
    r=prepare_joint_observation(query(),m,origin_ms=100000)
    assert r['status']=='ready_for_declared_model_only'
    assert r['components']['q'][0,0]==pytest.approx(.00025/2)


def test_camera_gap_is_censoring_not_inferred_from_silence():
    m=supplied();m['observation_windows_s']=[[2,4]]
    assert prepare_joint_observation(query(),m,origin_ms=100000)['reason']=='OBSERVATION_OUTSIDE_SUPPLIED_WINDOWS'
    empty=query(empty=True,offset=0)
    m['observation_windows_s']=[]
    c=rounded_components(empty,m)
    assert path_loglik([0]*4,c)==path_loglik([1]*4,c)==0


def test_unknown_resolution_not_taken_from_heuristic_radius():
    m=supplied();del m['timestamp_resolution_ms']
    assert prepare_joint_observation(query(),m,origin_ms=100000)['reason']=='SUPPLIED_TIMESTAMP_RESOLUTION_REQUIRED'


def test_rounding_partition_requires_explicit_origin_and_consistent_marks():
    m=supplied();del m['timestamp_rounding_origin_ms']
    assert prepare_joint_observation(query(),m,origin_ms=100000)['reason']=='SUPPLIED_ROUNDING_CLOCK_ORIGIN_REQUIRED'
    m=supplied();m['timestamp_resolution_ms']=1000
    assert prepare_joint_observation(query(),m,origin_ms=100000)['reason']=='TIMESTAMP_NOT_ON_SUPPLIED_ROUNDING_CLOCK'


def test_structural_zero_and_offphase_positive_rate():
    m=supplied();v=query(offset=0)
    c=rounded_components(v,m)
    assert math.isfinite(path_loglik([1]*4,c))
    m['rates_per_s'][1][0]=0
    assert path_loglik([1]*4,rounded_components(v,m))==-math.inf


def test_no_demand_unknown_cause():
    m=supplied();m['latent_demand_exposure']=[[0]*4]*2
    c=rounded_components(query(empty=True,offset=0),m)
    assert path_loglik([0]*4,c)==path_loglik([1]*4,c)==0


def test_inputs_unchanged_rename_and_source_required():
    m=supplied();v=query(offset=0);before=copy.deepcopy((v,m))
    a=rounded_components(v,m)
    assert (v,m)==before
    m['movements']=['one','two'];v['events'][0]['event']['movement']='one'
    b=rounded_components(v,m)
    assert path_loglik([0]*4,a)==path_loglik([0]*4,b)
    del m['timestamp_resolution_source']
    with pytest.raises(ModelUnavailable,match='SCIENTIFIC_SOURCES'):rounded_components(v,m)


def test_resource_exhaustion_no_partial_likelihood():
    with pytest.raises(ModelUnavailable,match='PIECE_BUDGET'):
        rounded_components(query(offset=0),supplied(),max_pieces=0)
    with pytest.raises(ModelUnavailable,match='Q_CELL'):
        rounded_components(query(offset=0),supplied(),max_q_cells=0)


def test_delay_mixture_equals_weighted_kernel_and_compensator():
    v=query(offset=0);m=supplied();m['release_detection_probability']=.5
    a=rounded_components(v,m)
    m['release_delay_s']=[[.1,1.]];b=rounded_components(v,m)
    m['release_delay_s']=[[0,.3],[.1,.7]];mix=rounded_components(v,m)
    np.testing.assert_allclose(mix['q'],.3*a['q']+.7*b['q'])
    np.testing.assert_allclose(mix['detected_probability'],.3*a['detected_probability']+.7*b['detected_probability'])
