"""Bounded raw-track sampling for independent review; no signal inference."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import time

from app.core.v9.events import _iter_json_records


def valid_ms(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0 and value==int(value)


class BudgetReader:
    def __init__(self,stream,*,max_bytes,deadline):
        self.stream=stream;self.max_bytes=max_bytes;self.deadline=deadline
        self.bytes_read=0;self.sha=hashlib.sha256();self.eof=False

    def read(self,n):
        if time.monotonic()>self.deadline: raise ValueError('INPUT_TIME_BUDGET_EXCEEDED')
        if self.bytes_read>=self.max_bytes: raise ValueError('INPUT_BYTE_BUDGET_EXCEEDED')
        raw=self.stream.read(min(n,self.max_bytes-self.bytes_read))
        self.bytes_read+=len(raw);self.sha.update(raw)
        if not raw:self.eof=True
        return raw


def select_raw_window(stream,start_ms,end_ms,*,max_input_bytes=300*1024*1024,
                      max_output_bytes=32*1024*1024,max_tracks=400,max_seconds=60):
    if not valid_ms(start_ms) or not valid_ms(end_ms) or end_ms<=start_ms:
        raise ValueError('valid integer-ms half-open review interval required')
    if any(isinstance(x,bool) or not isinstance(x,int) or x<=0 for x in (max_input_bytes,max_output_bytes,max_tracks)):
        raise ValueError('positive resource limits required')
    if not isinstance(max_seconds,(int,float)) or isinstance(max_seconds,bool) or not math.isfinite(max_seconds) or max_seconds<=0:
        raise ValueError('positive time limit required')
    started=time.monotonic();deadline=started+max_seconds
    reader=BudgetReader(stream,max_bytes=max_input_bytes,deadline=deadline)
    selected=[];lineage=[];stats=Counter();size=2
    for source_index,track in enumerate(_iter_json_records(reader)):
        stats['source_records']+=1
        ds=track.get('detections') or []
        if not isinstance(ds,list): stats['invalid_detection_lists']+=1;continue
        inside=[d for d in ds if isinstance(d,dict) and valid_ms(d.get('millis')) and start_ms<=d['millis']<end_ms]
        if not inside:continue
        encoded=json.dumps(track,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
        size+=len(encoded)+1
        if size>max_output_bytes:raise ValueError('OUTPUT_BYTE_BUDGET_EXCEEDED')
        if len(selected)>=max_tracks:raise ValueError('OUTPUT_TRACK_BUDGET_EXCEEDED')
        selected.append(track)
        times=[d['millis'] for d in ds if isinstance(d,dict) and valid_ms(d.get('millis'))]
        lineage.append({'source_record_index':source_index,'source_track_id':track.get('id'),
            'canonical_raw_record_sha256':hashlib.sha256(encoded).hexdigest(),
            'fingerprint_algorithm':'sha256 JSON sorted keys, compact separators, UTF-8; not extractor track fingerprint',
            'full_track_range_ms':[min(times),max(times)],'detections_in_requested_window':len(inside),
            'track_copied_whole':True,'entry_endpoint_censoring_not_modified':True})
    if not reader.eof:raise ValueError('COMPLETE_INPUT_SCAN_REQUIRED')
    if time.monotonic()>deadline:raise ValueError('INPUT_TIME_BUDGET_EXCEEDED')
    if not selected:raise ValueError('NO_TRACKS_OBSERVED_IN_REQUESTED_WINDOW')
    times=[d['millis'] for r in selected for d in r['detections'] if isinstance(d,dict) and valid_ms(d.get('millis'))]
    origin=min(times)
    return selected,{'schema':'calibration-raw-window-v1','requested_range_ms':[start_ms,end_ms],
        'input_bytes_read':reader.bytes_read,'complete_entry_sha256':reader.sha.hexdigest(),
        'complete_entry_scanned':True,'selected_tracks':len(selected),'lineage':lineage,'stats':dict(stats),
        'sample_detection_extent_ms':[origin,max(times)],
        'recommended_preview_start_s':(start_ms-origin)/1000,'recommended_preview_duration_s':(end_ms-start_ms)/1000,
        'runtime_s':time.monotonic()-started,'inference_runs':0,
        'scope':'whole raw tracks with at least one actual detection inside window; no gap bridging, sorting or synthetic boundaries',
        'units':{'millis':'ms per input contract','coordinates':'UNKNOWN','speed':'UNKNOWN','durations':'supplier semantics unverified'},
        'geometry':'UNKNOWN; no stop-line inferred from zones'}
