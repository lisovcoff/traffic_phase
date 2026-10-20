"""Read-only incident search in raw tracks; no phase/light inference."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.v9.events import _iter_source_records
from app.core.intersection_project import read_json
from scripts.check_incident_counterfactual import OUT


def main():
    jobs=read_json(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')['jobs']
    archive=next(j['path'] for j in jobs if j['id']=='0094');found=[];counts=Counter()
    for member,records in _iter_source_records(archive):
        for track in records:
            counts['tracks']+=1
            if track.get('category_name')!='bus':continue
            ds=track.get('detections') or []
            if not ds:continue
            ds=sorted(ds,key=lambda d:d['millis']);first=ds[0]['millis'];last=ds[-1]['millis']
            stopped=[d for d in ds if d.get('speed') is not None and d['speed']<=1]
            run=[];longest=[]
            for d in ds:
                if d.get('speed') is not None and d['speed']<=1:
                    if run and d['millis']-run[-1]['millis']>2000:run=[]
                    run.append(d)
                    if run[-1]['millis']-run[0]['millis']>(longest[-1]['millis']-longest[0]['millis'] if longest else 0):longest=list(run)
                else:run=[]
            middle=longest[len(longest)//2] if longest else {}
            found.append(dict(member=member,id=track['id'],origin=track.get('zone_in'),target=track.get('zone_out'),
                detections=len(ds),first_ms=first,last_ms=last,duration_s=(last-first)/1000,
                longest_near_stop_s=(longest[-1]['millis']-longest[0]['millis'])/1000 if longest else 0,
                near_stop_interval_ms=[longest[0]['millis'],longest[-1]['millis']] if longest else None,
                near_stop_xy=[middle.get('centroid_x'),middle.get('centroid_y')],
                vendor_stay_duration_ms=track.get('stay_duration_millis')))
        print('SCANNED',member,'buses',len(found),flush=True)
    found.sort(key=lambda x:x['longest_near_stop_s'],reverse=True)
    save(OUT/'enthusiasts_bus_search.json',dict(archive=archive,counts=dict(counts),buses=found,
        semantics='vehicle detection category/speed only; bus-stop and signal queues are not certified accidents',
        video_clock_not_inferred=True))
    print(found[:12],flush=True)


if __name__=='__main__':main()
