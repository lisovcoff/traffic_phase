import copy

import pytest

from app.experimental.local_registration_validation import evaluate_registration


def inputs():
    h = [[1,0,0],[0,1,0],[0,0,1]]
    model = dict(homography=h, delta_s=0, origin_ms=0, training_ids=[1],
        common_observed_delta_bounds_s=[-.1,.1], optimizer_success=True,
        jacobian_rank=9, limit_active=False, training_max_error_px=0)
    records = [dict(id=2,detections=[dict(millis=t,centroid_x=t/1000,centroid_y=.5)
        for t in [0,100,200,300,400]])]
    annotations = dict(rows=[dict(track_id=2,requested_media_s=.2,actual_media_pts_s=.2,
        image_point_px=[.2*2688,.5*1520])],unavailable=[])
    plan = dict(training_tracks=[1],validation_track=2,additional_validation_tracks=[],
        media_times=[.2],training_localization_allowance_px=30,validation_localization_allowance_px=50)
    return model,records,annotations,plan


def test_frozen_validation_preserves_inputs_and_does_not_certify_clock():
    m,r,a,p = inputs()
    before = copy.deepcopy((m,r,a,p))
    x = evaluate_registration(m,m,r,a,p)
    assert x['gate_status']=='PASS_DECLARED_LOCAL_IMAGE_CHECK'
    assert x['tracks'][0]['new_max_error_px']==0
    assert x['fitted_delta_in_joint_set']
    assert x['calibrated_sync_uncertainty_ms'] is None
    assert not x['production_usable']
    assert x['physical_state']=='UNKNOWN'
    assert (m,r,a,p)==before


def test_training_vehicle_cannot_be_validation():
    m,r,a,p = inputs();p['additional_validation_tracks']=[1]
    with pytest.raises(ValueError,match='OVERLAP'):
        evaluate_registration(m,m,r,a,p)


@pytest.mark.parametrize('key',['phase','phase_label','release_timestamp_ms','signal_state'])
def test_annotation_channel_refuses_signal_labels(key):
    m,r,a,p = inputs();a['rows'][0][key]='forbidden'
    with pytest.raises(ValueError,match='LABEL_FORBIDDEN'):
        evaluate_registration(m,m,r,a,p)


def test_missing_frame_remains_unavailable_and_gate_does_not_pass():
    m,r,a,p = inputs();a['rows']=[]
    a['unavailable']=[dict(track_id=2,requested_media_s=.2,reason='BODY_CLIPPED')]
    x=evaluate_registration(m,m,r,a,p)
    assert not x['validation_gate_pass']
    assert x['manual_points']==0
    assert x['unavailable_points'][0]['reason']=='BODY_CLIPPED'
    assert x['joint_frozen_h_clock_sets_s'] is None
    assert x['clock_status']=='UNAVAILABLE_NO_VISIBLE_POINTS'


def test_silent_dropped_frame_is_rejected():
    m,r,a,p = inputs();a['rows']=[]
    with pytest.raises(ValueError,match='ACCOUNTING'):
        evaluate_registration(m,m,r,a,p)


def test_pixel_failure_is_retained_without_offset_retry():
    m,r,a,p=inputs();a['rows'][0]['image_point_px'][0]+=200
    x=evaluate_registration(m,m,r,a,p)
    assert x['gate_status']=='FAIL_DECLARED_LOCAL_IMAGE_CHECK'
    assert x['tracks'][0]['new_max_error_px']==200
    assert not x['fitted_delta_in_joint_set']
    assert m['delta_s']==0  # An alternative offset can be feasible; no refit occurs.


def test_existing_restart_proxy_can_precede_generated_vehicle_motion():
    """Post-validation mechanism witness, NOT a newly passing recovery gate.

    Vehicle truth is constant until20s; detections have deterministic localization
    jitter. Existing symmetric smoothing spreads future motion backwards in time.
    Keep this behavior documented until a separately validated timing fix exists.
    """
    import numpy as np
    from app.core.v9.events import _kinematic_release_candidate

    detections = [dict(millis=int(round(t*1000)),
        centroid_x=.3+.01*max(0,t-20)+1e-5*np.sin(3*t),centroid_y=.5)
        for t in np.arange(0,40.01,.1)]
    result = _kinematic_release_candidate(detections,0,40000)
    assert result is not None
    assert result[1] < 20
    # This test demonstrates an early heuristic proxy; no signal truth is inferred.


def test_saved_fit_seal_and_validation_account_for_all_points():
    import hashlib
    import json
    from pathlib import Path

    p=Path(__file__).resolve().parents[1]/'evidence/local_vehicle_registration_20261015'
    seal=json.loads((p/'fit_seal.json').read_text())
    assert hashlib.sha256((p/'local_model.json').read_bytes()).hexdigest()==seal['model_sha256']
    annotations=json.loads((p/'validation_points.json').read_text())
    assert annotations['training_model_seal']==seal
    assert len(annotations['rows'])+len(annotations['unavailable'])==20
    result=json.loads((p/'validation_result.json').read_text())
    assert len(result['tracks'])==4
    assert result['evaluation_invocations']==1
    assert not result['production_usable']
