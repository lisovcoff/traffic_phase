"""Read-only follow-up to user's independent identification of W -> _W crash car."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.v9.events import _iter_source_records
from app.core.intersection_project import read_json,digest

OUT=ROOT/'evidence/coherent_signal_20261020/video_link'
LOCAL=ROOT/'.web_runtime/coherent_signal_20261020/uturn_candidates'


def main():
    source=read_json(ROOT/'evidence/enthusiasts_crash_20261020/raw_candidates.json')['archive']
    OUT.mkdir(parents=True,exist_ok=False);LOCAL.mkdir(parents=True,exist_ok=False)
    rows=[];count=0
    for member,records in _iter_source_records(source):
        for t in records:
            count+=1;ds=t.get('detections',[])
            if t.get('zone_in')!='W' or not ds:continue
            start=min(d['millis'] for d in ds);end=max(d['millis'] for d in ds)
            if t.get('zone_out')!='_W' and end-start<90000:continue
            name=member.removesuffix('.json')+'_'+str(t['id'])+'.json';save(LOCAL/name,t)
            sample=ds[::max(1,len(ds)//30)]
            rows.append(dict(member=member,id=t['id'],category=t.get('category_name'),origin='W',target=t.get('zone_out'),
                start_ms=start,end_ms=end,duration_s=(end-start)/1000,stay_ms=t.get('stay_duration_millis'),
                samples=[dict(millis=d['millis'],x=d['centroid_x'],y=d['centroid_y'],speed=d.get('speed')) for d in sample],
                raw_copy=str((LOCAL/name).relative_to(ROOT)),sha256=digest(LOCAL/name)))
        print('READ',member,'candidates',len(rows),flush=True)
    save(OUT/'uturn_inventory.json',dict(user_identification='W -> _W',tracks_read=count,candidates=rows,
        candidate_8341='NOT_ACCEPTED: source origin E disagrees with user W; no relabeling of raw input',
        video_clock_accepted=False,signal_predictions_used=False))
    print('UTURNS',[(r['id'],r['start_ms'],r['duration_s']) for r in rows if r['target']=='_W'],flush=True)


if __name__=='__main__':main()
