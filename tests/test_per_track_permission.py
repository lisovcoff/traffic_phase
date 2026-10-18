from dataclasses import replace
import itertools

from app.core.temporal_evidence import TemporalEvent
from app.core.v9.vehicle_evidence import select_permission_events_per_track


def event(ident,kind='CROSSING_PROXY',timestamp=2000,source='a',**flags):
    return TemporalEvent(timestamp,kind,'N->S',ident,'test',.5,
        'MEDIUM' if kind=='RELEASE' else 'LOW',None,
        {'track_fingerprint':str(ident),'source':source,'eligible_proxy':True,**flags})


def test_one_restart_does_not_remove_fifty_other_cars_on_same_movement():
    values=[event(0,'RELEASE')]+[event(i) for i in range(1,51)]
    selected,methods=select_permission_events_per_track(values)
    assert len(selected)==51
    assert {e.source_track_id for e in selected}==set(range(51))
    assert methods=={'N->S':'mixed_release_and_crossing_proxy'}


def test_same_vehicle_does_not_count_as_both_restart_and_crossing():
    proxy,release=event(1),event(1,'RELEASE',1000)
    selected,_=select_permission_events_per_track([proxy,release,proxy,release])
    assert selected==[release]


def test_missing_identity_and_ineligible_proxy_do_not_become_permission():
    bad=event(0)
    missing=replace(bad,provenance={})
    selected,_=select_permission_events_per_track([missing,event(1,eligible_proxy=False),
        event(2,invalid_detections=1),event(3,conflicting_timestamps=1)])
    assert selected==[]


def test_source_scope_keeps_identical_track_fingerprints_separate():
    selected,_=select_permission_events_per_track([event(1,source='a'),event(1,source='b')])
    assert len(selected)==2


def test_low_quality_restart_does_not_hide_eligible_crossing():
    selected,_=select_permission_events_per_track([replace(event(1,'RELEASE'),evidence_quality='LOW'),event(1)])
    assert len(selected)==1 and selected[0].event_type=='CROSSING_PROXY'


def test_selection_is_deterministic_across_input_order_and_timestamp_ties():
    values=[event(2),event(1),event(3,'RELEASE',1000),event(3),event(1,timestamp=3000)]
    expected=select_permission_events_per_track(values)
    for order in itertools.permutations(values):
        assert select_permission_events_per_track(order)==expected
