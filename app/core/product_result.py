"""Read-only product view over an existing V9 prediction; no discovery or fitting.

Zone labels identify observed origins, not verified geometry/complete approaches.
Activity signatures remain scores, and hardware proposals remain unverified.
"""
from copy import deepcopy
import hashlib
import json
import math
from numbers import Real
from collections.abc import Mapping

from app.core.state_contract import StateEstimate, physical_estimate, prepare_logical_query

VERSION = 'traffic-phase-product-result-v1'


def _seal(value):
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':'), allow_nan=False).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()


def build_product_result(prediction, *, timestamps_s=(), history_source='accepted'):
    """Build a detached view. Times are relative to schedule_base_timestamp_ms.

    Preserves the original schedule/selection/period, including failed history
    validation. Queries use one validated common-contract snapshot, never a
    periodic fallback. This is an export adapter, not a new inference default.
    """
    if not isinstance(prediction, Mapping) or not isinstance(prediction.get('schedule'), Mapping):
        raise ValueError('PREDICTION_WITH_SCHEDULE_REQUIRED')
    schedule = prediction['schedule']
    times = list(timestamps_s)
    if len(times) > 2048 or any(isinstance(t, bool) or not isinstance(t, Real)
                              or not math.isfinite(t) for t in times):
        raise ValueError('INVALID_OR_EXCESSIVE_QUERY_TIMESTAMPS')
    rows = schedule.get('stream_activity_by_phase', [])
    counts = prediction.get('movement_streams', {})
    if not isinstance(rows, list) or not isinstance(counts, Mapping):
        raise ValueError('INVALID_MOVEMENT_INPUT')
    if len(rows) > 256 or len(counts) > 256:
        raise ValueError('MOVEMENT_EXPORT_BUDGET_EXCEEDED')
    if any(len(schedule.get(key, [])) > 100000 for key in ('raw_hsmm_segments', 'baseline_segments')
           if isinstance(schedule.get(key), list)):
        raise ValueError('HISTORY_EXPORT_BUDGET_EXCEEDED')
    activity = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get('stream'), str) or not row['stream'].strip():
            raise ValueError('INVALID_ACTIVITY_ROW')
        movement = row['stream']
        if movement in activity:
            raise ValueError('DUPLICATE_ACTIVITY_MOVEMENT')
        scores = row.get('event_probability_by_phase', {})
        if not isinstance(scores, Mapping) or any(isinstance(v, bool) or not isinstance(v, Real)
                or not math.isfinite(v) or not 0 <= v <= 1 for v in scores.values()):
            raise ValueError('INVALID_ACTIVITY_SCORE')
        activity[movement] = dict(scores)
    if any(not isinstance(m, str) or not m.strip() for m in counts):
        raise ValueError('INVALID_MOVEMENT_LABEL')
    movements = sorted(set(counts) | set(activity))
    if len(movements) > 256:
        raise ValueError('MOVEMENT_EXPORT_BUDGET_EXCEEDED')
    by_origin, unassigned = {}, []
    for movement in movements:
        parts = movement.split('->')
        # Preserve arbitrary zone names. No compass topology, straight/turn or
        # hardware classification can follow from this string operation.
        origin = parts[0].strip() if len(parts) == 2 and all(p.strip() for p in parts) else None
        item = dict(movement=movement, input_event_count=counts.get(movement),
                    activity_scores_by_phase=activity.get(movement, {}),
                    activity_estimate=StateEstimate(
                        'MODELLED_EVENT_ACTIVITY' if activity.get(movement) else 'UNKNOWN',
                        'activity', VERSION,
                        ('event_occupancy_score_NOT_lamp_probability',),
                        {'kind': 'aggregate_fitted_signature_NOT_local_observation'},
                        None if activity.get(movement) else 'NO_ACTIVITY_SIGNATURE').to_dict())
        if origin is None:
            unassigned.append(item)
        else:
            by_origin.setdefault(origin, []).append(item)
    query = prepare_logical_query(prediction, history_source=history_source)
    intervals = [list(row[:2]) for row in query.segments]
    extent = [intervals[0][0], intervals[-1][1]] if intervals else None
    covered = sum(b - a for a, b in intervals)
    gaps = [[a[1], b[0]] for a, b in zip(intervals, intervals[1:]) if b[0] > a[1]]
    queries = []
    for t in times:
        logical = query.at(t)
        queries.append(dict(timestamp_s=t, logical_phase=logical.to_dict(),
                            physical_section=physical_estimate('UNKNOWN', logical_support=logical).to_dict()))
    invariant = {key: deepcopy(prediction.get(key)) for key in
                 ('schedule', 'phase_model_selection', 'period_inference', 'schedule_base_timestamp_ms',
                  'analysis_base_timestamp_ms', 'event_base_timestamp_ms', 'recording_start_timestamp_ms')}
    return dict(schema=VERSION, inference_performed=False, scientific_validation='NOT_PERFORMED',
                invariant_payload=invariant, invariant_sha256=_seal(invariant),
                phase_count=schedule.get('phase_count'), period_s=schedule.get('period_s'),
                observed_origin_count=len(by_origin), complete_approach_count=None,
                origin_semantics='observed source-zone labels_NOT_verified_intersection_geometry',
                approaches=[dict(origin_zone=origin, movements=items,
                                hardware=physical_estimate('UNKNOWN').to_dict(),
                                hardware_type='UNKNOWN', additional_section_count=None)
                            for origin, items in sorted(by_origin.items())],
                unassigned_movements=unassigned,
                phase_composition=dict(status='UNVERIFIED_ACTIVITY_SIGNATURE',
                    reason='activity_scores_do_not_identify_permission_or_hardware',
                    legacy_plan_proposal=deepcopy(prediction.get('physical_signal_plan')),
                    proposal_semantics='legacy_hypothesis_NOT_verified_mapping_or_observed_lamps'),
                history=dict(source=query.segment_source, selection=history_source,
                    validation_error=query.validation_error, unavailable_reason=query.unavailable_reason,
                    coverage_semantics='model_history_NOT_camera_coverage_or_lamp_accuracy',
                    intervals_s=intervals, internal_gaps_s=gaps, extent_s=extent,
                    covered_seconds=covered,
                    covered_fraction_within_extent=covered/(extent[1]-extent[0]) if extent else None,
                    local_observation_coverage='UNKNOWN'),
                query_timebase=dict(unit='seconds_relative_to_schedule_anchor',
                                    anchor_ms=prediction.get('schedule_base_timestamp_ms')),
                queries=queries, physical_section=physical_estimate('UNKNOWN').to_dict(),
                calibrated_lamp_probability=None,
                limitations=['No events does not prove no approach or RED.',
                             'Turn activity does not prove an additional section.',
                             'Hardware types/counts and permissive/protected semantics need independent evidence.',
                             '2D.1 local extension reconstruction remains FAIL and opt-in.'])
