"""Assemble saved calibration evidence only. No trajectory/video read or inference."""
from pathlib import Path
import csv
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.experimental.calibration_bundle import build_bundle

SOURCES = {
    'direct_video':'evidence/video_boundary_verification_20261015/verified_video_boundaries.json',
    'vehicle_video':'evidence/restart_multicycle_validation_20261015/visual_review.json',
    'operator':'evidence/video_calibration_intake_20261015/clarified_events.json',
    'proxy_queries':'evidence/restart_multicycle_validation_20261015/evidence_adapter_queries.json',
    'clock_candidate':'evidence/local_vehicle_registration_20261015/local_model.json',
    'clock_checks':'evidence/restart_multicycle_validation_20261015/clock_check.json',
    'mapping':'evidence/video_calibration_intake_20261015/h1_operator_mapping.json',
    'trajectory_lineage':'evidence/video_calibration_pilot_20261015/trajectory_sample/sample_manifest.json',
    'review_template':'evidence/video_calibration_pilot_20261015/review_template.json',
    'review_proofs':'evidence/restart_multicycle_validation_20261015/proof_manifest.json',
    'criteria':'config/calibration_acceptance_v1.json',
}


def main():
    folder=ROOT/'evidence/calibration_bundle_20261016'
    folder.mkdir(exist_ok=True)
    sources, seals, total = {}, {}, 0
    for key, relative in SOURCES.items():
        path=ROOT/relative
        if path.stat().st_size>1024*1024:
            raise ValueError('SOURCE_BYTE_BUDGET_EXCEEDED')
        raw=path.read_bytes();total+=len(raw)
        if total>4*1024*1024:
            raise ValueError('TOTAL_SOURCE_BYTE_BUDGET_EXCEEDED')
        sources[key]=json.loads(raw)
        seals[key]=dict(path=relative,sha256_lf=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest())
    bundle=build_bundle(sources)
    bundle['source_catalog']=seals
    proofs={row['file']:row for row in sources['review_proofs']}
    for record in bundle['records']:
        if record['source_key']!='vehicle_video':continue
        name=(f"proof/onset_{record['window']}_{record['track_id_hypothesis']}.png"
              if record['kind']=='sampled_vehicle_motion' else f"proof/H1_{record['window']}.png")
        proof=proofs.get(name)
        if proof is None:raise ValueError('DERIVED_REVIEW_ASSET_REFERENCE_MISSING')
        if not {f['sha256'] for f in record['frame_references']}.issubset({f['sha256'] for f in proof['source_frames']}):
            raise ValueError('DERIVED_REVIEW_ASSET_LINEAGE_MISMATCH')
        record['derived_review_asset']=dict(path='evidence/restart_multicycle_validation_20261015/'+name,
            sha256=proof['sha256'],semantics=proof['processing'])
    def write(name,value):
        (folder/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    # Resolve only explicitly referenced frame paths, with a separate bounded budget.
    integrity=[];frame_bytes=0
    for row in sources['direct_video']['transitions']:
        for field in ('before_frame','after_frame'):
            ref=row[field];path=(ROOT/ref['path']).resolve()
            if not path.is_relative_to(ROOT):raise ValueError('FRAME_PATH_OUTSIDE_REPOSITORY')
            result=dict(path=ref['path'],expected_sha256=ref['sha256'])
            if not path.is_file():result['status']='MISSING_LOCAL_FRAME'
            elif path.stat().st_size>8*1024*1024 or frame_bytes+path.stat().st_size>32*1024*1024:
                result['status']='FRAME_VERIFICATION_BUDGET_EXCEEDED'
            else:
                raw=path.read_bytes();frame_bytes+=len(raw)
                actual=hashlib.sha256(raw).hexdigest();result.update(sha256=actual,status='MATCH' if actual==ref['sha256'] else 'HASH_MISMATCH')
            integrity.append(result)
    derived=[]
    for record in bundle['records']:
        ref=record.get('derived_review_asset')
        if ref is None:continue
        path=(ROOT/ref['path']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():raise ValueError('DERIVED_REVIEW_ASSET_MISSING')
        if frame_bytes+path.stat().st_size>32*1024*1024:raise ValueError('FRAME_VERIFICATION_BUDGET_EXCEEDED')
        raw=path.read_bytes();frame_bytes+=len(raw)
        actual=hashlib.sha256(raw).hexdigest()
        derived.append(dict(path=ref['path'],sha256=actual,status='MATCH' if actual==ref['sha256'] else 'HASH_MISMATCH'))
    if any(x['status']=='HASH_MISMATCH' for x in integrity+derived):raise ValueError('SOURCE_FRAME_HASH_MISMATCH')
    write('calibration_bundle.json',bundle)
    write('frame_integrity.json',dict(frames=integrity,bytes_read=frame_bytes,
        derived_review_assets=derived,
        other_frame_references='recorded hashes preserved; original blobs not verified by this bounded check'))
    metrics=[]
    definitions=[('K','NO_COMPLETE_INTERSECTION_PHASE_TRUTH'),
                 ('phase_composition','RAW_MOVEMENT_PERMISSION_MAPPING_UNCONFIRMED'),
                 ('phase_boundaries_json_clock','CALIBRATED_JSON_VIDEO_SYNC_UNAVAILABLE'),
                 ('vehicle_event_timing_json_clock','CALIBRATED_JSON_VIDEO_SYNC_AND_IDENTITY_UNAVAILABLE'),
                 ('per_second_physical_sections','NO_CONTINUOUS_LAMP_TRUTH'),
                 ('hold_shortening_episodes','NO_INDEPENDENT_EXTENSION_EPISODE_LABELS')]
    for name,reason in definitions:
        metrics.append(dict(metric=name,status='UNAVAILABLE',value=None,eligible_observations=0,
                            time_range=None,reason=reason))
    signals=[r for r in bundle['records'] if r['kind']=='sampled_signal_appearance']
    metrics.append(dict(metric='saved_signal_appearance_review',status='AVAILABLE_FOR_REVIEW_ONLY',
        value=None,eligible_observations=len(signals),time_range=[min(r['media_interval_s'][0] for r in signals),max(r['media_interval_s'][1] for r in signals)],
        time_unit='video_media_seconds',reason='not a reconstructed-signal accuracy metric'))
    write('metric_eligibility.json',dict(metrics=metrics,metrics_evaluated=False,
        predictions_loaded=False,criteria_source=seals['criteria']))
    template=json.loads(json.dumps(sources['review_template']))
    template.update(status='AWAITING_INDEPENDENT_REVIEW',independent_truth_filled=False,
        reused_template_source=seals['review_template'],
        review_tasks=[dict(record_id=r['record_id'],source_key=r['source_key'],source_pointer=r['source_pointer'],
            review_assets=[r['derived_review_asset']] if 'derived_review_asset' in r else r.get('frame_references',[]),
            independent_reviewer=None,independent_event_type=None,independent_interval=None,
            visibility=None,uncertainty=None,geometry_source=None,notes=None)
            for r in bundle['records'] if r['kind'] in ('sampled_signal_appearance','sampled_vehicle_motion')])
    write('independent_review_tasks.json',template)
    with (folder/'evidence_table.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=['record_id','kind','clock','start','end','event','source','status'])
        writer.writeheader()
        for row in bundle['records']:
            interval=row.get('media_interval_s',row.get('annotated_interval_ms'))
            if interval is None:interval=[row['original_event']['timestamp_ms']]*2
            writer.writerow(dict(record_id=row['record_id'],kind=row['kind'],
                clock='video_media_seconds' if 'media_interval_s' in row else 'trajectory_milliseconds',
                start=interval[0],end=interval[1],event=row.get('event',row.get('claimed_start_event',row.get('original_event',{}).get('event_type','vehicle_motion'))),
                source=seals[row['source_key']]['path']+'#'+row['source_pointer'],
                status=row.get('interpretation_status',row.get('identity_status','unverified'))))
    code={name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in
          ['app/experimental/calibration_bundle.py','scripts/prepare_calibration_bundle.py','config/calibration_acceptance_v1.json']}
    write('manifest.json',dict(base_sha='5038b7eb0a0eb7ba4ddebaf1376e2b0943b96d8b',
        sources=seals,code_sha256_lf=code,source_bytes_read=total,frame_bytes_read=frame_bytes,
        inference_calls=0,video_trajectory_archive_bytes_read=0,independent_validation_sessions=0,
        outputs={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file() and p.name not in ('manifest.json','commands.log')}))
    print(json.dumps(dict(records=len(bundle['records']),counts=bundle['counts'],
        frames_verified=sum(x['status']=='MATCH' for x in integrity),same_video_motion_before_H1=bundle['same_video_motion_before_H1_count'],
        inference_calls=0,metric_status='UNAVAILABLE_FOR_INDEPENDENT_SIGNAL_ACCURACY')))


if __name__=='__main__':main()
