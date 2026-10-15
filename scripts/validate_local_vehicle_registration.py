"""One read-only evaluation of a sealed image/clock fit and withheld points."""
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.experimental.local_registration_validation import evaluate_registration

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'evidence/local_vehicle_registration_20261015'


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    target=OUT/'validation_result.json'
    if target.exists():
        raise ValueError('FRESH_OUTPUT_REQUIRED_NO_VALIDATION_RETRY')
    start=time.perf_counter()
    plan=load(OUT/'plan.json')
    assert sha(OUT/'plan.json')==(OUT/'plan.sha256').read_text().strip()
    for name,digest in plan['input_sha256'].items():
        assert sha(ROOT/name)==digest,name
    seal=load(OUT/'fit_seal.json')
    assert sha(OUT/'local_model.json')==seal['model_sha256']
    assert sha(OUT/'training_points.json')==seal['training_points_sha256']
    assert sha(ROOT/'app/experimental/vehicle_clock_alignment.py')==seal['fit_code_sha256']
    assert sha(OUT/'validation_points.json')==(OUT/'validation_points.sha256').read_text().strip()
    model=load(OUT/'local_model.json')
    previous=load(ROOT/'evidence/vehicle_clock_alignment_20261015/corrected_training_model.json')
    records=load(ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json')
    annotations=load(OUT/'validation_points.json')
    assert annotations['training_model_seal']==seal
    result=evaluate_registration(model,previous,records,annotations,plan)
    result.update(model_sha256=seal['model_sha256'],
        annotation_sha256=sha(OUT/'validation_points.json'),
        plan_sha256=sha(OUT/'plan.json'), evaluation_invocations=1,
        runtime_s=time.perf_counter()-start)
    target.write_text(json.dumps(result,indent=2),encoding='utf8')
    (OUT/'validation_result.sha256').write_text(sha(target)+'\n',encoding='utf8')
    print(result['gate_status'], result['clock_status'])
    for row in result['tracks']:
        print(row['track_id'],row.get('observations'), 'old max',round(row.get('old_max_error_px',0),2),
              'new max',round(row.get('new_max_error_px',0),2),row['status'])
    print('Frozen-H conditional clock sets',result['joint_frozen_h_clock_sets_s'])
    print('Fitted delta inside all sets',result['fitted_delta_in_joint_set'])


if __name__=='__main__':
    main()
