"""Require full delivery of all marks reachable by a finite observation model.

Query selection acts on reported timestamps, not on true detection time. This
guard rejects incomplete delivery instead of changing the observation kernel.
It does NOT establish camera availability, track validity or population coverage.
"""
import math


def require_complete_query(view, *, horizon_s, windows, channels,
                           error_type=ValueError, resolution_ms=None,
                           rounding_origin_ms=None,finite_clock=None):
    """channels=(name, shifts_s, detection_probability); all inputs validated.

    Rounded: include every clock centre whose cell overlaps a reachable camera
    interval with positive measure. Finite clock: exact discrete reachable marks.
    A half-open query must include the rightmost reported centre itself.
    """
    query=view.get('range_ms')
    def fail(reason,details=None):
        exc=error_type(reason)
        exc.observation_domain=details or {}
        raise exc
    if (not isinstance(query,(list,tuple)) or len(query)!=2 or any(
            isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in query)
            or query[1]<=query[0]):
        fail('QUERY_TIMESTAMP_DOMAIN_REQUIRED')
    report=dict(query_range_ms=list(query),selection_clock='reported_timestamp',
        validation='finite_population_reachable_marks_NOT_camera_or_demand_verification',
        upstream_event_delivery='ASSUMED_WITHIN_SUPPLIED_INDEX_NOT_VERIFIED_FROM_RAW_DATA',
        required_channel_ranges_ms=[],complete=True)
    for name,shifts,probability in channels:
        if probability==0:continue
        for shift in sorted(set(shifts)):
            for a,b in windows:
                if resolution_ms is None:
                    # Clock comes from the existing backend, not independent defaults.
                    offset,step,n=finite_clock
                    offset+=shift*1000
                    jlo=max(0,math.ceil((a*1000-offset)/step))
                    jhi=min(n-1,math.ceil((b*1000-offset)/step)-1)
                    if jhi<jlo:continue
                    first,last=offset+jlo*step,offset+jhi*step
                else:
                    lo=max(a,shift)*1000;hi=min(b,horizon_s+shift)*1000
                    if hi<=lo:continue
                    half=resolution_ms/2
                    # Cell [c-half,c+half) intersects [lo,hi) iff
                    # lo-half < c < hi+half (zero-mass ties irrelevant).
                    jlo=math.floor((lo-half-rounding_origin_ms)/resolution_ms)+1
                    jhi=math.ceil((hi+half-rounding_origin_ms)/resolution_ms)-1
                    if jhi<jlo:continue
                    first=rounding_origin_ms+jlo*resolution_ms
                    last=rounding_origin_ms+jhi*resolution_ms
                report['required_channel_ranges_ms'].append(dict(channel=name,
                    first_reported_ms=first,last_reported_ms=last))
                if not query[0]<=first or not last<query[1]:report['complete']=False
    if not report['complete']:fail('QUERY_DOMAIN_INCOMPLETE',report)
    for row in view.get('events',[]):
        ts=row['event']['timestamp_ms']
        if not query[0]<=ts<query[1]:fail('EVENT_OUTSIDE_QUERY_DOMAIN',report)
    return report


def censored_query_windows(view,windows,*,resolution_ms,rounding_origin_ms,error_type=ValueError):
    """Exact true-time preimage of retained rounded centres, then camera censoring.

    Rounding ties have zero mass under the continuous latent model. Supplied
    windows remain physical camera windows; the intersection is a delivery
    selection model, not an assertion that the camera stopped observing.
    """
    checked=require_complete_query(view,horizon_s=0,windows=[],channels=[],error_type=error_type)
    lo,hi=checked['query_range_ms'];r=resolution_ms;o=rounding_origin_ms
    try:
        first=o+math.ceil((lo-o)/r)*r
        last=o+(math.ceil((hi-o)/r)-1)*r
    except (OverflowError,ValueError):
        raise error_type('ROUNDING_QUERY_DOMAIN_NUMERIC_LIMIT') from None
    if not math.isfinite(first) or not math.isfinite(last):
        raise error_type('ROUNDING_QUERY_DOMAIN_NUMERIC_LIMIT')
    effective=[];retained=None
    if first<=last:
        a=(first-r/2)/1000;b=(last+r/2)/1000
        retained=[a,b]
        effective=[[max(x,a),min(y,b)] for x,y in windows if max(x,a)<min(y,b)]
    return effective,dict(delivery_mode='censored_reported_timestamps',
        query_range_ms=[lo,hi],retained_clock_centres_ms=[first,last] if first<=last else [],
        retained_true_mark_interval_s=retained,effective_observation_windows_s=effective,
        supplied_camera_windows_s=[list(w) for w in windows],
        upstream_event_delivery=checked['upstream_event_delivery'],
        semantics='exact query selection under supplied rounding model; not physical camera exposure')
