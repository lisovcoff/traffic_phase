import copy
import json
from pathlib import Path

import pytest

from app.experimental.clock_observation_check import (
    associate_same_video, conditional_display_check,
)


def clock_inputs():
    return ({'clock_candidate': {'origin_ms': 1000000, 'delta_s': 1.25},
             'overlay_readouts': [{'file': 'one', 'media_pts_s': 10,
                                   'interpreted_display_epoch_ms': 1010000}]},
            {'origin_ms': 1000000, 'delta_s': 1.25},
            {'joint_frozen_h_clock_sets_s': [[1.05, 1.5]]})


def test_candidate_outside_both_conditional_models_does_not_select_new_offset():
    out = conditional_display_check(*clock_inputs())
    floor, nearest = out['conditional_models']
    assert floor['conditional_delta_bounds_s'] == [0, 1]
    assert nearest['conditional_delta_bounds_s'] == [-.5, .5]
    assert not floor['candidate_in_set'] and not nearest['candidate_in_set']
    assert floor['intersection_with_saved_frozen_geometry'] == []
    assert out['saved_candidate_delta_s'] == 1.25
    assert out['accepted_json_video_clock_transform'] is out['calibrated_sync_uncertainty_ms'] is None
    assert out['causal_explanation'] == 'UNKNOWN'


@pytest.mark.parametrize('candidate,in_set', [(0, True), (1, False), (-.001, False)])
def test_display_floor_is_half_open(candidate, in_set):
    c, m, g = clock_inputs()
    c['clock_candidate']['delta_s'] = m['delta_s'] = candidate
    out = conditional_display_check(c, m, g)
    assert out['conditional_models'][0]['candidate_in_set'] == in_set


def test_repeated_display_value_can_falsify_constant_clock_assumptions():
    c, m, g = clock_inputs()
    c['overlay_readouts'].append(dict(file='two', media_pts_s=12, interpreted_display_epoch_ms=1010000))
    out = conditional_display_check(c, m, g)
    assert all(x['status'] == 'INCONSISTENT_UNDER_DECLARED_ASSUMPTIONS' for x in out['conditional_models'])


def test_no_readout_is_unavailable_and_different_model_is_rejected():
    c, m, g = clock_inputs()
    c['overlay_readouts'] = []
    out = conditional_display_check(c, m, g)
    assert all(x['candidate_in_set'] is None for x in out['conditional_models'])
    m['delta_s'] += 1
    with pytest.raises(ValueError, match='MODEL_MISMATCH'):
        conditional_display_check(c, m, g)


@pytest.mark.parametrize('value', [True, float('nan'), float('inf')])
def test_nonfinite_time_refused(value):
    c, m, g = clock_inputs()
    c['overlay_readouts'][0]['media_pts_s'] = value
    with pytest.raises(ValueError, match='FINITE_NUMERIC'):
        conditional_display_check(c, m, g)


def motion(track=1):
    return dict(record_id=f'm{track}', capture_id='capture', window='A', track_id_hypothesis=track,
                media_interval_s=[8, 9], identity_status='PROVISIONAL')


def head():
    return dict(record_id='h', capture_id='capture', window='A', head_id='H1',
                event='MAIN_GREEN_AND_LATERAL_GREEN_APPEARANCE', media_interval_s=[10, 11])


def test_before_appearance_is_retained_not_clipped_to_positive_reaction_delay():
    out = associate_same_video([motion()], [head()], [])
    row = out['rows'][0]
    assert row['onset_minus_H1_appearance_s'] == [-3, -1]
    assert row['relation'] == 'WHOLLY_BEFORE'
    assert row['calibrated_vehicle_signal_delay_s'] is None
    assert row['physical_section_state'] == 'UNKNOWN'


def test_no_nearest_matching_for_missing_or_ambiguous_head():
    wrong = head(); wrong['capture_id'] = 'different'
    out = associate_same_video([motion()], [wrong], [])
    assert out['rows'][0]['status'] == 'UNAVAILABLE_HEAD_REFERENCE_MISSING'
    other = head(); other['record_id'] = 'h2'
    out = associate_same_video([motion()], [head(), other], [])
    assert out['rows'][0]['status'] == 'UNAVAILABLE_HEAD_REFERENCE_AMBIGUOUS'
    assert out['rows'][0]['onset_minus_H1_appearance_s'] is None


def test_empty_input_and_touching_intervals_do_not_fabricate_event_or_direction():
    assert associate_same_video([], [], [])['media_extent_s'] is None
    m = motion(); m['media_interval_s'] = [9, 10]
    assert associate_same_video([m], [head()], [])['rows'][0]['relation'] == 'OVERLAPPING_OR_TOUCHING'


def test_input_immutability_and_resource_limit():
    args = clock_inputs(); before = copy.deepcopy(args)
    conditional_display_check(*args)
    assert args == before
    with pytest.raises(ValueError, match='RESOURCE_LIMIT'):
        associate_same_video([motion()] * 1001, [], [])


def test_saved_inputs_retain_all_motions_and_existing_video_differences():
    root = Path(__file__).resolve().parents[1]
    bundle = json.loads((root/'evidence/calibration_bundle_20261016/calibration_bundle.json').read_text(encoding='utf-8'))
    records = bundle['records']
    motions = [r for r in records if r['kind'] == 'sampled_vehicle_motion']
    heads = [r for r in records if r['kind'] == 'sampled_signal_appearance' and 'window' in r]
    proxies = [r for r in records if r['kind'] == 'vehicle_event_proxy']
    out = associate_same_video(motions, heads, proxies)
    assert out['motion_count'] == out['available_association_count'] == 8
    assert out['relation_counts'] == dict(WHOLLY_BEFORE=2, WHOLLY_AFTER=5, OVERLAPPING_OR_TOUCHING=1, UNKNOWN=0)
    for row, original in zip(out['rows'], motions):
        assert row['motion_record_id'] == original['record_id']
        assert row['onset_minus_H1_appearance_s'] == pytest.approx(original['vehicle_onset_minus_H1_appearance_s'])
        assert row['proxy_match_status'] == 'UNIQUE_ID_HYPOTHESIS'
