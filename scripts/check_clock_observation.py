"""Bounded saved-evidence diagnostic. python -m scripts.check_clock_observation"""
import csv
import hashlib
import json
from pathlib import Path
import time

from app.experimental.clock_observation_check import (
    associate_same_video, conditional_display_check,
)

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / 'evidence/clock_observation_check_20261016'
BASE = 'd4be0f1dbff24003cdb88ad9794f413777940930'
SOURCES = {
    'confirmation': 'evidence/h1_confirmation_20261016/confirmation.json',
    'confirmation_manifest': 'evidence/h1_confirmation_20261016/manifest.json',
    'model': 'evidence/local_vehicle_registration_20261015/local_model.json',
    'registration': 'evidence/local_vehicle_registration_20261015/validation_result.json',
    'bundle': 'evidence/calibration_bundle_20261016/calibration_bundle.json',
    'bundle_manifest': 'evidence/calibration_bundle_20261016/manifest.json',
    'clock_source': 'evidence/camera_clock_provenance_20261016/user_confirmation.json',
    'clock_source_manifest': 'evidence/camera_clock_provenance_20261016/manifest.json',
}


def sha(data):
    return hashlib.sha256(data.replace(b'\r\n', b'\n')).hexdigest()


def main():
    started = time.monotonic()
    if FOLDER.exists():
        raise ValueError('OUTPUT_EXISTS_DO_NOT_OVERWRITE')
    values, seals, payloads = {}, {}, {}
    total = 0
    for name, relative in SOURCES.items():
        path = ROOT / relative
        if path.stat().st_size > 512 * 1024:
            raise ValueError('INPUT_FILE_RESOURCE_LIMIT')
        raw = path.read_bytes()
        total += len(raw)
        if total > 2 * 1024 * 1024 or time.monotonic()-started > 10:
            raise ValueError('INPUT_RESOURCE_LIMIT')
        payloads[name] = raw
        values[name] = json.loads(raw)
        seals[name] = dict(path=relative, sha256_lf=sha(raw))
    confirmation = values['confirmation']
    if hashlib.sha256(payloads['confirmation']).hexdigest() != values['confirmation_manifest']['confirmation_sha256']:
        raise ValueError('HISTORICAL_CONFIRMATION_SEAL_MISMATCH')
    for key in ['model', 'registration']:
        previous = confirmation['source_catalog']['model' if key == 'model' else 'validation']
        if previous['path'] != SOURCES[key] or previous['sha256_lf'] != seals[key]['sha256_lf']:
            raise ValueError('HISTORICAL_REGISTRATION_SEAL_MISMATCH')
    if hashlib.sha256(payloads['bundle']).hexdigest() != values['bundle_manifest']['outputs']['calibration_bundle.json']:
        raise ValueError('HISTORICAL_BUNDLE_SEAL_MISMATCH')
    previous = next(s for s in values['clock_source_manifest']['sources'] if s['path'] == SOURCES['clock_source'])
    if previous['sha256_lf'] != seals['clock_source']['sha256_lf']:
        raise ValueError('CLOCK_SOURCE_SEAL_MISMATCH')
    protocol = ROOT / 'docs/CLOCK_OBSERVATION_PROTOCOL_20261016.md'
    code_paths = ['app/experimental/clock_observation_check.py',
                  'scripts/check_clock_observation.py', 'tests/test_clock_observation_check.py']
    freeze = dict(base_sha=BASE, sources=seals, protocol_sha256_lf=sha(protocol.read_bytes()),
                  code_sha256_lf={p: sha((ROOT/p).read_bytes()) for p in code_paths},
                  budgets=dict(max_seconds=10, max_total_input_bytes=2*1024*1024,
                               max_file_bytes=512*1024, max_checker_runs=1),
                  frozen_before_calculation=True, previously_reviewed_development_data=True)
    FOLDER.mkdir()

    def save(name, data):
        (FOLDER/name).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')

    save('freeze.json', freeze)
    records = values['bundle']['records']
    if len(records) > 1000 or len(confirmation['local_raw_zone_anchors']) > 100:
        raise ValueError('RECORD_RESOURCE_LIMIT')
    clock = conditional_display_check(confirmation, values['model'], values['registration'])
    associations = associate_same_video(
        [r for r in records if r['kind'] == 'sampled_vehicle_motion'],
        [r for r in records if r['kind'] == 'sampled_signal_appearance' and 'window' in r],
        [r for r in records if r['kind'] == 'vehicle_event_proxy'])
    geometry = dict(anchors=confirmation['local_raw_zone_anchors'],
                    movement_mapping_proposals=confirmation['movement_mapping_proposals'],
                    support='previously checked frozen local image correspondences; NOT recomputed',
                    supplier_centroid_units='UNKNOWN', stop_line_geometry='UNKNOWN',
                    calibrated_joint_error_model=None,
                    saved_scaled_jacobian_singular_values=values['model']['scaled_jacobian_singular_values'])
    runtime = time.monotonic()-started
    if runtime > 10:
        save('unavailable.json', dict(status='UNAVAILABLE_TIME_BUDGET', runtime_s=runtime))
        raise ValueError('DIAGNOSTIC_TIME_BUDGET_EXCEEDED')
    result = dict(schema='clock-observation-diagnostic-v1', clock=clock,
                  geometry=geometry, same_video=associations,
                  clock_source=values['clock_source']['clock_source'],
                  joint_calibration_status='UNAVAILABLE_UNVERIFIED_NUISANCE_MODEL',
                  missing_inputs=['overlay rounding/update/exposure timing relative to detections',
                                  'independent identity/feature and coordinate transform uncertainty',
                                  'independent validation capture with observable signals'],
                  calibrated_vehicle_signal_delay=None, physical_section_state='UNKNOWN',
                  calibrated_lamp_probability=None, production_usable=False,
                  phase_fits=0, decoder_calls=0, event_extractions=0, raw_video_archive_bytes_read=0,
                  input_bytes_read=total, computation_runtime_s=runtime)
    save('result.json', result)
    with (FOLDER/'vehicle_associations.csv').open('w', encoding='utf-8', newline='') as handle:
        fields = ['window', 'track_id_hypothesis', 'motion_media_interval_s', 'head_media_interval_s',
                  'onset_minus_H1_appearance_s', 'relation', 'status', 'proxy_match_status']
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(associations['rows'])
    manifest = dict(base_sha=BASE, protocol_sha256_lf=freeze['protocol_sha256_lf'],
                    outputs={p.name: sha(p.read_bytes()) for p in sorted(FOLDER.iterdir()) if p.is_file()},
                    historical_seals_checked=True, inference_calls=0)
    save('manifest.json', manifest)
    print(json.dumps(dict(output=str(FOLDER), readouts=clock['readout_count'],
                          geometry_anchors=len(geometry['anchors']),
                          motions=associations['motion_count'], relations=associations['relation_counts'],
                          runtime_s=runtime, input_bytes=total)))


if __name__ == '__main__':
    main()
