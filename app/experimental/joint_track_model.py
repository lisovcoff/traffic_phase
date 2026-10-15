"""Finite synthetic posterior for correlated vehicle observations.

Explicit known K/order/start/count, rates, demand exposure and delay model.
Never imported by production; no annotation/truth inputs. No real lamp estimates.
"""
from __future__ import annotations

from collections import defaultdict
import math
import time

import numpy as np

from app.core.state_contract import StateEstimate, physical_estimate

PRIORS = {
    'flat': {'min_s':4, 'max_s':48, 'step_s':2, 'family':'uniform'},
    'soft': {'min_s':4, 'max_s':48, 'step_s':2, 'family':'discrete_laplace', 'center_s':12, 'scale_s':8},
}
LIMITS = {'max_seconds':5.0,'max_paths':10000,'max_horizon_s':80,'max_tracks':512,
          'max_q_cells':50000,'max_memory_bytes':32*1024*1024}
GRID_S=2
OFFSET_MS=250


class ModelUnavailable(ValueError):
    pass


def _finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def _normalize_mass(mass):
    if not isinstance(mass,list) or not mass:
        raise ModelUnavailable('MISSING_DELAY_DISTRIBUTION')
    if any(not isinstance(x,list) or len(x)!=2 or not _finite(x[0]) or x[0]<0
           or x[0]%GRID_S or not _finite(x[1]) or x[1]<=0 for x in mass):
        raise ModelUnavailable('INVALID_DISCRETE_DELAY_DISTRIBUTION')
    if len({x[0] for x in mass})!=len(mass) or abs(sum(x[1] for x in mass)-1)>1e-10:
        raise ModelUnavailable('UNNORMALIZED_DELAY_DISTRIBUTION')
    return [(int(a),float(p)) for a,p in mass]


def tracks_from_view(view, spec):
    """Known same-track association; unrelated observations are never paired."""
    grouped=defaultdict(lambda:{'movement':None,'release_ms':set(),'crossing_ms':set()})
    methods={'RELEASE':spec.get('release_method'),'CROSSING_PROXY':spec.get('crossing_method')}
    for row in view.get('events',[]):
        event=row['event']; kind=event['event_type']
        if kind not in methods or not row['eligible_vehicle_evidence']:
            continue
        if event['evidence_method']!=methods[kind]:
            raise ModelUnavailable('EVENT_METHOD_NOT_IN_SUPPLIED_OBSERVATION_MODEL')
        group=row.get('vehicle_group_id')
        if not group: raise ModelUnavailable('TRACK_IDENTITY_UNKNOWN')
        obj=grouped[group]
        if obj['movement'] is not None and obj['movement']!=event['movement']:
            raise ModelUnavailable('TRACK_MOVEMENT_CONFLICT')
        obj['movement']=event['movement']
        obj['release_ms' if kind=='RELEASE' else 'crossing_ms'].add(event['timestamp_ms'])
    result=[]
    for group,obj in sorted(grouped.items()):
        if len(obj['release_ms'])>1 or len(obj['crossing_ms'])>1:
            raise ModelUnavailable('MULTIPLE_DISTINCT_SAME_METHOD_OBSERVATIONS_PER_TRACK')
        result.append({'group_id':group,'movement':obj['movement'],
            'release_ms':next(iter(obj['release_ms']),None),
            'crossing_ms':next(iter(obj['crossing_ms']),None)})
    return result


def observation_components(view, spec, *, max_tracks=512, max_q_cells=50000):
    """Exact finite q_i(u) and thinning exposure, with missing detections."""
    h=spec.get('horizon_s')
    if not isinstance(h,int) or isinstance(h,bool) or not 0<h or h%GRID_S:
        raise ModelUnavailable('GRID_ALIGNED_HORIZON_REQUIRED')
    movements=spec.get('movements')
    rates=spec.get('rates_per_s')
    if not isinstance(movements,list) or not movements or len(movements)>16 or len(set(movements))!=len(movements):
        raise ModelUnavailable('INVALID_MOVEMENT_NAMES')
    if rates is None or not spec.get('rate_source') or not spec.get('delay_source'):
        raise ModelUnavailable('SUPPLIED_RATE_AND_DELAY_MODEL_REQUIRED')
    rates=np.asarray(rates,dtype=float)
    if rates.ndim!=2 or rates.shape[0] not in (2,3) or rates.shape[1]!=len(movements) or not np.isfinite(rates).all() or (rates<0).any():
        raise ModelUnavailable('INVALID_INTENSITY_MATRIX')
    exposure=spec.get('latent_demand_exposure')
    if exposure is None: raise ModelUnavailable('SUPPLIED_DEMAND_EXPOSURE_REQUIRED')
    exposure=np.asarray(exposure,dtype=float)
    n=h//GRID_S
    if exposure.shape!=(len(movements),n) or not np.isfinite(exposure).all() or (exposure<0).any():
        raise ModelUnavailable('INVALID_DEMAND_EXPOSURE')
    windows=spec.get('observation_windows_s')
    if not isinstance(windows,list): raise ModelUnavailable('SUPPLIED_OBSERVATION_WINDOWS_REQUIRED')
    previous=0
    for a,b in windows:
        if not _finite(a) or not _finite(b) or not 0<=a<b or a<previous:
            raise ModelUnavailable('INVALID_OBSERVATION_WINDOWS')
        previous=b
    delays=_normalize_mass(spec.get('release_delay_s'))
    transit=_normalize_mass(spec.get('transit_delay_s'))
    pr,pc=spec.get('release_detection_probability'),spec.get('crossing_detection_probability')
    if not _finite(pr) or not _finite(pc) or not 0<=pr<=1 or not 0<=pc<=1:
        raise ModelUnavailable('SUPPLIED_DETECTION_PROBABILITIES_REQUIRED')
    from app.experimental.observation_domain import require_complete_query
    domain=require_complete_query(view,horizon_s=h,windows=windows,error_type=ModelUnavailable,
        finite_clock=(OFFSET_MS,GRID_S*1000,n),
        channels=[('RELEASE',[d for d,_ in delays],pr),
            ('CROSSING_PROXY',[d+lag for d,_ in delays for lag,_ in transit],pc)])
    tracks=tracks_from_view(view,spec)
    if len(tracks)>max_tracks: raise ModelUnavailable('TRACK_BUDGET_EXHAUSTED')
    if len(tracks)*n>max_q_cells: raise ModelUnavailable('Q_CELL_BUDGET_EXHAUSTED')
    def visible(t): return any(a<=t/1000<b for a,b in windows)
    for t in tracks:
        if t['movement'] not in movements: raise ModelUnavailable('MOVEMENT_NOT_IN_RATE_MODEL')
        for field in ('release_ms','crossing_ms'):
            timestamp=t[field]
            if timestamp is not None and (not _finite(timestamp) or timestamp<OFFSET_MS
                    or (timestamp-OFFSET_MS)%(GRID_S*1000)!=0):
                raise ModelUnavailable('TIMESTAMP_UNSUPPORTED_BY_DECLARED_DISCRETE_CLOCK')
            if timestamp is not None and not visible(timestamp):
                raise ModelUnavailable('OBSERVATION_OUTSIDE_SUPPLIED_WINDOWS')
    q=np.zeros((len(tracks),n),dtype=float)
    detected=np.zeros(n,dtype=float)
    for j in range(n):
        u=j*GRID_S*1000+OFFSET_MS
        for d,pd in delays:
            r=u+d*1000
            for lag,pt in transit:
                c=r+lag*1000
                a,b=(pr if visible(r) else 0.),(pc if visible(c) else 0.)
                mass=pd*pt
                detected[j]+=mass*(1-(1-a)*(1-b))
                for i,t in enumerate(tracks):
                    if t['release_ms'] is not None and t['release_ms']!=r: continue
                    if t['crossing_ms'] is not None and t['crossing_ms']!=c: continue
                    q[i,j]+=mass*(a if t['release_ms'] is not None else 1-a)*(b if t['crossing_ms'] is not None else 1-b)
    if len(tracks) and np.any(q.sum(axis=1)==0):
        raise ModelUnavailable('TRACK_PATTERN_UNSUPPORTED_BY_DELAY_DETECTION_MODEL')
    return {'tracks':tracks,'q':q,'detected_probability':detected,
            'rates':rates,'exposure':exposure,'movements':movements,'n':n,
            'observation_domain':domain}


def path_loglik(labels, components):
    """One likelihood term per observed track; independent unit is latent vehicle."""
    labels=np.asarray(labels,dtype=int)
    r=components['rates']; ex=components['exposure']; pd=components['detected_probability']
    if labels.shape!=(components['n'],) or (labels<0).any() or (labels>=len(r)).any():
        raise ValueError('invalid fixed path')
    value=0.
    for m,name in enumerate(components['movements']):
        intensity=r[labels,m]*ex[m]*GRID_S
        value-=float(intensity@pd)
        for i,t in enumerate(components['tracks']):
            if t['movement']!=name: continue
            mu=float(intensity@components['q'][i])
            if mu<=0: return -math.inf
            value+=math.log(mu)
    return value


def enumerate_paths(horizon_s, *, max_paths=10000):
    """Exactly four observed segments; last right-censored, not a terminal switch."""
    rows=[]
    for a in range(4,min(48,horizon_s-10)+1,2):
        for b in range(a+4,min(a+48,horizon_s-6)+1,2):
            for c in range(b+4,min(b+48,horizon_s-2)+1,2):
                if horizon_s-c>48: continue
                if len(rows)>=max_paths: raise ModelUnavailable('PATH_BUDGET_EXHAUSTED_NO_POSTERIOR')
                rows.append((a,b,c))
    if not rows: raise ModelUnavailable('NO_PATH_IN_SUPPLIED_DURATION_SUPPORT')
    return np.asarray(rows,dtype=np.int16)


def _logprior(bounds, horizon, prior):
    ds=np.arange(4,49,2)
    if prior['family']=='uniform': mass=np.ones(len(ds))
    else: mass=np.exp(-np.abs(ds-prior['center_s'])/prior['scale_s'])
    mass/=mass.sum()
    complete=np.diff(np.c_[np.zeros(len(bounds),dtype=int),bounds],axis=1)
    value=np.log(mass[(complete-4)//2]).sum(axis=1)
    last=horizon-bounds[:,-1]
    survival=np.array([mass[ds>=d].sum() for d in last])
    return value+np.log(survival)


def _weights(scores):
    finite=np.isfinite(scores)
    if not finite.any(): raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
    result=np.zeros(len(scores)); result[finite]=np.exp(scores[finite]-scores[finite].max())
    result/=result.sum()
    return result


def infer_joint(view, spec, *, priors=None, max_seconds=5.0, max_paths=10000,
                max_horizon_s=80, max_tracks=512, max_q_cells=50000,
                max_memory_bytes=32*1024*1024):
    """Exact posterior on declared finite support, or explicit unavailable."""
    started=time.process_time()
    limits={'max_seconds':max_seconds,'max_paths':max_paths,'max_horizon_s':max_horizon_s,
            'max_tracks':max_tracks,'max_q_cells':max_q_cells,'max_memory_bytes':max_memory_bytes}
    priors=PRIORS if priors is None else priors
    unknown=StateEstimate('UNKNOWN','logical_phase','experimental_joint_track_model',
        abstention_reason='MODEL_CONDITIONED_DIAGNOSTIC_ONLY').to_dict()
    base={'schema':'experimental-joint-track-posterior-v1','complete':False,
        'logical_phase':unknown,'physical_section':physical_estimate('UNKNOWN',source='experimental_joint_track_model').to_dict(),
        'interval_type':'model_conditioned_finite_grid_posterior','grid_s':GRID_S,
        'timestamp_resolution_ms':1,'calibrated_lamp_probability':None,
        'assumptions':['supplied rates/demand/exposure/delay/detection', 'nonexclusive movement intensities',
            'known K/order/start and exactly four observed segments', 'right-censored last segment',
            'discrete synthetic clock, not a continuous-time guarantee']}
    def unavailable(reason):
        return {**base,'status':'unavailable','reason':reason,'results':{},'cpu_s':time.process_time()-started}
    try:
        if not _finite(max_seconds) or max_seconds<0 or any(isinstance(v,bool) or not isinstance(v,int) or v<0
                for key,v in limits.items() if key!='max_seconds'):
            raise ModelUnavailable('INVALID_RESOURCE_LIMITS')
        if spec.get('observed_segment_count')!=4: raise ModelUnavailable('TRANSITION_COUNT_NOT_SUPPLIED_AS_FOUR_SEGMENTS')
        if spec.get('initial_phase')!=0 or spec.get('initial_phase_start_s')!=0:
            raise ModelUnavailable('KNOWN_INITIAL_ANCHOR_REQUIRED')
        h=spec.get('horizon_s')
        if not isinstance(h,int) or h>limits['max_horizon_s'] or limits['max_seconds']<=0:
            raise ModelUnavailable('RESOURCE_LIMIT')
        if priors!=PRIORS: raise ModelUnavailable('ONLY_PREREGISTERED_PRIORS_ALLOWED')
        comp=observation_components(view,spec,max_tracks=limits['max_tracks'],max_q_cells=limits['max_q_cells'])
        k=len(comp['rates']); bounds=enumerate_paths(h,max_paths=limits['max_paths'])
        memory=len(bounds)*comp['n']*4+len(bounds)*96+512*comp['n']*16+256*512*24
        if memory>limits['max_memory_bytes']: raise ModelUnavailable('DECLARED_MEMORY_ALLOWANCE_EXCEEDED')
        clock=np.arange(comp['n'])*GRID_S
        labels=((clock[None,:]>=bounds[:,0,None]).astype(np.int16)
                +(clock[None,:]>=bounds[:,1,None])+(clock[None,:]>=bounds[:,2,None]))%k
        scores=np.zeros(len(bounds))
        for first in range(0,len(bounds),256):
            if time.process_time()-started>limits['max_seconds']: raise ModelUnavailable('CPU_BUDGET_EXHAUSTED_NO_POSTERIOR')
            z=labels[first:first+256]; ll=np.zeros(len(z))
            for m,name in enumerate(comp['movements']):
                intensity=comp['rates'][z,m]*comp['exposure'][m]*GRID_S
                ll-=intensity@comp['detected_probability']
                indices=[i for i,t in enumerate(comp['tracks']) if t['movement']==name]
                if indices:
                    mu=intensity@comp['q'][indices].T
                    with np.errstate(divide='ignore'): ll+=np.log(mu).sum(axis=1)
            scores[first:first+len(z)]=ll
        results={}
        finite=scores[np.isfinite(scores)]
        if not len(finite): raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
        for name,prior in priors.items():
            prior_log=_logprior(bounds,h,prior)
            prior_w=_weights(prior_log); posterior=_weights(scores+prior_log)
            best=int(np.argmax(scores+prior_log)); cuts=[0,*bounds[best].tolist(),h]
            segments=[[a,b,i%k] for i,(a,b) in enumerate(zip(cuts,cuts[1:]))]
            intervals=[]
            for ordinal in range(3):
                times=np.unique(bounds[:,ordinal]); masses=np.array([posterior[bounds[:,ordinal]==t].sum() for t in times])
                cumulative=np.cumsum(masses)
                lo=int(times[min(int(np.searchsorted(cumulative,.05)),len(times)-1)])
                hi=int(times[min(int(np.searchsorted(cumulative,.95)),len(times)-1)])
                intervals.append({'ordinal':ordinal+1,'equal_tailed_90_s':[lo,hi],
                    'times_s':times.tolist(),'posterior_mass':masses.tolist()})
            phase_posterior=[]
            for t in range(comp['n']):
                phase_posterior.append([float(posterior[labels[:,t]==z].sum()) for z in range(k)])
            mask=posterior>0
            kl=float(np.sum(posterior[mask]*np.log(posterior[mask]/prior_w[mask])))
            results[name]={'diagnostic_segments':segments,'boundary_posteriors':intervals,
                'phase_posterior':phase_posterior,'prior':prior,'posterior_vs_prior_kl_nats':kl,
                'map_log_likelihood':float(scores[best]),'finite_path_count':int(np.isfinite(scores).sum()),
                'posterior_semantics':'conditional on supplied synthetic model; not lamp probability or verified nominal coverage'}
        if time.process_time()-started>limits['max_seconds']: raise ModelUnavailable('CPU_BUDGET_EXHAUSTED_NO_POSTERIOR')
        return {**base,'status':'complete_finite_posterior','complete':True,'results':results,
            'path_count':len(bounds),'observed_track_count':len(comp['tracks']),
            'observed_vehicle_mark_count':sum(t['release_ms'] is not None for t in comp['tracks'])+sum(t['crossing_ms'] is not None for t in comp['tracks']),
            'likelihood_range':[float(finite.min()),float(finite.max())],
            'data_support':'joint track patterns + supplied thinning exposure',
            'prior_only_numerically':bool(float(finite.max()-finite.min())<=1e-10),
            'prior_only_tolerance_semantics':'numerical diagnostic, not identifiability or observability threshold',
            'published_logical_unknown_fraction':1.0,'declared_memory_allowance_used_bytes':memory,
            'cpu_s':time.process_time()-started}
    except (ModelUnavailable,ValueError,TypeError,KeyError,IndexError) as exc:
        return unavailable(str(exc))
