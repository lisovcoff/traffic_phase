"""One predeclared synthetic review; no real data/annotations/refitting access."""
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from app.core.v9.primitives import build_occupancy_matrix
from app.core.v9.decoder import LocalHistoryConfig,decode_cyclic_hsmm,decode_local_history
from app.core.offline_benchmark import evaluate_history,validate_annotation
from app.core.state_contract import physical_estimate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/stage2d1_sparse_review'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def occupancy(case):
    streams={name:[] for name in case['model_movements']}
    for event in case['events']:streams[event['movement']].append(event['timestamp_ms']/1000.)
    x,names=build_occupancy_matrix(streams,case['extent_s'],dt=1.)
    source=np.array(case['templates']);templates=source[:,[case['model_movements'].index(m) for m in names]]
    coverage=np.array([any(a<=t<b for a,b in case['provided_input_intervals_s']) for t in range(len(x))])
    return x,templates,coverage,names


def conditional_mark_emissions(x,templates):
    """Conditional on event count; assumes stable mark mix/exposure. Zeros add no term."""
    templates=np.asarray(templates,dtype=float)
    distribution=templates/np.sum(templates,axis=1,keepdims=True)
    return np.asarray(x)@np.log(distribution).T


def diagnostic_candidate(x,templates,coverage,period,targets,config):
    started=time.monotonic();k=len(templates);n=len(x)
    work=n*k*int(max(3,np.max(np.round(np.maximum(np.minimum(config.max_duration_s,
        config.duration_max_factor*np.asarray(targets)),
        np.maximum(config.min_duration_s,config.duration_min_factor*np.asarray(targets))+1)))+1))
    if n>config.max_bins or work>config.max_work_units:
        return {'status':'unavailable','reason':'WORK_BUDGET','candidate_segments':[]}
    if not np.any(x[coverage]):
        return {'status':'unavailable','reason':'NO_EVENTS; prior alone is not evidence','candidate_segments':[]}
    try:
        labels,score,segments,decoder=decode_cyclic_hsmm(x,templates,period,k,initial_phase=0,
            duration_targets=targets,min_duration_s=config.min_duration_s,max_duration_s=config.max_duration_s,
            duration_min_factor=config.duration_min_factor,duration_max_factor=config.duration_max_factor,
            duration_penalty_strength=config.duration_penalty_strength,transition_penalty=config.transition_penalty,
            observation_mask=coverage,deadline_monotonic=started+config.max_seconds,
            diagnostic_emissions=conditional_mark_emissions(x,templates))
    except (TimeoutError,RuntimeError) as error:
        return {'status':'unavailable','reason':type(error).__name__+': '+str(error),'candidate_segments':[]}
    if time.monotonic()-started>config.max_seconds:
        return {'status':'unavailable','reason':'TIME_BUDGET','candidate_segments':[]}
    return {'status':'diagnostic_only','candidate_segments':segments,'score':score,'decoder':decoder,
        'runtime_s':time.monotonic()-started,'assumptions':['stable conditional mark mix and observation exposure',
        'frozen occupancy templates treated as conditional mark proxy','unchanged uncalibrated duration prior'],
        'support_kind':'temporal_sequence_plus_duration_prior; NOT independently identified intervals',
        'publication_approved':False,'cause':'UNKNOWN','calibrated_lamp_probability':None}


def summary(hist):
    b=hist['boundaries'];m=b['mae_s']
    return {'matched':m['matched_boundaries'],'truth':m['truth_boundaries'],'predicted':m['predicted_boundaries'],
        'recall':b['recall'],'precision':b['precision'],'MAE':m,'p95':b['p95_s'],
        'nearest_MAE':b['nearest_truth_boundary_mae_s_diagnostic'],'coverage':hist['coverage']}


def review():
    if (OUT/'experiment_started.json').exists():raise RuntimeError('suite already started; no repeat/tuning')
    manifest=json.loads((OUT/'predeclared_manifest.json').read_text(encoding='utf-8'))
    suite=json.loads((OUT/'sparse_suite.json').read_text(encoding='utf-8'))
    config=LocalHistoryConfig(**manifest['config']);assert asdict(config)==manifest['config']
    save(OUT/'experiment_started.json',{'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'suite_sha256':sha(OUT/'sparse_suite.json'),'manifest_sha256':sha(OUT/'predeclared_manifest.json'),
        'config':asdict(config),'max_suite_runs':1,'real_files_read':0})
    ledger=[];suite_started=time.monotonic()
    for case in suite:
        if time.monotonic()-suite_started>60:
            raise TimeoutError('synthetic suite cooperative 60s budget exceeded; gate unavailable, no real replay')
        x,templates,coverage,names=occupancy(case)
        legacy=decode_local_history(x,templates,case['period_s'],case['duration_targets_s'],coverage_mask=coverage)
        proposal=diagnostic_candidate(x,templates,coverage,case['period_s'],case['duration_targets_s'],config)
        published={'status':'unavailable','reason':'VALIDATED_INTERVAL_SUPPORT_MODEL_NOT_IMPLEMENTED',
                   'segments':[],'cause':'UNKNOWN','calibrated_lamp_probability':None}
        prediction={'case':case['case'],'seed':case['seed'],'fixed_K':case['K'],'fixed_period_s':case['period_s'],
            'events':case['events'],'local_event_bin_count':int(np.sum(np.any(x>0,axis=1))),
            'provided_input_coverage':case['provided_input_intervals_s'],'templates_sha256':hashlib.sha256(templates.tobytes()).hexdigest(),
            'legacy_rejected_history':legacy,'proposal_diagnostic':proposal,'proposed_published_history':published,
            'physical_section':physical_estimate('UNKNOWN').to_dict()}
        name=f"{case['case']}_seed{case['seed']}.json";path=OUT/'synthetic_predictions'/name;save(path,prediction)
        ledger.append({'case':case['case'],'seed':case['seed'],'prediction_sha256':sha(path)})
    save(OUT/'predictions_sealed.json',ledger)
    # Generated truth stays outside the candidate/decoder interfaces.
    rows=[];core_pass=True
    for case,entry in zip(suite,ledger):
        name=f"{case['case']}_seed{case['seed']}.json";path=OUT/'synthetic_predictions'/name
        assert sha(path)==entry['prediction_sha256'];pred=json.loads(path.read_text(encoding='utf-8'))
        segments=case['truth_segments'];marks=[{'timestamp_ms':a*1000,'kind':str(z),'offset_s':a} for a,b,z in segments]
        marks.append({'timestamp_ms':case['extent_s']*1000,'kind':str((segments[-1][2]+1)%case['K']),'offset_s':case['extent_s']})
        annotation=validate_annotation({'start_ms':0,'marks':marks});assert annotation['valid']
        adapter={'schedule_base_timestamp_ms':0,'schedule':{
            'legacy_supported':pred['legacy_rejected_history']['segments'],
            'legacy_candidate':pred['legacy_rejected_history'].get('candidate_segments',[]),
            'proposal_candidate':pred['proposal_diagnostic']['candidate_segments'],
            'proposal_published':pred['proposed_published_history']['segments']},
            'source_prediction_sha256':sha(path),'tolerance_s':manifest['boundary_tolerance_s']}
        artifact=OUT/'evaluation_adapters'/name;save(artifact,adapter);h=sha(artifact)
        metrics={field:summary(evaluate_history(adapter,annotation,field,manifest['boundary_tolerance_s']))
                 for field in adapter['schedule']}
        core=case['case'].startswith(('stable','hold','shorten'))
        recall=metrics['proposal_candidate']['recall']['value']
        recovery_pass=not core or (recall is not None and recall>=manifest['core_candidate_recall_min'])
        core_pass &= recovery_pass
        rows.append({'case':case['case'],'seed':case['seed'],'events':len(case['events']),
            'core_recovery_case':core,'candidate_recovery_pass':recovery_pass,'metrics':metrics,
            'prediction_sha256':sha(path),'adapter_sha256':h,
            'published_UNKNOWN_fraction':1.,'published_unknown_reason':pred['proposed_published_history']['reason']})
        assert h==sha(artifact)
    result={'base_sha':manifest['base_sha'],'rows':rows,'candidate_sparse_recovery_gate':'PASS' if core_pass else 'FAIL',
        'publication_identifiability_gate':'FAIL: interval support/latent demand ambiguity unvalidated',
        'overall_gate':'FAIL','real_replays':0,'real_replay_reason':'predeclared sparse recovery AND identifiability gate not passed',
        'no_post_result_tuning':True,'interpretation':'synthetic diagnostic candidates, not approved history or lamp accuracy'}
    save(OUT/'comparison.json',result)
    print('Sparse suite complete. Candidate recovery:',result['candidate_sparse_recovery_gate'])
    print('Overall gate FAIL. Real replay prohibited; no parameters/seeds retried.')


if __name__=='__main__':review()
