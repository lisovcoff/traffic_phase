"""Independent preregistered sparse Poisson generator; no inference imports."""
import numpy as np

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence


def make_case(k,seed,kind):
    h=64 if kind=='hold30' else 34
    order=[0,1] if k==2 else [2,0,1];first=1 if k==2 else 2
    age=2 if seed==7 else 6
    altered={'hold10':20,'shortening':6,'hold30':40}.get(kind,10)
    durations=[10-age,altered]+[10]*8
    truth=[];start=0
    for i,d in enumerate(durations):
        end=min(h,start+d)
        truth.append([start,end,order[(order.index(first)+i)%k]])
        start=end
        if start==h:break
    exposure=[.25,1.5] if kind=='unequal_demand' else [0]*k if kind=='no_demand' else [1]*k
    windows=[[0,10],[18,h]] if kind=='gap' else [[0,h]]
    rates=[[.6 if z==m else .03 for m in range(k)] for z in range(k)]
    rng=np.random.default_rng(seed);events=[];latent_count=0
    # Truth exists before event generation; decoder never supplies it.
    for cell in range(0,h,2):
        z=next(z for a,b,z in truth if a<=cell<b)
        for movement in range(k):
            count=int(rng.poisson(rates[z][movement]*exposure[movement]*2))
            latent_count+=count
            for u in rng.uniform(cell,cell+2,size=count):
                if not any(a<=u<b for a,b in windows):continue
                ts=int(np.rint(u*1000))
                i=len(events)
                events.append(TemporalEvent(ts,'RELEASE',f'm{movement}',i,
                    'declared_poisson_release',.5,'MEDIUM',None,
                    {'source':'sparse_poisson_generator','track_fingerprint':str(i)}))
    name=f'K{k}_{kind}_seed{seed}'
    spec=dict(horizon_s=h,movements=[f'm{i}' for i in range(k)],cyclic_order=order,
        rates_per_s=rates,rate_source='preregistered Poisson generator',
        latent_demand_exposure=[[x]*(h//2) for x in exposure],demand_source='supplied generator exposure',
        observation_windows_s=windows,observation_window_source='supplied generator camera windows',
        release_delay_s=[[0,1.]],transit_delay_s=[[0,1.]],delay_source='supplied generator vehicle delay',
        release_detection_probability=1.,crossing_detection_probability=0.,
        release_method='declared_poisson_release',crossing_method='unused_crossing',
        clock_model='continuous_latent_rounded_marks',timestamp_resolution_ms=1,
        timestamp_rounding_origin_ms=0,timestamp_resolution_source='generator nearest-ms rounding')
    return dict(case=name,kind=kind,seed=seed,origin_ms=0,spec=spec,
        view=build_local_evidence(events,source_namespace=name).query(0,h*1000+1)),dict(
        segments=truth,initial_age_s=age,latent_count=latent_count,observed_count=len(events))


def suite():
    cases=[(k,seed,kind) for k in (2,3) for seed in (7,23)
        for kind in ('stable','hold10','shortening')]
    cases += [(2,7,kind) for kind in ('unequal_demand','no_demand','gap','hold30')]
    inputs=[];truth={}
    for args in cases:
        item,labels=make_case(*args);inputs.append(item);truth[item['case']]=labels
    return inputs,truth
