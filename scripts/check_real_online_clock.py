"""Conditional real replay against already-revealed visible N-main video brackets.

Same recording is included in the historical offline model. This is NOT an
independent accuracy holdout. Video/clock mapping is evaluator-only, after replay.
"""
import argparse
import json
from pathlib import Path

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
prepare_worker_environment()


def main(out,model_id='402997a8e8ce4e989576e5764903ba39'):
    from app.core.intersection_project import read_model,read_json
    from app.core.intersection_online import CausalIntersection
    from scripts.v9_spatial_visualizer import load_tracks
    from scripts.online_packets import packets_from_tracks
    from scripts.realistic_traffic_benchmark import match_transitions
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    model=read_model(ROOT/'logs/intersection_projects'/model_id)
    session=model['sessions'][0];tracks=load_tracks(Path(model['input_path_private']),source_member=session['source_member'])
    truth=read_json(ROOT/'evidence/accuracy_recovery_20261019/video_holdout/truth_sealed.json')['rows']
    first=truth[0];base=first['clock_mapping']['json_bracket_fixed_clock_ms'][0]-first['bracket_s'][0]*1000
    engine=CausalIntersection(model);onsets={color:[] for color in ('GREEN','YELLOW','RED')};previous=None;rows=[]
    for packet in packets_from_tracks(tracks,start_ms=base+1980000,end_ms=base+2400000):
        r=engine.ingest(packet);color=r['heads']['N']['main']['state'];timestamp=r['timestamp_ms']
        if timestamp>=base+2100000 and color!=previous and color in onsets:onsets[color].append(timestamp)
        rows.append(dict(timestamp_ms=timestamp,main_N=color,phase=r['phase_name'],confidence=r['phase_confidence'],evidence_count=r['evidence_count']))
        previous=color
    save(out/'causal_issuance.json',rows)
    metrics={}
    for color,predicted in onsets.items():
        brackets=[r['clock_mapping']['json_bracket_fixed_clock_ms'] for r in truth if r['color']==color]
        # Distance to the independently read image bracket, not its midpoint.
        mid=[sum(b)/2 for b in brackets]
        metrics[color]={str(t):match_transitions([p/1000 for p in predicted],[m/1000 for m in mid],t) for t in (2,5,10)}
    save(out/'receipt.json',dict(status='COMPLETED_NOT_INDEPENDENT_VALIDATION',model_id=model['model_id'],
        evaluated_video_pts_s=[2100,2400],warmup_video_pts_s=[1980,2100],onsets_ms=onsets,metrics=metrics,
        video_supplied_to_engine=False,clock_correction_supplied_to_engine=False,
        limitations='same-recording offline training; already revealed labels; conditional video/JSON clock; midpoint scoring omits clock uncertainty'))
    print(metrics,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--model',default='402997a8e8ce4e989576e5764903ba39');args=p.parse_args();main(args.out,args.model)
