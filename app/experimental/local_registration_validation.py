"""Frozen vehicle-image registration checks. No signal/event inference or fit.

Pixel allowances are declared localization assumptions, never probabilities.
Validation vehicles must be disjoint from training; missing images stay missing.
"""
import copy
import math

import numpy as np

from app.experimental.vehicle_clock_alignment import (
    _intersect, conditional_clock_set, predict, prepare_tracks,
)


def evaluate_registration(model, previous_model, records, annotations, plan):
    rows = annotations['rows']
    missing = annotations['unavailable']
    training = set(plan['training_tracks'])
    validation = {plan['validation_track'], *plan['additional_validation_tracks']}
    if training & validation:
        raise ValueError('TRAIN_VALIDATION_OVERLAP')
    if set(model['training_ids']) != training:
        raise ValueError('MODEL_TRAINING_SET_MISMATCH')
    expected = {(tid, t) for tid in validation for t in plan['media_times']}
    observed = [(r['track_id'], r['requested_media_s']) for r in rows+missing]
    if len(set(observed)) != len(observed) or set(observed) != expected:
        raise ValueError('INCOMPLETE_OR_DUPLICATE_VALIDATION_ACCOUNTING')
    if any(not r.get('reason') for r in missing):
        raise ValueError('MISSING_ABSTENTION_REASON')
    for row in rows:
        if any(k in row for k in ('phase', 'phase_label', 'release_timestamp_ms', 'signal_state')):
            raise ValueError('SIGNAL_EVENT_LABEL_FORBIDDEN')
        if (not math.isfinite(row['actual_media_pts_s'])
                or len(row['image_point_px']) != 2
                or not all(math.isfinite(x) for x in row['image_point_px'])):
            raise ValueError('INVALID_VIDEO_FEATURE')
    # Preparing only validation tracks ensures none of the scores reuse training observations.
    selected = [r for r in records if r['id'] in validation]
    if len({r['id'] for r in selected}) != len(selected) or {r['id'] for r in selected} != validation:
        raise ValueError('VALIDATION_RECORDS_MISMATCH')
    tracks = prepare_tracks(selected)
    by_track = []
    common = [model['common_observed_delta_bounds_s']]
    for record in selected:
        points = [r for r in rows if r['track_id'] == record['id']]
        if not points:
            by_track.append(dict(track_id=record['id'], status='UNAVAILABLE_NO_VISIBLE_POINTS'))
            continue
        target = np.asarray([r['image_point_px'] for r in points])
        before = predict(tracks, points, previous_model['homography'],
                         previous_model['delta_s'], previous_model['origin_ms'])
        after = predict(tracks, points, model['homography'], model['delta_s'], model['origin_ms'])
        old_errors = np.linalg.norm(before-target, axis=1)
        new_errors = np.linalg.norm(after-target, axis=1)
        clock = conditional_clock_set(model, record, points, plan['validation_localization_allowance_px'])
        common = _intersect(common, clock['delta_sets_s'])
        by_track.append(dict(track_id=record['id'], observations=len(points),
            old_errors_px=old_errors.tolist(), new_errors_px=new_errors.tolist(),
            old_max_error_px=float(max(old_errors)), new_max_error_px=float(max(new_errors)),
            new_rmse_px=float(np.sqrt(np.mean(new_errors**2))),
            status='PASS_DECLARED_PIXEL_ALLOWANCE' if max(new_errors) <= plan[
                'validation_localization_allowance_px'] else 'FAIL_DECLARED_PIXEL_ALLOWANCE',
            predicted_image_points_px=after.tolist(), conditional_clock=clock))
    training_pass = bool(model['optimizer_success'] and model['jacobian_rank'] == 9
        and not model['limit_active'] and model['training_max_error_px'] <= plan[
            'training_localization_allowance_px'])
    validation_pass = all(r['status'] == 'PASS_DECLARED_PIXEL_ALLOWANCE' for r in by_track)
    return dict(training_gate_pass=training_pass, validation_gate_pass=validation_pass,
        gate_status='PASS_DECLARED_LOCAL_IMAGE_CHECK' if training_pass and validation_pass
            else 'FAIL_DECLARED_LOCAL_IMAGE_CHECK',
        tracks=by_track, manual_points=len(rows), unavailable_points=copy.deepcopy(missing),
        joint_frozen_h_clock_sets_s=common if rows else None,
        clock_status=('UNAVAILABLE_NO_VISIBLE_POINTS' if not rows else
            'CONDITIONAL_FEASIBLE_SET' if common else 'INCONSISTENT_FROZEN_H_ASSUMPTIONS'),
        fitted_delta_in_joint_set=bool(rows) and any(a <= model['delta_s'] <= b for a,b in common),
        conditional_clock_semantics='intersection of declared50px frozen-H feasibility sets; '
            'NOT joint calibrated clock uncertainty; excludes geometry, identity, feature and shutter error',
        calibrated_sync_uncertainty_ms=None, production_usable=False, phase_fits=0,
        independent_untouched_holdout=False, physical_state='UNKNOWN')
