"""New online-demand control after rejecting V6; fixed offline models, no tuning."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
import argparse
import time

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from scripts.check_regime_observations import OUT,baseline_class
from app.core.intersection_project import read_json,digest


def seal():
    paths=['app/core/intersection_online.py','app/core/intersection_emissions.py','app/core/observed_topology.py',
        'app/core/intersection_project.py','app/core/intersection_age_prior.py','app/api/intersection_projects.py','app/api/intersection_online.py']
    save(OUT/'final_control_protocol.json',dict(engine='causal-intersection-v7',cases=[dict(k=k,rep=rep,seed=2026109011+k*100+rep)
        for k in (2,3,4,5) for rep in (0,1)],code_sha256={p:digest(ROOT/p) for p in paths},
        frozen_before_control=True,no_more_tuning_on_these_seeds=True,duration_s=1800,warmup_s=180,
        purpose='fresh demand controls after V6 duration learning failed real video; existing fixed offline training models; all colors incl UNKNOWN'))


def run(k,rep):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_online import CausalIntersection
    protocol=read_json(OUT/'final_control_protocol.json');case=next(c for c in protocol['cases'] if c['k']==k and c['rep']==rep)
    assert all(digest(ROOT/p)==sha for p,sha in protocol['code_sha256'].items())
    out=OUT/'final_control'/f'k{k}_{rep}';out.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    training=OUT/'synthetic'/f'k{k}_holdout';model=read_json(training/'model.json');original=read_json(training/'online_truth.json')
    config={**original['config'],'seed':case['seed']};environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    tracks,truth=sim.generate(config,environment);save(out/'truth.json',truth)
    expected={}
    for a,b in dict(N='S',S='N',E='W',W='E').items():
        phases={p for p,g in enumerate(truth['groups']) if a+'->_'+b in g}
        expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
    engines=dict(baseline=baseline_class()(model),candidate=CausalIntersection(model));stats={n:Counter() for n in engines}
    for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000):
        second=(packet['timestamp_ms']-sim.BASE_MS)/1000
        for name,engine in engines.items():
            r=engine.ingest(packet)
            if second<180:continue
            for a,h in r['heads'].items():
                actual=sim.movement_color_at(expected[a],second)[0];predicted=h['main']['state']
                stats[name]['total']+=1;stats[name]['correct']+=predicted==actual;stats[name]['known']+=predicted!='UNKNOWN'
    assert all(digest(ROOT/p)==sha for p,sha in protocol['code_sha256'].items())
    scores={n:dict(counts=dict(s),accuracy=s['correct']/s['total'],coverage=s['known']/s['total']) for n,s in stats.items()}
    save(out/'receipt.json',dict(case=case,scores=scores,model_id=model['model_id'],offline_model_sha256=digest(training/'model.json'),
        working_K=[r['phase_count'] for r in model['regimes']],runtime_s=time.monotonic()-start,protocol_sha256=digest(OUT/'final_control_protocol.json'),
        video_and_annotations_used=False,online_demand_seeds_disjoint_from_training=True,scope='simulation, not field lamp accuracy'))
    print('FINAL_CONTROL',k,rep,[(n,round(s['accuracy'],4)) for n,s in scores.items()],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seal',action='store_true');parser.add_argument('--k',type=int);parser.add_argument('--rep',type=int,default=0)
    args=parser.parse_args()
    seal() if args.seal else run(args.k,args.rep)
