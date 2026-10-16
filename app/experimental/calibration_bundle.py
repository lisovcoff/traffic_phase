"""Preparation of existing reviews only; no model, fit, offset or truth expansion.

Video appearance, operator reports and vehicle proxies are separate record kinds.
All materials are development/calibration candidates from one capture.
"""
from copy import deepcopy
import hashlib
import json
import math

VERSION = 'calibration-evidence-bundle-v1'


def _interval(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(isinstance(x, bool) or not isinstance(x, (int, float))
                   or not math.isfinite(x) for x in value)
            or value[0] < 0 or value[1] <= value[0]):
        raise ValueError('INVALID_OBSERVATION_INTERVAL')
    return list(value)


def build_bundle(sources):
    """sources is a named snapshot of saved JSON documents, never predictions."""
    records = []

    def add(kind, source, pointer, **fields):
        identity = f'{source}#{pointer}'
        records.append(dict(record_id=hashlib.sha256(identity.encode()).hexdigest(), kind=kind,
            source_key=source, source_pointer=pointer, capture_id='len-sverdl-2025-02-27',
            split='development_calibration_candidate', independent_validation=False,
            calibrated_lamp_probability=None, **deepcopy(fields)))

    for index, row in enumerate(sources['direct_video']['transitions']):
        bracket = _interval(row['video_presentation_bracket_s'])
        # Before/after decoded frame timestamps must actually support the bracket.
        if [row['before_frame']['actual_media_time_s'], row['after_frame']['actual_media_time_s']] != bracket:
            raise ValueError('FRAME_BRACKET_MISMATCH')
        status = row.get('status', 'sampled_appearance_change')
        add('sampled_signal_appearance', 'direct_video', f'/transitions/{index}',
            head_id='H1', event=row['event'], media_interval_s=bracket,
            interval_semantics='sampled decoded appearance_NOT_calibrated_lamp_switch_interval',
            trajectory_timestamp_ms=None, physical_switch_uncertainty_ms=None,
            before_appearance=row['before_appearance'], after_appearance=row['after_appearance'],
            review_status='single_reviewer_NOT_independently_cross_reviewed',
            interpretation_status=status,
            certified_final_off=False,
            continuous_state_truth=False, reviewer=row.get('reviewer'),
            frame_references=[row['before_frame'], row['after_frame']])

    head_refs = {}
    visual = sources['vehicle_video']
    for index, row in enumerate(visual['head_references']):
        window = row['window']
        if window in head_refs:
            raise ValueError('DUPLICATE_HEAD_REFERENCE_WINDOW')
        head_refs[window] = _interval(row['media_bracket_s'])
        add('sampled_signal_appearance', 'vehicle_video', f'/head_references/{index}',
            head_id=row['head_id'], window=window, event=row['observed_change'],
            media_interval_s=head_refs[window], trajectory_timestamp_ms=None,
            interval_semantics='sampled decoded appearance_NOT_calibrated_lamp_switch_interval',
            physical_switch_uncertainty_ms=None, continuous_state_truth=False,
            review_status='single_reviewer_NOT_independently_cross_reviewed',
            interpretation_status='sampled_appearance_change', certified_final_off=False,
            frame_references=row['frames'])

    video_ids = set()
    for index, row in enumerate(visual['rows']):
        window, track = row['window'], row['track_id_hypothesis']
        key = (window, track)
        if key in video_ids:
            raise ValueError('DUPLICATE_VEHICLE_VIDEO_RECORD')
        video_ids.add(key)
        onset = _interval(row['observed_onset_bracket_s'])
        green = head_refs.get(window)
        relation = ([onset[0]-green[1], onset[1]-green[0]] if green else None)
        add('sampled_vehicle_motion', 'vehicle_video', f'/rows/{index}', window=window,
            track_id_hypothesis=track, identity_status=row['identity_status'],
            media_interval_s=onset, interval_semantics=visual['boundary_semantics'],
            frame_references=row['frames'], visibility=row.get('visibility'),
            vehicle_onset_minus_H1_appearance_s=relation,
            wholly_before_H1_appearance=bool(green and onset[1] < green[0]),
            relation_semantics='same-video association_NOT_causal_delay_or_calibrated_error',
            calibrated_vehicle_timing_uncertainty_ms=None, trajectory_timestamp_ms=None)

    for index, row in enumerate(sources['operator']['events']):
        add('operator_interval_report', 'operator', f'/events/{index}',
            annotation_id=row['annotation_id'], group=row['group'],
            claimed_start_event=row['claimed_start_event'], certainty=row['certainty'],
            annotated_interval_ms=_interval(row['interval_ms']),
            start_switch_verified=False, end_switch_asserted=False, continuous_state_truth=False,
            derived_media_interval_s=_interval(row['derived_media_interval_s']),
            media_binding_status='historical_unverified_operator_binding_NOT_clock_calibration',
            correction=row['correction'])

    proxy_ids=set()
    for window, query in sorted(sources['proxy_queries']['queries'].items()):
        for index, row in enumerate(query['events']):
            if row['event_id'] in proxy_ids:
                raise ValueError('DUPLICATE_PROXY_EVENT_ID')
            proxy_ids.add(row['event_id'])
            event = row['event']
            t = event['timestamp_ms']
            if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
                raise ValueError('INVALID_PROXY_TIMESTAMP')
            add('vehicle_event_proxy', 'proxy_queries', f'/queries/{window}/events/{index}',
                window=window, source_event_id=row['event_id'],
                vehicle_group_id=row['vehicle_group_id'], original_event=event,
                matching_video_identity_hypothesis=(window, event['source_track_id']) in video_ids,
                independent_vehicle_truth=False, lamp_switch_observation=False)

    if len(records) > 512:
        raise ValueError('CALIBRATION_RECORD_BUDGET_EXCEEDED')
    clock = sources['clock_candidate']
    # Never turn a successful optimizer or frozen-H interval into calibrated sync.
    if clock.get('sync_certified') is not False or clock.get('calibrated_sync_uncertainty_ms') is not None:
        raise ValueError('CLOCK_SCHEMA_CHANGED_REQUIRES_EXPLICIT_REVIEW')
    counts = {kind:sum(r['kind']==kind for r in records) for kind in sorted({r['kind'] for r in records})}
    return dict(schema=VERSION, records=records, counts=counts,
        capture_count=1, validation_session_count=0, inference_performed=False,
        accepted_clock_transform=None, accepted_duration_prior=None, accepted_vehicle_signal_delay=None,
        clock_candidate={key:deepcopy(clock.get(key)) for key in
                         ('origin_ms','delta_s','sync_certified','calibrated_sync_uncertainty_ms','production_usable')},
        clock_candidate_semantics='diagnostic_only; timestamp_ms=origin_ms+1000*(media_s+delta_s)',
        continuous_lamp_truth_intervals=[], intersection_phase_truth=None,
        raw_movement_permission_mapping=None, assumptions=deepcopy(sources['mapping']),
        blockers=['CALIBRATED_JSON_VIDEO_SYNC_UNAVAILABLE','NO_COMPLETE_INTERSECTION_PHASE_TRUTH',
                  'RAW_MOVEMENT_PERMISSION_MAPPING_UNCONFIRMED','NO_CONTINUOUS_LAMP_TRUTH',
                  'NO_INDEPENDENT_VALIDATION_SESSION','NO_INDEPENDENT_EXTENSION_EPISODE_LABELS'],
        same_video_motion_before_H1_count=sum(r.get('wholly_before_H1_appearance',False) for r in records),
        release_status='NOT_ACCEPTED; stage2D1 remains FAIL')
