"""Calibration guards only; no phase fitting or real data."""
import copy

import numpy as np
import pytest

from app.experimental.vehicle_clock_alignment import fit_training, interpolate, prepare_tracks, project, predict, conditional_clock_set


def track():
    return {'id':1,'detections':[{'millis':1000,'centroid_x':.1,'centroid_y':.2},
                                {'millis':1200,'centroid_x':.3,'centroid_y':.4}]}


def test_raw_inputs_immutable_and_empirical_coordinates_do_not_claim_units():
    row=track();before=copy.deepcopy(row)
    prepared=prepare_tracks([row])[1]
    assert np.allclose(interpolate(prepared,1100),[.2,.3])
    assert row==before


def test_unobserved_gap_and_out_of_range_not_interpolated():
    prepared=prepare_tracks([track()])[1]
    with pytest.raises(ValueError,match='SOURCE_OBSERVATION_GAP'):
        interpolate(prepared,1100,max_gap_ms=150)
    with pytest.raises(ValueError,match='OUTSIDE_SOURCE_TRACK'):
        interpolate(prepared,999)


def test_duplicate_detection_not_silently_averaged():
    row=track();row['detections'].append(copy.deepcopy(row['detections'][0]))
    with pytest.raises(ValueError,match='DUPLICATE_SOURCE_TIMESTAMP'):
        prepare_tracks([row])


def test_heldout_video_observation_cannot_enter_training():
    with pytest.raises(ValueError,match='HELDOUT_OBSERVATIONS_FORBIDDEN'):
        fit_training([track()],[{'track_id':2}],training_ids=[1],heldout_id=2,origin_ms=0)


def test_projection_rejects_singularity_instead_of_fabricated_point():
    with pytest.raises(ValueError,match='SINGULAR_IMAGE_PROJECTION'):
        project([[0,0]],[[1,0,0],[0,1,0],[0,0,0]])


def test_large_epoch_does_not_erase_clock_derivative():
    epoch=1740632395000
    points=np.array([[epoch,.1,.2],[epoch+200,.3,.4]])
    rows=[{'track_id':1,'actual_media_pts_s':.1}]
    a=predict({1:points},rows,np.eye(3),0,epoch)
    b=predict({1:points},rows,np.eye(3),1.49e-8,epoch)
    assert np.linalg.norm(b-a)>1e-6


@pytest.mark.parametrize('epoch',[0,1740632395000])
def test_independent_curved_tracks_recover_known_clock_at_either_epoch(epoch):
    records=[]
    for key in (1,2):
        detections=[]
        for millis in range(0,10001,100):
            t=millis/1000
            x,y=(.05+.04*t+.002*t*t,.4-.01*t+.004*t*t) if key==1 else (.8-.03*t+.001*t*t,.2+.06*t-.0015*t*t)
            detections.append({'millis':epoch+millis,'centroid_x':x,'centroid_y':y})
        records.append({'id':key,'detections':detections})
    rows=[{'track_id':key,'actual_media_pts_s':t,'image_point_px':[0,0]} for key in (1,2) for t in (1.4,2.4,3.4,4.4,5.4,6.4,7.4)]
    # Independent analytic observations, not produced by the fitted predictor.
    for row in rows:
        t=row['actual_media_pts_s']+.4
        x,y=(.05+.04*t+.002*t*t,.4-.01*t+.004*t*t) if row['track_id']==1 else (.8-.03*t+.001*t*t,.2+.06*t-.0015*t*t)
        row['image_point_px']=[2688*x,1520*y]
    out=fit_training(records,rows,training_ids=[1,2],heldout_id=3,origin_ms=epoch)
    assert abs(out['delta_s']-.4)<.01
    assert out['training_max_error_px']<.01
    assert out['sync_certified'] is False


def test_frozen_geometry_clock_set_matches_known_pixel_disk_without_refit():
    model={'homography':np.eye(3).tolist(),'origin_ms':0,'delta_s':0,
           'common_observed_delta_bounds_s':[-.1,.1]}
    row=track()
    allowed=conditional_clock_set(model,row,[{'track_id':1,'actual_media_pts_s':1.1,
        'image_point_px':[.2*2688,.3*1520]}],30)
    width=30/np.hypot(2688,1520)
    assert np.allclose(allowed['delta_sets_s'],[[-width,width]])
    assert allowed['frozen_candidate_in_set'] and not allowed['refit']
    assert allowed['calibrated_sync_uncertainty_ms'] is None


def test_stationary_vehicle_does_not_invent_clock_precision():
    row=track();row['detections'][1].update(centroid_x=.1,centroid_y=.2)
    model={'homography':np.eye(3).tolist(),'origin_ms':0,'delta_s':0,
           'common_observed_delta_bounds_s':[-.1,.1]}
    result=conditional_clock_set(model,row,[{'track_id':1,'actual_media_pts_s':1.1,
        'image_point_px':[.1*2688,.2*1520]}],30)
    assert np.allclose(result['delta_sets_s'],[[-.1,.1]])


def test_isolated_tangency_is_not_silently_removed_from_feasible_set():
    row=track();row['detections'][1]['centroid_y']=.2
    model={'homography':np.eye(3).tolist(),'origin_ms':0,'delta_s':0,
           'common_observed_delta_bounds_s':[-.1,.1]}
    result=conditional_clock_set(model,row,[{'track_id':1,'actual_media_pts_s':1.1,
        'image_point_px':[.2*2688,.2*1520+30]}],30)
    assert result['delta_sets_s']
    assert abs(result['delta_sets_s'][0][0])<1e-8
    assert abs(result['delta_sets_s'][0][1])<1e-8
