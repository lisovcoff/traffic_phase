"""Visible-head onset diagnostics; no authorization to alter production clocks."""
import math
from statistics import median


def head_onsets(estimate,approach,color):
    states={r['id']:r['heads'][approach]['main']['state'] for r in estimate['states']}
    rows=estimate['segments'];result=[]
    for index,row in enumerate(rows):
        if index and states[row[2]]==color and states[rows[index-1][2]]!=color:
            result.append(float(row[0]))
    return result


def pair_unique(predicted,truth,max_distance_s=25):
    """Only unambiguous, one-to-one same-color correspondences. Never reuse."""
    if any(not math.isfinite(t) for t in predicted):raise ValueError('finite times required')
    pairs=[];used=set()
    for row in truth:
        lo,hi=row['bracket_s']
        if not math.isfinite(lo+hi) or hi<lo:raise ValueError('valid bracket required')
        mid=(lo+hi)/2
        choices=[(i,t) for i,t in enumerate(predicted) if abs(t-mid)<max_distance_s]
        if len(choices)>1:raise ValueError('ambiguous predicted onsets near one truth')
        if not choices:continue
        index,t=choices[0]
        if index in used:raise ValueError('one prediction cannot match two truths')
        used.add(index)
        pairs.append(dict(index=row['index'],predicted_s=t,truth_s=[lo,hi],
                          signed_error_s=t-mid,error_interval_s=[t-hi,t-lo]))
    return pairs


def fit_constant_bias(predicted,truth):
    pairs=pair_unique(predicted,truth)
    if len(pairs)<3:raise ValueError('at least three unique calibration pairs required')
    errors=[p['signed_error_s'] for p in pairs];bias=median(errors)
    mad=median(abs(e-bias) for e in errors)
    if mad>1 or max(errors)-min(errors)>3:raise ValueError('constant bias unsupported by calibration spread')
    return dict(bias_s=bias,calibration_pairs=pairs,median_absolute_deviation_s=mad,
        fitting_rule='median signed midpoint error on calibration window only',
        production_enabled=False,clock_mapping_verified=False,
        interpretation='combined apparent model bias and assumed video/JSON clock offset; not isolated physical algorithm latency')


def evaluate_bias(predicted,truth,bias_s=0):
    pairs=pair_unique([t-bias_s for t in predicted],truth)
    distances=[max(p['error_interval_s'][0],-p['error_interval_s'][1],0.) for p in pairs]
    return dict(truth_onsets=len(truth),predicted_onsets=len(predicted),paired_onsets=len(pairs),
        missed_truth=len(truth)-len(pairs),unpaired_predictions=len(predicted)-len(pairs),
        mean_signed_midpoint_error_s=sum(p['signed_error_s'] for p in pairs)/len(pairs) if pairs else None,
        mean_absolute_midpoint_error_s=sum(abs(p['signed_error_s']) for p in pairs)/len(pairs) if pairs else None,
        mean_distance_to_truth_bracket_s=sum(distances)/len(pairs) if pairs else None,
        within_0_5s_of_bracket=sum(v<=.5 for v in distances),within_2s_of_bracket=sum(v<=2 for v in distances),
        pairs=pairs,physical_clock_uncertainty_included=False)


def production_bias(candidate,*,clock_mapping_verified,head_mapping_verified):
    if not clock_mapping_verified or not head_mapping_verified:
        raise ValueError('verified independent clock and head mappings required for production calibration')
    return float(candidate['bias_s'])
