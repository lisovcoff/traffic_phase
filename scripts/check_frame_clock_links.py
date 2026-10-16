"""Check a small supplied frame-clock manifest; no media/trajectory read or fit."""
import argparse
import hashlib
import json
from pathlib import Path

from app.experimental.frame_clock_links import inspect_frame_clock_links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise ValueError('FRESH_OUTPUT_REQUIRED')
    if args.input.stat().st_size > 512*1024:
        raise ValueError('FRAME_MANIFEST_BYTE_LIMIT')
    raw = args.input.read_bytes()
    result = inspect_frame_clock_links(json.loads(raw))
    result['input_sha256'] = hashlib.sha256(raw).hexdigest()
    result['input_bytes'] = len(raw)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=result['status'], rows=result['row_count'], out=str(args.out))))


if __name__ == '__main__':
    main()
