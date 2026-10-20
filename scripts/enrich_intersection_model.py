"""Fork a saved offline project with automatically learned queue references.

Original model, streams and source bytes are preserved. Only that model's own
offline input may train the fork; online recordings and labels are not accepted.
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import shutil
import uuid
import math

from app.core.intersection_project import read_model,read_json,write_json,digest,model_fingerprint
from app.core.intersection_queue_observations import IntersectionQueueLearner
from app.core.v9.events import _iter_source_records


def link_or_copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    try:os.link(source,target)
    except OSError:
        with source.open('rb') as incoming,target.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)


def enrich(original,destination=None,*,max_tracks=20000):
    if destination is None:return enrich_saved_fits(original)
    original,destination=Path(original).resolve(),Path(destination).resolve()
    if max_tracks<1:raise ValueError('positive offline training budget required')
    if destination.exists():raise FileExistsError(destination)
    model=read_model(original);source=Path(model['input_path_private'])
    if digest(source)!=model['input']['sha256']:raise ValueError('offline source hash mismatch')
    before=model_fingerprint(model);learner=IntersectionQueueLearner();count=0;members=[];lo=hi=None
    inventory={r['source_member'] for r in model['source_inventory'] if r['status'] in ('READY','PARTIAL')}
    # Use archive ordering, never label/video time or a filename-selected site.
    for member in sorted(inventory):
        records=_iter_source_records(source,source_member=member)
        try:
            for _,rows in records:
                members.append(member)
                for track in rows:
                    learner.add(track);count+=1
                    for d in track.get('detections',[]):
                        if isinstance(d,dict) and type(d.get('millis')) in (int,float) and math.isfinite(d['millis']):
                            t=d['millis'];lo=t if lo is None else min(lo,t);hi=t if hi is None else max(hi,t)
                    if count>=max_tracks:break
                if count>=max_tracks:break
        finally:records.close()
        if count>=max_tracks:break
    learned=learner.finish(model['regimes'])
    if not learned['references']:raise ValueError('No supported queue front in the bounded offline sample')
    destination.mkdir(parents=True,exist_ok=False)
    learned['training']=dict(method='bounded_offline_source_prefix',records=count,max_records=max_tracks,
        source_sha256=model['input']['sha256'],source_members=members,
        sampled_timestamp_extent_ms=[lo,hi],lamp_labels_used=False,online_recording_used=False)
    target_source=destination/('input'+source.suffix.lower())
    link_or_copy(source,target_source)
    for session in model['sessions']:
        relative=Path(session['prediction']);old=(original/relative).resolve()
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('unsafe stored asset path')
        if not old.is_relative_to(original):raise ValueError('unsafe stored asset path')
        if digest(old)!=session['prediction_sha256']:raise ValueError('offline prediction hash mismatch')
        target=destination/relative
        if not target.exists():link_or_copy(old,target)
    result=deepcopy(model)
    result.update(model_id=destination.name,input_path_private=str(target_source),queue_observations=learned)
    result['fingerprint']=model_fingerprint(result)
    write_json(destination/'model.json',result)
    state=read_json(original/'status.json')
    state.update(model_id=result['model_id'],model_fingerprint=result['fingerprint'],stage='finished',
                 queue_reference_upgrade=dict(parent_model_id=model['model_id'],parent_fingerprint=before))
    write_json(destination/'status.json',state)
    return dict(model_id=result['model_id'],parent_model_id=model['model_id'],references=sorted(learned['references']),
                offline_tracks=count,model_fingerprint=result['fingerprint'],original_model_preserved=read_model(original)['fingerprint']==before)


def enrich_saved_fits(folder):
    """Preserve the existing age-prior enrichment API used by audit scripts."""
    from app.core.intersection_age_prior import attach_age_priors
    from app.api.intersection_projects import PROJECT_ROOT
    folder=Path(folder);model=deepcopy(read_model(folder));parent=model['fingerprint']
    destination=PROJECT_ROOT/uuid.uuid4().hex;destination.mkdir(parents=True)
    source=Path(model['input_path_private']);target=destination/('input'+source.suffix)
    shutil.copyfile(source,target)
    assert digest(target)==model['input']['sha256']
    for session in model['sessions']:
        to=destination/session['prediction'];to.parent.mkdir(exist_ok=True)
        shutil.copyfile(folder/session['prediction'],to)
    model.update(model_id=destination.name,input_path_private=str(target),offline_parent_fingerprint=parent)
    attach_age_priors(model,destination);model['fingerprint']=model_fingerprint(model)
    write_json(destination/'model.json',model)
    write_json(destination/'status.json',dict(status='READY',stage='finished',model_id=model['model_id'],
        sources_total=model['input']['source_count'],sources_done=model['input']['source_count'],sessions_done=len(model['sessions']),
        sources=model['source_inventory'],derivation='saved offline fits plus trajectory restart age histograms; no refit'))
    return model,destination


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original',type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--max-tracks',type=int,default=20000)
    args=parser.parse_args()
    print(json.dumps(enrich(args.original,args.output,max_tracks=args.max_tracks),indent=2),flush=True)
