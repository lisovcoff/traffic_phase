import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.product_result import build_product_result


def prediction():
    return dict(schedule_base_timestamp_ms=1000000, phase_model_selection={'selected_phase_count': 2},
                period_inference={'period_s': 20}, movement_streams={'a->b': 4, 'b->c': 1, 'c->a': 0},
                schedule=dict(phase_count=2, phase_names=['P', 'Q'], period_s=20,
                    raw_hsmm_segments=[[0, 10, 0], [12, 20, 1]],
                    baseline_segments=[[0, 10, 0], [10, 20, 1]],
                    stream_activity_by_phase=[{'stream': 'a->b', 'event_probability_by_phase': {'P': .8, 'Q': .2}},
                                              {'stream': 'b->c', 'event_probability_by_phase': {'P': .1, 'Q': .7}}]))


def test_three_observed_origins_are_not_complete_topology_or_hardware():
    out = build_product_result(prediction())
    assert out['observed_origin_count'] == 3
    assert out['complete_approach_count'] is None
    assert all(row['hardware_type'] == 'UNKNOWN' and row['additional_section_count'] is None
               for row in out['approaches'])
    assert out['physical_section']['estimated_state'] == 'UNKNOWN'


def test_shared_movement_signature_is_not_forced_to_one_phase():
    out = build_product_result(prediction())
    movement = out['approaches'][0]['movements'][0]
    assert movement['activity_scores_by_phase'] == {'P': .8, 'Q': .2}
    assert movement['activity_estimate']['level'] == 'activity'
    assert movement['activity_estimate']['calibrated_lamp_probability'] is None


def test_gaps_and_half_open_endpoints_do_not_use_baseline_or_modulo():
    out = build_product_result(prediction(), timestamps_s=[0, 9, 10, 11, 12, 20, 100])
    assert [q['logical_phase']['estimated_state'] for q in out['queries']] == ['P','P','UNKNOWN','UNKNOWN','Q','UNKNOWN','UNKNOWN']
    assert all(q['physical_section']['estimated_state'] == 'UNKNOWN' for q in out['queries'])
    assert out['history']['internal_gaps_s'] == [[10, 12]]
    assert out['history']['covered_seconds'] == 18
    assert out['history']['covered_fraction_within_extent'] == .9
    assert out['history']['local_observation_coverage'] == 'UNKNOWN'


def test_conflicting_history_fails_closed_via_common_query():
    data = prediction()
    data['schedule']['raw_hsmm_segments'] = [[0,10,0], [5,15,1]]
    out = build_product_result(data, timestamps_s=[7])
    assert out['history']['validation_error'] == 'OVERLAPPING_SEGMENTS'
    assert out['queries'][0]['logical_phase']['estimated_state'] == 'UNKNOWN'
    assert out['history']['covered_seconds'] == 0


def test_experimental_unavailable_is_explicit_and_never_falls_back():
    data = prediction()
    data['reconstruction_history'] = {'status': 'unavailable', 'reason': 'NO_SUPPORTED_HISTORY', 'segments': []}
    assert build_product_result(data, timestamps_s=[1])['queries'][0]['logical_phase']['estimated_state'] == 'P'
    out = build_product_result(data, timestamps_s=[1], history_source='experimental')
    assert out['queries'][0]['logical_phase']['abstention_reason'] == 'NO_SUPPORTED_HISTORY'


def test_invariants_and_detached_payload_preserve_input_exactly():
    data = prediction()
    frozen = copy.deepcopy(data)
    out = build_product_result(data)
    assert data == frozen
    for key in ('schedule', 'phase_model_selection', 'period_inference'):
        assert out['invariant_payload'][key] == data[key]
    out['invariant_payload']['schedule']['raw_hsmm_segments'][0][0] = 5
    assert data == frozen


def test_bijective_renaming_preserves_scores_queries_and_coverage():
    data = prediction()
    renamed = copy.deepcopy(data)
    rename = {'a->b':'southwest->island', 'b->c':'island->ramp', 'c->a':'ramp->southwest'}
    renamed['movement_streams'] = {rename[k]: v for k,v in data['movement_streams'].items()}
    for row in renamed['schedule']['stream_activity_by_phase']:
        row['stream'] = rename[row['stream']]
    one = build_product_result(data, timestamps_s=[1,11,15])
    two = build_product_result(renamed, timestamps_s=[1,11,15])
    assert one['queries'] == two['queries']
    assert one['history'] == two['history']
    assert two['observed_origin_count'] == 3
    scores = {r['movement']: r['activity_scores_by_phase'] for a in two['approaches'] for r in a['movements']}
    assert scores['southwest->island'] == {'P':.8, 'Q':.2}


def test_empty_demand_does_not_give_red_or_no_approach_claim():
    data = prediction()
    data['movement_streams'] = {}
    data['schedule']['stream_activity_by_phase'] = []
    out = build_product_result(data, timestamps_s=[1])
    assert out['observed_origin_count'] == 0 and out['complete_approach_count'] is None
    assert out['queries'][0]['logical_phase']['estimated_state'] == 'P'
    assert out['queries'][0]['physical_section']['estimated_state'] == 'UNKNOWN'


def test_four_origins_and_k4_are_not_capped_and_empty_signature_abstains():
    data = prediction()
    data['movement_streams']['d->a'] = 0
    data['schedule'].update(phase_count=4, phase_names=['P','Q','R','S'])
    data['schedule']['stream_activity_by_phase'].append({'stream':'d->a','event_probability_by_phase':{}})
    out = build_product_result(data)
    assert out['observed_origin_count'] == out['phase_count'] == 4
    assert out['approaches'][-1]['movements'][0]['activity_estimate']['estimated_state'] == 'UNKNOWN'


def test_legacy_turn_arrow_proposal_never_becomes_verified_hardware():
    data = prediction()
    data['physical_signal_plan'] = {'stages': [{'arrows': {'a->b': 'GREEN'}}]}
    out = build_product_result(data)
    assert out['phase_composition']['status'] == 'UNVERIFIED_ACTIVITY_SIGNATURE'
    assert all(a['hardware']['estimated_state'] == 'UNKNOWN' for a in out['approaches'])


def test_unparseable_labels_are_kept_without_invented_origin():
    data = prediction()
    data['movement_streams']['unknown'] = 2
    out = build_product_result(data)
    assert out['unassigned_movements'][0]['movement'] == 'unknown'


@pytest.mark.parametrize('timestamps', [[float('nan')], [True], [0]*2049])
def test_query_limits(timestamps):
    with pytest.raises(ValueError, match='TIMESTAMPS'):
        build_product_result(prediction(), timestamps_s=timestamps)


def test_duplicate_activity_is_not_silently_overwritten():
    data = prediction()
    data['schedule']['stream_activity_by_phase'] *= 2
    with pytest.raises(ValueError, match='DUPLICATE'):
        build_product_result(data)


def test_cli_export_needs_no_raw_trajectories_and_does_not_modify_prediction(tmp_path):
    source = tmp_path/'prediction.json'
    output = tmp_path/'product.json'
    raw = json.dumps(prediction()).encode()
    source.write_bytes(raw)
    script = Path(__file__).resolve().parents[1]/'scripts/export_product_result.py'
    result = subprocess.run([sys.executable,str(script),str(source),str(output),'--time-s','11'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == raw
    out = json.loads(output.read_text(encoding='utf-8'))
    assert out['inference_performed'] is False
    assert out['queries'][0]['logical_phase']['estimated_state'] == 'UNKNOWN'


@pytest.mark.local_evidence
def test_three_saved_exports_preserve_accepted_model_and_seals():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'evidence/product_result_20261016/invariants.json').read_text(encoding='utf-8'))
    assert len(manifest['runs']) == 3
    assert not manifest['new_fitting'] and not manifest['real_replay']
    assert [r['phase_count'] for r in manifest['runs']] == [3,2,3]
    for row in manifest['runs']:
        raw = (root/row['input']).read_bytes()
        exported = (root/row['output']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['input_sha256']
        assert hashlib.sha256(exported).hexdigest() == row['output_sha256']
        source, out = json.loads(raw), json.loads(exported)
        for key in ('schedule','phase_model_selection','period_inference'):
            assert source[key] == out['invariant_payload'][key]
        assert out['queries'][-1]['logical_phase']['estimated_state'] == 'UNKNOWN'
