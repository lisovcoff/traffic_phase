"""One bounded stream scan for disjoint vehicle-review windows. No phase model."""
import hashlib
import json
import time

from app.core.calibration_sample import BudgetReader,valid_ms
from app.core.v9.events import _iter_json_records
from app.core.v9.primitives import norm_zone


def select_review_windows(stream,windows,excluded_ids,*,max_bytes=300*1024*1024,
                          max_output_bytes=32*1024*1024,max_tracks=400,max_seconds=60):
    ranges=[w['json_range_ms'] for w in windows]
    if not ranges or any(not(valid_ms(a) and valid_ms(b) and a<b) for a,b in ranges):
        raise ValueError('INVALID_REVIEW_WINDOWS')
    if ranges!=sorted(ranges) or any(b>c for (a,b),(c,d) in zip(ranges,ranges[1:])):
        raise ValueError('OVERLAPPING_OR_UNSORTED_WINDOWS')
    start=time.monotonic()
    reader=BudgetReader(stream,max_bytes=max_bytes,deadline=start+max_seconds)
    selected=[];excluded=[];seen=set();size=0;count=0
    for index,record in enumerate(_iter_json_records(reader)):
        count+=1
        if norm_zone(record.get('zone_in'))!='N':
            continue
        ds=record.get('detections') or []
        if not isinstance(ds,list):
            continue
        hits=[i for i,(a,b) in enumerate(ranges) if any(
            isinstance(d,dict) and valid_ms(d.get('millis')) and a<=d['millis']<b for d in ds)]
        if not hits:
            continue
        encoded=json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
        digest=hashlib.sha256(encoded).hexdigest()
        lineage=dict(source_record_index=index,track_id=record.get('id'),
                     canonical_record_sha256=digest,window_indices=hits)
        if record.get('id') in excluded_ids or len(hits)!=1:
            excluded.append({**lineage,'reason':'PRIOR_REVIEW_ID' if record.get('id') in excluded_ids else 'CROSS_WINDOW_TRACK'})
            continue
        if record.get('id') in seen:
            raise ValueError('DUPLICATE_SOURCE_TRACK_ID_REQUIRES_REVIEW')
        seen.add(record.get('id'));size+=len(encoded)
        if len(selected)>=max_tracks or size>max_output_bytes:
            raise ValueError('OUTPUT_BUDGET_EXHAUSTED')
        selected.append(dict(record=record,lineage=lineage))
    if not reader.eof:
        raise ValueError('INCOMPLETE_SOURCE_SCAN')
    return selected,dict(input_bytes_read=reader.bytes_read,complete_entry_sha256=reader.sha.hexdigest(),
        source_records=count,selected_records=len(selected),excluded=excluded,
        runtime_s=time.monotonic()-start,complete_entry_scanned=True)
