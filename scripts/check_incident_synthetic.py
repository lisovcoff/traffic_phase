"""Fresh focused incident controls, fixed earlier offline models; truth evaluator only."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
import argparse
import time
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,digest
from scripts.check_incident_counterfactual import OUT,CODE


def seal():
    save(OUT/'synthetic_paired_protocol.json',dict(
        seeds={str(k):2026102073+k*101 for k in (2,3)},
        cases=['normal','blocked_N','extended_12s'],duration_s=1800,warmup_s=180,
        offline_models='previously frozen k2/k3 holdout models, no refit',
        code_sha256={p:digest(ROOT/p) for p in (*CODE,'scripts/realistic_traffic_benchmark.py')},
        metrics='all seconds after warmup, main heads incl UNKNOWN as wrong; incident window separately',
        blocked_window_s=[756,1152],block_location='35m downstream; queues propagate through FIFO',
        independent_lane_rng=True,earlier_unpaired_probes_retained='synthetic/',
        extension='one phase0 green after600s, +12s, later schedule shifts; no emergency label in packets',
        purpose='new development probes, not independent real-road accuracy'))


def run(k):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_online import CausalIntersection
    p=read_json(OUT/'synthetic_paired_protocol.json')
    assert all(digest(ROOT/f)==h for f,h in p['code_sha256'].items())
    training=ROOT/'evidence/cross_day_model_selection_20261019/synthetic'/f'k{k}_holdout'
    model=read_json(training/'model.json');config=read_json(training/'online_truth.json')['config']
    config={**config,'seed':p['seeds'][str(k)],'arrival_rate_s':.16,'regime_change':False,'independent_lane_rng':True}
    env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    normal_truth=None
    for name in p['cases']:
        out=OUT/'synthetic_paired'/f'k{k}_{name}';out.mkdir(parents=True,exist_ok=False);began=time.monotonic()
        change={'blocking':.22,'block_approaches':['N']} if name=='blocked_N' else (
            {'single_extension':dict(phase=0,after_s=600,seconds=12)} if name=='extended_12s' else {})
        tracks,truth=sim.generate({**config,**change},env);save(out/'truth.json',truth)
        if name=='normal': normal_truth=truth
        elif name=='blocked_N':
            assert truth['signal_plan']==normal_truth['signal_plan']
            assert ([v for v in truth['vehicle_crossings'] if not v['movement'].startswith('N->')]==
                    [v for v in normal_truth['vehicle_crossings'] if not v['movement'].startswith('N->')])
        expected={}
        for a,b in dict(N='S',S='N',E='W',W='E').items():
            phases={z for z,g in enumerate(truth['groups']) if a+'->_'+b in g}
            expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
        engine=CausalIntersection(model);stats=Counter();confusion=Counter()
        # Truth is already saved before the first online tick. Never pass it to engine.
        for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+1800000):
            second=(packet['timestamp_ms']-sim.BASE_MS)/1000;r=engine.ingest(packet)
            if second<180:continue
            for a,h in r['heads'].items():
                actual=sim.movement_color_at(expected[a],second)[0];pred=h['main']['state']
                stats['total']+=1;stats['correct']+=pred==actual;stats['unknown']+=pred=='UNKNOWN'
                confusion[f'{actual}->{pred}']+=1
                if 756<second<1152:
                    prefix='incident_N' if a=='N' else 'incident_other'
                    stats[prefix+'_total']+=1;stats[prefix+'_correct']+=pred==actual
                    if a=='N' and actual=='GREEN':
                        stats['incident_N_green_total']+=1;stats['incident_N_green_correct']+=pred==actual
        assert all(digest(ROOT/f)==h for f,h in p['code_sha256'].items())
        result=dict(k=k,case=name,counts=dict(stats),accuracy=stats['correct']/stats['total'],
            confusion=dict(confusion),model_sha256=digest(training/'model.json'),truth_sha256=digest(out/'truth.json'),
            tracks=len(tracks),runtime_s=time.monotonic()-began,
            same_signal_as_normal=name!='extended_12s',video_and_annotations_used=False)
        save(out/'result.json',result);print('INCIDENT',k,name,result['accuracy'],dict(stats),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seal',action='store_true');p.add_argument('--k',type=int,choices=[2,3])
    args=p.parse_args();seal() if args.seal else run(args.k)
