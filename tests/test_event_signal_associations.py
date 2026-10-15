"""Association semantics counterexamples, independent of phase inference."""
import copy
import pytest

from app.core.temporal_evidence import TemporalEvent
from app.experimental.event_signal_associations import associate


def profile():
    return {'origin_ms':100000,'delta_s':.5,'conditional_delta_sets_s':[[0,1]],
            'validated_media_extent_s':[0,10]}


def reference():
    return [{'event':'REFERENCE_ONSET','video_presentation_bracket_s':[2,2.1],
             'status':'CONDITIONAL_DIAGNOSTIC_ONLY'}]


def event(kind='RELEASE',timestamp=105000,movement='arbitrary_movement',fp='track1'):
    row=TemporalEvent(timestamp,kind,movement,1,'test_vehicle_method',.6,'MEDIUM',1300,
        {'source':'unit_test','track_fingerprint':fp,'eligible_proxy':True,
         'observation_interval_ms':[timestamp-100,timestamp]}).to_dict()
    row['selected_permission']=kind=='RELEASE'
    return row


def test_signed_offset_is_conditional_not_a_reaction_time_or_lamp_state():
    result=associate([event()],profile(),reference())
    pair=result['associations'][0]
    assert pair['conditional_offset_sets_s'][0]==pytest.approx([1.9,3])
    assert pair['physical_state']=='UNKNOWN' and not pair['causal_delay_eligible']
    assert pair['calibrated_lamp_probability'] is None
    assert pair['vehicle_localization_uncertainty_added'] is False
    assert result['counts']['supported_causal_delays']==0


def test_multimodal_clock_not_replaced_by_best_offset():
    clock=profile();clock.update(delta_s=.1,conditional_delta_sets_s=[[0,.2],[.8,1]])
    pairs=associate([event()],clock,reference())['associations'][0]['conditional_offset_sets_s']
    assert len(pairs)==2
    assert pairs[0]==pytest.approx([2.7,3]) and pairs[1]==pytest.approx([1.9,2.2])


def test_clock_boundary_censoring_does_not_extrapolate():
    result=associate([event(timestamp=100500)],profile(),reference())
    assert result['events'][0]['clock_scope']=='PARTIAL_CLOCK_CENSORING'
    assert result['associations']==[]


def test_no_events_do_not_prove_red_no_demand_or_camera_coverage():
    result=associate([],profile(),reference())
    assert result['physical_state']=='UNKNOWN'
    assert result['local_evidence']['observation_support']['status']=='UNKNOWN'
    assert result['counts']['inside_known_track_groups']==0


def test_same_vehicle_channels_remain_correlated_without_input_mutation():
    rows=[event(),event('CROSSING_PROXY',105100)];before=copy.deepcopy(rows)
    result=associate(rows,profile(),reference())
    assert rows==before
    assert result['counts']['inside_permission_track_groups']==1
    assert result['counts']['inside_events_by_type']=={'RELEASE':1,'CROSSING_PROXY':1}
    assert len(result['local_evidence']['correlated_vehicle_groups'])==1


def test_unknown_track_identity_does_not_share_stop_support():
    result=associate([event('STOP',fp=None),event(fp=None)],profile(),reference())
    assert result['counts']['inside_known_track_groups']==0
    assert result['counts']['inside_stop_supported_release_events']==0


def test_bijective_movement_rename_preserves_numerical_offsets():
    a=associate([event(movement='N->S')],profile(),reference())
    b=associate([event(movement='stream_27')],profile(),reference())
    assert a['counts']==b['counts']
    assert a['associations'][0]['conditional_offset_sets_s']==b['associations'][0]['conditional_offset_sets_s']


def test_clock_candidate_cannot_be_claimed_inside_incompatible_sets():
    clock=profile();clock['delta_s']=2
    with pytest.raises(ValueError,match='CANDIDATE_CLOCK_OUTSIDE'):
        associate([event()],clock,reference())


def test_tampered_vehicle_seal_is_rejected_before_reading_external_references(tmp_path,monkeypatch):
    import json
    import sys
    from scripts.event_signal_associations import main
    events=tmp_path/'events.json';events.write_text('{}')
    seal=tmp_path/'seal.json';seal.write_text(json.dumps({'vehicle_events_sha256':'wrong'}))
    monkeypatch.setattr(sys,'argv',['audit','--events',str(events),'--seal',str(seal),
        '--profile',str(tmp_path/'must-not-read-profile.json'),
        '--references',str(tmp_path/'must-not-read-references.json'),'--out',str(tmp_path/'out')])
    with pytest.raises(ValueError,match='SEALED_EVENT_HASH_MISMATCH'):
        main()
    assert not (tmp_path/'out').exists()


def test_annotation_file_cannot_be_passed_to_extraction(tmp_path,monkeypatch):
    import json
    import scripts.seal_vehicle_events as producer
    source=tmp_path/'review.json';source.write_text(json.dumps({'schema':'trajectory-review-v1','annotations':[]}))
    monkeypatch.setattr(producer,'load_event_streams',lambda *a,**kw:pytest.fail('annotations reached extractor'))
    with pytest.raises(ValueError,match='ANNOTATION_OR_NON_TRACK_INPUT_FORBIDDEN'):
        producer.extract(source,tmp_path/'unread-plan.json',tmp_path/'out')


def test_extraction_wrapper_passes_only_raw_records_and_seals_before_join(tmp_path,monkeypatch):
    import hashlib
    import json
    import types
    import scripts.seal_vehicle_events as producer
    source=tmp_path/'raw.json';source.write_text(json.dumps([{'id':1,'detections':[]}]))
    plan=tmp_path/'plan.json';plan.write_text('{}')
    observed=[]
    def fake_extractor(path,*,_records):
        observed.append((_records,path))
        row=TemporalEvent(105000,'ENTRY','arbitrary',1,'unit',.5,'LOW',None,{})
        return types.SimpleNamespace(temporal_events=[row],diagnostics={'selected_event_indices':[]})
    monkeypatch.setattr(producer,'load_event_streams',fake_extractor)
    seal=producer.extract(source,plan,tmp_path/'out')
    assert observed==[([{'id':1,'detections':[]}],source)]
    assert seal['signal_references_not_loaded'] is True
    assert seal['vehicle_events_sha256']==hashlib.sha256((tmp_path/'out/vehicle_events.json').read_bytes()).hexdigest()
