"""Trajectory-only candidate transformations, pending measured promotion."""
from collections import defaultdict
from copy import deepcopy
import numpy as np


def rate_equivalent_mapping(probs,*,cosine_min=.95):
    probs=np.asarray(probs);k=len(probs)
    excess=np.maximum(0,probs-probs.min(axis=0))
    parent=list(range(k));pairs=[]
    def root(i):
        while parent[i]!=i:i=parent[i]
        return i
    for a in range(k):
        b=(a+1)%k;u,v=excess[a],excess[b]
        if max(u,default=0)<=0 or max(v,default=0)<=0:continue
        sa=u>=max(.005,.15*max(u));sb=v>=max(.005,.15*max(v))
        cosine=float(u@v/(np.linalg.norm(u)*np.linalg.norm(v)))
        if np.array_equal(sa,sb) and cosine>=cosine_min:
            parent[root(b)]=root(a);pairs.append(dict(a=a,b=b,cosine=cosine))
    groups=sorted({root(i) for i in range(k)},key=lambda r:min(i for i in range(k) if root(i)==r))
    if len(groups)<2:return {i:i for i in range(k)},[]
    return {i:groups.index(root(i)) for i in range(k)},pairs


def merge_rate_equivalent_phases(result,*,cosine_min=.95):
    """Discharge-rate changes with the same movement signature are not phases.

    Merge adjacent cyclic states only if their positive movement supports match
    and normalized excess-rate vectors agree. No lamp truth/topology is read.
    """
    from app.core.v9.fit import anonymous_phase_name
    from app.core.v9.events import periodic_baseline_from_segments,_phase_duration_targets_from_baseline,detect_temporary_phase_deviations
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    from app.core.state_contract import attach_state_contract
    original=result['schedule'];names=original['phase_names'];k=len(names)
    rows=original['stream_activity_by_phase']
    probs=np.array([[r['event_probability_by_phase'][n] for r in rows] for n in names])
    mapping,pairs=rate_equivalent_mapping(probs,cosine_min=cosine_min)
    n=len(set(mapping.values()))
    if n==k:return result
    output=deepcopy(result);schedule=output['schedule'];new_names=[anonymous_phase_name(i) for i in range(n)]
    durations=np.zeros(k);segments=[]
    for a,b,z in original['raw_hsmm_segments']:
        durations[int(z)]+=b-a;new=mapping[int(z)]
        if segments and segments[-1][1]==a and segments[-1][2]==new:segments[-1][1]=b
        else:segments.append([a,b,new])
    activity=[]
    for j,row in enumerate(rows):
        values={}
        for new in range(n):
            mask=[i for i in range(k) if mapping[i]==new]
            values[new_names[new]]=float(np.average(probs[mask,j],weights=np.maximum(durations[mask],1e-9)))
        activity.append(dict(stream=row['stream'],event_probability_by_phase=values))
    period=schedule['period_s'];end=max(r[1] for r in segments)
    baseline,centers,diagnostics=periodic_baseline_from_segments(segments,period,end,phase_count=n,return_diagnostics=True)
    targets=_phase_duration_targets_from_baseline(baseline,n);lengths=defaultdict(list)
    for a,b,z in segments:lengths[z].append(b-a)
    schedule.update(phase_count=n,phase_names=new_names,raw_hsmm_segments=segments,
        stream_activity_by_phase=activity,baseline_segments=[list(r) for r in baseline],
        baseline_phase_centers_s={new_names[z]:float(v) for z,v in centers.items()},
        baseline_duration_targets_s={new_names[z]:float(v) for z,v in enumerate(targets)},
        baseline_reconstruction=diagnostics,
        phase_duration_summary={new_names[z]:dict(median_s=float(np.median(v)),mean_s=float(np.mean(v)),observations=len(v)) for z,v in lengths.items()})
    output['phase_model_selection']['selected_phase_count']=n
    output['phase_model_selection']['effective_selection'].update(selected_k=n,recovery_rate_merge=True)
    output['phase_redundancy']['recovery_rate_equivalence']=dict(original_k=k,selected_k=n,mapping=mapping,pairs=pairs)
    output['anomaly_detection']['temporary_phase_deviations']=detect_temporary_phase_deviations(segments,baseline,n)
    try:output['physical_signal_plan']=infer_physical_signal_plan(output)
    except ValueError as exc:output['physical_signal_plan']=dict(enabled=False,reason=str(exc))
    return attach_state_contract(output)
