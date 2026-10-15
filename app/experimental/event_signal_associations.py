"""Descriptive offsets to supplied video references, never causal lamp delays.

Extraction must be sealed before this component receives video reference data.
No cycle assignment, nearest-onset matching, state fill, confidence weighting or
model fitting is performed. Shared clock uncertainty is retained as conditional.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math

from app.core.temporal_evidence import TemporalEvent
from app.experimental.local_evidence import build_local_evidence


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _interval(pair):
    if not isinstance(pair,(list,tuple)) or len(pair)!=2 or not all(_finite(x) for x in pair) or pair[1]<pair[0]:
        raise ValueError('FINITE_ORDERED_INTERVAL_REQUIRED')
    return pair


def associate(events, profile, references):
    lo,hi=_interval(profile['validated_media_extent_s'])
    if hi<=lo:raise ValueError('POSITIVE_VIDEO_EXTENT_REQUIRED')
    origin=profile['origin_ms'];delta=profile['delta_s']
    if not all(_finite(x) for x in (origin,delta)):raise ValueError('FINITE_CLOCK_REQUIRED')
    sets=[_interval(pair) for pair in profile['conditional_delta_sets_s']]
    if not sets:raise ValueError('NO_CONDITIONAL_CLOCK_SUPPORT')
    if any(a[1]>b[0] for a,b in zip(sets,sets[1:])):raise ValueError('CLOCK_SETS_MUST_BE_ORDERED_DISJOINT')
    if not any(a<=delta<=b for a,b in sets):raise ValueError('CANDIDATE_CLOCK_OUTSIDE_DECLARED_SETS')
    fields=TemporalEvent.__dataclass_fields__
    temporal=[TemporalEvent(**{key:row[key] for key in fields}) for row in events]
    index=build_local_evidence(temporal,source_namespace='calibration-243-track-sample',exposure_windows=None)
    # Source timeline query covers the union of conditional clock mappings.
    window=index.query(origin+1000*(lo+sets[0][0]),origin+1000*(hi+sets[-1][1]))
    usable=[]
    unavailable_refs=[]
    for ref in references:
        a,b=_interval(ref['video_presentation_bracket_s'])
        if ref.get('status')=='OUTSIDE_LOCAL_CALIBRATION_EXTENT' or not lo<=a<=b<hi:
            unavailable_refs.append({'event':ref['event'],'reason':'OUTSIDE_LOCAL_CLOCK_EXTENT'})
        else:
            usable.append(ref)
    all_rows=[];pairs=[];strata=defaultdict(Counter)
    stop_groups={e['provenance'].get('track_fingerprint') for e in events if e['event_type']=='STOP' and e['provenance'].get('track_fingerprint')}
    for position,event in enumerate(events):
        relative=(event['timestamp_ms']-origin)/1000
        media_sets=[[relative-b,relative-a] for a,b in sets]
        wholly=all(lo<=a<=b<hi for a,b in media_sets)
        intersects=any(a<hi and b>=lo for a,b in media_sets)
        scope='INSIDE_FOR_ALL_CONDITIONAL_CLOCKS' if wholly else 'PARTIAL_CLOCK_CENSORING' if intersects else 'OUTSIDE_LOCAL_CLOCK_EXTENT'
        row={'event_index':event.get('event_index',position),'event_type':event['event_type'],
            'movement':event['movement'],'method':event['evidence_method'],
            'source_track_id':event['source_track_id'],'track_fingerprint':event['provenance'].get('track_fingerprint'),
            'timestamp_ms':event['timestamp_ms'],'candidate_media_s':relative-delta,
            'conditional_media_sets_s':media_sets,'clock_scope':scope,
            'selected_permission':bool(event.get('selected_permission',False)),
            'observed_stop_event_for_track':event['provenance'].get('track_fingerprint') in stop_groups,
            'vehicle_sampling_interval_ms':event['provenance'].get('observation_interval_ms'),
            'vehicle_localization_heuristic_radius_ms':event['temporal_uncertainty_ms'],
            'event_to_signal_uncertainty_ms':None,'physical_state':'UNKNOWN',
            'head_mapping_status':'UNCONFIRMED','calibrated_lamp_probability':None}
        all_rows.append(row)
        if not wholly:continue
        key=(row['movement'],row['event_type'],row['method'])
        strata[key]['events']+=1
        strata[key]['selected_permission']+=row['selected_permission']
        for ref in usable:
            a,b=ref['video_presentation_bracket_s']
            pairs.append({'event_index':row['event_index'],'source_track_id':row['source_track_id'],
                'movement':row['movement'],'event_type':row['event_type'],'method':row['method'],
                'selected_permission':row['selected_permission'],'reference_event':ref['event'],
                'reference_status':ref.get('original_event_status','sampled_appearance_transition'),
                'candidate_signed_offset_s':relative-delta-(a+b)/2,
                'conditional_offset_sets_s':[[relative-dhi-b,relative-dlo-a] for dlo,dhi in sets],
                'semantics':'association to specified reference only, not assigned reaction time or causal signal delay',
                'shared_clock_uncertainty':True,'vehicle_localization_uncertainty_added':False,
                'causal_delay_eligible':False,'abstention_reason':'HEAD_MAPPING_AND_EVENT_SIGNAL_RELATION_UNVERIFIED',
                'physical_state':'UNKNOWN','calibrated_lamp_probability':None})
    inside=[r for r in all_rows if r['clock_scope']=='INSIDE_FOR_ALL_CONDITIONAL_CLOCKS']
    chosen=[r for r in inside if r['selected_permission']]
    return {'schema':'event-video-associations-v1','events':all_rows,'associations':pairs,
        'counts':{'input_events':len(events),'clock_scope':dict(Counter(r['clock_scope'] for r in all_rows)),
            'inside_events_by_type':dict(Counter(r['event_type'] for r in inside)),
            'inside_selected_events_by_type':dict(Counter(r['event_type'] for r in chosen)),
            'inside_known_track_groups':len({r['track_fingerprint'] for r in inside if r['track_fingerprint']}),
            'inside_permission_track_groups':len({r['track_fingerprint'] for r in inside if r['track_fingerprint'] and r['event_type'] in {'RELEASE','CROSSING_PROXY','CROSSING'}}),
            'inside_association_rows':len(pairs),'supported_causal_delays':0,
            'inside_stop_supported_release_events':sum(r['event_type']=='RELEASE' and r['observed_stop_event_for_track'] for r in inside)},
        'strata':[{'movement':m,'event_type':t,'method':method,**counts} for (m,t,method),counts in sorted(strata.items())],
        'reference_count':len(usable),'unavailable_references':unavailable_refs,
        'local_evidence':window,'calibrated_delay_model':{'status':'UNAVAILABLE',
            'reason':'HEAD_MAPPING_AND_EVENT_SIGNAL_RELATION_UNVERIFIED','parameters':None},
        'assumptions':['clock sets condition on frozen geometry and supplied pixel allowance',
            'one reference is not automatically the signal controlling a movement',
            'event absence does not prove RED, no demand or camera gaps',
            'same-track events remain correlated and are not independent lamp observations',
            'vehicle localization radius is never a lamp-switch uncertainty interval'],
        'physical_state':'UNKNOWN','phase_inference_runs':0}
