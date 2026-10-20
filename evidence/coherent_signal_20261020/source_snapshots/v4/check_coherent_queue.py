"""Offline-only queue-reference enrichment and raw causal joint-filter replay."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
from copy import deepcopy
import json
import time
import uuid
import numpy as np
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,read_model,digest,model_fingerprint
from app.core.intersection_signal_filter import CoherentIntersection
from app.core.intersection_queue_observations import learn_queue_references
from scripts.check_incident_counterfactual import MODEL,GreenStretch

OUT=ROOT/'evidence/coherent_signal_20261020/v4'
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020/v4'
SOURCES=['app/core/intersection_signal_filter.py','app/core/intersection_queue_observations.py','scripts/check_coherent_queue.py']


def train():
    from app.core.v9.events import _iter_json_records
    OUT.mkdir(parents=True,exist_ok=True);LOCAL.mkdir(parents=True,exist_ok=True)
    path=ROOT.parent/'data/17_2025_2_12_7.json';sha=digest(path);stats=Counter();bounds=[]
    def records():
        with path.open('rb') as stream:
            for t in _iter_json_records(stream):
                stats['tracks']+=1;stats['detections']+=len(t.get('detections',[]))
                bounds.extend(d['millis'] for d in t.get('detections',[])[::100])
                yield t
    learned=learn_queue_references(records());assert digest(path)==sha
    m=deepcopy(read_model(ROOT/'logs/intersection_projects'/MODEL));original=m['fingerprint']
    m['model_id']=uuid.uuid4().hex;m['queue_observations']=learned;m['fingerprint']=model_fingerprint(m)
    save(LOCAL/'model.json',m)
    save(OUT/'protocol.json',dict(source_sha256={p:digest(ROOT/p) for p in SOURCES},
        geometry_training_source=str(path),geometry_source_sha256=sha,geometry_scope='one earlier offline hourly recording; no target-day geometry fit',
        source_counts=dict(stats),sampled_detection_extent_ms=[min(bounds),max(bounds)],
        parent_model=MODEL,parent_fingerprint=original,candidate_model_sha256=digest(LOCAL/'model.json'),
        reference=learned,clearance_s=4,point_estimator='joint_state',
        lamp_truth_supplied_to_training=False,production_enabled=False))
    print('REFERENCES',json.dumps(learned),flush=True)


def replay(case):
    from app.api.intersection_online import LivePacket
    protocol=read_json(OUT/'protocol.json');assert all(digest(ROOT/p)==h for p,h in protocol['source_sha256'].items())
    m=read_json(LOCAL/'model.json');assert digest(LOCAL/'model.json')==protocol['candidate_model_sha256']
    source=ROOT/'.web_runtime/incident_validation_20261020'/(case+'.jsonl')
    manifest=read_json(ROOT/'evidence/incident_validation_20261020'/(case+'_packets.json'))
    assert digest(source)==manifest['sha256']
    assert protocol['sampled_detection_extent_ms'][1]<manifest['first_ms']
    p=read_json(ROOT/'evidence/incident_validation_20261020/protocol.json');warp=GreenStretch(**p['warp'])
    truth=read_json(p['truth_path'])['rows'];spans=[]
    for i in range(3):
        for color,nxt in [('GREEN','YELLOW'),('YELLOW','RED')]:
            a=next(r for r in truth if r['color']==color and r['index']==i)
            b=next(r for r in truth if r['color']==nxt and r['index']==i)
            start=a['clock_mapping']['json_bracket_fixed_clock_ms'][1];end=b['clock_mapping']['json_bracket_fixed_clock_ms'][0]
            spans.append((warp.timestamp(start) if case=='extended' else start,warp.timestamp(end) if case=='extended' else end,color))
    end_green=min(b for a,b,c in spans if c=='GREEN');counts=Counter();channels=Counter();latencies=[];transitions=[];previous=None
    engine=CoherentIntersection(m);began=time.monotonic()
    with source.open() as src,(LOCAL/(case+'_issuance.jsonl')).open('x') as dst:
        for n,line in enumerate(src,1):
            packet=LivePacket.model_validate_json(line).model_dump();start=time.perf_counter();r=engine.ingest(packet)
            latencies.append(time.perf_counter()-start);channels.update(r['observation_channels']);now=r['timestamp_ms'];color=r['heads']['N']['main']['state']
            for a,b,c in spans:
                if a<now<b:
                    counts['total']+=1;counts['correct']+=color==c;counts[c+'_total']+=1;counts[c+'_correct']+=color==c
            if case=='extended' and end_green-12000<=now<end_green:counts['added_total']+=1;counts['added_correct']+=color=='GREEN'
            if min(a for a,b,c in spans)<now<max(b for a,b,c in spans) and color!=previous:
                transitions.append(dict(timestamp_ms=now,color=color))
            previous=color
            dst.write(json.dumps(r,separators=(',',':'))+'\n')
            if n%600==0:dst.flush();print(case,n,round(time.monotonic()-began,1),flush=True)
    assert all(digest(ROOT/p)==h for p,h in protocol['source_sha256'].items())
    result=dict(case=case,counts=dict(counts),accuracy=counts['correct']/counts['total'],channels=dict(channels),
        transitions=transitions,packets=n,runtime_s=time.monotonic()-began,tick_p95_s=float(np.quantile(latencies,.95)),
        model_sha256=digest(LOCAL/'model.json'),production_enabled=False)
    save(OUT/(case+'_result.json'),result);print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['train','baseline','extended']);a=p.parse_args()
    train() if a.action=='train' else replay(a.action)
