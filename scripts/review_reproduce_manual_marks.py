"""Portable review-package verification and scoring; no inference by default."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def verify():
    manifest=read(ROOT/'REVIEW_MANIFEST.json')
    for name,expected in manifest['files'].items():
        path=ROOT/name
        data=path.read_bytes()
        if len(data)!=expected['bytes'] or hashlib.sha256(data).hexdigest()!=expected['sha256']:
            raise ValueError(f'review file mismatch: {name}')
    print(f"Manifest PASS: {len(manifest['files'])} files; source {manifest['source_commit']}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only',action='store_true')
    parser.add_argument('--check-caches',action='store_true',help='validate lossless event caches, without fitting')
    args=parser.parse_args()
    verify()
    if args.verify_only:
        return
    from app.core.offline_benchmark import evaluate_prediction,validate_annotation
    from app.core.manual_delay_evaluation import evaluate_reaction_bound
    from scripts.manual_marks_validation_report import resolved_prediction
    report=read(ROOT/'evidence/manual_marks_20261018/comparison.json')
    for source in read(ROOT/'data/review_sources.json')['rows']:
        name=source['source_name']
        annotation=read(ROOT/source['annotation'])
        path=ROOT/source['prediction']
        prediction=read(path)
        if args.check_caches:
            from scripts.hsmm_recurrence_check import cached_bundle
            cached_bundle(path)
        expected=next(row for row in report['rows'] if row['source']==name)['variants']
        for variant,profile in [('baseline_latent',None),('baseline_none','none')]:
            value=prediction if profile is None else resolved_prediction(prediction,profile)[0]
            metrics=evaluate_prediction(value,validate_annotation(annotation))
            metrics['operator_delay_compatibility']={field:evaluate_reaction_bound(value,annotation,field=field)
                for field in ('raw_hsmm_segments','baseline_segments')}
            # JSON object keys (e.g. anonymous phase IDs) are strings on disk.
            # Canonicalize keys only; do not round numbers or relax comparisons.
            serialized=json.loads(json.dumps(metrics,allow_nan=False))
            assert serialized==expected[variant]['metrics'],f'changed score: {name}/{variant}'
            score=metrics['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            reaction=metrics['operator_delay_compatibility']['raw_hsmm_segments']
            print(name,variant,f"strict={score['matched_boundaries']}/{score['truth_boundaries']}",
                f"predicted={score['predicted_boundaries']}",
                f"reaction={reaction['compatible_boundaries']}/{reaction['truth_boundaries']}")
    print('Saved scores reproduced exactly; no fitting or time shift performed.')


if __name__=='__main__':
    main()
