"""Estimate recurrence from queue fronts, avoiding demand/discharge centroid drift."""
from collections import defaultdict
import numpy as np
from scipy.ndimage import gaussian_filter1d


def refine_front_period(events,base_ms,period,end_s):
    releases=defaultdict(list)
    for event in events:
        if event.event_type=='RELEASE' and event.evidence_quality!='LOW':
            releases[event.movement].append((event.timestamp_ms-base_ms)/1000)
    estimates=[];support={}
    for movement,values in sorted(releases.items()):
        ts=np.array(sorted(values));hist=gaussian_filter1d(
            np.histogram(ts%period,bins=np.linspace(0,period,101))[0].astype(float),1,mode='wrap')
        low=hist<.1*hist.max();run=[];runs=[]
        for i in range(200):
            if low[i%100]:run.append(i)
            elif run:runs.append(run);run=[]
        if run:runs.append(run)
        if not runs:continue
        gap=max(runs,key=len)
        origin=((gap[0]+gap[-1])/2%100)*period/100
        cycles=np.floor((ts-origin)/period).astype(int)
        fronts=[(int(c),float(ts[cycles==c].min())) for c in np.unique(cycles)
            if origin+c*period>=0 and origin+(c+1)*period<=end_s]
        if len(fronts)<8:continue
        slopes=[(t2-t1)/(c2-c1) for c1,t1 in fronts for c2,t2 in fronts
            if c2-c1>=5 and abs((t2-t1)/(c2-c1)-period)<min(2.,.02*period)]
        if len(slopes)<5:continue
        estimates.append(dict(movement=movement,period_s=float(np.median(slopes)),fronts=len(fronts)))
        support[movement]=fronts
    proposed=float(np.median([r['period_s'] for r in estimates])) if estimates else period
    mad=float(np.median([abs(r['period_s']-proposed) for r in estimates])) if estimates else None
    accepted=len(estimates)>=2 and mad<=.005*period and abs(proposed-period)<=.02*period
    residuals=[]
    for row in estimates:
        fronts=support[row['movement']]
        error=np.array([t-c*proposed for c,t in fronts]);error-=np.median(error)
        row['front_residual_mad_s']=float(np.median(np.abs(error)))
        if abs(row['period_s']-proposed)<=.005*period:residuals.append(row['front_residual_mad_s'])
    residual_mad=float(np.median(residuals)) if residuals else None
    return (proposed if accepted else period),dict(method='robust_within_movement_queue_front_recurrence',
        applied=accepted,input_period_s=period,proposed_period_s=proposed,estimates=estimates,mad_s=mad,
        front_residual_mad_s=residual_mad,
        source='unlabelled restart observations only; no video/controller clock')
