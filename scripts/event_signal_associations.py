"""Join already sealed vehicle events to explicit video evidence, without fitting."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from app.experimental.event_signal_associations import associate


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--events',type=Path,required=True)
    p.add_argument('--seal',type=Path,required=True)
    p.add_argument('--profile',type=Path,required=True)
    p.add_argument('--references',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise ValueError('FRESH_OUTPUT_REQUIRED')
    raw=a.events.read_bytes();seal=json.loads(a.seal.read_text())
    if hashlib.sha256(raw).hexdigest()!=seal['vehicle_events_sha256']:
        raise ValueError('SEALED_EVENT_HASH_MISMATCH')
    extracted=json.loads(raw)
    profile=json.loads(a.profile.read_text())
    refs=json.loads(a.references.read_text())
    if refs['alignment_profile_sha256']!=hashlib.sha256(a.profile.read_bytes()).hexdigest():
        raise ValueError('REFERENCE_CLOCK_PROFILE_HASH_MISMATCH')
    result=associate(extracted['events'],profile,refs['events'])
    result['input_sha256']={name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in
                           [('events',a.events),('seal',a.seal),('profile',a.profile),('references',a.references)]}
    a.out.mkdir(parents=True)
    (a.out/'associations.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    with (a.out/'event_offsets.csv').open('w',encoding='utf-8',newline='') as stream:
        names=['event_index','source_track_id','movement','event_type','method','selected_permission',
               'reference_event','candidate_signed_offset_s','conditional_offset_sets_s','causal_delay_eligible']
        writer=csv.DictWriter(stream,fieldnames=names);writer.writeheader()
        for row in result['associations']:
            writer.writerow({key:json.dumps(row[key]) if isinstance(row[key],list) else row[key] for key in names})
    print(json.dumps(result['counts'],indent=2))


if __name__=='__main__':main()
