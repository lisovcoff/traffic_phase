"""Characterize the current locality counterexample, not acceptance of its policy.

This demonstrates information loss without phase truth or fitting. A future
selector experiment must replace this diagnostic with a preservation invariant.
"""
from app.core.temporal_evidence import TemporalEvent
from app.core.v9.vehicle_evidence import select_permission_events


def test_remote_restart_removes_local_proxy_in_current_selector():
    proxy=TemporalEvent(10000,'CROSSING_PROXY','arbitrary movement','local-car',
        'observed_zone_transition_proxy',.3,'LOW',None,{'eligible_proxy':True})
    restart=TemporalEvent(600000,'RELEASE','arbitrary movement','remote-car',
        'kinematic_restart_proxy',.6,'MEDIUM',1300,{'proxy':True})
    before,_=select_permission_events([proxy])
    after,_=select_permission_events([proxy,restart])
    local_before=[e for e in before if e.timestamp_ms<180000]
    local_after=[e for e in after if e.timestamp_ms<180000]
    assert local_before == [proxy]
    assert local_after == []  # Confirmed current behavior, not desired invariant.
    assert after == [restart]
    assert restart.to_dict()['uncertainty']['event_to_signal_switch']['status']=='UNKNOWN'
