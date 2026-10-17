"""Seal unresolved associations separately from established source provenance."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent


def save(name,value):
    p=OUT/name
    if p.exists():raise ValueError(f'fresh output required: {name}')
    p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


tracks=json.loads((ROOT/'.web_runtime'/OUT.name/'first_entry.json').read_text(encoding='utf-8'))
subset=[t for t in tracks if t['id'] in (258,441,652)]
save('candidate_raw_tracks.json',subset)
origin=1740300640994
candidates=[]
for t in subset:
    # These are cross-modal candidate episode references, explicitly NOT anchors.
    episode={258:('green full-size bus E-to-W',[90,100,110,120,130,150]),
             441:('red trolleybus E-to-W; another red trolleybus also visible at250s',[220,230,240,250]),
             652:('green full-size bus E-to-W',[300,310,330,360])}[t['id']]
    raw=json.dumps(t,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    candidates.append(dict(source_entry='6_2025_2_23_13.json',source_track_id=t['id'],
        source_raw_record_canonical_sha256=hashlib.sha256(raw).hexdigest(),category=t['category_name'],
        source_movement=[t['zone_in'],t['zone_out']],source_detection_extent_ms=[t['detections'][0]['millis'],t['detections'][-1]['millis']],
        source_extent_relative_to_first_entry_detection_s=[(t['detections'][0]['millis']-origin)/1000,(t['detections'][-1]['millis']-origin)/1000],
        video_episode_description=episode[0],video_review_requested_context_s=episode[1],
        association_status='PROVISIONAL_NOT_ADMITTED',identity_independently_verified=False,
        use_for_calibration=False,use_for_validation=False,json_to_video_offset_s=None,
        limitations=['class/route/order are insufficient for certified identity',
                    'source appearance crop/frame ID/PTS unavailable',
                    'coarse samples do not establish continuous vehicle identity',
                    'supplier recommends car category due detection error']))
save('candidate_review.json',dict(candidates=candidates,accepted_associations=[],
    review_basis='manual image context and raw vehicle metadata; no signal/phase matching',
    source_pair_status='SUPPLIER_LINKED_MEDIA_HASH_VERIFIED',clock_status='UNAVAILABLE_UNVERIFIED_CLOCK_LINK',
    confirmed_car_associations=0,clock_image_fit_calls=0,accepted_clock_transform=None,
    calibrated_sync_uncertainty_ms=None,drift_estimate=None,paired_metric_denominator=0,
    phase_fitting_runs=0,independent_second_reviewer=False,
    nonconclusion='No claim that the source pair is incompatible or that denser manual association is impossible.'))
template=json.loads((ROOT/'config/frame_clock_links_template.json').read_text(encoding='utf-8'))
template.update(capture_id='Enthusiasts supplier-linked 2024-10-05 video',
    video_source_id='sha256:c574f9204abab0b2bd4dd88425e581da8d335c8e6be0cf4425c0ac7143bfa987',
    trajectory_source_id='archive-sha256:b7190a8171e8af4cdfd7d7a66aa0fa5c60aadf96b95f558fbe53b9d00e48e534',
    source_reference='Инфо.docx paragraph19 and rId10; exact video hash verified; no same-exposure rows supplied',rows=[])
save('frame_clock_links_template.json',template)
cars=sorted((t for t in tracks if t['category_name']=='car'),key=lambda t:t['detections'][0]['millis'])
requests=[]
for index in (0,len(cars)//2,len(cars)-1):
    t=cars[index];d=t['detections'][len(t['detections'])//2]
    requests.append(dict(source_entry='6_2025_2_23_13.json',track_id=t['id'],
        detection_timestamp_ms=d['millis'],bbox_normalized={k:d[k] for k in ('x1','y1','x2','y2')},
        requested_video_pts_ticks=None,requested_same_exposure_reference=None))
save('producer_request_records.json',dict(records=requests,
    purpose='Unambiguous raw lookup examples for producer; no guessed video frames.',
    time_extent_limitation='All three examples are in the first JSON member. Additional separated-time anchors required for long-session drift.',
    sent=False))
save('user_provenance.json',dict(date_local='2026-10-18',
    question='Известно ли, что архив «Ленина-Энтузиастов 05.10.24.zip» получен обработкой именно видео lenina_entuziastov.mp4, или их соответствие пока предполагается только по названию?',
    answer='если даты совспадат, то да. но в инфо.докс  должно быть  написано подробнее',
    interpretation='Conditional date-based belief and instruction to inspect supplier document; not an unconditional pair or clock confirmation.'))
print(json.dumps(dict(unresolved_bus_candidates=len(candidates),accepted_vehicle_associations=0,
    producer_lookup_examples=len(requests),clock_transform=None)))
