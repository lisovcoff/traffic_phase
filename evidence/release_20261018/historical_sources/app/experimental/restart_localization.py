"""Opt-in localization of an EXISTING restart proxy on unsmoothed intervals.

Offline confirmation still uses later observations and a whole-track relative
speed threshold. This is NOT an online/causal detector or an observed STOP/GREEN.
No production selector or timestamp is modified; a separate result is returned.
"""
from dataclasses import replace
import inspect
import math

from scipy.ndimage import gaussian_filter1d

from app.core.state_contract import StateEstimate, physical_estimate
from app.core.temporal_evidence import TemporalEvent
from app.core.trajectory_geometry import _finite_number
from app.core.v9.events import _kinematic_release_candidate
from app.core.v9.vehicle_evidence import CONFIG, clean_detections, track_fingerprint


MAX_DETECTIONS = 20000  # resource limit, not a motion threshold


def localize_restart(track, event: TemporalEvent | None):
    source='experimental_raw_interval_restart_localization'
    assumptions=('relative_image_motion_NOT_absolute_stop',
                 'legacy_whole_track_threshold_and_seed_are_conditioning_assumptions',
                 'raw_interval_is_threshold_evidence_NOT_world_or_lamp_switch_interval')
    result=dict(status='unavailable',legacy_event=event.to_dict() if event else None,
                localized_event=None,alternatives=[],physical=physical_estimate('UNKNOWN').to_dict())

    def abstain(reason, **support):
        result['estimate']=StateEstimate('UNKNOWN','activity',source,assumptions,
            support,reason,{'production_default_changed':False}).to_dict()
        return result

    raw=track.get('detections') if isinstance(track,dict) else None
    if not isinstance(raw,list) or not raw:
        return abstain('NO_VEHICLE_OBSERVATIONS')
    if len(raw)>MAX_DETECTIONS:
        return abstain('DETECTION_RESOURCE_LIMIT',limit=MAX_DETECTIONS)
    ds,stats=clean_detections(track)
    if stats['conflicting_timestamps'] or stats['invalid_detections']:
        return abstain('INVALID_OR_CONFLICTING_OBSERVATIONS',**stats)
    if len(ds)<14:
        return abstain('INSUFFICIENT_VEHICLE_SAMPLES',detections=len(ds))
    if any(not _finite_number(d.get(k)) for d in ds for k in ['centroid_x','centroid_y']):
        return abstain('INVALID_IMAGE_COORDINATES')
    gaps=[b['millis']-a['millis'] for a,b in zip(ds,ds[1:])]
    if max(gaps)>CONFIG.max_detection_gap_s*1000:
        return abstain('OBSERVATION_GAP',max_gap_ms=max(gaps))
    if event is None:
        return abstain('NO_SELECTED_RESTART_PROXY')
    if event.evidence_method!='kinematic_restart_proxy':
        return abstain('UNSUPPORTED_RESTART_METHOD')
    fingerprint=track_fingerprint(track,ds)
    if event.source_track_id!=track.get('id') or event.provenance.get('track_fingerprint')!=fingerprint:
        return abstain('SOURCE_EVENT_TRACK_MISMATCH')
    diagnostics={}
    seed=_kinematic_release_candidate(ds,ds[0]['millis'],ds[-1]['millis'],diagnostics=diagnostics)
    if seed is None or not math.isclose(seed[1]*1000,event.timestamp_ms,abs_tol=.001,rel_tol=0):
        return abstain('LEGACY_CANDIDATE_MISMATCH')
    speeds=diagnostics['raw_image_speeds']
    threshold=diagnostics['relative_speed_threshold']
    width=diagnostics['confirmation_width_samples']
    multiplier=diagnostics['confirmation_multiplier']
    fraction=diagnostics['confirmation_fraction']
    # Same finite kernel support as the existing SciPy Gaussian default. It bounds
    # the seed's localization search, NOT temporal uncertainty or a confidence set.
    truncate=inspect.signature(gaussian_filter1d).parameters['truncate'].default
    radius=int(truncate*diagnostics['smoothing_sigma_samples']+.5)
    center=diagnostics['selected_seed_index']
    alternatives=[]
    for i in range(max(1,center-radius),min(len(speeds),center+radius+1)):
        if speeds[i-1]>threshold or speeds[i]<=threshold:
            continue
        after=speeds[i:i+width]
        if len(after)!=width:  # No fabricated confirmation in a clipped tail.
            continue
        supported=sum(v>threshold*multiplier for v in after)/width
        ordered=sorted(after)
        median=(ordered[(width-1)//2]+ordered[width//2])/2
        if supported<fraction or median<=threshold*multiplier:
            continue
        alternatives.append(dict(timestamp_ms=ds[i+1]['millis'],
            observation_interval_ms=[ds[i]['millis'],ds[i+1]['millis']],
            preceding_low_interval_ms=[ds[i-1]['millis'],ds[i]['millis']],
            confirmation_interval_ms=[ds[i]['millis'],ds[i+width]['millis']],
            confirmation_raw_intervals=width,raw_high_fraction=supported))
    result['alternatives']=alternatives
    if len(alternatives)!=1:
        return abstain('MULTIPLE_RAW_TRANSITIONS' if alternatives else 'NO_SUPPORTED_RAW_TRANSITION',
                       alternative_count=len(alternatives),**stats)
    chosen=alternatives[0]
    localized=replace(event,timestamp_ms=float(chosen['timestamp_ms']),
        evidence_method='kinematic_restart_unsmoothed_interval_proxy',
        provenance={**event.provenance,**chosen,'legacy_timestamp_ms':event.timestamp_ms,
            'timing_localizer_version':1,'selection_unchanged':True,
            'threshold_origin':'unchanged_legacy_relative_image_speed_clustering',
            'relative_image_speed_threshold':threshold,
            'symmetric_smoothing_used_for_timestamp':False,
            'offline_future_confirmation_used':True,
            'observation_interval_semantics':'threshold_displacement_support_NOT_guaranteed_world_onset_interval',
            'uncertainty_reason':'raw_threshold_proxy_and_legacy_heuristic_radius_not_calibrated'})
    result.update(status='available_proxy',localized_event=localized.to_dict(),
        estimate=StateEstimate('RELATIVE_IMAGE_MOTION_TRANSITION','activity',source,assumptions,
            chosen,None,{'track_fingerprint':fingerprint,'production_default_changed':False}).to_dict())
    return result
