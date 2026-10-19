"""Audit receipts, replay independent video truth, and export a standalone report."""
from __future__ import annotations

import argparse
from collections import Counter,defaultdict
import gzip
import hashlib
from html import escape
import json
from pathlib import Path
import statistics

from scripts.corpus_validation import ROOT,save,prepare_worker_environment
if __name__=='__main__':prepare_worker_environment()
import numpy as np
from scipy.optimize import linear_sum_assignment
from scripts.realistic_traffic_benchmark import score_prediction


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf8'))


def all_cases(evidence):
    cases=read(Path(evidence)/'synthetic/suite.json')['cases']
    extra=Path(evidence)/'synthetic/suite_extra.json'
    if extra.exists():cases=cases+read(extra)['cases']
    return cases


def without_samples(value):
    if isinstance(value,dict):return {k:without_samples(v) for k,v in value.items() if k not in ('samples','errors_s','traceback')}
    if isinstance(value,list):return [without_samples(v) for v in value]
    return value


def status(evidence):
    evidence=Path(evidence);inv=read(evidence/'inventory.json')
    result={}
    for folder,total in [('results',len(inv['jobs'])),('synthetic/results',len(all_cases(evidence)))]:
        rows=[read(p) for p in (evidence/folder).glob('*.json')]
        result[folder]=dict(done=len(rows),total=total,statuses=dict(Counter(r['status'] for r in rows)))
    return result


def rescore(evidence,runtime):
    evidence,runtime=Path(evidence),Path(runtime)
    cases=all_cases(evidence)
    for config in cases:
        case=config['id'];target=evidence/'synthetic/evaluation_v2'/f'{case}.json'
        if target.exists():continue
        receipt_path=evidence/'synthetic/results'/f'{case}.json'
        if not receipt_path.exists():raise ValueError(f'case not finished: {case}')
        receipt=read(receipt_path);product=runtime/'synthetic'/case
        output=dict(config=config,source_receipt_sha256=digest(receipt_path))
        try:
            raw=gzip.open(product/'truth.json.gz','rb').read()
            if hashlib.sha256(raw).hexdigest()!=receipt['truth_sha256']:raise ValueError('truth seal mismatch')
            truth=json.loads(raw)
            output['expected_phase_transitions']=sum(0<r['start_s']<config['duration_s'] for r in truth['signal_plan'])
            predictions=json.load(gzip.open(product/'predictions.json.gz','rt',encoding='utf8'))
            scores=[score_prediction(row['automatic']['result'],truth) for row in predictions if row['automatic']['status']=='ok']
            output.update(status='evaluated',scores=without_samples(scores),counts=truth['counts'],
                prediction_sha256=digest(product/'predictions.json.gz'),input_zip_sha256=receipt['input_zip_sha256'],
                truth_sha256=receipt['truth_sha256'],k_correct=bool(scores) and all(s['k_correct'] for s in scores),
                runtime_s=receipt['runtime_s'])
        except Exception as exc:
            output.update(status='failed',error=type(exc).__name__+': '+str(exc),k_correct=False)
        save(target,output)
        print(case,output['status'],flush=True)


def bracket_matches(predicted,brackets,tolerance):
    n,m=len(predicted),len(brackets)
    if not n or not m:return dict(matched=0,predicted=n,expected=m,precision=0 if n else None,recall=0 if m else None,pairs=[])
    distance=np.array([[max(a-p,0.,p-b) for a,b in brackets] for p in predicted])
    # Large invalid penalty maximizes cardinality before minimizing distance.
    left,right=linear_sum_assignment(np.where(distance<=tolerance,distance,1e9))
    pairs=[dict(prediction_ms=predicted[i],truth_interval_ms=brackets[j],distance_to_bracket_s=float(distance[i,j])/1000,
                midpoint_error_s=abs(predicted[i]-sum(brackets[j])/2)/1000)
        for i,j in zip(left,right) if distance[i,j]<=tolerance]
    return dict(matched=len(pairs),predicted=n,expected=m,precision=len(pairs)/n,recall=len(pairs)/m,
                midpoint_mae_s=statistics.mean(p['midpoint_error_s'] for p in pairs) if pairs else None,pairs=pairs)


def video_replay(evidence,runtime):
    from app.core.v10.estimated_signals import build_estimated_signals
    from app.core.v10.timing_profiles import resolve_timing_profile
    evidence,runtime=Path(evidence),Path(runtime);inv=read(evidence/'inventory.json')
    jobs=[j for j in inv['jobs'] if j['source_name']=='17_2025_2_27_10.json']
    if len(jobs)!=1:raise ValueError('exact independent-clock video source required')
    job=jobs[0];truth_path=ROOT/'evidence/yellow_timing_20261019/sverdlovsky/fresh_truth_sealed.json'
    truth=read(truth_path)['rows'];window=[3300,3600]
    # Frozen independent clock; physical exposure accuracy remains uncalibrated.
    clock_origin=1740632395000+1.253838016213823*1000
    a,b=[clock_origin+t*1000 for t in window]
    learned=json.load(gzip.open(runtime/f"{job['id']}_production_learned.json.gz",'rt',encoding='utf8'))
    baseline=json.load(gzip.open(runtime/f"{job['id']}_predictions.json.gz",'rt',encoding='utf8'))
    calibration=resolve_timing_profile(job['path'],job['source_name'],job['site'])
    modes={}
    sources={
        'automatic_known_hardware_uncalibrated':[r['automatic']['result'] for r in baseline if r['automatic']['status']=='ok'],
        'learned_known_hardware_uncalibrated':[c['result'] for r in learned for c in r['learned'].get('chunks',[]) if c['status']=='ok'],
        'learned_known_hardware_exact_source_calibration':[c['result'] for r in learned for c in r['learned'].get('chunks',[]) if c['status']=='ok'],
    }
    for name,results in sources.items():
        onsets=defaultdict(list);available=[]
        for result in results:
            estimate=build_estimated_signals(result,profile_id='lenina_sverdlovsky',
                boundary_calibration=calibration if name.endswith('exact_source_calibration') else None)
            available.append(dict(available=estimate['available'],reason=estimate.get('reason')))
            if not estimate['available']:continue
            states={s['id']:s for s in estimate['states']};segments=estimate['segments'];base=result['schedule_base_timestamp_ms']
            for previous,current in zip(segments,segments[1:]):
                if previous[1]!=current[0]:continue
                before=states[previous[2]]['heads']['N']['main']['state'];after=states[current[2]]['heads']['N']['main']['state']
                t=base+current[0]*1000
                if before!=after and a<t<b:onsets[after].append(t)
        metrics={}
        for color in ('GREEN','YELLOW','RED'):
            rows=[r for r in truth if r['color']==color]
            metrics[color]={}
            for scope,key in [('fixed_clock','json_bracket_fixed_clock_ms'),('conditional_clock_envelope','json_bracket_conditional_envelope_ms')]:
                intervals=[r['clock_mapping'][key] for r in rows]
                metrics[color][scope]={str(t):bracket_matches(onsets[color],intervals,t*1000) for t in (.5,1,2,3)}
        modes[name]=dict(mapping_availability=available,metrics=metrics,predicted_onsets_ms=dict(onsets))
    output=dict(source=job,truth_sha256=digest(truth_path),video_pts_window_s=window,modes=modes,
        replay_semantics='previously inspected same-session truth; rerun, NOT a fresh independent holdout',
        inference_input='cached trajectory events and frozen model/config only; truth read exclusively by evaluator',
        limitation='N main only, three cycles, conditional geometry/identity clock. No universal or other-day lamp accuracy claim.',
        enthusiasts='video yellow durations inform simulation; JSON/video clock unresolved, paired signal accuracy unavailable',
        chicherina='public video returns empty download body; user also unable to download; no direct lamp truth')
    save(evidence/'visible_head_replay.json',output)
    return output


def manual_replay(evidence,runtime):
    """Frozen chronological operator holdouts, never used in a predictor call."""
    from app.core.offline_benchmark import evaluate_prediction,validate_annotation
    from app.core.manual_delay_evaluation import evaluate_reaction_bound
    evidence,runtime=Path(evidence),Path(runtime);inv=read(evidence/'inventory.json')
    rows=[]
    for name in ('17_2025_2_19_10','19_2025_2_24_16','6_2025_2_14_20'):
        job=next(j for j in inv['jobs'] if j['source_name']==name+'.json')
        annotation_path=ROOT/'benchmarks/learned_profile_20261018/heldout'/f'{name}_v9.json'
        original=read(annotation_path)
        annotation=dict(start_ms=original['start_ms'],marks=[dict(timestamp_ms=m['timestamp_ms'],kind=m['kind']) for m in original['marks']])
        first,last=annotation['marks'][0]['timestamp_ms'],annotation['marks'][-1]['timestamp_ms']
        old=json.load(gzip.open(runtime/f"{job['id']}_predictions.json.gz",'rt',encoding='utf8'))
        new=json.load(gzip.open(runtime/f"{job['id']}_production_learned.json.gz",'rt',encoding='utf8'))
        modes={}
        for mode,possibilities in [('automatic',[r['automatic']['result'] for r in old if r['automatic']['status']=='ok']),
            ('learned',[c['result'] for r in new for c in r.get('learned',{}).get('chunks',[]) if c['status']=='ok'])]:
            covering=[r for r in possibilities if r['schedule_base_timestamp_ms']<=first and
                r['schedule_base_timestamp_ms']+max(b for a,b,z in r['schedule']['raw_hsmm_segments'])*1000>=last]
            if len(covering)!=1:modes[mode]=dict(status='unavailable',reason='NO_SINGLE_PREDICTION_COVERS_FROZEN_HOLDOUT');continue
            result=covering[0]
            modes[mode]=dict(status='evaluated',strict=evaluate_prediction(result,validate_annotation(annotation)),
                reaction_delay_0_3s=evaluate_reaction_bound(result,annotation),
                prediction_window='full-source production window, not refit to annotation bounds')
        rows.append(dict(source=job,annotation_sha256=digest(annotation_path),variants=modes,
            scope='previously frozen second-half operator marks; 0..3s reaction lag, NOT direct lamp truth'))
    output=dict(rows=rows,prediction_receives_annotations=False,profiles_retrained=False,
                scope='repeat on full-source inference; not a new independent holdout')
    save(evidence/'manual_marks_replay.json',output)
    return output


def witness(evidence,runtime):
    from scripts.realistic_traffic_benchmark import split_empty_phase,movement_signal_plan
    evidence,runtime=Path(evidence),Path(runtime)
    folder=runtime/'synthetic/k3_starved'
    truth=json.load(gzip.open(folder/'truth.json.gz','rt',encoding='utf8'))
    alternate=split_empty_phase(truth)
    observed=sorted({v['movement'] for v in truth['vehicle_crossings']})
    for movement in observed:
        def intervals(plan):
            phases={i for i,g in enumerate(plan['groups']) if movement in g}
            return [(r['start_s'],r['end_s'],r['green_end_s'],r['yellow_end_s'])
                for r in movement_signal_plan(plan['signal_plan'],phases)]
        if intervals(truth)!=intervals(alternate):raise AssertionError('observed signal schedule changed')
    alt_path=evidence/'nonidentifiability_alternate_plan.json'
    save(alt_path,{k:alternate[k] for k in ('base_ms','config','groups','signal_plan')})
    output=dict(case='k3_starved',same_raw_input_zip_sha256=digest(folder/'input.zip'),
        primary_truth_sha256=read(evidence/'synthetic/results/k3_starved.json')['truth_sha256'],
        alternate_plan_sha256=digest(alt_path),original_k=3,alternate_k=4,
        observed_movements=observed,observed_signal_intervals_exactly_equal=True,
        empty_movements=truth['groups'][-1],
        semantics='constructive counterexample from absent traffic; same input for both plans, not a 73rd independent case',
        chronology='constructed after primary predictions; no new fit, tuning, or independent held-out accuracy claim',
        conclusion='No trajectory-only deterministic predictor can identify both complete controller plans correctly from these identical observations.')
    save(evidence/'nonidentifiability_witness.json',output)
    return output


def aggregate(evidence):
    evidence=Path(evidence);inv=read(evidence/'inventory.json')
    rows=[];hashes=defaultdict(list);classes=Counter();total_tracks=total_detections=0
    archives={};samples=defaultdict(list)
    for job in inv['jobs']:
        path=evidence/'results'/f"{job['id']}.json"
        if not path.exists():raise ValueError(f'missing source receipt {job["id"]}')
        original=read(path);row=without_samples(original)
        stats=original.get('statistics',{});total_tracks+=stats.get('tracks',0);total_detections+=stats.get('detections',0)
        classes.update(stats.get('vehicle_classes',{}))
        for key,values in stats.get('samples',{}).items():samples[key].extend(values)
        if original.get('sha256'):hashes[original['sha256']].append(job['id'])
        archive=archives.setdefault(job['path'],dict(path=job['path'],members=0,statuses=Counter(),tracks=0,detections=0,
            automatic_statuses=Counter(),automatic_k=Counter(),learned_statuses=Counter(),sessions=0))
        archive['members']+=1;archive['statuses'][row['status']]+=1
        archive['tracks']+=stats.get('tracks',0);archive['detections']+=stats.get('detections',0)
        for p in row.get('predictions',[]):
            archive['sessions']+=1;archive['automatic_statuses'][p['automatic']['status']]+=1
            if p['automatic'].get('phase_count') is not None:archive['automatic_k'][str(p['automatic']['phase_count'])]+=1
        replay=evidence/'learned_replay'/f"{job['id']}.json"
        if not replay.exists():raise ValueError(f'missing production learned replay {job["id"]}')
        row['production_learned']=read(replay)
        for p in row['production_learned'].get('predictions',[]):archive['learned_statuses'][p['learned']['status']]+=1
        rows.append(row)
    synthetic=[];ordinary_samples=defaultdict(list);search_statuses=Counter();candidate_counts=Counter()
    for case in all_cases(evidence):
        path=evidence/'synthetic/evaluation_v2'/f"{case['id']}.json"
        if not path.exists():raise ValueError(f'missing synthetic evaluation {case["id"]}')
        synthetic.append(read(path))
        receipt=read(evidence/'synthetic/results'/f"{case['id']}.json")
        for prediction in receipt.get('predictions',[]):
            search=prediction['automatic'].get('model_selection',{}).get('search',{})
            search_statuses[search.get('search_status','unavailable')]+=1
            candidate_counts[str(search.get('attempted_candidate_count',0))]+=1
        if 'ordinary' in case['id']:
            for key,values in receipt.get('statistics',{}).get('samples',{}).items():ordinary_samples[key].extend(values)
    scored=[s for c in synthetic for s in c.get('scores',[])]
    k_correct=sum(c['k_correct'] for c in synthetic)
    transition={}
    for tolerance in ('.5','1','2','3'):
        key='0.5' if tolerance=='.5' else tolerance
        metrics=[s['transition_metrics'][key] for s in scored]
        matched=sum(m['matched'] for m in metrics);pred=sum(m['predicted'] for m in metrics)
        expected=sum(m['expected'] for m in metrics)+sum(c.get('expected_phase_transitions',0) for c in synthetic if not c.get('scores'))
        transition[key]=dict(matched=matched,predicted=pred,expected=expected,precision=matched/pred if pred else None,recall=matched/expected if expected else None)
    main_heads=[head for s in scored for head in s['production_main_heads']['heads'].values()]
    main_metrics={}
    for color in ('GREEN','YELLOW','RED'):
        main_metrics[color]={}
        for tolerance in ('0.5','1','2','3'):
            values=[h['onsets'][color][tolerance] for h in main_heads]
            matched=sum(v['matched'] for v in values);expected=sum(v['expected'] for v in values);predicted=sum(v['predicted'] for v in values)
            main_metrics[color][tolerance]=dict(matched=matched,expected=expected,predicted=predicted,
                precision=matched/predicted if predicted else None,recall=matched/expected if expected else None)
    summary=dict(schema='all-archive-and-realistic-synthetic-results-v1',inventory=inv,
        raw_tracks_including_duplicate_sources=total_tracks,raw_detections_including_duplicate_sources=total_detections,
        unique_content_sources=len(hashes),duplicate_content_sources=[ids for ids in hashes.values() if len(ids)>1],
        source_statuses=dict(Counter(r['status'] for r in rows)),archives=list(archives.values()),sources=rows,
        real_distributions=dict(vehicle_classes=dict(classes),sampling_scope='pooled bounded per-member reservoirs; source duplicates included here',
            quantiles={k:dict(zip(('p05','p25','p50','p75','p95'),map(float,np.quantile(v,[.05,.25,.5,.75,.95])))) for k,v in samples.items() if v}),
        synthetic=dict(cases=synthetic,total_cases=len(synthetic),k_correct=k_correct,k_accuracy=k_correct/len(synthetic),
            ordinary_distribution_quantiles={k:dict(zip(('p05','p25','p50','p75','p95'),map(float,np.quantile(v,[.05,.25,.5,.75,.95])))) for k,v in ordinary_samples.items() if v},
            statuses=dict(Counter(c['status'] for c in synthetic)),
            automatic_search_statuses=dict(search_statuses),automatic_attempted_candidate_counts=dict(candidate_counts),
            phase_count_confusion={str(k):dict(Counter(str(s['predicted_k']) for s in scored if s['expected_k']==k)) for k in (2,3,4,5)},
            period_absolute_error_s=dict(mean=float(np.mean([s['period_error_s'] for s in scored])) if scored else None,
                median=float(np.median([s['period_error_s'] for s in scored])) if scored else None),
            tracks=sum(c.get('counts',{}).get('tracks',0) for c in synthetic),
            detections=sum(c.get('counts',{}).get('detections',0) for c in synthetic),
            recording_hours=sum(c['config']['duration_s'] for c in synthetic)/3600,
            transition_metrics=transition,
            production_main_heads=dict(onsets=main_metrics,
                evaluated_head_seconds=sum(h['evaluated_s'] for h in main_heads),
                state_error_fraction=sum(h['error_fraction']*h['evaluated_s'] for h in main_heads)/sum(h['evaluated_s'] for h in main_heads) if main_heads else None,
                coverage_fraction=sum(h['coverage_fraction']*h['evaluated_s'] for h in main_heads)/sum(h['evaluated_s'] for h in main_heads) if main_heads else None,
                scope='actual production automatic physical projection, simulated four main heads; no truth/profile supplied to mapper'),
            cases_without_timing_score=[c['config']['id'] for c in synthetic if not c.get('scores')],
            state_error_fraction=(sum(s['phase_state_error_fraction']*s['evaluated_s'] for s in scored)+
                sum(c['config']['duration_s'] for c in synthetic if not c.get('scores')))/sum(c['config']['duration_s'] for c in synthetic),
            coverage_fraction=sum(s['coverage_fraction']*s['evaluated_s'] for s in scored)/sum(c['config']['duration_s'] for c in synthetic),
            groups={name:dict(cases=len([c for c in synthetic if name in c['config']['id']]),
                k_correct=sum(c['k_correct'] for c in synthetic if name in c['config']['id']))
                for name in ('ordinary','platoons','sparse','saturation','occlusion','yield_block','changing_cycle','nonzero_stops','starved','shared_main','four_hours','asymmetric_real_uturn','short_arrow_real_uturn')}),
        video=read(evidence/'visible_head_replay.json'),
        manual_marks=read(evidence/'manual_marks_replay.json'),
        nonidentifiability=read(evidence/'nonidentifiability_witness.json'),
        limitations=['Real unlabelled execution is not a lamp accuracy test.',
            'Learned K is supplied by training labels; automatic K is evaluated separately.',
            'Synthetic inputs are model-based assumptions, not new real-road ground truth.',
            'Video is not an inference input. Enthusiasts clock unresolved; Chicherina video inaccessible.'])
    return summary


def chart_payload(evidence,runtime):
    output=[];evidence,runtime=Path(evidence),Path(runtime)
    for case in all_cases(evidence):
        folder=runtime/'synthetic'/case['id'];score=read(evidence/'synthetic/evaluation_v2'/f"{case['id']}.json")
        if score['status']!='evaluated':continue
        truth=json.load(gzip.open(folder/'truth.json.gz','rt',encoding='utf8'))
        predictions=json.load(gzip.open(folder/'predictions.json.gz','rt',encoding='utf8'))
        success=[r['automatic']['result'] for r in predictions if r['automatic']['status']=='ok']
        if not success:continue
        r=success[0];base=(r['analysis_base_timestamp_ms']-truth['base_ms'])/1000
        mapping=score['scores'][0]['permutation_alignment']
        output.append(dict(id=case['id'],duration=case['duration_s'],
            truth=[[max(0,p['start_s']),min(case['duration_s'],p['end_s']),p['phase']] for p in truth['signal_plan'] if p['end_s']>0 and p['start_s']<case['duration_s']],
            prediction=[[a+base,b+base,mapping.get(str(int(z)),-1)] for a,b,z in r['schedule']['raw_hsmm_segments']]))
    return output


def render(summary,charts):
    syn=summary['synthetic']
    fmt=lambda n:f'{n:,}'.replace(',',' ')
    archive_rows=''.join('<tr><td>'+escape(Path(a['path']).name)+'</td><td>'+str(a['members'])+'</td><td>'+fmt(a['tracks'])+'</td><td>'+fmt(a['detections'])+'</td><td>'+escape(str(dict(a['automatic_k'])))+'</td></tr>' for a in summary['archives'])
    source_rows=''.join('<tr><td>'+r['job']['id']+'</td><td>'+escape(Path(r['job']['path']).name)+'</td><td>'+escape(r['job']['source_name'])+'</td><td>'+r['status']+'</td><td>'+escape(', '.join(str(p['automatic'].get('phase_count',p['automatic']['status'])) for p in r.get('predictions',[])))+'</td></tr>' for r in summary['sources'])
    case_rows=''.join('<tr><td>'+c['config']['id']+'</td><td>'+str(c['config']['k'])+'</td><td>'+(', '.join(str(s['predicted_k']) for s in c.get('scores',[])) or 'UNKNOWN')+'</td><td>'+('Да' if c['k_correct'] else 'Нет')+'</td><td>'+fmt(c.get('counts',{}).get('tracks',0))+'</td><td>'+fmt(c.get('counts',{}).get('detections',0))+'</td><td>'+(', '.join(f"{100*s['coverage_fraction']:.1f}%" for s in c.get('scores',[])))+'</td><td><a href="../../.web_runtime/all_archives_synthetic_20261019/synthetic/'+c['config']['id']+'/input.zip">input.zip</a></td></tr>' for c in syn['cases'])
    transition_rows=''.join(f'<tr><td>±{key} с</td><td>{m["matched"]} / {m["expected"]}</td><td>{m["matched"]} / {m["predicted"]}</td><td>{100*(m["recall"] or 0):.1f}%</td><td>{100*(m["precision"] or 0):.1f}%</td></tr>' for key,m in syn['transition_metrics'].items())
    main_rows=''
    for color,values in syn['production_main_heads']['onsets'].items():
        m=values['2'];main_rows+=f'<tr><td>{color}</td><td>{m["matched"]}/{m["expected"]}</td><td>{m["matched"]}/{m["predicted"]}</td><td>{100*(m["recall"] or 0):.1f}%</td><td>{100*(m["precision"] or 0):.1f}%</td></tr>'
    video_rows=''
    for mode,value in summary['video']['modes'].items():
        for color,metrics in value['metrics'].items():
            m=metrics['fixed_clock']['0.5'];mae=m.get('midpoint_mae_s')
            video_rows+=f'<tr><td>{escape(mode)}</td><td>{color}</td><td>{m["matched"]}/{m["expected"]}</td><td>{m["predicted"]}</td><td>{mae:.3f} с</td></tr>' if mae is not None else f'<tr><td>{escape(mode)}</td><td>{color}</td><td>{m["matched"]}/{m["expected"]}</td><td>{m["predicted"]}</td><td>—</td></tr>'
    fidelity_rows=''
    for key,label in [('detection_step_s','Шаг детекций, с'),('track_duration_s','Длительность трека, с'),('raw_speed','Числовое поле speed'),('wait_metadata_s','Поле ожидания, с')]:
        a=summary['real_distributions']['quantiles'].get(key,{})
        b=syn['ordinary_distribution_quantiles'].get(key,{})
        fidelity_rows+='<tr><td>'+label+'</td><td>'+' / '.join(f'{a.get(q,float("nan")):.3f}' for q in ('p05','p50','p95'))+'</td><td>'+' / '.join(f'{b.get(q,float("nan")):.3f}' for q in ('p05','p50','p95'))+'</td></tr>'
    manual_rows=''
    for row in summary['manual_marks']['rows']:
        for mode,value in row['variants'].items():
            if value['status']!='evaluated':
                manual_rows+=f'<tr><td>{escape(row["source"]["source_name"])}</td><td>{mode}</td><td colspan="3">{escape(value.get("reason",value["status"]))}</td></tr>'
                continue
            metric=value['strict']['histories']['raw_hsmm_segments']['boundaries']['mae_s']
            reaction=value['reaction_delay_0_3s']
            manual_rows+=f'<tr><td>{escape(row["source"]["source_name"])}</td><td>{mode}</td><td>{metric["matched_boundaries"]}/{metric["truth_boundaries"]}</td><td>{metric["predicted_boundaries"]}</td><td>{reaction["compatible_boundaries"]}/{reaction["truth_boundaries"]}</td></tr>'
    payload=json.dumps(charts,separators=(',',':')).replace('<','\\u003c')
    page='''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Traffic Phase — проверка всех архивов</title>
<style>body{margin:0;background:#10151e;color:#e5edf8;font:16px/1.5 system-ui}main{max-width:1200px;margin:auto;padding:24px}h1{font-size:30px}h2{margin-top:36px}.box{padding:18px;background:#1c2736;border-radius:12px;margin:14px 0}.warn{border-left:5px solid #efb458}.good{border-left:5px solid #58d5a2}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}.big{font-size:27px;font-weight:700}table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:9px;text-align:left;border-bottom:1px solid #344357;vertical-align:top}th{background:#26344a}a{color:#84c8ff}.scroll{overflow:auto}select,input,button{font:inherit;max-width:100%;padding:8px;background:#26344a;color:#fff;border:1px solid #6a7d98;border-radius:6px}canvas{display:block;width:100%;height:180px}code{overflow-wrap:anywhere}small{color:#adbed2}</style>
<main><h1>Проверка всех архивов и реалистичной синтетики</h1>
<div class="box warn"><strong>Универсальная точность пока не доказана.</strong> Боевой прогноз получает JSON/ZIP с траекториями. Видео нужно только для независимой проверки. Обученный режим дополнительно использует заранее подготовленный профиль перекрёстка.</div>
<div class="grid">__CARDS__</div>
<h2>Что именно проверено</h2><p>Все 216 транспортных JSON из шести архивов и три отдельных источника. Каждый файл прочитан полностью и хеширован; отдельные сеансы не объединены. Исторические результаты, ручная разметка и два ZIP с кодом/тестами не считаются новым транспортным наблюдением.</p>
<div class="box">Автоматический режим сам ищет 2–6 фаз. Обученный режим использует число и состав фаз из прежнего обучения. Успешный запуск на архиве без независимой разметки показывает работоспособность обработки, а не процент точности ламп.</div>
<div class="scroll"><table><thead><tr><th>Источник</th><th>JSON</th><th>Треки</th><th>Детекции</th><th>Распределение K автоматического режима</th></tr></thead><tbody>__ARCHIVES__</tbody></table></div>
<h2>Синтетика: очереди и причинная модель движения</h2><p>Параметры датчика и классы машин взяты из выборок всех шести архивов. Светофорный план задаётся раньше движения машин. Есть ускорение, торможение, очереди, задержка реакции, поворот с уступанием, блокировка выезда, пропуски, дубли, разрывы ID, редкий поток и смена цикла. Жёлтый 3 с согласуется с доступными видеометками; остальные физические параметры симулятора — явно указанные предположения.</p>
<p>Ни видео, ни истинные фазы не подаются алгоритму. Неизвестные/непокрытые интервалы включены в ошибку за полную запись; число правильных K делится на все сценарии. Состояния и включения физических цветов сравниваются на сетке 0,25 с; логические границы сравниваются по исходным временам. Результат симуляции не заменяет проверку на новом реальном перекрёстке.</p>
<div class="scroll"><table><thead><tr><th>Распределение</th><th>Реальные p05 / p50 / p95</th><th>Обычные синтетические p05 / p50 / p95</th></tr></thead><tbody>__FIDELITY__</tbody></table></div><p><small>Пулы ограниченных выборок, не точные квантили всех детекций. Единицы speed поставщика не подтверждены; в симуляторе заданы км/ч. Различия показаны явно. Перегрузка, аварийные остановки и пропуски вынесены в стресс-сценарии. Два сценария starved специально не содержат машин одной из фаз: её состав принципиально не наблюдается. Они включены в общий знаменатель и выделены отдельной группой в JSON.</small></p>
<div class="scroll"><table><thead><tr><th>Допуск границы логической фазы</th><th>Найдено / истинных</th><th>Подтверждено / предсказаний</th><th>Полнота</th><th>Точность предсказаний</th></tr></thead><tbody>__TRANSITIONS__</tbody></table></div>
<div class="box warn">Проверен конструктивный пример: один и тот же входной ZIP совместим с планами на 3 и 4 фазы. Два направления пустуют, а интервалы сигналов всех наблюдаемых машин в обоих планах совпадают точно. Это предел наблюдаемости, а не дополнительный успешный тест алгоритма. <a href="nonidentifiability_witness.json">Проверяемый пример и хеши</a>.</div>
<h2>Цвета основных сигналов в симуляции</h2><p>Здесь вызван настоящий автоматический проектор приложения без профиля известного перекрёстка. Схема симулятора используется только при сравнении; если приложение не определило секцию или интервал, прогноз UNKNOWN. Таблица: включения основных GREEN/YELLOW/RED в допуске ±2 с. Дополнительные стрелки в этот физический показатель не включены.</p><div class="scroll"><table><thead><tr><th>Сигнал</th><th>Найдено / истинных</th><th>Подтверждено / предсказаний</th><th>Полнота</th><th>Точность предсказаний</th></tr></thead><tbody>__MAIN_HEADS__</tbody></table></div>
<h2>Посмотреть результат</h2><p>Цвета обозначают логические фазы, не лампы. Строка «Истина» задана симулятором; строка «Прогноз» построена только из траекторий. Анонимные номера фаз сопоставлены исключительно при оценке. Серый означает отсутствие сопоставленной фазы.</p>
<label>Сценарий <select id="case"></select></label><p><label>Начало окна <input id="time" type="range" min="0" value="0" step="10"><span id="position"></span></label></p><canvas id="timeline"></canvas>
<p>В таблице доступны локальные ZIP для загрузки в приложение: внутри только траектории, без правильных ответов. ZIP сохранены в .web_runtime этого рабочего каталога; при переносе одного отчёта их нужно перенести отдельно.</p><div class="scroll"><table><thead><tr><th>Сценарий</th><th>Истинное K</th><th>Прогноз K</th><th>Совпало</th><th>Треки</th><th>Детекции</th><th>Покрытие логической истории</th><th>Входной ZIP</th></tr></thead><tbody>__CASES__</tbody></table></div>
<h2>Независимо видимый светофор</h2><p>Повторная проверка прежних 9 меток основного N на Свердловском, 3 цикла. Это та же запись, а не новый независимый день. Привязка часов условна по геометрии/идентичности машин; погрешность физической экспозиции камеры не сертифицирована. Поправки не перенесены на другие архивы.</p>
<div class="scroll"><table><thead><tr><th>Режим</th><th>Цвет</th><th>В 0,5 с от видеобрекета</th><th>Всего предсказаний</th><th>MAE до середины совпавших меток</th></tr></thead><tbody>__VIDEO__</tbody></table></div>
<p><strong>Строка exact_source_calibration — только ретроспективный диагностический контроль:</strong> она использует прежнюю видеопоправку для этой конкретной записи. Она исключена из оценки универсального алгоритма без видео. Первичная оценка — automatic, без таких поправок.</p>
<p>Энтузиастов: видеометки подтверждают длительность жёлтого, но независимая связь часов JSON/видео пока не принята. Чичерина: Яндекс отдаёт пустое тело видео; пользователь также не смог скачать файл. Прямой разметки ламп нет.</p>
<h2>Прежняя ручная разметка: повторная проверка</h2><p>Замороженные вторые половины трёх ручных разметок, допуск ±2 с. Отдельно показано попадание в заявленный интервал задержки реакции [метка −3 с; метка]. Это операторские фазы, а не точные физические переключения. Совпадение с меткой в ±2 с может лежать позже неё и не попасть в интервал реакции. Прогноз получен по полной записи без передачи контрольных меток; новые модели не обучались.</p><div class="scroll"><table><thead><tr><th>Источник</th><th>Режим</th><th>В ±2 с / границ</th><th>Предсказаний</th><th>В интервале реакции / границ</th></tr></thead><tbody>__MANUAL__</tbody></table></div>
<h2>Все источники</h2><label>Поиск <input id="filter" placeholder="Дата, архив или имя JSON"></label><div class="scroll"><table id="sources"><thead><tr><th>ID</th><th>Архив</th><th>JSON</th><th>Статус</th><th>Автоматическое K</th></tr></thead><tbody>__SOURCES__</tbody></table></div>
<p><a href="summary.json">Полные машиночитаемые результаты</a> · <a href="manifest_v2.json">Хеши и состав материалов с QA</a> · <a href="visible_head_replay.json">Проверка видимого светофора</a> · <a href="browser/receipt.json">Проверка браузера</a></p>
<small>Алгоритм фаз и main сохранены. В обычном просмотре отключена поправка, полученная из видео конкретного архива. Этот комплект измеряет ограничения текущей версии; он не объявляет программу универсально точной.</small></main>
<script>const charts=__DATA__;const choice=document.querySelector('#case'),slider=document.querySelector('#time'),canvas=document.querySelector('#timeline');const colors=['#66d3a2','#6ca7f7','#efbd69','#d586ed','#f47e88'];for(const c of charts){const o=document.createElement('option');o.value=c.id;o.textContent=c.id;choice.append(o)}function draw(){const c=charts.find(c=>c.id===choice.value);if(!c)return;slider.max=Math.max(0,c.duration-600);const a=+slider.value,b=Math.min(c.duration,a+600);document.querySelector('#position').textContent=` ${a}–${b} с`;const r=canvas.getBoundingClientRect(),d=devicePixelRatio||1;canvas.width=r.width*d;canvas.height=180*d;const x=canvas.getContext('2d');x.scale(d,d);x.fillStyle='#172130';x.fillRect(0,0,r.width,180);const left=90,width=r.width-left-10;['Истина','Прогноз'].forEach((label,i)=>{x.fillStyle='#e5edf8';x.fillText(label,5,45+i*65)});[c.truth,c.prediction].forEach((rows,i)=>{for(const [lo,hi,z]of rows){if(hi<=a||lo>=b)continue;x.fillStyle=colors[z]||'#677180';x.fillRect(left+(Math.max(a,lo)-a)/(b-a)*width,20+i*65,(Math.min(b,hi)-Math.max(a,lo))/(b-a)*width,42)}});x.fillStyle='#adbed2';for(let t=a;t<=b;t+=100)x.fillText(t+'с',left+(t-a)/(b-a)*width,165)}choice.onchange=()=>{slider.value=0;draw()};slider.oninput=draw;window.onresize=draw;draw();document.querySelector('#filter').oninput=e=>{const q=e.target.value.toLowerCase();for(const r of document.querySelectorAll('#sources tbody tr'))r.hidden=!r.textContent.toLowerCase().includes(q)};</script></html>'''
    cards=[('Источников',len(summary['sources'])),('Реальных треков, включая дубли источников',summary['raw_tracks_including_duplicate_sources']),
        ('Синтетических треков',syn['tracks']),('Синтетических детекций',syn['detections']),('Число фаз совпало',f'{syn["k_correct"]}/{syn["total_cases"]}'),
        ('Ошибка логической фазы за полную запись',f'{100*syn["state_error_fraction"]:.1f}%'),
        ('Ошибка цветов четырёх основных сигналов',f'{100*syn["production_main_heads"]["state_error_fraction"]:.1f}%'),
        ('Покрытие цветов основных сигналов',f'{100*syn["production_main_heads"]["coverage_fraction"]:.1f}%')]
    substitutions={'__CARDS__':''.join(f'<div class="box"><div>{escape(label)}</div><div class="big">{fmt(value) if isinstance(value,int) else value}</div></div>' for label,value in cards),
        '__ARCHIVES__':archive_rows,'__CASES__':case_rows,'__TRANSITIONS__':transition_rows,'__SOURCES__':source_rows,'__VIDEO__':video_rows,
        '__FIDELITY__':fidelity_rows,'__MANUAL__':manual_rows,'__MAIN_HEADS__':main_rows,'__DATA__':payload}
    for key,value in substitutions.items():page=page.replace(key,value)
    return page


def finalize(evidence,runtime):
    evidence,runtime=Path(evidence),Path(runtime)
    summary=aggregate(evidence)
    save(evidence/'summary.json',summary)
    with (evidence/'report.html').open('x',encoding='utf8',newline='\n') as stream:stream.write(render(summary,chart_payload(evidence,runtime)))
    # Receipts remain local even when large reservoirs are not committed. Hash
    # each one; small summary/manifest are the versioned review package.
    paths=[p for p in evidence.rglob('*') if p.is_file() and p.name!='manifest.json']
    save(evidence/'manifest.json',dict(schema='validation-artifact-manifest-v1',
        files=[dict(path=str(p.relative_to(evidence)).replace('\\','/'),bytes=p.stat().st_size,sha256=digest(p)) for p in sorted(paths)],
        solver_scope='phase solvers/profiles unchanged; normal viewer excludes reference-video bias; automatic permission_per_stream plus frozen learned profiles',
        code_files=[dict(path=str(p.relative_to(ROOT)).replace('\\','/'),sha256=digest(p)) for p in
            [ROOT/'scripts/corpus_validation.py',ROOT/'scripts/realistic_traffic_benchmark.py',ROOT/'scripts/validation_report.py',ROOT/'scripts/qa_corpus_validation.py',ROOT/'tests/test_corpus_realistic_validation.py',ROOT/'docs/ALL_ARCHIVES_SYNTHETIC_PROTOCOL_20261019.md',
             ROOT/'app/core/learned_visualization.py',ROOT/'app/api/learned_visualization.py']],
        raw_inputs='local ../data; input member hashes retained in summary',runtime_archives='local ignored .web_runtime/all_archives_synthetic_20261019/synthetic; hashes retained in summary'))
    print(json.dumps({k:summary['synthetic'][k] for k in ('total_cases','tracks','detections','k_correct','transition_metrics')},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['status','rescore','video','manual','witness','finalize'])
    parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.command=='status':print(json.dumps(status(args.evidence),ensure_ascii=False))
    else:globals()[{'video':'video_replay','manual':'manual_replay','witness':'witness','rescore':'rescore','finalize':'finalize'}[args.command]](args.evidence,args.runtime)


if __name__=='__main__':main()
