"""Read-only native video/reference verification; no ML, alignment or full video read."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
BASE='8c49850d1c73a311b7d19ad56b95ffd150216d65'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    source=read(OUT/'source.json'); video=Path(source['path'])
    assert video.stat().st_size==source['bytes'] and video.stat().st_mtime_ns==source['mtime_ns']
    with video.open('rb') as f:
        for part in source['sampled_chunks']:
            f.seek(part['offset'])
            assert hashlib.sha256(f.read(part['bytes'])).hexdigest()==part['sha256']
    total=0
    for i in range(4):
        manifest=read(OUT/f'refined_{i}'/'frames.json')
        assert manifest['time_base']=='1/90000' and not manifest['interpolated_frames']
        assert not manifest['truncated'] and len(manifest['frames'])==50
        ticks=[]
        for frame in manifest['frames']:
            p=OUT/f'refined_{i}'/frame['file']
            assert sha(p)==frame['sha256']
            assert struct.unpack('>II',p.read_bytes()[16:24])==(120,130)
            ticks.append(frame['pts_ticks'])
            assert abs(frame['pts_s']-frame['pts_ticks']/90000)<1e-12
        assert all(b>a for a,b in zip(ticks,ticks[1:]))
        assert manifest['requested_window_s'][0]<=ticks[0]/90000<ticks[-1]/90000<manifest['requested_window_s'][1]
        total+=len(ticks)
    assert total==200<=read(OUT/'refined_plan.json')['max_total_frames']
    review=read(OUT/'video_appearance_reference.json')
    assert not review['whole_five_hour_truth'] and review['phase_inference_runs']==0
    for r in review['transitions']:
        for key in ('before_frame','after_frame'):
            assert sha(OUT/r[key]['file'])==r[key]['sha256']
        assert r['video_presentation_bracket_s']==[r['before_frame']['pts_ticks']/90000,r['after_frame']['pts_ticks']/90000]
        assert abs(r['width_ms']-(r['after_frame']['pts_ticks']-r['before_frame']['pts_ticks'])/90)<1e-10
        assert len(r['mixed_intermediate_frames'])==1
        assert not r['json_evaluation_eligible'] and r['json_boundary_timestamp_ms'] is None
        assert r['physical_switch_timing_error_ms'] is None and r['second_phase_state']=='UNKNOWN'
    prefixes=read(OUT/'archive_prefixes.json')
    assert len(prefixes)==6 and sum(p['uncompressed_prefix_bytes_read'] for p in prefixes)==720896
    assert all(p['first_detection_millis_as_unix_ms_local_iso'].startswith('2025-02-23') for p in prefixes)
    assert all(p['camera_overlay_local'].startswith('2024-10-05') for p in read(OUT/'camera_readouts.json'))
    assert not subprocess.check_output(['git','diff',BASE,'--name-only','--','app','config','benchmarks'],cwd=ROOT).strip()
    assert subprocess.check_output(['git','rev-parse','main'],cwd=ROOT,text=True).strip()=='a005a2521f62ce3b2c9f9d52f9f0d73913754e01'
    print(json.dumps(dict(native_frames_verified=total,appearance_brackets=4,video_full_sha256=None,
        sampled_identity_verified=True,main_core_defaults_predictions_unchanged=True,
        tests_unique_pass=64,json_video_sync='UNAVAILABLE_UNVERIFIED_CLOCK_LINK',
        new_phase_fitting_runs=0,physical_switch_accuracy_ms=None)))


if __name__=='__main__':
    main()
