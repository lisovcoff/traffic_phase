"""Direct training-label agreement; no permutation is learned from test labels."""
from bisect import bisect_right
import json
from scripts.isolated_phase_check import ROOT,save

OUT=ROOT/'benchmarks/learned_clock_fixed_20261018'
TRAIN=ROOT/'benchmarks/learned_profile_20261018'


def main():
    evaluation=json.loads((OUT/'evaluation.json').read_text(encoding='utf8'))
    rows=[]
    for source in evaluation['rows']:
        name=source['file'];pred=json.loads((OUT/'predictions'/name).read_text(encoding='utf8'))
        model=json.loads((TRAIN/'models'/name).read_text(encoding='utf8'))
        ann=json.loads((TRAIN/'heldout'/name).read_text(encoding='utf8'))
        marks=ann['marks'];times=[m['timestamp_ms'] for m in marks]
        history=pred['schedule']['raw_hsmm_segments'];base=pred['schedule_base_timestamp_ms']
        starts=[base+row[0]*1000 for row in history]
        def label_at(t):
            i=bisect_right(starts,t)-1
            if i<0 or t>=base+history[i][1]*1000:return None
            return model['phase_labels'][history[i][2]]
        correct=0;total=0
        for t in range(times[0],times[-1],1000):
            true=marks[bisect_right(times,t)-1]['kind']
            correct+=label_at(t)==true;total+=1
        boundary=source['variants']['corrected_learned']['histories']['raw_hsmm_segments']['boundaries']
        typed=sum(label_at(pair['predicted_ms'])==next(m['kind'] for m in marks if m['timestamp_ms']==pair['truth_ms'])
                  for pair in boundary['matches'])
        rows.append(dict(file=name,grid_correct=correct,grid_total=total,direct_agreement=correct/total,
            timing_matches=boundary['mae_s']['matched_boundaries'],typed_timing_matches=typed,
            truth_boundaries=boundary['mae_s']['truth_boundaries'],
            test_label_permutation_fitted=False))
    save(OUT/'direct_label_diagnostics.json',rows)
    print(json.dumps(rows,indent=2))


if __name__=='__main__':main()
