"""Seal the delivered code/evidence and retained local reproduction artifacts."""
import hashlib
import gzip
import json
from pathlib import Path
import subprocess

from scripts.corpus_validation import ROOT,save
OUT=ROOT/'evidence/accuracy_recovery_20261019'
RUNTIME=ROOT/'.web_runtime/accuracy_recovery_20261019'


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def digest(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024*1024),b''):value.update(block)
    return value.hexdigest()


def entry(path):
    return dict(path=path.relative_to(ROOT).as_posix(),bytes=path.stat().st_size,sha256=digest(path))


def main():
    summary=read(OUT/'release_summary.json')
    parities=[read(path) for path in (OUT/'production_parity').glob('*.json')]
    assert len(parities)==315 and all(r['status']=='PASS' for r in parities)
    audits=[read(path) for path in (OUT/'zero_speed_audit_v3').glob('*.json')]
    assert len(audits)==219
    assert sum(r['exact_zero_speed_present'] for r in audits)==1
    originals=ROOT/'evidence/all_archives_synthetic_20261019'
    for audit in audits:
        old=read(originals/'ingest'/(audit['job']['id']+'.json'))
        assert (audit['sha256'],audit['bytes_read'])==(old['sha256'],old['bytes_read'])
    tests=read(OUT/'checks/full_pytest_receipt.json')
    assert tests['exit_code']==0 and tests['log_sha256']==digest(OUT/'checks/full_pytest.log')
    for receipt in ['browser_v2/receipt.json','browser_report_v3/receipt.json']:
        for row in read(OUT/receipt)['rows']:
            file=OUT/('report_v2.html' if 'report_v3' in receipt else 'report.html') if row['name']=='report' else OUT/'application_checks'/row['name']/'viewer.html'
            assert row['status']=='PASS' and digest(file)==row['file_sha256']
    for row in read(OUT/'video_holdout/truth_sealed.json')['rows']:
        for side in ('before','after'):
            assert digest(OUT/'video_holdout'/row[side]['file'])==row[side]['sha256']
    assert read(OUT/'checks/batch_cli_parity.json')['status']=='PASS'
    main_head=subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()
    assert main_head=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    source_files=sorted(set([*ROOT.glob('app/**/*.py'),*ROOT.glob('scripts/*.py'),
        *ROOT.glob('tests/**/*.py'),*ROOT.glob('config/*.json'),ROOT/'START_WEB.cmd',
        ROOT/'requirements-tested-py312.txt',ROOT/'README.md',ROOT/'ROADMAP.md',
        ROOT/'docs/PROJECT_STATUS.md',ROOT/'docs/ACCURACY_RECOVERY_RESULTS_20261019.md']))
    index={}
    raw=subprocess.check_output(['git','ls-files','--stage','-z'],cwd=ROOT)
    for record in raw.split(b'\0'):
        if record:
            metadata,name=record.split(b'\t',1);index[name.decode('utf8')]=metadata.decode().split()[1]
    code=[]
    for path in source_files:
        relative=path.relative_to(ROOT).as_posix();data=path.read_bytes();normal=data.replace(b'\r\n',b'\n')
        blob=lambda data:hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
        assert relative in index,relative+' must be staged first'
        assert index[relative] in (blob(data),blob(normal)),relative+' staged content differs'
        code.append(dict(**entry(path),sha256_lf=hashlib.sha256(normal).hexdigest(),staged_blob=index[relative]))
    artifacts=[entry(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='release_manifest.json']
    print('versioned/local evidence hashed',len(artifacts),flush=True)
    local=[entry(p) for p in sorted(RUNTIME.rglob('*')) if p.is_file() and '__pycache__' not in p.parts]
    print('local reproduction files hashed',len(local),flush=True)
    benchmark=[]
    for case in summary['cases']:
        parent=ROOT/Path(case['input_zip']).parent
        receipt=read(OUT/'holdout/results'/(case['id']+'.json')) if case['suite']=='reserved' else read(originals/'synthetic/evaluation_v2'/(case['id']+'.json'))
        row=entry(parent/'input.zip');assert row['sha256']==receipt['input_zip_sha256']
        truth=entry(parent/'truth.json.gz')
        uncompressed=hashlib.sha256()
        with gzip.open(parent/'truth.json.gz','rb') as stream:
            for block in iter(lambda:stream.read(4*1024*1024),b''):uncompressed.update(block)
        truth['uncompressed_sha256']=uncompressed.hexdigest()
        assert truth['uncompressed_sha256']==receipt['truth_sha256']
        benchmark.append(dict(case=case['id'],input_zip=row,truth_evaluation_only=truth))
    manifest=dict(schema='trajectory-recovery-release-manifest-v1',main_unchanged=main_head,
        branch=subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip(),
        commit_before_delivery=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_files=code,evidence_files=artifacts,local_reproduction_files=local,
        benchmark_inputs=benchmark,full_pytest=tests,production_parity='315/315 PASS',
        runtime_input='trajectory JSON only; no label/video or source-specific timing correction',
        limitations=summary['limitations'],final_report='report_v2.html',
        retained_earlier_report='report.html; only incidental failure-count text corrected in v2',
        immutability='This manifest excludes itself. Ignored local files remain on disk and are not distributed as source dependencies.')
    save(OUT/'release_manifest.json',manifest)
    print('Release checks PASS; main unchanged; source blobs match staged code',flush=True)


if __name__=='__main__':main()
