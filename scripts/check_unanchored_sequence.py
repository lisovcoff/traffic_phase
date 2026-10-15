"""One sealed engineering witness run; never real trajectories or phase labels."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import subprocess

from app.core.temporal_evidence import TemporalEvent
from app.core.offline_benchmark import match_boundaries, percentile
from app.experimental.local_evidence import build_local_evidence
from app.experimental.unanchored_sequence import infer_unanchored

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/unanchored_sequence_20261015'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name,value):
    p=OUT/name
    if p.exists():raise RuntimeError('No overwrite/retry: '+name)
    p.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def generate():
    """Deterministic independent witness; no decoder outputs used here."""
    inputs=[];truth={}
    for k,order in ((2,[0,1]),(3,[2,0,1])):
        initial=1 if k==2 else 2
        phases=[order[(order.index(initial)+i)%k] for i in range(5)]
        cuts=[0,2,6,10,14,16]
        segments=[[a,b,z] for a,b,z in zip(cuts,cuts[1:],phases)]
        events=[]
        for a,b,z in segments:
            for cell in range(a,b,2):
                for offset in (113,457,1021,1789):
                    i=len(events)
                    events.append(TemporalEvent(cell*1000+offset,'RELEASE',f'm{z}',i,
                        'declared_witness_release',.5,'MEDIUM',None,
                        {'source':'independent_engineering_generator','track_fingerprint':str(i)}))
        spec=dict(horizon_s=16,movements=[f'm{i}' for i in range(k)],cyclic_order=order,
            rates_per_s=[[2. if i==j else .01 for j in range(k)] for i in range(k)],
            rate_source='preregistered engineering witness',latent_demand_exposure=[[1]*8 for _ in range(k)],
            demand_source='supplied witness exposure',observation_windows_s=[[0,16]],
            observation_window_source='supplied witness camera window',
            release_delay_s=[[0,1.]],transit_delay_s=[[0,1.]],delay_source='supplied witness model',
            release_detection_probability=1.,crossing_detection_probability=0.,
            release_method='declared_witness_release',crossing_method='unused_witness_crossing',
            clock_model='continuous_latent_rounded_marks',timestamp_resolution_ms=1,
            timestamp_rounding_origin_ms=0,timestamp_resolution_source='supplied 1ms clock')
        name=f'informative_K{k}'
        view=build_local_evidence(events,source_namespace=name).query(0,16000)
        inputs.append(dict(case=name,view=view,spec=spec,origin_ms=0))
        truth[name]=segments
        if k==2:
            for mode in ('zero_demand','camera_missing','partial_gap'):
                s=json.loads(json.dumps(spec))
                ev=events
                if mode=='zero_demand':s['latent_demand_exposure']=[[0]*8 for _ in range(k)];ev=[]
                if mode=='camera_missing':s['observation_windows_s']=[];ev=[]
                if mode=='partial_gap':
                    s['observation_windows_s']=[[0,4],[8,16]]
                    ev=[e for e in events if not 4000<=e.timestamp_ms<8000]
                v=build_local_evidence(ev,source_namespace=mode).query(0,16000)
                inputs.append(dict(case=mode,view=v,spec=s,origin_ms=0))
                truth[mode]=segments
    return inputs,truth


def prepare():
    OUT.mkdir(exist_ok=True)
    inputs,truth=generate()
    write('inputs.json',inputs);write('truth.json',truth)
    write('manifest.json',dict(base_sha='2a039c8173396c60e70ee5ea863186bc0fe00292',
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        inputs_sha256=sha(OUT/'inputs.json'),truth_sha256=sha(OUT/'truth.json'),
        protocol_sha256=sha(ROOT/'docs/UNANCHORED_SEQUENCE_PROTOCOL_20261015.md'),
        inference_sha256_lf=hashlib.sha256((ROOT/'app/experimental/unanchored_sequence.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        source_sha256_lf={name:hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()
            for name in ('app/experimental/unanchored_sequence.py','app/experimental/phase_observation_bridge.py',
                         'app/experimental/rounded_observation.py','app/experimental/joint_track_model.py',
                         'scripts/check_unanchored_sequence.py')},
        point_tolerance_s=2,cases=len(inputs),max_calls=5,total_cpu_budget_s=30,
        per_call_limits=dict(max_paths=10000,max_seconds=5,max_memory_bytes=32*1024*1024)))


def run():
    if (OUT/'outputs_sealed.json').exists():raise RuntimeError('No repeated suite')
    manifest=json.loads((OUT/'manifest.json').read_text())
    assert sha(OUT/'inputs.json')==manifest['inputs_sha256']
    assert hashlib.sha256((ROOT/'app/experimental/unanchored_sequence.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest()==manifest['inference_sha256_lf']
    for name,expected in manifest['source_sha256_lf'].items():
        assert hashlib.sha256((ROOT/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==expected
    started=time.process_time();outputs={};calls=0
    for item in json.loads((OUT/'inputs.json').read_text()):
        if time.process_time()-started>=30:raise RuntimeError('Suite CPU budget exhausted; no retry')
        outputs[item['case']]=infer_unanchored(item['view'],item['spec'],origin_ms=item['origin_ms'],**manifest['per_call_limits'])
        calls+=1
    write('predictions.json',outputs)
    write('outputs_sealed.json',dict(predictions_sha256=sha(OUT/'predictions.json'),
        calls=calls,cpu_s=time.process_time()-started,truth_file_read_by_worker=False))
    print(json.dumps({name:dict(status=r['status'],paths=r.get('path_count'),
        prior_only=r.get('prior_only_numerically')) for name,r in outputs.items()},indent=2))


def evaluate():
    seal=json.loads((OUT/'outputs_sealed.json').read_text());m=json.loads((OUT/'manifest.json').read_text())
    assert sha(OUT/'predictions.json')==seal['predictions_sha256']
    assert sha(OUT/'truth.json')==m['truth_sha256']
    truth=json.loads((OUT/'truth.json').read_text())
    preds=json.loads((OUT/'predictions.json').read_text());rows=[]
    for name,r in preds.items():
        for prior,p in r.get('results',{}).items():
            segments=p['diagnostic_segments'];tb=[s[0]*1000 for s in truth[name][1:]];pb=[s[0]*1000 for s in segments[1:]]
            matched=match_boundaries(tb,pb,m['point_tolerance_s'])
            errors=[abs(x['signed_error_s']) for x in matched]
            rows.append(dict(case=name,prior=prior,matched=len(matched),truth=len(tb),predicted=len(pb),
                precision=len(matched)/len(pb) if pb else None,recall=len(matched)/len(tb) if tb else None,
                matched_mae_s=sum(errors)/len(errors) if errors else None,matched_p95_s=percentile(errors,.95) if errors else None,
                diagnostic_segments=segments,exact_witness_pass=segments==truth[name] if name.startswith('informative') else None,
                prior_only=r['prior_only_numerically'],posterior_vs_prior_kl_nats=p['posterior_vs_prior_kl_nats'],
                transition_count_posterior=p['transition_count_posterior'],initial_phase_posterior=p['initial_phase_posterior'],
                diagnostic_temporal_coverage=1.,published_logical_unknown_fraction=1.,physical_unknown_fraction=1.,range_s=[0,16]))
    write('comparison.json',dict(rows=rows,point_evaluator='unchanged app.core.offline_benchmark.match_boundaries',
        tolerance_s=2,not_population_or_lamp_accuracy=True,original_2d1_gate='FAIL_UNCHANGED'))
    for row in rows:print(row['case'],row['prior'],f"{row['matched']}/{row['truth']}/{row['predicted']}",'exact=',row['exact_witness_pass'],'prior_only=',row['prior_only'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','evaluate'])
    {'prepare':prepare,'run':run,'evaluate':evaluate}[parser.parse_args().action]()
