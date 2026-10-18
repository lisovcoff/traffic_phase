"""Verify saved delivery checks without replaying phase inference or needing Git."""
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]


def main():
    verification = json.loads((OUT/'verification.json').read_text(encoding='utf-8'))
    for name, digest in verification['files'].items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest() == digest, name
    for version in ('existing_python314', 'clean_python312'):
        result = verification['tests'][version]
        assert result['passed'] == (1325 if version == 'clean_python312' else 1323)
        assert f"{result['passed']} passed" in (OUT/result['log']).read_text(encoding='utf-8')
    snapshots = json.loads((OUT/'historical_sources.json').read_text(encoding='utf-8'))
    for name, info in snapshots['files'].items():
        raw = (ROOT/info['snapshot']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == info['canonical_lf_sha256'], name
        assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == info['git_blob_sha1'], name
    accuracy = json.loads((OUT/'accuracy_summary.json').read_text(encoding='utf-8'))
    assert hashlib.sha256((ROOT/accuracy['source']).read_bytes()).hexdigest() == accuracy['source_sha256']
    assert (accuracy['matched'], accuracy['truth'], accuracy['predictions']) == (19, 34, 41)
    assert verification['accuracy_acceptance'] == 'NOT_READY'
    print(json.dumps({'status': 'PASS', 'evidence_files': len(verification['files']),
        'accuracy_acceptance': verification['accuracy_acceptance']}))


if __name__ == '__main__':
    main()
