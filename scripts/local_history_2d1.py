"""One bounded development reconstruction run from frozen models, never refitting."""
import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
from app.core.v9.decoder import LocalHistoryConfig, decode_local_history
from app.core.v9.primitives import build_occupancy_matrix
from app.core.offline_benchmark import evaluate_history, validate_annotation

ROOT=Path(__file__).resolve().parents[1]
BASE='b248b4c7bac27def4a131ba61301f2678cd0b05a'
OUT=ROOT/'benchmarks/stage2d1_20261014'
INPUT=ROOT/'benchmarks/stage2c_20261014'
WORKER_TIMEOUT_S=90.
DT=1.


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')


def reconstruct_frozen(source,output):
    # No annotation path or payload in this worker interface.
    if 'manual_marks' in source.name or 'annotation' in source.name:
        raise ValueError('annotation files are forbidden as reconstruction inputs')
    pred=json.loads(source.read_text(encoding='utf-8'))
    if 'evaluation' in pred:raise ValueError('label-bearing prediction cannot be an inference input')
    schedule=pred['schedule'];streams=defaultdict(list)
    extraction=pred['event_extraction'];events=extraction['temporal_events']
    for i in extraction['quality_diagnostics']['selected_event_indices']:
        event=events[i];streams[event['movement']].append((event['timestamp_ms']-pred['schedule_base_timestamp_ms'])/1000)
    if pred.get('regime_detection',{}).get('method')=='hourly_local_period_consensus':
        pred['reconstruction_history']={'status':'unavailable','segments':[],'source':'fixed_templates_local_cyclic_hsmm',
            'reason':'MULTIPLE_REGIME_SCOPE_UNSUPPORTED','calibrated_lamp_probability':None}
    else:
        extent=schedule['raw_hsmm_segments'][-1][1]-DT
        x,names=build_occupancy_matrix(streams,extent,dt=DT)
        activity={row['stream']:row['event_probability_by_phase'] for row in schedule['stream_activity_by_phase']}
        templates=np.array([[activity[name][phase] for name in names] for phase in schedule['phase_names']])
        targets=[schedule['baseline_duration_targets_s'][phase] for phase in schedule['phase_names']]
        pred['reconstruction_history']=decode_local_history(x,templates,schedule['period_s'],targets,
            dt=DT,initial_phase=int(schedule['raw_hsmm_segments'][0][2]))
    pred['reconstruction_history']['provenance']={'fixed_prediction_sha256':sha(source),
        'observations':'unchanged selected temporal events; saved schedule anchor; binary occupancy',
        'annotations_used':False,'global_offset_fitted':False,'templates_refitted':False}
    save(output,pred)


def summarize(metric):
    b=metric['boundaries'];m=b['mae_s']
    return {'status':metric['status'],'reason':metric.get('reason'),
        'matched_count':m['matched_boundaries'],'truth_count':m['truth_boundaries'],'predicted_count':m['predicted_boundaries'],
        **{k:b[k] for k in ('precision','recall','mae_s','p95_s','nearest_truth_boundary_mae_s_diagnostic')},
        'coverage':metric['coverage']}


def run():
    if OUT.exists():raise RuntimeError('single development run already started; no retrial')
    OUT.mkdir(parents=True)
    files=sorted((INPUT/'predictions').glob('*_v9.json'));assert len(files)==3
    save(OUT/'run_manifest.json',{'base_sha':BASE,'code_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'local_config':asdict(LocalHistoryConfig()),'dt_s':DT,'worker_timeout_s':WORKER_TIMEOUT_S,
        'boundary_tolerance_s':2.,'max_runs':1,'K_search_runs':0,'fitting_runs':0,
        'input_hashes':{p.name:sha(p) for p in files}})
    ledger=[]
    for source in files:
        target=OUT/'predictions'/source.name;started=time.monotonic()
        env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        print('Reconstruct fixed model:',source.name,flush=True)
        try:
            result=subprocess.run([sys.executable,'-m','scripts.local_history_2d1','infer',str(source),str(target)],
                cwd=ROOT,env=env,capture_output=True,text=True,timeout=WORKER_TIMEOUT_S)
            reason=None if result.returncode==0 else 'WORKER_FAILED: '+result.stderr[-2000:]
        except subprocess.TimeoutExpired:
            reason='WORKER_TIMEOUT'
        if reason:
            pred=json.loads(source.read_text(encoding='utf-8'))
            pred['reconstruction_history']={'status':'unavailable','reason':reason,'segments':[],
                'source':'fixed_templates_local_cyclic_hsmm','calibrated_lamp_probability':None}
            if not target.exists():save(target,pred)
        ledger.append({'input':source.name,'prediction_sha256':sha(target),'runtime_s':time.monotonic()-started,'reason':reason})
    save(OUT/'predictions_sealed.json',ledger)
    # All predictions/hashes fixed before any annotation file is opened.
    rows=[]
    old_report=json.loads((INPUT/'baseline_metrics.json').read_text(encoding='utf-8'))
    old_rows={r['source_name']:r for r in old_report['rows']}
    for source,entry in zip(files,ledger):
        target=OUT/'predictions'/source.name;assert sha(target)==entry['prediction_sha256']
        pred=json.loads(target.read_text(encoding='utf-8'));old=json.loads(source.read_text(encoding='utf-8'))
        for field in ('schedule','phase_model_selection','period_inference','event_extraction'):
            assert pred[field]==old[field]
        name=source.name.removesuffix('_v9.json')+'.json'
        marks=ROOT.parent/'data'/'ручная разметка'/(name+'_manual_marks.json')
        annotation=validate_annotation(json.loads(marks.read_text(encoding='utf-8')))
        assert sha(marks)==old_rows[name]['annotation_sha256'] and annotation['valid']
        adapter={'schedule_base_timestamp_ms':pred['schedule_base_timestamp_ms'],
            'schedule':{**pred['schedule'],'reconstruction_segments':pred['reconstruction_history']['segments']},
            'adapter_metadata':{'source_prediction_sha256':sha(target),'source_field':'reconstruction_history.segments',
                'evaluated_field':'schedule.reconstruction_segments','boundary_tolerance_s':2.}}
        artifact=OUT/'evaluation_artifacts'/source.name;save(artifact,adapter);adapter_hash=sha(artifact)
        histories={field:summarize(evaluate_history(adapter,annotation,field,2.))
            for field in ('raw_hsmm_segments','baseline_segments','reconstruction_segments')}
        assert sha(artifact)==adapter_hash and sha(target)==entry['prediction_sha256']
        rows.append({'source':name,'K':pred['schedule']['phase_count'],'period_s':pred['schedule']['period_s'],
            'period_error_s':old_rows[name]['metrics']['period_absolute_error_s'],
            'invariants':'exact schedule/selection/period/event extraction equality with frozen2C prediction',
            'runtime_s':entry['runtime_s'],'reference_full_discovery_runtime_s':old_rows[name]['inference_runtime_s'],
            'runtime_interpretation':'local-only run, not directly comparable to full discovery',
            'history_status':pred['reconstruction_history']['status'],'reason':pred['reconstruction_history'].get('reason'),
            'abstention_intervals':pred['reconstruction_history'].get('abstention_intervals',[]),
            'history_coverage_s':pred['reconstruction_history'].get('coverage_s',0),
            'local_decoder_runtime_s':pred['reconstruction_history'].get('runtime_s'),
            'adapter_sha256':adapter_hash,'prediction_sha256':sha(target),'histories':histories})
    save(OUT/'comparison.json',{'interpretation':'development logical-phase histories, NOT lamp accuracy',
        'evaluated_new_field':'schedule.reconstruction_segments; hashed adapter from reconstruction_history.segments',
        'rows':rows})
    print('One development run completed; predictions sealed before evaluation.',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    worker=sub.add_parser('infer');worker.add_argument('source',type=Path);worker.add_argument('output',type=Path)
    sub.add_parser('run');args=parser.parse_args()
    if args.command=='infer':reconstruct_frozen(args.source,args.output)
    else:run()
