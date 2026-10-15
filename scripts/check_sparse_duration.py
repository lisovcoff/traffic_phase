"""One preregistered synthetic run, sealed before evaluation; no real replay."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import time

from app.core.offline_benchmark import match_boundaries,percentile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'evidence/sparse_duration_20261015'
SOURCES=['app/experimental/unanchored_sequence.py','app/experimental/rounded_observation.py',
    'app/experimental/phase_observation_bridge.py','app/experimental/joint_track_model.py',
    'scripts/sparse_duration_cases.py','scripts/check_sparse_duration.py']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))


def write(name,value):
    path=OUT/name
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,allow_nan=False)


def prepare():
    from scripts.sparse_duration_cases import suite
    inputs,truth=suite();OUT.mkdir(exist_ok=True)
    write('inputs.json',inputs);write('truth.json',truth)
    write('manifest.json',dict(base_sha='41563f5852ec2708a0db6a590d04888b256baae9',
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip(),
        inputs_sha256=sha(OUT/'inputs.json'),truth_sha256=sha(OUT/'truth.json'),
        source_sha256_lf={p:hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in SOURCES},
        protocol_sha256=sha(ROOT/'docs/SPARSE_DURATION_PROTOCOL_20261015.md'),
        max_calls=16,cpu_budget_s=60,wall_budget_s=90,
        limits=dict(max_paths=10000,max_seconds=5,max_memory_bytes=32*1024*1024),
        point_tolerance_s=2,core_recall_gate=.8))


def run():
    from app.experimental.unanchored_sequence import infer_unanchored
    m=read('manifest.json');assert sha(OUT/'inputs.json')==m['inputs_sha256']
    for p,expected in m['source_sha256_lf'].items():
        assert hashlib.sha256((ROOT/p).read_bytes().replace(b'\r\n',b'\n')).hexdigest()==expected
    write('run_started.json',dict(max_calls=16)) # no retries after interruption
    started=time.process_time();wall=time.perf_counter();entries=[];calls=0
    for item in read('inputs.json'):
        remaining=min(m['cpu_budget_s']-(time.process_time()-started),m['wall_budget_s']-(time.perf_counter()-wall))
        if remaining<=0:
            result=dict(status='unrun',complete=False,reason='SUITE_BUDGET_EXHAUSTED',results={})
        else:
            limits={**m['limits'],'max_seconds':min(5,remaining)}
            result=infer_unanchored(item['view'],item['spec'],origin_ms=item['origin_ms'],**limits)
            calls+=1
        filename=item['case']+'.json.gz'
        with (OUT/filename).open('xb') as f:
            f.write(gzip.compress(json.dumps(result,separators=(',',':'),allow_nan=False).encode(),mtime=0))
        entries.append(dict(case=item['case'],path=filename,sha256=sha(OUT/filename),status=result['status']))
        print(item['case'],result['status'],result.get('reason',''),flush=True)
    write('outputs_sealed.json',dict(predictions=entries,calls=calls,cpu_s=time.process_time()-started,
        wall_s=time.perf_counter()-wall,truth_file_read_by_worker=False))


def evaluate():
    m=read('manifest.json');seal=read('outputs_sealed.json')
    assert sha(OUT/'truth.json')==m['truth_sha256']
    # Verify every output before opening any truth labels.
    for e in seal['predictions']:assert sha(OUT/e['path'])==e['sha256']
    truth=read('truth.json');rows=[]
    for e in seal['predictions']:
        result=json.loads(gzip.decompress((OUT/e['path']).read_bytes()))
        tb=[s[0] for s in truth[e['case']]['segments'][1:]]
        horizon=truth[e['case']]['segments'][-1][1]
        core=any('_'+x+'_' in e['case'] for x in ('stable','hold10','shortening'))
        for prior in ('flat','soft'):
            p=result.get('results',{}).get(prior,{})
            segments=p.get('diagnostic_segments',[]);pb=[s[0] for s in segments[1:]]
            matches=match_boundaries([t*1000 for t in tb],[t*1000 for t in pb],m['point_tolerance_s'])
            errors=[abs(x['signed_error_s']) for x in matches]
            intervals=[];count=str(len(tb))
            conditional=p.get('boundary_posteriors_conditioned_on_count',{}).get(count,{})
            for ordinal,t in enumerate(tb,1):
                mass=conditional.get(str(ordinal),{})
                if not mass:
                    intervals.append(dict(ordinal=ordinal,issued=False,reason='NO_NUMERIC_POSTERIOR_FOR_TRUTH_COUNT'));continue
                times=sorted((int(k),v) for k,v in mass.items());cumulative=0.;lo=None;hi=None
                for x,v in times:
                    cumulative+=v
                    if lo is None and cumulative>=.05:lo=x
                    if hi is None and cumulative>=.95:hi=x
                hi=times[-1][0] if hi is None else hi
                near_mass=sum(row['posterior'][prior] for row in result['alternatives'] if any(abs(b-t)<=2 for b in row['boundaries_s']))
                intervals.append(dict(ordinal=ordinal,issued=True,interval_s=[lo,hi],width_s=hi-lo,
                    contained=lo<=t<=hi,any_boundary_posterior_mass_within_2s=near_mass))
            recall=len(matches)/len(tb) if tb else None
            rows.append(dict(case=e['case'],prior=prior,status=result['status'],reason=result.get('reason'),
                core_gate=('PASS' if recall is not None and recall>=m['core_recall_gate'] and result['complete'] else 'FAIL') if core else 'NOT_CORE',
                matched=len(matches),truth=len(tb),predicted=len(pb),precision=len(matches)/len(pb) if pb else None,recall=recall,
                matched_mae_s=sum(errors)/len(errors) if errors else None,matched_p95_s=percentile(errors,.95) if errors else None,
                nearest_mae_s=sum(min(abs(t-b) for b in pb) for t in tb)/len(tb) if tb and pb else None,
                exact_count=len(pb)==len(tb) if result['complete'] else None,
                exact_initial_phase=segments[0][2]==truth[e['case']]['segments'][0][2] if segments else None,
                truth_count_posterior_mass=p.get('transition_count_posterior',{}).get(count),
                transition_count_posterior=p.get('transition_count_posterior'),prior_only=result.get('prior_only_numerically'),
                posterior_vs_prior_kl_nats=p.get('posterior_vs_prior_kl_nats'),conditional_intervals=intervals,
                diagnostic_temporal_coverage=1. if result['complete'] else 0.,published_logical_unknown_fraction=1.,physical_unknown_fraction=1.,
                range_s=[0,horizon],event_count=truth[e['case']]['observed_count'],
                cpu_s=result.get('cpu_s'),wall_s=result.get('wall_s')))
    aggregates={}
    for prior in ('flat','soft'):
        core=[r for r in rows if r['prior']==prior and r['core_gate']!='NOT_CORE']
        issued=[v for r in core for v in r['conditional_intervals'] if v['issued']]
        widths=[v['width_s'] for v in issued]
        aggregates[prior]=dict(core_cases=len(core),core_pass=sum(r['core_gate']=='PASS' for r in core),
            matched=sum(r['matched'] for r in core),truth=sum(r['truth'] for r in core),predicted=sum(r['predicted'] for r in core),
            conditional_contained=sum(v['contained'] for v in issued),conditional_issued=len(issued),
            conditional_truth_total=sum(r['truth'] for r in core),conditional_median_width_s=percentile(widths,.5) if widths else None,
            conditional_p95_width_s=percentile(widths,.95) if widths else None,conditional_width_le4=sum(w<=4 for w in widths),
            unavailable=sum(r['status']!='complete_finite_posterior' for r in core))
    write('comparison.json',dict(rows=rows,aggregate=aggregates,tolerance_s=2,
        conditional_interval_warning='conditioned on truth count only after sealing; not a count recovery metric',original_2d1_gate='FAIL_UNCHANGED'))
    print(json.dumps(aggregates,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','evaluate'])
    {'prepare':prepare,'run':run,'evaluate':evaluate}[parser.parse_args().action]()
