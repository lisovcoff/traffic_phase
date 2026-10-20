"""Read-only raw candidate inventory for the video incident identified by user."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.v9.events import _iter_source_records
from app.core.intersection_project import read_json

OUT=ROOT/'evidence/enthusiasts_crash_20261020'
LOCAL=ROOT/'.web_runtime/enthusiasts_crash_20261020'


def main():
    jobs=read_json(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')['jobs']
    source=next(j['path'] for j in jobs if j['id']=='0094')
    OUT.mkdir(parents=True,exist_ok=True);LOCAL.mkdir(parents=True,exist_ok=True)
    counts=Counter();long=[];motor=[];buses=[]
    for member,records in _iter_source_records(source):
        for t in records:
            category=str(t.get('category_name'));counts[category]+=1
            ds=t.get('detections') or []
            if not ds:continue
            ds=sorted(ds,key=lambda d:d['millis']);start,end=ds[0]['millis'],ds[-1]['millis'];duration=(end-start)/1000
            row=dict(member=member,id=t['id'],category=category,origin=t.get('zone_in'),target=t.get('zone_out'),
                start_ms=start,end_ms=end,duration_s=duration,stay_ms=t.get('stay_duration_millis'),detections=len(ds),
                first_xy=[ds[0].get('centroid_x'),ds[0].get('centroid_y')],last_xy=[ds[-1].get('centroid_x'),ds[-1].get('centroid_y')])
            if duration>=120:long.append(row)
            if t['id']==8341 and member=='6_2025_2_23_15.json':
                save(LOCAL/'candidates/8341.json',t)
            if any(s in category.lower() for s in ('moto','bike','cycle')):
                motor.append(row)
                save(LOCAL/'motor'/f'{member}_{t["id"]}.json',t)
            if category=='bus':buses.append(dict(member=member,track=t))
        print('READ',member,dict(counts),flush=True)
    save(LOCAL/'bus_tracks.json',buses)
    save(OUT/'raw_candidates.json',dict(archive=source,categories=dict(counts),
        long_tracks=sorted(long,key=lambda x:x['duration_s'],reverse=True),motorcycle_candidates=motor,
        video_user_clock='05.10.2024 13:03:50',video_pts_approx_s=3832,
        clock_alignment_accepted=False,bus_id_confirmed=False,
        scope='read-only candidates, no phase fit or signal accuracy claim'))
    print('LONGEST',sorted(long,key=lambda x:x['duration_s'],reverse=True)[:12],flush=True)
    print('MOTOR',motor,flush=True)


if __name__=='__main__':main()
