"""Final evidence receipts, immutable old inputs and portable SHA manifest."""
import argparse
import json
import subprocess
from PIL import Image,ImageDraw
from scripts.yellow_video_review import OUT,ROOT
from scripts.cardinal_clock_link import read,save,sha


def code_sha(p):
    import hashlib
    return hashlib.sha256(p.read_text(encoding='utf8').encode('utf8')).hexdigest()


def check():
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    assert not subprocess.check_output(['git','diff','2669ea8','--','app/core/learned_phase.py','app/core/v9','config/learned_profiles','app/core/state_contract.py'],cwd=ROOT)
    old_count=0
    for name in ['direct_video_truth_20261018','cardinal_clock_link_20261018','enthusiasts_turn_clock_20261019']:
        folder=OUT.parent/name;m=read(folder/'manifest.json')
        for file,record in m['files'].items():
            p=folder/file;assert p.stat().st_size==record['bytes'] and sha(p)==record['sha256'],p
            old_count+=1
    assert read(OUT/'browser_v3/results.json')['status']=='PASS'
    assert read(OUT/'clock3600/result.json')['status']=='PASS'
    assert read(OUT/'integration_receipt.json')['status']=='PASS'
    for site,count in [('sverdlovsky',9),('enthusiasts',8)]:
        labels=read(OUT/site/'fresh_truth_sealed.json');assert len(labels['rows'])==count
        assert labels['prediction_data_read'] is False
        for row in labels['rows']:
            for key in ['before','after']:assert sha(OUT/row[key]['file'])==row[key]['sha256']
    assert read(OUT/'generic_training_reproduction.json')['exact_frozen_delays_reproduced']
    return old_count


def seal():
    # Display the FINAL endpoint labels; preserve original proposal sheets too.
    for site in ['sverdlovsky','enthusiasts']:
        rows=read(OUT/site/'fresh_truth_sealed.json')['rows'];box=(65,30,125,100) if site=='sverdlovsky' else (27,19,77,84)
        sheet=Image.new('RGB',(900,180*len(rows)),(20,25,35));d=ImageDraw.Draw(sheet)
        for j,row in enumerate(rows):
            d.text((410,j*180+15),f"{row['color']} {row['index']} {row['confidence']}",fill='white')
            for i,key in enumerate(['before','after']):
                r=row[key];im=Image.open(OUT/r['file']).crop(box);im=im.resize((im.width*2,im.height*2),Image.Resampling.NEAREST)
                sheet.paste(im,(200*i,j*180+30));d.text((200*i,j*180+5),f"{key} {r['pts_s']:.6f}",fill='white')
        sheet.save(OUT/site/'fresh_endpoints_reviewed.png')
    page=(OUT/'report.html').read_text(encoding='utf8')
    page=page.replace('fresh_endpoints.png','fresh_endpoints_reviewed.png').replace('затем28 затронутых','затем38 затронутых')
    (OUT/'report.html').write_text(page,encoding='utf8',newline='\n')
    save(OUT/'tests_receipt.json',dict(full=dict(passed=1392,failed=0,warnings=5,elapsed_s=258.87,
        command='pytest -q -p no:cacheprovider --basetemp=.web_runtime/yellow_pytest_20261019'),
        final_affected=dict(passed=38,failed=0,warnings=1,elapsed_s=6.53,
            command='pytest tests/test_signal_timing.py tests/test_timing_profiles.py tests/test_timing_calibration.py tests/test_estimated_signals.py tests/test_learned_visualization.py tests/v9/test_v9_spatial_visualizer.py tests/test_spatial_model_view.py -q -p no:cacheprovider'),
        browser='browser_v3/results.json',browser_screenshots_visually_reviewed=True))
    save(OUT/'attempts.json',dict(
        initial_catalog_test='1 failed/19 passed: old test counted microstates as stable phases; now checks preserved operating catalog; full suite passed',
        initial_native_sampling='two failed ffmpeg calls with duration .8; same windows rerun with0.8 in development_native_v2; initial plans preserved',
        endpoint_correction='First Enth yellow proposed before already yellow. Reviewed earlier native green3367.866667 -> yellow3367.933333 before sealing and evaluation; proposal retained',
        report_assertion='full schedule equality failed due old wrapper A/B/C vs exported C/A/B labels; raw boundaries/count/period and mapped signals exact; assertion scope corrected',
        browser_mobile='first two attempts failed min-content width for long transition state names. Original HTML and failed screenshots/overflow JSON retained; CSS wrap/min-width fix passes both viewers',
        initial_final_test_command='wrong tests/test_v9_spatial_visualizer.py path: no tests ran; corrected tests/v9 path final38 PASS',
        scientific_parameters_retuned_after_validation=False))
    verified=check()
    code_paths=[ROOT/'app/core/v10'/name for name in ['signal_timing.py','timing_calibration.py','timing_profiles.py','estimated_signals.py']]
    code_paths += [ROOT/'app/core/learned_visualization.py',ROOT/'scripts/v9_spatial_visualizer.py',ROOT/'config/known_intersections.json',ROOT/'config/signal_timing_profiles.json']
    names=['yellow_video_review','review_yellow_validation','yellow_green_sheets','refine_fresh_yellow_truth','propose_fresh_signal_truth',
        'seal_fresh_signal_truth','check_yellow_late_clock','score_yellow_late_clock','evaluate_yellow_timing','build_yellow_report',
        'fix_yellow_review_layout','qa_yellow_timing','seal_yellow_timing']
    code_paths += [ROOT/'scripts'/f'{name}.py' for name in names]
    code_paths += [ROOT/'tests'/name for name in ['test_signal_timing.py','test_timing_calibration.py','test_timing_profiles.py','test_estimated_signals.py']]
    files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file()}
    save(OUT/'manifest.json',dict(files=files,code_text_lf_sha256={p.relative_to(ROOT).as_posix():code_sha(p) for p in code_paths},
        historical_files_verified=verified,production_changed='shared estimated signal timing and scoped learned adapter; raw inference core unchanged',
        source_videos_and_full_archives_redistributed=False))


def main(command):
    if command=='seal':seal()
    elif command=='reseal':
        check();old=read(OUT/'manifest.json')
        files={p.relative_to(OUT).as_posix():dict(bytes=p.stat().st_size,sha256=sha(p)) for p in sorted(OUT.rglob('*')) if p.is_file()}
        save(OUT/'manifest_v2.json',dict(files=files,
            code_text_lf_sha256={name:code_sha(ROOT/name) for name in set(old['code_text_lf_sha256'])|{'tests/v9/test_v9_spatial_visualizer.py'}},
            supersedes_manifest_sha256=sha(OUT/'manifest.json'),
            reason='Forward explicit CLI transition durations to shared signal history; prior manifest and source snapshots retained',
            source_videos_and_full_archives_redistributed=False))
    else:
        check();manifest=OUT/('manifest_v2.json' if (OUT/'manifest_v2.json').exists() else 'manifest.json');m=read(manifest)
        for name,record in m['files'].items():
            p=OUT/name;assert p.stat().st_size==record['bytes'] and sha(p)==record['sha256'],name
        for name,digest in m['code_text_lf_sha256'].items():assert code_sha(ROOT/name)==digest,name
        assert {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()}==set(m['files'])|{manifest.name}
    print('PASS: yellow release evidence, both video truths, real archives/browser, old evidence and main verified')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['seal','reseal','verify']);main(p.parse_args().command)
