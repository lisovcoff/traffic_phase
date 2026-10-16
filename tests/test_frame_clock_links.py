import copy

import pytest

from app.experimental.frame_clock_links import inspect_frame_clock_links


def manifest():
    return dict(schema='frame-clock-links-v1', capture_id='synthetic-contract-test',
                video_source_id='v', trajectory_source_id='j', source_reference='test fixture',
                timestamp_field='detections[].millis', association_basis='producer_frame_identity',
                rows=[dict(frame_id='f1', video_pts_ticks=3003, video_time_base=[1, 90000],
                           detection_timestamp_ms=1033, timestamp_uncertainty_ms=1,
                           frame_identity_reference='export row1', uncertainty_source='supplied test bound'),
                      dict(frame_id='f2', video_pts_ticks=9000, video_time_base=[1, 90000],
                           detection_timestamp_ms=1100, timestamp_uncertainty_ms=1,
                           frame_identity_reference='export row2', uncertainty_source='supplied test bound')])


def test_actual_pts_not_fps_and_exact_rational_intersection_without_certification():
    out = inspect_frame_clock_links(manifest())
    assert out['rows'][0]['video_pts_ms_rational'] == '1001/30'
    assert out['conditional_constant_epoch_offset_ms_rational'] == ['999', '30019/30']
    assert out['status'] == 'DECLARATIONS_READY_FOR_INDEPENDENT_REVIEW'
    assert out['accepted_json_video_clock_transform'] is out['calibrated_sync_uncertainty_ms'] is None
    assert not out['production_usable'] and out['physical_section_state'] == 'UNKNOWN'


def test_blank_template_is_unavailable_no_fabricated_zero_offset():
    d = manifest(); d['rows'] = []
    out = inspect_frame_clock_links(d)
    assert out['status'] == 'UNAVAILABLE_NO_FRAME_LINKS'
    assert out['conditional_constant_epoch_offset_ms_rational'] is None


def test_signed_presentation_timestamp_and_equal_millisecond_values_are_valid():
    d = manifest()
    d['rows'][0]['video_pts_ticks'] = -90
    d['rows'][1]['video_pts_ticks'] = 0
    d['rows'][0]['detection_timestamp_ms'] = 1000
    d['rows'][1]['detection_timestamp_ms'] = 1000
    out = inspect_frame_clock_links(d)
    assert out['rows'][0]['video_pts_ms_rational'] == '-1'
    assert out['status'] == 'DECLARATIONS_READY_FOR_INDEPENDENT_REVIEW'


def test_unknown_uncertainty_not_silently_treated_as_zero_or_dropped():
    d = manifest(); d['rows'][0]['timestamp_uncertainty_ms'] = None
    out = inspect_frame_clock_links(d)
    assert out['row_count'] == 2
    assert out['status'] == 'UNAVAILABLE_TIMESTAMP_UNCERTAINTY'
    assert out['conditional_constant_epoch_offset_ms_rational'] is None


def test_unsourced_uncertainty_and_provenance_cannot_enable_timing_model():
    d = manifest(); d['rows'][0]['uncertainty_source'] = ''
    assert inspect_frame_clock_links(d)['status'] == 'UNAVAILABLE_TIMESTAMP_UNCERTAINTY'
    d = manifest(); d['source_reference'] = None
    assert inspect_frame_clock_links(d)['status'] == 'UNAVAILABLE_SOURCE_PROVENANCE'


@pytest.mark.parametrize('basis', ['phase_labels', 'vehicle_motion', 'overlay_readout_only'])
def test_reject_alignment_from_phase_errors_motion_or_overlay_without_frame_identity(basis):
    d = manifest(); d['association_basis'] = basis
    with pytest.raises(ValueError, match='FRAME_IDENTITY_REQUIRED'):
        inspect_frame_clock_links(d)


@pytest.mark.parametrize('value', [True, float('nan'), -.1])
def test_bad_uncertainty_refused(value):
    d = manifest(); d['rows'][0]['timestamp_uncertainty_ms'] = value
    with pytest.raises(ValueError, match='INVALID_TIMESTAMP_UNCERTAINTY'):
        inspect_frame_clock_links(d)


def test_duplicate_and_unsorted_frame_links_refused():
    d = manifest(); d['rows'][1]['frame_id'] = 'f1'
    with pytest.raises(ValueError, match='DUPLICATE_FRAME_ID'):
        inspect_frame_clock_links(d)
    d = manifest(); d['rows'].reverse()
    with pytest.raises(ValueError, match='FRAME_SEQUENCE'):
        inspect_frame_clock_links(d)


def test_conflicting_pairs_report_inconsistency_without_fitting_drift():
    d = manifest(); d['rows'][1]['detection_timestamp_ms'] += 100
    out = inspect_frame_clock_links(d)
    assert out['status'] == 'INCONSISTENT_DECLARED_CONSTANT_CLOCK'
    assert out['conditional_constant_epoch_offset_ms_rational'] is None


def test_input_unchanged_and_resource_limit():
    d = manifest(); before = copy.deepcopy(d)
    inspect_frame_clock_links(d)
    assert d == before
    d['rows'] *= 501
    with pytest.raises(ValueError, match='RESOURCE_LIMIT'):
        inspect_frame_clock_links(d)
