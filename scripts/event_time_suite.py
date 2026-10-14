"""New independent generator and declaration; no inference import."""
import json
from pathlib import Path
import numpy as np

BASE = '161dd0b5642ba312b1e930a4640c153b2bd799e5'
SEEDS = [101,307]
CASES = [('stable_K2',2,0),('stable_K3',3,0),('hold10_K2',2,10),
         ('hold20_K3',3,20),('shorten5_K3',3,-5),('changing_rate_K3',3,0),
         ('permissive_K3',3,0),('observation_gap_K3',3,0),('no_demand_K2',2,0)]


def generate(name,k,delta,seed):
    rng=np.random.default_rng(seed)
    durations=[10]*6; durations[k]+=delta
    bounds=np.cumsum([0]+durations).tolist()
    truth=[[a,b,i%k] for i,(a,b) in enumerate(zip(bounds,bounds[1:]))]
    rates=[.6,.4,.5][:k]; windows=[[0,bounds[-1]]]; events=[]
    for a,b,z in truth:
        rate=rates[z]*(.15 if name=='changing_rate_K3' and a>=30 else 1)
        t=a+rng.exponential(1/rate)
        while t<b:
            events.append({'timestamp_ms':int(round(t*1000)), 'movement':f'M{z}'})
            t+=rng.exponential(1/rate)
    if name=='permissive_K3':
        events.append({'timestamp_ms':5250,'movement':'M1'})
    if name=='no_demand_K2': events=[]
    if name=='observation_gap_K3':
        windows=[[0,20],[40,bounds[-1]]]
        events=[e for e in events if not 20000<=e['timestamp_ms']<40000]
    return {'case':name,'seed':seed,'truth_segments':truth,
            'inference_input':{'events':sorted(events,key=lambda e:e['timestamp_ms']),
                'mapping':{f'M{i}':i for i in range(k)},'order':list(range(k)),
                'windows':windows,'horizon':bounds[-1],'rates':rates},
            'correctly_specified':name not in {'changing_rate_K3','permissive_K3','no_demand_K2'},
            'misspecification':name if name in {'changing_rate_K3','permissive_K3','no_demand_K2'} else None}


def materialize(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    manifest={'base_sha':BASE,'seeds':SEEDS,'cases':CASES,'max_suite_runs':1,
              'priors':{'uniform':{'min_s':2,'max_s':40,'family':'uniform'},
                        'nominal10':{'min_s':2,'max_s':40,'family':'discrete_laplace','center_s':10,'scale_s':5}},
              'prior_source':'independent design hypotheses: broad durations vs nominal 10s; no test estimation',
              'interval_type':'feasible_sets_on_integer_grid','timestamp_rounding_ms':1,
              'numeric_limit':'rounding cells crossing possible grid boundaries -> unavailable; no silent quantization',
              'limits':{'max_seconds':3.,'max_edges':100000,'max_states':5000,'max_horizon':120,'max_memory_bytes':16000000},
              'suite_cpu_seconds':30.,'max_inference_calls':36,
              'memory_policy':'sequential cases; per-inference conservative object allowance 16MB, not process RSS cap',
              'point_tolerance_s':2,'original_core_recall_min':.8,
              'point_gate':'each stable/hold/shorten correctly specified case recall >=0.8 for each prior separately; unavailable FAIL',
              'feasible_gate':'true internal boundaries belong to ordinal feasible sets and true path to DAG in every correctly specified case; unavailable is unassessed, never PASS',
              'criteria':['event constraint violations zero on complete outputs',
                          'containment, hull median/p95 and <=4s separately; finite sets retained',
                          'optional/missing boundary counts and transition count ambiguity explicit',
                          'UNKNOWN separate from supplied input coverage',
                          'both priors retained; no winner selection',
                          'misspecification detection NOT guaranteed; no-demand cause unknown'],
              'real_runs':0,'production_acceptance':False}
    for name,value in [('manifest.json',manifest),('suite.json',[generate(n,k,d,s) for n,k,d in CASES for s in SEEDS])]:
        with (folder/name).open('x',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,indent=2);f.write('\n')


if __name__=='__main__': materialize('evidence/stage2d1_event_time_prototype')
