from copy import deepcopy

import numpy as np
import pytest

from app.core.intersection_signal_filter import JointSignalFilter
from app.experimental.intersection_timing_ensemble import TimingEnsembleIntersection, TimingHypothesis
from app.experimental.intersection_event_time_timing import EventTimeTimingIntersection
from app.experimental.intersection_leading_brake import LeadingBrakeTimingIntersection, LeadingBrakePointTimingIntersection
from app.experimental.intersection_adaptive_timing import AdaptiveRobustTimingIntersection, CompletedPhaseDurations
from tests.test_intersection_online import model, packet


@pytest.mark.parametrize('factory',[TimingEnsembleIntersection,LeadingBrakePointTimingIntersection,AdaptiveRobustTimingIntersection])
def test_timing_posterior_is_normalized_and_uses_only_offline_structure(factory):
    m=model();original=deepcopy(m);e=factory(m)
    for s in range(12):
        r=e.ingest(packet(s))
        assert sum(p['probability'] for p in r['intergreen_hypotheses'])==pytest.approx(1)
        assert r['phase_count']==2 and set(r['heads'])==set(m['approaches'])
        assert r['production_enabled'] is False
        assert all(np.isfinite(f.log_evidence) for f in e.filters)
        for f in e.filters:
            assert sum(float(g.sum()+edge.sum()) for g,edge in zip(f.green,f.edge))==pytest.approx(1)
    assert m==original


@pytest.mark.parametrize('factory',[TimingEnsembleIntersection,LeadingBrakePointTimingIntersection,AdaptiveRobustTimingIntersection])
def test_invalid_future_packet_does_not_change_any_timing_hypothesis_or_issued_prefix(factory):
    a=factory(model());b=factory(model());prefix=[]
    for s in range(9):
        r=a.ingest(packet(s));assert r==b.ingest(packet(s));prefix.append(deepcopy(r))
    bad=packet(9);bad['vehicles'][0]['detections'][0]['millis']=10000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.ingest(packet(9))==b.ingest(packet(9))
    assert prefix[0]['timestamp_ms']==0 and prefix[-1]['timestamp_ms']==8000


def test_color_edges_belong_to_same_duration_state_without_a_second_timer():
    f=TimingHypothesis(model(),7);f.green[0][:]=0;f.green[0][0,10]=1;f.edge[0][:]=0
    f.hazards[0][:]=0;f.hazards[0][0,10]=1;f.last_ms=0;f.evidence_ms=0
    colors=[f.tick(s*1000,[])['heads']['N']['main']['state'] for s in range(1,9)]
    assert colors==['YELLOW']*3+['RED']*5
    assert f.smoother.lag_s==0


def test_observation_score_is_conditional_evidence_not_a_change_to_state_updates():
    f=JointSignalFilter(model(),history_lag_s=0)
    before=f.log_evidence;f.tick(0,[('N','S',1.)])
    assert f.log_evidence<before
    after=f.log_evidence;f.tick(1000,[])
    assert f.log_evidence==after


def test_observed_onset_correction_is_bounded_and_does_not_rewrite_issued_results():
    e=EventTimeTimingIntersection(model());issued=[];sealed=[];corrections=[]
    for second in range(15):
        result=e.ingest(packet(second));issued.append(result);sealed.append(deepcopy(result))
        corrections.extend(result['corrected_restart_observations'])
        assert len(e.rows)<=8
        assert sum(p['probability'] for p in result['intergreen_hypotheses'])==pytest.approx(1)
    assert issued==sealed
    assert any(c['assigned_ms']<c['available_at_ms'] for c in corrections)
    assert all(0<=c['available_at_ms']-c['assigned_ms']<=8000 for c in corrections)
    assert all(c['assigned_ms']>=c['onset_estimate_ms'] for c in corrections)


def test_event_time_correction_rejects_future_atomically_and_clears_gap_buffer():
    a=EventTimeTimingIntersection(model());b=EventTimeTimingIntersection(model())
    for s in range(9):assert a.ingest(packet(s))==b.ingest(packet(s))
    old=deepcopy(a.rows);bad=packet(9);bad['vehicles'][0]['detections'][0]['millis']=10000
    with pytest.raises(ValueError,match='future'):a.ingest(bad)
    assert a.rows==old
    assert a.ingest(packet(9))==b.ingest(packet(9))
    a.ingest(dict(timestamp_ms=300000,sequence=10,vehicles=[]))
    assert len(a.rows)==1


def brake_case(*,leader=False,lateral_drift=False,stop_offset=0):
    e=AdaptiveRobustTimingIntersection(model())
    e.source.queues.references={'N':dict(anchor_lat_lng=[0,0],point_m=[0,0],heading=[1,0],lateral_radius_m=4)}
    def track(offset):
        ds=[]
        for i in range(8):
            t=i*.2;x=-25+10*t-t*t+offset+stop_offset;y=3*t/1.4 if lateral_drift else 0
            ds.append(dict(millis=i*200,lat=y/111000,lng=x/111000,zone='N'))
        return dict(origin='N',points=ds)
    e.source.motion.tracks={'car':track(0)}
    if leader:e.source.motion.tracks['leader']=track(8)
    return e


def test_leading_brake_requires_motion_fit_and_does_not_reemit_continuous_braking():
    e=brake_case();rows=e._leading_brakes(1400)
    assert len(rows)==1 and rows[0]['acceleration_mps2']==pytest.approx(-2)
    assert rows[0]['available_at_ms']==1400
    assert e._leading_brakes(1400)==[]
    assert e._leading_brakes(5000)==[]


def test_braking_behind_a_leader_or_turning_does_not_become_a_signal_observation():
    assert not any(r['vehicle_id']=='car' for r in brake_case(leader=True)._leading_brakes(1400))
    assert brake_case(lateral_drift=True)._leading_brakes(1400)==[]
    assert brake_case(stop_offset=-20)._leading_brakes(1400)==[]


def duration_run(first_phase_intervals):
    tracker=CompletedPhaseDurations(model()['regimes'][0]);tracker.observe(0,0);now=0;updates=[]
    for length in first_phase_intervals:
        now+=length*1000
        update=tracker.observe(1,now)
        if update:updates.append(update)
        now+=40000
        update=tracker.observe(0,now)
        if update:updates.append(update)
    return tracker,updates


def test_isolated_extension_does_not_replace_ordinary_duration():
    tracker,updates=duration_run([40,40,40,52,40,40])
    assert tracker.accepted==[40,40]
    assert all(r['median_s']==40 for r in updates)


def test_persistent_change_requires_repeated_completed_intervals_and_keeps_other_phase():
    tracker,updates=duration_run([40,40,40,46,46])
    assert tracker.accepted==[46,40]
    assert updates[-1]['median_s']==46 and updates[-1]['samples']==3
    tracker,updates=duration_run([40,40,40,46])
    assert tracker.accepted==[40,40]


def test_missing_long_gap_and_repeated_same_phase_do_not_become_completed_intervals():
    tracker=CompletedPhaseDurations(model()['regimes'][0]);tracker.observe(0,0)
    assert tracker.observe(0,5000) is None
    assert tracker.observe(1,400000) is None
    assert all(not row for row in tracker.samples)


def test_uncalibrated_logical_phase_age_histograms_do_not_become_physical_green_ages():
    m=model();n=deepcopy(m)
    n['regimes'][0]['restart_age_histograms']={'E->W':[[50]+[.001]*15,[.001]*15+[50]]}
    a=AdaptiveRobustTimingIntersection(m);b=AdaptiveRobustTimingIntersection(n)
    for s in range(12):assert a.ingest(packet(s))==b.ingest(packet(s))
    assert all(not f.use_restart_age_prior for f in a.filters)


def test_joint_timing_is_invariant_to_absolute_packet_clock_translation():
    a=AdaptiveRobustTimingIntersection(model());b=AdaptiveRobustTimingIntersection(model())
    for s in range(15):
        p=packet(s);shifted=deepcopy(p);shifted['timestamp_ms']+=86400000
        for v in shifted['vehicles']:
            for d in v['detections']:d['millis']+=86400000
        x=a.ingest(p);y=b.ingest(shifted)
        assert x['heads']==y['heads']
        assert x['intergreen_hypotheses']==y['intergreen_hypotheses']
