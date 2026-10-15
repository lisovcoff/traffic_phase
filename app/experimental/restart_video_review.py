"""Descriptive join of sealed vehicle-image observations and saved events.

Not an extractor, signal model, clock calibration, or causal delay estimator.
The image bracket and conditional clock set have different uncertainty semantics.
"""
from __future__ import annotations

import math


def _interval(value):
    if (len(value) != 2 or not all(math.isfinite(x) for x in value)
            or value[1] < value[0]):
        raise ValueError('INVALID_INTERVAL')
    return list(value)


def compare_review(review, events, cohort, *, clock_certified=False):
    """Keep every preregistered track, including unavailable video observations.

    Signed differences are event media time minus video onset. Their ranges are
    descriptive interval arithmetic, NOT calibrated timing-error intervals.
    Occluded/censored onsets cannot silently become point observations.
    """
    if len(set(cohort)) != len(cohort):
        raise ValueError('DUPLICATE_COHORT_ID')
    rows = review['rows']
    ids = [r['track_id_hypothesis'] for r in rows]
    if len(set(ids)) != len(ids) or set(ids) != set(cohort):
        raise ValueError('REVIEW_COHORT_MISMATCH')
    result = []
    for tid in cohort:
        row = next(r for r in rows if r['track_id_hypothesis'] == tid)
        selected = [e for e in events if e['source_track_id'] == tid
                    and e['event_type'] == 'RELEASE' and e['selected_permission']]
        if len(selected) != 1:
            raise ValueError('EXPECTED_ONE_SELECTED_RELEASE')
        event = selected[0]
        out = dict(track_id=tid, video_object=row['video_object'],
                   event_index=event['event_index'], method=event['method'],
                   movement=event['movement'], timestamp_ms=event['timestamp_ms'],
                   track_fingerprint=event['track_fingerprint'],
                   identity_status=row['identity_status'],
                   timing_validation_status='UNAVAILABLE',
                   timing_validation_reasons=[], physical_state='UNKNOWN',
                   calibrated_lamp_probability=None)
        bracket = row.get('observed_onset_bracket_s')
        if bracket is None:
            out['timing_validation_reasons'].append('VIDEO_ONSET_CENSORED_OR_OCCLUDED')
        else:
            left, right = _interval(bracket)
            sustained = row.get('sustained_motion_media_s')
            if sustained is None or not math.isfinite(sustained) or sustained <= right:
                raise ValueError('MISSING_SUSTAINED_MOTION_SUPPORT')
            point = event['candidate_media_s']
            if not math.isfinite(point):
                raise ValueError('INVALID_EVENT_TIME')
            sets = [_interval(x) for x in event['conditional_media_sets_s']]
            out.update(video_onset_bracket_s=bracket,
                       candidate_event_media_s=point,
                       point_event_minus_onset_range_s=[point-right, point-left],
                       conditional_event_media_sets_s=sets,
                       conditional_event_minus_onset_sets_s=[
                           [a-right, b-left] for a, b in sets],
                       conditional_sets_overlap_video_bracket=any(
                           a <= right and b >= left for a, b in sets),
                       vehicle_localization_heuristic_radius_ms=event.get(
                           'vehicle_localization_heuristic_radius_ms'),
                       uncertainty_semantics='frozen-H conditional clock sets; excludes '
                           'joint geometry/clock error; video bracket is sampled visibility')
        if row['identity_status'] != 'INDEPENDENTLY_CONFIRMED':
            out['timing_validation_reasons'].append('TRACK_VIDEO_IDENTITY_PROVISIONAL')
        if not clock_certified:
            out['timing_validation_reasons'].append('JOINT_LOCAL_CLOCK_GEOMETRY_NOT_CALIBRATED')
        if not out['timing_validation_reasons']:
            out['timing_validation_status'] = 'COMPARABLE_VEHICLE_EVENT_ONLY'
        result.append(out)
    return result
