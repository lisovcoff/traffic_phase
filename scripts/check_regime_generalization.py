"""Fresh demand seeds: raw ZIP training and causal trajectory-only online tests."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import json
from pathlib import Path
import time
import types
import uuid
import zipfile
import gzip

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,run_project,digest
from scripts.check_regime_observations import baseline_class,OUT,RUNTIME


def seal():
    cases=[]
    for index,k in enumerate((2,3,4,5)):
        for condition in ('ordinary','shifted','holdout'):
            case=dict(id=f'k{k}_{condition}',k=k,partition='holdout' if condition=='holdout' else 'development',
                duration_s=1800,training_duration_s=1500,periods=[90,108],arrival_rate_s=.08,
                training_seeds=[2026107000+index*100+1,2026107000+index*100+2],online_seed=2026107000+index*100+3)
            if condition=='shifted':case.update(online_seed=case['online_seed']+20,arrival_rate_s=.12,regime_change=True,dropout=.1)
            if condition=='holdout':case.update(online_seed=case['online_seed']+40,training_seeds=[s+40 for s in case['training_seeds']],
                arrival_rate_s=.05,regime_change=True,nonzero_stops=True,dropout=.15)
            cases.append(case)
    save(OUT/'synthetic_protocol.json',dict(cases=cases,warmup_s=180,
        inference_inputs='training raw vehicle ZIP, then independent-demand causal packets only',
        simulator_scope='finite FIFO queues, sensor noise, reaction, permissive turns; not independent field lamp truth',
        holdout_policy='do not inspect holdout metrics until candidate code frozen',
        metrics='all observed main heads and all seconds after warmup; UNKNOWN counts as incorrect'))


def run_case(identifier):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_online import CausalIntersection
    from app.core.intersection_emissions import MovementMarks
    cases=read_json(OUT/'synthetic_protocol.json')['cases'];case=next(c for c in cases if c['id']==identifier)
    out=OUT/'synthetic'/identifier;out.mkdir(parents=True,exist_ok=False)
    runtime=RUNTIME/'synthetic'/identifier;runtime.mkdir(parents=True,exist_ok=False)
    env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    folder=ROOT/'logs/intersection_projects'/uuid.uuid4().hex;folder.mkdir(parents=True)
    source=folder/'input.zip';began=time.monotonic()
    code_sha=digest(ROOT/'app/core/intersection_online.py')
    with zipfile.ZipFile(source,'x',compression=zipfile.ZIP_DEFLATED) as archive:
        for i,(seed,period) in enumerate(zip(case['training_seeds'],case['periods'])):
            tracks,truth=sim.generate(dict(seed=seed,k=case['k'],duration_s=case['training_duration_s'],period_s=period,
                arrival_rate_s=.08,cycle_jitter=.025,realistic_turns=True),env)
            save(out/f'training{i}_truth.json',truth)
            archive.writestr(f'session{i}.json',json.dumps(tracks,separators=(',',':')))
    config=dict(seed=case['online_seed'],k=case['k'],duration_s=case['duration_s'],period_s=90,
        arrival_rate_s=case['arrival_rate_s'],cycle_jitter=.025,realistic_turns=True)
    for key in ('regime_change','nonzero_stops','dropout'):
        if key in case:config[key]=case[key]
    tracks,truth=sim.generate(config,env);save(out/'online_truth.json',truth)
    # All signal truth sealed before the application reads training trajectories.
    model=run_project(source,folder)
    save(out/'model.json',model)
    expected={}
    for a,b in dict(N='S',S='N',E='W',W='E').items():
        phases={p for p,g in enumerate(truth['groups']) if a+'->_'+b in g}
        expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
    baseline=baseline_class()(model);normalized=baseline_class()(model)
    normalized.marks=MovementMarks(model['regimes']);normalized._observe=types.MethodType(CausalIntersection._observe,normalized)
    engines=dict(baseline=baseline,normalized=normalized,candidate=CausalIntersection(model))
    stats={name:Counter() for name in engines};modes={name:Counter() for name in engines};latency={n:[] for n in engines}
    with (runtime/'issuance.jsonl').open('x',encoding='utf8') as issued:
        for packet in packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+case['duration_s']*1000):
            second=(packet['timestamp_ms']-sim.BASE_MS)/1000;row=dict(second=second)
            for name,engine in engines.items():
                start=time.perf_counter();r=engine.ingest(packet);latency[name].append((time.perf_counter()-start)*1000)
                modes[name][r['regime_id']]+=1
                row[name]={a:h['main']['state'] for a,h in r['heads'].items()}
                if second<180:continue
                for a,color in row[name].items():
                    actual=sim.movement_color_at(expected[a],second)[0]
                    stats[name]['total']+=1;stats[name]['known']+=color!='UNKNOWN';stats[name]['correct']+=color==actual
                    stats[name]['correct_'+actual]+=color==actual;stats[name]['total_'+actual]+=1
            issued.write(json.dumps(row,separators=(',',':'))+'\n')
    import numpy as np
    scores={name:dict(counts=dict(s),accuracy=s['correct']/max(1,s['total']),coverage=s['known']/max(1,s['total']),
        tick_p95_ms=float(np.quantile(latency[name],.95)),regime_counts=dict(modes[name])) for name,s in stats.items()}
    save(out/'receipt.json',dict(case=case,model_id=model['model_id'],working_K=[r['phase_count'] for r in model['regimes']],
        latent_K=[s['latent_phase_count'] for s in model['sessions']],scores=scores,
        code_sha256=code_sha,runtime_s=time.monotonic()-began,
        online_truth_supplied_to_predictor=False,training_online_demand_seeds_disjoint=True))
    print(identifier,'COMPLETE',[(n,round(s['accuracy'],4)) for n,s in scores.items()],flush=True)


def compare_case(identifier):
    """Fresh byte-identical trajectory generation; causal event-cache parity."""
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from app.core.intersection_online import CausalIntersection
    out=OUT/'synthetic'/identifier;runtime=RUNTIME/'synthetic'/identifier
    receipt=read_json(out/'receipt.json');case=receipt['case'];truth=read_json(out/'online_truth.json')
    env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json')
    tracks,regenerated=sim.generate(truth['config'],env);assert json.loads(json.dumps(regenerated))==truth
    model=read_json(out/'model.json')
    baseline=baseline_class()(model);original=baseline._observe;events=[]
    def observe(rows):events.extend(rows);original(rows)
    baseline._observe=observe
    rows=[]
    with (runtime/'issuance.jsonl').open(encoding='utf8') as issuance:
        for packet,line in zip(packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+case['duration_s']*1000),issuance):
            events.clear();r=baseline.ingest(packet);expected=json.loads(line)
            assert {a:h['main']['state'] for a,h in r['heads'].items()}==expected['baseline']
            rows.append(dict(timestamp_ms=packet['timestamp_ms'],sequence=packet['sequence'],events=events.copy()))
    with gzip.open(runtime/'causal_events.json.gz','xt',encoding='utf8') as f:json.dump(rows,f,separators=(',',':'))
    current=(ROOT/'app/core/intersection_online.py').read_text(encoding='utf8')
    current=current.replace('events=[];rendered=[]','events=list(self.replay_events);rendered=[]')
    module=types.ModuleType('causal_event_replay');exec(compile(current,'<causal-event-replay>','exec'),module.__dict__)
    engines={name:module.CausalIntersection(model) for name in ('candidate','noise10','noise20')}
    from app.core.intersection_emissions import MovementMarks
    for engine in engines.values():engine.marks=MovementMarks(model['regimes'])
    for name,noise in [('noise10',.1),('noise20',.2)]:
        engine=engines[name];n=len(engine.marks.vocabulary)
        engine.marks.distributions=[(1-noise)*m+noise/n for m in engine.marks.distributions]
    expected={}
    for a,b in dict(N='S',S='N',E='W',W='E').items():
        phases={p for p,g in enumerate(truth['groups']) if a+'->_'+b in g}
        expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
    stats={name:Counter() for name in engines}
    for row in rows:
        second=(row['timestamp_ms']-sim.BASE_MS)/1000
        for name,engine in engines.items():
            engine.replay_events=row['events'];r=engine.ingest(dict(timestamp_ms=row['timestamp_ms'],sequence=row['sequence'],vehicles=[]))
            if second<180:continue
            for a,h in r['heads'].items():
                color=h['main']['state'];actual=sim.movement_color_at(expected[a],second)[0]
                stats[name]['total']+=1;stats[name]['known']+=color!='UNKNOWN';stats[name]['correct']+=color==actual
    scores={n:dict(counts=dict(s),accuracy=s['correct']/s['total'],coverage=s['known']/s['total']) for n,s in stats.items()}
    save(out/'comparison.json',dict(scores=scores,baseline=receipt['scores']['baseline'],causal_event_cache_parity_packets=len(rows),
        code_sha256=digest(ROOT/'app/core/intersection_online.py')))
    print('COMPARE',identifier,[(n,round(s['accuracy'],4)) for n,s in scores.items()],flush=True)


def final_development(revision='v6'):
    from scripts import realistic_traffic_benchmark as sim
    from scripts.online_packets import packets_from_tracks
    from scripts.rebuild_intersection_projection import rebuild
    cases=[c for c in read_json(OUT/'synthetic_protocol.json')['cases'] if c['partition']=='development']
    env=read_json(ROOT/'evidence/all_archives_synthetic_20261019/simulation_environment.json');results=[]
    code=(ROOT/'app/core/intersection_online.py').read_text(encoding='utf8').replace('events=[];rendered=[]','events=list(self.replay_events);rendered=[]')
    module=types.ModuleType('final_development_replay');exec(compile(code,'<final-development>','exec'),module.__dict__)
    for case in cases:
        identifier=case['id'];out=OUT/'synthetic'/identifier;runtime=RUNTIME/'synthetic'/identifier
        receipt=read_json(out/'receipt.json');old=read_json(out/'model.json');truth=read_json(out/'online_truth.json')
        cache=runtime/'causal_events.json.gz'
        if not cache.exists():
            tracks,regenerated=sim.generate(truth['config'],env);assert json.loads(json.dumps(regenerated))==truth
            base=baseline_class()(old);original=base._observe;observed=[]
            def observe(events):observed.extend(events);original(events)
            base._observe=observe;rows=[]
            with (runtime/'issuance.jsonl').open(encoding='utf8') as source:
                for packet,line in zip(packets_from_tracks(tracks,start_ms=sim.BASE_MS,end_ms=sim.BASE_MS+case['duration_s']*1000),source):
                    observed.clear();r=base.ingest(packet)
                    assert {a:h['main']['state'] for a,h in r['heads'].items()}==json.loads(line)['baseline']
                    rows.append(dict(timestamp_ms=packet['timestamp_ms'],sequence=packet['sequence'],events=observed.copy()))
            with gzip.open(cache,'xt',encoding='utf8') as f:json.dump(rows,f,separators=(',',':'))
        with gzip.open(cache,'rt',encoding='utf8') as f:rows=json.load(f)
        if (out/'final_projection.json').exists():
            from app.core.intersection_project import read_model
            model=read_model(ROOT/'logs/intersection_projects'/read_json(out/'final_projection.json')['model_id'])
        else:model=rebuild(old['model_id'],out/'final_projection.json')
        engine=module.CausalIntersection(model)
        expected={}
        for a,b in dict(N='S',S='N',E='W',W='E').items():
            phases={p for p,g in enumerate(truth['groups']) if a+'->_'+b in g}
            expected[a]=sim.movement_signal_plan(truth['signal_plan'],phases)
        counts=Counter()
        for row in rows:
            engine.replay_events=row['events'];r=engine.ingest(dict(timestamp_ms=row['timestamp_ms'],sequence=row['sequence'],vehicles=[]))
            second=(row['timestamp_ms']-sim.BASE_MS)/1000
            if second<180:continue
            for a,h in r['heads'].items():
                color=h['main']['state'];actual=sim.movement_color_at(expected[a],second)[0]
                counts['total']+=1;counts['known']+=color!='UNKNOWN';counts['correct']+=color==actual
        result=dict(id=identifier,model_id=model['model_id'],baseline=receipt['scores']['baseline'],
            working_K=[r['phase_count'] for r in model['regimes']],counts=dict(counts),accuracy=counts['correct']/counts['total'],
            coverage=counts['known']/counts['total'],code_sha256=digest(ROOT/'app/core/intersection_online.py'),
            causal_event_parity_packets=len(rows),heldout=False)
        save(out/('final_receipt.json' if revision=='v6' else 'final_receipt_'+revision+'.json'),result);results.append(result)
        print('FINAL_DEV',identifier,round(result['baseline']['accuracy'],4),round(result['accuracy'],4),flush=True)
    save(OUT/('development_'+revision+'_complete.json'),dict(cases=results))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--seal',action='store_true');parser.add_argument('--case')
    parser.add_argument('--compare')
    parser.add_argument('--final-development',action='store_true')
    parser.add_argument('--revision',default='v6')
    args=parser.parse_args()
    if args.seal:seal()
    elif args.final_development:final_development(args.revision)
    elif args.compare:compare_case(args.compare)
    else:run_case(args.case)
