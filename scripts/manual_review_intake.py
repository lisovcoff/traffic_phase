"""Read-only intake of operator phase intervals; no inference or evaluation."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.core.annotation_workbench import validate_review


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(path):
    payload = json.loads(path.read_text(encoding='utf-8-sig'))
    validation = validate_review(payload)
    source = path.parent / Path(payload['source']['name']).name
    source_hash = digest(source)
    lo = payload['source']['timestamp_origin_ms']
    window = payload['display']['preview_window_ms']
    marks = payload['annotations']
    rows = []
    overlaps = []
    gaps = []
    for i, mark in enumerate(marks):
        a, b = mark['interval_start_ms'], mark['interval_end_ms']
        rows.append({'id': mark['id'], 'label': mark['label'],
                     'start_relative_s': (a-lo)/1000, 'end_relative_s': (b-lo)/1000,
                     'duration_s': (b-a)/1000,
                     'start_at_window_edge': a == lo+window[0],
                     'end_at_window_edge': b == lo+window[1],
                     'selected_track_movement_context_only': mark.get('movement')})
        if i:
            delta = a-marks[i-1]['interval_end_ms']
            if delta < 0:
                overlaps.append({'previous_id': marks[i-1]['id'], 'next_id': mark['id'], 'ms': -delta})
            if delta > 0:
                gaps.append({'previous_id': marks[i-1]['id'], 'next_id': mark['id'], 'ms': delta})
    # Union duration, retaining contradictory overlaps separately. This is labelled
    # time, not camera coverage or physical-state accuracy.
    union_ms = 0
    last = None
    for a, b in sorted((m['interval_start_ms'], m['interval_end_ms']) for m in marks):
        union_ms += max(0, b-max(a, last if last is not None else a))
        last = max(b, last if last is not None else b)
    return {
        'review_file': path.name, 'review_sha256': digest(path),
        'source_file': source.name, 'source_sha256_actual': source_hash,
        'source_hash_matches': source_hash == payload['source']['sha256'],
        'source_bytes_match': source.stat().st_size == payload['source']['bytes'],
        'validation': validation, 'intersection_knowledge': payload['intersection_knowledge'],
        'session_role': payload['session_role'], 'timezone': 'Asia/Yekaterinburg',
        'window_start_local': datetime.fromtimestamp((lo+window[0])/1000, timezone(timedelta(hours=5))).isoformat(),
        'window_end_local': datetime.fromtimestamp((lo+window[1])/1000, timezone(timedelta(hours=5))).isoformat(),
        'sorted_by_start': all(marks[i]['interval_start_ms'] <= marks[i+1]['interval_start_ms'] for i in range(len(marks)-1)),
        'duplicate_intervals': sum(n-1 for n in Counter((m['label'], m['interval_start_ms'], m['interval_end_ms']) for m in marks).values()),
        'overlaps': overlaps, 'gaps_between_labels': gaps,
        'labelled_union_s': union_ms/1000,
        'unlabelled_window_s': (window[1]-window[0]-union_ms)/1000,
        'window_s': (window[1]-window[0])/1000, 'intervals': rows,
        'uncertainty_fields_in_original': dict(Counter(str(m.get('vehicle_timing_uncertainty_ms')) for m in marks)),
        'trajectory_time_extent_reparsed': False,
        'track_fingerprints_revalidated': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    files = sorted(args.data.glob('*_review.json'))
    if len(files) != 3:
        raise ValueError('This intake expects exactly the three supplied reviews')
    results = [inspect(p) for p in files]
    report = {
        'schema': 'manual-phase-intake-v1',
        'inference_or_benchmark_run': False,
        'operator_confirmation': '2026-10-15: intervals denote the full duration of group activity, not boundary uncertainty brackets',
        'operator_timing_claim': {'maximum_error_ms': 2000, 'basis': 'driver reaction and onsite intersection knowledge',
                                  'independently_verified': False, 'applies_to': 'phase boundaries, not vehicle sampling'},
        'operator_density_report': {'enthusiasts': 'sparse', 'other_two': 'adequate per operator'},
        'physical_lamp_accuracy': None,
        'edge_policy': 'Window endpoints are censored/ambiguous, not confirmed switches; no gap fill or overlap repair',
        'selected_track_policy': 'A selected car is UI context, not a mapping of the entire phase',
        'files': results,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for path in files:
        (args.output/path.name).write_bytes(path.read_bytes())
    (args.output/'intake.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    for r in results:
        print(r['source_file'], 'hash=', r['source_hash_matches'], 'valid=', r['validation']['valid'],
              'intervals=', len(r['intervals']), 'labelled_s=', r['labelled_union_s'], 'overlaps=', r['overlaps'])
    if not all(r['source_hash_matches'] and r['source_bytes_match'] for r in results):
        raise SystemExit('SOURCE MISMATCH')


if __name__ == '__main__':
    main()
