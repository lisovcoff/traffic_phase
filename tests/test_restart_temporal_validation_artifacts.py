"""Read-only checks: never reruns source extraction or real inference."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_multicycle_validation_20261015'


def load(name):
    return json.loads((OUT/name).read_text(encoding='utf8'))


def sha(name):
    return hashlib.sha256((OUT/name).read_bytes()).hexdigest()


def test_all_new_cohort_ids_disjoint_from_prior_review_and_each_other():
    rows=load('selected_raw_tracks.json')
    excluded=set(load('exclusion_registry.json')['excluded_ids'])
    ids=[r['record']['id'] for r in rows]
    assert len(ids)==len(set(ids))==8
    assert not (set(ids)&excluded)
    for row in rows:
        raw=json.dumps(row['record'],sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        assert hashlib.sha256(raw).hexdigest()==row['lineage']['canonical_record_sha256']
        assert len(row['lineage']['window_indices'])==1


def test_frozen_algorithms_and_plan_not_tuned_after_validation():
    plan=load('plan.json')
    assert sha('plan.json')==(OUT/'plan.sha256').read_text().strip()
    snapshots=json.loads((ROOT/'evidence/release_20261018/historical_sources.json').read_text(encoding='utf8'))['files']
    for name,digest in plan['frozen_code_canonical_lf_sha256'].items():
        # Saved negative validation belongs to the frozen historical sources.
        raw=(ROOT/snapshots[name]['snapshot'] if name in snapshots else ROOT/name).read_bytes().replace(b'\r\n',b'\n')
        assert hashlib.sha256(raw).hexdigest()==digest
    assert load('scan_manifest.json')['complete_entry_sha256']==plan['archive']['complete_entry_sha256']


def test_output_and_annotation_seals_and_full_denominators():
    assert sha('frozen_event_outputs.json')==load('output_seal.json')['output_sha256']
    assert sha('visual_review.json')==(OUT/'visual_review.sha256').read_text().strip()
    assert sha('clock_anchor_review.json')==(OUT/'clock_anchor_review.sha256').read_text().strip()
    comparison=load('comparison.json')
    assert len(comparison['rows'])==8
    assert [r['observations'] for r in comparison['summary']]==[4,4]
    assert all(r['point_count_denominator']==r['observations'] for r in comparison['summary'])
    assert all(r['physical_state']=='UNKNOWN' for r in comparison['rows'])
    assert not comparison['production_promoted']


def test_sampling_unknown_distinct_from_clock_incompatibility():
    clock=load('clock_check.json')
    assert clock['A']['status']=='UNAVAILABLE_SOURCE_SUPPORT'
    assert clock['A']['conditional_clock_set_s'] is None
    assert clock['A']['nominal_candidate_in_conditional_set'] is None
    assert clock['B']['nominal_candidate_in_conditional_set'] is True
    assert clock['B']['calibrated_sync_uncertainty_ms'] is None
    assert len(load('clock_anchor_review.json')['unavailable'])==1


def test_mixed_results_and_before_green_counterexamples_remain_visible():
    report=load('comparison.json');a,b=report['summary']
    assert a['old_point_in_bracket']==2 and a['new_point_in_bracket']==1
    assert b['old_point_in_bracket']==0 and b['new_point_in_bracket']==2
    assert sum(r['independent_video_motion_wholly_before_green'] for r in report['rows'])==2
    assert report['integration_status']=='NOT_ACCEPTED_AS_CALIBRATED_SIGNAL_PERMISSION_OR_SWITCH_EVIDENCE'


def test_actual_adapter_does_not_double_count_reference_events_or_claim_exposure():
    artifact=load('evidence_adapter_queries.json')
    for query in artifact['queries'].values():
        assert query['counts']['events']==4
        assert query['counts']['known_vehicle_groups_with_eligible_evidence']==4
        assert len(query['restart_localization_adapter']['original_events_in_window'])==4
        assert query['restart_localization_adapter']['replacement_count_in_window']==4
        assert not query['restart_localization_adapter']['fallback_to_legacy_timestamp']
        assert query['observation_support']['status']=='UNKNOWN'
        assert query['physical_section']['estimated_state']=='UNKNOWN'
    assert artifact['legacy_likelihood_adapter']['phase_count'] is None
    assert artifact['legacy_likelihood_adapter']['reason_code']=='METHOD_DEPENDENCE_AND_EVENT_SIGNAL_DELAY_UNMODELLED'
