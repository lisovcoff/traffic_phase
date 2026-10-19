"""Queue/kinematics simulation and an untouched trajectory-only solver benchmark.

Ground truth is a separate simulator output, sealed before the solver runs.
This is a controlled model of roads, not a certificate of real-road accuracy.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time
import traceback
import zipfile

from scripts.corpus_validation import CorpusStats, ROOT, compact_predictions, predict_modes, save,prepare_worker_environment

if __name__=='__main__':prepare_worker_environment()
import numpy as np
from scipy.optimize import linear_sum_assignment

BASE_MS = 1_800_000_000_000
GROUPS = {
    2: [['N->_S','S->_N'],['E->_W','W->_E']],
    3: [['N->_S','S->_N'],['N->_E','E->_N'],['E->_W','W->_E']],
    4: [['N->_S'],['E->_W'],['S->_N'],['W->_E']],
    5: [['N->_S'],['E->_W'],['S->_N'],['W->_E'],['N->_E']],
}
DIRECTIONS = {'N':np.array([0.,1.]),'S':np.array([0.,-1.]),
              'E':np.array([1.,0.]),'W':np.array([-1.,0.])}


def fit_environment(ingest_dir):
    """Use traffic distributions only; never predicted phase boundaries."""
    values, classes = defaultdict(list), Counter()
    sources, tracks, detections = [], 0, 0
    for path in sorted(Path(ingest_dir).glob('*.json')):
        item = json.loads(path.read_text(encoding='utf8'))
        stats = item['statistics']
        # Equal file content does not supply extra independent evidence.
        if item.get('sha256') and any(s['sha256']==item['sha256'] for s in sources):
            continue
        sources.append(dict(id=item['job']['id'], sha256=item.get('sha256'),
            sample_scope=item.get('sample_scope','complete member'), job=item['job'],
            prefix_sha256=item.get('prefix_sha256')))
        tracks += stats['tracks']; detections += stats['detections']
        classes.update(stats['vehicle_classes'])
        for key, sample in stats['samples'].items():
            values[key].extend(sample)
    if not sources:
        raise ValueError('real-source ingestion receipts are required before simulation')
    step = [v for v in values['detection_step_s'] if .03<=v<=1.]
    speed = [v for v in values['raw_speed'] if 5<=v<=90]
    video=[]
    for site in ('sverdlovsky','enthusiasts'):
        path=ROOT/'evidence/yellow_timing_20261019'/site/'fresh_truth_sealed.json'
        labels=json.loads(path.read_text(encoding='utf8'))['rows']
        yellow=[r['bracket_s'] for r in labels if r['color']=='YELLOW' and r.get('bracket_s')]
        red=[r['bracket_s'] for r in labels if r['color']=='RED' and r.get('bracket_s')]
        intervals=[]
        for a,b in yellow:
            following=[(c,d) for c,d in red if b<c<b+6]
            if following:
                c,d=min(following);intervals.append([c-b,d-a])
        video.append(dict(site=site,source=str(path.relative_to(ROOT)),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                          observed_yellow_duration_bounds_s=intervals,
                          use='video-only duration corroboration; no video access by inference; no Enthusiasts JSON clock assumed'))
    return dict(schema='traffic-simulation-environment-v1',sources=sources,tracks=tracks,detections=detections,
        detection_step_quantiles_s=np.quantile(step,[.1,.25,.5,.75,.9]).tolist(),
        positive_raw_speed_quantiles=np.quantile(speed,[.1,.25,.5,.75,.9]).tolist(),
        raw_speed_units='unknown in supplier data; simulator explicitly uses km/h',
        vehicle_classes=dict(classes),
        track_duration_quantiles_s=np.quantile(values['track_duration_s'],[.1,.25,.5,.75,.9]).tolist(),
        video_duration_evidence=video,
        calibration_scope='bounded per-member traffic reservoirs; source files deduplicated; NO phase predictions or truth used',
        physical_assumptions=dict(yellow_s=3.,red_yellow_s=2.,startup_delay_s=[.8,3.5],
            acceleration_mps2=[1.1,2.5],deceleration_mps2=3.,standstill_gap_m=6.5,
            reaction_headway_s=[.8,1.6],note='reaction/geometry/headways are simulator assumptions, not measured ground truth'))


def signal_plan(config):
    rng = random.Random(config['seed'] ^ 0x51A9)
    k, duration, nominal = config['k'], config['duration_s'], config['period_s']
    # Durations vary independently of demand. No traffic observation defines GT.
    proportions = np.asarray([rng.uniform(.7,1.3) for _ in range(k)])
    if config.get('phase_weights'):proportions=np.asarray(config['phase_weights'],dtype=float)
    proportions /= proportions.sum()
    rows=[];cursor=-2*nominal;cycle=0
    while cursor<duration+nominal:
        multiplier = 1.18 if config.get('regime_change') and cursor>=duration/2 else 1.
        period=nominal*multiplier*(1+rng.uniform(-config.get('cycle_jitter',0),config.get('cycle_jitter',0)))
        for phase in range(k):
            end=cursor+period*float(proportions[phase])
            all_red=float(config.get('all_red_s',1.))
            rows.append(dict(start_s=cursor,end_s=end,phase=phase,
                             green_end_s=end-3-all_red,yellow_end_s=end-all_red,cycle=cycle))
            cursor=end
        cycle+=1
    return rows


def signal_at(plan, phase, second):
    starts=[r['start_s'] for r in plan]
    i=int(np.searchsorted(starts,second,side='right'))-1
    row=plan[max(0,min(i,len(plan)-1))]
    if row['phase']==phase:
        if second<row['green_end_s']:return 'GREEN',row['start_s']
        if second<row['yellow_end_s']:return 'YELLOW',row['start_s']
    nxt=plan[i+1] if 0<=i+1<len(plan) else None
    if nxt and nxt['phase']==phase and second>=nxt['start_s']-2:
        return 'RED_YELLOW',nxt['start_s']
    return 'RED',row['start_s']


def movement_signal_plan(plan, phases):
    """A continuing main green does not turn yellow at an arrow-only change."""
    runs=[]
    for row in plan:
        if row['phase'] not in phases:continue
        if runs and abs(runs[-1]['end_s']-row['start_s'])<1e-7:
            runs[-1].update(end_s=row['end_s'],green_end_s=row['green_end_s'],yellow_end_s=row['yellow_end_s'])
        else:runs.append({**row,'phase':0})
    return runs


def movement_color_at(runs, second):
    for row in runs:
        if row['start_s']<=second<row['green_end_s']:return 'GREEN',row['start_s']
        if row['green_end_s']<=second<row['yellow_end_s']:return 'YELLOW',row['start_s']
        if row['start_s']-2<=second<row['start_s']:return 'RED_YELLOW',row['start_s']
    return 'RED',second


def project(movement, distances, geometry, *, return_world=False):
    source,target=movement.split('->');target=target.lstrip('_')
    origin,exit=DIRECTIONS[source],DIRECTIONS[target]
    x=np.asarray(distances)
    xy=np.where((x<0)[:,None],-x[:,None]*origin,x[:,None]*exit)
    # Smooth intersection traversal on a quadratic curve over 40m of arc.
    mask=(x>-20)&(x<20)
    u=(x[mask]+20)/40
    xy[mask]=(1-u[:,None])**2*20*origin+u[:,None]**2*20*exit
    if source==target:
        normal=np.array([-origin[1],origin[0]])
        xy+=np.tanh(x[:,None]/9)*3.25*normal
    if return_world:return xy
    theta,skew,depth=geometry
    rotate=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    xy=xy@rotate.T
    denominator=1+depth*xy[:,1]/250
    return np.column_stack((.5+(xy[:,0]+skew*xy[:,1])/400/denominator,
                            .5+xy[:,1]/400/denominator))


def generate(config, environment):
    """Simulate independent FIFO lanes with acceleration and car-following.

    Movements are separate lanes (no invented lane-changing physics). Signal
    phases and downstream blocking are hidden from exported detections.
    """
    rng=random.Random(config['seed']); nrng=np.random.default_rng(config['seed'])
    groups=[list(g) for g in GROUPS[config['k']]]; plan=signal_plan(config)
    if config.get('shared_stream'):groups[1].append(groups[0][0])
    if config.get('uturn'):groups[1 if config['k']==2 else 2].append('E->_E')
    duration=config['duration_s'];step=.2
    geometry=(rng.uniform(-math.pi,math.pi),rng.uniform(-.3,.3),rng.uniform(-.45,.45))
    fov_start,fov_end=-rng.uniform(25,90),rng.uniform(20,70)
    classes=list(environment['vehicle_classes']);weights=list(environment['vehicle_classes'].values())
    tracks=[];vehicle_truth=[];identifier=0;det_count=0;crossing_calendar={}
    blocked=float(config.get('blocking',0));drop=float(config.get('dropout',0))
    for phase,group in enumerate(groups):
        for lane,movement in enumerate(group):
            phases={p for p,other in enumerate(groups) if movement in other}
            if phase!=min(phases):continue
            lamp_runs=movement_signal_plan(plan,phases)
            zin,zout=movement.split('->');uturn=zin==zout.lstrip('_')
            lane_rate=config['arrival_rate_s']*rng.uniform(.75,1.25)
            if uturn:lane_rate*=.15
            if config.get('starved') and phase==config['k']-1:lane_rate=0
            arrivals=[];cursor=-120.
            while lane_rate and cursor<duration:
                # Upstream signals produce platoons, independently of this
                # intersection's phase clock. A refractory gap avoids overlaps.
                cursor+=max(.8,rng.expovariate(lane_rate))
                if config.get('platoons'):
                    cursor+=max(0.,8-(cursor%47)) if cursor%47<8 else 0
                arrivals.append(cursor)
            ai=0;active=[];completed=[]
            for ti in range(int((duration+120)/step)+1):
                second=-120+ti*step
                while ai<len(arrivals) and arrivals[ai]<=second:
                    identifier+=1
                    category=rng.choices(classes,weights=weights)[0]
                    heavy=any(v in category for v in ('bus','truck','train','tram'))
                    desired=max(4.,min(19.,rng.choice(environment['positive_raw_speed_quantiles'])/3.6))
                    if config.get('realistic_turns') and DIRECTIONS[zin].dot(DIRECTIONS[zout.lstrip('_')])>-.5:desired=min(desired,7.)
                    position=min(-120.,active[-1]['x']-9 if active else -120.)
                    active.append(dict(id=identifier,x=position,v=desired,desired=desired,
                        acceleration=rng.uniform(1.1,2.5)*(.65 if heavy else 1),
                        reaction=rng.uniform(.8,3.5),headway=rng.uniform(.8,1.6),category=category,
                        history=[],crossed=False,crossing_s=None,stopped_s=0.,stop_started=None))
                    ai+=1
                color,onset=movement_color_at(lamp_runs,second)
                leader=None
                for car in active:
                    old_x,old_v=car['x'],car['v']
                    gap=(leader['x']-car['x']-6.5) if leader else float('inf')
                    allowed=color=='GREEN' and (old_v>.2 or second>=onset+car['reaction'])
                    if color=='YELLOW' and -old_x<old_v*old_v/6+old_v*.8:allowed=True
                    # A permissive turn may wait while its signal is green.
                    if config.get('realistic_turns'):
                        conflicts=crossing_calendar.get('W->_E',[])
                        i=bisect_left(conflicts,second-3.)
                        yielding=uturn and i<len(conflicts) and conflicts[i]<second+4.
                    else:yielding=config.get('permissive') and phase==0 and lane==0 and second%19<11
                    if yielding:
                        if config.get('realistic_turns'):
                            if old_x<=12:gap=min(gap,max(0.,12-old_x))
                        elif old_x<0:allowed=False
                    if not allowed and old_x<=0:gap=min(gap,max(0.,-old_x))
                    # Downstream queue blocks the lane independently of lamps.
                    if blocked and second%duration>duration*.42 and second%duration<duration*(.42+blocked) and old_x<35:
                        gap=min(gap,max(0.,35-old_x))
                    desired=min(car['desired'],math.sqrt(max(0.,6*gap)))
                    if leader:desired=min(desired,max(0.,gap)/car['headway'])
                    acceleration=max(-3.,min(car['acceleration'],(desired-old_v)/step))
                    speed=max(0.,old_v+acceleration*step)
                    if speed<.12 and desired<.12:speed=0.
                    position=old_x+(old_v+speed)*.5*step
                    cap=leader['x']-6.5 if leader else float('inf')
                    if yielding and config.get('realistic_turns') and old_x<=12:cap=min(cap,12.)
                    if not allowed and old_x<=0:cap=min(cap,0.)
                    if position>cap:position=cap;speed=0.
                    car['x'],car['v']=max(old_x,position),speed
                    if old_x<=0<car['x'] and not car['crossed']:
                        car['crossed']=True;car['crossing_s']=second
                    if speed<.12:car['stopped_s']+=step
                    if fov_start<=car['x']<=fov_end and 0<=second<=duration:
                        car['history'].append((second,car['x'],speed))
                    leader=car
                while active and active[0]['x']>90:completed.append(active.pop(0))
            completed.extend(active)
            crossing_calendar[movement]=sorted(c['crossing_s'] for c in completed if c['crossing_s'] is not None)
            for car in completed:
                history=np.asarray(car['history'])
                if len(history)<3:continue
                cadence=float(rng.choice(environment['detection_step_quantiles_s']))
                cadence=max(.06,min(.25,cadence))*config.get('cadence_scale',1.)
                times=np.arange(history[0,0],history[-1,0],cadence)
                if len(times)<3:continue
                times+=nrng.uniform(-cadence*.12,cadence*.12,len(times));times=np.clip(times,history[0,0],history[-1,0])
                positions=np.interp(times,history[:,0],history[:,1]);speeds=np.interp(times,history[:,0],history[:,2])
                xy=project(movement,positions,geometry)+nrng.normal(0,.00015,(len(times),2))
                world=project(movement,positions,geometry,return_world=True)
                keep=nrng.random(len(times))>=drop
                if config.get('gap_s') and rng.random()<.4:
                    gap_start=rng.uniform(times[0],times[-1]);keep&=~((times>=gap_start)&(times<gap_start+config['gap_s']))
                source,target=movement.split('->')
                detections=[]
                raw_speed_scale=config.get('speed_scale',3.6)
                for i in np.flatnonzero(keep):
                    speed=float(speeds[i]*raw_speed_scale)
                    if config.get('nonzero_stops') and speed<.01:speed=rng.uniform(.01,.3)
                    zone=source if positions[i]<0 else target
                    detections.append(dict(millis=BASE_MS+int(round(times[i]*1000)),
                        centroid_x=float(xy[i,0]),centroid_y=float(xy[i,1]),
                        lat=float(55+world[i,1]/111_000),lng=float(61+world[i,0]/(111_000*math.cos(math.radians(55)))),
                        speed=speed if rng.random()>.02 else None,
                        zone=zone,score=rng.uniform(.72,.99),category=car['category']))
                if len(detections)<2:continue
                # Metadata contains accumulated stationary duration, not signal
                # time or a fabricated perfect release timestamp.
                track=dict(id=car['id'],millis=detections[-1]['millis'],zone_in=source,
                    zone_out=target if car['crossed'] else None,category_name=car['category'],
                    stay_duration_millis=int(round(car['stopped_s']*1000)),detections=detections)
                pieces=[track]
                if config.get('fragments') and len(detections)>40 and rng.random()<.15:
                    cut=rng.randrange(15,len(detections)-15)
                    pieces=[dict(track,detections=detections[:cut]),dict(track,id=car['id']+1_000_000,detections=detections[cut:])]
                for piece in pieces:
                    tracks.append(piece);det_count+=len(piece['detections'])
                    if rng.random()<config.get('duplicates',0):tracks.append(piece);det_count+=len(piece['detections'])
                vehicle_truth.append(dict(id=car['id'],movement=movement,crossing_s=car['crossing_s']))
    tracks.sort(key=lambda t:(t['detections'][0]['millis'],t['id']))
    truth=dict(schema='microsimulation-physical-truth-v1',base_ms=BASE_MS,config=config,groups=groups,
        signal_plan=plan,vehicle_crossings=vehicle_truth,geometry=geometry,fov_path_m=[fov_start,fov_end],
        counts=dict(tracks=len(tracks),detections=det_count),
        physical_scope='separate FIFO lanes, finite acceleration, car-following, signal stop lines; no lane changes; camera projection assumed',
        observable='structurally_unidentifiable_phase' if config.get('starved') else 'demand_present_NOT_guaranteed_identifiable')
    return tracks,truth


def match_transitions(predicted, expected, tolerance):
    """Chronological one-to-one matching; duplicates increase false positives."""
    pred,truth=sorted(predicted),sorted(expected)
    # Maximum-cardinality monotone matching with minimum absolute error as tie
    # breaker. Avoid greedy nearest-neighbour reusing one GT boundary.
    n,m=len(pred),len(truth)
    score=np.zeros((n+1,m+1),dtype=int);cost=np.zeros((n+1,m+1));back=np.zeros((n+1,m+1),dtype=np.int8)
    for i in range(1,n+1):
        for j in range(1,m+1):
            candidates=[(score[i-1,j],-cost[i-1,j],1),(score[i,j-1],-cost[i,j-1],2)]
            error=abs(pred[i-1]-truth[j-1])
            if error<=tolerance:candidates.append((score[i-1,j-1]+1,-cost[i-1,j-1]-error,3))
            count,negative,choice=max(candidates);score[i,j]=count;cost[i,j]=-negative;back[i,j]=choice
    errors=[];i,j=n,m
    while i and j:
        choice=back[i,j]
        if choice==3:errors.append(abs(pred[i-1]-truth[j-1]));i-=1;j-=1
        elif choice==1:i-=1
        else:j-=1
    matched=len(errors)
    return dict(matched=matched,predicted=n,expected=m,precision=matched/n if n else None,
        recall=matched/m if m else None,mae_s=float(np.mean(errors)) if errors else None,
        errors_s=errors)


def labels_at(segments, times, *, default=-1):
    labels=np.full(len(times),default,dtype=int)
    for a,b,z in segments:labels[(times>=a)&(times<b)]=int(z)
    return labels


def split_empty_phase(truth):
    """Two physically different plans with identical observed vehicle inputs.

    Split the final, completely unobserved group into two sequential heads.
    The original observed movements retain exactly their signal schedules.
    This is a non-identifiability witness, not another independent test sample.
    """
    from copy import deepcopy
    phase=len(truth['groups'])-1;empty=truth['groups'][phase]
    if len(empty)!=2 or any(v['movement'] in empty for v in truth['vehicle_crossings']):
        raise ValueError('requires two movements with no observed vehicles')
    alternate=deepcopy(truth);alternate['groups'][phase]=empty[:1]
    alternate['groups'].append(empty[1:]);alternate['config']['k']+=1
    rows=[]
    for row in truth['signal_plan']:
        if row['phase']!=phase:rows.append(dict(row));continue
        mid=(row['start_s']+row['end_s'])/2
        if mid-row['start_s']<=4:raise ValueError('insufficient duration for two physical runs')
        rows.extend([dict(row,end_s=mid,green_end_s=mid-4,yellow_end_s=mid-1),
            dict(row,phase=phase+1,start_s=mid)])
    alternate['signal_plan']=rows
    return alternate


def production_main_head_scores(result,truth,times):
    """Evaluate the ACTUAL automatic hardware projection, not an oracle map."""
    from app.core.v10.estimated_signals import build_estimated_signals
    estimate=build_estimated_signals(result,profile_id='none')
    states={s['id']:s for s in estimate.get('states',[])}
    base=(result.get('schedule_base_timestamp_ms',result.get('analysis_base_timestamp_ms',truth['base_ms']))-truth['base_ms'])/1000
    heads={}
    opposite={'N':'S','S':'N','E':'W','W':'E'}
    for head in opposite:
        movement=f'{head}->{opposite[head]}'
        phases={p for p,group in enumerate(truth['groups']) if movement in {s.replace('_','') for s in group}}
        runs=movement_signal_plan(truth['signal_plan'],phases)
        expected=np.array([movement_color_at(runs,float(t))[0] for t in times],dtype=object)
        predicted=np.full(len(times),'UNKNOWN',dtype=object)
        for a,b,sid in estimate.get('segments',[]):
            state=states[sid]['heads'].get(head,{}).get('main',{}).get('state','UNKNOWN')
            predicted[(times>=a+base)&(times<b+base)]=state
        metrics={}
        for color in ('GREEN','YELLOW','RED'):
            ep=[float(times[i]) for i in range(1,len(times)) if expected[i]==color and expected[i-1]!=color]
            pp=[float(times[i]) for i in range(1,len(times)) if predicted[i]==color and predicted[i-1] not in (color,'UNKNOWN')]
            metrics[color]={str(t):match_transitions(pp,ep,t) for t in (.5,1,2,3)}
        heads[head]=dict(evaluated_s=len(times)*.25,error_fraction=float(np.mean(expected!=predicted)),
            coverage_fraction=float(np.mean(predicted!='UNKNOWN')),onsets=metrics,
            per_color={color:dict(seconds=float(np.sum(expected==color)*.25),
                error_fraction=float(np.mean(predicted[expected==color]!=color)) if np.any(expected==color) else None)
                for color in ('GREEN','YELLOW','RED','RED_YELLOW')})
    return dict(mapping_available=estimate['available'],mapping_reason=estimate.get('reason'),heads=heads,
        scope='actual production automatic physical-plan mapping plus shared transitions; no known-site profile, no truth at prediction; straight main heads only, assumed simulator hardware')


def score_prediction(result, truth):
    schedule=result['schedule'];base=(result['analysis_base_timestamp_ms']-truth['base_ms'])/1000
    segments=[[a+base,b+base,z] for a,b,z in schedule['raw_hsmm_segments']]
    # Score the whole requested recording, including uncovered model intervals.
    # Representative-window output must not look like whole-session accuracy.
    start,end=0.,float(truth['config']['duration_s'])
    times=np.arange(start,end,.25)
    if not len(times):raise ValueError('no overlapping scoring support')
    expected=labels_at([[r['start_s'],r['end_s'],r['phase']] for r in truth['signal_plan']],times)
    predicted=labels_at(segments,times)
    k,pk=truth['config']['k'],schedule['phase_count']
    table=np.zeros((pk,k))
    for a,b in zip(predicted,expected):
        if a>=0 and b>=0:table[a,b]+=1
    left,right=linear_sum_assignment(-table)
    mapping=dict(zip(map(int,left),map(int,right)))
    aligned=np.array([mapping.get(int(z),-1) for z in predicted])
    expected_onsets=[r['start_s'] for r in truth['signal_plan'] if start<r['start_s']<end]
    predicted_onsets=[segments[i][0] for i in range(1,len(segments))
        if segments[i-1][1]==segments[i][0] and segments[i-1][2]!=segments[i][2]]
    timing={str(t):match_transitions(predicted_onsets,expected_onsets,t) for t in (.5,1,2,3)}
    # Composition is inferred from observed stream probabilities, not filled in
    # from GT. Label alignment alone is allowed for anonymous phase IDs.
    from app.core.v9.primitives import norm_zone
    def canonical(movement):return '->'.join(norm_zone(z) for z in movement.split('->'))
    assignment={};raw_assignment={}
    for row in schedule.get('stream_activity_by_phase',[]):
        probs=row['event_probability_by_phase'];name=max(probs,key=probs.get)
        label=schedule['phase_names'].index(name)
        raw_assignment[canonical(row['stream'])]=label
        assignment[canonical(row['stream'])]=mapping.get(label,-1)
    true_assignment=defaultdict(set)
    for p,group in enumerate(truth['groups']):
        for stream in group:true_assignment[canonical(stream)].add(p)
    all_streams=set(true_assignment)|set(assignment)
    composition=sum(assignment.get(s) in true_assignment.get(s,set()) for s in all_streams)/max(1,len(all_streams))
    # Dominant membership alone does not establish a shared movement's complete
    # activity set. Report this limitation in addition to dominant correctness.
    complete_membership=sum({assignment.get(s)}==true_assignment.get(s,set()) for s in all_streams)/max(1,len(all_streams))
    # Phase-local movement lamps are simulator heads, not an assertion of actual
    # hardware topology at any of the three real intersections.
    from app.core.v10.signal_timing import apply_signal_timing
    estimate=dict(available=True,topology={s:{} for s in all_streams},segments=segments,
        states=[dict(id=z,name=f'PHASE_{z}',heads={s:dict(main=dict(state=(
            'UNKNOWN' if s not in raw_assignment else 'GREEN' if raw_assignment[s]==z else 'RED')),arrows=[])
            for s in all_streams}) for z in range(pk)])
    timed=apply_signal_timing(estimate)
    state_catalog={s['id']:s for s in timed['states']}
    colors={};onset_scores={}
    for movement,phases in true_assignment.items():
        pcolors=np.full(len(times),'UNKNOWN',dtype=object)
        for a,b,z in timed['segments']:
            pcolors[(times>=a)&(times<b)]=state_catalog[z]['heads'][movement]['main']['state']
        lamp_runs=movement_signal_plan(truth['signal_plan'],phases)
        tcolors=np.array([movement_color_at(lamp_runs,float(t))[0] for t in times],dtype=object)
        colors[movement]=dict(evaluated_s=len(times)*.25,error_fraction=float(np.mean(tcolors!=pcolors)),
            coverage_fraction=float(np.mean(pcolors!='UNKNOWN')),
            semantics='diagnostic dominant-phase movement projection, NOT the app hardware projection; see production_main_heads for actual automatic projection',
            per_color={color:dict(seconds=float(np.sum(tcolors==color)*.25),
                error_fraction=float(np.mean(pcolors[tcolors==color]!=color)) if np.any(tcolors==color) else None)
                for color in ('GREEN','YELLOW','RED','RED_YELLOW')})
        onset_scores[movement]={}
        for color in ('GREEN','YELLOW','RED'):
            ep=[float(times[i]) for i in range(1,len(times)) if tcolors[i]==color and tcolors[i-1]!=color]
            pp=[float(times[i]) for i in range(1,len(times)) if pcolors[i]==color and pcolors[i-1]!=color and pcolors[i-1]!='UNKNOWN']
            onset_scores[movement][color]=match_transitions(pp,ep,2.)
    return dict(evaluation_schema='full-recording-including-unknown-v2',expected_k=k,predicted_k=pk,k_correct=k==pk,period_s=schedule['period_s'],
        nominal_period_s=truth['config']['period_s'],period_error_s=abs(schedule['period_s']-truth['config']['period_s']),
        phase_state_error_fraction=float(np.mean(aligned!=expected)),evaluated_s=len(times)*.25,
        coverage_fraction=float(np.mean(predicted>=0)),
        permutation_alignment=mapping,movement_assignment_accuracy=composition,
        complete_movement_membership_accuracy=complete_membership,
        composition_semantics='dominant probability phase per stream; shared membership incompleteness reported separately',transition_metrics=timing,
        movement_colors=colors,movement_color_onsets_at_2s=onset_scores,
        production_main_heads=production_main_head_scores(result,truth,times),
        observability=truth['observable'],scope='independent synthetic truth; label permutation alignment only; no solver tuning')


def cases():
    output=[]
    scenarios=[
        ('ordinary',{}),('platoons',dict(platoons=True)),
        ('sparse',dict(arrival_rate_s=.025)),('saturation',dict(arrival_rate_s=.45)),
        ('occlusion',dict(dropout=.18,gap_s=3.5,fragments=True,duplicates=.03)),
        ('yield_block',dict(permissive=True,blocking=.12)),
        ('changing_cycle',dict(cycle_jitter=.035,regime_change=True)),
        ('nonzero_stops',dict(nonzero_stops=True,speed_scale=1.,cadence_scale=2.)),
    ]
    for k in (2,3,4,5):
        for index,(name,options) in enumerate(scenarios):
            for seed_index in (0,1):
                config=dict(id=f'k{k}_{name}_{seed_index}',k=k,duration_s=1800 if seed_index==0 else 3600,
                    period_s=(72,100,128,160)[k-2],arrival_rate_s=.11,all_red_s=1.,
                    seed=2026101900+k*100+index*2+seed_index,**options) if 'arrival_rate_s' not in options else {
                    **dict(id=f'k{k}_{name}_{seed_index}',k=k,duration_s=1800 if seed_index==0 else 3600,
                    period_s=(72,100,128,160)[k-2],arrival_rate_s=.11,all_red_s=1.,
                    seed=2026101900+k*100+index*2+seed_index),**options}
                output.append(config)
    for k in (3,5):
        output.append(dict(id=f'k{k}_starved',k=k,duration_s=3600,period_s=120.,arrival_rate_s=.1,seed=3900+k,starved=True))
    for k in (3,4):
        output.append(dict(id=f'k{k}_shared_main',k=k,duration_s=3600,period_s=120.,arrival_rate_s=.11,
                           seed=5900+k,shared_stream=True,permissive=True))
    for k in (2,3):
        output.append(dict(id=f'k{k}_four_hours',k=k,duration_s=14400,period_s=100.,arrival_rate_s=.16,
                           seed=4900+k,platoons=True,dropout=.07,duplicates=.01))
    output.extend(extra_cases())
    return output


def extra_cases():
    return [dict(id='k2_asymmetric_real_uturn',k=2,duration_s=3600,period_s=100.,arrival_rate_s=.13,
                 seed=6902,phase_weights=[.2,.8],uturn=True,realistic_turns=True),
            dict(id='k3_short_arrow_real_uturn',k=3,duration_s=3600,period_s=100.,arrival_rate_s=.13,
                 seed=6903,phase_weights=[.37,.16,.47],uturn=True,realistic_turns=True,shared_stream=True)]


def write_tracks_zip(path,tracks):
    """Bounded per-record C encoding, byte-identical to compact array JSON.

    Avoid millions of tiny writes/compressor calls from iterencode(), without
    materializing a multi-gigabyte string or changing any observation.
    """
    with zipfile.ZipFile(path,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as archive:
        with archive.open('trajectories.json','w') as stream:
            stream.write(b'[')
            for index,track in enumerate(tracks):
                if index:stream.write(b',')
                stream.write(json.dumps(track,separators=(',',':')).encode())
            stream.write(b']')


def one(config, environment, evidence, runtime):
    from app.core.v9.events import load_event_streams,_iter_json_records
    begin=time.monotonic();case=config['id'];receipt=dict(config=config)
    try:
        tracks,truth=generate(config,environment)
        case_dir=Path(runtime)/case;case_dir.mkdir(parents=True,exist_ok=True)
        truth_bytes=json.dumps(truth,separators=(',',':')).encode()
        with gzip.open(case_dir/'truth.json.gz','xb') as stream:stream.write(truth_bytes)
        receipt['truth_sha256']=hashlib.sha256(truth_bytes).hexdigest()
        receipt['counts']=truth['counts'];receipt['generation_s']=time.monotonic()-begin
        write_tracks_zip(case_dir/'input.zip',tracks)
        receipt['input_zip_sha256']=hashlib.sha256((case_dir/'input.zip').read_bytes()).hexdigest()
        del tracks
        stats=CorpusStats(seed=config['seed'])
        with zipfile.ZipFile(case_dir/'input.zip') as archive:
            with archive.open('trajectories.json') as stream:
                bundle=load_event_streams(Path('records'),_records=stats.observe(_iter_json_records(stream)))
        receipt['statistics']=stats.result()
        save(Path(evidence)/'sealed'/f'{case}.json',receipt)
        # Read no truth files in the prediction function. Pass neither truth nor
        # original simulator config; compare only after prediction has returned.
        predictions=predict_modes(bundle)
        with gzip.open(case_dir/'predictions.json.gz','xt',encoding='utf8') as stream:json.dump(predictions,stream)
        scores=[]
        for row in predictions:
            if row['automatic']['status']=='ok':scores.append(score_prediction(row['automatic']['result'],truth))
        receipt.update(status='processed',predictions=compact_predictions(predictions),scores=scores)
    except Exception as exc:
        receipt.update(status='failed',error=type(exc).__name__+': '+str(exc),traceback=traceback.format_exc())
    receipt['runtime_s']=time.monotonic()-begin
    save(Path(evidence)/'results'/f'{case}.json',receipt)


def run(environment_path,evidence,runtime,*,concurrency=2,resume=False,only=None):
    evidence,runtime=Path(evidence),Path(runtime);runtime.mkdir(parents=True,exist_ok=True)
    suite=cases()
    if only:suite=[c for c in suite if c['id'] in only.split(',')]
    if not (evidence/'suite.json').exists():save(evidence/'suite.json',dict(cases=suite,environment_sha256=hashlib.sha256(Path(environment_path).read_bytes()).hexdigest()))
    elif not resume:raise ValueError('suite exists: use --resume or new output directory')
    pending=[c for c in suite if not (evidence/'results'/f"{c['id']}.json").exists()];active=[]
    env={**os.environ,'PYTHONHASHSEED':'0','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    limit_path=runtime/'concurrency.json'
    if not limit_path.exists():save(limit_path,dict(workers=concurrency))
    while pending or active:
        limit=int(json.loads(limit_path.read_text())['workers'])
        if not 1<=limit<=8:raise ValueError('workers must be in 1..8')
        while pending and len(active)<limit:
            config=pending.pop(0);config_path=runtime/f"{config['id']}_config.json"
            if not config_path.exists():save(config_path,config)
            log=(runtime/f"{config['id']}.log").open('ab')
            proc=subprocess.Popen([sys.executable,'-m','scripts.realistic_traffic_benchmark','worker','--config',str(config_path.resolve()),
                '--environment',str(Path(environment_path).resolve()),'--evidence',str(evidence.resolve()),'--runtime',str(runtime.resolve())],
                cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            active.append((config,proc,time.monotonic(),log))
        for item in active[:]:
            config,proc,begin,log=item
            if proc.poll() is None:continue
            log.close();target=evidence/'results'/f"{config['id']}.json"
            if not target.exists():save(target,dict(config=config,status='worker_failed',exit_code=proc.returncode))
            d=json.loads(target.read_text(encoding='utf8'))
            print(config['id'],d['status'],f'{time.monotonic()-begin:.1f}s',[(s['predicted_k'],s['expected_k']) for s in d.get('scores',[])],flush=True)
            active.remove(item)
        if active:time.sleep(.25)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    fit=sub.add_parser('environment');fit.add_argument('--ingest',type=Path,required=True);fit.add_argument('--out',type=Path,required=True)
    batch=sub.add_parser('run');batch.add_argument('--environment',type=Path,required=True);batch.add_argument('--evidence',type=Path,required=True)
    batch.add_argument('--runtime',type=Path,required=True);batch.add_argument('--concurrency',type=int,default=2);batch.add_argument('--resume',action='store_true');batch.add_argument('--only')
    worker=sub.add_parser('worker');worker.add_argument('--config',type=Path,required=True);worker.add_argument('--environment',type=Path,required=True)
    worker.add_argument('--evidence',type=Path,required=True);worker.add_argument('--runtime',type=Path,required=True)
    args=vars(parser.parse_args());command=args.pop('command')
    if command=='environment':save(args['out'],fit_environment(args['ingest']))
    elif command=='run':run(args.pop('environment'),**args)
    else:one(json.loads(args.pop('config').read_text(encoding='utf8')),json.loads(args.pop('environment').read_text(encoding='utf8')),**args)


if __name__=='__main__':main()
