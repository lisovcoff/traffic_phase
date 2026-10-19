"""Derive a new project from saved fits; originals and frozen outputs stay intact."""
from copy import deepcopy
from pathlib import Path
import shutil
import uuid


def enrich(folder):
    from app.core.intersection_project import read_model,write_json,model_fingerprint,digest
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
