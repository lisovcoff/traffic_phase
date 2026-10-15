"""Bounded metadata intake; never reads a trajectory, video or archive."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.experimental.pilot_readiness import assess_pilot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.manifest.stat().st_size > 128 * 1024:
        raise ValueError('MANIFEST_BYTE_BUDGET_EXCEEDED')
    raw = args.manifest.read_bytes()
    manifest = json.loads(raw)
    result = assess_pilot(manifest)
    # Only explicitly listed, small versioned documents; path traversal forbidden.
    seals = {}
    total = 0
    for relative in manifest.get('reference_files', []):
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('REFERENCE_NOT_LOCAL_VERSIONED_DOCUMENT')
        size = path.stat().st_size
        total += size
        if size > 1024 * 1024 or total > 3 * 1024 * 1024:
            raise ValueError('REFERENCE_BYTE_BUDGET_EXCEEDED')
        content = path.read_bytes().replace(b'\r\n', b'\n')
        seals[relative] = hashlib.sha256(content).hexdigest()
    result.update(manifest_sha256=hashlib.sha256(raw).hexdigest(),
                  reference_sha256_lf=seals, reference_bytes_read=total,
                  large_source_files_read=0, base_sha=manifest['base_sha'])
    if args.output.resolve() == args.manifest.resolve():
        raise ValueError('OUTPUT_CANNOT_OVERWRITE_MANIFEST')
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'blocks': result['registered_block_count'],
                      'declared_captures': result['declared_capture_count'],
                      'problems': len(result['problems']), 'reference_bytes_read': total,
                      'inference_performed': False}))


if __name__ == '__main__':
    main()
