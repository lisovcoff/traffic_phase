"""Unit-independent observed motion restart; never a physical GREEN label."""
from dataclasses import replace
import math
import statistics


def restart_from_raw_speed(detections,crossing_ms):
    points=[]
    for d in detections:
        t,v=d.get('millis'),d.get('speed')
        if isinstance(t,(int,float)) and isinstance(v,(int,float)) and not isinstance(t,bool) and not isinstance(v,bool) and math.isfinite(t) and math.isfinite(v) and v>=0:
            points.append((float(t),float(v)))
    points.sort();positive=[v for t,v in points if v>0]
    if len(points)<8 or not positive:return None
    reference=sorted(positive)[int(.75*(len(positive)-1))]
    start=last=None;candidates=[]
    for i,(t,v) in enumerate(points):
        if last is not None and t-last>2000:start=None
        if v==0:
            if start is None:start=t
        elif start is not None:
            if last-start>=1500 and t<crossing_ms:
                tail=[(u,w) for u,w in points[i:] if u<=min(t+2500,crossing_ms)]
                continuous=all(b[0]-a[0]<=2000 for a,b in zip(tail,tail[1:]))
                if len(tail)>=4 and tail[-1][0]-t>=600 and continuous and statistics.median(w for u,w in tail)>=.08*reference:
                    candidates.append(dict(timestamp_ms=t,interval_ms=[last,t],stationary_s=(last-start)/1000))
            start=None
        last=t
    return candidates[-1] if candidates else None


def extract_motion_evidence(track,*,source_name='records'):
    from app.core.v9.vehicle_evidence import extract_vehicle_evidence,clean_detections
    events,stats=extract_vehicle_evidence(track,source_name=source_name)
    crossing=next((e for e in events if e.event_type=='CROSSING_PROXY' and e.provenance.get('eligible_proxy')),None)
    if crossing is None or stats.get('invalid_detections') or stats.get('conflicting_timestamps'):return events,stats
    detections,_=clean_detections(track)
    motion=restart_from_raw_speed(detections,crossing.timestamp_ms)
    if motion is None:return events,stats
    event=replace(crossing,timestamp_ms=motion['timestamp_ms'],event_type='RELEASE',
        evidence_method='observed_raw_speed_restart',confidence=.75,evidence_quality='MEDIUM',
        temporal_uncertainty_ms=motion['interval_ms'][1]-motion['interval_ms'][0],
        provenance={**crossing.provenance,'role':'observed_vehicle_restart_NOT_GREEN',
            'observation_interval_ms':motion['interval_ms'],'stationary_duration_s':motion['stationary_s'],
            'speed_units_required':False,'lamp_timing_uncertainty_ms':None})
    stats={**stats,'observed_raw_motion_restarts':1}
    return sorted([e for e in events if e.event_type!='RELEASE']+[event],key=lambda e:e.timestamp_ms),stats
