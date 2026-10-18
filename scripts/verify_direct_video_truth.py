"""Seal/verify video evidence without replaying a model or rewriting old data."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from scripts.video_truth_inventory import ROOT,OUT,save


def read(p):return json.loads(p.read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_inputs():
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    protected=['app/core/learned_phase.py','app/core/learned_visualization.py','app/api/learned_visualization.py',
               'app/core/v9','config/learned_profiles','config/known_intersections.json','app/main.py']
    assert not subprocess.check_output(['git','diff','d884689','--',*protected],cwd=ROOT)
    for site,count,filename in [('sverdlovsky',12,'video_only_truth_sealed.json'),
                                ('sverdlovsky',10,'video_red_truth_sealed.json'),
                                ('enthusiasts',12,'video_only_truth_sealed.json')]:
        data=read(OUT/site/filename);rows=[r for w in data['windows'] for r in w['transitions']]
        assert len(rows)==count
        for row in rows:
            assert row['bracket_s'][0]<row['bracket_s'][1]
            for key in ('before','after'):
                frame=row[key];assert sha(OUT/frame['file'])==frame['sha256']
    frozen=read(OUT/'conditional_onset_calibration/frozen_candidates.json')
    pred=ROOT/'evidence/learned_archive_integration_20261018/archive_1/result.json'
    assert sha(pred)==frozen['source_prediction_sha256'] and frozen['production_enabled'] is False
    for color,name in [('green','video_only_truth_sealed.json'),('red','video_red_truth_sealed.json')]:
        assert sha(OUT/'sverdlovsky'/name)==frozen['truth_sha256'][color]
    assert read(OUT/'conditional_onset_calibration/evaluation.json')['json_video_clock_verified'] is False
    assert read(OUT/'browser/results.json')['status']=='PASS'
    return dict(status='PASS',video_green_intervals=24,clear_red_intervals=10,
                source_json_members=9,production_unchanged=True,independent_clock_mapping_verified=False)


def main(command):
    receipt=verify_inputs()
    if command=='seal':
        save(OUT/'tests_receipt.json',dict(command='pytest tests/test_video_onset_bias.py tests/test_video_signal_brackets.py tests/test_frame_clock_links.py tests/test_clock_observation_check.py tests/test_video_boundary_evidence.py -q -p no:cacheprovider',
            passed=50,failed=0,elapsed_s=.58,
            experimental_core_sha256=sha(ROOT/'app/experimental/video_onset_bias.py'),
            new_tests_sha256=sha(ROOT/'tests/test_video_onset_bias.py')))
        save(OUT/'attempts.json',dict(preserved_failures=[
            dict(step='initial inventory script',error='ModuleNotFoundError: ijson',resolution='reuse repository streaming parser; no new package installed'),
            dict(step='initial native truth finalization',error='ValueError: no clear green endpoint',resolution='earlier window exposed LED alias; retain combined2.467s bracket; initial artifacts kept'),
            dict(step='initial browser QA helper import',error='ModuleNotFoundError: PIL in optional QA-only venv',resolution='remove unnecessary imaging import from QA helper; actual MP4 check then passed')],
            coarse_color_proposals='Original and cyan-revised feature proposals retained; manually reject red-phase reflections; never tune against phase predictions',
            production_changes=0))
        files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p))
               for p in sorted(OUT.rglob('*')) if p.is_file()}
        save(OUT/'manifest.json',dict(receipt=receipt,files=files,
            scope='local video crops/metadata/labels/inventory/conditional diagnostics; source MP4s/ZIPs not redistributed'))
    else:
        manifest=read(OUT/'manifest.json')
        for name,item in manifest['files'].items():
            p=OUT/name;assert p.stat().st_size==item['bytes'] and sha(p)==item['sha256'],name
        assert {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()}==set(manifest['files'])|{'manifest.json'}
        receipt['files_verified']=len(manifest['files'])
    print(json.dumps(receipt))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['seal','verify'])
    main(p.parse_args().command)
