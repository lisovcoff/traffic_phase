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
