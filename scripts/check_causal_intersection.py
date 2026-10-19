"""Independent-demand online replay with offline-only structure; diagnostic metrics.

All simulated cases are sealed before fitting. This first integration benchmark
does not certify physical accuracy or replace the earlier offline holdout.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import uuid
import zipfile

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_project import run_project,read_json
    from app.core.intersection_online import CausalIntersection
    from app.api.intersection_projects import PROJECT_ROOT
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    cases=[dict(k=k,training_seeds=[2026101921+k,2026101941+k],online_seed=2026101961+k,
        periods=[90,106.2],duration_s=1800,regime_change=True) for k in (2,3)]
    save(out/'protocol.json',dict(cases=cases,warmup_s=180,video=False,annotations=False,
        metrics='all four main heads incl UNKNOWN; coverage and conditional accuracy separately; causal issuance',
        scope='first diagnostic online integration; not independently accepted physical accuracy'))
    env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    sealed=[]
    for case in cases:
        folder=PROJECT_ROOT/uuid.uuid4().hex;folder.mkdir(parents=True);source=folder/'input.zip'
        with zipfile.ZipFile(source,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            for i,(seed,period) in enumerate(zip(case['training_seeds'],case['periods'])):
                tracks,truth=sim.generate(dict(seed=seed,k=case['k'],duration_s=900,period_s=period,
                    arrival_rate_s=.08,cycle_jitter=.025,realistic_turns=True),env)
                archive.writestr(f'session{i}.json',json.dumps(tracks,separators=(',',':')))
                save(out/f"k{case['k']}_training{i}_truth.json",truth)
        tracks,truth=sim.generate(dict(seed=case['online_seed'],k=case['k'],duration_s=case['duration_s'],
            period_s=90,arrival_rate_s=.08,cycle_jitter=.025,regime_change=True,realistic_turns=True),env)
        save(out/f"k{case['k']}_online_truth.json",truth)
        # Runtime receives only the driver packets, never truth or complete tracks.
        packets=list(packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+case['duration_s']*1000))
        feed=out/f"k{case['k']}_packets.jsonl"
        with feed.open('x',encoding='utf8') as f:
            for packet in packets:f.write(json.dumps(packet,separators=(',',':'))+'\n')
        sealed.append((case,folder,source,truth,packets))
    results=[]
    for case,folder,source,truth,packets in sealed:
        model=run_project(source,folder);engine=CausalIntersection(model)
        save(out/f"k{case['k']}_model.json",{k:v for k,v in model.items() if k!='input_path_private'})
        main_runs={}
        for approach,target in dict(N='S',S='N',E='W',W='E').items():
            phases={p for p,g in enumerate(truth['groups']) if approach+'->_'+target in g}
            main_runs[approach]=sim.movement_signal_plan(truth['signal_plan'],phases)
        counts=Counter();samples=[];latencies=[]
        with (out/f"k{case['k']}_issuance.jsonl").open('x',encoding='utf8') as f:
            for packet in packets:
                start=time.perf_counter();r=engine.ingest(packet);latencies.append((time.perf_counter()-start)*1000)
                second=(packet['timestamp_ms']-sim.BASE_MS)/1000
                f.write(json.dumps(dict(timestamp_ms=r['timestamp_ms'],phase=r['phase_id'],regime=r['regime_id'],
                    confidence=r['phase_confidence'],heads=r['heads'],evidence_count=r['evidence_count']),separators=(',',':'))+'\n')
                if second<180:continue
                for a,head in r['heads'].items():
                    expected=sim.signal_at(main_runs[a],0,second)[0];actual=head['main']['state']
                    counts['total']+=1;counts['known']+=actual!='UNKNOWN';counts['correct']+=actual==expected
                if int(second)%120==0:samples.append(dict(second=second,phase=r['phase_id'],confidence=r['phase_confidence'],regime=r['regime_id']))
        import numpy as np
        result=dict(k=case['k'],model_id=model['model_id'],offline_working_k=[r['phase_count'] for r in model['regimes']],
            offline_regimes=len(model['regimes']),packets=len(packets),counts=dict(counts),
            main_accuracy_including_unknown=counts['correct']/max(1,counts['total']),
            known_coverage=counts['known']/max(1,counts['total']),
            conditional_known_accuracy=counts['correct']/max(1,counts['known']),
            tick_ms_p50=float(np.quantile(latencies,.5)),tick_ms_p95=float(np.quantile(latencies,.95)),samples=samples)
        save(out/f"k{case['k']}_receipt.json",result);results.append(result);print(result,flush=True)
    save(out/'receipt.json',dict(status='COMPLETED_NOT_ACCURACY_ACCEPTED',results=results,
        future_tracks_supplied_to_engine=False,offline_and_online_demand_seeds_disjoint=True))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    main(parser.parse_args().out)
