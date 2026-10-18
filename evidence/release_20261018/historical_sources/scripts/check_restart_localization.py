"""Bounded event-only check. No phase inference, video sampling or label fitting.

Synthetic truth and real video review enter scoring only after outputs are sealed.
All real examples are development; this script never promotes a production policy.
"""
import argparse
from dataclasses import fields
import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.core.temporal_evidence import TemporalEvent
from app.core.v9.events import _kinematic_release_candidate
from app.core.v9.vehicle_evidence import clean_detections,extract_vehicle_evidence
from app.experimental.restart_localization import localize_restart
from tests.restart_localization_cases import generate_case

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/restart_localization_20261015'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf8'))


def save_new(name,value):
    path=OUT/name
    with path.open('x',encoding='utf8') as f:
        json.dump(value,f,indent=2,allow_nan=False)
    return sha(path)


def seal(name,inputs,output):
    save_new(name,dict(inputs_sha256={str(p.relative_to(ROOT)).replace('\\','/'):sha(p) for p in inputs},
                       output_sha256=sha(OUT/output)))


def synthetic(plan):
    start=time.perf_counter()
    cases=[];truth=[]
    for spec in plan['cases']:
        track,label=generate_case(spec,plan['generator'])
        cases.append(dict(name=spec['name'],track=track))
        truth.append(dict(name=spec['name'],**label))
    save_new('synthetic_inputs.json',cases)
    save_new('synthetic_truth.json',truth)  # generation, before inference
    results=[]
    for case in cases:
        events,_=extract_vehicle_evidence(case['track'])
        event=next((e for e in events if e.event_type=='RELEASE'),None)
        result=localize_restart(case['track'],event)
        results.append(dict(name=case['name'],result=result))
        if time.perf_counter()-start>plan['budgets']['synthetic_total_seconds']:
            raise RuntimeError('SYNTHETIC_RESOURCE_BUDGET_EXHAUSTED_NO_REAL_CHECK')
    save_new('synthetic_outputs.json',results)
    seal('synthetic_output_seal.json',[OUT/'plan.json',OUT/'synthetic_inputs.json'],'synthetic_outputs.json')
    # Only now score against independent generation truth.
    scored=[]
    for row,label in zip(results,load(OUT/'synthetic_truth.json')):
        r=row['result'];kind=label['kind']
        recover=kind in ['abrupt_dt01','abrupt_dt02','acceleration','identical_duplicates','sine_witness']
        item=dict(name=row['name'],expected_recovery=recover,status=r['status'])
        if recover and r['localized_event']:
            actual=label['independent_world_onset_ms']
            old=r['legacy_event']['timestamp_ms']-actual
            new=r['localized_event']['timestamp_ms']-actual
            interval=r['localized_event']['provenance']['observation_interval_ms']
            contained=interval[0]<=actual<=interval[1]
            passed=new>=-1 and new<=(1000 if kind=='acceleration' else label['dt_ms']+1)
            passed=passed and (contained or kind=='acceleration')
            item.update(old_error_ms=old,new_error_ms=new,observation_interval_contains_world_onset=contained,
                        gate_pass=passed)
        else:
            item['gate_pass']=not recover and r['status']=='unavailable'
        scored.append(item)
    metrics=dict(cases=len(scored),gate_pass=all(x['gate_pass'] for x in scored),
                 expected_recovery=sum(x['expected_recovery'] for x in scored),
                 recovered=sum(x['status']=='available_proxy' for x in scored),
                 unavailable=sum(x['status']=='unavailable' for x in scored),
                 rows=scored,runtime_s=time.perf_counter()-start,
                 semantics='vehicle image-motion proxy check, NOT signal-boundary or lamp accuracy')
    save_new('synthetic_metrics.json',metrics)
    print('Synthetic gate',metrics['gate_pass'],'cases',len(scored),'recovered',metrics['recovered'],
          'unavailable',metrics['unavailable'])
    if not metrics['gate_pass']:
        raise RuntimeError('SYNTHETIC_GATE_FAIL_NO_REAL_CHECK')


def real(plan):
    if not load(OUT/'synthetic_metrics.json')['gate_pass']:
        raise RuntimeError('SYNTHETIC_GATE_NOT_PASSED')
    frozen=load(OUT/'code_config_seal.json')
    for name,digest in frozen['files_sha256'].items():
        if sha(ROOT/name)!=digest:
            raise ValueError('FROZEN_CODE_CONFIG_CHANGED')
    source=ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json'
    sidecar=ROOT/'evidence/event_signal_associations_20261015/vehicle_events.json'
    tracks=load(source)
    events=[e for e in load(sidecar)['events'] if e['event_type']=='RELEASE'
            and e['source_track_id'] in {r['id'] for r in tracks}]
    if len(tracks)!=plan['budgets']['real_tracks'] or len(events)!=len(tracks):
        raise ValueError('FIXED_REAL_COHORT_MISMATCH')
    results=[];start=time.perf_counter()
    for record in tracks:
        source_event=next(e for e in events if e['source_track_id']==record['id'])
        event=TemporalEvent(**{f.name:source_event[f.name] for f in fields(TemporalEvent)})
        # Default selection/timestamp must still reproduce the saved seed.
        ds,_=clean_detections(record)
        legacy=_kinematic_release_candidate(ds,ds[0]['millis'],ds[-1]['millis'])
        if legacy is None or abs(legacy[1]*1000-event.timestamp_ms)>.001:
            raise ValueError('LEGACY_SEED_NOT_REPRODUCED_STOP')
        results.append(dict(track_id=record['id'],result=localize_restart(record,event),
                            unchanged_default_seed=list(legacy)))
    save_new('real_outputs.json',dict(rows=results,runtime_s=time.perf_counter()-start,
                                    fits=0,phase_model_replays=0,production_default_changed=False))
    seal('real_output_seal.json',[source,sidecar,OUT/'code_config_seal.json'],'real_outputs.json')
    print('Seven real event outputs sealed BEFORE reading video onset review')


def evaluate_real():
    output=load(OUT/'real_outputs.json')
    if sha(OUT/'real_outputs.json')!=load(OUT/'real_output_seal.json')['output_sha256']:
        raise ValueError('OUTPUT_SEAL_MISMATCH')
    review_path=ROOT/'evidence/seven_restart_review_20261015/visual_review.json'
    profile_path=ROOT/'evidence/local_vehicle_registration_20261015/local_model.json'
    clock_path=ROOT/'evidence/local_vehicle_registration_20261015/validation_result.json'
    review=load(review_path);profile=load(profile_path);clock=load(clock_path)
    rows=[]
    for row in output['rows']:
        tid=row['track_id'];r=row['result']
        annotation=next(a for a in review['rows'] if a['track_id_hypothesis']==tid)
        left,right=annotation['observed_onset_bracket_s']
        item=dict(track_id=tid,status=r['status'],video_onset_bracket_s=[left,right],
                  timing_validation_status='UNAVAILABLE_JOINT_CLOCK_GEOMETRY_IDENTITY_NOT_CALIBRATED',
                  physical_state='UNKNOWN',calibrated_lamp_probability=None)
        for name,key in [('old','legacy_event'),('new','localized_event')]:
            e=r[key]
            if e:
                rel=(e['timestamp_ms']-profile['origin_ms'])/1000
                point=rel-profile['delta_s']
                sets=[[rel-b,rel-a] for a,b in clock['joint_frozen_h_clock_sets_s']]
                distance=max(left-point,0,point-right)
                item[name]=dict(candidate_media_s=point,point_minus_onset_range_s=[point-right,point-left],
                    distance_to_sampled_video_bracket_s=distance,
                    conditional_clock_sets_s=sets,
                    conditional_clock_sets_overlap_bracket=any(a<=right and b>=left for a,b in sets))
        item['abstention_reason']=r['estimate']['abstention_reason']
        rows.append(item)
    report=dict(rows=rows,observations=len(rows),independent_cycles=1,
        available=sum(r['status']=='available_proxy' for r in rows),
        unavailable=sum(r['status']!='available_proxy' for r in rows),
        old_point_in_sampled_bracket=sum(r['old']['distance_to_sampled_video_bracket_s']==0 for r in rows),
        new_point_in_sampled_bracket=sum('new' in r and r['new']['distance_to_sampled_video_bracket_s']==0 for r in rows),
        semantics='development vehicle-level diagnostic, not phase accuracy; missing new events NOT counted as matches',
        video_review_sha256=sha(review_path),clock_model_sha256=sha(profile_path),
        clock_validation_sha256=sha(clock_path),real_output_sha256=sha(OUT/'real_outputs.json'))
    save_new('real_comparison.json',report)
    print('Development cohort',report['available'],'available',report['unavailable'],'UNKNOWN;',
          'point inside sampled bracket old/new',report['old_point_in_sampled_bracket'],report['new_point_in_sampled_bracket'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['synthetic','real','evaluate-real'])
    mode=parser.parse_args().mode
    plan=load(OUT/'plan.json')
    if sha(OUT/'plan.json')!=(OUT/'plan.sha256').read_text().strip():
        raise ValueError('PLAN_SEAL_MISMATCH')
    {'synthetic':lambda:synthetic(plan),'real':lambda:real(plan),'evaluate-real':evaluate_real}[mode]()
