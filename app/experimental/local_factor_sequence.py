"""Exact bounded semi-Markov messages for strictly cell-local vehicle factors.

Nonlocal joint-track factors are rejected. No q threshold, beam or approximation.
Unknown initial phase/residual/count; unchanged priors and right censoring.
"""
import math
import time
import copy

import numpy as np

from app.core.state_contract import StateEstimate,physical_estimate
from app.experimental.joint_track_model import GRID_S,PRIORS,ModelUnavailable
from app.experimental.unanchored_sequence import duration_masses
from app.experimental.context_observation import prepare_context_observation


def _lse(x):
    x=np.asarray(x);m=float(np.max(x))
    return m+math.log(float(np.exp(x-m).sum())) if math.isfinite(m) else -math.inf


def local_emissions(comp):
    """Exact factorization; compensator plus one term per complete vehicle factor."""
    n=comp['n'];k=len(comp['rates'])
    e=np.zeros((n,k))
    for z in range(k):
        e[:,z]=-np.sum(comp['rates'][z,:,None]*comp['exposure']*GRID_S,axis=0)*comp['detected_probability']
    for i,t in enumerate(comp['tracks']):
        support=np.flatnonzero(comp['q'][i]>0)
        if len(support)!=1:
            raise ModelUnavailable('NONLOCAL_TRACK_KERNEL_REQUIRES_EXPANDED_STATE')
        j=int(support[0]);m=comp['movements'].index(t['movement'])
        mu=comp['rates'][:,m]*comp['exposure'][m,j]*GRID_S*comp['q'][i,j]
        with np.errstate(divide='ignore'):e[j]+=np.log(mu)
    return e


def _map_segments(e,order,mass,residual,check):
    """MAP over observed segment paths, summing over censored duration tails."""
    n,k=e.shape;R=len(mass)-1
    prefix=np.vstack([np.zeros(k),np.cumsum(np.where(np.isfinite(e),e,0.),axis=0)])
    blocked=np.vstack([np.zeros(k),np.cumsum(~np.isfinite(e),axis=0)])
    def emission(a,b,z):return -math.inf if blocked[b,z]>blocked[a,z] else prefix[b,z]-prefix[a,z]
    best=np.full((n,k),-math.inf);paths={}
    for b in range(1,n):
        check()
        for z in order:
            score=math.log(residual[b]/k)+emission(0,b,z) if b<=R and residual[b]>0 else -math.inf
            candidate=[(0,b,z)]
            prev=order[(order.index(z)-1)%k]
            for d in range(1,min(R,b-1)+1):
                if mass[d]<=0:continue
                a=b-d;v=best[a,prev]+math.log(mass[d])+emission(a,b,z)
                if v>score:score=v;candidate=paths.get((a,prev),[])+[(a,b,z)]
            best[b,z]=score;paths[b,z]=candidate
    value=-math.inf;segments=[]
    for z in order:
        p=float(residual[n:].sum()) if n<=R else 0.
        v=math.log(p/k)+emission(0,n,z) if p>0 else -math.inf
        if v>value:value=v;segments=[(0,n,z)]
        prev=order[(order.index(z)-1)%k]
        for a in range(1,n):
            remaining=n-a;p=float(mass[remaining:].sum()) if remaining<=R else 0.
            if p<=0:continue
            v=best[a,prev]+math.log(p)+emission(a,n,z)
            if v>value:value=v;segments=paths.get((a,prev),[])+[(a,n,z)]
    return [[a*GRID_S,b*GRID_S,z] for a,b,z in segments],float(value)


def infer_local_factors(comp,order,*,max_seconds=5.,max_memory_bytes=32*1024*1024):
    started=time.process_time();wall=time.perf_counter()
    base=dict(schema='experimental-local-factor-renewal-v1',status='unavailable',complete=False,results={},
        logical_phase=StateEstimate('UNKNOWN','logical_phase','local_factor_sequence',
            abstention_reason='MODEL_CONDITIONED_DIAGNOSTIC_NOT_VALIDATED_HISTORY').to_dict(),
        physical_section=physical_estimate('UNKNOWN',source='local_factor_sequence').to_dict(),
        calibrated_lamp_probability=None,published_logical_unknown_fraction=1.,
        published_physical_unknown_fraction=1.,production_default_changed=False,
        assumptions=['all vehicle kernels exactly cell-local','supplied rates/exposure/detection/delay/rounding',
            'stationary grid-renewal start and same prior per phase','fixed K/order;2s phase grid'],
        enumeration_used=False,truncation_used=False)
    def failed(reason):return {**base,'reason':reason,'cpu_s':time.process_time()-started,'wall_s':time.perf_counter()-wall}
    def check():
        if time.perf_counter()-wall>max_seconds or time.process_time()-started>max_seconds:
            raise ModelUnavailable('TIME_BUDGET_EXHAUSTED_NO_POSTERIOR')
    try:
        if (isinstance(max_seconds,bool) or not isinstance(max_seconds,(int,float)) or not math.isfinite(max_seconds) or max_seconds<=0
                or isinstance(max_memory_bytes,bool) or not isinstance(max_memory_bytes,int) or max_memory_bytes<0):
            raise ModelUnavailable('INVALID_OR_EXHAUSTED_RESOURCE_LIMIT')
        n=comp['n'];k=len(comp['rates']);R=24
        if not isinstance(n,int) or not 1<=n<=40 or k not in (2,3):raise ModelUnavailable('BOUNDED_K2_K3_CONTEXT_REQUIRED')
        if not isinstance(order,list) or any(isinstance(z,bool) or not isinstance(z,int) for z in order) or sorted(order)!=list(range(k)):
            raise ModelUnavailable('SUPPLIED_CYCLIC_ORDER_REQUIRED')
        # Forward-count cube plus backward/marginal work arrays and retained messages.
        allowance=(n*k*(R+1)*(n+1)*8)*3+65536
        if allowance>max_memory_bytes:raise ModelUnavailable('MEMORY_BUDGET_EXHAUSTED_NO_POSTERIOR')
        check();e=local_emissions(comp);results={}
        for name,prior in PRIORS.items():
            ds,pm=duration_masses(prior);mass=np.zeros(R+1);mass[(ds//GRID_S).astype(int)]=pm
            residual=np.array([0.]+[float(mass[r:].sum()) for r in range(1,R+1)])
            residual/=float(np.arange(R+1)@mass)
            alpha=np.full((n,k,R+1,n+1),-math.inf)
            for z in order:alpha[0,z,1:,0]=np.log(residual[1:]/k)
            for j in range(n-1):
                check()
                for z in order:
                    # Remaining>1 keeps count; remaining1 completes an interior phase.
                    alpha[j+1,z,1:R,:]=np.logaddexp(alpha[j+1,z,1:R,:],alpha[j,z,2:R+1,:]+e[j,z])
                    nxt=order[(order.index(z)+1)%k]
                    for d in np.flatnonzero(mass):
                        alpha[j+1,nxt,d,1:]=np.logaddexp(alpha[j+1,nxt,d,1:],
                            alpha[j,z,1,:-1]+e[j,z]+math.log(mass[d]))
            last=alpha[-1]+e[-1,:,None,None];logZ=_lse(last)
            if not math.isfinite(logZ):raise ModelUnavailable('ALL_PATHS_HAVE_ZERO_OBSERVATION_PROBABILITY')
            count=np.array([math.exp(_lse(last[:,:,c])-logZ) for c in range(n+1)])
            beta=np.full((n,k,R+1),-math.inf);beta[-1,:,1:]=e[-1,:,None]
            for j in range(n-2,-1,-1):
                check()
                for z in order:
                    beta[j,z,2:]=e[j,z]+beta[j+1,z,1:R]
                    nxt=order[(order.index(z)+1)%k]
                    beta[j,z,1]=e[j,z]+_lse([math.log(mass[d])+beta[j+1,nxt,d] for d in np.flatnonzero(mass)])
            summed=np.logaddexp.reduce(alpha,axis=3)
            phase=[[math.exp(_lse(summed[j,z,1:]+beta[j,z,1:])-logZ) for z in range(k)] for j in range(n)]
            boundaries=[]
            for j in range(n-1):
                terms=[]
                for z in order:
                    nxt=order[(order.index(z)+1)%k]
                    for d in np.flatnonzero(mass):
                        terms.append(summed[j,z,1]+e[j,z]+math.log(mass[d])+beta[j+1,nxt,d])
                boundaries.append(dict(time_s=(j+1)*GRID_S,model_conditioned_existence_probability=math.exp(_lse(terms)-logZ)))
            seg,score=_map_segments(e,order,mass,residual,check)
            results[name]=dict(prior=copy.deepcopy(prior),log_normalizer=logZ,
                transition_count_posterior={str(c):float(p) for c,p in enumerate(count) if p>0},
                phase_posterior=phase,boundary_existence=boundaries,diagnostic_segments=seg,
                diagnostic_map_log_joint=score,
                posterior_semantics='exact within supplied finite grid model; not calibrated lamp probability')
        check()
        return {**base,'status':'complete_local_factor_posterior','complete':True,'results':results,
            'likelihood_constant_over_phase_paths':bool(np.all(e==e[:,[0]])),
            'path_dependence_semantics':'equality sufficient for prior-only; inequality NOT identifiability',
            'declared_array_allowance_bytes':allowance,'context_extent_s':[0,n*GRID_S],
            'cpu_s':time.process_time()-started,'wall_s':time.perf_counter()-wall}
    except (ModelUnavailable,ValueError,TypeError,KeyError,IndexError) as exc:return failed(str(exc))


def infer_local_context(index,spec,*,context_origin_ms,target_range_ms,**limits):
    """Explicit opt-in context entry point; retains UNKNOWN publication semantics."""
    prepared=prepare_context_observation(index,spec,context_origin_ms=context_origin_ms,target_range_ms=target_range_ms)
    if prepared['status']!='ready_for_supplied_context_model_only':return prepared
    result=infer_local_factors(prepared['components'],spec.get('cyclic_order'),**limits)
    return {**result,'context_plan':prepared['context_plan'],'input_sha256':prepared['input_sha256'],
        'supplied_model_sha256':prepared['supplied_model_sha256']}
