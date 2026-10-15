"""Single frozen synthetic run. Worker reads inputs only; truth is evaluation-only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from app.experimental.joint_track_model import infer_joint, LIMITS, PRIORS
from app.core.offline_benchmark import evaluate_history, validate_annotation, percentile
from scripts.offline_benchmark import ROOT, write_json, sha256_file, git


def prepare(out):
    if (out/'manifest.json').exists(): raise ValueError('manifest already exists')
    inputs=json.loads((out/'inputs.json').read_text(encoding='utf-8'))
    if len(inputs)!=24: raise ValueError('declared suite requires 24 inputs')
    paths=[ROOT/'app/experimental/joint_track_model.py',ROOT/'app/experimental/local_evidence.py',
           ROOT/'app/core/state_contract.py',ROOT/'app/core/temporal_evidence.py',
           ROOT/'app/core/offline_benchmark.py',ROOT/'scripts/joint_track_suite.py',Path(__file__),
           ROOT/'tests/test_joint_track_model.py',ROOT/'docs/JOINT_TRACK_OBSERVATION_PROTOCOL_20261015.md']
    manifest={'schema':'joint-track-synthetic-experiment-v1',
        'base':'59cb228516b40ad41c52334b826286500714e4b1','prepared_head':git('rev-parse','HEAD'),
        'inputs_sha256':sha256_file(out/'inputs.json'),'suite_sha256':sha256_file(out/'suite.json'),
        'file_hashes':{str(p.relative_to(ROOT)):sha256_file(p) for p in paths},
        'limits':LIMITS,'suite_cpu_s':60.0,'external_worker_timeout_s':90,'max_calls':24,'retries':0,
        'priors':PRIORS,'point_tolerance_s':2.0,'per_case_core_recall_gate':.8,
        'intervals':'equal-tailed90% model-conditioned finite-grid posterior',
        'known_assumptions':'K/order/initial anchor and exactly four observed segments supplied',
        'original_2D1_gate':'FAIL unchanged; this test is not real acceptance',
        'real_data_reads':0,'real_replays':0,'production_acceptance':False}
    write_json(out/'manifest.json',manifest)
    (out/'manifest.sha256').write_bytes((sha256_file(out/'manifest.json')+'\n').encode())


def worker(out):
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    inputs=json.loads((out/'inputs.json').read_text(encoding='utf-8'))
    if sha256_file(out/'inputs.json')!=manifest['inputs_sha256']: raise ValueError('inputs changed')
    if len(inputs)>manifest['max_calls']: raise ValueError('call limit')
    started=time.process_time(); ledger=[]
    for item in inputs:
        limits=dict(manifest['limits'])
        remaining=manifest['suite_cpu_s']-(time.process_time()-started)
        limits['max_seconds']=min(limits['max_seconds'],max(0.,remaining))
        result=infer_joint(**item['inference_input'],priors=manifest['priors'],**limits)
        name=f"{item['case']}_seed{item['seed']}.json"
        path=out/'predictions'/name
        if path.exists(): raise ValueError('prediction already exists; no retries')
        write_json(path,result)
        ledger.append({'case':item['case'],'seed':item['seed'],'path':str(path.relative_to(out)),
                       'sha256':sha256_file(path),'status':result['status'],'cpu_s':result['cpu_s']})
        print(item['case'],item['seed'],result['status'],round(result['cpu_s'],3),flush=True)
    write_json(out/'worker_ledger.json',{'predictions':ledger,'cpu_s':time.process_time()-started,
        'calls':len(ledger),'inputs_after_sha256':sha256_file(out/'inputs.json')})


def evaluate_one(case, output, prior, digest, out):
    h=case['inference_input']['spec']['horizon_s'];truth=case['truth_segments']
    model=output.get('results',{}).get(prior,{})
    segments=model.get('diagnostic_segments',[])
    marks=[{'timestamp_ms':a*1000,'kind':str(z)} for a,b,z in truth]
    marks.append({'timestamp_ms':h*1000,'kind':str(truth[-1][2])})
    annotation=validate_annotation({'start_ms':0,'marks':marks})
    adapter={'schedule_base_timestamp_ms':0,'schedule':{'candidate':segments},
             'prediction_sha256':digest,'evaluated_field':'diagnostic_candidate',
             'published_logical_history':'UNKNOWN; no publication'}
    name=f"{case['case']}_seed{case['seed']}_{prior}.json"
    write_json(out/'evaluation_adapters'/name,adapter)
    point=evaluate_history(adapter,annotation,'candidate',2.0)
    intervals=model.get('boundary_posteriors',[])
    checks=[]
    for i,segment in enumerate(truth[1:]):
        bracket=intervals[i]['equal_tailed_90_s'] if i<len(intervals) else None
        checks.append({'ordinal':i+1,'truth_s':segment[0],'issued':bracket is not None,
            'contained':bracket[0]<=segment[0]<=bracket[1] if bracket else None,
            'width_s':bracket[1]-bracket[0] if bracket else None})
    widths=[c['width_s'] for c in checks if c['issued']]
    core=case['case'].startswith(('stable','hold','shortening'))
    recall=point['boundaries']['recall']['value']
    return {'case':case['case'],'seed':case['seed'],'prior':prior,
        'correctly_specified':case['correctly_specified'],'status':output['status'],'reason':output.get('reason'),
        'point':point,'core_point_gate':('PASS' if recall is not None and recall>=.8 else 'FAIL') if core else 'NOT_CORE',
        'interval_checks':checks,'interval_containment':{'contained':sum(c['contained'] is True for c in checks),
             'issued':len(widths),'truth':len(checks),'unissued':len(checks)-len(widths)},
        'interval_width_s':{'n':len(widths),'median':percentile(widths,.5) if widths else None,
                           'p95':percentile(widths,.95) if widths else None,'le_4s':sum(w<=4 for w in widths)},
        'prior_vs_posterior_kl_nats':model.get('posterior_vs_prior_kl_nats'),
        'prior_only_numerically':output.get('prior_only_numerically'),
        'published_logical_unknown_fraction':1.0,'physical_unknown_fraction':1.0,
        'observed_tracks':output.get('observed_track_count'),'observed_marks':output.get('observed_vehicle_mark_count'),
        'path_count':output.get('path_count'),'joint_pattern_violations':0 if output['complete'] else None,
        'generated_off_phase_vehicles':case['generation']['off_phase_vehicle_count'],
        'interpretation':'synthetic model-conditioned posterior, not verified lamp accuracy',
        'prediction_sha256':digest,'evaluation_adapter_sha256':sha256_file(out/'evaluation_adapters'/name)}


def evaluate(out, ledger):
    # First truth access happens only after parent sealed every prediction.
    if not (out/'outputs_sealed.json').exists(): raise ValueError('prediction seal missing')
    suite=json.loads((out/'suite.json').read_text(encoding='utf-8'))
    index={(c['case'],c['seed']):c for c in suite}
    rows=[]; dependence=[]
    for entry in ledger['predictions']:
        path=out/entry['path']
        if sha256_file(path)!=entry['sha256']: raise ValueError('prediction changed')
        result=json.loads(path.read_text(encoding='utf-8'))
        case=index[(entry['case'],entry['seed'])]
        rows.extend(evaluate_one(case,result,prior,entry['sha256'],out) for prior in PRIORS)
        a,b=[result.get('results',{}).get(prior,{}) for prior in PRIORS]
        dependence.append({'case':entry['case'],'seed':entry['seed'],
            'same_point_path':a.get('diagnostic_segments')==b.get('diagnostic_segments') if result['complete'] else None})
        if sha256_file(path)!=entry['sha256']: raise ValueError('evaluation mutated prediction')
    summary={}
    for prior in PRIORS:
        chosen=[r for r in rows if r['prior']==prior]
        boundary=[r['point']['boundaries']['recall'] for r in chosen]
        widths=[c['width_s'] for r in chosen for c in r['interval_checks'] if c['issued']]
        errors=[abs(m['signed_error_s']) for r in chosen for m in r['point']['boundaries']['matches']]
        totals={key:sum(v[key] for v in boundary) for key in ('matched_boundaries','truth_boundaries','predicted_boundaries')}
        matched,truth,pred=[totals[k] for k in ('matched_boundaries','truth_boundaries','predicted_boundaries')]
        summary[prior]={**totals,'precision':matched/pred if pred else None,'recall':matched/truth if truth else None,
            'matched_mae_s':sum(errors)/len(errors) if errors else None,
            'matched_p95_s':percentile(errors,.95) if errors else None,
            'complete_cases':sum(r['status']=='complete_finite_posterior' for r in chosen),
            'core_gate_passed':sum(r['core_point_gate']=='PASS' for r in chosen),
            'core_gate_failed':sum(r['core_point_gate']=='FAIL' for r in chosen),
            'interval_contained':sum(r['interval_containment']['contained'] for r in chosen),
            'interval_issued':len(widths),'truth_boundaries':truth,
            'interval_median_width_s':percentile(widths,.5) if widths else None,
            'interval_p95_width_s':percentile(widths,.95) if widths else None,
            'interval_width_le4_count':sum(w<=4 for w in widths),
            'unissued_intervals':sum(r['interval_containment']['unissued'] for r in chosen),
            'scope':'all 24 synthetic cases, including uninformative/misspecified; not real accuracy'}
    write_json(out/'comparison.json',{'rows':rows,'summary':summary,'prior_dependence':dependence,
        'known_transition_count':True,'real_runs':0,'historical_gate':'FAIL unchanged',
        'production_acceptance':False,'physical_lamp_accuracy':None})
    print(json.dumps(summary,indent=2),flush=True)


def run(out):
    manifest_path=out/'manifest.json'
    if sha256_file(manifest_path)!=(out/'manifest.sha256').read_text().strip(): raise ValueError('manifest changed')
    manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    if sha256_file(out/'suite.json')!=manifest['suite_sha256']: raise ValueError('suite changed')
    if sha256_file(out/'inputs.json')!=manifest['inputs_sha256']: raise ValueError('inputs changed')
    for file,digest in manifest['file_hashes'].items():
        if sha256_file(ROOT/file)!=digest: raise ValueError('frozen code changed: '+file)
    with (out/'started.json').open('x',encoding='utf-8') as f:
        json.dump({'code_sha':git('rev-parse','HEAD'),'manifest_sha256':sha256_file(manifest_path)},f)
    env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYTHONHASHSEED':'0'}
    try:
        p=subprocess.run([sys.executable,'-m','scripts.run_joint_track_experiment','worker','--out',str(out)],
            cwd=ROOT,env=env,capture_output=True,timeout=90)
    except subprocess.TimeoutExpired:
        write_json(out/'run_status.json',{'status':'unavailable','reason':'EXTERNAL_TIMEOUT_NO_RETRY'})
        raise SystemExit(1)
    (out/'worker.log').write_bytes(p.stdout+p.stderr)
    if p.returncode: raise RuntimeError('worker failed; no retries; see worker.log')
    ledger=json.loads((out/'worker_ledger.json').read_text(encoding='utf-8'))
    if ledger['calls']!=24 or ledger['inputs_after_sha256']!=manifest['inputs_sha256']: raise ValueError('ledger/input mismatch')
    for entry in ledger['predictions']:
        if sha256_file(out/entry['path'])!=entry['sha256']: raise ValueError('prediction changed before seal')
    write_json(out/'outputs_sealed.json',{**ledger,'manifest_sha256':sha256_file(manifest_path),'evaluation_started':False})
    evaluate(out,ledger)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run','worker'])
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    {'prepare':prepare,'run':run,'worker':worker}[a.command](a.out)
