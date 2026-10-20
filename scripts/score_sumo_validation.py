"""Score a frozen automatic model against separate native SUMO signal output."""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
import hashlib
import json
import os
from pathlib import Path


def score(model_path, case, output):
    os.environ.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    from scripts.corpus_validation import prepare_worker_environment
    prepare_worker_environment()
    from app.core.intersection_online import CausalIntersection
    from scripts.online_packets import packets_from_tracks

    model_path, case, output = Path(model_path), Path(case), Path(output)
    if output.exists():
        raise FileExistsError(output)
    model = json.loads(model_path.read_text(encoding='utf8'))
    truth = json.loads((case/'truth.json').read_text(encoding='utf8'))
    raw = (case/'vehicles.json').read_bytes()
    if truth['audit']['physics_status'] != 'PASS':
        raise ValueError('Fixture failed physics gate')
    if hashlib.sha256(raw).hexdigest() != truth['vehicle_input_sha256']:
        raise ValueError('Fixture hash mismatch')
    if model['input']['sha256'] == truth['vehicle_input_sha256']:
        raise ValueError('Online validation must use different tracks from offline fitting')
    tracks = json.loads(raw)
    if {r['zone_in'] for r in tracks} != set(truth['link_indices']):
        raise ValueError('Vehicle export omitted an approach; invalid fixture')
    engine = CausalIntersection(model)  # Only the learned model enters inference.
    counts, confusion, per_head = Counter(), Counter(), {}
    times = [r['time_s'] for r in truth['actual_tls_states']]
    states = [r['state'] for r in truth['actual_tls_states']]
    colors = dict(r='RED', u='RED_YELLOW', G='GREEN', g='GREEN', y='YELLOW')
    base, duration = truth['base_ms'], truth['config']['duration_s']
    warmup, end = 180, duration-10
    if end <= warmup:
        raise ValueError('No scored interval')
    for packet in packets_from_tracks(tracks, start_ms=base, end_ms=base+duration*1000):
        response = engine.ingest(packet)
        second = (packet['timestamp_ms']-base)/1000
        if not warmup <= second < end:
            continue
        state = states[bisect_right(times, second)-1]
        # Iterate truth heads, so missing predicted heads cannot improve accuracy.
        for approach, index in truth['link_indices'].items():
            actual = colors[state[index]]
            predicted = response['heads'].get(approach, {}).get('main', {}).get('state', 'UNKNOWN')
            head = per_head.setdefault(approach, Counter())
            for target in (counts, head):
                target['total'] += 1
                target['correct'] += predicted == actual
                target[actual+'_total'] += 1
                target[actual+'_correct'] += predicted == actual
            confusion[actual+'->'+predicted] += 1
    result = dict(schema='sumo-independent-evaluation-v1',
        case_config=truth['config'], scored_seconds=[warmup,end],
        counts=dict(counts), confusion=dict(confusion),
        per_head={k:dict(v) for k,v in per_head.items()},
        accuracy=counts['correct']/counts['total'],
        macro_color_recall=sum(counts[c+'_correct']/counts[c+'_total']
                               for c in set(colors.values()) if counts[c+'_total']) /
                           sum(bool(counts[c+'_total']) for c in set(colors.values())),
        automatic_phase_counts=[r['phase_count'] for r in model['regimes']],
        automatic_approaches=model['approaches'],
        model_sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
        truth_sha256=hashlib.sha256((case/'truth.json').read_bytes()).hexdigest(),
        vehicles_sha256=hashlib.sha256(raw).hexdigest(),
        video_or_signal_truth_supplied_to_inference=False,
        real_road_accuracy_claim=False)
    with output.open('x',encoding='utf8') as handle:
        json.dump(result,handle,indent=2)
    print(json.dumps(dict(accuracy=result['accuracy'], macro_color_recall=result['macro_color_recall'],
                         counts=dict(counts))),flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--case', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    score(args.model, args.case, args.output)
