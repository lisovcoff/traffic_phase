"""One descriptive evaluation of previously sealed two-block vehicle outputs."""
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.experimental.temporal_validation_clock import check_frozen_window

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_multicycle_validation_20261015'


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name,value):
    with (OUT/name).open('x',encoding='utf8') as f:
        json.dump(value,f,indent=2,allow_nan=False)


def main():
    if (OUT/'comparison.json').exists():
        raise ValueError('FRESH_OUTPUT_REQUIRED_NO_RETRY_AFTER_RESULTS')
    plan=load(OUT/'plan.json')
    for name,digest in plan['frozen_code_canonical_lf_sha256'].items():
        assert hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==digest,name
    assert sha(OUT/'frozen_event_outputs.json')==load(OUT/'output_seal.json')['output_sha256']
    assert sha(OUT/'visual_review.json')==(OUT/'visual_review.sha256').read_text().strip()
    assert sha(OUT/'clock_anchor_review.json')==(OUT/'clock_anchor_review.sha256').read_text().strip()
    review=load(OUT/'visual_review.json')
    anchors=load(OUT/'clock_anchor_review.json')
    records=load(OUT/'selected_raw_tracks.json')
    output=load(OUT/'frozen_event_outputs.json')
    modelpath=ROOT/'evidence/local_vehicle_registration_20261015/local_model.json'
    assert sha(modelpath)==plan['frozen_model_sha256']
    model=load(modelpath)
    clock={}
    for window in plan['windows']:
        name=window['name']
        clock[name]=check_frozen_window(model,[r['record'] for r in records if r['window']==name],
            [r for r in anchors['rows'] if r['window']==name])
        clock[name]['missing_video_anchors']=[r for r in anchors['unavailable'] if r['window']==name]
    save('clock_check.json',clock)
    rows=[]
    for result in output['rows']:
        block=result['window'];tid=result['track_id'];inferred=result['result']
        row=next(r for r in review['rows'] if r['track_id_hypothesis']==tid)
        head=next(h for h in review['head_references'] if h['window']==block)
        left,right=row['observed_onset_bracket_s'];ga,gb=head['media_bracket_s']
        item=dict(window=block,track_id=tid,movement=inferred['legacy_event']['movement'],
            status=inferred['status'],abstention_reason=inferred['estimate']['abstention_reason'],
            video_onset_bracket_s=[left,right],H1_green_appearance_bracket_s=[ga,gb],
            vehicle_onset_minus_H1_range_s=[left-gb,right-ga],
            independent_video_motion_wholly_before_green=right<ga,
            clock_check_status=clock[block]['status'],
            timing_validation_status='NOT_CALIBRATED_JOINT_GEOMETRY_CLOCK_IDENTITY',
            physical_state='UNKNOWN',calibrated_lamp_probability=None)
        for label,key in [('old','legacy_event'),('new','localized_event')]:
            event=inferred[key]
            if not event:
                continue
            rel=(event['timestamp_ms']-model['origin_ms'])/1000
            media=rel-model['delta_s']
            intervals=clock[block]['conditional_clock_set_s']
            sets=None if intervals is None else [[rel-b,rel-a] for a,b in intervals]
            item[label]=dict(nominal_media_s=media,nominal_point_minus_onset_range_s=[media-right,media-left],
                nominal_distance_to_sampled_bracket_s=max(left-media,0,media-right),
                conditional_clock_media_sets_s=sets,
                conditional_clock_set_overlap=None if sets is None else any(a<=right and b>=left for a,b in sets),
                observation_interval_ms=event['provenance'].get('observation_interval_ms'),
                uncertainty_semantics='nominal point is descriptive; conditional frozen-H sets NOT calibrated intervals')
        rows.append(item)
    summary=[]
    for window in plan['windows']:
        name=window['name'];part=[r for r in rows if r['window']==name];paired=[r for r in part if 'new' in r]
        summary.append(dict(window=name,observations=len(part),available=len(paired),unknown=len(part)-len(paired),
            old_point_in_bracket=sum(r['old']['nominal_distance_to_sampled_bracket_s']==0 for r in part),
            new_point_in_bracket=sum(r['new']['nominal_distance_to_sampled_bracket_s']==0 for r in paired),
            point_count_denominator=len(part),old_mean_distance_full_s=sum(r['old']['nominal_distance_to_sampled_bracket_s'] for r in part)/len(part) if part else None,
            paired_distance_denominator=len(paired),
            old_mean_distance_paired_s=sum(r['old']['nominal_distance_to_sampled_bracket_s'] for r in paired)/len(paired) if paired else None,
            new_mean_distance_available_s=sum(r['new']['nominal_distance_to_sampled_bracket_s'] for r in paired)/len(paired) if paired else None,
            motion_wholly_before_H1_green=sum(r['independent_video_motion_wholly_before_green'] for r in part),
            clock_status=clock[name]['status'],media_range_s=window['media_range_s']))
    report=dict(rows=rows,summary=summary,observed_video_cycles=2,
        old_reviewed_tracks_excluded=243,phase_fits=0,clock_fits=0,production_promoted=False,
        integration_status='NOT_ACCEPTED_AS_CALIBRATED_SIGNAL_PERMISSION_OR_SWITCH_EVIDENCE',
        next_scope='explicit opt-in event adapter may preserve localization/UNKNOWN/intervals; signal likelihood must allow motion before green and unobserved demand, no universal positive delay',
        denominator_scope='first4 existing selected N-release tracks per block, NOT all vehicle starts; no population recall claimed',
        evaluation_seals=dict(outputs_sha256=sha(OUT/'frozen_event_outputs.json'),
            video_review_sha256=sha(OUT/'visual_review.json'),anchor_review_sha256=sha(OUT/'clock_anchor_review.json')))
    save('comparison.json',report)
    with (OUT/'comparison.csv').open('x',encoding='utf8',newline='') as f:
        writer=csv.writer(f);writer.writerow(['block','track_id','movement','status','old_distance_to_video_bracket_s',
            'new_distance_to_video_bracket_s','motion_before_H1_min_s','motion_before_H1_max_s','clock_status','reason'])
        for r in rows:
            writer.writerow([r['window'],r['track_id'],r['movement'],r['status'],r['old']['nominal_distance_to_sampled_bracket_s'],
                r.get('new',{}).get('nominal_distance_to_sampled_bracket_s'),*r['vehicle_onset_minus_H1_range_s'],r['clock_check_status'],r['abstention_reason']])
    for r in summary:
        print(json.dumps(r))
    print('No calibrated signal model/default promotion; all8 denominator retained')


if __name__=='__main__':
    main()
