import copy
import inspect
import math

import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence
from app.experimental.phase_observation_bridge import prepare_joint_observation
from app.experimental.joint_track_model import path_loglik


def model():
    return dict(horizon_s=8, movements=['straight', 'turn'],
        rates_per_s=[[.2, .03], [.03, .2]], rate_source='declared test model',
        latent_demand_exposure=[[1]*4, [1]*4], demand_source='test exposure',
        observation_windows_s=[[0, 20]], observation_window_source='test camera windows',
        release_delay_s=[[0, 1.]], transit_delay_s=[[2, 1.]], delay_source='test model',
        release_detection_probability=1., crossing_detection_probability=.5,
        release_method='test_restart', crossing_method='test_zone')


def query(pair=False, empty=False, offset=100000):
    events=[]
    if not empty:
        events.append(TemporalEvent(offset+250, 'RELEASE', 'straight', 7,
            'test_restart', .65, 'MEDIUM', 1300,
            {'source': 'test', 'track_fingerprint': 'track7'}))
        if pair:
            events.append(TemporalEvent(offset+2250, 'CROSSING_PROXY', 'straight', 7,
                'test_zone', .5, 'MEDIUM', 3000,
                {'source': 'test', 'track_fingerprint': 'track7', 'eligible_proxy': True}))
    return build_local_evidence(events, source_namespace='test').query(offset, offset+20000)


def test_no_model_no_synthetic_defaults_or_lamp_claims():
    result=prepare_joint_observation(query())
    assert result['status']=='unavailable'
    assert 'latent_demand_exposure' in result['missing_inputs']
    assert result['components'] is None
    assert result['physical_section']['estimated_state']=='UNKNOWN'
    assert result['logical_phase']['estimated_state']=='UNKNOWN'
    assert result['calibrated_lamp_probability'] is None


def test_motion_before_phase_start_is_possible_without_claiming_green():
    result=prepare_joint_observation(query(), model(), origin_ms=100000)
    assert result['status']=='ready_for_declared_model_only'
    # straight event in phase1, then phase0 starts later: permitted nuisance intensity.
    assert math.isfinite(path_loglik([1, 1, 0, 0], result['components']))
    assert result['physical_section']['estimated_state']=='UNKNOWN'


def test_same_track_pair_is_one_unit_not_two_independent_events():
    a=prepare_joint_observation(query(), model(), origin_ms=100000)
    b=prepare_joint_observation(query(pair=True), model(), origin_ms=100000)
    assert a['vehicle_group_count']==b['vehicle_group_count']==1
    assert b['event_count']==2 and len(b['components']['tracks'])==1
    assert path_loglik([0, 1, 0, 1], a['components'])==path_loglik([0, 1, 0, 1], b['components'])


def test_no_demand_and_blockage_are_not_classified_by_silence():
    m=model(); m['latent_demand_exposure']=[[0]*4, [0]*4]
    a=prepare_joint_observation(query(empty=True), m, origin_ms=100000)
    assert path_loglik([0]*4, a['components'])==path_loglik([1]*4, a['components'])==0
    assert a['logical_phase']['estimated_state']=='UNKNOWN'
    # Unknown demand is unavailable, not manufactured zero/full exposure.
    del m['latent_demand_exposure']
    assert prepare_joint_observation(query(empty=True), m, origin_ms=100000)['status']=='unavailable'


@pytest.mark.parametrize('field', ['rate_source', 'delay_source', 'demand_source', 'observation_window_source'])
def test_missing_scientific_source_blocks_bridge(field):
    m=model(); del m[field]
    assert field in prepare_joint_observation(query(), m, origin_ms=100000)['missing_inputs']


def test_unknown_clock_and_off_grid_timestamps_not_rounded():
    assert prepare_joint_observation(query(), model())['reason']=='EXPLICIT_CLOCK_ORIGIN_REQUIRED'
    v=query(); v['events'][0]['event']['timestamp_ms']+=1
    assert 'DISCRETE_CLOCK' in prepare_joint_observation(v, model(), origin_ms=100000)['reason']


def test_observed_mark_in_supplied_gap_rejected_not_silently_deleted():
    m=model(); m['observation_windows_s']=[[2, 20]]
    assert prepare_joint_observation(query(), m, origin_ms=100000)['reason']=='OBSERVATION_OUTSIDE_SUPPLIED_WINDOWS'


def test_unverified_proxy_not_transferred_to_exclusive_mark_model():
    m=model(); m['rates_per_s'][1][0]=0
    assert 'NONEXCLUSIVE' in prepare_joint_observation(query(), m, origin_ms=100000)['reason']


def test_rename_and_snapshot_preserve_behavior_and_inputs():
    v=query(pair=True); m=model(); before=copy.deepcopy((v, m))
    a=prepare_joint_observation(v, m, origin_ms=100000)
    assert (v, m)==before
    m['movements']=['alpha', 'beta']
    for r in v['events']: r['event']['movement']='alpha'
    b=prepare_joint_observation(v, m, origin_ms=100000)
    assert path_loglik([0, 1, 0, 1], a['components'])==path_loglik([0, 1, 0, 1], b['components'])
    b['components']['tracks'][0]['movement']='changed'
    assert v['events'][0]['event']['provenance']['source']=='test'


def test_budget_and_no_inference_or_annotation_access():
    assert prepare_joint_observation(query(), model(), origin_ms=100000, max_events=0)['reason']=='EVENT_BUDGET_EXHAUSTED'
    source=inspect.getsource(prepare_joint_observation)
    assert 'infer_joint(' not in source and 'open(' not in source


def test_horizon_budget_checked_before_array_allocation():
    m=model(); m['horizon_s']=100000000
    assert prepare_joint_observation(query(), m, origin_ms=100000)['reason']=='HORIZON_BUDGET_EXHAUSTED'


def test_equal_intensities_silence_cannot_distinguish_phases():
    m=model(); m['rates_per_s']=[[.1, .1], [.1, .1]]
    r=prepare_joint_observation(query(empty=True), m, origin_ms=100000)
    assert path_loglik([0]*4, r['components'])==path_loglik([1]*4, r['components'])
    assert r['logical_phase']['estimated_state']=='UNKNOWN'


def test_unsupported_eligible_channel_not_silently_dropped():
    v=query(); v['events'][0]['event']['event_type']='CROSSING'
    assert prepare_joint_observation(v, model(), origin_ms=100000)['reason']=='ELIGIBLE_CHANNEL_NOT_IN_JOINT_MODEL'
