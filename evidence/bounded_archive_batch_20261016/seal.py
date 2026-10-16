"""Seal this small technical evidence only. No user inputs or model execution."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BASE = '519e6ea94610d12f5c814721d993ca02f2015b29'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for log in OUT.glob('*.log'):
        raw = log.read_bytes()
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
        log.write_text(text.replace('\r\n', '\n'), encoding='utf-8')
    for name in ('batch_server.out', 'batch_server.err', 'batch_saved_server.out', 'batch_saved_server.err'):
        source = ROOT/'.web_runtime'/name
        if source.is_file():
            (OUT/name).write_bytes(source.read_bytes())
    patch = subprocess.check_output(['git', 'diff', BASE, '--binary', '--', '.', ':!evidence'], cwd=ROOT)
    (OUT/'change.patch').write_bytes(patch)
    review = dict(initial_automated='PASS_INSUFFICIENT_CHECK',
                  initial_visual='FAIL_NESTED_REPORT_HEIGHT',
                  initial_full_query='FAIL_QUERY_METADATA',
                  final_visual='PASS_DESKTOP_AND_MOBILE_MANUALLY_REVIEWED',
                  final_full_query='PASS_15_OF_15_EXACT',
                  saved_ui_replays=2, extra_phase_fits_after_initial_batch=0,
                  production_inference_modified=False, real_replays=0)
    (OUT/'visual_review.json').write_text(json.dumps(review, indent=2)+'\n', encoding='utf-8')
    code = subprocess.check_output(['git', 'diff', BASE, '--name-only', '--', '.', ':!evidence'], cwd=ROOT, text=True).splitlines()
    manifest = dict(base_sha='519e6ea94610d12f5c814721d993ca02f2015b29',
        branch='feat/bounded-archive-batch-20261016', python=sys.version,
        packages={name: importlib.metadata.version(name) for name in ('fastapi', 'starlette', 'numpy', 'scipy', 'scikit-learn')},
        code_sha256_lf={name: hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n', b'\n')).hexdigest() for name in code},
        results='317 targeted tests; technical batch only; no new real accuracy estimate',
        outputs_sha256_raw={p.name: digest(p) for p in sorted(OUT.iterdir())
                            if p.is_file() and p.name not in ('manifest.json', 'evidence.zip')})
    (OUT/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    files = [p for p in sorted(OUT.iterdir()) if p.is_file() and p.name != 'evidence.zip']
    with zipfile.ZipFile(OUT/'evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.name)
    with zipfile.ZipFile(OUT/'evidence.zip') as archive:
        assert archive.testzip() is None
        for path in files:
            assert hashlib.sha256(archive.read(path.name)).hexdigest() == digest(path)
    print(json.dumps(dict(package=str(OUT/'evidence.zip'), bytes=(OUT/'evidence.zip').stat().st_size,
                          sha256=digest(OUT/'evidence.zip'), zip_crc_and_all_member_hashes='PASS')))


if __name__ == '__main__':
    main()
