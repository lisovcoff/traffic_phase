"""Reproduce only the saved sample/container inventory, not ffprobe or inference."""
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sample = ROOT/'evidence/seven_restart_review_20261015/selected_raw_tracks.json'
if sample.stat().st_size > 4*1024*1024:
    raise ValueError('INPUT_BYTE_LIMIT')
raw = sample.read_bytes()
expected = json.loads((ROOT/'evidence/h1_confirmation_20261016/confirmation.json').read_text(encoding='utf-8'))['source_catalog']['raw_anchors']['sha256_lf']
digest = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
assert digest == expected, 'SOURCE_SAMPLE_SEAL_MISMATCH'
records = json.loads(raw)
track_fields, detection_fields = Counter(), Counter()
rows = []
for record in records:
    track_fields.update(record.keys())
    fields = Counter()
    for detection in record['detections']:
        fields.update(detection.keys())
    detection_fields.update(fields)
    rows.append(dict(track_id=record['id'], detections=len(record['detections']),
                     detection_fields=dict(sorted(fields.items()))))
aliases = ['frame', 'frame_id', 'frameId', 'frame_index', 'frame_number', 'frameNumber',
           'pts', 'dts', 'video_pts_ticks', 'time_base', 'frame_timestamp', 'capture_timestamp']
metadata_path = OUT/'container_metadata.json'
metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
result = dict(schema='frame-clock-source-inventory-v1',
              scope='all detections of the saved seven-track cohort only; not all archives',
              sample_path=sample.relative_to(ROOT).as_posix(), sample_bytes=len(raw),
              sample_sha256_lf=digest, track_count=len(records),
              detection_count=sum(len(r['detections']) for r in records),
              track_fields=dict(sorted(track_fields.items())),
              detection_fields=dict(sorted(detection_fields.items())), tracks=rows,
              explicit_frame_link_alias_counts={k: dict(track=track_fields[k], detection=detection_fields[k]) for k in aliases},
              container_metadata_path=metadata_path.relative_to(ROOT).as_posix(),
              container_metadata_sha256_lf=hashlib.sha256(metadata_path.read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
              metadata=metadata,
              absolute_detection_to_frame_link='UNAVAILABLE',
              clock_tag_interpretation='container start_time/rates/encoder tags do not identify detections[].millis',
              media_decoding_calls=0, inference_calls=0, clock_fit_calls=0,
              physical_section_state='UNKNOWN')
target = OUT/'source_inventory.json'
if target.exists():
    raise ValueError('FRESH_OUTPUT_REQUIRED')
target.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
print(json.dumps(dict(tracks=result['track_count'], detections=result['detection_count'],
                     frame_link=result['absolute_detection_to_frame_link'], sample_bytes=len(raw))))
