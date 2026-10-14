"""Synthetic-only event brackets. No decoder, truth, fitted templates or phase labels."""
from math import isfinite


def reference(events, mapping, order, coverage, resolution_ms=1):
    """Round-to-nearest timestamps: outward bounds of +/- resolution/2.

    Adjacent observed runs imply a SINGLE bracket only conditional on no hidden
    transitions. With positive unbounded durations, full hidden cycles remain
    possible even between equal marks. Never claim global identification.
    """
    if len(order) < 2 or len(set(order)) != len(order):
        raise ValueError('distinct cyclic phases required')
    if not isfinite(resolution_ms) or resolution_ms <= 0:
        raise ValueError('positive timestamp resolution required')
    points = []
    for event in events:
        t = event['timestamp_ms']
        if not isfinite(t) or event['movement'] not in mapping:
            raise ValueError('invalid event')
        points.append((float(t), mapping[event['movement']]))
    points.sort()
    if any(z not in order for _, z in points):
        raise ValueError('phase not in order')
    runs = []
    for t, z in points:
        if runs and runs[-1]['phase'] == z:
            runs[-1]['last_ms'] = t
        else:
            runs.append({'phase': z, 'first_ms': t, 'last_ms': t})
    edges = []
    for a, b in zip(runs, runs[1:]):
        lo, hi = a['last_ms'] - resolution_ms/2, b['first_ms'] + resolution_ms/2
        step = (order.index(b['phase'])-order.index(a['phase'])) % len(order)
        covered = any(start*1000 <= lo and hi < end*1000 for start, end in coverage)
        reason = ('TIMESTAMP_ORDER_UNRESOLVED' if a['last_ms'] == b['first_ms'] else
                  'OBSERVATION_GAP' if not covered else
                  'UNOBSERVED_INTERMEDIATE_PHASE' if step != 1 else None)
        edges.append({'from_phase': a['phase'], 'to_phase': b['phase'],
                      'interval_ms': [lo, hi], 'minimum_transitions': step,
                      'status': 'ambiguous' if reason else 'conditional_bracket',
                      'reason': reason, 'hidden_full_cycles_possible': True,
                      'single_boundary_assumption': 'no unobserved transitions between these runs'})
    return {'status': 'ambiguous' if points else 'unavailable',
            'reason': 'HIDDEN_CYCLES_NOT_EXCLUDED' if points else 'NO_EVENTS',
            'timestamp_resolution_ms': resolution_ms, 'runs': runs, 'edges': edges,
            'endpoint_boundaries': 'unavailable', 'calibrated_interval': False,
            'semantics': 'ideal exclusive vehicle marks, NOT lamp switches'}
