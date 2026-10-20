"""Frozen-code paired all-color checks; simulator truth is evaluator-only."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
from copy import deepcopy
import time
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,digest,model_fingerprint

OUT=ROOT/'evidence/coherent_signal_20261020/v5/synthetic'
SOURCES=['app/core/intersection_signal_filter.py','app/core/intersection_signal_smoothing.py',
         'app/core/intersection_queue_observations.py','app/core/intersection_online.py',
         'scripts/check_coherent_synthetic.py','scripts/realistic_traffic_benchmark.py']


def seal():
    OUT.mkdir(parents=True,exist_ok=False)
    save(OUT/'protocol.json',dict(seeds={str(k):2026102091+k*137 for k in range(2,6)},
        cases=['normal','blocked_N','extended_12s'],source_sha256={p:digest(ROOT/p) for p in SOURCES},
        duration_s=1800,scored_seconds=[180,1790],history_lag_s=10,
        metrics='all main-head colors including UNKNOWN as incorrect; instant and 10s-delay history separate',
        queue_geometry='regenerated earlier offline training tracks only, no test tracks or lamp labels',
        phase_models='previously frozen k2..k5 holdout models; K and phases not refit',
        independent_lane_rng=True,production_enabled=False,real_road_accuracy_claim=False))


def run(k):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_online import CausalIntersection
    from app.core.intersection_signal_filter import CoherentIntersection
    from app.core.intersection_queue_observations import learn_queue_references
    protocol=read_json(OUT/'protocol.json')
    assert all(digest(ROOT/p)==h for p,h in protocol['source_sha256'].items())
    folder=ROOT/'evidence/cross_day_model_selection_20261019/synthetic'/f'k{k}_holdout'
    model=read_json(folder/'model.json');candidate=deepcopy(model)
    environment=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    rows=[]
    for i in range(2):
        offline,_=sim.generate(read_json(folder/f'training{i}_truth.json')['config'],environment)
        rows.extend(offline)
    candidate['queue_observations']=learn_queue_references(rows)
    candidate['fingerprint']=model_fingerprint(candidate)
    save(OUT/f'k{k}_queue_references.json',candidate['queue_observations'])
    normal_truth=None
    config={**read_json(folder/'online_truth.json')['config'],'seed':protocol['seeds'][str(k)],
            'arrival_rate_s':.16,'regime_change':False,'independent_lane_rng':True}
    for name in protocol['cases']:
        started=time.monotonic();out=OUT/f'k{k}_{name}';out.mkdir(exist_ok=False)
        change={'blocking':.22,'block_approaches':['N']} if name=='blocked_N' else (
            {'single_extension':dict(phase=0,after_s=600,seconds=12)} if name=='extended_12s' else {})
        tracks,truth=sim.generate({**config,**change},environment);save(out/'truth.json',truth)
        if name=='normal':normal_truth=truth
        elif name=='blocked_N':
            assert truth['signal_plan']==normal_truth['signal_plan']
            assert ([v for v in truth['vehicle_crossings'] if not v['movement'].startswith('N->')]==
                    [v for v in normal_truth['vehicle_crossings'] if not v['movement'].startswith('N->')])
        expected={}
        for a,b in dict(N='S',S='N',E='W',W='E').items():
            phases={z for z,g in enumerate(truth['groups']) if a+'->_'+b in g}
            expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
        engines={'v7_instant':CausalIntersection(model),'joint_instant':CoherentIntersection(candidate)}
        counts={name:Counter() for name in (*engines,'joint_history_10s')}
        confusion={name:Counter() for name in counts};latencies=[]
        def score(name,second,heads):
            if not 180<=second<1790:return
            for a,h in heads.items():
                actual=sim.movement_color_at(expected[a],second)[0];prediction=h['main']['state'];c=counts[name]
                c['total']+=1;c['correct']+=actual==prediction;c['unknown']+=prediction=='UNKNOWN'
                c[actual+'_total']+=1;c[actual+'_correct']+=actual==prediction
                confusion[name][f'{actual}->{prediction}']+=1
                if 756<second<1152 and a=='N' and actual=='GREEN':
                    c['blocked_window_N_green_total']+=1;c['blocked_window_N_green_correct']+=prediction==actual
        for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000):
            second=(packet['timestamp_ms']-sim.BASE_MS)/1000
            for label,engine in engines.items():
                began=time.perf_counter();r=engine.ingest(packet)
                if label=='joint_instant':latencies.append(time.perf_counter()-began)
                score(label,second,r['heads'])
                for h in r.get('finalized_history',[]):score('joint_history_10s',(h['timestamp_ms']-sim.BASE_MS)/1000,h['heads'])
        assert all(digest(ROOT/p)==h for p,h in protocol['source_sha256'].items())
        result=dict(k=k,case=name,counts={n:dict(c) for n,c in counts.items()},confusion={n:dict(c) for n,c in confusion.items()},
            accuracy={n:c['correct']/c['total'] for n,c in counts.items()},tracks=len(tracks),
            model_sha256=digest(folder/'model.json'),truth_sha256=digest(out/'truth.json'),
            elapsed_s=time.monotonic()-started,joint_tick_p95_s=sorted(latencies)[int(len(latencies)*.95)],
            production_enabled=False,video_and_lamp_labels_supplied_to_inference=False)
        save(out/'result.json',result);print('RESULT',k,name,result['accuracy'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seal',action='store_true');parser.add_argument('--k',type=int,choices=range(2,6))
    args=parser.parse_args();seal() if args.seal else run(args.k)
