"""Descriptive arithmetic on sealed evidence; never fits or extracts events.

--verify checks reproducibility of the saved comparison without rewriting it.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.experimental.restart_video_review import compare_review

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/local_vehicle_registration_20261015'


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    model=load(OUT/'local_model.json')
    seal=load(OUT/'fit_seal.json')
    assert sha(OUT/'local_model.json')==seal['model_sha256']
    val=load(OUT/'validation_result.json')
    assert sha(OUT/'validation_result.json')==(OUT/'validation_result.sha256').read_text().strip()
    if not(val['validation_gate_pass'] and val['fitted_delta_in_joint_set']):
        raise ValueError('LOCAL_REGISTRATION_UNAVAILABLE')
    source=ROOT/'evidence/event_signal_associations_20261015/analysis/associations.json'
    events=copy.deepcopy(load(source)['events'])
    for event in events:
        relative=(event['timestamp_ms']-model['origin_ms'])/1000
        event['candidate_media_s']=relative-model['delta_s']
        event['conditional_media_sets_s']=[[relative-b,relative-a]
            for a,b in val['joint_frozen_h_clock_sets_s']]
    review_path=ROOT/'evidence/seven_restart_review_20261015/visual_review.json'
    rows=compare_review(load(review_path),events,load(OUT/'plan.json')['cohort'])
    result=dict(rows=rows,phase_fits=0,event_extractions=0,
        input_events_sha256=sha(source),review_sha256=sha(review_path),
        model_sha256=sha(OUT/'local_model.json'),validation_sha256=sha(OUT/'validation_result.json'),
        semantics='descriptive vehicle timing under locally checked frozen geometry; not calibrated event-error intervals or lamp accuracy',
        head_mapping='operator-confirmed video-relative directions; no independent protected/permissive certification')
    target=OUT/'release_comparison.json'
    if '--verify' in sys.argv:
        assert result==load(target),'SAVED_COMPARISON_MISMATCH'
        assert sha(target)==(OUT/'release_comparison.sha256').read_text().strip()
        print('Saved7-event comparison reproduced; no files rewritten, no calibration rerun')
    else:
        if target.exists():
            raise ValueError('FRESH_OUTPUT_REQUIRED')
        target.write_text(json.dumps(result,indent=2),encoding='utf8')
        (OUT/'release_comparison.sha256').write_text(sha(target)+'\n',encoding='utf8')


if __name__=='__main__':
    main()
