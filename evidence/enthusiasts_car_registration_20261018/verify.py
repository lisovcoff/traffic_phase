"""Verify preserved rejection evidence and guards; no fit, decode, or replay."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from app.experimental.vehicle_clock_alignment import inspect_registration_support


def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def lfsha(p):return hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest()


def main(seal=False):
    for name in ('fit_seal.json','corrected_seal.json','static_geometry_seal.json'):
        for target,digest in read(OUT/name).items():assert sha(OUT/target)==digest
    # Preserve every artifact from the prior source-identity checkpoint.
    prior=ROOT/'evidence/enthusiasts_vehicle_link_20261018'
    for target,digest in read(prior/'manifest.json')['files'].items():assert sha(prior/target)==digest
    raw=ROOT/'.web_runtime/enthusiasts_vehicle_link_20261018/first_entry.json'
    assert sha(raw)=='f71585ad7a887514d6fd254cdf86b3e08be54e915ca032f42ce08123efe501f6'
    records=read(raw)
    frames=[];wall=0
    for name in ('frames.json','fine_frames.json'):
        m=read(OUT/name);wall+=m['decode_wall_s']
        for r in m['frames']:
            assert sha(ROOT/r['file'])==r['sha256']
            assert abs(r['pts_s']-r['pts_ticks']/90000)<1e-12
            assert r['requested_s']<=r['pts_s']<=r['requested_s']+.2
            frames.append(r)
    plan=read(OUT/'plan.json')
    assert len(frames)==18<=plan['max_new_native_frames'] and wall<plan['max_decode_wall_seconds']
    score=read(OUT/'independent_result.json')
    assert not score['all_pass'] and not score['refit'] and score['accepted_clock_transform'] is None
    assert {r['track_id'] for r in score['independent_vehicles']}=={7,19}
    assert all(not r['pass_50px'] for r in score['independent_vehicles'])
    model=read(OUT/'corrected_model.json')
    guard=inspect_registration_support(model,records)
    assert guard['status']=='REJECTED_ROAD_HORIZON_CROSSING'
    cli=read(OUT/'guarded_cli_result.json')
    assert cli['registration_support']==guard
    assert not cli['scoring_performed'] and 'conditional_clock_set' not in cli
    assert cli['accepted_json_video_clock_transform'] is None and not cli['production_usable']
    static=read(OUT/'static_geometry_model.json')
    assert inspect_registration_support(static,records)['status']=='REJECTED_ROAD_HORIZON_CROSSING'
    assert read(OUT/'static_alternatives.json')['total_clock_optimizer_calls']==2
    assert not subprocess.check_output(['git','diff','b9233dc','--name-only','--','app/core','app/main.py','config','benchmarks'],cwd=ROOT).strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    assert '53 passed' in (OUT/'tests.log').read_text(encoding='utf-8-sig')
    for p in OUT.glob('*.py'):compile(p.read_text(encoding='utf-8'),str(p),'exec')
    target=OUT/'manifest.json'
    if seal:
        if target.exists():raise ValueError('fresh manifest required')
        files={p.relative_to(OUT).as_posix():sha(p) for p in sorted(OUT.rglob('*')) if p.is_file() and p.name not in ('manifest.json','verification.log')}
        code={p:lfsha(ROOT/p) for p in ('app/experimental/vehicle_clock_alignment.py','scripts/vehicle_clock_calibration.py','tests/test_registration_support.py')}
        target.write_text(json.dumps(dict(base='b9233dc',files=files,code_sha256_lf=code,native_frames=18,
            decode_wall_s=wall,tests_pass=53,clock_optimizer_calls=2,static_linear_solves=3,
            accepted_clock_transform=None,phase_fitting_runs=0),indent=2)+'\n',encoding='utf-8')
    manifest=read(target)
    for name,digest in manifest['files'].items():assert sha(OUT/name)==digest,name
    for name,digest in manifest['code_sha256_lf'].items():assert lfsha(ROOT/name)==digest,name
    print(json.dumps(dict(evidence_files=len(manifest['files']),native_frames=18,tests_pass=53,
        real_cli_status=cli['status'],accepted_clock_transform=None,phase_fitting_runs=0,
        production_core_main_and_historical_artifacts_unchanged=True)))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seal',action='store_true');main(p.parse_args().seal)
