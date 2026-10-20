"""Isolated forecast diagnosis on already revealed cases; production unchanged."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import Counter
import json
import types
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_model,read_json,digest
from scripts.check_incident_counterfactual import OUT,RUNTIME,MODEL,GreenStretch


def candidate_class(variant):
    source=(ROOT/'app/core/intersection_online.py').read_text(encoding='utf8')
    if variant=='revision':
        old="if pending and (pending['token']!=token or a in fresh):"
        new="if pending and (pending['token']!=token or a in fresh or (remaining>3 and head['main']['state']=='GREEN' and any(origin==a for origin,target,weight in events))):"
        assert source.count(old)==1;source=source.replace(old,new)
    elif variant=='posterior_red':
        old="color='YELLOW' if now<pending['deadline_ms'] else 'RED'"
        # Do not overrule a continuing GREEN phase posterior with an expired
        # median-duration forecast. This can improve extensions but must face
        # ordinary end-of-green controls before any production consideration.
        new="color='YELLOW' if now<pending['deadline_ms'] else None"
        assert source.count(old)==1;source=source.replace(old,new)
    elif variant=='flow_guard':
        # Diagnostics only: an exit is delayed evidence, not current permission.
        # Therefore test this explicitly rather than quietly treating it as GT.
        old="fresh={a for a,b,w in events if w>=1}"
        new="fresh={a for a,b,w in events}"
        assert source.count(old)==1;source=source.replace(old,new)
    elif variant=='coupled_flow':
        old="fresh={a for a,b,w in events if w>=1}"
        new="""fresh={a for a,b,w in events if w>=1}
            # Only a mark favoring the current over the following learned phase
            # may revise its end forecast; continuous nondiscriminating flow may not.
            supporting=any(self.marks.likelihoods(origin,target)[regime_index][phase] >
                           2*self.marks.likelihoods(origin,target)[regime_index][nxt]
                           for origin,target,weight in events)
            if supporting:
                fresh.update(a for a,h in best_heads.items() if h.get('main',{}).get('state')=='GREEN')"""
        assert source.count(old)==1;source=source.replace(old,new)
    elif variant!='baseline':raise ValueError(variant)
    # Inject AFTER aggregation: aggregating a second time can reorder otherwise
    # equal-weight observations and change floating-point normalization order.
    old='        if events:\n            self._observe(events);self.evidence_ms=now'
    assert source.count(old)==1
    source=source.replace(old,'        events=list(self.replay_events)\n'+old)
    module=types.ModuleType('isolated_forecast_'+variant);exec(compile(source,'<isolated-forecast>','exec'),module.__dict__)
    return module.CausalIntersection


def trace():
    from app.core.intersection_online import CausalIntersection
    model=read_model(ROOT/'logs/intersection_projects'/MODEL);engine=CausalIntersection(model)
    observed=[];original=engine._observe
    def observe(events):observed.extend(events);original(events)
    engine._observe=observe;engine.projection=None
    with (RUNTIME/'extended.jsonl').open() as src,(RUNTIME/'extended_issuance.jsonl').open() as expected,(RUNTIME/'extended_events.jsonl').open('x') as dst:
        for n,(line,truth) in enumerate(zip(src,expected),1):
            packet=json.loads(line);observed.clear();r=engine.ingest(packet);old=json.loads(truth)
            assert r['heads']==old['heads'] and r['phase_id']==old['phase'] and r['regime_id']==old['regime']
            regime=next(i for i,x in enumerate(model['regimes']) if x['regime_id']==r['regime_id'])
            row=dict(timestamp_ms=packet['timestamp_ms'],sequence=packet['sequence'],events=list(observed),
                heads=r['heads'],phase=r['phase_id'],regime=r['regime_id'],age=r['phase_age_estimate_s'],
                phase_confidence=r['phase_confidence'],remaining=engine.medians[regime][r['phase_id']]-r['phase_age_estimate_s'])
            dst.write(json.dumps(row,separators=(',',':'))+'\n')
            if n%600==0:dst.flush();print('TRACE',n,flush=True)
    save(OUT/'extended_events_receipt.json',dict(packets=n,exact_heads_parity=n,
        trace_sha256=digest(RUNTIME/'extended_events.jsonl'),code_sha256=digest(ROOT/'app/core/intersection_online.py')))


def replay(variant):
    model=read_model(ROOT/'logs/intersection_projects'/MODEL);engine=candidate_class(variant)(model)
    p=read_json(OUT/'protocol.json');warp=GreenStretch(**p['warp']);stats=Counter();transitions=[];previous=None
    rows=read_json(p['truth_path'])['rows'];spans=[]
    for i in range(3):
        for color,nxt in [('GREEN','YELLOW'),('YELLOW','RED')]:
            a=next(r for r in rows if r['color']==color and r['index']==i)
            b=next(r for r in rows if r['color']==nxt and r['index']==i)
            spans.append((warp.timestamp(a['clock_mapping']['json_bracket_fixed_clock_ms'][1]),
                          warp.timestamp(b['clock_mapping']['json_bracket_fixed_clock_ms'][0]),color))
    end_green=min(b for a,b,c in spans if c=='GREEN')
    with (RUNTIME/'extended_events.jsonl').open() as src:
        for n,line in enumerate(src,1):
            row=json.loads(line);engine.replay_events=row['events']
            r=engine.ingest(dict(sequence=row['sequence'],timestamp_ms=row['timestamp_ms'],vehicles=[]))
            if variant=='baseline':assert r['heads']==row['heads']
            now=r['timestamp_ms'];color=r['heads']['N']['main']['state']
            for a,b,c in spans:
                if a<now<b:stats['total']+=1;stats['correct']+=color==c
            if end_green-12000<=now<end_green:stats['added_total']+=1;stats['added_correct']+=color=='GREEN'
            if min(a for a,b,c in spans)<now<max(b for a,b,c in spans) and color!=previous:
                transitions.append(dict(timestamp_ms=now,color=color))
            previous=color
    result=dict(variant=variant,counts=dict(stats),accuracy=stats['correct']/stats['total'],transitions=transitions,
                exact_baseline_parity=n if variant=='baseline' else None,production_enabled=False)
    save(OUT/(variant+'_forecast_diagnostic_v2.json'),result);print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['trace','baseline','revision','posterior_red','flow_guard','coupled_flow']);args=p.parse_args()
    trace() if args.action=='trace' else replay(args.action)
