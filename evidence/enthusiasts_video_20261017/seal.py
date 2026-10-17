"""Seal evidence; ZIP includes endpoints, not whole video/large predictions."""
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
BASE='8c49850d1c73a311b7d19ad56b95ffd150216d65'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    for p in OUT.glob('*.log'):
        b=p.read_bytes()
        text=b.decode('utf-16') if b.startswith((b'\xff\xfe',b'\xfe\xff')) else b.decode('utf-8-sig')
        p.write_text(text.replace('\r\n','\n'),encoding='utf-8',newline='\n')
    args=['.',':!evidence',':!benchmarks']
    (OUT/'change.patch').write_bytes(subprocess.check_output(['git','diff',BASE,'--binary','--',*args],cwd=ROOT))
    changed=subprocess.check_output(['git','diff',BASE,'--name-only','--',*args],cwd=ROOT,text=True).splitlines()
    files=[p for p in sorted(OUT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts
           and p.name not in ('manifest.json','evidence.zip')]
    manifest=dict(base_sha=BASE,tests_unique_pass=64,new_fitting_runs=0,
        json_video_evaluation='UNAVAILABLE_UNVERIFIED_CLOCK_LINK',
        physical_switch_accuracy_ms=None,video_fingerprint_scope='three1MiBchunks_NOT_full_video_SHA',
        zip_scope='endpoint_mixed_clock_subset; full PNG corpus available in repository',
        source_sha256_lf={n:hashlib.sha256((ROOT/n).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for n in changed},
        artifacts_sha256_raw={p.relative_to(ROOT).as_posix():sha(p) for p in files})
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8',newline='\n')
    review=json.loads((OUT/'video_appearance_reference.json').read_text())
    selected={OUT/'manifest.json'}
    selected.update(p for p in files if p.suffix in ('.json','.csv','.md','.py','.patch','.log'))
    for r in review['transitions']:
        selected.update(OUT/r[k] for k in ('before_file','after_file'))
        selected.update(OUT/n for n in r['mixed_intermediate_frames'])
    selected.update(OUT/(n+'_clock.png') for n in ('start','middle','end'))
    selected.add(OUT/'start_context.jpg')
    with zipfile.ZipFile(OUT/'evidence.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(selected):z.write(p,p.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(OUT/'evidence.zip') as z:
        assert z.testzip() is None
        for p in selected:assert hashlib.sha256(z.read(p.relative_to(ROOT).as_posix())).hexdigest()==sha(p)
    print(json.dumps(dict(artifacts=len(files),zip_files=len(selected),zip_bytes=(OUT/'evidence.zip').stat().st_size,
                         zip_sha256=sha(OUT/'evidence.zip'))))


if __name__=='__main__':main()
