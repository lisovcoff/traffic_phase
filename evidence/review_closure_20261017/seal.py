"""Seal this completed comparison; never inference, annotation scoring or tuning."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'benchmarks/review_closure_20261017'
BASE='c414c5ef486b145cb7605017fbeabee3e68237b0'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for p in [*OUT.glob('*.log'),OUT/'verification.json']:
        raw=p.read_bytes()
        text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
        p.write_text(text.replace('\r\n','\n'),encoding='utf-8',newline='\n')
    args=['.',':!evidence',':!benchmarks']
    # New files must already be staged, so the patch includes their full text.
    (OUT/'change.patch').write_bytes(subprocess.check_output(['git','diff',BASE,'--binary','--',*args],cwd=ROOT))
    changed=subprocess.check_output(['git','diff',BASE,'--name-only','--',*args],cwd=ROOT,text=True).splitlines()
    files=[p for folder in (OUT,RUN) for p in sorted(folder.rglob('*')) if p.is_file()
           and '__pycache__' not in p.parts and p not in (OUT/'manifest.json',OUT/'evidence.zip')]
    manifest=dict(base_sha=BASE,code_before_replay='9e987c804c1880b991f5298da27f71224778d8c8',
        tests_unique_pass=291,strict_xfails=0,open_independent_defects=0,
        structural_gate='PASS',development_benefit='NOT_MET_MIXED_BASELINE_REGRESSION',local_2D1='FAIL_DEFAULT_OFF',
        source_sha256_lf={n:hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in changed},
        artifacts_sha256_raw={p.relative_to(ROOT).as_posix():sha(p) for p in files},
        no_post_result_tuning=True,physical_lamp_accuracy='UNKNOWN')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    files.append(OUT/'manifest.json')
    with zipfile.ZipFile(OUT/'evidence.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUT/'evidence.zip') as archive:
        assert archive.testzip() is None
        for p in files:
            assert hashlib.sha256(archive.read(p.relative_to(ROOT).as_posix())).hexdigest()==sha(p)
    print(json.dumps(dict(zip_bytes=(OUT/'evidence.zip').stat().st_size,zip_sha256=sha(OUT/'evidence.zip'),
        member_hashes_and_CRC='PASS',artifacts=len(files))))


if __name__=='__main__':
    main()
