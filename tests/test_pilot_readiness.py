import copy
import hashlib
import json
from pathlib import Path

import pytest

from app.experimental.phase_observation_bridge import REQUIRED
from app.experimental.pilot_readiness import EVIDENCE_FIELDS, VERSION, assess_pilot


def documented():
    return {'status': 'documented', 'source': 'external-review-required'}


def session(name, role):
    return dict(id=name, role=role, capture_id=name, intersection_id='I1', camera_id='C1',
                source_ids=[name + ':original'], previously_used_for_development=False,
                trajectory_source=documented(), independent_signal_source=documented(),
                synchronization={**documented(), 'uncertainty_ms': 250})


def complete_metadata():
    # Placeholders deliberately pass COMPLETENESS only. Never a scientific approval.
    return dict(schema=VERSION, sessions=[session('cal', 'calibration'), session('val', 'validation')],
                evidence={key: documented() for key in EVIDENCE_FIELDS},
                observation_model={key: 'supplied-not-numerically-validated' for key in REQUIRED},
                observation_parameter_sources={key: 'source-required-review' for key in REQUIRED},
                supplier_definitions={'required_by_model': False, 'status': 'UNKNOWN'},
                geometry={'required_by_model': False, 'status': 'UNKNOWN'})


def test_metadata_completeness_never_approves_inference():
    out = assess_pilot(complete_metadata())
    assert out['status'] == 'ready_for_independent_review'
    assert out['scientific_validation'] == 'NOT_PERFORMED'
    assert out['inference_performed'] is False
    assert out['physical_section'] == out['logical_phase'] == 'UNKNOWN'
    assert out['calibrated_lamp_probability'] is None


def test_disjoint_blocks_of_one_capture_are_not_independent_sessions():
    data = complete_metadata()
    data['sessions'][1].update(capture_id='cal', range_ms=[10000, 20000])
    data['sessions'][0]['range_ms'] = [0, 1000]
    out = assess_pilot(data)
    assert out['split_collisions'][0]['reasons'] == ['SAME_CONTINUOUS_CAPTURE']


def test_renamed_original_file_is_still_shared_and_development_counts():
    data = complete_metadata()
    data['sessions'].append(session('old', 'development'))
    data['sessions'][1]['source_ids'] = ['old:original']
    assert assess_pilot(data)['split_collisions'][0]['other'] == 'old'


def test_known_development_is_not_untouched_by_relabeling():
    data = complete_metadata()
    data['sessions'][1]['previously_used_for_development'] = True
    assert 'val:VALIDATION_ALREADY_USED_OR_USAGE_UNKNOWN' in assess_pilot(data)['problems']


@pytest.mark.parametrize('uncertainty', [None, -1, float('nan'), float('inf'), True])
def test_invalid_sync_uncertainty(uncertainty):
    data = complete_metadata()
    data['sessions'][0]['synchronization']['uncertainty_ms'] = uncertainty
    assert 'cal:SYNC_UNCERTAINTY_UNKNOWN_OR_INVALID' in assess_pilot(data)['problems']


def test_missing_parameters_do_not_import_synthetic_defaults():
    data = complete_metadata()
    data['observation_model'] = {}
    out = assess_pilot(data)
    assert out['missing_model_inputs'] == list(REQUIRED)


def test_parameter_values_alone_are_not_documented_calibration():
    data = complete_metadata()
    data['observation_parameter_sources'] = {}
    assert assess_pilot(data)['unsourced_model_inputs'] == list(REQUIRED)


def test_units_and_geometry_unknown_allowed_only_when_not_used():
    data = complete_metadata()
    data['geometry']['required_by_model'] = True
    assert 'REQUIRED_GEOMETRY_UNKNOWN' in assess_pilot(data)['problems']


def test_no_validation_session_and_no_mutation_or_annotations_consumed():
    data = complete_metadata()
    data['sessions'] = data['sessions'][:1]
    frozen = copy.deepcopy(data)
    result = assess_pilot(data)
    assert 'INDEPENDENT_VALIDATION_SESSION_NOT_REGISTERED' in result['problems']
    assert data == frozen
    data['annotations'] = {'fake_phase_truth': [1, 2, 3]}
    assert assess_pilot(data) == result


def test_unknown_roles_or_alias_session_ids_refused():
    data = complete_metadata()
    data['sessions'][1]['id'] = 'cal'
    with pytest.raises(ValueError, match='DUPLICATE_SESSION_ID'):
        assess_pilot(data)


@pytest.mark.local_evidence
def test_saved_real_intake_has_no_synthetic_parameters_and_reproducible_seals():
    root = Path(__file__).resolve().parents[1]
    folder = root / 'evidence/real_pilot_readiness_20261016'
    raw = (folder / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    saved = json.loads((folder / 'readiness.json').read_text(encoding='utf-8'))
    assert manifest['observation_model'] == {}
    assert all(s['role'] == 'development' for s in manifest['sessions'])
    assert saved['manifest_sha256'] == hashlib.sha256(raw).hexdigest()
    assert saved['base_sha'] == 'e537c525e605602a1146b8e98e916fa0feacdf8c'
    result = assess_pilot(manifest)
    for key, value in result.items():
        assert saved[key] == value
    assert result['status'] == 'incomplete'
    assert 'INDEPENDENT_VALIDATION_SESSION_NOT_REGISTERED' in result['problems']
    for name, digest in saved['reference_sha256_lf'].items():
        assert hashlib.sha256((root / name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() == digest
