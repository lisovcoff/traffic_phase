import copy

from app.experimental.temporal_validation_clock import check_frozen_window


def data(step):
    model=dict(origin_ms=0,homography=[[1,0,0],[0,1,0],[0,0,1]],delta_s=0,
               declared_delta_bounds_s=[-.1,.1],common_observed_delta_bounds_s=[0,.01])
    record=dict(id=1,detections=[dict(millis=t,centroid_x=t/1000,centroid_y=.5)
                                for t in range(0,3001,step)])
    point=dict(track_id=1,actual_media_pts_s=1.5,image_point_px=[1.5*2688,.5*1520],
               localization_allowance_px=50)
    return model,record,point


def test_complete_source_domain_constrains_clock_without_refit():
    m,r,p=data(100);before=copy.deepcopy((m,r,p))
    out=check_frozen_window(m,[r],[p])
    assert out['nominal_candidate_in_conditional_set']
    assert out['fit_calls']==0 and out['calibrated_sync_uncertainty_ms'] is None
    assert (m,r,p)==before


def test_one_second_missing_observations_do_not_falsify_clock():
    m,r,p=data(1000)
    out=check_frozen_window(m,[r],[p])
    assert out['status']=='UNAVAILABLE_SOURCE_SUPPORT'
    assert out['conditional_clock_set_s'] is None
    assert out['nominal_candidate_in_conditional_set'] is None
    assert out['rows'][0]['nominal_prediction_reason']=='SOURCE_OBSERVATION_GAP'


def test_bad_geometry_with_full_support_is_distinguishable_from_missing_data():
    m,r,p=data(100);p['image_point_px'][1]+=200
    out=check_frozen_window(m,[r],[p])
    assert out['status']=='FROZEN_CLOCK_INCOMPATIBLE'
    assert out['conditional_clock_set_s']==[]


def test_prior_training_track_availability_not_a_new_clock_prior():
    m,r,p=data(100);m['common_observed_delta_bounds_s']=[.05,.08]
    out=check_frozen_window(m,[r],[p])
    assert out['nominal_candidate_in_conditional_set']
