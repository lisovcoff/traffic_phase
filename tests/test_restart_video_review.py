import copy

import pytest

from app.experimental.restart_video_review import compare_review


def inputs():
    review = {'rows': [dict(track_id_hypothesis=1, video_object='car',
        identity_status='PROVISIONAL', observed_onset_bracket_s=[10., 11.],
        sustained_motion_media_s=12.)]}
    events = [dict(source_track_id=1, event_type='RELEASE', selected_permission=True,
        event_index=3, method='proxy', movement='arbitrary-name', timestamp_ms=1000,
        track_fingerprint='abc', candidate_media_s=9.,
        conditional_media_sets_s=[[8., 9.5]],
        vehicle_localization_heuristic_radius_ms=1300)]
    return review, events


def test_interval_arithmetic_does_not_claim_certified_timing_or_lamp():
    r, e = inputs()
    before = copy.deepcopy((r, e))
    out = compare_review(r, e, [1])[0]
    assert out['point_event_minus_onset_range_s'] == [-2., -1.]
    assert out['conditional_event_minus_onset_sets_s'] == [[-3., -.5]]
    assert not out['conditional_sets_overlap_video_bracket']
    assert out['timing_validation_status'] == 'UNAVAILABLE'
    assert out['physical_state'] == 'UNKNOWN'
    assert out['calibrated_lamp_probability'] is None
    assert (r, e) == before


def test_occluded_onset_keeps_cohort_and_abstains():
    r, e = inputs()
    r['rows'][0]['observed_onset_bracket_s'] = None
    out = compare_review(r, e, [1])[0]
    assert 'VIDEO_ONSET_CENSORED_OR_OCCLUDED' in out['timing_validation_reasons']
    assert 'point_event_minus_onset_range_s' not in out


@pytest.mark.parametrize('bracket', [[11, 10], [float('nan'), 11], [10, float('inf')]])
def test_invalid_brackets_rejected(bracket):
    r, e = inputs()
    r['rows'][0]['observed_onset_bracket_s'] = bracket
    with pytest.raises(ValueError, match='INVALID_INTERVAL'):
        compare_review(r, e, [1])


def test_missing_or_duplicate_track_cannot_disappear():
    r, e = inputs()
    with pytest.raises(ValueError, match='COHORT'):
        compare_review(r, e, [1, 2])
    with pytest.raises(ValueError, match='ONE_SELECTED_RELEASE'):
        compare_review(r, e+e, [1])


def test_single_frame_motion_is_not_sustained_support():
    r, e = inputs()
    r['rows'][0]['sustained_motion_media_s'] = 11
    with pytest.raises(ValueError, match='SUSTAINED'):
        compare_review(r, e, [1])


def test_bijective_movement_rename_preserves_result():
    r, e = inputs()
    a = compare_review(r, e, [1])[0]
    e[0]['movement'] = 'renamed'
    b = compare_review(r, e, [1])[0]
    assert {k:v for k,v in a.items() if k != 'movement'} == {
        k:v for k,v in b.items() if k != 'movement'}


@pytest.mark.local_evidence
def test_actual_sealed_review_has_entire_preregistered_cohort():
    import hashlib
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    folder = root/'evidence/seven_restart_review_20261015'
    plan = json.loads((folder/'plan.json').read_text())
    review = json.loads((folder/'visual_review.json').read_text())
    assert hashlib.sha256((folder/'visual_review.json').read_bytes()).hexdigest() == (
        folder/'visual_review.sha256').read_text().strip()
    events = json.loads((root/'evidence/event_signal_associations_20261015/analysis/associations.json').read_text())['events']
    rows = compare_review(review, events, plan['cohort'])
    assert len(rows) == 7
    assert all(r['physical_state']=='UNKNOWN' for r in rows)
    assert all(r['timing_validation_status']=='UNAVAILABLE' for r in rows)
