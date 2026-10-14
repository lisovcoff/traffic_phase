"""Exactly one sealed synthetic run; unchanged historical evaluator, no real data."""
import hashlib
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from scripts.event_time_prototype import infer, PRIORS
from app.core.offline_benchmark import evaluate_history, validate_annotation

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/stage2d1_event_time_prototype'


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(obj,f,indent=2,allow_nan=False); f.write('\n')


def summary(values):
    return {'n':len(values),'median':float(np.median(values)) if values else None,
            'p95':float(np.percentile(values,95)) if values else None,
            'le_4s':sum(v<=4 for v in values), 'reason':None if values else 'NO_ISSUED_SETS'}


def evaluate_one(case,prior,out,prediction_hash):
    inp=case['inference_input']; truth=case['truth_segments']; events=inp['events']
    segments=out['diagnostic_segments']; horizon=inp['horizon']
    marks=[{'timestamp_ms':a*1000,'kind':str(z),'offset_s':a} for a,b,z in truth]
    marks.append({'timestamp_ms':horizon*1000,'kind':str((truth[-1][2]+1)%len(inp['order'])),'offset_s':horizon})
    annotation=validate_annotation({'start_ms':0,'marks':marks}); assert annotation['valid']
    adapter={'schedule_base_timestamp_ms':0,'schedule':{'diagnostic_candidate':segments},
             'prediction_sha256':prediction_hash,'point_tolerance_s':2}
    name=f"{case['case']}_seed{case['seed']}_{prior}.json"
    path=OUT/'evaluation_adapters'/name; save(path,adapter)
    point=evaluate_history(adapter,annotation,'diagnostic_candidate',2)
    sets={b['ordinal']:b for b in out['boundary_sets']}
    contain=[{'ordinal':i,'truth_s':seg[0], 'issued':i in sets,
              'contained':seg[0] in sets[i]['times_s'] if i in sets else None,
              'optional':not sets[i]['exists_in_all_paths'] if i in sets else None}
             for i,seg in enumerate(truth[1:],1)]
    graph={tuple(e) for e in out.get('feasible_graph',[])}
    truth_path=bool(graph) and all((a,i,b,i==len(truth)-1) in graph for i,(a,b,z) in enumerate(truth))
    violations=[i for i,e in enumerate(events) if not any(a<=e['timestamp_ms']/1000<b and z==inp['mapping'][e['movement']] for a,b,z in segments)] if out['complete'] else None
    widths=[b['hull_s'][1]-b['hull_s'][0] for b in sets.values()]
    mandatory=[b['hull_s'][1]-b['hull_s'][0] for b in sets.values() if b['exists_in_all_paths']]
    core=case['case'].startswith(('stable','hold','shorten'))
    recall=point['boundaries']['recall']['value']
    return {'case':case['case'],'seed':case['seed'],'prior':prior,'range_s':[0,horizon],
            'correctly_specified':case['correctly_specified'],'misspecification':case['misspecification'],
            'status':out['status'],'unavailable_reason':out.get('reason'),
            'point':point, 'point_core_gate':('PASS' if recall is not None and recall>=.8 else 'FAIL') if core else 'NOT_CORE',
            'interval_truth_checks':contain,'truth_path_feasible':truth_path,
            'feasible_gate':('PASS' if truth_path else 'FAIL') if out['complete'] and case['correctly_specified'] else 'UNASSESSED_OR_MISSPECIFIED',
            'issued_ordinal_sets':len(sets),'optional_ordinal_sets':sum(not b['exists_in_all_paths'] for b in sets.values()),
            'truth_boundaries_unissued':sum(not c['issued'] for c in contain),
            'widths_all_issued_hulls_s':summary(widths),'widths_mandatory_hulls_s':summary(mandatory),
            'transition_counts':out.get('possible_transition_counts',[]),
            'transition_count_ambiguous':len(out.get('possible_transition_counts',[]))>1,
            'event_constraint_violations':len(violations) if violations is not None else None,
            'violating_event_indices':violations,'events':len(events),
            'unknown_fraction':out['unknown_fraction'],'input_coverage_fraction':sum(b-a for a,b in inp['windows'])/horizon,
            'cpu_s':out['cpu_s'],'prediction_sha256':prediction_hash,'adapter_sha256':sha(path)}


def run():
    manifest=json.loads((OUT/'manifest.json').read_text())
    assert manifest['priors']==PRIORS
    # inputs.json has no truth timestamps/segments: prepared before this run.
    inputs=json.loads((OUT/'inputs.json').read_text())
    save(OUT/'started.json',{'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
         'manifest_sha256':sha(OUT/'manifest.json'),'inputs_sha256':sha(OUT/'inputs.json'),
         'suite_sha256':sha(OUT/'suite.json'),'evaluator_sha256':sha(ROOT/'app/core/offline_benchmark.py'),
         'max_runs':1,'source_hashes':{p:sha(ROOT/p) for p in ['scripts/event_time_prototype.py','scripts/run_event_time_prototype.py','scripts/event_time_suite.py']}})
    started=time.process_time(); ledger=[]; calls=0
    for case in inputs:
        for prior in PRIORS:
            remaining=manifest['suite_cpu_seconds']-(time.process_time()-started)
            limits=dict(manifest['limits']); limits['max_seconds']=min(limits['max_seconds'],max(0,remaining))
            if calls>=manifest['max_inference_calls']: raise RuntimeError('call budget violated')
            output=infer(**case['inference_input'],prior=PRIORS[prior],**limits); calls+=1
            path=OUT/'predictions'/f"{case['case']}_seed{case['seed']}_{prior}.json"
            save(path,output)
            ledger.append({'case':case['case'],'seed':case['seed'],'prior':prior,'path':str(path.relative_to(ROOT)),'sha256':sha(path)})
    save(OUT/'outputs_sealed.json',{'predictions':ledger,'inference_calls':calls,'cpu_s':time.process_time()-started,
         'inputs_after_sha256':sha(OUT/'inputs.json'),'evaluation_not_started':True})
    # First truth use in this runner: all inference outputs already sealed.
    suite=json.loads((OUT/'suite.json').read_text()); index={(c['case'],c['seed']):c for c in suite}
    rows=[]; outputs={}
    for item in ledger:
        path=ROOT/item['path']; assert sha(path)==item['sha256']
        out=json.loads(path.read_text()); key=(item['case'],item['seed'])
        rows.append(evaluate_one(index[key],item['prior'],out,item['sha256']))
        outputs[(*key,item['prior'])]=out
    sensitivity=[]
    for case in inputs:
        key=(case['case'],case['seed'])
        a,b=[outputs[(*key,p)] for p in PRIORS]
        same_count=len(a['diagnostic_segments'])==len(b['diagnostic_segments'])
        shifts=[y[0]-x[0] for x,y in zip(a['diagnostic_segments'][1:],b['diagnostic_segments'][1:])] if same_count and a['complete'] and b['complete'] else None
        sensitivity.append({'case':key[0],'seed':key[1], 'same_feasible_sets':a['boundary_sets']==b['boundary_sets'],
                            'same_diagnostic_path':a['diagnostic_segments']==b['diagnostic_segments'],
                            'ordinal_point_shifts_s':shifts,
                            'reason':None if shifts is not None else 'UNAVAILABLE_OR_DIFFERENT_TRANSITION_COUNTS'})
    save(OUT/'comparison.json',{'rows':rows,'prior_dependence':sensitivity,
         'historical_gate':'FAIL_UNCHANGED','real_runs':0,'production_acceptance':False,
         'interpretation':'finite-grid feasible sets under hard assumptions; points diagnostic; not posterior/lamp accuracy'})
    for prior in PRIORS:
        chosen=[r for r in rows if r['prior']==prior]
        b=[r['point']['boundaries']['mae_s'] for r in chosen]
        print(prior,'complete',sum(r['status']=='complete_grid_search' for r in chosen),'/',len(chosen),
              'point matched/truth/predicted',tuple(sum(v[k] for v in b) for k in ['matched_boundaries','truth_boundaries','predicted_boundaries']),
              'core fail',sum(r['point_core_gate']=='FAIL' for r in chosen),
              'feasible failures',sum(r['feasible_gate']=='FAIL' for r in chosen))


if __name__=='__main__': run()
