"""Post-evaluation summaries of sealed synthetic outputs, no inference calls."""
import argparse
import csv
import json
from pathlib import Path

from app.core.offline_benchmark import percentile
from scripts.offline_benchmark import sha256_file, write_json


def summarize(out):
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    seal=json.loads((out/'outputs_sealed.json').read_text(encoding='utf-8'))
    comparison=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
    assert sha256_file(out/'inputs.json')==manifest['inputs_sha256']
    assert sha256_file(out/'suite.json')==manifest['suite_sha256']
    suite=json.loads((out/'suite.json').read_text(encoding='utf-8'))
    truth={(c['case'],c['seed']):[s[0] for s in c['truth_segments'][1:]] for c in suite}
    outputs={}
    for entry in seal['predictions']:
        path=out/entry['path'];assert sha256_file(path)==entry['sha256']
        outputs[(entry['case'],entry['seed'])]=json.loads(path.read_text(encoding='utf-8'))
    records=[]
    for r in comparison['rows']:
        output=outputs[(r['case'],r['seed'])]
        model=output.get('results',{}).get(r['prior'],{})
        b=r['point']['boundaries']['recall']
        records.append({'case':r['case'],'seed':r['seed'],'prior':r['prior'],
            'status':r['status'],'core_gate':r['core_point_gate'],
            'matched':b['matched_boundaries'],'truth':b['truth_boundaries'],'predicted':b['predicted_boundaries'],
            'precision':r['point']['boundaries']['precision']['value'],'recall':b['value'],
            'matched_mae_s':r['point']['boundaries']['mae_s']['value'],
            'matched_p95_s':r['point']['boundaries']['p95_s']['value'],
            'nearest_mae_s':r['point']['boundaries']['nearest_truth_boundary_mae_s_diagnostic']['value'],
            'diagnostic_temporal_coverage':r['point']['coverage']['value'],
            'published_logical_unknown_fraction':1,'physical_unknown_fraction':1,
            'interval_contained':r['interval_containment']['contained'],'interval_issued':r['interval_containment']['issued'],
            'interval_median_width_s':r['interval_width_s']['median'],'interval_p95_width_s':r['interval_width_s']['p95'],
            'interval_width_le4_count':r['interval_width_s']['le_4s'],
            'prior_only':r['prior_only_numerically'],
            'truth_boundaries_s':str(truth[(r['case'],r['seed'])]),
            'diagnostic_boundaries_s':str([s[0] for s in model.get('diagnostic_segments',[])[1:]])})
    with (out/'compact_comparison.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    aggregates={}
    for prior in ('flat','soft'):
        aggregates[prior]={}
        for group,predicate in {
            'core_stable_hold_shortening':lambda r:r['core_point_gate']!='NOT_CORE',
            'uninformative':lambda r:r['prior_only_numerically'],
            'misspecified':lambda r:not r['correctly_specified'],
            'correctly_specified_informative':lambda r:r['correctly_specified'] and not r['prior_only_numerically'],
        }.items():
            chosen=[r for r in comparison['rows'] if r['prior']==prior and predicate(r)]
            counts=[r['point']['boundaries']['recall'] for r in chosen]
            widths=[c['width_s'] for r in chosen for c in r['interval_checks'] if c['issued']]
            errors=[abs(m['signed_error_s']) for r in chosen for m in r['point']['boundaries']['matches']]
            m,t,p=[sum(c[k] for c in counts) for k in ('matched_boundaries','truth_boundaries','predicted_boundaries')]
            aggregates[prior][group]={'cases':len(chosen),'matched':m,'truth':t,'predicted':p,
                'precision':m/p if p else None,'recall':m/t if t else None,
                'matched_mae_s':sum(errors)/len(errors) if errors else None,
                'matched_p95_s':percentile(errors,.95) if errors else None,
                'interval_contained':sum(r['interval_containment']['contained'] for r in chosen),
                'interval_issued':len(widths),'median_width_s':percentile(widths,.5) if widths else None,
                'p95_width_s':percentile(widths,.95) if widths else None,
                'width_le4_count':sum(w<=4 for w in widths)}
    write_json(out/'aggregate.json',{'comparison_sha256':sha256_file(out/'comparison.json'),
        'groups':aggregates,'point_paths_differ_between_priors':sum(d['same_point_path'] is False for d in comparison['prior_dependence']),
        'total_paired_prior_cases':len(comparison['prior_dependence']),
        'suite_cpu_s':seal['cpu_s'],'calls':seal['calls'],'new_inference_calls':0,
        'max_declared_array_allowance_bytes':max(o.get('declared_memory_allowance_used_bytes',0) for o in outputs.values()),
        'limits':'fixed known initial anchor and transition count; rates/demand/delays supplied; synthetic only'})
    print(json.dumps(aggregates,indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True,type=Path)
    summarize(p.parse_args().out)
