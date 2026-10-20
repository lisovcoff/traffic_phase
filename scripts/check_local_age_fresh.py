"""Four fresh controls for the already-selected local_v1; no subsequent tuning."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import time
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,digest
from scripts.train_causal_local_ages import SOURCES,OUT,LOCAL

DEST=OUT/'fresh'


def seal():
    DEST.mkdir(exist_ok=False)
    save(DEST/'protocol.json',dict(source_sha256={p:digest(ROOT/p) for p in SOURCES+['scripts/check_local_age_fresh.py']},
        selected_candidate='LocalProfileIntersection/local_v1 BEFORE fresh outcomes',
        cases=[dict(k=k,seed=20261020211+k*307,scenario={2:'normal',3:'blocked_N',4:'extended_12s',5:'normal'}[k]) for k in range(2,6)],
        duration_s=1800,scored_seconds=[180,1790],history_lag_s=10,physical_truth_supplied_to_learner=False,
        no_parameter_changes_after_outcomes=True,production_enabled=False))


def run(k):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.experimental.intersection_local_filter import LocalProfileIntersection
    from app.core.intersection_online import CausalIntersection
    p=read_json(DEST/'protocol.json');assert all(digest(ROOT/n)==h for n,h in p['source_sha256'].items())
    case=next(r for r in p['cases'] if r['k']==k);original=ROOT/f'evidence/cross_day_model_selection_20261019/synthetic/k{k}_holdout'
    model=read_json(LOCAL/f'synthetic/k{k}_model.json');assert digest(LOCAL/f'synthetic/k{k}_model.json')==read_json(OUT/f'synthetic/k{k}_training.json')['model_sha256']
    config={**read_json(original/'online_truth.json')['config'],'seed':case['seed'],'arrival_rate_s':.16,
            'regime_change':False,'independent_lane_rng':True}
    if case['scenario']=='blocked_N':config.update(blocking=.22,block_approaches=['N'])
    if case['scenario']=='extended_12s':config.update(single_extension=dict(phase=0,after_s=600,seconds=12))
    tracks,truth=sim.generate(config,read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json'))
    save(DEST/f'k{k}_truth.json',truth);expected={}
    for a,b in dict(N='S',S='N',E='W',W='E').items():
        phases={z for z,g in enumerate(truth['groups']) if a+'->_'+b in g};expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
    engines={'v7':CausalIntersection(model),'local_instant':LocalProfileIntersection(model)}
    counts={n:Counter() for n in (*engines,'local_history_10s')};began=time.monotonic()
    def score(label,ms,heads):
        second=(ms-sim.BASE_MS)/1000
        if not 180<=second<1790:return
        for a,h in heads.items():
            actual=sim.movement_color_at(expected[a],second)[0];correct=actual==h['main']['state'];c=counts[label]
            c['total']+=1;c['correct']+=correct;c[actual+'_total']+=1;c[actual+'_correct']+=correct
    for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000):
        for name,engine in engines.items():
            r=engine.ingest(packet);score(name,r['timestamp_ms'],r['heads'])
            for h in r.get('finalized_history',[]):score('local_history_10s',h['timestamp_ms'],h['heads'])
    assert all(digest(ROOT/n)==h for n,h in p['source_sha256'].items())
    result=dict(case=case,counts={n:dict(c) for n,c in counts.items()},accuracy={n:c['correct']/c['total'] for n,c in counts.items()},
        runtime_s=time.monotonic()-began,production_enabled=False,truth_sha256=digest(DEST/f'k{k}_truth.json'))
    save(DEST/f'k{k}_result.json',result);print('FRESH',k,result['accuracy'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','run']);p.add_argument('--k',type=int,choices=range(2,6))
    a=p.parse_args();seal() if a.action=='seal' else run(a.k)
