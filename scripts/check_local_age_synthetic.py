"""Development regression on the SAME paired streams as the preceding candidate.

Local profiles see only two original offline training recordings. Simulator lamp
truth is saved and used by the evaluator after inference, never by the learner.
"""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
from copy import deepcopy
import json
import time
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,digest,model_fingerprint
from scripts.train_causal_local_ages import phase_history,fit_packets,SOURCES

OUT=ROOT/'evidence/local_observation_age_20261020/v1/synthetic'
LOCAL=ROOT/'.web_runtime/local_observation_age_20261020/v1/synthetic'


def seal():
    OUT.mkdir(parents=True,exist_ok=False);LOCAL.mkdir(parents=True,exist_ok=False)
    save(OUT/'protocol.json',dict(source_sha256={p:digest(ROOT/p) for p in SOURCES+['scripts/check_local_age_synthetic.py']},
        cases='same twelve revealed paired streams from coherent v5; development, NOT fresh holdout',
        previous_protocol_sha256=digest(ROOT/'evidence/coherent_signal_20261020/v5/synthetic/protocol.json'),
        training_inputs='two earlier synthetic training recordings, no test vehicles/lamps',
        queue_geometry='frozen previous offline queue references',scored_seconds=[180,1790],history_lag_s=10,
        production_enabled=False))


def train(k):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_local_emissions import LocalAgeCounts
    protocol=read_json(OUT/'protocol.json');assert all(digest(ROOT/p)==h for p,h in protocol['source_sha256'].items())
    folder=ROOT/'evidence/cross_day_model_selection_20261019/synthetic'/f'k{k}_holdout'
    model=deepcopy(read_json(folder/'model.json'))
    model['queue_observations']=read_json(ROOT/f'evidence/coherent_signal_20261020/v5/synthetic/k{k}_queue_references.json')
    environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    counts={r['regime_id']:LocalAgeCounts(model['approaches'],r['phase_count']) for r in model['regimes']};stats=[]
    sessions={s['session_id']:s for s in model['sessions']}
    for r in model['regimes']:
        for member in r['members']:
            session=sessions[member['session_id']];index=int(session['source_member'].replace('session','').replace('.json',''))
            tracks,_=sim.generate(read_json(folder/f'training{index}_truth.json')['config'],environment)
            segments,base=phase_history(ROOT/'logs/intersection_projects'/model['model_id'],session,
                                       model['approaches'],model['projection_version'])
            profile,summary=fit_packets(model,r,member,segments,base,packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1500000))
            c=counts[r['regime_id']];c.counts+=profile['counts'];c.samples.update(profile['samples']);stats.append(summary)
        r['causal_local_emissions']=counts[r['regime_id']].finish()
    model['fingerprint']=model_fingerprint(model)
    save(LOCAL/f'k{k}_model.json',model)
    save(OUT/f'k{k}_training.json',dict(stats=stats,profiles={r['regime_id']:r['causal_local_emissions'] for r in model['regimes']},
        model_sha256=digest(LOCAL/f'k{k}_model.json'),phase_model_sha256=digest(folder/'model.json'),
        simulator_truth_supplied_to_learner=False))
    print('TRAIN SYNTH',k,[r['causal_local_emissions']['samples'] for r in model['regimes']],flush=True)


def evaluate(k):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.experimental.intersection_local_filter import LocalProfileIntersection
    p=read_json(OUT/'protocol.json');assert all(digest(ROOT/n)==h for n,h in p['source_sha256'].items())
    assert digest(LOCAL/f'k{k}_model.json')==read_json(OUT/f'k{k}_training.json')['model_sha256']
    model=read_json(LOCAL/f'k{k}_model.json');environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    for name in ('normal','blocked_N','extended_12s'):
        start=time.monotonic();previous=ROOT/f'evidence/coherent_signal_20261020/v5/synthetic/k{k}_{name}'
        truth=read_json(previous/'truth.json');tracks,regenerated=sim.generate(truth['config'],environment)
        assert json.loads(json.dumps(regenerated))==truth
        expected={}
        for a,b in dict(N='S',S='N',E='W',W='E').items():
            phases={z for z,g in enumerate(truth['groups']) if a+'->_'+b in g}
            expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
        stats={n:Counter() for n in ('instant','history_10s')};confusion={n:Counter() for n in stats};engine=LocalProfileIntersection(model)
        def score(label,ms,heads):
            second=(ms-sim.BASE_MS)/1000
            if not 180<=second<1790:return
            for a,h in heads.items():
                actual=sim.movement_color_at(expected[a],second)[0];predicted=h['main']['state'];c=stats[label]
                c['total']+=1;c['correct']+=predicted==actual;c['unknown']+=predicted=='UNKNOWN'
                c[actual+'_total']+=1;c[actual+'_correct']+=predicted==actual;confusion[label][actual+'->'+predicted]+=1
        for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000):
            r=engine.ingest(packet);score('instant',r['timestamp_ms'],r['heads'])
            for h in r['finalized_history']:score('history_10s',h['timestamp_ms'],h['heads'])
        assert all(digest(ROOT/n)==h for n,h in p['source_sha256'].items())
        result=dict(k=k,case=name,counts={n:dict(c) for n,c in stats.items()},accuracy={n:c['correct']/c['total'] for n,c in stats.items()},
            confusion={n:dict(c) for n,c in confusion.items()},previous=read_json(previous/'result.json')['accuracy'],
            original_truth_sha256=digest(previous/'truth.json'),runtime_s=time.monotonic()-start,production_enabled=False)
        save(OUT/f'k{k}_{name}.json',result);print('LOCAL AGE',k,name,result['accuracy'],'previous',result['previous'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','train','evaluate']);p.add_argument('--k',type=int,choices=range(2,6))
    a=p.parse_args();seal() if a.action=='seal' else train(a.k) if a.action=='train' else evaluate(a.k)
