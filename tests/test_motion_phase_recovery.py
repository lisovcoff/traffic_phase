"""Physical observation and grouping regressions for trajectory recovery."""
import numpy as np
import pytest
from types import SimpleNamespace

from app.experimental.motion_restart import restart_from_raw_speed,extract_motion_evidence
from app.experimental.trajectory_phase_recovery import rate_equivalent_mapping


def trajectory(scale=1.):
    return [dict(millis=100000+i*100,speed=scale*(0 if i<22 else (i-21)*.5),
        centroid_x=.1+(max(0,i-21)**2)*.00002,centroid_y=.2,
        zone='N' if i<38 else '_S') for i in range(65)]


def test_observed_restart_is_unit_invariant_and_sampling_bounded():
    a=restart_from_raw_speed(trajectory(),104000)
    b=restart_from_raw_speed(trajectory(3.6),104000)
    assert a==b
    assert a['timestamp_ms']==102200
    assert a['interval_ms']==[102100,102200]


def test_freeflow_does_not_establish_a_restart():
    ds=trajectory()
    for d in ds:d['speed']=10.
    assert restart_from_raw_speed(ds,104000) is None


def test_no_fictitious_restart_across_a_detection_gap():
    ds=[d for d in trajectory() if d['millis']<=100100 or d['millis']>=102300]
    assert restart_from_raw_speed(ds,104000) is None


def test_later_observed_stop_replaces_an_earlier_queue_creep():
    ds=trajectory()
    for i,d in enumerate(ds):
        if 23<=i<43:d['speed']=0
        elif i>=43:d['speed']=(i-42)*.5
    result=restart_from_raw_speed(ds,106400)
    assert result['timestamp_ms']==104300


def test_restart_after_crossing_is_not_an_approach_release():
    assert restart_from_raw_speed(trajectory(),101000) is None


def test_observed_motion_is_not_promoted_to_lamp_truth():
    track=dict(id=1,zone_in='N',zone_out='_S',detections=trajectory())
    events,_=extract_motion_evidence(track)
    release=next(e for e in events if e.evidence_method=='observed_raw_speed_restart')
    assert release.timestamp_ms==102200
    assert release.provenance['signal_state_observed'] is False
    assert release.provenance['verified_stop_line'] is False
    assert release.provenance['lamp_timing_uncertainty_ms'] is None
    assert sum(e.event_type=='RELEASE' for e in events)==1


def test_discharge_density_alone_does_not_create_an_extra_phase():
    rates=np.array([[.24,.22,.01,.01],[.07,.08,.01,.01],[.01,.01,.2,.18]])
    mapping,pairs=rate_equivalent_mapping(rates)
    assert mapping[0]==mapping[1] and mapping[2]!=mapping[0]
    assert len(pairs)==1


def test_new_movement_preserves_a_distinct_phase_with_shared_main():
    rates=np.array([[.24,.22,.01,.01],[.17,.01,.23,.01],[.01,.01,.01,.2]])
    mapping,pairs=rate_equivalent_mapping(rates)
    assert len(set(mapping.values()))==3 and pairs==[]


def test_grouping_is_invariant_to_movement_column_order():
    rates=np.array([[.24,.22,.01,.01],[.07,.08,.01,.01],[.01,.01,.2,.18]])
    assert rate_equivalent_mapping(rates)[0]==rate_equivalent_mapping(rates[:,[2,0,3,1]])[0]


def test_equal_permission_support_can_merge_different_discharge_proportions():
    rates=np.array([[.083,.092,.01,.01],[.046,.0194,.01,.01],[.01,.01,.05,.033]])
    mapping,_=rate_equivalent_mapping(rates,cosine_min=0.)
    assert mapping[0]==mapping[1] and mapping[2]!=mapping[0]


def test_boolean_speed_does_not_establish_a_stationary_run():
    ds=trajectory()
    for d in ds:
        if d['speed']==0:d['speed']=False
    assert restart_from_raw_speed(ds,104000) is None


def test_front_period_rejects_discharge_centroid_drift():
    from app.experimental.front_period import refine_front_period
    events=[]
    for movement,offset in [('N->S',10.),('E->W',60.)]:
        for c in range(32):
            events.append(SimpleNamespace(event_type='RELEASE',evidence_quality='MEDIUM',movement=movement,
                timestamp_ms=(c*100+offset+.1*np.sin(c))*1000))
            for tail in range(8):
                events.append(SimpleNamespace(event_type='RELEASE',evidence_quality='MEDIUM',movement=movement,
                    timestamp_ms=(c*100+offset+3+tail+.15*c)*1000))
    period,diagnostic=refine_front_period(events,0.,99.9,3200.)
    assert diagnostic['applied']
    assert abs(period-100)<.03


def test_short_record_does_not_invent_a_precise_front_clock():
    from app.experimental.front_period import refine_front_period
    events=[SimpleNamespace(event_type='RELEASE',evidence_quality='MEDIUM',movement='N->S',timestamp_ms=t*1000)
        for t in (10,20,110,120,210,220)]
    period,diagnostic=refine_front_period(events,0.,99.,300.)
    assert period==99. and diagnostic['applied'] is False


@pytest.mark.parametrize('literal,zero',[(b'-0.0',True),(b'1e-9999',True),(b'0.00001',False),(b'false',False),(b'"0"',False)])
def test_zero_speed_cache_audit_uses_numeric_semantics(tmp_path,literal,zero):
    import hashlib
    from scripts.audit_zero_speed import audit
    data=b'[{"detections":[{"speed":'+literal+b'}]}]'
    source=tmp_path/'input.json';source.write_bytes(data)
    audit(dict(id='test',path=str(source),member=None),dict(sha256=hashlib.sha256(data).hexdigest(),bytes_read=len(data)),tmp_path)
    import json
    receipt=json.loads((tmp_path/'test.json').read_text())
    assert receipt['exact_zero_speed_present'] is zero
    assert receipt['evidence_cache_reusable_for_exact_zero_restart'] is not zero
