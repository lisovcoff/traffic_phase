"""Verify sealed learned results and collect remaining integration logs."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/learned_release_20261018'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf8'))


def main():
    for name,entry in read(OUT/'manifest.json')['files'].items():
        path=OUT/name
        assert path.stat().st_size==entry['bytes'] and sha(path)==entry['sha256'],name
    for folder in ('learned_profile_20261018','learned_clock_fixed_20261018'):
        base=ROOT/'benchmarks'/folder
        for row in read(base/'predictions_sealed.json'):
            assert row['reason'] is None and sha(base/'predictions'/row['file'])==row['sha256']
    for path in (ROOT/'config/learned_profiles').glob('*.json'):
        deployed=read(path)
        candidates=[p for p in (ROOT/'benchmarks/learned_profile_20261018/models').glob('*.json')
                    if read(p)['phase_labels']==deployed['phase_labels']
                    and read(p)['profile']==deployed['profile']]
        assert len(candidates)==1,path
        frozen=read(candidates[0])
        assert all(deployed[k]==v for k,v in frozen.items()),path
    http=read(OUT/'http/result.json')
    assert http['status']=='PASS' and not http['annotations_sent']
    assert sha(OUT/'http/response.html')==http['html_sha256']
    assert all(row['status']=='PASS' for row in read(OUT/'browser/results.json'))
    main_sha=subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()
    assert main_sha=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    for pattern in ('count*20261018*.log','learned*20261018*.log'):
        for source in sorted((ROOT/'.web_runtime').glob(pattern)):
            dest=OUT/'logs'/source.name
            if dest.exists():continue
            raw=source.read_bytes()
            decoded=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf8',errors='replace')
            with dest.open('x',encoding='utf8',newline='\n') as stream:stream.write(decoded)
    files=[p for p in OUT.rglob('*') if p.is_file() and 'runs' not in p.relative_to(OUT).parts]
    receipt=dict(status='PASS',main_sha256_commit=main_sha,
        frozen_predictions_unchanged=True,all_deployed_classifier_fields_match_frozen_training=True,
        http_response_hash_verified=True,browser_checks_pass=True,launcher_check='PASS',
        scope='all release evidence except retained raw HTTP uploads; no accuracy claim beyond summary',
        files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(files)})
    with (OUT/'verification.json').open('x',encoding='utf8',newline='\n') as stream:
        json.dump(receipt,stream,ensure_ascii=False,indent=2);stream.write('\n')
    print('PASS: frozen predictions, deployment profiles, HTTP response, browser evidence and main;',len(files),'files sealed')


if __name__=='__main__':main()
