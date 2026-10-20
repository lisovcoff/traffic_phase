import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.experimental.calibration_bundle import build_bundle


def sources():
    return dict(direct_video={'transitions':[dict(event='LATERAL_LAST_OBSERVED_ON_TO_DARK',
        video_presentation_bracket_s=[1,2],before_frame={'actual_media_time_s':1},
        after_frame={'actual_media_time_s':2},before_appearance='lit',after_appearance='dark',
        status='candidate_blink_cessation_not_certified_final_off')]},
        vehicle_video=dict(boundary_semantics='sampled appearance',head_references=[
            dict(window='A',head_id='H1',observed_change='GREEN_APPEARANCE',media_bracket_s=[5,6],frames=[])],
            rows=[dict(window='A',track_id_hypothesis=7,observed_onset_bracket_s=[3,4],
                       identity_status='PROVISIONAL',frames=[])]),
        operator={'events':[dict(annotation_id='one',group='1',claimed_start_event='OFF',certainty='operator_report',
                                interval_ms=[100000,110000],derived_media_interval_s=[0,10],correction=[])]},
        proxy_queries={'queries':{'A':{'events':[dict(event_id='original',vehicle_group_id='vehicle7',
            event=dict(source_track_id=7,timestamp_ms=103000,event_type='RELEASE',confidence=.6,
                       temporal_uncertainty_ms=1300,provenance={'method':'proxy'}))]}}},
        clock_candidate=dict(origin_ms=100000,delta_s=1.25,sync_certified=False,
                             calibrated_sync_uncertainty_ms=None,production_usable=False),mapping={'head_id':'H1'})


def test_blink_dark_sample_not_promoted_to_final_off_or_continuous_history():
    out=build_bundle(sources())
    signal=out['records'][0]
    assert signal['certified_final_off'] is False
    assert signal['continuous_state_truth'] is False
    assert signal['trajectory_timestamp_ms'] is None
    assert out['continuous_lamp_truth_intervals']==[] and out['intersection_phase_truth'] is None


def test_window_edges_and_operator_duration_are_not_physical_switch_truth():
    out=build_bundle(sources())
    report=next(r for r in out['records'] if r['kind']=='operator_interval_report')
    assert report['annotated_interval_ms']==[100000,110000]
    assert report['start_switch_verified'] is report['end_switch_asserted'] is False
    assert not report['continuous_state_truth']


def test_clock_candidate_does_not_translate_video_brackets_to_json_or_certify_delay():
    out=build_bundle(sources())
    assert out['accepted_clock_transform'] is out['accepted_duration_prior'] is out['accepted_vehicle_signal_delay'] is None
    assert out['validation_session_count']==0
    assert all(r['independent_validation'] is False for r in out['records'])


def test_proxy_provenance_heuristic_confidence_and_uncertainty_remain_exact():
    data=sources();out=build_bundle(data)
    proxy=next(r for r in out['records'] if r['kind']=='vehicle_event_proxy')
    assert proxy['original_event']==data['proxy_queries']['queries']['A']['events'][0]['event']
    assert proxy['calibrated_lamp_probability'] is None
    assert proxy['independent_vehicle_truth'] is proxy['lamp_switch_observation'] is False
    assert proxy['matching_video_identity_hypothesis'] is True


def test_same_video_negative_association_not_a_causal_lamp_delay():
    out=build_bundle(sources())
    vehicle=next(r for r in out['records'] if r['kind']=='sampled_vehicle_motion')
    assert vehicle['vehicle_onset_minus_H1_appearance_s']==[-3,-1]
    assert vehicle['wholly_before_H1_appearance'] is True
    assert out['same_video_motion_before_H1_count']==1


def test_shared_head_reference_not_duplicated_per_vehicle_and_records_detached():
    data=sources();frozen=copy.deepcopy(data)
    out=build_bundle(data)
    assert out==build_bundle(data) and data==frozen
    assert out['counts']['sampled_signal_appearance']==2
    out['assumptions']['head_id']='mutated'
    out['records'][-1]['original_event']['timestamp_ms']=0
    assert data==frozen


@pytest.mark.parametrize('interval',[[2,1],[1,1],[True,2],[float('nan'),2]])
def test_invalid_intervals_refused(interval):
    data=sources();data['direct_video']['transitions'][0]['video_presentation_bracket_s']=interval
    with pytest.raises(ValueError,match='INVALID_OBSERVATION_INTERVAL'):build_bundle(data)


def test_frame_interval_mismatch_refused():
    data=sources();data['direct_video']['transitions'][0]['after_frame']['actual_media_time_s']=3
    with pytest.raises(ValueError,match='FRAME_BRACKET_MISMATCH'):build_bundle(data)


def test_duplicate_window_does_not_select_convenient_head_reference():
    data=sources();data['vehicle_video']['head_references']*=2
    with pytest.raises(ValueError,match='DUPLICATE_HEAD_REFERENCE'):build_bundle(data)


def test_duplicate_proxy_not_counted_twice():
    data=sources();data['proxy_queries']['queries']['A']['events']*=2
    with pytest.raises(ValueError,match='DUPLICATE_PROXY_EVENT_ID'):build_bundle(data)


def test_equal_proxy_timestamps_from_different_vehicles_are_preserved():
    data=sources();rows=data['proxy_queries']['queries']['A']['events']
    other=copy.deepcopy(rows[0]);other['event_id']='second';other['event']['source_track_id']=8
    other['vehicle_group_id']='vehicle8';rows.append(other)
    out=build_bundle(data)
    assert out['counts']['vehicle_event_proxy']==2


def test_preparation_cannot_import_fitting_or_inference():
    root=Path(__file__).resolve().parents[1]
    module=ast.parse((root/'app/experimental/calibration_bundle.py').read_text(encoding='utf-8'))
    imports=[node.module for node in ast.walk(module) if isinstance(node,ast.ImportFrom)]
    assert all(not name.startswith('app.') for name in imports)


@pytest.mark.local_evidence
def test_saved_real_bundle_and_source_seals():
    root=Path(__file__).resolve().parents[1];folder=root/'evidence/calibration_bundle_20261016'
    bundle=json.loads((folder/'calibration_bundle.json').read_text(encoding='utf-8'))
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert len(bundle['records'])==30
    assert bundle['counts']==dict(operator_interval_report=5,sampled_signal_appearance=9,
        sampled_vehicle_motion=8,vehicle_event_proxy=8)
    assert bundle['same_video_motion_before_H1_count']==2
    assert manifest['inference_calls']==manifest['video_trajectory_archive_bytes_read']==0
    assert len({r['record_id'] for r in bundle['records']})==30
    for source in manifest['sources'].values():
        assert hashlib.sha256((root/source['path']).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==source['sha256_lf']
    for name,digest in manifest['outputs'].items():
        assert hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
    metrics=json.loads((folder/'metric_eligibility.json').read_text(encoding='utf-8'))
    assert not metrics['metrics_evaluated'] and not metrics['predictions_loaded']
    for row in metrics['metrics'][:-1]:
        assert row['value'] is None and row['eligible_observations']==0 and row['reason']
    template=json.loads((folder/'independent_review_tasks.json').read_text(encoding='utf-8'))
    assert len(template['review_tasks'])==17 and not template['independent_truth_filled']
    assert all(t['independent_interval'] is None and t['independent_event_type'] is None for t in template['review_tasks'])
