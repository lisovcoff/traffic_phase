"""Export an existing V9 prediction for product consumers, without model fitting."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.product_result import build_product_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prediction', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--time-s', type=float, action='append', default=[])
    parser.add_argument('--history', choices=['accepted', 'experimental'], default='accepted')
    args = parser.parse_args()
    if args.prediction.resolve() == args.output.resolve():
        raise ValueError('OUTPUT_CANNOT_OVERWRITE_PREDICTION')
    if args.prediction.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('PREDICTION_EXPORT_BYTE_BUDGET_EXCEEDED')
    raw = args.prediction.read_bytes()
    result = build_product_result(json.loads(raw), timestamps_s=args.time_s, history_source=args.history)
    result['source_prediction_sha256'] = hashlib.sha256(raw).hexdigest()
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'phase_count': result['phase_count'], 'observed_origins': result['observed_origin_count'],
                      'physical_section': 'UNKNOWN', 'inference_performed': False}))


if __name__ == '__main__':
    main()
