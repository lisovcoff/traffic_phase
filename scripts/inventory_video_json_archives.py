"""Read every JSON record in the two video-linked ZIPs, without model fitting."""
import argparse
from collections import Counter
from datetime import datetime,timedelta,timezone
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile
from app.core.v9.events import _iter_json_records
from scripts.video_truth_inventory import ROOT,OUT,save

ARCHIVES={'sverdlovsky':'Ленина-Свердловский 27.02.25.zip',
          'enthusiasts':'Ленина-Энтузиастов 05.10.24.zip'}


class HashedReader(io.RawIOBase):
    def __init__(self,source):self.source=source;self.digest=hashlib.sha256();self.count=0
    def readable(self):return True
    def readinto(self,buffer):
        data=self.source.read(len(buffer));buffer[:len(data)]=data
        self.digest.update(data);self.count+=len(data);return len(data)


def text(ms):
    return datetime.fromtimestamp(ms/1000,timezone(timedelta(hours=5))).isoformat() if ms is not None else None


def main(site):
    archive=ROOT.parent/'data'/ARCHIVES[site];target=OUT/'archive_inventory'/site
    target.mkdir(parents=True,exist_ok=False);reports=[];began=time.monotonic()
    with zipfile.ZipFile(archive) as z:
        for name in sorted(z.namelist()):
            if not name.lower().endswith('.json'):continue
            info=z.getinfo(name);starts=[];ends=[];top=[];track_ids=[];categories=Counter();movements=Counter();detection_count=0
            with z.open(name) as raw:
                source=HashedReader(raw)
                with io.BufferedReader(source) as buffered:
                    for record in _iter_json_records(buffered):
                        detections=record.get('detections') or []
                        times=[int(d['millis']) for d in detections if d.get('millis') is not None]
                        if times:starts.append(min(times));ends.append(max(times))
                        detection_count+=len(detections);track_ids.append(record.get('id'))
                        if record.get('millis') is not None:top.append(int(record['millis']))
                        categories[str(record.get('category_name'))]+=1
                        movements[str(record.get('zone_in'))+'->'+str(record.get('zone_out'))]+=1
            assert source.count==info.file_size
            row=dict(member=name,uncompressed_bytes=source.count,json_sha256=source.digest.hexdigest(),
                crc32=f'{info.CRC:08x}',crc_checked_by_zipfile_read=True,tracks=len(track_ids),detections=detection_count,
                min_detection_ms=min(starts) if starts else None,max_detection_ms=max(ends) if ends else None,
                min_departure_ms=min(top) if top else None,max_departure_ms=max(top) if top else None,
                categories=dict(categories),movements=dict(movements),record_order_assumed_temporal=False)
            row.update(min_detection_utc5=text(row['min_detection_ms']),max_detection_utc5=text(row['max_detection_ms']))
            save(target/(Path(name).stem+'.json'),row);reports.append(row)
            print(json.dumps({k:row[k] for k in ('member','tracks','detections','min_detection_utc5','max_detection_utc5')},ensure_ascii=False),flush=True)
    start=min(r['min_detection_ms'] for r in reports if r['min_detection_ms'] is not None)
    end=max(r['max_detection_ms'] for r in reports if r['max_detection_ms'] is not None)
    save(target/'summary.json',dict(source=str(archive),archive_bytes=archive.stat().st_size,
        members=reports,total_tracks=sum(r['tracks'] for r in reports),total_detections=sum(r['detections'] for r in reports),
        detection_extent_ms=[start,end],detection_extent_utc5=[text(start),text(end)],
        elapsed_detection_s=(end-start)/1000,runtime_s=time.monotonic()-began,
        all_json_members_scanned=True,phase_models_run=False,json_video_clock_verified=False))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('site',choices=ARCHIVES)
    main(p.parse_args().site)
