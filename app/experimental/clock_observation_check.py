"""Read-only conditional clock checks and same-video associations; never inference.

Display rounding models are hypothetical. Their feasible sets are not calibrated
clock intervals and do not include unknown overlay/processing/geometry error.
"""
from copy import deepcopy
import math


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('FINITE_NUMERIC_VALUE_REQUIRED')
    return value


def _interval(value):
    if len(value) != 2:
        raise ValueError('TWO_INTERVAL_ENDPOINTS_REQUIRED')
    lo, hi = map(_finite, value)
    if hi < lo:
        raise ValueError('REVERSED_INTERVAL')
    return lo, hi


def conditional_display_check(confirmation, frozen_model, registration):
    """Compare a saved candidate and frozen geometry sets, without selecting delta."""
    readouts = confirmation['overlay_readouts']
    if len(readouts) > 100:
        raise ValueError('READOUT_RESOURCE_LIMIT')
    candidate = _finite(frozen_model['delta_s'])
    origin = _finite(frozen_model['origin_ms'])
    saved = confirmation['clock_candidate']
    if saved['origin_ms'] != origin or saved['delta_s'] != candidate:
        raise ValueError('FROZEN_MODEL_MISMATCH')
    geometry = [_interval(s) for s in registration['joint_frozen_h_clock_sets_s']]
    rows = []
    seen = set()
    for row in readouts:
        if row['file'] in seen:
            raise ValueError('DUPLICATE_READOUT')
        seen.add(row['file'])
        pts = _finite(row['media_pts_s'])
        # Subtract the epoch before converting to seconds.
        centre = (_finite(row['interpreted_display_epoch_ms']) - origin) / 1000 - pts
        rows.append(dict(file=row['file'], media_pts_s=pts,
                         delta_for_exact_displayed_second_s=centre,
                         candidate_minus_displayed_second_s=candidate-centre))
    modes = []
    for mode, rounding in [('floor', (0, 1)), ('nearest', (-.5, .5))]:
        bounds = None
        if rows:
            bounds = [max(r['delta_for_exact_displayed_second_s']+rounding[0] for r in rows),
                      min(r['delta_for_exact_displayed_second_s']+rounding[1] for r in rows)]
        nonempty = bounds is not None and bounds[0] < bounds[1]
        intersections = []
        if nonempty:
            for lo, hi in geometry:
                left, right = max(lo, bounds[0]), min(hi, bounds[1])
                inclusive = right < bounds[1]  # saved geometry intervals are closed
                if left < right or (left == right and inclusive):
                    intersections.append(dict(bounds_s=[left, right], lower_inclusive=True,
                                              upper_inclusive=inclusive))
        contains = bool(nonempty and bounds[0] <= candidate < bounds[1])
        distance = None if not nonempty else max(bounds[0]-candidate, candidate-bounds[1], 0)
        modes.append(dict(rounding_model=mode,
                          conditional_delta_bounds_s=bounds if nonempty else None,
                          lower_inclusive=True, upper_inclusive=False,
                          status=('UNAVAILABLE_NO_READOUTS' if not rows else
                                  'CONDITIONALLY_FEASIBLE' if nonempty else
                                  'INCONSISTENT_UNDER_DECLARED_ASSUMPTIONS'),
                          candidate_in_set=contains if rows else None,
                          distance_to_set_closure_s=distance,
                          intersection_with_saved_frozen_geometry=intersections))
    return dict(readouts=rows, readout_count=len(rows),
                media_extent_s=[min(r['media_pts_s'] for r in rows),
                                max(r['media_pts_s'] for r in rows)] if rows else None,
                rounding_convention='UNKNOWN', conditional_models=modes,
                frozen_geometry_delta_sets_s=deepcopy(geometry),
                saved_candidate_delta_s=candidate,
                assumptions=['constant unit-scale clock', 'supplied UTC+5 interpretation',
                             'JSON detection and display refer to the same instant',
                             'zero unmodelled overlay/processing latency'],
                assumptions_verified=False, calibrated_sync_uncertainty_ms=None,
                accepted_json_video_clock_transform=None,
                joint_error_status='UNAVAILABLE_JOINT_GEOMETRY_CLOCK_IDENTITY_MODEL',
                causal_explanation='UNKNOWN', refit=False)


def associate_same_video(motions, appearances, proxies):
    """Retain every supplied motion. Join by capture/window, never by nearest time.

    These are sampled image-appearance differences, not causal signal delays.
    Logical phases/operator annotations and predicted phase errors are not inputs.
    """
    if max(len(motions), len(appearances), len(proxies)) > 1000:
        raise ValueError('ASSOCIATION_RESOURCE_LIMIT')
    ids = [r['record_id'] for r in motions+appearances+proxies]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_RECORD_ID')
    rows = []
    for motion in motions:
        lo, hi = _interval(motion['media_interval_s'])
        key = motion['capture_id'], motion['window']
        heads = [r for r in appearances if (r['capture_id'], r['window']) == key
                 and r['head_id'] == 'H1'
                 and r['event'] == 'MAIN_GREEN_AND_LATERAL_GREEN_APPEARANCE']
        matches = [r for r in proxies if (r['capture_id'], r['window']) == key
                   and r['original_event']['source_track_id'] == motion['track_id_hypothesis']]
        row = dict(motion_record_id=motion['record_id'], capture_id=key[0], window=key[1],
                   track_id_hypothesis=motion['track_id_hypothesis'],
                   identity_status=motion['identity_status'], motion_media_interval_s=[lo, hi],
                   head_record_ids=[r['record_id'] for r in heads],
                   status='AVAILABLE_SAME_VIDEO_ASSOCIATION' if len(heads) == 1 else
                          'UNAVAILABLE_HEAD_REFERENCE_MISSING' if not heads else
                          'UNAVAILABLE_HEAD_REFERENCE_AMBIGUOUS',
                   onset_minus_H1_appearance_s=None, relation='UNKNOWN',
                   proxy_record_ids=[r['record_id'] for r in matches],
                   proxy_match_status='UNIQUE_ID_HYPOTHESIS' if len(matches) == 1 else
                                      'UNAVAILABLE_MISSING_OR_AMBIGUOUS',
                   calibrated_vehicle_signal_delay_s=None, physical_section_state='UNKNOWN')
        if len(heads) == 1:
            head_lo, head_hi = _interval(heads[0]['media_interval_s'])
            difference = [lo-head_hi, hi-head_lo]
            row.update(head_media_interval_s=[head_lo, head_hi],
                       onset_minus_H1_appearance_s=difference,
                       relation='WHOLLY_BEFORE' if difference[1] < 0 else
                                'WHOLLY_AFTER' if difference[0] > 0 else
                                'OVERLAPPING_OR_TOUCHING')
        if len(matches) == 1:
            event = matches[0]['original_event']
            row['proxy_provenance'] = deepcopy({k: event.get(k) for k in
                ['timestamp_ms', 'evidence_method', 'movement', 'source_track_id', 'uncertainty']})
        rows.append(row)
    relations = {key: sum(r['relation'] == key for r in rows) for key in
                 ['WHOLLY_BEFORE', 'WHOLLY_AFTER', 'OVERLAPPING_OR_TOUCHING', 'UNKNOWN']}
    return dict(rows=rows, motion_count=len(rows), relation_counts=relations,
                available_association_count=sum(r['status'] == 'AVAILABLE_SAME_VIDEO_ASSOCIATION' for r in rows),
                media_extent_s=[min(r['motion_media_interval_s'][0] for r in rows),
                                max(r['motion_media_interval_s'][1] for r in rows)] if rows else None,
                causal_delay_model='UNAVAILABLE', calibrated_lamp_probability=None,
                semantics='sampled_same_video_associations_NOT_calibrated_onset_or_lamp_switch_intervals')
