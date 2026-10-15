"""Inspect a video review export without inference or interpretation of group IDs."""
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

from app.core.annotation_workbench import validate_review


def inspect(review, sample_manifest):
    validation = validate_review(review)
    source = review['source']
    sample = sample_manifest['sample']
    if source['sha256'] != sample['sha256'] or source['bytes'] != sample['bytes']:
        raise ValueError('SOURCE_IDENTITY_MISMATCH')
    if [source['timestamp_origin_ms'], source['end_timestamp_ms']] != sample_manifest['sample_detection_extent_ms']:
        raise ValueError('SOURCE_TIME_EXTENT_MISMATCH')
    rows = []
    local = timezone(timedelta(hours=5))
    for mark in review['annotations']:
        a, b = mark['interval_start_ms'], mark['interval_end_ms']
        sync = mark['evidence_source'].get('synchronization', {})
        binding = sync.get('video_binding')
        media = None
        if binding:
            media = [binding['video_seconds'] + (x-binding['trajectory_timestamp_ms'])/1000 for x in (a,b)]
        rows.append({
            'id': mark['id'], 'label': mark['label'], 'kind': mark['kind'],
            'range_ms': [a,b], 'local_range': [datetime.fromtimestamp(x/1000,local).isoformat() for x in (a,b)],
            'duration_s': (b-a)/1000, 'derived_media_range_s': media,
            'media_conversion_status': 'manual_binding_UNVERIFIED' if media else 'UNAVAILABLE',
            'synchronization': sync, 'physical_section': 'UNCONFIRMED',
            'physical_state': 'UNKNOWN_pending_explicit_group_semantics',
            'selected_track_is_context_not_signal_mapping': True,
            'track_id': mark.get('source_track_id'), 'movement_context': mark.get('movement'),
        })
    overlaps = []
    for i, first in enumerate(rows):
        for second in rows[i+1:]:
            a = max(first['range_ms'][0], second['range_ms'][0])
            b = min(first['range_ms'][1], second['range_ms'][1])
            if a < b:
                overlaps.append({'ids': [first['id'],second['id']], 'range_ms': [a,b],
                                 'duration_s': (b-a)/1000, 'interpretation': 'REQUIRES_REVIEW_not_automatically_invalid'})
    return {'validation': validation, 'source_manifest_identity_match': True,
            'counts_by_kind': dict(Counter(m['kind'] for m in review['annotations'])),
            'intervals': rows, 'overlaps': overlaps,
            'group_to_physical_event_mapping': 'AWAITING_OPERATOR_CLARIFICATION',
            'yellow': 'user explicitly ignored; unannotated, not zero-duration',
            'window_edges': 'not automatically signal transitions',
            'signal_timing_uncertainty_ms': None, 'independent_sync_verified': False,
            'phase_inference_runs': 0, 'model_accuracy_evaluated': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review',type=Path,required=True)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    raw = args.review.read_bytes()
    report = inspect(json.loads(raw),json.loads(args.manifest.read_text(encoding='utf-8')))
    report['review_sha256'] = hashlib.sha256(raw).hexdigest()
    report['sample_manifest_sha256'] = hashlib.sha256(args.manifest.read_bytes()).hexdigest()
    if args.out.exists():
        raise ValueError('fresh output directory required')
    args.out.mkdir(parents=True)
    (args.out/'calibration_tracks_review.json').write_bytes(raw)
    (args.out/'intake.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'annotations':len(report['intervals']),'overlaps':len(report['overlaps']),
                      'source_match':True,'physical_event_mapping':'AWAITING_CLARIFICATION'}))


if __name__ == '__main__':
    main()
