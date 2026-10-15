"""Read saved, sealed predictions only; descriptive diagnostics, no fitting."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path

from scripts.offline_benchmark import sha256_file, write_json
from app.core.v9.signal_renderer import build_signal_model, signal_state_at


def summarize(root):
    report = json.loads((root/'comparison.json').read_text(encoding='utf-8'))
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    rows, diagnostics, events = [], [], []
    for result, entry in zip(report['rows'],manifest['sessions']):
        if result['status'] != 'ok':
            diagnostics.append({'source':result['source'],'status':result['status']})
            continue
        path = root/result['prediction']
        assert sha256_file(path) == result['prediction_sha256']
        prediction = json.loads(path.read_text(encoding='utf-8'))
        adapter = json.loads((root/entry['adapter']).read_text(encoding='utf-8'))
        start,end = adapter['window_ms']
        selection = prediction['phase_model_selection']
        quality = prediction['event_extraction']['quality_diagnostics']
        selected = [prediction['event_extraction']['temporal_events'][i] for i in quality['selected_event_indices']]
        local = [e for e in selected if start <= e['timestamp_ms'] < end]
        all_local = [e for e in prediction['event_extraction']['temporal_events'] if start <= e['timestamp_ms'] < end]
        eligible_local = [e for e in all_local if e['event_type']=='CROSSING_PROXY'
            and e['provenance'].get('eligible_proxy') and not e['provenance'].get('invalid_detections')
            and not e['provenance'].get('conflicting_timestamps')]
        for e in local:
            events.append({'source': result['source'], 'relative_s': (e['timestamp_ms']-start)/1000,
                'timestamp_ms':e['timestamp_ms'], 'movement':e['movement'], 'type':e['event_type'],
                'method':e['evidence_method'], 'track_id':e['source_track_id'],
                'fingerprint':e['provenance'].get('track_fingerprint'),
                'semantics':'vehicle proxy, not lamp switch'})
        model=build_signal_model(prediction)
        unknown=0
        for t in range(180):
            q=signal_state_at(model,(start-prediction['schedule_base_timestamp_ms'])/1000+t)
            unknown+=q['physical_section']['estimated_state']=='UNKNOWN'
            assert all(s['state']=='UNKNOWN' for s in q['streams'])
        bounds=model.logical_query.segments
        outside=[signal_state_at(model,t)['logical_phase']['estimated_state']
                 for t in (bounds[0][0]-1,bounds[-1][1])]
        assert outside==['UNKNOWN','UNKNOWN']
        diagnostics.append({'source':result['source'],
            'phase_search':selection['search'],
            'unsupported_phases':selection['selected_candidate_after_redundancy']['unsupported_phase_count'],
            'selected_event_count_full':len(selected), 'selected_event_count_window':len(local),
            'window_ms':[start,end], 'events_by_movement_window':dict(Counter(e['movement'] for e in local)),
            'all_event_type_counts_window':dict(Counter(e['event_type'] for e in all_local)),
            'eligible_crossing_proxies_by_movement_window':dict(Counter(e['movement'] for e in eligible_local)),
            'selection_methods_full_session':quality['selection_by_movement'],
            'methods_window':dict(Counter(e['evidence_method'] for e in local)),
            'decoder_metadata':prediction['schedule']['decoder'],
            'period_inference':prediction['period_inference'],
            'regime_detection':prediction['regime_detection'],
            'manual_marks_used_for_discovery':prediction['event_extraction']['manual_marks_used_for_discovery'],
            'physical_unknown_queries':unknown,'physical_query_count':180,
            'out_of_history_logical_states':outside,
            'limitation':'counts/period mismatch do not identify signal cause or calibrate vehicle delay'})
        metrics=result['metrics']
        for field,h in metrics['histories'].items():
            rows.append({'source':result['source'],'history':field,
                'K':metrics['phase_count']['value'],'operator_K':metrics['phase_count']['operator_groups'],
                'period_s':metrics['period_absolute_error_s']['predicted_s'],
                'expert_recurrence_s':metrics['period_absolute_error_s']['expert_recurrence_median_s'],
                'recurrence_n':metrics['period_absolute_error_s']['n_observations'],
                'matched':h['matched'],'truth':h['truth'],'predicted':h['predicted'],
                **{key:h[key]['value'] for key in ('precision','recall','matched_mae_s','matched_p95_s','nearest_mae_s','temporal_coverage')},
                'runtime_s':result['runtime_s'], 'evaluated_candidates':selection['search']['evaluated_candidate_count'],
                'search_status':selection['search']['search_status']})
        assert sha256_file(path) == result['prediction_sha256']
    for name,values in [('summary.csv',rows),('selected_events_in_review_window.csv',events)]:
        if values:
            with (root/name).open('w',encoding='utf-8',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(values[0]));writer.writeheader();writer.writerows(values)
    write_json(root/'saved_prediction_diagnostics.json',{'script_sha256':sha256_file(Path(__file__)),
        'comparison_sha256':sha256_file(root/'comparison.json'), 'new_inference_runs':0,
        'description':'post-evaluation descriptive diagnostics; no rules or parameters selected', 'rows':diagnostics})
    for row in rows: print(row)
    for d in diagnostics: print(d['source'],'local events',d.get('selected_event_count_window'),'unsupported',d.get('unsupported_phases'))


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    summarize(p.parse_args().out)
