"""Experimental vehicle-event alignment, estimated from same-track event pairs.

Restart preceding observed output-zone transition is a model assumption, not
verified stop-line geometry. Aligned times are estimates with explicit provenance.
"""
from collections import defaultdict
from types import SimpleNamespace
import statistics


def aligned_event_channels(events):
    tracks=defaultdict(dict)
    for event in events:
        fp=event.provenance.get('track_fingerprint')
        if not fp:continue
        key=(event.provenance.get('source',''),fp,event.movement)
        if event.event_type=='RELEASE' and event.evidence_quality!='LOW':
            tracks[key]['release']=event
        elif (event.event_type=='CROSSING_PROXY' and event.provenance.get('eligible_proxy')
              and not event.provenance.get('invalid_detections')
              and not event.provenance.get('conflicting_timestamps')):
            tracks[key]['crossing']=event
    pairs=defaultdict(list);invalid=defaultdict(int)
    for (source,fp,movement),record in tracks.items():
        if 'release' in record and 'crossing' in record:
            delta=(record['crossing'].timestamp_ms-record['release'].timestamp_ms)/1000.
            if delta>=0:pairs[source,movement].append(delta)
            else:invalid[source,movement]+=1
    estimates={key:statistics.median(values) for key,values in pairs.items() if len(values)>=5}
    selected=[];excluded=0;rejected=0;methods=defaultdict(int)
    for (source,fp,movement),record in sorted(tracks.items()):
        release,crossing=record.get('release'),record.get('crossing')
        if release and crossing and release.timestamp_ms>crossing.timestamp_ms:
            release=None;rejected+=1
        if release:
            timestamp=release.timestamp_ms;actual=release;method='own_supported_restart'
        elif crossing and (source,movement) in estimates:
            timestamp=crossing.timestamp_ms-estimates[source,movement]*1000.
            actual=crossing;method='paired_vehicle_relative_alignment'
        else:
            excluded+=1;continue
        if timestamp<0:
            excluded+=1;continue
        methods[method]+=1
        selected.append(SimpleNamespace(timestamp_ms=timestamp,movement=movement,
            event_type='COMMON_VEHICLE_PROXY',source_track_id=actual.source_track_id,
            provenance={**actual.provenance,'actual_observation_timestamp_ms':actual.timestamp_ms,
                'actual_observation_kind':actual.event_type,'alignment_method':method}))
    selected.sort(key=lambda e:(e.timestamp_ms,e.movement,str(e.source_track_id)))
    diagnostic=dict(method='same_vehicle_nonnegative_restart_to_zone_delay_median',
        minimum_pairs=5,manual_marks_used=False,physical_delay_calibrated=False,
        causal_restart_assumption='intersection-relevant restart precedes output-zone transition',
        rejected_post_zone_restarts=rejected,excluded_unaligned_tracks=excluded,
        observation_methods=dict(methods),delay_estimates=[dict(source=key[0],movement=key[1],
            median_s=value,pairs=len(pairs[key]),negative_pairs=invalid[key]) for key,value in sorted(estimates.items())],
        aligned_observations=[dict(timestamp_ms=e.timestamp_ms,movement=e.movement,
            source_track_id=e.source_track_id,actual_observation_timestamp_ms=e.provenance['actual_observation_timestamp_ms'],
            actual_observation_kind=e.provenance['actual_observation_kind'],method=e.provenance['alignment_method']) for e in selected])
    return selected,sorted({(e.movement,e.event_type) for e in selected}),diagnostic
