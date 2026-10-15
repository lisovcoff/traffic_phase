"""Isolated image/clock calibration diagnostic, never phase inference.

The empirical homography relates supplied coordinates to manually reviewed video
features. It does not certify geometry, metric units, vehicle identity or clock
accuracy. Held-out observations are never accepted by fit_training.
"""
from __future__ import annotations

import copy
import math
import time

import numpy as np
from scipy.optimize import least_squares


def prepare_tracks(records):
    result = {}
    for row in records:
        key = row['id']
        if key in result:
            raise ValueError('DUPLICATE_TRACK_ID')
        points = sorted((d['millis'],d['centroid_x'],d['centroid_y']) for d in row['detections'])
        values = np.asarray(points,dtype=float)
        if values.ndim!=2 or values.shape[1]!=3 or len(values)<2 or not np.isfinite(values).all():
            raise ValueError('INVALID_SOURCE_FEATURES')
        if np.any(np.diff(values[:,0])<=0):
            raise ValueError('DUPLICATE_SOURCE_TIMESTAMP')
        result[key] = values
    return result


def interpolate(track, timestamp_ms, max_gap_ms=300):
    at = np.searchsorted(track[:,0],timestamp_ms)
    if at<len(track) and track[at,0]==timestamp_ms:
        return track[at,1:].copy()
    if at==0 or at==len(track):
        raise ValueError('OUTSIDE_SOURCE_TRACK')
    left,right = track[at-1],track[at]
    if right[0]-left[0]>max_gap_ms:
        raise ValueError('SOURCE_OBSERVATION_GAP')
    fraction = (timestamp_ms-left[0])/(right[0]-left[0])
    return left[1:] + fraction*(right[1:]-left[1:])


def project(points, homography, size=(2688,1520)):
    points = np.asarray(points,dtype=float)
    h = np.asarray(homography,dtype=float).reshape(3,3)
    mapped = np.c_[points,np.ones(len(points))] @ h.T
    if not np.isfinite(mapped).all() or np.any(np.abs(mapped[:,2])<1e-8):
        raise ValueError('SINGULAR_IMAGE_PROJECTION')
    return mapped[:,:2]/mapped[:,2,None]*np.asarray(size)


def predict(track_map, observations, h, delta_s, origin_ms):
    features = [interpolate(track_map[r['track_id']],origin_ms+1000*(r['actual_media_pts_s']+delta_s)) for r in observations]
    return project(features,h)


def fit_training(records, observations, *, training_ids, heldout_id, origin_ms,
                 delta_bounds=(-5,5), max_nfev=1000, max_seconds=15):
    if heldout_id in training_ids or any(r['track_id'] not in training_ids for r in observations):
        raise ValueError('HELDOUT_OBSERVATIONS_FORBIDDEN_IN_FIT')
    if len(observations)<6:
        raise ValueError('INSUFFICIENT_IMAGE_POINTS')
    if not all(math.isfinite(r['actual_media_pts_s']) and len(r['image_point_px'])==2 and all(math.isfinite(x) for x in r['image_point_px']) for r in observations):
        raise ValueError('INVALID_MANUAL_IMAGE_POINTS')
    if any(r['id'] not in training_ids for r in records):
        raise ValueError('HELDOUT_RECORDS_FORBIDDEN_IN_FIT')
    track_map = prepare_tracks(records)
    lower,upper = delta_bounds
    for row in observations:
        track = track_map[row['track_id']]
        lower = max(lower,(track[0,0]-origin_ms)/1000-row['actual_media_pts_s'])
        upper = min(upper,(track[-1,0]-origin_ms)/1000-row['actual_media_pts_s'])
    if not lower<0<upper:
        raise ValueError('INITIAL_CLOCK_OUTSIDE_COMMON_SUPPORT')
    target = np.asarray([r['image_point_px'] for r in observations],dtype=float)
    started = time.monotonic()

    def residual(parameters):
        if time.monotonic()-started>max_seconds:
            raise ValueError('CALIBRATION_TIME_BUDGET_EXCEEDED')
        h = np.r_[parameters[:8],1].reshape(3,3)
        return (predict(track_map,observations,h,parameters[8],origin_ms)-target).ravel()

    # One initialization and one solve. No grid, restarts, prior or phase labels.
    solved = least_squares(residual,[1,0,0,0,.8,.2,0,0,0],
        bounds=([-np.inf]*8+[lower],[np.inf]*8+[upper]),max_nfev=max_nfev,x_scale='jac')
    h = np.r_[solved.x[:8],1].reshape(3,3)
    errors = np.linalg.norm(solved.fun.reshape(-1,2),axis=1)
    norms = np.linalg.norm(solved.jac,axis=0)
    scaled = solved.jac/np.where(norms>0,norms,1)
    singular_values = np.linalg.svd(scaled,compute_uv=False)
    return {'schema':'vehicle-clock-diagnostic-v1','origin_ms':origin_ms,
        'homography':h.tolist(),'delta_s':float(solved.x[8]),
        'declared_delta_bounds_s':list(delta_bounds),'common_observed_delta_bounds_s':[lower,upper],
        'training_ids':list(training_ids),'heldout_id':heldout_id,
        'training_image_points':copy.deepcopy(observations),'training_errors_px':errors.tolist(),
        'training_max_error_px':float(np.max(errors)),'training_rmse_px':float(np.sqrt(np.mean(errors**2))),
        'scaled_jacobian_singular_values':singular_values.tolist(),'jacobian_rank':int(np.linalg.matrix_rank(solved.jac)),
        'optimizer_success':bool(solved.success),'optimizer_message':str(solved.message),
        'limit_active':bool(np.any(solved.active_mask)),'nfev':solved.nfev,
        'runtime_s':time.monotonic()-started,'calibrated_sync_uncertainty_ms':None,
        'sync_certified':False,'phase_labels_used':False,'production_usable':False}


def score_heldout(model, record, observations):
    if record['id']!=model['heldout_id'] or any(r['track_id']!=record['id'] for r in observations):
        raise ValueError('WRONG_HELDOUT_ID')
    predicted = predict(prepare_tracks([record]),observations,model['homography'],model['delta_s'],model['origin_ms'])
    errors = np.linalg.norm(predicted-np.asarray([r['image_point_px'] for r in observations]),axis=1)
    return {'predicted_image_points_px':predicted.tolist(),'errors_px':errors.tolist(),
            'max_error_px':float(np.max(errors)),'rmse_px':float(np.sqrt(np.mean(errors**2))),
            'refit':False,'sync_certified':False}
