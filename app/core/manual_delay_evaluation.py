"""Evaluation against a declared operator reaction interval; never shifts predictions."""
from __future__ import annotations

import math

from app.core.offline_benchmark import segments_absolute, validate_annotation


def match_reaction_intervals(marks_ms, predictions_ms, max_delay_s=3.):
    if isinstance(max_delay_s, bool) or not isinstance(max_delay_s, (int, float)) or not math.isfinite(max_delay_s) or max_delay_s < 0:
        raise ValueError('invalid annotation reaction bound')
    truth, predicted = sorted(marks_ms), sorted(predictions_ms)
    scores = [[(0, 0.) for _ in range(len(predicted)+1)] for _ in range(len(truth)+1)]
    actions = {}
    for i, mark in enumerate(truth, 1):
        for j, timestamp in enumerate(predicted, 1):
            options = [(scores[i-1][j], 'truth'), (scores[i][j-1], 'prediction')]
            if mark-max_delay_s*1000 <= timestamp <= mark:
                count, cost = scores[i-1][j-1]
                options.append(((count+1, cost-abs(timestamp-mark)), 'match'))
            scores[i][j], actions[i,j] = max(options, key=lambda item:item[0])
    pairs, i, j = [], len(truth), len(predicted)
    while i and j:
        action = actions[i,j]
        if action == 'match':
            pairs.append(dict(mark_ms=truth[i-1], predicted_ms=predicted[j-1],
                compatible_signal_interval_ms=[truth[i-1]-max_delay_s*1000, truth[i-1]],
                prediction_minus_mark_s=(predicted[j-1]-truth[i-1])/1000))
            i, j = i-1, j-1
        elif action == 'truth':
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def evaluate_reaction_bound(prediction, annotation, *, field='raw_hsmm_segments', max_delay_s=3.):
    truth = validate_annotation(annotation)
    if not truth['valid']:
        raise ValueError('invalid manual marks')
    rows, error = segments_absolute(prediction, field)
    if error:
        return dict(status='unavailable', reason=error)
    marks = truth['marks']
    start, end = truth['known_range_ms']
    boundaries = [marks[i]['timestamp_ms'] for i in range(1,len(marks)-1)
                  if marks[i-1]['kind'] != marks[i]['kind']]
    predicted = [b[0] for a,b in zip(rows,rows[1:])
                 if abs(a[1]-b[0]) <= .001 and a[2] != b[2] and start < b[0] < end]
    pairs = match_reaction_intervals(boundaries, predicted, max_delay_s)
    return dict(status='ok', truth_boundaries=len(boundaries), predicted_boundaries=len(predicted),
        compatible_boundaries=len(pairs), max_operator_delay_s=max_delay_s,
        interval='[manual_mark - declared_delay, manual_mark]',
        matching='untyped_absolute_one_to_one_no_offset_fit', pairs=pairs,
        missed_marks_ms=[t for t in boundaries if t not in {p['mark_ms'] for p in pairs}],
        extra_predictions_ms=[t for t in predicted if t not in {p['predicted_ms'] for p in pairs}],
        interpretation='compatibility_with_operator_claim_NOT_measured_switch_accuracy')
