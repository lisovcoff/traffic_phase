"""Full raw-packet v5 replay, preserving the old stream and its failed results."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
import hashlib
import json
import sqlite3
import time

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from scripts.check_regime_observations import OUT,RUNTIME


def main(model_id=None,run_name=None):
    from pathlib import Path
    out=OUT/run_name if run_name else OUT
    runtime=RUNTIME/run_name if run_name else RUNTIME
    out.mkdir(parents=True,exist_ok=True);runtime.mkdir(parents=True,exist_ok=True)
    from app.core.intersection_project import read_json,read_model,digest
    from app.core import intersection_online_store as store
    from app.core.intersection_online import CausalIntersection,VERSION
    from app.api.intersection_online import LivePacket
    from scripts.realistic_traffic_benchmark import match_transitions
    import numpy as np
    old=ROOT/'evidence/cross_day_sverdlovsky_20261019'
    manifest=read_json(old/'online_packets_manifest.json');job=read_json(old/'online_job.json')
    folder=ROOT/'logs/intersection_projects'/(model_id or job['model_id']);model=read_model(folder)
    packets=__import__('pathlib').Path(manifest['output']);assert digest(packets)==manifest['sha256']
    assert max(s['observation_end_ms'] for s in model['sessions'])<manifest['first_ms']
    stream=store.create_stream(folder)['stream_id'];home=store._home(folder,stream)
    code={p:digest(ROOT/p) for p in ('app/core/intersection_online.py','app/core/intersection_emissions.py','app/core/intersection_durations.py')}
    save(out/'release_job.json',dict(model_id=model['model_id'],stream_id=stream,engine=VERSION,code_sha256=code,
        offline_fingerprint=model['fingerprint'],packet_sha256=manifest['sha256'],
        url=f'http://127.0.0.1:8017/visualization?project={model["model_id"]}&stream={stream}'))
    windows=[]
    for file,bounds in [('accuracy_recovery_20261019/video_holdout/truth_sealed.json',[2100,2400]),
                        ('yellow_timing_20261019/sverdlovsky/fresh_truth_sealed.json',[3300,3600])]:
        rows=read_json(ROOT/'evidence'/file)['rows'];base=rows[0]['clock_mapping']['json_bracket_fixed_clock_ms'][0]-rows[0]['bracket_s'][0]*1000
        windows.append(dict(rows=rows,pts=bounds,start=base+bounds[0]*1000,end=base+bounds[1]*1000,onsets={c:[] for c in ('GREEN','YELLOW','RED')}))
    engine=CausalIntersection(model);counts=Counter();previous=None;latencies=[];began=time.monotonic();parity=0
    db=None
    with packets.open(encoding='utf8') as source,(runtime/'release_issuance.jsonl').open('x',encoding='utf8') as issued:
        for count,line in enumerate(source,1):
            packet=LivePacket.model_validate_json(line).model_dump();start=time.perf_counter()
            result=engine.ingest(packet);encoded=store._encode(result)
            if count<=24:
                actual=store.accept_packet(folder,stream,packet)
                assert store._encode(actual)==encoded,'ordinary store / raw replay mismatch'
                parity+=1
            else:
                if db is None:db=sqlite3.connect(home/'stream.sqlite3')
                payload=store._encode(packet);sha=hashlib.sha256(payload.encode()).hexdigest()
                db.execute('INSERT INTO packets VALUES (?,?,?,?,?)',(packet['sequence'],packet['timestamp_ms'],sha,payload,encoded))
                if count%300==0:db.commit()
            latencies.append(time.perf_counter()-start);counts[result['regime_id']]+=1
            color=result['heads']['N']['main']['state'];now=result['timestamp_ms']
            for win in windows:
                if win['start']<=now<=win['end'] and color!=previous and color in win['onsets']:win['onsets'][color].append(now)
            previous=color
            issued.write(json.dumps(dict(timestamp_ms=now,sequence=result['sequence'],regime=result['regime_id'],
                heads=result['heads'],phase=result['phase_id'],confidence=result['phase_confidence']),separators=(',',':'))+'\n')
            if count%1200==0:issued.flush();print('RELEASE',count,round(time.monotonic()-began,1),flush=True)
    if db:db.commit();db.close()
    assert count==manifest['packets']
    assert code=={p:digest(ROOT/p) for p in code},'code changed during sealed release replay'
    metrics=[]
    for win in windows:
        scores={}
        for color,pred in win['onsets'].items():
            truth=[sum(row['clock_mapping']['json_bracket_fixed_clock_ms'])/2000 for row in win['rows'] if row['color']==color]
            scores[color]={str(t):match_transitions([p/1000 for p in pred],truth,t) for t in (2,5,10)}
        metrics.append(dict(pts_s=win['pts'],scores=scores,onsets_ms=win['onsets']))
    with sqlite3.connect(home/'stream.sqlite3') as db:
        integrity=db.execute('PRAGMA integrity_check').fetchone()[0]
        n,low,high=db.execute('SELECT COUNT(*),MIN(sequence),MAX(sequence) FROM packets').fetchone()
        assert integrity=='ok' and n==count and low==0 and high==count-1
    save(out/'release_complete.json',dict(engine=VERSION,model_id=model['model_id'],stream_id=stream,packets=count,
        ordinary_store_exact_prefix_packets=parity,accelerated_journal_commits=True,
        tick_s_p50=float(np.quantile(latencies,.5)),tick_s_p95=float(np.quantile(latencies,.95)),runtime_s=time.monotonic()-began,
        modes=dict(counts),video_metrics=metrics,code_sha256=code,sqlite_integrity=integrity,
        semantics='raw causal packets, offline earlier dates, unchanged fingerprint; video evaluator only',
        limitations='Previously revealed video windows and conditional camera clock; N main only; accelerated latency is not durable HTTP latency'))
    print('COMPLETE',stream,flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--model');parser.add_argument('--run-name')
    args=parser.parse_args();main(args.model,args.run_name)
