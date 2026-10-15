"""Bounded raw-track extraction receipt. No annotation/reference input accepted."""
import argparse
import hashlib
import json
from pathlib import Path
import time

from app.core.v9.events import load_event_streams


def extract(source, plan, out):
    if out.exists():raise ValueError('FRESH_OUTPUT_REQUIRED')
    if source.stat().st_size>32*1024*1024:raise ValueError('SOURCE_BYTE_LIMIT')
    raw=source.read_bytes();tracks=json.loads(raw)
    if not isinstance(tracks,list) or any(not isinstance(t,dict) or 'detections' not in t for t in tracks):
        raise ValueError('ANNOTATION_OR_NON_TRACK_INPUT_FORBIDDEN')
    if len(tracks)>400:raise ValueError('TRACK_COUNT_LIMIT')
    started=time.monotonic()
    bundle=load_event_streams(source,_records=tracks)
    runtime=time.monotonic()-started
    if runtime>30 or len(bundle.temporal_events)>4000:raise ValueError('EXTRACTION_BUDGET_EXCEEDED')
    selected=set(bundle.diagnostics['selected_event_indices'])
    events=[{**e.to_dict(),'event_index':i,'selected_permission':i in selected} for i,e in enumerate(bundle.temporal_events)]
    data={'events':events,'selection_diagnostics':bundle.diagnostics,'runtime_s':runtime,
          'source_sha256':hashlib.sha256(raw).hexdigest()}
    encoded=(json.dumps(data,indent=2)+'\n').encode()
    files=['app/core/v9/events.py','app/core/v9/vehicle_evidence.py',
           'app/core/temporal_evidence.py','app/core/trajectory_events.py']
    seal={'vehicle_events_sha256':hashlib.sha256(encoded).hexdigest(),
          'plan_sha256':hashlib.sha256(plan.read_bytes()).hexdigest(),
          'signal_references_not_loaded':True,
          'producer_files_sha256':{p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in files}}
    out.mkdir(parents=True)
    (out/'vehicle_events.json').write_bytes(encoded)
    (out/'extraction_seal.json').write_text(json.dumps(seal,indent=2)+'\n',encoding='utf-8')
    return seal


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(extract(args.source,args.plan,args.out)))
