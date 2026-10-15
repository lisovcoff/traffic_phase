"""Reproduce the descriptive comparison from sealed video annotations only.

Uses previously saved extraction and clock profile. No archives, phase labels,
event extraction, optimization or production model calls.
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.experimental.restart_video_review import compare_review
from app.experimental.vehicle_clock_alignment import prepare_tracks, predict


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'evidence/seven_restart_review_20261015'


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    plan = load(OUT/'plan.json')
    assert sha(OUT/'plan.json') == (OUT/'plan.sha256').read_text().strip()
    assert sha(OUT/'visual_review.json') == (OUT/'visual_review.sha256').read_text().strip()
    for name, digest in plan['input_sha256'].items():
        assert sha(ROOT/name) == digest, name
    events = load(ROOT/'evidence/event_signal_associations_20261015/analysis/associations.json')['events']
    review = load(OUT/'visual_review.json')
    result = compare_review(review, events, plan['cohort'])
    profile = load(ROOT/'evidence/vehicle_clock_alignment_20261015/alignment_profile.json')
    records = load(ROOT/'evidence/video_calibration_pilot_20261015/trajectory_sample/calibration_tracks.json')
    tracks = [r for r in records if r['id'] in plan['cohort']]
    assert len(tracks) == 7
    (OUT/'selected_raw_tracks.json').write_text(json.dumps(tracks), encoding='utf8')
    pts = next(f['actual_media_time_s'] for f in load(OUT/'frames.json')['frames']
               if f['requested_elapsed_s'] == 318)
    coordinates = predict(prepare_tracks(tracks), [dict(track_id=r['track_id_hypothesis'],
        actual_media_pts_s=pts) for r in review['rows']], profile['homography'],
        profile['delta_s'], profile['origin_ms'])
    geometry = []
    for row, xy in zip(review['rows'], coordinates):
        a,b,c,d = row['stationary_roi_bbox_at_318_requested_px']
        point = [(a+c)/2+1050, b+.75*(d-b)+900]
        geometry.append(dict(track_id_hypothesis=row['track_id_hypothesis'],
            actual_media_pts_s=pts, projected_source_point_px=xy.tolist(),
            manual_video_feature_px=point,
            descriptive_residual_px=sum((x-y)**2 for x,y in zip(xy,point))**.5,
            interpretation='identity/feature definition/parallax/geometry/clock confounded; '
                'clipped rear features not independently defined; not a certified residual gate'))
    # Both times here are VIDEO presentation times; no JSON clock conversion.
    green = [318.866667, 318.933333]
    for row, out in zip(review['rows'], result):
        left, right = row['observed_onset_bracket_s']
        out['video_onset_minus_H1_green_range_s'] = [left-green[1], right-green[0]]
        out['H1_relation'] = 'same video cycle association; approach mapping UNCONFIRMED'
    report = dict(schema='seven-restart-video-comparison-v1', rows=result,
        geometry_diagnostic=geometry, events=len(result),
        comparable_certified_timing_count=sum(r['timing_validation_status'] != 'UNAVAILABLE' for r in result),
        candidate_points_before_video_bracket=sum(r['point_event_minus_onset_range_s'][1]<0 for r in result),
        conditional_sets_overlap_video_bracket=sum(r['conditional_sets_overlap_video_bracket'] for r in result),
        independent_signal_cycles=1, phase_fits=0, new_extractions=0,
        calibrated_event_delay_model='UNAVAILABLE', production_changed=False,
        input_sha256=plan['input_sha256'], visual_review_sha256=sha(OUT/'visual_review.json'))
    (OUT/'comparison.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    with (OUT/'events.csv').open('w', newline='', encoding='utf8') as f:
        writer = csv.writer(f)
        writer.writerow(['track_id','movement','video_object','video_onset_left_s','video_onset_right_s',
                         'candidate_release_media_s','candidate_minus_onset_min_s','candidate_minus_onset_max_s',
                         'conditional_clock_overlap','certified_timing_status'])
        for r in result:
            writer.writerow([r['track_id'],r['movement'],r['video_object'],*r['video_onset_bracket_s'],
                r['candidate_event_media_s'],*r['point_event_minus_onset_range_s'],
                r['conditional_sets_overlap_video_bracket'],r['timing_validation_status']])
    print(json.dumps({k:v for k,v in report.items() if k not in ['rows','input_sha256','geometry_diagnostic']}))
    print('Geometry descriptive residuals:', [round(g['descriptive_residual_px'],1) for g in geometry])


if __name__ == '__main__':
    main()
