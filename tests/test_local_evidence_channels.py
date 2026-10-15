import copy
from dataclasses import replace
import json
import pytest

from app.core.temporal_evidence import TemporalEvent, EvidenceUnavailable
from app.core.v9.vehicle_evidence import select_permission_events
from app.experimental.local_evidence import build_local_evidence, ExposureWindow


def event(t=10000, kind='CROSSING_PROXY', track='car1', movement='M', **provenance):
    defaults={'source':'synthetic','track_fingerprint':track,'eligible_proxy':True,
              'verified_stop_line':kind=='CROSSING','signal_state_observed':False}
    defaults.update(provenance)
    return TemporalEvent(t,kind,movement,7,kind.lower()+'_test_method',.4,
                         'MEDIUM' if kind=='RELEASE' else 'LOW',None,defaults)


def build(events,**kwargs):
    return build_local_evidence(events,source_namespace='synthetic-session',**kwargs)


def local(events,**kwargs):
    return build(events,**kwargs).query(0,180000)


def semantic_projection(result):
    result=copy.deepcopy(result)
    for row in result['events']: row.pop('source_indices')
    return result


@pytest.mark.parametrize('track',['other-car','car1'])
def test_remote_release_preserves_early_channel_in_new_view(track):
    early=event()
    late=event(600000,'RELEASE',track)
    old,_=select_permission_events([early,late])
    assert not [e for e in old if e.timestamp_ms<180000]
    assert semantic_projection(local([early]))==semantic_projection(local([late,early]))


def test_non_stopping_car_keeps_crossing_without_fabricated_release():
    r=local([event()])
    assert r['counts']['events_by_type']=={'CROSSING_PROXY':1}
    assert r['counts']['eligible_vehicle_events']==1
    assert r['physical_section']['estimated_state']=='UNKNOWN'
    assert r['events'][0]['event']['uncertainty']['event_to_signal_switch']['status']=='UNKNOWN'


def test_same_vehicle_restart_and_crossing_are_distinct_but_correlated():
    a,b=event(10000,'RELEASE'),event(20000)
    r=local([a,b])
    assert len(r['channels'])==2
    assert r['counts']['eligible_vehicle_events']==2
    assert r['counts']['known_vehicle_groups_with_eligible_evidence']==1
    assert len(next(iter(r['correlated_vehicle_groups'].values())))==2


def test_exact_duplicates_preserve_provenance_without_extra_vehicle():
    e=event(); idx=build([e,copy.deepcopy(e)])
    r=idx.query(0,180000)
    assert idx.duplicate_events==1
    assert r['counts']['eligible_vehicle_events']==1
    assert r['events'][0]['source_indices']==[0,1]
    assert r['events'][0]['event']==e.to_dict()


def test_reused_numeric_track_id_not_identity_and_namespace_isolated():
    a,b=event(track='fp1'),event(track='fp2')
    assert a.source_track_id==b.source_track_id
    assert local([a,b])['counts']['known_vehicle_groups_with_eligible_evidence']==2
    x=build_local_evidence([a],source_namespace='other-session').query(0,180000)
    assert x['events'][0]['vehicle_group_id']!=local([a])['events'][0]['vehicle_group_id']


def test_unknown_track_identity_stays_unknown():
    r=local([event(track=None)])
    assert r['counts']['known_vehicle_groups_with_eligible_evidence']==0
    assert r['counts']['eligible_events_without_track_identity']==1
    assert r['events'][0]['vehicle_group_id'] is None


@pytest.mark.parametrize('scenario', ['permissive turn','unblocked queue','priority vehicle'])
def test_identical_vehicle_evidence_cannot_identify_signal_or_cause(scenario):
    e=event(kind='RELEASE',movement='arbitrary turn')
    # Hidden scenario is deliberately not supplied to representation.
    r=local([e])
    assert r['logical_phase']['estimated_state']=='UNKNOWN'
    assert r['physical_section']['estimated_state']=='UNKNOWN'
    assert r['physical_section']['calibrated_lamp_probability'] is None
    assert r['events'][0]['signal_relation']=='UNKNOWN'


def test_blocked_queue_and_demand_are_not_permission_or_red():
    r=local([event(kind='ENTRY'),event(11000,'STOP')])
    assert r['counts']['eligible_vehicle_events']==0
    assert r['abstention_reason']=='NO_ELIGIBLE_LOCAL_MOVEMENT_EVIDENCE'
    assert r['physical_section']['estimated_state']=='UNKNOWN'


def test_no_demand_cannot_be_distinguished_from_missing_observation():
    unknown=local([])
    supplied=local([],exposure_windows=[ExposureWindow(0,180000,'synthetic camera on')])
    assert unknown['observation_support']['status']=='UNKNOWN'
    assert supplied['observation_support']['status']=='SUPPLIED_FULL_WINDOW'
    assert supplied['observation_support']['demand']=='UNKNOWN'
    assert supplied['abstention_reason']==unknown['abstention_reason']=='NO_LOCAL_EVENTS'
    assert supplied['physical_section']['estimated_state']=='UNKNOWN'
    with pytest.raises(EvidenceUnavailable,match='missing'): build(None)


def test_declared_gap_not_filled_and_contradictory_event_flagged():
    exposure=[ExposureWindow(0,20000,'provided test window'),ExposureWindow(40000,180000,'provided test window')]
    r=local([event(30000)],exposure_windows=exposure)
    assert r['observation_support']['supplied_duration_s']==160
    assert r['observation_support']['status']=='SUPPLIED_PARTIAL_WINDOW'
    assert r['observation_support']['event_ids_outside_supplied_windows']==[r['events'][0]['event_id']]
    assert r['physical_section']['estimated_state']=='UNKNOWN'
    idx=build([],exposure_windows=exposure)
    assert idx.query(20000,40000)['observation_support']['status']=='NO_SUPPLIED_WINDOW_SUPPORT'


def test_half_open_bounds_do_not_create_boundary_events():
    r=local([event(0),event(179999),event(180000)])
    assert [x['event']['timestamp_ms'] for x in r['events']]==[0,179999]


def test_order_rename_and_shared_movement_without_topology():
    data=[event(10000,'RELEASE','fp1','shared'),event(20000,'CROSSING_PROXY','fp2','shared'),event(30000,'CROSSING_PROXY','fp3','other')]
    assert semantic_projection(local(data))==semantic_projection(local(list(reversed(data))))
    renamed=[replace(e,movement={'shared':'random-x','other':'random-y'}[e.movement]) for e in data]
    assert local(renamed)['counts']==local(data)['counts']
    assert len(local(renamed)['channels'])==3


def test_immutable_snapshot_and_no_implicit_legacy_union():
    e=event();original=copy.deepcopy(e.to_dict());idx=build([e]);r=idx.query(0,180000)
    assert e.to_dict()==original
    e.provenance['new_field']='changed after build'
    r['events'][0]['event']['provenance']['another']='changed exported data'
    assert idx.query(0,180000)['events'][0]['event']==original
    with pytest.raises(EvidenceUnavailable) as exc: idx.legacy_streams()
    assert exc.value.to_dict()['reason_code']=='METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED'


@pytest.mark.parametrize('kw,reason',[({'max_events':0},'EVIDENCE_EVENT_LIMIT'),({'max_seconds':0},'EVIDENCE_TIME_LIMIT')])
def test_resource_limit_not_partial_success(kw,reason):
    with pytest.raises(EvidenceUnavailable) as exc: build([event()],**kw)
    assert exc.value.to_dict()['reason_code']==reason
    assert exc.value.to_dict()['phase_count'] is None


def test_query_budget_and_bad_interval():
    idx=build([event()])
    with pytest.raises(EvidenceUnavailable): idx.query(0,2000000)
    with pytest.raises(EvidenceUnavailable): idx.query(0,180000,max_events=0)
    for lo,hi in [(0,float('nan')),(0,0),(True,1000),(-1,1)]:
        with pytest.raises(ValueError): idx.query(lo,hi)
    with pytest.raises(ValueError): build([replace(event(),timestamp_ms=True)])
    with pytest.raises(TypeError): build([{'kind':'phase_hypothesis'}])


def test_old_eligibility_guards_preserved_but_excluded_provenance_visible():
    bad=event(invalid_detections=1)
    r=local([bad])
    assert r['counts']['eligible_vehicle_events']==0
    assert r['events'][0]['exclusion_reason']=='INVALID_DETECTIONS'
    assert r['events'][0]['event']==bad.to_dict()


def test_confirmed_geometry_still_not_a_signal_observation():
    r=local([event(kind='CROSSING')])
    assert r['events'][0]['role']=='vehicle_crossing_verified_geometry'
    assert r['physical_section']['estimated_state']=='UNKNOWN'


def test_supplied_exposure_resource_and_validation():
    with pytest.raises(EvidenceUnavailable):
        build([],exposure_windows=[ExposureWindow(0,1,'source')]*1001)
    with pytest.raises(ValueError):
        build([],exposure_windows=[ExposureWindow(0,10,'source'),ExposureWindow(9,11,'source')])
    with pytest.raises(ValueError): ExposureWindow(0,10,'')


def test_saved_sidecar_adapter_without_labels_or_any_fit(monkeypatch):
    from scripts.local_evidence_experiment import inspect_sidecar
    from app.core.v9 import model
    def forbidden(*a,**kw): raise AssertionError('inference is forbidden in sidecar experiment')
    monkeypatch.setattr(model,'discover_records',forbidden)
    monkeypatch.setattr(model,'discover_path',forbidden)
    monkeypatch.setattr(model,'discover_phase_count',forbidden)
    data=[event(),event(600000,'RELEASE','remote')]
    saved={'recording_start_timestamp_ms':0,'event_extraction':{
        'temporal_events':[e.to_dict() for e in data],
        'quality_diagnostics':{'selected_event_indices':[1]}}}
    original=copy.deepcopy(saved)
    r=inspect_sidecar(saved,source_namespace='test')
    assert r['old_selected_local_count']==0
    assert r['new_eligible_local_count']==1
    assert r['recovered_event_count']==1
    assert r['new_phase_prediction'] is None
    assert saved==original
    with pytest.raises(TypeError): inspect_sidecar(saved,source_namespace='test',annotations=[])


def test_saved_contract_loss_is_rejected():
    from scripts.local_evidence_experiment import inspect_sidecar
    e=event().to_dict();e['unknown_extra_metadata']='must not disappear silently'
    with pytest.raises(ValueError,match='lossless roundtrip'):
        inspect_sidecar({'recording_start_timestamp_ms':0,'event_extraction':{
            'temporal_events':[e],'quality_diagnostics':{'selected_event_indices':[]}}},source_namespace='test')
