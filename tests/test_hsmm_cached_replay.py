import json
from pathlib import Path

import pytest

from app.core.v9.events import extract_timing_streams
from scripts.hsmm_recurrence_check import cached_bundle
from tests.test_v9_source_scope import track


def cache(tmp_path):
    bundle = extract_timing_streams([track()])
    value = dict(trajectory_count=bundle[8], event_count=bundle[9],
        analysis_base_timestamp_ms=bundle[7], recording_start_timestamp_ms=bundle[6],
        archive={'source_files': list(bundle[5])}, event_extraction=dict(
            evidence_policy='permission_per_stream', manual_marks_used_for_discovery=False,
            temporal_events=[e.to_dict() for e in bundle.temporal_events],
            quality_diagnostics=bundle.diagnostics))
    path = tmp_path/'cached_v9.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    return path, value, bundle


def test_lossless_event_bundle_restoration_uses_original_anchors_and_selection(tmp_path):
    path, original, bundle = cache(tmp_path)
    pred, restored = cached_bundle(path)
    assert pred == original and tuple(restored) == tuple(bundle)
    assert restored.permission_streams == bundle.permission_streams
    assert [e.to_dict() for e in restored.temporal_events] == [e.to_dict() for e in bundle.temporal_events]


@pytest.mark.parametrize('modification', ['evaluation', 'labels_used', 'selected_indices'])
def test_contaminated_or_different_cache_cannot_reach_fitting(tmp_path, modification):
    path, value, _ = cache(tmp_path)
    if modification == 'evaluation':
        value['evaluation'] = {'truth': 'forbidden'}
    elif modification == 'labels_used':
        value['event_extraction']['manual_marks_used_for_discovery'] = True
    else:
        value['event_extraction']['quality_diagnostics']['selected_event_indices'] = []
    path.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises((ValueError, AssertionError)):
        cached_bundle(path)
