"""Bounded fixed-K/order renewal posterior with unknown initial phase/count.

No production imports this module. Complete finite model or explicit unavailable;
no posterior is returned from a prefix of the alternative paths.
"""
import math
import time
import copy

import numpy as np

from app.core.state_contract import StateEstimate, physical_estimate
from app.experimental.joint_track_model import GRID_S, PRIORS, ModelUnavailable, path_loglik
from app.experimental.phase_observation_bridge import prepare_joint_observation

VERSION='experimental-unanchored-renewal-v1'


def duration_masses(prior):
    ds=np.arange(prior['min_s'],prior['max_s']+1,prior['step_s'])
    mass=np.ones(len(ds)) if prior['family']=='uniform' else np.exp(
        -np.abs(ds-prior['center_s'])/prior['scale_s'])
    return ds,mass/mass.sum()


def renewal_log_prior(bounds,h,prior):
    """Initial grid-equilibrium residual, complete durations, right censoring."""
    ds,mass=duration_masses(prior)
    residual_times=np.arange(GRID_S,int(ds[-1])+1,GRID_S)
    residual=np.array([mass[ds>=r].sum() for r in residual_times])/(float(ds@mass)/GRID_S)
    if not bounds:
        p=residual[residual_times>=h].sum()
        return math.log(p) if p>0 else -math.inf
    p=residual[residual_times==bounds[0]].sum()
    if p<=0:return -math.inf
    result=math.log(p)
    for a,b in zip(bounds,bounds[1:]):
        p=mass[ds==b-a].sum()
        if p<=0:return -math.inf
        result+=math.log(p)
    p=mass[ds>=h-bounds[-1]].sum()
    return result+math.log(p) if p>0 else -math.inf


def enumerate_sequences(h,order,*,max_paths=10000,max_memory_bytes=32*1024*1024,
                        deadline=math.inf):
    """All paths including hidden cycles; bounds strictly interior to horizon."""
    paths=[]
    allowance_per_path=2048+(h//GRID_S)*16
    def add(bounds):
        for first in order:
            if time.perf_counter()>deadline:
                raise ModelUnavailable('TIME_BUDGET_EXHAUSTED_NO_POSTERIOR')
            if len(paths)>=max_paths:raise ModelUnavailable('PATH_BUDGET_EXHAUSTED_NO_POSTERIOR')
            if (len(paths)+1)*allowance_per_path>max_memory_bytes:
                raise ModelUnavailable('MEMORY_BUDGET_EXHAUSTED_NO_POSTERIOR')
            paths.append((first,tuple(bounds)))
    def visit(bounds):
        last=bounds[-1]
        if h-last<=48:add(bounds)
        for duration in range(4,49,GRID_S):
            if last+duration>=h:break
            visit((*bounds,last+duration))
    if h<=48:add(())
    for first in range(GRID_S,min(48,h-GRID_S)+1,GRID_S):visit((first,))
    return paths


def _weights(logs):
    finite=np.isfinite(logs)
    if not finite.any():raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
    x=np.zeros(len(logs)); x[finite]=np.exp(logs[finite]-logs[finite].max())
    return x/x.sum()


def infer_unanchored(view,spec,*,origin_ms,max_paths=10000,max_seconds=5.,
                     max_memory_bytes=32*1024*1024):
    """Both fixed priors; supplied clock/rates/exposure/order, no truth input."""
    started=time.process_time()
    wall_started=time.perf_counter()
    base=dict(schema=VERSION,status='unavailable',complete=False,results={},
        calibrated_lamp_probability=None,production_default_changed=False,
        logical_phase=StateEstimate('UNKNOWN','logical_phase',VERSION,
            abstention_reason='EXPERIMENTAL_MODEL_CONDITIONED_DIAGNOSTIC_ONLY').to_dict(),
        physical_section=physical_estimate('UNKNOWN',source=VERSION).to_dict(),
        assumptions=['fixed supplied K/mapping/cyclic order',
            'grid-stationary renewal start; initial age marginalized',
            'same duration prior across phases; uniform initial phase',
            'supplied rates/demand/exposure/delays/rounding',
            'no latent vehicles outside supplied horizon',
            'finite 2s phase grid, not lamp probabilities'],
        initial_age_status='MARGINALIZED_NOT_OBSERVED',
        published_logical_unknown_fraction=1.,published_physical_unknown_fraction=1.)
    def failed(reason):return {**base,'reason':reason,'cpu_s':time.process_time()-started,
        'wall_s':time.perf_counter()-wall_started}
    try:
        if (isinstance(max_seconds,bool) or not isinstance(max_seconds,(int,float))
                or not math.isfinite(max_seconds) or max_seconds<=0
                or any(isinstance(x,bool) or not isinstance(x,int) or x<0
                    for x in (max_paths,max_memory_bytes))):
            raise ModelUnavailable('INVALID_OR_EXHAUSTED_RESOURCE_LIMIT')
        deadline=wall_started+max_seconds
        if spec.get('clock_model')!='continuous_latent_rounded_marks':
            raise ModelUnavailable('EXPLICIT_ROUNDED_CLOCK_MODEL_REQUIRED')
        if any(spec.get(k) is not None for k in ('initial_phase','initial_phase_start_s','observed_segment_count')):
            raise ModelUnavailable('FIXED_INITIAL_ANCHOR_OR_COUNT_NOT_ACCEPTED')
        order=spec.get('cyclic_order')
        rates=spec.get('rates_per_s')
        k=len(rates) if isinstance(rates,list) else 0
        if k not in (2,3) or not isinstance(order,list) or len(order)!=k or any(
                isinstance(x,bool) or not isinstance(x,int) for x in order) or sorted(order)!=list(range(k)):
            raise ModelUnavailable('SUPPLIED_K2_K3_CYCLIC_ORDER_REQUIRED')
        prepared=prepare_joint_observation(view,spec,origin_ms=origin_ms)
        if prepared['status']!='ready_for_declared_model_only':
            return {**failed(prepared['reason']),'observation_readiness':{
                k:v for k,v in prepared.items() if k!='components'}}
        comp=prepared['components'];h=spec['horizon_s']
        # Account for bounded observation arrays before retaining alternatives.
        component_bytes=sum(v.nbytes for v in comp.values() if isinstance(v,np.ndarray))
        paths=enumerate_sequences(h,order,max_paths=max_paths,
            max_memory_bytes=max_memory_bytes-component_bytes,deadline=deadline)
        clock=np.arange(comp['n'])*GRID_S
        scores=[]
        for first,bounds in paths:
            if time.perf_counter()>deadline or time.process_time()-started>max_seconds:
                raise ModelUnavailable('TIME_BUDGET_EXHAUSTED_NO_POSTERIOR')
            z=np.asarray(order)[(order.index(first)+np.searchsorted(bounds,clock,side='right'))%k]
            scores.append(path_loglik(z,comp))
        scores=np.asarray(scores);finite=scores[np.isfinite(scores)]
        if not len(finite):raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
        rows=[dict(initial_phase=first,boundaries_s=list(bounds),transition_count=len(bounds),
            log_likelihood=float(ll) if math.isfinite(ll) else None,
            log_likelihood_status='finite' if math.isfinite(ll) else 'structural_zero',
            posterior={}) for (first,bounds),ll in zip(paths,scores)]
        results={}
        for name,prior in PRIORS.items():
            logs=np.array([renewal_log_prior(b,h,prior)-math.log(k) for _,b in paths])
            pw=_weights(logs); post=_weights(logs+scores)
            count_mass={};phase_mass={str(z):0. for z in order};by_count={}
            for row,p in zip(rows,post):
                row['posterior'][name]=float(p)
                count=str(row['transition_count']);count_mass[count]=count_mass.get(count,0.)+float(p)
                phase_mass[str(row['initial_phase'])]+=float(p)
                for ordinal,t in enumerate(row['boundaries_s']):
                    masses=by_count.setdefault(count,{}).setdefault(str(ordinal+1),{})
                    masses[str(t)]=masses.get(str(t),0.)+float(p)
            zero_mass_conditionals={}
            for count,ordinals in list(by_count.items()):
                if count_mass[count]>0:
                    for masses in ordinals.values():
                        for t in masses:masses[t]/=count_mass[count]
                else:
                    del by_count[count]
                    zero_mass_conditionals[count]='NUMERIC_ZERO_POSTERIOR_MASS'
            best=int(np.argmax(logs+scores));cuts=[0,*paths[best][1],h]
            positive=post>0
            results[name]=dict(prior=copy.deepcopy(prior),transition_count_posterior=count_mass,
                initial_phase_posterior=phase_mass,
                boundary_posteriors_conditioned_on_count=by_count,
                unavailable_boundary_posteriors_by_count=zero_mass_conditionals,
                boundary_semantics='ordinal times conditional on count; do not pool across counts',
                diagnostic_segments=[[a,b,int(z)] for a,b,z in zip(cuts,cuts[1:],
                    np.asarray(order)[(order.index(paths[best][0])+np.arange(len(cuts)-1))%k])],
                diagnostic_path_index=best,
                posterior_vs_prior_kl_nats=float(np.sum(post[positive]*np.log(post[positive]/pw[positive]))))
        if time.perf_counter()>deadline or time.process_time()-started>max_seconds:
            raise ModelUnavailable('TIME_BUDGET_EXHAUSTED_NO_POSTERIOR')
        return {**base,'status':'complete_finite_posterior','complete':True,
            'path_count':len(paths),'alternatives':rows,'results':results,
            'input_sha256':prepared['input_sha256'],'supplied_model_sha256':prepared['supplied_model_sha256'],
            'prior_only_numerically':bool(np.isfinite(scores).all() and finite.max()-finite.min()<=1e-10),
            'prior_only_semantics':'numeric diagnostic, not identifiability threshold',
            'likelihood_range':[float(finite.min()),float(finite.max())],
            'observation_support':{'vehicle_groups':len(comp['tracks']),
                'source':'joint vehicle patterns and supplied thinning exposure',
                'history_temporal_extent_s':[0,h],'lamp_observability':'UNKNOWN'},
            'cpu_s':time.process_time()-started,'wall_s':time.perf_counter()-wall_started}
    except (ModelUnavailable,ValueError,TypeError,KeyError,IndexError,OverflowError) as exc:
        return failed(str(exc))
