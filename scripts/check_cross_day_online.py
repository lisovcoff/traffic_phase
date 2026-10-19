"""Full February27 causal replay using exclusively the earlier-week offline model."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter,defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()


def main(accelerated=False):
    from app.core.intersection_project import read_json,read_model,digest
    from app.core import intersection_online_store as store
    from app.core.intersection_online import CausalIntersection,VERSION
    from app.api.intersection_online import LivePacket
    from scripts.realistic_traffic_benchmark import match_transitions
    import numpy as np
    out=ROOT/'evidence/cross_day_sverdlovsky_20261019'
    complete=read_json(out/'verified_v2/accelerated_complete.json')
    folder=ROOT/'logs/intersection_projects'/complete['model_id'];model=read_model(folder)
    manifest=read_json(out/'online_packets_manifest.json');packets=Path(manifest['output'])
    assert digest(packets)==manifest['sha256']
    assert max(s['observation_end_ms'] for s in model['sessions'])<manifest['first_ms']
    runtime=ROOT/'.web_runtime/cross_day_sverdlovsky_20261019'
    if accelerated:
        job=read_json(out/'online_job.json');stream=job['stream_id']
        assert job['model_id']==model['model_id'] and job['offline_fingerprint']==model['fingerprint']
    else:stream=store.create_stream(folder)['stream_id']
    # Reference labels are evaluator-only; never passed to create/accept/model.
    windows=[]
    for file,bounds in [('accuracy_recovery_20261019/video_holdout/truth_sealed.json',[2100,2400]),
                        ('yellow_timing_20261019/sverdlovsky/fresh_truth_sealed.json',[3300,3600])]:
        truth=read_json(ROOT/'evidence'/file)['rows']
        base=truth[0]['clock_mapping']['json_bracket_fixed_clock_ms'][0]-truth[0]['bracket_s'][0]*1000
        windows.append(dict(truth=truth,pts_s=bounds,start_ms=base+bounds[0]*1000,end_ms=base+bounds[1]*1000,
            onsets={color:[] for color in ('GREEN','YELLOW','RED')}))
    previous=None
    colors=defaultdict(Counter);regimes=Counter();latencies=[];count=0;began=time.monotonic()
    if not accelerated:
        save(out/'online_job.json',dict(model_id=model['model_id'],stream_id=stream,offline_fingerprint=model['fingerprint'],
            packet_manifest_sha256=digest(out/'online_packets_manifest.json'),future_fields=False,
            view_url=f'http://127.0.0.1:8017/visualization?project={model["model_id"]}&stream={stream}'))
    prefix={};engine=None;db=None
    if accelerated:
        home=store._home(folder,stream);stream_manifest=read_json(home/'stream.json')
        assert stream_manifest['engine']==VERSION
        db=sqlite3.connect(home/'stream.sqlite3')
        prefix={r[0]:r[1:] for r in db.execute('SELECT sequence,digest,response FROM packets')}
        engine=CausalIntersection(model)
    issuance='online_issuance_accelerated.jsonl' if accelerated else 'online_issuance.jsonl'
    with packets.open(encoding='utf8') as source,(runtime/issuance).open('x',encoding='utf8') as issued:
        for line in source:
            packet=LivePacket.model_validate_json(line).model_dump()
            assert all(d['millis']<=packet['timestamp_ms'] for v in packet['vehicles'] for d in v['detections'])
            before=time.perf_counter()
            if accelerated:
                result=engine.ingest(packet)
                payload=store._encode(packet);encoded=store._encode(result);packet_digest=hashlib.sha256(payload.encode()).hexdigest()
                if packet['sequence'] in prefix:
                    assert prefix[packet['sequence']]==(packet_digest,encoded),'ordinary/batch issuance mismatch'
                else:
                    db.execute('INSERT INTO packets VALUES (?,?,?,?,?)',(packet['sequence'],packet['timestamp_ms'],packet_digest,payload,encoded))
                if (count+1)%300==0:db.commit()
            else:result=store.accept_packet(folder,stream,packet)
            latencies.append(time.perf_counter()-before)
            assert result['model_fingerprint']==model['fingerprint'] and result['phase_count'] in {r['phase_count'] for r in model['regimes']}
            assert not result['video_used'] and not result['annotations_used']
            count+=1;regimes[result['regime_id']]+=1
            for a,h in result['heads'].items():colors[a][h['main']['state']]+=1
            color=result['heads']['N']['main']['state'];timestamp=result['timestamp_ms']
            for window in windows:
                if window['start_ms']<=timestamp<=window['end_ms'] and color!=previous and color in window['onsets']:
                    window['onsets'][color].append(timestamp)
            previous=color
            issued.write(json.dumps(dict(sequence=result['sequence'],timestamp_ms=timestamp,
                regime_id=result['regime_id'],phase_id=result['phase_id'],phase_confidence=result['phase_confidence'],
                heads=result['heads'],events=result['evidence_count']),separators=(',',':'))+'\n')
            if count%300==0:
                issued.flush()
                print('ONLINE',count,'/',manifest['packets'],'seconds',round(time.monotonic()-began,1),flush=True)
                from app.core.intersection_project import write_json
                write_json(out/'online_progress.json',dict(accepted=count,total=manifest['packets'],elapsed_s=time.monotonic()-began))
    if db is not None:db.commit();db.close()
    assert count==manifest['packets']
    metrics=[]
    for window in windows:
        scores={}
        for color,predicted in window['onsets'].items():
            mids=[sum(row['clock_mapping']['json_bracket_fixed_clock_ms'])/2 for row in window['truth'] if row['color']==color]
            scores[color]={str(t):match_transitions([p/1000 for p in predicted],[m/1000 for m in mids],t) for t in (2,5,10)}
        metrics.append(dict(video_pts_s=window['pts_s'],onsets_ms=window['onsets'],scores=scores))
    save(out/'online_complete.json',dict(status='COMPLETED_NOT_UNIVERSAL_ACCURACY_ACCEPTANCE',model_id=model['model_id'],stream_id=stream,
        packets=count,duration_s=(manifest['last_ms']-manifest['first_ms'])/1000,runtime_s=time.monotonic()-began,
        latency_s=dict(p50=float(np.quantile(latencies,.5)),p95=float(np.quantile(latencies,.95)),max=max(latencies),over_one_second=sum(t>1 for t in latencies)),
        colors={a:dict(c) for a,c in colors.items()},regime_packet_counts=dict(regimes),
        known_main_coverage={a:1-c['UNKNOWN']/count for a,c in colors.items()},video_metrics=metrics,
        train_test_dates_disjoint=True,video_supplied_to_engine=False,annotations_supplied_to_engine=False,
        accelerated_journal_commits=accelerated,ordinary_path_exact_prefix_packets=len(prefix),
        latency_scope='accelerated replay compute/enqueue, NOT per-packet durable HTTP latency' if accelerated else 'ordinary per-packet durable store',
        limitations='Labels previously revealed in development. Conditional video/JSON clock. Visible N-main only; other heads have no independent lamp truth. Known coverage is not accuracy.'))
    from app.core.intersection_project import write_json
    write_json(out/'online_progress.json',dict(status='COMPLETED',accepted=count,total=manifest['packets'],elapsed_s=time.monotonic()-began))
    print('FULL ONLINE COMPLETE',count,stream,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--accelerated',action='store_true')
    main(parser.parse_args().accelerated)
