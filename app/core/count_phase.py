"""Independent count/composition phase core. No V9 fit/decoder is called.

Vehicle observation types are separate channels. Absence of an event carries
no categorical observation, so empty seconds retain their time but no emission.
All outputs are trajectory-based estimates, never observations of signal lamps.
"""
from collections import defaultdict
import math
import numpy as np


def circular_partition(counts,period):
    """Bounded circular multinomial change points, enumerating each grid origin."""
    counts=np.asarray(counts,dtype=float)
    m,s=counts.shape
    if not np.isfinite(counts).all() or (counts<0).any() or counts.sum()<=0:
        raise ValueError('finite nonnegative observed counts required')
    prefix=np.vstack([np.zeros(s),np.cumsum(np.tile(counts,(2,1)),axis=0)])
    c=np.maximum(0.,prefix[None,:,:]-prefix[:,None,:])
    totals=c.sum(axis=2)
    costs=totals*np.log(np.maximum(totals,1.))-np.sum(c*np.log(np.maximum(c,1e-15)),axis=2)
    minimum=max(1,int(math.ceil(3./(period/m))))
    candidates=[]
    # One state is permitted; no fabricated second phase when observations do
    # not distinguish recurring movement compositions.
    for k in range(1,min(6,m//minimum)+1):
        best=None
        maximum=m if k==1 else int(math.floor(.9*m))
        for origin in range(m):
            dp=np.full((k+1,m+1),np.inf);dp[0,0]=0.
            back=np.full((k+1,m+1),-1,dtype=int)
            for z in range(1,k+1):
                for end in range(z*minimum,m+1):
                    starts=np.arange(max((z-1)*minimum,end-maximum),end-minimum+1)
                    if not len(starts):continue
                    options=dp[z-1,starts]+costs[origin+starts,origin+end]
                    index=int(np.argmin(options))
                    dp[z,end]=options[index];back[z,end]=starts[index]
            if not np.isfinite(dp[k,m]):continue
            if best is None or dp[k,m]<best[0]-1e-9:
                end=m;segments=[]
                for z in range(k,0,-1):
                    start=int(back[z,end]);segments.append((origin+start,origin+end));end=start
                best=(float(dp[k,m]),list(reversed(segments)))
        if best is None:continue
        bic=2*best[0]+(k*(s-1)+k)*math.log(max(2.,float(counts.sum())))
        candidates.append(dict(k=k,bic=bic,negative_loglik=best[0],segments=best[1]))
    if not candidates:raise ValueError('no feasible phase partition')
    selected=min(candidates,key=lambda c:(c['bic'],c['k']))
    groups=[]
    for a,b in selected['segments']:
        groups.append(dict(onset=(a%m)*period/m,duration=(b-a)*period/m,
            counts=prefix[b]-prefix[a]))
    groups.sort(key=lambda g:g['onset'])
    return groups,[{key:value for key,value in c.items() if key!='segments'} for c in candidates]


def local_history(counts,probabilities,durations,period):
    """Fresh semi-Markov DP in seconds with censored recording endpoints."""
    x=np.asarray(counts,dtype=float);p=np.asarray(probabilities,dtype=float)
    n=x.shape[0];k=p.shape[0]
    emissions=x@np.log(np.maximum(p,1e-15)).T
    prefix=np.vstack([np.zeros(k),np.cumsum(emissions,axis=0)])
    targets=np.asarray(durations,dtype=float)
    sigma=np.maximum(3.,.2*targets)
    minimum=np.full(k,3,dtype=int)
    maximum=np.ceil(np.minimum(.95*period,targets+np.maximum(10.,.5*targets))).astype(int)
    maximum=np.maximum(maximum,minimum+1)
    winner=None
    for initial in range(k):
        dp=np.full((n+1,k),-np.inf);back=np.full((n+1,k),-1,dtype=int)
        for end in range(1,n+1):
            if end<=maximum[initial]:
                # Initial phase may have begun before observation start.
                dp[end,initial]=prefix[end,initial]-.5*(max(0.,end-targets[initial])/sigma[initial])**2
                back[end,initial]=0
            for state in range(k):
                starts=np.arange(max(1,end-maximum[state]),end-minimum[state]+1)
                if not len(starts):continue
                ds=end-starts
                penalty=.5*((ds-targets[state])/sigma[state])**2
                if end==n:penalty=.5*(np.maximum(0.,ds-targets[state])/sigma[state])**2
                scores=dp[starts,(state-1)%k]+prefix[end,state]-prefix[starts,state]-penalty
                best=int(np.argmax(scores))
                if scores[best]>dp[end,state]:dp[end,state]=scores[best];back[end,state]=starts[best]
        state=int(np.argmax(dp[n]));score=float(dp[n,state])
        if not np.isfinite(score):continue
        if winner is None or score>winner[0]:
            rows=[];end=n
            while end:
                start=int(back[end,state])
                if start<0:raise RuntimeError('invalid local history trace')
                rows.append([float(start),float(end),int(state)])
                end,state=start,(state-1)%k
            winner=(score,list(reversed(rows)))
    if winner is None:raise ValueError('no valid count phase history')
    return winner[1]


def event_channels(events):
    """One observation per source/vehicle/movement, typed without double count."""
    grouped=defaultdict(list)
    for e in events:
        fingerprint=e.provenance.get('track_fingerprint')
        if not fingerprint:continue
        eligible=(e.event_type=='RELEASE' and e.evidence_quality!='LOW') or (
            e.event_type=='CROSSING_PROXY' and e.provenance.get('eligible_proxy')
            and not e.provenance.get('invalid_detections') and not e.provenance.get('conflicting_timestamps'))
        if eligible:grouped[(e.provenance.get('source',''),fingerprint,e.movement)].append(e)
    selected=[min(es,key=lambda e:(e.event_type!='RELEASE',e.timestamp_ms,e.evidence_method)) for es in grouped.values()]
    selected.sort(key=lambda e:(e.timestamp_ms,e.movement,e.event_type,str(e.source_track_id)))
    channels=sorted({(e.movement,e.event_type) for e in selected})
    return selected,channels


def discover_bundle(bundle,*,input_name='records'):
    from app.core.v9.primitives import infer_period
    from app.core.v10.automatic_physical import infer_physical_signal_plan
    from app.core.state_contract import attach_state_contract
    events,channels=event_channels(bundle.temporal_events)
    if not events:raise ValueError('no supported vehicle events')
    period,period_info=infer_period(bundle[1])
    base=float(bundle[7]);end=max(max(v) for v in bundle[1].values() if len(v))
    end=max(end,max((e.timestamp_ms-base)/1000 for e in events))
    n=int(math.floor(end))+1;m=100
    if n>10_800:raise ValueError('count phase supports one scoped recording up to3 hours')
    folded=np.zeros((m,len(channels)));counts=np.zeros((n,len(channels)))
    index={c:j for j,c in enumerate(channels)}
    for event in events:
        t=(event.timestamp_ms-base)/1000;j=index[event.movement,event.event_type]
        if t<0:continue
        folded[int((t%period)/period*m)%m,j]+=1.
        counts[min(n-1,int(t)),j]+=1.
    groups,candidates=circular_partition(folded,period)
    k=len(groups);names=[f'PHASE_{chr(65+i)}' for i in range(k)]
    p=np.asarray([g['counts']+.5 for g in groups]);p/=p.sum(axis=1,keepdims=True)
    durations=[g['duration'] for g in groups]
    segments=local_history(counts,p,durations,period)
    baseline=[]
    for cycle in range(-1,int(n/period)+1):
        for z,g in enumerate(groups):
            a=max(0.,cycle*period+g['onset']);b=min(float(n),cycle*period+g['onset']+g['duration'])
            if b>a:baseline.append([a,b,z])
    baseline.sort()
    streams=sorted({movement for movement,kind in channels})
    activity=[]
    for stream in streams:
        js=[j for j,c in enumerate(channels) if c[0]==stream]
        activity.append(dict(stream=stream,event_probability_by_phase={names[z]:float(1.-np.exp(
            -sum(g['counts'][js])/max(1.,g['duration']*n/period))) for z,g in enumerate(groups)}))
    result=dict(algorithm='Count phase v1: circular multinomial partition + local count DP',
        input=input_name,trajectory_count=int(bundle[8]),event_count=len(events),movement_stream_count=len(streams),
        movement_streams={s:sum(e.movement==s for e in events) for s in streams},
        recording_start_timestamp_ms=float(bundle[6]),analysis_base_timestamp_ms=base,
        event_base_timestamp_ms=base,schedule_base_timestamp_ms=base,recording_duration_s=float(end),
        archive={'source_files':bundle[5]},period_inference={'period_s':period,**period_info},
        event_extraction={'evidence_policy':'typed_per_track_counts','manual_marks_used_for_discovery':False,
            'selected_event_count':len(events),'channels':[list(c) for c in channels]},
        phase_evidence={'source':'typed_per_track_counts','demand_entries_used_for_phase_evidence':False},
        phase_model_selection={'selected_phase_count':k,'raw_selected_phase_count':k,
            'criterion':'circular_conditional_multinomial_BIC','candidates':candidates},
        schedule={'model':'count_phase_v1','phase_count':k,'phase_names':names,'period_s':period,
            'raw_hsmm_segments':segments,'baseline_segments':baseline,
            'baseline_duration_targets_s':dict(zip(names,durations)),
            'stream_activity_by_phase':activity},
        anomaly_detection={'temporary_phase_deviations':[],'cause':'unknown'},
        count_phase={'experimental':True,'physical_lamps_observed':False,'manual_marks_used':False,
            'folded_bins':m,'time_step_s':1,'observation_model':'conditional_on_vehicle_event',
            'empty_seconds_not_negative_lamp_evidence':True,'phase_onsets_s':[g['onset'] for g in groups],
            'calibrated_lamp_probability':None})
    try:result['physical_signal_plan']=infer_physical_signal_plan(result)
    except ValueError as exc:result['physical_signal_plan']={'enabled':False,'reason':str(exc)}
    return attach_state_contract(result)


def discover_path(path,*,source_member=None,session_id=None):
    from app.core.v9.events import load_event_streams
    from app.core.v9.source_scope import choose_source,choose_session,attach_input_scope
    chosen,sources=choose_source(path,source_member)
    bundle=load_event_streams(path,source_member=chosen)
    scoped,selected,sessions=choose_session(bundle,chosen,session_id)
    result=discover_bundle(scoped,input_name=str(path))
    return attach_input_scope(result,chosen,selected,sessions,source_count=len(sources))
