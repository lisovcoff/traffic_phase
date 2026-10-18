"""Operator-calibrated cyclic observation model with a separate prediction API."""
from collections import defaultdict
import math
import numpy as np
from scipy.ndimage import gaussian_filter1d


def observations(events):
    grouped=defaultdict(list)
    for e in events:
        fp=e.provenance.get('track_fingerprint')
        if not fp:continue
        eligible=(e.event_type=='RELEASE' and e.evidence_quality!='LOW') or (
            e.event_type=='CROSSING_PROXY' and e.provenance.get('eligible_proxy')
            and not e.provenance.get('invalid_detections') and not e.provenance.get('conflicting_timestamps'))
        if eligible:grouped[(e.provenance.get('source',''),fp,e.movement)].append(e)
    rows=[]
    for values in grouped.values():
        for e in values:rows.append((e.timestamp_ms,(e.movement,e.event_type),1./len(values)))
    return sorted(rows,key=lambda r:(r[0],r[1]))


def fit_profile(events,training_marks,*,base_ms,period_s,train_start_ms,train_end_ms):
    """Receives training marks only. There is no test-annotation argument."""
    marks=sorted(training_marks,key=lambda m:m['timestamp_ms'])
    if len(marks)<4:raise ValueError('at least four training marks required')
    if any(m['timestamp_ms']>train_end_ms for m in marks):raise ValueError('training mark beyond cut')
    labels=sorted({m['kind'] for m in marks})
    onsets={}
    for label in labels:
        times=[m['timestamp_ms'] for m in marks[1:] if m['kind']==label]
        if not times:raise ValueError('uncensored training onset required for every phase')
        angle=np.asarray([(t-base_ms)/1000/period_s*2*np.pi for t in times])
        mean=np.exp(1j*angle).mean()
        if abs(mean)<.5:raise ValueError('training onsets not concentrated under inferred period')
        onsets[label]=float(np.angle(mean)%(2*np.pi)*100/(2*np.pi))
    order=sorted(labels,key=onsets.get)
    rows=observations([e for e in events if train_start_ms<=e.timestamp_ms<train_end_ms])
    channels=sorted({r[1] for r in rows})
    if not channels:raise ValueError('no supported training observations')
    idx={c:j for j,c in enumerate(channels)}
    hist=np.zeros((100,len(channels)))
    for time,channel,weight in rows:
        phase=int(((time-base_ms)/1000%period_s)/period_s*100)%100
        hist[phase,idx[channel]]+=weight
    profile=gaussian_filter1d(hist,2.,axis=0,mode='wrap')+.5
    profile/=profile.sum(axis=0,keepdims=True)
    return dict(schema='learned-traffic-phase-v1',period_s=float(period_s),bins=100,
        channels=[list(c) for c in channels],profile=profile.tolist(),
        phase_labels=order,phase_onsets_bins=[onsets[label] for label in order],
        training_range_ms=[train_start_ms,train_end_ms],training_marks=len(marks),
        training_marks_sha_scope='training subset only',manual_marks_used_for_training=True,
        phase_count_source='training_labels_NOT_automatic_discovery',
        timestamp_semantics='operator_calibrated_NOT_observed_lamp_switch',
        prediction_uses_test_marks=False,transductive_period_from_unlabelled_recording=True)


def predict_profile(events,model,*,start_ms,end_ms,period_s=None):
    """Prediction accepts observations/model/window; never manual test labels."""
    period=float(period_s or model['period_s']);m=100
    channels={tuple(c):j for j,c in enumerate(model['channels'])}
    n=int(math.ceil((end_ms-start_ms)/1000))
    if not 0<n<=10_800:raise ValueError('bounded positive prediction window required')
    x=np.zeros((n,len(channels)))
    used=0
    for time,channel,weight in observations([e for e in events if start_ms<=e.timestamp_ms<end_ms]):
        if start_ms<=time<end_ms and channel in channels:
            i=int((time-start_ms)/1000);x[i,channels[channel]]+=weight;used+=1
    if not used:raise ValueError('no supported prediction observations')
    emission=x@np.log(np.maximum(np.asarray(model['profile']),1e-15)).T
    expected=m/period;steps=np.arange(int(math.ceil(expected))+3)
    penalties=.5*((steps-expected)/.5)**2
    positions=np.arange(m)
    previous=(positions[:,None]-steps[None,:])%m
    score=np.zeros(m);back=np.zeros((n,m),dtype=np.int16)
    for t in range(n):
        choices=score[previous]-penalties[None,:]
        best=np.argmax(choices,axis=1)
        score=choices[positions,best]+emission[t]
        back[t]=previous[positions,best]
    position=int(np.argmax(score));path=np.zeros(n,dtype=int)
    for t in range(n-1,-1,-1):path[t]=position;position=int(back[t,position])
    onsets=np.asarray(model['phase_onsets_bins']);k=len(onsets)
    labels=np.searchsorted(onsets,path,side='right')-1;labels%=k
    rows=[];start=0
    for i in range(1,n+1):
        if i==n or labels[i]!=labels[start]:
            rows.append([float(start),min(float(i),(end_ms-start_ms)/1000),int(labels[start])]);start=i
    names=[f'PHASE_{chr(65+i)}' for i in range(k)]
    return dict(algorithm='Learned cyclic traffic profile; operator-calibrated',
        recording_start_timestamp_ms=start_ms,analysis_base_timestamp_ms=start_ms,
        schedule_base_timestamp_ms=start_ms,recording_duration_s=(end_ms-start_ms)/1000,
        event_count=used,phase_model_selection={'selected_phase_count':k,'conditional_on_training_labels':True},
        schedule={'model':'learned_cyclic_traffic_profile','phase_count':k,'phase_names':names,
            'period_s':period,'raw_hsmm_segments':rows,'baseline_segments':rows},
        learned_phase={'model_schema':model['schema'],'training_range_ms':model['training_range_ms'],
            'phase_labels':model['phase_labels'],'test_marks_received':False,
            'phase_count_source':'training_labels_NOT_automatic_discovery',
            'physical_lamps_observed':False,'operator_reaction_uncertainty_s':[0,3]},
        physical_signal_plan={'enabled':False,'reason':'no independent physical lamp evidence'})
