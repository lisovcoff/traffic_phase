"""Package reviewed sources and native results; no inference/evaluator execution."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'benchmarks/seed_flow_20261017'
BASE='b7675c70bf191a20454fe974baa18cc161f01856'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    # Never normalize external originals; their byte hashes are part of intake.
    for path in [*OUT.glob('local_*.log'),*OUT.glob('native_*.log'),OUT/'native_verification.json']:
        raw=path.read_bytes()
        text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
        path.write_text(text.replace('\r\n','\n'),encoding='utf-8')
    original_manifest=json.loads((OUT/'astra_original/evidence/independent_review_20261017/manifest.json').read_text(encoding='utf-8'))
    for name,digest in original_manifest['files'].items():
        assert sha(OUT/'astra_original'/name)==digest,name
    source=json.loads((OUT/'source_manifest.json').read_text(encoding='utf-8'))['received_files_sha256']
    assert sha(OUT/'astra_review_original.zip')==source['astra_zip']
    assert sha(OUT/'gemini_original.md')==source['gemini']
    assert sha(OUT/'seed_flow.patch')==source['astra_patch']
    args=['.',':!evidence',':!benchmarks']
    (OUT/'native_change.patch').write_bytes(subprocess.check_output(['git','diff',BASE,'--binary','--',*args],cwd=ROOT))
    changed=subprocess.check_output(['git','diff',BASE,'--name-only','--',*args],cwd=ROOT,text=True).splitlines()
    files=[p for folder in (OUT,RUN) for p in sorted(folder.rglob('*')) if p.is_file()
           and '__pycache__' not in p.parts and p not in (OUT/'manifest.json',OUT/'evidence.zip')]
    manifest=dict(base_sha=BASE,native_code_before_replay='35fc8fe899193bea4440b3e910e4f49782563836',
        native_tests={'passed':208,'strict_xfail_cases':8,'open_defects':7},
        structural_gate='PASS',development_benefit='FAIL_NO_GAIN',local_2D1='FAIL_DEFAULT_OFF',
        code_sha256_lf={n:hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in changed},
        artifacts_sha256_raw={p.relative_to(ROOT).as_posix():sha(p) for p in files},
        external_originals_verified=True,no_post_result_tuning=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    files.append(OUT/'manifest.json')
    with zipfile.ZipFile(OUT/'evidence.zip','w',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:archive.write(path,path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUT/'evidence.zip') as archive:
        assert archive.testzip() is None
        for path in files:
            assert hashlib.sha256(archive.read(path.relative_to(ROOT).as_posix())).hexdigest()==sha(path)
    print(json.dumps(dict(zip_bytes=(OUT/'evidence.zip').stat().st_size,zip_sha256=sha(OUT/'evidence.zip'),
                          member_hashes_and_CRC='PASS',external_sources_unchanged=True)))


if __name__=='__main__':main()
