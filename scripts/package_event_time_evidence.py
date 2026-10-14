"""Package current sealed artifacts and previous reference sources, no inference."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/stage2d1_event_time_prototype'
BASE='161dd0b5642ba312b1e930a4640c153b2bd799e5'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run():
    sources=['scripts/event_time_prototype.py','scripts/event_time_suite.py',
             'scripts/run_event_time_prototype.py','scripts/summarize_event_time_prototype.py',
             'scripts/package_event_time_evidence.py','tests/test_event_time_prototype.py',
             'tests/test_event_time_artifacts.py','scripts/exclusive_mark_reference.py',
             'scripts/evaluate_exclusive_reference.py','tests/test_exclusive_mark_reference.py',
             'docs/EXCLUSIVE_MARK_REFERENCE_2D1.md','docs/EVENT_TIME_PROTOTYPE_2D1.md',
             'docs/PROJECT_STATUS.md','evidence/stage2d1_interval_reference/reference_seal.json',
             'evidence/stage2d1_interval_reference/checksums.json',
             'app/core/offline_benchmark.py']
    protected=['app','evidence/stage2d1_sparse_review','evidence/stage2d1_interval_reference',
               'benchmarks','scripts/exclusive_mark_reference.py','tests/test_exclusive_mark_reference.py']
    unchanged=subprocess.check_output(['git','diff',BASE,'--',*protected],cwd=ROOT)
    assert not unchanged
    versions={'base_sha':BASE,'implementation_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
              'main_sha':subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip(),
              'protected_diff_empty':True,'pre_run_sha':json.loads((OUT/'started.json').read_text())['code_sha'],
              'inference_runs':1,'inference_calls':36,'real_runs':0,
              'reference_source_sha256':{p:sha(ROOT/p) for p in sources if 'reference' in p}}
    with (OUT/'versions.json').open('x',encoding='utf-8') as f:json.dump(versions,f,indent=2)
    diff=subprocess.check_output(['git','diff',BASE,'--','.gitattributes','scripts','tests','docs'],cwd=ROOT)
    (OUT/'implementation.diff').write_bytes(diff)
    paths=[ROOT/p for p in sources]+[p for p in OUT.rglob('*') if p.is_file() and p.name not in {'evidence.zip','zip_sha256.txt','checksums.json'}]
    checksums={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in sorted(set(paths))}
    with (OUT/'checksums.json').open('x',encoding='utf-8') as f:json.dump(checksums,f,indent=2)
    with zipfile.ZipFile(OUT/'evidence.zip','x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(set(paths+[OUT/'checksums.json'])):z.write(p,str(p.relative_to(ROOT)).replace('\\','/'))
    with zipfile.ZipFile(OUT/'evidence.zip') as z:
        assert z.testzip() is None
        for name,h in checksums.items(): assert hashlib.sha256(z.read(name)).hexdigest()==h
    (OUT/'zip_sha256.txt').write_text(sha(OUT/'evidence.zip')+'\n',encoding='utf-8')
    print('Verified ZIP:',(OUT/'evidence.zip').stat().st_size,'bytes;',len(checksums),'hashed members')


if __name__=='__main__':run()
