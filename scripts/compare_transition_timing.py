"""Reproduce baseline/candidate comparison on sealed native-video brackets.

Video time is evaluator-only. Both estimators receive the same vehicle packets;
no label, clock offset, image, or scoring window is passed into their models.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def compare(model_path,candidate_model_path,packet_path,truth_path,out,*,start=5400,end=5520,warmup=200,estimator='adaptive'):
    os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
    from scripts.corpus_validation import prepare_worker_environment
    prepare_worker_environment()
    from app.core.intersection_online import CausalIntersection
    from app.experimental.intersection_leading_brake import LeadingBrakePointTimingIntersection
    from app.experimental.intersection_adaptive_timing import AdaptiveRobustTimingIntersection
    factory={'leading_brake':LeadingBrakePointTimingIntersection,'adaptive':AdaptiveRobustTimingIntersection}[estimator]

    paths=list(map(Path,[model_path,candidate_model_path,packet_path,truth_path]));mp,cp,pp,tp=paths
    model=json.loads(mp.read_text(encoding='utf8'));candidate=json.loads(cp.read_text(encoding='utf8'))
    # Candidate may add learned queue geometry; phase/duration catalogue is identical.
    if model['input']['sha256']!=candidate['input']['sha256'] or model['regimes']!=candidate['regimes']:
        raise ValueError('Candidates must use the same offline source and phase catalogue')
    labels=json.loads(tp.read_text(encoding='utf8'))['rows']
    labels=[r for r in labels if r['site']=='sverdlovsky' and r.get('clock_mapping')]
    selected=[r for r in labels if start<=r['bracket_s'][0]<end]
    if not selected:raise ValueError('No accepted labels in scoring window')
    base=labels[0]['clock_mapping']['json_bracket_fixed_clock_ms'][0]-labels[0]['bracket_s'][0]*1000
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    protocol=dict(warmup_pts_s=[start-warmup,start],scored_pts_s=[start,end],
                  estimator=factory.__name__,
                  model_sha256=hashlib.sha256(mp.read_bytes()).hexdigest(),
                  candidate_model_sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),
                  truth_sha256=hashlib.sha256(tp.read_bytes()).hexdigest(),
                  inference_inputs='offline model and chronological current/past vehicle packets only',
                  code_sha256={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in [
                      'app/core/intersection_online.py','app/core/intersection_signal_filter.py',
                      'app/experimental/intersection_timing_ensemble.py','app/experimental/intersection_leading_brake.py',
                      'app/experimental/intersection_adaptive_timing.py']})
    (out/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf8',newline='\n')
    engines=dict(baseline=CausalIntersection(model),candidate=factory(candidate))
    previous={};onsets={name:[] for name in engines};brakes=0;counts={name:0 for name in engines}
    with pp.open(encoding='utf8') as source,(out/'issued.jsonl').open('x',encoding='utf8',newline='\n') as saved:
        for line in source:
            packet=json.loads(line);pts=(packet['timestamp_ms']-base)/1000
            if pts<start-warmup:continue
            if pts>=end:break
            row=dict(timestamp_ms=packet['timestamp_ms'],video_pts_conditional_s=pts)
            for name,engine in engines.items():
                r=engine.ingest(packet);color=r['heads'].get('N',{}).get('main',{}).get('state','UNKNOWN')
                if pts>=start:
                    counts[name]+=1
                    if color!=previous.get(name):onsets[name].append(dict(timestamp_ms=packet['timestamp_ms'],color=color))
                previous[name]=color;row[name]=dict(color=color,phase=r['phase_name'])
                if name=='candidate':
                    brakes+=len(r['leading_brake_observations'])
                    row[name]['intergreen_hypotheses']=r['intergreen_hypotheses']
            saved.write(json.dumps(row,separators=(',',':'))+'\n')
    metrics={}
    for name,transitions in onsets.items():
        values=[]
        for label in selected:
            a,b=label['clock_mapping']['conditional_envelope_ms']
            candidates=[r for r in transitions if r['color']==label['color']]
            nearest=min(candidates,key=lambda r:abs(r['timestamp_ms']-(a+b)/2)) if candidates else None
            values.append(dict(color=label['color'],video_bracket_s=label['bracket_s'],nearest=nearest,
                               distance_to_conditional_clock_envelope_s=(max(a-nearest['timestamp_ms'],nearest['timestamp_ms']-b,0)/1000
                                                                         if nearest else None)))
        metrics[name]=values
    if not counts['baseline']:raise ValueError('No packets in scoring interval')
    result=dict(estimator=factory.__name__,metrics=metrics,onsets=onsets,scored_seconds=counts,leading_brake_observations=brakes,
                scope='Known development window, conditional vehicle-based clock; not full-head color accuracy',
                production_enabled=False)
    (out/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8',newline='\n')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('model','candidate-model','packets','truth','output'):p.add_argument('--'+name,required=True,type=Path)
    p.add_argument('--start',type=float,default=5400);p.add_argument('--end',type=float,default=5520)
    p.add_argument('--estimator',choices=['leading_brake','adaptive'],default='adaptive')
    p.add_argument('--warmup',type=float,default=200);a=p.parse_args()
    compare(a.model,a.candidate_model,a.packets,a.truth,a.output,start=a.start,end=a.end,warmup=a.warmup,estimator=a.estimator)
