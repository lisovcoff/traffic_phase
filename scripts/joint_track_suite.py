"""Independent paired-vehicle generator. Never imports the posterior model."""
import hashlib
import json
from pathlib import Path

import numpy as np

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence

SEEDS=[2027,4099]
CASES=['stable_K2','stable_K3','hold10_K2','hold30_K3','shortening4_K3',
       'unequal_demand_K2','shared_K3','observation_gap_K3','no_demand_K2',
       'all_observations_missing_K2','changed_rate_K3','blockage_K2']


def generate(name,seed):
    rng=np.random.default_rng(seed)
    k=3 if name.endswith('K3') else 2
    durations=[10,10,10,10]
    if name=='hold10_K2': durations[1]+=10
    if name=='hold30_K3': durations[1]+=30
    if name=='shortening4_K3': durations[1]-=4
    horizon=sum(durations)-2
    boundaries=np.cumsum([0]+durations).tolist()
    truth=[[a,min(b,horizon),i%k] for i,(a,b) in enumerate(zip(boundaries,boundaries[1:])) if a<horizon]
    movements=[f'movement-{i}' for i in range(k)]
    rates=np.full((k,k),.03)
    for i in range(k): rates[i,i]=.7
    if name=='shared_K3':
        movements.append('shared-movement')
        rates=np.c_[rates,[.5,.03,.5]]
    n=horizon//2
    exposure=np.ones((len(movements),n))
    if name=='unequal_demand_K2': exposure[0]*=.2;exposure[1]*=1.5
    if name=='no_demand_K2': exposure[:]=0
    actual_exposure=exposure.copy()
    if name=='changed_rate_K3': actual_exposure[:,n//2:]*=.15
    if name=='blockage_K2': actual_exposure[:,6:14]=0
    windows=[[0,horizon+10]]
    if name=='observation_gap_K3': windows=[[0,12],[24,horizon+10]]
    if name=='all_observations_missing_K2': windows=[]
    def visible(t): return any(a<=t/1000<b for a,b in windows)
    source=f'{name}_seed{seed}'
    events=[]; vehicle_count=0; off_phase=0
    latent=[]
    for j in range(n):
        time_s=j*2
        phase=next(z for a,b,z in truth if a<=time_s<b)
        for m,movement in enumerate(movements):
            count=int(rng.poisson(rates[phase,m]*actual_exposure[m,j]*2))
            for _ in range(count):
                vehicle_count+=1
                identity=f'vehicle-{vehicle_count}'
                d=int(rng.choice([0,2,4],p=[.25,.5,.25]))
                lag=int(rng.choice([2,4,6],p=[.25,.5,.25]))
                r=j*2000+250+d*1000;c=r+lag*1000
                observed_r=visible(r) and rng.random()<.8
                observed_c=visible(c) and rng.random()<.9
                if m<k and m!=phase: off_phase+=1
                latent.append({'id':identity,'opportunity_ms':j*2000+250,'movement':movement,
                    'release_ms':r,'crossing_ms':c,'observed_release':bool(observed_r),'observed_crossing':bool(observed_c)})
                for ts,kind,method,observed in [(r,'RELEASE','synthetic_release',observed_r),
                                               (c,'CROSSING_PROXY','synthetic_crossing',observed_c)]:
                    if observed:
                        events.append(TemporalEvent(ts,kind,movement,identity,method,.5,'MEDIUM',None,
                            {'source':source,'track_fingerprint':identity,'eligible_proxy':True,
                             'synthetic':True,'signal_state_observed':False}))
    raw=json.dumps([e.to_dict() for e in events],sort_keys=True).encode()
    index=build_local_evidence(events,source_namespace=hashlib.sha256(raw).hexdigest())
    view=index.query(0,(horizon+10)*1000)
    spec={'horizon_s':horizon,'movements':movements,'rates_per_s':rates.tolist(),
        'latent_demand_exposure':exposure.tolist(),'observation_windows_s':windows,
        'release_delay_s':[[0,.25],[2,.5],[4,.25]],'transit_delay_s':[[2,.25],[4,.5],[6,.25]],
        'release_detection_probability':.8,'crossing_detection_probability':.9,
        'release_method':'synthetic_release','crossing_method':'synthetic_crossing',
        'rate_source':'supplied synthetic generator design','delay_source':'supplied synthetic generator design',
        'initial_phase':0,'initial_phase_start_s':0,'observed_segment_count':4}
    return {'case':name,'seed':seed,'truth_segments':truth,'latent_vehicles':latent,
        'generation':{'durations_s':durations,'latent_vehicle_count':vehicle_count,'off_phase_vehicle_count':off_phase,
                      'actual_demand_exposure':actual_exposure.tolist()},
        'correctly_specified':name not in {'changed_rate_K3','blockage_K2'},
        'inference_input':{'view':view,'spec':spec}}


def materialize(out):
    if out.exists(): raise ValueError('fresh suite directory required')
    out.mkdir(parents=True)
    suite=[generate(name,seed) for name in CASES for seed in SEEDS]
    inputs=[{'case':c['case'],'seed':c['seed'],'inference_input':c['inference_input']} for c in suite]
    for name,value in [('suite.json',suite),('inputs.json',inputs)]:
        (out/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    materialize(p.parse_args().out)
