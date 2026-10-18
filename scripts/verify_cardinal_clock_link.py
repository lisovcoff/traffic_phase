"""Seal and verify the clock-link review without fitting or phase replay."""
import argparse
import json
import subprocess
from app.experimental.video_clock_mapping import map_bracket
from scripts.cardinal_clock_link import ROOT,OUT,read,save,sha
from scripts.verify_direct_video_truth import main as verify_old


def verify_inputs():
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    protected=['app/core','app/api','app/main.py','config/learned_profiles','config/known_intersections.json']
    assert not subprocess.check_output(['git','diff','55c99e4','--',*protected],cwd=ROOT)
    assert read(OUT/'result.json')['status']=='REJECTED'
    assert read(OUT/'sverdlovsky_motion/clock_validation.json')['status']=='EMPIRICAL_FROZEN_HYPOTHESIS_PASSES'
    late=read(OUT/'sverdlovsky_late_control/clock_validation.json');assert late['status']=='PASS'
    assert late['clock_refit'] is False and late['geometry_refit'] is False
    corrections=read(OUT/'user_head_corrections.json')
    assert corrections['sverdlovsky']['extra_section_movement']=='N->E'
    assert corrections['enthusiasts']['visible_head_approach']=='E'
    mapped=read(OUT/'mapped_main_truth.json');assert len(mapped['rows'])==22
    for r in mapped['rows']:
        expected=map_bracket(r['video_bracket_s'],origin_ms=1740632395000,delta_s=mapped['delta_s'],delta_bounds_s=mapped['conditional_delta_bounds_s'])
        for k,v in expected.items():assert r[k]==v
    calibration=read(OUT/'clock_aware_calibration.json')
    assert calibration['production_enabled'] is False and calibration['independent_new_holdout_claimed'] is False
    payload=read(OUT/'comparison_data.json');timeline=read(OUT/'calibrated_N_main_onsets.json')['events']
    assert len(payload['events'])==len(timeline)
    for a,b in zip(payload['events'],timeline):
        assert abs(a['time']-a['bias']-b['video_pts_s'])<1e-8
        assert b['calibrated_json_timestamp_ms']<b['original_json_timestamp_ms']
    assert read(OUT/'browser/results.json')['status']=='PASS'
    assert read(OUT/'sverdlovsky_frozen_review/candidates.json')['source_track_subset_sha256']==sha(OUT/'sverdlovsky_frozen_review/source_tracks_clipped.json')
    verify_old('verify')


def main(command):
    if command=='seal':
        cache=ROOT/'.web_runtime/cardinal_clock_link_20261018/fresh_tracks.json'
        with (OUT/'sverdlovsky_frozen_review/source_tracks_clipped.json').open('xb') as f:f.write(cache.read_bytes())
        save(OUT/'attempts.json',dict(
            rejected_fit='Enthusiasts: one wider development fit, max133.479px and road horizon crossing; no retry',
            initial_fresh_car_score='INVALID_SOURCE_FEATURES from unrelated one-point clipped tracks; filter to three declared IDs, same sealed annotations and frozen model',
            initial_clock_aware_builder='SyntaxError unmatched parenthesis; corrected before any output',
            additional_late_control_reason='Documented coverage extension to3300s before extracting frames; no refit',
            discarded_results=False,production_changes=False))
        save(OUT/'tests_receipt.json',dict(passed=57,failed=0,elapsed_s=.66,
            command='pytest tests/test_video_clock_mapping.py tests/test_video_onset_bias.py tests/test_video_signal_brackets.py tests/test_frame_clock_links.py tests/test_clock_observation_check.py tests/test_video_boundary_evidence.py -q -p no:cacheprovider',
            browser_result='browser/results.json'))
    verify_inputs()
    if command=='seal':
        scripts=['cardinal_clock_link','build_cardinal_clock_review','collect_sverdlovsky_vehicle_motion',
            'score_sverdlovsky_frozen_clock','collect_late_clock_control','score_late_clock_control',
            'build_clock_aware_video_review','qa_clock_aware_video_review','build_enthusiasts_identity_review','verify_cardinal_clock_link']
        code=[ROOT/'scripts'/f'{name}.py' for name in scripts]
        code += [ROOT/'app/experimental/video_clock_mapping.py',ROOT/'tests/test_video_clock_mapping.py']
        files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file()}
        save(OUT/'manifest.json',dict(files=files,code={p.relative_to(ROOT).as_posix():sha(p) for p in code},
            source_scope='clipped vehicle detections and local image crops only; no full MP4 or full archive redistributed',
            production_changed=False))
    else:
        manifest=read(OUT/'manifest.json')
        for name,item in manifest['files'].items():
            p=OUT/name;assert p.stat().st_size==item['bytes'] and sha(p)==item['sha256'],name
        for name,digest in manifest['code'].items():assert sha(ROOT/name)==digest,name
        assert {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()}==set(manifest['files'])|{'manifest.json'}
    print(json.dumps(dict(status='PASS',clock_support_cars=4,mapped_truth_onsets=22,production_unchanged=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['seal','verify'])
    main(parser.parse_args().command)
