"""Observation-regularized phase clock, with explicit nonstationary fallback."""
from collections import defaultdict
from copy import deepcopy
import numpy as np


def replace_history(result,segments,period):
    from app.core.v9.events import periodic_baseline_from_segments,_phase_duration_targets_from_baseline,detect_temporary_phase_deviations
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    from app.core.state_contract import attach_state_contract
    output=deepcopy(result);s=output['schedule'];k=s['phase_count'];names=s['phase_names']
    end=max(r[1] for r in segments)
    baseline,centers,diagnostic=periodic_baseline_from_segments(segments,period,end,phase_count=k,return_diagnostics=True)
    targets=_phase_duration_targets_from_baseline(baseline,k);lengths=defaultdict(list)
    for a,b,z in segments:lengths[z].append(b-a)
    s.update(period_s=float(period),raw_hsmm_segments=segments,baseline_segments=[list(r) for r in baseline],
        baseline_phase_centers_s={names[z]:float(v) for z,v in centers.items()},
        baseline_duration_targets_s={names[z]:float(v) for z,v in enumerate(targets)},baseline_reconstruction=diagnostic,
        phase_duration_summary={names[z]:dict(median_s=float(np.median(v)),mean_s=float(np.mean(v)),observations=len(v)) for z,v in lengths.items()})
    output['period_inference']['period_s']=float(period)
    output['anomaly_detection']['temporary_phase_deviations']=detect_temporary_phase_deviations(segments,baseline,k)
    try:output['physical_signal_plan']=infer_physical_signal_plan(output)
    except ValueError as exc:output['physical_signal_plan']=dict(enabled=False,reason=str(exc))
    return attach_state_contract(output)


def regularize_phase_clock(result,events,*,boundary_sigma_s=1.5):
    from app.core.recovery.period import refine_front_period
    from app.core.v9.events import periodic_baseline_from_segments
    from app.core.v9.vehicle_evidence import select_permission_events_per_track
    s=result['schedule'];base=result['schedule_base_timestamp_ms'];end=max(r[1] for r in s['raw_hsmm_segments'])
    period,diagnostic=refine_front_period(events,base,s['period_s'],end)
    clock_ok=diagnostic['applied'] and diagnostic['front_residual_mad_s'] is not None and diagnostic['front_residual_mad_s']<=2.
    baseline,_,info=periodic_baseline_from_segments(s['raw_hsmm_segments'],period,end,
        phase_count=s['phase_count'],return_diagnostics=True)
    diagnostic['stationary_clock_accepted']=bool(clock_ok and baseline)
    if not clock_ok or not baseline:
        output=deepcopy(result);output['phase_clock']=diagnostic
        return output
    rows=s['stream_activity_by_phase'];index={r['stream']:i for i,r in enumerate(rows)}
    probs=np.array([[r['event_probability_by_phase'][name] for r in rows] for name in s['phase_names']])
    dt=.25;x=np.zeros((int(np.ceil(end/dt))+1,len(index)))
    for e in select_permission_events_per_track(events)[0]:
        t=(e.timestamp_ms-base)/1000
        if e.movement in index and 0<=t<end:x[int(t/dt),index[e.movement]]=1
    segments=[list(r) for r in baseline];shifts=[]
    for i in range(1,len(segments)):
        before,current=baseline[i-1],baseline[i];b=float(current[0]);previous=int(before[2]);phase=int(current[2])
        width=min(10.,.35*(before[1]-before[0]),.35*(current[1]-current[0]))
        candidates=np.arange(max(0,b-width),min(end,b+width)+dt/2,dt)
        candidates=np.unique(np.append(candidates,b))
        lo=max(0,int((b-width)/dt));hi=min(len(x),int(np.ceil((b+width)/dt))+1)
        logratio=np.log(np.maximum(probs[previous],1e-6)/np.maximum(probs[phase],1e-6))
        logratio[np.abs(logratio)<np.log(3.)]=0
        values=x[lo:hi]@logratio;prefix=np.r_[0,np.cumsum(values)]
        positions=np.clip((candidates/dt).astype(int)-lo,0,len(values))
        score=prefix[positions]-.5*((candidates-b)/boundary_sigma_s)**2
        boundary=float(candidates[int(np.argmax(score))])
        # Each boundary moves <=35% of either neighbor, so ordering survives.
        segments[i-1][1]=boundary;segments[i][0]=boundary
        shifts.append(boundary-b)
    output=replace_history(result,segments,period)
    output['phase_clock']={**diagnostic,'boundary_regularization_sigma_s':boundary_sigma_s,
        'local_boundary_adjustments':len(shifts),'mean_absolute_adjustment_s':float(np.mean(np.abs(shifts))) if shifts else 0,
        'history_source':'queue-front clock plus local discriminating movement events; no annotations/video',
        'uncertainty_semantics':'regularization scale is NOT calibrated lamp-time confidence'}
    return output
