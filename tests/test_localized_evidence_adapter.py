import copy
from dataclasses import replace

import pytest

from app.core.temporal_evidence import EvidenceUnavailable,TemporalEvent
from app.experimental.localized_evidence_adapter import build_localized_evidence_view


def inputs(available=True):
    event=TemporalEvent(2000,'RELEASE','arbitrary',1,'kinematic_restart_proxy',.6,'MEDIUM',1300,
        {'track_fingerprint':'fp','source':'fixture','proxy':True})
    localized=replace(event,timestamp_ms=2500,evidence_method='kinematic_restart_unsmoothed_interval_proxy',
        provenance={**event.provenance,'legacy_timestamp_ms':2000,'observation_interval_ms':[2400,2500]})
    result=dict(status='available_proxy' if available else 'unavailable',legacy_event=event.to_dict(),
        localized_event=localized.to_dict() if available else None,
        alternatives=[] if available else [{'timestamp_ms':2400},{'timestamp_ms':2600}],
        estimate={'abstention_reason':None if available else 'MULTIPLE_RAW_TRANSITIONS'})
    entry=replace(event,timestamp_ms=1000,event_type='ENTRY',evidence_method='input_zone_entry')
    crossing=replace(event,timestamp_ms=3000,event_type='CROSSING_PROXY',
        evidence_method='observed_zone_transition_proxy',
        provenance={**event.provenance,'eligible_proxy':True})
    return [entry,event,crossing],[result]


def test_new_point_existing_channels_and_track_dependence_preserved():
    events,results=inputs();before=copy.deepcopy((events,results))
    view=build_localized_evidence_view(events,results,source_namespace='test')
    query=view.query(0,4000)
    assert query['counts']['events']==3
    assert query['counts']['known_vehicle_groups_with_eligible_evidence']==1
    assert query['observation_support']['status']=='UNKNOWN'
    assert query['physical_section']['estimated_state']=='UNKNOWN'
    assert view.replacements==1 and len(view.references)==1
    assert query['restart_localization_adapter']['replacement_count_in_window']==1
    assert view.query(0,2100)['restart_localization_adapter']['replacement_count_in_window']==0
    assert (events,results)==before
    with pytest.raises(EvidenceUnavailable,match='no implicit timestamp union'):
        view.index.legacy_streams()


def test_unknown_has_no_hidden_legacy_point_fallback():
    events,results=inputs(False)
    view=build_localized_evidence_view(events,results,source_namespace='test')
    query=view.query(0,4000)
    assert query['counts']['events']==2  # demand/zone channels retained
    assert not query['restart_localization_adapter']['fallback_to_legacy_timestamp']
    assert view.abstentions[0]['reason']=='MULTIPLE_RAW_TRANSITIONS'
    assert len(view.abstentions[0]['alternatives'])==2
    assert view.references[0].timestamp_ms==2000


def test_absent_result_is_unknown_not_default_timestamp():
    events,_=inputs()
    view=build_localized_evidence_view(events,[],source_namespace='test')
    assert view.abstentions[0]['reason']=='NO_LOCALIZATION_RESULT'
    assert view.query(1900,2100)['counts']['events']==0


def test_duplicates_and_foreign_sources_refused():
    events,results=inputs()
    with pytest.raises(ValueError,match='DUPLICATE'):
        build_localized_evidence_view(events,results+results,source_namespace='test')
    results[0]['localized_event']['movement']='different'
    with pytest.raises(ValueError,match='CONTRACT_MISMATCH'):
        build_localized_evidence_view(events,results,source_namespace='test')


def test_no_annotations_argument_or_unbounded_generator():
    events,results=inputs()
    with pytest.raises(TypeError):
        build_localized_evidence_view(events,results,source_namespace='test',annotations={})
    with pytest.raises(TypeError):
        build_localized_evidence_view(iter(events),results,source_namespace='test')


def test_resource_exhaustion_is_structured_unavailable():
    events,results=inputs()
    with pytest.raises(EvidenceUnavailable) as exc:
        build_localized_evidence_view(events,results,source_namespace='test',max_events=1)
    assert exc.value.reason_code=='ADAPTER_EVENT_LIMIT'


def test_unknown_source_checked_and_reference_snapshots_do_not_alias_inputs():
    events,results=inputs(False)
    view=build_localized_evidence_view(events,results,source_namespace='test')
    results[0]['alternatives'].clear()
    events[1].provenance['mutated_after_build']=True
    assert len(view.abstentions[0]['alternatives'])==2
    assert 'mutated_after_build' not in view.references[0].provenance
    events,results=inputs(False)
    results[0]['legacy_event']['movement']='foreign'
    with pytest.raises(ValueError,match='SOURCE_MISMATCH'):
        build_localized_evidence_view(events,results,source_namespace='test')


def test_vehicle_proxy_cannot_be_upgraded_to_signal_observation():
    events,results=inputs()
    results[0]['localized_event']['provenance']['signal_state_observed']=True
    with pytest.raises(ValueError,match='CONTRACT_MISMATCH'):
        build_localized_evidence_view(events,results,source_namespace='test')


def test_other_restart_methods_pass_through_and_cannot_be_mislabeled_localized():
    events,results=inputs()
    metadata=replace(events[1],evidence_method='metadata_dwell_end_restart_supported')
    view=build_localized_evidence_view([metadata],[],source_namespace='test')
    assert view.query(0,4000)['events'][0]['event']['evidence_method']==metadata.evidence_method
    assert view.replacements==0
    results[0]['legacy_event']=metadata.to_dict()
    with pytest.raises(ValueError,match='ONLY_KINEMATIC'):
        build_localized_evidence_view([metadata],results,source_namespace='test')
