"""Evaluate a sealed three-file candidate with unchanged manual-marks scorers."""
import argparse
import hashlib
import json
from pathlib import Path

from app.core.manual_delay_evaluation import evaluate_reaction_bound
from app.core.offline_benchmark import evaluate_prediction,validate_annotation
from scripts.manual_marks_validation_report import resolved_prediction

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(prediction,annotation):
    value=evaluate_prediction(prediction,validate_annotation(annotation))
    value['reaction_0_3s']={f:evaluate_reaction_bound(prediction,annotation,field=f)
        for f in ('raw_hsmm_segments','baseline_segments')}
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    ledger=read(args.run/'predictions_sealed.json')
    assert len(ledger)==3 and all(r['reason'] is None for r in ledger),ledger
    baseline=read(ROOT/'benchmarks/manual_marks_20261018_baseline/baseline_metrics.json')
    rows=[]
    for source in baseline['rows']:
        annotation_path=Path(source['annotation_path'])
        assert sha(annotation_path)==source['annotation_sha256']
        annotation=read(annotation_path)
        filename=Path(source['source_name']).stem+'_v9.json'
        prediction_path=args.run/'predictions'/filename
        assert sha(prediction_path)==next(r['sha256'] for r in ledger if r['file']==filename)
        original_path=ROOT/'benchmarks/manual_marks_20261018_baseline'/source['prediction_file']
        assert sha(original_path)==source['prediction_sha256_before_evaluation']
        row=dict(file=source['source_name'],variants={})
        for variant,path in [('baseline',original_path),('candidate',prediction_path)]:
            prediction=read(path)
            row['variants'][variant+'_latent']=metrics(prediction,annotation)
            for profile in (['none','lenina_sverdlovsky'] if filename.startswith('17_') else ['none']):
                resolved,projection=resolved_prediction(prediction,profile)
                row['variants'][variant+'_'+profile]=dict(projection=projection,
                    metrics=metrics(resolved,annotation) if resolved else None)
            raw=row['variants'][variant+'_latent']
            b=raw['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            delay=raw['reaction_0_3s']['raw_hsmm_segments']
            print(row['file'],variant,'K',raw['phase_count_match']['predicted'],
                'strict',b['matched_boundaries'],'/',b['truth_boundaries'],'pred',b['predicted_boundaries'],
                'MAE',b['value'],'reaction',delay['compatible_boundaries'],flush=True)
        rows.append(row)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf8',newline='\n') as stream:
        json.dump(dict(rows=rows,scoring='unchanged absolute matching; no offset fit',
            phase_inference_used_annotations=False),stream,ensure_ascii=False,indent=2,allow_nan=False)


if __name__=='__main__':
    main()
