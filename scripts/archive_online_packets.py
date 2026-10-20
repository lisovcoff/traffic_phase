"""Bounded-memory conversion of trajectory ZIP/JSON to causal arrival packets.

This replay driver sorts observations on disk. zone_out and other completed-track
metadata never enter packets. Source namespaces are kept separate explicitly.
"""
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import sqlite3

from app.core.v9.events import _iter_source_records


def prepare(source,spool,output,on_progress=None):
    source,spool,output=map(Path,(source,spool,output))
    if spool.exists() or output.exists():raise ValueError('use new spool and output paths')
    spool.parent.mkdir(parents=True,exist_ok=True);output.parent.mkdir(parents=True,exist_ok=True)
    counts=Counter();members=[]
    with sqlite3.connect(spool) as db:
        db.execute('CREATE TABLE observations (arrival INTEGER, vehicle TEXT, origin TEXT, millis INTEGER, payload TEXT, PRIMARY KEY(arrival,vehicle,millis)) WITHOUT ROWID')
        for member,records in _iter_source_records(source):
            current=Counter()
            for track in records:
                current['tracks']+=1
                origin=str(track.get('zone_in','')).replace('_','').strip().upper()
                ds=track.get('detections') or []
                valid=[d for d in ds if isinstance(d,dict) and isinstance(d.get('millis'),(int,float)) and not isinstance(d['millis'],bool) and math.isfinite(d['millis']) and d['millis']>=0 and int(d['millis'])==d['millis']]
                current['invalid_timestamps']+=len(ds)-len(valid)
                if origin not in 'NSEW' or len(origin)!=1:
                    current['invalid_origin_tracks']+=1;continue
                if not valid:continue
                start=min(int(d['millis']) for d in valid)
                identity=member+':'+str(track.get('id'))+':'+str(start)
                for d in valid:
                    millis=int(d['millis']);arrival=((millis+999)//1000)*1000
                    value={k:d[k] for k in ('centroid_x','centroid_y','speed','zone','lat','lng') if k in d}
                    value['millis']=millis
                    for key in ('centroid_x','centroid_y','speed','lat','lng'):
                        number=value.get(key)
                        if number is not None and (isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number)):
                            raise ValueError('invalid '+key+' in '+identity)
                    payload=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
                    cursor=db.execute('INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?)',(arrival,identity,origin,millis,payload))
                    if not cursor.rowcount:
                        old=db.execute('SELECT payload,origin FROM observations WHERE arrival=? AND vehicle=? AND millis=?',(arrival,identity,millis)).fetchone()
                        if old!=(payload,origin):raise ValueError('conflicting duplicate detection in '+identity)
                        current['duplicate_detections']+=1
                    else:current['detections']+=1
            db.commit();members.append(dict(member=member,counts=dict(current)));counts.update(current)
            if on_progress:on_progress(members[-1])
        first,last=db.execute('SELECT MIN(arrival),MAX(arrival) FROM observations').fetchone()
        if first is None:raise ValueError('no usable detections')
        rows=iter(db.execute('SELECT arrival,vehicle,origin,payload FROM observations ORDER BY arrival,vehicle,millis'))
        groups=iter(itertools.groupby(rows,key=lambda r:r[0]));pending=next(groups,None);digest=hashlib.sha256();packet_count=0
        with output.open('xb') as stream:
            for sequence,timestamp in enumerate(range(first,last+1,1000)):
                vehicles=[]
                if pending and pending[0]==timestamp:
                    for identity,observations in itertools.groupby(pending[1],key=lambda r:r[1]):
                        ds=[];origin=None
                        for _,_,origin,payload in observations:ds.append(json.loads(payload))
                        vehicles.append(dict(id=identity,zone_in=origin,detections=ds))
                    pending=next(groups,None)
                packet=dict(sequence=sequence,timestamp_ms=timestamp,vehicles=vehicles)
                line=(json.dumps(packet,separators=(',',':'),allow_nan=False)+'\n').encode()
                stream.write(line);digest.update(line);packet_count+=1
    return dict(source=str(source.resolve()),members=members,counts=dict(counts),packets=packet_count,
        first_ms=first,last_ms=last,sha256=digest.hexdigest(),output=str(output.resolve()),
        future_fields=False,vehicle_identity='source-member + raw ID + first observed timestamp; no association across file namespaces')


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path,help='Original trajectory JSON or ZIP')
    parser.add_argument('--spool',required=True,type=Path,help='New temporary SQLite path; retained after conversion')
    parser.add_argument('--output',required=True,type=Path,help='New per-second JSONL path')
    args=parser.parse_args()
    result=prepare(args.source,args.spool,args.output,
                   on_progress=lambda member:print(json.dumps(member,ensure_ascii=True),flush=True))
    print(json.dumps(result,indent=2,ensure_ascii=True))
