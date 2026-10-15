"""Evaluation adapter for operator-labelled phase durations; never used by inference.

Window edges are censoring, not switches. Small or large two-label overlaps
remain explicit endpoint discrepancies; their rounded midpoint is only a point
diagnostic convention. Gaps split evaluation blocks. No offset is fitted.
"""
from __future__ import annotations

import statistics

from app.core.annotation_workbench import validate_review
from app.core.offline_benchmark import (
    evaluate_history, finite_number, metric, percentile, validate_annotation,
)


def adapt_review(review, group_definitions):
    validate_review(review)
    if not group_definitions or any(not v for v in group_definitions.values()):
        raise ValueError('explicit operator group definitions required')
    origin = review['source']['timestamp_origin_ms']
    window = [origin + x for x in review['display']['preview_window_ms']]
    if (len(window) != 2 or not all(finite_number(x) and x == int(x) for x in window)
            or window[1] <= window[0]):
        raise ValueError('invalid review window')
    marks = review['annotations']
    if not marks or any(m['kind'] != 'phase_hypothesis' for m in marks):
        raise ValueError('phase-duration hypotheses required')
    chunks, current, boundaries, gaps = [], [], [], []
    previous = None
    for m in marks:
        a, b, label = m['interval_start_ms'], m['interval_end_ms'], m['label']
        if label not in group_definitions:
            raise ValueError('label missing independent operator group definition')
        if not window[0] <= a < b <= window[1] or a != int(a) or b != int(b):
            raise ValueError('invalid phase interval or outside review window')
        if previous:
            pa, pb, pl = previous
            if a <= pa or b <= pb:
                raise ValueError('unsorted, nested or duplicate phase intervals')
            if len(current) > 1 and a < current[-2][1]:
                raise ValueError('multiple simultaneous phase intervals')
            if a > pb:
                gaps.append([pb, a])
                chunks.append(current)
                current = []
            elif label != pl:
                boundaries.append({'from_group': pl, 'to_group': label,
                    'endpoint_interval_ms': [a, pb],
                    'endpoint_disagreement_ms': pb-a,
                    'point_diagnostic_ms': (a+pb)//2,
                    'interpretation': 'endpoint discrepancy bracket, not calibrated lamp interval'})
        current.append((a, b, label))
        previous = (a, b, label)
    chunks.append(current)
    blocks = []
    for chunk in chunks:
        points = [{'timestamp_ms': chunk[0][0], 'kind': chunk[0][2]}]
        for left, right in zip(chunk, chunk[1:]):
            if left[2] != right[2]:
                points.append({'timestamp_ms': (left[1]+right[0])//2, 'kind': right[2]})
        points.append({'timestamp_ms': chunk[-1][1], 'kind': chunk[-1][2]})
        annotation = validate_annotation({'start_ms': origin, 'marks': points})
        if not annotation['valid']:
            raise ValueError(annotation['errors'])
        blocks.append({'annotation': annotation,
                       'endpoint_semantics': 'left and right censoring sentinels; never boundary truth'})
    return {'schema': 'expert-phase-duration-adapter-v1', 'window_ms': window,
            'group_definitions': group_definitions, 'blocks': blocks,
            'boundary_hypotheses': boundaries, 'unlabelled_gaps_ms': gaps,
            'labelled_duration_s': sum((b['annotation']['known_range_ms'][1]-b['annotation']['known_range_ms'][0])/1000 for b in blocks),
            'operator_error_claim_ms': 2000, 'independent_lamp_truth': False,
            'selected_track_used_for_mapping': False,
            'interval_semantics_confirmed_by_operator': True}


def evaluate_review(prediction, adapter):
    """Reuse unchanged history evaluator. Compute recurrence from switches only.

The original evaluator's recurrence includes endpoints, so its whole-prediction
entry point is deliberately not used with censoring sentinels.
"""
    interval = adapter['window_ms']
    schedule = prediction.get('schedule', {})
    returns, last = [], {}
    for boundary in adapter['boundary_hypotheses']:
        # Do not form recurrences across an unlabelled gap.
        t, label = boundary['point_diagnostic_ms'], boundary['to_group']
        if label in last and not any(last[label] < b and a < t for a, b in adapter['unlabelled_gaps_ms']):
            returns.append((t-last[label])/1000)
        last[label] = t
    recurrence = statistics.median(returns) if returns else None
    period = schedule.get('period_s')
    valid_period = finite_number(period) and period > 0
    k = schedule.get('phase_count')
    histories = {}
    for field in ('raw_hsmm_segments', 'baseline_segments'):
        blocks = [evaluate_history(prediction, b['annotation'], field, 2.0) for b in adapter['blocks']]
        counts = [b['boundaries']['recall'] for b in blocks]
        matched = sum(c['matched_boundaries'] for c in counts)
        truth = sum(c['truth_boundaries'] for c in counts)
        predicted = sum(c['predicted_boundaries'] for c in counts)
        errors = [abs(p['signed_error_s']) for b in blocks for p in b['boundaries']['matches']]
        nearest = [b['boundaries']['nearest_truth_boundary_mae_s_diagnostic'] for b in blocks]
        nearest_n = sum(x['n_observations'] for x in nearest)
        covered = sum(b['coverage']['covered_duration_s'] for b in blocks)
        duration = adapter['labelled_duration_s']
        unavailable = next((b['reason'] for b in blocks if b['status'] != 'ok'), None)
        common = {'matched': matched, 'truth': truth, 'predicted': predicted,
                  'range_ms': interval, 'tolerance_s': 2.0}
        histories[field] = {
            **common, 'blocks': blocks,
            'precision': metric(matched/predicted if predicted and not unavailable else None,
                                n=predicted, interval=interval, reason=unavailable or (None if predicted else 'no_predicted_boundaries')),
            'recall': metric(matched/truth if truth and not unavailable else None,
                             n=truth, interval=interval, reason=unavailable or (None if truth else 'no_internal_transitions')),
            'matched_mae_s': metric(statistics.mean(errors) if errors else None, n=matched, interval=interval,
                                   reason=unavailable or (None if errors else 'no_matches')),
            'matched_p95_s': metric(percentile(errors, .95) if errors else None, n=matched, interval=interval,
                                   reason=unavailable or (None if errors else 'no_matches')),
            'nearest_mae_s': metric(sum(x['value']*x['n_observations'] for x in nearest if x['value'] is not None)/nearest_n if nearest_n else None,
                                   n=nearest_n, interval=interval, reason=unavailable or (None if nearest_n else 'no_boundary_pairs')),
            'temporal_coverage': metric(covered/duration if duration and not unavailable else None,
                                       n=len(blocks), interval=interval, reason=unavailable,
                                       covered_s=covered, labelled_s=duration,
                                       interpretation='temporal coverage, not lamp accuracy'),
        }
    return {'interpretation': 'development comparison to expert hypotheses, not independent signal accuracy',
            'phase_count': metric(k, n=1, interval=interval, reason=None if k is not None else 'missing_K',
                                  operator_groups=len(adapter['group_definitions']),
                                  matches_operator_groups=k == len(adapter['group_definitions']) if k is not None else None),
            'period_absolute_error_s': metric(abs(period-recurrence) if valid_period and recurrence is not None else None,
                n=len(returns), interval=interval, reason=None if valid_period and returns else 'missing_period_or_internal_recurrence',
                predicted_s=period, expert_recurrence_median_s=recurrence, recurrence_s=returns,
                interpretation='internal recurrence only; not stationary controller period truth'),
            'histories': histories,
            'physical_lamp_accuracy': metric(n=0, interval=interval, reason='no_independent_lamp_truth')}
