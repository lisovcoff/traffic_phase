"""Checks on saved outputs; never reruns the real localizer or phase inference."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_localization_20261015'


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def test_frozen_code_and_input_hashes_match():
    seal=load(OUT/'code_config_seal.json')
    portable=load(OUT/'source_content_seal.json')['files']
    snapshots=load(ROOT/'evidence/release_20261018/historical_sources.json')['files']
    for name,digest in seal['files_sha256'].items():
        # Verify the experiment's exact recorded source, rather than requiring
        # future production fixes to retain the 2026-10-15 implementation forever.
        raw=(ROOT/snapshots[name]['snapshot'] if name in snapshots else ROOT/name).read_bytes()
        if name in portable:
            assert portable[name]['original_run_byte_sha256']==digest
            assert snapshots[name]['git_blob_sha1']==portable[name]['git_blob_sha1']
            assert hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()==portable[name]['canonical_lf_sha256']
        else:
            assert hashlib.sha256(raw).hexdigest()==digest


def test_seven_saved_legacy_candidates_preserve_all_recorded_attributes():
    source=load(ROOT/'evidence/event_signal_associations_20261015/vehicle_events.json')
    rows=load(OUT/'real_outputs.json')['rows']
    assert len(rows)==7
    for row in rows:
        original=next(e for e in source['events'] if e['event_type']=='RELEASE'
                      and e['source_track_id']==row['track_id'])
        duration,timestamp,confidence,separation=row['unchanged_default_seed']
        assert timestamp*1000==pytest.approx(original['timestamp_ms'],abs=.001)
        assert duration==original['provenance']['relative_low_speed_duration_s']
        assert separation==original['provenance']['image_speed_separation']
        assert min(.65,confidence)==original['confidence']
        assert row['result']['legacy_event']['timestamp_ms']==original['timestamp_ms']


def test_output_seal_and_unavailable_denominator_are_preserved():
    source=OUT/'real_outputs.json'
    assert hashlib.sha256(source.read_bytes()).hexdigest()==load(OUT/'real_output_seal.json')['output_sha256']
    outputs=load(source)
    comparison=load(OUT/'real_comparison.json')
    assert comparison['available']+comparison['unavailable']==7
    assert outputs['fits']==0 and outputs['phase_model_replays']==0
    assert not outputs['production_default_changed']
    for row in outputs['rows']:
        assert row['result']['physical']['estimated_state']=='UNKNOWN'
        if row['result']['status']=='unavailable':
            assert row['result']['localized_event'] is None
            assert row['result']['estimate']['abstention_reason']


def test_synthetic_truth_separate_and_gate_not_replaced_with_real_score():
    metrics=load(OUT/'synthetic_metrics.json')
    assert metrics['cases']==21
    assert metrics['gate_pass']
    assert metrics['expected_recovery']==9
    assert metrics['recovered']==9 and metrics['unavailable']==12
    inputs=load(OUT/'synthetic_inputs.json')
    assert all(set(row)=={'name','track'} for row in inputs)
    assert all('independent_world_onset_ms' not in row['track'] for row in inputs)
