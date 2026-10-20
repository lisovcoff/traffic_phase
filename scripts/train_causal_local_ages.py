"""Train confirmation-age profiles on earlier offline members, never video truth."""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
import argparse
from bisect import bisect_right
from collections import Counter
from copy import deepcopy
import gzip
import json
from pathlib import Path
import shutil
import time
import zipfile
import numpy as np
from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from app.core.intersection_project import read_json,read_model,digest,model_fingerprint,operating_template
from app.core.observed_topology import project_observed_topology
from app.core.intersection_local_emissions import LocalAgeCounts
from app.experimental.intersection_local_filter import LocalObservationSource

OUT=ROOT/'evidence/local_observation_age_20261020/v1'
LOCAL=ROOT/'.web_runtime/local_observation_age_20261020/v1'
PARENT='44ae19132cc145758452d13b3eab55d3'
SOURCES=['app/core/intersection_local_emissions.py','app/experimental/intersection_local_filter.py',
         'app/core/intersection_signal_filter.py','app/core/intersection_queue_observations.py',
         'app/core/intersection_signal_smoothing.py','app/core/intersection_online.py',
         'scripts/train_causal_local_ages.py']


def phase_history(model_folder,session,approaches,projection_version):
    p=model_folder/session['prediction'];assert digest(p)==session['prediction_sha256']
    with gzip.open(p,'rt',encoding='utf8') as f:result=json.load(f)
    template=operating_template(project_observed_topology(result,approaches,repair_missing_phases=(
        'selective' if projection_version=='observed-topology-v3' else projection_version=='observed-topology-v2')))
    return template['schedule']['raw_hsmm_segments'],result.get('schedule_base_timestamp_ms',result['analysis_base_timestamp_ms'])


def fit_packets(model,regime,member,segments,base,packets):
    counts=LocalAgeCounts(model['approaches'],regime['phase_count']);source=LocalObservationSource(model)
    starts=[s[0] for s in segments];lags=[];emitted=Counter();bounds=[]
    for n,packet in enumerate(packets,1):
        now=packet['timestamp_ms'];_,local,legacy,marks,delays=source.ingest(packet);lags.extend(v for a,v in delays)
        bounds.append(now);second=(now-base)/1000;ix=bisect_right(starts,second)-1
        if ix<0:continue
        a,b,z=segments[ix]
        if not a<=second<b:continue
        phase=member['phase_mapping'][str(int(z))]
        for kind,origin in marks:counts.add(kind,origin,phase,(second-a)/(b-a));emitted[kind]+=1
    return counts.finish(),dict(packets=n,first_ms=min(bounds),last_ms=max(bounds),marks=dict(emitted),
        confirmed_restart_samples=len(lags),confirmation_delay_quantiles_ms=np.quantile(lags,[0,.5,.9,.99,1]).tolist() if lags else [])


def seal():
    OUT.mkdir(parents=True,exist_ok=False);LOCAL.mkdir(parents=True,exist_ok=False)
    model=read_model(ROOT/'logs/intersection_projects'/PARENT)
    sessions={s['session_id']:s for s in model['sessions']};chosen=[]
    for i,r in enumerate(model['regimes']):
        member=r['members'][0];session=sessions[member['session_id']]
        chosen.append(dict(index=i,regime_id=r['regime_id'],member=member,session=session))
    save(OUT/'protocol.json',dict(source_sha256={p:digest(ROOT/p) for p in SOURCES},parent=PARENT,
        chosen=chosen,queue_reference='previous offline February12-only geometry; frozen unchanged',
        expected_geometry_model_sha256=digest(ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json'),
        training_timing='causal packet confirmation age, aligned to frozen trajectory phase histories',
        label_scope='logical trajectory fits, NOT physical lamp/reaction latency',
        video_or_test_day_supplied_to_training=False,production_enabled=False))
    print('SEALED',len(chosen),'representative earlier regime members',flush=True)


def train(index):
    from scripts.archive_online_packets import prepare
    protocol=read_json(OUT/'protocol.json');assert all(digest(ROOT/p)==sha for p,sha in protocol['source_sha256'].items())
    model=read_model(ROOT/'logs/intersection_projects'/PARENT);chosen=protocol['chosen'][index]
    r=model['regimes'][index];session=chosen['session'];runtime=LOCAL/f'train_{index}';runtime.mkdir(exist_ok=False)
    source=Path(model['input_path_private']);path=runtime/'source.json'
    with zipfile.ZipFile(source) as z,z.open(session['source_member']) as f,path.open('xb') as dst:shutil.copyfileobj(f,dst,4*1024**2)
    geometry=read_json(ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')
    assert digest(ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')==protocol['expected_geometry_model_sha256']
    model['queue_observations']=geometry['queue_observations']
    segments,base=phase_history(ROOT/'logs/intersection_projects'/PARENT,session,model['approaches'],model['projection_version'])
    manifest=prepare(path,runtime/'packets.sqlite3',runtime/'packets.jsonl')
    began=time.monotonic()
    with (runtime/'packets.jsonl').open() as f:
        profile,stats=fit_packets(model,r,chosen['member'],segments,base,(json.loads(line) for line in f))
    assert all(digest(ROOT/p)==sha for p,sha in protocol['source_sha256'].items())
    save(OUT/f'train_{index}.json',dict(regime_id=r['regime_id'],source_member=session['source_member'],
        raw_sha256=digest(path),prediction_sha256=session['prediction_sha256'],packet_manifest=manifest,
        profile=profile,stats=stats,runtime_s=time.monotonic()-began))
    print('TRAIN',index,r['regime_id'],stats,flush=True)


def combine():
    p=read_json(OUT/'protocol.json');assert all(digest(ROOT/n)==h for n,h in p['source_sha256'].items())
    model=deepcopy(read_json(ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json'))
    assert digest(ROOT/'.web_runtime/coherent_signal_20261020/v5/model.json')==p['expected_geometry_model_sha256']
    latest=0
    for i,r in enumerate(model['regimes']):
        learned=read_json(OUT/f'train_{i}.json');assert learned['regime_id']==r['regime_id']
        r['causal_local_emissions']=learned['profile'];latest=max(latest,learned['stats']['last_ms'])
    assert latest<read_json(ROOT/'evidence/incident_validation_20261020/baseline_packets.json')['first_ms']
    model['fingerprint']=model_fingerprint(model);save(LOCAL/'model.json',model)
    save(OUT/'model_receipt.json',dict(sha256=digest(LOCAL/'model.json'),latest_training_ms=latest,
        model_fingerprint=model['fingerprint'],training_regimes=len(model['regimes']),physical_color_labels_used=False))
    print('COMBINED',len(model['regimes']),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['seal','train','combine']);p.add_argument('--index',type=int)
    a=p.parse_args();seal() if a.action=='seal' else combine() if a.action=='combine' else train(a.index)
