"""Compare one sealed development run with frozen 2B.1 metrics; no fitting."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(folder,row):
    if row['status']!='ok':
        return {'status':row['status'],'reason':row.get('reason'),'runtime_s':row.get('inference_runtime_s'),
                'candidate_count':None,'candidate_reason':'no persisted prediction; worker timeout/failure is unavailable, not optimal search'}
    path=folder/row['prediction_file'];assert sha(path)==row['prediction_sha256_before_evaluation']
    pred=json.loads(path.read_text(encoding='utf-8')); metrics=row['metrics']
    histories={}
    for name,hist in metrics['histories'].items():
        b=hist['boundaries'];matches=len(b['matches'])
        histories[name]={'matched_count':matches,'truth_count':matches+len(b['missed_truth_ms']),
            'predicted_count':matches+len(b['extra_predicted_ms']),
            **{key:b[key] for key in ('precision','recall','mae_s','p95_s','nearest_truth_boundary_mae_s_diagnostic')},
            'coverage':hist['coverage']}
    selection=pred['phase_model_selection']
    return {'status':'ok','K':pred['schedule']['phase_count'],'raw_selected_K':selection['raw_selected_phase_count'],
        'period_s':pred['schedule']['period_s'],'period_error_s':metrics['period_absolute_error_s'],
        'runtime_s':row['inference_runtime_s'],'candidate_count':len(selection['candidates']),
        'candidates':selection['candidates'],'search':selection.get('search'),
        'phase_redundancy':pred.get('phase_evidence',{}).get('phase_redundancy'),
        'histories':histories,'prediction_sha256':sha(path)}


def main():
    before_path=ROOT/'benchmarks/stage2b1_20261013/baseline_metrics.json'
    after_path=ROOT/'benchmarks/stage2c_20261014/baseline_metrics.json'
    before=json.loads(before_path.read_text(encoding='utf-8'));after=json.loads(after_path.read_text(encoding='utf-8'))
    assert before['config']==after['config']
    rows=[];old={r['source_name']:r for r in before['rows']}
    for new in after['rows']:
        previous=old[new['source_name']]
        for field in ('source_sha256','annotation_sha256'):
            assert previous.get(field)==new.get(field)
        rows.append({'source':new['source_name'],
            'source_sha256':new.get('source_sha256'),'annotation_sha256':new.get('annotation_sha256'),
            'before':summary(before_path.parent,previous),'after':summary(after_path.parent,new)})
    result={'before_report_sha256':sha(before_path),'after_report_sha256':sha(after_path),
        'identical_evaluator_config_sha256':after['config_sha256'],
        'interpretation':'one development regression run; not independent lamp accuracy; no post-result tuning',
        'rows':rows}
    path=after_path.parent/'comparison.json'
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(result,f,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
    print('comparison.json saved; input/config hashes match frozen baseline.')


if __name__=='__main__':main()
