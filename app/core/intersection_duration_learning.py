"""Predictive duration laws from offline fitted phase intervals, no lamp labels."""
import math
import numpy as np


def duration_law(durations,*,clearance_s=4):
    values=np.asarray(durations,dtype=float)
    values=values[np.isfinite(values)&(values>clearance_s+1)]
    if len(values)<8:return None
    p10,median,p90=np.quantile(values,[.1,.5,.9]);green_median=max(2.,float(median)-clearance_s)
    # One second is the observation grid resolution, not a 12% phase jitter.
    scale=max(1.,float(p90-p10)/2.563)
    tail_count=int(np.sum(values>median+3*scale))
    return dict(schema='offline-robust-duration-v1',samples=len(values),phase_median_s=float(median),
        green_median_s=green_median,ordinary_scale_s=scale,
        log_sigma=max(1/green_median,(math.log(max(1.,p90-clearance_s))-math.log(max(1.,p10-clearance_s)))/2.563),
        tail_count=tail_count,tail_cutoff_s=float(median+3*scale),
        tail_probability=max(.02,min(.2,(tail_count+1)/(len(values)+2))),
        tail_probability_floor=.02,tail_mean_s=4*green_median,
        timing_basis='offline trajectory phase fits, NOT measured physical green durations')


def duration_arrays(law,age_cap):
    med=law['green_median_s'];sigma=law['log_sigma'];tail=law['tail_probability']
    survival=np.array([(1-tail)*.5*math.erfc((math.log(max(.01,a))-math.log(med))/sigma/math.sqrt(2))+
                       tail*math.exp(-a/law['tail_mean_s']) for a in range(age_cap+2)])
    return np.clip(1-survival[1:]/survival[:-1],.00001,.995),survival[:-1]
