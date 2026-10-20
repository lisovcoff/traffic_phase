"""Development replay of one joint color/duration candidate; no production promotion."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import json
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,read_model,digest
from app.core.intersection_signal_filter import JointSignalFilter
from scripts.check_incident_counterfactual import MODEL,GreenStretch

OUT=ROOT/'evidence/coherent_signal_20261020'
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020'


def seal():
    OUT.mkdir(parents=True,exist_ok=True);LOCAL.mkdir(parents=True,exist_ok=True)
    save(OUT/'protocol.json',dict(
        source_sha256={p:digest(ROOT/p) for p in ['app/core/intersection_signal_filter.py','scripts/check_coherent_signal.py']},
        baseline='causal-intersection-v7',candidate='coherent-v1',
        priors=dict(yellow_s=3,red_yellow_s=2,clearance_s=4,calibration='generic uncalibrated prior'),
        real_development='known original/+12s N-main green/yellow; then two known video windows, all colors/onsets available',
        acceptance=dict(added_green_min=10,baseline_labelled_seconds_no_loss=True,no_yellow_loss=True,
                        no_extra_yellow_to_green_reversals=True,new_synthetic_controls_no_regression=True),
        inference='offline model plus chronological vehicle events only',
        no_production_promotion_without_acceptance=True))


def replay():
    p=read_json(OUT/'protocol.json');assert all(digest(ROOT/f)==h for f,h in p['source_sha256'].items())
    parent=ROOT/'evidence/incident_validation_20261020';runtime=ROOT/'.web_runtime/incident_validation_20261020'
    protocol=read_json(parent/'protocol.json');warp=GreenStretch(**protocol['warp'])
    truth=read_json(protocol['truth_path'])['rows'];spans=[]
    for i in range(3):
        for color,nxt in [('GREEN','YELLOW'),('YELLOW','RED')]:
            a=next(r for r in truth if r['color']==color and r['index']==i)
            b=next(r for r in truth if r['color']==nxt and r['index']==i)
            spans.append((warp.timestamp(a['clock_mapping']['json_bracket_fixed_clock_ms'][1]),
                          warp.timestamp(b['clock_mapping']['json_bracket_fixed_clock_ms'][0]),color))
    end_green=min(b for a,b,c in spans if c=='GREEN');stats=Counter();transitions=[];previous=None
    f=JointSignalFilter(read_model(ROOT/'logs/intersection_projects'/MODEL))
    with (runtime/'extended_events.jsonl').open() as src,(LOCAL/'extended_predictions.jsonl').open('x') as dst:
        for line in src:
            row=json.loads(line);r=f.tick(row['timestamp_ms'],row['events']);now=row['timestamp_ms'];color=r['heads']['N']['main']['state']
            for a,b,c in spans:
                if a<now<b:
                    stats['total']+=1;stats['correct']+=color==c;stats[c+'_total']+=1;stats[c+'_correct']+=color==c
            if end_green-12000<=now<end_green:stats['added_total']+=1;stats['added_correct']+=color=='GREEN'
            if min(a for a,b,c in spans)<now<max(b for a,b,c in spans) and color!=previous:
                transitions.append(dict(timestamp_ms=now,color=color))
            previous=color;dst.write(json.dumps(dict(timestamp_ms=now,**r),separators=(',',':'))+'\n')
    result=dict(counts=dict(stats),accuracy=stats['correct']/stats['total'],transitions=transitions,
                production_enabled=False,code_sha256=p['source_sha256'])
    save(OUT/'extended_result.json',result);print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['seal','replay']);a=p.parse_args()
    seal() if a.action=='seal' else replay()
