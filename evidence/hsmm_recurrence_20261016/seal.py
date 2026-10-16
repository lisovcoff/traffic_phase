"""Small evidence pack; no inference/evaluation, binary hashes never normalized."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUN = ROOT/'benchmarks/hsmm_recurrence_20261016'
BASE = '5b84eab96966f2220d85978056b1568d2f17226a'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for path in [*OUT.glob('*.log'), OUT/'verification.json']:
        raw = path.read_bytes()
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
        path.write_text(text.replace('\r\n', '\n'), encoding='utf-8')
    args = ['.', ':!evidence', ':!benchmarks']
    (OUT/'change.patch').write_bytes(subprocess.check_output(['git', 'diff', BASE, '--binary', '--', *args], cwd=ROOT))
    changed = subprocess.check_output(['git', 'diff', BASE, '--name-only', '--', *args], cwd=ROOT, text=True).splitlines()
    sources = {name: hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in changed}
    artifacts = [p for folder in (OUT, RUN) for p in sorted(folder.rglob('*'))
                 if p.is_file() and '__pycache__' not in p.parts
                 and p.name not in ('evidence.zip', 'manifest.json')]
    manifest = dict(base_sha=BASE, code_before_development_run='98446c4d94a4a38a9a291d7ff53aab6ec569b7cc',
        code_sha256_lf=sources, artifacts_sha256_raw={p.relative_to(ROOT).as_posix(): sha(p) for p in artifacts},
        total_unique_targeted_tests=199, real_accuracy_improvement=False, gate_2D1='FAIL',
        known_development_only=True, raw_trajectory_reads=0, no_post_result_tuning=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    artifacts.append(OUT/'manifest.json')
    with zipfile.ZipFile(OUT/'evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for path in artifacts:
            zipped.write(path, path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUT/'evidence.zip') as zipped:
        assert zipped.testzip() is None
        for path in artifacts:
            assert hashlib.sha256(zipped.read(path.relative_to(ROOT).as_posix())).hexdigest() == sha(path)
    print(json.dumps(dict(zip_bytes=(OUT/'evidence.zip').stat().st_size,
                          zip_sha256=sha(OUT/'evidence.zip'), crc_and_member_hashes='PASS')))


if __name__ == '__main__':
    main()
