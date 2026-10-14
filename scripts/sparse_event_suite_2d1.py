"""Independent timestamp/movement generator. No decoder imports or fitted truth."""
import json
from pathlib import Path
import numpy as np

SEEDS=(11,29)
CASES=[(f'{change}_K{k}',k,delta) for k in (2,3) for change,delta in
       [('stable',0),('hold10',10),('hold30',30),('shorten10',-10)]]
CASES += [('unequal_demand_K3',3,0),('no_demand_K2',2,0),('blockage_K2',2,0),('observation_gap_K3',3,0)]


def generate(name,k,delta,seed):
    rng=np.random.default_rng(seed);durations=[30]* (4*k)
    durations[k]+=delta
    starts=np.cumsum([0]+durations)
    truth=[[int(a),int(b),i%k] for i,(a,b) in enumerate(zip(starts,starts[1:]))]
    rates=[.25]*k
    if name=='unequal_demand_K3':rates=[.35,.12,.25]
    events=[]
    for a,b,z in truth:
        t=a+rng.exponential(1/rates[z])
        while t<b:
            events.append({'timestamp_ms':int(round(t*1000)),'movement':f'M{z}'})
            t+=rng.exponential(1/rates[z])
    coverage=[[0,int(starts[-1])]]
    if name in {'no_demand_K2','blockage_K2'}:events=[]
    if name=='observation_gap_K3':
        events=[e for e in events if not 90000<=e['timestamp_ms']<180000]
        coverage=[[0,90],[180,int(starts[-1])]]
    return {'case':name,'seed':seed,'K':k,'period_s':30*k,'duration_targets_s':[30]*k,
        'truth_segments':truth,'events':sorted(events,key=lambda e:e['timestamp_ms']),
        'provided_input_intervals_s':coverage,'extent_s':int(starts[-1]),
        'rates_per_s':rates,'initial_phase':0,'model_movements':[f'M{i}' for i in range(k)],
        'templates':(np.eye(k)*.88+.02).tolist()}


def materialize(folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    suite=[generate(name,k,delta,seed) for name,k,delta in CASES for seed in SEEDS]
    manifest={'base_sha':'714a0917bfe4f46ab5022e25e88cc4410a9539ea','seeds':SEEDS,
        'cases':CASES,'dt_s':1,'cycles':4,'generator':'Poisson arrivals only in corresponding logical phase; ideal event model, not lamps',
        'rates_per_s':.25,'unequal_rates_per_s':[.35,.12,.25],
        'boundary_tolerance_s':2,'core_candidate_recall_min':.8,'core_published_recall_min':.8,
        'core_published_coverage_min':.8,
        'identifiability_requirements':['no-demand/blockage observations indistinguishable; no cause claim',
            'explicit missing observations distinct from no arrival','no physical state from event emissions',
            'no identification claim from unique float maximum'],
        'one_predeclared_diagnostic_proposal':'conditional mark likelihood x@log(row_normalized_templates); absence neutral; existing duration prior/config unchanged',
        'proposal_status':'diagnostic only; publishing needs validated interval-support/ambiguity model',
        'max_suite_runs':1,'max_real_replays':1,'real_replay_condition':'sparse recovery AND publishing/identifiability gate PASS',
        'config':{'min_duration_s':2.,'max_duration_s':180.,'duration_min_factor':.1,'duration_max_factor':4.,
                  'duration_penalty_strength':2.,'transition_penalty':.25,'max_bins':10000,
                  'max_work_units':5000000,'max_seconds':15.}}
    for name,value in [('predeclared_manifest.json',manifest),('sparse_suite.json',suite)]:
        with (folder/name).open('x',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,indent=2);f.write('\n')


if __name__=='__main__':materialize('evidence/stage2d1_sparse_review')
