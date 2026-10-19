"""Replay driver only: expose detections at their arrival second, no future fields."""
import math
from collections import defaultdict


def packets_from_tracks(tracks,*,start_ms=None,end_ms=None):
    buckets=defaultdict(lambda:defaultdict(list));origins={}
    for track in tracks:
        key=str(track['id']);origin=track.get('zone_in')
        if key in origins and origins[key]!=origin:raise ValueError('conflicting track ID origins')
        origins[key]=origin
        for d in track.get('detections',[]):
            timestamp=int(d['millis']);second=int(math.ceil(timestamp/1000)*1000)
            if start_ms is not None and second<start_ms:continue
            if end_ms is not None and second>end_ms:continue
            buckets[second][key].append({k:d.get(k) for k in ('millis','centroid_x','centroid_y','speed','zone','lat','lng')})
    if not buckets:return
    first=min(buckets) if start_ms is None else int(math.ceil(start_ms/1000)*1000)
    last=max(buckets) if end_ms is None else int(math.floor(end_ms/1000)*1000)
    for sequence,second in enumerate(range(first,last+1,1000)):
        yield dict(sequence=sequence,timestamp_ms=second,vehicles=[dict(id=key,zone_in=origins[key],
            detections=sorted(ds,key=lambda d:d['millis'])) for key,ds in sorted(buckets[second].items())])
