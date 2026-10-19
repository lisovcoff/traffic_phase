"""Create a new model from checksum-verified fitted sessions; never edit an old model."""
from copy import deepcopy
import gzip
import json
import shutil
import uuid

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_model,operating_template,build_catalogue,model_fingerprint,digest,write_json
from app.core.observed_topology import project_observed_topology
from app.core.intersection_age_prior import attach_age_priors


def rebuild(identifier,receipt_path=None):
    old=ROOT/'logs/intersection_projects'/identifier;original=read_model(old)
    model=deepcopy(original);folder=old.parent/uuid.uuid4().hex;folder.mkdir(parents=True)
    predictions=[];changes=[]
    for session in model['sessions']:
        source=old/session['prediction'];sha=digest(source)
        assert sha==session.get('prediction_sha256',sha)
        destination=folder/session['prediction'];destination.parent.mkdir(exist_ok=True);shutil.copyfile(source,destination)
        with gzip.open(source,'rt',encoding='utf8') as stream:result=json.load(stream)
        template=operating_template(project_observed_topology(result,model['approaches'],repair_missing_phases='selective'))
        changes.append(dict(session_id=session['session_id'],old_K=session.get('phase_count'),
            new_K=template['schedule']['phase_count'],raw_prediction_sha256=sha))
        session.update(phase_count=template['schedule']['phase_count'],state_basis=template['state_basis'])
        predictions.append((session['session_id'],template))
    model.update(model_id=folder.name,regimes=build_catalogue(predictions),projection_version='observed-topology-v3')
    by_session={m['session_id']:r['regime_id'] for r in model['regimes'] for m in r['members']}
    for s in model['sessions']:s['regime_id']=by_session[s['session_id']]
    attach_age_priors(model,folder);model['fingerprint']=model_fingerprint(model)
    write_json(folder/'model.json',model)
    write_json(folder/'status.json',dict(status='READY',stage='finished',model_id=folder.name,
        input_name=model.get('input',{}).get('name','verified fitted sessions'),model_fingerprint=model['fingerprint']))
    if receipt_path:save(receipt_path,dict(old_model_id=identifier,model_id=folder.name,changes=changes,
        semantics='fresh projection/catalogue/age-priors from unchanged hash-verified fitted sessions; no numerical refit; originals preserved'))
    return model


if __name__=='__main__':
    import sys
    print(rebuild(sys.argv[1],sys.argv[2] if len(sys.argv)>2 else None)['model_id'],flush=True)
