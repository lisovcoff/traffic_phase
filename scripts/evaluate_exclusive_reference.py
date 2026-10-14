"""Read saved events first, seal reference, then read generation truth for assessment.

No decoding/fitting imports. Candidate alignment uses ordinal phase-run sequences
only when the complete observed and candidate sequences agree, never truth.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import numpy as np
from scripts.exclusive_mark_reference import reference

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT/'evidence/stage2d1_sparse_review'
OUT = ROOT/'evidence/stage2d1_interval_reference'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    with (OUT/name).open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def candidate_checks(segments, ref, events):
    phases = [int(s[2]) for s in segments]
    observed = [r['phase'] for r in ref['runs']]
    aligned = phases == observed and bool(observed)
    positions = []
    if aligned:
        for edge, segment in zip(ref['edges'], segments[1:]):
            t = segment[0]*1000
            lo, hi = edge['interval_ms']
            positions.append({'timestamp_ms': t, 'interval_ms': [lo, hi],
                              'position': 'before' if t < lo else 'after' if t > hi else 'inside',
                              'reference_status': edge['status']})
    # Existence of any compatible latent time within the 1ms rounding cell.
    violations = []
    for i, e in enumerate(events):
        lo, hi = e['timestamp_ms']-.5, e['timestamp_ms']+.5
        phase = int(e['movement'][1:])
        if not any(int(z) == phase and a*1000 <= hi and b*1000 > lo for a,b,z in segments):
            violations.append(i)
    return {'alignment': 'ordinal_equal_phase_sequences_conditional_on_no_hidden_cycles' if aligned else 'ambiguous_or_missing_sequence',
            'boundary_positions': positions, 'event_constraint_violations': len(violations),
            'event_count': len(events), 'violating_event_indices': violations,
            'interpretation': 'ideal exclusive mark constraints only; not real RELEASE validity'}


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = json.loads((OLD/'predictions_sealed.json').read_text())
    outputs = []; inputs = {}
    for entry in ledger:
        name = f"{entry['case']}_seed{entry['seed']}.json"
        path = OLD/'synthetic_predictions'/name
        assert digest(path) == entry['prediction_sha256']
        pred = json.loads(path.read_text())
        k = pred['fixed_K']
        result = reference(pred['events'], {f'M{i}': i for i in range(k)}, list(range(k)),
                           pred['provided_input_coverage'])
        outputs.append({'case': pred['case'], 'seed': pred['seed'], 'reference': result})
        inputs[name] = digest(path)
    save('reference_outputs.json', outputs)
    save('reference_seal.json', {'base_sha': '3ce49ae6ac998049443884413968db9e153efa09',
         'code_sha': subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
         'source_sha256': {p: digest(ROOT/p) for p in ['scripts/exclusive_mark_reference.py','scripts/evaluate_exclusive_reference.py']},
         'reference_sha256': digest(OUT/'reference_outputs.json'), 'prediction_hashes': inputs,
         'assumptions': ['ideal exclusive marks','known cyclic order/mapping','rounded milliseconds',
                         'no duration lower bound or count of cycles supplied',
                         'single-boundary brackets conditional on no hidden transitions'],
         'truth_access_before_seal': False, 'new_decoding_runs': 0})
    # Truth first accessed here, after all 24 reference results sealed.
    suite = json.loads((OLD/'sparse_suite.json').read_text())
    rows = []; widths = []; hits = []; midpoints = []
    for item, case in zip(outputs, suite):
        assert (item['case'],item['seed']) == (case['case'],case['seed'])
        name = f"{case['case']}_seed{case['seed']}.json"
        pred = json.loads((OLD/'synthetic_predictions'/name).read_text())
        ref = item['reference']; truth = case['truth_segments']
        # Ordinal association fixed by observed phase sequence, NOT closest truth.
        aligned = [r['phase'] for r in ref['runs']] == [s[2] for s in truth]
        checks = []
        for i, edge in enumerate(ref['edges']):
            lo, hi = edge['interval_ms']; width = (hi-lo)/1000
            conditional = edge['status'] == 'conditional_bracket'
            if conditional: widths.append(width)
            check = {'width_s': width, 'reference_status': edge['status'],
                     'truth_match': 'ordinal_equal_sequences' if aligned else 'ambiguous_not_scored',
                     'truth_inside': None, 'midpoint_within_2s': None}
            if aligned and conditional:
                t = truth[i+1][0]*1000
                check.update(truth_inside=lo <= t <= hi, midpoint_within_2s=abs((lo+hi)/2-t)<=2000)
                hits.append(check['truth_inside']); midpoints.append(check['midpoint_within_2s'])
            checks.append(check)
        candidates = {
            'legacy': candidate_checks(pred['legacy_rejected_history'].get('candidate_segments',[]), ref, case['events']),
            'conditional_mark': candidate_checks(pred['proposal_diagnostic'].get('candidate_segments',[]), ref, case['events'])}
        rows.append({'case': case['case'], 'seed': case['seed'], 'range_s': [0,case['extent_s']],
                     'event_count':len(case['events']), 'reference_status':ref['status'],
                     'truth_internal_boundaries':len(truth)-1, 'interval_checks': checks, 'candidates':candidates})
    aggregate = {'conditional_brackets': len(widths), 'median_width_s':float(np.median(widths)),
                 'p95_width_s':float(np.percentile(widths,95)), 'width_le_4s_count':sum(w<=4 for w in widths),
                 'width_le_4s_fraction':sum(w<=4 for w in widths)/len(widths),
                 'truth_scored':len(hits),'truth_inside_count':sum(hits),
                 'midpoint_within_2s_count':sum(midpoints), 'midpoint_diagnostic_fraction':sum(midpoints)/len(midpoints),
                 'unconditional_identified_boundaries':0}
    save('reference_metrics.json', {'aggregate':aggregate,'rows':rows,
          'old_recovery_gate':'FAIL_UNCHANGED','real_replays':0,'decoding_runs':0,
          'truth_suite_sha256':digest(OLD/'sparse_suite.json')})
    print(json.dumps(aggregate, indent=2))


if __name__ == '__main__':
    run()
