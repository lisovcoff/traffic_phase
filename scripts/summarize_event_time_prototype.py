"""Read-only aggregation of sealed run, no inference or evaluator invocation."""
import csv
import json
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/stage2d1_event_time_prototype'


def summary(values):
    return {'n':len(values),'median':float(np.median(values)) if values else None,
            'p95':float(np.percentile(values,95)) if values else None,
            'le_4s':sum(v<=4 for v in values)}


def run():
    comparison=json.loads((OUT/'comparison.json').read_text())
    rows=comparison['rows']; aggregate={}; table=[]
    for prior in ['uniform','nominal10']:
        selected=[r for r in rows if r['prior']==prior]
        result={}
        for population, group in [('all',selected),('correctly_specified',[r for r in selected if r['correctly_specified']]),
                                   ('core',[r for r in selected if r['point_core_gate']!='NOT_CORE']),
                                   ('misspecified',[r for r in selected if not r['correctly_specified']])]:
            bs=[r['point']['boundaries'] for r in group]
            matched=sum(b['mae_s']['matched_boundaries'] for b in bs)
            truth=sum(b['mae_s']['truth_boundaries'] for b in bs)
            predicted=sum(b['mae_s']['predicted_boundaries'] for b in bs)
            errors=[abs(m['signed_error_s']) for b in bs for m in b.get('matches',[])]
            checks=[c for r in group for c in r['interval_truth_checks']]
            widths=[];mandatory=[]
            for r in group:
                name=f"{r['case']}_seed{r['seed']}_{prior}.json"
                out=json.loads((OUT/'predictions'/name).read_text())
                widths.extend(b['hull_s'][1]-b['hull_s'][0] for b in out['boundary_sets'])
                mandatory.extend(b['hull_s'][1]-b['hull_s'][0] for b in out['boundary_sets'] if b['exists_in_all_paths'])
            seconds=sum(r['range_s'][1] for r in group)
            result[population]={'cases':len(group),'complete_cases':sum(r['status']=='complete_grid_search' for r in group),
                'matched_truth_predicted':[matched,truth,predicted],
                'precision':matched/predicted if predicted else None,'recall':matched/truth if truth else None,
                'matched_MAE_s':float(np.mean(errors)) if errors else None,'matched_p95_s':float(np.percentile(errors,95)) if errors else None,
                'truth_boundary_count':len(checks),'contained':sum(c['contained'] is True for c in checks),
                'excluded':sum(c['contained'] is False for c in checks),'unissued':sum(not c['issued'] for c in checks),
                'all_set_hull_widths_s':summary(widths),'mandatory_set_hull_widths_s':summary(mandatory),
                'optional_sets':sum(r['optional_ordinal_sets'] for r in group),
                'ambiguous_count_cases':sum(r['transition_count_ambiguous'] for r in group),
                'unknown_seconds':sum(r['unknown_fraction']*r['range_s'][1] for r in group),
                'total_seconds':seconds,
                'input_covered_seconds':sum(r['input_coverage_fraction']*r['range_s'][1] for r in group),
                'diagnostic_candidate_covered_seconds':sum(r['point']['coverage'].get('covered_duration_s',0) for r in group),
                'violations':sum(r['event_constraint_violations'] or 0 for r in group),
                'evaluated_events':sum(r['events'] for r in group if r['event_constraint_violations'] is not None),
                'unassessed_events':sum(r['events'] for r in group if r['event_constraint_violations'] is None),
                'core_fail_cases':sum(r['point_core_gate']=='FAIL' for r in group)}
        aggregate[prior]=result
    for r in rows:
        b=r['point']['boundaries']; m=b['mae_s']
        table.append({'case':r['case'],'seed':r['seed'],'prior':r['prior'],'status':r['status'],
                      'unavailable_reason':r['unavailable_reason'],'start_s':r['range_s'][0],'end_s':r['range_s'][1],
                      'matched':m['matched_boundaries'],'truth':m['truth_boundaries'],'predicted':m['predicted_boundaries'],
                      'precision':b['precision']['value'],'recall':b['recall']['value'],
                      'matched_MAE_s':m['value'],'matched_p95_s':b['p95_s']['value'],
                      'candidate_temporal_coverage':r['point']['coverage']['value'],
                      'input_coverage':r['input_coverage_fraction'],'UNKNOWN_fraction':r['unknown_fraction'],
                      'contained_truth':sum(c['contained'] is True for c in r['interval_truth_checks']),
                      'unissued_truth':r['truth_boundaries_unissued'],'issued_sets':r['issued_ordinal_sets'],
                      'optional_sets':r['optional_ordinal_sets'],
                      'median_hull_s':r['widths_all_issued_hulls_s']['median'],'p95_hull_s':r['widths_all_issued_hulls_s']['p95'],
                      'violations':r['event_constraint_violations'],'cpu_s':r['cpu_s']})
    with (OUT/'aggregate.json').open('x',encoding='utf-8') as f:
        json.dump(aggregate,f,indent=2);f.write('\n')
    with (OUT/'compact_comparison.csv').open('x',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    print(json.dumps(aggregate,indent=2))


if __name__=='__main__':run()
