"""Train the same onset-delay rule for any independently clock-linked head."""
import math
from statistics import median


def fit_onset_delays(estimate,truth,*,approach,training_range_s,clock_provenance):
    """Truth brackets must already use the estimate's source-relative clock.

    Only training annotations are accepted. Clock fitting and lamp inference
    cannot be used to manufacture the required independent clock provenance.
    """
    if not clock_provenance.get('independent_vehicle_link_supported'):
        raise ValueError('independent vehicle clock link required')
    start,end=training_range_s
    if not math.isfinite(start+end) or start>=end:raise ValueError('finite training range required')
    states={r['id']:r['heads'][approach]['main']['state'] for r in estimate['states']}
    rows=estimate['segments'];predicted={c:[] for c in ['GREEN','RED']}
    for a,b in zip(rows,rows[1:]):
        color=states[b[2]]
        if a[1]==b[0] and color in predicted and color!=states[a[2]] and start<=b[0]<end:
            predicted[color].append(b[0])
    errors={c:[] for c in predicted};used=set()
    for label in truth:
        lo,hi=label['bracket_s'];color=label['color']
        if color not in errors or not math.isfinite(lo+hi) or not start<=lo<=hi<=end:
            raise ValueError('only valid training G/R brackets accepted')
        candidates=[t for t in predicted[color] if abs(t-(lo+hi)/2)<25]
        if len(candidates)!=1 or (color,candidates[0]) in used:
            raise ValueError('unique one-to-one training onset correspondence required')
        used.add((color,candidates[0]));errors[color].append(candidates[0]-(lo+hi)/2)
    biases={}
    for color,values in errors.items():
        if len(values)<3:raise ValueError('at least three training cycles of each onset required')
        center=median(values)
        if median(abs(v-center) for v in values)>1 or max(values)-min(values)>3:
            raise ValueError('constant onset delay unsupported by training spread')
        biases[color]=center
    return dict(approach=approach,onset_bias_s=biases,training_range_s=list(training_range_s),
        training_pairs_by_color={c:len(v) for c,v in errors.items()},clock_provenance=clock_provenance,
        numerical_delay_scope='this trained observation process, not a universal constant',
        fitting_rule='median signed onset-midpoint errors; training labels only')
