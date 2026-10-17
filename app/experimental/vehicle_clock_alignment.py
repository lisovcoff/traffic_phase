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


def inspect_registration_support(model, records):
    """Reject a projective horizon crossing the supplied observed-road support.

    A small training residual (even with a full-rank Jacobian) cannot validate
    extrapolation to other approaches. A plane visible in both image views must
    keep one homogeneous-denominator sign across its connected support. Opposite
    signs at observed points imply a zero inside their convex hull, including
    when every individually projected point happens to be finite.

    This checks only the supplied coordinate support, not vehicle identity,
    coplanarity, camera synchronization, pixel accuracy, or unobserved regions.
    It must be called with the broader intended road scope before using a local
    fit elsewhere. It never makes a clock transform production-usable.
    """
    h = np.asarray(model['homography'], dtype=float)
    if h.shape != (3, 3) or not np.isfinite(h).all() or np.linalg.matrix_rank(h) != 3:
        raise ValueError('INVALID_REGISTRATION_HOMOGRAPHY')
    row_norm = float(np.linalg.norm(h[2]))
    if row_norm == 0:
        raise ValueError('INVALID_REGISTRATION_HOMOGRAPHY')
    # Homographies are defined up to any nonzero scale, including a sign flip.
    denominator_row = h[2] / row_norm
    points = []
    track_ids = []
    for record in records:
        for detection in record.get('detections', []):
            x, y = detection.get('centroid_x'), detection.get('centroid_y')
            if (isinstance(x, bool) or isinstance(y, bool)
                    or not isinstance(x, (int, float)) or not isinstance(y, (int, float))
                    or not math.isfinite(x) or not math.isfinite(y)):
                raise ValueError('INVALID_REGISTRATION_SUPPORT_POINT')
            points.append((x, y, 1.0))
            track_ids.append(record.get('id'))
    result = dict(schema='registration-support-check-v1', observed_points=len(points),
                  support_scope='convex hull of supplied observed image features only',
                  accepted_json_video_clock_transform=None, production_usable=False,
                  scientific_validation='NOT_CERTIFIED', refit=False)
    if not points:
        return dict(result, status='UNAVAILABLE_NO_OBSERVED_ROAD_SUPPORT',
                    geometry_usable_on_supplied_support=False)
    values = np.asarray(points) @ denominator_row
    low, high = float(np.min(values)), float(np.max(values))
    tolerance = 1e-10
    crosses = low <= tolerance and high >= -tolerance
    witnesses = [dict(track_id=track_ids[i], point=list(points[i][:2]),
                      normalized_denominator=float(values[i]))
                 for i in (int(np.argmin(values)), int(np.argmax(values)))]
    return dict(result,
                status=('REJECTED_ROAD_HORIZON_CROSSING' if crosses
                        else 'GEOMETRY_FINITE_ON_SUPPLIED_SUPPORT_ONLY'),
                geometry_usable_on_supplied_support=not crosses,
                normalized_denominator_extent=[low, high], witnesses=witnesses)


def predict(track_map, observations, h, delta_s, origin_ms):
    # Subtract the epoch before floating-point clock arithmetic. A ~1e-8s
    # numerical derivative disappears when added to a ~1e12ms absolute time.
    relative = {key:np.c_[track[:,0]-origin_ms,track[:,1:]] for key,track in track_map.items()}
    features = [interpolate(relative[r['track_id']],1000*(r['actual_media_pts_s']+delta_s)) for r in observations]
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


def _intersect(left, right):
    pieces = []
    for a,b in left:
        for c,d in right:
            if max(a,c)<=min(b,d):
                pieces.append([max(a,c),min(b,d)])
    merged = []
    for a,b in sorted(pieces):
        if merged and a<=merged[-1][1]+1e-9:
            merged[-1][1]=max(b,merged[-1][1])
        else:
            merged.append([a,b])
    return merged


def conditional_clock_set(model, record, observations, radius_px):
    """Exact pixel-disk feasibility along supplied piecewise-linear features.

    Homography is FROZEN. Radius is a declared localization allowance, not a
    measured probability. This is neither joint geometry uncertainty nor a
    calibrated clock interval. No offset is selected or fitted here.
    """
    if not math.isfinite(radius_px) or radius_px<=0:
        raise ValueError('POSITIVE_LOCALIZATION_ALLOWANCE_REQUIRED')
    track = prepare_tracks([record])[record['id']].copy()
    track[:,0] -= model['origin_ms']
    h = np.asarray(model['homography'])
    common = [model['common_observed_delta_bounds_s']]
    per_observation = []
    for row in observations:
        if row['track_id']!=record['id']:
            raise ValueError('WRONG_TRACK_ID')
        target = np.asarray(row['image_point_px'])
        allowed = []
        for left,right in zip(track,track[1:]):
            if right[0]-left[0]>300:
                continue
            p=h @ np.r_[left[1:],1]
            d=h @ np.r_[right[1:]-left[1:],0]
            if p[2]*(p[2]+d[2])<=0:
                raise ValueError('PROJECTION_POLE_IN_SOURCE_SEGMENT')
            a=p[:2]*[2688,1520]-target*p[2]
            b=d[:2]*[2688,1520]-target*d[2]
            coefficients=np.array([b@b-radius_px**2*d[2]**2,
                2*(a@b-radius_px**2*p[2]*d[2]), a@a-radius_px**2*p[2]**2])
            qa,qb,qc=coefficients
            tolerance=32*np.finfo(float).eps*max(qb*qb,abs(4*qa*qc),1)
            discriminant=qb*qb-4*qa*qc
            if qa==0:
                roots=[] if qb==0 else [-qc/qb]
            elif discriminant < -tolerance:
                roots=[]
            else:
                sqrt_d=math.sqrt(max(0,discriminant))
                roots=[(-qb-sqrt_d)/(2*qa),(-qb+sqrt_d)/(2*qa)]
            cuts=sorted(set([0.,1.]+[float(x) for x in roots if 0<=x<=1]))
            # Keep isolated tangencies too, within floating-point arithmetic.
            q_tolerance=32*np.finfo(float).eps*max(np.max(np.abs(coefficients)),1)
            feasible=[(x,x) for x in cuts if abs(np.polyval(coefficients,x))<=q_tolerance]
            for lo,hi in zip(cuts,cuts[1:]):
                if np.polyval(coefficients,(lo+hi)/2)<=0:
                    feasible.append((lo,hi))
            for lo,hi in feasible:
                allowed.append([(left[0]+lo*(right[0]-left[0]))/1000-row['actual_media_pts_s'],
                                (left[0]+hi*(right[0]-left[0]))/1000-row['actual_media_pts_s']])
        allowed=_intersect([model['common_observed_delta_bounds_s']],allowed)
        per_observation.append(allowed)
        common=_intersect(common,allowed)
    return {'delta_sets_s':common,'per_observation_sets_s':per_observation,
        'frozen_candidate_in_set':any(a<=model['delta_s']<=b for a,b in common),
        'localization_allowance_px':radius_px,'homography_frozen':True,'refit':False,
        'semantics':'conditional feasible set only; supplied pixel allowance; excludes geometry/identity/shutter/clock uncertainty',
        'calibrated_sync_uncertainty_ms':None}
