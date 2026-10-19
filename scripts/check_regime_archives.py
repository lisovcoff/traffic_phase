"""All-source sealed offline parity and held-member raw causal replay per archive.

Motion prediction scores are not lamp accuracy: these sites lack independent,
accepted signal/JSON clock labels. The replay member is excluded from training.
"""
import os
os.environ.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import time
import uuid
import zipfile

from scripts.corpus_validation import ROOT,prepare_worker_environment,save
prepare_worker_environment()
from scripts.check_regime_observations import OUT,RUNTIME,baseline_class
from app.core.intersection_project import read_json,digest,operating_template,build_catalogue,model_fingerprint,write_json,SCHEMA


def main():
    from app.core.observed_topology import project_observed_topology
    from app.core.intersection_age_prior import attach_age_priors
    from app.core.intersection_online import CausalIntersection
    from app.core.intersection_emissions import MovementMarks
    from scripts.verify_recovery_release import prediction_path
    from scripts.archive_online_packets import prepare
    sealed=read_json(ROOT/'evidence/accuracy_recovery_20261019/release_manifest.json')
    artifacts={r['path']:r for r in sealed['local_reproduction_files']+sealed['evidence_files']}
    guarded={r['path']:r['sha256_lf'] for r in sealed['source_files'] if r['path'].startswith('app/core/recovery/')}
    for name,sha in guarded.items():assert hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==sha,name
    jobs=read_json(ROOT/'evidence/all_archives_synthetic_20261019/inventory.json')['jobs'];archives={}
    for j in jobs:
        if j['member'] and j['site']!='lenina_sverdlovsky':archives.setdefault(j['path'],[]).append(j)
    assert len(archives)==4
    summary=[]
    for index,(path,jobs) in enumerate(sorted(archives.items())):
        out=OUT/'archives'/f'archive_{index}';out.mkdir(parents=True,exist_ok=False)
        runtime=RUNTIME/'archives'/f'archive_{index}';runtime.mkdir(parents=True,exist_ok=False)
        start=time.monotonic();predictions=[];checks=[];sessions=[]
        held=sorted(jobs,key=lambda j:j['member'])[0]
        folder=ROOT/'logs/intersection_projects'/uuid.uuid4().hex;folder.mkdir(parents=True)
        for j in jobs:
            key='real_'+j['id'];cached=prediction_path(key);relative=cached.relative_to(ROOT).as_posix();receipt=artifacts[relative]
            assert digest(cached)==receipt['sha256'] and cached.stat().st_size==receipt['bytes']
            parity=read_json(ROOT/'evidence/accuracy_recovery_20261019/production_parity'/(key+'.json'))
            assert parity['status']=='PASS' and all(parity['checks'].values())
            with gzip.open(cached,'rt',encoding='utf8') as stream:result=json.load(stream)
            template=operating_template(project_observed_topology(result,['N','S','E','W'],repair_missing_phases=True))
            checks.append(dict(id=j['id'],member=j['member'],prediction_sha256=receipt['sha256'],
                latent_K=result['schedule']['phase_count'],working_K=template['schedule']['phase_count'],
                period_s=result['schedule']['period_s'],offline_solver_guard='unchanged code + sealed production parity'))
            if j==held:continue
            sid=j['id'];destination=folder/'sessions'/(sid+'.json.gz');destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(cached,destination)
            predictions.append((sid,template));sessions.append(dict(session_id=sid,prediction=destination.relative_to(folder).as_posix()))
        model=dict(schema=SCHEMA,model_id=folder.name,approaches=['N','S','E','W'],geometries={},sessions=sessions,
            regimes=build_catalogue(predictions),projection_version='observed-topology-v2',
            validation_scope='sealed full-source offline fits, held member omitted; geometry rendering not under test')
        attach_age_priors(model,folder);model['fingerprint']=model_fingerprint(model);write_json(folder/'model.json',model)
        member_path=runtime/(held['id']+'.json')
        with zipfile.ZipFile(path) as archive,archive.open(held['member']) as source,member_path.open('xb') as target:
            shutil.copyfileobj(source,target,4*1024**2)
        ingest=read_json(ROOT/'evidence/all_archives_synthetic_20261019/ingest'/(held['id']+'.json'))
        assert digest(member_path)==ingest['sha256'],'held raw member changed'
        packets=prepare(member_path,runtime/'observations.sqlite3',runtime/'packets.jsonl')
        save(out/'packet_manifest.json',packets)
        engines=dict(baseline=baseline_class()(model),candidate=CausalIntersection(model));marks=MovementMarks(model['regimes'])
        nll=Counter();weights=Counter();modes={n:Counter() for n in engines};colors={n:Counter() for n in engines};seen={n:[] for n in engines}
        for name,engine in engines.items():
            def wrap(original,owner,name):
                def observe(events):
                    seen[name].extend(events)
                    for a,b,w in events:
                        p=sum(float(bank.sum(axis=1)@likelihood) for bank,likelihood in zip(owner.banks,marks.likelihoods(a,b)))
                        nll[name]-=w*math.log(max(1e-15,p));weights[name]+=w
                    return original(events)
                return observe
            engine._observe=wrap(engine._observe,engine,name)
        with Path(packets['output']).open(encoding='utf8') as stream:
            for count,line in enumerate(stream,1):
                packet=json.loads(line)
                for name,engine in engines.items():
                    seen[name].clear();r=engine.ingest(packet);modes[name][r['regime_id']]+=1
                    colors[name].update(h['main']['state'] for h in r['heads'].values())
                assert seen['baseline']==seen['candidate'],'motion extractor changed'
        row=dict(archive=Path(path).name,sources=len(jobs),sources_checked=checks,held_member=held['member'],
            model_id=model['model_id'],training_members=len(jobs)-1,regimes=len(model['regimes']),packets=count,
            raw_held_sha256=ingest['sha256'],metrics={name:dict(observation_nll_per_weight=nll[name]/max(1,weights[name]),
                total_observation_weight=weights[name],modes=dict(modes[name]),main_colors=dict(colors[name])) for name in engines},
            runtime_s=time.monotonic()-start,lamp_accuracy='NOT_MEASURABLE_WITHOUT_ACCEPTED_INDEPENDENT_LAMP_LABELS',
            all_sources_fresh_cold=False,offline_cache_semantics='sealed production predictions, unchanged solver hash; fresh catalogue, fresh raw held-member replay')
        save(out/'receipt.json',row);summary.append(row)
        print('ARCHIVE',index,len(jobs),count,'NLL',[(n,round(nll[n]/max(1,weights[n]),4)) for n in engines],flush=True)
    save(OUT/'archives_complete.json',dict(archives=summary,status='PIPELINE_AND_MOTION_SCORES_NOT_LAMP_ACCURACY',guarded_code_sha256_lf=guarded))


def final(revision='v6'):
    from app.core.intersection_online import CausalIntersection
    from app.core.intersection_emissions import MovementMarks
    from scripts.rebuild_intersection_projection import rebuild
    from app.core.intersection_project import read_model
    summary=[]
    first=read_json(OUT/'archives_complete.json')
    for index,previous in enumerate(first['archives']):
        out=OUT/('archives_'+revision)/f'archive_{index}';out.mkdir(parents=True,exist_ok=True)
        if (out/'receipt.json').exists():summary.append(read_json(out/'receipt.json'));continue
        old=read_model(ROOT/'logs/intersection_projects'/previous['model_id'])
        prior_projection=OUT/'archives_v6'/f'archive_{index}'/'projection.json'
        if revision!='v6' and not (out/'projection.json').exists():
            save(out/'projection.json',dict(model_id=read_json(prior_projection)['model_id'],
                unchanged_projection_receipt_sha256=digest(prior_projection),semantics='same frozen v3 training model; only online engine changed'))
        model=(read_model(ROOT/'logs/intersection_projects'/read_json(out/'projection.json')['model_id'])
               if (out/'projection.json').exists() else rebuild(previous['model_id'],out/'projection.json'))
        packet_manifest=read_json(OUT/'archives'/f'archive_{index}'/'packet_manifest.json')
        assert digest(packet_manifest['output'])==packet_manifest['sha256']
        engines=dict(baseline=baseline_class()(old),candidate=CausalIntersection(model))
        common=MovementMarks(old['regimes']+model['regimes'],contamination=.2)
        mark_tables=dict(baseline=common.distributions[:len(old['regimes'])],candidate=common.distributions[len(old['regimes']):])
        nll=Counter();weights=Counter();modes={n:Counter() for n in engines};known=Counter();seen={n:{} for n in engines};unique=Counter()
        for name,engine in engines.items():
            def wrap(original,owner,name):
                def observe(events):
                    for a,b,w in events:
                        indices=[j for j,(x,y) in enumerate(common.parts) if x==a and (b is None or y==b)]
                        p=sum(float(bank.sum(axis=1)@matrix[indices].sum(axis=0)) for bank,matrix in zip(owner.banks,mark_tables[name]))
                        seen[name][a,b,w]=(-w*math.log(max(1e-15,p)),w)
                    return original(events)
                return observe
            engine._observe=wrap(engine._observe,engine,name)
        started=time.monotonic()
        with Path(packet_manifest['output']).open(encoding='utf8') as stream:
            for count,line in enumerate(stream,1):
                packet=json.loads(line)
                for name,engine in engines.items():
                    seen[name].clear();r=engine.ingest(packet);modes[name][r['regime_id']]+=1
                    known[name]+=sum(h['main']['state']!='UNKNOWN' for h in r['heads'].values())
                common_events=seen['baseline'].keys()&seen['candidate'].keys()
                for name in engines:
                    unique[name]+=len(seen[name].keys()-common_events)
                    for event in common_events:
                        loss,weight=seen[name][event];nll[name]+=loss;weights[name]+=weight
        row=dict(archive=previous['archive'],offline_sources_verified=previous['sources'],model_id=model['model_id'],
            raw_held_sha256=previous['raw_held_sha256'],held_member=previous['held_member'],packets=count,
            packet_sha256=packet_manifest['sha256'],runtime_s=time.monotonic()-started,
            metrics={n:dict(observation_nll_per_weight=nll[n]/max(1,weights[n]),weight=weights[n],modes=dict(modes[n]),
                known_coverage=known[n]/(4*count),additional_unscored_events=unique[n]) for n in engines},
            lamp_accuracy='NOT_MEASURABLE_WITHOUT_INDEPENDENT_LAMP_LABELS',
            score_semantics='causal predictive movement score on common events only, common alphabet/contamination; not lamp accuracy; new selective phases can admit additional marks',
            offline_scope='new v3 projection from sealed solver outputs; raw held member excluded from model')
        save(out/'receipt.json',row);summary.append(row)
        print('FINAL_ARCHIVE',index,count,[(n,round(nll[n]/max(1,weights[n]),4)) for n in engines],flush=True)
    save(OUT/('archives_'+revision+'_complete.json'),dict(archives=summary,sources=sum(r['offline_sources_verified'] for r in summary),
        packets=sum(r['packets'] for r in summary),all_four_motion_scores_improve=all(r['metrics']['candidate']['observation_nll_per_weight']<r['metrics']['baseline']['observation_nll_per_weight'] for r in summary)))


if __name__=='__main__':
    import sys
    if '--final-v7' in sys.argv:final('v7')
    elif '--final' in sys.argv:final()
    else:main()
