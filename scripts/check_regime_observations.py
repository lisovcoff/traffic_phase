"""Reproducible, evaluator-only diagnosis of causal mode likelihoods.

The baseline observation trace is sealed before variants are evaluated. Neither
video times nor expected colors are used by an observation/filter variant.
"""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import time
import types
import numpy as np
import subprocess

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_model,read_json

OUT=ROOT/'evidence/cross_day_model_selection_20261019'
RUNTIME=ROOT/'.web_runtime/cross_day_model_selection_20261019'


def baseline_class():
    protocol=read_json(OUT/'protocol.json')
    assert hashlib.sha256((RUNTIME/'baseline_online.py').read_bytes()).hexdigest()==protocol['baseline_sha256']
    spec=importlib.util.spec_from_file_location('frozen_online',RUNTIME/'baseline_online.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.CausalIntersection


def trace():
    OUT.mkdir(parents=True,exist_ok=True);RUNTIME.mkdir(parents=True,exist_ok=True)
    frozen=RUNTIME/'baseline_online.py'
    source=subprocess.run(['git','show','13364ca:app/core/intersection_online.py'],cwd=ROOT,capture_output=True,check=True).stdout
    with frozen.open('xb') as f:f.write(source)
    manifest=read_json(ROOT/'evidence/cross_day_sverdlovsky_20261019/online_packets_manifest.json')
    job=read_json(ROOT/'evidence/cross_day_sverdlovsky_20261019/online_job.json')
    save(OUT/'protocol.json',dict(baseline_sha256=hashlib.sha256(frozen.read_bytes()).hexdigest(),
        model_id=job['model_id'],packet_sha256=manifest['sha256'],
        scope='development diagnostics; real video windows previously revealed; no universal real-lamp acceptance',
        variants=['baseline','no_duplicate_exit','categorical_marks','categorical_no_duplicate_exit'],
        inference_inputs='offline model and chronological vehicle packets only'))
    engine=baseline_class()(read_model(ROOT/'logs/intersection_projects'/job['model_id']))
    original=engine._observe;observed=[]
    def observe(events):observed.extend(events);original(events)
    engine._observe=observe;began=time.monotonic()
    with Path(manifest['output']).open(encoding='utf8') as packets,(RUNTIME/'baseline_trace.jsonl').open('x',encoding='utf8') as out:
        for count,line in enumerate(packets,1):
            observed.clear();result=engine.ingest(json.loads(line))
            duplicates=[(t['origin'],t['target']) for t in engine.tracks.values() if t['released'] and t['target']]
            row=dict(timestamp_ms=result['timestamp_ms'],sequence=result['sequence'],events=observed,
                previously_released_exits=duplicates,heads={a:h['main']['state'] for a,h in result['heads'].items()},
                regime=result['regime_id'])
            out.write(json.dumps(row,separators=(',',':'))+'\n')
            if count%600==0:out.flush();print('TRACE',count,round(time.monotonic()-began,1),flush=True)
    save(OUT/'trace_complete.json',dict(packets=count,runtime_s=time.monotonic()-began,
        sha256=hashlib.sha256((RUNTIME/'baseline_trace.jsonl').read_bytes()).hexdigest()))


def replay(variant='baseline',limit=None,regime=None):
    """Replay sealed causal observations, without repeating vehicle extraction."""
    from scripts.realistic_traffic_benchmark import match_transitions
    protocol=read_json(OUT/'protocol.json')
    model=read_model(ROOT/'logs/intersection_projects'/protocol['model_id'])
    if regime:model['regimes']=[r for r in model['regimes'] if r['regime_id']==regime]
    text=(RUNTIME/'baseline_online.py').read_text(encoding='utf8')
    text=text.replace('events=[];rendered=[]','events=list(self.replay_events);rendered=[]')
    if 'overdue' in variant:
        text=text.replace('if 0<=remaining<=3:', 'if remaining<=3:')
        text=text.replace("color='YELLOW' if current=='GREEN'", "color=('YELLOW' if remaining>0 else 'RED') if current=='GREEN'")
    module=types.ModuleType('event_replay');exec(compile(text,'<sealed-event-replay>','exec'),module.__dict__)
    engine=module.CausalIntersection(model);original=engine._observe
    vocab=sorted(set(m for r in model['regimes'] for m in r['movement_probabilities']))
    matrices=[]
    for r in model['regimes']:
        matrix=np.array([r['movement_probabilities'].get(m,[.01]*r['phase_count']) for m in vocab])
        if 'balanced' in variant:matrix/=np.maximum(.01,matrix.mean(axis=1))[:,None]
        matrices.append(matrix/np.maximum(1e-12,matrix.sum(axis=0)))
    def observe(events):
        if 'marks' not in variant and 'balanced' not in variant:return original(events)
        for a,b,w in events:
            indices=[j for j,m in enumerate(vocab) if m.replace('_','').split('->')[0]==a and (not b or m.replace('_','').split('->')[1]==b)]
            for i,matrix in enumerate(matrices):
                values=matrix[indices].sum(axis=0)
                engine.banks[i]*=np.maximum(.001,values[:,None])**w
                if 'age' in variant and w>=1:
                    hist=[np.array(hist) for m,hist in model['regimes'][i].get('restart_age_histograms',{}).items()
                          if m.replace('_','').split('->')[0]==a and (b is None or m.replace('_','').split('->')[1]==b)]
                    if hist:
                        histogram=np.mean(hist,axis=0)
                        for phase,median in enumerate(engine.medians[i]):
                            bins=np.minimum(15,(np.arange(engine.age_cap+1)/median*16).astype(int))
                            engine.banks[i][phase]*=.5+.5*histogram[phase,bins]
            total=sum(bank.sum() for bank in engine.banks)
            for bank in engine.banks:bank/=max(total,1e-300)
    engine._observe=observe
    windows=[]
    for file,bounds in [('accuracy_recovery_20261019/video_holdout/truth_sealed.json',[2100,2400]),
                        ('yellow_timing_20261019/sverdlovsky/fresh_truth_sealed.json',[3300,3600])]:
        rows=read_json(ROOT/'evidence'/file)['rows'];base=rows[0]['clock_mapping']['json_bracket_fixed_clock_ms'][0]-rows[0]['bracket_s'][0]*1000
        windows.append(dict(rows=rows,pts=bounds,start=base+bounds[0]*1000,end=base+bounds[1]*1000,onsets={c:[] for c in ('GREEN','YELLOW','RED')}))
    counts=Counter();previous=None;parity=0;began=time.monotonic()
    with (RUNTIME/'baseline_trace.jsonl').open(encoding='utf8') as source:
        for count,line in enumerate(source,1):
            if limit and count>limit:break
            row=json.loads(line);events=row['events']
            if 'release' in variant:events=[e for e in events if e[2]>=1]
            engine.replay_events=events
            r=engine.ingest(dict(timestamp_ms=row['timestamp_ms'],sequence=row['sequence'],vehicles=[]))
            colors={a:h['main']['state'] for a,h in r['heads'].items()}
            if variant=='baseline' and regime is None:
                assert colors==row['heads'] and r['regime_id']==row['regime'],count
                parity+=1
            counts[r['regime_id']]+=1;color=colors['N']
            for win in windows:
                if win['start']<=row['timestamp_ms']<=win['end'] and color!=previous and color in win['onsets']:
                    win['onsets'][color].append(row['timestamp_ms'])
            previous=color
    scores=[]
    for win in windows:
        metrics={}
        for color,pred in win['onsets'].items():
            mids=[sum(row['clock_mapping']['json_bracket_fixed_clock_ms'])/2000 for row in win['rows'] if row['color']==color]
            metrics[color]={str(t):match_transitions([p/1000 for p in pred],mids,t) for t in (2,5,10)}
        scores.append(dict(pts=win['pts'],scores=metrics,onsets=win['onsets']))
    result=dict(variant=variant,regime_subset=regime,regimes=dict(counts),video_metrics=scores,
        baseline_color_parity=parity,runtime_s=time.monotonic()-began)
    path=OUT/(variant+('_'+regime if regime else '')+'.json');save(path,result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['trace','replay'])
    parser.add_argument('--variant',default='baseline');parser.add_argument('--limit',type=int);parser.add_argument('--regime')
    args=parser.parse_args()
    if args.action=='trace':trace()
    else:replay(args.variant,args.limit,args.regime)
