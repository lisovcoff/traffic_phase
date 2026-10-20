"""Gather all already-fitted offline intervals; preserve original fit files."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from collections import defaultdict
from copy import deepcopy
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,model_fingerprint
from app.core.intersection_duration_learning import duration_law
from scripts.train_causal_local_ages import phase_history,PARENT,OUT,LOCAL


def attach(model,folder):
    sessions={s['session_id']:s for s in model['sessions']};durations=defaultdict(list);sources=[]
    for r in model['regimes']:
        for member in r['members']:
            session=sessions[member['session_id']]
            segments,_=phase_history(folder,session,model['approaches'],model['projection_version'])
            sources.append(dict(session_id=session['session_id'],sha256=session['prediction_sha256']))
            for a,b,z in segments[1:-1]:
                phase=member['phase_mapping'][str(int(z))];durations[r['regime_id'],phase].append(b-a)
        r['causal_duration_laws']=[duration_law(durations[r['regime_id'],z]) for z in range(r['phase_count'])]
    model['fingerprint']=model_fingerprint(model)
    return sources


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--k',type=int);a=p.parse_args()
    if a.k:
        source=LOCAL/'synthetic'/f'k{a.k}_model.json';model=deepcopy(read_json(source));folder=ROOT/'logs/intersection_projects'/model['model_id']
        out=OUT/'duration_v1/synthetic';runtime=LOCAL/'duration_v1/synthetic';filename=f'k{a.k}_model.json'
    else:
        model=deepcopy(read_json(LOCAL/'model.json'));folder=ROOT/'logs/intersection_projects'/PARENT
        out=OUT/'duration_v1';runtime=LOCAL/'duration_v1';filename='model.json'
    out.mkdir(parents=True,exist_ok=True);runtime.mkdir(parents=True,exist_ok=True)
    sources=attach(model,folder);save(runtime/filename,model)
    save(out/(filename.removesuffix('.json')+'_duration_laws.json'),dict(sources=sources,
        laws={r['regime_id']:r['causal_duration_laws'] for r in model['regimes']},physical_lamp_labels_used=False))
    print('DURATION LAWS',a.k or 'real',len(sources),flush=True)
